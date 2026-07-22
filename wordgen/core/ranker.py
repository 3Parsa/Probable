"""Frequency-weighted ranker: orders candidates by likelihood, using structural
frequency weights derived from RockYou (see scripts/extract_weights.py)."""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

_WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data" / "weights.json"

# Used in place of a missing/zero weight so a candidate isn't wiped out to zero
# just for lacking one feature - the other features still matter.
_BASELINE = 0.01

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


def _safe_weight(weight: float | None) -> float:
    """Fall back to the baseline for a missing or non-positive weight, so a
    single category never zeroes out (or log-blows-up) the combined score."""
    return weight if weight and weight > 0 else _BASELINE


def _category_log_bounds(category: dict) -> tuple[float, float]:
    """Min/max log-weight seen within a single category (including the baseline,
    since that's a value a candidate can actually be scored with)."""
    logs = [math.log(_safe_weight(w)) for w in category.values()]
    logs.append(math.log(_BASELINE))
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
    return {
        "case_patterns": _category_log_bounds(weights.get("case_patterns", {})),
        "suffixes": _category_log_bounds(weights.get("suffixes", {})),
        "leet_subs": _category_log_bounds(weights.get("leet_subs", {})),
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

    leet_log = 0.0
    leet_found = False
    for digit, key in _LEET_KEYS.items():
        if digit in candidate:
            leet_found = True
            leet_log += math.log(_safe_weight(leet_subs.get(key)))
    if not leet_found:
        leet_log = math.log(_BASELINE)
    leet_norm = _normalize(leet_log, bounds["leet_subs"])

    return case_norm + suffix_norm + leet_norm


def rank(candidates: Iterable[str]) -> list[str]:
    """Sort candidates by descending likelihood score."""
    weights = _load_weights()
    bounds = _compute_bounds(weights)
    scored = [(candidate, _score(candidate, weights, bounds)) for candidate in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [candidate for candidate, _ in scored]
