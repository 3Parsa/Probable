"""probable CLI: generate ranked candidate wordlists, and evaluate them against a hash."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer
import yaml

from wordgen.core.engine import generate as engine_generate
from wordgen.core.tokens import Token
from wordgen.eval.harness import HashcatExecutionError, HashcatNotFoundError, evaluate as harness_evaluate

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
    algo: str = typer.Option("sha256", "--algo", help="Hash algorithm: sha256, sha1, or md5. (hashlib path only)"),
    hashcat: bool = typer.Option(
        False, "--hashcat", help="Route through the hashcat-backed harness instead of the plain hashlib check."
    ),
    mode: Optional[str] = typer.Option(
        None, "--mode", help="Hashcat hash mode (e.g. 0 for MD5, 1400 for SHA256). Required with --hashcat."
    ),
    hashcat_bin: str = typer.Option("hashcat", "--hashcat-bin", help="Path to the hashcat executable."),
) -> None:
    """Hash each candidate in a wordlist and report whether/where it matches a target hash."""
    if hashcat:
        _eval_with_hashcat(wordlist, hash, mode, hashcat_bin)
        return

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


def _eval_with_hashcat(wordlist: Path, target_hash: str, mode: Optional[str], hashcat_bin: str) -> None:
    if not mode:
        typer.secho("--mode is required when --hashcat is set (e.g. --mode 1400 for SHA256).", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    target = target_hash.strip()
    with tempfile.NamedTemporaryFile("w", suffix=".hash", delete=False) as hash_file:
        hash_file.write(target + "\n")
        hash_file_path = Path(hash_file.name)

    try:
        metrics = harness_evaluate(
            wordlist=wordlist,
            hash_file=hash_file_path,
            mode=mode,
            target_hashes=[target],
            hashcat_bin=hashcat_bin,
        )
    except (HashcatNotFoundError, HashcatExecutionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    finally:
        hash_file_path.unlink(missing_ok=True)

    position = metrics.positions.get(target)
    candidate_count = sum(1 for line in wordlist.read_text(encoding="utf-8").splitlines() if line.strip())

    if position is not None:
        typer.echo(f"cracked at position {position} of {candidate_count}")
    else:
        typer.echo(f"not found in {candidate_count} candidates")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the web GUI to."),
    port: int = typer.Option(8000, "--port", help="Port to bind the web GUI to."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (development only)."),
) -> None:
    """Serve the probable web GUI (FastAPI + uvicorn) on localhost."""
    import uvicorn

    uvicorn.run("wordgen.web.app:app", host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
