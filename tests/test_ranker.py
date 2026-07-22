import wordgen.core.ranker as ranker_module
from wordgen.core.ranker import rank

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

    results = rank(["johnsmith", "Johnsmith1998"])
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

    results = rank([strong_case_no_suffix, strong_suffix_weak_case])
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
    candidates = ["johnsmith", "Johnsmith1998", "JOHNSMITH", "john!"]
    results = rank(candidates)

    from wordgen.core.ranker import _compute_bounds, _load_weights, _score

    weights = _load_weights()
    bounds = _compute_bounds(weights)
    scores = [_score(c, weights, bounds) for c in results]
    assert scores == sorted(scores, reverse=True)
