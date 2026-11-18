"""Penulis keluaran: memilih format dari argumen eksplisit atau sufiks berkas.

Tiap penulis adalah fungsi murni ``TranslatedDocument -> str``, sehingga server
web bisa merender di memori dan ``write_output`` hanya menulis ke disk.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from ..config import REGISTERED_OUTPUT_FORMATS
from ..errors import ConfigError, JptransError
from ..models import TranslatedDocument
from .html import render_html
from .subtitle import render_ass, render_srt, render_vtt
from .text import render_json, render_md, render_txt

logger = logging.getLogger(__name__)

RENDERERS: dict[str, Callable[[TranslatedDocument], str]] = {
    "html": render_html,
    "txt": render_txt,
    "md": render_md,
    "json": render_json,
    "srt": render_srt,
    "vtt": render_vtt,
    "ass": render_ass,
}
SUFFIX_FORMATS = {
    ".html": "html",
    ".htm": "html",
    ".txt": "txt",
    ".md": "md",
    ".json": "json",
    ".srt": "srt",
    ".vtt": "vtt",
    ".ass": "ass",
    ".ssa": "ass",
}
CONTENT_TYPES: dict[str, str] = {
    "html": "text/html",
    "txt": "text/plain",
    "md": "text/markdown",
    "json": "application/json",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "ass": "text/plain",
}


def output_format(out: Path, fmt: str | None = None) -> str:
    """Tentukan format keluaran: argumen ``fmt`` menang atas sufiks ``out``."""
    chosen = fmt or SUFFIX_FORMATS.get(Path(out).suffix.lower())
    if chosen not in RENDERERS:
        supported = ", ".join(RENDERERS)
        raise ConfigError(
            f"format keluaran {chosen or Path(out).suffix!r} tidak dikenal; "
            f"pilih: {supported}"
        )
    return chosen


def render_output(
    result: TranslatedDocument, fmt: str, *, bilingual: bool = False
) -> str:
    """Bangun isi keluaran sebagai string tanpa menyentuh disk."""
    if fmt not in RENDERERS:
        raise ConfigError(
            f"format keluaran {fmt!r} tidak dikenal; pilih: {', '.join(RENDERERS)}"
        )
    if fmt == "txt":
        return render_txt(result, bilingual=bilingual)
    return RENDERERS[fmt](result)


def write_output(
    result: TranslatedDocument,
    out: Path,
    fmt: str | None = None,
    *,
    bilingual: bool = False,
) -> Path:
    """Tulis hasil terjemahan ke berkas UTF-8 dengan baris baru ``\\n``."""
    out = Path(out)
    content = render_output(
        result, output_format(out, fmt), bilingual=bilingual
    )
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise JptransError(
            f"tidak bisa menulis {out}: {exc.strerror or exc}"
        ) from exc
    logger.info("keluaran ditulis ke %s (%d karakter)", out, len(content))
    return out


def register_writer(
    fmt: str,
    renderer: Callable[[TranslatedDocument], str],
    *,
    suffixes: Sequence[str] = (),
    content_type: str = "text/plain",
) -> None:
    """Daftarkan penulis keluaran kustom ke ``RENDERERS``, ``SUFFIX_FORMATS``, dan ``Config``."""
    clean = fmt.strip().lower().lstrip(".")
    if not clean or not callable(renderer):
        raise ConfigError(f"penulis atau nama format tidak sah: {fmt!r}")
    RENDERERS[clean] = renderer
    CONTENT_TYPES[clean] = content_type
    for raw_sfx in suffixes or (f".{clean}",):
        sfx = raw_sfx.strip().lower()
        SUFFIX_FORMATS[sfx if sfx.startswith(".") else f".{sfx}"] = clean
    if clean not in REGISTERED_OUTPUT_FORMATS:
        REGISTERED_OUTPUT_FORMATS.append(clean)
    logger.debug("penulis kustom terdaftar: %s", clean)


__all__ = [
    "CONTENT_TYPES",
    "RENDERERS",
    "SUFFIX_FORMATS",
    "output_format",
    "render_output",
    "register_writer",
    "write_output",
]
