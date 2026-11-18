"""Aturan gaya subtitle/fansub: bentuk akhir nama, honorifik, urutan, sufiks, gloss.

``Renderer`` mengubah satu ``models.Slot`` (entri + honorifik + sufiks)
menjadi teks Latin final seperti ``Tanaka-san``, ``Bu Tanaka``,
``rumah Tanaka-san``, ``Stasiun Tokyo``, atau ``Rasengan (Bola Spiral)``.

Aturan disambiguasi kata kerja + ん terhadap nama berhonorifik dipisahkan ke
modul ``disambig`` dan diekspor ulang di sini demi kompatibilitas pemanggil.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from . import data
from .config import Config, effective_name_order
from .disambig import (
    DASH_BREAKS,
    HONORIFIC_SURFACES,
    PEOPLE_SUFFIXES,
    PLACE_KINDS,
    PLACE_SUFFIXES,
    SUFFIX_RULES,
    TITLE_WORDS,
    VERB_AFTER_CHARS,
    VERB_CONTEXT_CHARS,
    VERB_CONTEXT_TABLE,
    honorific_fits,
    honorific_names_person,
    honorific_proves_name,
    is_known_name,
    is_verb_stem,
    thing_head,
    verb_run_before_honorific,
)
from .models import PERSON, GlossaryEntry, Slot
from .romaji import romanize_foreign, romanize_name
from .textnorm import (
    KANJI_RE,
    KATAKANA_RUN_RE,
    is_kana_text,
    kata_to_hira,
    widen_halfwidth_kana,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DASH_BREAKS",
    "Gendered",
    "HONORIFIC_SURFACES",
    "LOCALIZED",
    "PEOPLE_SUFFIXES",
    "PLACE_KINDS",
    "PLACE_SUFFIXES",
    "Renderer",
    "SUFFIX_RULES",
    "TITLE_WORDS",
    "VERB_AFTER_CHARS",
    "VERB_CONTEXT_CHARS",
    "VERB_CONTEXT_TABLE",
    "can_render",
    "honorific_fits",
    "honorific_names_person",
    "honorific_proves_name",
    "is_katakana_name",
    "is_known_name",
    "is_verb_stem",
    "thing_head",
    "verb_run_before_honorific",
]

_SPACED_KATAKANA_RE = re.compile(
    f"{KATAKANA_RUN_RE.pattern}(?:[ \u3000]{KATAKANA_RUN_RE.pattern})*"
)
_HONORIFIC_HOUSE_RULE = ("rumah {name}", "{name}'s house")


@dataclass(frozen=True)
class Gendered:
    """Tiga templat sapaan menurut gender entri: laki-laki, perempuan, netral."""

    male: str
    female: str
    unknown: str

    @classmethod
    def same(cls, template: str) -> Gendered:
        """Templat yang sama untuk semua gender."""
        return cls(template, template, template)

    def pick(self, gender: str) -> str:
        """Pilih templat untuk ``gender`` (``m``, ``f``, atau kosong)."""
        return {"m": self.male, "f": self.female}.get(gender, self.unknown)


_NAME_ONLY = Gendered.same("{name}")

LOCALIZED: dict[str, dict[str, Gendered]] = {
    "id": {
        "san": Gendered("Pak {name}", "Bu {name}", "{name}"),
        "kun": _NAME_ONLY,
        "chan": _NAME_ONLY,
        "sama": Gendered("Tuan {name}", "Nona {name}", "{name}-sama"),
        "senpai": Gendered.same("Kak {name}"),
        "sensei": Gendered("Pak {name}", "Bu {name}", "{name}-sensei"),
        "dono": Gendered("Tuan {name}", "Nona {name}", "{name}-dono"),
        "shi": Gendered("Pak {name}", "Bu {name}", "{name}"),
        "tan": _NAME_ONLY,
        "cchi": _NAME_ONLY,
    },
    "en": {
        "san": Gendered("Mr. {name}", "Ms. {name}", "{name}"),
        "kun": _NAME_ONLY,
        "chan": _NAME_ONLY,
        "sama": Gendered("Lord {name}", "Lady {name}", "{name}-sama"),
        "senpai": _NAME_ONLY,
        "sensei": Gendered("Mr. {name}", "Ms. {name}", "{name}-sensei"),
        "dono": Gendered("Lord {name}", "Lady {name}", "{name}-dono"),
        "shi": Gendered("Mr. {name}", "Ms. {name}", "{name}"),
        "tan": _NAME_ONLY,
        "cchi": _NAME_ONLY,
    },
}


class Renderer:
    """Pembuat bentuk Latin final untuk tiap slot entitas dalam satu dokumen."""

    def __init__(self, cfg: Config, lang: str | None = None) -> None:
        self.cfg = cfg
        self.lang = lang or cfg.target_lang
        self.name_order = effective_name_order(cfg.name_order, self.lang)
        self.seen: set[str] = set()

    def base_name(self, entry: GlossaryEntry) -> str | None:
        """Nama dasar tanpa honorifik dan sufiks."""
        return _base_name(
            entry, self.lang, self.cfg.romanization, self.cfg.foreign_names
        )

    def apply_order(self, name: str, entry: GlossaryEntry) -> str:
        """Balik nama orang dua kata berkanji untuk urutan ``western``."""
        words = name.split()
        if (
            entry.kind == PERSON
            and self.name_order == "western"
            and len(words) == 2
            and KANJI_RE.search(entry.surface)
        ):
            return f"{words[1]} {words[0]}"
        return name

    def honorific(self, name: str, hon: str, entry: GlossaryEntry) -> str:
        """Pasang honorifik sesuai ``cfg.honorific_style``."""
        style = self.cfg.honorific_style
        if not hon or style == "drop":
            return name
        localized = LOCALIZED[self.lang].get(hon)
        if style == "keep" or localized is None:
            return f"{name}-{hon}"
        return localized.pick(entry.gender).format(name=name)

    def apply_suffix(self, name: str, suffix: str, *, has_honorific: bool = False) -> str:
        """Render sufiks Jepang (達, 家, 駅, ...) di sekitar nama."""
        if not suffix:
            return name
        if has_honorific and suffix == "家":
            rule: tuple[str, str] | None = _HONORIFIC_HOUSE_RULE
        else:
            rule = SUFFIX_RULES.get(suffix)
        if rule is None:
            logger.debug("sufiks %r tidak punya aturan; ditempel apa adanya", suffix)
            return name + suffix
        template = rule[0] if self.lang == "id" else rule[1]
        return template.format(name=name)

    def __call__(self, slot: Slot) -> str:
        """Render lengkap: nama -> urutan -> honorifik -> sufiks -> gloss pertama."""
        parts = [self._render_part(slot.entry, slot.honorific, slot.suffix)]
        parts += [
            self._render_part(entry, "", suffix)
            for entry, suffix in reversed(slot.parents)
        ]
        return ", ".join(parts)

    def _render_part(self, entry: GlossaryEntry, hon: str, suffix: str) -> str:
        base = self.base_name(entry)
        if base is None:
            name = f"{entry.surface}-{hon}" if hon else entry.surface
        else:
            ordered = (
                base if entry.render_for(self.lang) else self.apply_order(base, entry)
            )
            name = self.honorific(ordered, hon, entry)
        rendered = self.apply_suffix(name, suffix, has_honorific=bool(hon))
        return self._with_first_gloss(rendered, entry)

    def _with_first_gloss(self, text: str, entry: GlossaryEntry) -> str:
        first_time = entry.surface not in self.seen
        self.seen.add(entry.surface)
        gloss = entry.gloss_for(self.lang)
        if first_time and gloss and self.cfg.first_gloss:
            return f"{text} ({gloss})"
        return text


def can_render(entry: GlossaryEntry, lang: str) -> bool:
    """Periksa apakah entri punya bentuk Latin untuk bahasa ``lang``."""
    return _base_name(entry, lang, "macron") is not None


def _same_reading(reading: str, place_reading: str) -> bool:
    if not reading:
        return True
    return "".join(kata_to_hira(reading).split()) == place_reading


def is_katakana_name(entry: GlossaryEntry) -> bool:
    """Tulisan entri katakana dan bacaannya kosong atau sama dengan tulisan itu."""
    surface = widen_halfwidth_kana(entry.surface)
    if _SPACED_KATAKANA_RE.fullmatch(surface) is None:
        return False
    return not entry.reading or _bare_kana(entry.reading) == _bare_kana(surface)


def _bare_kana(text: str) -> str:
    return "".join(
        ch for ch in kata_to_hira(widen_halfwidth_kana(text)) if ch not in " 　・"
    )


def _base_name(
    entry: GlossaryEntry, lang: str, mode: str, foreign: str = "auto"
) -> str | None:
    explicit_target = entry.render_for(lang)
    if explicit_target:
        return explicit_target
    engine_kanji_guess = (
        "engine" in entry.source
        and bool(entry.reading)
        and KANJI_RE.search(entry.surface) is not None
    )
    if entry.romaji and not engine_kanji_guess:
        return entry.romaji
    place = data.places().get(entry.surface)
    if place is not None and _same_reading(entry.reading, place["reading"]):
        return place[lang]
    if foreign != "hepburn" and is_katakana_name(entry):
        return romanize_foreign(widen_halfwidth_kana(entry.surface), mode)
    if entry.reading:
        return romanize_name(entry.reading, mode)
    if entry.romaji:
        return entry.romaji
    if is_kana_text(entry.surface):
        return romanize_name(entry.surface, mode)
    return None
