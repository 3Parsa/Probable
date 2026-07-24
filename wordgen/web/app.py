"""FastAPI web GUI: same engine.generate() the CLI uses, over HTTP.

No generation logic lives here -- this is a thin form-in/JSON-or-file-out
wrapper around wordgen.core.engine.generate, per CLAUDE.md's "no duplicated
logic" rule.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from wordgen.core.engine import generate as engine_generate
from wordgen.core.tokens import Token

app = FastAPI(title="probable")

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

_PREVIEW_LIMIT = 50

# Form field name -> Token type it expands into.
_FIELDS = {
    "names": "name",
    "dates": "date",
    "pets": "pet",
    "teams": "team",
    "places": "place",
    "partner": "partner",
    "custom": "custom",
}

_SPLIT_RE = re.compile(r"[,\n]")


def _split_field(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in _SPLIT_RE.split(value) if item.strip()]


def build_tokens(
    names: Optional[str] = None,
    dates: Optional[str] = None,
    pets: Optional[str] = None,
    teams: Optional[str] = None,
    places: Optional[str] = None,
    partner: Optional[str] = None,
    custom: Optional[str] = None,
) -> list[Token]:
    """Turn comma/newline-separated form text into the same Token list the
    YAML-driven CLI path builds."""
    raw = {
        "names": names,
        "dates": dates,
        "pets": pets,
        "teams": teams,
        "places": places,
        "partner": partner,
        "custom": custom,
    }
    tokens: list[Token] = []
    for field, token_type in _FIELDS.items():
        for value in _split_field(raw[field]):
            tokens.append(Token(type=token_type, value=value))
    return tokens


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.post("/generate")
def generate(
    names: Optional[str] = Form(None),
    dates: Optional[str] = Form(None),
    pets: Optional[str] = Form(None),
    teams: Optional[str] = Form(None),
    places: Optional[str] = Form(None),
    partner: Optional[str] = Form(None),
    custom: Optional[str] = Form(None),
    size: str = Form("medium"),
) -> dict:
    tokens = build_tokens(names, dates, pets, teams, places, partner, custom)
    candidates = engine_generate(tokens, size=size)
    return {"preview": candidates[:_PREVIEW_LIMIT], "total": len(candidates)}


@app.get("/download")
def download(
    names: Optional[str] = None,
    dates: Optional[str] = None,
    pets: Optional[str] = None,
    teams: Optional[str] = None,
    places: Optional[str] = None,
    partner: Optional[str] = None,
    custom: Optional[str] = None,
    size: str = "large",
) -> PlainTextResponse:
    tokens = build_tokens(names, dates, pets, teams, places, partner, custom)
    candidates = engine_generate(tokens, size=size)
    text = "\n".join(candidates) + ("\n" if candidates else "")
    return PlainTextResponse(
        text,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=candidates.txt"},
    )
