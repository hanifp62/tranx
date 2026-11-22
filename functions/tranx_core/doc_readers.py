"""Custom PDF and DOCX readers with archive zip-bomb, path-traversal, and XXE protections."""

from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path
from typing import Any
from xml.parsers import expat

import docx
from jptrans.errors import InputError
from jptrans.models import Document, Paragraph
from jptrans.readers import read_document as jptrans_read_document
from jptrans.readers import register_reader
from pypdf import PdfReader

MAX_ARCHIVE_ENTRIES = 2000
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024  # 64 MB safe ceiling for 512 MB Cloud Function
MAX_SINGLE_MEMBER_BYTES = 16 * 1024 * 1024  # 16 MB per archive member (OOM defense)
MAX_COMPRESSION_RATIO = 120.0
MAX_PDF_PAGES = 500
MAX_PDF_EXTRACTED_CHARS = 2_000_000
MAX_DOCX_PARAGRAPHS = 50_000
MAX_DOCX_CHARS = 2_000_000
ALLOWED_ZIP_METHODS = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_STRICT_XML_EXTS = (".xml", ".rels", ".opf", ".ncx", ".xhtml", ".svg")
_HTML_EXTS = (".html", ".htm")
_EPUB_CONTENT_EXTS = (".xhtml", ".html", ".htm", ".ncx")
_SAFE_EPUB_DOCTYPE_PUBIDS = frozenset(
    {
        "-//W3C//DTD XHTML 1.1//EN",
        "-//W3C//DTD XHTML 1.0 Strict//EN",
        "-//W3C//DTD XHTML 1.0 Transitional//EN",
        "-//W3C//DTD XHTML 1.0 Frameset//EN",
        "-//W3C//DTD HTML 4.01//EN",
        "-//W3C//DTD HTML 4.01 Transitional//EN",
        "-//NISO//DTD ncx 2005-1//EN",
    }
)
_SAFE_EPUB_SYSTEM_PREFIXES = (
    "http://www.w3.org/TR/xhtml",
    "https://www.w3.org/TR/xhtml",
    "http://www.w3.org/TR/html4/",
    "https://www.w3.org/TR/html4/",
    "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd",
    "https://www.daisy.org/z3986/2005/ncx-2005-1.dtd",
)
_SAFE_EPUB_DOCTYPE_BYTES_RE = re.compile(
    rb"<!doctype\s+(?:html\s*>|(?:html|ncx)\s+public\s+[\"'](?:-//w3c//dtd\s+x?html\s+[0-9.]+(?:\s+(?:strict|transitional|frameset))?//en|-//niso//dtd\s+ncx\s+2005-1//en)[\"'](?:\s+[\"']https?://(?:www\.w3\.org/tr/x?html[^\"'\[\]<>]*|www\.daisy\.org/z3986/2005/ncx-2005-1\.dtd)[\"'])?\s*>)",
    re.I,
)
_DOCTYPE_SCAN_RE = re.compile(rb"<!doctype\b[^>]{0,512}>?", re.I)
_VTT_RP_LINEAR_RE = re.compile(r"<rp\b[^>]{0,128}>[^<]{0,64}</rp>", re.I)
_VTT_RP_OPEN_RE = re.compile(r"</?rp\b[^>]{0,128}>", re.I)

_REGISTERED = False


def sanitize_vtt_content(raw_text: str) -> str:
    """Linearly strip WebVTT <rp> ruby parentheses before jptrans subtitle regex parsing (ReDoS defense)."""
    if not raw_text or ("<rp" not in raw_text and "<RP" not in raw_text):
        return raw_text
    cleaned = _VTT_RP_LINEAR_RE.sub("", raw_text)
    if "<rp" in cleaned.lower():
        cleaned = _VTT_RP_OPEN_RE.sub("", cleaned)
    return cleaned


def read_document_safely(path: Path, title: str | None = None) -> Document:
    """Safely read any supported document, pre-sanitizing .vtt against catastrophic ruby <rp> backtracking."""
    path = Path(path)
    if path.suffix.lower() == ".vtt":
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        sanitized = sanitize_vtt_content(raw)
        if sanitized != raw:
            path.write_text(sanitized, encoding="utf-8")
    return jptrans_read_document(path, title=title)


def _make_strict_xml_scanner(*, allow_safe_epub_doctype: bool = False) -> Any:
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def _reject(*_args: object) -> None:
        raise InputError("Deklarasi DOCTYPE/entitas XML eksternal (XXE) ditolak demi keamanan")

    def _check_doctype(
        doctype_name: str,
        system_id: str | None,
        public_id: str | None,
        has_internal_subset: bool,
    ) -> None:
        if has_internal_subset or not allow_safe_epub_doctype:
            _reject()
        low_name = (doctype_name or "").strip().lower()
        if low_name == "html" and not system_id and not public_id:
            return
        if low_name in ("html", "ncx") and public_id in _SAFE_EPUB_DOCTYPE_PUBIDS:
            if not system_id or system_id.startswith(_SAFE_EPUB_SYSTEM_PREFIXES):
                return
        _reject()

    parser.StartDoctypeDeclHandler = _check_doctype
    parser.EntityDeclHandler = _reject
    parser.UnparsedEntityDeclHandler = _reject
    parser.ExternalEntityRefHandler = _reject
    return parser


def inspect_zip_archive(path: Path) -> None:
    """Validate ZIP-based documents (.epub, .docx) against magic spoofing, overlapping-entry zip bombs, traversal, and XXE."""
    try:
        with open(path, "rb") as raw_fp:
            head = raw_fp.read(4)
        if head not in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
            raise InputError("Signature magic berkas bukan arsip ZIP yang sah")
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise InputError(
                    f"Arsip memuat terlalu banyak berkas ({len(infos)} > {MAX_ARCHIVE_ENTRIES})"
                )
            # Fifield non-recursive overlapping-entry zip-bomb guard using exact on-disk local headers
            spans: list[tuple[int, int]] = []
            with open(path, "rb") as span_fp:
                for info in infos:
                    start = int(info.header_offset)
                    span_fp.seek(start)
                    lfh = span_fp.read(30)
                    if len(lfh) < 30 or lfh[:4] != b"PK\x03\x04":
                        raise InputError("Header lokal berkas ZIP tidak sah")
                    fname_len, extra_len = struct.unpack("<HH", lfh[26:30])
                    end = start + 30 + fname_len + extra_len + max(0, int(info.compress_size))
                    spans.append((start, end))
            spans.sort(key=lambda s: s[0])
            for idx in range(1, len(spans)):
                prev_start, prev_end = spans[idx - 1]
                cur_start, _ = spans[idx]
                if cur_start < prev_end and cur_start >= prev_start:
                    raise InputError("Arsip ZIP memiliki entri tumpang tindih (potensi zip bomb)")
            is_epub_archive = path.suffix.lower() == ".epub"
            total_uncompressed = 0
            total_compressed = 0
            for info in infos:
                if info.compress_type not in ALLOWED_ZIP_METHODS:
                    raise InputError("Metode kompresi arsip tidak didukung")
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise InputError("Tautan simbolik di dalam arsip ditolak demi keamanan")
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise InputError(f"Jalur berkas arsip tidak aman: {info.filename!r}")
                total_compressed += max(info.compress_size, 1)
                lower_name = name.lower()
                is_strict_xml = lower_name.endswith(_STRICT_XML_EXTS)
                is_html = lower_name.endswith(_HTML_EXTS)
                allow_epub_doctype = is_epub_archive and lower_name.endswith(_EPUB_CONTENT_EXTS)
                xml_parser = (
                    _make_strict_xml_scanner(allow_safe_epub_doctype=allow_epub_doctype)
                    if (is_strict_xml or is_html)
                    else None
                )
                first_chunk = True
                prev_tail = b""
                member_bytes = 0
                with zf.open(info, "r") as member:
                    while True:
                        chunk = member.read(65536)
                        if not chunk:
                            break
                        member_bytes += len(chunk)
                        total_uncompressed += len(chunk)
                        if member_bytes > MAX_SINGLE_MEMBER_BYTES:
                            raise InputError("Ukuran berkas tunggal dalam arsip melampaui batas aman 16 MB")
                        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                            raise InputError("Ukuran dekompresi berkas melampaui batas aman 64 MB")
                        if first_chunk:
                            first_chunk = False
                            if xml_parser is None:
                                trimmed = chunk.lstrip(b" \t\r\n\xef\xbb\xbf")
                                if trimmed.startswith(
                                    (
                                        b"<",
                                        b"\xff\xfe<\x00",
                                        b"\xfe\xff\x00<",
                                        b"\xff\xfe\x00\x00<\x00\x00\x00",
                                        b"\x00\x00\xfe\xff\x00\x00\x00<",
                                    )
                                ):
                                    xml_parser = _make_strict_xml_scanner(allow_safe_epub_doctype=False)
                        # Supplemental byte-level XXE/DOCTYPE check resilient to parser recovery modes
                        if is_strict_xml or is_html or xml_parser is not None:
                            window_lc = (prev_tail + chunk).lower()
                            ascii_folded = window_lc.replace(b"\x00", b"")
                            if b"<!entity" in ascii_folded:
                                raise InputError(
                                    "Deklarasi DOCTYPE/entitas XML eksternal (XXE) ditolak demi keamanan"
                                )
                            if b"<!doctype" in ascii_folded:
                                if not allow_epub_doctype:
                                    raise InputError(
                                        "Deklarasi DOCTYPE/entitas XML eksternal (XXE) ditolak demi keamanan"
                                    )
                                for m in _DOCTYPE_SCAN_RE.finditer(ascii_folded):
                                    frag = m.group(0)
                                    if b"[" in frag or not _SAFE_EPUB_DOCTYPE_BYTES_RE.fullmatch(frag):
                                        raise InputError(
                                            "Deklarasi DOCTYPE/entitas XML eksternal (XXE) ditolak demi keamanan"
                                        )
                            prev_tail = chunk[-64:]
                        if xml_parser is not None:
                            try:
                                xml_parser.Parse(chunk, False)
                            except expat.ExpatError as exc:
                                if is_strict_xml and not allow_epub_doctype:
                                    raise InputError("Struktur XML arsip tidak sah") from exc
                                xml_parser = None
                if xml_parser is not None:
                    try:
                        xml_parser.Parse(b"", True)
                    except expat.ExpatError as exc:
                        if is_strict_xml and not allow_epub_doctype:
                            raise InputError("Struktur XML arsip tidak sah") from exc
            if total_compressed > 0 and (total_uncompressed / total_compressed) > MAX_COMPRESSION_RATIO:
                raise InputError("Rasio kompresi arsip tidak wajar (potensi zip bomb)")
    except InputError:
        raise
    except zipfile.BadZipFile as exc:
        raise InputError("Berkas arsip rusak atau bukan format ZIP yang sah") from exc


def read_pdf_document(
    path: Path, title: str | None = None, _encoding: str | None = None
) -> Document:
    path = Path(path)
    try:
        with open(path, "rb") as raw_fp:
            pdf_head = raw_fp.read(1024)
        if b"%PDF-" not in pdf_head:
            raise InputError("Signature magic berkas bukan dokumen PDF yang sah")
    except InputError:
        raise
    except OSError as exc:
        raise InputError(f"PDF tidak dapat dibaca: {exc}") from exc
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
    total_chars = 0
    for page_num, page in enumerate(reader.pages, start=1):
        raw_text = (page.extract_text() or "").strip()
        if not raw_text:
            continue
        norm = raw_text.replace("\r\n", "\n")
        blocks = [blk.strip() for blk in norm.split("\n\n") if blk.strip()]
        if len(blocks) <= 1 and "\n" in norm:
            blocks = [line.strip() for line in norm.splitlines() if line.strip()]
        for blk in blocks:
            total_chars += len(blk)
            if total_chars > MAX_PDF_EXTRACTED_CHARS:
                raise InputError(
                    f"Teks PDF melebihi batas aman {MAX_PDF_EXTRACTED_CHARS:,} karakter"
                )
            paragraphs.append(Paragraph(text=blk, meta={"page": page_num}))

    doc_title = (title or path.stem or "Dokumen PDF").strip()
    return Document(
        title=doc_title,
        paragraphs=paragraphs,
        source_path=str(path),
        fmt="pdf",
    )


def read_docx_document(
    path: Path,
    title: str | None = None,
    _encoding: str | None = None,
    *,
    already_validated: bool = False,
) -> Document:
    path = Path(path)
    if not already_validated:
        inspect_zip_archive(path)
    try:
        word_doc = docx.Document(str(path))
    except Exception as exc:
        raise InputError(f"Berkas DOCX tidak dapat dibaca: {exc}") from exc

    paragraphs: list[Paragraph] = []
    total_chars = 0

    def _append_docx_para(para: Paragraph) -> None:
        nonlocal total_chars
        total_chars += len(para.text)
        if len(paragraphs) >= MAX_DOCX_PARAGRAPHS or total_chars > MAX_DOCX_CHARS:
            raise InputError(
                f"Teks DOCX melebihi batas aman {MAX_DOCX_CHARS:,} karakter atau {MAX_DOCX_PARAGRAPHS:,} paragraf"
            )
        paragraphs.append(para)

    para_by_el = {p._element: p for p in word_doc.paragraphs}
    table_by_el = {t._element: t for t in word_doc.tables}
    body = getattr(word_doc.element, "body", None)
    if body is not None:
        for child in body:
            para_obj = para_by_el.get(child)
            if para_obj is not None:
                txt = para_obj.text.strip()
                if not txt:
                    continue
                style_name = (para_obj.style.name if para_obj.style and para_obj.style.name else "").lower()
                kind = "heading" if style_name.startswith("heading") or style_name == "title" else "text"
                _append_docx_para(Paragraph(text=txt, kind=kind))
                continue
            table_obj = table_by_el.get(child)
            if table_obj is not None:
                for row in table_obj.rows:
                    seen_cells: set[int] = set()
                    for cell in row.cells:
                        if id(cell._tc) in seen_cells:
                            continue
                        seen_cells.add(id(cell._tc))
                        cell_text = cell.text.strip()
                        if cell_text:
                            _append_docx_para(Paragraph(text=cell_text, meta={"table": True}))
    else:
        for para in word_doc.paragraphs:
            txt = para.text.strip()
            if not txt:
                continue
            style_name = (para.style.name if para.style and para.style.name else "").lower()
            kind = "heading" if style_name.startswith("heading") or style_name == "title" else "text"
            _append_docx_para(Paragraph(text=txt, kind=kind))
        for table in word_doc.tables:
            for row in table.rows:
                seen_cells = set()
                for cell in row.cells:
                    if id(cell._tc) in seen_cells:
                        continue
                    seen_cells.add(id(cell._tc))
                    cell_text = cell.text.strip()
                    if cell_text:
                        _append_docx_para(Paragraph(text=cell_text, meta={"table": True}))

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
