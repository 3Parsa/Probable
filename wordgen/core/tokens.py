from dataclasses import dataclass
from typing import Literal

TokenType = Literal["name", "date", "pet", "team", "place", "partner", "custom"]


@dataclass(frozen=True)
class Token:
    type: TokenType
    value: str
