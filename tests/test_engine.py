from wordgen.core.engine import generate
from wordgen.core.tokens import Token


def test_date_variants():
    tokens = [Token(type="date", value="1998-06-12")]
    results = list(generate(tokens))

    expected = {"1998", "98", "0612", "1206", "12061998", "06121998", "061298", "120698"}
    assert expected.issubset(set(results)), f"Missing variants. Got: {results}"


def test_name_expansion():
    tokens = [Token(type="name", value="alice")]
    results = list(generate(tokens))
    assert "alice" in results
    assert "ALICE" in results
    assert "Alice" in results
    assert "4lice" in results
    assert "alice123" in results


def test_dedup():
    # Two identical date tokens should not produce duplicate candidates.
    tokens = [
        Token(type="date", value="2000-01-01"),
        Token(type="date", value="2000-01-01"),
    ]
    results = list(generate(tokens))
    assert len(results) == len(set(results))


def test_multiple_tokens():
    tokens = [
        Token(type="name", value="bob"),
        Token(type="date", value="19850304"),
    ]
    results = list(generate(tokens))
    assert "bob" in results
    assert "1985" in results
    assert "85" in results
    assert "0304" in results


def test_standalone_penalty_repro_case():
    """Real bug repro, kept as a permanent regression guard: this exact
    7-token set at `medium` size used to put bare, un-personalized
    standalone candidates from place/partner/custom tokens ("london1",
    "sunshine1", "emily1", "liverpool1") in the top 10, crowding out the
    only two candidates actually built from the target's own facts
    (Michael1995, Buddy1995) -- for a *targeted* tool, that defeats the
    purpose (see ranker.py's STANDALONE_PENALTY and CLAUDE.md). This is the
    core "does personalization actually dominate the top of the list"
    property of the whole tool, not just a ranker implementation detail --
    hence a dedicated engine-level (not ranker-unit-level) test, exercising
    the real combiner -> ranker pipeline end to end."""
    tokens = [
        Token(type="name", value="Michael"),
        Token(type="date", value="1995-03-15"),
        Token(type="pet", value="Buddy"),
        Token(type="place", value="Liverpool"),
        Token(type="place", value="London"),
        Token(type="partner", value="Emily"),
        Token(type="custom", value="Sunshine"),
    ]
    results = generate(tokens, size="medium")

    top_10 = results[:10]
    generic_standalone_fillers = {
        "london1", "sunshine1", "emily1", "liverpool1",
        "london123", "sunshine123", "emily123", "liverpool123",
        "london", "sunshine", "emily", "liverpool",
    }
    leaked = [value for value in top_10 if value in generic_standalone_fillers]
    assert not leaked, (
        f"generic place/partner/custom standalone candidates leaked into the "
        f"top 10, crowding out personalized combos: {leaked}. Top 10: {top_10}"
    )

    # The two real combos (built from the target's actual name+date and
    # pet+date facts) must both be near the top, not just "not at the very
    # bottom".
    assert results.index("Michael1995") < 10
    assert results.index("Buddy1995") < 10
