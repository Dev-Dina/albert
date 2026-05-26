from dataclasses import dataclass
from typing import Literal


@dataclass
class RouterDecision:
    action: Literal["agent", "direct"]
    label: str
    confidence: float
    routed_to: str
    reply: str | None = None
