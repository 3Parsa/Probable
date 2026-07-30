"""Entry point: typed tokens -> ranked candidate list."""

from __future__ import annotations

from typing import Iterator

from wordgen.core.combiner import Candidate, combine, expand_multiword_value
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


def generate(tokens: list[Token], size: str = "large") -> list[str]:
    ranked = rank(_normalize_spaces(combine(tokens)))
    limit = _SIZE_LIMITS[size]
    if limit is None:
        return ranked
    return ranked[:limit]
