#!/usr/bin/env python3
"""One-off offline extraction: derive wordgen/data/weights.json from a RockYou-style
count-annotated wordlist. Re-run manually if the source data changes; this script
is not part of the core engine or the test suite.

Input: /tmp/rockyou-withcount.txt, one password per line, formatted as
"<count><whitespace><password>" (tab or space separated).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

SOURCE_PATH = Path("/tmp/rockyou-withcount.txt")
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "wordgen" / "data" / "weights.json"

YEAR_SUFFIX_RE = re.compile(r"(19|20)\d{2}$")
LEET_PAIRS = {"4": "a", "3": "e", "1": "i", "0": "o", "5": "s"}


def load_counts(path: Path) -> dict[str, int]:
    """Parse "<count> <password>" lines into a password -> total count map.
    Duplicate passwords (shouldn't normally occur, but be defensive) accumulate."""
    counts: dict[str, int] = defaultdict(int)
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            raw_count, password = parts
            try:
                count = int(raw_count)
            except ValueError:
                continue
            if not password:
                continue
            counts[password] += count
    return counts


def classify_case_pattern(password: str) -> str | None:
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)

    if not has_lower and not has_upper:
        return None  # no letters at all - not applicable

    if has_lower and not has_upper:
        return "lowercase_only"
    if has_upper and not has_lower:
        return "uppercase_only"

    # mixed case: is it "Capitalized" (first letter upper, rest of letters lower)?
    first_alpha_index = next(i for i, c in enumerate(password) if c.isalpha())
    rest_letters_lower = all(
        c.islower() for c in password[first_alpha_index + 1 :] if c.isalpha()
    )
    if password[first_alpha_index].isupper() and rest_letters_lower:
        return "capitalized_first"
    return "mixed"


def has_single_trailing_digit(password: str) -> bool:
    if len(password) < 1 or not password[-1].isdigit():
        return False
    if len(password) >= 2 and password[-2].isdigit():
        return False
    return True


def extract_weights(counts: dict[str, int]) -> dict:
    grand_total = sum(counts.values())
    case_totals: dict[str, int] = defaultdict(int)
    case_applicable_total = 0
    suffix_totals: dict[str, int] = defaultdict(int)
    leet_totals: dict[str, int] = defaultdict(int)

    for password, count in counts.items():
        # --- case pattern ---
        pattern = classify_case_pattern(password)
        if pattern is not None:
            case_totals[pattern] += count
            case_applicable_total += count

        # --- suffixes ---
        if YEAR_SUFFIX_RE.search(password):
            suffix_totals["year_like"] += count
        if password.endswith("123"):
            suffix_totals["123"] += count
        if password.endswith("!"):
            suffix_totals["bang"] += count
        if password.endswith("?"):
            suffix_totals["question_mark"] += count
        if has_single_trailing_digit(password):
            suffix_totals["single_trailing_digit"] += count

        # --- leet substitutions (approximate proxy) ---
        # A password containing a leet digit "counts" toward that substitution
        # if swapping the digit back to its letter yields another password that
        # actually exists in the dataset (i.e. this looks like a real leet swap
        # of a real word, not a coincidental digit).
        for digit, letter in LEET_PAIRS.items():
            if digit in password:
                candidate = password.replace(digit, letter)
                if candidate != password and candidate in counts:
                    leet_totals[f"{digit}_for_{letter}"] += count

    case_patterns = {
        key: (value / case_applicable_total if case_applicable_total else 0.0)
        for key, value in case_totals.items()
    }
    suffixes = {
        key: (value / grand_total if grand_total else 0.0)
        for key, value in suffix_totals.items()
    }
    leet_subs = {
        key: (value / grand_total if grand_total else 0.0)
        for key, value in leet_totals.items()
    }

    return {
        "grand_total_weight": grand_total,
        "case_patterns": case_patterns,
        "suffixes": suffixes,
        "leet_subs": leet_subs,
    }


def main() -> None:
    if not SOURCE_PATH.exists():
        raise SystemExit(f"Source wordlist not found: {SOURCE_PATH}")

    print(f"Reading {SOURCE_PATH} ...")
    counts = load_counts(SOURCE_PATH)
    print(f"Loaded {len(counts):,} unique passwords.")

    weights = extract_weights(counts)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2, sort_keys=True)

    print(f"\nWrote {OUTPUT_PATH}")
    print(f"\nTotal weighted passwords: {weights['grand_total_weight']:,}")

    print("\nCase patterns:")
    for key, value in sorted(weights["case_patterns"].items(), key=lambda kv: -kv[1]):
        print(f"  {key:20s} {value:.4f}")

    print("\nSuffixes:")
    for key, value in sorted(weights["suffixes"].items(), key=lambda kv: -kv[1]):
        print(f"  {key:20s} {value:.4f}")

    print("\nLeet substitutions:")
    for key, value in sorted(weights["leet_subs"].items(), key=lambda kv: -kv[1]):
        print(f"  {key:20s} {value:.4f}")


if __name__ == "__main__":
    main()
