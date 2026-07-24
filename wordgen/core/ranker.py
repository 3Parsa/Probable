"""Frequency-weighted ranker: orders candidates by likelihood, using structural
frequency weights derived from RockYou (see scripts/extract_weights.py)."""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Union

from wordgen.core.combiner import Candidate

_WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data" / "weights.json"

# Used in place of a missing/zero weight so a candidate isn't wiped out to zero
# just for lacking one feature - the other features still matter.
_BASELINE = 0.01

# Additive bonus applied to a combo candidate's (already per-category
# min-max-normalized) score, keyed by combo_kind (see combiner.Candidate).
# Personalization -- surfacing candidates built from the target's *actual*
# multiple known facts (name+date, name+team, ...) -- is the whole value
# proposition of a targeted tool, but pure population-frequency weighting
# alone buries these under generic single-token patterns that just happen to
# be common in the population at large (e.g. "ahmet1" outranking
# "ahmetGalatasaray"). Deliberately additive on top of, not a replacement
# for, the frequency score: a combo with a genuinely weak case/suffix/leet
# pattern can still lose to a standalone candidate with strong pattern
# signal, it's just no longer buried by default.
#
# Kind-differentiated rather than one flat constant: a birth year is one of
# the single most common real personalization patterns (nearly everyone has
# one, and name+year is a textbook password structure), while a specific
# notable teammate/nickname is a rarer, more idiosyncratic choice -- not
# every target follows a team, and even fans don't always work a specific
# player's name into a password. "date" gets the larger bonus to reflect
# that real-world frequency gap. A flat bonus previously wasn't large enough
# to lift a capitalized name+year combo (e.g. "Ahmet1999") past a lowercase
# generic single-digit candidate (e.g. "ahmet1") -- see CLAUDE.md and
# tests/ranking_eval_cases.py for the worked example these values were tuned
# against.
COMBO_BONUS = {
    "date": 1.1,
    "team": 0.35,
}
_DEFAULT_COMBO_BONUS = 0.5  # fallback if combo_kind is ever missing/unrecognized

_YEAR_SUFFIX_RE = re.compile(r"(19|20)\d{2}$")

_LEET_KEYS = {
    "4": "4_for_a",
    "3": "3_for_e",
    "1": "1_for_i",
    "0": "0_for_o",
    "5": "5_for_s",
}


@lru_cache(maxsize=1)
def _load_weights() -> dict:
    with _WEIGHTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _classify_case_pattern(candidate: str) -> str | None:
    has_lower = any(c.islower() for c in candidate)
    has_upper = any(c.isupper() for c in candidate)

    if not has_lower and not has_upper:
        return None  # no letters, e.g. a bare year or symbol string

    if has_lower and not has_upper:
        return "lowercase_only"
    if has_upper and not has_lower:
        return "uppercase_only"

    first_alpha_index = next(i for i, c in enumerate(candidate) if c.isalpha())
    rest_letters_lower = all(
        c.islower() for c in candidate[first_alpha_index + 1 :] if c.isalpha()
    )
    if candidate[first_alpha_index].isupper() and rest_letters_lower:
        return "capitalized_first"
    return "mixed"


def _classify_suffix(candidate: str) -> str | None:
    if _YEAR_SUFFIX_RE.search(candidate):
        return "year_like"
    if candidate.endswith("123"):
        return "123"
    if candidate.endswith("!"):
        return "bang"
    if candidate.endswith("?"):
        return "question_mark"
    if candidate[-1:].isdigit() and not candidate[-2:-1].isdigit():
        return "single_trailing_digit"
    return None


_SUFFIX_LENGTHS = {
    "year_like": 4,
    "123": 3,
    "bang": 1,
    "question_mark": 1,
    "single_trailing_digit": 1,
}


def _strip_recognized_suffix(candidate: str, suffix: str | None) -> str:
    """Drop the trailing characters _classify_suffix already matched, before
    leet detection scans for digit substitutions. Without this, a numeric
    suffix's own digits (e.g. the '1' in "ahmet1", or the whole "1999" in
    "ahmet1999") get double-counted as a *leet* signal too, just because
    _LEET_KEYS checks raw digit characters anywhere in the string -- a
    trailing year or single digit was never meant to read as a letter
    substitution. This was always a latent confound, but stayed harmless
    while leet's no-signal baseline was low (~_BASELINE); now that
    _no_leet_weight is correctly the dominant value, the false positive would
    otherwise crash scores for almost every suffixed candidate."""
    length = _SUFFIX_LENGTHS.get(suffix, 0)
    return candidate[:-length] if length else candidate


def _no_leet_weight(leet_subs: dict) -> float:
    """Implied weight for 'this candidate has no leet substitution at all' --
    the complement of the population covered by the individual leet_subs
    entries, mirroring how case_patterns' weights already sum to ~1.0 (every
    candidate has *some* case pattern, `lowercase_only` dominates as the
    common default). leet_subs weights sum to only ~0.084 (real leet subs are
    each individually rare), so the natural complement -- "no leet at all" --
    is ~0.916: overwhelmingly the common case, not a rare fallback. Using
    _BASELINE (0.01) here instead, as this used to, put "no leet" *below*
    most individual leet weights, backwards-inverting "has leet" over
    "has no leet" with no other signal present. Falls back to _BASELINE only
    if leet_subs is empty/degenerate (e.g. synthetic test weights), matching
    the neutral-signal fallback used elsewhere."""
    return max(1.0 - sum(leet_subs.values()), _BASELINE)


def _leet_signal(candidate: str, leet_subs: dict) -> float:
    """Pick the single dominant (highest-weight) leet substitution present in
    `candidate`, mirroring how _classify_case_pattern/_classify_suffix each
    classify a candidate into exactly one category value. Multiple
    substitutions can appear in one candidate (e.g. "ahmet1907" has both a
    '1' and a '0'), but summing their log-weights -- as this used to do --
    breaks the min-max normalization below, which assumes one weight per
    candidate per category: the combined log falls well outside the
    single-weight bounds computed for that category, crashing the score.
    Taking the max keeps every category on the same "one weight in, one
    normalized value out" footing."""
    weights_found = [_safe_weight(leet_subs.get(key)) for digit, key in _LEET_KEYS.items() if digit in candidate]
    if not weights_found:
        return _no_leet_weight(leet_subs)
    return max(weights_found)


def _safe_weight(weight: float | None) -> float:
    """Fall back to the baseline for a missing or non-positive weight, so a
    single category never zeroes out (or log-blows-up) the combined score."""
    return weight if weight and weight > 0 else _BASELINE


def _category_log_bounds(category: dict, floor: float = _BASELINE) -> tuple[float, float]:
    """Min/max log-weight seen within a single category (including `floor`,
    since that's a value a candidate can actually be scored with -- the
    no-signal fallback for that category)."""
    logs = [math.log(_safe_weight(w)) for w in category.values()]
    logs.append(math.log(floor))
    return min(logs), max(logs)


def _normalize(log_value: float, bounds: tuple[float, float]) -> float:
    """Min-max normalize a log-weight to roughly 0-1 within its own category's
    range, so no category's internal skew (e.g. case_patterns spanning a much
    wider log range than suffixes) can dominate the summed score."""
    min_log, max_log = bounds
    if max_log == min_log:
        return 0.5  # category has no spread - contributes a neutral signal
    return (log_value - min_log) / (max_log - min_log)


def _compute_bounds(weights: dict) -> dict[str, tuple[float, float]]:
    leet_subs = weights.get("leet_subs", {})
    return {
        "case_patterns": _category_log_bounds(weights.get("case_patterns", {})),
        "suffixes": _category_log_bounds(weights.get("suffixes", {})),
        "leet_subs": _category_log_bounds(leet_subs, floor=_no_leet_weight(leet_subs)),
    }


def _score(candidate: str, weights: dict, bounds: dict[str, tuple[float, float]]) -> float:
    """Per-category log-score, min-max normalized within that category's own
    weight range, then summed - this keeps each category's relative ordering
    meaningful while preventing one category's absolute scale, or internal
    skew, from drowning out the others."""
    case_patterns = weights.get("case_patterns", {})
    suffixes = weights.get("suffixes", {})
    leet_subs = weights.get("leet_subs", {})

    pattern = _classify_case_pattern(candidate)
    case_score = _safe_weight(case_patterns.get(pattern)) if pattern else _BASELINE
    case_norm = _normalize(math.log(case_score), bounds["case_patterns"])

    suffix = _classify_suffix(candidate)
    suffix_score = _safe_weight(suffixes.get(suffix)) if suffix else _BASELINE
    suffix_norm = _normalize(math.log(suffix_score), bounds["suffixes"])

    leet_candidate = _strip_recognized_suffix(candidate, suffix)
    leet_score = _leet_signal(leet_candidate, leet_subs)
    leet_norm = _normalize(math.log(leet_score), bounds["leet_subs"])

    return case_norm + suffix_norm + leet_norm


def rank(candidates: Iterable[Union[Candidate, tuple[str, bool, Union[str, None]]]]) -> list[str]:
    """Sort candidates by descending likelihood score.

    Takes (value, is_combo, combo_kind) triples -- as yielded by
    combiner.combine -- rather than bare strings, since neither "did this
    come from a cross-token combo" nor "which token types produced it" is
    reliably re-derivable from the string itself; the combiner already knows
    both at generation time.
    """
    weights = _load_weights()
    bounds = _compute_bounds(weights)
    scored = []
    for value, is_combo, combo_kind in candidates:
        score = _score(value, weights, bounds)
        if is_combo:
            score += COMBO_BONUS.get(combo_kind, _DEFAULT_COMBO_BONUS)
        scored.append((value, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [value for value, _ in scored]
