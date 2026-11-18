#!/usr/bin/env python3
"""Unpack translator.py into functions/vendor/jptrans/ and generate MANIFEST.sha256."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

EXPECTED_TRANSLATOR_MD5 = "60b276c23e67e756a4c959b3861f759a"
EXPECTED_FILE_COUNT = 52


def unpack_vendor(repo_root: Path | None = None) -> Path:
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    translator_path = root / "translator.py"
    if not translator_path.is_file():
        raise FileNotFoundError(f"translator.py not found at {translator_path}")

    actual_md5 = hashlib.md5(translator_path.read_bytes()).hexdigest()
    if actual_md5 != EXPECTED_TRANSLATOR_MD5:
        raise RuntimeError(
            f"translator.py MD5 mismatch: expected {EXPECTED_TRANSLATOR_MD5}, got {actual_md5}"
        )

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import translator  # type: ignore[import-not-found]

    vendor_dir = root / "functions" / "vendor"
    jptrans_dir = vendor_dir / "jptrans"
    if jptrans_dir.exists():
        shutil.rmtree(jptrans_dir)
    vendor_dir.mkdir(parents=True, exist_ok=True)

    written = translator.ekstrak_paket(vendor_dir, timpa=True)
    if len(written) != EXPECTED_FILE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_FILE_COUNT} unpacked files, got {len(written)}"
        )

    lines: list[str] = []
    for path in sorted(written, key=lambda p: p.relative_to(vendor_dir).as_posix()):
        rel = path.relative_to(vendor_dir).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}")

    manifest_path = vendor_dir / "MANIFEST.sha256"
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return manifest_path


def main() -> int:
    manifest = unpack_vendor()
    print(f"Unpacked {EXPECTED_FILE_COUNT} files and wrote {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
