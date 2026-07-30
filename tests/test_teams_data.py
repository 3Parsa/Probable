"""Validates wordgen/data/teams.json itself (schema + hand-seed survival),
as distinct from tests/test_rules.py's behavioral tests of expand_team().
Exercises the real, checked-in data file -- as produced by
scripts/fetch_teams.py -- not synthetic fixtures.
"""

import importlib.util
import json
import unicodedata
from pathlib import Path

from wordgen.core.rules import expand_team, team_lookup_key
from wordgen.core.tokens import Token

_TEAMS_PATH = Path(__file__).resolve().parent.parent / "wordgen" / "data" / "teams.json"
_FETCH_TEAMS_PATH = Path(__file__).resolve().parent.parent / "scripts" / "fetch_teams.py"

# The 5 originally hand-curated entries (before scripts/fetch_teams.py
# existed) and their manually-researched notable-player names, which the
# fetch script must never overwrite on merge.
_HAND_SEEDED_NOTABLE = {
    "fenerbahce": ["Alex", "Aykut"],
    "galatasaray": ["Drogba", "Hagi"],
    "besiktas": ["Necati"],
    "barcelona": ["Messi", "Xavi"],
    "real madrid": ["Ronaldo", "Zidane"],
}


def _load_teams() -> dict:
    with _TEAMS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _first_new_team(teams: dict) -> str:
    name = next((n for n in teams if n not in _HAND_SEEDED_NOTABLE), None)
    assert name is not None, "expected at least one API-fetched team beyond the hand seed"
    return name


def test_teams_file_has_grown_well_beyond_the_original_five_seeds():
    teams = _load_teams()
    assert len(teams) >= 100, (
        "expected scripts/fetch_teams.py to have broadened teams.json to "
        "roughly 100-200 teams, not just the original 5 hand-seeded entries"
    )


def test_teams_file_matches_expected_schema():
    teams = _load_teams()
    assert teams, "teams.json should not be empty"

    for name, entry in teams.items():
        assert isinstance(name, str) and name == team_lookup_key(name), (
            f"team key {name!r} must already be in canonical lookup-key form "
            "(lowercase, diacritics stripped, whitespace collapsed) -- "
            "otherwise expand_team's own normalization would never match it"
        )
        assert isinstance(entry, dict)
        assert set(entry.keys()) == {"nickname", "founded", "notable"}
        assert isinstance(entry["nickname"], str)
        assert isinstance(entry["founded"], str)
        assert isinstance(entry["notable"], list)
        assert all(isinstance(n, str) for n in entry["notable"])


def test_hand_curated_notable_names_survived_the_fetch_merge():
    teams = _load_teams()
    for name, expected_notable in _HAND_SEEDED_NOTABLE.items():
        assert name in teams, f"hand-seeded team {name!r} missing from teams.json"
        assert teams[name]["notable"] == expected_notable, (
            f"{name!r}'s manually-curated notable names must survive the "
            "API merge unchanged"
        )


def test_no_non_latin_script_content_in_teams_file():
    # Policy: non-Latin-script alternate names (e.g. a Cyrillic
    # strTeamAlternate) are filtered out at fetch time (scripts/fetch_teams.py
    # _is_latin_script/_nickname_from), not carried through to runtime --
    # rules.py's case/leet/suffix mangling only handles Latin letters, so a
    # non-Latin nickname would otherwise reach expand_team() as a dead
    # candidate: yielded raw, never mangled, contributing nothing.
    teams = _load_teams()
    for name, entry in teams.items():
        for field in ("nickname", *entry["notable"]):
            for ch in field:
                if ch.isalpha():
                    assert unicodedata.name(ch, "").startswith("LATIN"), (
                        f"{name!r} has non-Latin-script content {field!r} -- "
                        "should have been filtered out by fetch_teams.py"
                    )


def test_no_non_football_teams_in_teams_file():
    # Regression test: "Scottish Premiership" is an ambiguous league name on
    # TheSportsDB -- it resolved to the Scottish Rugby Premiership, not the
    # Scottish football top flight, so teams.json briefly picked up rugby
    # clubs (Heriots Rugby Club, Jed-Forest, Marr, Musselburgh, Selkirk, ...).
    # Fixed by pointing fetch_teams.py's LEAGUES at the unambiguous "Scottish
    # Premier League" name, plus an explicit strSport == "Soccer" filter in
    # build_teams() as a safety net independent of getting every league name
    # right. This denylist guards against that exact regression reappearing.
    teams = _load_teams()
    known_non_football_clubs = {
        "heriots rugby club",
        "jed-forest",
        "marr",
        "musselburgh",
        "selkirk",
        "currie",
        "edinburgh academicals",
        "glasgow hawks",
        "glasgow hutchesons aloysians",
        "hawick",
    }
    present = known_non_football_clubs & set(teams)
    assert not present, f"non-football (rugby) teams leaked into teams.json: {present}"

    # And the football teams the corrected league name should have pulled in
    # are actually present.
    assert "aberdeen" in teams
    assert "celtic" in teams


def test_premier_league_big_six_all_present():
    # Regression test for a real data-completeness bug, originally against
    # TheSportsDB: search_all_teams.php's free-tier bulk per-league fetch
    # was capped at ~10 results per league, returned alphabetically --
    # confirmed directly against the raw API (10/10 English Premier League
    # results were "Arsenal" through "Fulham", none past F). For a ~20-team
    # league, this silently truncated away every club sorting into the back
    # half of the alphabet with no error at all -- Arsenal/Chelsea made it
    # into teams.json while Liverpool, both Manchester clubs, and Tottenham
    # -- some of the league's most recognizable, highest-personalization-
    # value clubs -- were silently missing. A per-club patch fixed that one
    # gap, but the cap itself was a hard free-tier limit with no workaround,
    # which is why scripts/fetch_teams.py has since been rebuilt entirely on
    # Wikipedia's complete, uncapped league-club-list pages instead (see
    # CLAUDE.md). This remains the strongest sanity check for EPL
    # completeness going forward regardless of data source -- if this ever
    # regresses, some kind of silent truncation is back.
    teams = _load_teams()
    big_six = {
        "arsenal",
        "chelsea",
        "liverpool",
        "manchester united",
        "manchester city",
        "tottenham hotspur",
    }
    missing = big_six - set(teams)
    assert not missing, f"Premier League 'big six' missing from teams.json: {missing}"


# Full current-season (2026-27) rosters for the top 5 major leagues, each
# individually captured from scripts/fetch_teams.py's own
# find_club_roster()/_slug() against the live Wikipedia pages when this test
# was written (not hand-typed guesses) and cross-checked against the real
# league sizes in scripts/fetch_teams.py's EXPECTED_TEAM_COUNTS (20/20/18/
# 20/18). Exact-set assertions, not just "at least N teams" -- the whole
# point of these is to catch a *partial* roster (any kind of silent
# truncation, alphabetical-cap or otherwise) the way the old TheSportsDB bug
# would have kept passing a loose ">= N" check. Will need updating by hand
# each time scripts/fetch_teams.py is re-run against a new season
# (promotions/relegations change league membership every year).
_FULL_LEAGUE_ROSTERS = {
    "English Premier League": {
        "arsenal", "aston villa", "bournemouth", "brentford",
        "brighton & hove albion", "chelsea", "coventry city",
        "crystal palace", "everton", "fulham", "hull city", "ipswich town",
        "leeds united", "liverpool", "manchester city", "manchester united",
        "newcastle united", "nottingham forest", "sunderland",
        "tottenham hotspur",
    },
    "Spanish La Liga": {
        "alaves", "athletic bilbao", "atletico madrid", "barcelona",
        "celta vigo", "deportivo a coruna", "elche", "espanyol", "getafe",
        "levante", "malaga", "osasuna", "racing santander",
        "rayo vallecano", "real betis", "real madrid", "real sociedad",
        "sevilla", "valencia", "villarreal",
    },
    "German Bundesliga": {
        "1. fc koln", "bayer leverkusen", "bayern munich",
        "borussia dortmund", "borussia monchengladbach",
        "eintracht frankfurt", "fc augsburg", "hamburger sv", "mainz 05",
        "rb leipzig", "sc freiburg", "sc paderborn", "schalke 04",
        "sv elversberg", "tsg hoffenheim", "union berlin", "vfb stuttgart",
        "werder bremen",
    },
    "Italian Serie A": {
        "ac milan", "atalanta", "bologna", "cagliari", "como", "fiorentina",
        "frosinone", "genoa", "inter milan", "juventus", "lazio", "lecce",
        "monza", "napoli", "parma", "roma", "sassuolo", "torino", "udinese",
        "venezia",
    },
    "French Ligue 1": {
        "angers", "auxerre", "brest", "le havre", "le mans", "lens",
        "lille", "lorient", "lyon", "marseille", "monaco", "nice",
        "paris fc", "paris saint-germain", "rennes", "strasbourg",
        "toulouse", "troyes",
    },
}


def test_top_five_leagues_have_their_full_current_season_roster():
    teams = _load_teams()
    for league, roster in _FULL_LEAGUE_ROSTERS.items():
        missing = roster - set(teams)
        assert not missing, f"{league}: missing from teams.json: {sorted(missing)}"


def test_api_only_teams_have_no_fabricated_notable_names():
    teams = _load_teams()
    new_team = _first_new_team(teams)
    assert teams[new_team]["notable"] == [], (
        "TheSportsDB doesn't provide notable players -- new teams must get "
        "an empty list, never fabricated names"
    )


def test_arbitrary_new_team_resolves_through_expand_team():
    teams = _load_teams()
    new_team = _first_new_team(teams)
    entry = teams[new_team]

    results = list(expand_team(Token(type="team", value=new_team)))

    assert results[0] == new_team
    if entry["nickname"]:
        assert entry["nickname"] in results
    if entry["founded"]:
        assert entry["founded"] in results
    assert len(results) == 1 + bool(entry["nickname"]) + bool(entry["founded"])


def test_diacritic_bearing_team_names_resolve_to_the_same_ascii_folded_key():
    # Regression test: teams.json's keys are ASCII-folded by
    # scripts/fetch_teams.py's _slug(), but expand_team() used to only
    # .lower() the input, so a team typed with its real, diacritic-bearing
    # name (e.g. "Beşiktaş", "Borussia Mönchengladbach") silently failed to
    # match and fell back to raw passthrough with no nickname/founded
    # expansion.
    teams = _load_teams()
    assert team_lookup_key("Beşiktaş") in teams
    assert team_lookup_key("Borussia Mönchengladbach") in teams

    results = list(expand_team(Token(type="team", value="Beşiktaş")))
    assert results == ["Beşiktaş", "Kartal", "1903", "Necati"]


def test_fetch_teams_slug_matches_runtime_lookup_key():
    # scripts/fetch_teams.py deliberately doesn't import wordgen.core.rules
    # (one-off scripts stay decoupled from the package), so its _slug() and
    # rules.team_lookup_key() are two independently-maintained implementations
    # that MUST agree byte-for-byte, or teams.json's keys (built with _slug)
    # would silently stop matching expand_team's lookups (built with
    # team_lookup_key). This test is the guardrail against that drift.
    spec = importlib.util.spec_from_file_location("fetch_teams", _FETCH_TEAMS_PATH)
    fetch_teams = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch_teams)

    sample_names = [
        "Beşiktaş",
        "Fenerbahçe",
        "Deportivo Alavés",
        "Gençlerbirliği",
        "  Real   Madrid  ",
        "ac milan",
        "AC MILAN",
        "Çorum",
    ]
    for name in sample_names:
        assert fetch_teams._slug(name) == team_lookup_key(name), (
            f"fetch_teams._slug and rules.team_lookup_key disagree on {name!r}"
        )


def test_new_team_lookup_is_case_insensitive_like_hand_seeded_teams():
    teams = _load_teams()
    new_team = _first_new_team(teams)

    lower_results = list(expand_team(Token(type="team", value=new_team)))
    upper_results = list(expand_team(Token(type="team", value=new_team.upper())))

    # First yield is always the raw input value verbatim; everything after
    # that comes from the case-insensitive teams.json lookup and must match.
    assert lower_results[1:] == upper_results[1:]
