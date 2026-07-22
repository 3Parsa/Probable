"""Per-type token expansion rules. Each function accepts a Token and yields string candidates."""

from __future__ import annotations

from typing import Iterator

from wordgen.core.tokens import Token


def expand_date(token: Token) -> Iterator[str]:
    """Expand a date token into format variants.

    Accepts flexible formats: YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD, or bare YYYY.
    Yields: YYYY, YY, MMDD, DDMM, MMDDYYYY, DDMMYYYY, MMDDYY, DDMMYY.
    """
    raw = token.value.replace("-", "").replace("/", "")

    if len(raw) == 8:
        yyyy, mm, dd = raw[:4], raw[4:6], raw[6:8]
        yy = yyyy[2:]
        yield yyyy
        yield yy
        yield mm + dd
        yield dd + mm
        yield mm + dd + yyyy
        yield dd + mm + yyyy
        yield mm + dd + yy
        yield dd + mm + yy
    elif len(raw) == 4:
        # bare year
        yield raw
        yield raw[2:]
    else:
        yield raw


_LEET_MAP = {
    "a": "4",
    "e": "3",
    "i": "1",
    "o": "0",
    "s": "5",
}

_AFFIXES = ["123", "!", "?", "1"]


def expand_name(token: Token) -> Iterator[str]:
    """Expand a name-like token: case toggles, single-swap leet, and common affixes.

    Applies to name, pet, place, partner, and custom tokens alike, since they're
    all free-text personal tokens with the same likely mangling patterns.
    """
    base = token.value
    lower = base.lower()
    upper = base.upper()
    capitalized = base.capitalize()

    yield lower
    if upper != lower:
        yield upper
    if capitalized != lower and capitalized != upper:
        yield capitalized

    for char, digit in _LEET_MAP.items():
        if char in lower:
            yield lower.replace(char, digit)

    for suffix in _AFFIXES:
        yield lower + suffix


_DISPATCH = {
    "date": expand_date,
    "name": expand_name,
    "pet": expand_name,
    "place": expand_name,
    "partner": expand_name,
    "custom": expand_name,
}


def expand(token: Token) -> Iterator[str]:
    """Dispatch to the appropriate rule for this token type. Falls back to the raw value."""
    fn = _DISPATCH.get(token.type)
    if fn:
        yield from fn(token)
    else:
        yield token.value
