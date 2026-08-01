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
from wordgen.core.plausibility import plausibility_score, plausibility_score_bounds

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

# Subtractive penalty applied to a *standalone* (is_combo=False) candidate's
# score when it comes from a "personal-context" token type -- place, partner,
# pet, custom (see _PENALIZED_STANDALONE_TYPES). Real repro case that forced
# this: a token set of name=Michael, date=1995-03-15, pet=Buddy, two place
# tokens (Liverpool, London), partner=Emily, custom=Sunshine produced a
# medium-size ranked list whose top 10 was almost entirely bare
# "<generic-word><common-suffix>" candidates -- "london1", "sunshine1",
# "sunshin3", "emily1", "liverpool1" -- with only "Michael1995" and
# "Buddy1995" (both real combos, built from the target's actual facts)
# mixed in. These bare candidates aren't wrong to generate (a real password
# could be exactly "london1"), but for a *targeted* tool the point of the
# ranking is to put personalization first -- and pure population-frequency
# case/suffix/leet scoring has no way to tell "london" (a bare place name
# that happens to look like any other common word once suffixed) from a
# word that's actually distinctive of the target, because by the time
# scoring runs the string is just a string. The token type at generation
# time is the only place that distinction still exists, so the penalty is
# applied there via combiner.Candidate.token_type (see its docstring).
#
# name/date standalone candidates are deliberately NOT penalized (kept out
# of _PENALIZED_STANDALONE_TYPES): a bare name or date is still direct,
# first-order information about the target even with no other token
# combined into it (unlike "sunshine", which is only in the wordlist at
# all because the operator called it e.g. a "custom" fact) -- see CLAUDE.md.
# pet IS penalized despite being combo-eligible (pet+date, pet+team):
# this only ever fires on pet's *standalone* forms (is_combo=False checked
# first in rank() below), never on a pet+date/pet+team combo, which still
# gets COMBO_BONUS as before -- a bare "buddy1" has exactly the same
# "generic word + common suffix, no personalization signal" problem as
# "london1", it just happens to come from a token type that can *also*
# combine.
STANDALONE_PENALTY = 1.3
_PENALIZED_STANDALONE_TYPES = {"place", "partner", "pet", "custom"}


def _effective_combo_kind(value: str, combo_kind: str | None) -> str | None:
    """Reclassify a "team" combo as "date" when the candidate is itself
    shaped like a bare 4-digit year (e.g. "ahmet1907", built from a team's
    founding year in teams.json). combo_kind is tagged by the combiner based
    on *source* token-type pair (name+team), but the bonus is meant to track
    how common a personalization *pattern* is -- and a founding year mangled
    into a candidate is structurally indistinguishable from a real birth
    year (same year_like suffix/prefix shape), so scoring it at the smaller
    team-tier bonus purely because of which combiner produced it was an
    arbitrary penalty, not a real distinction the string itself supports.
    Non-numeric team tokens (nicknames, notable names) don't match this
    shape check and keep their original "team" tag. Checked as a post-hoc
    step here (rather than in the combiner) so it applies uniformly
    regardless of which combiner produced the (value, is_combo, combo_kind)
    triple -- including hand-authored ones in the ranking eval set."""
    if combo_kind != "team":
        return combo_kind
    if _YEAR_SUFFIX_RE.search(value) or _YEAR_PREFIX_RE.match(value):
        return "date"
    return combo_kind

_YEAR_SUFFIX_RE = re.compile(r"(19|20)\d{2}$")
_YEAR_PREFIX_RE = re.compile(r"^(19|20)\d{2}")

_LEET_KEYS = {
    "4": "4_for_a",
    "3": "3_for_e",
    "1": "1_for_i",
    "0": "0_for_o",
    "5": "5_for_s",
    "@": "@_for_a",
    "$": "$_for_s",
}

# Separator characters in their standalone-trailing-suffix role (e.g. "bob_",
# "bob$") - distinct from the same characters' combiner-joiner role (scored
# under "separators" below) and from @/$'s unrelated leet-substitution role
# (scored under "leet_subs"). All three categories are looked up and stripped
# independently so none of them double-count the same character.
# "_", ".", "-", "#", "$", "@" are the high-value tier; "&", "*", "+", "%"
# are the medium-value tier, added the same way (see rules.py's _AFFIXES and
# combiner.py's _SEPARATORS).
_SUFFIX_CHAR_NAMES = {
    "_": "underscore",
    ".": "dot",
    "-": "hyphen",
    "#": "hash",
    "$": "dollar",
    "@": "at_symbol",
    "&": "ampersand",
    "*": "asterisk",
    "+": "plus",
    "%": "percent",
}

# Heuristic for "a separator character joining an alphabetic run to a numeric
# run" (e.g. "ahmet_1907", "1907@ahmet") - mirrors the same heuristic in
# scripts/extract_weights.py used to derive the real frequencies for this
# category. Deliberately simple: full-string match, single separator char,
# alpha on one side and digits on the other.
_SEPARATOR_RE = re.compile(
    r"^[A-Za-z]+([_.\-#$@&*+%])\d+$|^\d+([_.\-#$@&*+%])[A-Za-z]+$"
)


def _classify_separator(candidate: str) -> tuple[str | None, str | None]:
    """Returns (category_name, separator_char), or (None, None) if the
    candidate doesn't look like an alpha/digit run joined by a separator."""
    match = _SEPARATOR_RE.match(candidate)
    if not match:
        return None, None
    sep_char = match.group(1) or match.group(2)
    return _SUFFIX_CHAR_NAMES[sep_char], sep_char


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
    if candidate[-1:] in _SUFFIX_CHAR_NAMES:
        return _SUFFIX_CHAR_NAMES[candidate[-1:]]
    return None


_SUFFIX_LENGTHS = {
    "year_like": 4,
    "123": 3,
    "bang": 1,
    "question_mark": 1,
    "single_trailing_digit": 1,
    "underscore": 1,
    "dot": 1,
    "hyphen": 1,
    "hash": 1,
    "dollar": 1,
    "at_symbol": 1,
    "ampersand": 1,
    "asterisk": 1,
    "plus": 1,
    "percent": 1,
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


def _no_separator_weight(separators: dict) -> float:
    """Implied weight for 'no combiner-joiner separator present' -- mirrors
    _no_leet_weight's reasoning exactly: separator usage, like leet subs, is
    an individually rare structural feature across the whole population (most
    candidates are either a single token or a direct concatenation with no
    joiner at all), so its complement is the overwhelmingly common default,
    not a rare fallback."""
    return max(1.0 - sum(separators.values()), _BASELINE)


def _separator_signal(candidate: str, separators: dict) -> float:
    """Weight for the separator category, mirroring _leet_signal: classify to
    the one separator (if any) the candidate matches, or fall back to the
    'no separator' weight."""
    name, _ = _classify_separator(candidate)
    if name is None:
        return _no_separator_weight(separators)
    return _safe_weight(separators.get(name))


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
    separators = weights.get("separators", {})
    return {
        "case_patterns": _category_log_bounds(weights.get("case_patterns", {})),
        "suffixes": _category_log_bounds(weights.get("suffixes", {})),
        "leet_subs": _category_log_bounds(leet_subs, floor=_no_leet_weight(leet_subs)),
        "separators": _category_log_bounds(separators, floor=_no_separator_weight(separators)),
        # Not derived from `weights` (RockYou has nothing to say about
        # natural-language bigram plausibility) -- its own analytically
        # derived bounds, see plausibility_score_bounds().
        "plausibility": plausibility_score_bounds(),
    }


def _score(candidate: str, weights: dict, bounds: dict[str, tuple[float, float]]) -> float:
    """Per-category log-score, min-max normalized within that category's own
    weight range, then summed - this keeps each category's relative ordering
    meaningful while preventing one category's absolute scale, or internal
    skew, from drowning out the others."""
    case_patterns = weights.get("case_patterns", {})
    suffixes = weights.get("suffixes", {})
    leet_subs = weights.get("leet_subs", {})
    separators = weights.get("separators", {})

    pattern = _classify_case_pattern(candidate)
    case_score = _safe_weight(case_patterns.get(pattern)) if pattern else _BASELINE
    case_norm = _normalize(math.log(case_score), bounds["case_patterns"])

    suffix = _classify_suffix(candidate)
    suffix_score = _safe_weight(suffixes.get(suffix)) if suffix else _BASELINE
    suffix_norm = _normalize(math.log(suffix_score), bounds["suffixes"])

    sep_score = _separator_signal(candidate, separators)
    sep_norm = _normalize(math.log(sep_score), bounds["separators"])

    # Strip both the recognized trailing suffix AND the joiner separator (if
    # any) before leet detection - neither a suffix's own digits nor a
    # separator character (some of which, @ and $, double as leet-substitution
    # digits) were ever meant to read as a letter substitution. Keeps the
    # three categories from double-counting the same character.
    base_content = _strip_recognized_suffix(candidate, suffix)
    _, sep_char = _classify_separator(candidate)
    if sep_char:
        base_content = base_content.replace(sep_char, "", 1)
    leet_score = _leet_signal(base_content, leet_subs)
    leet_norm = _normalize(math.log(leet_score), bounds["leet_subs"])

    # Plausibility (wordgen/core/plausibility.py): scored on the same
    # suffix/separator-stripped base_content as leet detection above, so
    # "ahmet1999" is scored on "ahmet"'s bigram plausibility, not the whole
    # mangled string's. plausibility_score() already returns a *length-
    # normalized mean* log-bigram-probability -- it is NOT a raw frequency
    # weight like the other categories, so unlike them it is min-max
    # normalized directly (no extra math.log() here, which would
    # double-transform an already-log value, and no summing it unnormalized
    # alongside the raw per-category log-weights above, which would
    # reintroduce exactly the length bias plausibility_score's own averaging
    # was built to avoid -- see CLAUDE.md).
    plaus_norm = _normalize(plausibility_score(base_content), bounds["plausibility"])

    return case_norm + suffix_norm + leet_norm + sep_norm + plaus_norm


def rank(
    candidates: Iterable[Union[Candidate, tuple[str, bool, Union[str, None]]]]
) -> list[str]:
    """Sort candidates by descending likelihood score.

    Takes (value, is_combo, combo_kind[, token_type]) tuples -- as yielded
    by combiner.combine -- rather than bare strings, since neither "did this
    come from a cross-token combo" nor "which token type(s) produced it" is
    reliably re-derivable from the string itself; the combiner already knows
    both at generation time. token_type is read positionally (index 3) with
    a None default so hand-authored 3-element tuples (e.g.
    tests/ranking_eval_cases.py's combo cases, which have no standalone
    penalty to exercise) keep working unchanged -- None never matches
    _PENALIZED_STANDALONE_TYPES, so it's equivalent to "not penalized".
    """
    weights = _load_weights()
    bounds = _compute_bounds(weights)
    scored = []
    for entry in candidates:
        value, is_combo, combo_kind = entry[0], entry[1], entry[2]
        token_type = entry[3] if len(entry) > 3 else None
        score = _score(value, weights, bounds)
        if is_combo:
            effective_kind = _effective_combo_kind(value, combo_kind)
            score += COMBO_BONUS.get(effective_kind, _DEFAULT_COMBO_BONUS)
        elif token_type in _PENALIZED_STANDALONE_TYPES:
            score -= STANDALONE_PENALTY
        scored.append((value, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [value for value, _ in scored]
