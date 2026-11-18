"""Pembaca EPUB 2/3 dengan ``zipfile``, ``xml.etree`` dan ``html.parser``.

Alur: ``META-INF/container.xml`` menunjuk berkas OPF; OPF memuat metadata
(``dc:title``), manifest (id ke berkas), dan spine (urutan baca). Tiap dokumen
XHTML di spine diurai menjadi paragraf, dan ruby ``<ruby>悠真<rt>ゆうま</rt></ruby>``
disimpan sebagai pasangan bacaan.

Keamanan dan legalitas:

- Isi ZIP tidak pernah di-extract ke disk (tidak ada path traversal). Ukuran
  di header ZIP bisa berbohong (zip bomb), jadi batas yang menentukan adalah
  anggaran deterministik: seluruh entri yang dibaca berbagi ``MAX_TOTAL_BYTES``
  (64 MB) byte hasil dekompresi, dihitung dari byte nyata yang keluar dari
  ``zipfile.open`` per blok ``READ_BLOCK``, sehingga pembacaan berhenti paling
  lambat satu blok setelah anggaran habis apa pun isi header. Hanya metode
  stored dan deflate (yang diizinkan OCF) yang diterima. Penolakan rasio
  kompresi untuk entri besar hanyalah penolakan dini yang murah, dokumen yang
  disebut berulang di spine hanya dibaca sekali, dan jumlah paragraf dibatasi,
  sehingga unggahan kecil tidak bisa menjadi jutaan paragraf.
- Deklarasi entitas XML ditolak di tingkat parser (expat), apa pun encoding
  berkasnya (UTF-8 maupun UTF-16). Di XHTML (``html.parser``), deklarasi DOCTYPE
  dibuang utuh beserta internal subset-nya sebelum parsing (``strip_doctype``), dan
  rujukan ke entitas yang dideklarasikan di subset dibuang tanpa diperluas, sehingga
  ``]>`` dan ``&x;`` tidak bocor ke teks dan tidak ada berkas yang dibaca.
- EPUB ber-DRM ditolak, tidak dibongkar. Obfuscation font IDPF/Adobe bukan DRM.
- EPUB fixed-layout (khas manga) hanya berisi gambar; pengguna diarahkan ke
  alur komik ``pages.json``.
"""

from __future__ import annotations

import html
import logging
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from html.entities import html5 as HTML5_ENTITIES
from html.parser import HTMLParser
from xml.parsers import expat
from pathlib import Path
from urllib.parse import unquote

from ..errors import InputError
from ..models import Document, Paragraph

logger = logging.getLogger(__name__)

MAX_ENTRY_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
"""Anggaran byte hasil dekompresi untuk SEMUA entri yang dibaca dari satu EPUB.

Satu jilid novel berisi beberapa MB XHTML; 64 MB jauh di atasnya tetapi tetap
aman untuk memori. Dihitung dari byte nyata, tidak pernah dari header ZIP.
"""
READ_BLOCK = 64 * 1024
"""Ukuran satu ``read`` dari ``ZipExtFile``; deflate mengeluarkan paling banyak sebesar ini."""
ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
"""Metode yang diizinkan OCF. bzip2/LZMA di ``zipfile`` tidak membatasi keluaran per blok."""
MAX_COMPRESSION_RATIO = 100
"""XHTML biasa terkompresi 3–10×; rasio di atas ini hanya dipakai bom dekompresi."""
RATIO_CHECK_BYTES = 1024 * 1024
"""Entri kecil boleh berasio tinggi (berkas berisi spasi); hanya entri besar yang diperiksa."""
MAX_PARAGRAPHS = 100_000
"""Satu jilid novel berisi beberapa ribu paragraf; batas ini jauh di atasnya."""
CONTAINER_PATH = "META-INF/container.xml"
ENCRYPTION_PATH = "META-INF/encryption.xml"
DRM_MARKERS = ("META-INF/rights.xml", "META-INF/sinf.xml")
FONT_OBFUSCATION = frozenset({
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#RC",
})
XHTML_TYPES = frozenset({"application/xhtml+xml", "text/html", "text/x-oeb1-document"})
FIXED_LAYOUT_HINT = (
    "EPUB fixed-layout (komik/manga) hanya berisi gambar. Jalankan OCR dulu "
    "lalu terjemahkan berkas pages.json (lihat readers.pages)."
)

_XML_ENCODING_RE = re.compile(rb"""^<\?xml[^>]*encoding=["']([A-Za-z0-9._-]+)["']""")
# Baris baru dari indentasi sumber di antara dua karakter Jepang bukan spasi kata.
_CJK_NEWLINE_RE = re.compile(r"(?<=[^\x00-\x7f])[ \t\r\f]*\n[ \t\r\n\f]*(?=[^\x00-\x7f])")
_ASCII_SPACE_RE = re.compile(r"[ \t\r\n\f]+")
_DOCTYPE_SCAN_RE = re.compile(r"<!--|<!\[CDATA\[|<!DOCTYPE\b", re.IGNORECASE)
"""Awal komentar, CDATA, atau DOCTYPE: ``strip_doctype`` melewati dua yang pertama utuh."""
_ELEMENT_START_RE = re.compile(r"</?[A-Za-z]")
_ENTITY_DECL_RE = re.compile(r"<!ENTITY\s+([^\s%][^\s\"'>]*)")
"""Nama entitas umum di internal subset (entitas parameter ``<!ENTITY % p ...>`` dilewati)."""
SENTENCE_END = "。．.！!？?…‥」』）)】"
"""Tanda akhir kalimat/ujaran: ``<br>`` sesudahnya selalu memisah baris (``XhtmlExtractor``)."""
SOFT_BREAK_TAILS = "、，,はがをにでともへのや"
"""Akhir baris yang jelas belum selesai (koma, partikel): ``<br>`` sesudahnya baris lunak
(``湊は<br/>笑った。``). Akhir lain (kanji, ``た``, tanda pisah, tanda akhir) tetap memisah baris:
``第一章<br/>湊の朝``, ``湊は笑った<br/>美咲は泣いた``."""
LINE_OPENERS = "「『（(〈《【〔―—─‐-"
"""Awal baris yang membuka ujaran/baris baru: baris lunak sebelumnya dibatalkan
(``「待って――<br/>「なに？」``, ``――湊<br/>――美咲``)."""
WORD_INNER_STARTS = "っゃゅょぁぃぅぇぉゎんーッャュョァィゥェォヮン"
"""Huruf yang tidak pernah memulai kata: baris yang diawalinya melanjutkan kata yang terpotong
(``湊は笑<br/>った。``), jadi ``<br>`` sebelumnya tetap baris lunak walau baris sebelumnya
berakhir kanji."""
SOFT_MARK = "\ue000"
"""Penanda baris lunak di buffer: spasi di antara huruf Latin, selain itu dihapus
(``_join_soft``)."""
_SOFT_JOIN_RE = re.compile(r"[ \t\r\n\f]*\ue000[ \t\r\n\f]*")


class _ZipReader:
    """Membaca entri ZIP di memori, per blok, dengan anggaran byte yang deterministik.

    Attributes:
        bytes_read: Total byte hasil dekompresi yang sudah keluar dari semua
            entri (termasuk blok yang membuat anggaran terlampaui).
    """

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self.archive = archive
        self.names = frozenset(archive.namelist())
        self.bytes_read = 0

    def read(self, name: str) -> bytes:
        """Isi entri ``name``; ``InputError`` bila hilang, rusak, atau melampaui batas.

        Ukuran di header hanya dipakai untuk penolakan dini rasio kompresi.
        Batas per entri dan anggaran total dihitung dari byte nyata yang dibaca
        bertahap, jadi header yang mengaku kecil tetap berhenti di anggaran.
        """
        if name not in self.names:
            raise InputError(f"EPUB rusak: entri {name} tidak ada")
        info = self.archive.getinfo(name)
        if info.compress_type not in ALLOWED_COMPRESSION:
            raise InputError(f"EPUB ditolak: entri {name} memakai metode kompresi "
                             f"{info.compress_type} (hanya stored/deflate)")
        if info.file_size > RATIO_CHECK_BYTES and \
                info.file_size > MAX_COMPRESSION_RATIO * max(info.compress_size, 1):
            raise InputError(f"EPUB ditolak: entri {name} terkompresi tidak wajar (bom ZIP?)")
        try:
            return self._read_blocks(name)
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError,
                NotImplementedError) as exc:
            raise InputError(f"EPUB rusak: entri {name} tidak bisa dibaca ({exc})") from exc

    def _read_blocks(self, name: str) -> bytes:
        """Baca ``name`` per ``READ_BLOCK`` sambil menghitung anggaran per entri dan total."""
        chunks: list[bytes] = []
        entry_bytes = 0
        with self.archive.open(name) as handle:
            while block := handle.read(READ_BLOCK):
                entry_bytes += len(block)
                self.bytes_read += len(block)
                if self.bytes_read > MAX_TOTAL_BYTES:
                    raise InputError("EPUB ditolak: total isi hasil dekompresi melebihi "
                                     f"anggaran {MAX_TOTAL_BYTES} byte")
                if entry_bytes > MAX_ENTRY_BYTES:
                    raise InputError(f"EPUB ditolak: entri {name} melebihi {MAX_ENTRY_BYTES} byte")
                chunks.append(block)
        return b"".join(chunks)


class XhtmlExtractor(HTMLParser):
    """Ambil paragraf dan pasangan ruby dari satu dokumen XHTML.

    Batas paragraf: ``p``, ``div``, ``h1``-``h6``, ``li``, ``blockquote``, dan
    ``br`` (banyak EPUB Jepang memakai satu ``<br/>`` per baris). Di dalam ``<p>``,
    satu ``<br>`` sesudah baris yang jelas belum selesai (berakhir koma/partikel
    ``SOFT_BREAK_TAILS`` seperti ``湊は<br/>笑った。``, atau huruf/angka Latin) atau sebelum
    baris yang melanjutkan kata (``WORD_INNER_STARTS``: ``湊は笑<br/>った。``) adalah baris
    lunak: kalimatnya tidak dipecah, dan baris itu menjadi spasi di antara huruf Latin atau
    hilang di antara huruf Jepang (``_join_soft``). Baris lunak batal bila baris berikutnya
    diawali ``LINE_OPENERS`` (kurung pembuka, tanda pisah). Baris lain (``第一章<br/>湊の朝``),
    dua ``<br>`` berturut-turut, ``<br>`` sesudah ``SENTENCE_END``, dan ``<br>`` di luar ``<p>``
    (``<div>`` baris demi baris) tetap memisah baris. Teks ``rt`` menjadi bacaan, ``rp``
    dibuang, dan basis ruby tetap masuk ke teks.

    Attributes:
        paragraphs: Paragraf hasil ekstraksi, berurutan.
        ruby: Pasangan ``(basis, bacaan)`` sesuai urutan kemunculan.
    """

    BLOCK_TAGS = frozenset({"p", "div", "li", "blockquote", "br", "dt", "dd",
                            "h1", "h2", "h3", "h4", "h5", "h6"})
    HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
    SKIP_TAGS = frozenset({"head", "script", "style", "rp", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[Paragraph] = []
        self.ruby: list[tuple[str, str]] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._heading_depth = 0
        self._in_ruby = False
        self._in_rt = False
        self._ruby_pending_base: list[str] = []
        self._ruby_current_rt: list[str] = []
        self._ruby_pairs_buf: list[tuple[str, str]] = []
        self._para_depth = 0
        self._soft_break = False
        self._soft_index = -1
        self._soft_tail = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._line_break()
        elif tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "ruby":
            self._in_ruby = True
            self._in_rt = False
            self._ruby_pending_base = []
            self._ruby_current_rt = []
            self._ruby_pairs_buf = []
        elif tag == "rt":
            if self._in_rt:
                self._commit_rt()
            self._in_rt = True
            self._ruby_current_rt = []
        elif tag in self.BLOCK_TAGS:
            self._flush()
            self._para_depth += tag == "p"
            if tag in self.HEADING_TAGS:
                self._heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "br":
            return
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "rt":
            self._commit_rt()
        elif tag == "ruby":
            self._close_ruby()
        elif tag in self.BLOCK_TAGS:
            self._flush()
            if tag == "p":
                self._para_depth = max(0, self._para_depth - 1)
            if tag in self.HEADING_TAGS:
                self._heading_depth = max(0, self._heading_depth - 1)

    def _line_break(self) -> None:
        """``<br>``: calon baris lunak di dalam ``<p>``, selebihnya batas paragraf.

        Keputusan akhir menunggu teks baris berikutnya (``handle_data``): baris lunak bila baris
        sebelumnya berakhir ``SOFT_BREAK_TAILS``/huruf Latin atau baris berikutnya diawali
        ``WORD_INNER_STARTS``, dan baris berikutnya tidak diawali ``LINE_OPENERS``.
        """
        if self._skip_depth:
            return
        last = "".join(self._buffer).rstrip(" \t\r\n\f")[-1:]
        if not self._para_depth or self._soft_break or not last or last in SENTENCE_END:
            self._flush()
            return
        self._soft_index = len(self._buffer)
        self._soft_tail = last in SOFT_BREAK_TAILS or (last.isascii() and last.isalnum())
        self._buffer.append(SOFT_MARK)
        self._soft_break = True

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_rt:
            self._ruby_current_rt.append(data)
            return
        if self._in_ruby:
            self._ruby_pending_base.append(data)
        if data.strip():
            first = data.lstrip()[0]
            if self._soft_break and (first in LINE_OPENERS or not (
                    self._soft_tail or first in WORD_INNER_STARTS)):
                self._buffer = self._buffer[:self._soft_index]
                self._flush()
            self._soft_break = False
        self._buffer.append(data)

    def close(self) -> None:
        """Selesaikan parsing dan simpan paragraf terakhir yang belum tertutup."""
        super().close()
        self._flush()

    def _commit_rt(self) -> None:
        if not self._in_rt:
            return
        base = "".join(self._ruby_pending_base).strip()
        reading = "".join(self._ruby_current_rt).strip()
        if base and reading:
            self._ruby_pairs_buf.append((base, reading))
        self._ruby_pending_base = []
        self._ruby_current_rt = []
        self._in_rt = False

    def _close_ruby(self) -> None:
        if self._in_rt:
            self._commit_rt()
        if self._ruby_pairs_buf:
            base = "".join(b for b, _r in self._ruby_pairs_buf)
            reading = "".join(r for _b, r in self._ruby_pairs_buf)
            if base and reading:
                self.ruby.append((base, reading))
        self._ruby_pending_base = []
        self._ruby_current_rt = []
        self._ruby_pairs_buf = []
        self._in_ruby = False
        self._in_rt = False

    def _flush(self) -> None:
        if self._in_ruby:
            self._close_ruby()
        else:
            self._in_rt = False
        text = tidy_inline(_join_soft("".join(self._buffer)))
        self._buffer = []
        self._soft_break = False
        if text:
            kind = "heading" if self._heading_depth else "text"
            self.paragraphs.append(Paragraph(text=text, kind=kind))


def _join_soft(text: str) -> str:
    """Ganti penanda baris lunak (``SOFT_MARK``) dengan spasi di antara huruf/angka Latin
    (``He said<br/>hello``) atau hapus di antara huruf lain (``湊は<br/>笑った``)."""
    def repl(match: re.Match[str]) -> str:
        left = match.string[match.start() - 1:match.start()]
        right = match.string[match.end():match.end() + 1]
        latin = left.isascii() and right.isascii() and (left + right).strip(",;:").isalnum()
        return " " if latin and left and right else ""
    return _SOFT_JOIN_RE.sub(repl, text)


def tidy_inline(text: str) -> str:
    """Rapikan spasi dari indentasi sumber XHTML tanpa menyentuh spasi penuh di tengah.

    Spasi penuh (U+3000) di tepi dibuang karena itu indentasi paragraf.
    """
    text = _CJK_NEWLINE_RE.sub("", text)
    return _ASCII_SPACE_RE.sub(" ", text).strip(" 　")


def extract_xhtml(markup: str) -> tuple[list[Paragraph], list[tuple[str, str]]]:
    """Urai satu dokumen XHTML menjadi ``(paragraf, pasangan_ruby)``.

    DOCTYPE dibuang lebih dulu (``strip_doctype``); rujukan ke entitas yang dideklarasikan di
    internal subset-nya dibuang tanpa diperluas, kecuali nama entitas standar HTML
    (``&nbsp;``, ``&amp;``) yang tetap diperluas ``html.parser`` seperti tanpa subset.
    """
    markup, declared = strip_doctype(markup)
    custom = sorted(name for name in declared if name + ";" not in HTML5_ENTITIES)
    if custom:
        pattern = "|".join(re.escape(name) for name in custom)
        markup, dropped = re.subn(f"&(?:{pattern});", "", markup)
        logger.warning("DOCTYPE berisi %d deklarasi entitas; %d rujukan dibuang tanpa diperluas",
                       len(custom), dropped)
    parser = XhtmlExtractor()
    parser.feed(markup)
    parser.close()
    return parser.paragraphs, parser.ruby


def strip_doctype(markup: str) -> tuple[str, frozenset[str]]:
    """Buang deklarasi ``<!DOCTYPE ...>`` beserta internal subset ``[...]``.

    ``html.parser`` mengakhiri DOCTYPE di ``>`` pertama, sehingga subset seperti
    ``[<!ENTITY x SYSTEM "file:///etc/passwd">]>`` bocor sebagai teks ``]>``. Komentar dan
    CDATA dilewati utuh (``<!DOCTYPE`` di dalamnya hanya teks). Pemindai subset
    (``_doctype_end``) menghormati kutipan, komentar, dan PI. DOCTYPE yang tidak ditutup dibuang
    hanya sampai awal elemen berikutnya, dengan peringatan, agar isi bab tidak ikut hilang.
    Entitas tidak pernah diperluas.

    Returns:
        ``(markup tanpa DOCTYPE, nama entitas umum yang dideklarasikan di subset)``.
    """
    parts: list[str] = []
    names: set[str] = set()
    pos = scan = 0
    while (match := _DOCTYPE_SCAN_RE.search(markup, scan)) is not None:
        token = match.group()
        if not token.upper().startswith("<!DOCTYPE"):
            close = markup.find("-->" if token == "<!--" else "]]>", match.end())
            scan = len(markup) if close < 0 else close + 3
            continue
        parts.append(markup[pos:match.start()])
        pos, subset, closed = _doctype_end(markup, match.end())
        if not closed:
            logger.warning("DOCTYPE tidak ditutup; dibuang sampai awal elemen berikutnya")
        names.update(_ENTITY_DECL_RE.findall(subset))
        scan = pos
    parts.append(markup[pos:])
    return "".join(parts), frozenset(names)


def _doctype_end(markup: str, start: int) -> tuple[int, str, bool]:
    """Ujung DOCTYPE yang namanya berakhir di ``start``: ``(posisi sesudahnya, subset, tertutup)``.

    Kepala (nama, PUBLIC/SYSTEM) dibaca sampai ``[`` atau ``>`` dengan menghormati kutipan.
    Subset dibaca per token (``_subset_token_end``) sampai ``]`` lalu ``>``. Elemen atau token
    yang tidak tertutup berarti DOCTYPE rusak (``_unclosed_doctype``).
    """
    quote, i = "", start
    while i < len(markup):
        char = markup[i]
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == ">":
            return i + 1, "", True
        elif char in "[<":
            break
        i += 1
    if i >= len(markup) or markup[i] != "[":
        return _unclosed_doctype(markup, start, -1)
    subset_start = i = i + 1
    while i < len(markup):
        if markup[i] == "]":
            close = re.compile(r"\s*>").match(markup, i + 1)
            return (close.end() if close else i + 1), markup[subset_start:i], close is not None
        after = _subset_token_end(markup, i)
        if after is None:
            return _unclosed_doctype(markup, start, subset_start)
        i = after
    return _unclosed_doctype(markup, start, subset_start)


def _subset_token_end(markup: str, i: int) -> int | None:
    """Posisi sesudah satu token internal subset di ``i`` (komentar, PI, deklarasi ``<!...>``
    berkutipan, atau satu huruf lain); ``None`` bila token tidak ditutup atau ``i`` adalah awal
    elemen (``<html``, ``</p``: subset tidak pernah ditutup)."""
    if markup.startswith("<!--", i):
        close = markup.find("-->", i + 4)
        return None if close < 0 else close + 3
    if markup.startswith("<?", i):
        close = markup.find("?>", i + 2)
        return None if close < 0 else close + 2
    if markup.startswith("<!", i):
        quote = ""
        for j in range(i + 2, len(markup)):
            char = markup[j]
            if quote:
                quote = "" if char == quote else quote
            elif char in "\"'":
                quote = char
            elif char == ">":
                return j + 1
        return None
    return None if markup[i] == "<" else i + 1


def _unclosed_doctype(markup: str, start: int, subset_start: int) -> tuple[int, str, bool]:
    """DOCTYPE rusak: dibuang sampai awal elemen pertama sesudah ``start`` (atau akhir teks)."""
    element = _ELEMENT_START_RE.search(markup, start)
    end = element.start() if element else len(markup)
    return end, markup[subset_start:end] if subset_start >= 0 else "", False


def decode_markup(raw: bytes, name: str) -> str:
    """Decode XHTML/XML menurut BOM atau deklarasi ``<?xml encoding=...?>``.

    Byte yang rusak diganti U+FFFD (dengan peringatan) alih-alih menggagalkan
    seluruh buku karena satu karakter.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        declared = _XML_ENCODING_RE.match(raw.removeprefix(b"\xef\xbb\xbf"))
        encoding = declared.group(1).decode("ascii") if declared else "utf-8"
    try:
        text = raw.decode("utf-8-sig" if encoding.lower() == "utf-8" else encoding,
                          errors="replace")
    except LookupError:
        logger.warning("encoding %s di %s tidak dikenal; dibaca sebagai UTF-8", encoding, name)
        text = raw.decode("utf-8-sig", errors="replace")
    if "�" in text:
        logger.warning("%s memuat byte yang tidak sah untuk %s", name, encoding)
    return text


def _local(tag: str) -> str:
    """Nama tag tanpa namespace: ``{http://...}spine`` menjadi ``spine``."""
    return tag.rsplit("}", 1)[-1]


def _parse_xml(raw: bytes, name: str) -> ET.Element:
    """Urai XML kecil (container, OPF, encryption) setelah memastikan tanpa entitas."""
    _reject_entities(raw, name)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise InputError(f"EPUB rusak: {name} bukan XML yang sah ({exc})") from exc


def _reject_entities(raw: bytes, name: str) -> None:
    """Tolak deklarasi entitas XML dengan expat, apa pun encoding berkasnya.

    OPF/container/encryption tidak pernah butuh deklarasi entitas; menolaknya
    menutup serangan "billion laughs" dan entitas eksternal tanpa defusedxml.
    Pencarian byte ``<!ENTITY`` saja bisa dilewati dengan XML UTF-16.

    Raises:
        InputError: Ada deklarasi entitas, atau XML tidak sah.
    """
    def refuse(*_args: object) -> None:
        raise InputError(f"EPUB ditolak: {name} memuat deklarasi entitas XML")

    parser = expat.ParserCreate()
    parser.EntityDeclHandler = refuse
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as exc:
        raise InputError(f"EPUB rusak: {name} bukan XML yang sah ({exc})") from exc


def _child(parent: ET.Element, name: str) -> ET.Element | None:
    return next((el for el in parent if _local(el.tag) == name), None)


def check_drm(zip_reader: _ZipReader) -> None:
    """Tolak EPUB ber-DRM.

    ``encryption.xml`` yang hanya berisi obfuscation font masih diizinkan;
    algoritma lain apa pun dianggap enkripsi konten.

    Raises:
        InputError: EPUB ber-DRM.
    """
    if any(marker in zip_reader.names for marker in DRM_MARKERS):
        raise InputError("EPUB ber-DRM tidak didukung")
    if ENCRYPTION_PATH not in zip_reader.names:
        return
    root = _parse_xml(zip_reader.read(ENCRYPTION_PATH), ENCRYPTION_PATH)
    algorithms = [el.get("Algorithm", "") for el in root.iter()
                  if _local(el.tag) == "EncryptionMethod"]
    if any(algo not in FONT_OBFUSCATION for algo in algorithms):
        raise InputError("EPUB ber-DRM tidak didukung")


def find_opf_path(zip_reader: _ZipReader) -> str:
    """Lokasi berkas OPF menurut ``container.xml``."""
    root = _parse_xml(zip_reader.read(CONTAINER_PATH), CONTAINER_PATH)
    for element in root.iter():
        if _local(element.tag) == "rootfile" and element.get("full-path"):
            return element.get("full-path", "")
    raise InputError("EPUB rusak: container.xml tidak menunjuk berkas OPF")


def opf_title(package: ET.Element) -> str:
    """Isi ``dc:title`` pertama, atau string kosong."""
    metadata = _child(package, "metadata")
    if metadata is None:
        return ""
    title = next((el for el in metadata.iter() if _local(el.tag) == "title"), None)
    return (title.text or "").strip() if title is not None else ""


def is_fixed_layout(package: ET.Element) -> bool:
    """``True`` untuk EPUB pre-paginated (EPUB 3) atau ``fixed-layout`` gaya lama."""
    metadata = _child(package, "metadata")
    if metadata is None:
        return False
    for meta in metadata.iter():
        if _local(meta.tag) != "meta":
            continue
        prop = meta.get("property") or meta.get("name") or ""
        value = (meta.text or meta.get("content") or "").strip().lower()
        if prop == "rendition:layout" and value == "pre-paginated":
            return True
        if prop == "fixed-layout" and value == "true":
            return True
    return False


def spine_documents(package: ET.Element, opf_path: str) -> list[str]:
    """Nama entri ZIP dokumen XHTML sesuai urutan spine, tanpa ``linear="no"``.

    Href di manifest relatif terhadap folder OPF dan bisa ter-URL-encode.
    Dokumen yang disebut lebih dari sekali hanya diambil pada kemunculan pertama.
    """
    manifest = _child(package, "manifest")
    spine = _child(package, "spine")
    if manifest is None or spine is None:
        raise InputError("EPUB rusak: OPF tanpa manifest atau spine")
    base = posixpath.dirname(opf_path)
    items = {}
    for item in manifest:
        href = unquote((item.get("href") or "").split("#", 1)[0])
        if item.get("id") and href:
            joined = href.lstrip("/") if href.startswith("/") else posixpath.join(base, href)
            path = posixpath.normpath(joined)
            if path != "." and not path.startswith(".."):
                items[item.get("id")] = (path, item.get("media-type", ""))
    documents: list[str] = []
    for itemref in spine:
        if _local(itemref.tag) != "itemref" or itemref.get("linear", "yes") == "no":
            continue
        path, media_type = items.get(itemref.get("idref", ""), ("", ""))
        if not path:
            logger.warning("itemref %s tidak ada di manifest", itemref.get("idref"))
        elif media_type in XHTML_TYPES and path not in documents:
            documents.append(path)
    return documents


def read_epub(path: Path, title: str | None = None) -> Document:
    """Baca EPUB menjadi ``Document`` dengan ruby tersimpan di ``doc.ruby``.

    Args:
        path: Lokasi berkas ``.epub``.
        title: Judul; bawaan ``dc:title``, lalu nama berkas.

    Returns:
        Dokumen dengan ``fmt="epub"``.

    Raises:
        InputError: Bukan EPUB, rusak, ber-DRM, fixed-layout, terlalu besar,
            atau tidak berisi teks.
    """
    path = Path(path)
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise InputError(f"{path.name} bukan EPUB/ZIP yang bisa dibaca: {exc}") from exc
    with archive:
        zip_reader = _ZipReader(archive)
        check_drm(zip_reader)
        opf_path = find_opf_path(zip_reader)
        package = _parse_xml(zip_reader.read(opf_path), opf_path)
        if is_fixed_layout(package):
            raise InputError(FIXED_LAYOUT_HINT)
        paragraphs: list[Paragraph] = []
        ruby: dict[str, str] = {}
        for name in spine_documents(package, opf_path):
            if name not in zip_reader.names:
                logger.warning("dokumen spine %s tidak ada di ZIP, dilewati", name)
                continue
            found, pairs = extract_xhtml(decode_markup(zip_reader.read(name), name))
            paragraphs.extend(found)
            if len(paragraphs) > MAX_PARAGRAPHS:
                raise InputError(f"EPUB ditolak: lebih dari {MAX_PARAGRAPHS} paragraf")
            for base, reading in pairs:
                ruby.setdefault(base, reading)
    if not paragraphs:
        raise InputError(f"{path.name} tidak berisi teks yang bisa diterjemahkan")
    logger.debug("epub: %d paragraf, %d ruby, %d byte dibaca",
                 len(paragraphs), len(ruby), zip_reader.bytes_read)
    return Document(
        title=title or opf_title(package) or path.stem,
        paragraphs=paragraphs, ruby=ruby, source_path=str(path), fmt="epub",
    )


_HTML_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def read_html(
    path: Path, title: str | None = None, encoding: str | None = None
) -> Document:
    """Baca berkas ``.html``/``.htm``/``.xhtml`` mandiri beserta tag ``<ruby>``."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"tidak bisa membaca {path}: {exc.strerror or exc}") from exc
    if len(raw) > MAX_ENTRY_BYTES:
        raise InputError(f"HTML ditolak: ukuran melebihi {MAX_ENTRY_BYTES} byte")
    if encoding:
        try:
            markup = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            raise InputError(f"HTML tidak bisa di-decode sebagai {encoding}: {exc}") from exc
    else:
        markup = decode_markup(raw, path.name)
    paragraphs, pairs = extract_xhtml(markup)
    if not paragraphs:
        raise InputError(f"{path.name} tidak berisi teks yang bisa diterjemahkan")
    ruby: dict[str, str] = {}
    for base, reading in pairs:
        ruby.setdefault(base, reading)
    found_title = ""
    title_match = _HTML_TITLE_RE.search(markup)
    if title_match:
        found_title = tidy_inline(html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))))
    return Document(
        title=title or found_title or path.stem,
        paragraphs=paragraphs,
        ruby=ruby,
        source_path=str(path),
        fmt="html",
    )
