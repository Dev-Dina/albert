from dataclasses import dataclass
from typing import Literal

# How the turn is executed. Defaults to "agent" so any decision constructed
# without an explicit handler routes to the bounded agent (safe fallback).
Handler = Literal["drop", "rag", "lead", "escalate", "agent"]


@dataclass
class RouterDecision:
    action: Literal["agent", "direct"]
    label: str
    confidence: float
    routed_to: str
    reply: str | None = None
    handler: Handler = "agent"
