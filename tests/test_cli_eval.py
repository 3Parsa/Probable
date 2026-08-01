import hashlib
import shutil
import subprocess
from pathlib import Path

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


def test_eval_hashcat_requires_mode(tmp_path):
    wordlist = tmp_path / "candidates.txt"
    wordlist.write_text("alice\n", encoding="utf-8")

    result = runner.invoke(app, ["eval", "--wordlist", str(wordlist), "--hash", "deadbeef", "--hashcat"])

    assert result.exit_code == 1
    assert "--mode is required" in result.stderr


def test_eval_hashcat_reports_clear_error_when_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _bin: None)
    wordlist = tmp_path / "candidates.txt"
    wordlist.write_text("alice\n", encoding="utf-8")

    result = runner.invoke(
        app, ["eval", "--wordlist", str(wordlist), "--hash", "deadbeef", "--hashcat", "--mode", "0"]
    )

    assert result.exit_code == 1
    assert "hashcat" in result.stderr.lower()
    assert "not found" in result.stderr.lower()


def test_eval_hashcat_reports_backend_failure_not_a_false_negative(tmp_path, monkeypatch):
    candidates = ["alice", "bob123", "target_password"]
    wordlist = tmp_path / "candidates.txt"
    wordlist.write_text("\n".join(candidates) + "\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda _bin: "/usr/bin/hashcat")

    def fake_run(cmd, capture_output, text, check):
        return subprocess.CompletedProcess(
            cmd, returncode=-1, stdout="", stderr="clGetPlatformIDs(): CL_PLATFORM_NOT_FOUND_KHR\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        app, ["eval", "--wordlist", str(wordlist), "--hash", "deadbeef", "--hashcat", "--mode", "1400"]
    )

    assert result.exit_code == 1
    assert "not found" not in result.stdout.lower()
    assert "backend" in result.stderr.lower()


def test_eval_hashcat_routes_through_harness(tmp_path, monkeypatch):
    candidates = ["alice", "bob123", "target_password"]
    wordlist = tmp_path / "candidates.txt"
    wordlist.write_text("\n".join(candidates) + "\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda _bin: "/usr/bin/hashcat")

    def fake_run(cmd, capture_output, text, check):
        # Real hashcat --outfile-format=1,3 output shape: "hash:hex_plain".
        outfile = Path(cmd[cmd.index("-o") + 1])
        outfile.write_text(f"deadbeef:{'target_password'.encode().hex()}\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        app, ["eval", "--wordlist", str(wordlist), "--hash", "deadbeef", "--hashcat", "--mode", "1400"]
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "cracked at position 3 of 3"
