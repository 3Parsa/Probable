from wordgen.core.engine import generate
from wordgen.core.tokens import Token


def test_small_returns_at_most_fifty():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998-06-12")]
    results = generate(tokens, size="small")
    assert len(results) <= 50


def test_medium_returns_at_most_five_hundred():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998-06-12")]
    results = generate(tokens, size="medium")
    assert len(results) <= 500


def test_large_returns_full_pool_when_smaller_than_limits():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998-06-12")]
    small = generate(tokens, size="small")
    medium = generate(tokens, size="medium")
    large = generate(tokens, size="large")

    assert len(large) >= len(medium) >= len(small)
    assert len(small) <= 50
    assert len(medium) <= 500
