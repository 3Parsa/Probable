from wordgen.core.combiner import combine
from wordgen.core.rules import expand
from wordgen.core.tokens import Token


def _values(tokens):
    return {candidate.value for candidate in combine(tokens)}


def _combo_values(tokens):
    return {candidate.value for candidate in combine(tokens) if candidate.is_combo}


def _standalone_values(tokens):
    return {candidate.value for candidate in combine(tokens) if not candidate.is_combo}


def test_name_date_produces_both_concatenation_orders():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998")]
    results = _values(tokens)

    assert "ahmet1998" in results
    assert "1998ahmet" in results


def test_combo_count_stays_small_not_full_cross_product():
    name_token = Token(type="name", value="ahmet")
    date_token = Token(type="date", value="1998")
    tokens = [name_token, date_token]

    combos = _combo_values(tokens)

    # Base-value cross (direct concat + separator-joined, 2 orders each, x
    # light mangle) should stay a bounded handful, not anywhere near 9 name
    # variants x 16 date variants = 144+. 1 base each x (2 direct + 10
    # separators x 2 orders) x up to 2 mangle variants = up to 44.
    assert 0 < len(combos) <= 44


def test_no_junk_from_crossing_expanded_variants():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998")]
    results = _values(tokens)

    assert "ahmet!1998" not in results
    assert "4hmet1998" not in results
    assert "ahmet1231998" not in results


def test_pet_date_produces_both_concatenation_orders():
    tokens = [Token(type="pet", value="rex"), Token(type="date", value="2010")]
    results = _values(tokens)

    assert "rex2010" in results
    assert "2010rex" in results


def test_name_team_produces_both_concatenation_orders():
    tokens = [Token(type="name", value="ahmet"), Token(type="team", value="fenerbahce")]
    results = _values(tokens)

    assert "ahmetFener" in results
    assert "ahmet1907" in results
    assert "ahmetfenerbahce" not in results
    assert "fenerbahceahmet" not in results


def test_untouched_types_still_pass_through_individually():
    tokens = [Token(type="team", value="Lakers")]
    results = list(combine(tokens))

    # Solo token, no pairing partner -> just its own expansion, no crossing.
    assert [c.value for c in results] == ["Lakers"]
    assert all(not c.is_combo for c in results)


def test_no_cross_for_unlisted_type_pairs():
    # place+partner isn't in the combo list, so no concatenations should appear.
    tokens = [Token(type="place", value="paris"), Token(type="partner", value="mia")]
    results = _values(tokens)

    assert "parismia" not in results
    assert "miaparis" not in results


def test_iso_date_combos_use_realistic_formats_not_raw_hyphenated_value():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998-06-12")]
    results = _values(tokens)

    assert "ahmet1998-06-12" not in results
    assert "1998-06-12ahmet" not in results
    # The raw ISO/hyphenated date string itself should never appear as a combo
    # base - but a "-" can still legitimately appear as a *separator* joining
    # a realistic date base (e.g. "ahmet-1998"), which is a different thing.
    assert not any("06-12" in candidate for candidate in results)

    assert "ahmet1998" in results
    assert "ahmet12061998" in results
    assert "ahmet-1998" in results


def test_separator_joined_combos_appear_for_name_date():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1999")]
    results = _combo_values(tokens)

    for sep in ["_", ".", "-", "#", "$", "@"]:
        assert f"ahmet{sep}1999" in results
        assert f"1999{sep}ahmet" in results

    # direct concatenation combos still present alongside the separated ones
    assert "ahmet1999" in results


def test_separator_joined_combos_appear_for_name_team():
    tokens = [Token(type="name", value="ahmet"), Token(type="team", value="fenerbahce")]
    results = _combo_values(tokens)

    assert "ahmet_1907" in results
    assert "ahmet_Fener" in results
    assert "1907_ahmet" in results


def test_medium_value_separator_joined_combos_appear_for_name_date():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1999")]
    results = _combo_values(tokens)

    for sep in ["&", "*", "+", "%"]:
        assert f"ahmet{sep}1999" in results
        assert f"1999{sep}ahmet" in results

    # direct concatenation combos still present alongside the separated ones
    assert "ahmet1999" in results


def test_medium_value_separator_joined_combos_appear_for_name_team():
    tokens = [Token(type="name", value="ahmet"), Token(type="team", value="fenerbahce")]
    results = _combo_values(tokens)

    assert "ahmet&1907" in results
    assert "ahmet*Fener" in results
    assert "1907+ahmet" in results


def test_combo_flag_distinguishes_cross_products_from_standalone_expansions():
    tokens = [Token(type="name", value="ahmet"), Token(type="date", value="1998")]

    standalone = _standalone_values(tokens)
    combos = _combo_values(tokens)

    # Single-token expansions (each token's own case/leet/date-format variants)
    # must never be tagged as combos.
    assert "ahmet" in standalone
    assert "1998" in standalone
    assert not standalone & combos

    # Cross-token concatenations must be tagged as combos.
    assert "ahmet1998" in combos
    assert "1998ahmet" in combos
