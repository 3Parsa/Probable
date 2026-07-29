from fastapi.testclient import TestClient

from wordgen.cli.main import load_tokens
from wordgen.core.engine import generate as engine_generate
from wordgen.core.tokens import Token
from wordgen.web.app import app

client = TestClient(app)

_FORM_DATA = {
    "names": "Ahmet1998",
    "dates": "1998-06-12",
    "size": "small",
}


def test_generate_matches_cli_for_same_input():
    response = client.post("/generate", data=_FORM_DATA)
    assert response.status_code == 200

    body = response.json()
    assert body["preview"], "expected non-empty ranked preview"
    assert body["total"] > 0
    assert len(body["preview"]) <= 50

    expected = engine_generate(
        load_tokens({"names": ["Ahmet1998"], "dates": ["1998-06-12"]}), size="small"
    )
    assert body["preview"] == expected
    assert body["total"] == len(expected)


def test_generate_produces_team_derived_combos_via_web_form():
    # Regression test: previously untested path -- submitting a "teams" form
    # field via the web GUI (as opposed to the CLI's YAML "teams: [...]")
    # must reach engine_generate() as a proper Token(type="team", ...), which
    # means nickname/founding-year/notable expansions AND name+team combo
    # candidates should show up in the response, exactly like the CLI.
    response = client.post(
        "/generate",
        data={"names": "Ahmet", "teams": "Galatasaray", "size": "large"},
    )
    assert response.status_code == 200
    body = response.json()

    expected = engine_generate(
        [Token(type="name", value="Ahmet"), Token(type="team", value="Galatasaray")],
        size="large",
    )
    assert body["preview"] == expected[:50]
    assert body["total"] == len(expected)

    # Standalone team-token expansions (data/teams.json's galatasaray entry).
    assert "Cimbom" in expected
    assert "1905" in expected
    assert "Drogba" in expected
    assert "Hagi" in expected
    # An actual name+team combo, not just the standalone team expansions.
    assert any("Cimbom" in c and c != "Cimbom" for c in expected)


def test_generate_maps_every_form_field_to_its_token_type():
    # Guards against the same class of bug (a form field silently not
    # reaching Token()) for every other field, not just teams -- pets,
    # places, partner, and custom each get a value that can only appear in
    # the output if build_tokens() actually mapped that field through.
    response = client.post(
        "/generate",
        data={
            "names": "Ahmet",
            "dates": "1998-06-12",
            "pets": "Boncuk",
            "teams": "Galatasaray",
            "places": "Istanbul",
            "partner": "Ayse",
            "custom": "go-eagles",
            "size": "large",
        },
    )
    assert response.status_code == 200
    body = response.json()

    expected = engine_generate(
        [
            Token(type="name", value="Ahmet"),
            Token(type="date", value="1998-06-12"),
            Token(type="pet", value="Boncuk"),
            Token(type="team", value="Galatasaray"),
            Token(type="place", value="Istanbul"),
            Token(type="partner", value="Ayse"),
            Token(type="custom", value="go-eagles"),
        ],
        size="large",
    )
    assert body["preview"] == expected[:50]
    assert body["total"] == len(expected)

    assert "boncuk" in expected  # pets
    assert "Cimbom" in expected  # teams
    assert "istanbul" in expected  # places
    assert "ayse" in expected  # partner
    assert "go-eagles" in expected  # custom


def test_download_returns_full_text_file():
    response = client.get("/download", params=_FORM_DATA)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]

    lines = [line for line in response.text.splitlines() if line]
    assert lines, "expected non-empty downloaded wordlist"
    assert "ahmet1998" in lines
