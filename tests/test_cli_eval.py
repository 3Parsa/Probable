import hashlib

from typer.testing import CliRunner

from wordgen.cli.main import app

runner = CliRunner()


def test_eval_finds_known_hash_at_correct_position(tmp_path):
    candidates = ["alice", "bob123", "target_password", "charlie"]
    wordlist = tmp_path / "candidates.txt"
    wordlist.write_text("\n".join(candidates) + "\n", encoding="utf-8")

    target_hash = hashlib.sha256(b"target_password").hexdigest()

    result = runner.invoke(app, ["eval", "--wordlist", str(wordlist), "--hash", target_hash])

    assert result.exit_code == 0
    assert result.stdout.strip() == "cracked at position 3 of 4"


def test_eval_reports_not_found_for_wrong_hash(tmp_path):
    candidates = ["alice", "bob123", "charlie"]
    wordlist = tmp_path / "candidates.txt"
    wordlist.write_text("\n".join(candidates) + "\n", encoding="utf-8")

    wrong_hash = hashlib.sha256(b"nowhere_in_the_list").hexdigest()

    result = runner.invoke(app, ["eval", "--wordlist", str(wordlist), "--hash", wrong_hash])

    assert result.exit_code == 0
    assert result.stdout.strip() == "not found in 3 candidates"
