"""Pembaca teks polos dan deteksi encoding Jepang tanpa pustaka luar.

Berkas novel Jepang beredar dalam UTF-8, Shift_JIS (``cp932``), EUC-JP,
ISO-2022-JP, atau UTF-16. Deteksi di sini tidak percaya begitu saja pada
"bisa di-decode": byte EUC-JP yang pendek (``短`` = ``C3 BB``) juga UTF-8 yang
sah dan menghasilkan ``û``. Karena itu setiap kandidat diberi skor menurut
seberapa "Jepang" hasil decode-nya, lalu skor tertinggi yang dipilih.
"""

from __future__ import annotations

import codecs
import logging
from pathlib import Path

from ..errors import InputError
from ..models import Document, Paragraph
from ..segment import split_paragraphs
from ..textnorm import is_hiragana, is_kanji, is_katakana

logger = logging.getLogger(__name__)

# BOM dicek sebelum apa pun karena menentukan encoding secara pasti.
_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
# Escape sequence pindah ke JIS X 0208 (1983 dan 1978) khas ISO-2022-JP.
_ISO2022_ESCAPES = (b"\x1b$B", b"\x1b$@")
# Urutan = prioritas saat skor setara. cp932 dipakai alih-alih shift_jis karena
# berkas buatan Windows sering memuat karakter tambahan NEC/IBM (①, ㈱, 髙).
CANDIDATE_ENCODINGS = ("utf-8", "cp932", "euc_jp")
# Kandidat berikutnya harus unggul lebih dari ini agar menggeser yang sebelumnya.
TIE_MARGIN = 0.05
# Skor cukup dihitung dari awal teks; validitas decode tetap memeriksa seluruh byte.
SCORE_SAMPLE_CHARS = 20_000

_JAPANESE_PUNCT = frozenset("…‥―")


def detect_encoding(raw: bytes) -> str:
    """Tebak encoding berkas teks Jepang.

    Urutan: BOM, escape ISO-2022-JP, lalu skor untuk tiap kandidat di
    ``CANDIDATE_ENCODINGS`` yang bisa men-decode seluruh byte secara ketat.

    Args:
        raw: Isi berkas mentah.

    Returns:
        Nama codec Python, misalnya ``"utf-8"``, ``"cp932"``, ``"euc_jp"``.

    Raises:
        InputError: Tidak ada kandidat yang bisa men-decode byte tersebut.
    """
    for bom, name in _BOMS:
        if raw.startswith(bom):
            return name
    if b"\x00" in raw:
        raise InputError(
            "berkas tampak biner atau UTF-16 tanpa BOM; coba --encoding utf-16le"
        )
    if any(esc in raw for esc in _ISO2022_ESCAPES):
        return "iso2022_jp"

    best_name, best_score = "", float("-inf")
    for name in CANDIDATE_ENCODINGS:
        try:
            text = raw.decode(name)
        except UnicodeDecodeError:
            continue
        score = japanese_score(text)
        logger.debug("skor encoding %s = %.3f", name, score)
        if score > best_score + TIE_MARGIN:
            best_name, best_score = name, score
    if not best_name:
        raise InputError("encoding berkas tidak dikenali; coba tentukan dengan --encoding")
    return best_name


def japanese_score(text: str) -> float:
    """Skor rata-rata kewajaran Jepang per karakter non-ASCII (-1 sampai 1).

    ASCII cetak tidak dihitung karena sama persis di semua kandidat encoding;
    sampel diambil dari ``SCORE_SAMPLE_CHARS`` karakter non-ASCII pertama.
    """
    weights: list[float] = []
    size = len(text)
    for idx, ch in enumerate(text):
        if " " <= ch <= "~" or ch in "\t\n\r":
            continue
        prev_ch = text[idx - 1] if idx > 0 else ""
        next_ch = text[idx + 1] if idx + 1 < size else ""
        weights.append(_char_weight(ch, prev_ch, next_ch))
        if len(weights) >= SCORE_SAMPLE_CHARS:
            break
    if not weights:
        return 0.0
    return sum(weights) / len(weights)


def _is_ascii_letter(ch: str) -> bool:
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z")


def _char_weight(ch: str, prev_ch: str = "", next_ch: str = "") -> float:
    code = ord(ch)
    if 0xFF61 <= code <= 0xFF9F:
        return -1.0
    if is_hiragana(ch) or is_katakana(ch) or ch in _JAPANESE_PUNCT:
        return 1.0
    if is_kanji(ch):
        return 1.0 if _is_common_kanji(ch) else 0.3
    if 0x3000 <= code <= 0x303F:
        return 1.0
    if 0xFF01 <= code <= 0xFF60:
        return 0.5
    if code < 0x20 or 0x7F <= code <= 0x9F or 0xE000 <= code <= 0xF8FF or code == 0xFFFD:
        return -1.0
    if 0xA0 <= code <= 0x24F:
        if _is_ascii_letter(prev_ch) or _is_ascii_letter(next_ch):
            return 0.8
        return -0.5
    return 0.0


def _is_common_kanji(ch: str) -> bool:
    """Kanji JIS X 0208 level 1 (byte pertama EUC-JP 0xB0-0xCF).

    Level 1 memuat kanji sehari-hari; teks hasil salah decode menyebar acak
    ke level 2 dan blok yang jarang, sehingga perbedaan ini memisahkan keduanya.
    """
    try:
        encoded = ch.encode("euc_jp")
    except UnicodeEncodeError:
        return False
    return len(encoded) == 2 and 0xB0 <= encoded[0] <= 0xCF


def decode_bytes(raw: bytes, encoding: str | None = None) -> str:
    """Decode byte menjadi teks dengan baris baru ``\\n`` dan tanpa BOM.

    Args:
        raw: Isi berkas mentah.
        encoding: Nama codec dari pengguna; ``None`` berarti deteksi otomatis.

    Returns:
        Teks hasil decode.

    Raises:
        InputError: Codec tidak dikenal atau byte tidak cocok dengan codec.
    """
    name = encoding or detect_encoding(raw)
    try:
        text = raw.decode(name)
    except LookupError as exc:
        raise InputError(f"encoding tidak dikenal: {name}") from exc
    except UnicodeDecodeError as exc:
        raise InputError(
            f"berkas tidak bisa dibaca sebagai {name} (byte ke-{exc.start}); "
            "coba --encoding lain"
        ) from exc
    logger.debug("decode %d byte sebagai %s", len(raw), name)
    return normalize_newlines(text.removeprefix("﻿"))


def normalize_newlines(text: str) -> str:
    """Samakan CR+LF (Windows, Aozora) dan CR (Mac lama) menjadi LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text_file(path: Path, encoding: str | None = None) -> str:
    """Baca berkas teks dari disk lalu decode dengan ``decode_bytes``.

    Raises:
        InputError: Berkas tidak bisa dibuka atau di-decode.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise InputError(f"tidak bisa membaca {path}: {exc.strerror or exc}") from exc
    return decode_bytes(raw, encoding)


def text_to_document(text: str, title: str, *, source_path: str = "") -> Document:
    """Ubah teks polos menjadi ``Document`` dengan satu paragraf per baris.

    Args:
        text: Teks yang sudah di-decode.
        title: Judul dokumen.
        source_path: Lokasi berkas asal, bila ada.
    """
    paragraphs = [Paragraph(text=line) for line in split_paragraphs(text)]
    return Document(title=title, paragraphs=paragraphs, source_path=source_path, fmt="txt")


def read_txt(path: Path, title: str | None = None, encoding: str | None = None) -> Document:
    """Baca berkas ``.txt``/``.md`` biasa (tanpa notasi Aozora).

    Args:
        path: Lokasi berkas.
        title: Judul; bawaan nama berkas tanpa sufiks.
        encoding: Paksa codec tertentu; ``None`` berarti deteksi otomatis.

    Raises:
        InputError: Berkas tidak bisa dibaca atau di-decode.
    """
    path = Path(path)
    text = read_text_file(path, encoding)
    return text_to_document(text, title or path.stem, source_path=str(path))
