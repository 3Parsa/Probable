from fastapi.testclient import TestClient

from wordgen.cli.main import load_tokens
from wordgen.core.engine import generate as engine_generate
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


def test_download_returns_full_text_file():
    response = client.get("/download", params=_FORM_DATA)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]

    lines = [line for line in response.text.splitlines() if line]
    assert lines, "expected non-empty downloaded wordlist"
    assert "ahmet1998" in lines
