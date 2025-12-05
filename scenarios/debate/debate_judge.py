import argparse
import contextlib
import uvicorn
import asyncio
import logging
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Literal

load_dotenv()

from google import genai
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    TaskState,
    Part,
    TextPart,
)
from a2a.utils import (
    new_agent_text_message
)

from agentbeats.green_executor import GreenAgent, GreenExecutor
from agentbeats.models import EvalRequest, EvalResult
from agentbeats.tool_provider import ToolProvider

from debate_judge_common import DebateEval, debate_judge_agent_card


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debate_judge")


class DebateJudge(GreenAgent):
    def __init__(self):
        self._required_roles = ["pro_debater", "con_debater"]
        self._required_config_keys = ["topic", "num_rounds"]
        self._client = genai.Client()
        self._tool_provider = ToolProvider()

    def validate_request(self, request: EvalRequest) -> tuple[bool, str]:
        missing_roles = set(self._required_roles) - set(request.participants.keys())
        if missing_roles:
            return False, f"Missing roles: {missing_roles}"
        missing_config_keys = set(self._required_config_keys) - set(request.config.keys())
        if missing_config_keys:
            return False, f"Missing config keys: {missing_config_keys}"
        try:
            int(request.config["num_rounds"])
        except Exception as e:
            return False, f"Can't parse num_rounds: {e}"
        return True, "ok"

    async def run_eval(self, req: EvalRequest, updater: TaskUpdater) -> None:
        logger.info(f"Starting debate orchestration: {req}")

        try:
            debate = await self.orchestrate_debate(req.participants,
                                                req.config["topic"],
                                                req.config["num_rounds"],
                                                updater)

            debate_text = ""
            for i, (pro, con) in enumerate(zip(debate["pro_debater"], debate["con_debater"]), start=1):
                debate_text += f"Pro Argument {i}: {pro}\n"
                debate_text += f"Con Argument {i}: {con}\n"

            await updater.update_status(TaskState.working, new_agent_text_message(f"Debate orchestration finished. Starting evaluation."))
            logger.info("Debate orchestration finished. Evaluating debate.")
            debate_eval: DebateEval = await self.judge_debate(req.config["topic"], debate_text)
            logger.info(f"Debate Evaluation:\n{debate_eval.model_dump_json()}")

            result = EvalResult(winner=debate_eval.winner, detail=debate_eval.model_dump())
            await updater.add_artifact(
                parts=[
                    Part(root=TextPart(text=debate_eval.reason)),
                    Part(root=TextPart(text=result.model_dump_json())),
                ],
                name="Result",
            )
        finally:
            self._tool_provider.reset()

    async def orchestrate_debate(
        self,
        participants: dict[str, str],
        topic: str,
        num_rounds: int,
        updater: TaskUpdater,
    ) -> dict[str, list[str]]:
        debate: dict[str, list[str]] = {"pro_debater": [], "con_debater": []}

        async def turn(role: str, prompt: str) -> str:
            response = await self._tool_provider.talk_to_agent(prompt, str(participants[role]), new_conversation=False)
            logger.info(f"{role}: {response}")
            debate[role].append(response)
            await updater.update_status(TaskState.working, new_agent_text_message(f"{role}: {response}"))
            return response

        # Opening turns
        response = await turn("pro_debater", f"Debate Topic: {topic}. Present your opening argument.")
        response = await turn("con_debater", f"Debate Topic: {topic}. Present your opening argument. Your opponent opened with: {response}")

        # Remaining rounds
        for _ in range(num_rounds - 1):
            response = await turn("pro_debater", f"Your opponent said: {response}. Present your next argument.")
            response = await turn("con_debater", f"Your opponent said: {response}. Present your next argument.")

        return debate

    async def judge_debate(self, topic: str, debate_text: str) -> DebateEval:
        # prompt adapted from InspireScore: https://github.com/fywang12/InspireDebate/blob/main/inspirescore.py

        system_prompt = """
        You are an experienced debate judge tasked with evaluating debates. For each debate, you will assess both sides based on four key criteria: Emotional Appeal, Clarity of Argument and Reasoning, Logical Arrangement of Arguments, and Relevance to Debate Topic.

        For each of the four subdimensions, provide a score from 0 to 1 (with 0 being the lowest and 1 being the highest) for both the **Pro (Affirmative)** side and the **Con (Negative)** side. Additionally, provide a brief analysis for both sides for each subdimension.

        Scoring Criteria:
            1. **Emotional Appeal**
                - How effectively does each side connect with the audience emotionally? Does the argument evoke empathy, passion, or values?
                - **0**: No emotional appeal. The argument feels cold or disconnected.
                - **1**: Highly engaging emotionally, strongly connects with the audience.

            2. **Clarity of Argument and Reasoning**
                - Are the arguments clearly presented? Is the reasoning sound and easy to follow?
                - **0**: The arguments are unclear or confusing.
                - **1**: The arguments are well-structured and easy to understand.

            3. **Logical Arrangement of Arguments**
                - Is the argument presented in a logical, coherent manner? Does each point flow into the next without confusion?
                - **0**: The arguments are disorganized and difficult to follow.
                - **1**: The arguments follow a clear and logical progression.

            4. **Relevance to Debate Topic**
                - Does each argument directly address the debate topic? Are there any irrelevant points or off-topic distractions?
                - **0**: Arguments that stray far from the topic.
                - **1**: Every argument is focused and relevant to the topic.

        Please output the result in the following format:

        1. **Pro (Affirmative Side) Score**:
            - Emotional Appeal: [score]
            - Argument Clarity: [score]
            - Argument Arrangement: [score]
            - Relevance to Debate Topic: [score]
            - **Total Score**: [total score]

        2. **Con (Negative Side) Score**:
            - Emotional Appeal: [score]
            - Argument Clarity: [score]
            - Argument Arrangement: [score]
            - Relevance to Debate Topic: [score]
            - **Total Score**: [total score]

        3. **Winner**: [Pro/Con]
        4. **Reason**: [Provide detailed analysis based on the scores]
        """

        user_prompt = f"""
        Evaluate the debate on the topic: '{topic}'
        Debate analysis process and arguments are as follows:
        {debate_text}
        Provide a JSON formatted response with scores and comments for each criterion for both debaters.
        """

        response = self._client.models.generate_content(
            model="gemini-2.5-flash",
            config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=DebateEval,
                ),
            contents=user_prompt,
        )
        return response.parsed


async def main():
    parser = argparse.ArgumentParser(description="Run the A2A debate judge.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=9019, help="Port to bind the server")
    parser.add_argument("--card-url", type=str, help="External URL to provide in the agent card")
    parser.add_argument("--cloudflare-quick-tunnel", action="store_true", help="Use a Cloudflare quick tunnel. Requires cloudflared. This will override --card-url")
    args = parser.parse_args()

    if args.cloudflare_quick_tunnel:
        from agentbeats.cloudflare import quick_tunnel
        agent_url_cm = quick_tunnel(f"http://{args.host}:{args.port}")
    else:
        agent_url_cm = contextlib.nullcontext(args.card_url or f"http://{args.host}:{args.port}/")

    async with agent_url_cm as agent_url:
        agent = DebateJudge()
        executor = GreenExecutor(agent)
        agent_card = debate_judge_agent_card("DebateJudge", agent_url)

        request_handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=InMemoryTaskStore(),
        )

        server = A2AStarletteApplication(
            agent_card=agent_card,
            http_handler=request_handler,
        )

        uvicorn_config = uvicorn.Config(server.build(), host=args.host, port=args.port)
        uvicorn_server = uvicorn.Server(uvicorn_config)
        await uvicorn_server.serve()

if __name__ == '__main__':
    asyncio.run(main())
