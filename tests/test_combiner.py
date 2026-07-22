from wordgen.core.combiner import combine
from wordgen.core.rules import expand
from wordgen.core.tokens import Token


def test_name_date_produces_both_concatenation_orders():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998")]
    results = set(combine(tokens))

    assert "ahmet1998" in results
    assert "1998ahmet" in results


def test_combo_count_stays_small_not_full_cross_product():
    name_token = Token(type="name", value="ahmet")
    date_token = Token(type="date", value="1998")
    tokens = [name_token, date_token]

    results = set(combine(tokens))
    standalone = set(expand(name_token)) | set(expand(date_token))
    combos = results - standalone

    # Base-value cross (2 orders x light mangle) should be a handful, not
    # anywhere near 9 name variants x 16 date variants = 144+.
    assert 0 < len(combos) <= 12


def test_no_junk_from_crossing_expanded_variants():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998")]
    results = set(combine(tokens))

    assert "ahmet!1998" not in results
    assert "4hmet1998" not in results
    assert "ahmet1231998" not in results


def test_pet_date_produces_both_concatenation_orders():
    tokens = [Token(type="pet", value="rex"), Token(type="date", value="2010")]
    results = set(combine(tokens))

    assert "rex2010" in results
    assert "2010rex" in results


def test_name_team_produces_both_concatenation_orders():
    tokens = [Token(type="name", value="ahmet"), Token(type="team", value="fenerbahce")]
    results = set(combine(tokens))

    assert "ahmetfenerbahce" in results
    assert "fenerbahceahmet" in results


def test_untouched_types_still_pass_through_individually():
    tokens = [Token(type="team", value="Lakers")]
    results = list(combine(tokens))

    # Solo token, no pairing partner -> just its own expansion, no crossing.
    assert results == ["Lakers"]


def test_no_cross_for_unlisted_type_pairs():
    # place+partner isn't in the combo list, so no concatenations should appear.
    tokens = [Token(type="place", value="paris"), Token(type="partner", value="mia")]
    results = set(combine(tokens))

    assert "parismia" not in results
    assert "miaparis" not in results


def test_iso_date_combos_use_realistic_formats_not_raw_hyphenated_value():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998-06-12")]
    results = set(combine(tokens))

    assert "ahmet1998-06-12" not in results
    assert "1998-06-12ahmet" not in results
    assert not any("-" in candidate for candidate in results)

    assert "ahmet1998" in results
    assert "ahmet12061998" in results
