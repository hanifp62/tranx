"""Kelas karakter Jepang dan normalisasi kunci pencarian.

Modul ini menjadi satu-satunya tempat rentang Unicode Jepang didefinisikan,
sehingga deteksi entitas, masking, dan romanisasi memakai definisi yang sama.

Konstanta ``HIRAGANA``, ``KATAKANA``, dan ``KANJI`` berisi *isi* kelas
karakter regex tanpa kurung siku, agar bisa digabung::

    re.compile(f"[{KANJI}{KATAKANA}]+")

Prinsip penting: teks asli dokumen tidak pernah diubah. Normalisasi (misalnya
katakana setengah lebar menjadi lebar penuh) hanya dipakai untuk membuat
kunci pencarian glosarium lewat ``search_key``.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Blok Hiragana tanpa U+3040 (tidak terpakai). Termasuk ゝゞ dan tanda ゛゜.
HIRAGANA = "ぁ-ゟ"

# Katakana lebar penuh (termasuk ・ dan ー), Katakana Phonetic Extensions,
# dan katakana setengah lebar FF65-FF9F (･ sampai ﾟ).
KATAKANA = "ァ-ヿㇰ-ㇿ･-ﾟ"

# CJK Unified Ideographs, Ext A, Compatibility, Ext B sampai J, ditambah
# 々〆〇 dan ヶ yang di Aozora dan furigana diperlakukan sebagai kanji (一ヶ月).
# Batas atas 3347F (bukan 3134F) agar Ext H dan J ikut; lihat LAPORAN_RISET 4.2.
KANJI = "㐀-䶿一-鿿豈-﫿\U00020000-\U0003347F々〆〇ヶ"

# Huruf katakana: tanpa ・ (pemisah) dan ー (tanda panjang).
_KATAKANA_LETTER = "ァ-ヺヽ-ヿㇰ-ㇿｦ-ｯｱ-ﾟ"
_KATAKANA_LONG = "ーｰ"
_KATAKANA_DOT = "・･"
_HIRAGANA_LETTER = "ぁ-ゖゝ-ゟ"

KANJI_RE = re.compile(f"[{KANJI}]+")
"""Run satu atau lebih kanji berturut-turut (``findall`` memberi tiap run)."""

KANA_RE = re.compile(f"[{HIRAGANA}{KATAKANA}]+")
"""Run satu atau lebih kana (hiragana atau katakana)."""

KATAKANA_RUN_RE = re.compile(
    f"[{_KATAKANA_LETTER}](?:[{_KATAKANA_LETTER}{_KATAKANA_LONG}]"
    f"|[{_KATAKANA_DOT}](?=[{_KATAKANA_LETTER}]))+"
)
"""Kata katakana minimal 2 karakter; ・ hanya di tengah, ー boleh di tengah/akhir."""

_HIRAGANA_CHAR_RE = re.compile(f"[{HIRAGANA}]")
_KATAKANA_CHAR_RE = re.compile(f"[{KATAKANA}]")
_KANJI_CHAR_RE = re.compile(f"[{KANJI}]")
_JAPANESE_LETTER_RE = re.compile(f"[{_HIRAGANA_LETTER}{_KATAKANA_LETTER}{KANJI}]")
_HALFWIDTH_KANA_RE = re.compile("[･-ﾟ]+")

# Hiragana ぁ-ゖ dan ゝゞ berselisih tepat 0x60 dari padanan katakananya.
_HIRA_TO_KATA = {code: code + 0x60 for code in (*range(0x3041, 0x3097), 0x309D, 0x309E)}
_KATA_TO_HIRA = {kata: hira for hira, kata in _HIRA_TO_KATA.items()}

# shift_jis men-decode 0x8160 menjadi 〜 (U+301C), cp932 menjadi ～ (U+FF5E).
_WAVE_DASH_TABLE = str.maketrans({"～": "〜"})


def is_kanji(ch: str) -> bool:
    """Periksa apakah satu karakter adalah kanji (termasuk 々〆〇ヶ).

    Args:
        ch: Satu karakter. String dengan panjang lain selalu ``False``.

    Returns:
        ``True`` bila ``ch`` berada di rentang ``KANJI``.
    """
    return len(ch) == 1 and _KANJI_CHAR_RE.match(ch) is not None


def is_hiragana(ch: str) -> bool:
    """Periksa apakah satu karakter adalah hiragana.

    Args:
        ch: Satu karakter.

    Returns:
        ``True`` bila ``ch`` berada di blok Hiragana.
    """
    return len(ch) == 1 and _HIRAGANA_CHAR_RE.match(ch) is not None


def is_katakana(ch: str) -> bool:
    """Periksa apakah satu karakter adalah katakana (termasuk ー, ・, setengah lebar).

    Args:
        ch: Satu karakter.

    Returns:
        ``True`` bila ``ch`` berada di rentang ``KATAKANA``.
    """
    return len(ch) == 1 and _KATAKANA_CHAR_RE.match(ch) is not None


def is_kana(ch: str) -> bool:
    """Periksa apakah satu karakter adalah hiragana atau katakana.

    Args:
        ch: Satu karakter.

    Returns:
        ``True`` bila ``ch`` hiragana atau katakana.
    """
    return is_hiragana(ch) or is_katakana(ch)


def is_hiragana_text(text: str) -> bool:
    """Periksa apakah teks berupa kata hiragana, misalnya bacaan furigana ``さとう れん``.

    Args:
        text: Teks sembarang; spasi biasa dan U+3000 diabaikan.

    Returns:
        ``True`` bila tidak kosong dan semua karakter lainnya hiragana.
    """
    return _only(text, is_hiragana)


def is_kana_text(text: str) -> bool:
    """Periksa apakah teks hanya berisi kana (hiragana/katakana, termasuk ー) dan spasi.

    Args:
        text: Teks sembarang; spasi biasa dan U+3000 diabaikan.

    Returns:
        ``True`` bila tidak kosong dan semua karakter lainnya kana.
    """
    return _only(text, is_kana)


def _only(text: str, predicate: Callable[[str], bool]) -> bool:
    letters = text.replace(" ", "").replace("\u3000", "")
    return bool(letters) and all(predicate(ch) for ch in letters)


def widen_halfwidth_kana(text: str) -> str:
    """Ubah katakana setengah lebar menjadi lebar penuh (ﾃｽﾄ → テスト, ｶﾞ → ガ).

    NFKC hanya diterapkan pada run setengah lebar, sehingga karakter lain
    seperti ① atau Ａ tidak ikut berubah.

    Args:
        text: Teks sembarang.

    Returns:
        Salinan teks dengan katakana setengah lebar yang sudah dilebarkan.
    """
    return _HALFWIDTH_KANA_RE.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)


def narrow_katakana(text: str) -> str:
    """Ubah katakana lebar penuh menjadi setengah lebar (アリス → ｱﾘｽ, ガ → ｶﾞ).

    Kebalikan ``widen_halfwidth_kana`` untuk katakana; hiragana, kanji, dan
    karakter lain tidak berubah. Dipakai ``protect`` agar teks OCR atau komik
    yang memakai katakana setengah lebar tetap cocok dengan glosarium.

    Args:
        text: Teks sembarang.

    Returns:
        Salinan teks dengan katakana yang sudah disempitkan.
    """
    return text.translate(_FULL_TO_HALF)


def _full_to_half_table() -> dict[int, str]:
    """Tabel katakana lebar penuh → setengah lebar, termasuk ﾞ/ﾟ untuk huruf bersuara."""
    table = {"・": "\uff65"}
    for code in range(0xFF66, 0xFF9E):
        half = chr(code)
        table.setdefault(unicodedata.normalize("NFKC", half), half)
        for mark in ("\uff9e", "\uff9f"):
            voiced = unicodedata.normalize("NFKC", half + mark)
            if len(voiced) == 1:
                table.setdefault(voiced, half + mark)
    return {ord(full): half for full, half in table.items()}


_FULL_TO_HALF = _full_to_half_table()


def search_key(text: str) -> str:
    """Buat kunci pencarian glosarium yang ternormalisasi.

    Hanya dua normalisasi yang dilakukan: katakana setengah lebar dilebarkan
    dan ～ (U+FF5E) disamakan dengan 〜 (U+301C). Teks asli tidak diubah;
    fungsi ini mengembalikan string baru yang hanya dipakai sebagai kunci.

    Args:
        text: Tulisan entitas atau potongan teks.

    Returns:
        Kunci pencarian.
    """
    return widen_halfwidth_kana(text).translate(_WAVE_DASH_TABLE)


def hira_to_kata(s: str) -> str:
    """Ubah hiragana menjadi katakana; karakter lain dibiarkan.

    Args:
        s: Teks sembarang.

    Returns:
        Teks dengan hiragana yang sudah menjadi katakana (ゝゞ menjadi ヽヾ).
    """
    return s.translate(_HIRA_TO_KATA)


def kata_to_hira(s: str) -> str:
    """Ubah katakana lebar penuh menjadi hiragana; karakter lain dibiarkan.

    Katakana tanpa padanan hiragana satu karakter (ヷヸヹヺ, ー, ・) tidak diubah.

    Args:
        s: Teks sembarang.

    Returns:
        Teks dengan katakana yang sudah menjadi hiragana.
    """
    return s.translate(_KATA_TO_HIRA)


def strip_diacritics(text: str) -> str:
    """Buang tanda diakritik (makron, aksen) lewat dekomposisi Unicode NFD."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def contains_japanese(text: str) -> bool:
    """Periksa apakah teks memuat huruf Jepang (kana atau kanji).

    Tanda baca seperti ー, ・, 「」, atau 。 saja tidak dihitung, sehingga
    kalimat ``・・・`` atau ``「……」`` tidak perlu dikirim ke mesin penerjemah.

    Args:
        text: Teks sembarang.

    Returns:
        ``True`` bila ada minimal satu huruf hiragana, katakana, atau kanji.
    """
    return _JAPANESE_LETTER_RE.search(text) is not None



# BOM yang menentukan encoding berkas Unicode secara pasti (urutan: UTF-8 dulu).
_UNICODE_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def decode_unicode_text(raw: bytes) -> str:
    """Decode berkas JSON/teks Unicode yang mungkin disimpan Notepad Windows.

    Notepad lama menyimpan "UTF-8" dengan BOM dan "Unicode" sebagai UTF-16
    ber-BOM; ``json.loads`` menolak keduanya. BOM UTF-8 dibuang, BOM UTF-16
    (LE atau BE) menentukan codec, dan tanpa BOM byte harus UTF-8 sah.
    Encoding lama seperti cp932 sengaja tidak ditebak: berkas konfigurasi
    dan glosarium selalu Unicode.

    Args:
        raw: Isi berkas mentah.

    Returns:
        Teks tanpa BOM; baris baru tidak diubah.

    Raises:
        UnicodeDecodeError: Byte bukan UTF-8/UTF-16 yang sah.
    """
    for bom, codec in _UNICODE_BOMS:
        if raw.startswith(bom):
            return raw.decode(codec)
    return raw.decode("utf-8")
