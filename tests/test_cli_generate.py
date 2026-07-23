from typer.testing import CliRunner

from wordgen.cli.main import app, load_tokens
from wordgen.core.tokens import Token

runner = CliRunner()


def test_load_tokens_round_trips_yaml_fields():
    data = {
        "target": "Ahmet",
        "names": ["Ahmet1998"],
        "dates": ["1998-06-12"],
        "pets": ["Boncuk"],
        "teams": ["Galatasaray"],
        "places": ["Istanbul"],
        "partner": "Ayse",
        "custom": ["go-eagles"],
    }

    tokens = load_tokens(data)

    assert Token(type="name", value="Ahmet") in tokens
    assert Token(type="name", value="Ahmet1998") in tokens
    assert Token(type="date", value="1998-06-12") in tokens
    assert Token(type="pet", value="Boncuk") in tokens
    assert Token(type="team", value="Galatasaray") in tokens
    assert Token(type="place", value="Istanbul") in tokens
    assert Token(type="partner", value="Ayse") in tokens
    assert Token(type="custom", value="go-eagles") in tokens


def test_generate_command_produces_non_empty_output(tmp_path):
    input_file = tmp_path / "profile.yaml"
    input_file.write_text(
        "target: Ahmet\n"
        "names:\n"
        "  - Ahmet1998\n"
        "dates:\n"
        "  - 1998-06-12\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["generate", str(input_file), "--size", "small"])

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines, "expected non-empty candidate output"
    assert "ahmet1998" in lines


def test_generate_command_writes_to_output_file(tmp_path):
    input_file = tmp_path / "profile.yaml"
    input_file.write_text("names:\n  - bob\n", encoding="utf-8")
    output_file = tmp_path / "out.txt"

    result = runner.invoke(app, ["generate", str(input_file), "-o", str(output_file)])

    assert result.exit_code == 0
    assert result.stdout == ""
    content = output_file.read_text(encoding="utf-8")
    assert "bob" in content.splitlines()
