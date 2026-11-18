"""Pembaca dokumen masukan: memilih pengurai menurut sufiks atau format eksplisit.

Setiap pembaca mengembalikan ``models.Document`` sehingga pipa terjemahan tidak
bergantung pada format sumber (TXT, Markdown, Aozora Bunko, HTML, EPUB, SRT,
WebVTT, ASS/SSA, maupun JSON halaman komik).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ..errors import ConfigError, InputError
from ..models import Document
from .aozora import front_matter_title, is_aozora, parse_aozora
from .epub import read_epub, read_html
from .pages import read_pages
from .subtitle import read_ass, read_srt, read_vtt
from .txt import normalize_newlines, read_text_file, read_txt, text_to_document

logger = logging.getLogger(__name__)

Reader = Callable[[Path, str | None, str | None], Document]


def _read_txt_or_aozora(
    path: Path, title: str | None, encoding: str | None
) -> Document:
    text = read_text_file(path, encoding)
    doc = _parse_plain_or_aozora(
        text, title or front_matter_title(text) or path.stem
    )
    doc.source_path = str(path)
    return doc


def _read_aozora_forced(
    path: Path, title: str | None, encoding: str | None
) -> Document:
    text = read_text_file(path, encoding)
    doc = parse_aozora(text, title or front_matter_title(text) or path.stem)
    doc.source_path = str(path)
    return doc


def _read_epub(path: Path, title: str | None, _encoding: str | None) -> Document:
    return read_epub(path, title)


def _read_pages(
    path: Path, title: str | None, _encoding: str | None
) -> Document:
    return read_pages(path, title)


READERS: dict[str, Reader] = {
    ".txt": _read_txt_or_aozora,
    ".md": read_txt,
    ".html": read_html,
    ".htm": read_html,
    ".xhtml": read_html,
    ".epub": _read_epub,
    ".srt": read_srt,
    ".vtt": read_vtt,
    ".ass": read_ass,
    ".ssa": read_ass,
    ".json": _read_pages,
}

INPUT_FORMAT_READERS: dict[str, Reader] = {
    "auto": _read_txt_or_aozora,
    "txt": read_txt,
    "aozora": _read_aozora_forced,
    "md": read_txt,
    "html": read_html,
    "epub": _read_epub,
    "srt": read_srt,
    "vtt": read_vtt,
    "ass": read_ass,
    "pages": _read_pages,
}


def read_document(
    path: Path,
    *,
    title: str | None = None,
    encoding: str | None = None,
    input_format: str | None = None,
) -> Document:
    """Baca berkas masukan menurut ``input_format`` eksplisit atau sufiks berkas."""
    path = Path(path)
    if input_format and input_format != "auto":
        reader = INPUT_FORMAT_READERS.get(input_format.lower())
        if reader is None:
            choices = ", ".join(sorted(INPUT_FORMAT_READERS))
            raise InputError(
                f"format masukan {input_format!r} tidak dikenal; pilih: {choices}"
            )
    else:
        reader = READERS.get(path.suffix.lower())
        if reader is None:
            supported = ", ".join(sorted(READERS))
            suffix = path.suffix or "(tanpa sufiks)"
            raise InputError(
                f"format {suffix} tidak didukung; pilih: {supported}"
            )
    if not path.is_file():
        raise InputError(f"berkas tidak ditemukan: {path}")
    doc = reader(path, title, encoding)
    logger.info(
        "dibaca %s: %d paragraf, format %s",
        path.name,
        len(doc.paragraphs),
        doc.fmt,
    )
    return doc


def read_text(text: str, title: str) -> Document:
    """Ubah teks tempelan menjadi ``Document`` (mendeteksi Aozora bila cocok)."""
    return _parse_plain_or_aozora(
        normalize_newlines(text.removeprefix("\ufeff")), title
    )


def _parse_plain_or_aozora(text: str, title: str) -> Document:
    if is_aozora(text):
        return parse_aozora(text, title)
    return text_to_document(text, title)


def register_reader(
    suffix: str, reader: Reader, *, input_format: str | None = None
) -> None:
    """Daftarkan pembaca format masukan kustom ke ``READERS`` dan ``INPUT_FORMAT_READERS``."""
    clean = suffix.strip().lower()
    if not clean.startswith("."):
        clean = f".{clean}"
    if clean == "." or not callable(reader):
        raise ConfigError(f"pembaca atau sufiks tidak sah: {suffix!r}")
    READERS[clean] = reader
    fmt_name = (input_format or clean.lstrip(".")).strip().lower()
    if fmt_name:
        INPUT_FORMAT_READERS[fmt_name] = reader
    logger.debug("pembaca kustom terdaftar: %s (%s)", clean, fmt_name)


__all__ = [
    "INPUT_FORMAT_READERS",
    "READERS",
    "Reader",
    "read_document",
    "read_text",
    "register_reader",
]
