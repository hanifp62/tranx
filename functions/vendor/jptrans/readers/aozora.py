"""Pengurai notasi Aozora Bunko (青空文庫).

Notasi yang ditangani (lihat https://www.aozora.gr.jp/annotation/):

- Ruby ``漢字《かんじ》`` dan ``｜武州《ぶしゅう》``. Tanpa ``｜``, basis ruby adalah
  deretan karakter sejenis tepat sebelum ``《`` (kanji, katakana, hiragana, atau
  huruf Latin). ``仝々〆〇ヶ`` dihitung kanji, sehingga ``一ヶ月《いっかげつ》``
  utuh menjadi satu basis.
- Anotasi ``［＃...］`` dibuang; baris dengan anotasi ``見出し`` menjadi judul bab.
- Gaiji ``※［＃「木＋青」、第3水準1-85-73］`` diubah ke karakter Unicode lewat
  codec ``euc_jis_2004`` (JIS X 0213), atau ``U+XXXX`` bila tertulis begitu.
- Blok keterangan simbol di kepala (di antara dua garis ``-----``) dan blok
  keterangan naskah di akhir (mulai ``底本：``) dibuang.

Ruby tidak dibuang begitu saja: pasangannya disimpan ke ``Document.ruby`` karena
furigana adalah sumber bacaan nama yang paling akurat.
"""

from __future__ import annotations

import logging
import re

from ..models import Document, Paragraph
from ..segment import split_paragraphs
from ..textnorm import KANJI

logger = logging.getLogger(__name__)

AOZORA_MARKERS = ("［＃", "※［＃")
UNKNOWN_CHAR = "〓"   # 下駄記号: pengganti resmi Aozora untuk karakter tak terwakili

_KANJI = "仝" + KANJI
_KANA_READING = r"[ぁ-ゖァ-ヺーゝゞヽヾ・\s]+"
_BARRED_RUBY_RE = re.compile(r"｜[^｜《》\n]+《[^《》\n]+》")
_UNBARRED_RUBY_RE = re.compile(
    rf"(?:[{_KANJI}]+|[A-Za-zＡ-Ｚａ-ｚ]+)《{_KANA_READING}》"
)
_RUBY_RE = re.compile(
    r"｜(?P<bar_base>[^｜《》\n]+)《(?P<bar_reading>[^《》\n]+)》"
    r"|(?P<base>[" + _KANJI + r"]+|[A-Za-zＡ-Ｚａ-ｚ]+)《(?P<reading>" + _KANA_READING + r")》"
)
_GAIJI_RE = re.compile(r"※［＃([^］]*)］")
_JIS_LEVEL_RE = re.compile(r"第[34]水準(\d)-(\d{1,2})-(\d{1,2})")
_UNICODE_RE = re.compile(r"U\+([0-9A-Fa-f]{4,6})")
_ANNOTATION_RE = re.compile(r"［＃[^］]*］")
_HEADING_RE = re.compile(r"［＃[^］]*見出し[^］]*］")
_DASH_LINE_RE = re.compile(r"^-{10,}[ \t]*$", re.MULTILINE)
_FOOTER_RE = re.compile(r"^[ \t　]*底本[：:]", re.MULTILINE)
_HEADER_HINTS = ("テキスト中に現れる記号", "《》：ルビ", "［＃］：入力者注")


def is_aozora(text: str) -> bool:
    """``True`` bila teks memuat anotasi khas Aozora atau furigana berpola sah."""
    if any(marker in text for marker in AOZORA_MARKERS):
        return True
    if _FOOTER_RE.search(text):
        return True
    return bool(_BARRED_RUBY_RE.search(text) or _UNBARRED_RUBY_RE.search(text))


def _has_aozora_header(text: str, dashes: list[re.Match[str]]) -> bool:
    if len(dashes) < 2 or dashes[0].start() > 1000:
        return False
    legend = text[dashes[0].end():dashes[1].start()]
    return any(hint in legend for hint in _HEADER_HINTS)


def front_matter_title(text: str) -> str | None:
    """Ambil judul karya dari kepala berkas Aozora Bunko."""
    dashes = list(_DASH_LINE_RE.finditer(text))
    if not is_aozora(text) or not _has_aozora_header(text, dashes):
        return None
    for line in text[: dashes[0].start()].split("\n"):
        clean, _pairs = extract_ruby(_ANNOTATION_RE.sub("", line))
        if clean.strip():
            return clean.strip()
    return None


def strip_header_footer(text: str) -> str:
    """Buang blok keterangan simbol Aozora di kepala dan ``底本：`` di akhir."""
    footer = _FOOTER_RE.search(text)
    if footer:
        text = text[: footer.start()]
    dashes = list(_DASH_LINE_RE.finditer(text))
    if _has_aozora_header(text, dashes):
        text = text[: dashes[0].start()] + text[dashes[1].end():]
    return text


def gaiji_to_char(annotation: str) -> str:
    """Ubah isi anotasi gaiji menjadi karakter Unicode, atau ``〓`` bila gagal.

    Args:
        annotation: Isi di antara ``※［＃`` dan ``］``, misalnya
            ``「木＋青」、第3水準1-85-73``.

    Returns:
        Karakter hasil konversi (bisa dua code point untuk JIS X 0213).
    """
    unicode_match = _UNICODE_RE.search(annotation)
    if unicode_match:
        code = int(unicode_match.group(1), 16)
        if code <= 0x10FFFF:
            return chr(code)
    level_match = _JIS_LEVEL_RE.search(annotation)
    if level_match:
        men, ku, ten = (int(part) for part in level_match.groups())
        if 1 <= ku <= 94 and 1 <= ten <= 94:
            raw = bytes([0xA0 + ku, 0xA0 + ten])
            if men == 2:
                raw = b"\x8f" + raw   # bidang 2 JIS X 0213 memakai awalan SS3 di EUC
            try:
                return raw.decode("euc_jis_2004")
            except UnicodeDecodeError:
                pass
    logger.debug("gaiji tidak dikenali, diganti %s", UNKNOWN_CHAR)
    return UNKNOWN_CHAR


def convert_gaiji(text: str) -> str:
    """Ganti semua notasi ``※［＃...］`` dengan karakternya."""
    return _GAIJI_RE.sub(lambda m: gaiji_to_char(m.group(1)), text)


def extract_ruby(line: str) -> tuple[str, list[tuple[str, str]]]:
    """Buang notasi ruby dari satu baris dan kumpulkan pasangannya.

    Args:
        line: Satu baris teks Aozora (anotasi ``［＃］`` sebaiknya sudah dibuang).

    Returns:
        ``(teks_bersih, [(basis, bacaan), ...])``; teks bersih hanya berisi basis.
    """
    pairs: list[tuple[str, str]] = []

    def keep_base(match: re.Match[str]) -> str:
        base = match.group("bar_base") or match.group("base")
        reading = match.group("bar_reading") or match.group("reading")
        pairs.append((base, reading))
        return base

    return _RUBY_RE.sub(keep_base, line), pairs


def parse_aozora(text: str, title: str) -> Document:
    """Urai teks Aozora Bunko menjadi ``Document`` bersih beserta pasangan ruby.

    Baris beranotasi ``見出し`` diberi ``kind="heading"``; bila berkas memiliki
    blok keterangan di kepala, baris pertamanya (judul karya) juga. Bacaan
    pertama untuk satu basis yang menang.

    Args:
        text: Teks Aozora yang sudah di-decode (biasanya dari Shift_JIS).
        title: Judul dokumen.

    Returns:
        Dokumen dengan ``fmt="aozora"``.
    """
    dashes = list(_DASH_LINE_RE.finditer(text))
    has_front_matter = _has_aozora_header(text, dashes)
    body = convert_gaiji(strip_header_footer(text))
    ruby: dict[str, str] = {}
    paragraphs: list[Paragraph] = []
    for line in body.split("\n"):
        is_title = has_front_matter and not paragraphs
        is_heading = is_title or bool(_HEADING_RE.search(line))
        clean, pairs = extract_ruby(_ANNOTATION_RE.sub("", line))
        _merge_ruby(ruby, pairs)
        for part in split_paragraphs(clean):
            kind = "heading" if is_heading else "text"
            paragraphs.append(Paragraph(text=part, kind=kind))
    logger.debug("aozora: %d paragraf, %d pasangan ruby", len(paragraphs), len(ruby))
    return Document(title=title, paragraphs=paragraphs, ruby=ruby, fmt="aozora")


def _merge_ruby(ruby: dict[str, str], pairs: list[tuple[str, str]]) -> None:
    for base, reading in pairs:
        known = ruby.setdefault(base, reading)
        if known != reading:
            logger.debug("ruby bertentangan untuk %s: %s dipertahankan", base, known)
