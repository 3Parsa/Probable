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


_DISPATCH = {
    "date": expand_date,
}


def expand(token: Token) -> Iterator[str]:
    """Dispatch to the appropriate rule for this token type. Falls back to the raw value."""
    fn = _DISPATCH.get(token.type)
    if fn:
        yield from fn(token)
    else:
        yield token.value
