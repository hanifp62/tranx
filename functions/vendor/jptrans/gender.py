"""Gender nama orang untuk koreksi kata ganti bahasa Inggris (he/she).

Mesin sering salah menebak kata ganti karena bahasa Jepang jarang menyebutnya
(Google: 美咲 → "checked his watch"). Modul ini hanya menentukan gender sebuah
entri; keputusan kapan kata ganti boleh diubah ada di ``pipeline.pronoun_gender``
dan pengubahannya di ``postprocess.fix_pronouns``.

Urutan sumber, yang pertama memberi jawaban menang:

1. Field ``gender`` glosarium: ``m`` atau ``f``. Nilai ``x``
   (``NEUTRAL_GENDER``) berarti pengguna sengaja menyatakan gender tidak
   diketahui, sehingga tidak ditebak sama sekali (mode ``localize`` dan hints LLM
   memperlakukannya seperti kosong).
2. ``data/given_names.json``: tulisan nama depan (nama keluarga dari
   ``surnames.json`` di depannya dipotong dulu: 朝倉美咲 → 美咲). Ini satu-satunya
   tebakan KUAT (``STRONG_ORIGINS``): hanya tebakan ini yang boleh disimpan ke
   glosarium (dan karena itu dipakai mode ``localize`` dan hints LLM). Nama
   uniseks di kamus (薫, 伊織) menghentikan pencarian dengan hasil "tidak
   diketahui".
3. Sinyal lemah, hanya untuk koreksi kata ganti saat dokumen diproses:

   - bacaan nama depan (ミサキ, 美沙紀 dibaca みさき) lewat indeks bacaan kamus.
     Bacaan yang tidak sepakat di kamus (まこと) atau lazim untuk kedua gender
     (``data.UNISEX_READINGS``: れい, はるか, いずみ) memberi "tidak diketahui";
   - huruf terakhir nama depan kanji (``FEMALE_SUFFIXES`` 子 奈 香 花 恵 →
     perempuan; ``MALE_SUFFIXES`` 郎 彦 → laki-laki), HANYA bila nama keluarga
     dikenal sudah dipotong di depannya (佐藤澄子). Tulisan tanpa nama keluarga
     dikenal (立花, 宇佐美, 益子) bisa saja nama keluarga di luar
     ``surnames.json``, jadi tidak ditebak. 美 sengaja tidak dipakai karena
     banyak nama laki-laki berakhiran 美 (正美, 克美, 勝美).

   Honorifik -kun (くん/君) tidak pernah menetapkan gender sendirian, tetapi
   membatalkan tebakan lemah "perempuan" (perempuan jarang dipanggil -kun di
   karya fiksi, jadi pertentangan berarti "tidak diketahui"). Karena tebakan
   lemah tidak disimpan, -kun dievaluasi ulang di setiap dokumen.

Tulisan yang seluruhnya nama keluarga dikenal (佐藤, 金子) tidak pernah ditebak:
nama keluarga tidak membawa gender.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from . import data
from .models import PERSON, GlossaryEntry
from .names import MAX_SURNAME_CHARS, given_part
from .textnorm import KANJI, is_kana_text, is_kanji, kata_to_hira, widen_halfwidth_kana

logger = logging.getLogger(__name__)

__all__ = [
    "FEMALE_SUFFIXES",
    "GENDERS",
    "GENDER_SOURCE_MARK",
    "MALE_SUFFIXES",
    "MAX_SURNAME_CHARS",
    "MIN_SUFFIX_NAME",
    "NEUTRAL_GENDER",
    "ORIGIN_GLOSSARY",
    "ORIGIN_NAMES",
    "ORIGIN_READING",
    "ORIGIN_SUFFIX",
    "STRONG_ORIGINS",
    "gender_source",
    "given_part",
    "infer_gender",
    "kun_surfaces",
]

GENDERS = ("m", "f")
NEUTRAL_GENDER = "x"
"""Nilai ``gender`` glosarium untuk "jangan ditebak": tidak diketahui secara sengaja."""
ORIGIN_GLOSSARY = "glossary"
ORIGIN_NAMES = "given_names"
ORIGIN_READING = "given_names_reading"
ORIGIN_SUFFIX = "kanji_suffix"
STRONG_ORIGINS = frozenset({ORIGIN_NAMES})
"""Asal tebakan yang cukup kuat untuk disimpan ke glosarium (lihat docstring modul)."""
GENDER_SOURCE_MARK = "+gender:"
"""Penanda di ``source`` entri glosarium otomatis yang gendernya hasil tebakan."""
FEMALE_SUFFIXES = frozenset("子奈香花恵")
MALE_SUFFIXES = frozenset("郎彦")
MIN_SUFFIX_NAME = 2
"""Nama depan sependek ini baru boleh ditebak dari huruf terakhirnya (子 saja bukan nama)."""
_KUN_TEMPLATE = "(?:{name})(?:くん|クン|君)(?![{kanji}])"
_SPACE_RE = re.compile(r"[\s\u3000・]+")


def infer_gender(entry: GlossaryEntry, *, kun: bool = False) -> tuple[str, str]:
    """Tentukan gender entri orang beserta asal keputusannya.

    Args:
        entry: Entri glosarium.
        kun: Nama ini dipanggil dengan -kun di dokumen (sinyal lemah).

    Returns:
        Pasangan ``(gender, origin)``: gender ``"m"``/``"f"`` atau ``""``,
        origin salah satu ``ORIGIN_*`` atau ``""`` bila tidak ada bukti.
    """
    if entry.gender in GENDERS:
        return entry.gender, ORIGIN_GLOSSARY
    if entry.gender == NEUTRAL_GENDER:
        return "", ORIGIN_GLOSSARY
    if entry.kind != PERSON:
        return "", ""
    surface = widen_halfwidth_kana(entry.surface)
    given, reading = given_part(surface, entry.reading)
    if not given:
        return "", ""
    reading_hira = _SPACE_RE.sub("", kata_to_hira(reading))
    known = data.given_names().get(given)
    if known is not None and (not reading_hira or reading_hira == known["reading"]):
        gender = known["gender"]
        if not gender:
            return "", ""
        if gender == "f" and kun and (
            len(given) == 1 or known["reading"] in data.UNISEX_READINGS
        ):
            return "", ""
        return gender, ORIGIN_NAMES
    by_reading = data.given_name_genders_by_reading()
    key = reading_hira or (
        _SPACE_RE.sub("", kata_to_hira(given)) if is_kana_text(given) else ""
    )
    if key in by_reading:
        return _weak(by_reading[key], ORIGIN_READING, kun)
    if given == surface:
        return "", ""
    return _suffix_gender(given, kun)


def kun_surfaces(text: str, surfaces: Iterable[str]) -> set[str]:
    """Tulisan nama yang di dokumen diikuti -kun (くん/君, tetapi bukan 君子 dsb.).

    Args:
        text: Seluruh teks dokumen.
        surfaces: Tulisan nama yang diperiksa.

    Returns:
        Himpunan tulisan yang dipanggil -kun minimal sekali.
    """
    found = set()
    for surface in surfaces:
        pattern = _KUN_TEMPLATE.format(name=re.escape(surface), kanji=KANJI)
        if surface and re.search(pattern, text):
            found.add(surface)
    return found


def gender_source(source: str, origin: str) -> str:
    """Nilai ``source`` untuk entri otomatis yang gendernya ditebak (idempoten).

    ``auto`` + ``given_names`` → ``auto+gender:given_names``, sehingga pengguna
    bisa melihat (``jptrans glossary show``) bahwa gender itu tebakan dan
    mengoreksinya.
    """
    if GENDER_SOURCE_MARK in source:
        return source
    return f"{source}{GENDER_SOURCE_MARK}{origin}"


def _suffix_gender(given: str, kun: bool) -> tuple[str, str]:
    """Sinyal lemah dari huruf terakhir nama depan kanji (setelah nama keluarga dipotong)."""
    if len(given) < MIN_SUFFIX_NAME or not all(is_kanji(ch) for ch in given):
        return "", ""
    last = given[-1]
    if last in FEMALE_SUFFIXES:
        return _weak("f", ORIGIN_SUFFIX, kun)
    if last in MALE_SUFFIXES:
        return _weak("m", ORIGIN_SUFFIX, kun)
    return "", ""


def _weak(gender: str, origin: str, kun: bool) -> tuple[str, str]:
    """Tebakan lemah; -kun membatalkan "perempuan" karena keduanya bertentangan."""
    if not gender or (gender == "f" and kun):
        return "", ""
    return gender, origin
