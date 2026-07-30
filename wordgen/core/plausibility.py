"""Standalone character-bigram word plausibility scorer.

Scores how much a lowercase word/token "looks like" real language (a
dictionary word or common first name), using bigram frequencies derived from
a real corpus (see scripts/build_ngram_model.py) rather than RockYou --
passwords aren't representative of natural-language letter sequences, which
is exactly the signal this module is meant to add.

Deliberately standalone: NOT wired into wordgen/core/ranker.py or any other
existing scoring path. This module must be independently validated (see
tests/test_plausibility.py) before any integration work is considered.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

_MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "ngram_model.json"

# Smoothing floor for a bigram that's genuinely absent from the corpus (e.g.
# "qz"). Set below the real model's lowest observed probability (~0.000001,
# see scripts/build_ngram_model.py's least-frequent-bigrams sanity print) so
# an unseen bigram is still scored as *less* plausible than the rarest bigram
# actually seen in real language, without collapsing the whole candidate's
# score to -inf via log(0).
_UNSEEN_BIGRAM_FLOOR = 1e-7


@lru_cache(maxsize=1)
def _load_model() -> dict:
    with _MODEL_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _bigrams(word: str) -> list[str]:
    return [word[i : i + 2] for i in range(len(word) - 1)]


def plausibility_score(word: str) -> float:
    """Score how plausible `word` is as real language, via the *mean* of its
    character-bigram log-probabilities (log-sum in the same style as
    wordgen/core/ranker.py's frequency scoring -- prevents one weak bigram
    from multiplicatively dominating the whole score -- then divided by
    bigram count).

    The length-normalization matters: comparing two words of different
    lengths with a raw (un-normalized) log-sum systematically favors
    *shorter* words / fewer bigrams, regardless of how plausible each
    bigram actually is (e.g. a 4-letter word with one repeated
    moderately-common bigram summed 3 times can out-score a 5-letter word
    with 4 individually rarer bigrams, purely on bigram count). Averaging
    makes scores comparable across different word lengths -- the same idea
    as length-normalized log-likelihood/perplexity in language modeling.

    Higher (less negative) = more plausible. Length-0/1 strings have no
    bigrams to score and return 0.0 (neutral -- neither evidence for nor
    against plausibility). Bigrams absent from the corpus are scored at a
    small smoothing floor (_UNSEEN_BIGRAM_FLOOR) instead of crashing to
    log(0) = -inf.
    """
    word = word.lower()
    pairs = _bigrams(word)
    if not pairs:
        return 0.0

    bigram_probs = _load_model()["bigrams"]
    total = 0.0
    for pair in pairs:
        prob = bigram_probs.get(pair, _UNSEEN_BIGRAM_FLOOR)
        total += math.log(prob)
    return total / len(pairs)
