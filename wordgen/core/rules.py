"""Per-type token expansion rules. Each function accepts a Token and yields string candidates."""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from wordgen.core.tokens import Token

_TEAMS_PATH = Path(__file__).resolve().parent.parent / "data" / "teams.json"


def team_lookup_key(name: str) -> str:
    """Canonical lookup key for a team name: lowercase, diacritics stripped,
    whitespace collapsed. teams.json's keys are built this same way by
    scripts/fetch_teams.py's `_slug()` (team names fetched from Wikipedia
    routinely carry diacritics, e.g. "Beşiktaş", "Deportivo Alavés", which get
    ASCII-folded before being stored as the key). expand_team() below MUST use
    this same normalization when looking a token's value up -- a lookup that
    only `.lower()`'d without stripping diacritics would silently fail to
    match teams.json's ASCII-only keys whenever an operator typed a team's
    real, diacritic-bearing name (exactly the form they're most likely to
    type, since that's the team's actual name)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_name.lower().split())


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
    "a": ["4", "@"],
    "e": ["3"],
    "i": ["1"],
    "o": ["0"],
    "s": ["5", "$"],
}

# Trailing affixes: numeric/punctuation suffixes, plus the separator characters
# in their standalone-suffix role (see combiner.py for their other role, joining
# combo bases together - the two roles are scored as distinct categories in
# ranker.py, never conflated).
_AFFIXES = ["123", "!", "?", "1", "_", ".", "-", "#", "$", "@"]


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

    for char, digits in _LEET_MAP.items():
        if char in lower:
            for digit in digits:
                yield lower.replace(char, digit)

    for suffix in _AFFIXES:
        yield lower + suffix


@lru_cache(maxsize=1)
def _load_teams() -> dict:
    with _TEAMS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def team_related_values(token: Token) -> list[str]:
    """Raw nickname/founding-year/notable-name values for a known team,
    exactly as stored in teams.json -- no whitespace normalization applied.
    Shared by expand_team() below (which strips a multi-word nickname's
    internal whitespace before yielding it as a standalone candidate -- see
    there for why) and combiner._team_combo_bases() (which needs the
    original word boundaries preserved to build separator-joined nickname
    variants, e.g. "Die Bayern" -> "Die_Bayern", not just the already-
    stripped "DieBayern"), so both work off the same teams.json lookup
    without duplicating it. Empty list for an unknown team."""
    entry = _load_teams().get(team_lookup_key(token.value))
    if not entry:
        return []

    values = []
    nickname = entry.get("nickname")
    if nickname:
        values.append(nickname)

    founded = entry.get("founded")
    if founded:
        values.append(founded)

    values.extend(entry.get("notable", []))
    return values


def expand_team(token: Token) -> Iterator[str]:
    """Expand a team token into its related tokens (nickname, founding year, notable names).

    Related tokens are yielded raw, undigested — they get name-rule mangling
    separately if the operator adds them as their own tokens. Unknown teams
    (not in data/teams.json) fall back to the raw value.

    A multi-word value (real example: several teams' nicknames are two
    words, e.g. Bayern Munich's "Die Bayern", Liverpool's "The Reds") has
    its internal whitespace stripped before being yielded -- nobody puts a
    literal space in a real password, so "Die Bayern" is never itself a
    candidate; it becomes "DieBayern" here. (combiner._team_combo_bases()
    separately builds separator-joined variants like "Die_Bayern" for the
    combo case, from the same raw value via team_related_values() above --
    this function only needs the simple stripped form, since a standalone
    related-token candidate was never mangled further than this to begin
    with.) Single-word values pass through unchanged -- "".join(x.split())
    is a no-op when x has no internal whitespace.
    """
    yield token.value

    for value in team_related_values(token):
        yield "".join(value.split())


_DISPATCH = {
    "date": expand_date,
    "name": expand_name,
    "pet": expand_name,
    "place": expand_name,
    "partner": expand_name,
    "custom": expand_name,
    "team": expand_team,
}


def expand(token: Token) -> Iterator[str]:
    """Dispatch to the appropriate rule for this token type. Falls back to the raw value."""
    fn = _DISPATCH.get(token.type)
    if fn:
        yield from fn(token)
    else:
        yield token.value
