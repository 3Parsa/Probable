"""Entry point: typed tokens -> candidate iterator."""

from __future__ import annotations

from typing import Iterator

from wordgen.core.combiner import combine
from wordgen.core.tokens import Token


def generate(tokens: list[Token]) -> Iterator[str]:
    yield from combine(tokens)
