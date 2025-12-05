from pydantic import BaseModel
from typing import Literal

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)


class DebaterScore(BaseModel):
    emotional_appeal: float
    argument_clarity: float
    argument_arrangement: float
    relevance_to_topic: float
    total_score: float

class DebateEval(BaseModel):
    pro_debater: DebaterScore
    con_debater: DebaterScore
    winner: Literal["pro_debater", "con_debater"]
    reason: str


def debate_judge_agent_card(agent_name: str, card_url: str) -> AgentCard:
    skill = AgentSkill(
        id='moderate_and_judge_debate',
        name='Orchestrates and judges debate',
        description='Orchestrate and judge a debate between two agents on a given topic.',
        tags=['debate'],
        examples=["""
{
  "participants": {
    "pro_debater": "https://pro-debater.example.com:443",
    "con_debater": "https://con-debater.example.org:8443"
  },
  "config": {
    "topic": "Should artificial intelligence be regulated?",
    "num_rounds": 3
  }
}
"""]
    )
    agent_card = AgentCard(
        name=agent_name,
        description='Orchestrate and judge a structured debate between pro and con agents on a given topic with multiple rounds of arguments.',
        url=card_url,
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )
    return agent_card
