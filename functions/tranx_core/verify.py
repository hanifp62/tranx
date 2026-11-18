"""Runtime integrity check for unpacked jptrans vendor files."""

from __future__ import annotations

import hashlib
from pathlib import Path

EXPECTED_VENDOR_FILES = 52


def default_vendor_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "vendor"


def verify_vendor_manifest(vendor_dir: Path | None = None) -> str:
    """Verify every file in MANIFEST.sha256 and return a short manifest digest."""
    vdir = (vendor_dir or default_vendor_dir()).resolve()
    manifest_path = vdir / "MANIFEST.sha256"
    if not manifest_path.is_file():
        raise RuntimeError(f"Missing vendor manifest: {manifest_path}")

    raw_manifest = manifest_path.read_bytes()
    entries: list[tuple[str, str]] = []
    for line in raw_manifest.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        digest, rel = stripped.split("  ", 1)
        entries.append((rel, digest))

    if len(entries) != EXPECTED_VENDOR_FILES:
        raise RuntimeError(
            f"Expected {EXPECTED_VENDOR_FILES} vendor files, found {len(entries)}"
        )

    for rel, expected_sha in entries:
        target = vdir / rel
        if not target.is_file():
            raise RuntimeError(f"Missing vendor file: {rel}")
        actual_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise RuntimeError(f"Corrupted vendor file: {rel}")

    return hashlib.sha256(raw_manifest).hexdigest()[:16]
