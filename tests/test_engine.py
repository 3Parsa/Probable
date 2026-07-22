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
