"""Entry point: typed tokens -> ranked candidate list."""

from __future__ import annotations

from collections import deque
from typing import Iterator

from wordgen.core.combiner import Candidate, combine, expand_multiword_value, shape_family
from wordgen.core.ranker import rank
from wordgen.core.tokens import Token

# Tiers control only how many ranked candidates come back, not generation depth.
_SIZE_LIMITS = {
    "small": 50,
    "medium": 500,
    "large": None,
}


def _normalize_spaces(candidates: Iterator[Candidate]) -> Iterator[Candidate]:
    """Firm invariant, enforced as a final safety net regardless of source:
    no generated candidate should ever contain a literal space character --
    virtually no real system accepts spaces in passwords. Team nicknames
    already get this treatment at the source (rules.expand_team /
    combiner._team_combo_bases, see CLAUDE.md), which is still the better
    fix where it's feasible -- catching a space-containing value at its
    origin means it never has to flow through the rest of the pipeline
    carrying dead weight. But the source of a literal space isn't only
    nicknames: any raw operator-typed multi-word token value (e.g.
    Token("team", "Bayern Munich"), Token("place", "New York")) still
    echoes straight through as a standalone candidate via expand()'s
    "yield the raw value" step (name/date/team all do this), and any
    *future* token type or rule could introduce its own new space-leak path
    without anyone thinking to special-case it the way team nicknames were.
    This is the one place every candidate is guaranteed to pass through
    before ranking, so it's the right (and only reliable) place for a
    guarantee that has to hold regardless of which source produced the
    candidate.

    Reuses expand_multiword_value (combiner.py) rather than just
    `.replace(" ", "")` -- same "direct-concat + one variant per separator
    character" pattern as the nickname fix, applied uniformly here so a
    space-leak caught by this backstop degrades exactly the same way as one
    caught at the source, rather than silently only ever producing the
    stripped form. Re-dedupes on the way out: normalizing can produce a
    value that collides with one already seen (either another normalized
    variant or an already-space-free candidate), and combine()'s own dedup
    only ever saw the pre-normalization strings.
    """
    seen: set[str] = set()
    for candidate in candidates:
        variants = expand_multiword_value(candidate.value) if " " in candidate.value else [candidate.value]
        for variant in variants:
            if variant not in seen:
                seen.add(variant)
                yield candidate._replace(value=variant)


def _diversify(ranked: list[str]) -> list[str]:
    """Output-diversity pass, applied after ranking and before size
    truncation. Real bug (see CLAUDE.md): the ranker scores each candidate
    independently with no concept of output diversity, so when one combo
    pattern scores well, ALL of its separator variants score nearly
    identically and cluster together -- a real Michael1995+liverpool combo
    put 9 near-identical TheReds*Michael1995 variants (differing only by
    separator character) in the first 9 of the top 11 results, crowding out
    every other distinct candidate.

    Groups candidates into "shape families" via combiner.shape_family()
    (same base combo, separators stripped) and round-robins across
    families in score order rather than emitting a whole family
    consecutively: each pass takes one (the next-highest-scoring) member
    from every family that still has one left, so no family can occupy two
    output slots before every other family present has had a turn. The
    single highest-scoring candidate overall still leads the output --
    this reorders which candidates get *deferred*, not which one wins the
    top spot -- and a family with only one member is untouched.

    Applied to the full ranked list before size truncation (not just the
    top N) so a "small"/"medium" truncation afterward draws from an
    already-diversified pool, rather than the tier cutoff landing mid-family
    and this pass never getting a chance to run on the rest.
    """
    families: dict[str, deque[str]] = {}
    family_order: list[str] = []
    for value in ranked:
        key = shape_family(value)
        if key not in families:
            families[key] = deque()
            family_order.append(key)
        families[key].append(value)

    result: list[str] = []
    while family_order:
        next_order = []
        for key in family_order:
            bucket = families[key]
            result.append(bucket.popleft())
            if bucket:
                next_order.append(key)
        family_order = next_order
    return result


def generate(tokens: list[Token], size: str = "large") -> list[str]:
    ranked = _diversify(rank(_normalize_spaces(combine(tokens))))
    limit = _SIZE_LIMITS[size]
    if limit is None:
        return ranked
    return ranked[:limit]
