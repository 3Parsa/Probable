"""Trivial combiner: for each token, yield the base value then its rule expansions."""

from __future__ import annotations

from typing import Iterator

from wordgen.core.rules import expand
from wordgen.core.tokens import Token


def combine(tokens: list[Token]) -> Iterator[str]:
    seen: set[str] = set()
    for token in tokens:
        for candidate in expand(token):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate
