import shutil
import subprocess
from pathlib import Path

import pytest

from wordgen.eval.harness import (
    HashcatExecutionError,
    HashcatNotFoundError,
    compute_metrics,
    evaluate,
    run_hashcat,
)

HASHCAT_AVAILABLE = shutil.which("hashcat") is not None


def test_run_hashcat_raises_clear_error_when_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _bin: None)
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text("alice\n", encoding="utf-8")
    hash_file = tmp_path / "hashes.txt"
    hash_file.write_text("deadbeef\n", encoding="utf-8")

    with pytest.raises(HashcatNotFoundError, match="hashcat"):
        run_hashcat(wordlist, hash_file, mode="0", hashcat_bin="hashcat")


def test_run_hashcat_parses_outfile(tmp_path, monkeypatch):
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text("alice\nbob123\ntarget_password\n", encoding="utf-8")
    hash_file = tmp_path / "hashes.txt"
    hash_file.write_text("deadbeefcafebabe\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda _bin: "/usr/bin/hashcat")

    def fake_run(cmd, capture_output, text, check):
        outfile = Path(cmd[cmd.index("-o") + 1])
        outfile.write_text("deadbeefcafebabe:target_password\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    cracked = run_hashcat(wordlist, hash_file, mode="0", hashcat_bin="hashcat")

    assert cracked == {"deadbeefcafebabe": "target_password"}


def test_run_hashcat_raises_on_missing_backend_instead_of_reporting_not_found(tmp_path, monkeypatch):
    """Regression test: a hash confirmed present via the hashlib path was
    reported 'not found' by --hashcat because hashcat had no usable
    OpenCL/CUDA/HIP backend (`CL_PLATFORM_NOT_FOUND_KHR`). That failure must
    surface as an error, not be silently interpreted as a clean no-match."""
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text("alice\nbob123\ntarget_password\n", encoding="utf-8")
    hash_file = tmp_path / "hashes.txt"
    hash_file.write_text("deadbeef\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda _bin: "/usr/bin/hashcat")

    def fake_run(cmd, capture_output, text, check):
        # Simulates real hashcat behavior on a system with no compute backend:
        # non-zero/negative exit status, no outfile ever written, and the
        # ATTENTION/CL_PLATFORM_NOT_FOUND_KHR message on stdout.
        return subprocess.CompletedProcess(
            cmd,
            returncode=-1,
            stdout=(
                "hashcat (v7.1.2) starting\n\n"
                "Initializing backend runtimes. Please be patient...clGetPlatformIDs(): "
                "CL_PLATFORM_NOT_FOUND_KHR\n\n"
                "ATTENTION! No OpenCL, HIP or CUDA compatible platform found.\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(HashcatExecutionError, match="backend"):
        run_hashcat(wordlist, hash_file, mode="1400", hashcat_bin="hashcat")


def test_evaluate_raises_on_backend_failure_rather_than_returning_not_found(tmp_path, monkeypatch):
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text("alice\ntarget_password\n", encoding="utf-8")
    hash_file = tmp_path / "hashes.txt"
    hash_file.write_text("deadbeef\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda _bin: "/usr/bin/hashcat")

    def fake_run(cmd, capture_output, text, check):
        return subprocess.CompletedProcess(
            cmd, returncode=-1, stdout="", stderr="clGetPlatformIDs(): CL_PLATFORM_NOT_FOUND_KHR\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(HashcatExecutionError):
        evaluate(wordlist, hash_file, mode="1400", target_hashes=["deadbeef"])


def test_compute_metrics_reports_crack_rate_and_position(tmp_path):
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text("alice\nbob123\ntarget_password\ncharlie\n", encoding="utf-8")

    cracked = {"hash1": "target_password"}
    metrics = compute_metrics(cracked, target_hashes=["hash1", "hash2"], wordlist=wordlist)

    assert metrics.total == 2
    assert metrics.cracked_count == 1
    assert metrics.crack_rate == 0.5
    assert metrics.positions["hash1"] == 3
    assert metrics.positions["hash2"] is None


def test_evaluate_end_to_end_with_mocked_subprocess(tmp_path, monkeypatch):
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text("alice\nbob123\ntarget_password\n", encoding="utf-8")
    hash_file = tmp_path / "hashes.txt"
    hash_file.write_text("hash1\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda _bin: "/usr/bin/hashcat")

    def fake_run(cmd, capture_output, text, check):
        outfile = Path(cmd[cmd.index("-o") + 1])
        outfile.write_text("hash1:target_password\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    metrics = evaluate(wordlist, hash_file, mode="0", target_hashes=["hash1"])

    assert metrics.cracked_count == 1
    assert metrics.crack_rate == 1.0
    assert metrics.positions["hash1"] == 3


@pytest.mark.skipif(not HASHCAT_AVAILABLE, reason="hashcat is not installed on this system")
def test_run_hashcat_real_binary(tmp_path):
    import hashlib

    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text("alice\nbob123\ntarget_password\n", encoding="utf-8")
    hash_file = tmp_path / "hashes.txt"
    target_hash = hashlib.sha1(b"target_password").hexdigest()
    hash_file.write_text(target_hash + "\n", encoding="utf-8")

    # mode 100 = SHA1 (raw)
    try:
        cracked = run_hashcat(wordlist, hash_file, mode="100")
    except HashcatExecutionError as exc:
        pytest.skip(f"hashcat has no usable OpenCL/CUDA/HIP backend on this system: {exc}")

    assert cracked.get(target_hash) == "target_password"
