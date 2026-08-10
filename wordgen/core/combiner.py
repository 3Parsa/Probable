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

from wordgen.core.rules import expand, team_related_values
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


def expand_multiword_value(value: str) -> list[str]:
    """A value containing internal whitespace (real example: several teams'
    nicknames are two words, e.g. Bayern Munich's "Die Bayern") can't be
    used as-is -- nobody puts a literal space in a real password. Expands
    it into the same "direct-concat + one variant per separator character"
    shape _joined_combos already produces when crossing two *different*
    tokens, so a multi-word value's own internal words get joined exactly
    the same way -- e.g. "Die Bayern" -> ["DieBayern", "Die_Bayern",
    "Die.Bayern", ...]. Single-word values pass through unchanged (the
    overwhelmingly common case).

    Used in two places, for two different reasons: _team_combo_bases below
    takes only this list's first (direct-concat) entry as its combo base --
    NOT the full separator-variant list, which was tried first and caused a
    real double-separator-expansion bug (each pre-separated variant getting
    crossed again by _joined_combos' own separator set -- see
    _team_combo_bases' docstring). engine.py's _normalize_spaces calls this
    directly (using the full list) as a final catch-all safety net for *any*
    remaining space-containing candidate regardless of source (e.g. a raw
    operator-typed multi-word team/place/etc. value echoed as a standalone
    candidate) -- see its docstring for why that backstop exists on top of,
    not instead of, fixing each source individually."""
    words = value.split()
    if len(words) < 2:
        return [value]
    return ["".join(words)] + [sep.join(words) for sep in _SEPARATORS]


def _team_combo_bases(token: Token) -> list[str]:
    """Team combo bases are the related tokens (nickname, founding year, notable
    names) - the full club name itself is unrealistic as a password component.
    Uses team_related_values() (raw values, spaces intact) rather than
    expand_team()'s own yielded candidates -- expand_team() already strips a
    multi-word nickname down to one stripped-together form for its own
    standalone-candidate purposes, which would throw away the word
    boundaries expand_multiword_value needs.

    Takes only expand_multiword_value()'s first (direct-concat) form per
    related value, not its full separator-variant list (real bug, found via
    a real repro: Token("name", "Michael1995") + Token("team", "liverpool")
    produced 264 combo candidates for a *single* token pair, the large
    majority nested-separator junk like "The_Reds.Michael1995"). Taking every
    separator variant as its own base meant each one then got crossed AGAIN
    by _joined_combos' own full separator set below -- a nickname's 11
    internally-pre-separated variants (direct-concat + 10 separators) times
    _joined_combos' 22 join options each is 242 combos from one related value
    alone, before even counting founding year / notable names. This is the
    same "crossed full expansion sets instead of base values" root cause as
    the project's original combiner bug, just reached through this
    later-added multiword-nickname path instead. One canonical base per
    related value (its plain direct-concat form, e.g. "TheReds") lets the
    outer _joined_combos below supply all the separator diversity -- exactly
    how every other combo pair (name+date, pet+date) already works -- while
    still producing clean results like "MichaelTheReds"/"TheReds_Michael1995"
    without the nested-separator double expansion."""
    return [expand_multiword_value(value)[0] for value in team_related_values(token)]


def _combo_bases(token: Token) -> list[str]:
    if token.type == "date":
        return _date_combo_bases(token)
    if token.type == "team":
        return _team_combo_bases(token)
    return [token.value]


# Joiner characters the combiner can place between two combo bases, in
# addition to direct concatenation - real passwords commonly separate a name
# from a date/team fact with a punctuation character rather than jamming them
# together (e.g. "ahmet_1998"). "_", ".", "-", "#", "$", "@" are the
# high-value tier; "&", "*", "+", "%" are the medium-value tier, added the
# same way (see rules.py's _AFFIXES for their standalone-suffix counterpart).
_SEPARATORS = ["_", ".", "-", "#", "$", "@", "&", "*", "+", "%"]


def shape_family(value: str) -> str:
    """Collapses a candidate down to its "shape family" key: every joiner
    separator character stripped out, so candidates that differ only by
    which separator (or none) joins the same two combo bases collapse to
    the same key -- e.g. "TheReds_Michael1995", "TheReds.Michael1995", and
    "TheRedsMichael1995" (direct concat) all collapse to
    "TheRedsMichael1995". Used by engine.py's output-diversity pass to keep
    one combo pattern's separator variants (there are up to 11: direct
    concat + one per _SEPARATORS character) from crowding out every other
    distinct idea near the top of ranked output -- real repro: a
    Michael1995+liverpool combo put 9 near-identical TheReds*Michael1995
    variants in the first 9 slots of a top-11 result, differing from each
    other only by separator character."""
    result = value
    for sep in _SEPARATORS:
        result = result.replace(sep, "")
    return result


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
