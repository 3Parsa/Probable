#!/usr/bin/env python3
"""One-off offline fetch: pull real football team data (canonical name,
founding year, nickname) from Wikipedia's current-season club-roster tables
and each club's own article infobox, to build out wordgen/data/teams.json.

Replaces the previous TheSportsDB-based fetch entirely. TheSportsDB's
free-tier `search_all_teams.php` caps every league's bulk result at ~10
teams, alphabetically -- confirmed directly against the raw API (10/10
English Premier League results were "Arsenal" through "Fulham", nothing
past F). For a ~20-team league this doesn't fail, it silently truncates:
Arsenal/Chelsea (early alphabetically) made it into teams.json while
Liverpool, both Manchester clubs, and Tottenham Hotspur -- some of the
league's most recognizable, highest-personalization-value clubs -- were
silently missing. A targeted per-club patch (MUST_INCLUDE_TEAMS) fixed that
one gap, but the underlying cap is a hard free-tier limit with no paid-tier
workaround available to this project, and would keep recurring for every
other league in LEAGUES. Wikipedia's league-club-list pages are complete,
current, and well-maintained, with no equivalent artificial cap -- see
CLAUDE.md for the full writeup of both the original bug and this rebuild.

For each league: fetch its current-season Wikipedia article's club-roster
table via action=parse&prop=wikitext (the raw wikitext, not rendered HTML --
parses against Wikipedia's own stable markup rather than brittle CSS-class
scraping), extract each club's display name and its own article title from
the table's wikilinks, then fetch that club's own article and pull founding
year / nickname from its {{Infobox football club}} template. Never
fabricates a value: a club article missing that infobox entirely, or an
infobox missing a given field, is left out/empty rather than guessed -- see
fetch_club_infobox (the adapted "is this actually a football club" safety
net, replacing the old strSport == "Soccer" check) and
_clean_nickname/_clean_founded.

Wikitext is parsed with wikitextparser (github.com/5j9/wikitextparser), not
regex -- MediaWiki tables use rowspan/colspan that only a real table model
resolves correctly (e.g. a club with two stadiums, like Argentina's Central
Córdoba (SdE), spans two table rows for one club; a naive "first cell per
row" parse would misread the continuation row's stadium name as a second,
bogus club -- data(span=True) resolves this properly, and find_club_roster
also dedupes by wikilink target as a second safety net).

Identifies itself with a descriptive User-Agent and paces every request
(~1/second) per Wikipedia's API etiquette
(https://www.mediawiki.org/wiki/API:Etiquette) -- this is a manually re-run,
one-off script, never an automated/scheduled bot, and the request volume
(roughly one per league plus one per club, a few hundred total) reflects
that.

Like scripts/extract_weights.py, this is a one-off/offline tool -- re-run
manually if you want fresher data, not part of the test suite or any
automated pipeline. NOTE: LEAGUE_PAGES' page titles are season-specific
(e.g. "2026-27 Premier League") and will need bumping by hand in a future
season; EXPECTED_TEAM_COUNTS may need the same if a league's format changes
(promotion/relegation count, competition restructuring, etc.).
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import wikitextparser as wtp

API_BASE = "https://en.wikipedia.org/w/api.php"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "wordgen" / "data" / "teams.json"
REQUEST_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 20
USER_AGENT = (
    "probable-wordgen-teams-fetch/2.0 "
    "(one-off, manually re-run offline dataset build script for a personal "
    "password-wordlist research project; not an automated/scheduled bot; "
    "self-throttled to ~1 request/second, see scripts/fetch_teams.py)"
)

# Each league's current-season (or, where noted, main league page) Wikipedia
# article -- the page whose club-roster table is the source of truth for
# "who is currently in this league". SEASON-SPECIFIC: written against the
# 2026-27 (or 2026, for calendar-year leagues) season as of this script's
# last run -- bump these titles by hand when re-running in a future season.
# Each was individually verified against the raw Wikipedia API (wikitext
# fetched, table parsed, row count checked) when this list was built; see
# CLAUDE.md for the full per-league verification notes.
LEAGUE_PAGES = {
    "English Premier League": "2026–27 Premier League",
    "Spanish La Liga": "2026–27 La Liga",
    "Italian Serie A": "2026–27 Serie A",
    "German Bundesliga": "2026–27 Bundesliga",
    "Turkish Super Lig": "2026–27 Süper Lig",
    "French Ligue 1": "2026–27 Ligue 1",
    "Dutch Eredivisie": "2026–27 Eredivisie",
    "Portuguese Primeira Liga": "2026–27 Primeira Liga",
    "Belgian Pro League": "2026–27 Belgian Pro League",
    "Scottish Premier League": "2026–27 Scottish Premiership",
    "Brazilian Serie A": "2026 Campeonato Brasileiro Série A",
    "Argentinian Primera Division": "2026 AFA Liga Profesional de Fútbol",
    "American Major League Soccer": "2026 Major League Soccer season",
    "Russian Football Premier League": "2026–27 Russian Premier League",
    "Greek Superleague Greece": "2026–27 Super League Greece",
    # NOT the 2026-27 season page: confirmed (on both the 2025-26 and
    # 2026-27 season articles) that its "Teams" section table only ever
    # shows 5 of the league's 12 clubs (a partial stadium-photo showcase,
    # not a full roster) -- a real per-league exception, not a bug in the
    # general table-finding logic below. The main (non-season) "Swiss Super
    # League" article has a clean, complete, 12-row
    # Club/Location/Stadium/Capacity table instead.
    "Swiss Super League": "Swiss Super League",
    "Austrian Bundesliga": "2026–27 Austrian Football Bundesliga",
}

# Real club counts for each league's current season, individually verified
# against these same Wikipedia pages (parsed row count, cross-checked where
# available against the article's own prose statement, e.g. "eighteen teams
# are participating" on the Ligue 1 page) when this list was built -- see
# CLAUDE.md. Used as a completeness cross-check on every run: build_teams()
# flags (never silently accepts) any league whose parsed roster doesn't
# match, whether short or, just as suspiciously, over.
EXPECTED_TEAM_COUNTS = {
    "English Premier League": 20,
    "Spanish La Liga": 20,
    "Italian Serie A": 20,
    "German Bundesliga": 18,
    "Turkish Super Lig": 18,
    "French Ligue 1": 18,
    "Dutch Eredivisie": 18,
    "Portuguese Primeira Liga": 18,
    "Belgian Pro League": 18,
    "Scottish Premier League": 12,
    "Brazilian Serie A": 20,
    "Argentinian Primera Division": 30,
    "American Major League Soccer": 30,
    "Russian Football Premier League": 16,
    "Greek Superleague Greece": 14,
    "Swiss Super League": 12,
    "Austrian Bundesliga": 12,
}

# Hand-curated seed data (wordgen/data/teams.json's original 5 entries).
# notable-player names here are real and manually researched -- never
# overwritten by the fetch below, which has nothing equivalent to offer.
SEED_TEAMS = {
    "fenerbahce": {"nickname": "Fener", "founded": "1907", "notable": ["Alex", "Aykut"]},
    "galatasaray": {"nickname": "Cimbom", "founded": "1905", "notable": ["Drogba", "Hagi"]},
    "besiktas": {"nickname": "Kartal", "founded": "1903", "notable": ["Necati"]},
    "barcelona": {"nickname": "Barca", "founded": "1899", "notable": ["Messi", "Xavi"]},
    "real madrid": {"nickname": "Los Blancos", "founded": "1902", "notable": ["Ronaldo", "Zidane"]},
}

_REF_RE = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
# Pure display/formatting wrapper templates seen in real infobox nickname
# fields -- these wrap real content rather than being data of their own, so
# they're unwrapped to their first item rather than stripped like a
# citation template. Two sub-kinds share one set since both are handled the
# same way (take the first line/bullet of the wrapped argument): simple
# single-value wrappers (e.g. {{Nowrap|''Los Blancos'' (The Whites)}}) and
# bulleted-list wrappers (e.g. LASK's nickname field,
# "{{Plainlist|\n*''Die Schwarz-Weißen''\n*''Die Laskler''\n...}}" -- a
# naive unwrap-to-whole-argument here would leave the '\n*' bullets in the
# text, and this module's <br>-based "take the first alternative" split
# doesn't know about them).
_PASSTHROUGH_TEMPLATES = {
    "nowrap", "nobold", "small", "nobr", "small caps",
    "plainlist", "flatlist", "unbulleted list", "ubl", "hlist",
}
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")


def _slug(name: str) -> str:
    """Lowercase, diacritic-stripped, whitespace-collapsed lookup key.
    Wikipedia club names routinely carry diacritics ("Beşiktaş",
    "Fenerbahçe") -- stripping them here is what lets a Wikipedia-fetched
    "Beşiktaş" merge into the existing "besiktas" entry instead of creating
    a duplicate.

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
    nicknames in scripts (Cyrillic, etc.) that rules.py's case/leet/suffix
    mangling has no handling for at all -- keeping one through would
    silently produce a candidate that's yielded raw and never mangled. A
    character with no Unicode name at all is treated as non-Latin (fail
    closed)."""
    return all(unicodedata.name(ch, "").startswith("LATIN") for ch in text if ch.isalpha())


_MAX_RETRIES = 4


def _fetch_wikitext(title: str) -> tuple[str | None, str | None]:
    """Fetch one article's raw wikitext via action=parse. Returns
    (wikitext, error_message); error_message is None on success. Both
    network-level failures and Wikipedia's own "page doesn't exist" API
    error are caught here so one bad page doesn't abort the whole run.

    Passes redirects=1 -- several roster-table wikilinks point at a redirect
    page rather than the club's real article (e.g. "SK Rapid Vienna"
    redirects to "SK Rapid Wien"); without this, the API returns just the
    one-line "#REDIRECT [[...]]" stub instead of following it, which has no
    infobox at all and would wrongly trip the "not actually a football
    club" safety net in fetch_club_infobox for a real, valid club.

    Retries on HTTP 429 (rate limited) -- respecting the server's own
    Retry-After header when present, falling back to simple exponential
    backoff (5s, 10s, 20s, ...) when it isn't -- rather than either
    hammering straight through a 429 or aborting the whole run over a
    transient throttle. A handful of these are expected in a run this size
    even at the script's self-imposed pace; giving up immediately would
    turn a brief throttle into missing data."""
    url = f"{API_BASE}?action=parse&page={urllib.parse.quote(title)}&prop=wikitext&redirects=1&format=json"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    backoff = 5.0
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < _MAX_RETRIES:
                wait = float(exc.headers.get("Retry-After", backoff)) if exc.headers else backoff
                time.sleep(wait)
                backoff *= 2
                continue
            return None, f"{title}: HTTP {exc.code} {exc.reason}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            return None, f"{title}: {exc}"
    else:
        return None, f"{title}: gave up after {_MAX_RETRIES} retries (rate limited)"
    if "error" in payload:
        return None, f"{title}: {payload['error'].get('info', payload['error'])}"
    return payload["parse"]["wikitext"]["*"], None


def _first_wikilink(cell: str) -> tuple[str, str] | None:
    """First [[target|text]] (or [[target]]) wikilink in a table cell's
    wikitext, as (target, display_text) -- display_text falls back to
    target for an unpiped link. Cells sometimes carry a leading template
    before the link (e.g. "{{flagicon|LIE}} [[FC Vaduz]]" -- a national-team
    eligibility flag on some rosters), so this scans for the first link
    rather than assuming the cell starts with one."""
    links = wtp.parse(cell).wikilinks
    if not links:
        return None
    link = links[0]
    target = link.target.strip()
    text = (link.text or link.target).strip()
    return target, text


def find_club_roster(wikitext: str) -> list[tuple[str, str]] | None:
    """Locate the current-season club-roster table in a league page's
    wikitext and return [(display_name, article_title), ...] in table
    order, or None if no such table is found. Looks for the first wikitable
    (in document order) with a header cell literally "club" or "team" --
    validated against every LEAGUE_PAGES entry to reliably be the roster
    table specifically (season pages consistently place it before any
    "Managerial changes"/"Top scorers"/etc. table that also happens to have
    a "Team" column).

    Dedupes by wikilink target within the table: MediaWiki's rowspan means a
    club with more than one attribute in a given row (e.g. two stadiums --
    Argentina's Central Córdoba (SdE)) produces a second row that's *missing*
    the rowspanned club cell, so data(span=True) (which resolves span
    correctly) yields the same club-cell content twice, not a second club.
    Without this dedup, that second row would be misread as a distinct club.
    """
    parsed = wtp.parse(wikitext)
    for table in parsed.tables:
        try:
            data = table.data(span=True)
        except Exception:
            continue
        if not data:
            continue
        header = [(cell or "").strip().lower() for cell in data[0]]
        col_idx = next((i for i, name in enumerate(header) if name in ("club", "team")), None)
        if col_idx is None:
            continue

        roster: list[tuple[str, str]] = []
        seen_targets: set[str] = set()
        for row in data[1:]:
            cell = row[col_idx]
            if not cell:
                continue
            link = _first_wikilink(cell)
            if link is None:
                continue
            target, text = link
            if target in seen_targets:
                continue
            seen_targets.add(target)
            roster.append((text, target))
        return roster
    return None


def _first_list_item(value: str) -> str:
    """First non-blank line of a wrapper template's argument value, with any
    leading "*" bullet marker stripped -- handles both a plain single-value
    wrapper (one line, no bullets: this just returns it) and a bulleted-list
    wrapper like {{Plainlist|\\n*item one\\n*item two}} (returns "item one")."""
    for line in value.split("\n"):
        line = line.strip().lstrip("*").strip()
        if line:
            return line
    return value.strip()


def _unwrap_passthrough_templates(parsed: wtp.WikiText) -> None:
    """Mutating one Template node's .string shifts every other node's
    cached span in the same parse tree -- continuing to iterate
    parsed.templates (a snapshot taken before any mutation) after that first
    mutation raises wikitextparser.DeadIndexError on the next stale node
    (hit in practice on fields with more than one wrapper template, e.g.
    Real Madrid's nickname field, which has three separate {{Nowrap|...}}
    entries). Re-querying parsed.templates fresh after every single mutation
    avoids operating on any stale node."""
    while True:
        target = next(
            (
                t
                for t in parsed.templates
                if t.name.strip().lower() in _PASSTHROUGH_TEMPLATES and t.arguments
            ),
            None,
        )
        if target is None:
            return
        target.string = _first_list_item(target.arguments[0].value)


def _clean_nickname(raw: str) -> str:
    """Best-effort single nickname from an infobox's raw |nickname= wikitext
    value. Real values are messy: multiple alternatives separated by <br>,
    formatting-wrapper templates ({{Nowrap|...}}), citations, and
    parenthetical glosses ("Los Blancos (The Whites)", "the Blaugrana
    (team)"). Takes only the first alternative, reduced to plain text --
    good enough for a password-wordlist nickname token. Empty string (never
    fabricated) if nothing usable survives."""
    if not raw or not raw.strip():
        return ""
    text = _REF_RE.sub("", raw)
    parsed = wtp.parse(text)
    _unwrap_passthrough_templates(parsed)
    text = str(parsed)
    first_segment = re.split(r"<br\s*/?>|\n", text, flags=re.IGNORECASE)[0]
    plain = wtp.parse(first_segment).plain_text().strip()
    plain = re.sub(r"\s*\([^)]*\)\s*$", "", plain).strip(" ,;")
    plain = re.split(r"\s+or\s+", plain, maxsplit=1)[0].strip()
    return plain


def _clean_founded(raw: str) -> str:
    """Founding year from an infobox's raw |founded= wikitext value. Real
    values are almost always a {{Start date and age|...}}/{{Start date|...}}
    template -- the year is always its first *positional* argument
    regardless of where the named |df=yes flag sits. Falls back to a bare
    4-digit-year regex over the plain text for the rare article that states
    it in prose instead (e.g. "founded in 1899"). Empty string (never
    fabricated) if neither finds one."""
    if not raw or not raw.strip():
        return ""
    text = _REF_RE.sub("", raw)
    parsed = wtp.parse(text)
    for template in parsed.templates:
        if template.name.strip().lower().startswith("start date"):
            positional = [arg for arg in template.arguments if arg.positional]
            if positional:
                candidate = positional[0].value.strip()
                if candidate.isdigit() and len(candidate) == 4:
                    return candidate
    match = _YEAR_RE.search(wtp.parse(text).plain_text())
    return match.group(1) if match else ""


_INFOBOX_TEMPLATE_NAMES = {"infobox football club", "football club infobox"}


def fetch_club_infobox(article_title: str) -> tuple[dict | None, str | None]:
    """Fetch one club's own Wikipedia article and pull founded/nickname out
    of its {{Infobox football club}} template (or its "Football club
    infobox" word-order alias -- both are real, in-use template names on
    English Wikipedia, confirmed on SV Elversberg and Çorum F.K. after an
    earlier run flagged them as missing the infobox entirely; matching only
    the more common ordering silently lost real clubs that happened to use
    the alias). Returns (None, reason) if the article couldn't be fetched,
    or has neither template at all -- the adapted safety net (in place of
    the old strSport == "Soccer" check against TheSportsDB): a linked
    article that isn't actually a football club's page (redirect oddity,
    disambiguation, wrong sport) is skipped and counted, never silently kept
    as a blank/wrong entry."""
    wikitext, error = _fetch_wikitext(article_title)
    if error:
        return None, error
    parsed = wtp.parse(wikitext)
    for template in parsed.templates:
        if template.name.strip().lower() in _INFOBOX_TEMPLATE_NAMES:
            founded = ""
            nickname = ""
            for arg in template.arguments:
                key = arg.name.strip().lower()
                if key == "founded":
                    founded = _clean_founded(arg.value)
                elif key in ("nickname", "nicknames"):
                    nickname = _clean_nickname(arg.value)
            return {"founded": founded, "nickname": nickname}, None
    return None, f"{article_title}: no 'Infobox football club' template found"


def _process_team(
    display_name: str,
    infobox: dict,
    merged: dict,
    seed_keys: set[str],
    seen_this_run: set[str],
    stats: dict,
) -> None:
    """Apply one fetched club to `merged`/`stats` in place -- fills gaps in
    a hand-seeded entry without overwriting its curated fields, skips an
    already-seen duplicate (a club appearing in more than one league is not
    expected here, but stays defensive), or adds a brand-new entry."""
    stats["teams_seen"] += 1

    nickname = infobox["nickname"]
    if nickname and not _is_latin_script(nickname):
        stats["non_latin_nicknames_filtered"] += 1
        nickname = ""

    key = _slug(display_name)
    fetched_entry = {"nickname": nickname, "founded": infobox["founded"], "notable": []}

    if key in seed_keys:
        existing = merged[key]
        # Fill gaps only -- never overwrite a non-empty hand-curated
        # field with a fetched value.
        if not existing.get("nickname") and fetched_entry["nickname"]:
            existing["nickname"] = fetched_entry["nickname"]
        if not existing.get("founded") and fetched_entry["founded"]:
            existing["founded"] = fetched_entry["founded"]
        if existing.get("notable"):
            stats["notable_preserved"].add(key)
        stats["teams_merged_into_seed"] += 1
    elif key in seen_this_run:
        stats["duplicate_teams_skipped"] += 1
    else:
        merged[key] = fetched_entry
        seen_this_run.add(key)
        stats["teams_added"] += 1


def build_teams() -> tuple[dict, dict]:
    """Fetches every league in LEAGUE_PAGES and merges the results into
    SEED_TEAMS. Returns (merged_teams, stats) for the run summary."""
    merged = {key: dict(value) for key, value in SEED_TEAMS.items()}
    seed_keys = set(SEED_TEAMS.keys())
    seen_this_run: set[str] = set()

    stats = {
        "leagues_ok": 0,
        "leagues_failed": [],
        "leagues_short": [],  # [(league, expected, actual), ...]
        "teams_seen": 0,
        "teams_added": 0,
        "teams_merged_into_seed": 0,
        "duplicate_teams_skipped": 0,
        "notable_preserved": set(),
        "non_latin_nicknames_filtered": 0,
        "non_football_articles_skipped": [],
    }

    request_count = 0

    def _pace() -> None:
        nonlocal request_count
        if request_count > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        request_count += 1

    for league, page_title in LEAGUE_PAGES.items():
        _pace()
        wikitext, error = _fetch_wikitext(page_title)
        if error:
            stats["leagues_failed"].append(error)
            continue

        roster = find_club_roster(wikitext)
        if roster is None:
            stats["leagues_failed"].append(
                f"{league}: no club-roster table found on {page_title!r}"
            )
            continue

        expected = EXPECTED_TEAM_COUNTS.get(league)
        if expected is not None and len(roster) != expected:
            stats["leagues_short"].append((league, expected, len(roster)))

        stats["leagues_ok"] += 1

        for display_name, article_title in roster:
            _pace()
            infobox, error = fetch_club_infobox(article_title)
            if error:
                stats["non_football_articles_skipped"].append(error)
                continue
            _process_team(display_name, infobox, merged, seed_keys, seen_this_run, stats)

    return merged, stats


def main() -> None:
    merged, stats = build_teams()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {OUTPUT_PATH}")

    print(f"\nLeagues fetched OK: {stats['leagues_ok']}/{len(LEAGUE_PAGES)}")
    if stats["leagues_failed"]:
        print("Leagues failed:")
        for failure in stats["leagues_failed"]:
            print(f"  {failure}")

    print("\nCompleteness check (parsed roster vs. known real league size):")
    if stats["leagues_short"]:
        for league, expected, actual in stats["leagues_short"]:
            print(f"  MISMATCH: {league} -- expected {expected}, got {actual}")
    else:
        print("  All leagues matched their expected team count.")

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
    print(f"Non-Latin-script nicknames filtered out: {stats['non_latin_nicknames_filtered']}")
    if stats["non_football_articles_skipped"]:
        print(
            "Articles skipped (no 'Infobox football club' template / fetch error): "
            f"{len(stats['non_football_articles_skipped'])}"
        )
        for reason in stats["non_football_articles_skipped"]:
            print(f"  {reason}")


if __name__ == "__main__":
    main()
