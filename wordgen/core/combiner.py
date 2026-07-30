"""Combiner: per-token expansions, plus base-value cross-products for pairs of
token types that commonly co-occur in real passwords (name+date is one of the
most common real password structures).

Cross-products use each token's raw/base value, not its full expanded variant
set — crossing full expansions (e.g. 9 name variants x 16 date variants) explodes
combinatorially and produces unrealistic junk like "ahmet!1998". A single light
mangle pass (capitalize-first) is applied to the combined result afterward.

Bases are joined either directly ("ahmet1998") or with a separator character
("ahmet_1998", "ahmet.1998", ...) - this is the separator characters' *joiner*
role, distinct from (and never combined with) their standalone-suffix role in
rules.py's _AFFIXES, or the unrelated leet-substitution role some of the same
characters (@, $) play in rules.py's _LEET_MAP. ranker.py scores all three as
separate categories.
"""

from __future__ import annotations

from typing import Iterator, NamedTuple

from wordgen.core.rules import expand, expand_team
from wordgen.core.tokens import Token


class Candidate(NamedTuple):
    """A generated candidate string, tagged with whether it came from the
    combiner's cross-token step (a name+date, name+team, ... combo) rather
    than a single token's own expansion. The ranker uses this tag to give
    personalized multi-token combos a boost -- it has no reliable way to
    re-detect "comes from a combo" just by looking at the string.

    combo_kind identifies which *token-type pair* produced the combo --
    "date" for name+date/pet+date, "team" for name+team/pet+team -- so the
    ranker can give date combos (a real birth year, one of the most common
    real personalization patterns) a bigger bonus than team combos (a
    specific notable teammate/nickname, a rarer, more idiosyncratic pattern).
    Always None when is_combo is False. Note this reflects the *source*
    token types, not what the resulting string looks like -- a name+team
    combo built from a team's founding year (e.g. "ahmet1907") is still
    combo_kind="team", since the personalization signal (whether the target
    actually supports that team) is about the team fact, not the fact that
    the related token happens to be numeric.

    token_type is the source token's type ("name", "date", "pet", "place",
    "partner", "custom", "team"), set only for standalone candidates
    (is_combo=False) -- combo candidates already carry their own
    provenance signal via combo_kind, and mixing the two would be
    ambiguous (a combo comes from a *pair* of token types, not one). The
    ranker uses this to tell a bare standalone candidate that's still
    directly about the target (a plain name or date, e.g. "michael",
    "1995") from one that's generic filler riding common-word/suffix
    statistics with no personalization signal at all (a bare place/
    partner/pet/custom value, e.g. "london1", "sunshine1") -- see
    ranker.py's STANDALONE_PENALTY."""

    value: str
    is_combo: bool
    combo_kind: str | None = None
    token_type: str | None = None

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


def _combo_kind(type_a: str, type_b: str) -> str:
    pair = {type_a, type_b}
    if "date" in pair:
        return "date"
    if "team" in pair:
        return "team"
    raise ValueError(f"no combo kind for type pair {pair!r}")  # unreachable given _should_combine


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


# Joiner characters the combiner can place between two combo bases, in
# addition to direct concatenation - real passwords commonly separate a name
# from a date/team fact with a punctuation character rather than jamming them
# together (e.g. "ahmet_1998").
_SEPARATORS = ["_", ".", "-", "#", "$", "@"]


def _light_mangle(combo: str) -> Iterator[str]:
    """One light mangle pass on an already-combined string: capitalize-first."""
    yield combo
    capitalized_first = combo[:1].upper() + combo[1:]
    if capitalized_first != combo:
        yield capitalized_first


def _joined_combos(base_a: str, base_b: str) -> Iterator[str]:
    """Every way to join two combo bases: direct concatenation (both orders)
    plus each separator character (both orders)."""
    yield base_a + base_b
    yield base_b + base_a
    for sep in _SEPARATORS:
        yield base_a + sep + base_b
        yield base_b + sep + base_a


def combine(tokens: list[Token]) -> Iterator[Candidate]:
    seen: set[str] = set()

    for token in tokens:
        for candidate in expand(token):
            if candidate not in seen:
                seen.add(candidate)
                yield Candidate(candidate, is_combo=False, token_type=token.type)

    for i, token_a in enumerate(tokens):
        for token_b in tokens[i + 1 :]:
            if not _should_combine(token_a.type, token_b.type):
                continue
            kind = _combo_kind(token_a.type, token_b.type)
            for base_a in _combo_bases(token_a):
                for base_b in _combo_bases(token_b):
                    for combo in _joined_combos(base_a, base_b):
                        for mangled in _light_mangle(combo):
                            if mangled not in seen:
                                seen.add(mangled)
                                yield Candidate(mangled, is_combo=True, combo_kind=kind)
