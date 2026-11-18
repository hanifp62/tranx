"""Glosarium per judul: sumber kebenaran ejaan nama, tempat, dan istilah.

Satu karya = satu berkas JSON yang bisa diedit pengguna::

    {"title": "...", "version": 1, "entries": [{"surface": "田中", ...}, ...]}

Setiap entri adalah ``models.GlossaryEntry`` dalam bentuk dict (``aliases``
ditulis sebagai list). Pencarian memakai ``textnorm.search_key`` sehingga
katakana setengah lebar (ｱﾘｽ) tetap menemukan entri アリス, tetapi tulisan asli
entri tidak pernah diubah.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from . import data
from .config import Config
from .errors import NON_UTF8_FS_HINT, InputError, JptransError
from .models import ENTITY_KINDS, PLACE, GlossaryEntry
from .textnorm import decode_unicode_text, search_key

logger = logging.getLogger(__name__)

GLOSSARY_VERSION = 1
BUILTIN_SOURCE = "builtin"
"""``source`` entri tempat bawaan dari ``data/places.json``."""
USER_SOURCE = "user"
"""``source`` entri milik pengguna: tidak pernah ditimpa atau ditafsir ulang secara otomatis."""
STRONG_SOURCE_MARK = "+tegas"
"""Penanda di ``source`` entri otomatis satu kanji batang kata kerja (磨, 歩) yang disimpan karena
minimal dua kemunculan berkonteks nama tegas (``ner.strong_name_counts``). Hanya entri bertanda
ini yang boleh dimasking tanpa honorifik (磨が, 磨と) di dokumen lain; tingkat nama 2 untuk aturan
kata kerja + ん tetap hanya dari dokumen itu sendiri."""


def strong_source(source: str) -> str:
    """``source`` dengan ``STRONG_SOURCE_MARK`` (idempoten): ``auto`` → ``auto+tegas``."""
    return source if STRONG_SOURCE_MARK in source else source + STRONG_SOURCE_MARK

_ENTRY_FIELDS = frozenset(f.name for f in fields(GlossaryEntry))
_BOOL_FIELDS = frozenset({"allow_compound", "confirmed"})
_STR_FIELDS = _ENTRY_FIELDS - _BOOL_FIELDS - {"aliases", "score"}
# Karakter terlarang di nama berkas Windows, karakter kontrol, dan spasi.
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\s]+')
# Nama perangkat Windows; terlarang juga bila diikuti ekstensi (CON.txt, nul.json).
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"{port}{i}" for port in ("COM", "LPT") for i in [*"123456789", "¹", "²", "³"]),
})
_MAX_SLUG = 80
# Batas byte UTF-8: ext4/APFS menolak nama > 255 byte. 240 + "-" + hash 8 + ".json"
# = 254 byte, dan 80 kanji (3 byte) tetap muat utuh.
_MAX_SLUG_BYTES = 240
_HASH_CHARS = 8
# os.replace di Windows gagal (PermissionError) bila berkas tujuan sedang dibuka
# proses lain tanpa FILE_SHARE_DELETE; dicoba ulang dengan jeda bertambah.
REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


def slugify(title: str) -> str:
    """Ubah judul menjadi nama berkas yang mudah dibaca dan aman di semua platform.

    Judul dinormalkan ke NFC dulu (macOS bisa memberi nama berkas NFD). Huruf
    Jepang dipertahankan; karakter ``<>:"/\\|?*``, karakter kontrol, dan spasi
    diganti ``_``. Titik dan ``_`` di ujung (titik di akhir ditolak Windows)
    dibuang. Nama perangkat Windows (``CON``, ``nul.txt``, ``COM1``, ``COM¹``,
    ``CONIN$``) diberi awalan ``_``. Hasilnya TIDAK unik: dipakai untuk nama
    unduhan; nama berkas glosarium memakai ``glossary_stem``.

    Args:
        title: Judul karya.

    Returns:
        Nama dasar berkas, maksimal 80 karakter dan 240 byte UTF-8;
        ``untitled`` bila kosong.
    """
    text = unicodedata.normalize("NFC", title).strip()
    slug = _UNSAFE_FILENAME_RE.sub("_", text).strip("._")[:_MAX_SLUG]
    while len(slug.encode("utf-8")) > _MAX_SLUG_BYTES:
        slug = slug[:-1]
    slug = slug.rstrip("._")
    if not slug:
        return "untitled"
    if slug.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        return f"_{slug}"
    return slug


def glossary_stem(title: str) -> str:
    """Nama dasar berkas glosarium yang deterministik dan unik per judul.

    Bila ``slugify`` mengubah judul (karakter terlarang, spasi, titik di ujung,
    nama perangkat Windows, pemotongan) atau judul memuat huruf kapital (disk
    Windows dan macOS tidak membedakan ``Title`` dan ``title``), ditambahkan
    ``-`` dan 8 huruf heksadesimal awal SHA-256 judul NFC yang sudah di-strip.
    Judul Jepang dan judul huruf kecil yang aman tetap tanpa hash.

    Args:
        title: Judul karya.

    Returns:
        Nama dasar tanpa ``.json``, paling banyak 249 byte UTF-8.
    """
    canonical = unicodedata.normalize("NFC", title).strip()
    slug = slugify(canonical)
    if slug == canonical and canonical == canonical.lower():
        return slug
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_HASH_CHARS]
    return f"{slug}-{digest}"


def _legacy_stem(title: str) -> str:
    """Nama dasar berkas glosarium sebelum ``glossary_stem`` (untuk berkas lama)."""
    slug = _UNSAFE_FILENAME_RE.sub("_", title.strip()).strip("._")[:_MAX_SLUG]
    if not slug:
        return "untitled"
    return f"_{slug}" if slug.upper() in _WINDOWS_RESERVED else slug


class Glossary:
    """Kumpulan ``GlossaryEntry`` untuk satu judul.

    Entri disimpan menurut kunci ``search_key(surface)``; alias menunjuk ke
    kunci entri pemiliknya. Bila alias satu entri sama dengan surface entri
    lain, surface yang menang.

    Args:
        title: Judul karya.
        entries: Entri awal; entri yang lebih belakang menimpa yang lebih depan.
    """

    def __init__(self, title: str, entries: Iterable[GlossaryEntry] = ()) -> None:
        self.title = title
        self._entries: dict[str, GlossaryEntry] = {}
        self._aliases: dict[str, str] = {}
        for entry in entries:
            self.upsert(entry, overwrite_confirmed=True)

    @classmethod
    def load(cls, path: Path, title: str | None = None) -> Glossary:
        """Baca glosarium dari berkas JSON.

        Args:
            path: Lokasi berkas.
            title: Judul bila berkas belum ada atau tidak mencantumkan judul.

        Returns:
            Glosarium berisi entri dari berkas, atau glosarium kosong bila
            berkas belum ada.

        Raises:
            InputError: Berkas tidak bisa dibaca, bukan JSON, atau isinya salah.
        """
        fallback_title = title or path.stem
        if not path.exists():
            logger.debug("glosarium %s belum ada; mulai kosong", path)
            return cls(fallback_title)
        try:
            # BOM UTF-8 dan UTF-16 (glosarium yang diedit di Notepad Windows) diterima.
            raw = json.loads(decode_unicode_text(path.read_bytes()))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InputError(f"glosarium {path} tidak bisa dibaca: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("entries", []), list):
            raise InputError(f"glosarium {path} harus objek JSON dengan daftar 'entries'")
        if raw.get("version", GLOSSARY_VERSION) != GLOSSARY_VERSION:
            logger.warning("versi glosarium %s tidak dikenal: %r", path, raw.get("version"))
        items = raw.get("entries", [])
        entries = [_entry_from_dict(item, index) for index, item in enumerate(items)]
        logger.debug("glosarium %s dimuat: %d entri", path, len(entries))
        return cls(raw.get("title") or fallback_title, entries)

    def save(self, path: Path) -> None:
        """Tulis glosarium ke JSON secara atomik (berkas sementara lalu ``replace``).

        Args:
            path: Lokasi tujuan; foldernya dibuat bila belum ada.

        Raises:
            JptransError: Berkas tidak bisa ditulis.
        """
        payload = {
            "title": self.title,
            "version": GLOSSARY_VERSION,
            "entries": [_entry_to_dict(entry) for entry in self._entries.values()],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            _write_atomic(path, text)
        except OSError as exc:
            raise JptransError(f"glosarium {path} tidak bisa disimpan: {exc}") from exc
        except UnicodeError as exc:
            raise JptransError(f"glosarium {path} tidak bisa disimpan: "
                               f"{NON_UTF8_FS_HINT}") from exc
        logger.debug("glosarium %s disimpan: %d entri", path, len(self))

    def get(self, surface: str) -> GlossaryEntry | None:
        """Cari entri menurut surface atau alias.

        Args:
            surface: Tulisan Jepang; katakana setengah lebar juga dikenali.

        Returns:
            Entri yang cocok, atau ``None``.
        """
        key = search_key(surface)
        entry = self._entries.get(key)
        if entry is None and key in self._aliases:
            entry = self._entries.get(self._aliases[key])
        return entry

    def upsert(self, entry: GlossaryEntry, *, overwrite_confirmed: bool = False) -> bool:
        """Tambah entri baru atau ganti entri dengan surface yang sama.

        Entri yang sudah ``confirmed`` tidak ditimpa oleh entri otomatis
        (``source`` selain ``user``) kecuali ``overwrite_confirmed=True``.
        Entri dari pengguna selalu boleh menimpa.

        Args:
            entry: Entri yang akan disimpan.
            overwrite_confirmed: Izinkan menimpa entri terkonfirmasi.

        Returns:
            ``True`` bila entri disimpan, ``False`` bila ditolak.
        """
        key = search_key(entry.surface)
        old = self._entries.get(key)
        if old is not None and _is_protected(old, entry) and not overwrite_confirmed:
            logger.debug("entri terkonfirmasi %s tidak ditimpa entri %s", old.surface, entry.source)
            return False
        if old is not None:
            self._drop_aliases(key)
        self._entries[key] = entry
        for alias in entry.aliases:
            self._aliases[search_key(alias)] = key
        return True

    def remove(self, surface: str) -> bool:
        """Hapus entri menurut surface atau alias.

        Returns:
            ``True`` bila ada entri yang dihapus.
        """
        entry = self.get(surface)
        if entry is None:
            return False
        key = search_key(entry.surface)
        self._drop_aliases(key)
        del self._entries[key]
        return True

    def entries(self, confirmed_only: bool = False) -> list[GlossaryEntry]:
        """Kembalikan entri sesuai urutan penambahan.

        Args:
            confirmed_only: Hanya entri ``confirmed``.
        """
        return [e for e in self._entries.values() if e.confirmed or not confirmed_only]

    def surface_map(self, confirmed_only: bool = True) -> dict[str, GlossaryEntry]:
        """Peta semua tulisan (surface DAN alias) ke entrinya, untuk ``EntityMatcher``.

        Args:
            confirmed_only: Hanya entri ``confirmed`` (bawaan ``True``: entri
                tinjau tidak dipakai untuk masking).

        Returns:
            Dict tulisan asli → entri. Surface mengalahkan alias yang sama.
        """
        chosen = self.entries(confirmed_only)
        mapping = {alias: entry for entry in chosen for alias in entry.aliases}
        mapping.update({entry.surface: entry for entry in chosen})
        return mapping

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[GlossaryEntry]:
        return iter(list(self._entries.values()))

    def _drop_aliases(self, key: str) -> None:
        """Hapus semua alias yang menunjuk ke entri ``key``."""
        for alias in [a for a, owner in self._aliases.items() if owner == key]:
            del self._aliases[alias]


def default_glossary_path(cfg: Config, title: str) -> Path:
    """Lokasi bawaan berkas glosarium sebuah judul: ``<home>/glossaries/<stem>.json``.

    ``<stem>`` dari ``glossary_stem``. Agar glosarium lama tidak hilang, berkas
    bernama lama (``_legacy_stem``) tetap dipakai bila berkas baru belum ada
    dan judul yang tersimpan di dalamnya sama dengan ``title`` (NFC). Berkas
    lama milik judul lain (dulu dua judul bisa berbagi satu berkas) diabaikan.
    """
    path = cfg.glossary_dir / f"{glossary_stem(title)}.json"
    legacy = cfg.glossary_dir / f"{_legacy_stem(title)}.json"
    if legacy == path or _is_file(path) or not _is_file(legacy):
        return path
    if _stored_title(legacy) == unicodedata.normalize("NFC", title).strip():
        logger.info("memakai glosarium bernama lama %s", legacy)
        return legacy
    return path


def _is_file(path: Path) -> bool:
    """``Path.is_file`` yang menganggap nama tidak sah (mis. > 255 byte) tidak ada.

    Python 3.11 dan 3.12 meneruskan ``ENAMETOOLONG`` dari ``stat`` sebagai
    ``OSError``; nama glosarium lama untuk judul panjang bisa sepanjang itu.
    """
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


def _stored_title(path: Path) -> str | None:
    """Judul yang tercatat di berkas glosarium, atau ``None`` bila tidak terbaca."""
    try:
        raw = json.loads(decode_unicode_text(path.read_bytes()))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("glosarium lama %s tidak terbaca: %s", path, exc)
        return None
    title = raw.get("title") if isinstance(raw, dict) else None
    return unicodedata.normalize("NFC", title).strip() if isinstance(title, str) else None


def builtin_entries() -> list[GlossaryEntry]:
    """Entri tempat terkenal dari ``data/places.json``.

    Pipeline menggabungkannya dengan prioritas di bawah glosarium pengguna.

    Returns:
        Entri berjenis ``PLACE`` dengan ``render_id``/``render_en`` terisi dan
        ``source="builtin"``.
    """
    return [
        GlossaryEntry(
            surface=surface,
            kind=PLACE,
            reading=info["reading"],
            render_id=info["id"],
            render_en=info["en"],
            source=BUILTIN_SOURCE,
        )
        for surface, info in data.places().items()
    ]


def _write_atomic(path: Path, text: str) -> None:
    """Tulis ke berkas sementara di folder yang sama, lalu ganti tujuan sekaligus.

    Dengan cara ini berkas lama tetap utuh bila proses terputus di tengah jalan.
    Byte UTF-8 ditulis apa adanya sehingga baris baru tetap ``\\n`` juga di
    Windows. Nama berkas sementara pendek (bukan nama tujuan + akhiran) agar
    tidak melewati batas 255 byte untuk judul panjang. ``os.replace`` yang
    gagal karena berkas tujuan sedang dibuka proses lain (Windows) dicoba ulang
    sesuai ``REPLACE_RETRY_DELAYS``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=".jptrans-", suffix=".tmp", delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        try:
            handle.write(text.encode("utf-8"))
        except OSError:
            handle.close()
            temp_path.unlink(missing_ok=True)
            raise
    try:
        _replace_with_retry(temp_path, path)
    except (OSError, UnicodeError):
        # UnicodeEncodeError: nama tujuan tidak bisa dienkode sistem berkas non-UTF-8.
        temp_path.unlink(missing_ok=True)
        raise


def _replace_with_retry(source: Path, target: Path) -> None:
    """``os.replace`` dengan percobaan ulang untuk ``PermissionError`` (berkas terkunci)."""
    for delay in REPLACE_RETRY_DELAYS:
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            logger.debug("%s sedang dipakai (%s); coba lagi dalam %.2f s", target, exc, delay)
            time.sleep(delay)
    os.replace(source, target)


def _is_protected(old: GlossaryEntry, new: GlossaryEntry) -> bool:
    """Entri terkonfirmasi hanya boleh ditimpa oleh pengguna."""
    return old.confirmed and new.source != USER_SOURCE


def _entry_to_dict(entry: GlossaryEntry) -> dict[str, Any]:
    """Ubah entri menjadi dict JSON (``aliases`` sebagai list)."""
    item = asdict(entry)
    item["aliases"] = list(entry.aliases)
    return item


def _entry_from_dict(item: Any, index: int) -> GlossaryEntry:
    """Bangun ``GlossaryEntry`` dari dict JSON dengan pesan galat yang jelas.

    Raises:
        InputError: Bukan objek, kunci tidak dikenal, atau nilai bertipe salah.
    """
    where = f"entri ke-{index + 1}"
    if not isinstance(item, dict):
        raise InputError(f"{where} glosarium harus objek JSON")
    unknown = sorted(set(item) - _ENTRY_FIELDS)
    if unknown:
        raise InputError(f"{where}: kunci tidak dikenal {', '.join(unknown)}")
    surface = item.get("surface")
    if not isinstance(surface, str) or not surface.strip():
        raise InputError(f"{where}: 'surface' wajib berupa teks tidak kosong")
    if item.get("kind", "PERSON") not in ENTITY_KINDS:
        raise InputError(f"{where} ({surface}): kind harus salah satu dari {ENTITY_KINDS}")
    values = dict(item)
    aliases = values.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise InputError(f"{where} ({surface}): 'aliases' harus daftar teks")
    values["aliases"] = tuple(aliases)
    for name in _BOOL_FIELDS & set(values):
        if not isinstance(values[name], bool):
            raise InputError(f"{where} ({surface}): '{name}' harus true/false")
    for name in _STR_FIELDS & set(values):
        if not isinstance(values[name], str):
            raise InputError(f"{where} ({surface}): '{name}' harus teks")
    try:
        values["score"] = float(values.get("score", 1.0))
    except (TypeError, ValueError) as exc:
        raise InputError(f"{where} ({surface}): 'score' harus angka") from exc
    return GlossaryEntry(**values)
