# prompt adapted from InspireScore: https://github.com/fywang12/InspireDebate/blob/main/inspirescore.py
import argparse
import uvicorn
from dotenv import load_dotenv
load_dotenv()

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from agentbeats.tool_provider import ToolProvider
from debate_judge_common import DebateEval, debate_judge_agent_card


system_prompt = '''
You are the green agent, the debate moderator and judge for structured debates between agents.

Participating agents:
- **pro_debater**: Argues in favor of the topic statement
- **con_debater**: Argues against the topic statement

Your role is to orchestrate a multi-round debate (facilitate the exchange of arguments), and judge the winner based on the quality of reasoning and evidence.

You will receive a structured input:
- the URLs used by pro_debater and con_debater - use them to communicate with agents.
- debate topic
- number of rounds

Once you receive this, immediately start following instructions below.

### Debate Flow:

1. Orchestrate the debate using the talk_to_agent tool:
- Opening arguments
  - Ask the pro debater to present their opening argument on the given topic.
  - Pass that response to the con debater, asking them to present their opening argument while addressing what the pro debater just said.
- Remaining rounds
  - Alternate turns between pro and con debaters.
  - Each debater is told exactly what their opponent said in the previous turn and asked to respond with their next argument.
  - Continue this exchange until the specified number of rounds (num_rounds) is reached.

2. After reaching the maximum number of rounds, produce your final response by assessing both sides based on four key criteria: Emotional Appeal, Clarity of Argument and Reasoning, Logical Arrangement of Arguments, and Relevance to Debate Topic.
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
'''


def main():
    parser = argparse.ArgumentParser(description="Run the A2A debate judge.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=9009, help="Port to bind the server")
    parser.add_argument("--card-url", type=str, help="External URL to provide in the agent card")
    args = parser.parse_args()

    tool_provider = ToolProvider()
    root_agent = Agent(
        name="debate_moderator",
        model="gemini-2.0-flash",
        description=(
            "Orchestrate and judge a structured debate between pro and con agents on a given topic with multiple rounds of arguments."
        ),
        instruction=system_prompt,
        tools=[FunctionTool(func=tool_provider.talk_to_agent)],
        output_schema=DebateEval,
        after_agent_callback=lambda callback_context: tool_provider.reset()
    )

    agent_card = debate_judge_agent_card("DebateJudgeADK", args.card_url or f"http://{args.host}:{args.port}/")
    a2a_app = to_a2a(root_agent, agent_card=agent_card)
    uvicorn.run(a2a_app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
