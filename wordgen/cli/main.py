"""probable CLI: generate ranked candidate wordlists, and evaluate them against a hash."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml

from wordgen.core.engine import generate as engine_generate
from wordgen.core.tokens import Token

app = typer.Typer(name="probable", help="Generate and evaluate targeted password candidate lists.")

# Maps YAML top-level list keys to the Token type they expand into.
_LIST_FIELDS = {
    "names": "name",
    "dates": "date",
    "pets": "pet",
    "teams": "team",
    "places": "place",
    "custom": "custom",
}

_SUPPORTED_ALGOS = {"sha256", "sha1", "md5"}


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def load_tokens(data: dict) -> list[Token]:
    """Convert a parsed YAML input document into a flat list of Token objects."""
    tokens: list[Token] = []

    target = data.get("target")
    if target:
        tokens.append(Token(type="name", value=str(target)))

    for field, token_type in _LIST_FIELDS.items():
        for value in _as_list(data.get(field)):
            tokens.append(Token(type=token_type, value=value))

    for value in _as_list(data.get("partner")):
        tokens.append(Token(type="partner", value=value))

    return tokens


@app.command()
def generate(
    input_file: Path = typer.Argument(..., exists=True, readable=True, help="YAML input file."),
    size: str = typer.Option("medium", "--size", help="Output tier: small, medium, or large."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Write ranked candidates to this file."),
    stdout: bool = typer.Option(False, "--stdout", help="Also print to stdout even if -o is set."),
) -> None:
    """Read a YAML target profile and generate a ranked candidate wordlist."""
    if size not in {"small", "medium", "large"}:
        typer.secho(f"Invalid --size: {size!r} (expected small, medium, or large)", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    with input_file.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    tokens = load_tokens(data)
    candidates = engine_generate(tokens, size=size)
    text = "\n".join(candidates)

    if output:
        output.write_text(text + ("\n" if text else ""), encoding="utf-8")
        if stdout:
            typer.echo(text)
    else:
        typer.echo(text)


@app.command()
def eval(
    wordlist: Path = typer.Option(..., "--wordlist", exists=True, readable=True, help="Candidate file, one per line."),
    hash: str = typer.Option(..., "--hash", help="Target hash to search for."),
    algo: str = typer.Option("sha256", "--algo", help="Hash algorithm: sha256, sha1, or md5."),
) -> None:
    """Hash each candidate in a wordlist and report whether/where it matches a target hash."""
    if algo not in _SUPPORTED_ALGOS:
        typer.secho(
            f"Invalid --algo: {algo!r} (expected one of {sorted(_SUPPORTED_ALGOS)})",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    target = hash.strip().lower()
    candidates = [line.strip() for line in wordlist.read_text(encoding="utf-8").splitlines() if line.strip()]
    total = len(candidates)

    for position, candidate in enumerate(candidates, start=1):
        digest = hashlib.new(algo, candidate.encode("utf-8")).hexdigest()
        if digest == target:
            typer.echo(f"cracked at position {position} of {total}")
            return

    typer.echo(f"not found in {total} candidates")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
