"""Entry point: typed tokens -> ranked candidate list."""

from __future__ import annotations

from wordgen.core.combiner import combine
from wordgen.core.ranker import rank
from wordgen.core.tokens import Token

# Tiers control only how many ranked candidates come back, not generation depth.
_SIZE_LIMITS = {
    "small": 50,
    "medium": 500,
    "large": None,
}


def generate(tokens: list[Token], size: str = "large") -> list[str]:
    ranked = rank(combine(tokens))
    limit = _SIZE_LIMITS[size]
    if limit is None:
        return ranked
    return ranked[:limit]
