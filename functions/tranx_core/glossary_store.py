"""1:1 GlossaryEntry serializer and FirestoreGlossary(Glossary) adapter."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Protocol

from jptrans.errors import InputError
from jptrans.glossary import Glossary, builtin_entries
from jptrans.models import ENTITY_KINDS, PERSON, GlossaryEntry

GLOSSARY_ENTRY_FIELDS: frozenset[str] = frozenset(
    f.name for f in fields(GlossaryEntry)
)
STRIPPED_META_KEYS: frozenset[str] = frozenset(
    {"id", "key", "updatedAt", "createdAt"}
)
_SAFE_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_\-\u3040-\u30ff\u3400-\u9fff]{1,80}$")


def normalize_surface_key(surface: str) -> str:
    return unicodedata.normalize("NFKC", surface).strip()


def glossary_doc_id(surface: str) -> str:
    """Build a collision-free Firestore document ID for a Japanese surface."""
    norm = normalize_surface_key(surface)
    if not norm:
        raise InputError("surface glosarium tidak boleh kosong")
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
    if _SAFE_DOC_ID_RE.match(norm) and not (norm.startswith("__") and norm.endswith("__")):
        return f"{norm}_{digest}"
    return f"e_{digest}"


def glossary_entry_to_dict(entry: GlossaryEntry) -> dict[str, Any]:
    raw = asdict(entry)
    raw["aliases"] = list(entry.aliases)
    return raw


def dict_to_glossary_entry(item: Mapping[str, Any]) -> GlossaryEntry:
    cleaned = {
        k: v for k, v in item.items() if k not in STRIPPED_META_KEYS
    }
    unknown = sorted(set(cleaned) - GLOSSARY_ENTRY_FIELDS)
    if unknown:
        raise InputError(f"Field GlossaryEntry tidak dikenal: {', '.join(unknown)}")

    surface = cleaned.get("surface")
    if not isinstance(surface, str) or not surface.strip():
        raise InputError("'surface' wajib berupa string tidak kosong")

    kind = str(cleaned.get("kind", PERSON))
    if kind not in ENTITY_KINDS:
        raise InputError(f"kind={kind!r} tidak sah; pilih {ENTITY_KINDS}")

    aliases_raw = cleaned.get("aliases", ())
    if isinstance(aliases_raw, (list, tuple)):
        aliases = tuple(str(a).strip() for a in aliases_raw if str(a).strip())
    else:
        raise InputError("'aliases' harus berupa daftar string")

    gender = str(cleaned.get("gender", "") or "")
    if gender not in ("m", "f", ""):
        gender = ""

    return GlossaryEntry(
        surface=surface.strip(),
        kind=kind,
        reading=str(cleaned.get("reading", "") or ""),
        romaji=str(cleaned.get("romaji", "") or ""),
        render_id=str(cleaned.get("render_id", "") or ""),
        render_en=str(cleaned.get("render_en", "") or ""),
        gloss_id=str(cleaned.get("gloss_id", "") or ""),
        gloss_en=str(cleaned.get("gloss_en", "") or ""),
        gender=gender,
        aliases=aliases,
        allow_compound=bool(cleaned.get("allow_compound", False)),
        confirmed=bool(cleaned.get("confirmed", True)),
        source=str(cleaned.get("source", "user") or "user"),
        score=float(cleaned.get("score", 1.0)),
    )


class GlossaryBackend(Protocol):
    def load_entries(self, title_id: str) -> tuple[str, list[dict[str, Any]]]: ...
    def commit_mutations(
        self,
        title_id: str,
        upserts: dict[str, dict[str, Any]],
        removals: set[str],
    ) -> None: ...


class InMemoryGlossaryBackend:
    """Transactional in-memory GlossaryBackend enforcing user-lock precedence."""

    def __init__(self) -> None:
        self.titles: dict[str, str] = {}
        self.entries: dict[str, dict[str, dict[str, Any]]] = {}

    def set_title(self, title_id: str, title_name: str) -> None:
        self.titles[title_id] = title_name
        self.entries.setdefault(title_id, {})

    def load_entries(self, title_id: str) -> tuple[str, list[dict[str, Any]]]:
        name = self.titles.get(title_id, title_id)
        rows = list(self.entries.get(title_id, {}).values())
        return name, rows

    def commit_mutations(
        self,
        title_id: str,
        upserts: dict[str, dict[str, Any]],
        removals: set[str],
    ) -> None:
        bucket = self.entries.setdefault(title_id, {})
        for doc_id in removals:
            existing = bucket.get(doc_id)
            if existing and existing.get("source") == "user" and existing.get("confirmed"):
                continue
            bucket.pop(doc_id, None)
        for doc_id, incoming in upserts.items():
            existing = bucket.get(doc_id)
            if (
                existing is not None
                and existing.get("confirmed") is True
                and existing.get("source") == "user"
                and incoming.get("source") != "user"
            ):
                continue
            bucket[doc_id] = dict(incoming)


class FirestoreGlossary(Glossary):
    """jptrans.Glossary subclass backed by Firestore without touching local disk."""

    def __init__(
        self,
        title_id: str,
        title_name: str,
        backend: GlossaryBackend | None = None,
        initial_entries: Iterable[GlossaryEntry] = (),
        *,
        include_builtins: bool = True,
    ) -> None:
        self.title_id = title_id
        self._backend = backend
        self._dirty_upserts: dict[str, GlossaryEntry] = {}
        self._dirty_removals: set[str] = set()
        self._bootstrapping = True
        seed: list[GlossaryEntry] = []
        if include_builtins:
            seed.extend(builtin_entries())
        seed.extend(initial_entries)
        super().__init__(title_name, seed)
        self._bootstrapping = False

    @classmethod
    def load_from_backend(
        cls,
        title_id: str,
        backend: GlossaryBackend,
        *,
        fallback_title: str = "Tanpa judul",
    ) -> FirestoreGlossary:
        stored_title, raw_items = backend.load_entries(title_id)
        parsed = [dict_to_glossary_entry(item) for item in raw_items]
        return cls(
            title_id=title_id,
            title_name=stored_title or fallback_title,
            backend=backend,
            initial_entries=parsed,
        )

    def upsert(
        self, entry: GlossaryEntry, *, overwrite_confirmed: bool = False
    ) -> bool:
        existing = self.get(entry.surface)
        # Never allow non-user mutations to overwrite a user-confirmed entry,
        # even when Translator._infer_genders passes overwrite_confirmed=True.
        if (
            not self._bootstrapping
            and existing is not None
            and existing.confirmed
            and existing.source == "user"
            and entry.source != "user"
        ):
            return False

        stored = super().upsert(entry, overwrite_confirmed=overwrite_confirmed)
        if stored and not self._bootstrapping and entry.source != "builtin":
            doc_id = glossary_doc_id(entry.surface)
            self._dirty_removals.discard(doc_id)
            self._dirty_upserts[doc_id] = entry
        return stored

    def remove(self, surface: str) -> bool:
        existing = self.get(surface)
        if existing is not None and existing.confirmed and existing.source == "user":
            return False
        removed = super().remove(surface)
        if removed and not self._bootstrapping and existing is not None and existing.source != "builtin":
            doc_id = glossary_doc_id(existing.surface)
            self._dirty_upserts.pop(doc_id, None)
            self._dirty_removals.add(doc_id)
        return removed

    def save(self, path: Path | None = None) -> None:
        """Flush dirty entries to GlossaryBackend instead of writing to filesystem."""
        del path
        if self._backend is None or (not self._dirty_upserts and not self._dirty_removals):
            return
        payload = {
            doc_id: glossary_entry_to_dict(entry)
            for doc_id, entry in self._dirty_upserts.items()
        }
        removals = set(self._dirty_removals)
        self._dirty_upserts.clear()
        self._dirty_removals.clear()
        self._backend.commit_mutations(self.title_id, payload, removals)

    def non_builtin_entries(self) -> list[GlossaryEntry]:
        return [e for e in self.entries(confirmed_only=False) if e.source != "builtin"]
