"""Combiner: per-token expansions, plus base-value cross-products for pairs of
token types that commonly co-occur in real passwords (name+date is one of the
most common real password structures).

Cross-products use each token's raw/base value, not its full expanded variant
set — crossing full expansions (e.g. 9 name variants x 16 date variants) explodes
combinatorially and produces unrealistic junk like "ahmet!1998". A single light
mangle pass (capitalize-first) is applied to the combined result afterward.
"""

from __future__ import annotations

from typing import Iterator

from wordgen.core.rules import expand, expand_team
from wordgen.core.tokens import Token

# Only these type pairs get crossed - arbitrary crossing explodes combinatorially
# without adding realistic candidates.
_COMBO_PAIRS = frozenset(
    {
        frozenset({"name", "date"}),
        frozenset({"pet", "date"}),
        frozenset({"name", "team"}),
        frozenset({"pet", "team"}),
    }
)


def _should_combine(type_a: str, type_b: str) -> bool:
    return frozenset({type_a, type_b}) in _COMBO_PAIRS


def _date_combo_bases(token: Token) -> list[str]:
    """A small, sensible subset of date formats for combination (YYYY, DDMMYYYY) -
    real passwords use these, not the raw hyphenated/ISO value."""
    raw = token.value.replace("-", "").replace("/", "")
    if len(raw) == 8:
        yyyy, mm, dd = raw[:4], raw[4:6], raw[6:8]
        return [yyyy, dd + mm + yyyy]
    return [raw]


def _team_combo_bases(token: Token) -> list[str]:
    """Team combo bases are the related tokens (nickname, founding year, notable
    names) - the full club name itself is unrealistic as a password component."""
    return list(expand_team(token))[1:]


def _combo_bases(token: Token) -> list[str]:
    if token.type == "date":
        return _date_combo_bases(token)
    if token.type == "team":
        return _team_combo_bases(token)
    return [token.value]


def _light_mangle(combo: str) -> Iterator[str]:
    """One light mangle pass on an already-combined string: capitalize-first."""
    yield combo
    capitalized_first = combo[:1].upper() + combo[1:]
    if capitalized_first != combo:
        yield capitalized_first


def combine(tokens: list[Token]) -> Iterator[str]:
    seen: set[str] = set()

    for token in tokens:
        for candidate in expand(token):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate

    for i, token_a in enumerate(tokens):
        for token_b in tokens[i + 1 :]:
            if not _should_combine(token_a.type, token_b.type):
                continue
            for base_a in _combo_bases(token_a):
                for base_b in _combo_bases(token_b):
                    for combo in (base_a + base_b, base_b + base_a):
                        for mangled in _light_mangle(combo):
                            if mangled not in seen:
                                seen.add(mangled)
                                yield mangled
