#!/usr/bin/env python3
"""One-off offline fetch: pull real football team data (canonical name,
short/alternate name, founding year) from TheSportsDB's free public API
(https://www.thesportsdb.com/api/v1/json/3/search_all_teams.php, no API key
required for this endpoint) to build out wordgen/data/teams.json well beyond
the 5 hand-seeded entries.

TheSportsDB's free tier has no reliable "notable players" concept, so this
script does NOT fabricate any -- newly-added teams get notable=[] (empty,
not fake data). The 5 hand-curated teams (fenerbahce, galatasaray, besiktas,
barcelona, real madrid) keep their existing, manually-researched notable
names untouched: this script merges API data into the hand-seed, it never
overwrites a non-empty hand-curated field.

Non-Latin-script alternate names (e.g. a Cyrillic strTeamAlternate) are
filtered out at fetch time, not carried through to teams.json: rules.py's
case/leet/suffix mangling only operates on Latin letters, so a non-Latin
nickname would reach runtime as a dead candidate -- yielded raw, never
mangled, contributing nothing. Filtering here means the runtime never has to
special-case it. See _is_latin_script/_nickname_from below.

Like scripts/extract_weights.py, this is a one-off/offline tool -- re-run
manually if you want fresher/broader data, not part of the test suite or any
automated pipeline. Rate-limited to one request per league (~1.5s apart) with
a generous timeout; a single league's failure is caught and reported in the
summary rather than aborting the whole run.
"""

from __future__ import annotations

import json
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://www.thesportsdb.com/api/v1/json/3/search_all_teams.php"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "wordgen" / "data" / "teams.json"
REQUEST_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 15

# Major football leagues spanning several confederations, for breadth without
# hammering the API (one request per league). TheSportsDB's shared free-tier
# key caps each league's team list at ~10 teams (alphabetical) regardless of
# the league's real size, so ~17 leagues lands in the 100-200 team range this
# project wants, not tens of thousands. League name strings must match
# TheSportsDB's own `strLeague` values exactly or the query returns nothing.
LEAGUES = [
    "English Premier League",
    "Spanish La Liga",
    "Italian Serie A",
    "German Bundesliga",
    "Turkish Super Lig",
    "French Ligue 1",
    "Dutch Eredivisie",
    "Portuguese Primeira Liga",
    "Belgian Pro League",
    "Scottish Premiership",
    "Brazilian Serie A",
    "Argentinian Primera Division",
    "American Major League Soccer",
    "Russian Football Premier League",
    "Greek Superleague Greece",
    "Swiss Super League",
    "Austrian Bundesliga",
]

# Hand-curated seed data (wordgen/data/teams.json's original 5 entries).
# notable-player names here are real and manually researched -- never
# overwritten by the API fetch below, which has nothing equivalent to offer.
SEED_TEAMS = {
    "fenerbahce": {"nickname": "Fener", "founded": "1907", "notable": ["Alex", "Aykut"]},
    "galatasaray": {"nickname": "Cimbom", "founded": "1905", "notable": ["Drogba", "Hagi"]},
    "besiktas": {"nickname": "Kartal", "founded": "1903", "notable": ["Necati"]},
    "barcelona": {"nickname": "Barca", "founded": "1899", "notable": ["Messi", "Xavi"]},
    "real madrid": {"nickname": "Los Blancos", "founded": "1902", "notable": ["Ronaldo", "Zidane"]},
}


def _slug(name: str) -> str:
    """Lowercase, diacritic-stripped, whitespace-collapsed lookup key.
    TheSportsDB returns names like "Beşiktaş"/"Fenerbahçe" -- stripping
    diacritics here is what lets an API-fetched "Beşiktaş" merge into the
    existing "besiktas" entry instead of creating a duplicate.

    MUST stay byte-for-byte identical to wordgen.core.rules.team_lookup_key,
    which expand_team() uses at lookup time to turn an operator-typed team
    token (e.g. "Beşiktaş" or "Deportivo Alavés" -- the team's real name,
    which is exactly what an operator is likely to type) into the same key
    this script stores. This script deliberately doesn't import
    wordgen.core.rules (one-off scripts stay decoupled from the package, same
    as extract_weights.py), so the two copies are cross-checked by
    tests/test_teams_data.py::test_fetch_teams_slug_matches_runtime_lookup_key
    rather than by sharing code -- keep them in sync by hand."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_name.lower().split())


def _is_latin_script(text: str) -> bool:
    """True if every alphabetic character in `text` is Latin script (this
    covers accented Latin letters too, e.g. "ş"/"ç"/"é" -- Unicode's own
    character names for those still start with "LATIN"). Used to filter out
    alternate names in scripts (Cyrillic, etc.) that rules.py's
    case/leet/suffix mangling has no handling for at all -- keeping one
    through would silently produce a candidate that's yielded raw and never
    mangled. A character with no Unicode name at all is treated as
    non-Latin (fail closed)."""
    return all(unicodedata.name(ch, "").startswith("LATIN") for ch in text if ch.isalpha())


def _nickname_from(team: dict) -> tuple[str, bool]:
    """Best-effort short/alternate name, used as the "nickname" field.
    TheSportsDB's free tier has no real nickname concept: strTeamShort is
    usually blank (only populated for a handful of teams, e.g. "GAL" for
    Galatasaray), so fall back to the first comma-separated
    strTeamAlternate entry. Empty string (never a fabricated guess) if
    neither is present or usable.

    Returns (nickname, was_filtered) -- was_filtered is True if at least one
    candidate (short or alternate) existed but was dropped for not being
    Latin-script, even if a later candidate was accepted instead. Used only
    for the run summary."""
    candidates = []
    short = (team.get("strTeamShort") or "").strip()
    if short:
        candidates.append(short)
    alternate = (team.get("strTeamAlternate") or "").strip()
    if alternate:
        first = alternate.split(",")[0].strip()
        if first:
            candidates.append(first)

    was_filtered = False
    for candidate in candidates:
        if _is_latin_script(candidate):
            return candidate, was_filtered
        was_filtered = True
    return "", was_filtered


def fetch_league(league: str) -> tuple[list[dict], str | None]:
    """Fetch one league's teams. Returns (teams, error_message); error_message
    is None on success. Network/timeout/malformed-JSON errors are caught here
    so one bad league doesn't abort the whole run."""
    url = f"{API_BASE}?l={urllib.parse.quote(league)}"
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return [], f"{league}: {exc}"
    return payload.get("teams") or [], None


def build_teams() -> tuple[dict, dict]:
    """Fetches every league in LEAGUES and merges the results into
    SEED_TEAMS. Returns (merged_teams, stats) for the run summary."""
    merged = {key: dict(value) for key, value in SEED_TEAMS.items()}
    seed_keys = set(SEED_TEAMS.keys())
    seen_this_run: set[str] = set()

    stats = {
        "leagues_ok": 0,
        "leagues_failed": [],
        "teams_seen": 0,
        "teams_added": 0,
        "teams_merged_into_seed": 0,
        "duplicate_teams_skipped": 0,
        "notable_preserved": set(),
        "non_latin_nicknames_filtered": 0,
    }

    for i, league in enumerate(LEAGUES):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        teams, error = fetch_league(league)
        if error:
            stats["leagues_failed"].append(error)
            continue
        stats["leagues_ok"] += 1

        for team in teams:
            name = team.get("strTeam")
            if not name:
                continue
            stats["teams_seen"] += 1
            key = _slug(name)

            nickname, was_filtered = _nickname_from(team)
            if was_filtered:
                stats["non_latin_nicknames_filtered"] += 1

            fetched_entry = {
                "nickname": nickname,
                "founded": (team.get("intFormedYear") or "").strip(),
                "notable": [],
            }

            if key in seed_keys:
                existing = merged[key]
                # Fill gaps only -- never overwrite a non-empty hand-curated
                # field with an API-derived value.
                if not existing.get("nickname") and fetched_entry["nickname"]:
                    existing["nickname"] = fetched_entry["nickname"]
                if not existing.get("founded") and fetched_entry["founded"]:
                    existing["founded"] = fetched_entry["founded"]
                if existing.get("notable"):
                    stats["notable_preserved"].add(key)
                stats["teams_merged_into_seed"] += 1
            elif key in seen_this_run:
                # Same team surfaced from a second league query (e.g. cup
                # cross-listing) -- already added, nothing new to do.
                stats["duplicate_teams_skipped"] += 1
            else:
                merged[key] = fetched_entry
                seen_this_run.add(key)
                stats["teams_added"] += 1

    return merged, stats


def main() -> None:
    merged, stats = build_teams()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {OUTPUT_PATH}")

    print(f"\nLeagues fetched OK: {stats['leagues_ok']}/{len(LEAGUES)}")
    if stats["leagues_failed"]:
        print("Leagues failed:")
        for failure in stats["leagues_failed"]:
            print(f"  {failure}")

    print(f"\nTotal teams in file: {len(merged)}")
    print(f"Raw teams seen across all league fetches: {stats['teams_seen']}")
    print(f"New teams added: {stats['teams_added']}")
    print(f"Duplicate teams skipped (seen in >1 league): {stats['duplicate_teams_skipped']}")
    print(f"Teams matched to a hand-seeded entry (merged, not duplicated): {stats['teams_merged_into_seed']}")
    if stats["notable_preserved"]:
        preserved = ", ".join(sorted(stats["notable_preserved"]))
        print(f"Hand-curated notable-names preserved (not overwritten) for: {preserved}")
    else:
        print("No hand-seeded teams were matched by this run's fetch -- seed notable-names untouched regardless.")
    print(f"Non-Latin-script alternate names filtered out (nickname omitted or fell back): {stats['non_latin_nicknames_filtered']}")


if __name__ == "__main__":
    main()
