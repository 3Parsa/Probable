#!/usr/bin/env python3
"""One-off offline extraction: derive wordgen/data/ngram_model.json (character
bigram frequencies) from a real word/name corpus. Re-run manually if the
source corpus changes; this script is not part of the core engine or the
test suite -- same pattern as extract_weights.py/fetch_teams.py.

Corpora used (real language, deliberately NOT RockYou -- passwords aren't
representative of natural-language letter sequences):

1. System dictionary at DICT_PATH (/usr/share/dict/words, Arch `words`
   package -> american-english wordlist). Required; the script aborts with
   an actionable message if it's missing (mirrors extract_weights.py's
   SOURCE_PATH check).
2. A public first-names corpus, fetched over the network from
   NAMES_CORPUS_URL (dominictarr/random-name's first-names.txt, MIT
   licensed, sourced from the public-domain Moby Word List) -- same
   network-fetch pattern as fetch_teams.py. If the fetch fails, the script
   proceeds on the dictionary alone and prints a note, rather than aborting
   (the dictionary corpus already includes many common given names, e.g.
   "Aaron", "Aaliyah").
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

DICT_PATH = Path("/usr/share/dict/words")
NAMES_CORPUS_URL = (
    "https://raw.githubusercontent.com/dominictarr/random-name/master/first-names.txt"
)
REQUEST_TIMEOUT_SECONDS = 15

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "wordgen" / "data" / "ngram_model.json"


def load_dictionary_words(path: Path) -> list[str]:
    words: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            word = line.strip()
            if not word:
                continue
            # Drop possessive/plural entries like "Aaron's" -> keep only the
            # base token; the apostrophe isn't a letter sequence we want to
            # model as a bigram source.
            word = word.split("'")[0]
            if word.isalpha():
                words.append(word.lower())
    return words


def fetch_names_corpus(url: str) -> list[str]:
    request = urllib.request.Request(url, headers={"User-Agent": "probable/ngram-build"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        text = response.read().decode("utf-8", errors="replace")
    names = [line.strip().lower() for line in text.splitlines() if line.strip()]
    return [name for name in names if name.isalpha()]


def extract_bigrams(words: list[str]) -> Counter:
    """Count overlapping 2-character sequences within each word (not across
    word boundaries)."""
    counts: Counter = Counter()
    for word in words:
        for i in range(len(word) - 1):
            counts[word[i : i + 2]] += 1
    return counts


def main() -> None:
    if not DICT_PATH.exists():
        raise SystemExit(
            f"System dictionary not found: {DICT_PATH}\n"
            "On Arch Linux, install it with: sudo pacman -S words"
        )

    print(f"Reading {DICT_PATH} ...")
    words = load_dictionary_words(DICT_PATH)
    print(f"Loaded {len(words):,} dictionary words.")

    names_used = False
    try:
        print(f"Fetching first-names corpus from {NAMES_CORPUS_URL} ...")
        names = fetch_names_corpus(NAMES_CORPUS_URL)
        print(f"Loaded {len(names):,} first names.")
        words.extend(names)
        names_used = True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"WARNING: could not fetch first-names corpus ({exc}).")
        print("Proceeding with the system dictionary alone.")

    total_corpus_size = len(words)
    bigram_counts = extract_bigrams(words)
    total_bigrams = sum(bigram_counts.values())

    bigram_probs = {
        bigram: count / total_bigrams for bigram, count in bigram_counts.items()
    }

    model = {
        "corpus_size": total_corpus_size,
        "names_corpus_used": names_used,
        "vocabulary_size": len(bigram_probs),
        "total_bigram_count": total_bigrams,
        "bigrams": bigram_probs,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, sort_keys=True)

    print(f"\nWrote {OUTPUT_PATH}")
    print(f"Corpus size (words): {total_corpus_size:,}")
    print(f"Names corpus used: {names_used}")
    print(f"Bigram vocabulary: {len(bigram_probs):,}")
    print(f"Total bigram occurrences: {total_bigrams:,}")

    ranked = sorted(bigram_probs.items(), key=lambda kv: -kv[1])
    print("\nTop 10 most frequent bigrams:")
    for bigram, prob in ranked[:10]:
        print(f"  {bigram!r:6s} {prob:.6f}")

    print("\n10 least frequent bigrams (sanity check -- should look implausible):")
    for bigram, prob in ranked[-10:]:
        print(f"  {bigram!r:6s} {prob:.6f}")


if __name__ == "__main__":
    main()
