import wordgen.core.ranker as ranker_module
from wordgen.core.ranker import rank
from tests.ranking_eval_cases import CASES

# Synthetic weights isolate the scoring mechanism from the actual values in
# data/weights.json (which are derived from real RockYou data and could change
# on re-extraction) - here capitalized+year is deliberately weighted above
# plain lowercase to exercise the combination logic deterministically.
_SYNTHETIC_WEIGHTS = {
    "case_patterns": {"lowercase_only": 0.1, "capitalized_first": 0.5},
    "suffixes": {"year_like": 0.5},
    "leet_subs": {},
}


def test_capitalized_year_suffix_outscores_plain_lowercase(monkeypatch):
    monkeypatch.setattr(ranker_module, "_load_weights", lambda: _SYNTHETIC_WEIGHTS)

    results = rank([("johnsmith", False, None), ("Johnsmith1998", False, None)])
    assert results[0] == "Johnsmith1998"
    assert results.index("Johnsmith1998") < results.index("johnsmith")


# Weights modeling the realistic shape of the dominance bug: lowercase_only is
# by far the most common case pattern, so multiplying raw weights let it crush
# any suffix signal. capitalized_first is much rarer on its own, but a strong
# year suffix should be able to log-sum its way past a no-suffix lowercase
# candidate once no single category's absolute scale can drown out the rest.
_DOMINANCE_WEIGHTS = {
    "case_patterns": {"lowercase_only": 0.9, "capitalized_first": 0.02},
    "suffixes": {"year_like": 0.8},
    "leet_subs": {},
}


def test_strong_suffix_can_outrank_strong_case_pattern_with_no_suffix(monkeypatch):
    monkeypatch.setattr(ranker_module, "_load_weights", lambda: _DOMINANCE_WEIGHTS)

    # weak case pattern + strong suffix
    strong_suffix_weak_case = "Ahmet1998"
    # strong case pattern + no suffix at all
    strong_case_no_suffix = "ahmetsmith"

    results = rank([(strong_case_no_suffix, False, None), (strong_suffix_weak_case, False, None)])
    assert results[0] == strong_suffix_weak_case
    assert results.index(strong_suffix_weak_case) < results.index(strong_case_no_suffix)


# Note: no regression test asserting "Ahmet1998" outranks "ahmet1" against the
# real wordgen/data/weights.json. Verified empirically that it does not, and
# that's correct given the actual RockYou-derived statistics: lowercase_only
# (0.929) vastly outranks capitalized_first (0.0215) even after per-category
# normalization, AND single_trailing_digit (0.093) is genuinely more common
# than year_like (0.033) in real data. Both categories independently favor
# ahmet1 - that's real signal, not a dominance artifact, so no scoring fix
# should flip it. The synthetic-weights test above exercises the actual
# mechanism (a category's own normalized range letting a strong-suffix
# candidate outrank a strong-case one) without depending on real data values.


def test_rank_sorts_descending_by_score():
    candidates = [
        ("johnsmith", False, None),
        ("Johnsmith1998", False, None),
        ("JOHNSMITH", False, None),
        ("john!", False, None),
    ]
    results = rank(candidates)

    from wordgen.core.ranker import _compute_bounds, _load_weights, _score

    weights = _load_weights()
    bounds = _compute_bounds(weights)
    scores = [_score(c, weights, bounds) for c in results]
    assert scores == sorted(scores, reverse=True)


def test_combo_bonus_lifts_personalized_combo_near_top_of_generic_single_tokens():
    # Repro of the real 6-token web GUI finding: name+date combos didn't
    # surface until position 19+ behind a wall of generic single-token
    # variants that all share the population's single most common pattern
    # (lowercase + a single trailing digit, e.g. "ahmet1", "mehmet1", ...).
    # Uses the actual RockYou-derived weights (no monkeypatch) since this is
    # specifically about that real-data shape, not a synthetic mechanism.
    from wordgen.core.combiner import combine
    from wordgen.core.tokens import Token

    name_date_combo = list(combine([Token(type="name", value="ahmet"), Token(type="date", value="1999")]))
    generic_single_tokens = [
        (f"{name}1", False, None)
        for name in ["mehmet", "seker", "yilmaz", "kartal", "aslan", "kaplan", "deniz", "murat"]
    ]

    results = rank(name_date_combo + generic_single_tokens)

    # The combo is now competitive with, not buried behind, the generic wall.
    assert results.index("ahmet1999") < 3

    # Without the bonus, this same combo is buried well behind the generic
    # single-token wall -- confirms the bonus is doing real work here, not
    # just riding an already-favorable pattern score.
    monkeypatch_free_results = rank(
        [(value, False, None) for value, _, _ in name_date_combo] + generic_single_tokens
    )
    assert monkeypatch_free_results.index("ahmet1999") > results.index("ahmet1999")


def test_combo_bonus_does_not_flip_documented_ahmet1_vs_ahmet1998_finding():
    # The documented real-data finding (see note above and CLAUDE.md): with the
    # actual RockYou-derived weights, "ahmet1" legitimately outranks
    # "Ahmet1998" -- both are single-token candidates with no combo tag, so the
    # combo bonus must not apply to either and this ordering must be unaffected.
    results = rank([("ahmet1", False, None), ("Ahmet1998", False, None)])
    assert results[0] == "ahmet1"


def test_ranking_eval_cases_against_real_weights():
    """Runs the labeled eval set (tests/ranking_eval_cases.py) through the real
    ranker.rank() against the real wordgen/data/weights.json -- no synthetic
    weights, no monkeypatch. This is the falsifiable, measurable substitute
    for eyeballing `probable generate` output.

    Collects every failing case rather than stopping at the first one, so a
    single pytest run reports the full honest pass/fail breakdown for tuning.
    This test is allowed to fail today -- see CLAUDE.md for the current
    baseline pass rate and why each known failure happens. It's the target
    for the next round of scoring work, not a guarantee about current
    behavior.
    """
    failures = []
    for case in CASES:
        results = rank([case.higher, case.lower])
        if results[0] != case.higher[0]:
            failures.append(case)

    total = len(CASES)
    passed = total - len(failures)
    report_lines = [f"{passed}/{total} ranking eval cases passed ({100 * passed / total:.0f}%)."]
    for case in failures:
        report_lines.append(
            f"FAILED: expected {case.higher[0]!r} > {case.lower[0]!r} -- {case.reason}"
        )

    assert not failures, "\n".join(report_lines)
