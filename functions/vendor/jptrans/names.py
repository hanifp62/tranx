"""Pemisahan nama keluarga, nama depan, dan bacaan nama orang Jepang.

Modul ini menyatukan aturan struktur nama diri Jepang yang sebelumnya tersebar
di ``ner``, ``gender``, ``style``, dan ``pipeline`` agar batas marga (1-3 kanji)
dan nama depan konsisten di seluruh pipa.
"""

from __future__ import annotations

import logging
import re

from . import data
from .textnorm import is_kanji

logger = logging.getLogger(__name__)

MAX_SURNAME_CHARS = 3
_SPACE_RE = re.compile(r"[\s\u3000・]+")


def ambiguous_given_name(surface: str) -> bool:
    """Periksa apakah tulisan ``given_names.json`` juga punya bacaan lain di data."""
    given = data.given_names().get(surface)
    if given is None:
        return False
    return any(
        reading != given["reading"]
        for reading in data.name_word_readings().get(surface, ())
    )


def has_surname_head(surface: str) -> bool:
    """Apakah ``surface`` diawali nama keluarga yang sah diikuti nama depan.

    Marga 2-3 kanji diterima bila masih ada sisa karakter (``佐藤恒治``).
    Marga 1 kanji (``原``, ``関``, ``森``) terlalu sering mengawali kata umum
    (``原画監督``, ``関連会社社長``), sehingga hanya diterima bila sisanya dikenal
    sebagai nama depan di ``given_names.json`` (``森健太``).
    """
    surnames = data.surnames()
    given_names = data.given_names()
    for size in (3, 2):
        if len(surface) > size and surface[:size] in surnames:
            return True
    return (
        len(surface) > 1
        and surface[:1] in surnames
        and surface[1:] in given_names
    )


def split_family_reading(surface: str, reading: str) -> str:
    """Sisipkan spasi di antara bacaan marga dan nama depan bila belum berspasi."""
    if not reading or " " in reading or "\u3000" in reading:
        return reading
    surnames = data.surnames()
    for size in (3, 2, 1):
        family = surnames.get(surface[:size], "")
        if (
            len(surface) > size
            and family
            and reading.startswith(family)
            and len(reading) > len(family)
        ):
            return f"{family} {reading[len(family):]}"
    return reading


def given_part(surface: str, reading: str = "") -> tuple[str, str]:
    """Potong marga yang dikenal dari depan tulisan nama dan bacaannya."""
    surnames = data.surnames()
    if surface in surnames:
        return "", ""
    parts = _SPACE_RE.split(reading.strip()) if reading.strip() else []
    for size in range(min(MAX_SURNAME_CHARS, len(surface) - 1), 0, -1):
        head = surface[:size]
        if head not in surnames:
            continue
        if len(parts) > 1:
            return surface[size:], parts[-1]
        family = surnames[head]
        rest = reading[len(family):] if reading.startswith(family) else ""
        return surface[size:], rest
    return surface, parts[-1] if parts else ""


def split_known_full_name(surface: str) -> tuple[str, str, str] | None:
    """Urai nama lengkap kanji menjadi ``(marga, nama_depan, bacaan_lengkap)``.

    Hanya mengembalikan hasil bila ``surface`` seluruhnya kanji (>= 3 huruf),
    bukan kata tunggal yang sudah ada di kamus, dan hanya memiliki TEPAT SATU
    titik potong ``marga + nama_depan`` yang tidak ambigu. Dengan ini nama umum
    seperti ``山田太郎`` atau ``佐藤美咲`` tetap bisa dirender secara luring
    tanpa memanggil mesin penerjemah.
    """
    if len(surface) < 3 or not all(is_kanji(ch) for ch in surface):
        return None
    surnames = data.surnames()
    given_names = data.given_names()
    if (
        surface in surnames
        or surface in given_names
        or surface in data.places()
        or surface in data.name_word_readings()
    ):
        return None
    matches: list[tuple[str, str, str]] = []
    for size in (3, 2, 1):
        if len(surface) <= size:
            continue
        family_part = surface[:size]
        given = surface[size:]
        if size == 1 and len(given) < 2:
            continue
        if (
            family_part in surnames
            and given in given_names
            and not ambiguous_given_name(given)
        ):
            given_reading = given_names[given].get("reading", "")
            if given_reading:
                matches.append(
                    (family_part, given, f"{surnames[family_part]} {given_reading}")
                )
    return matches[0] if len(matches) == 1 else None
