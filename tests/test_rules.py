from wordgen.core.rules import expand
from wordgen.core.tokens import Token


def test_case_transforms():
    results = set(expand(Token(type="name", value="Bob")))
    assert "bob" in results
    assert "BOB" in results
    assert "Bob" in results


def test_leet_substitutions_are_single_swap():
    results = set(expand(Token(type="name", value="alessio")))

    assert "4lessio" in results  # a -> 4
    assert "al3ssio" in results  # e -> 3
    assert "aless1o" in results  # i -> 1
    assert "alessi0" in results  # o -> 0
    assert "ale55io" in results  # s -> 5

    # never combined in one variant
    assert "4l3ss1o0" not in results


def test_new_leet_substitutions_single_swap():
    results = set(expand(Token(type="name", value="alessio")))

    assert "4lessio" in results  # existing a -> 4 still yielded
    assert "@lessio" in results  # new a -> @
    assert "ale55io" in results  # existing s -> 5 still yielded
    assert "ale$$io" in results  # new s -> $

    # still never combined with each other or with other letters' subs
    assert "@l3ss1o0" not in results
    assert "4le$$io" not in results


def test_affixes():
    results = set(expand(Token(type="name", value="bob")))
    assert "bob123" in results
    assert "bob!" in results
    assert "bob?" in results
    assert "bob1" in results


def test_new_separator_suffixes():
    results = set(expand(Token(type="name", value="bob")))
    assert "bob_" in results
    assert "bob." in results
    assert "bob-" in results
    assert "bob#" in results
    assert "bob$" in results
    assert "bob@" in results


def test_pet_place_partner_custom_use_same_rules_as_name():
    for token_type in ("pet", "place", "partner", "custom"):
        results = set(expand(Token(type=token_type, value="Rex")))
        assert "rex" in results
        assert "REX" in results
        assert "r3x" in results
        assert "rex123" in results


def test_known_team_yields_related_tokens():
    results = list(expand(Token(type="team", value="fenerbahce")))
    assert results == ["fenerbahce", "Fener", "1907", "Alex", "Aykut"]


def test_unknown_team_falls_back_to_raw():
    results = list(expand(Token(type="team", value="Lakers")))
    assert results == ["Lakers"]
