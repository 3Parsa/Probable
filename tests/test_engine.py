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


def test_multiword_team_nickname_never_yields_a_literal_space():
    """Real bug repro: crossing a name token with a team whose nickname is
    two words (e.g. Liverpool's "The Reds") used to yield the raw,
    space-containing nickname as a combo base directly -- producing
    candidates like "BardiyaThe Reds" with a literal, unescaped space, which
    nobody puts in a real password. Fixed in rules.expand_team() (strips a
    multi-word nickname before yielding it standalone) and
    combiner._team_combo_bases()/expand_multiword_value() (builds a
    stripped variant plus one separator-joined variant per separator
    character for the combo case, e.g. "TheReds"/"The_Reds"/"The.Reds"/...,
    mirroring the same "direct-concat + per-separator variant" shape used
    for every other combo pair).

    Uses Liverpool specifically (a single-word team name) rather than a
    multi-word one (e.g. "Bayern Munich") so this test isolates the
    nickname bug -- expand_team()'s first yield is always the raw operator-
    typed team name verbatim (a separate, pre-existing, intentionally
    tested contract, see test_arbitrary_new_team_resolves_through_
    expand_team), which would itself contain a space for a multi-word team
    name and isn't what this test is checking.
    """
    tokens = [Token(type="name", value="Bardiya"), Token(type="team", value="Liverpool")]
    results = generate(tokens, size="large")

    assert not any(" " in value for value in results), (
        f"raw space leaked into a generated candidate: "
        f"{[v for v in results if ' ' in v]}"
    )

    # The requested direct-concat and separator-joined forms are both
    # actually present, not just "no spaces anywhere".
    assert "BardiyaTheReds" in results
    assert "Bardiya_The_Reds" in results


def test_no_generated_candidate_ever_contains_a_literal_space():
    """Firm, permanent invariant (engine._normalize_spaces): no candidate
    generate() returns should ever contain a literal space character --
    virtually no real system accepts spaces in passwords. This is
    deliberately broader than the team-nickname regression test above: it
    exercises raw operator-typed multi-word *input* directly (a team name
    typed as "Bayern Munich" rather than a single-word one, plus a
    multi-word place value), which used to echo straight through with the
    space intact as a standalone candidate via expand()'s "yield the raw
    value" step -- a different leak path than the nickname one, not fixed
    by the nickname-specific change alone.

    This test is intentionally written as a blanket assertion over the
    *entire* output, not a check for a few specific known-bad strings, so
    it stays a real guard even against a space-leak nobody has thought of
    yet -- any future token type or rule that introduces a new way for a
    raw multi-word value to reach a candidate unmangled would still be
    caught here, because _normalize_spaces sits in the one place every
    candidate is guaranteed to pass through (right before ranking),
    regardless of which source produced it.
    """
    tokens = [
        Token(type="team", value="Bayern Munich"),
        Token(type="place", value="New York"),
        Token(type="partner", value="Mary Jane"),
        Token(type="name", value="Bardiya"),
        Token(type="date", value="1995-03-15"),
    ]
    results = generate(tokens, size="large")

    assert results, "expected a non-empty candidate list for this token set"
    leaked = [value for value in results if " " in value]
    assert not leaked, f"literal space leaked into generated candidates: {leaked}"


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
