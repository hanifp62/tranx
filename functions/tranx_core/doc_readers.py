"""Custom PDF and DOCX readers with archive zip-bomb, path-traversal, and XXE protections."""

from __future__ import annotations

import zipfile
from pathlib import Path

import docx
from jptrans.errors import InputError
from jptrans.models import Document, Paragraph
from jptrans.readers import register_reader
from pypdf import PdfReader

MAX_ARCHIVE_ENTRIES = 2000
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024  # 250 MB
MAX_COMPRESSION_RATIO = 120.0
MAX_PDF_PAGES = 500

_REGISTERED = False


def inspect_zip_archive(path: Path) -> None:
    """Validate ZIP-based documents (.epub, .docx) against zip bombs, traversal, and XXE."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise InputError(
                    f"Arsip memuat terlalu banyak berkas ({len(infos)} > {MAX_ARCHIVE_ENTRIES})"
                )
            total_uncompressed = 0
            total_compressed = 0
            for info in infos:
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise InputError(f"Jalur berkas arsip tidak aman: {info.filename!r}")
                total_uncompressed += max(info.file_size, 0)
                total_compressed += max(info.compress_size, 1)
                if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                    raise InputError("Ukuran dekompresi berkas melampaui batas aman 250 MB")
                if name.lower().endswith((".xml", ".rels", ".opf", ".xhtml", ".ncx")):
                    head = zf.open(info).read(4096)
                    if b"<!ENTITY" in head.upper():
                        raise InputError("Entitas XML eksternal (XXE) ditolak demi keamanan")
            if total_compressed > 0 and (total_uncompressed / total_compressed) > MAX_COMPRESSION_RATIO:
                raise InputError("Rasio kompresi arsip tidak wajar (potensi zip bomb)")
    except zipfile.BadZipFile as exc:
        raise InputError("Berkas arsip rusak atau bukan format ZIP yang sah") from exc


def read_pdf_document(
    path: Path, title: str | None = None, _encoding: str | None = None
) -> Document:
    path = Path(path)
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise InputError(f"PDF tidak dapat dibaca: {exc}") from exc

    if reader.is_encrypted:
        raise InputError("Berkas PDF terkunci sandi atau ber-DRM")

    if len(reader.pages) > MAX_PDF_PAGES:
        raise InputError(
            f"PDF memiliki {len(reader.pages)} halaman (batas maksimum {MAX_PDF_PAGES} halaman)"
        )

    paragraphs: list[Paragraph] = []
    for page_num, page in enumerate(reader.pages, start=1):
        raw_text = (page.extract_text() or "").strip()
        if not raw_text:
            continue
        blocks = [blk.strip() for blk in raw_text.replace("\r\n", "\n").split("\n\n") if blk.strip()]
        if not blocks:
            blocks = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for blk in blocks:
            paragraphs.append(Paragraph(text=blk, meta={"page": page_num}))

    doc_title = (title or path.stem or "Dokumen PDF").strip()
    return Document(
        title=doc_title,
        paragraphs=paragraphs,
        source_path=str(path),
        fmt="pdf",
    )


def read_docx_document(
    path: Path, title: str | None = None, _encoding: str | None = None
) -> Document:
    path = Path(path)
    inspect_zip_archive(path)
    try:
        word_doc = docx.Document(str(path))
    except Exception as exc:
        raise InputError(f"Berkas DOCX tidak dapat dibaca: {exc}") from exc

    paragraphs: list[Paragraph] = []
    for para in word_doc.paragraphs:
        txt = para.text.strip()
        if not txt:
            continue
        style_name = (para.style.name if para.style and para.style.name else "").lower()
        kind = "heading" if style_name.startswith("heading") or style_name == "title" else "text"
        paragraphs.append(Paragraph(text=txt, kind=kind))

    for table in word_doc.tables:
        for row in table.rows:
            seen_cells: set[int] = set()
            for cell in row.cells:
                if id(cell._tc) in seen_cells:
                    continue
                seen_cells.add(id(cell._tc))
                cell_text = cell.text.strip()
                if cell_text:
                    paragraphs.append(Paragraph(text=cell_text, meta={"table": True}))

    doc_title = (title or path.stem or "Dokumen DOCX").strip()
    return Document(
        title=doc_title,
        paragraphs=paragraphs,
        source_path=str(path),
        fmt="docx",
    )


def register_custom_readers() -> None:
    """Register .pdf and .docx readers into jptrans idempotently."""
    global _REGISTERED
    if _REGISTERED:
        return
    register_reader(".pdf", read_pdf_document, input_format="pdf")
    register_reader(".docx", read_docx_document, input_format="docx")
    _REGISTERED = True
