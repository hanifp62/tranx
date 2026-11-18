"""Orkestrasi terjemahan: dokumen masuk, ``TranslatedDocument`` keluar.

Pipeline ini menjadi pemilik tunggal tangga fallback antarmesin, cache, dan
siklus hidup glosarium. Penyelesaian bacaan kanji dipisahkan ke ``readings``
dan analisis wacana kata ganti/petunjuk LLM dipisahkan ke ``coref``.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from importlib.util import find_spec
from pathlib import Path
from types import TracebackType

from .cache import TranslationCache, make_key
from .config import Config
from .coref import (
    GENDER_LABELS,
    KIND_LABELS,
    NOT_SINGLE_PRONOUNS,
    OTHER_PERSON_WORDS,
    PARTNER_PHRASES,
    PARTNER_VERBS,
    QUOTE_CLOSERS,
    QUOTE_OPENERS,
    SPEAKER_QUOTES,
    explicit_pronoun,
    hint_lines,
    mark_speaker,
    narrative_part,
    person_forms,
    person_names,
    pronoun_gender,
    vocative_lead,
)
from .disambig import is_verb_stem
from .engines import ENGINE_FACTORIES, Engine, normalize_engine_names
from .engines.base import env_value, require_same_length
from .engines.mymemory import EMAIL_ENV
from .errors import AllEnginesFailed, EngineError, EngineUnavailable, QuotaExceeded
from .gender import STRONG_ORIGINS, gender_source, infer_gender, kun_surfaces
from .glossary import USER_SOURCE, Glossary, default_glossary_path, strong_source
from .models import (
    PERSON,
    STATUS_CACHED,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_PLAIN,
    STATUS_PRESUB,
    Document,
    GlossaryEntry,
    Masked,
    SentencePair,
    Slot,
    TranslatedDocument,
    TranslatedParagraph,
    split_format_tags,
    split_leading_tags,
    strip_format_tags,
)
from .ner import (
    attested_names,
    candidates_to_entries,
    detect_entities,
    honorific_name_counts,
    is_time_word_place,
    strong_name_counts,
)
from .net import RateLimiter, http_status
from .phonetic import validate_foreign_name
from .postprocess import (
    capitalize_first,
    fix_explicit_pronouns,
    fix_names,
    fix_pronouns,
    lower_after_comma,
    lower_after_vocative,
    proper_nouns,
    tidy,
)
from .protect import (
    EntityMatcher,
    check_presubstituted,
    missing_tokens,
    presubstitute,
    restore,
)
from .readers import read_text
from .readings import (
    MIN_PLACE_LOOKUP_KANJI,
    NAME_LOOKUP_KINDS,
    admin_stem_entry,
    ambiguous_given_name,
    candidate_readings,
    clean_name,
    complete_reading,
    family_first,
    given_fallbacks,
    is_admin_stem,
    kanji_spellings,
    known_readings,
    known_word_readings,
    masking_map,
    merge_foreign_answer,
    needs_foreign_lookup,
    split_compound_reading,
    user_name_spelling,
)
from .residue import looks_untranslated, residue_letters
from .segment import (
    attach_format_tags,
    chunk_long_text,
    make_batches,
    split_sentences,
    split_speaker_turns,
    unwrap_lines,
)
from .style import Renderer, can_render
from .textnorm import contains_japanese

logger = logging.getLogger(__name__)

__all__ = [
    "DEEPL_FREE_MONTHLY_CHARS",
    "GENDER_LABELS",
    "KIND_LABELS",
    "MYMEMORY_DAILY_CHARS",
    "MYMEMORY_DAILY_CHARS_EMAIL",
    "NOT_SINGLE_PRONOUNS",
    "OTHER_PERSON_WORDS",
    "PARTNER_PHRASES",
    "PARTNER_VERBS",
    "Progress",
    "QUOTE_CLOSERS",
    "QUOTE_OPENERS",
    "SPEAKER_FORMATS",
    "SPEAKER_QUOTES",
    "Translator",
    "admin_stem_entry",
    "ambiguous_given_name",
    "build_units",
    "candidate_readings",
    "clean_name",
    "complete_reading",
    "detect_new_entries",
    "drop_time_word_places",
    "estimate",
    "explicit_pronoun",
    "family_first",
    "hint_lines",
    "is_admin_stem",
    "janome_available",
    "join_pieces",
    "known_readings",
    "known_word_readings",
    "mark_speaker",
    "masking_map",
    "merge_foreign_answer",
    "narrative_part",
    "needs_foreign_lookup",
    "person_forms",
    "person_names",
    "pronoun_gender",
    "split_compound_reading",
    "split_turns",
    "tokens_intact",
    "unique_entries",
    "user_name_spelling",
    "vocative_lead",
]

SOURCE_LANG = "ja"
NAME_LOOKUP_LANG = "en"
MIN_SAVED_SINGLE_KANJI_HITS = 2
HINT_SEPARATOR = "\x1e"
RATE_LIMITED_ENGINES = frozenset({"mymemory", "google"})
RATE_LIMIT_STATUS = 429
MYMEMORY_DAILY_CHARS = 5_000
MYMEMORY_DAILY_CHARS_EMAIL = 50_000
DEEPL_FREE_MONTHLY_CHARS = 500_000

SPEAKER_FORMATS = frozenset({"srt", "vtt", "ass"})
_SPEAKER_TOKEN_RE = re.compile(r"^\[\[E\d+\]\][：:]?「")


@dataclass
class Progress:
    """Kabar kemajuan terjemahan yang dikirim ke fungsi callback."""

    done: int
    total: int
    message: str = ""


@dataclass
class _Unit:
    """Satu kalimat dokumen yang sedang diproses oleh pipa terjemahan."""

    paragraph: int
    source: str
    masked: Masked | None
    turn: int = 0
    lead: str = ""
    trail: str = ""
    tagged: bool = False
    raw: str = ""
    status: str = ""
    engine: str = ""
    names: list[str] = field(default_factory=list)
    presub: bool = False
    partial: str = ""
    partial_engine: str = ""
    partial_residue: int = 0
    partial_names: list[str] = field(default_factory=list)
    partial_presub: bool = False

    @property
    def waiting(self) -> bool:
        return self.masked is not None and not self.status

    def settle(
        self,
        raw: str,
        status: str,
        engine: str,
        names: Sequence[str] = (),
        presub: bool = False,
    ) -> None:
        self.raw = raw
        self.status = status
        self.engine = engine
        self.names = list(names)
        self.presub = presub

    def remember_partial(
        self,
        raw: str,
        engine: str,
        residue: int,
        names: Sequence[str] = (),
        presub: bool = False,
    ) -> None:
        if not self.partial or residue < self.partial_residue:
            self.partial = raw
            self.partial_engine = engine
            self.partial_residue = residue
            self.partial_names = list(names)
            self.partial_presub = presub


@dataclass
class _Counters:
    """Penghitung beban kerja dan kemajuan satu dokumen."""

    total: int = 0
    done: int = 0
    requests: int = 0
    chars_sent: int = 0


class Translator:
    """Penerjemah dokumen lengkap dengan glosarium, cache, dan fallback mesin."""

    def __init__(
        self,
        cfg: Config,
        engines: list[Engine],
        cache: TranslationCache,
        glossary: Glossary,
        *,
        progress: Callable[[Progress], None] | None = None,
        glossary_path: Path | None = None,
        owns_cache: bool = False,
    ) -> None:
        self.cfg = cfg
        self.lang = cfg.target_lang
        self.cache = cache
        self._owns_cache = owns_cache
        self.glossary = glossary
        self.glossary_path = glossary_path or default_glossary_path(
            cfg, glossary.title
        )
        self._progress = progress
        self._live: list[Engine] = list(engines)
        self._dead: list[str] = []
        self._limiters = {
            id(engine): RateLimiter(
                cfg.request_delay if engine.name in RATE_LIMITED_ENGINES else 0.0
            )
            for engine in engines
        }
        self._surface_map: dict[str, GlossaryEntry] = {}
        self._named: frozenset[str] = frozenset()
        self._new_entries: list[GlossaryEntry] = []
        self._kun: set[str] = set()
        self._review_people: tuple[str, ...] = ()
        self._keep: tuple[str, ...] = ()
        self._proper: frozenset[str] = frozenset()
        self._counters = _Counters()
        self._renderer = Renderer(cfg)
        self._plain = Renderer(replace(cfg, first_gloss=False))

    def close(self) -> None:
        """Tutup cache milik objek ini bila dibuat otomatis oleh factory SDK."""
        if self._owns_cache:
            self.cache.close()

    def __enter__(self) -> Translator:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def prepare(self, doc: Document) -> list[GlossaryEntry]:
        """Siapkan glosarium dokumen: deteksi entitas, bacaan, gender, dan ejaan."""
        self._new_entries = detect_new_entries(doc, self.cfg, self.glossary)
        stale = drop_time_word_places(self.glossary)
        genders = self._infer_genders(doc)
        surface_map = masking_map(self.glossary, doc.ruby)
        surface_map, resolved = self._resolve_unknown(surface_map)
        self._surface_map = surface_map
        self._named = attested_names(
            "\n".join(paragraph.text for paragraph in doc.paragraphs), doc.ruby
        )
        self._drop_weak_entries(doc)
        self._keep = tuple(
            key for key, entry in surface_map.items() if not self._renderable(entry)
        )
        if self._new_entries or resolved or genders or stale:
            self.glossary.save(self.glossary_path)
            logger.info(
                "glosarium disimpan: %d entri baru, %d ejaan mesin, %d gender",
                len(self._new_entries),
                resolved,
                genders,
            )
        return unique_entries(surface_map.values())

    def _infer_genders(self, doc: Document) -> int:
        persons = [
            entry
            for entry in self.glossary.entries(confirmed_only=True)
            if entry.kind == PERSON
        ]
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
        self._kun = kun_surfaces(text, [entry.surface for entry in persons])
        self._review_people = tuple(
            surface
            for surface, entry in self.glossary.surface_map(
                confirmed_only=False
            ).items()
            if entry.kind == PERSON and not entry.confirmed
        )
        updated = 0
        for entry in persons:
            if entry.gender or entry.source == USER_SOURCE:
                continue
            gender, origin = infer_gender(entry, kun=entry.surface in self._kun)
            if gender and origin in STRONG_ORIGINS:
                guessed = replace(
                    entry, gender=gender, source=gender_source(entry.source, origin)
                )
                updated += self.glossary.upsert(guessed, overwrite_confirmed=True)
        return updated

    def _drop_weak_entries(self, doc: Document) -> None:
        weak = [
            entry
            for entry in self._new_entries
            if entry.kind == PERSON
            and entry.confirmed
            and len(entry.surface) == 1
            and (
                not self._surface_map.get(entry.surface, entry).reading
                or is_verb_stem(entry.surface)
            )
        ]
        if not weak:
            return
        hits, strong = honorific_name_counts(doc), strong_name_counts(doc)
        dropped = {
            entry.surface
            for entry in weak
            if not self._renderable(self._surface_map.get(entry.surface, entry))
            or (strong if is_verb_stem(entry.surface) else hits)[entry.surface]
            < MIN_SAVED_SINGLE_KANJI_HITS
        }
        for surface in dropped:
            self.glossary.remove(surface)
        self._mark_strong(
            entry.surface
            for entry in weak
            if is_verb_stem(entry.surface) and entry.surface not in dropped
        )
        self._new_entries = [
            entry for entry in self._new_entries if entry.surface not in dropped
        ]
        if dropped:
            logger.info(
                "%d entri orang satu kanji tidak disimpan: bukti lemah",
                len(dropped),
            )

    def _mark_strong(self, surfaces: Iterable[str]) -> None:
        for surface in surfaces:
            entry = self.glossary.get(surface)
            if entry is not None and entry.source != USER_SOURCE:
                self.glossary.upsert(
                    replace(entry, source=strong_source(entry.source)),
                    overwrite_confirmed=True,
                )

    def _gender_of(self, entry: GlossaryEntry) -> str:
        return infer_gender(entry, kun=entry.surface in self._kun)[0]

    def _resolve_unknown(
        self, surface_map: dict[str, GlossaryEntry]
    ) -> tuple[dict[str, GlossaryEntry], int]:
        entries = unique_entries(surface_map.values())
        stems = {
            entry.surface: entry
            for key, entry in surface_map.items()
            if is_admin_stem(key, entry) and not can_render(entry, self.lang)
        }
        engine_mode = self.cfg.unknown_reading == "engine"
        unknown = [
            entry
            for entry in entries
            if engine_mode
            and (
                entry.kind in NAME_LOOKUP_KINDS
                or (
                    entry.surface in stems
                    and len(entry.surface) >= MIN_PLACE_LOOKUP_KANJI
                )
            )
            and not can_render(entry, self.lang)
        ]
        foreign = [
            entry
            for entry in entries
            if self.cfg.foreign_names == "auto"
            and needs_foreign_lookup(entry, self.lang)
        ]
        outputs: list[str] = []
        source = self._live[0].name if self._live else ""
        if (unknown or foreign) and self._live:
            outputs = self._lookup_names(unknown + foreign)
        if not outputs:
            unknown, foreign = [], []
        stored, working = kanji_spellings(
            unknown, outputs, source, self.cfg.romanization
        )
        working.update(
            self._foreign_spellings(foreign, outputs[len(unknown):], source)
        )
        updated = sum(self._remember(entry) for entry in stored.values())
        resolved = {**stored, **working}
        resolved.update(given_fallbacks(entries, resolved, self.cfg.romanization))
        new_map = {
            key: resolved.get(entry.surface, entry)
            for key, entry in surface_map.items()
        }
        return new_map, updated

    def _foreign_spellings(
        self,
        foreign: list[GlossaryEntry],
        outputs: Sequence[str],
        source: str,
    ) -> dict[str, GlossaryEntry]:
        working: dict[str, GlossaryEntry] = {}
        for entry, raw in zip(foreign, outputs):
            name = validate_foreign_name(entry.surface, raw)
            if name is None:
                logger.info(
                    "ejaan nama asing dari %s tidak lolos validasi (%d karakter)",
                    source,
                    len(raw),
                )
                continue
            name = merge_foreign_answer(
                entry.surface, name, self.cfg.romanization
            )
            if name is None:
                logger.debug(
                    "jawaban %s hanya mengulang Hepburn; mode romanisasi dipakai",
                    source,
                )
            else:
                working[entry.surface] = replace(entry, romaji=name, source="engine")
        return working

    def _lookup_names(self, entries: list[GlossaryEntry]) -> list[str]:
        engine = self._live[0]
        try:
            return self._lookup(engine, [entry.surface for entry in entries])
        except (QuotaExceeded, EngineUnavailable) as exc:
            self._kill(engine, exc)
        except EngineError as exc:
            logger.warning(
                "ejaan %d nama tidak bisa ditanyakan: %s", len(entries), exc
            )
        return []

    def _remember(self, entry: GlossaryEntry) -> bool:
        old = self.glossary.get(entry.surface)
        if old is None or old.source == USER_SOURCE:
            return False
        return self.glossary.upsert(entry, overwrite_confirmed=True)

    def _lookup(self, engine: Engine, surfaces: list[str]) -> list[str]:
        keys = [
            make_key(engine.cache_tag(), SOURCE_LANG, NAME_LOOKUP_LANG, s)
            for s in surfaces
        ]
        outputs = [self.cache.get(key) for key in keys]
        missing = [i for i, value in enumerate(outputs) if value is None]
        if missing:
            fresh = self._send(
                engine,
                [surfaces[i] for i in missing],
                [{}] * len(missing),
                tgt=NAME_LOOKUP_LANG,
            )
            cache_rows: list[tuple[str, str, str, str, str]] = []
            for i, value in zip(missing, fresh):
                outputs[i] = value
                if value and not looks_untranslated(value, surfaces[i]):
                    cache_rows.append(
                        (keys[i], engine.name, SOURCE_LANG, NAME_LOOKUP_LANG, value)
                    )
            self.cache.put_many(cache_rows)
        return [value or "" for value in outputs]

    def translate_document(self, doc: Document) -> TranslatedDocument:
        """Terjemahkan seluruh dokumen sumber menjadi ``TranslatedDocument``."""
        started = time.monotonic()
        self._counters = _Counters()
        self._renderer = Renderer(self.cfg)
        self.prepare(doc)
        matcher = EntityMatcher(self._surface_map, self._named)
        units = build_units(doc, matcher, self._renderable)
        logger.info(
            "dokumen %d paragraf, %d kalimat", len(doc.paragraphs), len(units)
        )
        self._counters.total = len(units)
        self._counters.done = sum(1 for unit in units if unit.masked is None)
        self._report("mulai")
        for engine in list(self._live):
            if not any(unit.waiting for unit in units):
                break
            self._run_engine(engine, units)
        self._accept_partials(units)
        translatable = [unit for unit in units if unit.masked is not None]
        if translatable and all(unit.waiting for unit in translatable):
            raise AllEnginesFailed(
                f"semua mesin gagal untuk {len(translatable)} kalimat"
                + (
                    f" (mesin mati: {', '.join(self._dead)})"
                    if self._dead
                    else ""
                )
            )
        paragraphs = [
            TranslatedParagraph(source=paragraph) for paragraph in doc.paragraphs
        ]
        self._proper = proper_nouns(
            unit.raw for unit in units if not unit.waiting
        )
        context: dict[int, list[Masked]] = {}
        for unit in units:
            if unit.masked is not None:
                context.setdefault(unit.paragraph, []).append(unit.masked)
        for unit in units:
            paragraphs[unit.paragraph].sentences.append(
                self._finish(unit, context.get(unit.paragraph, []))
            )
        self._counters.done = self._counters.total
        self._report("selesai")
        return TranslatedDocument(
            document=doc,
            paragraphs=paragraphs,
            source_lang=SOURCE_LANG,
            target_lang=self.lang,
            glossary=self._used_glossary(doc, units),
            stats=self._stats(paragraphs, units, time.monotonic() - started),
        )

    def translate_text(self, text: str, title: str = "teks") -> TranslatedDocument:
        """Terjemahkan teks mentah secara langsung (API pustaka praktis)."""
        return self.translate_document(read_text(text, title))

    def _run_engine(self, engine: Engine, units: list[_Unit]) -> None:
        try:
            stale: set[int] = set()
            for unit in [u for u in units if u.waiting]:
                assert unit.masked is not None
                raw = self.cache.get(
                    self._key(engine, unit.masked.text, unit.masked.slots)
                )
                if raw is None or looks_untranslated(raw, unit.masked.text):
                    continue
                if self._has_residue(engine, unit, raw):
                    stale.add(id(unit))
                    if not tokens_intact(raw, unit.masked):
                        self._presubstitute(engine, unit)
                else:
                    self._settle(engine, unit, raw, STATUS_CACHED)
            todo = [
                unit for unit in units if unit.waiting and id(unit) not in stale
            ]
            texts = [unit.masked.text for unit in todo if unit.masked is not None]
            for batch in make_batches(texts, engine.max_chars, engine.max_items):
                self._translate_group(engine, [todo[i] for i in batch])
                self._report(engine.name)
        except (QuotaExceeded, EngineUnavailable) as exc:
            self._kill(engine, exc)

    def _translate_group(self, engine: Engine, group: list[_Unit]) -> None:
        outputs = self._send_group(engine, group)
        if outputs is None:
            return
        retry = self._accept_outputs(engine, group, outputs)
        if len(group) > 1:
            for unit in retry:
                self._translate_group(engine, [unit])

    def _send_group(
        self, engine: Engine, group: list[_Unit]
    ) -> list[str] | None:
        try:
            return self._send(
                engine,
                [u.masked.text for u in group if u.masked is not None],
                [u.masked.slots for u in group if u.masked is not None],
            )
        except (QuotaExceeded, EngineUnavailable):
            raise
        except EngineError as exc:
            if http_status(exc) == RATE_LIMIT_STATUS:
                if len(group) == 1 or engine.name != "llm":
                    message = "terlalu banyak permintaan (HTTP 429)"
                    raise EngineUnavailable(engine.name, message) from exc
                time.sleep(min(2.0, max(self.cfg.request_delay, 0.5)))
            if len(group) == 1:
                logger.info("%s gagal untuk satu kalimat: %s", engine.name, exc)
                return None
            logger.info(
                "%s gagal untuk batch %d kalimat, diulang per kalimat: %s",
                engine.name,
                len(group),
                exc,
            )
            for unit in group:
                self._translate_group(engine, [unit])
            return None

    def _accept_outputs(
        self, engine: Engine, group: list[_Unit], outputs: list[str]
    ) -> list[_Unit]:
        retry: list[_Unit] = []
        to_cache: list[tuple[str, str, str, str, str]] = []
        try:
            for unit, raw in zip(group, outputs):
                assert unit.masked is not None
                if looks_untranslated(raw, unit.masked.text):
                    retry.append(unit)
                    continue
                if self._has_residue(engine, unit, raw):
                    if len(group) == 1 and not tokens_intact(raw, unit.masked):
                        self._presubstitute(engine, unit)
                    if unit.waiting:
                        retry.append(unit)
                    continue
                if tokens_intact(raw, unit.masked):
                    to_cache.append((
                        self._key(engine, unit.masked.text, unit.masked.slots),
                        engine.name,
                        SOURCE_LANG,
                        self.lang,
                        raw,
                    ))
                    self._accept(unit, raw, STATUS_OK, engine.name)
                else:
                    self._presubstitute(engine, unit)
        finally:
            self.cache.put_many(to_cache)
        if retry:
            logger.info(
                "%s tidak menerjemahkan %d dari %d kalimat",
                engine.name,
                len(retry),
                len(group),
            )
        return retry

    def _has_residue(self, engine: Engine, unit: _Unit, raw: str) -> bool:
        assert unit.masked is not None
        if self._own_echo(engine, unit.masked.text, raw):
            return False
        residue = residue_letters(raw, unit.masked.text, self._keep)
        if not residue:
            return False
        logger.info(
            "%s menyisakan huruf Jepang di satu kalimat (%d huruf)",
            engine.name,
            residue,
        )
        if tokens_intact(raw, unit.masked):
            unit.remember_partial(raw, engine.name, residue)
        return True

    def _own_echo(self, engine: Engine, text: str, raw: str) -> bool:
        echo = getattr(engine, "echo", None)
        if not getattr(engine, "echoes_source", False) or not callable(echo):
            return False
        pieces = chunk_long_text(text, engine.max_chars) or [text]
        return (
            raw
            == join_pieces([echo(piece, self.lang) for piece in pieces], [0] * len(pieces), 1)[0]
        )

    def _accept_partials(self, units: list[_Unit]) -> None:
        partial = [unit for unit in units if unit.waiting and unit.partial]
        for unit in partial:
            self._accept(
                unit,
                unit.partial,
                STATUS_PARTIAL,
                unit.partial_engine,
                unit.partial_names,
                presub=unit.partial_presub,
            )
        if partial:
            logger.warning(
                "%d kalimat masih memuat huruf Jepang (status %s)",
                len(partial),
                STATUS_PARTIAL,
            )

    def _settle(
        self, engine: Engine, unit: _Unit, raw: str, status: str
    ) -> None:
        assert unit.masked is not None
        if tokens_intact(raw, unit.masked):
            if status == STATUS_OK:
                self.cache.put(
                    self._key(engine, unit.masked.text, unit.masked.slots),
                    engine.name,
                    SOURCE_LANG,
                    self.lang,
                    raw,
                )
            self._accept(unit, raw, status, engine.name)
        else:
            self._presubstitute(engine, unit)

    def _presubstitute(self, engine: Engine, unit: _Unit) -> None:
        assert unit.masked is not None
        text, required = presubstitute(unit.masked, self._plain)
        key = self._key(engine, text)
        raw = self.cache.get(key)
        fresh = raw is None
        if raw is None:
            try:
                raw = self._send(engine, [text], [{}])[0]
            except (QuotaExceeded, EngineUnavailable):
                raise
            except EngineError as exc:
                logger.info("%s gagal di jalur cadangan: %s", engine.name, exc)
                return
            if looks_untranslated(raw, text):
                logger.info(
                    "%s tidak menerjemahkan kalimat di jalur cadangan",
                    engine.name,
                )
                return
        residue = 0
        if not self._own_echo(engine, text, raw):
            residue = residue_letters(raw, text, (*self._keep, *required))
        missing = check_presubstituted(raw, required)
        if missing:
            logger.info(
                "%s menghilangkan %d nama di jalur cadangan",
                engine.name,
                len(missing),
            )
        names = person_forms(unit.masked, self._plain)
        if residue:
            logger.info(
                "%s menyisakan huruf Jepang di jalur cadangan (%d huruf)",
                engine.name,
                residue,
            )
            if not missing:
                unit.remember_partial(
                    raw, engine.name, residue, names, presub=True
                )
            return
        if not missing:
            if fresh:
                self.cache.put(key, engine.name, SOURCE_LANG, self.lang, raw)
            self._accept(unit, raw, STATUS_PRESUB, engine.name, names, presub=True)

    def _accept(
        self,
        unit: _Unit,
        raw: str,
        status: str,
        engine: str,
        names: Sequence[str] = (),
        presub: bool = False,
    ) -> None:
        unit.settle(raw, status, engine, names, presub)
        self._counters.done += 1

    def _send(
        self,
        engine: Engine,
        texts: list[str],
        slots: list[Mapping[int, Slot]],
        *,
        tgt: str | None = None,
    ) -> list[str]:
        target = tgt or self.lang
        pieces: list[str] = []
        owners: list[int] = []
        for owner, text in enumerate(texts):
            for piece in chunk_long_text(text, engine.max_chars) or [text]:
                pieces.append(piece)
                owners.append(owner)
        outputs: list[str] = []
        for batch in make_batches(pieces, engine.max_chars, engine.max_items):
            chunk = [pieces[i] for i in batch]
            hints = hint_lines(
                chunk,
                [slots[owners[i]] for i in batch],
                self._plain,
                self._gender_of,
            )
            self._limiters[id(engine)].wait()
            self._counters.requests += 1
            self._counters.chars_sent += sum(len(piece) for piece in chunk)
            result = engine.translate(chunk, SOURCE_LANG, target, hints)
            outputs.extend(require_same_length(engine.name, chunk, result))
        return join_pieces(outputs, owners, len(texts))

    def _kill(self, engine: Engine, exc: EngineError) -> None:
        if engine in self._live:
            self._live.remove(engine)
            self._dead.append(engine.name)
        logger.warning(
            "mesin %s tidak dipakai lagi di sesi ini: %s", engine.name, exc
        )

    def _key(
        self,
        engine: Engine,
        text: str,
        slots: Mapping[int, Slot] | None = None,
    ) -> str:
        if slots and getattr(engine, "uses_hints", False):
            hints = hint_lines([text], [slots], self._plain, self._gender_of)
            text += HINT_SEPARATOR + "\n".join(hints)
        elif slots:
            sig = "|".join(
                f"E{num}:{slot.entry.kind}:{slot.suffix}:{len(slot.parents)}"
                for num, slot in sorted(slots.items())
                if slot.suffix or slot.parents or slot.entry.kind != PERSON
            )
            if sig:
                text += HINT_SEPARATOR + sig
        return make_key(engine.cache_tag(), SOURCE_LANG, self.lang, text)

    def _renderable(self, entry: GlossaryEntry) -> bool:
        return can_render(entry, self.lang)

    def _finish(
        self, unit: _Unit, context: Sequence[Masked] = ()
    ) -> SentencePair:
        if unit.masked is None:
            return SentencePair(
                unit.source, unit.source, status=STATUS_PLAIN, turn=unit.turn
            )
        if unit.waiting:
            return SentencePair(
                unit.source, unit.source, status=STATUS_FAILED, turn=unit.turn
            )
        if unit.presub:
            text, names = unit.raw, unit.names
            forms = [self._plain(slot) for slot in unit.masked.slots.values()]
        else:
            text, names, forms = self._restore(unit)
        id_or_en_names = names if self.lang == "en" else [*names, *forms]
        target = fix_names(tidy(text, self.lang), id_or_en_names, self.lang)
        if _SPEAKER_TOKEN_RE.match(unit.masked.text):
            target = mark_speaker(target, names)
        if self.lang == "en":
            gender = pronoun_gender(
                unit.masked,
                context or [unit.masked],
                self._gender_of,
                self._review_people,
            )
            target = fix_pronouns(target, gender)
            target = fix_explicit_pronouns(
                target, *explicit_pronoun(unit.masked.text)
            )
        target = lower_after_comma(target, self.lang, forms)
        lead = vocative_lead(unit.masked)
        if lead is not None:
            target = lower_after_vocative(
                target, self.lang, forms, self._proper, lead
            )
        if unit.tagged:
            if not strip_format_tags(unit.source).lstrip()[:1].isascii():
                tags, rest = split_leading_tags(target)
                target = tags + capitalize_first(rest)
        elif not unit.source[:1].isascii():
            target = capitalize_first(target)
        if unit.lead or unit.trail:
            target = unit.lead + target.strip() + unit.trail
        return SentencePair(
            unit.source,
            target,
            engine=unit.engine,
            status=unit.status,
            turn=unit.turn,
        )

    def _restore(self, unit: _Unit) -> tuple[str, list[str], list[str]]:
        assert unit.masked is not None
        names: list[str] = []
        forms: list[str] = []

        def render(slot: Slot) -> str:
            form = self._renderer(slot)
            forms.append(form)
            if slot.entry.kind == PERSON:
                names.extend(person_names(form, self._plain.base_name(slot.entry)))
            return form

        return restore(unit.raw, unit.masked, render), names, forms

    def _report(self, message: str) -> None:
        if self._progress is not None:
            self._progress(
                Progress(self._counters.done, self._counters.total, message)
            )

    def _used_glossary(
        self, doc: Document, units: list[_Unit]
    ) -> list[GlossaryEntry]:
        used = {
            slot.entry.surface: slot.entry
            for unit in units
            if unit.masked
            for slot in unit.masked.slots.values()
        }
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
        for entry in self.glossary.entries():
            if not entry.confirmed and entry.surface in text:
                used.setdefault(entry.surface, entry)
        return list(used.values())

    def _stats(
        self,
        paragraphs: list[TranslatedParagraph],
        units: list[_Unit],
        seconds: float,
    ) -> dict:
        pairs = [pair for paragraph in paragraphs for pair in paragraph.sentences]
        stats: dict = {
            "by_status": dict(Counter(pair.status for pair in pairs)),
            "by_engine": dict(
                Counter(pair.engine for pair in pairs if pair.engine)
            ),
            "requests": self._counters.requests,
            "chars_sent": self._counters.chars_sent,
            "seconds": round(seconds, 2),
            "new_entries": len(self._new_entries),
            "rendered": self._rendered_forms(units),
        }
        if self._dead:
            stats["dead_engines"] = list(self._dead)
        return stats

    def _rendered_forms(self, units: list[_Unit]) -> dict[str, str]:
        forms: dict[str, str] = {}
        for unit in units:
            for slot in unit.masked.slots.values() if unit.masked else ():
                forms.setdefault(
                    slot.entry.surface, self._plain(Slot(slot.entry))
                )
        return forms


def detect_new_entries(
    doc: Document, cfg: Config, glossary: Glossary
) -> list[GlossaryEntry]:
    """Jalankan deteksi entitas dan masukkan kandidat terkunci/tinjau ke glosarium."""
    if not cfg.auto_detect:
        return []
    known = set(glossary.surface_map(confirmed_only=False))
    candidates = detect_entities(doc, known, use_janome=janome_available())
    locked, review = candidates_to_entries(candidates, cfg)
    added = [entry for entry in locked + review if glossary.upsert(entry)]
    logger.info(
        "deteksi: %d dikunci, %d perlu ditinjau, %d ditambahkan",
        len(locked),
        len(review),
        len(added),
    )
    return added


def drop_time_word_places(glossary: Glossary) -> int:
    """Keluarkan entri tempat otomatis lama yang hanya kata waktu + sufiks."""
    stale = [
        entry.surface
        for entry in glossary.entries()
        if entry.source != USER_SOURCE and is_time_word_place(entry.surface)
    ]
    for surface in stale:
        glossary.remove(surface)
    if stale:
        logger.info(
            "%d entri tempat kata waktu dikeluarkan dari glosarium", len(stale)
        )
    return len(stale)


def split_turns(doc: Document) -> list[list[list[str]]]:
    """Pecah tiap paragraf menjadi giliran pembicara, lalu kalimat."""
    split: list[list[list[str]]] = []
    for paragraph in doc.paragraphs:
        if doc.fmt in SPEAKER_FORMATS:
            split.append(
                [
                    attach_format_tags(split_sentences(turn))
                    for turn in split_speaker_turns(paragraph.text)
                ]
            )
        else:
            split.append([split_sentences(unwrap_lines(paragraph.text))])
    return split


def build_units(
    doc: Document,
    matcher: EntityMatcher,
    renderable: Callable[[GlossaryEntry], bool],
) -> list[_Unit]:
    """Buat daftar kalimat termasking untuk seluruh dokumen."""
    units: list[_Unit] = []
    tagged = doc.fmt in SPEAKER_FORMATS
    for index, turns in enumerate(split_turns(doc)):
        for turn, sentences in enumerate(turns):
            for sentence in sentences:
                lead, body, trail = (
                    split_format_tags(sentence) if tagged else ("", sentence, "")
                )
                masked = (
                    matcher.mask(body, renderable)
                    if body and contains_japanese(body)
                    else None
                )
                units.append(
                    _Unit(
                        index,
                        sentence,
                        masked,
                        turn,
                        lead=lead,
                        trail=trail,
                        tagged=tagged,
                    )
                )
    return units


def tokens_intact(raw: str, masked: Masked) -> bool:
    """Periksa apakah semua penanda asli ada di keluaran mesin."""
    return not missing_tokens(raw, masked)


def join_pieces(
    outputs: Sequence[str], owners: Sequence[int], count: int
) -> list[str]:
    """Gabungkan hasil potongan kembali menjadi satu hasil per teks asli."""
    joined: list[list[str]] = [[] for _ in range(count)]
    for owner, output in zip(owners, outputs):
        joined[owner].append(output.strip())
    return [" ".join(part for part in parts if part) for parts in joined]


def unique_entries(entries: Iterable[GlossaryEntry]) -> list[GlossaryEntry]:
    """Buang entri ganda (alias menunjuk ke entri yang sama), urutan dipertahankan."""
    return list({entry.surface: entry for entry in entries}.values())


def janome_available() -> bool:
    """``True`` bila pustaka opsional Janome terpasang."""
    return find_spec("janome") is not None


def estimate(doc: Document, cfg: Config, glossary: Glossary) -> dict:
    """Perkirakan beban terjemahan tanpa memanggil mesin (untuk ``--dry-run``)."""
    working = Glossary(glossary.title, glossary.entries())
    new_entries = detect_new_entries(doc, cfg, working)
    surface_map = masking_map(working, doc.ruby)

    def renderable(entry: GlossaryEntry) -> bool:
        return can_render(entry, cfg.target_lang)

    named = attested_names(
        "\n".join(paragraph.text for paragraph in doc.paragraphs), doc.ruby
    )
    units = build_units(doc, EntityMatcher(surface_map, named), renderable)
    masked = [unit.masked.text for unit in units if unit.masked is not None]
    masked_chars = sum(len(text) for text in masked)
    used = {
        slot.entry.surface
        for unit in units
        if unit.masked
        for slot in unit.masked.slots.values()
    }
    return {
        "title": doc.title,
        "paragraphs": len(doc.paragraphs),
        "sentences": len(units),
        "translatable": len(masked),
        "plain": len(units) - len(masked),
        "source_chars": sum(
            len(unit.source) for unit in units if unit.masked is not None
        ),
        "masked_chars": masked_chars,
        "entities": len(used),
        "new_entries": len(new_entries),
        "unrenderable": sorted(
            entry.surface
            for entry in unique_entries(surface_map.values())
            if not renderable(entry)
        ),
        "engines": [
            _engine_estimate(name, cfg, masked)
            for name in normalize_engine_names(cfg.engines)
        ],
        "quota": _quota_estimate(masked_chars),
    }


def _engine_estimate(name: str, cfg: Config, texts: list[str]) -> dict:
    engine = ENGINE_FACTORIES[name](cfg)
    available, reason = engine.available()
    pieces = [
        piece for text in texts for piece in chunk_long_text(text, engine.max_chars)
    ]
    requests = (
        len(make_batches(pieces, engine.max_chars, engine.max_items))
        if pieces
        else 0
    )
    return {
        "name": name,
        "available": available,
        "reason": reason,
        "requests": requests,
    }


def _quota_estimate(chars: int) -> dict:
    mymemory_limit = (
        MYMEMORY_DAILY_CHARS_EMAIL
        if env_value(EMAIL_ENV)
        else MYMEMORY_DAILY_CHARS
    )
    return {
        "mymemory": {
            "limit": mymemory_limit,
            "period": "hari",
            "percent": round(100 * chars / mymemory_limit, 1),
        },
        "deepl": {
            "limit": DEEPL_FREE_MONTHLY_CHARS,
            "period": "bulan",
            "percent": round(100 * chars / DEEPL_FREE_MONTHLY_CHARS, 1),
        },
    }
