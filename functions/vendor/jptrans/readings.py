"""Penyelesaian bacaan kanji, validasi fonetis nama dari mesin, dan peta masking.

Modul ini menangani seluruh tahap melengkapi bacaan nama orang, tempat, dan
istilah majemuk sebelum kalimat dimasking oleh ``protect.EntityMatcher``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from . import data
from .glossary import STRONG_SOURCE_MARK, USER_SOURCE, Glossary, builtin_entries, strong_source
from .models import PERSON, PLACE, GlossaryEntry
from .names import ambiguous_given_name, split_family_reading, split_known_full_name
from .ner import ADMIN_UNIT_CHARS, MUNICIPALITY_SUFFIXES, is_time_word_place
from .phonetic import is_hepburn_echo, is_near_echo, looks_romanized, matches_reading
from .romaji import MODES, foreign_spelling, is_latin, looks_japanese, romanize_name
from .style import is_katakana_name
from .textnorm import (
    is_hiragana_text,
    is_kanji,
    kata_to_hira,
    strip_diacritics,
    widen_halfwidth_kana,
)

logger = logging.getLogger(__name__)

NAME_LOOKUP_KINDS = frozenset({PERSON})
MIN_PLACE_LOOKUP_KANJI = 2
MAX_NAME_CHARS = 40
MAX_NAME_WORDS = 3
SINGLE_WORD_NAME_CHARS = 2
MAX_CANDIDATE_READINGS = 256
MIN_SINGLE_KANJI_READING = 2

_SOKUON_ROWS = "かきくけこさしすせそたちつてとはひふへほ"
_SMALL_KANA = frozenset("ゃゅょぁぃぅぇぉ")
_SOKUON_BEFORE = {
    "つ": _SOKUON_ROWS,
    "ち": _SOKUON_ROWS,
    "く": "かきくけこ",
    "き": "かきくけこ",
}
_HANDAKU = str.maketrans("はひふへほ", "ぱぴぷぺぽ")
ITERATION_MARK = "々"
_KANJI_VARIANT_TABLE = str.maketrans(dict(data.KANJI_VARIANTS))
_RENDAKU = str.maketrans(
    "かきくけこさしすせそたちつてとはひふへほ",
    "がぎぐげござじずぜぞだぢづでどばびぶべぼ",
)
MAX_KNOWN_PIECE = 4
COMPOUND_KANJI = 4
_NAME_PART_RE = re.compile(r"[\s\u3000・]+")
_Partial = tuple[str, str, bool]


def masking_map(glossary: Glossary, ruby: Mapping[str, str]) -> dict[str, GlossaryEntry]:
    """Bangun peta tulisan -> entri untuk masking (tempat bawaan + glosarium judul)."""
    builtin = Glossary("builtin", builtin_entries()).surface_map()
    confirmed = [
        entry
        for entry in glossary.entries(confirmed_only=True)
        if entry.source == USER_SOURCE or not is_time_word_place(entry.surface)
    ]
    known = known_readings(confirmed, ruby)
    completed: dict[str, GlossaryEntry] = {}
    for entry in confirmed:
        done = complete_reading(entry, ruby)
        if done.kind != PERSON:
            split = split_compound_reading(done.surface, done.reading, known)
            done = replace(done, reading=split) if split != done.reading else done
        completed[entry.surface] = done
    own = {
        key: completed[entry.surface]
        for key, entry in glossary.surface_map().items()
        if entry.surface in completed
    }
    stems = {surface: admin_stem_entry(entry) for surface, entry in completed.items()}
    own = {key: stems[entry.surface] or entry for key, entry in own.items()}
    return {**builtin, **own}


def admin_stem_entry(entry: GlossaryEntry) -> GlossaryEntry | None:
    """Salinan kerja entri kota bersufiks (``松本市``) yang belum berbacaan."""
    surface = entry.surface
    if (
        entry.kind != PLACE
        or entry.reading
        or entry.romaji
        or entry.render_id
        or entry.render_en
        or len(surface) < 2
        or not surface.endswith(MUNICIPALITY_SUFFIXES)
        or not all(is_kanji(ch) for ch in surface)
    ):
        return None
    stem = surface[:-1]
    places = data.places()
    if len(stem) < MIN_PLACE_LOOKUP_KANJI and stem not in places:
        return None
    if (
        stem[0] in ADMIN_UNIT_CHARS
        or "市" in stem
        or "区" in stem
        or any(
            ch in ADMIN_UNIT_CHARS and stem[:index] in places
            for index, ch in enumerate(stem)
            if index
        )
    ):
        return None
    known = dict(data.surnames())
    known.update((key, place["reading"]) for key, place in places.items())
    return replace(entry, surface=stem, reading=known.get(stem, ""), aliases=())


def is_admin_stem(key: str, entry: GlossaryEntry) -> bool:
    """Kunci peta masking adalah tulisan entri tempat + 市/区/町/村."""
    return (
        entry.kind == PLACE
        and len(key) == len(entry.surface) + 1
        and key.startswith(entry.surface)
        and key.endswith(MUNICIPALITY_SUFFIXES)
    )


def complete_reading(entry: GlossaryEntry, ruby: Mapping[str, str]) -> GlossaryEntry:
    """Isi ``reading`` yang kosong dari furigana, kamus marga/nama depan, atau gabungan."""
    reading = entry.reading
    doc_ruby = ruby.get(entry.surface, "")
    has_doc_ruby = is_hiragana_text(doc_ruby)
    if not reading:
        if has_doc_ruby:
            reading = doc_ruby
        else:
            reading = data.surnames().get(entry.surface, "")
        if not reading and entry.kind == PERSON and not ambiguous_given_name(entry.surface):
            reading = data.given_names().get(entry.surface, {}).get("reading", "")
        if not reading and entry.kind == PERSON:
            full = split_known_full_name(entry.surface)
            if full is not None:
                reading = full[2]
    if entry.kind == PERSON:
        reading = split_family_reading(entry.surface, reading)
    if has_doc_ruby and "engine" in entry.source and entry.romaji:
        return replace(entry, reading=reading, romaji="")
    return replace(entry, reading=reading) if reading != entry.reading else entry


def given_fallbacks(
    entries: Iterable[GlossaryEntry],
    resolved: Mapping[str, GlossaryEntry],
    mode: str,
) -> dict[str, GlossaryEntry]:
    """Cadangan bacaan kamus untuk nama ``ambiguous_given_name`` bila mesin gagal."""
    found: dict[str, GlossaryEntry] = {}
    for entry in entries:
        if (
            entry.kind != PERSON
            or entry.reading
            or entry.romaji
            or not ambiguous_given_name(entry.surface)
        ):
            continue
        done = resolved.get(entry.surface)
        if done is None:
            reading = data.given_names()[entry.surface]["reading"]
            found[entry.surface] = replace(entry, reading=reading)
            continue
        spelled = _reading_spelling(done.romaji, candidate_readings(entry.surface), mode)
        if spelled:
            found[entry.surface] = replace(done, romaji=spelled)
    return found


def known_readings(
    entries: Iterable[GlossaryEntry], ruby: Mapping[str, str]
) -> dict[str, str]:
    """Peta tulisan -> bacaan tanpa spasi yang diketahui dari data proyek dan dokumen."""
    known = dict(data.surnames())
    known.update((surface, place["reading"]) for surface, place in data.places().items())
    known.update(
        (surface, reading)
        for surface, reading in ruby.items()
        if is_hiragana_text(reading)
    )
    known.update((entry.surface, entry.reading) for entry in entries if entry.reading)
    return {
        surface: reading
        for surface, reading in known.items()
        if reading and not _NAME_PART_RE.search(reading)
    }


def split_compound_reading(
    surface: str, reading: str, known: Mapping[str, str]
) -> str:
    """Pisah bacaan istilah 4 kanji menjadi dua kata bila kedua paruh 2+2 dikenal."""
    if (
        len(surface) != COMPOUND_KANJI
        or not all(is_kanji(ch) for ch in surface)
        or not reading
        or _NAME_PART_RE.search(reading)
    ):
        return reading
    half = COMPOUND_KANJI // 2
    head = kata_to_hira(known.get(surface[:half], ""))
    tail = kata_to_hira(known.get(surface[half:], ""))
    if head and tail and head + tail == kata_to_hira(reading):
        return f"{reading[:len(head)]} {reading[len(head):]}"
    return reading


def candidate_readings(surface: str) -> list[str]:
    """Daftar bacaan hiragana yang mungkin untuk tulisan nama kanji dari data proyek."""
    surface = surface.translate(_KANJI_VARIANT_TABLE)
    known = known_word_readings(surface)
    if known:
        return list(known)
    if len(surface) == 1:
        return _single_kanji_readings(surface)
    strict, loose = _combine_pieces(surface)
    names = data.name_readings()
    mixed = [reading for reading in loose if reading in names]
    return list(dict.fromkeys(strict + mixed))


def _single_kanji_readings(kanji: str) -> list[str]:
    return [
        reading
        for reading in data.kanji_reading_kinds().get(kanji, {})
        if len(reading) >= MIN_SINGLE_KANJI_READING
    ]


def _combine_pieces(surface: str) -> tuple[list[str], list[str]]:
    expanded = _expand_iteration_mark(surface)
    words = dict(data.surnames())
    words.update((key, place["reading"]) for key, place in data.places().items())
    kinds = data.kanji_reading_kinds()
    tables: dict[bool, list[list[_Partial]]] = {
        strict: [[("", "", False)]] + [[] for _ in surface]
        for strict in (True, False)
    }
    dropped = 0
    for end in range(1, len(surface) + 1):
        for start in range(max(0, end - MAX_KNOWN_PIECE), end):
            options = _piece_options(
                surface[start:end], expanded[start:end], start, words, kinds
            )
            for strict, found in tables.items():
                dropped += _extend_pieces(found[start], found[end], options, strict)
    if dropped:
        logger.debug(
            "rangkaian bacaan dibuang: %d (batas %d per posisi, nama %d karakter)",
            dropped,
            MAX_CANDIDATE_READINGS,
            len(surface),
        )
    strict_found, loose_found = (
        list(dict.fromkeys(item[0] for item in tables[strict][-1]))
        for strict in (True, False)
    )
    return strict_found, loose_found


def _extend_pieces(
    heads: list[_Partial],
    target: list[_Partial],
    options: list[_Partial],
    strict: bool,
) -> int:
    dropped = 0
    for option, kind, ambiguous in options:
        for head, last_kind, last_ambiguous in heads:
            if strict and not _kinds_agree(
                (last_kind, last_ambiguous), (kind, ambiguous)
            ):
                continue
            for reading in _joined(head, last_kind, option, kind):
                item = (reading, kind, ambiguous)
                if item in target:
                    continue
                if len(target) < MAX_CANDIDATE_READINGS:
                    target.append(item)
                else:
                    dropped += 1
    return dropped


def _joined(head: str, head_kind: str, option: str, kind: str) -> tuple[str, ...]:
    plain = head + option
    if head_kind != data.ON or kind != data.ON or not head or not option:
        return (plain,)
    if head[-1] == "ん" and option[0] in "はひふへほ":
        return plain, head + option[0].translate(_HANDAKU) + option[1:]
    if option[0] not in _SOKUON_BEFORE.get(head[-1], ""):
        return (plain,)
    return plain, head[:-1] + "っ" + option[0].translate(_HANDAKU) + option[1:]


def known_word_readings(surface: str) -> tuple[str, ...]:
    """Bacaan tulisan yang dikenal utuh di data proyek, atau tuple kosong."""
    forms = dict.fromkeys((surface, _expand_iteration_mark(surface)))
    found: list[str] = []
    places = data.places()
    given = data.given_names()
    for form in forms:
        if form in data.surnames():
            found.append(data.surnames()[form])
        if form in places:
            found.append(places[form]["reading"])
        if form in given:
            found.append(given[form]["reading"])
        found.extend(data.name_word_readings().get(form, ()))
    return tuple(dict.fromkeys(reading for reading in found if reading))


def _expand_iteration_mark(surface: str) -> str:
    chars = list(surface)
    for index in range(1, len(chars)):
        if chars[index] == ITERATION_MARK:
            chars[index] = chars[index - 1]
    return "".join(chars)


def _piece_options(
    piece: str,
    expanded: str,
    start: int,
    words: Mapping[str, str],
    kinds: Mapping[str, Mapping[str, str]],
) -> list[_Partial]:
    options: list[_Partial] = []
    if piece in words:
        options.append((words[piece], "", False))
    if len(expanded) == 1 and expanded in kinds:
        readings = kinds[expanded]
        ambiguous = {data.ON, data.KUN} <= set(readings.values())
        for reading, kind in readings.items():
            options.append((reading, kind, ambiguous))
            voiced = reading.translate(_RENDAKU) if start else reading
            if voiced[:1] != reading[:1]:
                options.append((voiced[:1] + reading[1:], kind, ambiguous))
    return options


def _kinds_agree(left: tuple[str, bool], right: tuple[str, bool]) -> bool:
    (left_kind, left_ambiguous), (right_kind, right_ambiguous) = left, right
    if not left_kind or not right_kind or left_kind == right_kind:
        return True
    return left_ambiguous and right_ambiguous


def needs_foreign_lookup(entry: GlossaryEntry, lang: str) -> bool:
    """Apakah ejaan nama asing katakana ini perlu ditanyakan ke mesin."""
    if (
        entry.kind not in NAME_LOOKUP_KINDS
        or entry.romaji
        or entry.render_for(lang)
        or not is_katakana_name(entry)
    ):
        return False
    surface = widen_halfwidth_kana(entry.surface)
    parts = [part for part in _NAME_PART_RE.split(surface) if part]
    return any(
        not foreign_spelling(part) and not looks_japanese(part) for part in parts
    )


def merge_foreign_answer(surface: str, name: str, mode: str) -> str | None:
    """Gabungkan ejaan nama asing tervalidasi dengan romanisasi biasa per bagian."""
    parts = [
        part for part in _NAME_PART_RE.split(widen_halfwidth_kana(surface)) if part
    ]
    words = name.split()
    echoes = [
        is_hepburn_echo(part, word)
        or (looks_japanese(part) and is_near_echo(part, word))
        for part, word in zip(parts, words)
    ]
    if all(echoes):
        return None
    return " ".join(
        foreign_spelling(part) or romanize_name(part, mode) if echo else word
        for part, word, echo in zip(parts, words, echoes)
    )


def kanji_spellings(
    unknown: list[GlossaryEntry],
    outputs: Sequence[str],
    source: str,
    mode: str = "macron",
) -> tuple[dict[str, GlossaryEntry], dict[str, GlossaryEntry]]:
    """Saring jawaban mesin untuk nama kanji dan kota tanpa bacaan dengan ``clean_name``."""
    stored: dict[str, GlossaryEntry] = {}
    working: dict[str, GlossaryEntry] = {}
    for entry, raw in zip(unknown, outputs):
        name = clean_name(
            raw, entry.surface, candidate_readings(entry.surface), mode=mode
        )
        if name is None and entry.source == USER_SOURCE:
            name = user_name_spelling(raw, entry.surface)
        if name is None:
            logger.info(
                "ejaan dari %s ditolak untuk satu nama (%d karakter)", source, len(raw)
            )
            continue
        owner = USER_SOURCE if entry.source == USER_SOURCE else "engine"
        if STRONG_SOURCE_MARK in entry.source:
            owner = strong_source(owner)
        spelled = replace(entry, romaji=name, source=owner)
        if len(entry.surface) == 1:
            logger.debug(
                "ejaan nama satu kanji dari %s hanya dipakai di salinan kerja", source
            )
            working[entry.surface] = spelled
        else:
            stored[entry.surface] = spelled
    return stored, working


def clean_name(
    raw: str,
    surface: str = "",
    readings: Sequence[str] | None = None,
    *,
    mode: str | None = None,
) -> str | None:
    """Terima ejaan nama dari mesin hanya bila berupa nama Latin yang cocok bunyinya."""
    name = " ".join(raw.strip().strip(".。").split())
    words = name.split()
    limit = (
        1 if 0 < len(surface) <= SINGLE_WORD_NAME_CHARS else MAX_NAME_WORDS
    )
    if not is_latin(name) or len(name) > MAX_NAME_CHARS or len(words) > limit:
        return None
    lower = any(word[:1].islower() for word in words)
    if lower:
        if readings is None:
            return None
        name = " ".join(word[:1].upper() + word[1:] for word in words)
    if readings is not None and not _sounds_like_name(name, surface, readings, lower):
        return None
    if lower and mode and readings and len(words) == 1:
        name = _reading_spelling(name, readings, mode) or name
    return family_first(name, surface)


def _reading_spelling(
    name: str, readings: Sequence[str], mode: str
) -> str | None:
    bare = name.casefold()
    found = {
        romanize_name(reading, mode)
        for reading in readings
        if any(romanize_name(reading, other).casefold() == bare for other in MODES)
    }
    return found.pop() if len(found) == 1 else None


def user_name_spelling(raw: str, surface: str) -> str | None:
    """Ejaan untuk entri glosarium pengguna yang bacaannya jukujikun di luar data."""
    name = clean_name(raw, surface)
    if name is None or not looks_romanized(name):
        return None
    if any(word.casefold() in data.COMMON_ENGLISH_WORDS for word in name.split()):
        return None
    if len(surface) == 1 and not _starts_like_reading(name, surface):
        return None
    return name


def _starts_like_reading(name: str, kanji: str) -> bool:
    readings = data.kanji_readings().get(kanji, ())
    if not readings:
        return True
    word = name.split()[0].casefold()
    for reading in readings:
        mora = (
            reading[:2]
            if reading[1:2] and reading[1:2] in _SMALL_KANA
            else reading[:1]
        )
        if any(
            word.startswith(romanize_name(mora, mode).casefold()) for mode in MODES
        ):
            return True
    return False


def _sounds_like_name(
    name: str, surface: str, readings: Sequence[str], lower: bool
) -> bool:
    words = name.split()
    single = len(surface) == 1 and not known_word_readings(
        surface.translate(_KANJI_VARIANT_TABLE)
    )
    if single and name.casefold() in data.COMMON_ENGLISH_WORDS:
        return False
    if readings:
        orders = [name, " ".join(reversed(words))] if len(words) == 2 else [name]
        if any(
            matches_reading(reading, order)
            for reading in readings
            for order in orders
        ):
            return True
        return len(words) == 2 and _parts_sound_alike(words, surface)
    if any(word.casefold() in data.COMMON_ENGLISH_WORDS for word in words):
        return False
    return not lower and not single and looks_romanized(name)


def _parts_sound_alike(words: Sequence[str], surface: str) -> bool:
    for cut in range(1, len(surface)):
        parts = (surface[:cut], surface[cut:])
        options = [candidate_readings(part) for part in parts]
        if not all(options):
            continue
        for first, second in (tuple(words), tuple(reversed(words))):
            if any(matches_reading(r, first) for r in options[0]) and any(
                matches_reading(r, second) for r in options[1]
            ):
                return True
    return False


def family_first(name: str, surface: str) -> str:
    """Ubah nama dua kata dari mesin ke urutan Jepang (keluarga dulu) bila terbukti."""
    words = name.split()
    if len(words) != 2:
        return name
    surnames = data.surnames()
    readings = [
        surnames[surface[:size]]
        for size in (3, 2, 1)
        if len(surface) > size and surface[:size] in surnames
    ]
    spellings = {
        strip_diacritics(romanize_name(reading, mode).casefold())
        for reading in readings
        for mode in MODES
    }
    first, second = (strip_diacritics(word.casefold()) for word in words)
    if second in spellings and first not in spellings:
        return f"{words[1]} {words[0]}"
    return name
