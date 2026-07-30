"""Labeled ranking eval set: pairs of candidates with a justified expected
ordering, so ranker quality is measurable and falsifiable instead of judged by
eyeballing `probable generate` output.

Each case is (higher, lower, reason) where `higher` is expected to score
*above* `lower` in wordgen.core.ranker.rank(). `higher`/`lower` are
(value, is_combo, combo_kind) triples, matching the contract
wordgen.core.combiner.combine() yields (as Candidate) and
wordgen.core.ranker.rank() consumes -- see CLAUDE.md's Ranker/Combiner notes
for why is_combo/combo_kind are tagged at generation time rather than
re-derived from the string. combo_kind is "date" or "team" when is_combo is
True (mirroring the token-type pair that produced the combo), else None.

This file is deliberately NOT auto-fixed to 100% passing. It's the target for
the next round of scoring work (see tests/test_ranker.py::
test_ranking_eval_cases_against_real_weights for the current honest pass
rate and CLAUDE.md for the baseline write-up).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankingCase:
    higher: tuple[str, bool, str | None]  # (value, is_combo, combo_kind) -- expected above `lower`
    lower: tuple[str, bool, str | None]  # (value, is_combo, combo_kind) -- expected below `higher`
    reason: str


CASES: list[RankingCase] = [
    RankingCase(
        higher=("ahmet1999", True, "date"),
        lower=("ahmet7", False, None),
        reason="name+year combo (a real personalized fact pairing) should beat "
        "name+arbitrary-single-digit (not tied to any known fact about the target).",
    ),
    RankingCase(
        higher=("Ahmet1999", True, "date"),
        lower=("AhmetHagi", True, "team"),
        reason="year is a stronger, more common real-world suffix pattern (year_like) "
        "than a bare name+notable-name combo with no numeric suffix at all -- also "
        "exercises the kind-differentiated bonus, since date combos get the larger "
        "bonus (a birth year is a far more common personalization pattern than a "
        "specific teammate's name).",
    ),
    RankingCase(
        higher=("ahmet1", False, None),
        lower=("ahmet", False, None),
        reason="a recognized suffix (single trailing digit) should beat no suffix at "
        "all, holding case pattern constant.",
    ),
    RankingCase(
        higher=("Ahmet1999", True, "date"),
        lower=("ahmet1", False, None),
        reason="CORE BUG CASE: a personalized two-fact combo (target's real name + "
        "real birth year) should beat a generic single-fact standalone candidate "
        "that only has an arbitrary trailing digit -- this is the exact real-data "
        "finding (combos buried at position 19+) the combo bonus was added for. "
        "Needed the kind-differentiated 'date' bonus tier to actually win, not "
        "just the original flat bonus -- see CLAUDE.md.",
    ),
    RankingCase(
        higher=("Ahmet1999", True, "date"),
        lower=("ahmetzzzz123", True, "date"),
        reason="GUARDRAIL: a real personalized combo (real name + real year) must "
        "beat pure nonsense (fabricated filler letters + a generic '123' suffix) "
        "even under the worst case of both getting the same (larger, 'date') bonus "
        "tier -- the bonus should not let garbage win just for being tagged a combo. "
        "KNOWN FAILURE -- see CLAUDE.md: this isn't fixable by bonus tuning, it "
        "exposes a real architectural limit (structural case/suffix/leet scoring "
        "can't tell real content from nonsense content). STILL FAILS after wiring "
        "in wordgen/core/plausibility.py as a scoring category: plausibility does "
        "correctly favor 'ahmet' over 'ahmetzzzz' (-6.44 vs -7.28 mean "
        "log-bigram-probability -> normalized gap ~+0.07 in Ahmet1999's favor), "
        "but that's nowhere near enough to offset the case_pattern gap between "
        "capitalized_first and lowercase_only (~-0.83 -- lowercase_only is ~93% "
        "of real RockYou passwords) plus the suffix gap between year_like and "
        "'123' (~+0.16) working against it; net effect is still negative. The "
        "real architectural point survives the fix, just sharpened: capitalizing "
        "a real name costs far more in log-space than the plausibility gap "
        "between a real name and a short repeated-letter run gains back, when "
        "plausibility is only one of five equally-weighted categories.",
    ),
    RankingCase(
        higher=("ahmet1999", True, "date"),
        lower=("AHMET1999", True, "date"),
        reason="lowercase_only is by far the single most common real-world case "
        "pattern -- a lowercase combo should beat an uppercase-only combo that "
        "shares the same year suffix and the same combo-kind bonus.",
    ),
    RankingCase(
        higher=("ahmet", False, None),
        lower=("4hmet", False, None),
        reason="GUARDRAIL: with no suffix on either side, a plain no-leet standalone "
        "should beat a leetspeak substitution -- leet subs are individually rarer "
        "than plain lowercase in real password data.",
    ),
    RankingCase(
        higher=("ahmet1", False, None),
        lower=("4hmet1", False, None),
        reason="GUARDRAIL: same single-trailing-digit suffix on both sides -- a "
        "plain name should still beat one that additionally stacks a leet "
        "substitution.",
    ),
    RankingCase(
        higher=("rex1999", True, "date"),
        lower=("rex7", False, None),
        reason="pet+date combo (a real fact pairing) should beat pet+arbitrary-digit "
        "standalone -- mirrors the name+date case above for a different token pair.",
    ),
    RankingCase(
        higher=("ahmetcimbom", True, "team"),
        lower=("ahmet", False, None),
        reason="name+team nickname combo should beat the bare standalone name with "
        "no suffix at all.",
    ),
    RankingCase(
        higher=("rexcimbom", True, "team"),
        lower=("rex", False, None),
        reason="pet+team nickname combo should beat the bare standalone pet with no "
        "suffix -- mirrors the name+team case above for a different combo-pair type.",
    ),
    RankingCase(
        higher=("ahmetdrogba", True, "team"),
        lower=("AhmetDrogba", True, "team"),
        reason="lowercase name+notable-name combo should beat the capitalized-mangle "
        "variant of the identical combo -- isolates the case penalty on combos "
        "specifically, since both share the same token pairing and the same bonus.",
    ),
    RankingCase(
        higher=("ahmet1907", True, "team"),
        lower=("ahmet7", False, None),
        reason="GUARDRAIL: name+real-founding-year combo should beat name+arbitrary-"
        "digit standalone, same as the name+birth-year case above. Tagged combo_kind="
        "'team' at the source (the combo is built from a name+team token pair), but "
        "the ranker's _effective_combo_kind reclassifies it to the 'date' bonus tier "
        "before scoring, since a bare founding year is shape-identical to a real "
        "birth year -- see CLAUDE.md's combo-bonus tagging fix.",
    ),
    RankingCase(
        higher=("Ahmet1905", True, "team"),
        lower=("AhmetHagi", True, "team"),
        reason="RECLASSIFICATION CASE: Ahmet1905 (Galatasaray's founding year, tagged "
        "combo_kind='team' at the source since it's a name+team combo) should score "
        "comparably to an equivalent date-kind combo, not at the smaller team-tier "
        "bonus, because a bare 4-digit year is structurally identical to a real date "
        "combo -- it gets the year_like suffix and the larger 'date' bonus via "
        "_effective_combo_kind's shape-based reclassification. AhmetHagi (a "
        "non-numeric notable-name combo) has no such shape match and stays at the "
        "smaller team-tier bonus, so it should lose.",
    ),
    RankingCase(
        higher=("ahmet1", False, None),
        lower=("ahmet!", False, None),
        reason="single trailing digit is a far more common real suffix pattern than "
        "a trailing '!' mangle, holding case pattern constant.",
    ),
    RankingCase(
        higher=("ahmet1999", True, "date"),
        lower=("ahmet_1999", True, "date"),
        reason="SEPARATOR CASE: direct concatenation (no joiner) should beat the same "
        "name+year combo joined with a separator character. Per real RockYou data "
        "(scripts/extract_weights.py), 'no separator at all' covers ~99.5% of "
        "candidates vs. underscore (the single most common separator) at ~0.22% -- "
        "direct concatenation is overwhelmingly the common case, a separator joiner "
        "is the rarer, more idiosyncratic choice.",
    ),
    RankingCase(
        higher=("ahmet.1999", True, "date"),
        lower=("ahmet@1999", True, "date"),
        reason="SEPARATOR CASE: '.' should beat '@' as a joiner between the same "
        "name+year combo. Per real RockYou data, '.' is used as a separator "
        "(~0.067%) noticeably more often than '@' (~0.043%) -- confirms the "
        "intuition that '.' is the more common punctuation-as-joiner choice.",
    ),
    # --- Plausibility cases (wordgen/core/plausibility.py, wired into ranker.py's
    # per-category scoring) -- each pair below deliberately holds case pattern,
    # suffix, leet, and separator identical (and combo_kind, so the bonus
    # cancels too), so plausibility is the *only* category free to differ. This
    # isolates the new signal instead of conflating it with the categories
    # above -- see CLAUDE.md's Plausibility section for why the Ahmet1999 vs
    # ahmetzzzz123 case (below) still doesn't flip even with plausibility wired
    # in.
    RankingCase(
        higher=("ahmet1999", True, "date"),
        lower=("qxzvb1999", True, "date"),
        reason="PLAUSIBILITY CASE: identical suffix (year_like), case pattern "
        "(lowercase_only), and combo_kind ('date', so COMBO_BONUS cancels) on "
        "both sides -- a real name+year combo should still beat a random "
        "consonant-cluster+year combo, since plausibility is the only category "
        "left free to differ.",
    ),
    RankingCase(
        higher=("ahmetcimbom", True, "team"),
        lower=("qxzvbfghjk", True, "team"),
        reason="PLAUSIBILITY CASE: identical case pattern (lowercase_only), no "
        "suffix on either side, and combo_kind ('team') on both -- a real "
        "name+nickname combo should beat a same-shape combo built from random "
        "consonant clusters on both sides.",
    ),
    RankingCase(
        higher=("sarah2001", True, "date"),
        lower=("xqzak2001", True, "date"),
        reason="PLAUSIBILITY CASE: mirrors the ahmet1999/qxzvb1999 case with a "
        "different name+year pair, to check the plausibility signal isn't an "
        "artifact of 'ahmet' specifically.",
    ),
]
