"""Hashcat-backed eval harness: shells out to hashcat for real cracking runs,
and computes the crack-rate / crack-position metrics that prove the ranker
works (see CLAUDE.md "the demo that proves it works").

Separate from the simple hashlib single-hash check in `wordgen/cli/main.py`,
which stays as the quick no-hashcat-required path.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class HashcatNotFoundError(RuntimeError):
    """Raised when the hashcat executable can't be found on the system."""


class HashcatExecutionError(RuntimeError):
    """Raised when hashcat runs but fails outright (e.g. no usable OpenCL/CUDA/HIP
    backend) -- as opposed to running cleanly and simply not cracking anything,
    which is a legitimate result, not an error."""


# Substrings (checked case-insensitively) that indicate hashcat failed to find a
# usable compute backend, rather than genuinely exhausting the wordlist.
_BACKEND_FAILURE_MARKERS = (
    "cl_platform_not_found",
    "no opencl",
    "no devices found",
    "no such device",
    "clgetplatformids",
    "no backend devices",
)

# hashcat's own exit codes: 0 = all hashes cracked, 1 = exhausted (a legitimate
# "nothing matched"), 2 = aborted by user/runtime. Anything else is a real error.
_NON_ERROR_EXIT_CODES = {0, 1, 2}


def _check_for_backend_failure(result: subprocess.CompletedProcess) -> None:
    combined = f"{result.stdout}\n{result.stderr}"
    lowered = combined.lower()
    if any(marker in lowered for marker in _BACKEND_FAILURE_MARKERS):
        raise HashcatExecutionError(
            "hashcat ran but found no usable compute backend (OpenCL/CUDA/HIP) -- "
            "this looks like a 'not found' result but isn't. Install a backend "
            "runtime (e.g. an OpenCL ICD, PoCL for CPU-only systems, or a GPU "
            f"driver); run `hashcat -I` for diagnostics. hashcat output:\n{combined.strip()}"
        )
    if result.returncode not in _NON_ERROR_EXIT_CODES:
        raise HashcatExecutionError(
            f"hashcat exited with unexpected status {result.returncode}:\n{combined.strip()}"
        )


@dataclass
class CrackMetrics:
    """Crack rate + per-hash position in the ranked wordlist."""

    total: int
    cracked_count: int
    crack_rate: float
    positions: dict[str, int | None]  # target hash -> 1-indexed position, or None if not cracked


def _read_candidates(wordlist: Path) -> list[str]:
    return [line.strip() for line in wordlist.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_hashcat(
    wordlist: Path,
    hash_file: Path,
    mode: str,
    hashcat_bin: str = "hashcat",
    extra_args: list[str] | None = None,
) -> dict[str, str]:
    """Shell out to hashcat, running a straight dictionary attack (`-a 0`) with
    `wordlist` against the hashes in `hash_file` (one hash per line, hashcat's
    own format for the given `mode`).

    Returns {hash: plaintext} for every hash hashcat cracked. Raises
    HashcatNotFoundError -- with a clear, actionable message -- if hashcat
    isn't installed, instead of letting subprocess blow up with a raw
    FileNotFoundError/traceback. Raises HashcatExecutionError if hashcat ran
    but failed outright (e.g. no usable OpenCL/CUDA/HIP backend) -- this is
    NOT the same as a clean "nothing cracked" result, and must not be
    silently reported as one.
    """
    if shutil.which(hashcat_bin) is None:
        raise HashcatNotFoundError(
            f"hashcat executable {hashcat_bin!r} not found on PATH. "
            "Install hashcat (e.g. `pacman -S hashcat`, `apt install hashcat`, "
            "or see https://hashcat.net/hashcat/) or pass --hashcat-bin with an explicit path."
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        outfile = Path(tmp_dir) / "cracked.out"
        cmd = [
            hashcat_bin,
            "-m",
            str(mode),
            "-a",
            "0",
            str(hash_file),
            str(wordlist),
            "--potfile-disable",
            "--outfile-format=1,3",
            "-o",
            str(outfile),
            *(extra_args or []),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            # Race: `which` found it but exec failed anyway (removed, not executable, etc).
            raise HashcatNotFoundError(
                f"hashcat executable {hashcat_bin!r} could not be run: {exc}"
            ) from exc

        _check_for_backend_failure(result)

        if not outfile.exists():
            return {}

        cracked: dict[str, str] = {}
        for line in outfile.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            # --outfile-format=1,3 -> "hash[:salt]:hex_plain". rsplit (not
            # split) on the *last* colon, since a salted hash's own
            # hash[:salt] field can itself contain a colon -- splitting on
            # the first one would tear the salt off into the plaintext field.
            hash_value, hex_plaintext = line.rsplit(":", 1)
            cracked[hash_value] = bytes.fromhex(hex_plaintext).decode("utf-8")
        return cracked


def compute_metrics(cracked: dict[str, str], target_hashes: list[str], wordlist: Path) -> CrackMetrics:
    """Given hashcat's {hash: plaintext} results, work out the crack rate across
    `target_hashes` and, for each cracked hash, its position in the original
    ranked `wordlist` -- the core "prove the ranking works" metric.
    """
    candidates = _read_candidates(wordlist)
    first_position: dict[str, int] = {}
    for index, candidate in enumerate(candidates, start=1):
        first_position.setdefault(candidate, index)

    positions: dict[str, int | None] = {}
    cracked_count = 0
    for target_hash in target_hashes:
        plaintext = cracked.get(target_hash)
        if plaintext is None:
            positions[target_hash] = None
            continue
        cracked_count += 1
        positions[target_hash] = first_position.get(plaintext)

    total = len(target_hashes)
    crack_rate = cracked_count / total if total else 0.0
    return CrackMetrics(total=total, cracked_count=cracked_count, crack_rate=crack_rate, positions=positions)


def evaluate(
    wordlist: Path,
    hash_file: Path,
    mode: str,
    target_hashes: list[str],
    hashcat_bin: str = "hashcat",
    extra_args: list[str] | None = None,
) -> CrackMetrics:
    """Full harness run: hashcat attack + metrics computation."""
    cracked = run_hashcat(wordlist, hash_file, mode, hashcat_bin=hashcat_bin, extra_args=extra_args)
    return compute_metrics(cracked, target_hashes, wordlist)
