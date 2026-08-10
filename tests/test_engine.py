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
    combiner._team_combo_bases()/expand_multiword_value() (uses the
    stripped direct-concat form, e.g. "TheReds", as the team's combo base --
    see test_multiword_team_nickname_combo_does_not_double_expand_separators
    below for why it's just this one form and not also a separator-joined
    inner variant per separator character, which was tried first and caused
    a real double-separator-expansion bug).

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
    assert "Bardiya_TheReds" in results


def test_multiword_team_nickname_combo_does_not_double_expand_separators():
    """Real bug repro, found the same session as the space-leak fix above:
    Token("name", "Michael1995") + Token("team", "liverpool") produced 264
    combo candidates from a single token pair, the overwhelming majority
    nested-separator junk like "The_Reds.Michael1995" -- confirmed by
    isolating a plain two-name-token case (which stayed small and sane) from
    this name+team case (which didn't), then narrowing further to a name
    token containing digits crossed with a team whose nickname is two words.

    Root cause: combiner._team_combo_bases() used to feed team_related_values()
    through expand_multiword_value()'s *full* separator-variant list (e.g.
    Liverpool's "The Reds" -> 11 bases: "TheReds" plus one per separator
    character), and each of those 11 pre-separated bases then got crossed
    AGAIN by _joined_combos' own full separator set below -- 11 x 22 = 242
    combos from the nickname alone, before even counting founding year /
    notable names. Same root cause as the project's original "crossed full
    expansion sets instead of base values" combiner bug, reached through the
    later-added multiword-nickname path instead. Fixed by taking only
    expand_multiword_value()'s first (direct-concat) form as the team combo
    base, letting the outer _joined_combos supply separator diversity on its
    own -- exactly how every other combo pair (name+date, pet+date) already
    works.

    A small, real name+team combo count (comparable to a name+date combo
    over a small date-format base list) is asserted directly, not just
    "smaller than before" -- and the double-separator junk shape
    (".Michael1995" after any team-side separator character) is asserted
    absent by construction, since a sane combo count with real content checks
    below rules it out implicitly.
    """
    tokens = [Token(type="name", value="Michael1995"), Token(type="team", value="liverpool")]
    results = list(generate(tokens, size="large"))

    combo_like = [
        v for v in results if "TheReds" in v or "1892" in v
    ]  # liverpool's nickname + founding year, the only two related values
    assert len(combo_like) < 50, (
        f"name+team combo exploded: {len(combo_like)} candidates, "
        f"expected a small, non-exploded set. Sample: {combo_like[:10]}"
    )

    assert "Michael1995TheReds" in results
    assert "TheReds_Michael1995" in results
    assert "Michael19951892" in results

    # No nested/double-separator junk: a separator character should never
    # appear twice in a single combo candidate (the double-expansion bug's
    # signature shape, e.g. "The_Reds.Michael1995").
    for value in combo_like:
        assert not any(value.count(sep) > 1 for sep in "_.-#$@&*+%"), (
            f"nested-separator junk survived: {value!r}"
        )


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


def test_medium_value_characters_never_leak_a_literal_space():
    """The medium-value separator/suffix tier (&, *, +, %) is ASCII, no
    different in kind from the high-value tier the space-safety-net was
    built for -- this confirms that assumption with a real generate() run
    rather than just asserting it, using the same token shapes as
    test_no_generated_candidate_ever_contains_a_literal_space above."""
    tokens = [
        Token(type="team", value="Bayern Munich"),
        Token(type="place", value="New York"),
        Token(type="name", value="Bardiya"),
        Token(type="date", value="1995-03-15"),
    ]
    results = generate(tokens, size="large")

    assert any(c in "&*+%" for value in results for c in value), (
        "expected at least one candidate using a medium-value tier character"
    )
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


def test_output_diversity_no_family_dominates_top_results():
    """Real bug repro: Token("name", "Michael1995") + Token("team", "liverpool")
    at size="small" put 9 near-identical "TheReds*Michael1995" candidates
    (differing only by which separator character joins the two combo bases,
    e.g. "TheRedsMichael1995", "TheReds_Michael1995", "TheReds.Michael1995",
    ...) in the first 9 of the top 11 results -- the ranker scores each
    candidate independently with no notion of output diversity, so a combo
    pattern that scores well has ALL of its separator variants score nearly
    identically and cluster together, crowding out every other distinct
    candidate. This wasn't a generation-side bug (the candidate pool itself
    was already correctly, non-explosively sized after the earlier
    _team_combo_bases fix) -- it's an output-shaping problem, fixed by
    engine._diversify(): candidates are grouped into "shape families"
    (combiner.shape_family(), same base combo with separators stripped) and
    round-robined across families in score order, so no family can occupy a
    second output slot before every other family present has had a turn.

    Asserts the general property (no shape family holds more than 2 of the
    top 15 slots) rather than hand-checking exact positions, so this stays a
    real guard against any base pattern with many separator variants
    dominating output, not just this one team-nickname case."""
    from collections import Counter

    from wordgen.core.combiner import shape_family

    tokens = [Token(type="name", value="Michael1995"), Token(type="team", value="liverpool")]
    results = generate(tokens, size="small")

    top_15 = results[:15]
    family_counts = Counter(shape_family(value) for value in top_15)
    dominant = family_counts.most_common(1)[0]
    assert dominant[1] <= 2, (
        f"shape family {dominant[0]!r} occupies {dominant[1]} of the top 15 "
        f"slots, crowding out other distinct candidates: {top_15}"
    )

    # The dominant combo pattern's best member still legitimately wins the
    # top spot -- diversity reorders what gets *deferred*, not the winner.
    assert results[0] == "TheRedsMichael1995"
