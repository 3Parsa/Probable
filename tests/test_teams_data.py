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
    # name (e.g. "Beşiktaş", "Deportivo Alavés") silently failed to match and
    # fell back to raw passthrough with no nickname/founded expansion.
    teams = _load_teams()
    assert team_lookup_key("Beşiktaş") in teams
    assert team_lookup_key("Deportivo Alavés") in teams

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
