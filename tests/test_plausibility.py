"""Validation tests for wordgen/core/plausibility.py -- the standalone
character-bigram plausibility scorer. This module is NOT yet wired into
wordgen/core/ranker.py or any other existing scoring path (see CLAUDE.md);
these tests are what has to hold up *before* any integration work is
considered.

Labeled eval set, same falsifiable-pairs style as tests/ranking_eval_cases.py
-- each case states an expected ordering and the real-language reason behind
it, checked against the actual bigram model built by
scripts/build_ngram_model.py (not a synthetic/mocked model), so a failure
here means the approach itself needs revisiting, not just a test fixture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from wordgen.core.plausibility import _UNSEEN_BIGRAM_FLOOR, plausibility_score


@dataclass(frozen=True)
class PlausibilityCase:
    higher: str  # expected to score above `lower`
    lower: str
    reason: str


CASES: list[PlausibilityCase] = [
    PlausibilityCase(
        higher="ahmet",
        lower="zzzz",
        reason="a real name should beat a repeated-letter run that essentially "
        "never occurs in real words/names ('zz' is a rare bigram in the corpus).",
    ),
    PlausibilityCase(
        higher="ahmet",
        lower="qxzvb",
        reason="a real name should beat a random consonant cluster with no "
        "vowels and no real-language bigrams at all.",
    ),
    PlausibilityCase(
        higher="hello",
        lower="hzxpq",
        reason="a real English word should beat a same-length random "
        "consonant cluster.",
    ),
    PlausibilityCase(
        higher="table",
        lower="tqzbl",
        reason="a real English word should beat a same-length string with no "
        "recognizable English letter sequences.",
    ),
    PlausibilityCase(
        higher="sarah",
        lower="xqzak",
        reason="a common first name should beat a same-length string built "
        "from rare/absent bigrams.",
    ),
    PlausibilityCase(
        higher="banana",
        lower="bqnqnq",
        reason="a real word should beat a similarly-structured (alternating "
        "consonant/vowel-shaped) but non-real string using an implausible "
        "letter ('q' where 'a' belongs).",
    ),
    PlausibilityCase(
        higher="christopher",
        lower="xhqvstopfer",
        reason="a common real name should beat a same-length string with "
        "several implausible letter transitions.",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.higher}>{c.lower}")
def test_plausibility_eval_cases(case: PlausibilityCase) -> None:
    higher_score = plausibility_score(case.higher)
    lower_score = plausibility_score(case.lower)
    assert higher_score > lower_score, (
        f"{case.higher!r} ({higher_score}) should score above "
        f"{case.lower!r} ({lower_score}): {case.reason}"
    )


def test_short_strings_score_neutral() -> None:
    # Length 0-1 strings have no bigrams to score -- should return the
    # documented neutral value, not crash.
    assert plausibility_score("") == 0.0
    assert plausibility_score("a") == 0.0


def test_unseen_bigram_degrades_gracefully_instead_of_crashing() -> None:
    # "qz" is genuinely absent from the real bigram model (verified against
    # wordgen/data/ngram_model.json), so this exercises the smoothing floor
    # rather than a real corpus hit.
    score = plausibility_score("qz")
    assert math.isfinite(score)
    assert score == pytest.approx(math.log(_UNSEEN_BIGRAM_FLOOR))


def test_unseen_bigram_scores_below_a_real_bigram() -> None:
    # The floor should sit below every real observed bigram probability, so
    # an unseen-but-typed bigram is treated as less plausible than any real
    # one, not accidentally more plausible.
    seen_word_score = plausibility_score("an")  # "an" is a common real bigram
    unseen_word_score = plausibility_score("qz")
    assert unseen_word_score < seen_word_score


def test_word_with_one_unseen_bigram_does_not_crash_to_negative_infinity() -> None:
    # A longer, mostly-real word with exactly one implausible bigram spliced
    # in should still produce a finite score -- the floor should absorb the
    # one bad bigram, not blow up the whole candidate.
    score = plausibility_score("ahmeqzt")
    assert math.isfinite(score)
    assert score < plausibility_score("ahmet")
