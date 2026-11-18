#!/usr/bin/env python3
"""Verify translator.py purity, vendor MANIFEST.sha256, 32/32 selftests, AST import boundaries, secrets, and em-dash hygiene."""

from __future__ import annotations

import ast
import hashlib
import io
import re
import sys
import unittest
from pathlib import Path

EXPECTED_TRANSLATOR_MD5 = "60b276c23e67e756a4c959b3861f759a"
EXPECTED_FILE_COUNT = 52
EXPECTED_SELFTESTS = 32

SECRET_PATTERNS = (
    re.compile(r"AIzaSy[0-9A-Za-z_-]{33}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
)


def check_translator_md5(root: Path) -> None:
    src = root / "translator.py"
    if not src.is_file():
        raise AssertionError("translator.py is missing from repository root")
    digest = hashlib.md5(src.read_bytes()).hexdigest()
    if digest != EXPECTED_TRANSLATOR_MD5:
        raise AssertionError(
            f"translator.py MD5 altered: {digest} != {EXPECTED_TRANSLATOR_MD5}"
        )


def check_vendor_manifest(root: Path) -> None:
    vendor_dir = root / "functions" / "vendor"
    manifest_path = vendor_dir / "MANIFEST.sha256"
    if not manifest_path.is_file():
        raise AssertionError("functions/vendor/MANIFEST.sha256 is missing; run tools/vendor_jptrans.py")

    entries: dict[str, str] = {}
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        digest, rel = line.split("  ", 1)
        entries[rel] = digest

    if len(entries) != EXPECTED_FILE_COUNT:
        raise AssertionError(
            f"MANIFEST.sha256 has {len(entries)} entries, expected {EXPECTED_FILE_COUNT}"
        )

    actual_files = {
        p.relative_to(vendor_dir).as_posix()
        for p in (vendor_dir / "jptrans").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(".pyc")
    }
    if actual_files != set(entries.keys()):
        missing = sorted(set(entries.keys()) - actual_files)
        extra = sorted(actual_files - set(entries.keys()))
        raise AssertionError(f"Vendor file set mismatch: missing={missing}, extra={extra}")

    for rel, expected_sha in entries.items():
        actual_sha = hashlib.sha256((vendor_dir / rel).read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise AssertionError(f"SHA-256 mismatch in vendor/{rel}")


def check_jptrans_selftests(root: Path) -> int:
    vendor_dir = str((root / "functions" / "vendor").resolve())
    if vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)
    from jptrans import selftest  # type: ignore[import-not-found]

    suite = unittest.defaultTestLoader.loadTestsFromModule(selftest)
    buf = io.StringIO()
    result = unittest.TextTestRunner(stream=buf, verbosity=1).run(suite)
    if not result.wasSuccessful() or result.testsRun != EXPECTED_SELFTESTS:
        raise AssertionError(
            f"jptrans selftests failed ({result.testsRun} run):\n{buf.getvalue()}"
        )
    return result.testsRun


def check_ast_import_boundaries(root: Path) -> int:
    fn_dir = root / "functions"
    if not fn_dir.is_dir():
        return 0
    scanned = 0
    for py_file in fn_dir.rglob("*.py"):
        if any(part in ("vendor", "venv", ".venv", "tests", "__pycache__") for part in py_file.parts):
            continue
        scanned += 1
        rel = py_file.relative_to(fn_dir)
        in_tranx_core = rel.parts[0] == "tranx_core"
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            imported = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name
                    if not in_tranx_core and (imported == "jptrans" or imported.startswith("jptrans.")):
                        raise AssertionError(
                            f"Forbidden jptrans import outside tranx_core in {rel}: {imported}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module
                if not in_tranx_core and (imported == "jptrans" or imported.startswith("jptrans.")):
                    raise AssertionError(
                        f"Forbidden jptrans import outside tranx_core in {rel}: {imported}"
                    )
    return scanned


def check_hygiene_and_secrets(root: Path) -> None:
    targets: list[Path] = []
    for sub in ("functions", "web/src", "tools"):
        base = root / sub
        if base.exists():
            for p in base.rglob("*"):
                if p.is_file() and not any(
                    skip in p.parts for skip in ("vendor", "venv", ".venv", "node_modules", "__pycache__")
                ):
                    if p.suffix in {".py", ".ts", ".tsx", ".css", ".html", ".json", ".md"}:
                        targets.append(p)

    for p in targets:
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pat in SECRET_PATTERNS:
            # Skip regex definitions inside verify_integrity.py itself
            if p.name == "verify_integrity.py":
                continue
            if pat.search(text):
                raise AssertionError(f"Potential secret detected in {p.relative_to(root)}")
        if p.suffix in {".ts", ".tsx", ".css", ".html"} and "\u2014" in text:
            raise AssertionError(f"Forbidden em-dash (U+2014) in UI file {p.relative_to(root)}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    check_translator_md5(root)
    check_vendor_manifest(root)
    tests_run = check_jptrans_selftests(root)
    scanned_py = check_ast_import_boundaries(root)
    check_hygiene_and_secrets(root)
    print(
        f"INTEGRITY OK: translator.py md5={EXPECTED_TRANSLATOR_MD5}, "
        f"vendor={EXPECTED_FILE_COUNT} files, selftests={tests_run}/{EXPECTED_SELFTESTS} OK, "
        f"ast_checked={scanned_py} files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
