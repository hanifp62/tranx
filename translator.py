#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""translator.py: penerjemah dokumen Jepang ke Indonesia dan Inggris (satu berkas).

Berkas ini mengemas paket ``jptrans`` secara utuh dalam satu skrip Python mandiri
tanpa pustaka pihak ketiga (hanya pustaka bawaan Python 3.11+). Dapat dijalankan
di Windows, macOS, Linux, Android (Termux/Pydroid), dan iOS (a-Shell/Pyto).

Fitur Utama & Alur Pipa (8 Tahap):
1. Pembacaan (``readers``): TXT, Markdown, Aozora Bunko, SRT, WebVTT, ASS/SSA,
   HTML/XHTML, EPUB, serta hasil OCR folder gambar komik/dokumen (``ocr``).
2. Segmentasi (``segment``): pemecahan paragraf dan kalimat peka kutipan Jepang
   (「…」, 『…』), elipsis, serta penggabungan giliran dialog subtitle.
3. Deteksi Entitas & Disambiguasi (``ner``, ``disambig``, ``names``, ``readings``):
   mengenali nama tokoh, marga, nama asing/fantasi katakana, dan nama tempat
   agar tidak ikut diterjemahkan secara harfiah seperti kamus biasa.
4. Pelindungan Entitas (``protect``): mengunci entitas menjadi token ``[[E1]]``,
   ``[[E2]]``, dst. sebelum dikirim ke mesin terjemahan.
5. Mesin & Cache Idempoten (``engines``, ``cache``, ``net``): mendukung MyMemory,
   DeepL, Gemini, Groq/OpenRouter/OpenAI/Ollama, LibreTranslate, dan Google
   (tidak resmi dengan ``--allow-unofficial``). Dilengkapi SQLite mode WAL,
   pembatas laju (rate limiter), backoff otomatis, dan pemutus arus (breaker).
6. Perender Gaya Subtitle (``style``, ``gender``, ``romaji``, ``phonetic``):
   mengembalikan token entitas sesuai gaya honorifik (keep/localized/strip),
   urutan nama (family-first/given-first), dan glosarium lintas bab.
7. Pascaproses Bahasa Target (``postprocess``, ``coref``, ``residue``): merapikan
   kata ganti (he/she/ia), klitik Indonesia (``-nya``/``-mu``/``-ku``), dan tanda baca.
8. Penulisan Keluaran (``writers``, ``server``): menulis TXT, Markdown, SRT, VTT,
   ASS, JSON, atau HTML dwibahasa berdampingan, serta antarmuka web lokal.

Keamanan & Konfigurasi Kunci API (Tanpa Rahasia Tertanam):
- Kunci API dibaca dari variabel lingkungan atau berkas ``.env`` di folder kerja
  maupun folder data ``jptrans`` (tanpa ``eval``):
  ``DEEPL_API_KEY``, ``GEMINI_API_KEY``, ``GROQ_API_KEY``, ``OPENROUTER_API_KEY``,
  ``OPENAI_API_KEY``, ``JPTRANS_LLM_API_KEY``, ``LIBRETRANSLATE_API_KEY``.
- Menyimpan kunci API di ``config.json`` ditolak otomatis demi keamanan.

Observabilitas & Kode Keluar (Exit Codes):
- Logging terstruktur berstempel waktu di stderr (``-v`` untuk DEBUG, ``-q`` untuk
  ERROR saja, ``--log-json`` untuk format JSON per baris siap pantau CI/CD).
- Kode keluar standar: ``0`` berhasil, ``1`` galat berkas/runtime, ``2`` galat
  argumen CLI/konfigurasi, ``3`` mesin terjemahan gagal, ``130`` dihentikan
  pengguna (Ctrl+C), ``141`` pipa keluaran ditutup (SIGPIPE).

Contoh Pemakaian CLI:
    python3 translator.py translate bab1.txt --to id -o bab1_id.html
    python3 translator.py translate episode01.srt --to id
    python3 translator.py translate episode01.vtt --to en -o episode01_en.vtt
    python3 translator.py translate novel.epub --to id -o novel_id.html
    python3 translator.py detect bab1.txt
    python3 translator.py glossary show --title "Judul Seri"
    python3 translator.py cache stats
    python3 translator.py serve
    python3 translator.py doctor
    python3 translator.py test -v
    python3 translator.py unpack ./proyek_aplikasi/src
Windows: ganti ``python3`` dengan ``py``.

Integrasi sebagai Codebase Utama Aplikasi (SDK Python, Plugin, & HTTP JSON API):
    import translator, jptrans
    hasil = jptrans.translate_text("田中さんは東京駅に行った。", target_lang="id")
    print(hasil.target)
    # Endpoint HTTP lokal untuk UI kustom: GET /api/meta, POST /api/translate, POST /api/jobs
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    sys.exit(
        "translator.py membutuhkan Python 3.11 atau lebih baru (terpasang: %s)"
        % sys.version.split()[0]
    )

import importlib
import importlib.abc
import importlib.machinery
import io
import logging
from collections.abc import Iterator
from importlib.resources.abc import Traversable, TraversableResources
from pathlib import Path
from types import ModuleType
from typing import Any

logger = logging.getLogger("translator")

VERSI = "1.1.0"
PAKET = "jptrans"
MODUL: dict[str, tuple[bool, str]] = {}
"""Peta nama modul penuh -> (apakah_paket, kode_sumber)."""
DATA: dict[str, str] = {}
"""Peta path relatif paket (mis. ``data/surnames.json``) -> teks UTF-8."""


class BerkasTertanam(Traversable):
    """Berkas atau folder data di memori untuk ``importlib.resources``."""

    def __init__(self, path: str) -> None:
        self._path = path.strip("/")

    @property
    def name(self) -> str:
        return self._path.rsplit("/", 1)[-1]

    def is_file(self) -> bool:
        return self._path in DATA

    def is_dir(self) -> bool:
        prefix = self._path + "/" if self._path else ""
        return any(key.startswith(prefix) for key in DATA)

    def iterdir(self) -> Iterator[BerkasTertanam]:
        prefix = self._path + "/" if self._path else ""
        children = {
            key[len(prefix):].split("/", 1)[0]
            for key in DATA
            if key.startswith(prefix)
        }
        return iter([BerkasTertanam(prefix + child) for child in sorted(children)])

    def joinpath(self, *descendants: str) -> BerkasTertanam:
        parts = [self._path] if self._path else []
        for piece in descendants:
            for part in str(piece).replace("\\", "/").split("/"):
                if part in ("", "."):
                    continue
                if part == "..":
                    raise ValueError("path data tertanam tidak boleh keluar paket")
                parts.append(part)
        return BerkasTertanam("/".join(parts))

    def __truediv__(self, child: str) -> BerkasTertanam:
        return self.joinpath(child)

    def read_bytes(self) -> bytes:
        return self._text().encode("utf-8")

    def read_text(
        self, encoding: str | None = None, errors: str | None = None
    ) -> str:
        return self._text()

    def open(self, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode in ("r", "rt"):
            return io.StringIO(self._text())
        if mode == "rb":
            return io.BytesIO(self.read_bytes())
        raise ValueError(f"mode {mode!r} tidak didukung untuk data tertanam")

    def _text(self) -> str:
        try:
            return DATA[self._path]
        except KeyError:
            raise FileNotFoundError(
                f"data tertanam tidak ditemukan: {self._path}"
            ) from None

    def __repr__(self) -> str:
        return f"BerkasTertanam({self._path!r})"


class SumberDataTertanam(TraversableResources):
    """Pembaca sumber daya ``importlib.resources`` untuk paket tertanam."""

    def __init__(self, fullname: str) -> None:
        self._fullname = fullname

    def files(self) -> BerkasTertanam:
        relative = self._fullname.split(".", 1)[1] if "." in self._fullname else ""
        return BerkasTertanam(relative.replace(".", "/"))


class PemuatTertanam(importlib.abc.InspectLoader):
    """Pemuat modul dari teks sumber di ``MODUL`` dengan dukungan ``inspect``."""

    def is_package(self, fullname: str) -> bool:
        return MODUL[fullname][0]

    def get_source(self, fullname: str) -> str:
        return MODUL[fullname][1]

    def get_code(self, fullname: str) -> Any:
        return compile(
            self.get_source(fullname), _asal(fullname), "exec", dont_inherit=True
        )

    def exec_module(self, module: ModuleType) -> None:
        exec(self.get_code(module.__name__), module.__dict__)

    def get_resource_reader(self, fullname: str) -> SumberDataTertanam:
        return SumberDataTertanam(fullname)

    def ekstrak_paket(self, tujuan: str | Path, *, timpa: bool = False) -> list[Path]:
        """Ekstrak seluruh modul dan data tertanam menjadi paket ``<tujuan>/jptrans/``."""
        pasang()
        galat = importlib.import_module(f"{PAKET}.errors")
        akar = Path(tujuan).resolve()
        target_list: list[tuple[Path, str]] = []
        for fullname, (is_pkg, source) in sorted(MODUL.items()):
            rel = fullname.replace(".", "/") + (
                "/__init__.py" if is_pkg else ".py"
            )
            dest = (akar / rel).resolve()
            if akar not in dest.parents:
                raise galat.ConfigError(f"jalur modul di luar folder tujuan: {rel}")
            target_list.append((dest, source))
        for rel_data, raw in sorted(DATA.items()):
            dest = (akar / PAKET / rel_data).resolve()
            if akar not in dest.parents:
                raise galat.ConfigError(
                    f"jalur data di luar folder tujuan: {rel_data}"
                )
            target_list.append((dest, raw))
        if not timpa:
            existing = [p for p, _ in target_list if p.exists()]
            if existing:
                raise galat.ConfigError(
                    f"tujuan sudah berisi {existing[0].name}; "
                    "tambahkan --force untuk menimpa"
                )
        written: list[Path] = []
        try:
            for dest, content in target_list:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8", newline="\n")
                written.append(dest)
        except OSError as exc:
            raise galat.JptransError(
                f"gagal mengekstrak paket ke {akar}: {exc.strerror or exc}"
            ) from exc
        return written


class PencariTertanam(importlib.abc.MetaPathFinder):
    """Pencari ``sys.meta_path`` urutan pertama untuk paket ``jptrans``."""

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname not in MODUL:
            return None
        is_package = MODUL[fullname][0]
        spec = importlib.machinery.ModuleSpec(
            fullname, PEMUAT, origin=_asal(fullname), is_package=is_package
        )
        if is_package:
            spec.submodule_search_locations = []
        spec.has_location = True
        return spec


def _asal(fullname: str) -> str:
    tail = fullname.replace(".", "/") + (
        "/__init__.py" if MODUL[fullname][0] else ".py"
    )
    return f"{__file__}/{tail}"


PEMUAT = PemuatTertanam()
PENCARI = PencariTertanam()
ekstrak_paket = PEMUAT.ekstrak_paket


def pasang() -> None:
    """Pasang pencari modul tertanam di urutan pertama ``sys.meta_path``."""
    if PENCARI not in sys.meta_path:
        sys.meta_path.insert(0, PENCARI)
    loaded = [
        key for key in sys.modules if key == PAKET or key.startswith(PAKET + ".")
    ]
    for name in loaded:
        module = sys.modules[name]
        if getattr(getattr(module, "__spec__", None), "loader", None) is not PEMUAT:
            del sys.modules[name]


def main(argv: list[str] | None = None) -> int:
    """Pasang pemuat tertanam lalu jalankan CLI utama ``jptrans``."""
    pasang()
    modul_cli = importlib.import_module(f"{PAKET}.cli")
    kode: int = modul_cli.main(argv)
    return kode

# Daftar modul kode paket jptrans.

MODUL['jptrans'] = (
    True,
r'''"""jptrans: pustaka & SDK penerjemah dokumen Jepang bergaya subtitle.

Menyediakan API tingkat tinggi siap pakai untuk integrasi aplikasi desktop, web,
mobile, maupun backend:
- ``translate_text``: terjemahkan string Jepang secara instan.
- ``translate_file``: baca berkas dokumen/subtitle/EPUB, terjemahkan, dan tulis.
- ``create_translator``: buat objek ``Translator`` berstatus (glosarium + cache).
- ``register_engine`` / ``register_reader`` / ``register_writer``: titik ekstensi plugin.
- ``unpack_package``: ekstrak bundel satu berkas menjadi paket ``src/jptrans/``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

__version__ = "1.1.0"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

from .cache import TranslationCache  # noqa: E402
from .config import Config, load_config, load_dotenv  # noqa: E402
from .engines import Engine, build_engines, register_engine  # noqa: E402
from .errors import (  # noqa: E402
    AllEnginesFailed,
    ConfigError,
    EngineError,
    EngineUnavailable,
    InputError,
    JptransError,
    PlaceholderError,
    QuotaExceeded,
)
from .glossary import Glossary, default_glossary_path  # noqa: E402
from .models import (  # noqa: E402
    Candidate,
    Document,
    GlossaryEntry,
    Paragraph,
    SentencePair,
    TranslatedDocument,
    TranslatedParagraph,
)
from .ner import detect_entities  # noqa: E402
from .pipeline import Progress, Translator  # noqa: E402
from .readers import read_document, read_text, register_reader  # noqa: E402
from .writers import render_output, register_writer, write_output  # noqa: E402


def create_translator(
    cfg: Config | None = None,
    *,
    title: str = "teks",
    engines: Sequence[str] | None = None,
    cache: TranslationCache | None = None,
    use_cache: bool = True,
    glossary: Glossary | None = None,
    glossary_path: Path | None = None,
    progress: Callable[[Progress], None] | None = None,
) -> Translator:
    """Bangun instance ``Translator`` siap pakai (mendukung ``with create_translator(...)``)."""
    resolved_cfg = cfg or load_config()
    if engines is not None:
        resolved_cfg = replace(resolved_cfg, engines=list(engines))
    built_engines = build_engines(resolved_cfg)
    owns_cache = cache is None
    active_cache = (
        cache
        if cache is not None
        else TranslationCache(resolved_cfg.cache_path if use_cache else None)
    )
    try:
        g_path = glossary_path or default_glossary_path(resolved_cfg, title)
        active_glossary = (
            glossary if glossary is not None else Glossary.load(g_path, title)
        )
        return Translator(
            resolved_cfg,
            built_engines,
            active_cache,
            active_glossary,
            progress=progress,
            glossary_path=g_path,
            owns_cache=owns_cache,
        )
    except BaseException:
        if owns_cache:
            active_cache.close()
        raise


def translate_text(
    text: str,
    *,
    target_lang: str | None = None,
    title: str = "teks",
    cfg: Config | None = None,
    engines: Sequence[str] | None = None,
    glossary: Glossary | None = None,
    use_cache: bool = True,
) -> TranslatedDocument:
    """Terjemahkan teks Jepang langsung dalam satu pemanggilan fungsi SDK."""
    base_cfg = cfg or load_config()
    if target_lang is not None:
        base_cfg = replace(base_cfg, target_lang=target_lang)
    with create_translator(
        base_cfg,
        title=title,
        engines=engines,
        use_cache=use_cache,
        glossary=glossary,
    ) as translator:
        return translator.translate_text(text, title=title)


def translate_file(
    path: str | Path,
    *,
    output: str | Path | None = None,
    target_lang: str | None = None,
    output_format: str | None = None,
    title: str | None = None,
    encoding: str | None = None,
    input_format: str | None = None,
    bilingual: bool = False,
    cfg: Config | None = None,
    engines: Sequence[str] | None = None,
    use_cache: bool = True,
    progress: Callable[[Progress], None] | None = None,
) -> TranslatedDocument:
    """Baca berkas masukan, terjemahkan, dan tulis ke ``output`` bila diberikan."""
    base_cfg = cfg or load_config()
    if target_lang is not None:
        base_cfg = replace(base_cfg, target_lang=target_lang)
    doc = read_document(
        Path(path), title=title, encoding=encoding, input_format=input_format
    )
    with create_translator(
        base_cfg,
        title=doc.title,
        engines=engines,
        use_cache=use_cache,
        progress=progress,
    ) as translator:
        result = translator.translate_document(doc)
    if output is not None:
        write_output(result, Path(output), output_format, bilingual=bilingual)
    return result


def unpack_package(dest_dir: str | Path, *, overwrite: bool = False) -> list[Path]:
    """Ekstrak bundel satu berkas ``translator.py`` menjadi paket ``<dest_dir>/jptrans/``."""
    loader = getattr(__spec__, "loader", None)
    extractor = getattr(loader, "ekstrak_paket", None)
    if not callable(extractor):
        raise ConfigError(
            "paket jptrans sudah berbentuk folder multi-berkas di disk"
        )
    files: list[Path] = extractor(Path(dest_dir), timpa=overwrite)
    return files


__all__ = [
    "AllEnginesFailed",
    "Candidate",
    "Config",
    "ConfigError",
    "Document",
    "Engine",
    "EngineError",
    "EngineUnavailable",
    "Glossary",
    "GlossaryEntry",
    "InputError",
    "JptransError",
    "Paragraph",
    "PlaceholderError",
    "Progress",
    "QuotaExceeded",
    "SentencePair",
    "TranslatedDocument",
    "TranslatedParagraph",
    "TranslationCache",
    "Translator",
    "__version__",
    "create_translator",
    "detect_entities",
    "load_config",
    "load_dotenv",
    "read_document",
    "read_text",
    "register_engine",
    "register_reader",
    "register_writer",
    "render_output",
    "translate_file",
    "translate_text",
    "unpack_package",
    "write_output",
]
''')

MODUL['jptrans.__main__'] = (
    False,
r'''"""Menjalankan jptrans sebagai modul: ``python -m jptrans ...``.

Kode keluar dari ``cli.main`` diteruskan ke sistem operasi. Versi Python
diperiksa sebelum ``cli`` diimpor, karena modul lain memakai sintaks 3.10+
yang membuat Python lama berhenti dengan traceback yang membingungkan.
"""

from __future__ import annotations

import logging
import sys

# Logger modul ada karena aturan proyek: setiap modul src/jptrans punya
# ``logger = logging.getLogger(__name__)`` (diperiksa tests/test_code_rules.py), agar log
# yang kelak ditambahkan ikut hierarki ``jptrans.*``. Modul ini belum menulis log. Baris ini
# dan pemeriksaan versi di bawahnya sengaja hanya memakai sintaks yang juga dipahami
# Python lama, sehingga Python < 3.11 sampai ke pesan singkat, bukan SyntaxError.
logger = logging.getLogger(__name__)

MIN_PYTHON = (3, 11)

if sys.version_info < MIN_PYTHON:
    sys.exit("jptrans butuh Python 3.11 atau lebih baru (terpasang: %s)"
             % sys.version.split()[0])

from jptrans.cli import main  # noqa: E402 (sesudah pemeriksaan versi)

if __name__ == "__main__":
    sys.exit(main())
''')

MODUL['jptrans.cache'] = (
    False,
r'''"""Cache terjemahan berbasis sqlite3 dengan mode WAL dan cadangan memori.

Menyimpan keluaran mentah mesin untuk kalimat yang sudah dimasking (``[[E1]]``)
agar perubahan ejaan nama di glosarium tidak menghanguskan cache dan proses
yang dihentikan dapat dilanjutkan secara idempoten.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType

from .errors import ConfigError

try:
    import sqlite3
except ImportError:
    sqlite3 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

PERSISTENT_CACHE = sqlite3 is not None
_DB_ERROR: type[Exception] = sqlite3.Error if sqlite3 is not None else OSError

MARKER_VERSION = "E1"
KEY_SEPARATOR = "\x1f"
MEMORY = ":memory:"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    key TEXT PRIMARY KEY,
    engine TEXT NOT NULL,
    src TEXT NOT NULL,
    tgt TEXT NOT NULL,
    value TEXT NOT NULL,
    created REAL NOT NULL
)
"""


def make_key(engine_tag: str, src: str, tgt: str, masked_text: str) -> str:
    """Buat kunci cache SHA-256 yang deterministik untuk satu kalimat termasking."""
    raw = KEY_SEPARATOR.join((MARKER_VERSION, engine_tag, src, tgt, masked_text))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TranslationCache:
    """Penyimpanan pasangan kunci dan keluaran mesin di sqlite3 yang aman-thread."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._memory: dict[str, tuple[str, str]] = {}
        self._conn = _open_database(path) if PERSISTENT_CACHE else None
        if self._conn is None and not PERSISTENT_CACHE:
            logger.warning(
                "modul sqlite3 tidak tersedia; cache hanya di memori proses ini"
            )

    def get(self, key: str) -> str | None:
        """Ambil keluaran mesin yang tersimpan untuk ``key``."""
        with self._lock:
            row = self._select_value(key)
            if row is None:
                self._misses += 1
                return None
            self._hits += 1
            return row[0]

    def put(
        self, key: str, engine: str, src: str, tgt: str, value: str
    ) -> None:
        """Simpan atau perbarui satu entri keluaran mesin secara idempoten."""
        self.put_many([(key, engine, src, tgt, value)])

    def put_many(
        self, rows: Sequence[tuple[str, str, str, str, str]]
    ) -> None:
        """Simpan sekumpulan entri ``(key, engine, src, tgt, value)`` dalam satu transaksi."""
        if not rows:
            return
        now = time.time()
        with self._lock:
            if self._conn is None:
                for key, engine, _src, _tgt, value in rows:
                    self._memory[key] = (engine, value)
                return
            try:
                with self._conn:
                    self._conn.executemany(
                        "INSERT OR REPLACE INTO translations "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        [
                            (key, engine, src, tgt, value, now)
                            for key, engine, src, tgt, value in rows
                        ],
                    )
            except _DB_ERROR as exc:
                self._safe_rollback()
                logger.warning("cache tidak bisa ditulis: %s", exc)

    def clear(self) -> int:
        """Kosongkan seluruh isi cache dan kembalikan jumlah entri yang dihapus."""
        with self._lock:
            if self._conn is None:
                removed = len(self._memory)
                self._memory.clear()
                return removed
            try:
                with self._conn:
                    cur = self._conn.execute("DELETE FROM translations")
                    return max(cur.rowcount, 0)
            except _DB_ERROR as exc:
                self._safe_rollback()
                logger.warning("cache gagal dikosongkan: %s", exc)
                return 0

    def stats(self) -> dict:
        """Ringkasan isi cache dan rasio hit/miss selama objek ini hidup."""
        with self._lock:
            per_engine = self._count_per_engine()
            return {
                "path": str(self.path) if self.path else MEMORY,
                "entries": sum(per_engine.values()),
                "per_engine": per_engine,
                "hits": self._hits,
                "misses": self._misses,
            }

    def close(self) -> None:
        """Tutup koneksi sqlite3 dengan bersih (idempoten bila dipanggil ulang)."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except _DB_ERROR as exc:
                    logger.debug("penutupan cache mengembalikan galat: %s", exc)
                finally:
                    self._conn = None

    def _safe_rollback(self) -> None:
        if self._conn is not None:
            try:
                self._conn.rollback()
            except _DB_ERROR:
                pass

    def _select_value(self, key: str) -> tuple[str] | None:
        if self._conn is None:
            item = self._memory.get(key)
            return None if item is None else (item[1],)
        try:
            return self._conn.execute(
                "SELECT value FROM translations WHERE key = ?", (key,)
            ).fetchone()
        except _DB_ERROR as exc:
            logger.warning("cache tidak bisa dibaca: %s", exc)
            return None

    def _count_per_engine(self) -> dict[str, int]:
        if self._conn is None:
            counts: dict[str, int] = {}
            for engine, _value in self._memory.values():
                counts[engine] = counts.get(engine, 0) + 1
            return counts
        try:
            rows = self._conn.execute(
                "SELECT engine, COUNT(*) FROM translations GROUP BY engine"
            ).fetchall()
        except _DB_ERROR as exc:
            logger.warning("statistik cache gagal dibaca: %s", exc)
            return {}
        return {engine: count for engine, count in rows}

    def __enter__(self) -> TranslationCache:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _open_database(path: Path | None) -> sqlite3.Connection:
    try:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            MEMORY if path is None else str(path),
            timeout=10.0,
            check_same_thread=False,
        )
    except (OSError, sqlite3.Error) as exc:
        raise ConfigError(f"cache tidak bisa dibuka di {path}: {exc}") from exc
    try:
        if path is not None:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        with conn:
            conn.execute(_SCHEMA)
    except sqlite3.Error as exc:
        conn.close()
        raise ConfigError(
            f"berkas cache {path} rusak atau bukan sqlite3 ({exc}); hapus berkas itu"
        ) from exc
    logger.debug("cache dibuka: %s", path or MEMORY)
    return conn
''')

MODUL['jptrans.cli'] = (
    False,
r'''"""Antarmuka baris perintah (CLI) dan konfigurasi logging terstruktur ``jptrans``.

Subperintah: ``translate``, ``detect``, ``ocr``, ``glossary``, ``cache``,
``serve``, ``doctor``, dan ``test``. Hanya modul ini yang menulis ke stdout/stderr
pengguna; seluruh modul pustaka melapor lewat pustaka ``logging`` berstempel waktu.

Kode keluar (standar otomasi CLI dan CI/CD):
- ``0``   : berhasil
- ``1``   : galat berkas masukan atau galat runtime umum
- ``2``   : argumen CLI atau konfigurasi tidak sah
- ``3``   : seluruh mesin penerjemah gagal
- ``130`` : dihentikan pengguna (Ctrl+C / SIGINT)
- ``141`` : pipa keluaran ditutup pembaca lebih dulu (SIGPIPE)
"""

from __future__ import annotations

import argparse
import datetime
import json
import locale
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import __version__, unpack_package
from .cache import PERSISTENT_CACHE, TranslationCache
from .config import (
    FOREIGN_NAMES,
    HONORIFIC_STYLES,
    LANGS,
    NAME_ORDERS,
    REGISTERED_OUTPUT_FORMATS,
    ROMANIZATIONS,
    Config,
    load_config,
)
from .engines import build_engines, describe_engines
from .errors import NON_UTF8_FS_HINT, ConfigError, InputError, JptransError
from .glossary import USER_SOURCE, Glossary, default_glossary_path
from .models import ENTITY_KINDS, Document, GlossaryEntry, TranslatedDocument
from .ner import candidates_to_entries, detect_entities
from .pipeline import Progress, Translator, estimate, janome_available
from .readers import INPUT_FORMAT_READERS, read_document, read_text
from .readers.pages import ocr_images_to_pages
from .readers.txt import decode_bytes
from .style import Renderer
from .textnorm import kata_to_hira
from .writers import SUFFIX_FORMATS, render_output, write_output

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_TEST_FAILED = 1
EXIT_INTERRUPTED = 130
EXIT_BROKEN_PIPE = 141
MAX_PORT = 65535
STDIN = "-"
STDOUT = "-"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
ONLINE_TEST_TEXT = "こんにちは。"

EPILOG = """\
contoh pemakaian:
  Windows : py translator.py translate .\\bab1.txt --to id -o .\\bab1_id.html
  macOS   : python3 translator.py translate novel.epub --to en -o novel_en.html
  Linux   : python3 translator.py translate episode01.vtt --to id
  Android : python ~/translator.py translate ~/storage/downloads/bab1.txt -o \\
              ~/storage/downloads/bab1_id.html
  iOS     : python3 translator.py translate bab1.txt --to id
  Luring  : python3 translator.py translate bab1.txt --engine fake
  Web LAN : python3 translator.py serve --lan
  Uji unit: python3 translator.py test -v

Kunci API dibaca dari variabel lingkungan atau berkas .env: DEEPL_API_KEY,
JPTRANS_LLM_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY,
OPENAI_API_KEY, LIBRETRANSLATE_API_KEY, MYMEMORY_EMAIL (opsional).
"""


class JsonLogFormatter(logging.Formatter):
    """Pemformat satu objek JSON per baris log untuk pemantauan terstruktur."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.datetime.fromtimestamp(
            record.created, tz=datetime.timezone.utc
        ).isoformat(timespec="milliseconds")
        payload: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    """Bangun parser argumen utama lengkap dengan seluruh subperintah."""
    parser = argparse.ArgumentParser(
        prog="translator.py",
        description=(
            "Terjemahkan novel, komik, subtitle, dan dokumen Jepang ke bahasa "
            "Indonesia atau Inggris dengan pelindungan nama bergaya subtitle."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"jptrans {__version__}",
        help="tampilkan versi lalu keluar",
    )
    _add_global_options(parser, defaults=True)
    common = argparse.ArgumentParser(add_help=False)
    _add_global_options(common, defaults=False)

    commands = parser.add_subparsers(
        dest="command", metavar="PERINTAH", required=True
    )
    _add_translate(commands, common)
    _add_detect(commands, common)
    _add_ocr(commands, common)
    _add_glossary(commands, common)
    _add_cache(commands, common)
    _add_serve(commands, common)
    _add_doctor(commands, common)
    _add_test(commands, common)
    _add_unpack(commands, common)
    return parser


def _add_global_options(
    parser: argparse.ArgumentParser, *, defaults: bool
) -> None:
    def default(value: Any) -> Any:
        return value if defaults else argparse.SUPPRESS

    group = parser.add_argument_group("opsi umum")
    group.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=default(0),
        help="tampilkan log INFO (-vv untuk DEBUG)",
    )
    group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=default(False),
        help="hanya tampilkan pesan galat",
    )
    group.add_argument(
        "--log-file",
        type=Path,
        default=default(None),
        help="tulis log juga ke berkas ini (UTF-8)",
    )
    group.add_argument(
        "--log-json",
        action="store_true",
        default=default(False),
        help="format log sebagai JSON terstruktur per baris",
    )
    group.add_argument(
        "--debug",
        action="store_true",
        default=default(False),
        help="log level DEBUG dan traceback penuh saat galat",
    )
    group.add_argument(
        "--config",
        type=Path,
        default=default(None),
        help="berkas config JSON (bawaan: <JPTRANS_HOME>/config.json)",
    )


def _add_translate(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "translate",
        parents=[common],
        help="terjemahkan berkas dokumen atau aliran stdin",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub.add_argument(
        "input",
        help="berkas .txt/.md/.html/.epub/.srt/.vtt/.ass/.json, atau - (stdin)",
    )
    sub.add_argument(
        "-o",
        "--output",
        help="berkas keluaran, atau - untuk stdout",
    )
    sub.add_argument(
        "--to", dest="target_lang", choices=LANGS, help="bahasa sasaran"
    )
    sub.add_argument(
        "--title", help="judul karya; menentukan berkas glosarium"
    )
    sub.add_argument(
        "--engine",
        dest="engines",
        action="extend",
        nargs="+",
        metavar="NAMA",
        help="urutan mesin, mis. --engine deepl mymemory",
    )
    sub.add_argument(
        "--llm-model",
        dest="llm_model",
        help="nama model LLM untuk mesin llm (mis. gemini-2.5-flash)",
    )
    sub.add_argument(
        "--llm-base-url",
        dest="llm_base_url",
        help="endpoint dasar API OpenAI-compatible untuk mesin llm",
    )
    sub.add_argument(
        "--input-format",
        choices=tuple(sorted(INPUT_FORMAT_READERS)),
        help="paksa pembaca format masukan tertentu",
    )
    sub.add_argument(
        "--format",
        choices=tuple(REGISTERED_OUTPUT_FORMATS),
        help="format keluaran",
    )
    sub.add_argument(
        "--glossary",
        type=Path,
        help="berkas glosarium yang dibaca dan diperbarui",
    )
    sub.add_argument(
        "--honorifics",
        dest="honorific_style",
        choices=HONORIFIC_STYLES,
        help="keep: Tanaka-san, localize: Pak Tanaka, drop: Tanaka",
    )
    sub.add_argument(
        "--name-order",
        choices=NAME_ORDERS,
        help="jp: Yamada Tarō, western: Tarō Yamada",
    )
    sub.add_argument(
        "--romaji",
        dest="romanization",
        choices=ROMANIZATIONS,
        help="macron: Satō, kana: Satou, plain: Sato",
    )
    sub.add_argument(
        "--foreign-names",
        choices=FOREIGN_NAMES,
        help="nama asing katakana: auto, dict, atau hepburn",
    )
    sub.add_argument(
        "--allow-unofficial",
        action="store_true",
        default=None,
        help="izinkan endpoint Google tidak resmi",
    )
    sub.add_argument(
        "--no-detect",
        action="store_true",
        help="matikan deteksi entitas otomatis",
    )
    sub.add_argument(
        "--no-cache",
        action="store_true",
        help="pakai cache sementara di memori",
    )
    sub.add_argument(
        "--dry-run",
        action="store_true",
        help="perkirakan kalimat, karakter, dan kuota tanpa memanggil mesin",
    )
    sub.add_argument(
        "--limit",
        type=_positive_int,
        metavar="N",
        help="terjemahkan hanya N paragraf pertama",
    )
    sub.add_argument(
        "--encoding",
        help="paksa encoding berkas teks (mis. cp932, euc_jp, utf-8)",
    )
    sub.add_argument(
        "--bilingual",
        action="store_true",
        help="format txt: tulis baris Jepang asli di atas terjemahan",
    )
    sub.set_defaults(handler=cmd_translate)


def _add_detect(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "detect",
        parents=[common],
        help="tampilkan kandidat nama dan istilah di sebuah berkas",
    )
    sub.add_argument("input", help="berkas masukan, atau - untuk stdin")
    sub.add_argument("--title", help="judul karya")
    sub.add_argument("--glossary", type=Path, help="berkas glosarium")
    sub.add_argument("--encoding", help="paksa encoding berkas teks")
    sub.add_argument(
        "--input-format",
        choices=tuple(sorted(INPUT_FORMAT_READERS)),
        help="paksa pembaca format masukan tertentu",
    )
    sub.add_argument(
        "--save",
        action="store_true",
        help="simpan kandidat ke berkas glosarium",
    )
    sub.set_defaults(handler=cmd_detect)


def _add_ocr(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "ocr",
        parents=[common],
        help="ekstrak teks folder gambar komik/dokumen ke pages.json via Tesseract",
    )
    sub.add_argument("folder", type=Path, help="folder berisi gambar halaman")
    sub.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("pages.json"),
        help="lokasi berkas pages.json keluaran (bawaan: pages.json)",
    )
    sub.add_argument(
        "--lang",
        default="jpn_vert",
        help="model bahasa Tesseract (bawaan: jpn_vert; horizontal: jpn)",
    )
    sub.set_defaults(handler=cmd_ocr)


def _add_glossary(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "glossary", parents=[common], help="kelola glosarium per judul"
    )
    target = argparse.ArgumentParser(add_help=False)
    where = target.add_argument_group("glosarium")
    where.add_argument("--title", help="judul karya (berkas bawaan per judul)")
    where.add_argument("--glossary", type=Path, help="lokasi berkas glosarium")
    actions = sub.add_subparsers(dest="action", metavar="AKSI", required=True)

    show = actions.add_parser(
        "show", parents=[common, target], help="tampilkan isi glosarium"
    )
    show.set_defaults(handler=cmd_glossary_show)

    add = actions.add_parser(
        "add", parents=[common, target], help="tambah atau ubah satu entri"
    )
    add.add_argument("surface", help="tulisan Jepang, mis. 田中")
    add.add_argument(
        "--kind",
        choices=ENTITY_KINDS,
        default=ENTITY_KINDS[0],
        help="jenis entri",
    )
    add.add_argument("--reading", default="", help="bacaan kana, mis. たなか")
    add.add_argument(
        "--romaji", default="", help="ejaan Latin pilihan, mis. Tanaka"
    )
    add.add_argument("--render-id", default="", help="bentuk akhir Indonesia")
    add.add_argument("--render-en", default="", help="bentuk akhir Inggris")
    add.add_argument(
        "--gloss-id", default="", help="arti kemunculan pertama (ID)"
    )
    add.add_argument(
        "--gloss-en", default="", help="arti kemunculan pertama (EN)"
    )
    add.add_argument(
        "--gender",
        choices=("m", "f", "x", ""),
        default="",
        help="m, f, atau x (jangan ditebak)",
    )
    add.add_argument(
        "--alias",
        dest="aliases",
        action="append",
        default=[],
        help="tulisan lain untuk entitas yang sama",
    )
    add.add_argument(
        "--allow-compound",
        action="store_true",
        help="cocokkan walau menempel ke kanji lain",
    )
    add.set_defaults(handler=cmd_glossary_add)

    remove = actions.add_parser(
        "remove", parents=[common, target], help="hapus satu entri"
    )
    remove.add_argument("surface", help="tulisan atau alias")
    remove.set_defaults(handler=cmd_glossary_remove)

    export = actions.add_parser(
        "export",
        parents=[common, target],
        help="salin glosarium ke berkas JSON lain",
    )
    export.add_argument("path", type=Path, help="berkas tujuan")
    export.set_defaults(handler=cmd_glossary_export)

    imp = actions.add_parser(
        "import",
        parents=[common, target],
        help="gabungkan entri dari berkas JSON ke glosarium",
    )
    imp.add_argument("path", type=Path, help="berkas glosarium sumber")
    imp.set_defaults(handler=cmd_glossary_import)


def _add_cache(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "cache", parents=[common], help="lihat statistik atau bersihkan cache"
    )
    actions = sub.add_subparsers(dest="action", metavar="AKSI", required=True)
    stats_cmd = actions.add_parser(
        "stats", parents=[common], help="tampilkan jumlah entri cache per mesin"
    )
    stats_cmd.set_defaults(handler=cmd_cache_stats)
    clear_cmd = actions.add_parser(
        "clear", parents=[common], help="kosongkan seluruh isi cache terjemahan"
    )
    clear_cmd.set_defaults(handler=cmd_cache_clear)


def _add_serve(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "serve", parents=[common], help="jalankan antarmuka web lokal"
    )
    sub.add_argument(
        "--host", default="127.0.0.1", help="alamat bind (bawaan 127.0.0.1)"
    )
    sub.add_argument(
        "--port",
        type=_port,
        default=8765,
        help="port (bawaan 8765; 0 = pilih otomatis)",
    )
    sub.add_argument(
        "--lan",
        action="store_true",
        help="bind 0.0.0.0 agar dapat diakses perangkat di jaringan LAN yang sama",
    )
    sub.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="buka peramban secara otomatis setelah server siap",
    )
    sub.set_defaults(handler=cmd_serve)


def _add_doctor(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "doctor",
        parents=[common],
        help="periksa versi Python, folder data, mesin, dan plugin",
    )
    sub.add_argument(
        "--online",
        action="store_true",
        help="uji koneksi nyata ke tiap mesin yang tersedia",
    )
    sub.set_defaults(handler=cmd_doctor)


def _add_test(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "test",
        parents=[common],
        help="jalankan rangkaian unit test otomatis bawaan",
    )
    sub.add_argument(
        "-k",
        "--pattern",
        default="",
        help="jalankan hanya pengujian yang namanya memuat pola ini",
    )
    sub.set_defaults(handler=cmd_test)


def _add_unpack(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "unpack",
        parents=[common],
        help="ekstrak skrip tunggal ini menjadi paket multi-berkas jptrans/",
    )
    sub.add_argument(
        "dest",
        type=Path,
        help="folder induk tujuan (akan membuat <dest>/jptrans/...)",
    )
    sub.add_argument(
        "--force",
        action="store_true",
        help="timpa berkas yang sudah ada di folder tujuan",
    )
    sub.set_defaults(handler=cmd_unpack)


def _port(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"bukan bilangan bulat: {text!r}"
        ) from exc
    if not 0 <= value <= MAX_PORT:
        raise argparse.ArgumentTypeError(f"port harus 0 sampai {MAX_PORT}")
    return value


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"bukan bilangan bulat: {text!r}"
        ) from exc
    if value < 1:
        raise argparse.ArgumentTypeError("harus minimal 1")
    return value


def main(argv: list[str] | None = None) -> int:
    """Titik masuk utama CLI; mengembalikan kode keluar numerik."""
    _use_utf8_stdout()
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_OK
    stdout = _StdoutWatch(sys.stdout)
    try:
        configure_logging(
            args.verbose,
            args.quiet,
            args.log_file,
            args.debug,
            log_json=args.log_json,
        )
        with stdout:
            code: int = args.handler(args)
            if sys.stdout is not None:
                sys.stdout.flush()
        return code
    except BrokenPipeError:
        if not stdout.broken:
            raise
        _silence_stdout()
        return EXIT_BROKEN_PIPE
    except KeyboardInterrupt:
        _err(
            "\nDihentikan. Kalimat yang sudah selesai tersimpan di cache; "
            "jalankan perintah yang sama untuk melanjutkan."
        )
        return EXIT_INTERRUPTED
    except JptransError as exc:
        if args.debug:
            traceback.print_exc()
        _err(f"galat: {exc}")
        return exc.exit_code
    except UnicodeEncodeError:
        if _filesystem_is_utf8():
            raise
        if args.debug:
            traceback.print_exc()
        _err(f"galat: {NON_UTF8_FS_HINT}")
        return JptransError.exit_code


def configure_logging(
    verbose: int = 0,
    quiet: bool = False,
    log_file: Path | None = None,
    debug: bool = False,
    *,
    log_json: bool = False,
) -> None:
    """Pasang handler log berstempel waktu (atau JSON) pada logger ``jptrans``."""
    if debug or verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.ERROR if quiet else logging.WARNING
    root = logging.getLogger("jptrans")
    for handler in [
        h for h in root.handlers if getattr(h, "_jptrans_cli", False)
    ]:
        root.removeHandler(handler)
        handler.close()
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(
                f"berkas log {log_file} tidak bisa dibuka: {exc}"
            ) from exc
    formatter: logging.Formatter = (
        JsonLogFormatter()
        if log_json
        else logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    )
    for handler in handlers:
        handler.setFormatter(formatter)
        handler._jptrans_cli = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)


def cmd_translate(args: argparse.Namespace) -> int:
    """Subperintah ``translate``."""
    cfg = _load_config(args, _translate_overrides(args))
    doc = _read_input(
        args.input, args.title, args.encoding, args.input_format
    )
    if args.limit:
        doc.paragraphs = doc.paragraphs[: args.limit]
    glossary_path = args.glossary or default_glossary_path(cfg, doc.title)
    glossary = Glossary.load(glossary_path, doc.title)
    if args.dry_run:
        _print_estimate(estimate(doc, cfg, glossary))
        return EXIT_OK
    engines = build_engines(cfg)
    logger.info("mesin aktif: %s", ", ".join(engine.name for engine in engines))
    has_tty = sys.stderr is not None and sys.stderr.isatty()
    progress = None if args.quiet or not has_tty else _show_progress
    with TranslationCache(None if args.no_cache else cfg.cache_path) as cache:
        translator = Translator(
            cfg,
            engines,
            cache,
            glossary,
            progress=progress,
            glossary_path=glossary_path,
        )
        result = translator.translate_document(doc)
    if progress is not None:
        _err("")
    destination = _write_result(result, args, cfg)
    if not args.quiet:
        _print_summary(result, destination, to_stderr=destination is None)
    return EXIT_OK


def _translate_overrides(args: argparse.Namespace) -> dict[str, Any]:
    engines = None
    if args.engines:
        engines = [
            name.strip()
            for item in args.engines
            for name in item.split(",")
            if name.strip()
        ]
    return {
        "target_lang": args.target_lang,
        "engines": engines,
        "llm_model": args.llm_model,
        "llm_base_url": args.llm_base_url,
        "honorific_style": args.honorific_style,
        "name_order": args.name_order,
        "romanization": args.romanization,
        "foreign_names": args.foreign_names,
        "allow_unofficial": args.allow_unofficial,
        "auto_detect": False if args.no_detect else None,
        "output_format": args.format,
    }


def _write_result(
    result: TranslatedDocument, args: argparse.Namespace, cfg: Config
) -> Path | None:
    to_stdout = args.output == STDOUT or (
        args.output is None and args.input == STDIN
    )
    out = None if to_stdout or args.output is None else Path(args.output)
    fmt = args.format or (
        SUFFIX_FORMATS.get(out.suffix.lower()) if out else None
    )
    fmt = fmt or cfg.output_format
    if to_stdout:
        if sys.stdout is not None:
            sys.stdout.write(
                render_output(result, fmt, bilingual=args.bilingual)
            )
        return None
    if out is None:
        source = Path(args.input)
        out = source.with_name(f"{source.stem}.{cfg.target_lang}.{fmt}")
    return write_output(result, out, fmt, bilingual=args.bilingual)


def _print_summary(
    result: TranslatedDocument, out: Path | None, *, to_stderr: bool
) -> None:
    stats = result.stats
    statuses = ", ".join(
        f"{name} {count}" for name, count in stats["by_status"].items()
    )
    total = sum(stats["by_status"].values())
    lines = [
        f"Selesai: {total} kalimat ({statuses or '-'}) "
        f"dalam {stats['seconds']} detik."
    ]
    if stats.get("by_engine"):
        engines = ", ".join(
            f"{name} {count}" for name, count in stats["by_engine"].items()
        )
        lines.append(
            f"Mesin: {engines}; {stats['requests']} permintaan, "
            f"{stats['chars_sent']} karakter terkirim."
        )
    if stats.get("new_entries"):
        lines.append(
            f"Glosarium: {stats['new_entries']} entri baru (periksa dengan "
            f"'python3 translator.py glossary show "
            f"--title \"{result.document.title}\"')."
        )
    failed = stats["by_status"].get("failed", 0)
    if failed:
        lines.append(
            f"Peringatan: {failed} kalimat gagal diterjemahkan "
            "dan ditampilkan asli."
        )
    partial = stats["by_status"].get("partial", 0)
    if partial:
        lines.append(
            f"Peringatan: {partial} kalimat masih memuat huruf Jepang."
        )
    if out is not None:
        lines.append(f"Keluaran: {out}")
    for line in lines:
        (_err if to_stderr else print)(line)


def _print_estimate(info: dict) -> None:
    print(f"Judul        : {info['title']}")
    print(f"Paragraf     : {info['paragraphs']}")
    print(
        f"Kalimat      : {info['sentences']} "
        f"({info['translatable']} diterjemahkan, {info['plain']} disalin)"
    )
    print(
        f"Karakter     : {info['source_chars']} asli, "
        f"{info['masked_chars']} setelah masking"
    )
    print(
        f"Entitas      : {info['entities']} dimasking, "
        f"{info['new_entries']} entri baru dari deteksi"
    )
    if info["unrenderable"]:
        print(
            f"Tanpa bacaan : {', '.join(info['unrenderable'])} "
            "(ejaan ditanyakan ke mesin)"
        )
    print("Permintaan per mesin:")
    for engine in info["engines"]:
        state = "siap" if engine["available"] else "tidak tersedia"
        print(
            f"  {engine['name']:<15} {engine['requests']:>5}  "
            f"({state}: {engine['reason']})"
        )
    print("Perkiraan kuota gratis (bila semua dikirim ke satu mesin):")
    for name, quota in info["quota"].items():
        print(
            f"  {name:<15} {quota['percent']:>6}% dari "
            f"{quota['limit']} karakter/{quota['period']}"
        )


def _show_progress(progress: Progress) -> None:
    if sys.stderr is not None:
        sys.stderr.write(
            f"\r[{progress.done}/{progress.total}] {progress.message:<12}"
        )
        sys.stderr.flush()


def cmd_detect(args: argparse.Namespace) -> int:
    """Subperintah ``detect``."""
    cfg = _load_config(args)
    doc = _read_input(
        args.input, args.title, args.encoding, args.input_format
    )
    glossary_path = args.glossary or default_glossary_path(cfg, doc.title)
    glossary = Glossary.load(glossary_path, doc.title)
    known = set(glossary.surface_map(confirmed_only=False))
    candidates = detect_entities(doc, known, use_janome=janome_available())
    locked, review = candidates_to_entries(candidates, cfg)
    status = {entry.surface: "kunci" for entry in locked}
    status.update({entry.surface: "tinjau" for entry in review})
    rows = [
        (
            f"{cand.score:.2f}",
            cand.kind,
            status.get(cand.surface, "-"),
            cand.reading,
            str(cand.count),
            cand.surface,
        )
        for cand in candidates
    ]
    _print_table(("skor", "jenis", "status", "bacaan", "jumlah", "tulisan"), rows)
    print(
        f"{len(candidates)} kandidat: "
        f"{len(locked)} dikunci, {len(review)} perlu ditinjau."
    )
    if args.save:
        added = sum(glossary.upsert(entry) for entry in locked + review)
        glossary.save(glossary_path)
        print(f"{added} entri disimpan ke {glossary_path}")
    return EXIT_OK


def cmd_ocr(args: argparse.Namespace) -> int:
    """Subperintah ``ocr``: jalankan Tesseract pada folder gambar ke ``pages.json``."""
    _load_config(args)
    out = ocr_images_to_pages(args.folder, args.output, args.lang)
    print(f"Hasil OCR disimpan ke {out}")
    return EXIT_OK


def cmd_glossary_show(args: argparse.Namespace) -> int:
    """Subperintah ``glossary show``."""
    cfg, path, glossary = _open_glossary(args)
    renderer = Renderer(cfg)
    rows = [
        (
            entry.surface,
            entry.kind,
            entry.reading,
            renderer.base_name(entry) or "?",
            "ya" if entry.confirmed else "tinjau",
            entry.source,
        )
        for entry in glossary
    ]
    print(f"Glosarium '{glossary.title}' ({path}): {len(glossary)} entri")
    if rows:
        _print_table(
            ("tulisan", "jenis", "bacaan", "bentuk", "pasti", "asal"), rows
        )
    return EXIT_OK


def cmd_glossary_add(args: argparse.Namespace) -> int:
    """Subperintah ``glossary add``."""
    _, path, glossary = _open_glossary(args)
    entry = GlossaryEntry(
        surface=args.surface.strip(),
        kind=args.kind,
        reading=kata_to_hira(args.reading),
        romaji=args.romaji,
        render_id=args.render_id,
        render_en=args.render_en,
        gloss_id=args.gloss_id,
        gloss_en=args.gloss_en,
        gender=args.gender,
        aliases=tuple(args.aliases),
        allow_compound=args.allow_compound,
        confirmed=True,
        source=USER_SOURCE,
    )
    if not entry.surface:
        raise ConfigError("tulisan entri tidak boleh kosong")
    glossary.upsert(entry, overwrite_confirmed=True)
    glossary.save(path)
    print(f"Entri {entry.surface} disimpan ke {path}")
    return EXIT_OK


def cmd_glossary_remove(args: argparse.Namespace) -> int:
    """Subperintah ``glossary remove``."""
    _, path, glossary = _open_glossary(args)
    if not glossary.remove(args.surface):
        raise InputError(f"entri {args.surface} tidak ada di {path}")
    glossary.save(path)
    print(f"Entri {args.surface} dihapus dari {path}")
    return EXIT_OK


def cmd_glossary_export(args: argparse.Namespace) -> int:
    """Subperintah ``glossary export``."""
    _, path, glossary = _open_glossary(args)
    glossary.save(args.path)
    print(f"{len(glossary)} entri dari {path} diekspor ke {args.path}")
    return EXIT_OK


def cmd_glossary_import(args: argparse.Namespace) -> int:
    """Subperintah ``glossary import``."""
    _, path, glossary = _open_glossary(args)
    if not args.path.is_file():
        raise InputError(f"berkas glosarium tidak ditemukan: {args.path}")
    incoming = Glossary.load(args.path)
    added = sum(glossary.upsert(entry) for entry in incoming)
    glossary.save(path)
    print(f"{added} dari {len(incoming)} entri diimpor ke {path}")
    return EXIT_OK


def _open_glossary(
    args: argparse.Namespace,
) -> tuple[Config, Path, Glossary]:
    cfg = _load_config(args)
    if args.glossary is None and not args.title:
        raise ConfigError("sebutkan --title JUDUL atau --glossary BERKAS")
    path = args.glossary or default_glossary_path(cfg, args.title)
    return cfg, path, Glossary.load(path, args.title)


def cmd_cache_stats(args: argparse.Namespace) -> int:
    """Subperintah ``cache stats``."""
    cfg = _load_config(args)
    with TranslationCache(cfg.cache_path) as cache:
        info = cache.stats()
    print(f"Lokasi : {info['path']}")
    print(f"Total  : {info['entries']} entri")
    if info["per_engine"]:
        for engine, count in sorted(info["per_engine"].items()):
            print(f"  {engine:<15} {count}")
    return EXIT_OK


def cmd_cache_clear(args: argparse.Namespace) -> int:
    """Subperintah ``cache clear``."""
    cfg = _load_config(args)
    with TranslationCache(cfg.cache_path) as cache:
        removed = cache.clear()
    print(f"Cache dibersihkan: {removed} entri dihapus dari {cfg.cache_path}")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Subperintah ``serve``."""
    from .server import serve

    cfg = _load_config(args)
    serve(
        cfg,
        args.host,
        args.port,
        lan=args.lan,
        open_browser=args.open_browser,
        on_ready=_announce_server,
    )
    return EXIT_OK


def _announce_server(url: str, lan: bool) -> None:
    print(
        f"jptrans {__version__} siap. "
        "Buka alamat ini di browser (berisi token rahasia):"
    )
    print(f"  {url}")
    if lan:
        print(
            "Mode LAN aktif: siapa pun di jaringan lokal yang memiliki "
            "tautan bertoken ini dapat memakai server."
        )
    print("Tekan Ctrl+C untuk berhenti.")


def cmd_doctor(args: argparse.Namespace) -> int:
    """Subperintah ``doctor``."""
    cfg = _load_config(args)
    print(f"jptrans  : {__version__}")
    print(f"Python   : {platform.python_version()} ({sys.executable})")
    print(f"Platform : {platform.platform()}")
    fs_note = "" if _filesystem_is_utf8() else f" ({NON_UTF8_FS_HINT})"
    print(
        f"Encoding : nama berkas {sys.getfilesystemencoding()}, "
        f"locale {locale.getencoding()}, "
        f"mode UTF-8 {'aktif' if sys.flags.utf8_mode else 'mati'}{fs_note}"
    )
    print(
        f"Data     : {cfg.home} "
        f"({'ada' if cfg.home.is_dir() else 'belum dibuat'})"
    )
    cache_note = (
        ""
        if PERSISTENT_CACHE
        else " (sqlite3 tidak ada: cache hanya di memori)"
    )
    print(f"Cache    : {cfg.cache_path}{cache_note}")
    print(f"Glosarium: {cfg.glossary_dir}")
    print("Mesin:")
    for name, available, reason in describe_engines(cfg):
        print(f"  [{'ok' if available else '--'}] {name:<15} {reason}")
    tesseract = shutil.which("tesseract")
    print("Plugin opsional:")
    janome = (
        "terpasang"
        if janome_available()
        else "tidak ada (pip install janome)"
    )
    print(f"  janome    : {janome}")
    print(
        f"  tesseract : "
        f"{tesseract or 'tidak ada (OCR komik tidak tersedia)'}"
    )
    if args.online:
        _doctor_online(cfg)
    return EXIT_OK


def _doctor_online(cfg: Config) -> None:
    print("Uji koneksi:")
    try:
        engines = build_engines(
            cfg, [name for name, ok, _ in describe_engines(cfg) if ok]
        )
    except ConfigError as exc:
        print(f"  {exc}")
        return
    for engine in engines:
        started = time.monotonic()
        try:
            result = engine.translate([ONLINE_TEST_TEXT], "ja", cfg.target_lang)
        except JptransError as exc:
            print(f"  [gagal] {engine.name}: {exc}")
            continue
        elapsed = time.monotonic() - started
        print(f"  [ok] {engine.name}: {result[0]!r} ({elapsed:.1f} s)")


def cmd_test(args: argparse.Namespace) -> int:
    """Subperintah ``test``: jalankan suite pengujian otomatis bawaan."""
    from .selftest import run_tests

    verbosity = 2 if args.verbose else (0 if args.quiet else 1)
    ok = run_tests(verbosity=verbosity, pattern=args.pattern)
    return EXIT_OK if ok else EXIT_TEST_FAILED


def cmd_unpack(args: argparse.Namespace) -> int:
    """Subperintah ``unpack``: ekstrak paket ``jptrans`` untuk pengembangan aplikasi."""
    written = unpack_package(args.dest, overwrite=args.force)
    print(f"{len(written)} berkas paket diekstrak ke {Path(args.dest) / 'jptrans'}")
    return EXIT_OK


def _load_config(
    args: argparse.Namespace, overrides: dict[str, Any] | None = None
) -> Config:
    return load_config(args.config, overrides)


def _read_input(
    source: str,
    title: str | None,
    encoding: str | None,
    input_format: str | None = None,
) -> Document:
    if source != STDIN:
        return read_document(
            Path(source),
            title=title,
            encoding=encoding,
            input_format=input_format,
        )
    raw = (
        sys.stdin.buffer.read()
        if hasattr(sys.stdin, "buffer")
        else sys.stdin.read().encode()
    )
    if input_format and input_format != "auto":
        with tempfile.TemporaryDirectory(prefix="jptrans-stdin-") as folder:
            temp_path = Path(folder) / f"stdin.{input_format}"
            temp_path.write_bytes(raw)
            doc = read_document(
                temp_path,
                title=title or "stdin",
                encoding=encoding,
                input_format=input_format,
            )
            doc.source_path = ""
            return doc
    return read_text(decode_bytes(raw, encoding), title or "stdin")


def _print_table(
    header: Sequence[str], rows: Sequence[Sequence[str]]
) -> None:
    widths = [
        max(_width(row[i]) for row in [header, *rows])
        for i in range(len(header))
    ]
    for row in [header, *rows]:
        print(
            "  ".join(
                _pad(cell, width) for cell, width in zip(row, widths)
            ).rstrip()
        )


def _width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text
    )


def _pad(text: str, width: int) -> str:
    return text + " " * (width - _width(text))


def _err(message: str) -> None:
    if sys.stderr is not None:
        print(message, file=sys.stderr)


def _silence_stdout() -> None:
    logger.debug("stdout ditutup pembaca; sisa keluaran dibuang")
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        if sys.stdout is not None:
            os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        logger.debug("stdout tidak bisa dialihkan ke devnull")
    finally:
        os.close(devnull)


class _StdoutWatch:
    """Pembungkus ``sys.stdout`` yang mendeteksi ``BrokenPipeError`` pada stdout."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.broken = False

    def __enter__(self) -> _StdoutWatch:
        if self.stream is not None:
            sys.stdout = self  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: object) -> None:
        if sys.stdout is self:
            sys.stdout = self.stream

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)

    def write(self, text: str) -> int:
        return self._guard(self.stream.write, text)

    def writelines(self, lines: Any) -> None:
        self._guard(self.stream.writelines, lines)

    def flush(self) -> None:
        self._guard(self.stream.flush)

    def _guard(self, method: Callable[..., Any], *args: Any) -> Any:
        try:
            return method(*args)
        except BrokenPipeError:
            self.broken = True
            raise


def _filesystem_is_utf8() -> bool:
    return sys.getfilesystemencoding().lower().replace("-", "") == "utf8"


def _use_utf8_stdout() -> None:
    for stream, errors in (
        (sys.stdout, "surrogateescape"),
        (sys.stderr, "backslashreplace"),
    ):
        reconfigure: Callable[..., None] | None = getattr(
            stream, "reconfigure", None
        )
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors=errors)
            except (OSError, ValueError):
                logger.debug("stream tidak bisa dikonfigurasi ulang ke UTF-8")


if __name__ == "__main__":
    sys.exit(main())
''')

MODUL['jptrans.config'] = (
    False,
r'''"""Konfigurasi program dan pemuat variabel lingkungan ``.env``.

Urutan prioritas nilai: argumen CLI > variabel lingkungan proses > berkas ``.env``
> berkas ``config.json`` > nilai bawaan dataclass. Kunci API tidak pernah
disimpan di objek ``Config`` atau ditulis ke disk; mesin membacanya langsung
dari ``os.environ``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .textnorm import decode_unicode_text

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1
LANGS = ("id", "en")
HONORIFIC_STYLES = ("keep", "localize", "drop")
NAME_ORDERS = ("jp", "western")
ROMANIZATIONS = ("macron", "kana", "plain")
UNKNOWN_READING = ("keep", "engine")
FOREIGN_NAMES = ("auto", "dict", "hepburn")
OUTPUT_FORMATS = ("html", "txt", "md", "json", "srt", "vtt", "ass")
REGISTERED_OUTPUT_FORMATS: list[str] = list(OUTPUT_FORMATS)
DEFAULT_ENGINES = ("deepl", "llm", "google", "mymemory")
DEFAULT_LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_LLM_MODEL = "gemini-2.5-flash"

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_SUFFIXES = (
    "_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
)


def effective_name_order(name_order: str | None, lang: str) -> str:
    """Urutan nama efektif: pilihan eksplisit, atau ``jp`` (ID) / ``western`` (EN)."""
    if name_order:
        return name_order
    return "jp" if lang == "id" else "western"


def default_home() -> Path:
    """Folder data jptrans: ``$JPTRANS_HOME`` atau ``~/.jptrans``."""
    env = os.environ.get("JPTRANS_HOME")
    return Path(env).expanduser() if env else Path.home() / ".jptrans"


def load_dotenv(dotenv_path: Path | None = None, *, override: bool = False) -> int:
    """Muat berkas ``.env`` secara aman tanpa ``eval`` ke ``os.environ``.

    Baris kosong, komentar ``#``, serta kunci tidak sah dilewati. Tanda kutip
    tunggal atau ganda yang berpasangan di tepi nilai dikupas. Secara bawaan
    variabel lingkungan yang sudah ada di shell tidak ditimpa (``override=False``).

    Returns:
        Jumlah variabel baru yang berhasil dimasukkan ke ``os.environ``.
    """
    paths = (
        [dotenv_path]
        if dotenv_path is not None
        else [Path.cwd() / ".env", default_home() / ".env"]
    )
    loaded = 0
    for candidate in paths:
        if not candidate.is_file():
            continue
        try:
            content = decode_unicode_text(candidate.read_bytes())
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("berkas .env %s dilewati: %s", candidate, exc)
            continue
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, value = line.split("=", 1)
            key = key.strip()
            if not _ENV_KEY_RE.match(key):
                continue
            cleaned = _strip_env_quotes(value.strip())
            if override or key not in os.environ:
                os.environ[key] = cleaned
                loaded += 1
    return loaded


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] in ("'", '"'):
        quote_ch = value[0]
        end = value.find(quote_ch, 1)
        if end >= 1:
            rest = value[end + 1:].strip()
            if not rest or rest.startswith("#"):
                return value[1:end]
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    return value


@dataclass
class Config:
    """Semua pengaturan yang memengaruhi proses dan hasil terjemahan."""

    source_lang: str = "ja"
    target_lang: str = "id"
    honorific_style: str = "keep"
    name_order: str | None = None
    romanization: str = "macron"
    unknown_reading: str = "engine"
    foreign_names: str = "auto"
    first_gloss: bool = True
    engines: list[str] = field(default_factory=lambda: list(DEFAULT_ENGINES))
    allow_unofficial: bool = False
    auto_detect: bool = True
    auto_lock_threshold: float = 0.6
    candidate_threshold: float = 0.35
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    request_delay: float = 1.0
    output_format: str = "html"
    home: Path = field(default_factory=default_home)
    config_version: int = CONFIG_VERSION

    def __post_init__(self) -> None:
        self.home = Path(self.home).expanduser()
        self.validate()

    @property
    def cache_path(self) -> Path:
        """Lokasi berkas cache sqlite3."""
        return self.home / "cache.sqlite3"

    @property
    def glossary_dir(self) -> Path:
        """Folder glosarium per judul."""
        return self.home / "glossaries"

    def validate(self) -> None:
        """Periksa tipe, rentang, dan pilihan semua field; lempar ``ConfigError``."""
        _choice("target_lang", self.target_lang, LANGS)
        _choice("honorific_style", self.honorific_style, HONORIFIC_STYLES)
        if self.name_order is not None:
            _choice("name_order", self.name_order, NAME_ORDERS)
        _choice("romanization", self.romanization, ROMANIZATIONS)
        _choice("unknown_reading", self.unknown_reading, UNKNOWN_READING)
        _choice("foreign_names", self.foreign_names, FOREIGN_NAMES)
        _choice(
            "output_format",
            self.output_format,
            tuple(REGISTERED_OUTPUT_FORMATS),
        )
        for flag in ("first_gloss", "allow_unofficial", "auto_detect"):
            _boolean(flag, getattr(self, flag))
        for text_field in ("llm_base_url", "llm_model"):
            val = getattr(self, text_field)
            if not isinstance(val, str) or not val.strip():
                raise ConfigError(f"{text_field} harus string tidak kosong")
        if self.source_lang != "ja":
            raise ConfigError("source_lang saat ini hanya mendukung 'ja'")
        if not isinstance(self.engines, list) or not all(
            isinstance(name, str) for name in self.engines
        ):
            raise ConfigError(
                'engines harus daftar nama mesin, mis. ["deepl", "mymemory"]'
            )
        if not self.engines:
            raise ConfigError("daftar engines tidak boleh kosong")
        for name in (
            "auto_lock_threshold",
            "candidate_threshold",
            "request_delay",
        ):
            _number(name, getattr(self, name))
        for name in ("auto_lock_threshold", "candidate_threshold"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ConfigError(
                    f"{name} harus di antara 0 dan 1, bukan {value}"
                )
        if self.candidate_threshold > self.auto_lock_threshold:
            raise ConfigError(
                "candidate_threshold tidak boleh melebihi auto_lock_threshold"
            )
        if self.request_delay < 0:
            raise ConfigError("request_delay tidak boleh negatif")


def _boolean(name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise ConfigError(
            f"{name} harus boolean (true/false), bukan {value!r}"
        )


def _number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} harus angka, bukan {value!r}")


def _choice(name: str, value: object, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ConfigError(
            f"{name}={value!r} tidak valid; pilihan: {', '.join(allowed)}"
        )


_ENV_MAP = {
    "JPTRANS_TARGET": "target_lang",
    "JPTRANS_ENGINES": "engines",
    "JPTRANS_LLM_BASE_URL": "llm_base_url",
    "JPTRANS_LLM_MODEL": "llm_model",
    "JPTRANS_ALLOW_UNOFFICIAL": "allow_unofficial",
}


def load_config(
    path: Path | None = None, overrides: dict[str, Any] | None = None
) -> Config:
    """Muat konfigurasi dengan urutan prioritas default < file < .env < env < CLI."""
    load_dotenv()
    values: dict[str, Any] = {}
    file_path = path or default_home() / "config.json"
    if file_path.is_file():
        values.update(_read_config_file(file_path))
    elif path is not None:
        raise ConfigError(f"berkas config tidak ditemukan: {path}")

    for env_name, key in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw:
            values[key] = _parse_env(key, raw)

    for key, value in (overrides or {}).items():
        if value is not None:
            values[key] = value

    known = {f.name for f in fields(Config)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ConfigError(f"kunci config tidak dikenal: {', '.join(unknown)}")
    try:
        return Config(**values)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"config tidak valid: {exc}") from exc


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(decode_unicode_text(path.read_bytes()))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"tidak bisa membaca {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} harus berisi objek JSON")
    secrets = [
        k for k in data if k.lower().endswith(_SECRET_SUFFIXES)
    ]
    if secrets:
        raise ConfigError(
            f"{path} memuat rahasia ({', '.join(secrets)}); "
            "simpan kunci di variabel lingkungan atau .env"
        )
    logger.debug("config dimuat dari %s", path)
    return data


def _parse_env(key: str, raw: str) -> Any:
    if key == "engines":
        return [name.strip() for name in raw.split(",") if name.strip()]
    if key == "allow_unofficial":
        lowered = raw.strip().lower()
        if lowered in {"1", "true", "yes", "ya"}:
            return True
        if lowered in {"0", "false", "no", "tidak"}:
            return False
        raise ConfigError(
            f"JPTRANS_ALLOW_UNOFFICIAL={raw!r} harus true/false atau 1/0"
        )
    return raw
''')

MODUL['jptrans.coref'] = (
    False,
r'''"""Analisis wacana narasi, kata ganti orang ketiga, sapaan, dan petunjuk LLM.

Modul ini memisahkan bagian narasi dari dialog Jepang (「…」, 『…』), menentukan
gender kata ganti yang aman dikoreksi (``pronoun_gender`` dan
``explicit_pronoun``), serta merakit baris petunjuk glosarium untuk LLM.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence

from .disambig import DASH_BREAKS
from .models import PERSON, GlossaryEntry, Masked, Slot
from .protect import EXACT_TOKEN_RE
from .textnorm import contains_japanese

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "PERSON": "orang",
    "PLACE": "tempat",
    "ORG": "organisasi",
    "TERM": "istilah",
    "CULTURE": "budaya",
}
GENDER_LABELS = {"m": "laki-laki", "f": "perempuan"}
SPEAKER_QUOTES = ('"', "“", "「", "『", "«")

_LEADING_VOCATIVE_RE = re.compile(
    r"""[\s「『（(“"'"""
    + re.escape(DASH_BREAKS)
    + r"""]*\[\[E(\d+)\]\][ \t\u3000]*[、，,]"""
)

QUOTE_OPENERS = "「『（(“"
QUOTE_CLOSERS = "」』）)”"
OTHER_PERSON_WORDS = (
    "彼", "あいつ", "こいつ", "そいつ", "どいつ", "奴", "やつ", "少年", "少女", "青年", "男", "女",
    "子供", "子ども", "赤ちゃん", "この人", "その人", "あの人", "どの人", "誰", "者", "兄", "姉",
    "弟", "妹", "父", "母", "親", "先輩", "後輩", "先生", "友達", "友人", "仲間", "主人", "持ち主",
    "店員", "客", "王", "姫", "その", "あの",
    "運転手", "選手", "相手", "歌手", "助手", "投手", "騎手", "犯人", "老人", "恋人", "他人",
    "人々", "住人", "職人", "商人", "婦人", "夫人", "新人", "知人", "隣人", "証人", "囚人",
    "管理人", "番人", "人間", "店長", "店主", "社長", "部長", "校長", "課長", "会長", "隊長",
    "船長", "院長", "署長", "団長", "委員", "駅員", "社員", "職員", "係員", "警備員", "乗務員",
    "隊員", "部員", "警官", "警察", "刑事", "探偵", "上官", "教官", "医師", "教師", "講師",
    "看護師", "牧師", "漁師", "師匠", "生徒", "学生", "年生", "校生", "入生", "級生", "上司",
    "部下", "同僚", "家族", "夫婦", "旦那", "妻", "息子", "娘", "皆", "みんな", "全員", "相棒",
    "恩人", "兵", "騎士", "侍", "敵",
)
_OTHER_PERSON_RE = re.compile("|".join(map(re.escape, OTHER_PERSON_WORDS)))

NOT_SINGLE_PRONOUNS = (
    "彼ら", "彼等", "彼たち", "彼女ら", "彼女等", "彼女たち", "彼氏", "元彼",
    "今彼", "前彼", "旧彼",
)
_EXPLICIT_PRONOUN_RE = re.compile("彼女|彼")

PARTNER_VERBS = (
    "デート", "付き合", "付きあ", "つきあ", "ツキア", "別れ", "わかれ", "ワカレ", "振ら",
    "ふら", "フラ", "振っ", "ふっ", "フッ",
)
PARTNER_PHRASES = (
    "ができ", "が出来", "がデキ", "がいる", "がいない", "が居る", "が居な", "を作",
    "をつく", "を紹介", "持ち", "が欲し", "がほし", "欲し", "ほし",
)
_PARTNER_RE = re.compile(
    f"(?:彼女|彼)(?:(?:と|が|に|を|は|も|って)?(?:{'|'.join(PARTNER_VERBS)})"
    f"|{'|'.join(PARTNER_PHRASES)})"
)
_PRONOUN_FOLLOWERS = frozenset(
    "はがのをにともへでやかまっなしさこばすだじよね、。，．,.！？!?…‥」』）)～〜ー"
)
_APPOSITION_RE = re.compile(
    "(?:" + "|".join(map(re.escape, OTHER_PERSON_WORDS)) + r")の(?=\[\[E\d+\]\])"
)
_STRAY_HONORIFIC_RE = re.compile(r"(?<!\]\])(?:さん|くん|ちゃん|様|さま|殿|氏|君|たん)")
_VOCATIVE_RE = re.compile(
    r"\[\[E(\d+)\]\](?=[、，,！!？?]|$)|[、，,]\[\[E(\d+)\]\](?=[。．.！!？?…‥ー〜～]*$)"
)


def narrative_part(text: str) -> str:
    """Kembalikan bagian kalimat di luar kutipan 「」『』（） tempat narasi berada."""
    kept: list[str] = []
    depth = 0
    for ch in text:
        if ch in QUOTE_OPENERS:
            depth += 1
        elif ch in QUOTE_CLOSERS:
            if depth:
                depth -= 1
            else:
                kept.clear()
        elif not depth:
            kept.append(ch)
    return "".join(kept)


def pronoun_gender(
    masked: Masked,
    context: Sequence[Masked],
    gender_of: Callable[[GlossaryEntry], str],
    others: Sequence[str] = (),
) -> str:
    """Gender kata ganti orang ketiga yang aman dipaksakan pada terjemahan kalimat ini."""
    own = _narrative_persons(masked, others)
    if own is None:
        return ""
    if not own:
        if not contains_japanese(EXACT_TOKEN_RE.sub("", narrative_part(masked.text))):
            return ""
        for other in context:
            found = _narrative_persons(other, others)
            if found is None:
                return ""
            own.extend(found)
    if len(_distinct_people(own)) != 1:
        return ""
    genders = {gender_of(entry) for entry in own}
    return genders.pop() if len(genders) == 1 and genders <= {"m", "f"} else ""


def explicit_pronoun(text: str) -> tuple[str, int]:
    """Gender dan jumlah kata ganti orang ketiga tunggal eksplisit (彼, 彼女)."""
    if any(word in text for word in NOT_SINGLE_PRONOUNS) or _PARTNER_RE.search(text):
        return "", 0
    genders: list[str] = []
    for match in _EXPLICIT_PRONOUN_RE.finditer(text):
        after = text[match.end():match.end() + 1]
        if (
            after
            and after not in _PRONOUN_FOLLOWERS
            and not text.startswith("自身", match.end())
        ):
            return "", 0
        genders.append("f" if match.group() == "彼女" else "m")
    if not genders or len(set(genders)) != 1:
        return "", 0
    return genders[0], len(genders)


def _narrative_persons(
    masked: Masked, others: Sequence[str] = ()
) -> list[GlossaryEntry] | None:
    bare = EXACT_TOKEN_RE.sub("", _APPOSITION_RE.sub("", masked.text))
    if (
        _OTHER_PERSON_RE.search(bare)
        or _STRAY_HONORIFIC_RE.search(masked.text)
        or any(other and other in bare for other in others)
    ):
        return None
    narrative = narrative_part(masked.text)
    persons = {
        int(number)
        for number in EXACT_TOKEN_RE.findall(narrative)
        if (slot := masked.slots.get(int(number))) and slot.entry.kind == PERSON
    }
    for match in _VOCATIVE_RE.finditer(narrative):
        if int(match.group(1) or match.group(2)) in persons:
            return None
    return [masked.slots[number].entry for number in sorted(persons)]


def _distinct_people(entries: Iterable[GlossaryEntry]) -> list[str]:
    kept: list[str] = []
    for surface in sorted({entry.surface for entry in entries}, key=len, reverse=True):
        if not any(
            longer.startswith(surface) or longer.endswith(surface) for longer in kept
        ):
            kept.append(surface)
    return kept


def vocative_lead(masked: Masked) -> str | None:
    """Sumber termasking sesudah koma sapaan orang, atau ``None``."""
    match = _LEADING_VOCATIVE_RE.match(masked.text)
    slot = masked.slots.get(int(match.group(1))) if match else None
    if slot is None or slot.entry.kind != PERSON:
        return None
    return masked.text[match.end():]


def person_names(form: str, base: str | None) -> list[str]:
    """Bentuk nama orang yang diperiksa ``fix_names`` untuk satu slot."""
    names = [form] if form else []
    if base and base != form and form.startswith(base):
        names.append(base)
    return names


def person_forms(masked: Masked, render: Callable[[Slot], str]) -> list[str]:
    """Bentuk nama orang untuk ``fix_names`` di jalur cadangan ``presubstitute``."""
    return [
        render(slot)
        for slot in masked.slots.values()
        if slot.entry.kind == PERSON
    ]


def mark_speaker(text: str, names: Sequence[str]) -> str:
    """Beri titik dua setelah nama pembicara naskah (``Kenta "Hei"`` -> ``Kenta: "Hei"``)."""
    for name in names:
        if not text.startswith(name):
            continue
        rest = text[len(name):].lstrip()
        if rest.startswith(SPEAKER_QUOTES):
            return f"{name}: {rest}"
    return text


def hint_lines(
    texts: Sequence[str],
    slots: Sequence[Mapping[int, Slot]],
    render: Callable[[Slot], str],
    gender_of: Callable[[GlossaryEntry], str] | None = None,
) -> list[str]:
    """Baris glosarium untuk LLM, satu per penanda di tiap teks."""
    lines: list[str] = []
    for item, (text, item_slots) in enumerate(zip(texts, slots), start=1):
        for number in sorted({int(n) for n in EXACT_TOKEN_RE.findall(text)}):
            slot = item_slots.get(number)
            if slot is None:
                continue
            entry = slot.entry
            labels = [KIND_LABELS.get(entry.kind, entry.kind.lower())]
            gender = gender_of(entry) if gender_of is not None else entry.gender
            if gender in GENDER_LABELS:
                labels.append(GENDER_LABELS[gender])
            rendered = " ".join(render(slot).splitlines()).strip()
            lines.append(
                f"{item}: [[E{number}]] = {rendered} ({', '.join(labels)})"
            )
    return lines
''')

MODUL['jptrans.data'] = (
    True,
r'''"""Data bawaan jptrans: nama keluarga, tempat terkenal, dan kata serapan.

Berkas JSON dibaca lewat ``importlib.resources`` agar tetap bisa dibaca saat
program dijalankan dari zipapp (``jptrans.pyz``). Hasilnya di-cache dan
dibekukan (``MappingProxyType``, ``tuple``, ``frozenset``) sehingga tidak ada
state global yang bisa berubah.

Isi berkas:

- ``surnames.json``: ``{"佐藤": "さとう", ...}``, hanya nama keluarga dengan
  bacaan yang jelas dominan (河野, 東, 菅野 yang punya dua bacaan umum sengaja
  tidak dimasukkan). Kota/prefektur bawaan yang juga nama keluarga umum (町田,
  広島, 豊田) ikut dimuat dengan bacaan nama keluarganya (豊田 とよだ).
- ``places.json``: ``{"東京": {"id": "Tokyo", "en": "Tokyo", "reading": "とうきょう"}}``.
  Ejaan mapan tanpa makron. Prefektur disimpan tanpa 県/府/都 agar sufiksnya
  dirender oleh ``style.SUFFIX_RULES`` (千葉県 → Prefektur Chiba). Berisi
  prefektur, ibu kota prefektur, dan 50 kota terbesar (kota tanpa sufiks 市,
  agar 豊田市 → Kota Toyota). Kata yang juga kata umum (日光 "sinar matahari",
  柏 "pohon ek") dan kota bertulisan hiragana (さいたま, いわき; 咲いたまま)
  sengaja tidak dimasukkan. Dua prefektur yang juga kata umum (大分 "cukup",
  三重 "tiga lapis") dimuat agar 47 prefektur lengkap, tetapi tercatat di
  ``AMBIGUOUS_PLACES``: ``protect.EntityMatcher`` hanya memaskingnya bila
  diikuti sufiks tempat (大分県, 三重県, 大分駅). Tempat
  yang juga nama keluarga di ``surnames.json`` (山口, 千葉, 町田) ditafsir
  sebagai orang oleh ``protect.EntityMatcher`` hanya bila konteksnya orang
  (山口家, 千葉さん).
- ``loanwords.json``: daftar katakana umum yang bukan nama (ドア, ギルド, ...).
- ``foreign_names.json``: ``{"given": {"Elizabeth": ["エリザベス", "エリザベート"]},
  "family": {"Smith": ["スミス"]}}``. Nama depan dan nama keluarga Barat/fantasi
  umum yang disusun sendiri dari pengetahuan umum; katakana pertama adalah bentuk
  utama, sisanya varian lazim. Satu katakana hanya punya satu ejaan Latin. Bacaan
  yang juga nama Jepang lazim dengan ejaan berbeda (レイ Rei/Ray, リナ, ルイ, アン)
  dan kata serapan di ``loanwords.json`` sengaja tidak dimasukkan.
- ``given_names.json``: ``{"美咲": {"reading": "みさき", "gender": "f"}, ...}``.
  Nama depan Jepang umum (lebih dari 500) dengan bacaan dan gender ``m``/``f``,
  disusun sendiri dari pengetahuan umum; nama uniseks (薫, 翼, 真琴) bergender
  ``""``. Tidak ada yang tumpang tindih dengan ``surnames.json``. Dipakai
  ``gender.infer_gender`` untuk menebak gender nama tanpa gender di glosarium.
  Bacaan yang lazim untuk kedua gender (れい: 麗 perempuan, 零/怜 laki-laki)
  dicatat di ``UNISEX_READINGS`` agar indeks bacaan tidak menebaknya.

- ``kanji_readings.json``: ``{"on": {"藤": ["とう"]}, "kun": {"藤": ["ふじ"]}}``.
  Bacaan hiragana sekitar 1800 kanji yang lazim di nama orang dan tempat
  (jōyō dan jinmeiyō yang umum), disusun sendiri dari pengetahuan umum. ``on``
  berisi bacaan on (dalam hiragana), ``kun`` berisi bacaan kun dan nanori (bacaan
  khusus nama: 和 かず, 司 つかさ) tanpa okurigana. Hanya bacaan yang berguna
  untuk nama; bacaan langka sengaja dibuang. Satu bacaan hanya di satu golongan.
- ``name_words.json``: ``{"飛鳥": ["あすか"], "乾": ["いぬい"], ...}``. Bacaan kata utuh nama
  yang tidak bisa disusun dari bacaan per kanji (jukujikun dan nanori lazim: 飛鳥 あすか,
  五月女 さおとめ, 不知火 しらぬい, 仁 ひとし), serta nama satu kanji yang juga batang kata kerja
  di ``VERB_STEMS`` (乾 いぬい, 開 かい/ひらく, 弾 だん). Digabung dengan
  ``NAME_WORD_READINGS`` oleh ``name_word_readings``; dipakai untuk memvalidasi jawaban
  mesin dan untuk menandai tulisan sebagai nama yang dikenal, bukan untuk merender.

Turunan: ``kanji_readings()`` dan ``kanji_reading_kinds()`` memakai
``kanji_readings.json``; kanji yang tidak ada di sana memakai bacaan yang
diturunkan dari ``surnames.json`` dan ``places.json`` (lihat
``_derived_kanji_readings``). Hasilnya hanya dipakai sebagai *kandidat* untuk
memvalidasi jawaban mesin berhuruf kecil (``pipeline.candidate_readings``), bukan
untuk merender nama atau menebak bacaan kota yang tidak dikenal.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from ..errors import JptransError

logger = logging.getLogger(__name__)

SURNAMES_FILE = "surnames.json"
PLACES_FILE = "places.json"
LOANWORDS_FILE = "loanwords.json"
FOREIGN_NAMES_FILE = "foreign_names.json"
GIVEN_NAMES_FILE = "given_names.json"
KANJI_READINGS_FILE = "kanji_readings.json"
NAME_WORDS_FILE = "name_words.json"
ON = "on"
KUN = "kun"
UNISEX_READINGS = frozenset("""
    れい るい いずみ ちひろ はるか なつき いおり かえで ゆき まお みき あすか ましろ みらい のあ
    みなみ ちはる みづき みずき りつ いつき れん すばる しょう ひろみ かずみ まさみ かつみ ひでみ
    なおみ なお ひかる かおる あきら まこと じゅん しのぶ ゆう ゆうき つかさ あおい ひなた
""".split())
"""Bacaan nama depan yang lazim untuk kedua gender, apa pun gender tulisan di kamus.

Indeks bacaan (``given_name_genders_by_reading``) memberi gender kosong untuk
bacaan ini. Gender dari tulisan yang ada di kamus (麗, 遥) tetap dipakai; daftar
ini hanya menghentikan tebakan untuk tulisan lain (零, 怜) dan nama kana.
"""
KANA_NAME_READINGS = frozenset("""
    みく かなで つむぎ みお いろは こはく しおん まどか ほむら まみ みどり つばめ たま けい あずさ
    かのん ここあ さほ すみか ちか ちせ とうか なぎ のどか はづき ひより ふうか まひろ みこと
    みやび もか ゆずは ゆの りおん りの ゆかり いちか かりん きらら こなつ さくや しの ちとせ
    なのは のの はるひ ひびき まなみ みつき むぎ めぐる よる あきと いぶき がく げん こたろう
    ごう さすけ しんじ せいや そうま たいが てつ とうま はくと ふうが まさむね むさし らいと
    りゅう きりと けんしん こてつ さく ちから てんま ひろむ ほくと みちる ゆうせい あすま
    あまね とわ せつな かなた なると
    れい れな りな りん えみ るい るか あん ゆりあ れお のあ るな えま あんり えみり せな
""".split())
"""Bacaan nama Jepang yang lazim ditulis kana tetapi tidak ada di ``given_names.json``.

Dipakai ``romaji.looks_japanese`` agar nama katakana seperti ミク, マドカ, シオン tidak
ditanyakan ke mesin (シオン bisa dijawab ``Zion``). Baris terakhir adalah bacaan yang
juga nama asing dengan ejaan lain (レイ, ルカ, レオ, エマ); seperti di
``foreign_names.json``, bentuk ini sengaja dibiarkan Hepburn.
"""
COMMON_NAME_READINGS = frozenset("""
    あいか あいな あさひ あずみ あやこ あやめ あゆ あゆか いつみ うらら えつこ えりな かずは
    かなえ かなみ かのこ きく きぬ きみえ きよ きよみ くにこ こずえ ことり さえ さちえ さつき
    さと さな さなえ しずえ しずこ じゅり すみこ せつこ たえ たえこ ちえ ちえこ ちさ ちづ ちはや
    ちほ ちよこ つね とめ ともえ なえ なつ なつこ なほ なみ なみえ にな のぶこ のりえ はつ はつえ
    はるこ ひさこ ひでこ ひろこ ふき ふさ ふじこ ふみ ふみえ まき まきこ まさえ まさこ ますみ
    まち まつ まつこ まな まなか まほ まゆ まゆこ みえ みえこ みさ みさお みちよ みつえ みね みや
    みやこ みよ みよこ もとこ ももか やすこ やすえ ゆな ゆいか ゆきえ ゆきの ゆず ゆずか ゆめ ゆら
    よしえ よしの よね りお りさこ りほ りよ れいか わかこ うめ たけ さよ すず ちず
    あきお あきひろ あつし いわお えいすけ かい かいり かつお かつや かつのり かずお かずひろ
    かずのり かずよし かんじ きいち くにお けんご けんじろう けんと こうき さだお さとる しげお
    しげのぶ しゅう しゅうと しゅうま しょうご しょうじ しんご しんや すぐる そういち たいせい
    たいよう たかお たかのり たかひろ たけお たけひこ たけのり たけまさ ただお たつお たつろう
    ちゅうや てつお てつじ てるお とおる としお としひろ としや としゆき ともかず ともや なおゆき
    のぶお のぶなが のぶひろ のぶゆき のぶよし のりお のりひろ のりゆき ひでお ひでよし ひろき
    ひろかず ひろみち ひろや ふみお ふみや まさお まさかず まさし まさのぶ まさひろ まさみち
    まさや まさよし まなと みちお みつお みつる もとき やすお やすし やすひろ やすのり ゆうご
    ゆうや ゆきお ゆきひろ よういち ようすけ よしあき よしお よしかず よしのぶ よしひろ よしゆき
    りゅうじ りゅうせい りゅうと りょうじ りょうま りょうへい いえやす
""".split())
"""Bacaan nama depan Jepang yang lazim (termasuk nama lama seperti ウメ, トメ, キヨ).

Pelengkap ``given_names.json`` (yang hanya memuat tulisan kanji yang umum) untuk
``romaji.looks_japanese``: tanpa daftar ini nama katakana seperti マキ, ユナ, ノブナガ
ditanyakan ke mesin dan jawaban yang salah (``Mackie``, ``Una``) menggantikan
Hepburn yang sudah benar.
"""
NAME_ELEMENTS = frozenset("""
    あき あつ いえ いさ えい えつ かず かつ かね きみ きよ くに けい けん こう さだ さと しげ
    しず しょう しん すけ すみ たか たけ ただ たつ ちか つぐ つね てつ てる とし とみ とも なお
    なが なり のぶ のり はる ひさ ひこ ひで ひと ひろ ふみ まさ みち みつ むね もと もり やす
    ゆう ゆき よう よし より りゅう りょう しゅう じゅん だい ろう たろう じろう ぞう へい のすけ
""".split())
"""Unsur nama Jepang dua kana atau lebih yang lazim dirangkai (のぶ + なが, よう + すけ).

``romaji.looks_japanese`` menerima bacaan yang tersusun dari DUA unsur ini (ノブナガ,
ヒデヨシ, マサヒロ) atau satu unsur + satu kana penutup (エツ + コ, ヒデ + オ). Unsurnya
sengaja tidak memuat potongan yang lazim di nama asing (たち, まる, ごん), supaya
タチアナ, マルコ, ゴンサロ tetap dianggap asing.
"""
KANJI_VARIANTS: Mapping[str, str] = MappingProxyType({
    "髙": "高", "﨑": "崎", "嵜": "崎", "齋": "斎", "齊": "斉", "邊": "辺", "邉": "辺", "條": "条",
    "廣": "広", "國": "国", "曾": "曽", "栁": "柳", "冨": "富", "瀨": "瀬", "惠": "恵", "德": "徳",
    "黑": "黒", "藏": "蔵", "實": "実", "壽": "寿", "榮": "栄", "縣": "県", "佛": "仏", "舘": "館",
    "邨": "村", "嶌": "島", "驒": "騨", "圓": "円", "淺": "浅", "增": "増",
})
"""Bentuk kanji lama/varian yang lazim di nama keluarga → bentuk bakunya (髙橋 = 高橋).

``kanji_reading_kinds`` memberi varian bacaan bentuk bakunya, dan
``pipeline.candidate_readings`` mencari kata utuh dalam bentuk baku (渡邊 → 渡辺
わたなべ)."""
NAME_WORD_READINGS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "日向": ("ひなた", "ひゅうが", "ひむかい"), "河野": ("こうの", "かわの"),
    "菅野": ("かんの", "すがの"), "織田": ("おだ",), "伊達": ("だて",), "大和": ("やまと",),
    "北条": ("ほうじょう",), "八幡": ("はちまん", "やはた", "やわた"), "大伴": ("おおとも",),
    "飛騨": ("ひだ",), "播磨": ("はりま",), "筑紫": ("つくし",), "服部": ("はっとり",),
    "鷹司": ("たかつかさ",), "若宮": ("わかみや",), "藤堂": ("とうどう",),
    "二階堂": ("にかいどう",), "東海林": ("しょうじ", "とうかいりん"), "小鳥遊": ("たかなし",),
    "四月一日": ("わたぬき",), "百目鬼": ("どうめき", "どめき"), "御手洗": ("みたらい",),
    "勅使河原": ("てしがわら",), "日下部": ("くさかべ",), "綾小路": ("あやのこうじ",),
    "吉良": ("きら",), "浅井": ("あさい", "あざい"), "新田": ("にった", "しんでん"),
    "大和田": ("おおわだ",), "陽菜": ("ひな", "はるな"), "結菜": ("ゆいな", "ゆな"),
    "大翔": ("ひろと", "はると", "やまと"), "陽翔": ("はると", "ひなと", "あきと"),
    "翔": ("しょう", "かける"), "光": ("ひかる", "ひかり", "こう"), "蒼": ("あおい", "そう"),
    "優": ("ゆう", "まさる", "すぐる"), "心": ("こころ", "しん"), "尾道": ("おのみち",),
})
"""Bacaan kata utuh untuk memvalidasi jawaban mesin berhuruf kecil, bukan untuk merender.

Isinya bacaan yang tidak bisa disusun dari bacaan per kanji (日向 ひなた, 服部
はっとり, 小鳥遊 たかなし), nama yang bacaan rangkaiannya menyesatkan (鷹司: たか + し
akan meloloskan ``takashi``), dan bacaan ganda yang lazim dari kata yang juga ada di
``surnames.json``/``given_names.json`` dengan satu bacaan saja (河野, 陽菜). Kata utuh
yang dikenal hanya menerima bacaannya sendiri (``pipeline.candidate_readings``). Kode lain
membacanya lewat ``name_word_readings``, yang menambahkan isi ``name_words.json``."""
AMBIGUOUS_PLACES = frozenset({"大分", "三重"})
"""Tempat di ``places.json`` yang juga kata umum (大分 だいぶ "cukup", 三重 "tiga lapis").

``protect.EntityMatcher`` hanya memaskingnya bila langsung diikuti sufiks tempat
(大分県, 三重県, 大分市, 大分駅); tanpa sufiks teksnya dikirim apa adanya ke mesin."""
VERB_STEMS: Mapping[str, frozenset[str]] = MappingProxyType({
    "く": frozenset("行書聞置泣鳴抱働驚吹履吐弾焼巻招拭敷突着付就解説届続動乾叩嘆浮退剥向効"
                   "欠割裂貫省除背赴炊覗湧沸引開歩咲響輝磨抜描拓導囁呟頷傾築裁欺掃焚轢挽聴"
                   "利噴葺撒蒔妬渇飽溶梳穿点憑衝措"),
    "た": frozenset("見出寝着居似煮来経得干射立待持勝打保育討撃放断絶建発裁"),
    "さ": frozenset("許話貸返消押離逃殺隠戻出指刺増減回写移残倒化渡治直示越超試申足外壊成為流"
                   "放通癒冒犯侵汚潰記挿差推崩遺帰還課干下映"),
})
"""Batang kata kerja satu kanji → kana okurigana yang sama dengan awal honorifik ber-ん.

行 + くん di 行くんですか adalah 行く + ん (penjelas), 来 + たん di 来たんですか adalah
来た + ん (juga 待 + たん: negasi lisan 待たん), dan 許 + さん di 許さん adalah negasi lisan
許さん. Kunci = honorifik tanpa ん. Tabel ini hanya mencatat bahwa tulisan itu BISA dibaca
kata kerja; kanji yang juga lazim sebagai nama satu huruf (歩, 咲, 響, 輝, 開, 弾, 乾, 渡, 治,
直) sengaja ikut dimuat. Nama atau kata kerja diputuskan dari konteks oleh
``style.verb_run_before_honorific`` (jenis konteks sebelum dan sesudah honorifik di
``style.VERB_CONTEXT_TABLE``, dibandingkan dengan tingkat nama tulisan itu: dikenal di data
lewat ``style.is_known_name`` atau terbukti di dokumen)."""
COMMON_ENGLISH_WORDS = frozenset("""
    a an and as at be by do go gone went in is it me my no of on or so to up we us he she
    key dock shock line fall come came eat drink read run walk say said word back home way
    row see look sea sun moon star sky tree road path field stone rock wood fire water rain
    snow wind light dark day night year life love heart mind soul hand eye head red blue
    white black green gold silver king queen god demon devil dragon bird fish cat dog wolf
    bear fox horse tiger deer flower rose lily bell door gate house town city village castle
    temple shrine bridge river lake hill mountain island port bay shore spring summer autumn
    winter morning noon evening dream hope truth peace war blade sword arrow shield ship cloud
    cloudy field mound hall shop store yes yeah not all one two three ten going coming
    paw toe her him his our raw saw law jaw car bar far jar tar
""".split())
"""Kata Inggris umum yang tidak diterima sebagai ejaan nama dari mesin.

Mesin sering menjawab arti, bukan bunyi (行 → ``go``, 言 → ``gone``, 帰 → ``key``).
Dipakai ``pipeline.clean_name`` untuk nama satu kanji yang tidak dikenal utuh di data
proyek (bacaan on dua kana seperti ぎょう untuk 行 adalah kandidat, jadi daftar ini yang
menolak ``go``), dan untuk tiap kata jawaban bila data tidak punya kandidat bacaan sama
sekali (``Home`` untuk 猫屋). Nama yang dikenal (杏 あん) tetap boleh berbunyi seperti
kata Inggris."""
MIN_GROUP_WORDS = 2
"""Jumlah kata minimum yang berbagi kanji awal/akhir agar bacaan kanji itu diturunkan."""
MIN_SUBTRACT_KANA = 2
"""Bacaan kanji sependek ini (田 た) tidak dipakai untuk mengurangi: terlalu mudah salah potong."""


def surnames() -> Mapping[str, str]:
    """Kembalikan peta nama keluarga ke bacaan hiragana (``佐藤`` → ``さとう``)."""
    return _load(SURNAMES_FILE)


def places() -> Mapping[str, Mapping[str, str]]:
    """Kembalikan peta tempat terkenal ke ejaan ``id``/``en`` dan ``reading``."""
    return _load(PLACES_FILE)


def loanwords() -> frozenset[str]:
    """Kembalikan himpunan katakana umum yang bukan nama."""
    return frozenset(_load(LOANWORDS_FILE))


@lru_cache(maxsize=None)
def foreign_names() -> Mapping[str, str]:
    """Kembalikan peta katakana nama asing ke ejaan Latinnya (``エリザベート`` → ``Elizabeth``).

    Nama depan dan nama keluarga digabung, karena bagian nama (dipisah ・)
    dicari satu per satu.

    Raises:
        JptransError: Berkas rusak atau satu katakana punya dua ejaan berbeda.
    """
    merged: dict[str, str] = {}
    for group in _load(FOREIGN_NAMES_FILE).values():
        for latin, forms in group.items():
            for kana in forms:
                if merged.setdefault(kana, latin) != latin:
                    raise JptransError(f"{FOREIGN_NAMES_FILE}: {kana} punya dua ejaan")
    return MappingProxyType(merged)


def given_names() -> Mapping[str, Mapping[str, str]]:
    """Kembalikan peta nama depan ke ``reading`` dan ``gender`` (``美咲`` → みさき, f)."""
    return _load(GIVEN_NAMES_FILE)


@lru_cache(maxsize=None)
def name_word_readings() -> Mapping[str, tuple[str, ...]]:
    """Bacaan kata utuh nama: ``NAME_WORD_READINGS`` digabung dengan ``name_words.json``.

    Bacaan dari kedua sumber disatukan tanpa duplikat (百目鬼: どうめき, どめき, どどめき).

    Raises:
        JptransError: ``name_words.json`` rusak (bukan peta tulisan → daftar bacaan).
    """
    merged = {surface: list(readings) for surface, readings in NAME_WORD_READINGS.items()}
    raw = _load(NAME_WORDS_FILE)
    if not isinstance(raw, Mapping):
        raise JptransError(f"{NAME_WORDS_FILE} harus objek JSON")
    for surface, readings in raw.items():
        if not isinstance(readings, tuple) or not all(isinstance(r, str) for r in readings):
            raise JptransError(f"{NAME_WORDS_FILE}: bacaan {surface} harus daftar string")
        items = merged.setdefault(surface, [])
        items.extend(reading for reading in readings if reading not in items)
    return MappingProxyType({surface: tuple(items) for surface, items in merged.items()})


@lru_cache(maxsize=None)
def name_readings() -> frozenset[str]:
    """Semua bacaan nama utuh yang dikenal data proyek (hiragana, tanpa spasi).

    Gabungan bacaan ``surnames.json``, ``given_names.json``, ``name_word_readings``
    (``NAME_WORD_READINGS`` + ``name_words.json``), ``KANA_NAME_READINGS``, dan
    ``COMMON_NAME_READINGS``. Dipakai
    ``pipeline.candidate_readings`` untuk mengizinkan rangkaian bacaan on/kun campuran
    yang memang bacaan nama (御堂 みどう, 美堂 みどう).
    """
    found = set(surnames().values())
    found.update(info["reading"] for info in given_names().values())
    found.update(reading for items in name_word_readings().values() for reading in items)
    found.update(KANA_NAME_READINGS | COMMON_NAME_READINGS)
    return frozenset(reading for reading in found if reading)


@lru_cache(maxsize=None)
def given_name_genders_by_reading() -> Mapping[str, str]:
    """Peta bacaan hiragana nama depan → gender, untuk nama kana (ミサキ) atau kanji lain.

    Bila tulisan-tulisan dengan bacaan yang sama tidak sepakat (まこと: 誠 laki-laki,
    真琴 uniseks), atau bacaannya ada di ``UNISEX_READINGS`` (れい), gendernya
    kosong: bacaan saja tidak cukup sebagai bukti.

    Returns:
        Peta bacaan → ``"m"``, ``"f"``, atau ``""`` (beku).
    """
    found: dict[str, set[str]] = {}
    for info in given_names().values():
        found.setdefault(info["reading"], set()).add(info["gender"])
    for reading in UNISEX_READINGS:
        found.setdefault(reading, set()).add("")
    return MappingProxyType({reading: genders.pop() if len(genders) == 1 else ""
                             for reading, genders in found.items()})


@lru_cache(maxsize=None)
def kanji_reading_kinds() -> Mapping[str, Mapping[str, str]]:
    """Peta kanji → (bacaan hiragana → golongan ``"on"``, ``"kun"``, atau ``""``).

    Isi ``kanji_readings.json`` (kun dan nanori dulu, lalu on), ditambah bentuk
    varian ``KANJI_VARIANTS`` dengan bacaan bentuk bakunya (髙 = 高). Kanji yang tidak
    ada di berkas itu memakai bacaan turunan ``_derived_kanji_readings`` dengan
    golongan ``""`` (tidak diketahui). Bacaan turunan TIDAK ditambahkan ke kanji
    yang sudah ada di berkas: turunan seperti 宮 → のみや (dari 二宮, 西宮) akan
    membuat jawaban salah ``wakanomiya`` untuk 若宮 lolos.

    Raises:
        JptransError: Berkas rusak atau bacaan yang sama ada di dua golongan.
    """
    raw = _load(KANJI_READINGS_FILE)
    merged: dict[str, dict[str, str]] = {}
    for kind in (KUN, ON):
        for kanji, readings in raw[kind].items():
            for reading in readings:
                if merged.setdefault(kanji, {}).setdefault(reading, kind) != kind:
                    raise JptransError(f"{KANJI_READINGS_FILE}: {kanji} {reading} ganda")
    for variant, standard in KANJI_VARIANTS.items():
        if variant not in merged and standard in merged:
            merged[variant] = dict(merged[standard])
    for kanji, readings in _derived_kanji_readings().items():
        if kanji not in merged:
            merged[kanji] = {reading: "" for reading in readings}
    return MappingProxyType({kanji: MappingProxyType(items) for kanji, items in merged.items()})


@lru_cache(maxsize=None)
def kanji_readings() -> Mapping[str, tuple[str, ...]]:
    """Peta kanji → tuple bacaan hiragana (``kanji_reading_kinds`` tanpa golongan)."""
    return MappingProxyType({kanji: tuple(items)
                             for kanji, items in kanji_reading_kinds().items()})


@lru_cache(maxsize=None)
def _derived_kanji_readings() -> Mapping[str, tuple[str, ...]]:
    """Turunkan bacaan hiragana per kanji dari nama keluarga dan tempat bawaan.

    Tiga sumber, semuanya dari data proyek sendiri:

    1. Kata satu kanji (林 はやし, 森 もり).
    2. Awalan bersama: kata-kata yang diawali kanji yang sama (高橋 たかはし,
       高田 たかだ, 高木 たかぎ) memberi bacaan awalan bersama yang terpanjang
       (高 → たか). Hal yang sama untuk akhiran (二宮, 西宮 → 宮 → のみや).
       Minimal ``MIN_GROUP_WORDS`` kata, agar satu kata tidak dipotong asal.
    3. Pengurangan: kata dua kanji yang bacaan salah satu kanjinya sudah
       diketahui (minimal ``MIN_SUBTRACT_KANA`` kana) memberi bacaan kanji yang
       lain (宮本 みやもと − 宮 みや → 本 もと).

    Bacaan ini perkiraan dan hanya dipakai untuk kanji yang tidak ada di
    ``kanji_readings.json`` (lihat ``kanji_reading_kinds``).

    Returns:
        Peta kanji → tuple bacaan (tanpa duplikat, urutan stabil).
    """
    words = dict(surnames())
    words.update((surface, place["reading"]) for surface, place in places().items())
    found: dict[str, list[str]] = {}

    def add(kanji: str, reading: str) -> None:
        """Tambahkan ``reading`` ke bacaan ``kanji`` bila belum ada (urutan masuk dijaga)."""
        if reading and reading not in found.setdefault(kanji, []):
            found[kanji].append(reading)

    for surface, reading in words.items():
        if len(surface) == 1:
            add(surface, reading)
    for pick, shared in ((lambda w: w[0], _common_prefix), (lambda w: w[-1], _common_suffix)):
        groups: dict[str, list[str]] = {}
        for surface, reading in words.items():
            if len(surface) > 1:
                groups.setdefault(pick(surface), []).append(reading)
        for kanji, readings in groups.items():
            if len(readings) >= MIN_GROUP_WORDS:
                add(kanji, shared(readings))
    base = {kanji: [r for r in items if len(r) >= MIN_SUBTRACT_KANA]
            for kanji, items in found.items()}
    for surface, reading in words.items():
        if len(surface) != 2:
            continue
        head, tail = surface
        for known in base.get(head, ()):
            if reading.startswith(known) and len(reading) > len(known):
                add(tail, reading[len(known):])
        for known in base.get(tail, ()):
            if reading.endswith(known) and len(reading) > len(known):
                add(head, reading[:-len(known)])
    return MappingProxyType({kanji: tuple(items) for kanji, items in found.items()})


def _common_prefix(readings: list[str]) -> str:
    """Awalan bersama terpanjang dari beberapa bacaan."""
    first, last = min(readings), max(readings)
    size = 0
    while size < min(len(first), len(last)) and first[size] == last[size]:
        size += 1
    return first[:size]


def _common_suffix(readings: list[str]) -> str:
    """Akhiran bersama terpanjang dari beberapa bacaan."""
    return _common_prefix([reading[::-1] for reading in readings])[::-1]


@lru_cache(maxsize=None)
def _load(name: str) -> Any:
    """Baca satu berkas JSON bawaan sekali saja, lalu bekukan isinya.

    Raises:
        JptransError: Berkas tidak ada atau rusak (paket terpasang tidak utuh).
    """
    try:
        raw = files(__name__).joinpath(name).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise JptransError(f"data bawaan {name} tidak bisa dibaca: {exc}") from exc
    logger.debug("data bawaan %s dimuat", name)
    return _freeze(data)


def _freeze(value: Any) -> Any:
    """Ubah dict dan list bersarang menjadi bentuk yang tidak bisa diubah."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
''')

MODUL['jptrans.disambig'] = (
    False,
r'''"""Disambiguasi konteks kata kerja + ん terhadap nama diri + honorifik.

Membedakan run kanji sebelum honorifik (``歩くんだ``, ``許さん``, ``来たんです``)
dari nama orang berhonorifik (``歩くん``, ``治さん``) berdasarkan tabel konteks
kiri/kanan ``VERB_CONTEXT_TABLE`` serta daftar kata peran, benda, dan sapaan.
"""

from __future__ import annotations

import logging
import re

from . import data
from .models import ORG, PLACE
from .textnorm import KANJI, KANJI_RE, KATAKANA, is_hiragana, is_kanji, is_katakana

logger = logging.getLogger(__name__)

HONORIFIC_SURFACES: dict[str, str] = {
    "さん": "san", "くん": "kun", "君": "kun", "ちゃん": "chan",
    "様": "sama", "さま": "sama", "先輩": "senpai", "先生": "sensei",
    "殿": "dono", "氏": "shi", "たん": "tan", "っち": "cchi",
}
"""Tulisan honorifik Jepang → kunci romaji yang disimpan di ``Slot.honorific``."""

# Templat sufiks: (bahasa Indonesia, bahasa Inggris); {name} = nama yang sudah dirender.
PEOPLE_SUFFIXES: dict[str, tuple[str, str]] = {
    "達": ("{name} dan yang lain", "{name} and the others"),
    "たち": ("{name} dan yang lain", "{name} and the others"),
    "ら": ("{name} dan yang lain", "{name} and the others"),
    "家": ("keluarga {name}", "the {name} family"),
    "一家": ("keluarga {name}", "the {name} family"),
}
"""Sufiks setelah nama orang: jamak dan keluarga."""

PLACE_SUFFIXES: dict[str, tuple[str, str]] = {
    "駅": ("Stasiun {name}", "{name} Station"),
    "市": ("Kota {name}", "{name} City"),
    "町": ("Kota {name}", "{name} Town"),
    "村": ("Desa {name}", "{name} Village"),
    "県": ("Prefektur {name}", "{name} Prefecture"),
    "府": ("Prefektur {name}", "{name} Prefecture"),
    "都": ("{name}", "{name}"),
    "区": ("Distrik {name}", "{name} Ward"),
    "城": ("Kastel {name}", "{name} Castle"),
    "山": ("Gunung {name}", "Mount {name}"),
    "川": ("Sungai {name}", "{name} River"),
    "島": ("Pulau {name}", "{name} Island"),
    "国": ("Negeri {name}", "Kingdom of {name}"),
    "港": ("Pelabuhan {name}", "Port of {name}"),
    "寺": ("Kuil {name}", "{name} Temple"),
    "神社": ("Kuil {name}", "{name} Shrine"),
    "学園": ("Akademi {name}", "{name} Academy"),
    "学院": ("Akademi {name}", "{name} Academy"),
    "高校": ("SMA {name}", "{name} High School"),
    "中学": ("SMP {name}", "{name} Middle School"),
    "大学": ("Universitas {name}", "{name} University"),
}
"""Sufiks jenis tempat/lembaga. 府 都 区 港 寺 神社 中学 大学 adalah tambahan di luar SPEC."""

SUFFIX_RULES: dict[str, tuple[str, str]] = {**PEOPLE_SUFFIXES, **PLACE_SUFFIXES}
"""Semua sufiks yang dikenali ``protect.EntityMatcher`` beserta templatnya."""

PLACE_KINDS = frozenset({PLACE, ORG})
"""Jenis entri yang boleh diikuti sufiks tempat (東京駅, 星見学園)."""

TITLE_WORDS: tuple[str, ...] = (
    "社長", "副社長", "部長", "課長", "係長", "会長", "店長", "校長", "教授", "博士", "刑事",
    "警部", "選手", "監督", "団長", "隊長", "艦長", "知事", "首相", "大臣", "議員", "容疑者",
    "王子", "王女", "姫", "陛下", "殿下",
)
"""Gelar/jabatan kanji yang ditulis langsung setelah nama (佐藤部長, エリザ王女).

Gelar tidak dirender ``Renderer``: ``protect`` hanya memasking namanya dan
membiarkan gelar di teks agar mesin menerjemahkannya (``Manajer [[E1]]``).
"""


NAME_PARTICLES = frozenset("がはともにをへの、，")
"""Huruf sesudah くん yang hanya mungkin untuk nama (乾くんが, 開くんと, 弾くんの番, 拓くん、).

Kata kerja + ん penjelas (行くんだ) tidak pernah langsung disusul partikel kasus atau koma."""
VERB_ENDING_FOLLOWERS = frozenset("だでじかよねぞやな")
"""Huruf sesudah ん yang khas kata kerja + ん penjelas (行くんだ, 行くんですか, 来たんじゃ, 行くんなら)."""
NEGATIVE_NAME_FOLLOWERS = frozenset("はもにをへっー")
"""Huruf sesudah さん/たん yang hanya mungkin untuk nama: negasi lisan (許さん, 待たん) boleh
disusul が, と, の？, で, atau 、 (貸さんが、, 待たんといけない), tetapi tidak disusul partikel ini."""
NEGATIVE_TAIL_RE = re.compile(
    r"ぞ|と(?:言|い[うってけか]|あか|おか)|の[？?か]|かった|で(?:ええ|いい|くれ|[！!])")
"""Ekor yang khas negasi lisan 〜さん/〜たん (bukti kuat): 許さんぞ, 許さんと言った, 話さんといて,
待たんといけない, 出さんの？, 許さんかった, 持たんでええ, 直さんでいい, 話さんでくれ, 放さんで！."""
WEAK_NEGATIVE_TAILS = ("から", "か", "よ", "で", "や", "ね", "な")
"""Ekor sesudah さん yang cocok untuk negasi lisan maupun nama (許さんから / 治さんから,
許さんよ / 直さんよ): bukti lemah, hanya berlaku untuk tulisan yang bukan nama dikenal."""
KUN_NAME_TAILS = ("から", "まで", "さえ", "しか", "ばかり", "くらい", "ぐらい", "ほど", "こそ", "より",
                  "すら", "でさえ", "ばっかり", "なんて", "なんか", "みたい", "たら")
"""Partikel sesudah くん yang hanya mungkin untuk nama (響くんから？, 弾くんまで泣いてる, 歩くんより
速い, 弾くんすら来なかった, 咲くんばっかり, 歩くんなんて呼んでた, 鳴くんたら遅い, 拓くんみたいに):
kata kerja + ん tidak pernah langsung disusul partikel ini."""
IDENTITY_SUBJECTS = (
    "これ", "それ", "あれ", "どれ", "こちら", "そちら", "あちら", "こっち", "そっち", "あっち",
    "こいつ", "そいつ", "あいつ", "この子", "その子", "あの子", "この人", "その人", "あの人", "の",
)
"""Kata penunjuk sebagai subjek/topik kalimat identitas (あれが蓮くんだ, それって乾くんじゃない？,
あの子、咲くんだよね): が/は/も/って/koma sesudahnya bukan bukti kata kerja, karena kalimatnya
menyebut siapa orang itu. ``の`` mewakili kalimat cleft 〜のは/〜のが (優勝したのは歩くんだ)."""
FIRST_PERSON_PRONOUNS = ("僕", "ぼく", "俺", "おれ", "私", "わたし", "あたし")
"""Kata ganti orang pertama: + は/も/って/koma adalah subjek kata kerja (僕は歩くんだ, 俺は渡さん！,
私は歩くんですよ), karena orang jarang menyebut dirinya dengan くん."""
PERSONAL_PRONOUNS = FIRST_PERSON_PRONOUNS + (
    "君", "きみ", "あなた", "あんた", "お前", "おまえ", "貴方", "貴様", "彼", "彼女",
)
"""Kata ganti orang. + が adalah pola identitas (君が治さんか); + も kasus (お前も歩くんだよ). + は
dan koma: orang pertama kasus, orang kedua/ketiga topik (君は歩くんだよ kata kerja untuk nama yang
hanya dikenal di data, あなたは歩くんですか nama bila 歩 sudah terbukti nama di dokumen)."""
INANIMATE_VERBS = frozenset({
    "咲く", "乾く", "響く", "鳴く", "届く", "湧く", "沸く", "効く", "噴く", "渇く", "裂く", "剥く",
})
"""Kata kerja (batang + okurigana) yang subjeknya hampir tidak pernah orang (花が咲く, 布団が乾く,
音が響く, 犬が鳴く). Kata ganti atau kata benda orang + は/が/も sebelum run seperti itu adalah
kalimat identitas (君は響くんだね？, お前は乾くんか？), bukan subjek kata kerja."""
PERSON_NOUNS = (
    "犯人", "主役", "主人公", "代表", "当番", "日直", "担任", "担当", "次", "一番", "答え", "正解", "正体",
    "名前", "相手", "本命", "彼氏", "恋人", "相棒", "走者", "勝者", "兄", "姉", "弟", "妹", "兄貴",
    "姉貴", "子", "真ん中", "キャプテン", "リーダー", "エース", "主将", "新人", "転校生",
    "人", "一人", "ひとり", "息子", "娘", "孫", "甥", "姪", "いとこ", "親友", "友達", "友人",
    "幼なじみ", "幼馴染", "同級生", "同期", "先輩", "後輩", "仲間", "隣", "席", "幹事", "司会",
    "監督", "審判", "顧問", "部長", "会長", "社長", "店長", "委員", "委員長", "議長", "係", "担当者",
    "優勝", "一位", "最後", "残り", "メンバー", "ゲスト", "ボーカル", "マネージャー", "アンカー",
    "センター", "コーチ", "パートナー", "ライバル", "ヒーロー", "ヒロイン", "キーパー",
    "ゴールキーパー", "ピッチャー", "キャッチャー", "ストライカー", "ドラマー", "ギタリスト",
    "ベーシスト", "オーナー", "スタッフ", "チャンピオン",
    "MVP", "ＭＶＰ", "先発", "控え", "補欠", "代打", "代役", "黒幕", "主犯", "後任", "前任",
    "ボス", "王子", "王様", "女王", "大将", "親分", "推し", "お目当て", "目当て", "狙い",
    "お気に入り", "相方", "スター", "アイドル", "クラスメイト", "チームメイト",
    "先生", "師匠", "鬼", "代わり", "代理", "見張り", "新入り", "書記", "会計", "先鋒", "次鋒",
    "中堅", "主砲", "守護神", "トップバッター", "主人", "本人", "少年", "少女", "青年", "人物", "大物",
    "キング", "クイーン", "プリンス", "プリンセス", "ボディーガード", "パイロット", "コック", "シェフ",
    "ナース", "ガイド", "モデル", "スパイ", "ホスト", "ルーキー", "黒子", "大黒柱", "跡取り",
)
"""Kata benda peran/orang yang, sebagai topik atau subjek, menunjuk satu orang tertentu (犯人は歩くんだ,
主役は開くんだよ, うちの兄が歩くんです, 幹事は歩くんです, 窓際の席は輝くんだよ): は/が/koma
sesudahnya adalah posisi nama. Harus kata utuh, bukan ekor kata kanji/katakana lain (帽子, 様子,
目次, 他人事). Daftar ini sengaja lebar: topik di luar daftar dibaca topik benda (ギターは弾くんだけど).
Peringkat bernomor (四番, 二番手, 三番目, 二位) dikenali lewat ``_RANK_RE``; kata dengan awalan
peran (真犯人, 副担任, 準優勝, 大本命) lewat ``ROLE_PREFIXES``."""
_RANK_RE = re.compile(r"[一二三四五六七八九十0-9０-９]+(?:番(?:手|目)?|位)$")
"""Nomor urut orang dalam tim/barisan (四番は歩くんです, 二番手は拓くんです, 二位は輝くんだ)."""
PERSON_NOUN_ENDINGS = (
    "候補", "部員", "委員長", "部長", "会長", "班長", "隊長", "団長", "選手", "者", "員", "役",
    "官", "師", "士", "友", "督", "将", "生徒", "年生", "校生", "学生", "入生", "級生", "業生",
    "主", "医", "番", "郎", "婿", "嫁", "賓", "手", "娘", "人", "代理", "係", "最下位", "長", "王",
    "謀",
)
"""Ekor kata orang yang boleh didahului kanji lain (優勝候補, 新入部員, 学級委員長, 参加者, 店員,
悪役, 教師, 弁護士, 一年生, 持ち主, 主治医, 店番, 新郎, 花婿, 主賓, 語り手, 看板娘, 差出人,
部長代理). Kata jamak (全員, 三人) dikecualikan oleh ``_PLURAL_ENDINGS``; kata benda biasa
berekor sama di ``NOT_PERSON_WORDS``."""
NOT_PERSON_WORDS = (
    "大人", "他人", "万人", "国人", "日本人", "上手", "下手", "切手", "派手", "両手", "右手", "左手", "片手",
    "交番", "順番", "民主", "自主", "空手", "勝手", "定番", "身長", "成長", "延長", "特長",
)
"""Kata berekor ``PERSON_NOUN_ENDINGS`` yang bukan satu orang tertentu (大人は歩くんだ: orang
dewasa pada umumnya, 日本人, 上手, 順番)."""
ROLE_PREFIXES = frozenset("真副新準大前元現次")
"""Awalan satu kanji yang boleh menempel ke kata ``PERSON_NOUNS`` tanpa mengubah arti "orang"
(真犯人, 副担任, 副キャプテン, 準優勝, 大本命, 新キャプテン, 前会長)."""
HONORIFIC_NOUN_TAILS = ("さん", "様", "さま", "ちゃん")
"""Honorifik yang menempel ke kata benda orang biasa (お客さん, 店員さん, 王子様, お姫様)."""
_POLITE_NOUN_RE = re.compile(f"(?:^|[^ぁ-ゖ])[おご][{KANJI}][ぁ-ゖ]?$")
"""Kata benda berawalan sopan お/ご sebelum honorifik (お客, お姫, お巡り): orang, bukan nama diri."""
THING_WORDS = (
    "花", "桜", "梅", "バラ", "窓", "扉", "ドア", "戸", "門", "蓋", "ふた", "箱", "傘", "本", "店",
    "幕", "鍵", "布団", "服", "シャツ", "セーター", "タオル", "靴", "髪", "喉", "土", "ペンキ",
    "ピアノ", "ギター", "バイオリン", "ヴァイオリン", "ベース", "チェロ", "琴", "楽器", "曲", "歌",
    "音", "声", "鐘", "ベル", "犬", "猫", "鳥", "虫", "蝉", "セミ", "カエル", "星", "月", "太陽",
    "目", "瞳", "手紙", "荷物", "金", "お金", "ネジ", "マフラー", "包帯", "時計", "電話", "スマホ",
    "携帯", "帰り", "行き", "ここ", "そこ", "あそこ", "今", "最近", "普段", "昔", "結局", "季節",
    "春", "夏", "秋", "冬", "週末", "平日", "休み", "午前", "午後", "夕方", "今朝", "今夜", "今晩",
    "夜中", "深夜", "雨", "雪", "晴れ", "土地", "癖", "病気", "勝負", "秘密", "誤字", "話",
    "宝石", "ダイヤ", "空", "海", "光", "水面", "笑顔", "未来", "雷", "太鼓", "笛", "鈴", "汗", "口",
    "チャイム", "サイレン", "アラーム", "返事", "メール", "連絡", "知らせ", "便り", "招待状",
    "手", "足", "体", "肌", "紙", "葉",
)
"""Kata benda/waktu/tempat yang lazim menjadi topik kata kerja (ギターは弾くんだけど, 洗濯物は
乾くんですか, 冬は乾くんですか, 帰りは歩くんですか, 金は渡さん): benda yang dimainkan, dibuka,
dikeringkan, berbunyi, bersinar, atau waktu/tempat. Harus kata utuh. Topik kata benda yang tidak
dikenali (bukan ``PERSON_NOUNS`` dan bukan benda) condong ke nama seperti baseline_v6."""
THING_ENDINGS = (
    "日", "曜", "朝", "昼", "夜", "晩", "時", "時間", "物", "道", "先", "年", "週", "月", "屋上",
    "器", "機", "庫", "具", "品", "剤", "薬", "料", "線", "室", "館", "場", "園", "車", "船", "布",
    "板", "瓶", "袋", "計", "灯", "球", "石", "草", "木", "魚", "川", "山", "橋", "駅", "会", "毯",
    "顔", "風", "楽", "茶", "酒", "水",
)
"""Ekor kata waktu/benda/tempat (金曜日, 雨の日, 毎朝, 十時, 洗濯物, 帰り道, ここから先, 今年,
楽器, 冷蔵庫, 三味線, 教室, 毛布, 朝顔, 教会): morfem benda, bukan daftar kata utuh."""
DEMONSTRATIVES = ("この", "その", "あの", "どの", "こんな", "そんな", "あんな", "どんな")
"""Kata penunjuk + kata benda bukan orang (この扉, その傘, あの店): benda tertentu, topik kata
kerja (この扉は開くんですか). Kata penunjuk + orang (この子, あの人) tetap ``IDENTITY_SUBJECTS``."""
GROUP_TOPICS = ("の", "メンバー", "二人", "ふたり", "代表", "候補", "当番", "犯人", "ペア", "コンビ")
"""Topik (sebelum は) yang menyebut sekelompok orang: ``topik は A と`` + run sesudahnya adalah daftar
nama (来たのは私と歩くんです, メンバーは僕と響くんだ), bukan と komitatif (友達と歩くんだ). ``の``
mewakili kalimat cleft 〜のは. Topik peran lain (``_person_head``: 主役は私と, 優勝は姉と) juga
daftar nama, kecuali ``ORDER_TOPICS``."""
AGENT_TOPICS = (
    "次", "最後", "最初", "今度", "一番", "兄", "姉", "弟", "妹", "兄貴", "姉貴", "息子", "娘", "孫",
    "甥", "姪", "いとこ", "親友", "友達", "友人", "幼なじみ", "幼馴染", "同級生", "同期", "先輩",
    "後輩", "仲間", "彼氏", "恋人", "相棒", "相方", "人", "一人", "ひとり", "子", "隣", "新人",
    "転校生", "クラスメイト", "チームメイト",
)
"""Topik yang, walau ada di ``PERSON_NOUNS``, bukan "posisi" yang diisi daftar nama: kata urutan
yang lazim berarti "berikutnya/akhirnya" (次は友達と歩くんだ) dan orang yang bertindak sendiri
(兄は友達と歩くんだ "kakak berjalan dengan teman"). + と sesudahnya tetap komitatif, sedangkan
topik posisi (主役は私と響くんです, 優勝は姉と輝くんでした) daftar nama."""
COMMON_HONORIFIC_WORDS = (
    "兄", "姉", "母", "父", "赤", "坊", "嬢", "奥", "客", "婆", "爺", "皆", "叔父", "叔母", "伯父",
    "伯母", "店員", "運転手",
)
"""Kata benda biasa yang lazim memakai honorifik (お兄ちゃん, お母さん, 赤ちゃん, 皆さん): + と/や
bukan perangkai nama (お兄ちゃんと歩くんだ kata kerja)."""
VOCATIVE_WORDS = TITLE_WORDS + ("先生", "先輩", "後輩", "師匠", "コーチ")
"""Gelar sapaan sebelum koma (先生、 部長、): yang menyusul adalah panggilan atau kalimat baru."""
INTERJECTIONS = ("おい", "ほら", "ねえ", "ねぇ", "なあ", "やあ", "ああ", "あれ", "あれっ", "えっ", "あっ",
                 "よし", "もしもし")
"""Seruan yang lazim tepat sebelum nama panggilan tanpa koma (ほら乾くんだよ)."""
GREETINGS = ("おはよう", "ありがとう", "こんにちは", "こんばんは", "さようなら", "ごめん", "おかえり",
             "ただいま", "おめでとう", "よろしく")
"""Salam yang lazim tepat sebelum nama panggilan tanpa koma (おはよう歩くん！)."""
SENTENCE_WORDS = INTERJECTIONS + GREETINGS + (
    "やはり", "やっぱり", "やっぱ", "まさか", "さすが", "なんだ", "そうだ", "また", "もしかして",
    "本当に", "ほんとに", "実は", "やっと", "ついに", "結局", "たぶん", "多分", "じゃあ", "では",
    "ところで", "それなら", "そういえば", "例えば", "たとえば",
)
"""Kata keterangan kalimat, seruan, dan salam yang berdiri sendiri (didahului awal teks atau
tanda baca) tepat sebelum run: posisi nama (やっぱり乾くんだ, まさか弾くんか, なんだ治さんか,
また開くんか, それなら直さんでもいい). Pengecualian: kata itu didahului benda + koma
(あの犬、本当に歩くんだね): benda itu topik yang partikelnya dilesapkan, jadi kata kerja."""
CONJUNCTIONS = ("それで", "そして", "でも", "だから", "しかし", "それに", "それから", "だけど",
                "けど", "けれど", "なのに")
"""Kata sambung antarklausa yang berdiri sendiri: yang menyusul lazimnya predikat klausa berikutnya
(だから歩くんだ, でも歩くんでしょ？, それで歩くんですか？), jadi dinilai topik (kata kerja kecuali
tulisannya terbukti nama di dokumen ini)."""
MANNER_WORDS = (
    "ちゃんと", "きちんと", "わざと", "っと", "まだ", "もう", "すぐ", "しっかり", "ゆっくり",
    "いつも", "なぜ", "どうして", "なんで", "いつ", "どこ", "どう", "たくさん", "いっぱい", "また",
    "必ず", "ただ", "誰も", "何も", "どれも",
)
"""Kata keterangan cara/waktu/jumlah dan kata tanya yang hanya menerangkan kata kerja (よく歩くんだ,
まだ待たんといけない, なぜ泣くんだ, たくさん歩くんだって, いっぱい咲くんだよ, 必ず輝くんだ, 誰も
通さん; ``っと`` mewakili ずっと, もっと, そっと, じっと, きっと). Kata berakhiran く (強く, 早く)
diperlakukan sama. ``また`` yang berdiri sendiri tetap ``SENTENCE_WORDS``."""
EPISTEMIC_WORDS = ("きっと", "たぶん", "やっぱり", "おそらく", "絶対に", "もしかして", "もしかしたら",
                   "まさか", "間違いなく")
"""Kata keterangan dugaan yang sesudah topik peran tetap posisi nama (犯人はきっと咲くんだ,
犯人はもしかして歩くん？, 犯人は間違いなく弾くんだよ). ``人`` umum (努力した人はきっと輝くんです:
orang pada umumnya) bukan topik peran di sini."""
TE_FORM_STEMS = frozenset("歌笑黙待持立走帰戻座祈願迷叫使払洗拾習誘張踊怒取作送守通言会思酔")
"""Kanji kata kerja yang bentuk -te-nya kanji + って (歌って, 笑って, 頑張って): って sesudahnya
bentuk て, jadi run berikutnya predikat (歌って歩くんだ, kasus). Sesudah kanji lain って adalah
penanda topik (窓って, 犯人って)."""
EVEN_QUOTE_HEADS = ("言", "い", "聞", "思", "知", "分", "わか", "話", "書", "信", "決", "噂", "こと",
                    "の", "よ", "ね", "さ", "ば")
"""Awal kata sesudah 〜くんだって yang menandai kutipan/kabar (歩くんだって言ってた, 輝くんだって
信じてる): kata kerja + ん + だって. Kata lain sesudahnya berarti "bahkan X" (歩くんだって疲れる)."""
_ATTRIBUTIVE_RE = re.compile(f"[{KANJI}ぁ-ゖ]い$")
"""Adjektiva -i atributif tepat sebelum run (強い輝くん, 優しい響くん): menerangkan kata benda
(nama), karena adjektiva tidak menerangkan kata kerja dalam bentuk -i. Kata ``NOT_ATTRIBUTIVE``
(ない/たい, くらい, いっぱい, seruan おい/はい) dikecualikan."""
NOT_ATTRIBUTIVE = ("ない", "たい", "くらい", "ぐらい", "いっぱい", "おい", "はい", "せい", "みたい")
_MIMETIC_RE = re.compile(
    r"(?:([ぁ-ゖ]{2})\1|([ァ-ヺ]{2})\2|[ぁ-ゖ][っん][ぁ-ゖ]り|[ァ-ヺ][ッン][ァ-ヺ]リ)$")
"""Onomatope/mimetik cara (とぼとぼ, ふらふら, キラキラ, のんびり, ゆっくり): keterangan kata kerja."""
_QUANTITY_RE = re.compile(
    r"[一二三四五六七八九十百千万何数半〇0-9０-９]+"
    r"(?:(?:円|歩|時間|日|回|度|個|本|枚|杯|分|秒|年|週間|か月|ヶ月|キロ|晩|滴|口|言|つ)[はも]|人も)$")
"""Bilangan + satuan + は/も (一円も, 一歩も, 一時間は, 一日も, 一人も): keterangan jumlah kata kerja
(一円も渡さん, 一日も保たん, 一人も通さん). 一番 (peringkat) dan 一人は (orang tertentu: 残りの
一人は咲くんだ) tidak termasuk."""
_PLURAL_ENDINGS = ("たち", "達", "ら", "ども", "全員", "みんな", "皆")
"""Akhiran jamak: subjek jamak (子どもたちが, 僕らが, 全員が) tidak pernah identitas satu nama."""
_PLURAL_PEOPLE_RE = re.compile(r"[二三四五六七八九十百何数0-9０-９]人$")
"""Bilangan orang lebih dari satu (三人は): jamak, bukan identitas satu nama."""
_CONJUNCTIVE_RE = re.compile(
    r"(?:なら|たら|だら|れば|けば|げば|せば|てば|ねば|べば|めば|えば|から|ので|のに|けど|けれど|"
    r"けれども|ても|でも|[うくぐすつぬぶむる]と|ないと)$")
"""Akhir anak kalimat kondisional/alasan/konsesif sebelum koma (傘がないなら、 雨がやんだら、
いいから、 疲れたけど、): run sesudah koma adalah predikat klausa utama (kata kerja), bukan
panggilan. Kata sambung yang berdiri sendiri (だから、 でも、 そういえば、) tetap ``SENTENCE_WORDS``."""
_FINAL_PARTICLES = frozenset("よねぞぜわ")
"""Partikel akhir kalimat tanpa tanda baca (待ってよ治さん！): run sesudahnya awal klausa baru."""
_CASE_TAILS = ("には", "では", "へは", "からは", "までは", "だけは", "にも", "でも", "ても", "へも",
               "ながら", "まま", "なら",
               "まで", "から", "より", "だけ", "ほど", "こそ", "しか", "さえ", "じゃ", "たら", "ば",
               "を", "に", "へ", "で")
_TOPIC_TAILS = ("って", "とは", "は")
_NOMINAL_NO = ("そんなの", "こんなの", "あんなの", "どんなの")
_REVEAL_CLAUSES = ("と思えば", "と思ったら")
"""Klausa "ternyata" (誰かと思えば乾くんか): yang menyusul adalah orang yang ditemukan, jadi panggilan."""
_COMMAS = frozenset("、，,")
_THING_TOPIC_RE = re.compile(f"[{KANJI}{KATAKANA}]は")
_TRAILING_WORD_RE = re.compile(f"[{KANJI}{KATAKANA}]+$")
VERB_CONTEXT_CHARS = 8
"""Jumlah huruf sebelum dan sesudah honorifik yang diberikan pemanggil (``ner``, ``protect``)
ke ``verb_run_before_honorific``; cukup untuk ekor seperti といけない dan subjek あの子は."""
VERB_AFTER_CHARS = 16
"""Jumlah huruf sesudah honorifik untuk ``verb_run_before_honorific`` (``ner``, ``protect``):
lebih panjang dari ``VERB_CONTEXT_CHARS`` agar bagian kalimat terbalik yang dipindah ke belakang
terlihat utuh (``ですかね、こんな雨の中``, ``ですね、意外と早く。``). Jendela sebelum run tetap
``VERB_CONTEXT_CHARS``."""
_BREAKS = frozenset("。．.！!？?…‥ー～〜」』）)］]】、，,「『（(\"'“”‘’ \t　\r\n")
DASH_BREAKS = "-－‐–—―"
"""Tanda dialog subtitle dan tanda pisah (sama dengan ``segment.DIALOGUE_DASHES``) SEBELUM run
adalah jeda (``_before_kind``): konteks dinilai dari kata sebelum tanda itu (``道を――歩くんだ`` kasus),
dan baru menjadi batas panggilan bila sebelumnya awal teks atau tanda baca (``－歩くん？``,
``「――歩くん？``). Sesudah honorifik tanda ini tetap netral (``行くん—`` bukan akhir), agar ``行``
tidak dibaca nama."""
_BEFORE_BREAKS = _BREAKS | frozenset(DASH_BREAKS)
_INVERTED_ARGUMENT_RE = re.compile(
    r"(?:だ|です)(?:か|よ|ね)?[、，](?P<arg>[^、，。！？!?…\s]{1,5}?(?:まで|[がをへにでも]))"
    r"[。．！!？?…‥」』]")
"""Argumen yang dipindah ke belakang kalimat sesudah kopula (``咲くんだ、桜が。``,
``歩くんですか、駅まで？``): sama dengan ``桜が咲くんだ`` dan ``駅まで歩くんですか``. Argumen harus
diakhiri partikel (が を へ に で も まで; bukan は) dan tanda akhir di dalam ``VERB_CONTEXT_CHARS``
huruf sesudah honorifik."""
_COPULA_COMMA = r"(?:だ|です|じゃない)(?:よね|かね|かな|か|よ|ね|な|ぞ|わ)?[、，]"
_TRAILING_POINTED_RE = re.compile(
    _COPULA_COMMA + f"(?:この|その|あの|こんな|そんな|あんな)(?P<noun>[{KANJI}{KATAKANA}ー]+)")
"""Kopula (atau ``じゃない``) + koma + kata penunjuk + kata benda di belakang kalimat
(``開くんだよ、この箱は。``, ``咲くんじゃないよ、その花は。``): calon kalimat terbalik dengan
topik/objek yang dipindah. Apa yang mengikuti kata benda diperiksa ``_pointed_thing``. Panggilan
tanpa kopula (``開くん、この箱どう？``) tidak cocok."""
POINTED_TAILS = "はをもが。．！!？?…‥」』"
"""Huruf sesudah kata benda ``_TRAILING_POINTED_RE`` yang menutup topik/objek yang dipindah
(``この箱は。``, ``そのギターを``, ``この扉が``, ``このドア！``). ``の`` (``このクラスの``,
``この写真の子は``) menerangkan kata lain, jadi bukan topik yang dipindah."""
POINTED_TIME_NOUNS = ("時間", "時期", "季節", "時", "頃", "日", "夜", "朝", "晩", "春", "夏", "秋",
                      "冬")
"""Kata waktu yang boleh disusul に/で (``この時間になると``, ``この季節に``): keterangan waktu
kata kerja. Kata benda lain + に/で (``このクラスで一番``, ``この大会で``) tidak dihitung."""
TRAIT_NOUNS = ("声", "字", "足音", "筆跡", "顔", "写真", "後ろ姿", "背中", "匂い", "絵", "手紙")
"""Ciri yang menunjuk orang (``歩くんだね、その声は。``, ``響くんだ、この字は。``): kalimat
identifikasi, jadi run tetap nama."""
_TRAILING_OBJECT_RE = re.compile(_COPULA_COMMA + r"(?P<obj>[^、，。！？!?…\s]{1,5})を")
"""Kopula + koma + objek を di belakang (``弾くんだよ、ギターを。``, ``弾くんだよ、ピアノを毎晩。``):
kata kerja, juga bila tanda akhir jatuh di luar ``VERB_AFTER_CHARS``. Objek orang
(``私を助けてくれたのは``, ``あの子を泣かせたのは``) adalah anak kalimat cleft, bukan objek run."""
_TRAILING_MANNER_RE = re.compile(
    _COPULA_COMMA + r"(?P<adv>[^、，。！？!?…\s]{0,5}く|ちゃんと|きちんと|しっかり|ゆっくり|必ず|いつも)"
    r"(?:[。．！!？?…‥」』]|$)")
"""Kopula + koma + kata keterangan cara di belakang (``乾くんですね、意外と早く。``,
``咲くんだね、ちゃんと。``): kata kerja. Salam berakhiran く (``君が輝くんだね、よろしく。``) dan
kata keterangan kalimat (``SENTENCE_ADVERBS``: ``おそらく``, ``間違いなく``) bukan keterangan cara."""
_CLAUSE_END_RE = re.compile(r"[。．！!？?…‥」』\n]")
_IDENTITY_DENIAL_RE = re.compile(
    f"じゃ(?:ない|なく)[^、，。！？!?]{{0,3}}[、，](?P<word>[{KANJI}{KATAKANA}ー]+)")
"""Pengingkaran identitas ``〜くんじゃないよ、別人だ``: yang diingkari orang, jadi run nama."""
IDENTITY_DENIAL_WORDS = ("別人", "本人", "他人", "偽者", "偽物", "人違い", "違う人")
"""Kata sesudah ``じゃない、`` yang menandai pengingkaran identitas (selain kata benda orang)."""
SENTENCE_ADVERBS = EPISTEMIC_WORDS + ("恐らく", "多分", "確かに", "とにかく", "ともかく", "実は")
"""Kata keterangan kalimat (dugaan/penegasan) di belakang kalimat (``犯人は拓くんだよ、絶対に。``,
``あれが拓くんだよ、間違いなく。``): tidak menerangkan run, jadi bukan bukti kata kerja."""

# Jenis konteks sebelum run (``_before_kind``).
BEFORE_CALL = "panggilan"
BEFORE_TOPIC = "topik"
BEFORE_SUBJECT = "subjek"
BEFORE_CASE = "kasus"
BEFORE_WITH = "komitatif"
BEFORE_WITH_SELF = "komitatif-diri"
BEFORE_ROLE = "peran"
BEFORE_OPEN_TOPIC = "topik-terbuka"
# Jenis konteks sesudah honorifik (``_after_kind``); ``None`` berarti pasti nama.
AFTER_COPULA = "kopula"
AFTER_STRONG_NEGATIVE = "negasi-kuat"
AFTER_EXCLAMATION = "seru"
AFTER_WEAK_NEGATIVE = "negasi-lemah"
AFTER_QUESTION = "tanya"
AFTER_NEUTRAL = "netral"
AFTER_END = "akhir"
AFTER_LINK = "sambung"
AFTER_FROM = "dari"
AFTER_EVEN = "bahkan"

VERB_CONTEXT_TABLE: dict[str, dict[str, int]] = {
    BEFORE_CALL: {AFTER_COPULA: 0, AFTER_STRONG_NEGATIVE: 0, AFTER_EXCLAMATION: 0,
                  AFTER_WEAK_NEGATIVE: 0, AFTER_QUESTION: 0, AFTER_NEUTRAL: 0, AFTER_END: -1,
                  AFTER_LINK: 0, AFTER_FROM: 0, AFTER_EVEN: 0},
    BEFORE_ROLE: {AFTER_COPULA: 0, AFTER_STRONG_NEGATIVE: 2, AFTER_EXCLAMATION: 1,
                  AFTER_WEAK_NEGATIVE: 0, AFTER_QUESTION: 0, AFTER_NEUTRAL: 0, AFTER_END: -1,
                  AFTER_LINK: 0, AFTER_FROM: 0, AFTER_EVEN: 0},
    BEFORE_OPEN_TOPIC: {AFTER_COPULA: 0, AFTER_STRONG_NEGATIVE: 1, AFTER_EXCLAMATION: 1,
                        AFTER_WEAK_NEGATIVE: 1, AFTER_QUESTION: 0, AFTER_NEUTRAL: 1, AFTER_END: 0,
                        AFTER_LINK: 0, AFTER_FROM: 0, AFTER_EVEN: 0},
    BEFORE_TOPIC: {AFTER_COPULA: 1, AFTER_STRONG_NEGATIVE: 1, AFTER_EXCLAMATION: 1,
                   AFTER_WEAK_NEGATIVE: 1, AFTER_QUESTION: 0, AFTER_NEUTRAL: 1, AFTER_END: 0,
                   AFTER_LINK: 1, AFTER_FROM: 0, AFTER_EVEN: 0},
    BEFORE_SUBJECT: {AFTER_COPULA: 2, AFTER_STRONG_NEGATIVE: 1, AFTER_EXCLAMATION: 1,
                     AFTER_WEAK_NEGATIVE: 1, AFTER_QUESTION: 1, AFTER_NEUTRAL: 1, AFTER_END: 0,
                     AFTER_LINK: 2, AFTER_FROM: 0, AFTER_EVEN: 1},
    BEFORE_CASE: {AFTER_COPULA: 2, AFTER_STRONG_NEGATIVE: 2, AFTER_EXCLAMATION: 2,
                  AFTER_WEAK_NEGATIVE: 2, AFTER_QUESTION: 1, AFTER_NEUTRAL: 2, AFTER_END: 0,
                  AFTER_LINK: 2, AFTER_FROM: 0, AFTER_EVEN: 2},
    BEFORE_WITH: {AFTER_COPULA: 2, AFTER_STRONG_NEGATIVE: 2, AFTER_EXCLAMATION: 2,
                  AFTER_WEAK_NEGATIVE: 2, AFTER_QUESTION: 1, AFTER_NEUTRAL: 2, AFTER_END: 0,
                  AFTER_LINK: 2, AFTER_FROM: 0, AFTER_EVEN: 2},
    BEFORE_WITH_SELF: {AFTER_COPULA: 2, AFTER_STRONG_NEGATIVE: 2, AFTER_EXCLAMATION: 2,
                       AFTER_WEAK_NEGATIVE: 2, AFTER_QUESTION: 1, AFTER_NEUTRAL: 2, AFTER_END: 0,
                       AFTER_LINK: 0, AFTER_FROM: 0, AFTER_EVEN: 0},
}
"""Aturan konteks kata kerja + ん: konteks sebelum x konteks sesudah → tingkat nama tertinggi yang
masih dibaca kata kerja.

Tingkat nama (``_name_level``): 0 tulisan bukan nama dikenal (行, 許, 待), 1 nama di data proyek
(``is_known_name``: 歩, 咲, 治, 乾), 2 terbukti nama di dokumen ini (``named``: honorifik + partikel
nama atau ruby di dokumen yang sama). Sel bernilai ``n`` berarti kata kerja untuk tingkat 0 sampai
``n``; -1 berarti selalu nama. Jadi ``駅まで歩くんですか`` (kasus x kopula = 2) dan ``桜が咲くんだ``
(subjek benda x kopula = 2) kata kerja walau kanjinya terbukti nama, ``ギターは弾くんだけど``
(topik benda x kopula = 1) kata kerja kecuali kanjinya terbukti nama di dokumen, ``主人公は響くんです``
dan ``弟の歩くんです`` (panggilan x kopula = 0) nama, sedangkan ``行くんですか`` dan ``行くん？`` (0)
tetap kata kerja karena 行 bukan nama. Topik x tanya dan semua baris x akhir bernilai 0
(``待って――歩くん？``, ``おはよう歩くん。``, ``起きて乾くん！``): くん langsung disusul ？ atau akhir
kalimat lebih lazim untuk panggilan. Kolom ``sambung`` (くん + で + kata: ``よく歩くんで足が``
kata kerja "karena", ``俺と弾くんでバンドを`` nama) dan ``dari`` (さん + から/や + kata: ``話さんから
安心して`` kata kerja hanya untuk tingkat 0, ``治さんから聞いた`` nama) membedakan dua pola yang
dulu dianggap pasti nama. Baris ``komitatif`` (と sesudah kata benda atau kata ganti orang kedua/
ketiga: ``友達と``, ``犬と``, ``彼女と``, ``お兄ちゃんと``) sama dengan kasus, termasuk
``毎日犬と歩くんで足が`` dan ``彼女と歩くんで緊張する`` (kata kerja "karena"). Baris
``komitatif-diri`` (kata ganti orang pertama + と: ``俺と``, ``私と``) sama dengan komitatif kecuali
kolom ``sambung``: ``俺と弾くんでバンドを作った`` nama ("aku dan Dan-kun"), ``僕と歩くんだ`` kata
kerja. Baris ``peran`` (kata benda orang sebagai topik/subjek: ``犯人は``, ``幹事は``, ``うちの兄が``)
sama dengan panggilan kecuali negasi kuat dan seru: ``お前に娘は渡さんぞ`` kata kerja (topik orang
sebagai objek), ``娘は渡さん！`` kata kerja kecuali 渡 terbukti nama di dokumen, ``犯人は渡さんだ``
nama. Baris ``topik-terbuka`` (kata benda yang bukan orang dan bukan benda/waktu/tempat yang
dikenali ``thing_head``: ``主砲は``, ``真犯人は`` di luar daftar, ``代わりは``) sama dengan topik
kecuali kolom kopula, tanya, sambung: nilainya 0 seperti baris topik baseline_v6, jadi
``主砲は歩くんです`` nama, sedangkan ``金は渡さん`` dan ``勝負は勝たんと`` tetap kata kerja. Kolom
``bahkan`` (〜くんだって/〜くんでも + kata yang bukan kutipan: ``でも歩くんだって疲れる``,
``強い歩くんでも勝てない``) nama di posisi panggilan, peran, dan topik, kata kerja sesudah kasus
(``毎日歩くんだって母が``)."""


def honorific_fits(hon: str, text: str, end: int) -> bool:
    """Periksa apakah honorifik kanji benar-benar honorifik, bukan awal kata lain.

    Honorifik kanji yang langsung diikuti kanji lain adalah bagian kata baru:
    殿下 (Yang Mulia), 君子 (nama Kimiko), 様子 (keadaan), 氏名 (nama lengkap).
    Sufiks orang tetap boleh menyusul (田中君達).

    Args:
        hon: Tulisan honorifik yang cocok (boleh kosong).
        text: Teks sumber.
        end: Posisi tepat setelah honorifik.
    """
    if not hon or not is_kanji(hon[-1]) or end >= len(text) or not is_kanji(text[end]):
        return True
    return text.startswith(tuple(PEOPLE_SUFFIXES), end)


def is_known_name(word: str) -> bool:
    """Tulisan dikenal sebagai nama utuh di data proyek.

    Sumbernya ``surnames.json``, ``given_names.json``, dan ``data.name_word_readings``
    (``NAME_WORD_READINGS`` + ``name_words.json``). Satu-satunya pemeriksaan "nama dikenal"
    untuk aturan kata kerja + ん.
    """
    return (word in data.surnames() or word in data.given_names()
            or word in data.name_word_readings())


def is_verb_stem(kanji: str) -> bool:
    """Kanji tunggal ini batang kata kerja di salah satu golongan ``data.VERB_STEMS``."""
    return any(kanji in stems for stems in data.VERB_STEMS.values())


def honorific_proves_name(run: str, hon: str, before: str, after: str) -> bool:
    """Run + honorifik ini konteks nama tegas, bukan hanya condong ke nama karena aturan konteks.

    Tegas bila honorifiknya tidak mungkin okurigana kata kerja untuk kanji terakhir run (咲ちゃん,
    歩さま, 輝さん: 輝 bukan batang 〜さん di ``data.VERB_STEMS``), bila huruf sesudahnya hanya
    mungkin untuk nama (``honorific_names_person``: 歩くんが, 歩くん、, 渡さんが来た), atau bila
    run + honorifik dipanggil dengan koma/seru di posisi panggilan (awal teks, tanda baca, seruan
    atau salam: 渡さん、おはよう, おい歩くん！). Negasi sesudah topik (娘は渡さん！, お前には
    渡さん！) dan kalimat yang hanya dibaca nama oleh aturan konteks (やっぱり歩くんだ) tidak tegas.
    っ sesudah honorifik (歩くんっすよ, 渡さんっ！) bukan bukti: yang dinilai hanya posisi
    panggilan dari huruf sesudah っ (巻くんっ！ di awal baris tegas, 娘は渡さんっ！ tidak).
    Dipakai ``ner.strong_name_counts`` untuk menyimpan entri batang kata kerja ke glosarium seri.
    """
    if not hon.endswith("ん") or run[-1:] not in data.VERB_STEMS.get(hon[:-1], frozenset()):
        return True
    if after[:1] == "っ":
        after = after[1:]
    elif honorific_names_person(hon, after):
        return True
    if after[:1] not in "、，,！!":
        return False
    trimmed = before.rstrip()
    return (not trimmed or trimmed[-1] in _BEFORE_BREAKS
            or _standalone(trimmed, INTERJECTIONS + GREETINGS) is not None)


def honorific_names_person(hon: str, after: str) -> bool:
    """Huruf sesudah honorifik ber-ん membuktikan nama (乾くんが, 開くん、, 治さんは, 治さんが来た)."""
    if len(hon) < 2 or not hon.endswith("ん"):
        return False
    return _after_kind(hon[:-1], after) is None


def _after_kind(okurigana: str, after: str) -> str | None:
    """Jenis konteks sesudah honorifik ber-ん; ``None`` bila konteks itu pasti nama.

    くん: lihat ``_after_kun_kind``. さん/たん (negasi lisan juga mungkin): lihat
    ``_after_negative_kind``.
    """
    if okurigana == "く":
        return _after_kun_kind(after)
    return _after_negative_kind(okurigana, after)


def _after_kun_kind(after: str) -> str | None:
    """Jenis konteks sesudah くん.

    ``NAME_PARTICLES``, っ, ー, ``KUN_NAME_TAILS`` (響くんから？, 弾くんまで), だけ yang bukan だけど
    (咲くんだけが), kanji/katakana langsung (partikel dilesapkan: 歩くん来るって, 咲くん派), dan
    や yang disusul kata (開くんや鳴ちゃん) pasti nama: kata kerja + ん tidak pernah langsung
    disusul kata. で yang disusul kata sambung (よく歩くんで足が "karena", 弾くんでバンド "dengan");
    ``VERB_ENDING_FOLLOWERS`` kopula (行くんだ); ？ tanya; tanda baca lain dan akhir teks akhir
    (乾くん！); selebihnya netral. っす/っしょ (歩くんっすよ: です lisan) kopula. だって/でも yang
    disusul kata bukan kutipan (歩くんだって疲れる, 歩くんでも勝てない: "bahkan X") ``bahkan``;
    だって + 言/聞/思 (歩くんだって言ってた) tetap kopula.
    """
    head = after[:1]
    if after.startswith(("っす", "っしょ")):
        return AFTER_COPULA
    if head in NAME_PARTICLES or head in "っー" or after.startswith(KUN_NAME_TAILS):
        return None
    if after.startswith("だけ") and not after.startswith(("だけど", "だけれど")):
        return None
    if _starts_with_word(after) or (head == "や" and _starts_with_word(after[1:])):
        return None
    for tail in ("だって", "でも"):
        rest = after[len(tail):]
        if after.startswith(tail) and _starts_with_word(rest) and not rest.startswith(
                EVEN_QUOTE_HEADS):
            return AFTER_EVEN
    if head == "で" and _starts_with_word(after[1:]):
        return AFTER_LINK
    if head in VERB_ENDING_FOLLOWERS:
        return AFTER_COPULA
    if head in "？?":
        return AFTER_QUESTION
    return AFTER_END if not head or head in _BREAKS else AFTER_NEUTRAL


def _after_negative_kind(okurigana: str, after: str) -> str | None:
    """Jenis konteks sesudah さん/たん.

    Pasti nama: ``NEGATIVE_NAME_FOLLOWERS``; の yang bukan tanya dan disusul kata (治さんの家);
    が yang langsung disusul predikat (治さんが来た; 貸さんが、 tidak); からも/からは (治さんからも);
    だ/じゃ/です sesudah さん. や atau から yang disusul kata ``dari`` (治さんから聞いた nama,
    話さんから安心して kata kerja: hanya tingkat 0 yang kata kerja). Lalu ``NEGATIVE_TAIL_RE``
    negasi kuat; の + akhir/よ/ね/だ/で (勝たんのよ, これは治さんのよ) dan ``WEAK_NEGATIVE_TAILS``
    sesudah さん negasi lemah; ！ seru; ？ tanya; sesudah たん ``VERB_ENDING_FOLLOWERS`` kopula
    (来たんだ). っ yang disusul tanda baca atau akhir teks (渡さんっ！) dinilai dari huruf
    sesudahnya; っ yang disusul huruf (治さんって) tetap pasti nama.
    """
    head, rest = after[:1], after[1:]
    if head == "っ" and (not rest or rest[0] in _BREAKS):
        return _after_negative_kind(okurigana, rest)
    strong = NEGATIVE_TAIL_RE.match(after) is not None
    if head in NEGATIVE_NAME_FOLLOWERS:
        return None
    if head == "の" and not strong:
        return AFTER_WEAK_NEGATIVE if not rest or rest[0] in "よねだでさ" or rest[0] in _BREAKS \
            else None
    if head == "が" and rest[:1] and rest[0] not in _BREAKS:
        return None
    if after.startswith("から") and after[2:3] in ("も", "は"):
        return None
    if (head == "や" and _starts_with_word(rest)) or (
            after.startswith("から") and _starts_with_word(after[2:])):
        return AFTER_FROM
    if okurigana == "さ" and (head in "だじ" or after.startswith(("です", "でし"))):
        return None
    if strong:
        return AFTER_STRONG_NEGATIVE
    if head in "！!":
        return AFTER_EXCLAMATION
    if head in "？?":
        return AFTER_QUESTION
    if okurigana == "さ" and after.startswith(WEAK_NEGATIVE_TAILS):
        return AFTER_WEAK_NEGATIVE
    if okurigana != "さ" and head in VERB_ENDING_FOLLOWERS:
        return AFTER_COPULA
    return AFTER_NEUTRAL


def _ends_with_break(text: str) -> bool:
    """``text`` berakhir tanda baca/jeda (``_BREAKS``). ー sesudah katakana adalah tanda panjang
    kata itu (ギター, セーター), bukan jeda: ギター弾くんだ adalah objek tanpa partikel."""
    if not text or text[-1] not in _BREAKS:
        return False
    return not (text[-1] == "ー" and len(text) > 1 and is_katakana(text[-2]))


def _starts_with_word(text: str) -> bool:
    """``text`` diawali kanji atau katakana (awal kata benda/kata kerja berikutnya)."""
    return bool(text) and (is_kanji(text[0]) or is_katakana(text[0]))


def _standalone(before: str, words: tuple[str, ...]) -> str | None:
    """Kata ``words`` yang berdiri sendiri di akhir ``before``, atau ``None``.

    Berdiri sendiri: didahului awal teks, tanda baca/spasi, atau ``DASH_BREAKS``, jadi でも di
    雨でも dan また di 今また bukan kata sambung/keterangan kalimat.
    """
    for word in words:
        if before.endswith(word):
            rest = before[:-len(word)]
            if not rest or rest[-1] in _BEFORE_BREAKS:
                return word
    return None


def _before_kind(before: str, verb: str = "") -> str:
    """Jenis konteks tepat sebelum run kanji; ``verb`` adalah batang + okurigana (咲く) atau kosong.

    - panggilan: awal teks, tanda baca, spasi, kanji (bagian nama lengkap), ``SENTENCE_WORDS``
      (kecuali sesudah benda + koma), の atributif, adjektiva -i atributif (強い輝くん), や
      perangkai, nama + honorifik + と/や (咲ちゃんと歩くん), partikel akhir よ/ね/ぞ/ぜ/わ, klausa
      ``_REVEAL_CLAUSES`` (誰かと思えば乾くんか), kata identitas (``_host_kind``: あれが, あの子、,
      君が, のは, 君は + kata kerja benda, cleft + kata dugaan: 勝つのはやっぱり), kata benda orang
      katakana tanpa partikel (うちのリーダー歩くん), dan daftar nama (``_with_kind``: 来たのは私と,
      主役は私と, 先生と + 咲く);
    - peran: kata benda orang + は/が/koma (``_host_kind``: 犯人は, うちの兄が, 幹事は, 四番は,
      真犯人は, お客さんは, あそこに立ってる人が), juga sesudah kata dugaan (犯人はきっと,
      犯人はもしかして);
    - topik terbuka: kata benda kanji atau katakana berakhiran ー yang bukan orang dan bukan
      benda/waktu/tempat yang dikenali + は/って/koma (``_noun_topic_kind``: 主砲は, 代わりは);
    - kasus: を, に, へ, まで, で, から, より, だけ, ほど, こそ, しか, さえ, じゃ, ながら, まま, なら
      (juga には, でも, ても, からは, だけは), bentuk kondisional/て (〜たら, 〜ば, 〜て, 押すと,
      どうやって, 歌って), kata ganti orang pertama + は/も/が (僕は, 僕が), kata ganti + も, bilangan
      + satuan + は/も (一円も), ``MANNER_WORDS``, onomatope (とぼとぼ, のんびり, キラキラ), dan kata
      berakhiran く;
    - komitatif: と sesudah kata benda atau kata ganti (友達と, お兄ちゃんと, 誰と); kata ganti
      orang pertama + と komitatif-diri (俺と);
    - subjek: が/も sesudah kata lain (桜が咲くん, 人が歩くん), katakana lain (juga yang
      berakhiran ー: ギター弾くん), そんなの;
    - topik: は/って/koma sesudah benda/waktu/tempat yang dikenali (``thing_head``: ギターは,
      冬は, この窓って, 窓、), orang umum atau jamak (人は, 僕らは), kata katakana tanpa ー akhir,
      kata ganti orang kedua/ketiga + は (君は), とは, ``CONJUNCTIONS`` yang berdiri sendiri
      (だから歩くん), dan hiragana lain.

    Deretan ``DASH_BREAKS`` (dan spasi di sekitarnya) tepat sebelum run adalah jeda: konteksnya
    kata sebelum tanda itu (``_before_dash_kind``).
    """
    trimmed = before.rstrip()
    if trimmed[-1:] and trimmed[-1] in DASH_BREAKS:
        return _before_dash_kind(trimmed.rstrip(DASH_BREAKS).rstrip(), verb)
    if before[-1:] in _COMMAS:
        return _comma_kind(before[:-1].rstrip(), verb)
    if not before or _ends_with_break(before) or is_kanji(before[-1]) or _joined_name(before):
        return BEFORE_CALL
    if _standalone(before, CONJUNCTIONS) is not None:
        return BEFORE_TOPIC
    word = _standalone(before, SENTENCE_WORDS)
    if word is not None:
        rest = before[:-len(word)].rstrip()
        if rest[-1:] in _COMMAS and _comma_kind(rest[:-1].rstrip()) not in (BEFORE_CALL,
                                                                            BEFORE_ROLE):
            return BEFORE_CASE
        return BEFORE_CALL
    if before.endswith(_NOMINAL_NO):
        return BEFORE_SUBJECT
    if before.endswith(_REVEAL_CLAUSES):
        return BEFORE_CALL
    return _word_kind(before, verb)


def _word_kind(before: str, verb: str = "") -> str:
    """Jenis konteks dari kata/partikel hiragana atau katakana di akhir ``before`` (lihat
    ``_before_kind``)."""
    if not is_hiragana(before[-1]):
        return _katakana_kind(before)
    if before.endswith(("って", "は", "が", "も")) and not before.endswith(_CASE_TAILS):
        particle = "って" if before.endswith("って") else before[-1]
        kind = _host_kind(before[:-len(particle)], particle, verb)
        if kind is not None:
            return kind
    if _QUANTITY_RE.search(before):
        return BEFORE_CASE
    epistemic = next((word for word in EPISTEMIC_WORDS if before.endswith(word)), None)
    if epistemic is not None:
        return _epistemic_kind(before[:-len(epistemic)], verb)
    if before[-1] == "と" and not before.endswith(MANNER_WORDS):
        return _with_kind(before[:-1], verb)
    if (before.endswith(MANNER_WORDS) or before.endswith(_CASE_TAILS) or before[-1] == "く"
            or _MIMETIC_RE.search(before)):
        return BEFORE_CASE
    if before[-1] == "て" and not before.endswith("って"):
        return BEFORE_CASE
    if before.endswith("って"):
        head = before[:-2]
        if head and (is_hiragana(head[-1]) or head[-1] in TE_FORM_STEMS):
            return BEFORE_CASE
        return _noun_topic_kind(head)
    if _ATTRIBUTIVE_RE.search(before) and not before.endswith(NOT_ATTRIBUTIVE):
        return BEFORE_CALL
    if before[-1] in "のや" or before[-1] in _FINAL_PARTICLES:
        return BEFORE_CALL
    if before.endswith("は") and not before.endswith("とは"):
        return _noun_topic_kind(before[:-1])
    if before.endswith(_TOPIC_TAILS):
        return BEFORE_TOPIC
    if before[-1] in "がも":
        return BEFORE_SUBJECT
    return BEFORE_TOPIC


def _epistemic_kind(head: str, verb: str = "") -> str:
    """Jenis konteks run sesudah kata dugaan ``EPISTEMIC_WORDS``; ``head`` teks sebelum kata itu.

    Sesudah topik peran, kata identitas, atau topik kata benda terbuka (犯人はきっと, 勝つのは
    やっぱり, 主砲はまさか) posisi nama tetap berlaku; selebihnya kata keterangan kata kerja
    (きっと咲くんだ, 努力した人はきっと輝くんです: ``人`` umum) kasus.
    """
    if head.endswith("は") and not _ends_with_word(head[:-1], ("人",)):
        kind = _host_kind(head[:-1], "は", verb) or _noun_topic_kind(head[:-1])
        if kind in (BEFORE_CALL, BEFORE_ROLE, BEFORE_OPEN_TOPIC):
            return kind
    return BEFORE_CASE


def _katakana_kind(before: str) -> str:
    """Jenis konteks run yang langsung didahului kata katakana (atau huruf non-kana lain).

    Kata benda orang katakana tanpa partikel adalah aposisi (うちのリーダー歩くんです, 新メンバー
    響くんだよ): panggilan. Onomatope (キラキラ輝くんだ) kasus. Kata katakana lain adalah objek
    atau subjek tanpa partikel (ギター弾くんだ, セーター乾くんですか): subjek.
    """
    match = re.search(f"[{KATAKANA}]+$", before)
    word = match.group() if match else ""
    if word and _person_head(word):
        return BEFORE_CALL
    if word and _MIMETIC_RE.search(word):
        return BEFORE_CASE
    return BEFORE_SUBJECT


def thing_head(host: str) -> bool:
    """``host`` berakhir dengan kata benda/waktu/tempat yang dikenali sebagai topik kata kerja.

    ``THING_WORDS`` (ギター, 窓, 帰り, 冬), ``THING_ENDINGS`` (金曜日, 雨の日, 洗濯物, 帰り道), atau
    kata penunjuk + kata benda (``DEMONSTRATIVES``: この扉, その傘, あの店). Kata benda orang
    diperiksa lebih dulu oleh pemanggil (``_person_head``).
    """
    if host.endswith(THING_WORDS) or host.endswith(THING_ENDINGS):
        return True
    match = _TRAILING_WORD_RE.search(host)
    return bool(match) and host[:match.start()].endswith(DEMONSTRATIVES)


def _noun_topic_kind(host: str) -> str:
    """Jenis konteks topik ``host`` + は/って/koma yang bukan kata identitas atau kata benda orang.

    Topik benda/waktu/tempat yang dikenali (``thing_head``: ギターは, 冬は, この扉は), topik
    jamak atau orang umum (僕らは, 人は, 大人は), kata hiragana (いつもは, それでも), dan kata katakana
    yang tidak berakhiran ー (シーツは, カーテンは: kebanyakan benda serapan; peran katakana yang lazim
    ada di ``PERSON_NOUNS``) adalah topik kata kerja. Kata benda kanji lain dan katakana berakhiran
    ー (主砲は, 先鋒は, 参謀は, ストライカーは: pola pelaku -er) adalah ``topik-terbuka``: lebih
    sering peran yang diisi nama, seperti di baseline_v6.
    """
    if (not host or thing_head(host) or host.endswith(_PLURAL_ENDINGS)
            or _PLURAL_PEOPLE_RE.search(host) or _ends_with_word(host, ("人",))
            or host.endswith(NOT_PERSON_WORDS)):
        return BEFORE_TOPIC
    if is_kanji(host[-1]) or host[-1] in "ーｰ":
        return BEFORE_OPEN_TOPIC
    return BEFORE_TOPIC


def _with_kind(host: str, verb: str = "") -> str:
    """Jenis konteks run sesudah ``host`` + と; ``verb`` seperti di ``_before_kind``.

    と sesudah bentuk kata kerja (押すと, 行かないと) kondisional: kasus. Sesudah topik kelompok
    atau posisi (``GROUP_TOPICS``, ``_person_head`` di luar ``AGENT_TOPICS``: 来たのは私と,
    メンバーは僕と, 主役は私と, 優勝は姉と) daftar nama: panggilan. Orang + と sebelum kata kerja
    yang subjeknya benda (``INANIMATE_VERBS``: 先生と咲くんかな) juga daftar nama. Kata ganti orang
    pertama + と (俺と, 私と): komitatif-diri. Selebihnya と komitatif sesudah kata benda/kata ganti
    (友達と, 犬と, 彼女と, お兄ちゃんと): komitatif.
    """
    if host.endswith("ない") or (host[-1:] and host[-1] in "うくぐすつぬぶむる"
                                and not _ends_with_word(host, PERSONAL_PRONOUNS)
                                and not host.endswith(IDENTITY_SUBJECTS)):
        return BEFORE_CASE
    topic = host.rfind("は")
    head = host[:topic] if topic > 0 else ""
    if head and (head.endswith(GROUP_TOPICS) or (
            _person_head(head) and not _ends_with_word(head, AGENT_TOPICS))):
        return BEFORE_CALL
    if verb in INANIMATE_VERBS and (_person_head(host) or _ends_with_word(
            host, PERSONAL_PRONOUNS + VOCATIVE_WORDS)):
        return BEFORE_CALL
    if _ends_with_word(host, FIRST_PERSON_PRONOUNS):
        return BEFORE_WITH_SELF
    return BEFORE_WITH


def _host_kind(host: str, particle: str, verb: str = "") -> str | None:
    """Jenis konteks kata ``host`` + ``particle`` (は/が/も/って, atau 、 untuk partikel yang
    dilesapkan), atau ``None`` bila ``host`` bukan kata identitas.

    ``IDENTITY_SUBJECTS`` panggilan. ``PERSONAL_PRONOUNS``: orang pertama + が kasus (僕が歩くんですか:
    orang tidak menyebut dirinya dengan くん); orang kedua/ketiga + が, atau kata ganti + は/koma
    sebelum kata kerja yang subjeknya bukan orang (``INANIMATE_VERBS``: 君は響くんだね？), panggilan;
    orang kedua/ketiga + は/koma topik (君は歩くんだよ); selebihnya kasus (僕は歩くんだ, お前も
    歩くんだよ). Kata benda orang (``_person_head``: 犯人は, うちの兄が, 幹事は, 残りの一人は,
    真犯人は, お客さんは) peran dengan は/が/koma, kecuali subjek jamak (全員が, 三人は) dan subjek が
    yang didahului topik benda di jendela yang sama (バイオリンはうちの姉が弾くんです: kalimat kata
    kerja). ``人`` tanpa penjelas + は/が (人は歩くんだよ, 夜中でも人が歩くんですか) adalah orang
    pada umumnya, bukan peran; ``人`` berpenjelas (好きな人は, あそこに立ってる人が) tetap peran.
    """
    if host.endswith(IDENTITY_SUBJECTS):
        return BEFORE_CALL
    if host.endswith(_PLURAL_ENDINGS) or _PLURAL_PEOPLE_RE.search(host):
        return None
    if _ends_with_word(host, PERSONAL_PRONOUNS):
        if particle == "が" and _ends_with_word(host, FIRST_PERSON_PRONOUNS):
            return BEFORE_CASE
        if particle == "が" or (particle != "も" and verb in INANIMATE_VERBS):
            return BEFORE_CALL
        if particle in ("は", "、") and not _ends_with_word(host, FIRST_PERSON_PRONOUNS):
            return BEFORE_TOPIC
        return BEFORE_CASE
    if particle in ("も", "って") or not _person_head(host):
        return None
    if _ends_with_word(host, ("人",)) and _bare_word_head(host[:-1]):
        return None
    if particle == "が" and _THING_TOPIC_RE.search(host):
        return BEFORE_SUBJECT
    return BEFORE_ROLE


def _bare_word_head(rest: str) -> bool:
    """Teks sebelum sebuah kata berakhir awal teks, tanda baca, atau partikel: kata itu tidak
    diterangkan kata lain (人 di 人は, 夜は人が; bukan di 好きな人は, 近所の人は)."""
    return not rest or rest[-1] in _BEFORE_BREAKS or rest[-1] in "もはにでがをとへや"


def _person_head(host: str) -> bool:
    """``host`` berakhir dengan kata benda orang/peran.

    ``PERSON_NOUNS`` sebagai kata utuh (juga dengan satu awalan ``ROLE_PREFIXES``: 真犯人,
    副担任), ``PERSON_NOUN_ENDINGS`` (持ち主, 主治医, 差出人; kecuali ``NOT_PERSON_WORDS``),
    peringkat (``_RANK_RE``), atau kata benda orang + honorifik (``HONORIFIC_NOUN_TAILS``: 店員さん,
    王子様, dan kata berawalan お/ご: お客さん, お巡りさん). ``席`` sesudah kata penunjuk (この席,
    その席) adalah kursi itu sendiri, bukan orang yang duduk di sana (窓際の席は輝くんだよ).
    """
    if host.endswith(("この席", "その席", "あの席")) or host.endswith(NOT_PERSON_WORDS):
        return False
    for tail in HONORIFIC_NOUN_TAILS:
        if host.endswith(tail) and len(host) > len(tail):
            stem = host[:-len(tail)]
            return _person_head(stem) or _POLITE_NOUN_RE.search(stem) is not None
    if (_ends_with_word(host, PERSON_NOUNS) or any(_compound_tail(host, tail)
                                                    for tail in PERSON_NOUN_ENDINGS)
            or _RANK_RE.search(host) is not None):
        return True
    for word in PERSON_NOUNS:
        rest = host[:-len(word)]
        if host.endswith(word) and rest[-1:] in ROLE_PREFIXES and (
                len(rest) == 1 or not (is_kanji(rest[-2]) or is_katakana(rest[-2]))):
            return True
    return False


def _compound_tail(host: str, tail: str) -> bool:
    """``host`` berakhir ``tail``; ekor satu huruf harus menempel ke kata di depannya (持ち主,
    運転手, 差出人), bukan berdiri sendiri sesudah partikel atau awal teks (手は, 猫の手は)."""
    if not host.endswith(tail):
        return False
    rest = host[:-len(tail)]
    return len(tail) > 1 or (bool(rest) and rest[-1] not in _BEFORE_BREAKS
                             and rest[-1] not in "のはがもをにへとでや")


def _ends_with_word(text: str, words: tuple[str, ...]) -> bool:
    """``text`` berakhir dengan salah satu ``words`` sebagai kata utuh (tidak didahului
    kanji/katakana: 子 di 背の高い子, bukan di 帽子)."""
    for word in words:
        if text.endswith(word):
            rest = text[:-len(word)]
            if not rest or not (is_kanji(rest[-1]) or is_katakana(rest[-1])):
                return True
    return False


def _comma_kind(rest: str, verb: str = "") -> str:
    """Jenis konteks run sesudah koma; ``rest`` adalah teks sebelum koma.

    Koma sering menggantikan partikel topik (窓、開くんですか, 布団、乾くんですかね): benda biasa
    sebelum koma adalah topik. Panggilan: awal teks/tanda baca, hiragana (seruan, salam, partikel
    akhir, kata sambung yang berdiri sendiri: やあ、 ねえ、 優しいね、 でも、), kata identitas atau kata
    benda orang (あの子、 犯人、), ``VOCATIVE_WORDS`` (先生、 部長、), dan nama dikenal dua huruf atau
    lebih (田中、; 桜、 dan 花、 satu kanji juga kata biasa, jadi topik). Anak kalimat
    kondisional/alasan/konsesif (``_CONJUNCTIVE_RE``: 傘がないなら、 雨がやんだら、 疲れたけど、)
    kasus. は/が/も sebelum koma dinilai seperti tanpa koma (窓は、 topik, あれは、 panggilan); kata
    ganti orang pertama + koma kasus (僕、). Kata benda lain sebelum koma dinilai
    ``_noun_topic_kind``: benda/waktu yang dikenali (洗濯物、 明日、) topik, selebihnya topik terbuka.
    """
    if not rest or rest[-1] in DASH_BREAKS or _ends_with_break(rest):
        return BEFORE_CALL
    if is_hiragana(rest[-1]):
        if rest[-1] in "はがも" and len(rest) > 1 and not is_hiragana(rest[-2]):
            return _host_kind(rest[:-1], rest[-1], verb) or (
                BEFORE_TOPIC if rest[-1] == "は" else BEFORE_SUBJECT)
        if _standalone(rest, SENTENCE_WORDS) is None and _CONJUNCTIVE_RE.search(rest):
            return BEFORE_CASE
        return _host_kind(rest, "、", verb) or BEFORE_CALL
    kind = _host_kind(rest, "、", verb)
    if kind is not None:
        return kind
    match = _TRAILING_WORD_RE.search(rest)
    word = match.group() if match else ""
    if word.endswith(VOCATIVE_WORDS) or _surname_head(word) or (
            len(word) > 1 and is_known_name(word)):
        return BEFORE_CALL
    return _noun_topic_kind(rest)


def _before_dash_kind(rest: str, verb: str = "") -> str:
    """Jenis konteks run yang didahului tanda pisah/dialog; ``rest`` adalah teks sebelum tanda itu.

    Awal teks atau tanda baca (``－歩くん？``, ``「――歩くん？``, ``　――歩くんだよね``) adalah
    panggilan. Kata berakhiran kanji tidak menjadi bagian nama karena dipisah tanda: nama dikenal
    (``田中――歩くん？``) panggilan, kata lain (``毎日――歩くんだ``) subjek seperti katakana.
    Selebihnya aturan biasa, jadi partikel sebelum jeda tetap dihitung (``道を――歩くんだ`` kasus,
    ``桜が――咲くんだ`` subjek, ``花は――咲くんだよ`` topik seperti ``花は咲くんだよ``). Bentuk
    って sebelum jeda (``待って――歩くん？``) adalah akhir klausa perintah, jadi topik, bukan bentuk
    て yang menerangkan run (``歌って歩くんだ`` kasus).
    """
    if not rest or rest[-1] in _BREAKS:
        return BEFORE_CALL
    if is_kanji(rest[-1]):
        word = KANJI_RE.findall(rest)[-1]
        return BEFORE_CALL if is_known_name(word) or _surname_head(word) else BEFORE_SUBJECT
    kind = _before_kind(rest, verb)
    return BEFORE_TOPIC if kind == BEFORE_CASE and rest.endswith("って") else kind


def _inverted_kind(before: str, after: str, kind: str) -> str:
    """Jenis konteks ``kind`` disesuaikan dengan bagian kalimat yang dipindah ke belakang run.

    Bukti kata kerja sesudah kopula + koma (``_trailing_verb``: penunjuk + benda, objek を,
    keterangan cara, argumen kasus) membuat konteks kasus, kecuali konteks sebelumnya sudah kuat
    menandai nama (``_strong_name_context``: ``犯人は拓くんだよ、この事件の。``, ``優勝したのは
    響くんだよ、しかも大差で。``) atau bagian belakang adalah anak kalimat cleft
    (``拓くんだよ、ボールを投げたのは。``). Penunjuk + benda tetap berlaku sesudah subjek orang + が
    (``うちの兄が弾くんです、そのピアノ。``). Hanya untuk run di awal klausa (``kind`` panggilan dan
    ``before`` kosong, tanda baca, atau tanda pisah saja): argumen lain mengikuti partikelnya,
    jadi ``咲くんだ、桜が。`` sama dengan ``桜が咲くんだ`` (subjek). Argumen berupa nama atau kata
    identitas (``歩くんだ、あいつが。``) tetap panggilan.
    """
    if _strong_name_context(before, kind) or _cleft_tail(after):
        return kind
    if _trailing_verb(after, pointed_only=kind == BEFORE_ROLE):
        return BEFORE_CASE
    match = _INVERTED_ARGUMENT_RE.match(after)
    if not match or kind == BEFORE_ROLE:
        return kind
    arg_kind = _before_kind(match["arg"])
    if arg_kind == BEFORE_CASE:
        return kind if match["arg"].startswith(SENTENCE_ADVERBS) else BEFORE_CASE
    rest = before.rstrip().rstrip(DASH_BREAKS).rstrip()
    if kind != BEFORE_CALL or (rest and rest[-1] not in _BREAKS):
        return kind
    return arg_kind


def _strong_name_context(before: str, kind: str) -> bool:
    """Konteks sebelum run sudah kuat menandai nama: topik peran + は (``犯人は``, ``委員長は``,
    ``次の主将は``) atau fokus cleft (``優勝したのは``, ``呼んだのは``, ``好きなのが``)."""
    rest = before.rstrip()
    return (kind == BEFORE_ROLE and rest.endswith("は")) or rest.endswith(("のは", "のが"))


def _cleft_tail(after: str) -> bool:
    """Bagian sesudah kopula + koma sampai akhir klausa adalah anak kalimat cleft ``…のは``/
    ``…のが`` (``拓くんです、この絵を描いたのは。``): run adalah fokus identitas, jadi nama."""
    comma = re.search("[、，]", after)
    if comma is None:
        return False
    clause = _CLAUSE_END_RE.split(after[comma.end():], maxsplit=1)[0]
    return "のは" in clause or "のが" in clause


def _trailing_verb(after: str, *, pointed_only: bool = False) -> bool:
    """Bagian belakang sesudah kopula + koma menandai kata kerja.

    Penunjuk + benda yang bukan orang/ciri orang (``_pointed_thing``); bila ``pointed_only``
    salah juga objek を yang bukan orang (``ギターを``) dan keterangan cara (``意外と早く``,
    ``ちゃんと``) yang bukan salam atau kata keterangan kalimat (``SENTENCE_ADVERBS``).
    """
    if _pointed_thing(after):
        return True
    if pointed_only:
        return False
    obj = _TRAILING_OBJECT_RE.match(after)
    if obj and not (_person_head(obj["obj"]) or _ends_with_word(obj["obj"], PERSONAL_PRONOUNS)):
        return True
    manner = _TRAILING_MANNER_RE.match(after)
    return bool(manner) and not manner["adv"].endswith(GREETINGS) and not manner[
        "adv"].startswith(SENTENCE_ADVERBS)


def _pointed_thing(after: str) -> bool:
    """Kopula + koma + penunjuk + benda yang dipindah dari depan (``開くんだよ、この箱は。``).

    Kata benda harus disusul ``POINTED_TAILS``/akhir teks, ``の中`` (``こんな雨の中を``), atau
    に/で sesudah kata waktu (``この時間になると``). Kata benda orang (``その人は``), ciri orang
    (``TRAIT_NOUNS``: ``その声は``), dan ``この中`` ("di antara ini") tidak dihitung.
    """
    match = _TRAILING_POINTED_RE.match(after)
    if match is None:
        return False
    noun, tail = match["noun"], after[match.end():]
    if noun.startswith("中") or _person_head(noun) or noun.endswith(TRAIT_NOUNS):
        return False
    if not tail or tail[0] in POINTED_TAILS or tail.startswith("の中"):
        return True
    return tail[0] in "にで" and noun.endswith(POINTED_TIME_NOUNS)


def _joined_name(before: str) -> bool:
    """``before`` berakhir dengan nama + honorifik + と/や (咲ちゃんと, 田中さんや): perangkai nama.

    Honorifik harus didahului kanji atau katakana (nama), jadi ちゃんと sesudah koma atau awal
    teks (傘、ちゃんと開くんですか) tetap kata keterangan. Kata benda biasa ber-honorifik
    (``COMMON_HONORIFIC_WORDS``: お兄ちゃんと, お母さんと, 赤ちゃんと) bukan nama. ちゃんと sesudah
    kata kanji yang bukan nama dikenal (毎日ちゃんと歩くんだ, 毎年ちゃんと咲くんです, 傘ちゃんと
    開くんですか: partikel dilesapkan) juga kata keterangan "dengan benar"; 咲ちゃんと (nama dikenal,
    ``is_known_name``/nama keluarga) dan katakana (カナちゃんと) tetap perangkai nama.
    """
    if before[-1] not in "とや":
        return False
    head = before[:-1]
    for hon in HONORIFIC_SURFACES:
        if head.endswith(hon) and _starts_with_word(head[-len(hon) - 1:-len(hon)]):
            host = head[:-len(hon)]
            if before.endswith("ちゃんと") and is_kanji(host[-1]):
                word = KANJI_RE.findall(host)[-1]
                return is_known_name(word) or _surname_head(word)
            return not host.endswith(COMMON_HONORIFIC_WORDS)
    return False


def _denies_identity(after: str) -> bool:
    """``after`` mengingkari identitas orang: ``じゃないよ、別人`` atau ``じゃない、本人に``
    (``IDENTITY_DENIAL_WORDS``) atau kata benda orang sesudah koma. Run sebelumnya nama
    (``彼は拓くんじゃないよ、別人だ。``); ``彼は歩くんじゃないよ、走るんだ`` tetap kata kerja.
    Kata benda orang + が/は adalah subjek klausa kontras baru (``花が咲くんじゃない、人が
    咲かせるんだ``, ``僕が歩くんじゃなくて、先生が歩くんだ``), bukan pengingkaran identitas."""
    match = _IDENTITY_DENIAL_RE.match(after)
    if match is None:
        return False
    if match["word"].startswith(IDENTITY_DENIAL_WORDS):
        return True
    return _person_head(match["word"]) and not after[match.end():].startswith(("が", "は"))


def _name_level(word: str, named: frozenset[str]) -> int:
    """Tingkat nama untuk ``VERB_CONTEXT_TABLE``: 2 ``named``, 1 ``is_known_name``, 0 lainnya."""
    if word in named:
        return 2
    return 1 if is_known_name(word) else 0


def _surname_head(prefix: str) -> bool:
    """``prefix`` adalah atau diawali nama keluarga dua kanji atau lebih (鈴木大 di 鈴木大輝)."""
    surnames = data.surnames()
    return prefix in surnames or any(prefix[:size] in surnames
                                     for size in range(2, len(prefix)))


def verb_run_before_honorific(
    run: str, hon: str, after: str = "", not_names: frozenset[str] = frozenset(), *,
    before: str = "", named: frozenset[str] = frozenset(),
) -> bool:
    """Apakah run kanji + ``hon`` sebenarnya (kata lain +) kata kerja + okurigana + ん.

    Satu aturan konteks (``VERB_CONTEXT_TABLE``). Syarat awal: kanji terakhir run adalah
    batang kata kerja di ``data.VERB_STEMS`` untuk okurigana honorifik itu (歩 + くん = 歩く + ん,
    待 + たん = 待たん, 許 + さん = 許さん), dan konteks sesudahnya tidak pasti nama
    (``_after_kind``: 乾くんが, 巻くんっ, 治さんは). Lalu:

    - run satu kanji: jenis konteks sebelumnya (``_before_kind``) x jenis konteks sesudahnya
      dibandingkan dengan tingkat nama kanji itu (``_name_level``);
    - run lebih panjang: nama bila run dikenal, terbukti (``named``), diawali nama keluarga
      (鈴木大輝), atau diawali satu kanji yang bukan ``not_names`` (大輝, 雅行, 英治: kanji awal
      nama). Awalan lain adalah kata keterangan/argumen tanpa partikel (明日行くん, 来週行くんだ,
      東京行くんだ, 毎朝歩くんだ, 絶対渡さん) dan dinilai seperti konteks kasus.

    Args:
        run: Run kanji tepat sebelum honorifik.
        hon: Honorifik yang cocok.
        after: Teks sesudah honorifik (beberapa huruf; kosong berarti akhir teks).
        not_names: Kata yang bukan nama diri (``ner.NOT_NAMES``).
        before: Teks tepat sebelum run (beberapa huruf; kosong berarti awal teks).
        named: Tulisan yang terbukti nama di dokumen ini atau berbacaan.
    """
    if not run or len(hon) < 2 or not hon.endswith("ん"):
        return False
    okurigana = hon[:-1]
    if run[-1] not in data.VERB_STEMS.get(okurigana, frozenset()):
        return False
    after_kind = _after_kind(okurigana, after)
    if after_kind is None or _denies_identity(after):
        return False
    prefix = run[:-1]
    if not prefix:
        before_kind = _inverted_kind(before, after, _before_kind(before, run[-1] + okurigana))
    elif (run in named or is_known_name(run) or _surname_head(prefix)
          or (len(prefix) == 1 and prefix not in not_names)):
        return False
    else:
        before_kind = BEFORE_CASE
    return VERB_CONTEXT_TABLE[before_kind][after_kind] >= _name_level(run[-1], named)

''')

MODUL['jptrans.engines'] = (
    True,
r'''"""Registri mesin penerjemah.

``build_engines`` mengubah daftar nama di config menjadi objek mesin yang
siap dipakai, dengan urutan yang sama, dan melewati mesin yang tidak
tersedia (key belum diset, endpoint tidak resmi belum diizinkan).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from ..config import Config
from ..errors import ConfigError
from .base import Engine, env_value
from .deepl import DeepLEngine
from .fake import REPLIES_ENV, FakeEngine, load_replies, replies_tag
from .google import GoogleEngine
from .libretranslate import LibreTranslateEngine
from .llm import LLMEngine
from .mymemory import MyMemoryEngine

logger = logging.getLogger(__name__)

__all__ = [
    "DeepLEngine",
    "ENGINE_FACTORIES",
    "Engine",
    "FakeEngine",
    "GoogleEngine",
    "LLMEngine",
    "LibreTranslateEngine",
    "MyMemoryEngine",
    "build_engines",
    "describe_engines",
    "normalize_engine_names",
    "register_engine",
]


def _make_fake(_cfg: Config) -> Engine:
    """``FakeEngine``; dengan ``JPTRANS_FAKE_REPLIES`` memakai jawaban berskrip dari berkas.

    Jawaban berskrip mendapat tag cache sendiri (``replies_tag``), jadi tidak tertukar
    dengan gema bawaan yang sudah ada di cache.

    Raises:
        ConfigError: Berkas jawaban tidak sah (``load_replies``).
    """
    path = env_value(REPLIES_ENV)
    if not path:
        return FakeEngine()
    replies = load_replies(path)
    return FakeEngine(translations=replies, tag=replies_tag(replies))


ENGINE_FACTORIES: dict[str, Callable[[Config], Engine]] = {
    "fake": _make_fake,
    "mymemory": MyMemoryEngine,
    "google": GoogleEngine,
    "deepl": DeepLEngine,
    "llm": LLMEngine,
    "libretranslate": LibreTranslateEngine,
}

NO_ENGINE_HINT = (
    "set DEEPL_API_KEY atau JPTRANS_LLM_API_KEY/GEMINI_API_KEY, pakai --engine mymemory, "
    "atau izinkan Google tidak resmi dengan --allow-unofficial"
)


def build_engines(cfg: Config, names: Sequence[str] | None = None) -> list[Engine]:
    """Buat daftar mesin yang tersedia sesuai urutan yang diminta.

    Args:
        cfg: Konfigurasi program.
        names: Nama mesin; ``None`` berarti ``cfg.engines``. Nama ganda dibuang.

    Returns:
        Mesin yang ``available()``-nya benar, urut sesuai ``names``.

    Raises:
        ConfigError: Ada nama tak dikenal, daftar kosong, atau tidak ada
            satu pun mesin yang tersedia.
    """
    wanted = normalize_engine_names(cfg.engines if names is None else names)
    engines = []
    for name in wanted:
        engine = ENGINE_FACTORIES[name](cfg)
        ok, reason = engine.available()
        if ok:
            logger.debug("mesin %s dipakai: %s", name, reason)
            engines.append(engine)
        else:
            logger.info("mesin %s dilewati: %s", name, reason)
    if not engines:
        raise ConfigError(f"tidak ada mesin yang tersedia ({', '.join(wanted)}); {NO_ENGINE_HINT}")
    return engines


def describe_engines(cfg: Config) -> list[tuple[str, bool, str]]:
    """Status semua mesin terdaftar, untuk perintah ``doctor``.

    Args:
        cfg: Konfigurasi program.

    Returns:
        Daftar ``(nama, tersedia, alasan)`` untuk setiap mesin di registri.
    """
    return [(name, *factory(cfg).available()) for name, factory in ENGINE_FACTORIES.items()]


def normalize_engine_names(names: Sequence[str]) -> list[str]:
    """Rapikan daftar nama mesin: tanpa spasi tepi, huruf kecil, tanpa duplikat.

    Dipakai ``build_engines``, ``pipeline.estimate`` (``--dry-run``), dan
    server agar ketiganya menerima dan menolak nama yang sama.

    Args:
        names: Nama mesin dari CLI, config, atau permintaan web.

    Returns:
        Nama terdaftar, urutan pertama dipertahankan.

    Raises:
        ConfigError: Daftar kosong atau ada nama yang tidak dikenal.
    """
    wanted = list(dict.fromkeys(name.strip().lower() for name in names if name.strip()))
    if not wanted:
        raise ConfigError("daftar mesin kosong")
    unknown = [name for name in wanted if name not in ENGINE_FACTORIES]
    if unknown:
        raise ConfigError(
            f"mesin tidak dikenal: {', '.join(unknown)}; pilihan: {', '.join(ENGINE_FACTORIES)}"
        )
    return wanted


def register_engine(name: str, factory: Callable[[Config], Engine]) -> None:
    """Daftarkan mesin penerjemah kustom ke registri global ``ENGINE_FACTORIES``."""
    clean = name.strip().lower()
    if not clean or not all(ch.isalnum() or ch in "-_" for ch in clean):
        raise ConfigError(f"nama mesin tidak sah: {name!r}")
    if not callable(factory):
        raise ConfigError(f"factory mesin {clean!r} harus dapat dipanggil")
    ENGINE_FACTORIES[clean] = factory
    logger.debug("mesin kustom terdaftar: %s", clean)
''')

MODUL['jptrans.engines.base'] = (
    False,
r'''"""Kontrak bersama semua mesin penerjemah dan fungsi bantu kecilnya.

Mesin hanya menerjemahkan daftar teks yang sudah dimasking. Tangga
fallback (batch, per kalimat, presubstitusi, mesin berikutnya) milik
``pipeline.py``, sehingga tiap mesin tetap kecil dan mudah diuji.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from ..errors import EngineError

logger = logging.getLogger(__name__)


@runtime_checkable
class Engine(Protocol):
    """Antarmuka yang dipenuhi setiap mesin penerjemah.

    Attributes:
        name: Nama pendek mesin (``mymemory``, ``google``, ``deepl``, ``llm``, ``fake``).
        max_chars: Batas karakter per permintaan.
        max_items: Batas kalimat per permintaan (1 berarti tanpa batching).
    """

    name: str
    max_chars: int
    max_items: int

    def cache_tag(self) -> str:
        """Penanda versi mesin yang masuk ke kunci cache."""
        ...

    def available(self) -> tuple[bool, str]:
        """Kembalikan (bisa dipakai?, alasan singkat untuk pengguna)."""
        ...

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Terjemahkan ``texts``; hasil wajib sepanjang masukan.

        Args:
            texts: Kalimat termasking.
            src: Kode bahasa sumber (``ja``).
            tgt: Kode bahasa sasaran (``id`` atau ``en``).
            hints: Baris glosarium untuk mesin yang bisa memakainya (LLM).

        Raises:
            EngineError: Permintaan gagal atau jumlah hasil tidak cocok.
        """
        ...


def require_same_length(engine: str, texts: Sequence[str], results: Sequence[str]) -> list[str]:
    """Pastikan mesin mengembalikan satu hasil untuk tiap masukan.

    Args:
        engine: Nama mesin untuk pesan galat.
        texts: Masukan yang dikirim.
        results: Hasil dari mesin.

    Returns:
        ``results`` sebagai list.

    Raises:
        EngineError: Panjang keduanya berbeda.
    """
    if len(results) != len(texts):
        raise EngineError(engine, f"mengembalikan {len(results)} hasil untuk {len(texts)} teks")
    return list(results)


def lang_code(engine: str, codes: Mapping[str, str], lang: str) -> str:
    """Terjemahkan kode bahasa jptrans ke kode milik layanan.

    Args:
        engine: Nama mesin untuk pesan galat.
        codes: Pemetaan kode jptrans ke kode layanan.
        lang: Kode jptrans (``ja``, ``id``, ``en``).

    Returns:
        Kode bahasa versi layanan.

    Raises:
        EngineError: Bahasa tidak didukung mesin ini.
    """
    try:
        return codes[lang]
    except KeyError as exc:
        raise EngineError(engine, f"bahasa {lang!r} tidak didukung") from exc


def env_value(*names: str) -> str:
    """Ambil nilai environment variable pertama yang tidak kosong.

    Key dibaca langsung dari environment, tidak pernah dari berkas config.

    Args:
        *names: Nama variabel, urut prioritas.

    Returns:
        Nilai tanpa spasi tepi, atau string kosong.
    """
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""
''')

MODUL['jptrans.engines.deepl'] = (
    False,
r'''"""Mesin DeepL API (Free atau Pro) lewat ``POST /v2/translate``.

Key dibaca dari ``DEEPL_API_KEY``. Key berakhiran ``:fx`` milik paket Free
(500.000 karakter per bulan) dan memakai host ``api-free.deepl.com``.
Format permintaan (dicek di developers.deepl.com, 2026-11-15)::

    POST /v2/translate
    Authorization: DeepL-Auth-Key <key>
    {"text": ["...", "..."], "source_lang": "JA", "target_lang": "ID"}

    -> {"translations": [{"detected_source_language": "JA", "text": "..."}]}

Penanda ``[[E1]]`` dikirim apa adanya, sama seperti di mesin lain. Status
456 (kuota habis) dipetakan ``net.py`` menjadi ``QuotaExceeded``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..config import Config
from ..errors import EngineError, EngineUnavailable
from ..net import post_json
from .base import env_value, lang_code, require_same_length

logger = logging.getLogger(__name__)

KEY_ENV = "DEEPL_API_KEY"
FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"
SOURCE_CODES = {"ja": "JA"}
TARGET_CODES = {"id": "ID", "en": "EN-US"}


class DeepLEngine:
    """Penerjemah DeepL dengan batch hingga 50 kalimat per permintaan.

    Args:
        cfg: Konfigurasi program (saat ini tidak ada opsi khusus).
        api_key: Key eksplisit; bawaan dibaca dari ``DEEPL_API_KEY``.
    """

    name = "deepl"
    max_chars = 30000
    max_items = 50

    def __init__(self, cfg: Config | None = None, *, api_key: str | None = None) -> None:
        self._key = env_value(KEY_ENV) if api_key is None else api_key.strip()

    @property
    def endpoint(self) -> str:
        """URL ``/v2/translate`` yang sesuai jenis key."""
        return FREE_URL if self._key.endswith(":fx") else PRO_URL

    def cache_tag(self) -> str:
        """Kembalikan ``"deepl:v2"``."""
        return "deepl:v2"

    def available(self) -> tuple[bool, str]:
        """Tersedia bila ``DEEPL_API_KEY`` diset."""
        if not self._key:
            return False, f"{KEY_ENV} belum diset (daftar DeepL API Free: 500.000 karakter/bulan)"
        plan = "Free" if self._key.endswith(":fx") else "Pro"
        return True, f"key DeepL API {plan}"

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Terjemahkan satu batch dalam satu permintaan.

        Raises:
            EngineUnavailable: Key tidak ada atau ditolak.
            QuotaExceeded: Kuota bulanan habis (456).
            EngineError: Bahasa tidak didukung atau respons tidak sah.
        """
        if not self._key:
            raise EngineUnavailable(self.name, f"{KEY_ENV} belum diset")
        payload = {
            "text": list(texts),
            "source_lang": lang_code(self.name, SOURCE_CODES, src),
            "target_lang": lang_code(self.name, TARGET_CODES, tgt),
        }
        headers = {"Authorization": f"DeepL-Auth-Key {self._key}"}
        data = post_json(self.endpoint, payload, headers=headers, engine=self.name)
        return require_same_length(self.name, texts, parse_response(data))


def parse_response(data: Any) -> list[str]:
    """Ambil daftar terjemahan dari respons DeepL.

    Args:
        data: Objek JSON yang sudah diurai.

    Returns:
        Teks terjemahan, urut sesuai masukan.

    Raises:
        EngineError: Struktur ``translations`` tidak sesuai.
    """
    items = data.get("translations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise EngineError(DeepLEngine.name, "respons tanpa daftar 'translations'")
    texts = [item.get("text") if isinstance(item, dict) else None for item in items]
    if not all(isinstance(text, str) for text in texts):
        raise EngineError(DeepLEngine.name, "ada terjemahan tanpa teks")
    return texts
''')

MODUL['jptrans.engines.fake'] = (
    False,
r'''"""Mesin palsu yang deterministik, untuk tes dan demo tanpa jaringan.

Mesin ini tidak menerjemahkan apa pun. Secara bawaan ia hanya memberi
awalan pada teks dan membiarkan penanda ``[[E#]]`` utuh, sehingga hasil
akhir pipeline bisa diperiksa dengan pasti. Opsi lain meniru kelakuan
buruk mesin sungguhan: penanda hilang, urutan penanda berubah, atau galat.

Untuk menguji lewat CLI tanpa jaringan, ``--engine fake`` bisa diberi jawaban
berskrip dari berkas JSON ``{teks termasking: jawaban}`` yang ditunjuk
``JPTRANS_FAKE_REPLIES`` (``load_replies``). Jawaban berskrip diperlakukan
seperti jawaban mesin sungguhan (misalnya diperiksa sisa huruf Jepangnya) dan
disimpan di cache dengan tag sendiri (``replies_tag``), jadi tidak tertukar
dengan gema bawaan walau cache tidak dimatikan.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..errors import ConfigError
from ..protect import EXACT_TOKEN_RE, TOKEN_TEMPLATE

logger = logging.getLogger(__name__)

REPLIES_ENV = "JPTRANS_FAKE_REPLIES"
"""Variabel lingkungan berisi jalur berkas JSON jawaban berskrip untuk ``--engine fake``."""


@dataclass(frozen=True)
class FakeCall:
    """Rekaman satu panggilan ``FakeEngine.translate``."""

    texts: tuple[str, ...]
    src: str
    tgt: str
    hints: tuple[str, ...]


class FakeEngine:
    """Mesin uji yang hasilnya bisa ditebak.

    Args:
        prefix: Awalan tiap hasil; ``{tgt}`` diganti kode bahasa sasaran.
        drop_tokens: Nomor penanda yang dihapus dari hasil (menguji fallback).
        shuffle: Balik urutan penanda di tiap hasil (menguji restore berbasis ID).
        fail_with: Galat yang dilempar pada setiap panggilan.
        translations: Jawaban tetap ``{teks masukan: hasil}``; mengalahkan ``prefix``.
        tag: Tag cache pengganti ``"fake"`` (``replies_tag`` untuk jawaban berskrip CLI).

    Attributes:
        calls: Daftar ``FakeCall`` untuk asersi di tes.
        echoes_source: ``True``: gema bawaan (awalan + teks Jepang masukan, lihat
            ``echo``) sengaja memuat huruf Jepang, jadi pipeline tidak
            menganggap gema itu terjemahan bersisa (``residue.residue_letters``).
            Hanya keluaran yang sama persis dengan ``echo`` yang dibebaskan;
            jawaban ``translations`` dan jawaban cache lain tetap diperiksa.
            Subkelas yang meniru mesin sungguhan bisa mengubahnya menjadi ``False``.
    """

    name = "fake"
    echoes_source = True
    max_chars = 2000
    max_items = 50

    def __init__(
        self,
        prefix: str = "⟪{tgt}⟫ ",
        drop_tokens: Iterable[int] = (),
        shuffle: bool = False,
        fail_with: BaseException | None = None,
        translations: Mapping[str, str] | None = None,
        tag: str = "",
    ) -> None:
        """Siapkan mesin palsu.

        Args:
            prefix: Awalan gema; ``{tgt}`` diganti kode bahasa sasaran.
            drop_tokens: Nomor penanda yang dibuang dari setiap hasil.
            shuffle: Balik urutan penanda di setiap hasil (``reverse_tokens``).
            fail_with: Galat yang dilempar ``translate`` sebelum menjawab.
            translations: Jawaban tetap per teks masukan; teks lain digemakan.
            tag: Tag cache (lihat ``cache_tag``); kosong berarti ``"fake"``.
        """
        self.prefix = prefix
        self.drop_tokens = frozenset(drop_tokens)
        self.shuffle = shuffle
        self.fail_with = fail_with
        self.translations = dict(translations or {})
        self.tag = tag
        self.calls: list[FakeCall] = []

    def cache_tag(self) -> str:
        """Kembalikan ``tag`` bila diisi, selain itu ``"fake"``.

        ``translations`` yang diisi lewat kode tidak mengubah tag: di tes, jawaban itu
        meniru satu mesin yang sama di beberapa jalan (cache harus tetap kena). Jawaban
        berskrip dari ``JPTRANS_FAKE_REPLIES`` memakai tag sendiri (``replies_tag``).
        """
        return self.tag or self.name

    def available(self) -> tuple[bool, str]:
        """Selalu tersedia."""
        return True, "mesin uji deterministik tanpa jaringan"

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Kembalikan hasil palsu untuk tiap teks dan catat panggilannya.

        Raises:
            BaseException: ``fail_with`` bila diisi.
        """
        self.calls.append(FakeCall(tuple(texts), src, tgt, tuple(hints)))
        if self.fail_with is not None:
            raise self.fail_with
        return [self._fake_one(text, tgt) for text in texts]

    def echo(self, text: str, tgt: str) -> str:
        """Gema bawaan untuk ``text``: awalan + teks, setelah ``shuffle``/``drop_tokens``.

        Args:
            text: Teks masukan (termasking).
            tgt: Kode bahasa sasaran.

        Returns:
            Keluaran yang akan diberikan ``translate`` bila ``text`` tidak ada di
            ``translations``.
        """
        return self._distort(self.prefix.format(tgt=tgt) + text)

    def _fake_one(self, text: str, tgt: str) -> str:
        """Jawaban untuk satu teks: ``translations`` bila ada, selain itu gema ``echo``."""
        result = self.translations.get(text)
        if result is None:
            return self.echo(text, tgt)
        return self._distort(result)

    def _distort(self, result: str) -> str:
        """Terapkan ``shuffle`` dan ``drop_tokens`` ke satu hasil."""
        if self.shuffle:
            result = reverse_tokens(result)
        if self.drop_tokens:
            result = EXACT_TOKEN_RE.sub(
                lambda m: "" if int(m.group(1)) in self.drop_tokens else m.group(0), result
            )
        return result


def reverse_tokens(text: str) -> str:
    """Balik urutan penanda ``[[E#]]`` di dalam teks, sisanya tetap.

    Args:
        text: Teks berpenanda.

    Returns:
        Teks dengan penanda pertama bertukar tempat dengan yang terakhir, dst.
    """
    tokens = iter(reversed(EXACT_TOKEN_RE.findall(text)))
    return EXACT_TOKEN_RE.sub(lambda _m: TOKEN_TEMPLATE.format(next(tokens)), text)


def replies_tag(replies: Mapping[str, str]) -> str:
    """Tag cache untuk jawaban berskrip: ``fake+<12 heksa SHA-256 isi jawaban>``.

    Gema bawaan (tag ``"fake"``) dan tiap isi berkas jawaban punya ruang cache
    sendiri, jadi jawaban berskrip tidak tertutup gema yang sudah ada di cache dan
    tidak menetap di cache gema bawaan.

    Args:
        replies: Jawaban berskrip dari ``load_replies``.

    Returns:
        Tag cache.
    """
    payload = json.dumps(dict(replies), ensure_ascii=False, sort_keys=True)
    return f"{FakeEngine.name}+{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def load_replies(path: str | Path) -> dict[str, str]:
    """Baca jawaban berskrip ``{teks termasking: jawaban}`` untuk ``FakeEngine``.

    Isi berkas adalah data uji, bukan instruksi: hanya objek JSON berisi
    pasangan string yang diterima.

    Args:
        path: Berkas JSON (UTF-8).

    Returns:
        Peta teks masukan ke jawaban.

    Raises:
        ConfigError: Berkas tidak bisa dibaca, bukan JSON, atau bukan objek string ke string.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ConfigError(f"{REPLIES_ENV}: berkas {path} tidak bisa dibaca: {exc}") from exc
    if not isinstance(data, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in data.items()):
        raise ConfigError(f"{REPLIES_ENV}: {path} harus berisi objek JSON "
                          "{\"teks termasking\": \"jawaban\"}")
    logger.info("mesin fake memakai %d jawaban berskrip dari %s", len(data), REPLIES_ENV)
    return data
''')

MODUL['jptrans.engines.google'] = (
    False,
r'''"""Mesin Google Translate lewat endpoint TIDAK resmi ``translate_a/single``.

Peringatan yang juga ditampilkan di log saat mesin diaktifkan:

- Endpoint ini tidak didokumentasikan Google dan bisa berubah atau
  diblokir kapan saja (status 429 atau halaman captcha HTML).
- ``https://translate.googleapis.com/robots.txt`` berisi
  ``Disallow: /translate_a/``, dan Google Terms melarang akses otomatis
  yang melanggar instruksi semacam itu.

Karena itu mesin ini mati secara bawaan dan hanya hidup dengan
``allow_unofficial`` (``--allow-unofficial``). User-Agent tetap jujur.

Beberapa kalimat dikirim sekaligus, digabung dengan ``\\n``. Hasil dipecah
kembali per baris; bila jumlah baris berbeda, ``EngineError`` dilempar
agar pipeline mengulang per kalimat.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..config import Config
from ..errors import EngineError, EngineUnavailable
from ..net import parse_json, post_form
from .base import require_same_length

logger = logging.getLogger(__name__)

ENDPOINT = "https://translate.googleapis.com/translate_a/single"
UNOFFICIAL_NOTE = (
    "endpoint Google tidak resmi (robots.txt: Disallow: /translate_a/), bisa berhenti kapan saja"
)


class GoogleEngine:
    """Penerjemah lewat ``translate_a/single?client=gtx`` (opt-in).

    Args:
        cfg: Konfigurasi; mesin hanya hidup bila ``cfg.allow_unofficial``.
    """

    name = "google"
    max_chars = 1500
    max_items = 40

    def __init__(self, cfg: Config) -> None:
        self._allowed = cfg.allow_unofficial
        if self._allowed:
            logger.warning("google: memakai %s", UNOFFICIAL_NOTE)

    def cache_tag(self) -> str:
        """Kembalikan ``"google:gtx"``."""
        return "google:gtx"

    def available(self) -> tuple[bool, str]:
        """Tersedia hanya bila pengguna mengizinkan endpoint tidak resmi."""
        if not self._allowed:
            return False, f"{UNOFFICIAL_NOTE}; aktifkan dengan --allow-unofficial"
        return True, UNOFFICIAL_NOTE

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Terjemahkan satu batch dalam satu permintaan POST.

        Teks yang sendiri berisi baris baru (misalnya subtitle dua baris)
        tidak bisa dipecah ulang dengan aman, jadi batch seperti itu
        dikirim satu per satu.

        Raises:
            EngineUnavailable: ``allow_unofficial`` mati.
            EngineError: Respons bukan JSON, struktur aneh, atau jumlah baris beda.
        """
        if not self._allowed:
            raise EngineUnavailable(self.name, "endpoint tidak resmi belum diizinkan")
        if len(texts) > 1 and any("\n" in text for text in texts):
            logger.debug("google: batch berisi baris baru, dikirim per teks")
            return [self._request(text, src, tgt) for text in texts]
        if len(texts) == 1:
            return [self._request(texts[0], src, tgt)]
        joined = self._request("\n".join(texts), src, tgt)
        return require_same_length(self.name, texts, joined.split("\n"))

    def _request(self, text: str, src: str, tgt: str) -> str:
        fields = {"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text}
        raw = post_form(ENDPOINT, fields, engine=self.name)
        return extract_text(parse_json(raw, self.name))


def extract_text(data: Any) -> str:
    """Gabungkan segmen terjemahan dari respons gtx.

    Bentuk respons: ``[[["terjemahan", "asli", ...], ...], null, "ja", ...]``.

    Args:
        data: Objek JSON yang sudah diurai.

    Returns:
        Terjemahan utuh.

    Raises:
        EngineError: Struktur tidak sesuai atau terjemahan kosong.
    """
    try:
        pieces = [segment[0] for segment in data[0] if segment and isinstance(segment[0], str)]
    except (TypeError, IndexError, KeyError) as exc:
        raise EngineError(GoogleEngine.name, "struktur respons tidak dikenal") from exc
    text = "".join(pieces)
    if not text.strip():
        raise EngineError(GoogleEngine.name, "terjemahan kosong")
    return text
''')

MODUL['jptrans.engines.libretranslate'] = (
    False,
r'''"""Mesin LibreTranslate lewat ``POST {base_url}/translate``.

Mendukung server LibreTranslate mandiri (lokal) maupun instans daring.
Alamat dibaca dari ``LIBRETRANSLATE_URL`` dan kunci opsional dari
``LIBRETRANSLATE_API_KEY``; kunci ditolak bila dikirim lewat HTTP polos
ke host selain localhost.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from ..config import Config
from ..errors import EngineError, EngineUnavailable
from ..net import post_json
from .base import env_value, lang_code, require_same_length
from .llm import LOCAL_HOSTS

logger = logging.getLogger(__name__)

URL_ENV = "LIBRETRANSLATE_URL"
KEY_ENV = "LIBRETRANSLATE_API_KEY"
LANG_CODES = {"ja": "ja", "id": "id", "en": "en"}
INSECURE_KEY_MESSAGE = (
    "LIBRETRANSLATE_URL harus https untuk mengirim API key ke server bukan lokal"
)


class LibreTranslateEngine:
    """Penerjemah LibreTranslate dengan dukungan batch daftar teks."""

    name = "libretranslate"
    max_chars = 5000
    max_items = 25

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        raw_url = env_value(URL_ENV) if base_url is None else base_url.strip()
        self.base_url = raw_url.rstrip("/")
        self._key = env_value(KEY_ENV) if api_key is None else api_key.strip()
        parts = urlsplit(self.base_url) if self.base_url else None
        self._host = (parts.hostname or "").lower() if parts else ""
        self._scheme = parts.scheme.lower() if parts else ""

    @property
    def endpoint(self) -> str:
        """URL ``/translate`` lengkap."""
        return f"{self.base_url}/translate"

    @property
    def is_local(self) -> bool:
        return self._host in LOCAL_HOSTS

    @property
    def key_exposed(self) -> bool:
        return bool(self._key) and self._scheme != "https" and not self.is_local

    def cache_tag(self) -> str:
        """Penanda cache per host LibreTranslate."""
        return f"{self.name}:{self._host or 'default'}"

    def available(self) -> tuple[bool, str]:
        """Tersedia bila ``LIBRETRANSLATE_URL`` diset dengan aman."""
        if not self.base_url:
            return False, f"{URL_ENV} belum diset"
        if self._scheme not in {"http", "https"} or not self._host:
            return False, f"{URL_ENV} tidak valid"
        if self.key_exposed:
            return False, INSECURE_KEY_MESSAGE
        return True, f"endpoint {self._host}"

    def translate(
        self,
        texts: list[str],
        src: str,
        tgt: str,
        hints: Sequence[str] = (),
    ) -> list[str]:
        """Terjemahkan daftar teks dalam satu panggilan ``/translate``."""
        ok, reason = self.available()
        if not ok:
            raise EngineUnavailable(self.name, reason)
        payload: dict[str, Any] = {
            "q": texts[0] if len(texts) == 1 else list(texts),
            "source": lang_code(self.name, LANG_CODES, src),
            "target": lang_code(self.name, LANG_CODES, tgt),
            "format": "text",
        }
        if self._key:
            payload["api_key"] = self._key
        data = post_json(self.endpoint, payload, engine=self.name)
        return require_same_length(self.name, texts, parse_response(data))


def parse_response(data: Any) -> list[str]:
    """Ambil hasil terjemahan tunggal atau daftar dari respons LibreTranslate."""
    translated = (
        data.get("translatedText") if isinstance(data, dict) else None
    )
    if isinstance(translated, str):
        return [translated]
    if isinstance(translated, list) and all(
        isinstance(item, str) for item in translated
    ):
        return list(translated)
    raise EngineError(
        LibreTranslateEngine.name,
        "respons tanpa 'translatedText' yang sah",
    )
''')

MODUL['jptrans.engines.llm'] = (
    False,
r'''"""Mesin LLM lewat endpoint OpenAI-compatible ``{base_url}/chat/completions``.

Satu kelas melayani Gemini, Groq, OpenRouter, OpenAI, dan Ollama; kunci API
dipilih otomatis berdasarkan host agar kunci satu penyedia tidak terkirim ke
penyedia lain, dan server lokal boleh berjalan tanpa kunci API.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from ..config import DEFAULT_LLM_MODEL, Config
from ..errors import EngineError, EngineUnavailable
from ..net import http_status, post_json
from .base import env_value, lang_code

logger = logging.getLogger(__name__)

PROMPT_VERSION = "p1"
KEY_ENV = "JPTRANS_LLM_API_KEY"
PROVIDER_KEY_ENVS = {
    "generativelanguage.googleapis.com": "GEMINI_API_KEY",
    "api.groq.com": "GROQ_API_KEY",
    "openrouter.ai": "OPENROUTER_API_KEY",
    "api.openai.com": "OPENAI_API_KEY",
}
PROVIDER_DEFAULT_MODELS = {
    "generativelanguage.googleapis.com": "gemini-2.5-flash",
    "api.groq.com": "llama-3.3-70b-versatile",
    "openrouter.ai": "google/gemini-2.5-flash",
    "api.openai.com": "gpt-4o-mini",
}
LOCAL_DEFAULT_MODEL = "qwen2.5:7b"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
LANG_NAMES = {"ja": "Japanese", "id": "Indonesian", "en": "English"}
TIMEOUT = 90.0
JSON_RESPONSE_FORMAT = {"type": "json_object"}
INSECURE_KEY_MESSAGE = (
    "llm_base_url harus https untuk mengirim API key ke server bukan lokal"
)

SYSTEM_PROMPT = """\
You translate Japanese novels, manga and documents into {target}, in the style \
of a careful fansub or subtitle team: natural, faithful to tone and register, \
never summarised.
Rules:
1. Tokens such as [[E1]] or [[E2]] stand for protected names and terms. Copy \
every token exactly as written, once each. Never translate, explain, reorder \
inside, or drop a token.
2. Honorifics and titles are already inside the tokens, so do not add words \
like Mr., Tuan, Pak or -san around them. The glossary only tells you what \
each token refers to.
3. Translate every input item on its own. Do not merge, split, add or remove \
items, and keep line breaks inside an item.
4. Reply with one JSON object and nothing else: \
{{"translations": [{{"id": 1, "text": "..."}}]}} using exactly the input ids."""

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", re.DOTALL | re.IGNORECASE
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


def resolve_model_for_host(model: str, host: str) -> str:
    """Pilih model bawaan yang cocok dengan ``host`` bila pengguna memakai bawaan."""
    if model != DEFAULT_LLM_MODEL:
        return model
    if host in LOCAL_HOSTS:
        return LOCAL_DEFAULT_MODEL
    return PROVIDER_DEFAULT_MODELS.get(host, model)


class LLMEngine:
    """Penerjemah berbasis LLM dengan glosarium terstruktur di prompt."""

    name = "llm"
    max_chars = 4000
    max_items = 25
    uses_hints = True

    def __init__(self, cfg: Config, *, api_key: str | None = None) -> None:
        self.base_url = cfg.llm_base_url.rstrip("/")
        parts = urlsplit(self.base_url)
        self._host = (parts.hostname or "").lower()
        self._scheme = parts.scheme.lower()
        self.model = resolve_model_for_host(cfg.llm_model, self._host)
        self._key = (
            find_api_key(self._host) if api_key is None else api_key.strip()
        )

    @property
    def endpoint(self) -> str:
        """URL ``chat/completions`` lengkap."""
        return f"{self.base_url}/chat/completions"

    @property
    def is_local(self) -> bool:
        """``True`` bila server berjalan di komputer lokal (mis. Ollama)."""
        return self._host in LOCAL_HOSTS

    def cache_tag(self) -> str:
        """Kembalikan penanda unik ``llm:<host>:<model>:<versi prompt>``."""
        host_tag = self._host or "default"
        return f"{self.name}:{host_tag}:{self.model}:{PROMPT_VERSION}"

    @property
    def key_exposed(self) -> bool:
        """``True`` bila kunci akan terkirim tanpa TLS ke server bukan lokal."""
        return bool(self._key) and self._scheme != "https" and not self.is_local

    def available(self) -> tuple[bool, str]:
        """Tersedia bila ada kunci API yang cocok (lewat HTTPS), atau server lokal."""
        if self.key_exposed:
            return False, INSECURE_KEY_MESSAGE
        if self._key or self.is_local:
            return True, f"model {self.model} di {self._host or self.base_url}"
        provider_env = PROVIDER_KEY_ENVS.get(self._host)
        hint = f"{KEY_ENV} atau {provider_env}" if provider_env else KEY_ENV
        return False, f"{hint} belum diset untuk {self._host or self.base_url}"

    def translate(
        self,
        texts: list[str],
        src: str,
        tgt: str,
        hints: Sequence[str] = (),
    ) -> list[str]:
        """Terjemahkan satu batch kalimat dalam satu panggilan chat."""
        if self.key_exposed:
            raise EngineUnavailable(self.name, INSECURE_KEY_MESSAGE)
        if not (self._key or self.is_local):
            raise EngineUnavailable(self.name, f"{KEY_ENV} belum diset")
        payload = build_payload(self.model, texts, src, tgt, hints)
        try:
            data = self._post(payload)
        except EngineError as exc:
            if http_status(exc) != 400:
                raise
            logger.info(
                "llm: server menolak response_format (400), diulang tanpa field itu"
            )
            fallback = {
                key: value
                for key, value in payload.items()
                if key != "response_format"
            }
            try:
                data = self._post(fallback)
            except EngineError as retry_exc:
                if http_status(retry_exc) == 400:
                    raise EngineUnavailable(
                        self.name, str(retry_exc)
                    ) from retry_exc
                raise
        return parse_translations(message_content(data), len(texts))

    def _post(self, payload: dict[str, Any]) -> Any:
        headers = (
            {"Authorization": f"Bearer {self._key}"} if self._key else {}
        )
        return post_json(
            self.endpoint,
            payload,
            headers=headers,
            timeout=TIMEOUT,
            engine=self.name,
        )


def find_api_key(host: str) -> str:
    """Cari kunci API LLM di environment yang cocok dengan ``host``."""
    provider_env = PROVIDER_KEY_ENVS.get(host)
    return (
        env_value(KEY_ENV, provider_env)
        if provider_env
        else env_value(KEY_ENV)
    )


def sanitize_hint_line(line: str) -> str:
    """Bersihkan karakter kontrol dari baris petunjuk glosarium untuk LLM."""
    return _CONTROL_CHARS_RE.sub(" ", line).strip()[:240]


def build_payload(
    model: str,
    texts: Sequence[str],
    src: str,
    tgt: str,
    hints: Sequence[str] = (),
) -> dict[str, Any]:
    """Susun badan permintaan JSON ``chat/completions``."""
    lang_code(LLMEngine.name, LANG_NAMES, src)
    target = lang_code(LLMEngine.name, LANG_NAMES, tgt)
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(target=target)},
            {"role": "user", "content": build_user_message(texts, hints)},
        ],
        "response_format": JSON_RESPONSE_FORMAT,
    }


def build_user_message(
    texts: Sequence[str], hints: Sequence[str] = ()
) -> str:
    """Bentuk pesan pengguna berisi glosarium tersanitasi dan masukan JSON."""
    items = [
        {"id": index, "text": text} for index, text in enumerate(texts, start=1)
    ]
    parts: list[str] = []
    clean_hints = [
        cleaned for h in hints if (cleaned := sanitize_hint_line(h))
    ]
    if clean_hints:
        parts.append("Glossary:\n" + "\n".join(clean_hints))
    parts.append("Input:\n" + json.dumps(items, ensure_ascii=False))
    return "\n\n".join(parts)


def message_content(data: Any) -> str:
    """Ambil teks pesan asisten pertama dari respons ``chat/completions``."""
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (TypeError, KeyError, IndexError) as exc:
        raise EngineError(
            LLMEngine.name, "respons tanpa choices[0].message"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        raise EngineError(
            LLMEngine.name, f"jawaban kosong (finish_reason={reason})"
        )
    return content


def parse_translations(content: str, expected: int) -> list[str]:
    """Urai dan validasi jawaban JSON model terhadap jumlah masukan."""
    cleaned = _extract_json_text(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise EngineError(
            LLMEngine.name, f"jawaban bukan JSON ({len(content)} karakter)"
        ) from exc
    items = data.get("translations") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise EngineError(
            LLMEngine.name, "jawaban tanpa daftar 'translations'"
        )
    by_id: dict[int, str] = {}
    for item in items:
        item_id, text = _parse_item(item)
        if item_id in by_id:
            raise EngineError(LLMEngine.name, f"id {item_id} muncul dua kali")
        by_id[item_id] = text
    wanted = set(range(1, expected + 1))
    missing = sorted(wanted - by_id.keys())
    extra = sorted(by_id.keys() - wanted)
    if missing or extra:
        raise EngineError(
            LLMEngine.name, f"id tidak cocok: hilang {missing}, asing {extra}"
        )
    return [by_id[index] for index in range(1, expected + 1)]


def _parse_item(item: object) -> tuple[int, str]:
    if not isinstance(item, dict):
        raise EngineError(LLMEngine.name, "butir jawaban bukan objek")
    raw_id, text = item.get("id"), item.get("text")
    if isinstance(raw_id, str) and raw_id.strip().isdigit():
        raw_id = int(raw_id)
    if (
        isinstance(raw_id, bool)
        or not isinstance(raw_id, int)
        or not isinstance(text, str)
    ):
        raise EngineError(
            LLMEngine.name,
            "butir jawaban butuh 'id' bilangan dan 'text' string",
        )
    return raw_id, text


def _extract_json_text(content: str) -> str:
    stripped = _THINK_RE.sub("", content).strip()
    fence = _FENCE_RE.search(stripped)
    if fence is not None:
        return fence.group(1).strip()
    if stripped.startswith(("{", "[")):
        return stripped
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        return stripped[first_brace:last_brace + 1]
    return stripped
''')

MODUL['jptrans.engines.mymemory'] = (
    False,
r'''"""Mesin MyMemory: API resmi gratis tanpa key.

Batasnya kecil: 5.000 karakter per hari tanpa identitas (50.000 bila email
dikirim lewat ``de``) dan 500 karakter per permintaan. Server menghitung
batas itu per karakter, bukan per byte seperti tertulis di dokumentasinya,
jadi pemeriksaan memakai ``len(text)``. Satu permintaan berisi satu kalimat.

Bentuk respons (dicek 2026-11-15)::

    {"responseData": {"translatedText": "...", "match": 0.85},
     "quotaFinished": false, "responseDetails": "", "responseStatus": 200, ...}

``responseStatus`` kadang berupa string (``"403"``), jadi selalu diubah ke int.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..config import Config
from ..errors import EngineError, QuotaExceeded
from ..net import get_json
from .base import env_value

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mymemory.translated.net/get"
EMAIL_ENV = "MYMEMORY_EMAIL"
QUOTA_TEXT = "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"
QUOTA_STATUSES = frozenset({403, 429})
# Status 403 juga dipakai untuk galat masukan; pesan ini BUKAN tanda kuota habis.
NON_QUOTA_DETAILS = ("QUERY LENGTH LIMIT", "INVALID", "SELECT TWO DISTINCT LANGUAGES")


class MyMemoryEngine:
    """Penerjemah lewat ``api.mymemory.translated.net``.

    Args:
        cfg: Konfigurasi program (saat ini tidak ada opsi khusus).
        email: Email opsional untuk kuota lebih besar. Bawaan dibaca dari
            ``MYMEMORY_EMAIL``; tidak pernah dikirim bila tidak diset (opt-in),
            karena email itu sampai ke pihak ketiga.
    """

    name = "mymemory"
    max_chars = 500
    max_items = 1

    def __init__(self, cfg: Config | None = None, *, email: str | None = None) -> None:
        self._email = env_value(EMAIL_ENV) if email is None else email.strip()

    def cache_tag(self) -> str:
        """Kembalikan ``"mymemory"``."""
        return self.name

    def available(self) -> tuple[bool, str]:
        """Selalu tersedia; alasan menyebut kuota harian yang berlaku."""
        if self._email:
            return True, "tanpa key, dengan email (50.000 karakter/hari)"
        return True, "tanpa key (5.000 karakter/hari; set MYMEMORY_EMAIL untuk 50.000)"

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Terjemahkan tiap teks dengan satu permintaan per teks.

        Raises:
            QuotaExceeded: Kuota harian habis.
            EngineError: Teks terlalu panjang atau respons tidak sah.
        """
        return [self._translate_one(text, src, tgt) for text in texts]

    def _translate_one(self, text: str, src: str, tgt: str) -> str:
        if len(text) > self.max_chars:
            raise EngineError(self.name, f"teks {len(text)} karakter melebihi {self.max_chars}")
        params = {"q": text, "langpair": f"{src}|{tgt}"}
        if self._email:
            params["de"] = self._email
        return parse_response(get_json(ENDPOINT, params, engine=self.name))


def parse_response(data: Any) -> str:
    """Ambil terjemahan dari respons MyMemory yang sudah diurai.

    Args:
        data: Objek JSON dari ``/get``.

    Returns:
        Teks ``responseData.translatedText``.

    Raises:
        QuotaExceeded: ``responseStatus`` 429/403 (selain galat masukan),
            ``quotaFinished`` benar, atau teks peringatan kuota muncul.
        EngineError: Status selain 200, struktur aneh, atau terjemahan kosong.
    """
    if not isinstance(data, dict):
        raise EngineError(MyMemoryEngine.name, "struktur respons tidak dikenal")
    status = _status_code(data.get("responseStatus"))
    response_data = data.get("responseData")
    translated = response_data.get("translatedText") if isinstance(response_data, dict) else None
    translated = translated if isinstance(translated, str) else ""
    details = str(data.get("responseDetails") or "")
    if _is_quota_exhausted(status, data.get("quotaFinished"), translated, details):
        raise QuotaExceeded(MyMemoryEngine.name, f"kuota harian habis (status {status})")
    if status != 200:
        raise EngineError(MyMemoryEngine.name, f"responseStatus {status}: {details[:120]}")
    if not translated.strip():
        raise EngineError(MyMemoryEngine.name, "terjemahan kosong")
    return translated


def _is_quota_exhausted(status: int, finished: object, translated: str, details: str) -> bool:
    upper_details = details.upper()
    if QUOTA_TEXT in translated.upper() or QUOTA_TEXT in upper_details or finished is True:
        return True
    if status not in QUOTA_STATUSES:
        return False
    return not any(marker in upper_details for marker in NON_QUOTA_DETAILS)


def _status_code(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0
''')

MODUL['jptrans.errors'] = (
    False,
r'''"""Hierarki galat jptrans.

Semua galat yang sengaja dilempar program turun dari ``JptransError``.
CLI memetakan tiap jenis galat ke kode keluar yang berbeda, sehingga
skrip lain (misalnya cron atau batch) bisa membedakan "masukan salah"
dari "semua mesin penerjemah gagal".
"""

from __future__ import annotations

import logging

# Modul ini hanya mendefinisikan galat dan tidak menulis log sendiri (galat dicatat
# oleh pemanggilnya); logger tetap ada sesuai aturan proyek "satu logger per modul".
logger = logging.getLogger(__name__)

# Saran untuk Python yang sistem berkasnya bukan UTF-8 (Linux dengan locale C,
# PYTHONUTF8=0, dan PYTHONCOERCECLOCALE=0): nama berkas Jepang tidak bisa dipakai.
NON_UTF8_FS_HINT = (
    "sistem berkas Python ini tidak memakai UTF-8 sehingga nama berkas Jepang tidak "
    "bisa dipakai; jalankan dengan PYTHONUTF8=1 atau locale UTF-8 (mis. LANG=C.UTF-8)"
)


class JptransError(Exception):
    """Induk semua galat yang diketahui program ini."""

    exit_code = 1


class InputError(JptransError):
    """Berkas masukan tidak bisa dibaca: encoding, format, atau ber-DRM."""

    exit_code = 1


class ConfigError(JptransError):
    """Nilai konfigurasi atau argumen tidak valid."""

    exit_code = 2


class EngineError(JptransError):
    """Satu mesin penerjemah gagal memproses permintaan.

    Galat ini bersifat lokal: pipeline akan mencoba mesin berikutnya.
    """

    exit_code = 3

    def __init__(self, engine: str, message: str) -> None:
        super().__init__(f"[{engine}] {message}")
        self.engine = engine


class EngineUnavailable(EngineError):
    """Mesin tidak bisa dipakai sama sekali (tidak ada key, tidak diizinkan)."""


class QuotaExceeded(EngineError):
    """Kuota mesin habis. Mesin ini tidak dicoba lagi selama sesi berjalan."""


class AllEnginesFailed(JptransError):
    """Tidak ada satu pun mesin yang berhasil menerjemahkan."""

    exit_code = 3


class PlaceholderError(JptransError):
    """Penanda entitas hilang dari hasil terjemahan mesin."""

    def __init__(self, missing: list[int]) -> None:
        super().__init__(f"penanda hilang: {missing}")
        self.missing = missing
''')

MODUL['jptrans.gender'] = (
    False,
r'''"""Gender nama orang untuk koreksi kata ganti bahasa Inggris (he/she).

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
''')

MODUL['jptrans.glossary'] = (
    False,
r'''"""Glosarium per judul: sumber kebenaran ejaan nama, tempat, dan istilah.

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
''')

MODUL['jptrans.models'] = (
    False,
r'''"""Model data yang dipakai bersama oleh semua modul.

Modul lain hanya bertukar objek dari berkas ini, sehingga pembaca
(readers), mesin (engines), dan penulis (writers) tidak saling bergantung.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

# Modul data murni yang saat ini tidak menulis log; logger tetap ada sesuai aturan
# proyek "satu logger per modul", agar log yang kelak ditambahkan ikut hierarki jptrans.*.
logger = logging.getLogger(__name__)

# Jenis entitas yang dikenali.
PERSON = "PERSON"   # nama orang
PLACE = "PLACE"     # nama tempat
ORG = "ORG"         # organisasi, sekolah, kelompok
TERM = "TERM"       # istilah khusus karya: jurus, sihir, benda
CULTURE = "CULTURE"  # istilah budaya: onigiri, chuunibyou
ENTITY_KINDS = (PERSON, PLACE, ORG, TERM, CULTURE)

# Status terjemahan satu kalimat.
STATUS_OK = "ok"            # diterjemahkan dengan penanda utuh
STATUS_CACHED = "cached"    # diambil dari cache
STATUS_PRESUB = "presub"    # lewat jalur cadangan: nama Latin disisipkan dulu
STATUS_PLAIN = "plain"      # kalimat tanpa huruf Jepang, disalin apa adanya
STATUS_FAILED = "failed"    # semua mesin gagal; teks asli dipertahankan
STATUS_PARTIAL = "partial"  # jawaban terbaik masih bersisa huruf Jepang (tak ada yang bersih)

DIALOGUE_DASH = "- "
"""Awalan tiap baris pembicara di cue subtitle dua pembicara (selalu ``-`` ASCII)."""

# Tag format SRT. Satu sumber untuk semua regex tag di ``models`` dan ``segment``.
SIMPLE_TAG_NAMES = "[ibus]"
"""Nama tag format tanpa atribut (``<i>``, ``<b>``, ``<u>``, ``<s>``); pola regex."""
FORMAT_TAG_NAMES = rf"(?:{SIMPLE_TAG_NAMES}|font)"
"""Nama semua tag format SRT yang dikenal, termasuk ``<font ...>``; pola regex."""
_TAG_TAIL = r"(?:\s[^<>\n]*)?>"
OVERRIDE_TAG = r"\{\\[^{}\n]*\}"
"""Override posisi/gaya ASS di SRT (``{\\an8}``); tidak berpasangan."""
OPENING_TAG = rf"<{FORMAT_TAG_NAMES}{_TAG_TAIL}"
"""Tag pembuka, boleh beratribut (``<i>``, ``<font color="red">``)."""
CLOSING_TAG = rf"</{FORMAT_TAG_NAMES}{_TAG_TAIL}"
"""Tag penutup dengan bentuk yang sama dengan pembuka: ``</i>``, ``</i >``, dan juga
``</i atribut>`` (atribut di tag penutup diabaikan peramban, jadi tetap tag)."""
SIMPLE_OPENING_TAG = f"<{SIMPLE_TAG_NAMES}>"
"""Tag pembuka tanpa atribut; hanya tag ini yang boleh digabung lintas baris."""
FORMAT_TAG = f"{OVERRIDE_TAG}|{OPENING_TAG}|{CLOSING_TAG}"
"""Satu tag format SRT: override ``{\\an8}``, pembuka ``<i>``/``<font ...>``, atau penutup
``</i>``/``</font>``."""

LEADING_TAGS_RE = re.compile(f"(?:{OVERRIDE_TAG}|{OPENING_TAG})+", re.IGNORECASE)
"""Tag format SRT pembuka di awal baris: override ``{\\an8}`` dan ``<i>``/``<b>``/``<u>``/
``<s>``/``<font ...>``. Tag ini milik tampilan, jadi tanda dialog ditulis sesudahnya."""


def split_leading_tags(text: str) -> tuple[str, str]:
    """Pisah tag format pembuka di awal ``text`` dari isinya.

    Returns:
        ``(tag, sisa)``; ``tag`` kosong bila ``text`` tidak diawali tag.
    """
    match = LEADING_TAGS_RE.match(text)
    end = match.end() if match else 0
    return text[:end], text[end:]


_TAG_AT_RE = re.compile(rf"\s*(?:{FORMAT_TAG})", re.IGNORECASE)
_ANY_TAG_RE = re.compile(FORMAT_TAG, re.IGNORECASE)


def split_format_tags(text: str) -> tuple[str, str, str]:
    """Pisah tag format di tepi ``text``: ``(tag depan, isi, tag belakang)``.

    Tag depan dan belakang boleh pembuka maupun penutup. Spasi di antara tag dan
    isi dibuang (``<i> はい </i>`` memberi ``("<i>", "はい", "</i>")``), sehingga
    menyusun ulang ``depan + terjemahan + belakang`` tidak pernah memberi spasi
    sebelum ``</i>``. Teks yang isinya hanya tag memberi isi kosong dan semua
    tagnya di bagian depan.

    Tag tepi hanya dilepas bila isinya tidak lagi memuat tag. Bila pasangan tag
    hanya separuh berada di tepi (``<i>行くぞ</i>。``, ``今日は<i>魔法だ</i>``),
    melepas separuhnya membuat mesin menerima tag tanpa pasangan dan keluaran
    yang tidak seimbang. Dalam kasus itu hanya override ``{\\an8}`` di depan yang
    dilepas (override tidak berpasangan); sisanya, termasuk pasangan tag yang
    utuh, menjadi isi: ``{\\an8}<i>行くぞ</i>。`` memberi
    ``("{\\an8}", "<i>行くぞ</i>。", "")``.

    Pemindaian linear (tanpa regex yang mundur di seluruh teks), jadi cue raksasa
    dari unggahan tidak memperlambat server.

    Returns:
        Tiga bagian; menggabungkannya memberi ``text`` tanpa spasi di sekitar tag.
    """
    lead: list[str] = []
    ends: list[int] = []
    start = 0
    while match := _TAG_AT_RE.match(text, start):
        lead.append(match.group().strip())
        start = match.end()
        ends.append(start)
    trail: list[str] = []
    end = len(text)
    while True:
        while end > start and text[end - 1].isspace():
            end -= 1
        if end <= start or text[end - 1] not in ">}":
            break
        opener = text.rfind("<" if text[end - 1] == ">" else "{", start, end)
        if opener < 0 or not _ANY_TAG_RE.fullmatch(text, opener, end):
            break
        trail.insert(0, text[opener:end])
        end = opener
    body = text[start:end].strip()
    if body and _ANY_TAG_RE.search(body):
        overrides = 0
        while overrides < len(lead) and lead[overrides].startswith("{"):
            overrides += 1
        start = ends[overrides - 1] if overrides else 0
        return "".join(lead[:overrides]), text[start:].strip(), ""
    return "".join(lead), body, "".join(trail)


def strip_format_tags(text: str) -> str:
    """Buang semua tag format SRT dari ``text`` (untuk tampilan baca HTML)."""
    return _ANY_TAG_RE.sub("", text)


def dialogue_line(turn: str) -> str:
    """Satu baris pembicara: ``DIALOGUE_DASH`` sesudah tag pembuka (``{\\an8}- Ya.``)."""
    tags, body = split_leading_tags(turn)
    return tags + DIALOGUE_DASH + body.lstrip()


@dataclass(frozen=True)
class GlossaryEntry:
    """Satu entri glosarium: sumber kebenaran untuk sebuah nama atau istilah.

    Attributes:
        surface: Bentuk tulisan Jepang, misalnya ``田中`` atau ``紅蓮爆炎斬``.
        kind: Salah satu dari ``ENTITY_KINDS``.
        reading: Bacaan kana (``たなか``). Dipakai untuk romanisasi.
        romaji: Ejaan Latin pilihan pengguna. Mengalahkan romanisasi otomatis.
            Nama lengkap ditulis "Keluarga Diri" (``Yamada Tarō``).
        render_id: Bentuk akhir untuk bahasa Indonesia (mis. ``Akademi Sihir``).
        render_en: Bentuk akhir untuk bahasa Inggris.
        gloss_id: Arti untuk ditampilkan sekali pada kemunculan pertama (ID).
        gloss_en: Arti untuk kemunculan pertama (EN).
        gender: ``"m"``, ``"f"``, atau kosong. Dipakai mode honorifik localize.
        aliases: Bentuk tulisan lain untuk entitas yang sama.
        allow_compound: Izinkan pencocokan walau langsung diikuti kanji.
        confirmed: ``True`` bila sudah diperiksa pengguna atau dikunci otomatis.
        source: Asal entri: ``user``, ``ruby``, ``heuristic``, ``engine``, ...
        score: Skor keyakinan deteksi (0 sampai 1).
    """

    surface: str
    kind: str = PERSON
    reading: str = ""
    romaji: str = ""
    render_id: str = ""
    render_en: str = ""
    gloss_id: str = ""
    gloss_en: str = ""
    gender: str = ""
    aliases: tuple[str, ...] = ()
    allow_compound: bool = False
    confirmed: bool = True
    source: str = "user"
    score: float = 1.0

    def render_for(self, lang: str) -> str:
        """Kembalikan bentuk akhir khusus bahasa, atau string kosong."""
        return self.render_id if lang == "id" else self.render_en

    def gloss_for(self, lang: str) -> str:
        """Kembalikan gloss kemunculan pertama untuk bahasa sasaran."""
        return self.gloss_id if lang == "id" else self.gloss_en


@dataclass(frozen=True)
class Slot:
    """Satu entitas yang dimasking di dalam kalimat.

    Attributes:
        entry: Entri glosarium asal.
        honorific: Kunci romaji honorifik (``san``, ``senpai``), atau kosong.
        suffix: Sufiks Jepang setelah nama/honorifik (``達``, ``家``, ``駅``).
        parents: Unit wilayah yang mendahului tempat ini dalam satu alamat,
            terluar dulu, sebagai pasangan ``(entri, sufiks)``.
    """

    entry: GlossaryEntry
    honorific: str = ""
    suffix: str = ""
    parents: tuple[tuple[GlossaryEntry, str], ...] = ()


@dataclass
class Masked:
    """Hasil masking satu teks beserta peta slot penanda ``[[E#]]``."""

    original: str
    text: str
    slots: dict[int, Slot]


@dataclass
class Candidate:
    """Kandidat entitas hasil deteksi otomatis, sebelum masuk glosarium."""

    surface: str
    kind: str
    score: float
    reading: str = ""
    count: int = 0
    evidence: list[str] = field(default_factory=list)


@dataclass
class Paragraph:
    """Satu paragraf atau satu unit teks dari dokumen sumber.

    ``meta`` menyimpan data khusus format, misalnya nomor dan waktu
    subtitle (``{"index": 3, "start": "00:00:01,000", ...}``) atau
    nomor halaman dan balon pada komik.
    """

    text: str
    kind: str = "text"   # "text" atau "heading"
    meta: dict = field(default_factory=dict)


@dataclass
class Document:
    """Dokumen sumber yang sudah dibaca dan diurai.

    Attributes:
        title: Judul karya; menentukan berkas glosarium yang dipakai.
        paragraphs: Isi dokumen berurutan.
        ruby: Pasangan furigana ``{tulisan: bacaan}`` dari Aozora atau EPUB.
        source_path: Lokasi berkas asal.
        fmt: Format asal: ``txt``, ``aozora``, ``epub``, ``srt``, ``pages``.
    """

    title: str
    paragraphs: list[Paragraph]
    ruby: dict[str, str] = field(default_factory=dict)
    source_path: str = ""
    fmt: str = "txt"


@dataclass
class SentencePair:
    """Pasangan kalimat sumber dan terjemahannya.

    ``turn`` adalah nomor giliran pembicara di dalam paragraf (mulai 0). Hanya
    cue subtitle dua pembicara (``- はい`` / ``- いいえ``) yang punya giliran
    lebih dari satu; paragraf lain selalu 0.
    """

    source: str
    target: str
    engine: str = ""
    status: str = STATUS_OK
    turn: int = 0


@dataclass
class TranslatedParagraph:
    """Paragraf sumber beserta kalimat-kalimat terjemahannya."""

    source: Paragraph
    sentences: list[SentencePair] = field(default_factory=list)

    @property
    def is_dialogue(self) -> bool:
        """Paragraf ini cue dua pembicara atau lebih (ada kalimat dengan ``turn > 0``)."""
        return any(sentence.turn > 0 for sentence in self.sentences)

    def turn_sentences(self) -> list[list[SentencePair]]:
        """Kalimat yang dikelompokkan per giliran pembicara, berurutan.

        Paragraf biasa memberi satu kelompok tanpa kalimat bertarget kosong
        (atau tidak ada kelompok bila tidak ada terjemahan). Cue dua pembicara
        menyimpan semua kalimat, supaya jumlah baris tetap sama dengan jumlah
        pembicara walau ada terjemahan kosong.
        """
        dialogue = self.is_dialogue
        groups: dict[int, list[SentencePair]] = {}
        for sentence in self.sentences:
            if sentence.target or dialogue:
                groups.setdefault(sentence.turn, []).append(sentence)
        return [groups[turn] for turn in sorted(groups)]

    @property
    def turns(self) -> list[str]:
        """Terjemahan per giliran pembicara (kalimat dalam satu giliran dipisah spasi).

        Kalimat bertarget kosong diganti teks sumbernya, jadi tidak ada giliran
        yang lenyap dari cue dua pembicara.
        """
        return [" ".join(s.target or s.source for s in group).strip()
                for group in self.turn_sentences()]

    @property
    def target(self) -> str:
        """Teks terjemahan utuh paragraf ini.

        Cue dua pembicara menjadi satu baris per giliran berawalan
        ``DIALOGUE_DASH`` (``- Ya.\\n- Tidak.``), ditaruh sesudah tag format
        pembuka (``dialogue_line``); paragraf lain satu baris.
        """
        if self.is_dialogue:
            return "\n".join(dialogue_line(turn) for turn in self.turns)
        return " ".join(s.target for s in self.sentences if s.target).strip()


@dataclass
class TranslatedDocument:
    """Hasil akhir pipeline, siap ditulis oleh writer mana pun."""

    document: Document
    paragraphs: list[TranslatedParagraph]
    source_lang: str
    target_lang: str
    glossary: list[GlossaryEntry] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def target(self) -> str:
        """Teks terjemahan gabungan seluruh paragraf, dipisah baris kosong."""
        return "\n\n".join(p.target or p.source.text for p in self.paragraphs)
''')

MODUL['jptrans.names'] = (
    False,
r'''"""Pemisahan nama keluarga, nama depan, dan bacaan nama orang Jepang.

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
''')

MODUL['jptrans.ner'] = (
    False,
r'''"""Deteksi entitas (nama orang, tempat, organisasi, istilah) secara bertingkat.

Setiap tingkat menghasilkan *sinyal* ber-skor untuk satu tulisan; sinyal
terkuat menentukan jenis dan skor dasar, lalu bonus frekuensi ditambahkan.

=====  ===========================================  ======================
Tier   Sinyal                                       Skor (konstanta)
=====  ===========================================  ======================
T1     ruby berbacaan hiragana + sinyal nama        ``SCORE_RUBY_NAME``
T1     ruby berbacaan hiragana saja                 ``SCORE_RUBY_PLAIN``
T1     ruby berbacaan katakana (gloss: 本気《マジ》)  ``SCORE_RUBY_GLOSS``
T2     nama + honorifik (田中さん, アリスちゃん)       ``SCORE_HONORIFIC``
T2     nama + gelar (佐藤部長, エリザ王女)            ``SCORE_TITLE``
T2     pola pembicara di awal baris (アリス「…」)     ``SCORE_SPEAKER``
T2     nama + sufiks tempat (吉祥寺駅)                ``SCORE_PLACE``
T2     kota setelah 都道府県 (愛知県刈谷市)             ``SCORE_PLACE``
T2     nama + sufiks organisasi (星見魔法学園)         ``SCORE_ORG``
T2     run katakana bukan kata serapan              ``SCORE_KATAKANA`` + ulang
T3     Janome ``名詞,固有名詞,人名/地域/組織``          ``+JANOME_BONUS``
=====  ===========================================  ======================

Bobot ini **asumsi desain** dari prototipe riset (LAPORAN_RISET 4.1), belum
dikalibrasi dengan korpus beranotasi. Semua angka ada di kepala modul agar
mudah disetel.

Dua keputusan untuk mencegah salah kunci:

- Bonus frekuensi hanya untuk sinyal nama. Ruby tanpa sinyal nama dan run
  katakana tidak mendapat bonus umum, karena furigana juga dipakai untuk kata
  sulit (憂鬱《ゆううつ》) yang bisa muncul berkali-kali tanpa menjadi nama.
  Run katakana sudah punya bonus ulang sendiri.
- Kata kekerabatan, sapaan, gelar, dan kata ganti (お兄ちゃん, 皆さん,
  お疲れ様, 校長先生, 君 sebagai "kamu") tidak pernah menjadi nama. Begitu
  juga kata berawalan sopan お/ご (お隣さん, ご苦労様) dan pekerjaan
  berakhiran 屋/員 (八百屋さん, 駅員さん).
- Run kanji sebelum honorifik bisa memuat kata lain di depannya
  (昨日田中さん): bila ekornya nama keluarga yang dikenal, hanya ekor itu
  yang menjadi nama. Run lebih dari empat kanji (長谷川美咲さん) hanya
  diterima bila diawali nama keluarga yang dikenal.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Container, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import NamedTuple

from . import data
from .config import Config
from .disambig import (
    HONORIFIC_SURFACES,
    TITLE_WORDS,
    VERB_AFTER_CHARS,
    VERB_CONTEXT_CHARS,
    honorific_fits,
    honorific_names_person,
    honorific_proves_name,
    is_known_name,
    is_verb_stem,
    verb_run_before_honorific,
)
from .models import ORG, PERSON, PLACE, TERM, Candidate, Document, GlossaryEntry
from .names import ambiguous_given_name, has_surname_head, split_family_reading
from .textnorm import (
    KANJI,
    KATAKANA,
    KATAKANA_RUN_RE,
    is_hiragana_text,
    kata_to_hira,
    search_key,
)

logger = logging.getLogger(__name__)

SCORE_RUBY_NAME = 0.8
SCORE_RUBY_PLAIN = 0.5
SCORE_RUBY_GLOSS = 0.3
SCORE_HONORIFIC = 0.85
SCORE_TITLE = 0.7
SCORE_SPEAKER = 0.75
SCORE_PLACE = 0.6
SCORE_ORG = 0.55
SCORE_FOREIGN_NAME = 0.65
SCORE_KATAKANA = 0.35
KATAKANA_REPEAT_BONUS = 0.1
KATAKANA_REPEAT_LIMIT = 3
FREQUENCY_BONUS = 0.05
FREQUENCY_BONUS_MAX = 0.15
JANOME_BONUS = 0.2
SCORE_JANOME_ONLY = 0.4
SCORE_MAX = 0.99
MAX_PLAIN_KANJI_NAME = 4
"""Run kanji yang lebih panjang hanya nama bila diawali nama keluarga (長谷川美咲)."""
MAX_KANJI_NAME = 6
POLITE_PREFIXES = frozenset("おご")
SHOUT_MARKS = "ーｰ"
"""Tanda panjang yang dibuang dari ujung run katakana teriakan (リンーー → リン)."""
OCCUPATION_ENDINGS = ("屋", "員")
"""Akhiran pekerjaan (八百屋, 駅員); nama keluarga seperti 土屋 tetap diterima."""

PLACE_SUFFIXES = ("駅", "市", "町", "村", "県", "都", "府", "区", "城", "山", "川", "島",
                  "国", "港", "寺", "神社")
FACILITY_WORDS = ("空港",)
"""Kata fasilitas berakhiran sufiks tempat (空港 = 空 + 港): 明日空港 adalah kata waktu + 空港, bukan
tempat bernama 明日空 (``is_time_word_place``)."""
MUNICIPALITY_SUFFIXES = ("市", "区", "町", "村")
"""Sufiks kota/distrik yang boleh menempel langsung setelah 都道府県 (愛知県刈谷市, 東京都港区)."""
NOT_MUNICIPALITY_STARTS = frozenset("内全各同当他隣両近旧外第")
"""Awal kata yang membuat ``都内各区``/``県内全町``/``県第一区`` frasa biasa, bukan nama kota."""
ADMIN_UNIT_CHARS = "都道府県市区町村"
"""Huruf unit wilayah; nama kota setelah 都道府県 tidak diawali salah satunya."""
GENERIC_MUNICIPALITY_WORDS = ("地区", "学区", "校区", "選挙区", "特区", "管区")
"""Kata umum berakhiran 区 yang bisa menyusul 都道府県 (愛知県地区大会, 東京都知事選挙区)."""
ORG_SUFFIXES = ("学園", "学院", "高校", "中学", "大学", "騎士団", "団", "組", "会", "部",
                "社", "商会", "ギルド")

HONORIFIC_EXCEPTIONS = (
    "お兄ちゃん", "お姉ちゃん", "お兄さん", "お姉さん", "兄さん", "姉さん", "兄ちゃん",
    "姉ちゃん", "お父さん", "お母さん", "父さん", "母さん", "お嬢様", "王様", "神様",
    "皆さん", "皆様", "みんな", "お疲れ様", "お疲れさま", "ご馳走様", "ご馳走さま",
    "お客様", "お客さん", "奥様", "奥さん", "貴様", "俺様", "ご苦労様", "ご苦労さま", "御苦労様",
    "お世話様", "ご愁傷様",
)
"""Frasa utuh yang berakhiran honorifik tetapi bukan nama (dari SPEC)."""

NOT_NAMES = frozenset({
    # Kata ganti dan kata waktu (今日君は = "kamu hari ini", bukan "Kyō-kun").
    "俺", "僕", "私", "彼", "彼女", "貴方", "貴女", "自分", "皆", "誰", "何",
    "拙者", "儂", "吾輩", "小生", "余", "朕", "某", "妾",
    "今", "今日", "明日", "昨日", "毎日", "今度", "今回", "本当", "時", "前", "後", "頃",
    # Kekerabatan.
    "兄", "姉", "弟", "妹", "父", "母", "祖父", "祖母", "叔父", "叔母", "伯父", "伯母",
    "爺", "婆", "息子", "娘", "夫", "妻", "旦那", "奥", "嫁", "坊", "嬢", "赤",
    # Gelar dan peran (校長先生, 勇者様, お客様).
    "王", "王子", "王女", "女王", "姫", "神", "女神", "魔王", "勇者", "聖女", "殿", "陛下",
    "殿下", "先生", "先輩", "後輩", "校長", "担任", "店長", "部長", "社長", "課長", "会長",
    "隊長", "団長", "師匠", "医者", "博士", "主人", "客", "大家", "店員", "警官", "運転手",
    "看護師", "生徒", "学生", "一人", "二人", "人", "子", "子供", "女", "男",
    "主", "若", "彼氏", "奥方", "大工", "猫", "犬", "隣",
})
"""Kata kanji yang sering mendahului honorifik tetapi bukan nama diri."""

MIN_VERB_STEM_RUBY = 2
"""Panjang minimal bacaan ruby batang kata kerja satu kanji agar menjadi bukti nama
(``_ruby_attests``)."""

TIME_PREFIXES = (
    "毎日", "毎朝", "毎晩", "毎週", "毎月", "毎年", "今日", "明日", "昨日", "今朝", "今夜", "今晩",
    "今週", "来週", "先週", "今月", "来月", "先月", "今年", "来年", "去年",
    "毎回", "毎度", "毎時", "毎夜", "毎週末", "今週末", "来週末", "先週末", "週末", "先日", "前日",
    "翌日", "当日", "後日", "一昨日", "明後日", "一昨年", "再来週", "再来月", "再来年", "昨夜", "昨晩",
    "昨年", "明朝", "明晩", "翌朝", "翌週", "翌月", "翌年", "夕方", "早朝", "深夜", "夜中", "午前",
    "午後", "平日", "休日", "祝日", "連休", "今回", "前回", "次回", "最近",
    "今度", "本日", "先程", "後程", "今後", "年末", "年始", "月末", "月初", "正月", "元日", "元旦",
    "朝晩", "毎夕", "一日中", "日中", "夜間", "昼間", "終日", "土日", "放課後", "正午", "今朝方",
    "朝方", "夕刻", "当日中", "今頃", "当時", "現在", "以前", "以後", "将来",
    # Musim berawalan 今/来/昨/毎/去 (今夏, 来春, 毎冬) dan kata waktu lain (putaran 2).
    *(head + season for head in "今来昨毎去" for season in "春夏秋冬"),
    "今夕", "今宵", "先々週", "先々月", "先々日", "隔週", "隔日", "隔月", "隔年", "連日", "連夜",
    "年内", "月内", "週内", "年中",
)
"""Kata waktu/frekuensi yang bisa menempel ke depan tempat + sufiks tanpa partikel (毎日駅まで,
明日吉祥寺駅で, 先日駅で). Nama hari (月曜, 日曜日) ditangani ``_WEEKDAY_RE``. Dicocokkan
terpanjang dulu (毎週末 sebelum 毎週)."""

_TIME_WORDS_LONGEST = tuple(sorted(TIME_PREFIXES, key=len, reverse=True))
TIME_TAIL_KANJI = frozenset("朝昼夜晩夕中頃末")
"""Satu kanji waktu yang menempel ke kata waktu (明日朝, 昨日夜, 今日中): sisa ini bukan nama tempat
(``_without_time_word``), berbeda dengan sisa satu huruf lain (明日香村)."""
_WEEKDAY_RE = re.compile("毎?[月火水木金土日]曜日?")
"""Nama hari, boleh berawalan 毎 (毎日曜 = setiap Minggu, 毎土曜日)."""
_DURATION_NUMERALS = "〇一二三四五六七八九十百千数何"
_DURATION_RE = re.compile(
    f"[{_DURATION_NUMERALS}]+(?:(?:[日週年]|[かヶカケヵ]月)(?:間[前後]?|[前後中])"
    "|時間[前後中]?|[分秒](?:間[前後]?|[前後]))"
)
"""Lama waktu berangka + 前/後/中/間 (三日前, 二週間後, 数年前, 三か月後, 二時間後, 三十分前).
Tanpa ekor itu bukan kata waktu: 二日市, 四日市, 十日町 adalah nama tempat."""
_COUNTER_BEFORE_RE = re.compile(f"[{_DURATION_NUMERALS}]+[かカケヵ]$")
"""Angka + か/ヶ (hiragana/katakana) tepat sebelum kandidat: 三か月後駅 terpotong menjadi 月後駅."""

GENERIC_COMPOUNDS = frozenset({
    "城下町", "田舎町", "生徒会", "委員会", "新聞部", "運動部", "文芸部", "冒険者ギルド",
    "新聞社", "出版社", "通信社", "株式会社", "有限会社", "旅行会社", "保険会社",
})
"""Kata majemuk umum yang kebetulan berakhiran sufiks tempat/organisasi."""

JANOME_KINDS = {"人名": PERSON, "地域": PLACE, "組織": ORG}
"""Pemetaan POS IPADIC (dipakai Janome) ke jenis entitas."""

ALIAS_TAG = "alias:"
"""Awalan bukti untuk alias sejati (mis. ｱﾘｽ untuk アリス); dibaca ``candidates_to_entries``."""

_KANJI_NAME = f"(?<![{KANJI}])[{KANJI}]{{1,{MAX_KANJI_NAME}}}"
_KATAKANA_NAME = f"(?<![{KATAKANA}]){KATAKANA_RUN_RE.pattern}"
_HONORIFIC_RE = re.compile(
    f"(?P<name>{_KANJI_NAME}|{_KATAKANA_NAME})"
    f"(?P<hon>{'|'.join(sorted(HONORIFIC_SURFACES, key=len, reverse=True))})"
)
# Nama sesingkat mungkin (lazy) agar 田中副社長 menjadi 田中 + 副社長, bukan 田中副 + 社長.
_TITLE_RE = re.compile(
    f"(?P<name>(?<![{KANJI}])[{KANJI}]{{2,{MAX_KANJI_NAME}}}?|{_KATAKANA_NAME})"
    f"(?P<title>{'|'.join(sorted(TITLE_WORDS, key=len, reverse=True))})"
)
_SPEAKER_RE = re.compile(f"^(?P<name>[{KANJI}]{{1,4}}|{KATAKANA_RUN_RE.pattern})[：:]?「")
# Kata waktu boleh mendahului nama 2-4 kanji (毎週末吉祥寺駅); ``_without_time_word`` membuangnya.
_TIME_PREFIX = f"(?:{_WEEKDAY_RE.pattern}|{'|'.join(_TIME_WORDS_LONGEST)})?"
# Ekor alamat yang boleh menempel sesudah sufiks tempat (松本市出身, 長野県松本市在住); selain itu
# kanji sesudah sufiks membatalkan (松本市内). Sama dengan ``protect.ADDRESS_TAILS``.
ADDRESS_TAILS = ("出身", "在住", "在勤", "生まれ", "育ち", "産")
_PLACE_END = (f"(?!(?!{'|'.join(tail for tail in ADDRESS_TAILS if tail != '産')}"
              f"|産(?![{KANJI}]))[{KANJI}])")
_SUFFIX_BASE = f"(?P<base>(?<![{KANJI}]){_TIME_PREFIX}[{KANJI}]{{2,4}}|{_KATAKANA_NAME})"
# Organisasi tanpa awalan kata waktu: 毎日新聞社 adalah nama, bukan 毎日 + 新聞社.
_ORG_BASE = f"(?P<base>(?<![{KANJI}])[{KANJI}]{{2,4}}|{_KATAKANA_NAME})"
_PLACE_RE = re.compile(f"{_SUFFIX_BASE}(?P<suf>{'|'.join(PLACE_SUFFIXES)}){_PLACE_END}")
_ORG_RE = re.compile(
    f"{_ORG_BASE}(?P<suf>{'|'.join(sorted(ORG_SUFFIXES, key=len, reverse=True))})"
    f"(?![{KANJI}])"
)
# Kota setelah unit wilayah (愛知県刈谷市, 東京都港区): unit wilayah itu sendiri harus
# didahului kanji (bagian nama prefektur), agar 都内 di awal kalimat tidak ikut. Nama
# kotanya tidak diawali huruf unit wilayah dan tidak memuat 市/区, agar 京都市中京区,
# 学園都市第七学区, 都道府県市区町村, dan 大阪府大阪市北区 tidak menjadi kandidat palsu.
_ADMIN_CHILD_RE = re.compile(
    f"(?<=[{KANJI}][都道府県])(?![{ADMIN_UNIT_CHARS}])"
    f"(?P<base>(?:(?![市区])[{KANJI}]){{1,4}})"
    f"(?P<suf>{'|'.join(MUNICIPALITY_SUFFIXES)}){_PLACE_END}"
)
_KANJI_CHAR_RE = re.compile(f"[{KANJI}]")
_KATAKANA_WORD_RE = re.compile(f"[{KATAKANA}]+")


class _Signal(NamedTuple):
    """Satu bukti bahwa ``surface`` adalah entitas."""

    surface: str
    kind: str
    score: float
    evidence: str
    reading: str = ""
    frequency_bonus: bool = True


@dataclass
class _Found:
    """Gabungan sinyal untuk satu tulisan; sinyal terkuat menentukan jenis."""

    kind: str
    score: float
    frequency_bonus: bool
    reading: str = ""
    extra: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def absorb(self, signal: _Signal) -> None:
        """Masukkan sinyal baru; ganti jenis dan skor bila lebih kuat."""
        if signal.score > self.score:
            self.kind, self.score = signal.kind, signal.score
            self.frequency_bonus = signal.frequency_bonus
        self.reading = self.reading or signal.reading
        if signal.evidence not in self.evidence:
            self.evidence.append(signal.evidence)


def detect_entities(
    doc: Document, known: set[str] | None = None, *, use_janome: bool = False
) -> list[Candidate]:
    """Cari kandidat entitas di seluruh dokumen.

    Args:
        doc: Dokumen hasil pembaca; ``doc.ruby`` dipakai sebagai T1.
        known: Tulisan yang sudah ada di glosarium; dilewati. Tempat bawaan
            dari ``data/places.json`` juga selalu dilewati.
        use_janome: Pakai Janome (T3) bila terpasang.

    Returns:
        Kandidat terurut dari skor tertinggi, sudah melalui ``merge_aliases``.
    """
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    skip = set(known or ()) | set(data.places())
    found: dict[str, _Found] = {}
    _absorb_all(found, _honorific_signals(text, attested_names(text, doc.ruby)))
    _absorb_all(found, _title_signals(text))
    _absorb_all(found, _speaker_signals(paragraph.text for paragraph in doc.paragraphs))
    named = set(found)
    _absorb_all(found, _suffix_signals(text, skip))
    _absorb_all(found, _katakana_signals(text, skip))
    _absorb_all(found, _ruby_signals(doc.ruby, named))
    if use_janome:
        _apply_janome(found, text)
    candidates = [
        _finalize(surface, item, text, doc.ruby)
        for surface, item in found.items()
        if surface not in skip
    ]
    logger.info("deteksi entitas: %d kandidat dari %d karakter", len(candidates), len(text))
    return merge_aliases(candidates)


def attested_names(text: str, ruby: Mapping[str, str] | None = None) -> frozenset[str]:
    """Tulisan yang di ``text`` terbukti nama, untuk aturan kata kerja + ん dokumen ini.

    Bukti: run kanji + honorifik ber-ん yang disusul huruf yang hanya mungkin untuk nama
    (``style.honorific_names_person``: 乾くんが, 開くん、, 治さんは), atau tulisan berkanji
    yang punya ruby hiragana di dokumen (歩《あゆむ》; untuk batang kata kerja satu kanji hanya bacaan
    nama yang dikenal, lihat ``_ruby_attests``). Kemunculan lain yang konteksnya
    ambigu (乾くんだ！) lalu dibaca nama juga, baik di deteksi maupun di masking
    (``protect.EntityMatcher``), sehingga satu dokumen konsisten.

    Args:
        text: Seluruh teks dokumen.
        ruby: Pasangan furigana dokumen.
    """
    found = {base for base, reading in (ruby or {}).items()
             if _KANJI_CHAR_RE.search(base) and is_hiragana_text(reading)
             and _ruby_attests(base, reading)}
    for match in _HONORIFIC_RE.finditer(text):
        after = text[match.end():match.end() + VERB_CONTEXT_CHARS]
        if _KANJI_CHAR_RE.match(match["name"]) and honorific_names_person(match["hon"], after):
            found.add(match["name"])
    return frozenset(found)


def _ruby_attests(base: str, reading: str) -> bool:
    """Ruby ``base``《``reading``》 membuktikan nama untuk ``attested_names``.

    Ruby kata biasa selalu bukti. Untuk satu kanji yang juga batang kata kerja (``is_verb_stem``)
    ruby di EPUB/Aozora sering hanya bacaan batang kata kerja itu (咲《さ》く, 歩《ある》く,
    渡《わた》す), jadi bacaannya harus bacaan nama yang dikenal untuk kanji itu
    (``data.kanji_readings``, ``data.name_word_readings``, ``data.given_names``), minimal
    ``MIN_VERB_STEM_RUBY`` kana, dan bukan awalan bacaan nama lain yang lebih panjang (わた dari
    わたる). 歩《あゆむ》 dan 咲《さき》 tetap bukti.
    """
    if len(base) != 1 or not is_verb_stem(base):
        return True
    known = set(data.kanji_readings().get(base, ())) | set(data.name_word_readings().get(base, ()))
    given = data.given_names().get(base)
    if given and given.get("reading"):
        known.add(given["reading"])
    return (len(reading) >= MIN_VERB_STEM_RUBY and reading in known
            and not any(other != reading and other.startswith(reading) for other in known))


def honorific_name_counts(doc: Document) -> Counter[str]:
    """Jumlah kemunculan nama + honorifik per tulisan (sama dengan deteksi T2 honorifik).

    Dipakai ``pipeline.Translator`` untuk menilai seberapa kuat bukti entri satu kanji.
    """
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    named = attested_names(text, doc.ruby)
    return Counter(signal.surface for signal in _honorific_signals(text, named))


def strong_name_counts(doc: Document) -> Counter[str]:
    """Jumlah kemunculan nama + honorifik yang konteksnya nama tegas, per tulisan.

    Tegas menurut ``style.honorific_proves_name``: honorifik yang tidak mungkin okurigana kata
    kerja untuk kanji itu (咲ちゃん, 歩さま, 輝さん), huruf sesudah honorifik yang hanya mungkin untuk
    nama (歩くんが, 歩くん、, 渡さんが来た), atau panggilan dengan koma/seru di posisi panggilan
    (渡さん、おはよう, おい歩くん！). Negasi sesudah topik (娘は渡さん！) dan kemunculan yang
    dibaca nama hanya karena aturan konteks (やっぱり歩くんだ, まさか歩くんか) tidak dihitung.
    Dipakai ``pipeline.Translator`` untuk entri satu kanji yang juga batang kata kerja.
    """
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    counts: Counter[str] = Counter()
    for match in _HONORIFIC_RE.finditer(text):
        hon = match["hon"]
        if not honorific_fits(hon, text, match.end()) or _is_exception(
                text, match.start(), match.end()):
            continue
        after = text[match.end():match.end() + VERB_CONTEXT_CHARS]
        before = text[max(0, match.start() - VERB_CONTEXT_CHARS):match.start()]
        if honorific_proves_name(match["name"], hon, before, after):
            counts[match["name"]] += 1
    return counts


def merge_aliases(cands: Iterable[Candidate]) -> list[Candidate]:
    """Gabungkan alias sejati dan tautkan nama keluarga dengan nama lengkap.

    - Tulisan dengan ``search_key`` sama (ｱﾘｽ dan アリス) digabung menjadi satu
      kandidat; tulisan lain dicatat sebagai bukti ``alias:...`` dan menjadi
      ``GlossaryEntry.aliases``.
    - PERSON yang merupakan awalan atau akhiran PERSON lain (田中 / 太郎 dan
      田中太郎) **tetap kandidat terpisah**, karena alias glosarium dirender
      identik: menggabungkannya akan membuat 田中さん tampil sebagai
      "Tanaka Tarō-san". Keduanya hanya ditautkan lewat bukti, dan bacaan
      bagian itu diturunkan dari bacaan nama lengkap bila bacaan itu
      berspasi (``たなか たろう`` → 田中 ``たなか``, 太郎 ``たろう``).

    Args:
        cands: Kandidat hasil deteksi (tidak diubah).

    Returns:
        Daftar kandidat baru terurut dari skor tertinggi.
    """
    merged: dict[str, Candidate] = {}
    for cand in sorted(cands, key=_rank):
        key = search_key(cand.surface)
        main = merged.get(key)
        if main is None:
            merged[key] = replace(cand, evidence=list(cand.evidence))
            continue
        main.count += cand.count
        main.reading = main.reading or cand.reading
        main.evidence.append(f"{ALIAS_TAG}{cand.surface}")
    people = [cand for cand in merged.values() if cand.kind == PERSON]
    for short in people:
        for full in people:
            if full is short:
                continue
            if full.surface.startswith(short.surface):
                _link_part(short, full, given=False)
            elif full.surface.endswith(short.surface):
                _link_part(short, full, given=True)
    return sorted(merged.values(), key=_rank)


def candidates_to_entries(
    cands: Iterable[Candidate], cfg: Config
) -> tuple[list[GlossaryEntry], list[GlossaryEntry]]:
    """Ubah kandidat menjadi entri glosarium menurut ambang di ``cfg``.

    Args:
        cands: Kandidat dari ``detect_entities``.
        cfg: Konfigurasi (``auto_lock_threshold``, ``candidate_threshold``).

    Returns:
        Pasangan (entri terkunci ``confirmed=True``, entri untuk ditinjau
        ``confirmed=False``), keduanya ``source="auto"``. Kandidat di bawah
        ``candidate_threshold`` dibuang.
    """
    locked: list[GlossaryEntry] = []
    review: list[GlossaryEntry] = []
    for cand in cands:
        if cand.score >= cfg.auto_lock_threshold:
            locked.append(_to_entry(cand, confirmed=True))
        elif cand.score >= cfg.candidate_threshold:
            review.append(_to_entry(cand, confirmed=False))
    return locked, review


def _absorb_all(found: dict[str, _Found], signals: Iterable[_Signal]) -> None:
    """Masukkan semua sinyal ke tabel ``found``."""
    for signal in signals:
        item = found.get(signal.surface)
        if item is None:
            found[signal.surface] = item = _Found(
                signal.kind, signal.score, signal.frequency_bonus
            )
        item.absorb(signal)


def _honorific_signals(text: str, named: frozenset[str] = frozenset()) -> Iterator[_Signal]:
    """T2: nama kanji atau katakana 2+ huruf yang diikuti honorifik.

    ``named`` adalah tulisan yang terbukti nama di dokumen ini (``attested_names``).
    """
    surnames = data.surnames()
    for match in _HONORIFIC_RE.finditer(text):
        hon = match["hon"]
        if not honorific_fits(hon, text, match.end()) or _is_exception(
                text, match.start(), match.end()):
            continue
        if match.start() > 0 and text[match.start() - 1] in POLITE_PREFIXES \
                and match["name"] not in surnames:
            continue  # お隣さん, ご苦労様: kata biasa berawalan sopan, bukan nama
        before = text[max(0, match.start() - VERB_CONTEXT_CHARS):match.start()]
        after = text[match.end():match.end() + VERB_AFTER_CHARS]
        if _verb_ending(match["name"], hon, after, before, named):
            continue  # 行くんですか, 駅まで歩くんですか, 許さんと言った: kata kerja + ん
        name = _person_part(match["name"], surnames)
        if name is None or _is_not_name(name):
            continue
        yield _Signal(name, PERSON, SCORE_HONORIFIC, f"honorifik:{hon}", surnames.get(name, ""))


def _title_signals(text: str) -> Iterator[_Signal]:
    """T2: nama yang diikuti gelar jabatan (佐藤部長, 佐藤恒治社長, エリザ王女).

    Run kanji hanya diterima bila diawali nama keluarga yang dikenal, karena
    gelar juga mengikuti kata biasa (営業部長, 副社長). Tempat bawaan + sufiks
    tempat (千葉県知事, 広島県知事) bukan nama walau 千葉/広島 juga nama keluarga.
    """
    surnames = data.surnames()
    for match in _TITLE_RE.finditer(text):
        name = match["name"]
        if _KANJI_CHAR_RE.match(name) and not (name in surnames or _starts_with_surname(name)):
            continue
        if _is_builtin_place_with_suffix(name):
            continue
        if _is_not_name(name):
            continue
        yield _Signal(name, PERSON, SCORE_TITLE, f"gelar:{match['title']}",
                      surnames.get(name, ""))


def _speaker_signals(paragraphs: Iterable[str]) -> Iterator[_Signal]:
    """T2: baris naskah ``名前「…」`` atau ``名前：「…」``."""
    for paragraph in paragraphs:
        match = _SPEAKER_RE.match(paragraph)
        if match and not _is_not_name(match["name"]):
            yield _Signal(match["name"], PERSON, SCORE_SPEAKER, "pembicara")


def _suffix_signals(text: str, skip: set[str]) -> Iterator[_Signal]:
    """T2: tulisan + sufiks tempat (PLACE) atau organisasi (ORG).

    Kandidatnya tulisan utuh (吉祥寺駅). Bila bagian depannya sudah dikenal
    (東京駅 dengan 東京 di glosarium atau tempat bawaan), tidak ada kandidat
    baru: ``protect.EntityMatcher`` sudah menangani 東京 + sufiks 駅.

    Kota yang menempel langsung setelah 都道府県 (愛知県刈谷市) tidak tertangkap
    pola biasa karena didahului kanji, jadi dicari dengan ``_ADMIN_CHILD_RE``.
    Bila kotanya sudah dikenal (豊田), ``protect`` merangkai alamatnya sendiri.
    Kata umum (都内各区, 県第一区, 地区, 選挙区) tidak menjadi kandidat.
    """
    for match in _ADMIN_CHILD_RE.finditer(text):
        base, surface = match["base"], match.group()
        if base in skip or base[0] in NOT_MUNICIPALITY_STARTS \
                or surface.endswith(GENERIC_MUNICIPALITY_WORDS) \
                or _unit_inside_city_name(text, match.start(), skip):
            continue
        yield _Signal(surface, PLACE, SCORE_PLACE, f"sufiks:{match['suf']}:alamat")
    for pattern, kind, score in ((_PLACE_RE, PLACE, SCORE_PLACE), (_ORG_RE, ORG, SCORE_ORG)):
        for match in pattern.finditer(text):
            base, surface = match["base"], match.group()
            if kind == PLACE:
                if is_time_word_place(_counter_before(text, match.start()) + surface):
                    continue
                base = _without_time_word(base)
                surface = surface[len(surface) - len(base) - len(match["suf"]):]
            if not base or base in skip or _is_common_katakana(base) \
                    or surface in GENERIC_COMPOUNDS or _starts_with_known_admin_unit(base, skip):
                continue
            yield _Signal(surface, kind, score, f"sufiks:{match['suf']}")


def _counter_before(text: str, start: int) -> str:
    """Angka + か/ヶ tepat sebelum ``start`` (三か, 二ヶ), atau kosong (``_COUNTER_BEFORE_RE``).

    Huruf か/ヶ bukan kanji, jadi pola tempat bisa mulai di 月 (三か月後駅 → 月後駅); dengan awalan
    ini kandidat dikenali sebagai lama waktu (``is_time_word_place``).
    """
    found = _COUNTER_BEFORE_RE.search(text, max(0, start - 8), start)
    return found.group() if found is not None else ""


def _without_time_word(base: str) -> str:
    """``base`` tanpa kata waktu di depannya (``_time_word_prefix``): 毎日 dari 毎日駅 (kosong, bukan
    stasiun), 明日 dari 明日吉祥寺駅 (吉祥寺), 毎週末 dari 毎週末吉祥寺駅. Kata keterangan waktu
    tanpa partikel lazim menempel ke tempat tujuan (毎日駅まで歩く) dan bukan bagian nama tempat.

    Bila yang tersisa hanya satu huruf, kata waktu itu bagian nama tempat (明日香村, bukan
    明日 + 香村), jadi ``base`` dikembalikan utuh, kecuali huruf itu kanji waktu
    (``TIME_TAIL_KANJI``: 明日朝駅, 昨日夜駅), yang menghasilkan kosong.
    """
    prefix = _time_word_prefix(base)
    rest = base[len(prefix):]
    if prefix and rest in TIME_TAIL_KANJI:
        return ""
    return base if len(rest) == 1 else rest


def _time_word_prefix(base: str) -> str:
    """Deretan kata waktu di awal ``base`` (毎週 + 土曜日, 来週 + 月曜日), atau kosong.

    Tiap kata adalah yang terpanjang dari ``TIME_PREFIXES``, nama hari (``_WEEKDAY_RE``), atau
    lama waktu berangka (``_DURATION_RE``: 三日前, 二週間後).
    """
    end = 0
    while end < len(base):
        found = _WEEKDAY_RE.match(base, end) or _DURATION_RE.match(base, end)
        word = found.group() if found is not None else next(
            (word for word in _TIME_WORDS_LONGEST if base.startswith(word, end)), "")
        if not word:
            break
        end += len(word)
    return base[:end]


def is_time_word_place(surface: str) -> bool:
    """Apakah ``surface`` hanya kata waktu (boleh + kanji waktu) + sufiks tempat (毎日駅, 来週駅,
    日曜日駅, 今日町, 明日朝駅).

    Tulisan seperti itu bukan nama tempat: kata keterangan waktu tanpa partikel yang menempel
    ke sufiks (毎日駅まで走る = "setiap hari sampai stasiun"). Dipakai deteksi entitas (lewat
    ``_without_time_word``) dan ``pipeline.masking_map`` untuk entri otomatis lama. 新宿駅,
    明日香村, dan 駅 saja bukan.
    """
    for suffix in sorted(PLACE_SUFFIXES + FACILITY_WORDS, key=len, reverse=True):
        base = surface[:-len(suffix)]
        if surface.endswith(suffix) and base:
            prefix = _time_word_prefix(base)
            return bool(prefix) and (prefix == base or base[len(prefix):] in TIME_TAIL_KANJI)
    return False


def _unit_inside_city_name(text: str, start: int, skip: set[str]) -> bool:
    """Huruf 都道府県 sebelum ``start`` adalah awal nama kota, bukan unit wilayah.

    東京都府中市: 府 didahului 東京都 (tempat dikenal + unit wilayah), jadi 府 adalah
    huruf pertama 府中, bukan sufiks prefektur; kandidat ``中市`` palsu. 京都府京田辺市
    tetap diterima karena di depan 都 hanya ada 京, bukan tempat dikenal.
    """
    before = start - 2
    if before < 0 or text[before] not in ADMIN_UNIT_CHARS[:4]:
        return False
    return any(text[max(0, before - size):before] in skip for size in range(1, 5))


def _starts_with_known_admin_unit(base: str, skip: set[str]) -> bool:
    """Awal ``base`` adalah tempat dikenal + 都/道/府/県 (東京都港 dari 東京都港区).

    Kandidat seperti ``東京都港区`` menutupi 東京 di masking (kecocokan terpanjang
    yang ditolak tidak jatuh ke entri pendek), sehingga alamat keluar setengah
    Latin (``東京都Distrik Minato``). Kotanya sudah ditangkap ``_ADMIN_CHILD_RE``
    (``港区``) dan protect merangkai alamatnya sendiri.
    """
    return any(ch in ADMIN_UNIT_CHARS[:4] and base[:index] in skip
               for index, ch in enumerate(base) if index)


def _katakana_signals(text: str, skip: Container[str] = frozenset()) -> Iterator[_Signal]:
    """T2: kata katakana utuh yang bukan kata serapan umum atau onomatope.

    Ekor ー teriakan dibuang dulu (``_shout_base``): リンーー menjadi リン, dan ハルトー menjadi
    ハルト bila ハルト sudah dikenal (``skip``) atau muncul tanpa ー di teks yang sama
    (ハルトーっ！ ... ハルトが来た), agar teriakan tidak menjadi entri sampah.
    """
    found = [match.group() for match in KATAKANA_RUN_RE.finditer(text)
             if match.start() == 0 or not _KATAKANA_WORD_RE.match(text[match.start() - 1])]
    plain = frozenset(run for run in found if not run.endswith(tuple(SHOUT_MARKS)))
    runs = Counter(_shout_base(run, skip, plain) for run in found)
    foreign = data.foreign_names()
    for run, count in runs.items():
        if _is_common_katakana(run):
            continue
        parts = [p for p in search_key(run).split("・") if p]
        if parts and all(part in foreign for part in parts):
            yield _Signal(run, PERSON, SCORE_FOREIGN_NAME, f"nama-asing×{count}")
            continue
        repeat = KATAKANA_REPEAT_BONUS * min(count - 1, KATAKANA_REPEAT_LIMIT)
        yield _Signal(run, TERM, SCORE_KATAKANA + repeat, f"katakana×{count}",
                      frequency_bonus=False)


def _shout_base(run: str, skip: Container[str], plain: Container[str] = frozenset()) -> str:
    """Run katakana tanpa ekor ー teriakan (``SHOUT_MARKS``), bila ekor itu memang teriakan.

    Dua ー atau lebih selalu teriakan (リンーー → リン). Satu ー hanya dibuang bila tulisan
    dasarnya sudah dikenal (``skip``) atau muncul tanpa ー di dokumen yang sama (``plain``):
    ハルトー → ハルト. Kata seperti メーカー atau nama マリー tetap utuh.
    """
    base = run.rstrip(SHOUT_MARKS)
    tail = len(run) - len(base)
    if len(base) < 2 or not tail:
        return run
    return base if tail >= 2 or base in skip or base in plain else run


def _ruby_signals(ruby: Mapping[str, str], named: set[str]) -> Iterator[_Signal]:
    """T1: pasangan furigana dengan tulisan berkanji.

    Bacaan katakana di atas kanji (本気《マジ》) adalah gloss, bukan bacaan;
    bacaan hiragana tanpa sinyal nama bisa saja kata sulit biasa. Ruby batang kata kerja satu
    kanji yang hanya bacaan batang itu (咲《さ》, 歩《ある》; ``_ruby_attests``) dilewati: itu
    bacaan sebagian kata kerja, bukan kata.
    """
    for base, reading in ruby.items():
        if not _KANJI_CHAR_RE.search(base) or not reading:
            continue
        if is_hiragana_text(reading) and not _ruby_attests(base, reading):
            continue
        if _KATAKANA_WORD_RE.fullmatch(reading):
            yield _Signal(base, TERM, SCORE_RUBY_GLOSS, f"ruby-gloss:{reading}",
                          frequency_bonus=False)
        elif base in named:
            yield _Signal(base, PERSON, SCORE_RUBY_NAME, "ruby", reading)
        else:
            yield _Signal(base, _kind_by_suffix(base), SCORE_RUBY_PLAIN, "ruby", reading,
                          frequency_bonus=False)


def _apply_janome(found: dict[str, _Found], text: str) -> None:
    """T3 opsional: tambah skor tulisan yang ditandai Janome sebagai nama diri."""
    for surface, kind in sorted(set(_janome_proper_nouns(text))):
        item = found.get(surface)
        if item is None:
            found[surface] = item = _Found(kind, SCORE_JANOME_ONLY, frequency_bonus=True)
        else:
            item.extra = JANOME_BONUS
        item.evidence.append(f"janome:{kind}")


def _janome_proper_nouns(text: str) -> list[tuple[str, str]]:
    """Daftar (tulisan, jenis) untuk token ``名詞,固有名詞,人名/地域/組織``.

    Returns:
        Daftar kosong bila Janome tidak terpasang.
    """
    try:
        from janome.tokenizer import Tokenizer
    except ImportError:
        logger.info("Janome tidak terpasang; tingkat T3 dilewati")
        return []
    nouns = []
    for token in Tokenizer().tokenize(text):
        pos = token.part_of_speech.split(",")
        if pos[:2] == ["名詞", "固有名詞"] and len(pos) > 2 and pos[2] in JANOME_KINDS:
            nouns.append((token.surface, JANOME_KINDS[pos[2]]))
    return nouns


def _finalize(surface: str, item: _Found, text: str, ruby: Mapping[str, str]) -> Candidate:
    """Hitung skor akhir dan bacaan; bacaan ruby mengalahkan bacaan surnames.json."""
    count = max(text.count(surface), 1)
    bonus = min(FREQUENCY_BONUS * (count - 1), FREQUENCY_BONUS_MAX)
    if not item.frequency_bonus:
        bonus = 0.0
    score = min(round(item.score + bonus + item.extra, 4), SCORE_MAX)
    reading = _hiragana_reading(ruby.get(surface, "")) or item.reading
    if item.kind == PERSON:
        reading = split_family_reading(surface, reading)
    return Candidate(surface, item.kind, score, reading, count, list(item.evidence))


def _hiragana_reading(reading: str) -> str:
    """Bacaan ruby hanya dipakai bila berupa hiragana (bukan gloss katakana)."""
    return reading if is_hiragana_text(reading) else ""


def _is_not_name(name: str) -> bool:
    """Kata umum, gelar, kekerabatan, pekerjaan, kata serapan katakana, atau kata waktu.

    Kata waktu ``TIME_PREFIXES`` yang bukan nama dikenal (毎朝ちゃんと磨くんだ: 毎朝 + ちゃんと
    kata keterangan, bukan "Maiasa-chan") tidak pernah nama orang.
    """
    if name in NOT_NAMES or _is_common_katakana(name):
        return True
    if name in TIME_PREFIXES and not is_known_name(name):
        return True
    return name.endswith(OCCUPATION_ENDINGS) and name not in data.surnames()


def _verb_ending(run: str, hon: str, after: str, before: str, named: frozenset[str]) -> bool:
    """Run kanji + honorifik yang sebenarnya kata kerja + okurigana + ん.

    ``style.verb_run_before_honorific`` dengan ``NOT_NAMES`` sebagai awalan bukan nama:
    行くんですか, 駅まで歩くんですか, 明日行くん, dan kata waktu/tempat + 行くんだ
    (来週行くんだ) bukan nama; partikel nama sesudah honorifik (雅行くんが, 開くんが), posisi
    panggilan/atributif (おい、乾くん！, 弟の歩くんです), dan nama dua kanji (大輝くんです)
    membuatnya tetap nama.
    """
    return verb_run_before_honorific(run, hon, after, NOT_NAMES, before=before, named=named)


def _person_part(name: str, surnames: Mapping[str, str]) -> str | None:
    """Bagian nama orang dari run sebelum honorifik, atau ``None`` bila bukan nama."""
    if not _KANJI_CHAR_RE.match(name) or name in surnames or _starts_with_surname(name):
        return name
    given = data.given_names()
    if name in given:
        return name
    for idx in range(1, len(name)):
        tail = name[idx:]
        if tail in surnames or (
            len(tail) >= 2 and tail in given and not ambiguous_given_name(tail)
        ):
            return tail
    return name if len(name) <= MAX_PLAIN_KANJI_NAME else None


def _starts_with_surname(name: str) -> bool:
    """Run kanji diawali nama keluarga yang sah (lihat ``names.has_surname_head``)."""
    return has_surname_head(name)


def _is_builtin_place_with_suffix(name: str) -> bool:
    """Tempat bawaan diikuti sufiks tempat (千葉県, 広島市): bukan nama orang."""
    places = data.places()
    return any(
        name.endswith(suffix) and name[:-len(suffix)] in places for suffix in PLACE_SUFFIXES
    )


def _is_exception(text: str, start: int, end: int) -> bool:
    """Kecocokan ``text[start:end]`` adalah ekor frasa di ``HONORIFIC_EXCEPTIONS``."""
    return any(
        end - start <= len(phrase) <= end and text.startswith(phrase, end - len(phrase))
        for phrase in HONORIFIC_EXCEPTIONS
    )


def _is_common_katakana(word: str) -> bool:
    """Kata serapan, gabungan kata serapan (モンスターハウス), atau onomatope."""
    key = search_key(word).replace("・", "")
    if not _KATAKANA_WORD_RE.fullmatch(key):
        return False
    words = data.loanwords()
    return key in words or _is_loanword_compound(key, words) or _looks_like_sfx(key)


def _is_loanword_compound(word: str, words: frozenset[str]) -> bool:
    """Apakah ``word`` bisa dipecah habis menjadi kata-kata serapan (DP sederhana)."""
    reachable = [True] + [False] * len(word)
    for start in range(len(word)):
        if reachable[start]:
            for end in range(start + 2, len(word) + 1):
                if word[start:end] in words:
                    reachable[end] = True
    return reachable[-1]


def _looks_like_sfx(word: str) -> bool:
    """Onomatope: pengulangan (ドキドキ), satu huruf berulang (ゴゴゴ), atau berakhir ッ."""
    if word.endswith("ッ"):
        return True
    core = word.replace("ー", "")
    half = len(core) // 2
    repeated = len(core) >= 4 and len(core) % 2 == 0 and core[:half] == core[half:]
    return repeated or len(set(core)) == 1


def _kind_by_suffix(surface: str) -> str:
    """Tebak jenis dari sufiks: tempat, organisasi, atau orang."""
    if surface.endswith(PLACE_SUFFIXES):
        return PLACE
    if surface.endswith(ORG_SUFFIXES):
        return ORG
    return PERSON


def _link_part(short: Candidate, full: Candidate, *, given: bool) -> None:
    """Tautkan nama keluarga atau nama depan dengan nama lengkap tanpa menggabungkan rendernya.

    Bacaan bagian itu diturunkan dari bacaan nama lengkap yang berspasi:
    ``かんざき ゆうま`` memberi 神崎 → かんざき dan 悠真 → ゆうま.
    """
    parts = full.reading.split()
    if not short.reading and len(parts) >= 2:
        short.reading = parts[1 if given else 0]
    note = f"bagian-dari:{full.surface}"
    if note not in short.evidence:
        short.evidence.append(note)


def _rank(cand: Candidate) -> tuple[float, int, str]:
    """Urutan: skor tertinggi, lalu paling sering, lalu tulisan."""
    return (-cand.score, -cand.count, cand.surface)


def _to_entry(cand: Candidate, *, confirmed: bool) -> GlossaryEntry:
    """Bangun entri glosarium otomatis dari kandidat."""
    aliases = tuple(e[len(ALIAS_TAG):] for e in cand.evidence if e.startswith(ALIAS_TAG))
    return GlossaryEntry(
        surface=cand.surface,
        kind=cand.kind,
        reading=kata_to_hira(cand.reading),
        aliases=aliases,
        confirmed=confirmed,
        source="auto",
        score=cand.score,
    )
''')

MODUL['jptrans.net'] = (
    False,
r'''"""Lapisan HTTP bersama untuk semua mesin penerjemah.

Semua permintaan jaringan lewat ``http_request`` agar kebijakan yang sama
berlaku di mana-mana: User-Agent jujur, timeout, retry dengan exponential
backoff + jitter hanya untuk galat sementara (429, 5xx, timeout, koneksi
putus), dan pemetaan status HTTP ke galat jptrans:

========================  ===================================================
Status / kejadian         Galat yang dilempar
========================  ===================================================
429, 500, 502-504         dicoba ulang; bila tetap gagal ``EngineError``
timeout, koneksi putus    dicoba ulang; bila tetap gagal ``EngineUnavailable``
sertifikat TLS ditolak    ``EngineUnavailable`` tanpa retry, dengan petunjuk
402, 456 (DeepL)          ``QuotaExceeded`` tanpa retry
403/429 bertanda kuota    ``QuotaExceeded`` tanpa retry
401, 403 lain, 404        ``EngineUnavailable`` (key/endpoint/model tidak sah)
3xx (redirect)            ``EngineError``; redirect tidak pernah diikuti
4xx lain                  ``EngineError``
========================  ===================================================

Koneksi yang tetap gagal setelah semua percobaan ulang (HP sedang offline,
DNS gagal) mematikan mesin untuk sesi itu lewat ``EngineUnavailable``, agar
pipeline tidak mengulang belasan detik backoff untuk setiap kalimat.

Redirect sengaja tidak diikuti: ``urllib`` bawaan menyalin semua header,
termasuk ``Authorization``, ke host tujuan redirect (juga dari https ke http).
Badan respons dibatasi ``MAX_RESPONSE_BYTES``.

``urlopen`` adalah fungsi tingkat modul supaya tes bisa menggantinya dengan
``unittest.mock.patch("jptrans.net.urlopen")`` tanpa menyentuh jaringan.
"""

from __future__ import annotations

import json
import logging
import random
import ssl
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__
from .errors import EngineError, EngineUnavailable, QuotaExceeded

logger = logging.getLogger(__name__)

USER_AGENT = f"jptrans/{__version__} (+tugas-kuliah; python-urllib)"

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
QUOTA_STATUSES = frozenset({402, 456})
AUTH_STATUSES = frozenset({401, 403})
UNAVAILABLE_STATUSES = frozenset({404})
# Potongan teks (huruf kecil) di badan respons galat yang berarti kuota/saldo habis.
QUOTA_HINTS = (
    "quota",
    "exhausted",
    "used all available",
    "insufficient_quota",
    "insufficient_balance",
)
MAX_DELAY = 30.0
ERROR_BODY_LIMIT = 2048
MESSAGE_LIMIT = 160
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
CERTIFICATE_HINT = (
    "sertifikat TLS tidak bisa diverifikasi; di macOS jalankan 'Install Certificates.command' "
    "dari folder Python, atau periksa proxy jaringan"
)

# Galat pustaka yang berarti permintaan gagal di tengah jalan.
_NETWORK_ERRORS = (HTTPError, URLError, TimeoutError, ConnectionError, HTTPException)


class _NoRedirect(HTTPRedirectHandler):
    """Tolak redirect agar header ``Authorization`` tidak pernah pindah host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = build_opener(_NoRedirect)


def urlopen(request: Request, timeout: float) -> Any:
    """Buka ``request`` tanpa mengikuti redirect (status 3xx menjadi ``HTTPError``)."""
    return _OPENER.open(request, timeout=timeout)


@dataclass(frozen=True)
class _Failure:
    """Hasil klasifikasi satu kegagalan permintaan."""

    error: EngineError
    retryable: bool
    retry_after: float | None = None


def http_request(
    url: str,
    *,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    method: str | None = None,
    timeout: float = 20.0,
    retries: int = 3,
    backoff: float = 1.5,
    engine: str = "net",
) -> bytes:
    """Kirim satu permintaan HTTP dan kembalikan badan respons mentah.

    Args:
        url: Alamat lengkap, termasuk query string bila ada.
        data: Badan permintaan; bila diisi, metode bawaan menjadi POST.
        headers: Header tambahan. ``User-Agent`` diisi otomatis.
        method: Metode HTTP eksplisit (``GET``, ``POST``, ...).
        timeout: Batas waktu per percobaan, dalam detik.
        retries: Jumlah percobaan ulang setelah percobaan pertama.
        backoff: Jeda dasar backoff; jeda ke-n = ``backoff * 2**(n-1)`` + jitter.
        engine: Nama mesin untuk pesan galat dan log.

    Returns:
        Badan respons dalam bentuk bytes.

    Raises:
        QuotaExceeded: Status 456 atau 403 yang menyebut kuota.
        EngineUnavailable: Status 401 atau 403 lain, sertifikat TLS ditolak,
            atau koneksi yang tetap gagal setelah semua percobaan ulang.
        EngineError: Galat lain (termasuk redirect dan respons terlalu besar),
            atau galat HTTP sementara yang tetap terjadi setelah semua
            percobaan ulang.
    """
    request = _build_request(url, data, headers, method, engine)
    attempt = 0
    while True:
        attempt += 1
        try:
            with urlopen(request, timeout=timeout) as response:
                return _read_limited(response, engine)
        except _NETWORK_ERRORS as exc:
            failure = _classify(exc, engine)
            if not failure.retryable or attempt > retries:
                raise _final_error(failure, exc, engine) from exc
            delay = failure.retry_after
            if delay is None:
                delay = backoff_delay(attempt, backoff)
            logger.warning(
                "%s; percobaan ulang %d/%d dalam %.1f s", failure.error, attempt, retries, delay
            )
            time.sleep(delay)


def post_form(url: str, fields: Mapping[str, str], **kw: Any) -> bytes:
    """Kirim formulir ``application/x-www-form-urlencoded`` lewat POST.

    Args:
        url: Alamat tujuan.
        fields: Pasangan nama dan nilai formulir.
        **kw: Diteruskan ke ``http_request`` (``timeout``, ``engine``, ...).

    Returns:
        Badan respons mentah.
    """
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    headers.update(kw.pop("headers", None) or {})
    body = urlencode(fields).encode("ascii")
    return http_request(url, data=body, headers=headers, method="POST", **kw)


def post_json(
    url: str, payload: Any, headers: Mapping[str, str] | None = None, **kw: Any
) -> Any:
    """Kirim JSON lewat POST dan urai respons JSON-nya.

    Args:
        url: Alamat tujuan.
        payload: Objek yang bisa diserialisasi ``json.dumps``.
        headers: Header tambahan, misalnya ``Authorization``.
        **kw: Diteruskan ke ``http_request``.

    Returns:
        Objek Python hasil ``json.loads``.

    Raises:
        EngineError: Galat HTTP atau respons yang bukan JSON.
    """
    merged = {"Content-Type": "application/json", "Accept": "application/json"}
    merged.update(headers or {})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    raw = http_request(url, data=body, headers=merged, method="POST", **kw)
    return parse_json(raw, kw.get("engine", "net"))


def get_json(url: str, params: Mapping[str, str], **kw: Any) -> Any:
    """Kirim GET dengan query string dan urai respons JSON-nya.

    Args:
        url: Alamat dasar tanpa atau dengan query string.
        params: Parameter query; di-encode dengan ``urlencode``.
        **kw: Diteruskan ke ``http_request``.

    Returns:
        Objek Python hasil ``json.loads``.

    Raises:
        EngineError: Galat HTTP atau respons yang bukan JSON.
    """
    separator = "&" if "?" in url else "?"
    raw = http_request(url + separator + urlencode(params), method="GET", **kw)
    return parse_json(raw, kw.get("engine", "net"))


def parse_json(raw: bytes, engine: str = "net") -> Any:
    """Urai badan respons sebagai JSON UTF-8.

    Layanan gratis kadang membalas halaman HTML (captcha, blokir) dengan
    status 200, jadi kegagalan urai dianggap kegagalan mesin, bukan bug.

    Args:
        raw: Badan respons mentah.
        engine: Nama mesin untuk pesan galat.

    Returns:
        Objek Python hasil ``json.loads``.

    Raises:
        EngineError: Badan bukan JSON yang sah.
    """
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        kind = "HTML (mungkin captcha atau diblokir)" if _looks_like_html(raw) else "bukan JSON"
        raise EngineError(engine, f"respons {kind}, {len(raw)} byte") from exc


def http_status(error: BaseException) -> int | None:
    """Kembalikan status HTTP yang menyebabkan sebuah galat jptrans.

    ``http_request`` selalu memakai ``raise ... from exc``, sehingga
    ``HTTPError`` asli tersimpan di ``__cause__``. Mesin memakai ini untuk
    keputusan khusus, misalnya LLM yang mengulang tanpa ``response_format``
    ketika server membalas 400.

    Args:
        error: Galat yang ditangkap pemanggil.

    Returns:
        Kode status, atau ``None`` bila penyebabnya bukan respons HTTP.
    """
    cause = error.__cause__
    return cause.code if isinstance(cause, HTTPError) else None


def backoff_delay(attempt: int, backoff: float) -> float:
    """Hitung jeda exponential backoff dengan jitter acak.

    Args:
        attempt: Nomor percobaan yang baru gagal, mulai dari 1.
        backoff: Jeda dasar dalam detik.

    Returns:
        Jeda dalam detik, paling lama ``MAX_DELAY``.
    """
    base = backoff * 2 ** (attempt - 1)
    # Jitter mencegah banyak klien mencoba ulang pada detik yang sama.
    return min(MAX_DELAY, base + random.uniform(0, base / 2))


def parse_retry_after(headers: Message | None) -> float | None:
    """Baca header ``Retry-After`` berbentuk detik.

    Bentuk tanggal HTTP diabaikan karena jarang dipakai layanan ini.

    Args:
        headers: Header respons galat.

    Returns:
        Jeda dalam detik (0 sampai ``MAX_DELAY``), atau ``None``.
    """
    raw = headers.get("Retry-After") if headers is not None else None
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_DELAY)


class RateLimiter:
    """Menjaga jeda minimum antar-permintaan ke satu layanan.

    Dibuat satu per mesin. Aman dipakai beberapa thread sekaligus.

    Args:
        min_interval: Jeda minimum antar-panggilan ``wait`` (detik).
    """

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Tidur seperlunya agar jeda minimum terpenuhi.

        Returns:
            Lama tidur dalam detik (0 bila tidak perlu menunggu).
        """
        with self._lock:
            now = time.monotonic()
            delay = 0.0
            if self._last is not None:
                delay = max(0.0, self._last + self.min_interval - now)
            if delay:
                time.sleep(delay)
            self._last = time.monotonic()
            return delay


def server_message(body: bytes) -> str:
    """Ambil pesan galat singkat dari badan respons untuk ditampilkan.

    Args:
        body: Badan respons galat (boleh kosong).

    Returns:
        Pesan satu baris, paling panjang ``MESSAGE_LIMIT`` karakter.
    """
    if not body:
        return "tanpa pesan"
    if _looks_like_html(body):
        return "halaman HTML"
    text = body.decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            error = error.get("message")
        text = str(error or data.get("message") or data.get("responseDetails") or text)
    return " ".join(text.split())[:MESSAGE_LIMIT]


def _build_request(
    url: str,
    data: bytes | None,
    headers: Mapping[str, str] | None,
    method: str | None,
    engine: str,
) -> Request:
    merged = {"User-Agent": USER_AGENT}
    merged.update(headers or {})
    try:
        return Request(url, data=data, headers=merged, method=method)
    except ValueError as exc:
        raise EngineError(engine, f"URL tidak valid: {url.split('?', 1)[0]}") from exc


def _read_limited(response: Any, engine: str) -> bytes:
    """Baca badan respons sukses, paling banyak ``MAX_RESPONSE_BYTES``."""
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise EngineError(engine, f"respons melebihi {MAX_RESPONSE_BYTES} byte")
    return body


def _final_error(failure: _Failure, exc: BaseException, engine: str) -> EngineError:
    """Galat yang dilempar setelah percobaan terakhir.

    Galat koneksi (bukan respons HTTP) yang menetap berarti jaringan tidak
    bisa dipakai, jadi dinaikkan ke ``EngineUnavailable`` agar mesin dimatikan.
    """
    if failure.retryable and not isinstance(exc, HTTPError):
        return EngineUnavailable(engine, f"koneksi gagal: {_reason(exc)}")
    return failure.error


def _classify(exc: BaseException, engine: str) -> _Failure:
    """Petakan galat pustaka ke galat jptrans dan tentukan perlu retry atau tidak."""
    if isinstance(_cause(exc), ssl.SSLCertVerificationError):
        return _Failure(EngineUnavailable(engine, CERTIFICATE_HINT), retryable=False)
    if not isinstance(exc, HTTPError):
        return _Failure(EngineError(engine, f"koneksi gagal: {_reason(exc)}"), retryable=True)
    code = exc.code
    body = _read_error_body(exc)
    detail = f"HTTP {code}: {server_message(body)}"
    if (
        code in QUOTA_STATUSES
        or (code == 403 and _mentions_quota(body))
        or (code == 429 and b"insufficient_quota" in body.lower())
    ):
        return _Failure(
            QuotaExceeded(engine, f"kuota habis ({detail})"), retryable=False
        )
    if code in AUTH_STATUSES:
        return _Failure(
            EngineUnavailable(engine, f"akses ditolak ({detail})"),
            retryable=False,
        )
    if code in UNAVAILABLE_STATUSES:
        return _Failure(
            EngineUnavailable(engine, f"endpoint/model tidak ditemukan ({detail})"),
            retryable=False,
        )
    if code in RETRY_STATUSES:
        delay = parse_retry_after(exc.headers)
        return _Failure(EngineError(engine, detail), retryable=True, retry_after=delay)
    return _Failure(EngineError(engine, detail), retryable=False)


def _read_error_body(exc: HTTPError) -> bytes:
    """Baca awal badan respons galat, lalu tutup koneksinya (kode status tetap ada)."""
    try:
        return exc.read(ERROR_BODY_LIMIT) or b""
    except (OSError, HTTPException, ValueError):
        return b""
    finally:
        exc.close()


def _mentions_quota(body: bytes) -> bool:
    lowered = body.decode("utf-8", "replace").lower()
    return any(hint in lowered for hint in QUOTA_HINTS)


def _looks_like_html(raw: bytes) -> bool:
    return raw[:200].lstrip().startswith(b"<")


def _cause(exc: BaseException) -> BaseException:
    """Penyebab asli galat koneksi (``URLError.reason`` bila berupa galat)."""
    reason = getattr(exc, "reason", None) if isinstance(exc, URLError) else None
    return reason if isinstance(reason, BaseException) else exc


def _reason(exc: BaseException) -> str:
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, str):
        return reason
    return f"{type(reason).__name__}: {reason}" if str(reason) else type(reason).__name__
''')

MODUL['jptrans.phonetic'] = (
    False,
r'''"""Validasi fonetik ejaan nama dari mesin terhadap bacaan kana (fungsi murni).

Mesin penerjemah kadang menjawab nama dengan arti, bukan bunyi: ミサキ → ``Cape``
(misaki = tanjung), レオン → ``Lion``, リリア → ``Lily of the valley``. Modul ini
memeriksa apakah jawaban *terdengar* seperti katakana/bacaannya.

Cara kerja (keputusan desain, ambang bisa dikalibrasi):

1. ``normalize`` mengubah ejaan Latin menjadi bentuk kasar bunyi: huruf kecil
   tanpa diakritik, lalu kelompok bunyi yang tidak dibedakan katakana disamakan
   (r~l, b~v, s~sh~th, t~ts~ch, h~f, k~c~q~ck, g~j, z~s). ``h`` bisu setelah
   vokal (John, Satoh) dan ``r`` non-rotik setelah vokal (Lucifer, Charlotte)
   dibuang, huruf ganda diringkas, dan vokal akhir ``e``/``o``/``u`` setelah
   konsonan dibuang di KEDUA sisi: itu vokal epentetik katakana (スミス sumisu)
   atau ``e`` bisu bahasa Inggris (Alice).
2. ``similarity`` = 1 − jarak edit berbobot / panjang terpanjang. Vokal ``u``/``o``/``i``
   di antara dua konsonan pada sisi katakana murah dihapus (``EPENTHETIC_COST``,
   ヴィクトリア vi-ku-toria ↔ Victoria); s↔t setengah harga (``NEAR_COST``,
   シャーロット ↔ Charlotte). Perubahan vokal lain berharga penuh, sehingga
   レオン/Lion (e ↔ i) ditolak.
3. Kerangka konsonan (vokal dibuang) juga harus mirip (``MIN_SKELETON_SIMILARITY``),
   agar jawaban dengan vokal kebetulan sama tetapi konsonan lain tidak lolos.

Contoh keputusan: アリス/``Alicia`` DITOLAK (kemiripan 0,67). Alicia ditulis
アリシア dalam katakana; アリス tidak punya suku kata -シア, jadi Alicia adalah
nama lain, bukan ejaan lain dari Alice.

Jawaban yang seluruhnya huruf kapital (``FELICIA``) dijadikan Title Case per kata
(``Felicia``, ``O'BRIEN`` → ``O'Brien``), dan jawaban berhuruf kecil dikapitalkan
(``scheherazade`` → ``Scheherazade``) lalu tetap harus lolos validasi bunyi.
``is_hepburn_echo`` mengenali jawaban yang hanya mengulang Hepburn bagian itu
(リョーマ/``Ryoma``): itu tanda nama Jepang, sehingga pipeline memakai Hepburn
sesuai mode romanisasi.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from . import data
from .romaji import is_latin, kana_to_romaji
from .textnorm import kata_to_hira, strip_diacritics, widen_halfwidth_kana

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.82
"""Kemiripan minimum seluruh bunyi (vokal ikut dihitung).

0,82 (bukan 0,8) agar satu vokal akhir yang hilang pada nama lima huruf tidak
lolos: リリア/``Lily`` (riria ↔ riri, 0,8) ditolak, sedangkan Charlotte (0,9) dan
Smith (0,95) tetap diterima.
"""
MIN_SKELETON_SIMILARITY = 0.75
"""Kemiripan minimum kerangka konsonan."""
EUROPEAN_MIN_SIMILARITY = 0.86
"""Kemiripan minimum untuk ejaan Eropa (``_sounds_european``), lebih ketat dari ``MIN_SIMILARITY``.

Dikalibrasi pada pasangan silang kamus ``foreign_names.json`` (katakana x nama Latin lain): pada
0,82 jalur ini meloloskan 11 pasangan salah (ロナルド/``Donald`` 0,821, ドナルド/``Ronald``,
モルガナ/``Morgan`` 0,844, ジェラルド/``Gertrude`` 0,857); pada 0,86 nol. Pasangan benar yang
dikorbankan (ヴォルコフ/``Volkov``, ハプスブルク/``Habsburg``, ヴォルフガング/``Wolfgang``) tetap
ditolak seperti sebelumnya.
"""
EPENTHETIC_COST = 0.25
NEAR_COST = 0.5
VOWELS = frozenset("aeiou")
EPENTHETIC_VOWELS = frozenset("uoi")
FINAL_SILENT_VOWELS = frozenset("eou")
R_VOWEL_SPELLINGS: dict[str, frozenset[str]] = {
    "e": frozenset({"a", "ae", "ai", "ay", "ea", "ei"}),
    "o": frozenset({"o", "oa", "oo", "ou"}),
    "i": frozenset({"ea", "ee", "ei", "ie"}),
    "u": frozenset({"oo", "ou", "u", "ue"}),
}
"""Vokal katakana sebelum ア akhir → ejaan vokal Inggris di depan ``-r``/``-re`` non-rotik.

エア: Clare, Sinclair, Alistair; オア: Theodore, Eleonore; イア: Napier, Greer; ウア: Moore.
``e`` tunggal (``-er``) sengaja tidak ada di イア, jadi オリヴィア/``Oliver`` tetap ditolak.
"""

# Urutan penting: gugus tiga huruf dulu, lalu dua huruf.
_CLUSTERS = (
    ("tch", "t"), ("sch", "s"), ("sh", "s"), ("th", "s"), ("ch", "t"), ("ph", "f"),
    ("ck", "k"), ("qu", "ku"), ("dg", "g"), ("ts", "t"), ("wh", "w"),
)
_LETTERS = str.maketrans({"q": "k", "x": "ks", "j": "g", "v": "b", "l": "r", "f": "h",
                          "z": "s"})
# Ejaan vokal bahasa Inggris → bunyi yang ditulis katakana (hanya untuk sisi jawaban).
_ENGLISH_VOWELS = (
    (re.compile(r"ie$|ey$|ee|ea"), "i"), (re.compile(r"oo|ew"), "u"),
    (re.compile(r"au|aw"), "o"), (re.compile(r"ay"), "ei"),
    (re.compile(r"[eiuao]r$|[eiua]r(?![aeiouy])"), "a"), (re.compile(r"or(?![aeiouy])"), "o"),
)
_SOFT_C_RE = re.compile(r"c(?=[eiy])")
_INITIAL_SILENT_RE = re.compile(r"^(?:k(?=n)|w(?=r)|g(?=h))")
_GH_RE = re.compile(r"(?<=.)gh")
_Y_GLIDE_RE = re.compile(r"y(?=[aeiou])")
_SILENT_H_RE = re.compile(r"(?<=[aeiou])h(?![aeiou])")
_NON_ROTIC_R_RE = re.compile(r"(?<=[aeiou])r(?![aeiou])")
_DOUBLE_RE = re.compile(r"(.)\1+")
_PART_SEPARATOR_RE = re.compile(r"[\s・·]+")
_WORD_START_RE = re.compile(r"(^|['’\-])(\w)")
_LONG_VOWEL_RE = re.compile(r"ou|([aeiou])\1+")
# Satu kata romanisasi Jepang (Hepburn, juga Kunrei/wāpuro): suku kata konsonan(+y) + vokal,
# ん (n, atau m sebelum b/p/m), dengan konsonan ganda (sokuon) sudah diringkas lebih dulu.
_ROMANIZED_WORD_RE = re.compile(r"(?:(?:sh|ch|ts|[kgsztdnhbpmr]y?|[jfwy])?[aiueo]|n|m(?=[bpm]))+")
_GEMINATE_RE = re.compile(r"([kgsztdhbpcfjmn])\1|t(?=ch)")
_NATIVE_KANA_RE = re.compile("[ァィゥェォヮヴヵヶ]")
# Hepburn menulis ん sebagai m di depan b/p/m (Namba, Jimbo, Homma).
_HEPBURN_M_RE = re.compile(r"m(?=[bpm])", re.IGNORECASE)
# Ejaan ``-r``/``-re`` di akhir kata (Theodore, Sinclair); grup 1 = vokal di depan r.
_R_ENDING_RE = re.compile(r"(?<![aeiouy])([aeiouy]+)re?$")
_TRAILING = " \t.。,、!！?？"
# Katakana dengan ル + konsonan atau ル di akhir (ヒルデガルト, ゲオルグ, ベルント, ロルフ): ejaan aslinya
# punya r/l di akhir suku kata, yang bahasa Eropa ucapkan (bukan r non-rotik bahasa Inggris).
# ル + ー/vokal (ルーク, ルイ) bukan akhir suku kata.
_CODA_LIQUID_KANA_RE = re.compile("ル(?![ーァアィイゥウェエォオャュョヮ・])")
# Jawaban dengan r/l di akhir suku kata: disusul konsonan atau akhir kata (Bernd, Georg, Rolf).
_CODA_LIQUID_SPELLING_RE = re.compile(r"[rl]+(?![aeiouy])")
_LIQUID_MARK = "L"
"""Penanda sementara ``l`` di ``_normalize`` (huruf besar: tidak ada sesudah ``casefold``)."""
_CONSONANT_RUN_RE = re.compile("[b-df-hj-np-tv-z]*")
"""Deretan huruf mati (y termasuk) di awal teks, untuk ``_romaji_onset`` dan ``_codas_align``."""
_DEVOICED = str.maketrans({"d": "t", "g": "k", "b": "p"})
"""Pelemahan konsonan akhir bahasa Jerman: Bernd → ベルント, Gertrud → ゲルトルート."""
EUROPEAN_DECOY_WORDS = frozenset("""
    cult cults curd curds mild wild gold hold bold cold fold told sold mold gelt geld gourd halt
    malt salt hart hard card cart dart part mart art bolt colt jolt volt belt felt melt pelt welt
    milk silk bulk hulk golf gulf self shelf elf herd nerd bird word lord cord hurt girl karma kart
    park fork cork work pork turn burn horn corn worn barn yarn film helm elm palm calm realm
    tart hilt berth birth mirth girth earth worth north forth hertz
    sort shirk elk kelt mirk
""".split())
"""Kata Inggris umum ber-r/l + konsonan yang bunyinya sama dengan bacaan katakana ber-ル+konsonan
(クルト/``Cult``, ミルト/``Mild``, ゴルト/``Gold``, ベルト/``Belt``): bunyi tidak bisa membedakannya dari
nama Eropa, jadi jalur Eropa menolaknya (``data.COMMON_ENGLISH_WORDS`` juga). Nama yang juga kata
(Wolf, Mark, Ford, Curt) sengaja tidak ada."""
_EUROPEAN_ONSETS: dict[str, tuple[str, ...]] = {
    "": ("a", "e", "i", "o", "u", "y", "h"), "k": ("k", "c", "q"), "g": ("g",),
    "s": ("s", "z", "c"), "sh": ("sch", "sh", "s", "ch", "c"), "z": ("z", "s", "x"),
    "j": ("j", "g", "y", "dj", "zh"), "t": ("t",), "d": ("d",), "ch": ("ch", "c", "tsch", "cz"),
    "ts": ("ts", "z", "tz", "c"), "n": ("n", "kn"), "h": ("h",), "f": ("f", "ph"), "b": ("b",),
    "p": ("p",), "m": ("m",), "y": ("y", "j", "i"), "r": ("r", "l", "wr", "rh"),
    "w": ("w", "v", "o", "u"), "v": ("v", "w"),
}
"""Huruf awal ejaan yang sejalan dengan konsonan awal katakana di jalur Eropa (kosong = vokal;
Spanyol menulis h bisu: エルナンデス/``Hernandez``). ゴ/ゲ tidak ditulis j (ゴルト/``Jolt``), ハ tidak ditulis f
(ハルト/``Fardo``). Konsonan katakana lain cukup sama huruf pertamanya."""
_EUROPEAN_CODA_FITS: dict[str, tuple[str, ...]] = {
    "": ("",), "t": ("t", "d"), "d": ("d", "t"), "k": ("k", "c", "g", "q"), "g": ("g",),
    "f": ("f", "ph", "v", "w"), "b": ("b", "v", "w"), "v": ("v", "w", "f"), "w": ("w", "v"),
    "s": ("s", "z", "c", "x"), "z": ("z", "s"), "sh": ("sch", "sh", "s", "c", "ch"),
    "ch": ("ch", "tsch", "c", "cz"), "ts": ("ts", "tz", "z"), "j": ("j", "g", "s", "z"),
    "h": ("h", "ch"), "p": ("p", "b"), "r": ("r", "l"),
}
"""Huruf ejaan sesudah r/l akhir suku kata yang sejalan dengan konsonan sesudah ル (kosong = akhir
kata). ト boleh d (pelemahan Jerman: Hildegard, Ewald), ク boleh g (Georg ゲオルク), tetapi ト tidak
ch (ハルト/``Halch``). Konsonan katakana lain cukup sama huruf pertamanya."""


def normalize(latin: str, english: bool = False) -> str:
    """Ubah satu kata Latin menjadi bentuk bunyi kasar untuk dibandingkan.

    Args:
        latin: Kata Latin (boleh berhuruf kapital dan berdiakritik).
        english: Tafsirkan juga ejaan vokal bahasa Inggris (ee/ea → i, oo → u,
            au → o, er/ar/ir/ur di depan konsonan atau di akhir → a, ...). Hanya
            untuk jawaban mesin; romanisasi Hepburn sudah fonemis.

    Returns:
        Huruf a-z saja; kosong bila tidak ada huruf Latin.
    """
    return _normalize(latin, english)


def _normalize(latin: str, english: bool = False, *, keep_l: bool = False,
               keep_r: bool = False, devoice: bool = False, keep_e: bool = False) -> str:
    """Isi ``normalize`` dengan pilihan ejaan Eropa (hanya untuk ``_sounds_european``).

    Args:
        latin: Kata Latin.
        english: Lihat ``normalize``.
        keep_l: ``l`` di akhir suku kata tidak dibuang bersama ``r`` non-rotik (Rolf, Arnold).
        keep_r: ``r`` di akhir suku kata dipertahankan (Hildegard, Georg, Bernd).
        devoice: Konsonan akhir d/g/b dibaca t/k/p (Bernd, Gertrud).
        keep_e: ``e`` akhir sesudah konsonan tidak dibuang (ejaan Eropa mengucapkannya:
            Gertrude ≠ Gertrud, George ≠ Georg).
    """
    text = "".join(ch for ch in strip_diacritics(latin.casefold()) if "a" <= ch <= "z")
    text = _INITIAL_SILENT_RE.sub("", text)
    text = _GH_RE.sub("", text)
    text = _SILENT_H_RE.sub("", text)
    if english:
        for pattern, sound in _ENGLISH_VOWELS:
            text = pattern.sub(sound, text)
    for cluster, sound in _CLUSTERS:
        text = text.replace(cluster, sound)
    if keep_l:
        text = text.replace("l", _LIQUID_MARK)
    text = _SOFT_C_RE.sub("s", text).replace("c", "k").translate(_LETTERS)
    text = _Y_GLIDE_RE.sub("", text).replace("y", "i")
    text = _DOUBLE_RE.sub(r"\1", text).replace("ou", "o")
    if len(text) > 2 and text[-1] in FINAL_SILENT_VOWELS and text[-2] not in VOWELS \
            and not (keep_e and text[-1] == "e"):
        text = text[:-1]
    if not keep_r:
        text = _NON_ROTIC_R_RE.sub("", text)
    if devoice and text:
        text = text[:-1] + text[-1].translate(_DEVOICED)
    if keep_l and keep_r:
        return text.replace(_LIQUID_MARK, "r")
    text = text.replace(_LIQUID_MARK, "r")
    return _DOUBLE_RE.sub(r"\1", text)


def similarity(reference: str, answer: str, english: bool = False) -> float:
    """Kemiripan bunyi dua kata Latin, 0 sampai 1.

    Args:
        reference: Romanisasi bacaan kana (sisi yang boleh punya vokal epentetik).
        answer: Ejaan dari mesin.
        english: Teruskan ke ``normalize`` untuk sisi jawaban.

    Returns:
        ``1 − jarak / panjang`` setelah ``normalize``; 0 bila keduanya kosong.
    """
    return _ratio(normalize(reference), normalize(answer, english), epenthetic=True)


def skeleton_similarity(reference: str, answer: str, english: bool = False) -> float:
    """Kemiripan kerangka konsonan (vokal dibuang); 1 bila keduanya tanpa konsonan."""
    ref = _consonants(normalize(reference))
    ans = _consonants(normalize(answer, english))
    if not ref and not ans:
        return 1.0
    return _ratio(ref, ans, epenthetic=False)


def sounds_alike(reference: str, answer: str) -> bool:
    """``True`` bila ``answer`` lolos kedua ambang, dibaca sebagai Hepburn atau Inggris."""
    return any(similarity(reference, answer, english) >= MIN_SIMILARITY
               and skeleton_similarity(reference, answer, english) >= MIN_SKELETON_SIMILARITY
               for english in (False, True))


def validate_foreign_name(kana: str, answer: str) -> str | None:
    """Terima ejaan nama asing dari mesin hanya bila bentuk dan bunyinya cocok.

    Syarat: jumlah kata jawaban sama dengan jumlah bagian katakana (dipisah ・
    atau spasi), tiap kata huruf Latin, dan tiap kata ``sounds_alike`` dengan
    romanisasi Hepburn bagiannya. Kata yang seluruhnya huruf kapital (minimal
    dua huruf) dijadikan Title Case lebih dulu; kata berawalan huruf kecil
    dikapitalkan di awal kata dan sesudah ``-`` atau ``'`` (``scheherazade`` →
    ``Scheherazade``, ``jean-luc`` → ``Jean-Luc``, ``o'brien`` → ``O'Brien``).
    Huruf kecil aman diterima di sini karena syarat bunyi tetap berlaku: kata
    biasa yang artinya saja yang cocok (レオン/``lion``) tetap ditolak.

    Args:
        kana: Tulisan katakana, misalnya ``ジョン・スミス``; setengah lebar
            (``ｼﾞｮﾝ･ｽﾐｽ``) dilebarkan dulu.
        answer: Keluaran mesin, misalnya ``"John Smith."``; ・ dan · dianggap spasi.

    Returns:
        Nama Latin dengan satu spasi antar-bagian, atau ``None`` bila ditolak.
    """
    parts = [part for part in _PART_SEPARATOR_RE.split(widen_halfwidth_kana(kana)) if part]
    words = _PART_SEPARATOR_RE.split(answer.strip(_TRAILING))
    words = [_capitalize_lower(_title_if_shouting(word)) for word in words if word]
    if not parts or len(words) != len(parts) or not is_latin(" ".join(words)):
        return None
    for part, word in zip(parts, words):
        raw_word = "".join(
            ch for ch in strip_diacritics(word.casefold()) if "a" <= ch <= "z"
        )
        reference = kana_to_romaji(part, "plain")
        slavic_devoiced = (
            part.endswith("フ")
            and raw_word.endswith("v")
            and sounds_alike(reference, word[:-1] + "f")
        )
        if (
            not word[0].isupper()
            or raw_word in data.COMMON_ENGLISH_WORDS
            or not (
                sounds_alike(reference, word)
                or slavic_devoiced
                or _sounds_european(part, reference, word)
            )
            or not _keeps_final_vowels(reference, word)
        ):
            return None
    return " ".join(words)


def _sounds_european(kana: str, reference: str, word: str) -> bool:
    """``word`` cocok dengan ``reference`` bila r/l akhir suku kata diucapkan (ejaan Eropa).

    ``normalize`` membuang ``r`` sesudah vokal sebagai ``r`` non-rotik bahasa Inggris
    (Charlotte シャーロット), dan ``l`` ikut terbuang karena l↔r disamakan lebih dulu. Ejaan
    Jerman/Eropa justru mengucapkannya dan katakana menulisnya ル: ヒルデガルト/``Hildegard``,
    ゲオルグ/``Georg``, ベルント/``Bernd``, ロルフ/``Rolf``. Syarat jalur ini (semua):

    - katakana memuat ル + konsonan atau ル di akhir (``_CODA_LIQUID_KANA_RE``; ルーク tidak);
    - r/l akhir suku kata di ejaan sejajar dengan ル itu (``_codas_align``): huruf sesudahnya
      sejalan dengan konsonan sesudah ル (``_EUROPEAN_CODA_FITS``; Rainfall, Marshiness, Halch
      untuk ラインハルト, マルティネス, ハルト tidak);
    - bunyi cocok (``_european_variants``) dengan ambang ``EUROPEAN_MIN_SIMILARITY`` (lebih
      ketat), tanpa potongan biaya s↔t, ambang kerangka sama dengan ``sounds_alike``, dan
      konsonan akhir sama bila bacaan berakhir konsonan (Martinet untuk マルティネス tidak);
    - bukan kata Inggris yang sebunyi dengan nama (``EUROPEAN_DECOY_WORDS``: Cult, Mild, Gold,
      dan ``data.COMMON_ENGLISH_WORDS``);
    - katakana bukan bacaan nama Jepang yang dikenal (``data.name_readings``: ハルト = Haruto,
      bukan ``Halt``/``Hart``);
    - huruf awal ejaan sejalan dengan konsonan awal katakana (``_EUROPEAN_ONSETS``: ゴルト bukan
      ``Jolt``, ハルト bukan ``Fardo``).

    Hanya ``validate_foreign_name`` yang memakainya; ``matches_reading`` (nama Jepang) tidak.
    """
    raw = "".join(ch for ch in unicodedata.normalize("NFD", word.casefold()) if "a" <= ch <= "z")
    letters = raw.replace("y", "i")
    codas = [_romaji_onset(kana_to_romaji(kana[m.end():], "plain"))
             for m in _CODA_LIQUID_KANA_RE.finditer(kana)]
    if (not codas or raw in EUROPEAN_DECOY_WORDS or raw in data.COMMON_ENGLISH_WORDS
            or kata_to_hira(kana) in data.name_readings()
            or not _onset_fits(_romaji_onset(reference), raw)):
        return False
    # th Jerman/Belanda dibaca t (Berthold ベルトルト, Lothar ロタール).
    spellings = [spelling for spelling in dict.fromkeys((letters, letters.replace("th", "t")))
                 if _codas_align(codas, spelling)]
    ref = _normalize(reference, keep_e=True)
    ref_skeleton = _consonants(ref)
    variants = {form for spelling in spellings
                for form in _european_variants(spelling, german_w="ヴ" in kana)}
    for answer in variants:
        if (_ratio(ref, answer, epenthetic=True, near=False) >= EUROPEAN_MIN_SIMILARITY
                and _ratio(ref_skeleton, _consonants(answer), epenthetic=False)
                >= MIN_SKELETON_SIMILARITY
                and (ref[-1] in VOWELS or answer[-1:].translate(_DEVOICED)
                     == ref[-1].translate(_DEVOICED))):
            return True
    return False


def _european_variants(letters: str, *, german_w: bool = False) -> set[str]:
    """Bentuk bunyi ejaan Eropa ``letters`` untuk ``_sounds_european``.

    ``l`` dipertahankan, lalu ``r`` juga, masing-masing dengan dan tanpa pelemahan konsonan akhir
    (``_DEVOICED``). ``e`` akhir dipertahankan (Gertrude dan George bukan Gertrud dan Georg);
    sesudah n/m boleh juga dibuang (Verne ヴェルヌ, Persephone ペルセポネ). ei boleh dibaca ai
    (Reinhard ラインハルト), z boleh dibaca ts (Mozart モーツァルト), dan dt dibaca t (Arndt アルント).
    Bila ``german_w`` (katakana memuat ヴ), w juga boleh dibaca v (Ewald エーヴァルト, Waltraud
    ヴァルトラウト); tanpa ヴ tidak (シューベルト bukan ``Swelt``). Pemanggil sudah mengganti y dengan
    i (Halyard bukan ハラルト).
    """
    keep_e = (True, False) if len(letters) > 2 and letters[-2:] in ("ne", "me") else (True,)
    spellings = {letters, letters.replace("ei", "ai")}
    spellings |= {spelling.replace("z", "ts") for spelling in spellings}
    spellings |= {spelling.replace("dt", "t") for spelling in spellings}
    if german_w:
        spellings |= {spelling.replace("w", "v") for spelling in spellings}
    spellings |= {
        spelling[:-1] + "f" for spelling in spellings if spelling.endswith("v")
    }
    return {_normalize(spelling, keep_l=True, keep_r=keep_r, devoice=devoice, keep_e=final_e)
            for spelling in spellings for keep_r in (False, True) for devoice in (False, True)
            for final_e in keep_e}


def _onset_fits(kana_onset: str, raw: str) -> bool:
    """Huruf awal ejaan ``raw`` sejalan dengan konsonan awal katakana (``_EUROPEAN_ONSETS``).

    ``sh``/``sch`` di awal ejaan hanya untuk シ/シャ (ゾルト bukan ``Short``).
    """
    if raw.startswith(("sh", "sch")) and kana_onset != "sh":
        return False
    return raw.startswith(_EUROPEAN_ONSETS.get(kana_onset, (kana_onset[:1],)))


def _romaji_onset(romaji: str) -> str:
    """Konsonan awal ``romaji`` (sh/ch/ts utuh, selain itu satu huruf), kosong bila diawali vokal.

    ``kya`` → ``k``, ``nto`` (ン + ト) → ``n``, ``shi`` → ``sh``, ``a`` → kosong.
    """
    run = _CONSONANT_RUN_RE.match(romaji)
    cluster = run.group() if run is not None else ""
    return next((digraph for digraph in ("sh", "ch", "ts") if cluster.startswith(digraph)),
                cluster[:1])


def _codas_align(codas: list[str], letters: str) -> bool:
    """Konsonan sesudah tiap ル akhir suku kata (``codas``, dari ``_romaji_onset``) sejalan berurutan
    dengan huruf sesudah r/l akhir suku kata di ``letters`` (``_EUROPEAN_CODA_FITS``). ``r`` ejaan
    yang tidak berpasangan boleh dilewati: katakana menulisnya ー (Arnold アーノルド)."""
    pending = list(codas)
    for match in _CODA_LIQUID_SPELLING_RE.finditer(letters):
        run = _CONSONANT_RUN_RE.match(letters, match.end())
        cluster = run.group() if run is not None else ""
        if pending and _coda_fits(pending[0], cluster):
            pending.pop(0)
        elif match.group() != "r":
            return False
    return not pending


def _coda_fits(kana_consonant: str, cluster: str) -> bool:
    """Huruf ejaan ``cluster`` sesudah r/l sejalan dengan konsonan katakana sesudah ル."""
    allowed = _EUROPEAN_CODA_FITS.get(kana_consonant, (kana_consonant[:1],))
    return cluster == "" if not kana_consonant else cluster.startswith(allowed)


def _keeps_final_vowels(reference: str, word: str) -> bool:
    """Vokal akhir bacaan yang menyusul vokal lain (オリヴィエ ``...ie``) harus terwakili jawaban.

    Vokal itu suku kata sendiri, bukan vokal epentetik, jadi padanan Inggris yang
    membuangnya adalah nama lain: オリヴィエ/``Oliver`` ditolak, ``Olivier`` lolos.
    Jawaban dianggap mewakilinya bila (a) bentuk normalnya (Hepburn atau Inggris) berakhir
    vokal itu tepat sesudah vokal lain (マリア/``Maria``, ノア/``Noah``, ローレライ/``Lorelei``,
    カシオペア/``Cassiopeia``), atau (b) vokal akhirnya ア untuk ``-r`` non-rotik Inggris
    yang vokal di depannya cocok (``_keeps_r_vowel``: セオドア/``Theodore``, シンクレア/
    ``Sinclair``, アリステア/``Alistair``). オリヴィア/``Oliver`` tetap ditolak: ``-er``
    tidak pernah ditulis イア.
    """
    ref = normalize(reference)
    if len(ref) < 2 or ref[-1] not in VOWELS or ref[-2] not in VOWELS or ref[-1] == ref[-2]:
        return True
    for english in (False, True):
        answer = normalize(word, english)
        if len(answer) > 1 and answer[-1] == ref[-1] and answer[-2] in VOWELS:
            return True
    return _keeps_r_vowel(ref, word)


def _keeps_r_vowel(ref: str, word: str) -> bool:
    """Bacaan ``...Va`` (エア, オア, イア, ウア) sebagai ``-r``/``-re`` non-rotik jawaban.

    Katakana menulis ``-r`` non-rotik sesudah vokal sebagai ア, dan vokal sebelum ア
    mengikuti ejaan vokal di depan ``r`` (``R_VOWEL_SPELLINGS``): ``Theodore`` → セオドア
    (``o``), ``Sinclair`` → シンクレア (``ai``), ``Moore`` → ムーア (``oo``).
    """
    letters = "".join(ch for ch in unicodedata.normalize("NFD", word.casefold())
                      if "a" <= ch <= "z")
    match = _R_ENDING_RE.search(letters)
    return (ref[-1] == "a" and match is not None
            and match.group(1) in R_VOWEL_SPELLINGS.get(ref[-2], frozenset()))


def is_hepburn_echo(kana: str, word: str) -> bool:
    """Apakah ``word`` hanya mengulang romanisasi Hepburn ``kana``.

    Dibandingkan tanpa diakritik dan tanpa membedakan panjang vokal (``ou``,
    ``oo``, ``uu``, ... dianggap satu vokal): リョーマ/``Ryoma``, ``Ryouma``,
    dan ``Ryōma`` sama. Jawaban seperti itu menandakan nama Jepang yang ditulis
    katakana, bukan ejaan asing (フェリシア/``Felicia`` bukan gema).

    Args:
        kana: Satu bagian nama katakana tanpa ・.
        word: Satu kata jawaban mesin.
    """
    reference = _collapse_long_vowels(kana_to_romaji(widen_halfwidth_kana(kana), "plain"))
    return bool(reference) and _collapse_long_vowels(word) == reference


def is_near_echo(kana: str, word: str) -> bool:
    """Gema Hepburn yang hanya berbeda karena konsonan ganda (アマネ/``Amanne``, ラナ/``Ranna``).

    Hanya untuk katakana dengan kana Jepang biasa (tanpa ァィゥェォ kecil, ヴ, ヵ, ヶ).
    ``Hannah`` (ハンナ) dan ``Lana`` (ラナ) bukan gema. Fungsi ini hanya pendeteksi; yang
    memutuskan adalah ``pipeline.merge_foreign_answer``, dan gema diganti Hepburn hanya bila
    bagian katakana itu juga ``romaji.looks_japanese``: アマネ/``Amanne`` menjadi ``Amane``,
    sedangkan ラナ/``Ranna`` dan アナ/``Anna`` (nama Barat berkana biasa) dipakai apa adanya.
    """
    if not kana or _NATIVE_KANA_RE.search(widen_halfwidth_kana(kana)):
        return False
    reference = _collapse_long_vowels(kana_to_romaji(widen_halfwidth_kana(kana), "plain"))
    return bool(reference) and _GEMINATE_RE.sub(r"\1", _collapse_long_vowels(word)) == \
        _GEMINATE_RE.sub(r"\1", reference)


def looks_romanized(name: str) -> bool:
    """Apakah setiap kata ``name`` tersusun dari suku kata romanisasi Jepang saja.

    Diakritik (ō, ū) dan apostrof ``n'`` dibuang, konsonan ganda (``pp``, ``tch``) diringkas,
    lalu tiap kata harus habis dipecah menjadi suku kata konsonan(+y) + vokal atau ``n``
    (``m`` sebelum b/p/m: Shimbashi). ``Azumino``, ``Beppu``, ``Jun'ichirō`` lolos;
    ``Cloudy``, ``Field``, ``Mount Fuji`` tidak. Dipakai ``pipeline.clean_name`` hanya bila
    data proyek tidak punya kandidat bacaan sama sekali.
    """
    words = name.split()
    if not words:
        return False
    for word in words:
        decomposed = unicodedata.normalize("NFD", word.casefold())
        letters = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        letters = _GEMINATE_RE.sub(r"\1", letters.replace("'", "").replace("’", ""))
        if not _ROMANIZED_WORD_RE.fullmatch(letters):
            return False
    return True


def matches_reading(reading: str, answer: str) -> bool:
    """Periksa apakah ejaan (huruf besar atau kecil) terdengar seperti bacaan kana.

    Bila jumlah kata sama, tiap kata dibandingkan dengan pasangannya; bila tidak,
    seluruh bacaan dibandingkan dengan seluruh jawaban tanpa spasi. Jawaban juga
    dicoba dengan ``m`` di depan b/p/m dibaca ``n`` (Hepburn ん: ``Namba`` = なんば,
    ``Homma`` = ほんま); bentuk aslinya tetap dicoba lebih dulu (``Emma`` = えま).

    Args:
        reading: Bacaan kana, boleh berspasi (``やまだ たろう``).
        answer: Ejaan Latin dari mesin.
    """
    ref_words = [kana_to_romaji(word, "plain") for word in reading.split()]
    if not ref_words or not answer.split():
        return False
    for form in dict.fromkeys((answer, _HEPBURN_M_RE.sub("n", answer))):
        ans_words = form.split()
        if len(ref_words) == len(ans_words):
            if all(sounds_alike(ref, ans) for ref, ans in zip(ref_words, ans_words)):
                return True
        elif sounds_alike("".join(ref_words), "".join(ans_words)):
            return True
    return False


def _title_if_shouting(word: str) -> str:
    """``FELICIA`` → ``Felicia``, ``O'BRIEN`` → ``O'Brien``; kata lain dibiarkan."""
    if not word.isupper() or sum(ch.isalpha() for ch in word) < 2:
        return word
    return _WORD_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), word.lower())


def _capitalize_lower(word: str) -> str:
    """``jean-luc`` → ``Jean-Luc``; kata yang sudah berawalan kapital dibiarkan (``McCartney``)."""
    if not word[:1].islower():
        return word
    return _WORD_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), word)


def _collapse_long_vowels(latin: str) -> str:
    """Huruf a-z tanpa diakritik dengan vokal panjang diringkas (ryōma, ryouma → ryoma)."""
    decomposed = unicodedata.normalize("NFD", latin.casefold())
    letters = "".join(ch for ch in decomposed if "a" <= ch <= "z")
    return _LONG_VOWEL_RE.sub(lambda m: m.group()[0], letters)


def _consonants(text: str) -> str:
    """Buang vokal dari teks yang sudah dinormalisasi."""
    return "".join(ch for ch in text if ch not in VOWELS)


def _ratio(ref: str, ans: str, *, epenthetic: bool, near: bool = True) -> float:
    """``1 − jarak edit berbobot / panjang terpanjang``, minimal 0 (``near``: lihat
    ``_substitution``)."""
    longest = max(len(ref), len(ans))
    if longest == 0:
        return 0.0
    return max(0.0, 1.0 - _distance(ref, ans, epenthetic, near) / longest)


def _distance(ref: str, ans: str, epenthetic: bool, near: bool = True) -> float:
    """Jarak Levenshtein berbobot (lihat docstring modul)."""
    previous = [float(j) for j in range(len(ans) + 1)]
    for i, ref_ch in enumerate(ref, start=1):
        drop = EPENTHETIC_COST if epenthetic and _is_epenthetic(ref, i - 1) else 1.0
        current = [previous[0] + drop]
        for j, ans_ch in enumerate(ans, start=1):
            current.append(min(previous[j] + drop, current[j - 1] + 1.0,
                               previous[j - 1] + _substitution(ref_ch, ans_ch, near)))
        previous = current
    return previous[-1]


def _is_epenthetic(text: str, index: int) -> bool:
    """Vokal u/o/i yang diapit dua konsonan: kemungkinan sisipan katakana."""
    return (text[index] in EPENTHETIC_VOWELS and 0 < index < len(text) - 1
            and text[index - 1] not in VOWELS and text[index + 1] not in VOWELS)


def _substitution(left: str, right: str, near: bool = True) -> float:
    """Biaya mengganti satu huruf: 0 sama, ``NEAR_COST`` untuk s↔t (bila ``near``), selain itu 1."""
    if left == right:
        return 0.0
    return NEAR_COST if near and {left, right} == {"s", "t"} else 1.0
''')

MODUL['jptrans.pipeline'] = (
    False,
r'''"""Orkestrasi terjemahan: dokumen masuk, ``TranslatedDocument`` keluar.

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
''')

MODUL['jptrans.postprocess'] = (
    False,
r'''"""Perapian hasil terjemahan: tanda baca, kutip, dan tata bahasa di sekitar nama.

Masalah yang ditangani berasal dari keluaran mesin sungguhan
(LAPORAN_RISET 6.1 dan KRITIK_RISET no. 13):

- tanda baca Jepang yang tertinggal (、。！？「」（）) dan spasi lebar penuh U+3000,
- kutip campur gaya LaTeX ````…''``, kutip keriting “…”, dan kutip lurus,
- spasi hilang setelah kutip penutup (``sekolah?"kata Tanaka``),
- artikel bahasa Inggris sebelum nama (``the Tanaka``) dan posesif terpisah
  (``Tanaka 's``),
- klitik bahasa Indonesia yang menempel ke nama (``Tanakanya`` → ``Tanaka-nya``,
  EYD V tanda hubung aturan 5 dan 7),
- huruf kecil di awal kalimat (Google: おはようございます。 → ``good morning.``),
- huruf kapital palsu setelah koma (Google: 美咲ちゃん、おはよう！ →
  ``Misaki-chan, Good morning!``), lihat ``lower_after_comma``,
- kata ganti orang ketiga bergender salah dalam bahasa Inggris (美咲 perempuan →
  ``checked his watch``), lihat ``fix_pronouns``. Kapan kata ganti boleh diubah
  diputuskan pemanggil (``pipeline.pronoun_gender``).
- tanda panjang ``ー`` dan tilde ``〜``/``～`` yang ikut tersalin di belakang huruf Latin
  (``Haiー!``, ``Tunggu〜!``), lihat ``normalize_latin_marks``.

Semua fungsi murni dan idempoten: memanggilnya dua kali memberi hasil sama.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Collection, Iterable, Sequence

from .phonetic import similarity, skeleton_similarity
from .romaji import kana_to_romaji
from .style import DASH_BREAKS

logger = logging.getLogger(__name__)

_JAPANESE_PUNCT = str.maketrans({
    "、": ", ", "，": ", ", "。": ". ", "！": "! ", "？": "? ",
    "「": '"', "」": '"', "『": '"', "』": '"', "（": "(", "）": ")",
    "\u3000": " ",
})
_LATEX_QUOTES_RE = re.compile(r"``(.*?)''")
_CURLY_DOUBLE = str.maketrans({"“": '"', "”": '"', "„": '"'})
_QUOTE_PAIR_RE = re.compile(r'"([^"\n]*)"')
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([,.!?;:%)\]}])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[{])[ \t]+")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_DOUBLE_THE_RE = re.compile(r"\b(the)\s+the\b", re.IGNORECASE)
_LEADING_LOWER_RE = re.compile(
    r"""^([\s"'“‘(\[«""" + re.escape(DASH_BREAKS) + r"""]*)([a-z])"""
)
# Huruf Latin (ASCII sampai Latin Extended-B) tepat sebelum tanda panjang atau tilde.
_LATIN = "A-Za-z\u00c0-\u024f"
_JAPANESE_AFTER_MARK = r"(?![ーｰぁ-ゖァ-ヺｦ-ﾝ\u3400-\u9fff])"
_LONG_MARK_RE = re.compile(rf"(?<=[{_LATIN}])([ーｰ]+){_JAPANESE_AFTER_MARK}")
_DASH_FOLLOWER_RE = re.compile(rf"[ \t]*[{_LATIN}]")
_LATIN_WORD_LEFT_RE = re.compile(rf"[{_LATIN}]*$")
_LATIN_WORD_RIGHT_RE = re.compile(rf"[{_LATIN}]*")
# Rangkaian tilde yang menempel di huruf Latin/angka, boleh bercampur ``~`` dan ``ー`` di
# belakangnya (``Tunggu〜〜!``, ``Hei〜ー!``, ``Tunggu~〜!``); ``ー`` yang disusul huruf
# Jepang tidak ikut (``Kaito〜ーっ``). Juga rangkaian tepat sebelum huruf Latin/angka.
_TILDE_RE = re.compile(
    rf"(?<=[{_LATIN}0-9])~*[〜～](?:[〜～~]|[ーｰ]+{_JAPANESE_AFTER_MARK})*"
    rf"|[〜～][〜～~]*(?=[{_LATIN}0-9])")
_VOWELS = frozenset("aiueoAIUEO")
_EM_DASH = "\u2014"
_EN_ARTICLES = r"(?:[Tt]he|[Aa]n?)"
_ID_CLITICS = r"(?:nya|ku|mu)"

COMMON_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset("""
        Good Thank Thanks Yes No Please The But And Then It It's This That That's What What's
        Why How Where When Who Let's Let Sorry Hello Hi Hey Okay We You You're He She They My
        Your Our Their Is Are Was Were Do Does Did Don't Can Can't Could Would Should So Or If
        Because Well Oh Ah Um Uh Wait Come See Welcome Excuse There Here Now Just
        Really Maybe Of In On At To For With Not Even Still Also Too Very All Some Again Right
        Huh Wow Any Everyone Everything Nothing Something Someone Let's
    """.split()),
    "id": frozenset("""
        Selamat Terima Ya Iya Tidak Bukan Tapi Tetapi Lalu Kemudian Aku Kamu Dia Saya Itu Ini
        Apa Apakah Kenapa Mengapa Bagaimana Siapa Di Ke Dari Dan Atau Jadi Maaf Tolong Ayo
        Halo Hai Oke Baik Kita Kami Mereka Sudah Belum Jangan Ada Senang Sampai Permisi Benar
        Begitu Nah Eh Ah Oh Hm Sekarang Nanti Juga Masih Hanya Kalau Jika Karena Silakan Boleh
        Bisa Mau Akan Sedang Sangat Sekali Wah Aduh Yuk Sama Semua Seperti Untuk Dengan Pada
    """.split()),
}
"""Kata fungsi/kata umum yang hurufnya diturunkan bila muncul kapital setelah koma.

Sengaja tanpa kata yang juga lazim sebagai nama diri (May, Will, Grace, Mari,
kota Nice, permainan Go) dan tanpa "I". Daftar terpisah per bahasa sasaran.
"""
_ROMAJI_KIN = frozenset("""
    Onii Onee Nii Nee Ani Aniki Ane Aneki Okaa Otou Kaa Tou Ojii Obaa Jii Baa Oji Oba
    Oniichan Oneechan Oniisan Oneesan Niisan Neesan Okaasan Otousan Kaasan Tousan Ojiisan
    Obaasan Ojiichan Obaachan Ojisan Obasan
""".split())
"""Sapaan kekerabatan Jepang romaji; bentuk bertanda hubung dicocokkan lewat bagian depannya
(``Onii-chan`` → ``Onii``), karena kata sesudah sapaan berhenti di tanda hubung."""
ALWAYS_CAPITAL: dict[str, frozenset[str]] = {
    "en": frozenset("""
        Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April
        May June July August September October November December Christmas Xmas Easter
        Halloween Thanksgiving Valentine Hanukkah Ramadan Eid Diwali Obon Tanabata Santa
        English Japanese Chinese Korean French German Spanish Italian Russian Portuguese Dutch
        Arabic Hindi Thai Vietnamese Indonesian Malay Filipino Greek Turkish Latin Swedish
        Norwegian Danish Finnish Irish Scottish Welsh American British Canadian
        Australian Mexican Brazilian Indian European Asian African Western Japan America
        England France Germany China Korea Europe Asia Africa Italy Spain Russia Canada India
        Brazil Mexico Australia Indonesia Thailand Vietnam Taiwan Singapore Philippines Egypt
        Greece Hawaii London Paris Tokyo Osaka Kyoto Seoul God Lord Jesus Christ Buddha
        Allah Bible Christian Buddhist Muslim Catholic Shinto Mom Mommy Mum Mummy Dad Daddy
        Mama Papa Mother Father Grandma Grandpa Granny Grandmother Grandfather Aunt Auntie
        Uncle Brother Sister Master Boss Captain Mr Mrs Ms Mx Dr Prof Professor Sir Madam
        Mt St Ste Jr Sr Ft Sensei Senpai
    """.split()) | _ROMAJI_KIN,
    "id": frozenset("""
        Senin Selasa Rabu Kamis Jumat Jum'at Sabtu Minggu Januari Februari Maret April Mei
        Juni Juli Agustus September Oktober November Desember Natal Paskah Lebaran Idulfitri
        Iduladha Imlek Nyepi Waisak Ramadan Ramadhan Halloween Valentine Tanabata Obon Jepang
        Inggris Indonesia Cina Tiongkok Korea Amerika Prancis Perancis Jerman Belanda Rusia
        Italia Spanyol Arab Eropa Asia Afrika Thailand Kanada India Brasil Meksiko Australia
        Vietnam Taiwan Singapura Filipina Mesir Yunani Hawaii London Paris Tokyo Osaka Kyoto
        Seoul Jakarta Bandung Surabaya Yogyakarta Bali Lombok Sumatra Sumatera Kalimantan
        Sulawesi Papua Aceh Medan Semarang Makassar Malang Bogor Depok Bekasi Tangerang
        Batam Palembang Denpasar Tuhan Allah Yesus Kristus Buddha
        Alkitab Alquran Islam Kristen Katolik Hindu Ibu Ayah Bapak Kakak Adik Nenek Kakek
        Paman Bibi Tante Om Mama Papa Bunda Abang Kak Bu Pak Dik Mbak Mas Bang Nek Kek Opa
        Oma Eyang Mbah Pakde Pakdhe Bude Budhe Paklik Bulik Uwak Akang Teteh Tuan Nyonya
        Nona Profesor Sensei Senpai Gn Jl
    """.split()) | _ROMAJI_KIN,
}
"""Kata yang tetap kapital sesudah sapaan (``lower_after_vocative``), sekalipun tanpa nama.

Nama hari, bulan, hari raya, bahasa/bangsa, negara dan kota utama (simetris en/id),
Tuhan dan kitab, sapaan kekerabatan (dipakai sebagai acuan atau sapaan, EYD: ``Ibu
memanggilmu``; juga romaji ``Onii-chan``), gelar sapaan, dan singkatan bertitik di depan
nama (``Mt. Takao``, ``St. Luke's``). Daftar ini hanya melindungi: kata di dalamnya
diperlakukan seperti sebelum aturan sapaan ada. Bahasa Inggris juga mengenali bentuk jamak
``-s`` (``Mondays``); bentuk berapostrof (ASCII atau ``’``) dicocokkan utuh (``Jum'at``) atau
lewat bagian sebelum apostrof (``Mom's``). ``Polish`` sengaja tidak ada (kata kerja
``polish``). Nama diri lain biasanya terlindungi oleh ``_echoes_lead`` atau ``proper_nouns``.
"""
_ID_KIN_COMMON = frozenset({"tiri", "kandung", "angkat"})
_COMMON_NOUN_AFTER: dict[str, dict[str, frozenset[str]]] = {
    "id": {"Minggu": frozenset({"depan", "lalu", "ini", "kemarin"}),
           "Ibu": frozenset({"kota", "jari", "pertiwi"}) | _ID_KIN_COMMON,
           "Ayah": _ID_KIN_COMMON, "Bapak": _ID_KIN_COMMON,
           "Adik": frozenset({"kelas", "tingkat", "ipar"}),
           "Kakak": frozenset({"kelas", "tingkat", "ipar"}),
           "Mas": frozenset({"kawin"})},
}
"""Kata ``ALWAYS_CAPITAL`` yang menjadi kata umum bila disusul kata tertentu (``Minggu
depan``, ``Ibu kota``, ``Adik kelas``, ``Mas kawin``); kata penyusul boleh berklitik
(``Ibu jarimu``). Bentuk ulang berhubung (``Ibu-ibu``) juga kata umum."""
_AFTER_COMMA_RE = re.compile(r"(?<=[,，]) +([A-Z][a-z]*(?:['’][a-z]+)?)\b")
_NEXT_WORD_RE = re.compile(r"\s+([A-Za-z])")
# Kata itu anggota daftar berkoma: diikuti koma, atau "and/or/dan/atau" + kata kapital.
_LIST_ITEM_RE = re.compile(r"[,，]|\s+(?:and|or|dan|atau)\s+[A-Z]")
# Sapaan di awal kalimat: boleh didahului spasi, kutip, kurung, tanda dialog
# (``style.DASH_BREAKS``, sama dengan ``pipeline._LEADING_VOCATIVE_RE``), dan tag format.
_VOCATIVE_PREFIX_RE = re.compile(
    r"""(?:[\s"'“‘(\[«""" + re.escape(DASH_BREAKS) + r"""]|<[^<>\n]*>|\{\\[^{}\n]*\})*""")
# Koma sesudah nama sapaan lalu kata berhuruf awal kapital (grup 1 = kata itu).
_VOCATIVE_WORD_RE = re.compile(rf"[ \t]*[,，][ \t]+([A-Z][{_LATIN}]*(?:['’][{_LATIN}]+)?)")
# Kata berkapital tepat sesudah kata berakhir huruf kecil/angka dan spasi (nama diri).
_MID_CAPITAL_RE = re.compile(
    rf"(?<=[a-z0-9ß-öø-ÿ])[ \t]+([A-Z][{_LATIN}]+(?:['’][{_LATIN}]+)?)")
_APOSTROPHE_RE = re.compile(r"['’]")
# Kata sesudah kata sapaan (huruf Latin beraksen ikut: ``Ōta``).
_VOCATIVE_NEXT_RE = re.compile(rf"\s+([{_LATIN}]+)")
_ID_CLITIC_END_RE = re.compile(rf"{_ID_CLITICS}$")
# Awal sumber sesudah sapaan (sudah NFKC): kata katakana (berhenti di ・) atau kata Latin.
_LEAD_KATAKANA_RE = re.compile("[ァ-ヺ][ァ-ヺー]*")
_LEAD_LATIN_RE = re.compile("[A-Za-z]{2,}")
LEAD_MIN_SIMILARITY = 0.6
"""Ambang ``similarity`` dan ``skeleton_similarity`` kata sesudah sapaan terhadap romanisasi
katakana di awal sumber (``_echoes_lead``). Lebih longgar dari ``phonetic.MIN_SIMILARITY``
karena hanya menentukan kapital, bukan menerima ejaan nama: ``India``/インド (0,6) lolos,
``Get``/ゲーム dan ``Need``/ネット (kerangka 0,5) tidak."""

PRONOUN_FORMS = {
    "m": {"she": "he", "hers": "his", "herself": "himself"},
    "f": {"he": "she", "himself": "herself"},
}
"""Pemetaan kata ganti orang ketiga tunggal ke gender sasaran (his/her diatur terpisah).

Kata ganti objek (him, dan her sebagai objek) sengaja tidak ada: objek hampir
selalu merujuk orang LAIN selain subjek bernama (``Misaki smiled at him``), dan
orang lain itu sering tersirat sehingga tidak terlihat oleh pemanggil.
"""
OBJECT_FOLLOWERS = frozenset("""
    to at in on into onto with without for from by about of over under up down out off away
    around through across along toward towards behind inside outside near beside like as than
    after before and or but so nor yet if when while because since until though although
    whether then there here now too enough today tonight tomorrow yesterday already
    still just once again anymore alone either neither not never a an the this that these those
    some any each all both my your his her our their its me you him them us it go come
    feel cry laugh know be sit stand stay leave think say speak wait try get make see do eat die
    fall immediately quietly tightly gently softly closely carefully quickly slowly firmly warmly
    directly
""".split())
"""Kata setelah "her" yang menandakan "her" objek (dibiarkan), bukan posesif (→ his).

"her" + kata lain (kata benda/adjektiva: ``her bag``, ``her old coat``,
``her very own``, ``her every move``) dianggap posesif. Kata yang bisa benda atau
kerja (smile, look, back) sengaja tidak dimasukkan: dalam narasi, ``her smile``
lebih sering posesif. ``home`` diatur terpisah (``_POSSESSIVE_HOME_AFTER``).
"""
DITRANSITIVE_VERBS = frozenset("""
    give gives gave given giving hand hands handed handing show shows showed shown showing
    tell tells told telling send sends sent sending offer offers offered offering buy buys
    bought buying bring brings brought bringing teach teaches taught teaching ask asks asked
    asking pass passes passed passing lend lends lent lending owe owes owed owing promise
    promises promised promising get gets got getting make makes made making leave leaves left
    leaving pay pays paid paying throw throws threw thrown toss tossed sell sells sold write
    wrote written cook cooked find found save saved wish wished
""".split())
"""Kata kerja dua objek: ``gave her flowers`` adalah objek, bukan posesif."""
_POSSESSIVE_HOME_AFTER = frozenset("""
    to at from into in inside outside near toward towards reach reached
""".split())
"""``her home`` posesif hanya setelah kata ini (``back to her home``; ``took her home`` objek)."""
_PRONOUN_RE = re.compile(r"\b(he|him|his|himself|she|her|hers|herself)\b", re.IGNORECASE)
PARTNER_WORDS = ("girlfriend", "boyfriend", "lover", "sweetheart", "partner", "gf", "bf",
                 "fiance", "fiancé", "fiancee", "fiancée", "darling")
"""Kata benda pacar: bila ada di terjemahan, 彼女/彼 di sumber berarti pacar
(``fix_explicit_pronouns``)."""
_PARTNER_RE = re.compile(r"\b(?:%s)s?\b" % "|".join(PARTNER_WORDS), re.IGNORECASE)
_FOLLOWING_WORD_RE = re.compile(r"[ \t]*([A-Za-z]+)")
_PRECEDING_WORD_RE = re.compile(r"([A-Za-z]+)[ \t]*$")


def tidy(text: str, lang: str, *, straight_quotes: bool = True) -> str:
    """Rapikan tanda baca dan spasi hasil terjemahan.

    Args:
        text: Teks terjemahan (boleh beberapa baris).
        lang: Bahasa sasaran (``id`` atau ``en``); aturan saat ini sama untuk
            keduanya, parameter disediakan agar pemanggil tidak perlu berubah
            bila aturan khusus bahasa ditambahkan.
        straight_quotes: Ubah ````…''`` dan “…” menjadi kutip lurus ``"…"``.

    Returns:
        Teks yang sudah dirapikan, per baris.
    """
    logger.debug("tidy %d karakter (%s)", len(text), lang)
    return "\n".join(_tidy_line(line, straight_quotes) for line in text.split("\n"))


def normalize_latin_marks(text: str) -> str:
    """Rapikan ``ー`` dan ``〜`` Jepang yang menempel di huruf Latin keluaran mesin.

    Mesin kadang menyalin tanda panjang dari ucapan yang dipanjangkan (はーい！ →
    ``Haiー!``). Tanda itu bukan huruf, jadi tidak dihitung sisa, tetapi tetap asing bagi
    pembaca. Aturannya:

    - ``ー``/``ｰ`` (berapa pun) sesudah vokal Latin tanpa diakritik menjadi satu vokal yang
      sama (``Haiー!`` → ``Haii!``), cara menulis pemanjangan yang lazim di subtitle
      Indonesia dan Inggris. Vokal tambahan berhuruf kapital hanya bila kata Latin tempat
      tanda itu menempel seluruhnya kapital dan lebih dari satu huruf (``NOー!`` →
      ``NOO!``); selain itu huruf kecil (``Eー?`` → ``Ee?``, ``Oーi!`` → ``Ooi!``);
    - sesudah konsonan, ``y``, atau vokal bermakron tanda itu dibuang (``Heyー!`` →
      ``Hey!``, ``Kōー`` → ``Kō``);
    - dua tanda atau lebih yang langsung diikuti kata Latin adalah tanda pisah
      (犯人はカイトーーいや → ``Kaitoーーno``), jadi menjadi em dash (``Kaito—no``);
    - rangkaian ``〜``/``～`` yang menempel di huruf Latin atau angka menjadi SATU ``~``,
      termasuk ``~`` dan ``ー`` yang bercampur di belakangnya (``Tunggu〜!`` dan
      ``Tunggu〜〜!`` → ``Tunggu~!``, ``Hei〜ー!`` → ``Hei~!``, ``3〜5`` → ``3~5``).

    Tanda yang diikuti huruf Jepang (``Kaitoーっ``) atau tidak menempel di huruf Latin
    (``ーはい``, ``ね〜``) tidak diubah: itu bagian dari sisa Jepang yang sudah ditangani
    pemeriksaan sisa di pipeline.
    """
    def replace(match: re.Match[str]) -> str:
        """Bentuk pengganti satu deretan tanda panjang Jepang di belakang huruf Latin."""
        marks = match.group(1)
        before = text[match.start() - 1]
        if len(marks) > 1 and _DASH_FOLLOWER_RE.match(text, match.end()):
            return _EM_DASH
        if before not in _VOWELS:
            return ""
        return before if _shouting_word(text, match.start(), match.end()) else before.lower()

    return _TILDE_RE.sub("~", _LONG_MARK_RE.sub(replace, text))


def _shouting_word(text: str, start: int, end: int) -> bool:
    """Kata Latin di sekitar ``text[start:end]`` seluruhnya kapital dan lebih dari satu huruf.

    ``NOー`` dan ``OーI`` kata teriakan (vokal tambahan kapital); ``Eー`` dan ``Oーi`` bukan.
    """
    left = _LATIN_WORD_LEFT_RE.search(text, 0, start)
    right = _LATIN_WORD_RIGHT_RE.match(text, end)
    word = (left.group() if left else "") + (right.group() if right else "")
    return len(word) > 1 and word.isupper()


def fix_names(text: str, names: list[str], lang: str) -> str:
    """Perbaiki tata bahasa di sekitar nama yang sudah dirender.

    - ``en``: buang ``the``/``a``/``an`` tepat sebelum nama (kecuali nama itu
      sendiri diawali "the", mis. "the Royal Capital"), dan rapatkan posesif
      ``Tanaka 's`` → ``Tanaka's``.
    - ``id``: klitik -nya/-ku/-mu yang menempel diberi tanda hubung.

    Args:
        text: Teks terjemahan.
        names: Bentuk nama final (hasil ``Renderer``) yang ada di teks.
        lang: Bahasa sasaran.

    Returns:
        Teks yang sudah diperbaiki.
    """
    for name in sorted(set(names), key=len, reverse=True):
        if not name:
            continue
        escaped = re.escape(name)
        if lang == "en":
            text = _fix_english(text, name, escaped)
        elif lang == "id":
            text = re.sub(rf"(?<!\w)({escaped}){_ID_CLITICS}\b", _hyphenate, text)
    return text


def capitalize_first(text: str) -> str:
    """Jadikan huruf kecil ASCII pertama kalimat huruf besar (boleh didahului kutip/kurung).

    Pemanggil hanya memakainya untuk kalimat yang sumbernya diawali huruf Jepang,
    sehingga nama produk berhuruf kecil di awal kalimat sumber (``jptrans``,
    ``iPhone``) tidak ikut diubah.

    Args:
        text: Satu kalimat terjemahan.

    Returns:
        Kalimat dengan huruf pertama kapital; teks lain tidak berubah.
    """
    return _LEADING_LOWER_RE.sub(lambda m: m.group(1) + m.group(2).upper(), text, count=1)


def lower_after_comma(text: str, lang: str, names: Sequence[str] = ()) -> str:
    """Turunkan huruf kapital palsu tepat setelah koma: ``Misaki-chan, Good morning!``.

    Kata diturunkan hanya bila semua syarat terpenuhi:

    - kata itu (atau bagian sebelum apostrof: ``It's``) ada di ``COMMON_WORDS[lang]``;
    - bukan "I" (``I``, ``I'm``) dan bukan awal nama hasil render (``names``);
    - koma langsung diikuti spasi lalu huruf, jadi awal kutipan baru
      (``, "Good morning!"``) tidak tersentuh;
    - kata berikutnya tidak berhuruf kapital (kecuali awal nama hasil render),
      agar judul bergaya Title Case (``Episode 1, The Beginning``) tidak rusak;
    - kata itu bukan anggota daftar berkoma (diikuti koma, atau ``and``/``or``/
      ``dan``/``atau`` + kata kapital), agar nama diri yang tidak dimasking
      (``Paris, Nice, and Lyon``) tidak ikut diturunkan.

    Args:
        text: Satu kalimat terjemahan.
        lang: Bahasa sasaran (``id`` atau ``en``); bahasa lain tidak diubah.
        names: Bentuk akhir entitas yang dipasang di kalimat itu.

    Returns:
        Teks dengan huruf kapital palsu setelah koma diturunkan.
    """
    words = COMMON_WORDS.get(lang)
    if not words:
        return text

    def lower(match: re.Match[str]) -> str:
        word = match.group(1)
        normalized_word = word.replace("’", "'")
        base = _APOSTROPHE_RE.split(word)[0]
        start, end = match.span(1)
        if (
            base == "I"
            or not (normalized_word in words or base in words)
            or _starts_name(text, start, names)
        ):
            return match.group(0)
        following = _NEXT_WORD_RE.match(text, end)
        if (following and following.group(1).isupper()
                and not _starts_name(text, following.start(1), names)):
            return match.group(0)
        if _LIST_ITEM_RE.match(text, end):
            return match.group(0)
        return match.group(0)[:start - match.start()] + word[0].lower() + word[1:]

    return _AFTER_COMMA_RE.sub(lower, text)


def lower_after_vocative(
    text: str, lang: str, names: Sequence[str] = (), proper: Collection[str] = frozenset(),
    lead: str = "",
) -> str:
    """Turunkan kapital kata pertama sesudah sapaan nama di awal kalimat (``Yūma, Tunggu``).

    Pemanggil (``Translator._finish``) memakainya hanya bila sumber diawali nama orang yang
    dimasking lalu ``、`` (悠真、ちょっと待って。), jadi kata sesudah ``Nama, `` adalah awal
    isi kalimat, bukan awal kalimat baru. Berbeda dari ``lower_after_comma``, kata itu tidak
    harus ada di ``COMMON_WORDS``. Kapital dipertahankan bila kata itu:

    - awal bentuk entitas lain hasil render (``Yui, Tokyo itu jauh.``);
    - kata ganti ``I`` beserta bentuk singkatnya (``Mei, I think so.``, ``I'm``);
    - berhuruf kapital sesudah huruf pertamanya: singkatan (``OK``, ``NHK``) termasuk bentuk
      jamak/posesifnya (``DVDs``, ``NHK's``), dan camelCase (``McDonald's``, ``YouTube``,
      ``O'Neill``), juga bila bagian sesudah tanda hubung berkapital (``Shangri-La``);
    - ada di ``proper``: kata yang di keluaran mesin dokumen yang sama muncul berkapital di
      tengah kalimat (``proper_nouns``), yaitu nama diri yang tidak dimasking;
    - ejaan kata katakana atau Latin yang mengawali sumber sesudah sapaan (``lead``,
      ``_echoes_lead``): nama diri yang tidak dimasking (ロンドン → ``London``);
    - ada di ``ALWAYS_CAPITAL[lang]`` (``_always_capital``), kecuali bentuk kata umumnya
      (``Minggu depan``, ``Ibu kota``, ``Ibu-ibu``);
    - disusul kata berkapital (``New York``), termasuk awal nama hasil render (gelar + nama:
      ``Yui, Professor Itō``, ``Rin, Kak Yuki``); hanya kata ``COMMON_WORDS`` yang disusul
      nama hasil render tetap diturunkan (``Rin, ayo Yuki``);
    - anggota daftar berkoma (``Paris, Nice, and Lyon``), sama seperti ``lower_after_comma``.

    Args:
        text: Satu kalimat terjemahan.
        lang: Bahasa sasaran (``id`` atau ``en``); bahasa lain tidak diubah.
        names: Bentuk akhir entitas yang dipasang di kalimat itu.
        proper: Kata nama diri dari ``proper_nouns``.
        lead: Sumber termasking sesudah ``、`` sapaan (``pipeline.vocative_lead``).

    Returns:
        Teks dengan kapital palsu sesudah sapaan diturunkan; teks lain tidak berubah.
    """
    if lang not in COMMON_WORDS:
        return text
    start = _VOCATIVE_PREFIX_RE.match(text).end()
    name = next((name for name in sorted(names, key=len, reverse=True)
                 if name and text.startswith(name, start)), "")
    match = _VOCATIVE_WORD_RE.match(text, start + len(name)) if name else None
    if match is None or _keeps_vocative_capital(match, lang, names, proper, lead):
        return text
    begin = match.start(1)
    return text[:begin] + text[begin].lower() + text[begin + 1:]


def _keeps_vocative_capital(match: re.Match[str], lang: str, names: Sequence[str],
                            proper: Collection[str], lead: str) -> bool:
    """Apakah kata sesudah sapaan (grup 1 ``match``) harus tetap kapital.

    Aturannya diuraikan di ``lower_after_vocative``; argumen sama dengan fungsi itu.
    """
    text, word = match.string, match.group(1)
    begin, end = match.span(1)
    base = _APOSTROPHE_RE.split(word)[0]
    common = base in COMMON_WORDS[lang]
    hyphen_capital = text[end:end + 1] == "-" and text[end + 1:end + 2].isupper()
    if (base == "I" or any(ch.isupper() for ch in word[1:]) or hyphen_capital
            or word in proper or base in proper or _starts_name(text, begin, names)
            or (not common and _echoes_lead(base, lead))
            or _always_capital(word, base, lang, text, end)):
        return True
    following = _VOCATIVE_NEXT_RE.match(text, end)
    if following and following.group(1)[0].isupper() and (
            not common or not _starts_name(text, following.start(1), names)):
        return True
    return _LIST_ITEM_RE.match(text, end) is not None


def _echoes_lead(base: str, lead: str) -> bool:
    """Apakah ``base`` ejaan kata yang mengawali sumber sesudah sapaan (nama tak dimasking).

    Sumber yang diawali kata Latin (``McDonald'sに``, ``Jr.の``) cocok bila ``base`` diawali
    kata itu (tanpa membedakan kapital). Sumber yang diawali katakana (``ロンドンは``) cocok
    bila romanisasi kata katakana pertamanya (berhenti di ``・``) mirip bunyi ``base``:
    ``similarity`` dan ``skeleton_similarity`` keduanya minimal ``LEAD_MIN_SIMILARITY``,
    dibaca sebagai Hepburn atau Inggris. Kata pinjaman umum juga cocok (コーヒー/``Coffee``),
    jadi kapitalnya dipertahankan seperti sebelum aturan sapaan ada.

    Args:
        base: Kata sesudah sapaan tanpa bagian berapostrof (``India`` dari ``India's``).
        lead: Sumber termasking sesudah ``、`` sapaan; kosong bila tidak diketahui.

    Returns:
        True bila kata itu tampak sebagai ejaan awal sumber.
    """
    head = unicodedata.normalize("NFKC", lead[:40]).lstrip()
    latin = _LEAD_LATIN_RE.match(head)
    if latin:
        return base.casefold().startswith(latin.group().casefold())
    kana = _LEAD_KATAKANA_RE.match(head)
    if kana is None:
        return False
    reading = kana_to_romaji(kana.group(), "plain")
    return any(similarity(reading, base, english) >= LEAD_MIN_SIMILARITY
               and skeleton_similarity(reading, base, english) >= LEAD_MIN_SIMILARITY
               for english in (False, True))


def _always_capital(word: str, base: str, lang: str, text: str, end: int) -> bool:
    """Apakah kata sesudah sapaan ada di ``ALWAYS_CAPITAL`` dan tidak dipakai sebagai kata umum.

    Kata umum: disusul kata ``_COMMON_NOUN_AFTER`` (boleh berklitik: ``Ibu jarimu``), atau
    bentuk ulang berhubung (``Ibu-ibu``, ``Minggu-minggu``). Apostrof tipografis ``’``
    disamakan dengan ``'`` (``Jum’at``).

    Args:
        word: Kata seperti tertulis (``Mom's``, ``Jum'at``).
        base: Bagian sebelum apostrof (``Mom``).
        lang: Bahasa sasaran.
        text: Kalimat utuh.
        end: Indeks akhir kata di ``text``.

    Returns:
        True bila kapitalnya harus dipertahankan.
    """
    words = ALWAYS_CAPITAL.get(lang, frozenset())
    word = word.replace("’", "'")
    plural = lang == "en" and base.endswith("s") and base[:-1] in words
    if not (word in words or base in words or plural):
        return False
    if text[end:end + len(base) + 1].casefold() == "-" + base.casefold():
        return False
    following = _VOCATIVE_NEXT_RE.match(text, end)
    if following is None:
        return True
    common_after = _COMMON_NOUN_AFTER.get(lang, {}).get(base, frozenset())
    after = following.group(1)
    return not (after in common_after or _ID_CLITIC_END_RE.sub("", after) in common_after)


def proper_nouns(texts: Iterable[str]) -> frozenset[str]:
    """Kata berkapital yang muncul di tengah kalimat di salah satu ``texts`` (nama diri).

    "Di tengah kalimat" berarti tepat sesudah kata yang berakhir huruf kecil atau angka dan
    spasi (``pergi ke Narnia``); kata sesudah koma, titik, kutip, penanda ``[[E1]]``, atau di
    awal teks tidak dihitung, jadi kapital palsu ``Nama, Tunggu`` di kalimat lain tidak
    dianggap nama diri. ``I`` dan bentuk singkatnya serta singkatan berhuruf kapital semua
    diabaikan (aturannya sendiri di ``lower_after_vocative``).

    Args:
        texts: Keluaran mesin (boleh masih berpenanda) untuk semua kalimat dokumen.

    Returns:
        Himpunan kata itu, persis seperti ditulis (``Narnia``).
    """
    found: set[str] = set()
    for text in texts:
        for match in _MID_CAPITAL_RE.finditer(text):
            word = match.group(1)
            if not word.isupper() and _APOSTROPHE_RE.split(word)[0] != "I":
                found.add(word)
    return frozenset(found)


def fix_pronouns(text: str, gender: str) -> str:
    """Samakan kata ganti orang ketiga tunggal bahasa Inggris dengan ``gender``.

    he/his/himself ↔ she/her/hers/herself, dengan kapitalisasi dipertahankan
    (``He`` → ``She``, ``HE'S`` → ``SHE'S``). Aturan:

    - Kata ganti objek tidak pernah diubah: ``him``, dan ``her`` yang objek
      (diikuti tanda baca, akhir teks, kata di ``OBJECT_FOLLOWERS``, atau
      didahului kata kerja dua objek: ``gave her flowers``). Objek hampir selalu
      merujuk orang lain selain subjek bernama, termasuk orang yang tersirat.
    - f → m: ``her`` posesif (diikuti kata benda/adjektiva) → ``his``; ``hers`` →
      ``his``; ``she`` → ``he``; ``herself`` → ``himself``.
    - m → f: ``his`` + tanda baca atau akhir teks → ``hers``; ``his`` + kata apa pun
      → ``her`` (``his home``, ``his very own`` tetap posesif); ``he`` → ``she``;
      ``himself`` → ``herself``.

    Teks di dalam kutip lurus (``"…"``, dialog) tidak diubah karena kata ganti di
    dialog bisa merujuk orang lain; kutip yang tidak ditutup dianggap berlanjut
    sampai akhir teks. Fungsi ini tidak memeriksa apakah kalimat memang hanya
    membicarakan satu orang; itu tugas pemanggil.

    Args:
        text: Satu kalimat terjemahan bahasa Inggris (kutip sudah diluruskan).
        gender: ``"m"`` atau ``"f"``; nilai lain membuat teks tidak berubah.

    Returns:
        Teks dengan kata ganti yang sudah disamakan.
    """
    if gender not in PRONOUN_FORMS:
        return text
    pieces = text.split('"')
    for index in range(0, len(pieces), 2):
        pieces[index] = _PRONOUN_RE.sub(lambda m: _swap_pronoun(m, gender), pieces[index])
    return '"'.join(pieces)


def fix_explicit_pronouns(text: str, gender: str, count: int) -> str:
    """Samakan SEMUA kata ganti orang ketiga tunggal Inggris dengan kata ganti eksplisit sumber.

    Dipakai bila kalimat sumber memuat 彼 atau 彼女 secara eksplisit (``pipeline.explicit_pronoun``):
    kata ganti di terjemahan adalah padanan langsung kata itu. Hanya berjalan bila jumlah kata
    ganti he/him/his/himself/she/her/hers/herself di ``text`` (termasuk di dalam kutip) sama
    dengan ``count``; selain itu teks dibiarkan, karena terjemahan menambah atau membuang rujukan
    (refleksif 自分, orang tersirat). Berbeda dengan ``fix_pronouns``, kata ganti objek ikut
    diubah: 彼を/彼に → ``him``, 彼女を → ``her``. Terjemahan yang memuat kata benda pacar
    (``PARTNER_WORDS``: ``his girlfriend``, ``her boyfriend``) dibiarkan: 彼女/彼 di sumber
    berarti pacar, dan kata ganti terjemahan merujuk subjek, bukan 彼女/彼.

    - m: ``her`` objek → ``him``, ``her`` posesif → ``his``, ``hers`` → ``his``, ``she`` →
      ``he``, ``herself`` → ``himself``.
    - f: ``him`` → ``her``, ``his`` → ``her``/``hers``, ``he`` → ``she``, ``himself`` →
      ``herself``.

    Args:
        text: Satu kalimat terjemahan bahasa Inggris.
        gender: ``"m"`` atau ``"f"``; nilai lain membuat teks tidak berubah.
        count: Jumlah kata ganti eksplisit di sumber.

    Returns:
        Teks dengan kata ganti yang sudah disamakan.
    """
    if (gender not in PRONOUN_FORMS or count < 1 or len(_PRONOUN_RE.findall(text)) != count
            or _PARTNER_RE.search(text)):
        return text
    return _PRONOUN_RE.sub(lambda m: _swap_pronoun(m, gender, objects=True), text)


_PREDICATIVE_COPULAS = frozenset({
    "is", "was", "were", "are", "be", "been", "not", "all", "always", "never",
})
_PREDICATIVE_CONJUNCTIONS = frozenset({
    "and", "or", "but", "yet", "so", "for", "nor", "alone", "too", "instead", "though",
})


def _swap_pronoun(match: re.Match[str], gender: str, *, objects: bool = False) -> str:
    """Ganti satu kata ganti bila gendernya berlawanan, dengan kapitalisasi semula."""
    word = match.group(1)
    lower = word.lower()
    if gender == "m" and lower == "her":
        if _is_object_her(match):
            if not objects:
                return word
            new = "him"
        else:
            new = "his"
    elif objects and gender == "f" and lower == "him":
        new = "her"
    elif gender == "f" and lower == "his":
        following = _FOLLOWING_WORD_RE.match(match.string, match.end())
        preceding = _PRECEDING_WORD_RE.search(match.string, 0, match.start())
        before = preceding.group(1).lower() if preceding else ""
        is_predicative = following is None or (
            following.group(1).lower() in _PREDICATIVE_CONJUNCTIONS
            and before in _PREDICATIVE_COPULAS
        )
        new = "hers" if is_predicative else "her"
    else:
        new = PRONOUN_FORMS[gender].get(lower, lower)
    if new == lower:
        return word
    if word.isupper() and len(word) > 1:
        return new.upper()
    return new.capitalize() if word[0].isupper() else new


def _is_object_her(match: re.Match[str]) -> bool:
    """Apakah ``her`` ini objek (dibiarkan), bukan posesif."""
    following = _FOLLOWING_WORD_RE.match(match.string, match.end())
    if following is None:
        return True
    after = following.group(1).lower()
    preceding = _PRECEDING_WORD_RE.search(match.string, 0, match.start())
    before = preceding.group(1).lower() if preceding else ""
    if after == "home":
        return before not in _POSSESSIVE_HOME_AFTER
    return after in OBJECT_FOLLOWERS or before in DITRANSITIVE_VERBS


def _starts_name(text: str, index: int, names: Sequence[str]) -> bool:
    """Apakah salah satu nama hasil render dimulai tepat di ``index``."""
    return any(name and text.startswith(name, index) for name in names)


def _tidy_line(line: str, straight_quotes: bool) -> str:
    """Rapikan satu baris (urutan langkah penting agar hasilnya idempoten)."""
    line = normalize_latin_marks(line).translate(_JAPANESE_PUNCT)
    if straight_quotes:
        line = _LATEX_QUOTES_RE.sub(r'"\1"', line).translate(_CURLY_DOUBLE)
    line = _QUOTE_PAIR_RE.sub(_space_quote_pair, line)
    line = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", line)
    line = _SPACE_AFTER_OPEN_RE.sub(r"\1", line)
    line = _DOUBLE_THE_RE.sub(r"\1", line)
    return _MULTI_SPACE_RE.sub(" ", line).strip()


def _space_quote_pair(match: re.Match[str]) -> str:
    """Rapatkan isi kutip dan beri spasi di luar kutip bila menempel ke huruf."""
    source = match.string
    before = " " if match.start() > 0 and source[match.start() - 1].isalnum() else ""
    after = " " if match.end() < len(source) and source[match.end()].isalnum() else ""
    return f'{before}"{match.group(1).strip()}"{after}'


def _fix_english(text: str, name: str, escaped: str) -> str:
    """Aturan bahasa Inggris untuk satu nama."""
    if not name.lower().startswith("the "):
        text = re.sub(rf"\b{_EN_ARTICLES}\s+(?={escaped}(?!\w))", "", text)
    return re.sub(rf"({escaped})\s+(['’]s)\b", r"\1\2", text)


def _hyphenate(match: re.Match[str]) -> str:
    """``Tanakanya`` → ``Tanaka-nya``."""
    name = match.group(1)
    return f"{name}-{match.group(0)[len(name):]}"
''')

MODUL['jptrans.protect'] = (
    False,
r'''"""Melindungi entitas dari mesin penerjemah dengan penanda ``[[E1]]``.

Alur per kalimat:

1. ``EntityMatcher.mask``: setiap nama dari glosarium (beserta honorifik dan
   sufiks yang menempel, mis. 田中さん達 atau 東京駅) diganti satu penanda.
   Slot yang sama (entri + honorifik + sufiks) memakai nomor yang sama.
2. Teks berpenanda dikirim ke mesin.
3. ``restore``: penanda dicari dengan regex toleran (mesin kadang menulis
   ``[E1]``, ``[[ e1 ]]``, atau ``［［Ｅ１］］``), lalu diganti hasil ``Renderer``.
   Pemulihan berdasarkan NOMOR, bukan posisi, karena mesin memindahkan
   urutan penanda mengikuti tata bahasa sasaran.
4. Bila ada penanda yang hilang: ``PlaceholderError``. Pipeline lalu memakai
   jalur cadangan ``presubstitute`` (bentuk Latin final disisipkan ke teks
   Jepang) dan memeriksa hasilnya dengan ``check_presubstituted``.

Format ``[[E1]]`` dipilih dari eksperimen (LAPORAN_RISET 6.1): lolos 27/27
di Google dan 4/4 di MyMemory, sedangkan angka polos dan karakter PUA rusak.
"""

from __future__ import annotations

import enum
import html
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping

from . import data
from .disambig import (
    HONORIFIC_SURFACES,
    PEOPLE_SUFFIXES,
    PLACE_KINDS,
    PLACE_SUFFIXES,
    TITLE_WORDS,
    VERB_AFTER_CHARS,
    VERB_CONTEXT_CHARS,
    honorific_fits,
    is_known_name,
    is_verb_stem,
    verb_run_before_honorific,
)
from .errors import PlaceholderError
from .glossary import BUILTIN_SOURCE, STRONG_SOURCE_MARK, USER_SOURCE
from .models import PERSON, PLACE, GlossaryEntry, Masked, Slot
from .textnorm import (
    is_hiragana,
    is_kana,
    is_kanji,
    is_katakana,
    narrow_katakana,
    search_key,
    strip_diacritics,
)

logger = logging.getLogger(__name__)

TOKEN_TEMPLATE = "[[E{}]]"
TOKEN_RE = re.compile(
    r"\[(?:\s*\[)?\s*E\s*(\d+)\s*(?:[:=][^\[\]\n]{0,60})?\](?:\s*\])?",
    re.IGNORECASE,
)
"""Penanda toleran: ``[[E1]]``, ``[E1]``, ``[[ e1 ]]``, termasuk anotasi ``[[E1:nama]]``."""

# Bentuk lebar penuh yang kadang dikembalikan mesin: ［［Ｅ１］］.
_FULLWIDTH_TOKEN_CHARS = str.maketrans(
    {
        "［": "[",
        "］": "]",
        "Ｅ": "E",
        "ｅ": "e",
        "：": ":",
        "＝": "=",
        **{chr(0xFF10 + d): str(d) for d in range(10)},
    }
)
EXACT_TOKEN_RE = re.compile(r"\[\[E(\d+)\]\]")
"""Penanda persis seperti yang dibuat ``mask`` (``TOKEN_TEMPLATE``); grup 1 = nomor."""
# Penanda beserta tanda panjang yang menempel di belakangnya (``[[E1]]ー,``): mesin
# menyalin ー dari sumber (美咲ー、) atau menambahkannya sendiri. Grup ``tail`` = tanda itu;
# yang dipertahankan diputuskan satu aturan, ``_marker_tail``.
_MARKER_TAIL = r"(?P<tail>[ーｰ]*)"
_TOKEN_TAIL_RE = re.compile(TOKEN_RE.pattern + _MARKER_TAIL, TOKEN_RE.flags)
_EXACT_TOKEN_TAIL_RE = re.compile(EXACT_TOKEN_RE.pattern + _MARKER_TAIL, EXACT_TOKEN_RE.flags)
# Huruf (Latin atau Jepang) sesudah ``ーー`` di keluaran mesin: tanda pisah (``[[E1]]ーーno``,
# ``[[E1]]ーーいや``), bukan teriakan.
_LETTER_AFTER_DASH_RE = re.compile(r"[ \t]*[^\W\d_]")
_SPACES_RE = re.compile(r"[ \t\u3000]{2,}")
# ら hanya jamak bila tidak memulai kata lain (アリスらしい, 田中られる).
_SUFFIX_LOOKAHEAD = {"ら": "(?![しれ])"}
# Penanda di awal teks (boleh didahului kutip/kurung) dirender dengan huruf kapital.
_SENTENCE_START_RE = re.compile(r"""[\s"'“‘(\[«]*""")
_LONG_VOWELS = frozenset("ーｰ")
_SOKUON = frozenset("ッｯっ")
# Ekor teriakan setelah nama: deretan tanda panjang dan sokuon (アリスーッ！, アリスーー).
# っ hiragana (ユキっ！, ユキーっ！) hanya dihitung bila ekornya diserap ke slot
# (``_shout_end``); batas kanan nama (``_shouted``) hanya mengenal ー/ッ.
_SHOUT_TAIL_RE = {
    False: re.compile("[ーｰッｯ]+"),
    True: re.compile("[ーｰッｯっ]+"),
}
# Satu ー saja hanya teriakan bila langsung diikuti tanda seru/tanya, elipsis, atau ～
# (マリー！). Sebelum partikel, huruf lain, 、。」, atau akhir teks kata+ー lebih sering
# kata lain (マリーは = Marie, ミラー。 = cermin), jadi ditolak.
_SHOUT_END_CHARS = frozenset("！？!?…‥～〜‼⁉♪")
# Yang boleh menyusul ekor teriakan agar ekornya masuk slot: tanda teriakan, tanda baca
# penutup, kurung/kutip penutup, spasi, atau akhir teks. Sebelum huruf lain ーー adalah
# tanda pisah (田中ーーいや) dan ッ/っ awal kata berikutnya (ユキッて, 田中ッ子): dibiarkan.
_SHOUT_FOLLOWERS = _SHOUT_END_CHARS | frozenset("、。，．,.､｡」』）)］]】〉》〕\"'”’ \t\u3000\r\n")
# Honorifik ber-ん yang bisa dipanjangkan saat berteriak (田中さーん, ケンちゃーん).
_ELONGATED_HONORIFICS = ("さん", "くん", "ちゃん", "たん")
# Huruf unit kota/kabupaten di dalam sisa alamat (松本市内, 木曽郡上松町, 廿日市市).
_ADDRESS_UNIT_CHARS = frozenset("市区町村郡")
# Huruf kana yang tetap bagian nama tempat di tengah alamat (鎌ケ谷市, 市ヶ谷).
_ADDRESS_INNER_CHARS = frozenset("ヶケヵ")
_BARE_NAME_FOLLOWERS = frozenset("がはものにをへとやでかよねだじなっ")
"""Hiragana yang boleh menyusul nama satu kanji tanpa honorifik (翔が, 哲って, 開の).

Hiragana lain sesudah entri satu kanji non-pengguna adalah okurigana (来る, 持ち主, 見せて,
歩いて): kanjinya bagian kata kerja/kata biasa, bukan nama. Dipakai ``_bare_word``."""
_BARE_NAME_PARTICLES = ("まで", "しか", "さえ", "すら", "こそ", "ばかり", "ほど", "くらい",
                        "ぐらい")
"""Partikel berhuruf banyak yang awalnya tidak ada di ``_BARE_NAME_FOLLOWERS`` tetapi lazim
sesudah nama (翔まで, 哲しか, 玲さえ, 舜こそ, 潤ばかり, 徹ほど, 慧くらい)."""
_TTE_STEMS = frozenset("立待持勝打保育討撃放断絶建発裁治直通帰入取切言会渡回移残戻減写映成下")
"""Kanji kata kerja yang bentuk -te/-ta-nya kanji + って/った (勝って, 待って, 治って, 渡った).

Sesudah kanji lain, って adalah partikel kutipan (歩って誰？, 響って呼んで), jadi nama yang
dikenal tetap dimasking. Dipakai ``_bare_word``."""
# ら/たち setelah tempat bawaan hanya jamak orang bila disusul partikel ini atau bukan kana;
# selain itu ia awal kata lain (福島らへん, 宮崎らーめん, 千葉たちうお).
_PLURAL_KANA = frozenset({"ら", "たち"})
_PLURAL_FOLLOWERS = frozenset("はがをにのともでやかへだ")
_NOT_PLURAL_WORDS = ("へん",)
# Akhir unit wilayah: nama tempat sesudahnya adalah kata baru (愛知県豊田市, 北海道札幌市).
_ADMIN_ENDINGS = frozenset("都道府県")
# Nama tempat tanpa sufiks yang sendiri sudah unit wilayah (北海道). 京都/東京 sengaja tidak:
# 都 di situ bagian nama kota, bukan sufiks wilayah (京都大阪 bukan alamat).
_ADMIN_NAME_ENDINGS = ("道",)
# Sufiks kota yang boleh menjadi bagian kunci peta masking (松本市 → entri 松本).
_MUNICIPALITY_ENDINGS = frozenset("市区町村")
ADDRESS_TAILS = ("出身", "在住", "在勤", "生まれ", "育ち", "産")
"""Kata yang boleh menempel langsung sesudah tempat atau alamat tanpa membatalkannya.

静岡県浜松市出身 dan 愛知県豊田市在住 tetap satu alamat (``Kota Hamamatsu, Prefektur Shizuoka``),
静岡県出身 dan 浜松出身 tetap dimasking; ekornya diterjemahkan mesin. 産 hanya bila tidak
disusul kanji (静岡県産のお茶, bukan 静岡県産業). Kanji lain (松本市内, 札幌市中央区) tetap
membatalkan seperti sebelumnya. Lihat ``_address_tail``."""
HOUSE_CHI = "ち"
"""Bentuk lisan 家 sesudah honorifik orang: 田中さんち = rumah (keluarga) Tanaka-san."""
HOUSE_TEXT = "の家"
"""Pengganti ``HOUSE_CHI`` di teks termasking: ``[[E1]]の家`` (mesin menerima kalimat gramatikal)."""
_HOUSE_HONORIFICS = frozenset({"san", "kun", "chan"})
FESTIVAL_HONORIFIC = "くん"
KUNCHI_FESTIVALS = frozenset({"長崎", "唐津"})
"""Tempat yang + くんち adalah nama festival (長崎くんち, 唐津くんち): tempat itu tidak dibaca nama
keluarga + くん, sehingga ち juga bukan "rumah" (``EntityMatcher._accept``). Tempat bawaan lain
yang juga nama keluarga tetap dibaca orang + rumah (千葉くんちに = ke rumah Chiba-kun)."""
_HOUSE_FOLLOWERS = frozenset("のにでへはもをとよねさぞだじ、。，．,.！？!?…‥」』）) \t\u3000\r\n")
"""Huruf sesudah ち yang menandakan 〜さんち "rumah" (田中さんちに, 田中さんちだよ, 田中さんちじゃない),
bukan ちょっと/ちゃんと. Kanji sesudahnya juga (田中さんち行こう: partikel lisan yang dihilangkan)."""
_HOUSE_UNLESS: dict[str, tuple[str, ...]] = {
    "が": ("う", "わ", "え", "っ", "い", "お"),
    "か": ("い", "く", "け", "か", "っ", "づ", "よ"),
    "な": ("み",),
    "く": ("し", "わ", "ち", "び"),
    "ま": ("ち", "き", "み"),
    "や": ("ほ",),
}
"""Huruf sesudah ち yang menandakan rumah KECUALI disusul huruf di sini, karena ち lalu menjadi awal
kata lain: ちがう/ちがった (違う), ちかい/ちかく (近い), ちなみに, ちくしょう, ちくわ, ちまちま, ちまき,
ちやほや. Bentuk rumah: 田中さんちが近い, 田中さんちかな, 田中さんちから (dari rumah), 田中さんちなの,
田中さんちくらい, 田中さんちまで, 田中さんちや公園."""
_HOUSE_ONLY_IF: dict[str, tuple[str, ...]] = {"っ": ("て",)}
"""Huruf sesudah ち yang menandakan rumah HANYA bila disusul huruf di sini: 田中さんちって (rumah),
tetapi ちっとも, ちっちゃい, ちっこい, ちっさい adalah kata lain."""


class _NotAddress(enum.Enum):
    """Jenis penanda ``_NOT_ADDRESS`` (satu anggota, agar bisa diberi type hint)."""

    TOKEN = enum.auto()


_NOT_ADDRESS = _NotAddress.TOKEN
"""Hasil ``EntityMatcher._address``: aturan alamat tidak berlaku, pemeriksaan biasa berlanjut."""


class EntityMatcher:
    """Pencari entitas glosarium di teks Jepang.

    Regex berupa alternasi semua tulisan (terpanjang dulu) diikuti honorifik
    dan sufiks opsional: ``(?P<name>...)(?P<hon>...)?(?P<suf>...)?``.

    Aturan batas kata (bahasa Jepang tidak memakai spasi):

    - Nama yang diawali kanji ditolak bila karakter sebelumnya kanji
      (小田中 bukan 小 + 田中), kecuali tempat setelah unit wilayah
      都/道/府/県 (愛知県豊田市).
    - Tanpa honorifik/sufiks, nama yang diakhiri kanji ditolak bila diikuti
      kanji (田中央 bukan 田中 + 央), kecuali orang yang diikuti gelar
      ``TITLE_WORDS`` (佐藤部長): gelarnya dibiarkan untuk mesin.
    - Nama katakana ditolak bila diapit katakana lain (アリス di dalam アリスト),
      kecuali teriakan ーー/ッ setelah nama (アリスーッ！). Satu ー hanya
      teriakan bila langsung diikuti tanda seru/tanya, elipsis, atau ～
      (マリー！ dengan glosarium yang hanya punya マリ) dan nama+ー bukan kata
      serapan di ``loanwords.json`` (ミラー！ = cermin). Sebelum partikel,
      huruf lain, 、。」, atau akhir teks tetap menolak (マリーは = nama lain,
      ミラー。). Entri yang lebih panjang selalu menang karena alternasi regex
      terpanjang dulu. Tanda teriakan ikut masuk slot dan tidak dirender
      (``アリスーーッ！`` → ``[[E1]]！`` → ``Alice!``; juga 田中ーッ！), jadi
      mesin tidak pernah menerima ー/ッ yang menempel ke penanda.
    - Kunci peta = tulisan entri tempat + 市/区/町/村 (``pipeline.admin_stem_entry``:
      kunci 松本市, entri 松本) menghasilkan ``Slot(松本, "", "市")``.
    - Unit wilayah yang langsung diikuti tempat dikenal yang tidak bisa dirender
      (愛知県 + 刈谷市 tanpa bacaan) tidak dimasking: seluruh alamat dikirim
      apa adanya ke mesin, bukan ``Aichi県刈谷市``.
    - Tempat bawaan yang tulisannya juga nama keluarga di ``surnames.json``
      (山口, 千葉, 町田, 豊田) dicocokkan sebagai orang bila langsung diikuti
      honorifik, sufiks orang (家, 一家, 達, たち, ら), atau gelar
      (山口家 → keluarga Yamaguchi). ら/たち hanya dihitung bila disusul
      partikel atau bukan kana (福島らへん, 宮崎らーめん tetap tempat).
      Konteks lain tetap tempat (山口県, 千葉駅, 山口に). Entri pengguna tidak
      pernah ditafsir ulang.
    - Rangkaian alamat: tempat yang diakhiri unit wilayah 都/道/府/県 (北海道,
      愛知県) dan langsung diikuti tempat lain yang dikenal menjadi SATU slot
      (``Slot.parents``), dirender dari unit terkecil: ``Kota Toyota,
      Prefektur Aichi``. Rangkaian dibatalkan bila sesudahnya masih ada kanji
      (北海道札幌市中央区): sisa itu akan menempel ke unit terbesar. Pengecualian:
      ``ADDRESS_TAILS`` (静岡県浜松市出身, 愛知県豊田市在住) tidak membatalkan rangkaian,
      sufiks tempat (静岡県出身), maupun tempat tanpa sufiks (浜松出身).
    - 〜さんち/〜くんち/〜ちゃんち (田中さんちの犬): ち sesudah orang + honorifik itu, bila
      disusul partikel/kopula/tanda baca/kanji (``_house_chi``), diganti ``HOUSE_TEXT``
      (``[[E1]]の家の犬``); ちがう/ちかく/ちょっと tidak. Tempat bawaan + くんち (長崎くんち,
      festival) tetap tempat tanpa honorifik: ``[[E1]]くんち``.
    - Honorifik kanji yang diikuti kanji (殿下, 君子, 様子) bukan honorifik.
    - Sufiks jamak/keluarga untuk PERSON atau nama yang berhonorifik
      (千葉さん達); sufiks tempat hanya untuk PLACE dan ORG; sufiks yang
      diikuti kanji (田中達也) bukan sufiks. Sufiks yang tidak cocok
      diabaikan, lalu batas kanan diperiksa seperti biasa. Untuk tempat,
      sufiks yang menempel ke kata lain (星見市内, 東京駅前) dibiarkan di teks
      dan namanya tetap dimasking.
    - Katakana setengah lebar (ｱﾘｽ) cocok dengan entri lebar penuh.
    - ``allow_compound`` pada entri mematikan semua pemeriksaan batas.
    - Entri orang satu kanji yang bukan milik pengguna diperiksa konteksnya
      (``_not_this_entity``): kata kerja + ん (駅まで歩くんですか) dan okurigana (持ってきた)
      tidak dimasking.

    Args:
        surface_map: Tulisan (surface dan alias) → entri, biasanya dari
            ``Glossary.surface_map()``.
        named: Tulisan yang terbukti nama di dokumen ini (``ner.attested_names``);
            kemunculan yang konteksnya ambigu ikut dibaca nama.
    """

    def __init__(self, surface_map: Mapping[str, GlossaryEntry],
                 named: frozenset[str] = frozenset()) -> None:
        self._named = named
        self._entries = _with_halfwidth_forms(surface_map)
        self._pattern = _build_pattern(self._entries) if self._entries else None
        self._as_person = _surname_readings_of_builtin_places(self._entries.values())

    def mask(
        self, text: str, can_render: Callable[[GlossaryEntry], bool] | None = None
    ) -> Masked:
        """Ganti setiap entitas dengan penanda ``[[E#]]``.

        Args:
            text: Kalimat Jepang.
            can_render: Penyaring entri; entri yang ditolak tidak dimasking.

        Returns:
            Teks berpenanda beserta slotnya. Tanpa entitas, ``text`` sama
            dengan ``original`` dan ``slots`` kosong.
        """
        if self._pattern is None:
            return Masked(original=text, text=text, slots={})
        ids: dict[Slot, int] = {}
        pieces: list[str] = []
        emitted = 0
        match = self._pattern.search(text)
        while match is not None:
            found = self._accept(text, match, can_render)
            if found is None:
                # Kecocokan ditolak: coba lagi mulai karakter berikutnya.
                match = self._pattern.search(text, match.start() + 1)
                continue
            slot, end = found
            if slot is None:
                # Alamat yang sengaja dibiarkan utuh untuk mesin (``_address``).
                match = self._pattern.search(text, end)
                continue
            number = ids.setdefault(slot, len(ids) + 1)
            pieces += [text[emitted:match.start()], TOKEN_TEMPLATE.format(number)]
            emitted = end
            if _house_chi(text, end, slot):
                # 田中さんちに → [[E1]]の家に: ち bukan sisa nama, tetapi "rumah".
                pieces.append(HOUSE_TEXT)
                emitted = end + len(HOUSE_CHI)
            match = self._pattern.search(text, emitted)
        pieces.append(text[emitted:])
        slots = {number: slot for slot, number in ids.items()}
        return Masked(original=text, text="".join(pieces), slots=slots)

    def _accept(
        self,
        text: str,
        match: re.Match[str],
        can_render: Callable[[GlossaryEntry], bool] | None,
    ) -> tuple[Slot | None, int] | None:
        """Periksa satu kecocokan regex; kembalikan (slot, posisi akhir) atau ``None``.

        Slot ``None`` berarti teks sampai posisi akhir sengaja tidak dimasking dan
        pencarian dilanjutkan dari sana (alamat yang tidak bisa dirangkai).
        """
        name = match["name"]
        entry = self._entries[name]
        if can_render is not None and not can_render(entry):
            return None
        hon = match["hon"] or ""
        suffix = match["suf"] or ""
        if hon == FESTIVAL_HONORIFIC and entry.kind == PLACE and name in KUNCHI_FESTIVALS \
                and text.startswith(HOUSE_CHI, match.end("hon")):
            # 長崎くんち, 唐津くんち: nama festival (tempat + くんち), bukan orang + rumah.
            hon = ""
        if _not_this_entity(entry, text, match, self._named):
            return None
        inner = _inner_suffix(name, entry)
        if inner or not honorific_fits(hon, text, match.end("hon")):
            hon, suffix = "", ""
        name_end = match.end("name")
        # Batas kiri memakai entri asli: tempat bawaan setelah 都道府県 tetap diterima
        # walau konteksnya orang (千葉県山口さん, perilaku lama).
        if not entry.allow_compound and _blocked_left(text, match.start(), name, entry):
            return None
        entry = self._person_in_context(entry, hon, suffix, text, match)
        if inner and name_end < len(text) and is_kanji(text[name_end]) \
                and not _address_tail(text, name_end):
            # 松本市内, 松本市民: seperti 星見市内, sufiks yang menempel ke kata lain
            # dibiarkan di teks dan nama kotanya tetap dimasking. 松本市出身 tidak.
            return Slot(entry), name_end - len(inner)
        open_right = False
        if suffix and not _suffix_fits(suffix, entry, hon, text, match.end("suf")):
            address = self._address(entry, name, hon, suffix, text, match.end("suf"), can_render)
            if address is not _NOT_ADDRESS:
                return address
            open_right = suffix in PLACE_SUFFIXES and entry.kind in PLACE_KINDS
            suffix = ""
        if not entry.allow_compound:
            open_right = (open_right or bool(hon or suffix) or _titled(text, name_end, entry)
                          or (entry.kind in PLACE_KINDS and _address_tail(text, name_end)))
            if not open_right and _blocked_right(text, name_end, name):
                address = self._address(entry, name, hon, "", text, name_end, can_render)
                if address is not _NOT_ADDRESS:
                    return address
                if _shout_end(text, name_end, name) == name_end:
                    return None
        slot = Slot(entry, HONORIFIC_SURFACES.get(_plain_honorific(hon), ""), suffix or inner)
        end = name_end + len(hon) + len(suffix)
        return slot, _shout_end(text, end, suffix or hon or name)

    def _person_in_context(
        self, entry: GlossaryEntry, hon: str, suffix: str, text: str, match: re.Match[str]
    ) -> GlossaryEntry:
        """Tafsirkan tempat bawaan yang juga nama keluarga sebagai orang bila konteksnya orang.

        Konteks orang: honorifik (山口さん), sufiks orang yang benar-benar
        sufiks (山口家, 千葉一家, 石川達; bukan 山口達也; ら/たち hanya sebelum
        partikel atau bukan kana, bukan 福島らへん), atau gelar (石川部長).
        Tanpa konteks itu entri tempat dikembalikan apa adanya (山口県, 山口に).
        """
        person = self._as_person.get(entry.surface) if entry.kind == PLACE else None
        if person is None or entry.source != BUILTIN_SOURCE:
            return entry
        if hon:
            return person
        if suffix in PEOPLE_SUFFIXES:
            end = match.end("suf")
            fits = _suffix_fits(suffix, person, "", text, end) and (
                suffix not in _PLURAL_KANA or _plural_boundary(text, end))
            return person if fits else entry
        if not suffix and _titled(text, match.end("name"), person):
            return person
        return entry

    def _chain(
        self,
        entry: GlossaryEntry,
        suffix: str,
        text: str,
        match: re.Match[str] | None,
        can_render: Callable[[GlossaryEntry], bool] | None,
    ) -> tuple[Slot, int] | None:
        """Rangkai unit wilayah dengan tempat dikenal yang langsung mengikutinya.

        Hanya dipanggil ``_address`` setelah ``_admin_unit`` memastikan ``entry`` +
        ``suffix`` (愛知 + 県, atau 北海道 tanpa sufiks) berakhir dengan unit wilayah
        都/道/府/県. ``match`` adalah kecocokan glosarium tepat sesudahnya (dicari sekali
        oleh ``_address``) dan harus berupa tempat dikenal yang diterima aturan biasa
        (boleh berangkai lagi). Orang, honorifik, dan sufiks orang tidak pernah menjadi
        bagian alamat. Rangkaian yang langsung disusul kanji (北海道札幌市中央区,
        愛知県豊田市内) dibatalkan: sisa 市中央区 akan menempel ke unit terbesar
        ("Sapporo, Hokkaido市中央区"), jadi unitnya dimasking sendiri-sendiri seperti
        sebelum ada rangkaian.

        Returns:
            (slot gabungan, posisi akhir), atau ``None`` bila bukan rangkaian alamat.
        """
        found = self._accept(text, match, can_render) if match is not None else None
        if found is None or found[0] is None:
            return None
        child, end = found
        if child.entry.kind != PLACE or child.honorific or child.suffix in PEOPLE_SUFFIXES:
            return None
        if end < len(text) and is_kanji(text[end]) and not _address_tail(text, end):
            return None
        parents = ((entry, suffix), *child.parents)
        return Slot(child.entry, "", child.suffix, parents), end

    def _address(
        self,
        entry: GlossaryEntry,
        name: str,
        hon: str,
        suffix: str,
        text: str,
        pos: int,
        can_render: Callable[[GlossaryEntry], bool] | None,
    ) -> tuple[Slot | None, int] | _NotAddress | None:
        """Aturan alamat untuk ``entry`` + ``suffix`` yang menempel ke kata di ``pos``.

        Dipanggil saat batas kanan atau sufiks menolak kecocokan biasa. Hasilnya, dengan
        urutan pemeriksaan:

        1. Rangkaian alamat (``_chain``): ``(slot gabungan, akhir)``.
        2. Alamat yang dibiarkan utuh: ``(None, akhir)``. Unit wilayah BAWAAN (prefektur
           nyata 長野 + 県, atau 北海道) yang langsung diikuti kanji yang memuat unit kota
           ``市区町村郡`` tetapi tidak diawali tempat dikenal yang bisa dirender:
           長野県松本市内 (deteksi entitas tidak menangkap 松本市 sebelum 内), 長野県松本市民,
           広島県廿日市市 (nama kota mengandung 市), 長野県木曽郡上松町, 東京都府中市.
           Dulu prefekturnya tetap dimasking dan sisanya dikirim mentah, sehingga mesin
           yang menggemakan teks menghasilkan ``Nagano県松本市内``. Kini seluruh alamat
           (sampai akhir deretan kanji) dikirim apa adanya ke mesin, yang mengenal
           prefektur nyata, jadi keluarannya selalu satu bentuk. Prefektur dari glosarium
           pengguna (fiktif) tetap dimasking: melindungi nama lebih penting.
        3. Unit wilayah yang langsung diikuti tempat dikenal yang TIDAK bisa dirender
           (愛知県刈谷市 dengan entri 刈谷市 tanpa bacaan, ``unknown_reading="keep"`` atau
           jawaban mesin ditolak): ``None``, kecocokan ditolak. Bila 愛知 tetap dimasking,
           keluarannya setengah Latin (``Aichi県刈谷市`` dengan mesin yang menggemakan
           teks); seluruh alamat dibiarkan Jepang dan dikirim utuh ke mesin, sama seperti
           nama lain yang tidak bisa dirender.
        4. Selain itu ``_NOT_ADDRESS``: aturan alamat tidak berlaku dan ``_accept``
           melanjutkan pemeriksaan biasa. Bila yang menyusul tempat dikenal yang bisa
           dirender (愛知県豊田市内, 北海道札幌市中央区), unitnya dimasking sendiri-sendiri.
        """
        if not _admin_unit(entry, name, hon, suffix):
            return _NOT_ADDRESS
        match = self._pattern.match(text, pos) if self._pattern is not None else None
        chained = self._chain(entry, suffix, text, match, can_render)
        if chained is not None:
            return chained
        child = self._entries[match["name"]] if match is not None else None
        child = child if child is not None and child.kind == PLACE else None
        renderable = child is not None and (can_render is None or can_render(child))
        if entry.source == BUILTIN_SOURCE and not renderable:
            end = _address_run_end(text, pos)
            if end is not None:
                return None, end
        if child is not None and not renderable:
            return None
        return _NOT_ADDRESS


def missing_tokens(translated: str, masked: Masked) -> list[int]:
    """Nomor penanda asli yang tidak ditemukan di keluaran mesin (tanpa merender).

    Args:
        translated: Keluaran mentah mesin.
        masked: Hasil masking kalimat yang sama.

    Returns:
        Nomor yang hilang, terurut; kosong berarti semua penanda utuh.
    """
    return _missing(_count_tokens(_normalized(translated)), masked)


def restore(translated: str, masked: Masked, render: Callable[[Slot], str]) -> str:
    """Ganti penanda di hasil mesin dengan bentuk akhir dari ``render``.

    Semua nomor asli wajib ada. Penanda karangan mesin dibuang; penanda yang
    muncul lebih sering dari aslinya dicatat sebagai warning dan tetap
    dirender. ``render`` baru dipanggil setelah validasi lolos, sehingga
    status gloss kemunculan pertama tidak tercemar oleh percobaan yang gagal.

    Args:
        translated: Keluaran mentah mesin (boleh mengandung entitas HTML).
        masked: Hasil ``EntityMatcher.mask`` untuk kalimat yang sama.
        render: Pembuat bentuk akhir, biasanya ``style.Renderer``.

    Returns:
        Teks terjemahan dengan nama final dan spasi ganda dirapikan.

    Raises:
        PlaceholderError: Ada nomor penanda asli yang tidak ditemukan.
    """
    text = _normalized(translated)
    found = _count_tokens(text)
    missing = _missing(found, masked)
    if missing:
        raise PlaceholderError(missing)
    _warn_unexpected(found, masked)

    def substitute(match: re.Match[str]) -> str:
        """Bentuk akhir satu penanda (kapital di awal kalimat) plus ekor yang dipertahankan."""
        tail = _marker_tail(text, match)
        slot = masked.slots.get(int(match.group(1)))
        if slot is None:
            return tail
        form = render(slot)
        if _SENTENCE_START_RE.fullmatch(text, 0, match.start()):
            form = form[:1].upper() + form[1:]
        return form + tail

    return _squeeze_spaces(_TOKEN_TAIL_RE.sub(substitute, text))


def _marker_tail(text: str, match: re.Match[str], *, masked: bool = False) -> str:
    """Tanda panjang di belakang penanda yang dipertahankan; selebihnya dibuang.

    Satu aturan untuk ``restore`` (keluaran mesin, ``_TOKEN_TAIL_RE``) dan ``presubstitute``
    (teks termasking, ``_EXACT_TOKEN_TAIL_RE``, ``masked=True``). Satu ``ー``/``ｰ`` tepat di
    belakang nama selalu dibuang: itu teriakan yang tidak dirender, sama seperti yang sudah
    diserap slot (``美咲ー！`` → ``Misaki!``), jadi ``[[E1]]ー, tunggu!`` menjadi ``Misaki,
    tunggu!``, bukan ``Misakii``. ``ーー`` atau lebih adalah tanda pisah dan dipertahankan
    bila disusul kata, Latin atau Jepang, boleh didahului spasi (``[[E1]]ーーno`` →
    ``Misaki—no`` di pascaproses; ``[[E1]]ーーいや`` tetap apa adanya).

    Bedanya disengaja: di teks termasking ``_shout_end`` sudah menyerap ``ーー`` teriakan
    (yang disusul tanda baca, spasi, atau akhir teks) ke dalam slot, jadi ``ーー`` yang
    tersisa di belakang penanda selalu dipertahankan, juga sebelum angka atau simbol
    (``美咲ーー123`` dikirim `` Misaki ーー123``). Di keluaran mesin ``ーー`` sebelum angka,
    simbol, atau tanda baca bisa tambahan mesin sendiri, jadi dibuang.
    """
    tail = match.group("tail")
    if len(tail) < 2:
        return ""
    return tail if masked or _LETTER_AFTER_DASH_RE.match(text, match.end()) else ""


def presubstitute(masked: Masked, render: Callable[[Slot], str]) -> tuple[str, list[str]]:
    """Jalur cadangan: sisipkan bentuk Latin final langsung ke teks Jepang.

    Contoh: ``[[E1]]は東京へ`` → ``Tanaka-san は東京へ``. Mesin terbukti
    mempertahankan bentuk Latin seperti ini (LAPORAN_RISET 6.1).

    Args:
        masked: Hasil masking.
        render: Pembuat bentuk akhir.

    Returns:
        Pasangan (teks untuk dikirim ke mesin, daftar bentuk yang wajib
        muncul di hasil terjemahan tanpa duplikat).
    """
    required: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        """Bentuk Latin satu penanda berspasi, dan catat bentuk itu di ``required``."""
        form = render(masked.slots[int(match.group(1))])
        if form not in required:
            required.append(form)
        # Satu ー sisa di belakang nama (美咲ー、) tidak dikirim, seperti di ``restore``;
        # ーー sebelum huruf adalah tanda pisah dan tetap dikirim.
        return f" {form} " + _marker_tail(masked.text, match, masked=True)

    return _squeeze_spaces(_EXACT_TOKEN_TAIL_RE.sub(substitute, masked.text)), required


def check_presubstituted(translated: str, required: list[str]) -> list[str]:
    """Cari bentuk wajib yang hilang dari hasil jalur cadangan.

    Perbandingan mengabaikan huruf besar/kecil dan diakritik (ō ≈ o), karena
    mesin kadang menulis ulang ``Satō`` menjadi ``Sato``.

    Args:
        translated: Keluaran mesin.
        required: Bentuk dari ``presubstitute``.

    Returns:
        Bentuk yang tidak ditemukan; kosong berarti lolos.
    """
    haystack = _loose(html.unescape(translated))
    return [form for form in required if _loose(form) not in haystack]


def _build_pattern(entries: Mapping[str, GlossaryEntry]) -> re.Pattern[str]:
    """Rakit regex nama + honorifik + sufiks, alternatif terpanjang dulu."""
    names = _alternation(entries)
    # Honorifik yang dipanjangkan (さーん, ちゃーーん) dicoba dulu; kuncinya dinormalkan
    # ``_plain_honorific`` saat membuat slot.
    elongated = "|".join(re.escape(hon[:-1]) + "[ーｰ]+" + re.escape(hon[-1])
                         for hon in _ELONGATED_HONORIFICS if hon in HONORIFIC_SURFACES)
    hons = f"{elongated}|{_alternation(HONORIFIC_SURFACES)}" if elongated else _alternation(
        HONORIFIC_SURFACES)
    suffixes = _alternation({**PEOPLE_SUFFIXES, **PLACE_SUFFIXES}, _SUFFIX_LOOKAHEAD)
    return re.compile(f"(?P<name>{names})(?P<hon>{hons})?(?P<suf>{suffixes})?")


def _alternation(words: Iterable[str], lookahead: Mapping[str, str] | None = None) -> str:
    """Gabungkan kata menjadi alternasi regex, terpanjang dulu.

    Args:
        words: Kata-kata (kunci dict juga boleh).
        lookahead: Syarat tambahan per kata, mis. ``{"ら": "(?![しれ])"}``.
    """
    extra = lookahead or {}
    ordered = sorted(words, key=len, reverse=True)
    return "|".join(re.escape(word) + extra.get(word, "") for word in ordered)


def _with_halfwidth_forms(surface_map: Mapping[str, GlossaryEntry]) -> dict[str, GlossaryEntry]:
    """Tambahkan bentuk katakana setengah lebar (ｱﾘｽ) untuk tiap tulisan katakana."""
    entries = dict(surface_map)
    for surface, entry in surface_map.items():
        entries.setdefault(narrow_katakana(surface), entry)
    return entries


def _suffix_fits(suffix: str, entry: GlossaryEntry, hon: str, text: str, end: int) -> bool:
    """Periksa apakah sufiks benar-benar sufiks, bukan awal kata lain.

    Sufiks jamak/keluarga untuk orang, atau untuk nama apa pun yang sudah
    berhonorifik (千葉さん達 walau 千葉 juga nama prefektur). Sufiks tempat
    hanya untuk tempat/organisasi. Sufiks yang langsung diikuti kanji
    dianggap bagian kata majemuk: 田中達也 (nama Tatsuya), 田中家具店, 東京都庁, kecuali sufiks
    tempat yang disusul ``ADDRESS_TAILS`` (静岡県出身, 浜松市在住).
    """
    if end < len(text) and is_kanji(text[end]) and not (
            suffix in PLACE_SUFFIXES and entry.kind in PLACE_KINDS and _address_tail(text, end)):
        return False
    if suffix in PEOPLE_SUFFIXES:
        return entry.kind == PERSON or bool(hon)
    return entry.kind in PLACE_KINDS


def _address_tail(text: str, pos: int) -> bool:
    """Teks di ``pos`` diawali salah satu ``ADDRESS_TAILS`` (出身, 在住, 生まれ, 産 + bukan kanji)."""
    for tail in ADDRESS_TAILS:
        if text.startswith(tail, pos):
            after = pos + len(tail)
            return tail != "産" or after >= len(text) or not is_kanji(text[after])
    return False


def _house_chi(text: str, end: int, slot: Slot) -> bool:
    """``ち`` di ``end`` adalah 家 lisan sesudah orang + さん/くん/ちゃん (田中さんちの犬).

    Syaratnya ち disusul partikel, kopula, tanda baca, kanji, atau akhir teks
    (``_HOUSE_FOLLOWERS``), atau が/か/な/く/ま/や yang tidak memulai kata lain (``_HOUSE_UNLESS``),
    atau って (``_HOUSE_ONLY_IF``). Jadi 田中さんちょっと (= 田中さん、ちょっと), 福井さんちゃんと,
    田中さんちがう (= 違う), 田中さんちかく (= 近く), dan 田中さんちっこい tidak terkena. 長崎くんち
    (festival) sudah menjadi tempat tanpa honorifik di ``EntityMatcher._accept``
    (``KUNCHI_FESTIVALS``).
    """
    if (slot.entry.kind != PERSON or slot.honorific not in _HOUSE_HONORIFICS or slot.suffix
            or not text.startswith(HOUSE_CHI, end)):
        return False
    after = end + len(HOUSE_CHI)
    if after >= len(text) or text[after] in _HOUSE_FOLLOWERS or is_kanji(text[after]):
        return True
    only = _HOUSE_ONLY_IF.get(text[after])
    if only is not None:
        return text.startswith(only, after + 1)
    unless = _HOUSE_UNLESS.get(text[after])
    return unless is not None and not text.startswith(unless, after + 1)


def _surname_readings_of_builtin_places(
    entries: Iterable[GlossaryEntry],
) -> dict[str, GlossaryEntry]:
    """Entri orang pengganti untuk tempat bawaan yang juga nama keluarga (山口, 千葉).

    Entri ini hanya dipakai ``EntityMatcher`` saat konteksnya orang; tidak
    pernah masuk glosarium, sehingga entri tempat bawaan tetap utuh.

    Returns:
        Tulisan → ``GlossaryEntry`` PERSON berbacaan ``surnames.json``.
    """
    surnames = data.surnames()
    return {
        entry.surface: GlossaryEntry(
            entry.surface, kind=PERSON, reading=surnames[entry.surface], source=BUILTIN_SOURCE
        )
        for entry in entries
        if entry.kind == PLACE and entry.source == BUILTIN_SOURCE and entry.surface in surnames
    }


def _blocked_left(text: str, start: int, name: str, entry: GlossaryEntry) -> bool:
    """Tolak bila nama menyambung ke kata di kirinya (小田中, アリスト)."""
    if start == 0:
        return False
    if entry.kind in PLACE_KINDS and text[start - 1] in _ADMIN_ENDINGS:
        return False
    return _same_script(text[start - 1], name[0])


def _blocked_right(text: str, end: int, name: str) -> bool:
    """Tolak bila nama menyambung ke kata di kanannya (田中央, アリスト)."""
    if end >= len(text) or _shouted(text, end):
        return False
    return _same_script(text[end], name[-1])


def _shouted(text: str, end: int) -> bool:
    """Nama diikuti ーー/ッ/ーッ lalu bukan katakana: teriakan, bukan kata yang lebih panjang."""
    return _strong_shout_end(text, end, hiragana_sokuon=False,
                             follower_ok=lambda ch: not is_katakana(ch)) is not None


def _strong_shout_end(
    text: str, end: int, *, hiragana_sokuon: bool, follower_ok: Callable[[str], bool]
) -> int | None:
    """Akhir ekor teriakan "kuat" yang mulai di ``end``, satu sumber aturan teriakan.

    Ekor kuat adalah deretan ー/ッ (ditambah っ bila ``hiragana_sokuon``) yang
    minimal dua huruf atau berakhir sokuon: ``ーー``, ``ッ``, ``ーッ``. Satu ー saja
    bukan ekor kuat; ia ditangani ``_single_long_vowel_shout``.

    Args:
        text: Teks sumber.
        end: Posisi tepat sesudah nama atau honorifik.
        hiragana_sokuon: Hitung juga っ hiragana sebagai bagian ekor.
        follower_ok: Syarat huruf sesudah ekor; akhir teks selalu diterima.

    Returns:
        Posisi sesudah ekor, atau ``None`` bila tidak ada ekor kuat yang diterima.
    """
    tail = _SHOUT_TAIL_RE[hiragana_sokuon].match(text, end)
    if tail is None:
        return None
    run, after = tail.group(), tail.end()
    if len(run) < 2 and run[-1] not in _SOKUON:
        return None
    if after < len(text) and not follower_ok(text[after]):
        return None
    return after


def _single_long_vowel_shout(text: str, end: int, name: str, any_script: bool = False) -> bool:
    """Nama katakana + SATU ー lalu tanda seru/tanya, elipsis, atau ～ (マリー！, マリー…).

    Hanya dipanggil untuk kecocokan terpanjang di posisinya, jadi entri lain
    yang lebih panjang (マリー) sudah lebih dulu dicoba. ーー dan ーッ ditangani
    ``_strong_shout_end``. Nama+ー yang merupakan kata serapan (ミラー, ハンター) bukan
    teriakan.

    Args:
        any_script: Terima juga nama yang tidak berakhir katakana (田中ー！); dipakai
            ``_shout_end`` untuk menyerap teriakan, bukan untuk batas kanan.
    """
    if not (any_script or is_katakana(name[-1])):
        return False
    if end >= len(text) or text[end] not in _LONG_VOWELS:
        return False
    after = end + 1
    if after >= len(text) or text[after] not in _SHOUT_END_CHARS:
        return False
    return search_key(name + text[end]) not in data.loanwords()


def _shout_end(text: str, end: int, name: str) -> int:
    """Posisi akhir teriakan setelah nama/honorifik, atau ``end`` bila tidak ada teriakan.

    Teriakan ikut masuk slot dan tidak dirender: ``アリスーーッ！`` → ``[[E1]]！`` →
    ``Alice!``, juga setelah honorifik (``ユキちゃんーー！`` → ``Yuki-chan!``) dan
    dengan っ hiragana (``ユキっ！``, ``ユキさまーっ！``). Dengan begitu mesin tidak
    pernah menerima (dan menggemakan) ー/ッ yang menempel ke penanda. Bentuk
    teriakan: deretan ー/ッ/っ yang minimal dua huruf atau berakhir ッ/っ, atau SATU
    ー sebelum ``_SHOUT_END_CHARS`` yang bukan kata serapan (``name`` + ー).

    Ekornya hanya diserap bila disusul ``_SHOUT_FOLLOWERS`` (tanda teriakan, tanda
    baca, kurung/kutip penutup, spasi, akhir teks). Sebelum huruf lain ekor itu
    bukan teriakan dan dibiarkan di teks: ーー sebagai tanda pisah (``田中ーーいや``)
    dan ッ/っ awal partikel atau kata (``ユキッて``, ``ユキって``, ``田中ッ子``).
    """
    after = _strong_shout_end(text, end, hiragana_sokuon=True,
                              follower_ok=_SHOUT_FOLLOWERS.__contains__)
    if after is not None:
        return after
    return end + 1 if _single_long_vowel_shout(text, end, name, any_script=True) else end


def _not_this_entity(
    entry: GlossaryEntry, text: str, match: re.Match[str], named: frozenset[str] = frozenset()
) -> bool:
    """Kecocokan yang konteksnya menunjukkan kata biasa, bukan entri ini.

    - Entri orang yang bukan milik pengguna, diikuti honorifik yang sebenarnya okurigana + ん:
      aturan konteks yang sama dengan deteksi (``style.verb_run_before_honorific``), dengan
      ``named`` dan entri berbacaan (治 おさむ dari ruby, data, atau glosarium) sebagai nama
      yang terbukti (tingkat nama 2). Pengecualian: entri satu kanji yang juga batang kata
      kerja (``_verb_stem_entry``: 歩, 咲, 輝 dari jalan sebelumnya) hanya terbukti lewat
      ``named`` dokumen ini, karena bacaannya dari data tidak lebih kuat dari tingkat 1 dan
      entri itu bisa berasal dari salah baca di dokumen lain. 行くんですか, 駅まで歩くんですか,
      dan entri lama 来週行 di 来週行くんだ tidak dimasking; おい、乾くん！, 開くんが, dan
      弟の歩くんです tetap dimasking.
    - Entri orang satu kanji yang bukan milik pengguna, tanpa honorifik, dalam konteks kata
      biasa (``_bare_word``: 来るんだ, 持ってきた, 持ち主, 話は終わりだ). Entri batang kata kerja
      bertanda bukti tegas (``_strong_names``: 磨 dari 磨くんが dan 磨くん、) dianggap nama di sini.
    - Tempat bawaan yang juga kata umum (``data.AMBIGUOUS_PLACES``: 大分 "cukup", 三重
      "tiga lapis") tanpa sufiks tempat (大分よくなった, 三重の塔). 大分県, 三重県, 大分駅,
      dan 大分市 tetap tempat.

    Entri pengguna tidak pernah ditafsir ulang.
    """
    if entry.kind == PERSON and entry.source != USER_SOURCE:
        known = named | {match["name"]} if entry.reading else named
        hon = match["hon"] or ""
        if hon:
            end = match.end("hon")
            before = text[max(0, match.start() - VERB_CONTEXT_CHARS):match.start()]
            level = named if _verb_stem_entry(entry) else known
            if verb_run_before_honorific(match["name"], hon, text[end:end + VERB_AFTER_CHARS],
                                         before=before, named=level):
                return True
        elif not match["suf"] and _bare_word(match["name"], text, match.end("name"),
                                             known | _strong_names(entry)):
            return True
    return (entry.source == BUILTIN_SOURCE and entry.surface in data.AMBIGUOUS_PLACES
            and (match["suf"] or "") not in PLACE_SUFFIXES)


def _strong_names(entry: GlossaryEntry) -> frozenset[str]:
    """Tulisan entri yang tersimpan dengan bukti nama tegas (``glossary.STRONG_SOURCE_MARK``):
    boleh dimasking tanpa honorifik sebelum partikel nama (磨が, 磨と), bukan sebelum okurigana."""
    return frozenset({entry.surface}) if STRONG_SOURCE_MARK in entry.source else frozenset()


def _verb_stem_entry(entry: GlossaryEntry) -> bool:
    """Entri satu kanji yang kanjinya juga batang kata kerja (``style.is_verb_stem``: 歩, 渡)."""
    return len(entry.surface) == 1 and is_verb_stem(entry.surface)


def _bare_word(name: str, text: str, end: int, named: frozenset[str]) -> bool:
    """Kanji tunggal tanpa honorifik yang menjadi bagian kata kerja atau kata biasa.

    Batang kata kerja (``style.is_verb_stem``) yang tidak dikenal sebagai nama
    (``style.is_known_name`` atau ``named``) tidak pernah dimasking tanpa honorifik: 話は,
    持って, 来な. Kanji lain ditolak bila disusul hiragana okurigana, yaitu hiragana di luar
    ``_BARE_NAME_FOLLOWERS`` dan ``_BARE_NAME_PARTICLES`` (歩いて, 見る), atau って/った sesudah
    kanji yang bentuk -te/-ta-nya ``_TTE_STEMS`` (勝って, 治って, 渡った, 渡ったら). Nama satu
    kanji sebelum partikel tetap dimasking: 翔が, 哲って, 歩って誰, 翔ったら, 開の, 翔まで,
    哲しか, 慧くらい.
    """
    if len(name) != 1:
        return False
    if is_verb_stem(name) and name not in named and not is_known_name(name):
        return True
    if end >= len(text) or not is_hiragana(text[end]):
        return False
    if text.startswith(("って", "った"), end):
        return name in _TTE_STEMS
    if text.startswith(_BARE_NAME_PARTICLES, end):
        return False
    return text[end] not in _BARE_NAME_FOLLOWERS


def _plain_honorific(hon: str) -> str:
    """Honorifik tanpa tanda panjang teriakan: ``さーーん`` → ``さん``."""
    return "".join(ch for ch in hon if ch not in _LONG_VOWELS)


def _address_run_end(text: str, pos: int) -> int | None:
    """Akhir deretan kanji alamat mulai ``pos`` bila memuat unit kota ``市区町村郡``.

    Deretan berisi kanji dan ``ヶケヵ`` (鎌ケ谷市). ``None`` bila ``pos`` bukan kanji atau
    deretannya tidak memuat unit kota.
    """
    if pos >= len(text) or not is_kanji(text[pos]):
        return None
    end = pos
    while end < len(text) and (is_kanji(text[end]) or text[end] in _ADDRESS_INNER_CHARS):
        end += 1
    return end if _ADDRESS_UNIT_CHARS.intersection(text[pos:end]) else None


def _admin_unit(entry: GlossaryEntry, name: str, hon: str, suffix: str) -> bool:
    """Tempat yang berakhir unit wilayah 都/道/府/県 (愛知 + 県, atau 北海道 tanpa sufiks)."""
    if hon or entry.kind != PLACE:
        return False
    return suffix in _ADMIN_ENDINGS or (not suffix and name.endswith(_ADMIN_NAME_ENDINGS))


def _inner_suffix(name: str, entry: GlossaryEntry) -> str:
    """Sufiks kota di dalam kunci peta masking (松本市 → entri 松本 + ``市``), atau kosong.

    ``pipeline.admin_stem_entry`` menyimpan kota bersufiks dari deteksi entitas
    sebagai entri bertulisan nama saja dengan kunci tulisan utuh; sufiksnya
    dirender ``Renderer`` (``Kota Matsumoto``).
    """
    if (entry.kind == PLACE and len(name) == len(entry.surface) + 1
            and name.startswith(entry.surface) and name[-1] in _MUNICIPALITY_ENDINGS):
        return name[-1]
    return ""


def _plural_boundary(text: str, end: int) -> bool:
    """ら/たち berakhir di ``end`` dan yang menyusul partikel, tanda baca, atau akhir teks.

    Menolak awal kata lain: 福島らへん (sekitar), 宮崎らーめん, 千葉たちうお.
    """
    if end >= len(text) or not is_kana(text[end]):
        return True
    return text[end] in _PLURAL_FOLLOWERS and not text.startswith(_NOT_PLURAL_WORDS, end)


def _titled(text: str, end: int, entry: GlossaryEntry) -> bool:
    """Nama orang yang langsung diikuti gelar jabatan (佐藤部長, 田中社長)."""
    return entry.kind == PERSON and text.startswith(TITLE_WORDS, end)


def _same_script(neighbor: str, edge: str) -> bool:
    """Dua karakter sama-sama kanji atau sama-sama katakana."""
    return (is_kanji(neighbor) and is_kanji(edge)) or (
        is_katakana(neighbor) and is_katakana(edge)
    )


def _warn_unexpected(found: Counter[int], masked: Masked) -> None:
    """Catat penanda karangan mesin dan penanda yang terduplikasi."""
    expected = Counter(int(n) for n in EXACT_TOKEN_RE.findall(masked.text))
    invented = sorted(set(found) - set(masked.slots))
    if invented:
        logger.warning("penanda karangan mesin dibuang: %s", invented)
    for number in sorted(masked.slots):
        if found[number] > expected[number]:
            logger.warning(
                "penanda E%d muncul %d kali (asli %d)", number, found[number], expected[number]
            )


def _normalized(translated: str) -> str:
    """Keluaran mesin tanpa entitas HTML dan dengan penanda lebar penuh dinormalkan."""
    return html.unescape(translated).translate(_FULLWIDTH_TOKEN_CHARS)


def _count_tokens(text: str) -> Counter[int]:
    """Hitung kemunculan tiap nomor penanda (regex toleran)."""
    return Counter(int(m.group(1)) for m in TOKEN_RE.finditer(text))


def _missing(found: Counter[int], masked: Masked) -> list[int]:
    return sorted(set(masked.slots) - set(found))


def _squeeze_spaces(text: str) -> str:
    """Rapikan spasi ganda dan spasi di tepi tiap baris."""
    lines = (_SPACES_RE.sub(" ", line).strip(" \t") for line in text.split("\n"))
    return "\n".join(lines)


def _loose(text: str) -> str:
    """Bentuk longgar untuk perbandingan: tanpa diakritik, casefold, spasi tunggal."""
    return " ".join(strip_diacritics(text).casefold().split())
''')

MODUL['jptrans.readers'] = (
    True,
r'''"""Pembaca dokumen masukan: memilih pengurai menurut sufiks atau format eksplisit.

Setiap pembaca mengembalikan ``models.Document`` sehingga pipa terjemahan tidak
bergantung pada format sumber (TXT, Markdown, Aozora Bunko, HTML, EPUB, SRT,
WebVTT, ASS/SSA, maupun JSON halaman komik).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ..errors import ConfigError, InputError
from ..models import Document
from .aozora import front_matter_title, is_aozora, parse_aozora
from .epub import read_epub, read_html
from .pages import read_pages
from .subtitle import read_ass, read_srt, read_vtt
from .txt import normalize_newlines, read_text_file, read_txt, text_to_document

logger = logging.getLogger(__name__)

Reader = Callable[[Path, str | None, str | None], Document]


def _read_txt_or_aozora(
    path: Path, title: str | None, encoding: str | None
) -> Document:
    text = read_text_file(path, encoding)
    doc = _parse_plain_or_aozora(
        text, title or front_matter_title(text) or path.stem
    )
    doc.source_path = str(path)
    return doc


def _read_aozora_forced(
    path: Path, title: str | None, encoding: str | None
) -> Document:
    text = read_text_file(path, encoding)
    doc = parse_aozora(text, title or front_matter_title(text) or path.stem)
    doc.source_path = str(path)
    return doc


def _read_epub(path: Path, title: str | None, _encoding: str | None) -> Document:
    return read_epub(path, title)


def _read_pages(
    path: Path, title: str | None, _encoding: str | None
) -> Document:
    return read_pages(path, title)


READERS: dict[str, Reader] = {
    ".txt": _read_txt_or_aozora,
    ".md": read_txt,
    ".html": read_html,
    ".htm": read_html,
    ".xhtml": read_html,
    ".epub": _read_epub,
    ".srt": read_srt,
    ".vtt": read_vtt,
    ".ass": read_ass,
    ".ssa": read_ass,
    ".json": _read_pages,
}

INPUT_FORMAT_READERS: dict[str, Reader] = {
    "auto": _read_txt_or_aozora,
    "txt": read_txt,
    "aozora": _read_aozora_forced,
    "md": read_txt,
    "html": read_html,
    "epub": _read_epub,
    "srt": read_srt,
    "vtt": read_vtt,
    "ass": read_ass,
    "pages": _read_pages,
}


def read_document(
    path: Path,
    *,
    title: str | None = None,
    encoding: str | None = None,
    input_format: str | None = None,
) -> Document:
    """Baca berkas masukan menurut ``input_format`` eksplisit atau sufiks berkas."""
    path = Path(path)
    if input_format and input_format != "auto":
        reader = INPUT_FORMAT_READERS.get(input_format.lower())
        if reader is None:
            choices = ", ".join(sorted(INPUT_FORMAT_READERS))
            raise InputError(
                f"format masukan {input_format!r} tidak dikenal; pilih: {choices}"
            )
    else:
        reader = READERS.get(path.suffix.lower())
        if reader is None:
            supported = ", ".join(sorted(READERS))
            suffix = path.suffix or "(tanpa sufiks)"
            raise InputError(
                f"format {suffix} tidak didukung; pilih: {supported}"
            )
    if not path.is_file():
        raise InputError(f"berkas tidak ditemukan: {path}")
    doc = reader(path, title, encoding)
    logger.info(
        "dibaca %s: %d paragraf, format %s",
        path.name,
        len(doc.paragraphs),
        doc.fmt,
    )
    return doc


def read_text(text: str, title: str) -> Document:
    """Ubah teks tempelan menjadi ``Document`` (mendeteksi Aozora bila cocok)."""
    return _parse_plain_or_aozora(
        normalize_newlines(text.removeprefix("\ufeff")), title
    )


def _parse_plain_or_aozora(text: str, title: str) -> Document:
    if is_aozora(text):
        return parse_aozora(text, title)
    return text_to_document(text, title)


def register_reader(
    suffix: str, reader: Reader, *, input_format: str | None = None
) -> None:
    """Daftarkan pembaca format masukan kustom ke ``READERS`` dan ``INPUT_FORMAT_READERS``."""
    clean = suffix.strip().lower()
    if not clean.startswith("."):
        clean = f".{clean}"
    if clean == "." or not callable(reader):
        raise ConfigError(f"pembaca atau sufiks tidak sah: {suffix!r}")
    READERS[clean] = reader
    fmt_name = (input_format or clean.lstrip(".")).strip().lower()
    if fmt_name:
        INPUT_FORMAT_READERS[fmt_name] = reader
    logger.debug("pembaca kustom terdaftar: %s (%s)", clean, fmt_name)


__all__ = [
    "INPUT_FORMAT_READERS",
    "READERS",
    "Reader",
    "read_document",
    "read_text",
    "register_reader",
]
''')

MODUL['jptrans.readers.aozora'] = (
    False,
r'''"""Pengurai notasi Aozora Bunko (青空文庫).

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
''')

MODUL['jptrans.readers.epub'] = (
    False,
r'''"""Pembaca EPUB 2/3 dengan ``zipfile``, ``xml.etree`` dan ``html.parser``.

Alur: ``META-INF/container.xml`` menunjuk berkas OPF; OPF memuat metadata
(``dc:title``), manifest (id ke berkas), dan spine (urutan baca). Tiap dokumen
XHTML di spine diurai menjadi paragraf, dan ruby ``<ruby>悠真<rt>ゆうま</rt></ruby>``
disimpan sebagai pasangan bacaan.

Keamanan dan legalitas:

- Isi ZIP tidak pernah di-extract ke disk (tidak ada path traversal). Ukuran
  di header ZIP bisa berbohong (zip bomb), jadi batas yang menentukan adalah
  anggaran deterministik: seluruh entri yang dibaca berbagi ``MAX_TOTAL_BYTES``
  (64 MB) byte hasil dekompresi, dihitung dari byte nyata yang keluar dari
  ``zipfile.open`` per blok ``READ_BLOCK``, sehingga pembacaan berhenti paling
  lambat satu blok setelah anggaran habis apa pun isi header. Hanya metode
  stored dan deflate (yang diizinkan OCF) yang diterima. Penolakan rasio
  kompresi untuk entri besar hanyalah penolakan dini yang murah, dokumen yang
  disebut berulang di spine hanya dibaca sekali, dan jumlah paragraf dibatasi,
  sehingga unggahan kecil tidak bisa menjadi jutaan paragraf.
- Deklarasi entitas XML ditolak di tingkat parser (expat), apa pun encoding
  berkasnya (UTF-8 maupun UTF-16). Di XHTML (``html.parser``), deklarasi DOCTYPE
  dibuang utuh beserta internal subset-nya sebelum parsing (``strip_doctype``), dan
  rujukan ke entitas yang dideklarasikan di subset dibuang tanpa diperluas, sehingga
  ``]>`` dan ``&x;`` tidak bocor ke teks dan tidak ada berkas yang dibaca.
- EPUB ber-DRM ditolak, tidak dibongkar. Obfuscation font IDPF/Adobe bukan DRM.
- EPUB fixed-layout (khas manga) hanya berisi gambar; pengguna diarahkan ke
  alur komik ``pages.json``.
"""

from __future__ import annotations

import html
import logging
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from html.entities import html5 as HTML5_ENTITIES
from html.parser import HTMLParser
from xml.parsers import expat
from pathlib import Path
from urllib.parse import unquote

from ..errors import InputError
from ..models import Document, Paragraph

logger = logging.getLogger(__name__)

MAX_ENTRY_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
"""Anggaran byte hasil dekompresi untuk SEMUA entri yang dibaca dari satu EPUB.

Satu jilid novel berisi beberapa MB XHTML; 64 MB jauh di atasnya tetapi tetap
aman untuk memori. Dihitung dari byte nyata, tidak pernah dari header ZIP.
"""
READ_BLOCK = 64 * 1024
"""Ukuran satu ``read`` dari ``ZipExtFile``; deflate mengeluarkan paling banyak sebesar ini."""
ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
"""Metode yang diizinkan OCF. bzip2/LZMA di ``zipfile`` tidak membatasi keluaran per blok."""
MAX_COMPRESSION_RATIO = 100
"""XHTML biasa terkompresi 3–10×; rasio di atas ini hanya dipakai bom dekompresi."""
RATIO_CHECK_BYTES = 1024 * 1024
"""Entri kecil boleh berasio tinggi (berkas berisi spasi); hanya entri besar yang diperiksa."""
MAX_PARAGRAPHS = 100_000
"""Satu jilid novel berisi beberapa ribu paragraf; batas ini jauh di atasnya."""
CONTAINER_PATH = "META-INF/container.xml"
ENCRYPTION_PATH = "META-INF/encryption.xml"
DRM_MARKERS = ("META-INF/rights.xml", "META-INF/sinf.xml")
FONT_OBFUSCATION = frozenset({
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#RC",
})
XHTML_TYPES = frozenset({"application/xhtml+xml", "text/html", "text/x-oeb1-document"})
FIXED_LAYOUT_HINT = (
    "EPUB fixed-layout (komik/manga) hanya berisi gambar. Jalankan OCR dulu "
    "lalu terjemahkan berkas pages.json (lihat readers.pages)."
)

_XML_ENCODING_RE = re.compile(rb"""^<\?xml[^>]*encoding=["']([A-Za-z0-9._-]+)["']""")
# Baris baru dari indentasi sumber di antara dua karakter Jepang bukan spasi kata.
_CJK_NEWLINE_RE = re.compile(r"(?<=[^\x00-\x7f])[ \t\r\f]*\n[ \t\r\n\f]*(?=[^\x00-\x7f])")
_ASCII_SPACE_RE = re.compile(r"[ \t\r\n\f]+")
_DOCTYPE_SCAN_RE = re.compile(r"<!--|<!\[CDATA\[|<!DOCTYPE\b", re.IGNORECASE)
"""Awal komentar, CDATA, atau DOCTYPE: ``strip_doctype`` melewati dua yang pertama utuh."""
_ELEMENT_START_RE = re.compile(r"</?[A-Za-z]")
_ENTITY_DECL_RE = re.compile(r"<!ENTITY\s+([^\s%][^\s\"'>]*)")
"""Nama entitas umum di internal subset (entitas parameter ``<!ENTITY % p ...>`` dilewati)."""
SENTENCE_END = "。．.！!？?…‥」』）)】"
"""Tanda akhir kalimat/ujaran: ``<br>`` sesudahnya selalu memisah baris (``XhtmlExtractor``)."""
SOFT_BREAK_TAILS = "、，,はがをにでともへのや"
"""Akhir baris yang jelas belum selesai (koma, partikel): ``<br>`` sesudahnya baris lunak
(``湊は<br/>笑った。``). Akhir lain (kanji, ``た``, tanda pisah, tanda akhir) tetap memisah baris:
``第一章<br/>湊の朝``, ``湊は笑った<br/>美咲は泣いた``."""
LINE_OPENERS = "「『（(〈《【〔―—─‐-"
"""Awal baris yang membuka ujaran/baris baru: baris lunak sebelumnya dibatalkan
(``「待って――<br/>「なに？」``, ``――湊<br/>――美咲``)."""
WORD_INNER_STARTS = "っゃゅょぁぃぅぇぉゎんーッャュョァィゥェォヮン"
"""Huruf yang tidak pernah memulai kata: baris yang diawalinya melanjutkan kata yang terpotong
(``湊は笑<br/>った。``), jadi ``<br>`` sebelumnya tetap baris lunak walau baris sebelumnya
berakhir kanji."""
SOFT_MARK = "\ue000"
"""Penanda baris lunak di buffer: spasi di antara huruf Latin, selain itu dihapus
(``_join_soft``)."""
_SOFT_JOIN_RE = re.compile(r"[ \t\r\n\f]*\ue000[ \t\r\n\f]*")


class _ZipReader:
    """Membaca entri ZIP di memori, per blok, dengan anggaran byte yang deterministik.

    Attributes:
        bytes_read: Total byte hasil dekompresi yang sudah keluar dari semua
            entri (termasuk blok yang membuat anggaran terlampaui).
    """

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self.archive = archive
        self.names = frozenset(archive.namelist())
        self.bytes_read = 0

    def read(self, name: str) -> bytes:
        """Isi entri ``name``; ``InputError`` bila hilang, rusak, atau melampaui batas.

        Ukuran di header hanya dipakai untuk penolakan dini rasio kompresi.
        Batas per entri dan anggaran total dihitung dari byte nyata yang dibaca
        bertahap, jadi header yang mengaku kecil tetap berhenti di anggaran.
        """
        if name not in self.names:
            raise InputError(f"EPUB rusak: entri {name} tidak ada")
        info = self.archive.getinfo(name)
        if info.compress_type not in ALLOWED_COMPRESSION:
            raise InputError(f"EPUB ditolak: entri {name} memakai metode kompresi "
                             f"{info.compress_type} (hanya stored/deflate)")
        if info.file_size > RATIO_CHECK_BYTES and \
                info.file_size > MAX_COMPRESSION_RATIO * max(info.compress_size, 1):
            raise InputError(f"EPUB ditolak: entri {name} terkompresi tidak wajar (bom ZIP?)")
        try:
            return self._read_blocks(name)
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError,
                NotImplementedError) as exc:
            raise InputError(f"EPUB rusak: entri {name} tidak bisa dibaca ({exc})") from exc

    def _read_blocks(self, name: str) -> bytes:
        """Baca ``name`` per ``READ_BLOCK`` sambil menghitung anggaran per entri dan total."""
        chunks: list[bytes] = []
        entry_bytes = 0
        with self.archive.open(name) as handle:
            while block := handle.read(READ_BLOCK):
                entry_bytes += len(block)
                self.bytes_read += len(block)
                if self.bytes_read > MAX_TOTAL_BYTES:
                    raise InputError("EPUB ditolak: total isi hasil dekompresi melebihi "
                                     f"anggaran {MAX_TOTAL_BYTES} byte")
                if entry_bytes > MAX_ENTRY_BYTES:
                    raise InputError(f"EPUB ditolak: entri {name} melebihi {MAX_ENTRY_BYTES} byte")
                chunks.append(block)
        return b"".join(chunks)


class XhtmlExtractor(HTMLParser):
    """Ambil paragraf dan pasangan ruby dari satu dokumen XHTML.

    Batas paragraf: ``p``, ``div``, ``h1``-``h6``, ``li``, ``blockquote``, dan
    ``br`` (banyak EPUB Jepang memakai satu ``<br/>`` per baris). Di dalam ``<p>``,
    satu ``<br>`` sesudah baris yang jelas belum selesai (berakhir koma/partikel
    ``SOFT_BREAK_TAILS`` seperti ``湊は<br/>笑った。``, atau huruf/angka Latin) atau sebelum
    baris yang melanjutkan kata (``WORD_INNER_STARTS``: ``湊は笑<br/>った。``) adalah baris
    lunak: kalimatnya tidak dipecah, dan baris itu menjadi spasi di antara huruf Latin atau
    hilang di antara huruf Jepang (``_join_soft``). Baris lunak batal bila baris berikutnya
    diawali ``LINE_OPENERS`` (kurung pembuka, tanda pisah). Baris lain (``第一章<br/>湊の朝``),
    dua ``<br>`` berturut-turut, ``<br>`` sesudah ``SENTENCE_END``, dan ``<br>`` di luar ``<p>``
    (``<div>`` baris demi baris) tetap memisah baris. Teks ``rt`` menjadi bacaan, ``rp``
    dibuang, dan basis ruby tetap masuk ke teks.

    Attributes:
        paragraphs: Paragraf hasil ekstraksi, berurutan.
        ruby: Pasangan ``(basis, bacaan)`` sesuai urutan kemunculan.
    """

    BLOCK_TAGS = frozenset({"p", "div", "li", "blockquote", "br", "dt", "dd",
                            "h1", "h2", "h3", "h4", "h5", "h6"})
    HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
    SKIP_TAGS = frozenset({"head", "script", "style", "rp", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[Paragraph] = []
        self.ruby: list[tuple[str, str]] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._heading_depth = 0
        self._in_ruby = False
        self._in_rt = False
        self._ruby_pending_base: list[str] = []
        self._ruby_current_rt: list[str] = []
        self._ruby_pairs_buf: list[tuple[str, str]] = []
        self._para_depth = 0
        self._soft_break = False
        self._soft_index = -1
        self._soft_tail = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._line_break()
        elif tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "ruby":
            self._in_ruby = True
            self._in_rt = False
            self._ruby_pending_base = []
            self._ruby_current_rt = []
            self._ruby_pairs_buf = []
        elif tag == "rt":
            if self._in_rt:
                self._commit_rt()
            self._in_rt = True
            self._ruby_current_rt = []
        elif tag in self.BLOCK_TAGS:
            self._flush()
            self._para_depth += tag == "p"
            if tag in self.HEADING_TAGS:
                self._heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "br":
            return
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "rt":
            self._commit_rt()
        elif tag == "ruby":
            self._close_ruby()
        elif tag in self.BLOCK_TAGS:
            self._flush()
            if tag == "p":
                self._para_depth = max(0, self._para_depth - 1)
            if tag in self.HEADING_TAGS:
                self._heading_depth = max(0, self._heading_depth - 1)

    def _line_break(self) -> None:
        """``<br>``: calon baris lunak di dalam ``<p>``, selebihnya batas paragraf.

        Keputusan akhir menunggu teks baris berikutnya (``handle_data``): baris lunak bila baris
        sebelumnya berakhir ``SOFT_BREAK_TAILS``/huruf Latin atau baris berikutnya diawali
        ``WORD_INNER_STARTS``, dan baris berikutnya tidak diawali ``LINE_OPENERS``.
        """
        if self._skip_depth:
            return
        last = "".join(self._buffer).rstrip(" \t\r\n\f")[-1:]
        if not self._para_depth or self._soft_break or not last or last in SENTENCE_END:
            self._flush()
            return
        self._soft_index = len(self._buffer)
        self._soft_tail = last in SOFT_BREAK_TAILS or (last.isascii() and last.isalnum())
        self._buffer.append(SOFT_MARK)
        self._soft_break = True

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_rt:
            self._ruby_current_rt.append(data)
            return
        if self._in_ruby:
            self._ruby_pending_base.append(data)
        if data.strip():
            first = data.lstrip()[0]
            if self._soft_break and (first in LINE_OPENERS or not (
                    self._soft_tail or first in WORD_INNER_STARTS)):
                self._buffer = self._buffer[:self._soft_index]
                self._flush()
            self._soft_break = False
        self._buffer.append(data)

    def close(self) -> None:
        """Selesaikan parsing dan simpan paragraf terakhir yang belum tertutup."""
        super().close()
        self._flush()

    def _commit_rt(self) -> None:
        if not self._in_rt:
            return
        base = "".join(self._ruby_pending_base).strip()
        reading = "".join(self._ruby_current_rt).strip()
        if base and reading:
            self._ruby_pairs_buf.append((base, reading))
        self._ruby_pending_base = []
        self._ruby_current_rt = []
        self._in_rt = False

    def _close_ruby(self) -> None:
        if self._in_rt:
            self._commit_rt()
        if self._ruby_pairs_buf:
            base = "".join(b for b, _r in self._ruby_pairs_buf)
            reading = "".join(r for _b, r in self._ruby_pairs_buf)
            if base and reading:
                self.ruby.append((base, reading))
        self._ruby_pending_base = []
        self._ruby_current_rt = []
        self._ruby_pairs_buf = []
        self._in_ruby = False
        self._in_rt = False

    def _flush(self) -> None:
        if self._in_ruby:
            self._close_ruby()
        else:
            self._in_rt = False
        text = tidy_inline(_join_soft("".join(self._buffer)))
        self._buffer = []
        self._soft_break = False
        if text:
            kind = "heading" if self._heading_depth else "text"
            self.paragraphs.append(Paragraph(text=text, kind=kind))


def _join_soft(text: str) -> str:
    """Ganti penanda baris lunak (``SOFT_MARK``) dengan spasi di antara huruf/angka Latin
    (``He said<br/>hello``) atau hapus di antara huruf lain (``湊は<br/>笑った``)."""
    def repl(match: re.Match[str]) -> str:
        left = match.string[match.start() - 1:match.start()]
        right = match.string[match.end():match.end() + 1]
        latin = left.isascii() and right.isascii() and (left + right).strip(",;:").isalnum()
        return " " if latin and left and right else ""
    return _SOFT_JOIN_RE.sub(repl, text)


def tidy_inline(text: str) -> str:
    """Rapikan spasi dari indentasi sumber XHTML tanpa menyentuh spasi penuh di tengah.

    Spasi penuh (U+3000) di tepi dibuang karena itu indentasi paragraf.
    """
    text = _CJK_NEWLINE_RE.sub("", text)
    return _ASCII_SPACE_RE.sub(" ", text).strip(" 　")


def extract_xhtml(markup: str) -> tuple[list[Paragraph], list[tuple[str, str]]]:
    """Urai satu dokumen XHTML menjadi ``(paragraf, pasangan_ruby)``.

    DOCTYPE dibuang lebih dulu (``strip_doctype``); rujukan ke entitas yang dideklarasikan di
    internal subset-nya dibuang tanpa diperluas, kecuali nama entitas standar HTML
    (``&nbsp;``, ``&amp;``) yang tetap diperluas ``html.parser`` seperti tanpa subset.
    """
    markup, declared = strip_doctype(markup)
    custom = sorted(name for name in declared if name + ";" not in HTML5_ENTITIES)
    if custom:
        pattern = "|".join(re.escape(name) for name in custom)
        markup, dropped = re.subn(f"&(?:{pattern});", "", markup)
        logger.warning("DOCTYPE berisi %d deklarasi entitas; %d rujukan dibuang tanpa diperluas",
                       len(custom), dropped)
    parser = XhtmlExtractor()
    parser.feed(markup)
    parser.close()
    return parser.paragraphs, parser.ruby


def strip_doctype(markup: str) -> tuple[str, frozenset[str]]:
    """Buang deklarasi ``<!DOCTYPE ...>`` beserta internal subset ``[...]``.

    ``html.parser`` mengakhiri DOCTYPE di ``>`` pertama, sehingga subset seperti
    ``[<!ENTITY x SYSTEM "file:///etc/passwd">]>`` bocor sebagai teks ``]>``. Komentar dan
    CDATA dilewati utuh (``<!DOCTYPE`` di dalamnya hanya teks). Pemindai subset
    (``_doctype_end``) menghormati kutipan, komentar, dan PI. DOCTYPE yang tidak ditutup dibuang
    hanya sampai awal elemen berikutnya, dengan peringatan, agar isi bab tidak ikut hilang.
    Entitas tidak pernah diperluas.

    Returns:
        ``(markup tanpa DOCTYPE, nama entitas umum yang dideklarasikan di subset)``.
    """
    parts: list[str] = []
    names: set[str] = set()
    pos = scan = 0
    while (match := _DOCTYPE_SCAN_RE.search(markup, scan)) is not None:
        token = match.group()
        if not token.upper().startswith("<!DOCTYPE"):
            close = markup.find("-->" if token == "<!--" else "]]>", match.end())
            scan = len(markup) if close < 0 else close + 3
            continue
        parts.append(markup[pos:match.start()])
        pos, subset, closed = _doctype_end(markup, match.end())
        if not closed:
            logger.warning("DOCTYPE tidak ditutup; dibuang sampai awal elemen berikutnya")
        names.update(_ENTITY_DECL_RE.findall(subset))
        scan = pos
    parts.append(markup[pos:])
    return "".join(parts), frozenset(names)


def _doctype_end(markup: str, start: int) -> tuple[int, str, bool]:
    """Ujung DOCTYPE yang namanya berakhir di ``start``: ``(posisi sesudahnya, subset, tertutup)``.

    Kepala (nama, PUBLIC/SYSTEM) dibaca sampai ``[`` atau ``>`` dengan menghormati kutipan.
    Subset dibaca per token (``_subset_token_end``) sampai ``]`` lalu ``>``. Elemen atau token
    yang tidak tertutup berarti DOCTYPE rusak (``_unclosed_doctype``).
    """
    quote, i = "", start
    while i < len(markup):
        char = markup[i]
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == ">":
            return i + 1, "", True
        elif char in "[<":
            break
        i += 1
    if i >= len(markup) or markup[i] != "[":
        return _unclosed_doctype(markup, start, -1)
    subset_start = i = i + 1
    while i < len(markup):
        if markup[i] == "]":
            close = re.compile(r"\s*>").match(markup, i + 1)
            return (close.end() if close else i + 1), markup[subset_start:i], close is not None
        after = _subset_token_end(markup, i)
        if after is None:
            return _unclosed_doctype(markup, start, subset_start)
        i = after
    return _unclosed_doctype(markup, start, subset_start)


def _subset_token_end(markup: str, i: int) -> int | None:
    """Posisi sesudah satu token internal subset di ``i`` (komentar, PI, deklarasi ``<!...>``
    berkutipan, atau satu huruf lain); ``None`` bila token tidak ditutup atau ``i`` adalah awal
    elemen (``<html``, ``</p``: subset tidak pernah ditutup)."""
    if markup.startswith("<!--", i):
        close = markup.find("-->", i + 4)
        return None if close < 0 else close + 3
    if markup.startswith("<?", i):
        close = markup.find("?>", i + 2)
        return None if close < 0 else close + 2
    if markup.startswith("<!", i):
        quote = ""
        for j in range(i + 2, len(markup)):
            char = markup[j]
            if quote:
                quote = "" if char == quote else quote
            elif char in "\"'":
                quote = char
            elif char == ">":
                return j + 1
        return None
    return None if markup[i] == "<" else i + 1


def _unclosed_doctype(markup: str, start: int, subset_start: int) -> tuple[int, str, bool]:
    """DOCTYPE rusak: dibuang sampai awal elemen pertama sesudah ``start`` (atau akhir teks)."""
    element = _ELEMENT_START_RE.search(markup, start)
    end = element.start() if element else len(markup)
    return end, markup[subset_start:end] if subset_start >= 0 else "", False


def decode_markup(raw: bytes, name: str) -> str:
    """Decode XHTML/XML menurut BOM atau deklarasi ``<?xml encoding=...?>``.

    Byte yang rusak diganti U+FFFD (dengan peringatan) alih-alih menggagalkan
    seluruh buku karena satu karakter.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        declared = _XML_ENCODING_RE.match(raw.removeprefix(b"\xef\xbb\xbf"))
        encoding = declared.group(1).decode("ascii") if declared else "utf-8"
    try:
        text = raw.decode("utf-8-sig" if encoding.lower() == "utf-8" else encoding,
                          errors="replace")
    except LookupError:
        logger.warning("encoding %s di %s tidak dikenal; dibaca sebagai UTF-8", encoding, name)
        text = raw.decode("utf-8-sig", errors="replace")
    if "�" in text:
        logger.warning("%s memuat byte yang tidak sah untuk %s", name, encoding)
    return text


def _local(tag: str) -> str:
    """Nama tag tanpa namespace: ``{http://...}spine`` menjadi ``spine``."""
    return tag.rsplit("}", 1)[-1]


def _parse_xml(raw: bytes, name: str) -> ET.Element:
    """Urai XML kecil (container, OPF, encryption) setelah memastikan tanpa entitas."""
    _reject_entities(raw, name)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise InputError(f"EPUB rusak: {name} bukan XML yang sah ({exc})") from exc


def _reject_entities(raw: bytes, name: str) -> None:
    """Tolak deklarasi entitas XML dengan expat, apa pun encoding berkasnya.

    OPF/container/encryption tidak pernah butuh deklarasi entitas; menolaknya
    menutup serangan "billion laughs" dan entitas eksternal tanpa defusedxml.
    Pencarian byte ``<!ENTITY`` saja bisa dilewati dengan XML UTF-16.

    Raises:
        InputError: Ada deklarasi entitas, atau XML tidak sah.
    """
    def refuse(*_args: object) -> None:
        raise InputError(f"EPUB ditolak: {name} memuat deklarasi entitas XML")

    parser = expat.ParserCreate()
    parser.EntityDeclHandler = refuse
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as exc:
        raise InputError(f"EPUB rusak: {name} bukan XML yang sah ({exc})") from exc


def _child(parent: ET.Element, name: str) -> ET.Element | None:
    return next((el for el in parent if _local(el.tag) == name), None)


def check_drm(zip_reader: _ZipReader) -> None:
    """Tolak EPUB ber-DRM.

    ``encryption.xml`` yang hanya berisi obfuscation font masih diizinkan;
    algoritma lain apa pun dianggap enkripsi konten.

    Raises:
        InputError: EPUB ber-DRM.
    """
    if any(marker in zip_reader.names for marker in DRM_MARKERS):
        raise InputError("EPUB ber-DRM tidak didukung")
    if ENCRYPTION_PATH not in zip_reader.names:
        return
    root = _parse_xml(zip_reader.read(ENCRYPTION_PATH), ENCRYPTION_PATH)
    algorithms = [el.get("Algorithm", "") for el in root.iter()
                  if _local(el.tag) == "EncryptionMethod"]
    if any(algo not in FONT_OBFUSCATION for algo in algorithms):
        raise InputError("EPUB ber-DRM tidak didukung")


def find_opf_path(zip_reader: _ZipReader) -> str:
    """Lokasi berkas OPF menurut ``container.xml``."""
    root = _parse_xml(zip_reader.read(CONTAINER_PATH), CONTAINER_PATH)
    for element in root.iter():
        if _local(element.tag) == "rootfile" and element.get("full-path"):
            return element.get("full-path", "")
    raise InputError("EPUB rusak: container.xml tidak menunjuk berkas OPF")


def opf_title(package: ET.Element) -> str:
    """Isi ``dc:title`` pertama, atau string kosong."""
    metadata = _child(package, "metadata")
    if metadata is None:
        return ""
    title = next((el for el in metadata.iter() if _local(el.tag) == "title"), None)
    return (title.text or "").strip() if title is not None else ""


def is_fixed_layout(package: ET.Element) -> bool:
    """``True`` untuk EPUB pre-paginated (EPUB 3) atau ``fixed-layout`` gaya lama."""
    metadata = _child(package, "metadata")
    if metadata is None:
        return False
    for meta in metadata.iter():
        if _local(meta.tag) != "meta":
            continue
        prop = meta.get("property") or meta.get("name") or ""
        value = (meta.text or meta.get("content") or "").strip().lower()
        if prop == "rendition:layout" and value == "pre-paginated":
            return True
        if prop == "fixed-layout" and value == "true":
            return True
    return False


def spine_documents(package: ET.Element, opf_path: str) -> list[str]:
    """Nama entri ZIP dokumen XHTML sesuai urutan spine, tanpa ``linear="no"``.

    Href di manifest relatif terhadap folder OPF dan bisa ter-URL-encode.
    Dokumen yang disebut lebih dari sekali hanya diambil pada kemunculan pertama.
    """
    manifest = _child(package, "manifest")
    spine = _child(package, "spine")
    if manifest is None or spine is None:
        raise InputError("EPUB rusak: OPF tanpa manifest atau spine")
    base = posixpath.dirname(opf_path)
    items = {}
    for item in manifest:
        href = unquote((item.get("href") or "").split("#", 1)[0])
        if item.get("id") and href:
            joined = href.lstrip("/") if href.startswith("/") else posixpath.join(base, href)
            path = posixpath.normpath(joined)
            if path != "." and not path.startswith(".."):
                items[item.get("id")] = (path, item.get("media-type", ""))
    documents: list[str] = []
    for itemref in spine:
        if _local(itemref.tag) != "itemref" or itemref.get("linear", "yes") == "no":
            continue
        path, media_type = items.get(itemref.get("idref", ""), ("", ""))
        if not path:
            logger.warning("itemref %s tidak ada di manifest", itemref.get("idref"))
        elif media_type in XHTML_TYPES and path not in documents:
            documents.append(path)
    return documents


def read_epub(path: Path, title: str | None = None) -> Document:
    """Baca EPUB menjadi ``Document`` dengan ruby tersimpan di ``doc.ruby``.

    Args:
        path: Lokasi berkas ``.epub``.
        title: Judul; bawaan ``dc:title``, lalu nama berkas.

    Returns:
        Dokumen dengan ``fmt="epub"``.

    Raises:
        InputError: Bukan EPUB, rusak, ber-DRM, fixed-layout, terlalu besar,
            atau tidak berisi teks.
    """
    path = Path(path)
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise InputError(f"{path.name} bukan EPUB/ZIP yang bisa dibaca: {exc}") from exc
    with archive:
        zip_reader = _ZipReader(archive)
        check_drm(zip_reader)
        opf_path = find_opf_path(zip_reader)
        package = _parse_xml(zip_reader.read(opf_path), opf_path)
        if is_fixed_layout(package):
            raise InputError(FIXED_LAYOUT_HINT)
        paragraphs: list[Paragraph] = []
        ruby: dict[str, str] = {}
        for name in spine_documents(package, opf_path):
            if name not in zip_reader.names:
                logger.warning("dokumen spine %s tidak ada di ZIP, dilewati", name)
                continue
            found, pairs = extract_xhtml(decode_markup(zip_reader.read(name), name))
            paragraphs.extend(found)
            if len(paragraphs) > MAX_PARAGRAPHS:
                raise InputError(f"EPUB ditolak: lebih dari {MAX_PARAGRAPHS} paragraf")
            for base, reading in pairs:
                ruby.setdefault(base, reading)
    if not paragraphs:
        raise InputError(f"{path.name} tidak berisi teks yang bisa diterjemahkan")
    logger.debug("epub: %d paragraf, %d ruby, %d byte dibaca",
                 len(paragraphs), len(ruby), zip_reader.bytes_read)
    return Document(
        title=title or opf_title(package) or path.stem,
        paragraphs=paragraphs, ruby=ruby, source_path=str(path), fmt="epub",
    )


_HTML_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def read_html(
    path: Path, title: str | None = None, encoding: str | None = None
) -> Document:
    """Baca berkas ``.html``/``.htm``/``.xhtml`` mandiri beserta tag ``<ruby>``."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"tidak bisa membaca {path}: {exc.strerror or exc}") from exc
    if len(raw) > MAX_ENTRY_BYTES:
        raise InputError(f"HTML ditolak: ukuran melebihi {MAX_ENTRY_BYTES} byte")
    if encoding:
        try:
            markup = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            raise InputError(f"HTML tidak bisa di-decode sebagai {encoding}: {exc}") from exc
    else:
        markup = decode_markup(raw, path.name)
    paragraphs, pairs = extract_xhtml(markup)
    if not paragraphs:
        raise InputError(f"{path.name} tidak berisi teks yang bisa diterjemahkan")
    ruby: dict[str, str] = {}
    for base, reading in pairs:
        ruby.setdefault(base, reading)
    found_title = ""
    title_match = _HTML_TITLE_RE.search(markup)
    if title_match:
        found_title = tidy_inline(html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))))
    return Document(
        title=title or found_title or path.stem,
        paragraphs=paragraphs,
        ruby=ruby,
        source_path=str(path),
        fmt="html",
    )
''')

MODUL['jptrans.readers.pages'] = (
    False,
r'''"""Masukan komik: ``pages.json`` dari OCR mana pun, plus pembuat opsional via Tesseract.

Standard library tidak bisa men-decode JPEG/PNG, apalagi menemukan balon
dialog. Karena itu jptrans tidak melakukan OCR sendiri; ia menerima teks per
balon dalam format netral::

    {"title": "...", "pages": [{"page": 1, "image": "001.jpg",
      "bubbles": [{"id": 1, "text": "...", "box": [x, y, w, h]}]}]}

Format ini bisa dibuat oleh manga-ocr, mokuro, layanan cloud, atau ketikan
tangan. Tiap balon menjadi satu ``Paragraph`` dengan
``meta={"page", "bubble", "image", "box"}``, sehingga pipeline terjemahan untuk
komik sama persis dengan novel.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..errors import InputError, JptransError
from ..models import Document, Paragraph
from ..textnorm import decode_unicode_text

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")
OCR_TIMEOUT_SECONDS = 120
TESSERACT_HINT = (
    "Tesseract tidak ditemukan. Pasang dulu beserta data bahasa Jepang:\n"
    "  macOS   : brew install tesseract tesseract-lang\n"
    "  Debian  : sudo apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert\n"
    "  Windows : installer UB Mannheim (github.com/UB-Mannheim/tesseract), centang Japanese\n"
    "  Termux  : pkg install tesseract, lalu unduh jpn_vert.traineddata dari tessdata_best\n"
    "            ke $PREFIX/share/tessdata"
)
# Tesseract jpn sering menyisipkan spasi atau baris baru di antara karakter Jepang.
_CJK_GAP_RE = re.compile(
    r"(?<=[^\x00-\x7f])(?:[ \t]*\n[ \t]*(?!\n)|[ \t]+)(?=[^\x00-\x7f])"
)
_DIGITS_RE = re.compile(r"(\d+)")


def parse_pages(data: Any, title: str) -> Document:
    """Ubah objek ``pages.json`` yang sudah di-parse menjadi ``Document``.

    Args:
        data: Hasil ``json.loads``.
        title: Judul cadangan bila ``data`` tidak memuat ``"title"``.

    Returns:
        Dokumen dengan ``fmt="pages"``; balon tanpa teks dilewati.

    Raises:
        InputError: Struktur tidak sesuai format (pesan menyebut letak galatnya).
    """
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        raise InputError('pages.json harus berupa objek dengan daftar "pages"')
    paragraphs: list[Paragraph] = []
    for page_pos, page in enumerate(data["pages"], start=1):
        paragraphs.extend(_page_paragraphs(page, page_pos))
    doc_title = data.get("title") if isinstance(data.get("title"), str) else ""
    logger.debug("pages: %d halaman, %d balon", len(data["pages"]), len(paragraphs))
    return Document(title=doc_title or title, paragraphs=paragraphs, fmt="pages")


def _page_paragraphs(page: Any, page_pos: int) -> list[Paragraph]:
    where = f"halaman ke-{page_pos}"
    if not isinstance(page, dict) or not isinstance(page.get("bubbles", []), list):
        raise InputError(f'pages.json {where}: harus objek dengan daftar "bubbles"')
    page_no = _as_int(page.get("page", page_pos), f"{where}: page")
    image = page.get("image", "")
    if not isinstance(image, str):
        raise InputError(f"pages.json {where}: image harus teks")
    result = []
    for bubble_pos, bubble in enumerate(page.get("bubbles", []), start=1):
        spot = f"{where} balon ke-{bubble_pos}"
        if not isinstance(bubble, dict) or not isinstance(bubble.get("text", ""), str):
            raise InputError(f"pages.json {spot}: harus objek dengan text berupa teks")
        text = bubble.get("text", "").strip()
        if not text:
            continue
        meta = {
            "page": page_no,
            "bubble": _as_int(bubble.get("id", bubble_pos), f"{spot}: id"),
            "image": image,
            "box": _as_box(bubble.get("box"), spot),
        }
        result.append(Paragraph(text=text, meta=meta))
    return result


def _as_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"pages.json {where} harus bilangan bulat, bukan {value!r}")
    return value


def _as_box(value: Any, where: str) -> list[float] | None:
    if value is None:
        return None
    numbers_ok = isinstance(value, list) and all(
        isinstance(n, (int, float)) and not isinstance(n, bool) for n in value
    )
    if not numbers_ok or len(value) != 4:
        raise InputError(f"pages.json {where}: box harus [x, y, w, h]")
    return list(value)


def read_pages(path: Path, title: str | None = None) -> Document:
    """Baca berkas ``pages.json`` dari disk (UTF-8, boleh ber-BOM, atau UTF-16 ber-BOM).

    Args:
        path: Lokasi berkas.
        title: Judul; bawaan ``"title"`` di berkas, lalu nama berkas.

    Raises:
        InputError: Berkas tidak bisa dibaca, bukan JSON, atau strukturnya salah.
    """
    path = Path(path)
    try:
        text = decode_unicode_text(path.read_bytes())
    except OSError as exc:
        raise InputError(f"tidak bisa membaca {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise InputError(f"{path.name} harus UTF-8 atau UTF-16 ber-BOM "
                         f"(byte ke-{exc.start})") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path.name} bukan JSON yang sah (baris {exc.lineno})") from exc
    doc = parse_pages(data, path.stem)
    if title:
        doc.title = title
    doc.source_path = str(path)
    return doc


def natural_key(name: str) -> list[int | str]:
    """Kunci urut alami: ``2.jpg`` sebelum ``10.jpg``."""
    return [int(part) if part.isdigit() else part.casefold() for part in _DIGITS_RE.split(name)]


def list_images(folder: Path) -> list[Path]:
    """Gambar halaman di ``folder``, diurutkan secara alami."""
    images = [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(images, key=lambda p: natural_key(p.name))


def clean_ocr_text(text: str) -> str:
    """Rapikan keluaran Tesseract: hapus spasi/baris baru di antara karakter Jepang."""
    return _CJK_GAP_RE.sub("", text).strip()


def ocr_images_to_pages(folder: Path, out: Path, lang: str = "jpn_vert") -> Path:
    """Buat ``pages.json`` dari folder gambar komik dengan Tesseract (opsional).

    Satu halaman menjadi satu balon berisi seluruh teks halaman: memotong
    balon dialog butuh dekoder gambar (Pillow) atau detektor balon, yang
    sengaja tidak dijadikan dependensi. Akurasi Tesseract pada halaman manga
    utuh terbatas; hasilnya sebaiknya diperiksa sebelum diterjemahkan.

    Args:
        folder: Folder berisi gambar halaman (``001.jpg``, ``002.png``, ...).
        out: Lokasi ``pages.json`` yang akan ditulis.
        lang: Model Tesseract; ``jpn_vert`` untuk tategaki, ``jpn`` untuk horizontal.

    Returns:
        ``out`` setelah berkas ditulis.

    Raises:
        InputError: Tesseract tidak terpasang, folder kosong, atau OCR gagal.
        JptransError: Berkas keluaran tidak bisa ditulis.
    """
    tesseract = shutil.which("tesseract")
    if tesseract is None:
        raise InputError(TESSERACT_HINT)
    folder = Path(folder)
    if not folder.is_dir():
        raise InputError(f"folder gambar tidak ditemukan: {folder}")
    images = list_images(folder)
    if not images:
        raise InputError(f"tidak ada gambar ({', '.join(IMAGE_SUFFIXES)}) di {folder}")

    pages = []
    for number, image in enumerate(images, start=1):
        logger.info("OCR halaman %d/%d", number, len(images))
        text = clean_ocr_text(_run_tesseract(tesseract, image, lang))
        bubbles = [{"id": 1, "text": text, "box": None}] if text else []
        pages.append({"page": number, "image": image.name, "bubbles": bubbles})

    payload = {"title": folder.name, "pages": pages}
    out_path = Path(out)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise JptransError(f"tidak bisa menulis {out}: {exc.strerror or exc}") from exc
    return out_path


def _run_tesseract(tesseract: str, image: Path, lang: str) -> str:
    # psm 5 = satu blok teks vertikal; psm 6 = satu blok teks horizontal.
    psm = "5" if lang.endswith("_vert") else "6"
    command = [tesseract, str(image), "stdout", "-l", lang, "--psm", psm]
    try:
        done = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace",
            timeout=OCR_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise InputError(f"OCR {image.name} melebihi {OCR_TIMEOUT_SECONDS} detik") from exc
    except OSError as exc:
        raise InputError(f"tesseract tidak bisa dijalankan: {exc}") from exc
    if done.returncode != 0:
        detail = done.stderr.strip().splitlines()[-1:] or ["tanpa pesan"]
        raise InputError(f"tesseract gagal pada {image.name}: {detail[0]}")
    return done.stdout
''')

MODUL['jptrans.readers.subtitle'] = (
    False,
r'''"""Pembaca subtitle SRT, WebVTT (``.vtt``), dan ASS/SSA (``.ass``/``.ssa``).

Setiap blok atau baris dialog subtitle diubah menjadi ``Paragraph`` dengan
``meta={"index", "start", "end", ...}`` agar penulis subtitle bisa memulihkan
timing aslinya secara presisi maupun mengonversi lintas format subtitle.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import InputError
from ..models import Document, Paragraph
from .txt import read_text_file

logger = logging.getLogger(__name__)

SUBTITLE_FORMATS = frozenset({"srt", "vtt", "ass"})

_SRT_TIME = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
_SRT_TIMING_RE = re.compile(_SRT_TIME + r"\s*-->\s*" + _SRT_TIME)
_VTT_TIME = r"(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{1,3})"
_VTT_TIMING_RE = re.compile(
    _VTT_TIME + r"\s*-->\s*" + _VTT_TIME + r"(?:[ \t]+([^\n]*))?"
)
_BLOCK_SPLIT_RE = re.compile(r"\n[ \t]*\n")
_VTT_SKIP_HEADS = ("NOTE", "STYLE", "REGION")
_VTT_RUBY_RE = re.compile(
    r"<ruby\b[^>]*>(.*?)</ruby>", re.IGNORECASE | re.DOTALL
)
_VTT_RT_PAIR_RE = re.compile(
    r"([^<]+?)(?:<rp\b[^>]*>.*?</rp>)*<rt\b[^>]*>(.*?)</rt>(?:<rp\b[^>]*>.*?</rp>)*",
    re.IGNORECASE | re.DOTALL,
)
_VTT_INLINE_TAG_RE = re.compile(
    r"<(?:/?(?:c|v|lang|ruby|rt|rp)(?:\.[^>\n]*)?(?:\s[^>\n]*)?|\d{2}:\d{2}(?::\d{2})?\.\d{3})>",
    re.IGNORECASE,
)
_ASS_OVERRIDE_RE = re.compile(r"\{[^{}\n]*\}")


def format_timestamp(
    hours: str, minutes: str, seconds: str, millis: str
) -> str:
    """Bentuk baku SRT ``HH:MM:SS,mmm``; ``"5"`` milidetik berarti 500 ms."""
    h = int(hours) if hours else 0
    return f"{h:02d}:{minutes}:{seconds},{millis.ljust(3, '0')}"


def parse_srt(text: str, title: str) -> Document:
    """Urai isi berkas SRT menjadi ``Document`` (satu paragraf per cue)."""
    paragraphs: list[Paragraph] = []
    for number, block in enumerate(_BLOCK_SPLIT_RE.split(text.strip()), start=1):
        paragraph = _parse_srt_block(block.strip("\n"), number)
        if paragraph is not None:
            paragraphs.append(paragraph)
    if not paragraphs:
        raise InputError("tidak ada blok subtitle SRT yang sah di berkas ini")
    logger.debug("srt: %d blok", len(paragraphs))
    return Document(title=title, paragraphs=paragraphs, fmt="srt")


def _parse_srt_block(block: str, number: int) -> Paragraph | None:
    lines = block.split("\n")
    timing_at = next(
        (i for i, line in enumerate(lines) if _SRT_TIMING_RE.search(line)), None
    )
    if timing_at is None:
        logger.warning("blok SRT ke-%d tanpa baris timing, dilewati", number)
        return None
    match = _SRT_TIMING_RE.search(lines[timing_at])
    assert match is not None
    times = match.groups()
    index_line = lines[timing_at - 1].strip() if timing_at else ""
    text = "\n".join(
        line.strip() for line in lines[timing_at + 1:] if line.strip()
    )
    if not text:
        return None
    meta = {
        "index": int(index_line) if index_line.isdigit() else number,
        "start": format_timestamp(*times[:4]),
        "end": format_timestamp(*times[4:]),
    }
    return Paragraph(text=text, meta=meta)


def parse_vtt(text: str, title: str) -> Document:
    """Urai isi berkas WebVTT (``.vtt``) beserta furigana ``<ruby>`` menjadi ``Document``."""
    stripped = text.lstrip("\ufeff").lstrip()
    if not stripped.startswith("WEBVTT"):
        raise InputError("berkas WebVTT harus diawali header WEBVTT")
    blocks = _BLOCK_SPLIT_RE.split(stripped)
    paragraphs: list[Paragraph] = []
    ruby: dict[str, str] = {}
    cue_num = 0
    for block in blocks[1:]:
        clean = block.strip("\n")
        if not clean or clean.startswith(_VTT_SKIP_HEADS):
            continue
        cue_num += 1
        paragraph = _parse_vtt_block(clean, cue_num, ruby)
        if paragraph is not None:
            paragraphs.append(paragraph)
    if not paragraphs:
        raise InputError("tidak ada cue WebVTT yang sah di berkas ini")
    logger.debug("vtt: %d cue, %d ruby", len(paragraphs), len(ruby))
    return Document(title=title, paragraphs=paragraphs, ruby=ruby, fmt="vtt")


def _strip_vtt_ruby(line: str, ruby: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        pairs = _VTT_RT_PAIR_RE.findall(inner)
        if not pairs:
            return _VTT_INLINE_TAG_RE.sub("", inner)
        base = "".join(b.strip() for b, _r in pairs)
        reading = "".join(r.strip() for _b, r in pairs)
        if base and reading:
            ruby.setdefault(base, reading)
        leftover = _VTT_RT_PAIR_RE.sub("", inner)
        return base + _VTT_INLINE_TAG_RE.sub("", leftover)

    return _VTT_RUBY_RE.sub(repl, line)


def _parse_vtt_block(
    block: str, number: int, ruby: dict[str, str]
) -> Paragraph | None:
    lines = block.split("\n")
    timing_at = next(
        (i for i, line in enumerate(lines) if _VTT_TIMING_RE.search(line)), None
    )
    if timing_at is None:
        return None
    match = _VTT_TIMING_RE.search(lines[timing_at])
    assert match is not None
    h1, m1, s1, ms1, h2, m2, s2, ms2, settings = match.groups()
    cue_id = lines[timing_at - 1].strip() if timing_at else ""
    raw_lines = [
        _VTT_INLINE_TAG_RE.sub("", _strip_vtt_ruby(line, ruby)).strip()
        for line in lines[timing_at + 1:]
    ]
    text = "\n".join(line for line in raw_lines if line)
    if not text:
        return None
    meta: dict[str, object] = {
        "index": int(cue_id) if cue_id.isdigit() else number,
        "start": format_timestamp(h1 or "0", m1, s1, ms1),
        "end": format_timestamp(h2 or "0", m2, s2, ms2),
    }
    if settings and settings.strip():
        meta["vtt_settings"] = settings.strip()
    return Paragraph(text=text, meta=meta)


def parse_ass(text: str, title: str) -> Document:
    """Urai berkas subtitle ASS/SSA (``[Events]`` ``Dialogue:``) menjadi ``Document``."""
    lines = text.splitlines()
    in_events = False
    columns = [
        "layer", "start", "end", "style", "name",
        "marginl", "marginr", "marginv", "effect", "text",
    ]
    paragraphs: list[Paragraph] = []
    header_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_events = stripped.lower() == "[events]"
            if not in_events and not paragraphs:
                header_lines.append(line)
            continue
        if not in_events:
            if not paragraphs:
                header_lines.append(line)
            continue
        lower = stripped.lower()
        if lower.startswith("format:"):
            parsed_cols = [
                col.strip().lower()
                for col in stripped.split(":", 1)[1].split(",")
            ]
            if "text" in parsed_cols and "start" in parsed_cols and "end" in parsed_cols:
                columns = parsed_cols
            continue
        if not lower.startswith("dialogue:"):
            continue
        payload = stripped.split(":", 1)[1].lstrip()
        parts = payload.split(",", len(columns) - 1)
        if len(parts) < len(columns):
            continue
        row = dict(zip(columns, parts))
        raw_dialogue = (
            row["text"]
            .replace("\\N", "\n")
            .replace("\\n", "\n")
            .replace("\\h", " ")
        )
        clean_text = _ASS_OVERRIDE_RE.sub("", raw_dialogue).strip()
        if not clean_text:
            continue
        start_srt = _ass_time_to_srt(row["start"].strip())
        end_srt = _ass_time_to_srt(row["end"].strip())
        meta = {
            "index": len(paragraphs) + 1,
            "start": start_srt,
            "end": end_srt,
            "ass_style": row.get("style", "Default").strip() or "Default",
            "ass_actor": row.get("name", "").strip(),
        }
        paragraphs.append(Paragraph(text=clean_text, meta=meta))
    if not paragraphs:
        raise InputError("tidak ada baris Dialogue ASS/SSA yang sah di berkas ini")
    logger.debug("ass: %d baris dialog", len(paragraphs))
    return Document(title=title, paragraphs=paragraphs, fmt="ass")


def _ass_time_to_srt(stamp: str) -> str:
    match = re.match(r"^(\d+):(\d{2}):(\d{2})[.,](\d{1,3})$", stamp)
    if not match:
        raise InputError(f"waktu ASS/SSA tidak sah: {stamp!r}")
    h, m, s, frac = match.groups()
    ms = f"{int(frac) * 10:03d}" if len(frac) == 2 else frac.ljust(3, "0")
    return f"{int(h):02d}:{m}:{s},{ms[:3]}"


def read_srt(
    path: Path, title: str | None = None, encoding: str | None = None
) -> Document:
    """Baca berkas ``.srt`` dari disk."""
    path = Path(path)
    doc = parse_srt(read_text_file(path, encoding), title or path.stem)
    doc.source_path = str(path)
    return doc


def read_vtt(
    path: Path, title: str | None = None, encoding: str | None = None
) -> Document:
    """Baca berkas ``.vtt`` (WebVTT) dari disk."""
    path = Path(path)
    doc = parse_vtt(read_text_file(path, encoding), title or path.stem)
    doc.source_path = str(path)
    return doc


def read_ass(
    path: Path, title: str | None = None, encoding: str | None = None
) -> Document:
    """Baca berkas ``.ass`` atau ``.ssa`` dari disk."""
    path = Path(path)
    doc = parse_ass(read_text_file(path, encoding), title or path.stem)
    doc.source_path = str(path)
    return doc
''')

MODUL['jptrans.readers.txt'] = (
    False,
r'''"""Pembaca teks polos dan deteksi encoding Jepang tanpa pustaka luar.

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
''')

MODUL['jptrans.readings'] = (
    False,
r'''"""Penyelesaian bacaan kanji, validasi fonetis nama dari mesin, dan peta masking.

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
''')

MODUL['jptrans.residue'] = (
    False,
r'''"""Sisa huruf Jepang di keluaran mesin: gema, huruf sisa, judul 『…』, dan emotikon.

Pipeline memakai modul ini untuk memutuskan apakah keluaran mesin sudah benar-benar
diterjemahkan (``pipeline.Translator._accept_outputs``, ``_has_residue``, dan jalur
cadangan ``_presubstitute``). API publiknya:

- ``looks_untranslated(raw, sent)``: keluaran kosong atau gema persis masukan.
- ``residue_letters(raw, sent, keep)``: jumlah huruf Jepang sisa (nol = bersih).
- ``has_japanese_residue(raw, sent, keep)``: ``residue_letters(...) > 0``.
- ``japanese_letters(text)``: jumlah huruf Jepang (kana atau kanji) di teks.

Yang tidak dihitung sisa: penanda ``[[E#]]`` (juga bentuk lebar penuh dan berisi
tambahan mesin), tulisan ``keep`` beserta potongannya, kutipan judul 『…』 yang disalin
dari sumber, emotikon yang disalin dari sumber, tanda baca Jepang, dan deretan ``〇``.
Karakter kompatibilitas (㌔, ㋐, ⽇) dihitung menurut bentuk NFKC-nya. Modul ini
dipisah dari ``pipeline`` (dulu fungsi-fungsinya ada di sana) tanpa perubahan perilaku.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable

from .protect import EXACT_TOKEN_RE
from .textnorm import HIRAGANA, KANJI, KATAKANA, contains_japanese, is_hiragana_text

logger = logging.getLogger(__name__)

# Setiap huruf Jepang di keluaran mesin adalah sisa, kecuali yang berasal dari bagian
# di bawah ini (lihat ``residue_letters``).
_LOOSE_TOKEN_RE = re.compile(r"[\[［]{2}\s*[EＥ]\s*[0-9０-９]+[^\[\]［］\n]{0,40}[\]］]{2}")
"""Penanda ``[[E#]]``, juga bentuk lebar penuh atau berisi tambahan mesin (``[[E1:田中]]``)."""
_TITLE_QUOTE_RE = re.compile(r"『[^『』\n]{1,60}』")
"""Kutipan judul 『…』; hanya dibebaskan bila disalin utuh dari sumber (``_is_title_quote``)."""
_EMOTICON_RE = re.compile(r"[^\sA-Za-z0-9()（）]{0,2}[(（][^()（）\n]{1,16}[)）]"
                          r"[^\sA-Za-z0-9()（）]{0,2}")
"""Calon emotikon: isi kurung pendek plus "lengan" sampai 2 karakter (ヽ(・∀・)ノ, (つ´∀`)つ)."""
EMOTICON_ARM_LETTERS = frozenset("つっノﾉゞヾヽシｼミﾐヘﾍ")
"""Huruf Jepang yang lazim menjadi "lengan" emotikon; huruf lengan lain (``ね(^^)``) dihitung."""
EMOTICON_MARKS = frozenset("´`｀∀ωДдﾟ°・･＾^;；_＿≧≦▽∇ε◕‿◡•ᴗ゜｡〃<>＜＞*＊ー～〜∩⊂⊃﹏")
"""Simbol khas emotikon; calon tanpa satu pun simbol ini (``(笑)``) bukan emotikon."""
_COMPAT_RE = re.compile("[\u2e80-\u2fdf\u3200-\u33ff]")
"""Karakter kompatibilitas: radikal (⺀-⿕) dan huruf/kata berlingkaran atau berkotak (㋐ ㌔ ㍻)."""
_RADICALS_END = "\u2fdf"
_RADICAL_AS_KANJI = "\u4e00"
"""Pengganti radikal tanpa dekomposisi NFKC (⻑), agar dihitung satu kanji."""
PLACEHOLDER_MARKS = frozenset("〇")
"""``〇`` (U+3007) dihitung kanji oleh ``textnorm``, tetapi deretan ``〇〇`` adalah tanda sensor."""
_JAPANESE_RUN_RE = re.compile(f"[{HIRAGANA}{KATAKANA}{KANJI}]+")


def looks_untranslated(raw: str, sent: str) -> bool:
    """Kenali keluaran mesin yang hanya mengembalikan masukannya, atau kosong.

    Google kadang mengembalikan satu baris batch tanpa diterjemahkan, dan
    MyMemory kadang memantulkan masukan apa adanya. Keluaran kosong (atau
    hanya spasi) untuk kalimat berhuruf Jepang juga bukan terjemahan: bila
    diterima, kalimatnya lenyap dari hasil dengan status ``ok``. Keluaran
    seperti itu dianggap gagal agar kalimatnya dicoba ulang sendiri atau
    diteruskan ke mesin berikutnya. Kalimat yang isinya hanya penanda
    (``[[E1]]``) memang boleh kembali sama persis.

    Args:
        raw: Keluaran mentah mesin.
        sent: Teks termasking yang dikirim.

    Returns:
        ``True`` bila ``sent`` berisi huruf Jepang dan ``raw`` kosong atau sama
        dengan ``sent`` setelah semua spasi diabaikan.
    """
    if not contains_japanese(EXACT_TOKEN_RE.sub("", sent)):
        return False
    bare = "".join(raw.split())
    return not bare or bare == "".join(sent.split())


def japanese_letters(text: str) -> int:
    """Jumlah huruf Jepang (kana atau kanji) di teks; tanda baca Jepang tidak dihitung."""
    return sum(1 for ch in text if contains_japanese(ch))


def has_japanese_residue(raw: str, sent: str, keep: Iterable[str] = ()) -> bool:
    """Kenali keluaran yang masih memuat huruf Jepang, sekecil apa pun.

    ``looks_untranslated`` hanya menangkap gema persis; fungsi ini menangkap
    sisa apa saja, dari klausa yang disalin utuh sampai satu kata
    (``Dia makan 寿司.``). Lihat ``residue_letters`` untuk bagian yang tidak dihitung.

    Args:
        raw: Keluaran mentah mesin.
        sent: Teks yang dikirim (termasking).
        keep: Tulisan Jepang yang boleh tetap ada di keluaran.

    Returns:
        ``True`` bila ``residue_letters`` lebih dari nol.
    """
    return residue_letters(raw, sent, keep) > 0


def residue_letters(raw: str, sent: str, keep: Iterable[str] = ()) -> int:
    """Hitung huruf Jepang sisa di keluaran mesin.

    Setiap huruf Jepang (kana atau kanji) di keluaran dihitung, kecuali yang
    berasal dari:

    - penanda ``[[E#]]``, termasuk bentuk lebar penuh (``［［E1］］``) dan penanda yang
      diberi tambahan oleh mesin (``[[E1:田中]]``);
    - tulisan ``keep``, yaitu entri yang sengaja dibiarkan Jepang (tidak bisa
      dirender, mis. nama tanpa bacaan dengan ``unknown_reading="keep"``, atau bentuk
      akhir berhuruf Jepang di jalur cadangan), beserta potongannya (``美咲`` dari
      ``朝倉美咲``);
    - kutipan judul 『…』 yang disalin utuh dari sumber dan bukan ucapan
      (``_is_title_quote``);
    - emotikon yang disalin utuh dari sumber (``_is_emoticon``: ``(つ´∀`)つ``,
      ``ヽ(・∀・)ノ``).

    Tanda baca Jepang tanpa huruf (「」、。・ー) memang tidak pernah dihitung, begitu
    juga deretan ``〇`` saja (pengganti nama yang disensor, ``〇〇さん``). Karakter
    kompatibilitas dihitung menurut bentuk NFKC-nya (``_fold_compat``: ㌔ = キロ, ㋐ = ア,
    ⽇ = 日; ㎏ dan ㉑ bukan huruf Jepang).

    Tulisan ``keep`` hanya berlaku bila muncul di kalimat ``sent`` itu sendiri, dan
    potongannya hanya bila panjangnya minimal dua huruf atau bukan hiragana (``美咲``
    dan ``鬼`` boleh, ``の`` dari ``鬼の手`` tidak).

    Args:
        raw: Keluaran mentah mesin.
        sent: Teks yang dikirim (termasking).
        keep: Tulisan Jepang yang boleh tetap ada di keluaran.

    Returns:
        Jumlah huruf Jepang sisa; nol berarti keluaran bersih.
    """
    raw, sent = _fold_compat(raw), _fold_compat(sent)
    allowed = sorted({folded for folded in map(_fold_compat, keep) if folded and folded in sent},
                     key=len, reverse=True)

    def strip(text: str) -> str:
        """Ganti penanda (juga bentuk longgarnya) dan tulisan ``allowed`` dengan spasi."""
        text = _LOOSE_TOKEN_RE.sub(" ", text)
        for surface in allowed:
            text = text.replace(surface, " ")
        return text

    source, output = strip(sent), strip(raw)
    if not contains_japanese(output):
        return 0
    output = _TITLE_QUOTE_RE.sub(
        lambda m: " " if _is_title_quote(m.group(0), source) else m.group(0), output)
    output = _EMOTICON_RE.sub(lambda m: _drop_emoticon(m.group(0), source), output)
    count = 0
    for run in _JAPANESE_RUN_RE.findall(output):
        core = run.strip("ー・ｰ･")
        if core and (set(core) <= PLACEHOLDER_MARKS
                     or (_free_fragment(core) and any(core in surface for surface in allowed))):
            continue
        count += japanese_letters(run)
    return count


def _free_fragment(core: str) -> bool:
    """Potongan tulisan keep yang boleh dibebaskan: dua huruf atau lebih, atau bukan hiragana.

    Hiragana tunggal (の, と) adalah partikel yang bisa muncul di mana saja, jadi
    tidak dibebaskan walau ada di dalam tulisan keep (鬼の手).
    """
    return japanese_letters(core) >= 2 or not is_hiragana_text(core)


def _fold_compat(text: str) -> str:
    """Ganti karakter kompatibilitas Jepang dengan bentuk NFKC-nya untuk penghitungan sisa.

    ㌔ menjadi キロ, ㋐ menjadi ア, ⽇ menjadi 日, ㍻ menjadi 平成; ㎏ dan ㉑ menjadi huruf
    Latin dan angka. Radikal tanpa dekomposisi (⻑, ⺅) dihitung satu kanji. Hanya dipakai
    di dalam ``residue_letters``; teks keluaran tidak diubah.
    """
    def fold(match: re.Match[str]) -> str:
        """Bentuk NFKC satu karakter kompatibilitas; radikal tanpa dekomposisi jadi 一."""
        char = match.group(0)
        folded = unicodedata.normalize("NFKC", char)
        if folded == char and char <= _RADICALS_END:
            return _RADICAL_AS_KANJI
        return folded

    return _COMPAT_RE.sub(fold, text)


def _is_title_quote(quote: str, source: str) -> bool:
    """Kutipan 『…』 disalin utuh dari sumber dan isinya bukan ucapan.

    Ucapan di dalam 『』 (kutipan di dalam kutipan, suara telepon) kebanyakan
    hiragana (『待って』); judul karya memuat kanji atau katakana dan paling banyak
    separuh hurufnya hiragana (『ノルウェイの森』, 『君の名は。』).
    """
    if quote not in source:
        return False
    letters = [ch for ch in quote if contains_japanese(ch)]
    hiragana = sum(1 for ch in letters if is_hiragana_text(ch))
    return bool(letters) and hiragana * 2 <= len(letters)


def _drop_emoticon(candidate: str, source: str) -> str:
    """Buang emotikon dari calon ``_EMOTICON_RE`` bila disalin utuh dari sumber.

    "Lengan" regex bisa ikut menelan tanda baca atau huruf di sebelahnya
    (``(つ´∀`)つ。``, ``ね(^^)``), jadi dicoba dari bentuk terpanjang sampai inti
    kurungnya; yang pertama lolos ``_is_emoticon`` dan lengannya hanya memuat huruf
    lengan lazim (``EMOTICON_ARM_LETTERS``) saja yang dibuang, sisanya tetap dihitung.
    """
    opener = min(i for i in (candidate.find("("), candidate.find("（")) if i >= 0)
    closer = max(candidate.rfind(")"), candidate.rfind("）"))
    for start in range(opener + 1):
        for end in range(len(candidate), closer, -1):
            piece = candidate[start:end]
            arms = candidate[start:opener] + candidate[closer + 1:end]
            if (all(ch in EMOTICON_ARM_LETTERS for ch in arms if contains_japanese(ch))
                    and _is_emoticon(piece, source)):
                return candidate[:start] + " " + candidate[end:]
    return candidate


def _is_emoticon(candidate: str, source: str) -> bool:
    """Calon emotikon disalin utuh dari sumber, bersimbol khas, dan hurufnya tunggal.

    Huruf Jepang di emotikon selalu berdiri sendiri sebagai gambar (つ, ノ, ゞ);
    dua huruf berurutan (``(すし)``) berarti kata, bukan emotikon.
    """
    if candidate not in source or not EMOTICON_MARKS.intersection(candidate):
        return False
    return all(japanese_letters(run) <= 1 for run in _JAPANESE_RUN_RE.findall(candidate))
''')

MODUL['jptrans.romaji'] = (
    False,
r'''"""Romanisasi kana ke huruf Latin (Hepburn sesuai pedoman pemerintah Jepang 2025).

Tabel dibuat sendiri (bebas lisensi, tanpa pykakasi yang GPL). Aturan yang
dipakai mengikuti 令和7年内閣告示第4号 dan Q&A Bunka-cho (Feb 2026):

- ン selalu ``n`` (Shinbashi, bukan Shimbashi). Sebelum vokal atau ``y``
  diberi apostrof agar tidak ambigu: けんいち → ``ken'ichi``.
- Sokuon (っ/ッ) menggandakan konsonan berikutnya: がっこう → ``gakkō``.
  **Pilihan desain:** sebelum ``ch`` ditulis ``tch`` (マッチャ → ``matcha``),
  bukan ``cch`` seperti contoh resmi ``maccha``, karena ``tch`` lebih alami
  bagi pembaca dan merupakan ejaan internasional yang juga dihormati pedoman.
  Sokuon di akhir kata atau sebelum vokal (あっ) tidak ditulis.
- Tiga mode vokal panjang:

  ``macron``
      おう/おお → ō, うう → ū, ああ → ā, ええ → ē, ー → makron vokal sebelumnya
      (サーベル → ``sāberu``). えい tetap ``ei`` dan いい tetap ``ii``.
  ``kana``
      Ditulis apa adanya per kana; ー mengulang vokal (``saaberu``, ``satou``).
  ``plain``
      Tanda panjang dibuang (``tokyo``, ``sato``). Tidak resmi dan bisa
      bertabrakan (おおの dan おの sama-sama ``ono``), jadi kunci glosarium
      harus tetap bacaan kana, bukan hasil romanisasi.

Batas morfem: aturan kana tidak bisa melihat batas kata di dalam bacaan.
``おう`` selalu digabung menjadi ō (こういち ``Kōichi``, こうえん ``kōen``, そうえん
``sōen``, とうえい ``tōei``), KECUALI ``うえ``/``うお`` yang berada di akhir kata
(sebelum spasi, ・, tanda baca, atau akhir teks) atau yang menutup bacaan nama
keluarga di ``surnames.json`` (いのうえ ``Inoue``, juga いのうえさん). Kata kerja
seperti おもう tetap menjadi ``omō``. Penggabungan sebelum え/お hanya untuk
hiragana: ``ウエ``/``ウオ`` katakana adalah bunyi we/wo kata serapan
(ソフトウエア ``sofutouea``, オウエン ``Ouen``), jadi tetap dua suku kata.

Suku kata yang sudah dipanjangkan tidak menyerap vokal berikutnya: ほうおう
menjadi ``hōō`` (macron), ``hoo`` (plain), ``houou`` (kana). Mode plain selalu
sama dengan mode macron tanpa makron.

Nama asing katakana (``romanize_foreign``): tiap bagian nama (dipisah ・) dicari
di ``data/foreign_names.json`` (アリス → Alice); bagian yang tidak ada memakai
Hepburn. ``looks_japanese`` menandai bagian nama katakana yang tampak nama Jepang
(ハルカ, ユミコ); bagian di luar kamus yang tidak tampak Jepang ditanyakan ke mesin
(``pipeline.needs_foreign_lookup``).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache

from . import data
from .errors import ConfigError
from .textnorm import hira_to_kata, kata_to_hira, widen_halfwidth_kana

logger = logging.getLogger(__name__)

MODES = ("macron", "kana", "plain")

SOKUON = "ッ"
LONG_MARK = "ー"
SYLLABIC_N = "ン"

_MONOGRAPHS: dict[str, str] = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヰ": "i", "ヱ": "e", "ヲ": "o", SYLLABIC_N: "n",
    "ヴ": "vu", "ヷ": "va", "ヸ": "vi", "ヹ": "ve", "ヺ": "vo",
    # Kana kecil yang berdiri sendiri (ねぇ, ちょっ, ヶ月) dan katakana fonetis Ainu (ㇰ-ㇿ).
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ャ": "ya", "ュ": "yu", "ョ": "yo", "ヮ": "wa", "ヵ": "ka", "ヶ": "ke",
    "ㇰ": "ku", "ㇱ": "shi", "ㇲ": "su", "ㇳ": "to", "ㇴ": "nu",
    "ㇵ": "ha", "ㇶ": "hi", "ㇷ": "fu", "ㇸ": "he", "ㇹ": "ho",
    "ㇺ": "mu", "ㇻ": "ra", "ㇼ": "ri", "ㇽ": "ru", "ㇾ": "re", "ㇿ": "ro",
}

_KATAKANA_DAKUTEN = str.maketrans(
    "カキクケコサシスセソタチツテトハヒフヘホウ",
    "ガギグゲゴザジズゼゾダヂヅデドバビブベボヴ",
)
_KATAKANA_UNVOICE = str.maketrans(
    "ガギグゲゴザジズゼゾダヂヅデドバビブベボヴ",
    "カキクケコサシスセソタチツテトハヒフヘホウ",
)

# Yōon: kana baris -i + ャュョェ kecil. Akar konsonan digabung dengan vokalnya.
_YOON_STEMS = {
    "キ": "ky", "ギ": "gy", "シ": "sh", "ジ": "j", "チ": "ch", "ヂ": "j",
    "ニ": "ny", "ヒ": "hy", "ビ": "by", "ピ": "py", "ミ": "my", "リ": "ry",
}
_YOON_SMALL = {"ャ": "a", "ュ": "u", "ョ": "o", "ェ": "e"}

# Kombinasi untuk kata serapan dan nama asing.
_LOANWORD_DIGRAPHS = {
    "ファ": "fa", "フィ": "fi", "フェ": "fe", "フォ": "fo",
    "フャ": "fya", "フュ": "fyu", "フョ": "fyo",
    "ティ": "ti", "ディ": "di", "トゥ": "tu", "ドゥ": "du",
    "テュ": "tyu", "デュ": "dyu", "テョ": "tyo", "デョ": "dyo",
    "ウィ": "wi", "ウェ": "we", "ウォ": "wo", "イェ": "ye",
    "ヴァ": "va", "ヴィ": "vi", "ヴェ": "ve", "ヴォ": "vo",
    "ヴャ": "vya", "ヴュ": "vyu", "ヴョ": "vyo",
    "ツァ": "tsa", "ツィ": "tsi", "ツェ": "tse", "ツォ": "tso",
    "クァ": "kwa", "クィ": "kwi", "クェ": "kwe", "クォ": "kwo", "グァ": "gwa",
    "スィ": "si", "ズィ": "zi", "スュ": "syu", "ズュ": "zyu",
}

_DIGRAPHS: dict[str, str] = {
    **{stem + small: root + vowel
       for stem, root in _YOON_STEMS.items()
       for small, vowel in _YOON_SMALL.items()},
    **_LOANWORD_DIGRAPHS,
}

_BARE_VOWELS = frozenset("アイウエオァィゥェォ")
# Vokal yang bisa membuat う sebelumnya menjadi suku kata sendiri (い-の-う-え, Inoue),
# tetapi hanya di batas morfem (lihat ``_morpheme_boundary``).
_SPLITTING_VOWELS = frozenset("エオェォ")
_MACRONS = {"a": "ā", "i": "ī", "u": "ū", "e": "ē", "o": "ō"}
# Pasangan (vokal terakhir, vokal baru) yang dibaca sebagai satu vokal panjang.
# えい dan いい sengaja tidak ada: pedoman menulisnya ei dan ii.
_LONG_PAIRS = frozenset({("a", "a"), ("u", "u"), ("e", "e"), ("o", "o"), ("o", "u")})

_NAME_SEPARATOR_RE = re.compile(r"[\s・]+")
_LATIN_SYMBOLS = frozenset(" -'‐’̄")


def kana_to_romaji(kana: str, mode: str = "macron") -> str:
    """Romanisasi hiragana dan katakana dengan pencocokan terpanjang.

    Digraf (きゃ, しゅ, ちょ, ファ, ティ, ヴァ, ...) dicocokkan lebih dulu daripada
    kana tunggal. Karakter non-kana (kanji, Latin, tanda baca) dibiarkan.

    Args:
        kana: Bacaan atau teks yang memuat kana.
        mode: ``macron``, ``kana``, atau ``plain`` (lihat docstring modul).

    Returns:
        Teks Latin huruf kecil.

    Raises:
        ConfigError: ``mode`` tidak dikenal.
    """
    if mode not in MODES:
        raise ConfigError(f"mode romaji {mode!r} tidak valid; pilihan: {', '.join(MODES)}")
    widened = _expand_kana_iteration(widen_halfwidth_kana(kana))
    units = _split_units(hira_to_kata(widened))
    katakana = _katakana_units(widened, units)
    pieces: list[str] = []
    geminate = False
    # True bila suku kata terakhir sudah dipanjangkan: vokal berikutnya suku kata baru.
    lengthened = False
    for index, unit in enumerate(units):
        if unit == SOKUON:
            geminate = True
            continue
        if unit == LONG_MARK:
            _lengthen(pieces, mode)
            geminate = False
            lengthened = True
            continue
        roma = _MONOGRAPHS.get(unit) or _DIGRAPHS.get(unit)
        if roma is None:
            pieces.append(unit)
            geminate = lengthened = False
            continue
        if geminate:
            roma = _geminate(roma)
            geminate = False
        if pieces and pieces[-1] == "n" and roma[0] in "aiueoy":
            pieces[-1] = "n'"
        if (mode != "kana" and unit in _BARE_VOWELS and not lengthened
                and _extends_vowel(pieces, roma, units, index, katakana[index])):
            _lengthen(pieces, mode)
            lengthened = True
            continue
        pieces.append(roma)
        lengthened = False
    return "".join(pieces)


def romanize_name(reading: str, mode: str) -> str:
    """Romanisasi bacaan nama lalu kapitalkan tiap kata.

    Kata dipisah oleh spasi (biasa atau lebar penuh) dan ・, misalnya
    ``やまだ たろう`` → ``Yamada Tarō`` dan ``ジョン・スミス`` → ``Jon Sumisu``
    (Hepburn murni; ejaan nama asing ada di ``romanize_foreign``).

    Args:
        reading: Bacaan kana.
        mode: ``macron``, ``kana``, atau ``plain``.

    Returns:
        Nama Latin dengan huruf kapital di awal tiap kata.

    Raises:
        ConfigError: ``mode`` tidak dikenal.
    """
    words = _NAME_SEPARATOR_RE.split(kana_to_romaji(reading, mode))
    return " ".join(word[:1].upper() + word[1:] for word in words if word)


NAME_TAIL_KANA = frozenset("こみかなえよのほりやとたきじおまねせ")
"""Satu kana yang lazim menutup nama Jepang (子 美 香 奈 恵 代 乃 穂 里 也 斗 太 樹 二 夫 ...)."""
NAME_HEAD_KANA = frozenset("みまさちこあ")
"""Satu kana yang lazim membuka nama Jepang (美 真 沙 千 小 亜): ミユキ, マユミ."""
_NON_NATIVE_KANA = frozenset("ぁぃぅぇぉゎゔゕゖ")
_VOWEL_KANA = {"a": "あ", "i": "い", "u": "う", "e": "い", "o": "う"}


def looks_japanese(kana: str) -> bool:
    """Perkirakan apakah tulisan katakana SATU bagian nama adalah nama Jepang.

    Bacaannya (hiragana; ー diganti vokal panjangnya, ユーキ → ゆうき, コータ →
    こうた) harus memakai kana Jepang biasa (tanpa ァィゥェォ kecil dan ヴ) dan
    berbentuk salah satu dari:

    - bacaan utuh dari data proyek: nama depan ``given_names.json`` (ハルカ,
      ユキ, サクラ), nama keluarga ``surnames.json`` (タナカ), tempat,
      ``data.KANA_NAME_READINGS`` (ミク, マドカ, dan bentuk ambigu レオ, ルカ), atau
      ``data.COMMON_NAME_READINGS`` (マキ, ユナ, ウメ, ヨウスケ);
    - dua unsur ``data.NAME_ELEMENTS`` (のぶ + なが, ひで + よし, まさ + ひろ), atau
      satu unsur + satu kana penutup ``NAME_TAIL_KANA`` (えつ + こ);
    - bacaan utuh + satu kana penutup ``NAME_TAIL_KANA`` (ユミ + コ, アヤ + ネ,
      リョウ + マ), dengan "bacaan utuh" boleh juga dua kana pertama sebuah nama
      depan (あや dari あやの);
    - satu kana pembuka ``NAME_HEAD_KANA`` + bacaan utuh (マ + ユミ).

    Ini heuristik: nama asing yang kebetulan berbentuk sama (カレン = か + れん)
    dianggap Jepang dan tetap Hepburn (Karen); nama Jepang yang tidak dikenali
    hanya menambah satu pertanyaan nama yang jawabannya disaring gema Hepburn.

    Args:
        kana: Satu bagian nama (tanpa ・); setengah lebar dan hiragana diterima.
    """
    reading = _name_reading(kana)
    if not reading or any(ch in _NON_NATIVE_KANA for ch in reading):
        return False
    whole, heads = _japanese_name_pieces()
    if reading in whole:
        return True
    if reading[-1] in NAME_TAIL_KANA and (reading[:-1] in whole or reading[:-1] in heads
                                          or reading[:-1] in data.NAME_ELEMENTS):
        return True
    if any(reading[:cut] in data.NAME_ELEMENTS and reading[cut:] in data.NAME_ELEMENTS
           for cut in range(2, len(reading) - 1)):
        return True
    return reading[0] in NAME_HEAD_KANA and reading[1:] in whole


def _name_reading(kana: str) -> str:
    """Bacaan hiragana tanpa ー: tanda panjang diganti vokal suku kata sebelumnya."""
    hira = kata_to_hira(_expand_kana_iteration(widen_halfwidth_kana(kana).strip()))
    out: list[str] = []
    for ch in hira:
        if ch == LONG_MARK:
            if not out:
                return ""
            vowel = kana_to_romaji(out[-1], "kana")[-1:]
            ch = _VOWEL_KANA.get(vowel, "")
            if not ch:
                return ""
        elif not ("ぁ" <= ch <= "ゖ"):
            return ""
        out.append(ch)
    return "".join(out)


@lru_cache(maxsize=None)
def _japanese_name_pieces() -> tuple[frozenset[str], frozenset[str]]:
    """Bacaan nama utuh dari data proyek dan awalan dua kana nama depan."""
    given = {info["reading"] for info in data.given_names().values()}
    whole = frozenset(given | set(data.surnames().values())
                      | {place["reading"] for place in data.places().values()}
                      | data.UNISEX_READINGS | data.KANA_NAME_READINGS
                      | data.COMMON_NAME_READINGS)
    heads = frozenset(reading[:2] for reading in given if len(reading) >= 3)
    return whole, heads


def foreign_spelling(part: str) -> str | None:
    """Ejaan Latin satu bagian nama asing dari kamus bawaan, atau ``None``.

    Args:
        part: Satu bagian nama katakana tanpa ・ (``エリザベート``); hiragana dan
            katakana setengah lebar dinormalisasi dulu.
    """
    return data.foreign_names().get(hira_to_kata(widen_halfwidth_kana(part.strip())))


def romanize_foreign(name: str, mode: str) -> str:
    """Romanisasi nama asing per bagian: kamus dulu, Hepburn untuk sisanya.

    ``ジョン・スミス`` → ``John Smith``; ``ジョン・サトウ`` → ``John Satō`` (mode
    macron). Bagian dipisah ・ atau spasi.

    Args:
        name: Tulisan atau bacaan katakana.
        mode: Mode romanisasi untuk bagian yang tidak ada di kamus.

    Raises:
        ConfigError: ``mode`` tidak dikenal.
    """
    parts = [part for part in _NAME_SEPARATOR_RE.split(name) if part]
    return " ".join(foreign_spelling(part) or romanize_name(part, mode) for part in parts)


def is_latin(text: str) -> bool:
    """Periksa apakah teks hanya berisi huruf Latin dan pemisah nama.

    Yang diizinkan: huruf Latin (termasuk ā ō é), spasi, tanda hubung,
    apostrof (' atau ’), dan makron gabung (U+0304). Angka dan tanda baca
    lain ditolak, sehingga jawaban mesin seperti ``Tanaka.`` dianggap tidak
    bersih.

    Args:
        text: Teks yang diperiksa, biasanya ejaan nama dari mesin.

    Returns:
        ``True`` bila teks memuat minimal satu huruf Latin dan tidak ada
        karakter lain di luar daftar di atas.
    """
    has_letter = False
    for ch in text:
        if ch.isalpha() and unicodedata.name(ch, "").startswith("LATIN "):
            has_letter = True
        elif ch not in _LATIN_SYMBOLS:
            return False
    return has_letter


def _split_units(kata: str) -> list[str]:
    """Pecah teks katakana menjadi unit kana, digraf lebih dulu."""
    units: list[str] = []
    index = 0
    while index < len(kata):
        pair = kata[index:index + 2]
        step = 2 if pair in _DIGRAPHS else 1
        units.append(kata[index:index + step])
        index += step
    return units


def _geminate(roma: str) -> str:
    """Gandakan konsonan awal suku kata setelah sokuon (ch → tch)."""
    if roma[0] in "aiueo":
        return roma
    if roma.startswith("ch"):
        return "t" + roma
    return roma[0] + roma


def _katakana_units(text: str, units: list[str]) -> list[bool]:
    """Tandai unit ``_split_units`` yang aslinya ditulis katakana.

    ``hira_to_kata`` memetakan satu karakter ke satu karakter, jadi posisi unit
    di teks katakana sama dengan posisinya di ``text``.
    """
    flags: list[bool] = []
    offset = 0
    for unit in units:
        flags.append("ァ" <= text[offset] <= "ヺ")
        offset += len(unit)
    return flags


_MORPHEME_SPLIT_HEADS = frozenset({
    "まつう", "はるう", "つるう", "ひろお", "くろお", "しろお", "むろお", "よこお", "もとお",
})


def _expand_kana_iteration(text: str) -> str:
    """Urai tanda ulang kana ``ゝゞヽヾ`` berdasarkan huruf sebelumnya (みすゞ -> みすず)."""
    chars = list(text)
    for idx in range(1, len(chars)):
        mark = chars[idx]
        prev = chars[idx - 1]
        is_hira = "ぁ" <= prev <= "ゖ"
        is_kata = "ァ" <= prev <= "ヺ"
        if not (is_hira or is_kata):
            continue
        if mark in ("ゝ", "ヽ"):
            unvoiced_kata = hira_to_kata(prev).translate(_KATAKANA_UNVOICE)
            chars[idx] = kata_to_hira(unvoiced_kata) if is_hira else unvoiced_kata
        elif mark in ("ゞ", "ヾ"):
            voiced_kata = hira_to_kata(prev).translate(_KATAKANA_DAKUTEN)
            chars[idx] = kata_to_hira(voiced_kata) if is_hira else voiced_kata
    return "".join(chars)


def _extends_vowel(pieces: list[str], vowel: str, units: list[str], index: int,
                   katakana: bool = False) -> bool:
    """Tentukan apakah vokal tunggal ``units[index]`` memperpanjang vokal sebelumnya.

    ``katakana`` menandai bahwa vokal itu ditulis katakana; ウ katakana sebelum
    エ/オ tidak pernah dipanjangkan (bunyi we/wo kata serapan).
    """
    if not pieces or (pieces[-1][-1], vowel) not in _LONG_PAIRS:
        return False
    if not katakana and _is_compound_vowel_split(units, index):
        return False
    following = units[index + 1] if index + 1 < len(units) else ""
    if pieces[-1][-1] == "o" and vowel == "u" and following in _SPLITTING_VOWELS:
        # いのうえ: う-え di batas morfem adalah dua suku kata (Inoue, bukan Inōe).
        return not katakana and not _morpheme_boundary(units, index + 1)
    return True


def _is_compound_vowel_split(units: list[str], index: int) -> bool:
    """Cegah penggabungan vokal lintas morfem pada marga seperti 松浦, 広岡, 横尾."""
    start = index
    while start > 0 and _is_kana_unit(units[start - 1]):
        start -= 1
    prefix_hira = kata_to_hira("".join(units[start:index + 1]))
    return prefix_hira in _MORPHEME_SPLIT_HEADS


def _morpheme_boundary(units: list[str], index: int) -> bool:
    """Apakah ``units[index]`` (え/お setelah おう) menutup sebuah kata atau nama keluarga.

    Ya bila setelahnya bukan kana lagi (akhir teks, spasi, ・, tanda baca), atau
    bila bacaan dari awal kata sampai ``units[index]`` adalah bacaan nama keluarga
    di ``surnames.json`` yang berakhir うえ/うお (いのうえ + さん).
    """
    if index + 1 >= len(units) or not _is_kana_unit(units[index + 1]):
        return True
    start = index
    while start > 0 and _is_kana_unit(units[start - 1]):
        start -= 1
    return kata_to_hira("".join(units[start:index + 1])) in _surname_ue_readings()


def _is_kana_unit(unit: str) -> bool:
    """Unit hasil ``_split_units`` yang berupa kana (termasuk ッ dan ー)."""
    return unit in _MONOGRAPHS or unit in _DIGRAPHS or unit in (SOKUON, LONG_MARK)


@lru_cache(maxsize=1)
def _surname_ue_readings() -> frozenset[str]:
    """Bacaan nama keluarga bawaan yang berakhir うえ atau うお (いのうえ)."""
    return frozenset(reading for reading in data.surnames().values()
                     if reading.endswith(("うえ", "うお")))


def _lengthen(pieces: list[str], mode: str) -> None:
    """Panjangkan vokal terakhir sesuai mode (ā, aa, atau tetap a)."""
    if not pieces or pieces[-1][-1] not in _MACRONS:
        return
    last = pieces[-1]
    if mode == "macron":
        pieces[-1] = last[:-1] + _MACRONS[last[-1]]
    elif mode == "kana":
        pieces[-1] = last + last[-1]
''')

MODUL['jptrans.segment'] = (
    False,
r'''"""Segmentasi teks Jepang: dokumen → paragraf → kalimat → batch permintaan.

Aturan kalimat dirancang untuk light novel dan web novel:

- Kalimat berakhir pada 。！？!? hanya bila tidak berada di dalam kurung
  (「」『』（）【】〈〉《》).
- Kutipan 「」『』 yang selesai dengan tanda akhir (「はい。」) menutup kalimat,
  kecuali langsung diikuti partikel kutipan と/って (「本当に？！」と彼は言った。).
  Kurung biasa (彼（本当に？）は) tidak menutup kalimat.
- Elipsis …/‥ tidak memutus kalimat (これは……本当？ tetap satu kalimat).
- Tanda akhir berturut-turut (！？, 。」) tetap bagian kalimat yang sama.
- Kutipan tanpa penutup tidak boleh menelan sisa paragraf: bagian sejak
  kurung yang tak tertutup disegmentasi ulang tanpa menghitung kurung.
- Cue subtitle dua pembicara (``- はい\\n- いいえ``) dipecah per giliran oleh
  ``split_speaker_turns`` sebelum dipecah per kalimat, dan tag format SRT di tepi
  potongan kalimat ditempelkan ke kalimatnya oleh ``attach_format_tags``.
- Tanda pisah di akhir baris yang disusul tanda pisah di awal baris berikutnya
  (``行こうと思ったけど—\\n—やっぱりやめた。``) adalah sambungan kalimat satu pembicara,
  bukan dialog (``continues_with_dash``); sambungannya ditulis sekali. Di cue yang baris
  pertamanya bertanda, tanda panjang + spasi (``— 行こうと—\\n— やめろ！``) tetap giliran baru.

Semua fungsi murni dan tidak mengubah isi teks; menggabungkan kembali hasil
``split_sentences`` memberi paragraf asli tanpa spasi di tepi kalimat.
"""

from __future__ import annotations

import logging
import re

from .errors import ConfigError
from .models import (
    CLOSING_TAG, OPENING_TAG, OVERRIDE_TAG, SIMPLE_OPENING_TAG, split_leading_tags,
)
from .protect import EXACT_TOKEN_RE

logger = logging.getLogger(__name__)

OPENING_BRACKETS = "「『（【〈《"
CLOSING_BRACKETS = "」』）】〉》"
QUOTE_CLOSERS = "」』"
"""Penutup kutipan dialog; kurung biasa （） tidak pernah mengakhiri kalimat."""
SENTENCE_ENDERS = "。．！？!?‼⁇⁈⁉"
ELLIPSES = "…‥"
QUOTE_PARTICLES = ("と", "って")
"""Partikel setelah 」 yang menandakan kutipan masih bagian kalimat (と言った, って)."""
_NON_QUOTATIVE_TO_WORDS = (
    "とりあえず",
    "とにかく",
    "ところで",
    "とっさに",
    "とうとう",
    "とても",
    "とはいえ",
    "ともかく",
    "ときどき",
    "とたんに",
)
_QUOTE_CASE_TAILS = ("が", "を", "とは", "とか", "なんて", "など")

DIALOGUE_DASHES = "-－―‐\u2013\u2014"
"""Tanda dialog subtitle di awal baris: ``-`` ASCII, ``－`` lebar penuh, ``―``, ``‐``,
en dash (U+2013), dan em dash (U+2014)."""

LONG_DASHES = "\u2013\u2014\u2015"
"""Tanda pisah panjang (en dash, em dash, ``―``). Di awal baris hanya tanda dialog bila baris
berisi pertama cue juga bertanda (tanpa gaya Netflix), karena tanda ini juga dipakai untuk
menyambung kalimat (``けど—\\n—やっぱり``, ``彼は言った\\n— 本当だ。``)."""

HYPHEN_DASHES = "-－‐"
"""Tanda dialog jenis tanda hubung; hanya kelas ini yang mengenal gaya Netflix."""

KANA_DASH = "ー"
"""Tanda panjang katakana (U+30FC) yang dipakai hasil OCR sebagai tanda dialog (``ー はい``).
Hanya dihitung bila SEMUA baris cue diawali ``ー`` + spasi (``uses_kana_dash``)."""

_KANA_DASH_RE = re.compile(r"ー[ \u3000]+[^\sー]")
_SPACES = " \u3000"
_OPENING_TAG_RE = re.compile(f"{OVERRIDE_TAG}|{OPENING_TAG}", re.IGNORECASE)
_CLOSING_TAG_RE = re.compile(CLOSING_TAG, re.IGNORECASE)
_CLOSING_TAGS_RE = re.compile(f"(?:{CLOSING_TAG})+", re.IGNORECASE)
_SIMPLE_OPEN_RE = re.compile(f"(?:{SIMPLE_OPENING_TAG})+", re.IGNORECASE)
_TAG_NAME_RE = re.compile(r"</?([a-z]+)", re.IGNORECASE)

_CHUNK_DELIMITERS = "、，,"
_DIGITS = "0123456789０１２３４５６７８９"
_CJK_START = "\u2e80"
"""Titik awal blok CJK (radikal, kana, kanji, tanda baca lebar penuh)."""


def split_paragraphs(text: str) -> list[str]:
    """Pisah teks menjadi paragraf: satu baris tidak kosong = satu paragraf.

    Novel Jepang memakai satu baris per paragraf, jadi baris kosong hanya
    pemisah. Spasi (termasuk spasi lebar penuh U+3000 untuk indentasi) di
    kedua tepi baris dibuang; baris yang hanya berisi spasi diabaikan.

    Args:
        text: Isi dokumen dengan baris baru apa pun (``\\n``, ``\\r\\n``).

    Returns:
        Daftar paragraf tanpa indentasi, berurutan.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def unwrap_lines(text: str) -> str:
    """Gabungkan baris yang patah hanya karena tampilan menjadi satu baris.

    Subtitle dua baris (``今日は佐藤先輩と\\n魔法の練習``) dan teks OCR memecah
    satu kalimat di tengah. Bila tiap baris dikirim terpisah, mesin
    menerjemahkan dua potongan tanpa konteks. Bahasa Jepang tidak memakai
    spasi antarkata, jadi sambungan antara dua huruf CJK tidak diberi spasi;
    sambungan lain (teks Latin, baris dialog ``- はい``) diberi satu spasi.

    Args:
        text: Isi satu paragraf, boleh mengandung ``\\n``.

    Returns:
        Teks satu baris; baris kosong dibuang.
    """
    joined = ""
    for line in (part.strip() for part in text.split("\n")):
        if not line:
            continue
        if joined:
            both_cjk = _is_cjk_join(joined[-1]) and _is_cjk_join(line[0])
            joined += "" if both_cjk else " "
        joined += line
    return joined


def _is_cjk_join(ch: str) -> bool:
    return ch >= _CJK_START or ch in "…‥―\u2014"


def dialogue_line_text(line: str, *, kana_dash: bool = False) -> str | None:
    """Isi baris dialog subtitle tanpa tandanya, atau ``None`` bila bukan baris dialog.

    Baris dialog diawali satu tanda dari ``DIALOGUE_DASHES``, boleh disusul
    spasi (``- はい``, ``－はい``, ``―　はい``, ``— はい``), lalu isi yang tidak kosong.
    Yang bukan tanda dialog: tanda ganda (``――そうか``, ``——``, gaya jeda di naskah
    Jepang), tanda yang langsung menempel ke angka (``-5度``, ``–5度``), dan tanda
    tanpa isi. Tag format SRT pembuka (``{\\an8}- はい``, ``<i>- はい</i>``) dilewati
    saat mencari tanda dan dikembalikan di depan isi (``{\\an8}はい``).

    Args:
        line: Satu baris yang sudah dibuang spasi tepinya.
        kana_dash: Terima juga ``ー`` + spasi (``ー はい``) sebagai tanda. Pemanggil
            hanya menyalakannya bila semua baris cue memakai bentuk itu
            (``uses_kana_dash``), karena ``ー`` di awal kalimat biasanya bagian kata
            (``ーっ``, ``ーー``).
    """
    tags, body = split_leading_tags(line)
    if kana_dash and _KANA_DASH_RE.match(body):
        return tags + body[1:].strip(_SPACES)
    if len(body) < 2 or body[0] not in DIALOGUE_DASHES:
        return None
    if body[1] in DIALOGUE_DASHES or body[1] in _DIGITS:
        return None
    rest = body[1:].strip()
    return tags + rest if rest else None


def uses_kana_dash(lines: list[str]) -> bool:
    """Semua baris berisi diawali ``ー`` + spasi + isi (sesudah tag pembuka), minimal dua baris.

    Gaya OCR menulis tanda dialog sebagai ``ー はい`` / ``ー いいえ``. Satu baris saja
    yang tidak memakai bentuk itu (``ーっ、痛い！``, ``ーー``, baris tanpa tanda, atau
    tanda dialog lain) mematikan aturan ini untuk seluruh cue.
    """
    content = [line for line in lines if line and not is_mark_only_line(line)]
    return len(content) >= 2 and all(
        _KANA_DASH_RE.match(split_leading_tags(line)[1]) for line in content)


def is_mark_only_line(line: str) -> bool:
    """Baris yang hanya berisi tag format pembuka, tanda dialog, dan spasi (``- ``, ``{\\an8}``)."""
    return not split_leading_tags(line)[1].strip(DIALOGUE_DASHES + " \u3000")


def split_speaker_turns(text: str) -> list[str]:
    """Pisah cue subtitle menjadi giliran pembicara, tiap giliran satu baris.

    Setiap baris yang diawali tanda dialog (``dialogue_line_text``) memulai
    giliran baru; baris tanpa tanda ikut giliran sebelumnya (``join_tagged_lines``).
    Baris pertama tanpa tanda juga satu giliran (gaya Netflix, ``本当に？\\n- 本当だよ。``),
    tetapi tanda ``LONG_DASHES`` hanya memulai giliran bila baris berisi pertama
    juga bertanda, jadi ``彼は言った\\n— 本当だ。`` tetap satu giliran. Baris sambungan
    (``continues_with_dash``, ``けど—\\n—やっぱり``) langsung digabung dengan
    ``join_dash_connector``; baris tanda saja di antaranya dilewati (``_absorb_connector``).
    Di cue bertanda, elipsis (``— そうか……\\n— うん。``) dan tanda panjang + spasi sesudah
    tanda panjang (``— 行こうと—\\n— やめろ！``) bukan sambungan. ``ー`` + spasi hanya tanda bila
    semua baris memakainya (``uses_kana_dash``). Tanda dialog hanya dibuang bila hasilnya minimal
    dua giliran; cue satu giliran (``- はい``, ``— けど—\\n—やめた。``) tetap membawa tandanya.

    Baris yang hanya berisi tanda atau tag (``is_mark_only_line``) tidak pernah
    menjadi giliran: sebelum baris berisi pertama, tandanya dibuang dan tagnya
    pindah ke depan baris berisi itu (``{\\an8}\\n- はい``); di cue dua
    pembicara baris seperti itu dibuang. Cue yang isinya hanya tanda
    dikembalikan apa adanya lewat ``unwrap_lines``.

    Args:
        text: Isi satu cue, boleh mengandung ``\\n``.

    Returns:
        Daftar giliran tanpa ``\\n``; kosong bila ``text`` kosong.
    """
    lines = [part.strip() for part in text.split("\n")]
    kana_dash = uses_kana_dash(lines)
    carried = ""
    kept: list[str] = []
    turns: list[list[str]] = []
    long_marks = False
    for line in lines:
        if not line:
            continue
        if is_mark_only_line(line) and not turns:
            carried += split_leading_tags(line)[0]
            continue
        if carried:
            line, carried = carried + line, ""
        if kept and _absorb_connector(kept, turns[-1], line, marked_cue=long_marks):
            continue
        kept.append(line)
        spoken = dialogue_line_text(line, kana_dash=kana_dash)
        if not turns:
            long_marks = spoken is not None
        elif not long_marks and split_leading_tags(line)[1][:1] in LONG_DASHES:
            spoken = None
        if spoken is not None or not turns:
            turns.append([line if spoken is None else spoken])
        else:
            turns[-1].append(line)
    if not turns:
        joined = unwrap_lines(text)
        return [joined] if joined else []
    if len(turns) < 2:
        return [join_tagged_lines(kept)]
    return [join_tagged_lines([line for line in lines if not is_mark_only_line(line)])
            for lines in turns]


def _absorb_connector(kept: list[str], turn: list[str], line: str, *,
                      marked_cue: bool) -> bool:
    """Gabungkan ``line`` ke baris berisi terakhir bila ``continues_with_dash`` benar.

    Baris yang isinya hanya tanda (``is_mark_only_line``) di antara kedua bagian
    sambungan dilewati saat membandingkan dan dibuang dari ``kept`` dan ``turn``; tag
    pembukanya dipindah ke depan ``line``. Jadi ``けど—\\n—\\n—やっぱり`` menjadi
    ``けど—やっぱり``, bukan ``けど— — —やっぱり``. Baris tanda seperti itu selalu ada di
    ekor ``turn`` karena tidak pernah memulai giliran.

    Args:
        kept: Baris berisi cue sejauh ini (diubah di tempat).
        turn: Giliran terakhir (diubah di tempat).
        line: Baris baru.
        marked_cue: Baris berisi pertama cue bertanda dialog (lihat ``continues_with_dash``).

    Returns:
        ``True`` bila ``line`` sudah digabung dan tidak perlu diproses lagi.
    """
    marks = 0
    while marks < len(kept) and is_mark_only_line(kept[-1 - marks]):
        marks += 1
    if marks == len(kept):
        return False
    if not continues_with_dash(kept[-1 - marks], line, marked_cue=marked_cue):
        return False
    if marks:
        line = "".join(split_leading_tags(mark)[0] for mark in kept[-marks:]) + line
        del kept[-marks:], turn[-marks:]
    kept[-1] = join_dash_connector(kept[-1], line)
    turn[-1] = join_dash_connector(turn[-1], line)
    return True


def continues_with_dash(previous: str, line: str, *, marked_cue: bool = False) -> bool:
    """``line`` menyambung kalimat ``previous`` lewat tanda pisah, bukan giliran baru.

    Konvensi subtitle: tanda pisah di akhir baris yang disusul tanda pisah di awal
    baris berikutnya adalah satu kalimat yang dipatah (``行こうと思ったけど—\\n—やっぱり``).

    - Kelas ``LONG_DASHES``: ``line`` diawali tanda panjang dan ``previous`` diakhiri
      tanda panjang. Elipsis di akhir ``previous`` (``それは……\\n—嘘だ``)
      hanya sambungan bila ``marked_cue`` salah dan ``previous`` bukan baris dialog: di cue
      yang baris berisi pertamanya bertanda (``— そうか……\\n— うん。``) elipsis berarti
      pembicara menggantung lalu pembicara lain menjawab, jadi tetap dua giliran. Di cue
      seperti itu tanda panjang + spasi di awal ``line`` (``— 行こうと—\\n— やめろ！``) adalah
      penanda pembicara baru (ucapan dipotong orang lain), bukan sambungan; hanya tanda
      tanpa spasi (``— 行こうと—\\n—やっぱりやめた。``) yang menyambung. Spasi berarti whitespace
      apa pun (``str.isspace``: juga NBSP, tab, spasi tipis), sama dengan ``dialogue_line_text``.
      Di cue campuran (baris pertama tanpa tanda, ``行こうと—\\n— やめろ！``) spasi tidak dihitung.
    - Kelas ``HYPHEN_DASHES``: ``previous`` diakhiri tanda hubung dan bukan baris
      dialog, dan ``line`` adalah baris dialog bertanda hubung (``でも-\\n-やめた。``).
      Di cue yang barisnya bertanda (``- 行こうと-\\n- やめろ！``) tanda di akhir baris
      berarti ucapan dipotong pembicara lain, jadi tetap dua giliran. Angka negatif
      (``-5度``) bukan sambungan.

    Tag penutup di akhir ``previous`` dan tag pembuka di awal ``line`` dilewati.
    Baris yang isinya hanya tanda (``is_mark_only_line``), di sisi mana pun, tidak
    pernah dihitung sambungan.
    """
    body = split_leading_tags(line)[1]
    if is_mark_only_line(line) or is_mark_only_line(previous):
        return False
    tail = previous[:trailing_tags_start(previous, _CLOSING_TAG_RE)].rstrip()
    if not tail:
        return False
    if body[0] in LONG_DASHES:
        if tail[-1] in ELLIPSES:
            return not marked_cue and dialogue_line_text(previous) is None
        if marked_cue and len(body) > 1 and body[1].isspace():
            # Penanda pembicara "— A" di cue bertanda: ucapan sebelumnya dipotong orang lain.
            return False
        return tail[-1] in LONG_DASHES
    return (body[0] in HYPHEN_DASHES and tail[-1] in HYPHEN_DASHES
            and dialogue_line_text(line) is not None and dialogue_line_text(previous) is None)


def join_dash_connector(previous: str, line: str) -> str:
    """Sambung ``line`` ke ``previous`` sehingga tanda sambungnya hanya tertulis sekali.

    Tanda pisah di awal ``line`` (seluruh deretannya, ``――``) dan whitespace sesudahnya
    (spasi, U+3000, NBSP, tab) dibuang, lalu kedua baris ditempel tanpa spasi: tanda di
    akhir ``previous`` sudah menjadi pemisahnya (``けど—`` + ``—やっぱり`` memberi
    ``けど—やっぱり``). Tag yang sama
    di kedua sisi sambungan digabung seperti ``join_tagged_lines``. Dipanggil hanya
    bila ``continues_with_dash(previous, line)`` benar.
    """
    tags, body = split_leading_tags(line)
    dashes = LONG_DASHES if body[:1] in LONG_DASHES else HYPHEN_DASHES
    previous, line = _merge_tag_seam(previous, tags + body.lstrip(dashes).lstrip())
    return previous + line


def join_tagged_lines(lines: list[str]) -> str:
    """``unwrap_lines`` untuk baris subtitle yang masing-masing dibungkus tag yang sama.

    ``<i>今日は</i>`` / ``<i>練習だ</i>`` menjadi ``<i>今日は練習だ</i>``: tag penutup di
    akhir satu baris dan tag pembuka sederhana yang sama (``<i>``, ``<b>``, ``<u>``,
    ``<s>`` tanpa atribut) di awal baris berikutnya dibuang (``_merge_tag_seam``),
    sehingga mesin tidak menerima ``今日は</i> <i>練習だ``. Tag dengan atribut
    (``<font color=...>``) atau urutan yang berbeda tidak digabung.

    Args:
        lines: Baris satu giliran, sudah dibuang spasi tepinya.

    Returns:
        Teks satu baris hasil ``unwrap_lines``.
    """
    merged: list[str] = []
    for line in lines:
        if merged:
            merged[-1], line = _merge_tag_seam(merged[-1], line)
        merged.append(line)
    return unwrap_lines("\n".join(merged))


def _merge_tag_seam(previous: str, line: str) -> tuple[str, str]:
    """Buang tag penutup di akhir ``previous`` dan tag pembuka yang sama di awal ``line``.

    Hanya bila urutan nama tagnya cermin (``</b></i>`` dengan ``<i><b>``) dan kedua sisi
    masih punya isi; selain itu kedua baris dikembalikan apa adanya.
    """
    cut = trailing_tags_start(previous, _CLOSING_TAG_RE)
    closing = previous[cut:]
    opening = _SIMPLE_OPEN_RE.match(line)
    if (closing and opening
            and _tag_names(closing) == _tag_names(opening.group())[::-1]
            and previous[:cut].strip() and line[opening.end():].strip()):
        return previous[:cut].rstrip(), line[opening.end():].lstrip()
    return previous, line


def trailing_tags_start(text: str, tag_re: re.Pattern[str]) -> int:
    """Posisi awal deretan tag ``tag_re`` yang menempel di akhir ``text`` (tanpa spasi).

    Dipindai mundur satu tag demi satu tag dengan ``rfind`` dan ``fullmatch``, jadi
    waktunya linear. Regex berjangkar ``(...)+$`` dengan ``search`` dicoba dari tiap
    posisi dan menjadi kuadratik pada cue raksasa berisi ribuan tag. Awal satu tag
    selalu ``<`` atau ``{`` terakhir sebelum ``>`` atau ``}`` penutupnya (atribut dan
    override tidak boleh memuatnya), jadi hasilnya sama dengan regex itu.

    Args:
        text: Teks yang diperiksa.
        tag_re: Pola satu tag (dicocokkan dengan ``fullmatch``).

    Returns:
        ``len(text)`` bila ``text`` tidak diakhiri tag seperti itu.
    """
    end = len(text)
    while end and text[end - 1] in ">}":
        opener = text.rfind("<" if text[end - 1] == ">" else "{", 0, end)
        if opener < 0 or not tag_re.fullmatch(text, opener, end):
            break
        end = opener
    return end


def _tag_names(tags: str) -> list[str]:
    """Nama tag berurutan, huruf kecil (``</b></i>`` memberi ``["b", "i"]``)."""
    return [name.lower() for name in _TAG_NAME_RE.findall(tags)]


def attach_format_tags(pieces: list[str]) -> list[str]:
    """Tempelkan tag format SRT di tepi potongan kalimat ke kalimat pemiliknya.

    ``split_sentences`` memotong sesudah tanda akhir, jadi ``<i>田中さん、早く！</i>``
    memberi ``<i>田中さん、早く！`` dan ``</i>`` sebagai kalimat sendiri. Di sini tag
    penutup di awal potongan pindah ke akhir potongan sebelumnya, dan tag pembuka di
    akhir potongan pindah ke awal potongan berikutnya; potongan yang lalu kosong
    dibuang. Hasilnya tiap kalimat membawa tagnya sendiri (``<i>田中さん、早く！</i>``)
    dan pipeline bisa melepasnya sebelum dikirim ke mesin (``models.split_format_tags``).

    Args:
        pieces: Kalimat hasil ``split_sentences`` dari satu giliran.

    Returns:
        Kalimat tanpa potongan yang isinya hanya tag (kecuali semuanya hanya tag).
    """
    result = list(pieces)
    for index in range(1, len(result)):
        closing = _CLOSING_TAGS_RE.match(result[index])
        owner = next((i for i in range(index - 1, -1, -1) if result[i]), None)
        if closing and owner is not None:
            result[owner] += closing.group()
            result[index] = result[index][closing.end():].lstrip()
    for index in range(len(result) - 2, -1, -1):
        cut = trailing_tags_start(result[index], _OPENING_TAG_RE)
        owner = next((i for i in range(index + 1, len(result)) if result[i]), None)
        if cut < len(result[index]) and owner is not None:
            result[owner] = result[index][cut:] + result[owner]
            result[index] = result[index][:cut].rstrip()
    kept = [piece for piece in result if piece]
    return kept if kept else [piece for piece in pieces if piece]


def split_sentences(paragraph: str) -> list[str]:
    """Pisah satu paragraf menjadi kalimat.

    Args:
        paragraph: Satu paragraf hasil ``split_paragraphs``.

    Returns:
        Daftar kalimat tanpa spasi tepi; kalimat kosong dibuang.
    """
    ends, unclosed_at = _sentence_ends(paragraph, track_brackets=True)
    if unclosed_at is not None:
        logger.debug("kurung tanpa penutup di posisi %d; segmentasi ulang", unclosed_at)
        tail_ends, _ = _sentence_ends(paragraph[unclosed_at:], track_brackets=False)
        ends += [unclosed_at + end for end in tail_ends]
    return _cut(paragraph, ends)


def make_batches(items: list[str], max_chars: int, max_items: int) -> list[list[int]]:
    """Kelompokkan indeks item menjadi batch permintaan ke mesin.

    Panjang batch dihitung sebagai jumlah panjang item ditambah satu pemisah
    ``\\n`` di antara item. Item yang sendirian sudah melebihi ``max_chars``
    tetap menjadi batch sendiri; pemanggil yang memotongnya.

    Args:
        items: Teks yang akan dikirim, berurutan.
        max_chars: Batas karakter per permintaan.
        max_items: Batas jumlah item per permintaan.

    Returns:
        Daftar batch; tiap batch berisi indeks ``items`` yang berurutan.

    Raises:
        ConfigError: ``max_chars`` atau ``max_items`` kurang dari 1.
    """
    _require_positive(max_chars=max_chars, max_items=max_items)
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for index, item in enumerate(items):
        if current and (size + 1 + len(item) > max_chars or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        size += len(item) + (1 if current else 0)
        current.append(index)
    if current:
        batches.append(current)
    return batches


def chunk_long_text(text: str, max_chars: int) -> list[str]:
    """Potong teks yang terlalu panjang menjadi potongan ``<= max_chars``.

    Titik potong dipilih di 、 atau spasi terakhir dalam jendela ``max_chars``
    (tanda tetap ikut potongan kiri). Bila tidak ada, teks dipotong paksa,
    tetapi tidak pernah di tengah penanda ``[[E1]]``. Menggabungkan hasilnya
    dengan ``"".join`` memberi teks asli.

    Args:
        text: Kalimat (boleh sudah dimasking).
        max_chars: Panjang maksimum tiap potongan.

    Returns:
        Daftar potongan; kosong bila ``text`` kosong.

    Raises:
        ConfigError: ``max_chars`` kurang dari 1.
    """
    _require_positive(max_chars=max_chars)
    chunks: list[str] = []
    start = 0
    while len(text) - start > max_chars:
        cut = _chunk_cut(text, start, start + max_chars)
        chunks.append(text[start:cut])
        start = cut
    if start < len(text):
        chunks.append(text[start:])
    return chunks


def _sentence_ends(text: str, *, track_brackets: bool) -> tuple[list[int], int | None]:
    """Cari posisi akhir tiap kalimat.

    Returns:
        Pasangan (posisi akhir kalimat, posisi kurung pembuka yang tidak
        pernah ditutup atau ``None``).
    """
    ends: list[int] = []
    depth = 0
    unclosed_at: int | None = None
    index = 0
    while index < len(text):
        ch = text[index]
        candidate = False
        if track_brackets and ch in OPENING_BRACKETS:
            if depth == 0:
                unclosed_at = index
            depth += 1
        elif track_brackets and ch in CLOSING_BRACKETS and depth > 0:
            depth -= 1
            candidate = depth == 0 and ch in QUOTE_CLOSERS and _ends_with_terminal(text[:index])
        elif ch in SENTENCE_ENDERS and depth == 0 and not _is_inline_symbol(text, index):
            candidate = True
        if depth == 0:
            unclosed_at = None
        if candidate:
            end = _absorb_terminals(text, index + 1)
            if not _continues_after_quote(text, end):
                ends.append(end)
                index = end
                continue
        index += 1
    return ends, unclosed_at


def _ends_with_terminal(text: str) -> bool:
    """Periksa apakah isi kutipan diakhiri tanda akhir atau elipsis (。」, ……」)."""
    inner = text.rstrip(CLOSING_BRACKETS)
    return bool(inner) and inner[-1] in SENTENCE_ENDERS + ELLIPSES


def _absorb_terminals(text: str, index: int) -> int:
    """Lewati tanda akhir dan kurung penutup berturut-turut (！？, 。」)."""
    while index < len(text) and text[index] in SENTENCE_ENDERS + CLOSING_BRACKETS:
        index += 1
    return index


def _is_inline_symbol(text: str, index: int) -> bool:
    ch = text[index]
    if ch == "!" and text[index + 1:index + 2] == "=":
        return True
    if ch == "．" and 0 < index < len(text) - 1:
        return text[index - 1] in _DIGITS and text[index + 1] in _DIGITS
    return False


def _continues_after_quote(text: str, end: int) -> bool:
    """Periksa apakah kutipan yang baru ditutup masih berlanjut sebagai satu kalimat."""
    if text[end - 1] not in CLOSING_BRACKETS:
        return False
    tail = text[end:].lstrip()
    if tail.startswith(_NON_QUOTATIVE_TO_WORDS):
        return False
    if tail.startswith(QUOTE_PARTICLES):
        return True
    if end < len(text) and not text[end].isspace():
        if tail.startswith(_QUOTE_CASE_TAILS):
            return True
        if tail.startswith("は") and tail[1:2] not in "いあぁっは！!？?、。":
            return True
    return False


def _cut(text: str, ends: list[int]) -> list[str]:
    """Potong teks pada posisi ``ends`` dan buang potongan kosong."""
    pieces = []
    start = 0
    for end in [*ends, len(text)]:
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        start = end
    return pieces


def _chunk_cut(text: str, start: int, limit: int) -> int:
    """Pilih posisi potong di ``(start, limit]`` untuk ``chunk_long_text``."""
    window = text[start:limit]
    delimiter = max(
        (i for i, ch in enumerate(window) if ch in _CHUNK_DELIMITERS or ch.isspace()),
        default=-1,
    )
    if delimiter >= 0:
        return start + delimiter + 1
    for marker in EXACT_TOKEN_RE.finditer(text, start):
        if marker.start() >= limit:
            break
        if marker.end() > limit:
            # Penanda yang lebih panjang dari max_chars dibiarkan utuh.
            return marker.start() if marker.start() > start else marker.end()
    return limit


def _require_positive(**limits: int) -> None:
    """Lempar ``ConfigError`` bila ada batas yang kurang dari 1."""
    for name, value in limits.items():
        if value < 1:
            raise ConfigError(f"{name} harus minimal 1, bukan {value}")
''')

MODUL['jptrans.selftest'] = (
    False,
r'''"""Rangkaian pengujian unit dan integrasi otomatis bawaan ``jptrans``.

Dapat dijalankan langsung lewat ``python3 translator.py test -v`` tanpa pustaka
pihak ketiga dan tanpa koneksi internet. Menguji 5 kriteria rekayasa skrip
profesional: keandalan/idempotensi/pembersihan sumber daya, kebersihan modular,
keamanan konfigurasi, observabilitas/kode keluar, serta akurasi linguistik
dan dukungan lintas format.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import tempfile
import time
import unittest
import zipfile
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from . import cli, coref, data, disambig, gender, models, ner, net, phonetic
from . import postprocess, protect, readings, residue, romaji, segment, server
from . import style, textnorm
from .cache import TranslationCache, make_key
from .config import Config, load_config, load_dotenv
from .engines.fake import FakeEngine
from .engines.libretranslate import LibreTranslateEngine
from .engines.llm import LLMEngine, parse_translations, resolve_model_for_host
from .errors import AllEnginesFailed, ConfigError, EngineUnavailable, InputError
from .errors import QuotaExceeded
from .glossary import Glossary
from .pipeline import Translator
from .readers import read_document, read_text
from .readers.epub import extract_xhtml
from .readers.pages import clean_ocr_text
from .readers.subtitle import parse_ass, parse_srt, parse_vtt
from .readers.txt import detect_encoding
from .writers import render_output
from .writers.subtitle import wrap_cue

logger = logging.getLogger(__name__)


class ReliabilityAndCacheTests(unittest.TestCase):
    """Kriteria 1: Graceful failure, idempotensi, dan pembersihan sumber daya."""

    def test_sqlite_wal_idempotency_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.sqlite3"
            with TranslationCache(db_path) as cache:
                key = make_key("fake:v1", "ja", "id", "[[E1]]は来た。")
                cache.put(key, "fake", "ja", "id", "[[E1]] datang.")
                cache.put(key, "fake", "ja", "id", "[[E1]] datang.")
                self.assertEqual(cache.get(key), "[[E1]] datang.")
                self.assertEqual(cache.stats()["entries"], 1)
                assert cache._conn is not None
                mode = cache._conn.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            cache.close()
            self.assertIsNone(cache._conn)

    def test_cache_clear_and_batch_put_many(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with TranslationCache(Path(tmp) / "cache.sqlite3") as cache:
                rows = [
                    (make_key("fake", "ja", "id", f"s{i}"), "fake", "ja", "id", f"t{i}")
                    for i in range(4)
                ]
                cache.put_many(rows)
                self.assertEqual(cache.stats()["entries"], 4)
                removed = cache.clear()
                self.assertEqual(removed, 4)
                self.assertEqual(cache.stats()["entries"], 0)

    def test_corrupted_placeholder_does_not_poison_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            bad_engine = FakeEngine(
                translations={
                    "[[E1]]は走った。": "Dia berlari tanpa token.",
                    "Tanaka-san は走った。": "Tanaka-san berlari cepat.",
                }
            )
            glossary = Glossary("uji", [models.GlossaryEntry("田中", reading="たなか")])
            doc = read_text("田中さんは走った。", "uji")
            with TranslationCache(cfg.cache_path) as cache:
                translator = Translator(cfg, [bad_engine], cache, glossary)
                res = translator.translate_document(doc)
                self.assertEqual(res.paragraphs[0].target, "Tanaka-san berlari cepat.")
                self.assertEqual(
                    res.paragraphs[0].sentences[0].status, models.STATUS_PRESUB
                )
                masked_key = translator._key(
                    bad_engine,
                    "[[E1]]は走った。",
                    {1: models.Slot(glossary.get("田中") or models.GlossaryEntry("田中"), "san")},
                )
                self.assertIsNone(cache.get(masked_key))

    def test_idempotent_repeated_translation_and_slot_cache_separation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            engine = FakeEngine(
                translations={
                    "[[E1]]に電話した。": "Menghubungi [[E1]].",
                }
            )
            glossary = Glossary("seri")
            doc = read_text("田中さんに電話した。田中家に電話した。", "seri")
            with TranslationCache(cfg.cache_path) as cache:
                first = Translator(cfg, [engine], cache, glossary).translate_document(doc)
                count_after_first = len(glossary)
                second = Translator(cfg, [engine], cache, glossary).translate_document(doc)
                self.assertEqual(len(glossary), count_after_first)
                self.assertEqual(first.paragraphs[0].target, second.paragraphs[0].target)
                self.assertIn("Tanaka-san", second.paragraphs[0].target)
                self.assertIn("keluarga Tanaka", second.paragraphs[0].target)
                self.assertEqual(
                    second.paragraphs[0].sentences[0].status, models.STATUS_CACHED
                )

    def test_all_engines_failed_raises_clean_error(self) -> None:
        class BrokenEngine(FakeEngine):
            def translate(self, texts, src, tgt, hints=()):  # type: ignore[override]
                raise EngineUnavailable("broken", "jaringan terputus")

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            with TranslationCache(None) as cache:
                translator = Translator(cfg, [BrokenEngine()], cache, Glossary("uji"))
                with self.assertRaises(AllEnginesFailed):
                    translator.translate_text("こんにちは。")


class SecurityAndConfigTests(unittest.TestCase):
    """Kriteria 3: Keamanan rahasia, .env, validasi tipe, dan sanitasi input."""

    def test_dotenv_loader_parses_safely_without_overwriting_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "# komentar\n"
                "JPTRANS_TEST_ALPHA='nilai_satu'\n"
                "export JPTRANS_TEST_BETA=\"nilai_dua\" # komentar tepi\n"
                "JPTRANS_TEST_GAMMA=\"nilai # tiga\"\n"
                "INVALID-KEY=abaikan\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ, {"JPTRANS_TEST_ALPHA": "dari_shell"}, clear=False
            ):
                os.environ.pop("JPTRANS_TEST_BETA", None)
                os.environ.pop("JPTRANS_TEST_GAMMA", None)
                added = load_dotenv(env_file)
                self.assertEqual(added, 2)
                self.assertEqual(os.environ["JPTRANS_TEST_ALPHA"], "dari_shell")
                self.assertEqual(os.environ["JPTRANS_TEST_BETA"], "nilai_dua")
                self.assertEqual(os.environ["JPTRANS_TEST_GAMMA"], "nilai # tiga")
                os.environ.pop("JPTRANS_TEST_BETA", None)
                os.environ.pop("JPTRANS_TEST_GAMMA", None)

    def test_config_rejects_secrets_and_string_booleans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            secret_cfg = Path(tmp) / "secret.json"
            secret_cfg.write_text('{"deepl_api_key": "rahasia"}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(secret_cfg)

            bad_bool = Path(tmp) / "bool.json"
            bad_bool.write_text('{"allow_unofficial": "false"}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(bad_bool)

    def test_llm_security_provider_model_and_thinking_fence_parser(self) -> None:
        cfg_insecure = Config(llm_base_url="http://example.com/v1")
        llm_insecure = LLMEngine(cfg_insecure, api_key="sk-secret")
        ok, _ = llm_insecure.available()
        self.assertFalse(ok)
        with self.assertRaises(EngineUnavailable):
            llm_insecure.translate(["テスト"], "ja", "id")

        self.assertEqual(
            resolve_model_for_host("gemini-2.5-flash", "api.groq.com"),
            "llama-3.3-70b-versatile",
        )
        self.assertEqual(
            resolve_model_for_host("gemini-2.5-flash", "localhost"),
            "qwen2.5:7b",
        )
        raw_reply = (
            "<think>analisis internal</think>\n"
            "Berikut hasilnya:\n```JSON\n"
            '{"translations": [{"id": "1", "text": "Halo [[E1]]!"}]}\n```'
        )
        self.assertEqual(parse_translations(raw_reply, 1), ["Halo [[E1]]!"])

    def test_net_http_402_and_404_classification(self) -> None:
        err_402 = HTTPError(
            "https://openrouter.ai/api", 402, "Payment Required", Message(), None
        )
        err_404 = HTTPError(
            "https://example.com/v1", 404, "Not Found", Message(), None
        )
        self.assertIsInstance(net._classify(err_402, "llm").error, QuotaExceeded)
        self.assertIsInstance(net._classify(err_404, "llm").error, EngineUnavailable)

    def test_libretranslate_security_and_response(self) -> None:
        engine = LibreTranslateEngine(
            base_url="http://remote.example.com", api_key="secret"
        )
        self.assertFalse(engine.available()[0])
        local_engine = LibreTranslateEngine(base_url="http://localhost:5000")
        self.assertTrue(local_engine.available()[0])

    def test_server_ipv6_host_rebinding_guard(self) -> None:
        self.assertEqual(server.host_name("[::1]:8765"), "::1")
        self.assertEqual(server.host_name("[::1]"), "::1")
        self.assertEqual(server.host_name("[::1]evil.com"), "")
        self.assertEqual(server.host_name("127.0.0.1:8765"), "127.0.0.1")
        self.assertTrue(server._is_private_lan_ip("192.168.1.25"))
        self.assertFalse(server._is_private_lan_ip("evil.com"))


class LinguisticAndModularTests(unittest.TestCase):
    """Kriteria 2 & Akurasi: Modularitas, romaji, fonetik, NER, gender, dan gaya."""

    def test_offline_full_kanji_name_resolution(self) -> None:
        entry = models.GlossaryEntry(surface="山田太郎", kind=models.PERSON)
        completed = readings.complete_reading(entry, {})
        self.assertEqual(completed.reading, "やまだ たろう")
        cfg_id = Config(target_lang="id")
        cfg_en = Config(target_lang="en")
        self.assertEqual(style.Renderer(cfg_id)(models.Slot(completed, "san")), "Yamada Tarō-san")
        self.assertEqual(style.Renderer(cfg_en)(models.Slot(completed, "san")), "Tarō Yamada-san")

    def test_romaji_ainu_iteration_marks_and_morpheme_boundaries(self) -> None:
        self.assertEqual(romaji.romanize_name("アシㇼパ", "macron"), "Ashiripa")
        self.assertEqual(romaji.romanize_name("みすゞ", "macron"), "Misuzu")
        self.assertEqual(romaji.kana_to_romaji("こゝろ", "macron"), "kokoro")
        self.assertEqual(romaji.kana_to_romaji("づゝ", "plain"), "zutsu")
        self.assertTrue(romaji.looks_japanese("ミスヾ"))
        self.assertEqual(romaji.kana_to_romaji("アンーイ", "plain"), "an'i")
        self.assertEqual(romaji.romanize_name("まつうら", "macron"), "Matsuura")
        self.assertEqual(romaji.romanize_name("ひろおか", "macron"), "Hirooka")
        self.assertEqual(romaji.romanize_name("よこお", "macron"), "Yokoo")
        self.assertEqual(romaji.romanize_name("ゆうき", "macron"), "Yūki")
        self.assertEqual(romaji.romanize_name("おおさか", "macron"), "Ōsaka")

    def test_phonetic_rejects_english_decoys_and_accepts_slavic(self) -> None:
        self.assertIsNone(phonetic.validate_foreign_name("キール", "Key"))
        self.assertIsNone(phonetic.validate_foreign_name("シール", "Sea"))
        self.assertIsNone(phonetic.validate_foreign_name("ポール", "Paw"))
        self.assertEqual(phonetic.validate_foreign_name("ポール", "Paul"), "Paul")
        self.assertEqual(phonetic.validate_foreign_name("シャーロット", "Charlotte"), "Charlotte")
        self.assertEqual(phonetic.validate_foreign_name("オルロフ", "Orlov"), "Orlov")
        self.assertEqual(phonetic.validate_foreign_name("カルポフ", "Karpov"), "Karpov")
        self.assertEqual(phonetic.validate_foreign_name("ヴォルコフ", "Volkov"), "Volkov")
        self.assertEqual(phonetic.validate_foreign_name("ロマノフ", "Romanov"), "Romanov")
        self.assertEqual(phonetic.validate_foreign_name("イヴァノフ", "Ivanov"), "Ivanov")

    def test_ner_fantasy_names_loanwords_pronouns_and_titles(self) -> None:
        doc = read_text(
            "フリーレンは笑った。キミはアルバイトだ。拙者も行く。"
            "原画監督と関連会社社長が来た。結局美咲さんが勝った。",
            "ner_uji",
        )
        cands = {c.surface: c for c in ner.detect_entities(doc)}
        self.assertIn("フリーレン", cands)
        self.assertEqual(cands["フリーレン"].kind, models.PERSON)
        self.assertGreaterEqual(cands["フリーレン"].score, 0.6)
        self.assertIn("美咲", cands)
        for non_entity in ("キミ", "アルバイト", "拙者", "原画", "関連会社", "結局美咲"):
            self.assertNotIn(non_entity, cands)

    def test_gender_and_localized_honorific_accuracy(self) -> None:
        aoi = models.GlossaryEntry("蒼", kind=models.PERSON, reading="あおい")
        self.assertEqual(gender.infer_gender(aoi)[0], "")
        megumi_kun = models.GlossaryEntry("恵", kind=models.PERSON)
        self.assertEqual(gender.infer_gender(megumi_kun, kun=True)[0], "")

        cfg_loc_id = Config(target_lang="id", honorific_style="localize")
        cfg_loc_en = Config(target_lang="en", honorific_style="localize")
        elisabeth = models.GlossaryEntry("エリザベート", kind=models.PERSON)
        self.assertEqual(
            style.Renderer(cfg_loc_id)(models.Slot(elisabeth, "sama")),
            "Elizabeth-sama",
        )
        sakura_f = models.GlossaryEntry("さくら", kind=models.PERSON, gender="f")
        self.assertEqual(
            style.Renderer(cfg_loc_en)(models.Slot(sakura_f, "dono")),
            "Lady Sakura",
        )

        cfg_keep = Config(target_lang="id", honorific_style="keep")
        tanaka = models.GlossaryEntry("田中", kind=models.PERSON, reading="たなか")
        self.assertEqual(
            style.Renderer(cfg_keep)(models.Slot(tanaka, "san", "家")),
            "rumah Tanaka-san",
        )
        self.assertEqual(
            style.Renderer(cfg_keep)(models.Slot(tanaka, "", "家")),
            "keluarga Tanaka",
        )

    def test_protect_annotated_llm_tokens_and_postprocess_rules(self) -> None:
        tanaka = models.GlossaryEntry("田中", kind=models.PERSON, reading="たなか")
        masked = models.Masked("田中さん", "[[E1]]", {1: models.Slot(tanaka, "san")})
        restored = protect.restore("Halo [[E1:田中]]!", masked, lambda _s: "Tanaka-san")
        self.assertEqual(restored, "Halo Tanaka-san!")

        self.assertEqual(
            postprocess.tidy("The the Tanaka family arrived.", "en"),
            "The Tanaka family arrived.",
        )
        self.assertEqual(
            postprocess.fix_names("Tokyonya indah.", ["Tokyo"], "id"),
            "Tokyo-nya indah.",
        )
        self.assertEqual(
            postprocess.fix_pronouns("The victory was his and they cheered.", "f"),
            "The victory was hers and they cheered.",
        )
        self.assertEqual(
            postprocess.lower_after_comma("Misaki-chan, It’s morning!", "en", ["Misaki-chan"]),
            "Misaki-chan, it’s morning!",
        )
        self.assertEqual(
            postprocess.lower_after_vocative(
                "Yui, Lombok itu indah.", "id", ["Yui"], frozenset(), "ロンボクは綺麗だ。"
            ),
            "Yui, Lombok itu indah.",
        )

    def test_segmentation_quotes_fullwidth_period_and_ellipsis(self) -> None:
        self.assertEqual(
            segment.split_sentences("「行くぞ！」とりあえず走った。"),
            ["「行くぞ！」", "とりあえず走った。"],
        )
        self.assertEqual(
            segment.split_sentences("「バカ！」が口癖だ。"),
            ["「バカ！」が口癖だ。"],
        )
        self.assertEqual(
            segment.split_sentences("値は3．14である．次の文．"),
            ["値は3．14である．", "次の文．"],
        )
        self.assertEqual(segment.unwrap_lines("これは……\n本当？"), "これは……本当？")
        self.assertEqual(textnorm.strip_diacritics("Satō Tarō"), "Sato Taro")


class ReadersWritersAndCliTests(unittest.TestCase):
    """Kriteria 4 & 5: Pembaca/penulis lintas format, logging, dan kode keluar."""

    def test_encoding_detection_utf8_with_latin_accents_and_eucjp(self) -> None:
        utf8_bytes = "Résumé 東京の桜が咲いた。\n".encode("utf-8")
        self.assertEqual(detect_encoding(utf8_bytes), "utf-8")
        self.assertEqual(detect_encoding(b"\xc3\xbb\n"), "euc_jp")
        with self.assertRaises(InputError):
            detect_encoding(b"abc\x00def")

    def test_web_novel_brackets_and_scene_breaks_not_eaten_by_aozora(self) -> None:
        novel = (
            "彼は《火炎魔法》と《ファイアボール》を放った。\n"
            "----------\n次の場面。\n----------\n終わり。"
        )
        doc = read_text(novel, "webnovel")
        self.assertEqual(doc.fmt, "txt")
        joined = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("《火炎魔法》", joined)
        self.assertIn("《ファイアボール》", joined)
        self.assertIn("次の場面。", joined)

        aozora_latin = read_text("NHK《エヌエイチケイ》の放送。", "aozora_uji")
        self.assertEqual(aozora_latin.fmt, "aozora")
        self.assertEqual(aozora_latin.ruby.get("NHK"), "エヌエイチケイ")

    def test_xhtml_ruby_okurigana_and_standalone_html_reader(self) -> None:
        paras, pairs = extract_xhtml(
            "<p><ruby>見<rt>み</rt>える</ruby>と<ruby>悠<rt>ゆう</rt>真<rt>ま</rt></ruby></p>"
        )
        self.assertEqual(paras[0].text, "見えると悠真")
        self.assertIn(("見", "み"), pairs)
        self.assertIn(("悠真", "ゆうま"), pairs)
        self.assertNotIn(("見える", "み"), pairs)

        with tempfile.TemporaryDirectory() as tmp:
            html_file = Path(tmp) / "bab1.html"
            html_file.write_text(
                "<html><head><title>Judul HTML</title></head>"
                "<body><p>田中さんが来た。</p></body></html>",
                encoding="utf-8",
            )
            doc = read_document(html_file)
            self.assertEqual(doc.title, "Judul HTML")
            self.assertEqual(doc.paragraphs[0].text, "田中さんが来た。")

    def test_srt_vtt_ass_roundtrip_and_tag_safe_wrapping(self) -> None:
        tagged = (
            '<font color="yellow">Kalimat terjemahan ini cukup panjang '
            "sekali untuk diuji hari ini.</font>"
        )
        wrapped = wrap_cue(tagged, width=42)
        self.assertIn("\n", wrapped)
        self.assertTrue(wrapped.startswith('<font color="yellow">'))

        vtt_src = (
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.500\n"
            "<v 田中><ruby>東京<rp>(</rp><rt>とうきょう</rt><rp>)</rp></ruby>へ行く。\n"
        )
        doc_vtt = parse_vtt(vtt_src, "ep1")
        self.assertEqual(doc_vtt.paragraphs[0].text, "東京へ行く。")
        self.assertEqual(doc_vtt.ruby.get("東京"), "とうきょう")

        ass_src = (
            "[Script Info]\nTitle: Ep1\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:03.50,Default,Tanaka,0,0,0,,{\\an8}こんにちは。\\N元気？\n"
        )
        doc_ass = parse_ass(ass_src, "ep1")
        self.assertEqual(doc_ass.paragraphs[0].text, "こんにちは。\n元気？")

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            with TranslationCache(None) as cache:
                translator = Translator(cfg, [FakeEngine()], cache, Glossary("ep1"))
                res_vtt = translator.translate_document(doc_vtt)
                out_vtt = render_output(res_vtt, "vtt")
                self.assertTrue(out_vtt.startswith("WEBVTT"))
                out_srt = render_output(res_vtt, "srt")
                self.assertEqual(len(parse_srt(out_srt, "ep1").paragraphs), 1)
                out_ass = render_output(res_vtt, "ass")
                self.assertIn("Dialogue:", out_ass)
                out_html = render_output(res_vtt, "html")
                self.assertIn("<!DOCTYPE html>", out_html)

    def test_ocr_paragraph_preservation(self) -> None:
        cleaned = clean_ocr_text("田中 さん\n来た\n\n美咲 さん")
        self.assertEqual(cleaned, "田中さん来た\n\n美咲さん")

    def test_structured_logging_and_cli_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "run.jsonl"
            inp = tmp_path / "bab.txt"
            out = tmp_path / "bab_id.txt"
            inp.write_text("山田太郎さんは東京駅に行った。\n", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"JPTRANS_HOME": tmp}, clear=False),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code_ok = cli.main([
                    "-v", "--log-json", "--log-file", str(log_path),
                    "translate", str(inp), "--engine", "fake",
                    "--to", "id", "--format", "txt", "-o", str(out),
                ])
                self.assertEqual(code_ok, 0)
                self.assertIn("Yamada Tarō-san", out.read_text(encoding="utf-8"))
                log_lines = [
                    json.loads(line)
                    for line in log_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertTrue(any("timestamp" in row for row in log_lines))

                code_missing = cli.main(["-q", "translate", str(tmp_path / "404.txt")])
                self.assertEqual(code_missing, 1)

                code_bad_arg = cli.main(["--opsi-tidak-ada"])
                self.assertEqual(code_bad_arg, 2)

                with mock.patch("sys.stderr", None):
                    code_no_stderr = cli.main(["-q", "doctor"])
                self.assertEqual(code_no_stderr, 0)

                code_cache = cli.main(["cache", "stats"])
                self.assertEqual(code_cache, 0)
                code_clear = cli.main(["cache", "clear"])
                self.assertEqual(code_clear, 0)
            cli.configure_logging(quiet=True)

    def test_epub_xxe_rejection_and_glossary_cli_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_epub = tmp_path / "xxe.epub"
            with zipfile.ZipFile(bad_epub, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe "boom">]>'
                    "<container>&xxe;</container>",
                )
            with self.assertRaises(InputError):
                read_document(bad_epub)

            exp_file = tmp_path / "ekspor.json"
            with (
                mock.patch.dict(os.environ, {"JPTRANS_HOME": tmp}, clear=False),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    cli.main([
                        "glossary", "add", "--title", "SeriA", "紅蓮斬",
                        "--kind", "TERM", "--render-id", "Tebasan Teratai Merah",
                    ]),
                    0,
                )
                self.assertEqual(
                    cli.main(["glossary", "show", "--title", "SeriA"]), 0
                )
                self.assertEqual(
                    cli.main([
                        "glossary", "export", "--title", "SeriA", str(exp_file)
                    ]),
                    0,
                )
                self.assertEqual(
                    cli.main([
                        "glossary", "import", "--title", "SeriB", str(exp_file)
                    ]),
                    0,
                )
                self.assertEqual(
                    cli.main(["glossary", "remove", "--title", "SeriA", "紅蓮斬"]),
                    0,
                )
            cli.configure_logging(quiet=True)

    def test_disambig_coref_and_residue_modules(self) -> None:
        self.assertTrue(
            disambig.verb_run_before_honorific(
                "行", "くん", "ですか", before="駅まで"
            )
        )
        self.assertFalse(
            disambig.verb_run_before_honorific(
                "歩", "くん", "が来た", before=""
            )
        )
        self.assertFalse(
            disambig.verb_run_before_honorific(
                "歩", "くん", "だ", before="犯人は"
            )
        )
        misaki = models.GlossaryEntry("美咲", kind=models.PERSON, gender="f")
        masked = models.Masked(
            "美咲は時計を見た。",
            "[[E1]]は時計を見た。",
            {1: models.Slot(misaki)},
        )
        self.assertEqual(
            coref.pronoun_gender(masked, [masked], lambda e: e.gender), "f"
        )
        self.assertEqual(coref.explicit_pronoun("彼女は笑った。"), ("f", 1))
        self.assertEqual(coref.explicit_pronoun("彼女ができた。"), ("", 0))
        self.assertFalse(residue.has_japanese_residue("Halo [[E1]]!", "[[E1]]！"))
        self.assertTrue(residue.has_japanese_residue("Halo 未翻訳!", "テスト"))

    def test_local_web_server_security_and_lifecycle(self) -> None:
        class DummyServer:
            def __init__(self, cfg: Config) -> None:
                self.cfg = cfg
                self.token = "tok_uji_rahasia"
                self.allowed_hosts = frozenset({"127.0.0.1", "localhost", "::1"})
                self.allow_lan = False
                self.jobs = server.JobManager(
                    cfg, engine_builder=lambda _c: [FakeEngine()]
                )
                self.jobs.start()

        class NonClosingBytesIO(io.BytesIO):
            def close(self) -> None:
                self.flush()

        class MemorySocket:
            def __init__(self, raw_req: bytes) -> None:
                self._in = io.BytesIO(raw_req)
                self._out = NonClosingBytesIO()

            def settimeout(self, _timeout: float | None) -> None:
                pass

            def recv_into(self, buffer: bytearray | memoryview) -> int:
                return self._in.readinto(buffer)

            def makefile(self, mode: str, *_args: object, **_kwargs: object) -> io.BytesIO:
                return io.BytesIO() if "r" in mode else self._out

            def sendall(self, data: bytes) -> None:
                self._out.write(data)

            @property
            def response_bytes(self) -> bytes:
                return self._out.getvalue()

        def send_raw_http(dummy: DummyServer, raw_req: bytes) -> tuple[int, bytes]:
            mem_sock = MemorySocket(raw_req)
            addr = ("127.0.0.1", 12345)
            server.RequestHandler(mem_sock, addr, dummy)  # type: ignore[arg-type]
            raw_resp = mem_sock.response_bytes
            head, _, payload = raw_resp.partition(b"\r\n\r\n")
            status_code = int(head.splitlines()[0].split()[1])
            return status_code, payload

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            dummy = DummyServer(cfg)
            try:
                code_root, html_body = send_raw_http(
                    dummy, b"GET / HTTP/1.0\r\nHost: 127.0.0.1:8765\r\n\r\n"
                )
                self.assertEqual(code_root, 200)
                self.assertIn(b"<!DOCTYPE html>", html_body)
                self.assertIn(b'id="theme"', html_body)
                self.assertNotIn(b'href="#"', html_body)

                code_rebind, _ = send_raw_http(
                    dummy, b"GET / HTTP/1.0\r\nHost: [::1]evil.com\r\n\r\n"
                )
                self.assertEqual(code_rebind, 403)

                body = json.dumps({"text": "田中さんは来た。", "to": "id"}).encode()
                code_no_tok, _ = send_raw_http(
                    dummy,
                    b"POST /api/jobs HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body,
                )
                self.assertEqual(code_no_tok, 401)

                code_ok, job_resp = send_raw_http(
                    dummy,
                    b"POST /api/jobs HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    b"X-Token: tok_uji_rahasia\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body,
                )
                self.assertEqual(code_ok, 202)
                job_id = json.loads(job_resp.decode())["id"]

                status = ""
                for _ in range(30):
                    info = dummy.jobs.summary(job_id)
                    assert info is not None
                    status = info["status"]
                    if status in ("done", "failed"):
                        break
                    time.sleep(0.05)
                self.assertEqual(status, "done")

                dl_req = (
                    f"GET /api/jobs/{job_id}/download?fmt=txt HTTP/1.0\r\n"
                    "Host: 127.0.0.1\r\n"
                    "X-Token: tok_uji_rahasia\r\n\r\n"
                ).encode("ascii")
                code_dl, dl_body = send_raw_http(dummy, dl_req)
                self.assertEqual(code_dl, 200)
                self.assertIn("Tanaka-san", dl_body.decode("utf-8"))

                code_meta, meta_body = send_raw_http(
                    dummy,
                    b"GET /api/meta HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                    b"X-Token: tok_uji_rahasia\r\n\r\n",
                )
                self.assertEqual(code_meta, 200)
                meta_obj = json.loads(meta_body.decode("utf-8"))
                self.assertIn("id", meta_obj["languages"])
                self.assertTrue(any(e["name"] == "fake" for e in meta_obj["engines"]))

                sync_body = json.dumps({
                    "text": "田中さんは来た。",
                    "to": "id",
                    "honorifics": "drop",
                }).encode("utf-8")
                code_sync, sync_resp = send_raw_http(
                    dummy,
                    b"POST /api/translate HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    b"X-Token: tok_uji_rahasia\r\n"
                    + f"Content-Length: {len(sync_body)}\r\n\r\n".encode("ascii")
                    + sync_body,
                )
                self.assertEqual(code_sync, 200)
                sync_json = json.loads(sync_resp.decode("utf-8"))
                self.assertIn("Tanaka", sync_json["target"])
                self.assertNotIn("Tanaka-san", sync_json["target"])
            finally:
                dummy.jobs.stop()

    def test_epub_spine_relative_and_root_hrefs_with_html_themes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = Path(tmp) / "novel.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0"?>'
                    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>'
                    "</container>",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    '<?xml version="1.0"?>'
                    '<package xmlns="http://www.idpf.org/2007/opf">'
                    "<metadata><dc:title xmlns:dc=\"http://purl.org/dc/elements/1.1/\">"
                    "Novel Uji</dc:title></metadata>"
                    "<manifest>"
                    '<item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>'
                    '<item id="c2" href="/OEBPS/chap2.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                    "</manifest>"
                    '<spine><itemref idref="c1"/><itemref idref="c2"/></spine>'
                    "</package>",
                )
                zf.writestr(
                    "OEBPS/chap1.xhtml",
                    "<html><body><h1>第一章</h1>"
                    "<p><ruby>神崎<rt>かんざき</rt></ruby>"
                    "<ruby>悠真<rt>ゆうま</rt></ruby>さんは来た。</p></body></html>",
                )
                zf.writestr(
                    "OEBPS/chap2.xhtml",
                    "<html><body><h1>第二章</h1><p>東京は広い。</p></body></html>",
                )
            doc = read_document(epub_path)
            self.assertEqual(doc.title, "Novel Uji")
            self.assertEqual(len(doc.paragraphs), 4)
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            with TranslationCache(None) as cache:
                translator = Translator(cfg, [FakeEngine()], cache, Glossary("Novel Uji"))
                res = translator.translate_document(doc)
                html_out = render_output(res, "html")
                self.assertIn('id="th-dark"', html_out)
                self.assertIn('id="th-light"', html_out)
                self.assertIn("Kanzaki Yūma-san", html_out)

    def test_stdin_input_format_override_and_exit_code_three(self) -> None:
        srt_bytes = (
            "1\n00:00:01,000 --> 00:00:02,500\nこんにちは。\n"
        ).encode("utf-8")

        class FakeStdin:
            def __init__(self, payload: bytes) -> None:
                self.buffer = io.BytesIO(payload)

        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"JPTRANS_HOME": tmp}, clear=False),
                mock.patch("sys.stdin", FakeStdin(srt_bytes)),
                contextlib.redirect_stdout(stdout_buf),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = cli.main([
                    "-q", "translate", "-", "--input-format", "srt",
                    "--format", "vtt", "--engine", "fake", "--to", "id",
                ])
                self.assertEqual(code, 0)
                self.assertTrue(stdout_buf.getvalue().startswith("WEBVTT"))

                with mock.patch(
                    "jptrans.engines.fake.FakeEngine.translate",
                    side_effect=EngineUnavailable("fake", "mati"),
                ):
                    inp = Path(tmp) / "gagal.txt"
                    inp.write_text("こんにちは。\n", encoding="utf-8")
                    code_fail_all = cli.main([
                        "-q", "translate", str(inp), "--engine", "fake", "--no-cache",
                    ])
                    self.assertEqual(code_fail_all, 3)
            cli.configure_logging(quiet=True)

    def test_project_module_logger_invariants(self) -> None:
        import sys as _sys

        for name, mod in list(_sys.modules.items()):
            if mod is None or not (name == "jptrans" or name.startswith("jptrans.")):
                continue
            if name == "jptrans.__main__":
                continue
            mod_logger = getattr(mod, "logger", None)
            self.assertIsInstance(mod_logger, logging.Logger, f"{name} tanpa logger")

    def test_sdk_public_facade_and_plugin_registries(self) -> None:
        import jptrans
        from .config import REGISTERED_OUTPUT_FORMATS
        from .engines import ENGINE_FACTORIES
        from .readers import INPUT_FORMAT_READERS, READERS
        from .writers import CONTENT_TYPES, RENDERERS, SUFFIX_FORMATS

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            res = jptrans.translate_text(
                "山田太郎さんは東京駅に行った。", cfg=cfg, use_cache=False
            )
            self.assertIn("Yamada Tarō-san", res.target)

            with jptrans.create_translator(cfg, title="sdk_uji") as tr:
                res2 = tr.translate_text("美咲ちゃんが笑った。")
                self.assertIn("Misaki-chan", res2.target)
            self.assertIsNone(tr.cache._conn)

            inp_path = Path(tmp) / "sdk_in.txt"
            out_path = Path(tmp) / "sdk_out.txt"
            inp_path.write_text("田中さんは来た。\n", encoding="utf-8")
            res3 = jptrans.translate_file(inp_path, output=out_path, cfg=cfg)
            self.assertIn("Tanaka-san", res3.target)
            self.assertIn("Tanaka-san", out_path.read_text(encoding="utf-8"))

            try:
                jptrans.register_engine("fake_ext", lambda _c: FakeEngine(tag="ext"))
                jptrans.register_reader(
                    ".jptx",
                    lambda p, t, _e: read_text(p.read_text(encoding="utf-8"), t or p.stem),
                )
                jptrans.register_writer(
                    "jptout",
                    lambda r: f"OUT:{r.target}\n",
                    content_type="text/x-jpt",
                )
                ext_in = Path(tmp) / "bab.jptx"
                ext_out = Path(tmp) / "bab.jptout"
                ext_in.write_text("田中さんは来た。\n", encoding="utf-8")
                ext_cfg = Config(
                    target_lang="id",
                    engines=["fake_ext"],
                    output_format="jptout",
                    home=Path(tmp),
                )
                jptrans.translate_file(ext_in, output=ext_out, cfg=ext_cfg)
                rendered_ext = ext_out.read_text(encoding="utf-8")
                self.assertTrue(rendered_ext.startswith("OUT:"))
                self.assertIn("Tanaka-san", rendered_ext)
            finally:
                ENGINE_FACTORIES.pop("fake_ext", None)
                READERS.pop(".jptx", None)
                INPUT_FORMAT_READERS.pop("jptx", None)
                RENDERERS.pop("jptout", None)
                CONTENT_TYPES.pop("jptout", None)
                SUFFIX_FORMATS.pop(".jptout", None)
                if "jptout" in REGISTERED_OUTPUT_FORMATS:
                    REGISTERED_OUTPUT_FORMATS.remove("jptout")

    def test_unpack_bundle_to_multifile_package(self) -> None:
        loader = getattr(__import__("jptrans").__spec__, "loader", None)
        if not hasattr(loader, "ekstrak_paket"):
            return
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "extracted"
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code_ok = cli.main(["-q", "unpack", str(dest)])
                self.assertEqual(code_ok, 0)
                self.assertTrue((dest / "jptrans" / "__init__.py").is_file())
                self.assertTrue((dest / "jptrans" / "data" / "surnames.json").is_file())
                code_dup = cli.main(["-q", "unpack", str(dest)])
                self.assertEqual(code_dup, 2)
                code_force = cli.main(["-q", "unpack", str(dest), "--force"])
                self.assertEqual(code_force, 0)
            cli.configure_logging(quiet=True)


def run_tests(verbosity: int = 1, pattern: str = "") -> bool:
    """Jalankan seluruh TestCase di modul ini dan kembalikan ``True`` bila lulus."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__, fromlist=["*"]))
    if pattern:
        filtered = unittest.TestSuite()
        for group in suite:
            for case in group:
                if pattern.lower() in case.id().lower():
                    filtered.addTest(case)
        suite = filtered
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return result.wasSuccessful()
''')

MODUL['jptrans.server'] = (
    False,
r'''"""Antarmuka web lokal: satu halaman HTML untuk menerjemahkan dari browser HP.

Keamanan (LAPORAN_RISET 9.4, KRITIK_RISET no. 8 dan 21):

- Bind bawaan ``127.0.0.1``; ``--lan`` bind ``0.0.0.0`` dan mencetak IP LAN.
- Token acak ``secrets.token_urlsafe(24)`` dicetak di **fragment** URL
  (``http://host:port/#t=TOKEN``). Fragment tidak pernah dikirim browser ke
  server dan tidak masuk log. Halaman memindahkannya ke ``sessionStorage``,
  menghapusnya dari bilah alamat, lalu mengirimnya di header ``X-Token``.
  Semua endpoint ``/api/`` wajib token; dibandingkan dengan ``compare_digest``.
- Header ``Host`` harus salah satu host yang diizinkan (mencegah DNS
  rebinding). Tidak ada header CORS. ``Content-Length`` dibatasi 10 MB.
- ``BaseHTTPRequestHandler`` dipakai langsung; ``SimpleHTTPRequestHandler``
  sengaja dihindari karena menyajikan berkas apa pun dari disk.
- Terjemahan berjalan di SATU thread pekerja dengan ``queue.Queue`` (maks. 5
  antre), sehingga handler HTTP selalu cepat menjawab dan browser HP tidak
  timeout. Cache sqlite3 dibuka di thread pekerja itu sendiri.
- Klien lambat tidak bisa menahan server: tiap operasi soket punya batas
  waktu ``REQUEST_TIMEOUT``, dan di atasnya ada tenggat TOTAL per permintaan
  (``HEADER_TIMEOUT`` untuk baris permintaan + header, ``BODY_TIMEOUT`` untuk
  badan). Server berbicara HTTP/1.0 tanpa keep-alive, jadi satu koneksi
  melayani satu permintaan. Mengirim satu byte tiap beberapa detik tidak lagi
  memperpanjang koneksi.
  Koneksi serentak dibatasi ``MAX_CONNECTIONS`` total dan
  ``MAX_CONNECTIONS_PER_IP`` per alamat IP; koneksi di atas batas langsung
  dijawab ``503`` dengan ``Retry-After`` dari thread penerima (tanpa thread
  baru per koneksi, tanpa menunggu, soket non-blocking), arah tulisnya ditutup
  (FIN), lalu soket diserahkan ke satu thread penuai (``_LingerReaper``) yang
  membuang permintaan klien yang datang belakangan selama ``LINGER_SECONDS``
  sebelum menutupnya. Tanpa itu kernel menjawab permintaan yang tiba sesudah
  ``close`` dengan RST, dan klien kehilangan 503-nya (RFC 9112 bagian 9.6).
  Dokumen unggahan dibatasi ``MAX_JOB_PARAGRAPHS`` paragraf, dan isi
  unggahan dilepas dari memori setelah pekerjaan selesai.
- Di Windows ``SO_REUSEADDR`` mengizinkan proses lain bind port yang sedang
  dipakai, jadi opsi itu hanya dipasang di POSIX.
"""

from __future__ import annotations

import ipaddress
import io
import json
import logging
import os
import queue
import re
import secrets
import selectors
import socket
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any, cast
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__
from .cache import TranslationCache
from .config import HONORIFIC_STYLES, LANGS, NAME_ORDERS, ROMANIZATIONS, Config
from .engines import Engine, build_engines, describe_engines, normalize_engine_names
from .errors import ConfigError, InputError, JptransError
from .glossary import Glossary, default_glossary_path, slugify
from .models import Document, TranslatedDocument
from .pipeline import Progress, Translator
from .readers import READERS, read_document, read_text
from .writers import CONTENT_TYPES, RENDERERS, render_output
from .writers.text import result_to_dict

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 10 * 1024 * 1024
MAX_QUEUED = 5
MAX_KEPT_JOBS = 50
MAX_KEPT_RESULT_JOBS = 10
MAX_JOB_PARAGRAPHS = 100_000
REQUEST_TIMEOUT = 30
"""Detik tanpa data per operasi soket sebelum koneksi diputus."""
HEADER_TIMEOUT = 10.0
"""Tenggat total (detik) membaca baris permintaan + header (satu permintaan per koneksi)."""
BODY_TIMEOUT = 60.0
"""Tenggat total (detik) membaca badan permintaan (unggahan maks. ``MAX_BODY_BYTES``)."""
MAX_CONNECTIONS = 32
MAX_CONNECTIONS_PER_IP = 8
"""Browser memakai sekitar 6 koneksi per host; satu alamat tidak boleh memakai semua jatah."""
RETRY_AFTER_SECONDS = 5
_DRAIN_BYTES = 64 * 1024
LINGER_SECONDS = 2.0
"""Lama (detik) soket yang ditolak 503 tetap dibuka untuk membuang sisa permintaan klien."""
LINGER_MAX_SOCKETS = 64
"""Soket tertolak yang boleh ditahan bersamaan; bila penuh, soket langsung ditutup."""
LINGER_MAX_BYTES = 1024 * 1024
"""Byte yang dibuang per soket tertolak sebelum soket ditutup lebih awal."""
_LINGER_POLL = 0.1
UPLOAD_STEM = "upload"
TOKEN_BYTES = 24
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# Alamat TEST-NET-1 (RFC 5737): connect() UDP hanya memilih rute, tidak ada paket terkirim.
_ROUTE_PROBE = ("192.0.2.1", 80)
_JOB_PATH_RE = re.compile(r"^/api/jobs/(?P<id>[0-9a-f]{16})(?P<download>/download)?$")

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"

EngineBuilder = Callable[[Config], list[Engine]]


@dataclass(frozen=True)
class JobRequest:
    """Isi permintaan terjemahan dari browser.

    Attributes:
        title: Judul karya (menentukan glosarium).
        target: Bahasa sasaran.
        engines: Urutan mesin; kosong berarti ``cfg.engines``.
        text: Teks tempelan; kosong bila yang diunggah berkas.
        data: Isi berkas unggahan.
        filename: Nama berkas unggahan; sufiksnya menentukan pembaca.
    """

    title: str
    target: str
    engines: tuple[str, ...] = ()
    text: str = ""
    data: bytes = b""
    filename: str = ""
    honorific_style: str | None = None
    romanization: str | None = None
    name_order: str | None = None


@dataclass
class Job:
    """Satu pekerjaan terjemahan beserta statusnya."""

    id: str
    request: JobRequest
    status: str = QUEUED
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    title: str = ""
    result: TranslatedDocument | None = field(default=None, repr=False)
    html: str = field(default="", repr=False)
    finished: threading.Event = field(default_factory=threading.Event, repr=False)

    def state(self) -> dict[str, Any]:
        """Status singkat pekerjaan (tanpa hasil), aman disalin di bawah kunci."""
        title = (self.title or self.request.title
                 or Path(upload_basename(self.request.filename)).stem)
        return {
            "id": self.id, "title": title, "status": self.status,
            "done": self.done, "total": self.total, "message": self.message,
            "error": self.error,
        }


class JobManager:
    """Antrean pekerjaan dengan satu thread pekerja.

    Args:
        cfg: Konfigurasi dasar; bahasa dan mesin bisa diganti per pekerjaan.
        engine_builder: Pembuat daftar mesin (bisa diganti di tes).
        max_queued: Batas pekerjaan yang menunggu.
    """

    def __init__(
        self, cfg: Config, *, engine_builder: EngineBuilder = build_engines,
        max_queued: int = MAX_QUEUED,
    ) -> None:
        self.cfg = cfg
        self._build_engines = engine_builder
        self._queue: queue.Queue[Job] = queue.Queue(maxsize=max_queued)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._work, name="jptrans-worker", daemon=True)

    def start(self) -> None:
        """Jalankan thread pekerja."""
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Minta thread pekerja berhenti setelah pekerjaan yang sedang jalan."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def submit(self, request: JobRequest) -> Job | None:
        """Masukkan pekerjaan ke antrean.

        Returns:
            Pekerjaan baru, atau ``None`` bila antrean penuh.
        """
        job = Job(id=secrets.token_hex(8), request=request)
        with self._lock:
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                return None
            self._jobs[job.id] = job
            self._forget_old_jobs()
        logger.info("pekerjaan %s diantrekan (%s)", job.id, request.target)
        return job

    def run_sync(self, request: JobRequest, timeout: float = BODY_TIMEOUT) -> Job | None:
        """Antrekan pekerjaan lalu tunggu selesai untuk endpoint sinkron ``/api/translate``."""
        job = self.submit(request)
        if job is None:
            return None
        if not job.finished.wait(timeout):
            return None
        return job

    def summary(self, job_id: str) -> dict[str, Any] | None:
        """Status satu pekerjaan untuk ``GET /api/jobs/<id>``; hasil HTML bila selesai.

        Returns:
            Dict JSON, atau ``None`` bila pekerjaan tidak ada.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            info, result, page = job.state(), job.result, job.html
        if result is not None:
            # HTML dirender sekali oleh pekerja, bukan di setiap polling.
            info["html"] = page
            info["format"] = result.document.fmt
            info["stats"] = {key: value for key, value in result.stats.items()
                             if key != "rendered"}
        return info

    def result(self, job_id: str) -> TranslatedDocument | None:
        """Hasil pekerjaan yang sudah selesai, atau ``None``."""
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.result

    def _forget_old_jobs(self) -> None:
        finished = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in (DONE, FAILED)
        ]
        for job_id in finished[:-MAX_KEPT_RESULT_JOBS]:
            old = self._jobs[job_id]
            old.result = None
            old.html = ""
        for job_id in finished[:max(0, len(self._jobs) - MAX_KEPT_JOBS)]:
            del self._jobs[job_id]

    def _work(self) -> None:
        """Isi thread pekerja: cache sqlite3 dibuka di thread ini sendiri."""
        try:
            cache = TranslationCache(self.cfg.cache_path)
        except JptransError as exc:
            logger.error("pekerja tidak bisa membuka cache: %s", exc)
            cache = TranslationCache(None)
        with cache:
            while not self._stop.is_set():
                try:
                    job = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._run(job, cache)

    def _run(self, job: Job, cache: TranslationCache) -> None:
        self._update(job, status=RUNNING, message="mulai")
        try:
            result = self._translate(job, cache)
            page = render_output(result, "html")
        except JptransError as exc:
            self._update(job, status=FAILED, error=str(exc), message="gagal")
            logger.info("pekerjaan %s gagal: %s", job.id, exc)
        # Galat tak terduga tidak boleh mematikan satu-satunya thread pekerja.
        except Exception:  # noqa: BLE001
            logger.exception("pekerjaan %s gagal karena galat internal", job.id)
            self._update(job, status=FAILED, error="galat internal; lihat log server")
        else:
            self._update(job, status=DONE, result=result, html=page, message="selesai")
            logger.info("pekerjaan %s selesai", job.id)
        finally:
            # Unggahan (sampai 10 MB) tidak perlu disimpan setelah pekerjaan selesai.
            self._update(job, request=replace(job.request, data=b"", text=""))
            job.finished.set()

    def _translate(self, job: Job, cache: TranslationCache) -> TranslatedDocument:
        """Baca dokumen dulu agar judulnya (dan glosariumnya) sama dengan CLI."""
        request = job.request
        cfg = replace(
            self.cfg,
            target_lang=request.target,
            engines=list(request.engines) or self.cfg.engines,
            honorific_style=request.honorific_style or self.cfg.honorific_style,
            romanization=request.romanization or self.cfg.romanization,
            name_order=(
                request.name_order
                if request.name_order is not None
                else self.cfg.name_order
            ),
        )
        doc = _read_upload(request) if request.filename else read_text(request.text,
                                                                        request.title)
        if len(doc.paragraphs) > MAX_JOB_PARAGRAPHS:
            raise InputError(f"dokumen terlalu panjang (> {MAX_JOB_PARAGRAPHS} paragraf); "
                             "pecah dulu atau pakai CLI")
        self._update(job, title=doc.title)
        glossary = Glossary.load(default_glossary_path(cfg, doc.title), doc.title)

        def progress(state: Progress) -> None:
            self._update(job, done=state.done, total=state.total, message=state.message)

        translator = Translator(cfg, self._build_engines(cfg), cache, glossary, progress=progress)
        return translator.translate_document(doc)

    def _update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(job, name, value)


def _read_upload(request: JobRequest) -> Document:
    """Simpan unggahan ke berkas sementara, baca dengan pembaca yang sesuai, lalu hapus.

    Berkas sementara diperlukan karena pembaca EPUB memakai ``zipfile`` pada path.
    Judul mengikuti aturan CLI (``readers.read_document``): judul dari
    pengguna, lalu metadata/kepala berkas, lalu nama berkas asli.
    """
    original = Path(upload_basename(request.filename))
    with tempfile.TemporaryDirectory(prefix="jptrans-") as folder:
        path = Path(folder) / f"{UPLOAD_STEM}{original.suffix.lower()}"
        path.write_bytes(request.data)
        doc = read_document(path, title=request.title or None)
    if not request.title and doc.title == UPLOAD_STEM:
        doc.title = original.stem
    return doc


class JptransServer(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` yang membawa token, daftar host, dan antrean pekerjaan.

    Args:
        address: Pasangan (host, port); port 0 memilih port bebas.
        cfg: Konfigurasi program.
        allowed_hosts: Nilai header ``Host`` (tanpa port) yang diterima.
        engine_builder: Pembuat daftar mesin (bisa diganti di tes).
    """

    daemon_threads = True
    # Proses lain tidak boleh ikut bind di port yang sama. SO_REUSEPORT selalu mati;
    # SO_REUSEADDR hanya aman di POSIX (di Windows artinya "boleh berbagi port").
    allow_reuse_port = False
    allow_reuse_address = os.name != "nt"

    def __init__(
        self, address: tuple[str, int], cfg: Config, allowed_hosts: frozenset[str],
        *, engine_builder: EngineBuilder = build_engines, allow_lan: bool = False,
    ) -> None:
        # Dibuat sebelum bind: server_close() (dipanggil juga bila bind gagal) menghentikannya.
        self._reaper = _LingerReaper()
        super().__init__(address, RequestHandler)
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._per_ip: dict[str, int] = {}
        self._per_ip_lock = threading.Lock()
        self.cfg = cfg
        self.token = secrets.token_urlsafe(TOKEN_BYTES)
        self.allowed_hosts = allowed_hosts
        self.allow_lan = allow_lan
        self.jobs = JobManager(cfg, engine_builder=engine_builder)
        self.jobs.start()

    @property
    def port(self) -> int:
        """Port yang benar-benar dipakai (berguna bila diminta port 0)."""
        return self.server_address[1]

    def close(self) -> None:
        """Hentikan pekerja dan tutup soket."""
        self.jobs.stop()
        self.server_close()

    def server_close(self) -> None:
        """Tutup soket pendengar dan semua soket tertolak yang masih ditahan."""
        super().server_close()
        self._reaper.stop()

    def open_connections(self) -> int:
        """Jumlah koneksi yang sedang dilayani (untuk tes dan diagnosis)."""
        with self._per_ip_lock:
            return sum(self._per_ip.values())

    def process_request(self, request: Any, client_address: Any) -> None:
        """Layani koneksi di thread baru bila jatah total dan jatah IP-nya masih ada.

        Bila penuh, koneksi langsung dijawab 503 + ``Retry-After`` lalu
        diserahkan ke penuai (lihat ``_refuse_busy``); thread penerima tidak
        pernah menunggu jatah.
        """
        address = _client_ip(client_address)
        refusal = self._take_slot(address)
        if refusal:
            logger.warning("koneksi ditolak: %s", refusal)
            self._refuse_busy(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._return_slot(address)
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        """Jalankan handler lalu kembalikan jatah koneksi."""
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._return_slot(_client_ip(client_address))

    def _take_slot(self, address: str) -> str:
        """Ambil jatah untuk ``address``; kembalikan alasan penolakan atau string kosong."""
        with self._per_ip_lock:
            if self._per_ip.get(address, 0) >= MAX_CONNECTIONS_PER_IP:
                return f"sudah {MAX_CONNECTIONS_PER_IP} koneksi dari satu alamat"
            if not self._slots.acquire(blocking=False):
                return f"sudah {MAX_CONNECTIONS} koneksi terbuka"
            self._per_ip[address] = self._per_ip.get(address, 0) + 1
            return ""

    def _return_slot(self, address: str) -> None:
        with self._per_ip_lock:
            left = self._per_ip.get(address, 0) - 1
            if left > 0:
                self._per_ip[address] = left
            else:
                self._per_ip.pop(address, None)
            self._slots.release()

    def _refuse_busy(self, request: Any) -> None:
        """Kirim 503 singkat tanpa memblokir thread penerima, lalu serahkan ke penuai.

        Byte yang sudah tiba dikuras dulu (maks. ``_DRAIN_BYTES``), 503 dikirim,
        dan arah tulis ditutup (FIN) sehingga klien langsung melihat akhir
        balasan. Soketnya belum ditutup: permintaan klien bisa tiba beberapa
        milidetik setelah ``accept``, dan ``close`` sebelum itu membuat kernel
        membalas RST yang membuang 503 di sisi klien. Penuai membuang data itu
        lalu menutup soket. Bila penuai penuh atau soket sudah rusak, soket
        langsung ditutup seperti dulu.
        """
        try:
            request.setblocking(False)
            try:
                request.recv(_DRAIN_BYTES)
            except (BlockingIOError, InterruptedError):
                pass
            request.send(BUSY_RESPONSE)
            request.shutdown(socket.SHUT_WR)
        except OSError:
            self.shutdown_request(request)
            return
        if not self._reaper.add(request):
            self.shutdown_request(request)


class _LingerReaper:
    """Satu thread latar yang menahan soket tertolak sebentar sebelum menutupnya.

    Setiap soket dibaca tanpa blokir (lewat ``selectors``) dan isinya dibuang
    sampai klien menutup koneksi (EOF), ``LINGER_MAX_BYTES`` terlampaui, atau
    ``LINGER_SECONDS`` habis. Jumlah soket dibatasi ``LINGER_MAX_SOCKETS``;
    soket tidak memakai jatah ``MAX_CONNECTIONS``. Thread dibuat saat soket
    pertama datang dan diam (memblokir di antrean) bila tidak ada soket.
    """

    def __init__(self) -> None:
        self._incoming: queue.SimpleQueue[socket.socket | None] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._count = 0
        self._stopped = False
        self._thread: threading.Thread | None = None

    def pending(self) -> int:
        """Jumlah soket yang sedang ditahan (untuk tes dan diagnosis)."""
        with self._lock:
            return self._count

    def add(self, sock: socket.socket) -> bool:
        """Serahkan ``sock``; ``False`` bila penuh atau sudah dihentikan (pemanggil menutup)."""
        with self._lock:
            if self._stopped or self._count >= LINGER_MAX_SOCKETS:
                return False
            self._count += 1
            # Dimasukkan di bawah kunci agar tidak menyusul tanda berhenti dari stop().
            self._incoming.put(sock)
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="jptrans-linger", daemon=True)
                self._thread.start()
        return True

    def stop(self, timeout: float = 2.0) -> None:
        """Hentikan thread dan tutup semua soket yang masih ditahan."""
        with self._lock:
            self._stopped = True
            thread = self._thread
        if thread is not None:
            self._incoming.put(None)
            thread.join(timeout)

    def _run(self) -> None:
        """Putaran thread penuai: terima soket baru, buang datanya, tutup yang selesai."""
        selector = selectors.DefaultSelector()
        held: dict[socket.socket, list[float]] = {}  # soket -> [tenggat, byte dibuang]
        try:
            while True:
                if not self._admit(selector, held, block=not held):
                    return
                if not held:
                    continue
                now = time.monotonic()
                wait = min(_LINGER_POLL, max(0.0, min(v[0] for v in held.values()) - now))
                for key, _ in selector.select(wait):
                    self._drain(selector, held, cast(socket.socket, key.fileobj))
                now = time.monotonic()
                for sock in [s for s, v in held.items() if v[0] <= now]:
                    self._release(selector, held, sock)
        except Exception:  # noqa: BLE001 (thread latar tidak boleh mati diam-diam)
            logger.exception("penuai soket tertolak berhenti karena galat tak terduga")
        finally:
            for sock in list(held):
                self._release(selector, held, sock)
            selector.close()

    def _drain(self, selector: selectors.BaseSelector,
               held: dict[socket.socket, list[float]], sock: socket.socket) -> None:
        """Buang data yang tiba; tutup soket pada EOF, galat, atau batas byte."""
        try:
            data = sock.recv(_DRAIN_BYTES)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        held[sock][1] += len(data)
        if not data or held[sock][1] > LINGER_MAX_BYTES:
            self._release(selector, held, sock)

    def _admit(self, selector: selectors.BaseSelector,
               held: dict[socket.socket, list[float]], *, block: bool) -> bool:
        """Daftarkan soket baru dari antrean; ``False`` bila diminta berhenti."""
        while True:
            try:
                sock = self._incoming.get(block=block)
            except queue.Empty:
                return True
            if sock is None:
                return False
            block = False
            held[sock] = [time.monotonic() + LINGER_SECONDS, 0]
            try:
                selector.register(sock, selectors.EVENT_READ)
            except (OSError, ValueError):
                self._release(selector, held, sock)

    def _release(self, selector: selectors.BaseSelector,
                 held: dict[socket.socket, list[float]], sock: socket.socket) -> None:
        """Lepas ``sock`` dari selector, tutup, dan kurangi hitungan (sekali saja)."""
        if held.pop(sock, None) is None:
            return
        try:
            selector.unregister(sock)
        except (KeyError, ValueError, OSError):
            pass
        try:
            sock.close()
        except OSError:
            pass
        with self._lock:
            self._count -= 1


def _client_ip(client_address: Any) -> str:
    """Alamat IP dari ``client_address`` soket (tuple IPv4/IPv6 atau nilai lain)."""
    if isinstance(client_address, tuple) and client_address:
        return str(client_address[0])
    return str(client_address)


class _DeadlineReader(io.RawIOBase):
    """Pembaca soket mentah yang menolak membaca setelah tenggat total habis.

    Batas waktu soket per operasi diperpendek menjadi sisa tenggat, lalu
    dikembalikan ke ``REQUEST_TIMEOUT`` agar penulisan balasan tidak ikut
    terpotong. ``TimeoutError`` ditangani ``BaseHTTPRequestHandler``.
    """

    def __init__(self, sock: socket.socket, deadline: Callable[[], float]) -> None:
        super().__init__()
        self._sock = sock
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        remaining = self._deadline() - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("tenggat total permintaan habis")
        self._sock.settimeout(min(REQUEST_TIMEOUT, remaining))
        try:
            return self._sock.recv_into(buffer)
        finally:
            self._sock.settimeout(REQUEST_TIMEOUT)


class RequestHandler(BaseHTTPRequestHandler):
    """Router kecil untuk halaman dan API JSON."""

    server: JptransServer
    server_version = f"jptrans/{__version__}"
    sys_version = ""
    # StreamRequestHandler memasang batas waktu soket; TimeoutError ditangani http.server.
    timeout = REQUEST_TIMEOUT
    _deadline: float = 0.0
    """Waktu ``time.monotonic()`` saat tenggat fase baca yang sedang berjalan habis."""

    def setup(self) -> None:
        """Ganti ``rfile`` dengan pembaca bertenggat total (lihat ``_DeadlineReader``)."""
        super().setup()
        self._deadline = time.monotonic() + HEADER_TIMEOUT
        original = self.rfile
        self.rfile = io.BufferedReader(_DeadlineReader(self.connection, lambda: self._deadline))
        original.close()

    def handle_one_request(self) -> None:
        """Mulai tenggat header baru untuk setiap permintaan.

        Server berbicara HTTP/1.0 (``protocol_version`` bawaan), jadi koneksi
        ditutup setelah satu permintaan; penghitungan ulang ini hanya jaga-jaga
        bila ``protocol_version`` kelak dinaikkan dan keep-alive aktif.
        """
        self._deadline = time.monotonic() + HEADER_TIMEOUT
        super().handle_one_request()

    def do_GET(self) -> None:  # noqa: N802 (nama metode ditentukan http.server)
        """Halaman utama, status pekerjaan, dan unduhan hasil."""
        if not self._host_ok():
            return
        url = urlsplit(self.path)
        if url.path == "/":
            self._send(HTTPStatus.OK, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8",
                       extra={"Content-Security-Policy": PAGE_CSP})
            return
        if url.path == "/api/meta":
            if not self._token_ok():
                return
            self._json(HTTPStatus.OK, _server_meta(self.server.cfg))
            return
        match = _JOB_PATH_RE.match(url.path)
        if match is None:
            if url.path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "tidak ditemukan"})
            else:
                # Alamat yang diketik di browser: halaman galat kecil, bukan JSON mentah.
                # Jalur permintaan sengaja tidak ditampilkan ulang.
                self._send(HTTPStatus.NOT_FOUND, NOT_FOUND_HTML.encode("utf-8"),
                           "text/html; charset=utf-8",
                           extra={"Content-Security-Policy": ERROR_CSP})
            return
        if not self._token_ok():
            return
        if match["download"]:
            self._download(match["id"], parse_qs(url.query).get("fmt", ["html"])[0])
            return
        summary = self.server.jobs.summary(match["id"])
        if summary is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "pekerjaan tidak ditemukan"})
        else:
            self._json(HTTPStatus.OK, summary)

    def do_POST(self) -> None:  # noqa: N802
        """``POST /api/jobs`` (asinkron) dan ``POST /api/translate`` (JSON sinkron)."""
        if not self._host_ok():
            return
        url = urlsplit(self.path)
        if url.path not in ("/api/jobs", "/api/translate"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "tidak ditemukan"})
            return
        if not self._token_ok():
            return
        body = self._read_body()
        if body is None:
            return
        try:
            request = self._job_request(body, parse_qs(url.query))
        except ConfigError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if url.path == "/api/translate":
            self._translate_sync(request)
            return
        job = self.server.jobs.submit(request)
        if job is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "antrean penuh, coba lagi"},
                       extra={"Retry-After": str(RETRY_AFTER_SECONDS)})
        else:
            self._json(HTTPStatus.ACCEPTED, {"id": job.id, "status": job.status})

    def _translate_sync(self, request: JobRequest) -> None:
        job = self.server.jobs.run_sync(request)
        if job is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "antrean penuh atau waktu habis"},
                       extra={"Retry-After": str(RETRY_AFTER_SECONDS)})
            return
        if job.status != DONE or job.result is None:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": job.error or "terjemahan gagal"})
            return
        payload = {"target": job.result.target, **result_to_dict(job.result)}
        self._json(HTTPStatus.OK, payload)

    def _host_ok(self) -> bool:
        """Tolak header ``Host`` yang tidak dikenal (pertahanan DNS rebinding)."""
        host = self.headers.get("Host")
        if not host:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "header Host wajib"})
            return False
        parsed = host_name(host)
        if not parsed:
            self._json(HTTPStatus.FORBIDDEN, {"error": "host tidak diizinkan"})
            return False
        if parsed in self.server.allowed_hosts:
            return True
        if self.server.allow_lan and _is_private_lan_ip(parsed):
            return True
        self._json(HTTPStatus.FORBIDDEN, {"error": "host tidak diizinkan"})
        return False

    def _token_ok(self) -> bool:
        given = self.headers.get("X-Token", "")
        if secrets.compare_digest(given.encode("utf-8"), self.server.token.encode("utf-8")):
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "token salah atau tidak ada"})
        return False

    def _read_body(self) -> bytes | None:
        """Baca badan permintaan dengan batas ukuran; balas galat bila tidak sah."""
        raw = self.headers.get("Content-Length")
        if raw is None:
            self._json(HTTPStatus.LENGTH_REQUIRED, {"error": "Content-Length wajib"})
            return None
        try:
            length = int(raw)
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Content-Length tidak sah"})
            return None
        if length <= 0:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "badan permintaan kosong"})
            return None
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                       {"error": f"maksimal {MAX_BODY_BYTES // (1024 * 1024)} MB"})
            return None
        self._deadline = time.monotonic() + BODY_TIMEOUT
        data = self.rfile.read(length)
        if len(data) < length:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "badan permintaan terputus"})
            return None
        return data

    def _job_request(self, body: bytes, query: dict[str, list[str]]) -> JobRequest:
        """Ubah badan permintaan menjadi ``JobRequest`` yang sudah divalidasi.

        Raises:
            ConfigError: Isi permintaan tidak sah.
        """
        filename = unquote(self.headers.get("X-Filename", "")).strip()
        if filename:
            options = {key: values[-1] for key, values in query.items()}
            return parse_upload(filename, body, options, self.server.cfg)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            # RecursionError: JSON bersarang sangat dalam ([[[[...]]]]).
            raise ConfigError(f"badan bukan JSON UTF-8 yang sah: {type(exc).__name__}") from exc
        return parse_text_request(payload, self.server.cfg)

    def _download(self, job_id: str, fmt: str) -> None:
        result = self.server.jobs.result(job_id)
        if result is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "hasil belum ada"})
            return
        if fmt not in RENDERERS:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"format: {', '.join(RENDERERS)}"})
            return
        try:
            content = render_output(result, fmt)
        except JptransError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        name = f"{slugify(result.document.title)}.{result.target_lang}.{fmt}"
        encoded = quote(name, safe="")
        disposition = f"attachment; filename=\"jptrans.{fmt}\"; filename*=UTF-8''{encoded}"
        mime = CONTENT_TYPES.get(fmt, "application/octet-stream")
        self._send(HTTPStatus.OK, content.encode("utf-8"), f"{mime}; charset=utf-8",
                   extra={"Content-Disposition": disposition})

    def _json(self, status: HTTPStatus, payload: dict[str, Any],
              extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """Catat permintaan tanpa query string (tidak pernah memuat token)."""
        path = urlsplit(self.path).path if hasattr(self, "path") else "-"
        logger.info("%s %s %s", getattr(self, "command", "-"), path, code)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Alihkan log bawaan ``http.server`` (stderr) ke ``logging``."""
        logger.debug("http: %s", format % args)


def _busy_response(protocol: str) -> bytes:
    """Balasan 503 lengkap yang dikirim thread penerima saat jatah koneksi penuh.

    Args:
        protocol: Versi protokol di baris status, sama dengan balasan biasa server
            (``RequestHandler.protocol_version``, yaitu ``HTTP/1.0``).
    """
    body = json.dumps({"error": "server sibuk, coba lagi"}, ensure_ascii=False).encode("utf-8")
    head = (
        f"{protocol} 503 Service Unavailable\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Retry-After: {RETRY_AFTER_SECONDS}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "X-Content-Type-Options: nosniff\r\n\r\n"
    )
    return head.encode("ascii") + body


BUSY_RESPONSE = _busy_response(RequestHandler.protocol_version)


def _server_meta(cfg: Config) -> dict[str, Any]:
    """Metadata kapabilitas server untuk antarmuka web maupun klien aplikasi eksternal."""
    return {
        "version": __version__,
        "languages": list(LANGS),
        "honorific_styles": list(HONORIFIC_STYLES),
        "romanizations": list(ROMANIZATIONS),
        "name_orders": list(NAME_ORDERS),
        "input_formats": sorted(READERS),
        "output_formats": list(RENDERERS),
        "engines": [
            {"name": name, "available": ok, "reason": reason}
            for name, ok, reason in describe_engines(cfg)
        ],
    }


def _optional_choice(field_name: str, value: Any, choices: tuple[str, ...]) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in choices:
        raise ConfigError(f"{field_name!r} harus salah satu dari {', '.join(choices)}")
    return value


def parse_text_request(payload: Any, cfg: Config) -> JobRequest:
    """Validasi badan JSON ``{"text", "title", "to", "engine", ...}``."""
    if not isinstance(payload, dict):
        raise ConfigError("badan JSON harus objek")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ConfigError("'text' wajib berupa teks tidak kosong")
    return JobRequest(
        title=_title(payload.get("title"), "teks"),
        target=_target(payload.get("to"), cfg),
        engines=_engine_names(payload.get("engine")),
        text=text,
        honorific_style=_optional_choice(
            "honorifics", payload.get("honorifics"), HONORIFIC_STYLES
        ),
        romanization=_optional_choice("romaji", payload.get("romaji"), ROMANIZATIONS),
        name_order=_optional_choice(
            "name_order", payload.get("name_order"), NAME_ORDERS
        ),
    )


def parse_upload(filename: str, data: bytes, options: dict[str, str], cfg: Config) -> JobRequest:
    """Validasi unggahan berkas mentah; opsi dibaca dari query string."""
    name = upload_basename(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in READERS:
        raise ConfigError(f"format {suffix or '(tanpa sufiks)'} tidak didukung; "
                          f"pilih: {', '.join(sorted(READERS))}")
    return JobRequest(
        title=_title(options.get("title"), ""),
        target=_target(options.get("to"), cfg),
        engines=_engine_names(options.get("engine")),
        data=data,
        filename=name,
        honorific_style=_optional_choice(
            "honorifics", options.get("honorifics"), HONORIFIC_STYLES
        ),
        romanization=_optional_choice("romaji", options.get("romaji"), ROMANIZATIONS),
        name_order=_optional_choice(
            "name_order", options.get("name_order"), NAME_ORDERS
        ),
    )


def upload_basename(filename: str) -> str:
    """Nama dasar berkas unggahan, memisah di ``/`` maupun ``\\`` di semua platform.

    Browser lama di Windows mengirim path lengkap (``C:\\fakepath\\bab.txt``).
    ``Path`` di POSIX tidak menganggap ``\\`` pemisah, sehingga judul dan sufiks
    bisa berbeda dari server yang berjalan di Windows. ``PureWindowsPath``
    memisah keduanya dan membuang huruf drive.
    """
    return PureWindowsPath(filename).name


def _title(value: Any, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    if not isinstance(value, str):
        raise ConfigError("'title' harus teks")
    return value.strip() or fallback


def _target(value: Any, cfg: Config) -> str:
    target = cfg.target_lang if value in (None, "") else value
    if target not in LANGS:
        raise ConfigError(f"'to' harus salah satu dari {', '.join(LANGS)}")
    return target


def _engine_names(value: Any) -> tuple[str, ...]:
    if value in (None, "", []):
        return ()
    items = value.split(",") if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ConfigError("'engine' harus daftar nama mesin")
    names = [item for item in items if item.strip()]
    return tuple(normalize_engine_names(names)) if names else ()


def _is_private_lan_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def host_name(header: str) -> str:
    """Ambil nama host dari header ``Host`` secara ketat (mencegah bypass IPv6)."""
    header = header.strip().lower()
    if not header:
        return ""
    if header.startswith("["):
        inside, sep, rest = header[1:].partition("]")
        if not sep or not inside:
            return ""
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return ""
        return inside
    if ":" in header:
        name, port = header.rsplit(":", 1)
        return name if port.isdigit() and ":" not in name else ""
    return header


def lan_ip() -> str:
    """Tebak IP LAN komputer ini; ``127.0.0.1`` bila tidak ada jaringan."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(_ROUTE_PROBE)
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def allowed_hosts(bind_host: str, lan_address: str | None = None) -> frozenset[str]:
    """Daftar nilai ``Host`` yang diterima untuk alamat bind tertentu."""
    hosts = set(LOOPBACK_HOSTS)
    if bind_host not in ("0.0.0.0", "::", ""):
        hosts.add(bind_host.lower())
    if lan_address:
        hosts.add(lan_address)
    return frozenset(hosts)


def make_server(
    cfg: Config, host: str = "127.0.0.1", port: int = 8765, *, lan: bool = False,
    engine_builder: EngineBuilder = build_engines,
) -> JptransServer:
    """Buat server yang siap ``serve_forever`` (port 0 memilih port bebas, untuk tes).

    Raises:
        ConfigError: Port sedang dipakai atau alamat tidak bisa di-bind.
    """
    bind_host = "0.0.0.0" if lan else host
    lan_address = lan_ip() if lan else None
    try:
        return JptransServer(
            (bind_host, port),
            cfg,
            allowed_hosts(bind_host, lan_address),
            engine_builder=engine_builder,
            allow_lan=lan,
        )
    except OSError as exc:
        raise ConfigError(f"tidak bisa membuka server di {bind_host}:{port}: {exc}") from exc


def serve(
    cfg: Config, host: str = "127.0.0.1", port: int = 8765, *, lan: bool = False,
    open_browser: bool = False, on_ready: Callable[[str, bool], None] | None = None,
) -> None:
    """Jalankan server sampai Ctrl+C.

    Args:
        cfg: Konfigurasi program.
        host: Alamat bind.
        port: Port.
        lan: Bind ``0.0.0.0`` dan umumkan alamat IP LAN.
        open_browser: Buka browser bawaan ke URL bertoken.
        on_ready: Dipanggil dengan (URL bertoken, mode LAN) setelah server siap;
            CLI memakainya untuk mencetak URL. Tanpa callback, URL tidak
            ditampilkan di mana pun karena memuat token.
    """
    server = make_server(cfg, host, port, lan=lan)
    shown_host = lan_ip() if lan else ("127.0.0.1" if host in ("0.0.0.0", "") else host)
    url = f"http://{_url_host(shown_host)}:{server.port}/#t={server.token}"
    logger.info("server berjalan di %s:%d (lan=%s)", shown_host, server.port, lan)
    if on_ready is not None:
        on_ready(url, lan)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("server dihentikan")
    finally:
        server.close()


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


PAGE_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; frame-src 'self' blob:; img-src data: blob:; base-uri 'none'; "
            "form-action 'none'")

ERROR_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"

NOT_FOUND_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Halaman tidak ditemukan - jptrans</title>
<style>
:root { --bg: #fafaf7; --fg: #1d1d1b; --muted: #6b6b66; --accent: #2457a6; --line: #8e8d86; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --fg: #ecebe6; --muted: #a3a29c; --accent: #8db4f0; --line: #6c6b66; }
}
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 1rem; }
h1 { font-size: 1.4rem; margin: .5rem 0 1rem; }
p { color: var(--muted); }
a { color: var(--accent); min-height: 44px; display: inline-flex; align-items: center;
    padding: 0 .9rem; border: 1px solid var(--line); border-radius: .5rem; }
a:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
</style>
</head>
<body>
<main>
<h1>Halaman tidak ditemukan (404)</h1>
<p>Alamat ini tidak ada di server jptrans. Halaman penerjemah ada di alamat utama;
token tetap tersimpan selama tab browser ini terbuka.</p>
<p><a href="/">Kembali ke jptrans</a></p>
</main>
</body>
</html>
"""

PAGE_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>jptrans</title>
<style>
:root, :root[data-theme="light"] {
  color-scheme: light; --bg: #fafaf7; --fg: #1d1d1b; --muted: #6b6b66; --line: #8e8d86;
  --accent: #2457a6; --on-accent: #ffffff; --err: #b3261e; --err-bg: #fdecea;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark; --bg: #161615; --fg: #ecebe6; --muted: #a3a29c; --line: #6c6b66;
    --accent: #8db4f0; --on-accent: #161615; --err: #ff8a80; --err-bg: #3b1d1b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark; --bg: #161615; --fg: #ecebe6; --muted: #a3a29c; --line: #6c6b66;
  --accent: #8db4f0; --on-accent: #161615; --err: #ff8a80; --err-bg: #3b1d1b;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); overflow-wrap: break-word;
       font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 1rem 1rem 3rem; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: .75rem;
          margin: .25rem 0 1rem; flex-wrap: wrap; }
h1 { font-size: 1.4rem; margin: 0; }
label { display: block; font-weight: 600; margin: .75rem 0 .25rem; }
textarea, input, select, button { font: inherit; color: inherit; background: transparent;
  border: 1px solid var(--line); border-radius: .5rem; padding: .5rem .6rem; width: 100%;
  min-height: 44px; }
option { background: var(--bg); color: var(--fg); }
textarea { min-height: 10rem; resize: vertical; }
textarea:lang(ja) { font-family: "Hiragino Sans", "Yu Gothic", "Noto Sans JP", sans-serif; }
.row { display: grid; gap: .75rem; grid-template-columns: 1fr 1fr; }
.file-row { display: flex; gap: .5rem; align-items: center; }
button { background: var(--accent); color: var(--on-accent); border: 0; font-weight: 600;
         margin-top: 1rem; cursor: pointer; }
button.secondary { background: transparent; color: var(--fg); border: 1px solid var(--line);
                   margin-top: 0; width: auto; white-space: nowrap; padding: .5rem .9rem; }
button[disabled] { opacity: .5; cursor: not-allowed; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
#status { color: var(--muted); margin: 1rem 0; min-height: 1.5em; }
#status.err, .alert { color: var(--err); font-weight: 600; background: var(--err-bg);
                      border-left: 4px solid var(--err); border-radius: .5rem;
                      padding: .6rem .8rem; }
#links { display: flex; flex-wrap: wrap; gap: .5rem; margin: .75rem 0; }
iframe { width: 100%; height: 70vh; border: 1px solid var(--line); border-radius: .5rem;
         background: var(--bg); margin-top: .5rem; }
.hidden { display: none !important; }
@media (max-width: 30rem) { .row { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<main>
<div class="topbar">
  <h1>jptrans</h1>
  <button id="theme" type="button" class="secondary">Tema: Otomatis</button>
</div>
<p id="notoken" class="hidden alert" role="alert">Token tidak ada. Buka alamat lengkap
(dengan <code>#t=...</code>) yang dicetak di terminal.</p>
<form id="form">
  <label for="text">Teks Jepang</label>
  <textarea id="text" lang="ja" placeholder="田中さんは東京駅で佐藤先輩を待っていた。"></textarea>
  <label for="file">atau unggah berkas (.txt .md .html .epub .srt .vtt .ass .json)</label>
  <div class="file-row">
    <input id="file" type="file"
      accept=".txt,.md,.html,.htm,.xhtml,.epub,.srt,.vtt,.ass,.ssa,.json">
    <button id="clearfile" type="button" class="secondary hidden">Hapus berkas</button>
  </div>
  <div class="row">
    <div><label for="title">Judul (menentukan glosarium)</label>
      <input id="title" placeholder="teks"></div>
    <div><label for="to">Bahasa sasaran</label>
      <select id="to"><option value="id">Indonesia</option><option value="en">Inggris</option>
      </select></div>
  </div>
  <label for="engine">Mesin (kosong = bawaan, mis. deepl,mymemory atau fake)</label>
  <input id="engine" placeholder="">
  <button id="go" type="submit">Terjemahkan</button>
</form>
<p id="status" role="status">Tempel teks Jepang atau pilih berkas, lalu tekan Terjemahkan.</p>
<div id="links" class="hidden">
  <button type="button" class="secondary" data-fmt="html">Unduh HTML</button>
  <button type="button" class="secondary" data-fmt="txt">Unduh TXT</button>
  <button type="button" class="secondary" data-fmt="md">Unduh MD</button>
  <button type="button" class="secondary" data-fmt="json">Unduh JSON</button>
  <button type="button" class="secondary hidden" data-fmt="srt" id="srt">Unduh SRT</button>
  <button type="button" class="secondary hidden" data-fmt="vtt" id="vtt">Unduh VTT</button>
  <button type="button" class="secondary hidden" data-fmt="ass" id="ass">Unduh ASS</button>
</div>
<iframe id="view" class="hidden" sandbox title="Hasil terjemahan"></iframe>
</main>
<script>
"use strict";
const KEY = "jptrans-token";
const THEME_KEY = "jptrans-theme";
const THEMES = ["auto", "dark", "light"];
const THEME_LABELS = {auto: "Tema: Otomatis", dark: "Tema: Gelap", light: "Tema: Terang"};
const hash = new URLSearchParams(location.hash.slice(1));
if (hash.get("t")) {
  sessionStorage.setItem(KEY, hash.get("t"));
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem(KEY) || "";
const $ = (id) => document.getElementById(id);
if (!token) { $("notoken").classList.remove("hidden"); $("go").disabled = true; }
let jobId = null;

function applyTheme(mode) {
  if (mode === "dark" || mode === "light") {
    document.documentElement.dataset.theme = mode;
  } else {
    delete document.documentElement.dataset.theme;
    mode = "auto";
  }
  $("theme").textContent = THEME_LABELS[mode];
}
let currentTheme = localStorage.getItem(THEME_KEY) || "auto";
if (!THEMES.includes(currentTheme)) currentTheme = "auto";
applyTheme(currentTheme);
$("theme").addEventListener("click", () => {
  currentTheme = THEMES[(THEMES.indexOf(currentTheme) + 1) % THEMES.length];
  localStorage.setItem(THEME_KEY, currentTheme);
  applyTheme(currentTheme);
});

function api(path, options = {}) {
  options.headers = Object.assign({"X-Token": token}, options.headers || {});
  return fetch(path, options).then(async (response) => {
    if (!response.ok) {
      let message = response.statusText;
      try { message = (await response.json()).error || message; } catch (e) {}
      throw new Error(message);
    }
    return response;
  });
}

function say(text, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("err", error);
}

$("file").addEventListener("change", () => {
  $("clearfile").classList.toggle("hidden", !$("file").files.length);
});
$("clearfile").addEventListener("click", () => {
  $("file").value = "";
  $("clearfile").classList.add("hidden");
});

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("file").files[0];
  const options = {title: $("title").value.trim(), to: $("to").value,
                   engine: $("engine").value.trim()};
  let request;
  if (file) {
    const query = new URLSearchParams(options).toString();
    request = api("/api/jobs?" + query, {method: "POST", body: file,
      headers: {"X-Filename": encodeURIComponent(file.name),
                "Content-Type": "application/octet-stream"}});
  } else {
    const text = $("text").value;
    if (!text.trim()) { say("Isi teks atau pilih berkas dulu.", true); return; }
    const body = {text, title: options.title || "teks", to: options.to};
    if (options.engine) body.engine = options.engine.split(",");
    request = api("/api/jobs", {method: "POST", body: JSON.stringify(body),
      headers: {"Content-Type": "application/json"}});
  }
  $("go").disabled = true;
  $("links").classList.add("hidden");
  $("view").classList.add("hidden");
  try {
    jobId = (await (await request).json()).id;
    poll();
  } catch (error) { say("Gagal: " + error.message, true); $("go").disabled = false; }
});

async function poll() {
  try {
    const job = await (await api("/api/jobs/" + jobId)).json();
    if (job.status === "done") {
      say("Selesai.");
      $("view").srcdoc = job.html;
      $("view").classList.remove("hidden");
      const isSub = ["srt", "vtt", "ass"].includes(job.format);
      $("srt").classList.toggle("hidden", !isSub);
      $("vtt").classList.toggle("hidden", !isSub);
      $("ass").classList.toggle("hidden", !isSub);
      $("links").classList.remove("hidden");
      $("go").disabled = false;
      return;
    }
    if (job.status === "failed") {
      say("Gagal: " + job.error, true); $("go").disabled = false; return;
    }
    say(job.total ? `Menerjemahkan ${job.done}/${job.total} kalimat (${job.message})`
                  : "Menunggu giliran...");
    setTimeout(poll, 1000);
  } catch (error) { say("Gagal: " + error.message, true); $("go").disabled = false; }
}

$("links").addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-fmt]");
  if (!btn || !jobId) return;
  const fmt = btn.dataset.fmt;
  event.preventDefault();
  try {
    const response = await api(`/api/jobs/${jobId}/download?fmt=${fmt}`);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await response.blob());
    link.download = ($("title").value.trim() || "jptrans") + "." + fmt;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  } catch (error) { say("Gagal mengunduh: " + error.message, true); }
});
</script>
</body>
</html>
"""
''')

MODUL['jptrans.style'] = (
    False,
r'''"""Aturan gaya subtitle/fansub: bentuk akhir nama, honorifik, urutan, sufiks, gloss.

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
''')

MODUL['jptrans.textnorm'] = (
    False,
r'''"""Kelas karakter Jepang dan normalisasi kunci pencarian.

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
''')

MODUL['jptrans.writers'] = (
    True,
r'''"""Penulis keluaran: memilih format dari argumen eksplisit atau sufiks berkas.

Tiap penulis adalah fungsi murni ``TranslatedDocument -> str``, sehingga server
web bisa merender di memori dan ``write_output`` hanya menulis ke disk.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from ..config import REGISTERED_OUTPUT_FORMATS
from ..errors import ConfigError, JptransError
from ..models import TranslatedDocument
from .html import render_html
from .subtitle import render_ass, render_srt, render_vtt
from .text import render_json, render_md, render_txt

logger = logging.getLogger(__name__)

RENDERERS: dict[str, Callable[[TranslatedDocument], str]] = {
    "html": render_html,
    "txt": render_txt,
    "md": render_md,
    "json": render_json,
    "srt": render_srt,
    "vtt": render_vtt,
    "ass": render_ass,
}
SUFFIX_FORMATS = {
    ".html": "html",
    ".htm": "html",
    ".txt": "txt",
    ".md": "md",
    ".json": "json",
    ".srt": "srt",
    ".vtt": "vtt",
    ".ass": "ass",
    ".ssa": "ass",
}
CONTENT_TYPES: dict[str, str] = {
    "html": "text/html",
    "txt": "text/plain",
    "md": "text/markdown",
    "json": "application/json",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "ass": "text/plain",
}


def output_format(out: Path, fmt: str | None = None) -> str:
    """Tentukan format keluaran: argumen ``fmt`` menang atas sufiks ``out``."""
    chosen = fmt or SUFFIX_FORMATS.get(Path(out).suffix.lower())
    if chosen not in RENDERERS:
        supported = ", ".join(RENDERERS)
        raise ConfigError(
            f"format keluaran {chosen or Path(out).suffix!r} tidak dikenal; "
            f"pilih: {supported}"
        )
    return chosen


def render_output(
    result: TranslatedDocument, fmt: str, *, bilingual: bool = False
) -> str:
    """Bangun isi keluaran sebagai string tanpa menyentuh disk."""
    if fmt not in RENDERERS:
        raise ConfigError(
            f"format keluaran {fmt!r} tidak dikenal; pilih: {', '.join(RENDERERS)}"
        )
    if fmt == "txt":
        return render_txt(result, bilingual=bilingual)
    return RENDERERS[fmt](result)


def write_output(
    result: TranslatedDocument,
    out: Path,
    fmt: str | None = None,
    *,
    bilingual: bool = False,
) -> Path:
    """Tulis hasil terjemahan ke berkas UTF-8 dengan baris baru ``\\n``."""
    out = Path(out)
    content = render_output(
        result, output_format(out, fmt), bilingual=bilingual
    )
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise JptransError(
            f"tidak bisa menulis {out}: {exc.strerror or exc}"
        ) from exc
    logger.info("keluaran ditulis ke %s (%d karakter)", out, len(content))
    return out


def register_writer(
    fmt: str,
    renderer: Callable[[TranslatedDocument], str],
    *,
    suffixes: Sequence[str] = (),
    content_type: str = "text/plain",
) -> None:
    """Daftarkan penulis keluaran kustom ke ``RENDERERS``, ``SUFFIX_FORMATS``, dan ``Config``."""
    clean = fmt.strip().lower().lstrip(".")
    if not clean or not callable(renderer):
        raise ConfigError(f"penulis atau nama format tidak sah: {fmt!r}")
    RENDERERS[clean] = renderer
    CONTENT_TYPES[clean] = content_type
    for raw_sfx in suffixes or (f".{clean}",):
        sfx = raw_sfx.strip().lower()
        SUFFIX_FORMATS[sfx if sfx.startswith(".") else f".{sfx}"] = clean
    if clean not in REGISTERED_OUTPUT_FORMATS:
        REGISTERED_OUTPUT_FORMATS.append(clean)
    logger.debug("penulis kustom terdaftar: %s", clean)


__all__ = [
    "CONTENT_TYPES",
    "RENDERERS",
    "SUFFIX_FORMATS",
    "output_format",
    "render_output",
    "register_writer",
    "write_output",
]
''')

MODUL['jptrans.writers.html'] = (
    False,
r'''"""Penulis HTML bilingual: keluaran utama untuk membaca di HP.

Hasilnya satu berkas mandiri yang bisa dibuka di browser mana pun tanpa
Python, tanpa internet, dan tanpa JavaScript:

- Tiap paragraf adalah ``<details>``; ketuk terjemahan untuk menampilkan teks
  Jepang aslinya (lengkap dengan ``<ruby>`` furigana). Teks asli diletakkan di
  dalam ``<summary>`` dan disembunyikan dengan CSS, sehingga mode "tampilkan
  semua" dan mode dua kolom berdampingan cukup memakai checkbox CSS tanpa
  menggandakan teks.
- Tipografi nyaman untuk novel, mode gelap mengikuti ``prefers-color-scheme``,
  dua kolom (CSS grid) hanya di layar lebar.
- Bagian akhir: tabel glosarium, statistik, dan atribusi mesin.

Semua teks dari dokumen melewati ``html.escape``. Tag format subtitle SRT
(``<i>``, ``{\\an8}``, ``<font ...>``) milik pemutar video, jadi di halaman baca
hasil SRT tag itu dibuang dari terjemahan dan teks asli (``TAG_FORMATS``).
"""

from __future__ import annotations

import html
import logging
import re
from collections import Counter
from collections.abc import Callable

from .. import __version__
from ..models import (
    DIALOGUE_DASH, STATUS_CACHED, STATUS_FAILED, STATUS_OK, STATUS_PARTIAL, STATUS_PLAIN,
    STATUS_PRESUB, Paragraph, SentencePair, TranslatedDocument, TranslatedParagraph,
    strip_format_tags,
)
from ..textnorm import contains_japanese
from .text import paragraph_text, rendered_form, sorted_glossary

logger = logging.getLogger(__name__)

STATUS_ORDER = (STATUS_OK, STATUS_CACHED, STATUS_PRESUB, STATUS_PLAIN, STATUS_PARTIAL,
                STATUS_FAILED)
# Kunci stats yang tidak dicetak mentah: "rendered" adalah peta glosarium untuk tabel;
# jumlah per status dan per mesin sudah tampil sebagai ubin dan baris "Mesin".
HIDDEN_STATS = frozenset({"rendered", "by_status", "by_engine"})
# Status yang diberi penanda visual di teks (kelas CSS = nama status) dan dijelaskan di legenda.
MARKED_STATUSES = (STATUS_FAILED, STATUS_PRESUB, STATUS_PARTIAL)
TAG_FORMATS = frozenset({"srt", "vtt", "ass"})
"""Format masukan yang tag formatnya (``<i>``, ``{\\an8}``) tidak ditampilkan di HTML."""
MIN_RUBY_BASE = 2   # ruby satu kanji (日《ひ》) mudah salah bila ditempel di semua kemunculan

UI = {
    "id": {
        "lang_names": {"ja": "Jepang", "id": "Indonesia", "en": "Inggris"},
        "paragraphs": "paragraf", "sentences": "kalimat",
        "hint": "Ketuk paragraf untuk melihat teks Jepang aslinya.",
        "show_all": "Tampilkan teks asli", "side_by_side": "Berdampingan",
        "th_auto": "Tema: Otomatis", "th_light": "Terang", "th_dark": "Gelap",
        "toc": "Daftar isi", "page": "Halaman", "glossary": "Glosarium",
        "surface": "Tulisan", "reading": "Bacaan", "used": "Dipakai", "kind": "Jenis",
        "review": "perlu ditinjau", "stats": "Statistik", "engines": "Mesin",
        "total": "Total kalimat", "credits": "Atribusi",
        "failed_title": "Gagal diterjemahkan; teks asli dipertahankan",
        "presub_title": "Lewat jalur cadangan (nama disisipkan sebelum diterjemahkan); "
                        "periksa ulang",
        "partial_title": "Sebagian kalimat masih berhuruf Jepang",
        "legend": "Tanda:",
        "failed_note": "Kalimat bertanda kuning gagal diterjemahkan semua mesin "
                       "dan ditampilkan dalam bahasa aslinya.",
        "disclaimer": "Terjemahan mesin. Nama, tempat, dan istilah dijaga oleh glosarium "
                      "jptrans, tetapi makna kalimat bisa keliru.",
        "made_by": "Dibuat dengan jptrans",
        "engine_notes": {"google": "endpoint tidak resmi", "fake": "uji, bukan terjemahan nyata"},
        "yes": "ya", "no": "tidak",
        "kinds": {"PERSON": "orang", "PLACE": "tempat", "ORG": "organisasi",
                  "TERM": "istilah", "CULTURE": "budaya"},
        "status": {STATUS_OK: "diterjemahkan", STATUS_CACHED: "dari cache",
                   STATUS_PRESUB: "jalur cadangan", STATUS_PLAIN: "tanpa teks Jepang",
                   STATUS_PARTIAL: "sebagian masih Jepang", STATUS_FAILED: "gagal"},
        "stat_labels": {"chars_sent": "Karakter terkirim", "elapsed": "Waktu (detik)",
                        "seconds": "Waktu (detik)", "new_entries": "Entri glosarium baru",
                        "requests": "Permintaan", "by_engine": "Per mesin",
                        "by_status": "Per status"},
    },
    "en": {
        "lang_names": {"ja": "Japanese", "id": "Indonesian", "en": "English"},
        "paragraphs": "paragraphs", "sentences": "sentences",
        "hint": "Tap a paragraph to see the original Japanese.",
        "show_all": "Show original", "side_by_side": "Side by side",
        "th_auto": "Theme: Auto", "th_light": "Light", "th_dark": "Dark",
        "toc": "Contents", "page": "Page", "glossary": "Glossary",
        "surface": "Written", "reading": "Reading", "used": "Rendered as", "kind": "Type",
        "review": "needs review", "stats": "Statistics", "engines": "Engines",
        "total": "Total sentences", "credits": "Credits",
        "failed_title": "Translation failed; original text kept",
        "presub_title": "Fallback path (names inserted before translation); please check",
        "partial_title": "Part of the sentence is still in Japanese",
        "legend": "Marks:",
        "failed_note": "Sentences highlighted in yellow failed on every engine "
                       "and are shown in the original language.",
        "disclaimer": "Machine translation. Names, places and terms are kept consistent by "
                      "the jptrans glossary, but sentence meaning may be wrong.",
        "made_by": "Made with jptrans",
        "engine_notes": {"google": "unofficial endpoint", "fake": "test, not a real translation"},
        "yes": "yes", "no": "no",
        "kinds": {"PERSON": "person", "PLACE": "place", "ORG": "organization",
                  "TERM": "term", "CULTURE": "culture"},
        "status": {STATUS_OK: "translated", STATUS_CACHED: "from cache",
                   STATUS_PRESUB: "fallback path", STATUS_PLAIN: "no Japanese text",
                   STATUS_PARTIAL: "partly Japanese", STATUS_FAILED: "failed"},
        "stat_labels": {"chars_sent": "Characters sent", "elapsed": "Time (seconds)",
                        "seconds": "Time (seconds)", "new_entries": "New glossary entries",
                        "requests": "Requests", "by_engine": "By engine",
                        "by_status": "By status"},
    },
}

ENGINE_NAMES = {
    "deepl": "DeepL API (deepl.com)",
    "mymemory": "MyMemory (mymemory.translated.net)",
    "google": "Google Translate (translate.googleapis.com)",
    "llm": "LLM (OpenAI-compatible API)",
    "libretranslate": "LibreTranslate",
    "fake": "FakeEngine",
}

CSS = """
:root{color-scheme:light dark;--bg:#faf7f2;--fg:#22201c;--muted:#6b665d;--line:#878074;
--card:#f2ede4;--accent:#3d5bd9;--accent-fg:#fff;--warn:#8a5a0b;--warn-bg:#fdf3d7;
--info:#3d5bd9;
--serif:ui-serif,Georgia,"Noto Serif","Times New Roman",serif;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",sans-serif;
--ja:"Hiragino Mincho ProN","Yu Mincho","Noto Serif JP","Noto Serif CJK JP",serif}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e7e3db;--muted:#9b968c;
--line:#6d7380;--card:#1f2227;--accent:#93a4ff;--accent-fg:#16181c;--warn:#e0b45a;
--warn-bg:#4d3b14;--info:#93a4ff}}
:root:has(#th-light:checked){color-scheme:light;--bg:#faf7f2;--fg:#22201c;--muted:#6b665d;
--line:#878074;--card:#f2ede4;--accent:#3d5bd9;--accent-fg:#fff;--warn:#8a5a0b;
--warn-bg:#fdf3d7;--info:#3d5bd9}
:root:has(#th-dark:checked){color-scheme:dark;--bg:#16181c;--fg:#e7e3db;--muted:#9b968c;
--line:#6d7380;--card:#1f2227;--accent:#93a4ff;--accent-fg:#16181c;--warn:#e0b45a;
--warn-bg:#4d3b14;--info:#93a4ff}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);overflow-wrap:break-word;
font:400 clamp(17px,1rem + .3vw,20px)/1.75 var(--serif);padding:0 16px 3rem;
padding:0 max(16px,env(safe-area-inset-right)) 3rem max(16px,env(safe-area-inset-left))}
header,main,nav,footer{max-width:40rem;margin:0 auto}
header{padding:2.5rem 0 1rem;font-family:var(--sans)}
h1{font:700 1.6em/1.25 var(--serif);margin:0 0 .4rem;letter-spacing:-.01em}
h1:lang(ja){letter-spacing:0}
.meta,.hint,.legend{color:var(--muted);font-size:.8em;margin:.2rem 0}
.legend .key{color:var(--fg);margin-right:.9em;padding:0 .2em;display:inline-block}
:lang(ja){font-family:var(--ja);line-break:strict}
.opt{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}
.toggles{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0 0}
.toggles label{font:500 .78em/1.2 var(--sans);border:1px solid var(--line);border-radius:999px;
padding:.4em 1.1em;cursor:pointer;user-select:none;background:var(--card);min-height:44px;
display:inline-flex;align-items:center}
#opt-orig:checked~header label[for=opt-orig],#opt-sbs:checked~header label[for=opt-sbs],
#th-auto:checked~header label[for=th-auto],#th-light:checked~header label[for=th-light],
#th-dark:checked~header label[for=th-dark]{
background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}
#opt-orig:focus-visible~header label[for=opt-orig],
#opt-sbs:focus-visible~header label[for=opt-sbs],
#th-auto:focus-visible~header label[for=th-auto],
#th-light:focus-visible~header label[for=th-light],
#th-dark:focus-visible~header label[for=th-dark]{outline:2px solid var(--accent);outline-offset:2px}
label[for=opt-sbs],#opt-sbs{display:none}
nav.toc{font-family:var(--sans);font-size:.85em;margin-bottom:1.5rem}
nav.toc summary{cursor:pointer;color:var(--muted);min-height:44px;display:flex;
align-items:center;gap:.4em}
nav.toc summary::before{content:"\\25B8";font-size:.8em}
nav.toc details[open] summary::before{content:"\\25BE"}
nav.toc summary::-webkit-details-marker{display:none}
nav.toc ol{margin:0 0 .5rem;padding-left:1.4rem}
nav.toc a{display:flex;align-items:center;min-height:44px;line-height:1.3}
a{color:var(--accent)}
a:focus-visible,nav.toc summary:focus-visible{outline:2px solid var(--accent);
outline-offset:2px;border-radius:4px}
main{padding-top:.5rem}
details.p{margin:0 0 1.05em calc(-.6em - 3px);border-left:3px solid transparent;
transition:border-color .15s}
details.p>summary{display:block;list-style:none;cursor:pointer;padding:.15em .6em;
border-radius:6px;overflow-wrap:anywhere}
details.p>summary::-webkit-details-marker{display:none}
details.p>summary:hover{background:var(--card)}
details.p>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
details.p[open]{border-left-color:var(--accent)}
details.hd{margin-top:1.6em}
.hd .tr{font:700 1.25em/1.4 var(--serif);margin:0 0 .2em;display:block}
.orig{display:none;color:var(--muted);font-size:.95em;margin-top:.35em;padding-top:.35em;
border-top:1px dashed var(--line)}
details.p[open] .orig,#opt-orig:checked~main .orig{display:block}
ruby{ruby-align:center}rt{font-size:.55em;color:var(--muted)}
.ts{display:block;font:500 .7em/1.4 var(--sans);color:var(--muted);margin-bottom:.1em;
font-variant-numeric:tabular-nums}
.failed,.k-failed{background:var(--warn-bg);border-bottom:2px solid var(--warn);border-radius:3px;
-webkit-print-color-adjust:exact;print-color-adjust:exact}
.failed::before,.k-failed::before{content:"\\26A0\\FE0E\\00A0";color:var(--warn);
font-family:var(--sans)}
.presub,.k-presub{text-decoration:underline dotted var(--info) 2px;text-underline-offset:.25em}
.partial,.k-partial{text-decoration:underline wavy var(--warn) 1.5px;text-underline-offset:.25em}
.gloss{color:var(--muted);font-style:italic}
.page-mark{font:600 .75em/1 var(--sans);color:var(--muted);text-transform:uppercase;
letter-spacing:.08em;margin:2.2em 0 1em;display:flex;align-items:center;gap:.75em}
.page-mark::after{content:"";flex:1;border-top:1px solid var(--line)}
footer{font-family:var(--sans);font-size:.85em;margin-top:3rem;border-top:1px solid var(--line)}
footer h2{font:700 1.15em/1.3 var(--sans);margin:2rem 0 .8rem}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:.5em .6em;border-bottom:1px solid var(--line);vertical-align:top}
td{overflow-wrap:anywhere}td:last-child,th{white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:.85em}
td:first-child{font-size:1.1em}
.badge{display:inline-block;font-size:.72em;padding:.1em .5em;border-radius:999px;
background:var(--warn-bg);color:var(--fg);margin-left:.3em;white-space:nowrap}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(7.5rem,1fr));gap:.6rem}
.tile{background:var(--card);border-radius:10px;padding:.7em .8em}
.tile b{display:block;font-size:1.5em;line-height:1.2;font-variant-numeric:tabular-nums}
.tile span{color:var(--muted);font-size:.85em}
.tile.bad b{color:var(--warn)}
dl.kv{display:grid;grid-template-columns:auto 1fr;gap:.3em 1em;margin:1rem 0}
dl.kv dt{color:var(--muted)}dl.kv dd{margin:0;min-width:0}
.credit{color:var(--muted)}
@media (max-width:30rem){th,td{padding:.45em .35em}td:first-child{font-size:1em}
dl.kv{grid-template-columns:1fr;gap:0}dl.kv dd{margin-bottom:.5em}}
@media (min-width:60rem){label[for=opt-sbs]{display:inline-flex}#opt-sbs{display:block}
#opt-sbs:checked~header,#opt-sbs:checked~main,#opt-sbs:checked~nav,
#opt-sbs:checked~footer{max-width:72rem}
#opt-sbs:checked~main details.p>summary{display:grid;grid-template-columns:1fr 1fr;gap:2.5rem}
#opt-sbs:checked~main details.p>summary>*{min-width:0}
#opt-sbs:checked~main .orig{display:block;margin:0;padding:0;border:0}}
@media print{:root,:root:has(#th-dark:checked){color-scheme:light;--bg:#fff;--fg:#000;
--muted:#555;--line:#767676;--card:#f3f3f3;--accent:#1a3fb0;--accent-fg:#fff;
--warn:#7a4d00;--warn-bg:#fff1c2;--info:#1a3fb0}
body{font-size:11pt;padding:0}
.toggles,.hint,nav.toc{display:none}
header,main,nav,footer{max-width:none}
details.p .orig{display:block}
details.p{border-left:0;margin-left:0;break-inside:avoid}
details.p>summary{padding:0}
.scroll{overflow:visible}
a{color:inherit;text-decoration:none}
.tile{border:1px solid var(--line)}}
"""


def render_html(result: TranslatedDocument) -> str:
    """Bangun halaman HTML bilingual mandiri dari hasil terjemahan.

    Bentuk nama di tabel glosarium diambil dari ``result.stats["rendered"]``
    (``{tulisan: bentuk_akhir}``) bila pipeline menyediakannya, lalu dari
    ``render_id``/``render_en`` dan ``romaji`` entri.

    Args:
        result: Hasil pipeline.

    Returns:
        Dokumen HTML lengkap sebagai string.
    """
    ui = UI.get(result.target_lang, UI["en"])
    title = result.document.title or "jptrans"
    ruby = RubyIndex.from_result(result)
    glosses = GlossMarker.from_result(result)
    body = [
        '<input type="checkbox" id="opt-orig" class="opt">',
        '<input type="checkbox" id="opt-sbs" class="opt">',
        '<input type="radio" name="theme" id="th-auto" class="opt" checked>',
        '<input type="radio" name="theme" id="th-light" class="opt">',
        '<input type="radio" name="theme" id="th-dark" class="opt">',
        _header(result, title, ui),
        _toc(result.paragraphs, ui),
        _main(result.paragraphs, ruby, glosses, ui,
              _untagged if result.document.fmt in TAG_FORMATS else _as_is),
        _footer(result, ui),
    ]
    logger.debug("html: %d paragraf", len(result.paragraphs))
    return (
        f'<!DOCTYPE html>\n<html lang="{_esc(result.target_lang)}">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f'<meta name="generator" content="jptrans {_esc(__version__)}">\n'
        f"<title>{_esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        + "\n".join(part for part in body if part)
        + "\n</body>\n</html>\n"
    )


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _header(result: TranslatedDocument, title: str, ui: dict) -> str:
    names = ui["lang_names"]
    sentence_count = sum(len(p.sentences) for p in result.paragraphs)
    meta = (
        f"{names.get(result.source_lang, result.source_lang)} → "
        f"{names.get(result.target_lang, result.target_lang)} · "
        f"{len(result.paragraphs)} {ui['paragraphs']} · {sentence_count} {ui['sentences']}"
    )
    return (
        f"<header>\n<h1{_lang_ja(title)}>{_esc(title)}</h1>\n"
        f'<p class="meta">{_esc(meta)}</p>\n<p class="hint">{_esc(ui["hint"])}</p>\n'
        + _legend(result.paragraphs, ui)
        + '<div class="toggles">'
        f'<label for="opt-orig">{_esc(ui["show_all"])}</label>'
        f'<label for="opt-sbs">{_esc(ui["side_by_side"])}</label>'
        f'<label for="th-auto">{_esc(ui["th_auto"])}</label>'
        f'<label for="th-light">{_esc(ui["th_light"])}</label>'
        f'<label for="th-dark">{_esc(ui["th_dark"])}</label>'
        "</div>\n</header>"
    )


def _lang_ja(text: str) -> str:
    """Atribut ``lang="ja"`` bila teks memuat huruf Jepang (judul, nilai statistik).

    Tanpa atribut ini browser memilih glif CJK menurut bahasa halaman (``id``/``en``),
    sehingga kanji bisa tampil dengan bentuk Tionghoa dan fon Mincho tidak dipakai.
    """
    return ' lang="ja"' if contains_japanese(text) else ""


def _legend(paragraphs: list[TranslatedParagraph], ui: dict) -> str:
    """Legenda penanda status, hanya untuk status yang benar-benar ada di dokumen."""
    present = count_statuses(paragraphs)
    keys = [
        f'<span class="key k-{status}" title="{_esc(ui[status + "_title"])}">'
        f'{_esc(ui["status"][status])}</span>'
        for status in MARKED_STATUSES if present.get(status)
    ]
    if not keys:
        return ""
    return f'<p class="legend">{_esc(ui["legend"])} {"".join(keys)}</p>\n'


def _toc(paragraphs: list[TranslatedParagraph], ui: dict) -> str:
    links = [
        f'<li><a href="#p{number}">{_esc(paragraph_text(p))}</a></li>'
        for number, p in enumerate(paragraphs, start=1) if p.source.kind == "heading"
    ]
    if len(links) < 2:
        return ""
    return (
        f'<nav class="toc"><details><summary>{_esc(ui["toc"])}</summary>'
        f'<ol>{"".join(links)}</ol></details></nav>'
    )


def _as_is(text: str) -> str:
    """Teks apa adanya (format selain SRT: ``<i>`` di teks adalah isi, bukan tag)."""
    return text


def _untagged(text: str) -> str:
    """Teks tanpa tag format SRT dan tanpa spasi tepi yang ditinggalkannya."""
    return strip_format_tags(text).strip()


def _main(paragraphs: list[TranslatedParagraph], ruby: RubyIndex, glosses: GlossMarker,
          ui: dict, clean: Callable[[str], str] = _as_is) -> str:
    """Isi ``<main>``: semua paragraf, dengan penanda halaman bila nomor halaman berganti.

    ``clean`` membersihkan teks sumber sebelum ditampilkan (``_untagged`` untuk subtitle).
    """
    parts = ["<main>"]
    current_page = None
    for number, paragraph in enumerate(paragraphs, start=1):
        page = paragraph.source.meta.get("page")
        if page is not None and page != current_page:
            parts.append(f'<p class="page-mark">{_esc(ui["page"])} {_esc(page)}</p>')
            current_page = page
        parts.append(_paragraph(number, paragraph, ruby, glosses, ui, clean))
    parts.append("</main>")
    return "\n".join(parts)


def _paragraph(number: int, paragraph: TranslatedParagraph, ruby: RubyIndex,
               glosses: GlossMarker, ui: dict, clean: Callable[[str], str] = _as_is) -> str:
    """Satu paragraf sebagai ``<details>``: terjemahan di ``summary``, teks asli tersembunyi.

    Cue dua pembicara (``is_dialogue``) menampilkan tiap baris asli di baris sendiri.
    """
    source = paragraph.source
    heading = source.kind == "heading"
    translation = _timestamp(source) + _sentences_html(paragraph, glosses, ui, clean)
    role_attr = ' role="heading" aria-level="2"' if heading else ""
    css = "p hd" if heading else "p"
    if paragraph.is_dialogue:
        # Cue dua pembicara: tiap baris asli tetap baris sendiri.
        original = "<br>".join(ruby.markup(clean(line)) for line in source.text.split("\n"))
    else:
        original = ruby.markup(clean(source.text))
    return (
        f'<details class="{css}" id="p{number}"><summary>'
        f'<span class="tr"{role_attr}>{translation}</span>'
        f'<span class="orig" lang="ja">{original}</span>'
        "</summary></details>"
    )


def _timestamp(source: Paragraph) -> str:
    start = source.meta.get("start")
    if not isinstance(start, str):
        return ""
    return f'<span class="ts">{_esc(start.split(",")[0])}</span>'


def _sentences_html(paragraph: TranslatedParagraph, glosses: GlossMarker, ui: dict,
                    clean: Callable[[str], str] = _as_is) -> str:
    """Terjemahan paragraf; cue dua pembicara menjadi satu baris ``- …`` per giliran.

    ``clean`` membuang tag format SRT; kalimat yang isinya hanya tag tidak ditampilkan.
    """
    groups = paragraph.turn_sentences()
    if not groups:
        return _esc(clean(paragraph.source.text))
    lines = [" ".join(_sentence_html(sentence, glosses, ui, clean) for sentence in group
                      if clean(sentence.target or sentence.source))
             for group in groups]
    if paragraph.is_dialogue:
        return "<br>".join(_esc(DIALOGUE_DASH) + line for line in lines)
    return " ".join(lines)


def _sentence_html(sentence: SentencePair, glosses: GlossMarker, ui: dict,
                   clean: Callable[[str], str] = _as_is) -> str:
    """Satu kalimat terjemahan: gloss ditandai, status bermasalah diberi penanda.

    ``failed`` menampilkan teks asli (``lang="ja"``); ``presub`` dan ``partial`` tetap
    terjemahan tetapi perlu diperiksa, jadi diberi garis bawah dan ``title`` penjelas.
    """
    # Target kosong hanya sampai ke sini untuk giliran cue dua pembicara; sumbernya ditampilkan.
    if sentence.status == STATUS_FAILED:
        text = _esc(clean(sentence.target or sentence.source))
        return (f'<span class="failed" lang="ja" title="{_esc(ui["failed_title"])}">'
                f"{text}</span>")
    text = glosses.markup(clean(sentence.target or sentence.source))
    if sentence.status in (STATUS_PRESUB, STATUS_PARTIAL):
        title = ui[sentence.status + "_title"]
        text = f'<span class="{sentence.status}" title="{_esc(title)}">{text}</span>'
    return text


class GlossMarker:
    """Penanda gloss kemunculan pertama: ``(arti)`` dari glosarium dibungkus ``span.gloss``.

    Renderer gaya (``style.Renderer``) menyisipkan gloss sebagai teks biasa
    ``Nama (arti)``; di HTML gloss itu diberi warna redup agar terbaca sebagai
    keterangan, bukan bagian kalimat.

    Attributes:
        pattern: Regex semua bentuk ``(arti)`` untuk bahasa sasaran, atau ``None``.
    """

    def __init__(self, glosses: list[str]) -> None:
        alternatives = sorted({f"({gloss})" for gloss in glosses if gloss}, key=len,
                              reverse=True)
        self.pattern = re.compile("|".join(map(re.escape, alternatives))) if alternatives else None

    @classmethod
    def from_result(cls, result: TranslatedDocument) -> GlossMarker:
        """Ambil gloss bahasa sasaran dari glosarium hasil."""
        return cls([entry.gloss_for(result.target_lang) for entry in result.glossary])

    def markup(self, text: str) -> str:
        """Escape ``text`` dan bungkus setiap ``(arti)`` yang dikenal dengan ``span.gloss``."""
        if self.pattern is None:
            return _esc(text)
        parts, last = [], 0
        for match in self.pattern.finditer(text):
            parts.append(_esc(text[last:match.start()]))
            parts.append(f'<span class="gloss">{_esc(match.group(0))}</span>')
            last = match.end()
        parts.append(_esc(text[last:]))
        return "".join(parts)


class RubyIndex:
    """Penanda furigana: membungkus basis yang dikenal dengan ``<ruby>``.

    Attributes:
        readings: Peta ``{basis: bacaan}``.
    """

    def __init__(self, readings: dict[str, str]) -> None:
        self.readings = {base: reading for base, reading in readings.items()
                         if base and reading and base != reading}
        # Basis terpanjang dulu agar 田中太郎 tidak terpotong menjadi 田中 + 太郎.
        alternatives = sorted(self.readings, key=len, reverse=True)
        self.pattern = re.compile("|".join(map(re.escape, alternatives))) if alternatives else None

    @classmethod
    def from_result(cls, result: TranslatedDocument) -> RubyIndex:
        """Gabungkan ruby dokumen dengan bacaan glosarium (glosarium menang)."""
        readings = {base: reading for base, reading in result.document.ruby.items()
                    if len(base) >= MIN_RUBY_BASE}
        readings.update({entry.surface: entry.reading for entry in result.glossary
                         if entry.reading})
        return cls(readings)

    def markup(self, text: str) -> str:
        """Escape ``text`` dan sisipkan ``<ruby>`` (dengan ``<rp>`` sebagai cadangan)."""
        if self.pattern is None:
            return _esc(text)
        parts, last = [], 0
        for match in self.pattern.finditer(text):
            base = match.group(0)
            parts.append(_esc(text[last:match.start()]))
            parts.append(f"<ruby>{_esc(base)}<rp>(</rp><rt>{_esc(self.readings[base])}</rt>"
                         "<rp>)</rp></ruby>")
            last = match.end()
        parts.append(_esc(text[last:]))
        return "".join(parts)


def _footer(result: TranslatedDocument, ui: dict) -> str:
    return "\n".join(part for part in (
        "<footer>",
        _glossary_table(result, ui),
        _stats_section(result, ui),
        _credits(result, ui),
        "</footer>",
    ) if part)


def _glossary_table(result: TranslatedDocument, ui: dict) -> str:
    if not result.glossary:
        return ""
    rows = []
    for entry in sorted_glossary(result.glossary):
        badge = "" if entry.confirmed else f'<span class="badge">{_esc(ui["review"])}</span>'
        rows.append(
            f'<tr><td lang="ja">{_esc(entry.surface)}</td>'
            f'<td lang="ja">{_esc(entry.reading)}</td>'
            f"<td>{_esc(rendered_form(entry, result))}{badge}</td>"
            f'<td>{_esc(ui["kinds"].get(entry.kind, entry.kind))}</td></tr>'
        )
    head = "".join(f"<th>{_esc(ui[key])}</th>" for key in ("surface", "reading", "used", "kind"))
    return (
        f'<section id="glossary"><h2>{_esc(ui["glossary"])}</h2><div class="scroll">'
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        "</div></section>"
    )


def count_statuses(paragraphs: list[TranslatedParagraph]) -> Counter[str]:
    """Jumlah kalimat per status, dihitung langsung dari hasil."""
    return Counter(s.status for p in paragraphs for s in p.sentences)


def count_engines(paragraphs: list[TranslatedParagraph]) -> Counter[str]:
    """Jumlah kalimat per mesin (kalimat tanpa mesin, mis. ``plain``, tidak dihitung)."""
    return Counter(s.engine for p in paragraphs for s in p.sentences if s.engine)


def _stats_section(result: TranslatedDocument, ui: dict) -> str:
    statuses = count_statuses(result.paragraphs)
    tiles = [_tile(sum(statuses.values()), ui["total"])]
    for status in STATUS_ORDER:
        if statuses.get(status):
            tiles.append(_tile(statuses[status], ui["status"][status],
                               bad=status in (STATUS_FAILED, STATUS_PARTIAL)))
    rows = []
    engines = count_engines(result.paragraphs)
    if engines:
        rows.append((ui["engines"], ", ".join(f"{name} ({n})" for name, n in engines.items())))
    for key, value in result.stats.items():
        if key not in HIDDEN_STATS:
            rows.append((ui["stat_labels"].get(key, key.replace("_", " ")),
                         format_stat(value, ui)))
    details = "".join(f"<dt>{_esc(label)}</dt><dd{_lang_ja(value)}>{_esc(value)}</dd>"
                      for label, value in rows)
    note = ""
    if statuses.get(STATUS_FAILED):
        note = f'<p class="credit">{_esc(ui["failed_note"])}</p>'
    return (
        f'<section id="stats"><h2>{_esc(ui["stats"])}</h2>'
        f'<div class="tiles">{"".join(tiles)}</div>'
        + (f'<dl class="kv">{details}</dl>' if details else "")
        + note + "</section>"
    )


def _tile(number: int, label: str, *, bad: bool = False) -> str:
    css = "tile bad" if bad else "tile"
    return f'<div class="{css}"><b>{number}</b><span>{_esc(label)}</span></div>'


def format_stat(value: object, ui: dict) -> str:
    """Ubah satu nilai statistik menjadi teks singkat yang mudah dibaca."""
    if isinstance(value, bool):
        return ui["yes"] if value else ui["no"]
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return ", ".join(f"{key}: {format_stat(item, ui)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return ", ".join(format_stat(item, ui) for item in value)
    return str(value)


def _credits(result: TranslatedDocument, ui: dict) -> str:
    lines = []
    for name in count_engines(result.paragraphs):
        note = ui["engine_notes"].get(name)
        label = ENGINE_NAMES.get(name, name)
        lines.append(f"{label} ({note})" if note else label)
    listing = "".join(f"<li>{_esc(line)}</li>" for line in lines)
    return (
        f'<section id="credits"><h2>{_esc(ui["credits"])}</h2>'
        + (f"<ul>{listing}</ul>" if listing else "")
        + f'<p class="credit">{_esc(ui["disclaimer"])}</p>'
        f'<p class="credit">{_esc(ui["made_by"])} {_esc(__version__)}</p></section>'
    )
''')

MODUL['jptrans.writers.subtitle'] = (
    False,
r'''"""Penulis subtitle SRT, WebVTT (``.vtt``), dan ASS/SSA (``.ass``) bertiming asli.

Baris panjang dipotong pada spasi di luar tag format (``<i>``, ``<font ...>``,
``{\\an8}``) berdasarkan panjang teks tampak tanpa merusak atribut tag.
"""

from __future__ import annotations

import logging
import re

from ..errors import InputError
from ..models import TranslatedDocument, TranslatedParagraph, strip_format_tags
from ..readers.subtitle import SUBTITLE_FORMATS

logger = logging.getLogger(__name__)

MAX_LINE_CHARS = 42
_INLINE_TAG_SPAN_RE = re.compile(r"<[^<>\n]*>|\{\\[^{}\n]*\}")

ASS_DEFAULT_HEADER = """\
[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, \
BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,22,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,\
0,0,0,0,100,100,0,0,1,2,1,2,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def wrap_cue(text: str, width: int = MAX_LINE_CHARS) -> str:
    """Pecah teks cue satu baris menjadi dua baris seimbang di luar tag format."""
    if "\n" in text:
        return text
    visible = strip_format_tags(text)
    if len(visible) <= width or " " not in visible:
        return text
    tag_ranges = [m.span() for m in _INLINE_TAG_SPAN_RE.finditer(text)]
    candidate_spaces: list[tuple[int, int]] = []
    vis_pos = 0
    idx = 0
    tag_idx = 0
    while idx < len(text):
        while tag_idx < len(tag_ranges) and idx >= tag_ranges[tag_idx][1]:
            tag_idx += 1
        if tag_idx < len(tag_ranges) and tag_ranges[tag_idx][0] <= idx < tag_ranges[tag_idx][1]:
            idx = tag_ranges[tag_idx][1]
            continue
        if text[idx] == " ":
            candidate_spaces.append((idx, vis_pos))
        vis_pos += 1
        idx += 1
    if not candidate_spaces:
        return text
    middle = len(visible) / 2.0
    cut, _ = min(candidate_spaces, key=lambda item: abs(item[1] - middle))
    return f"{text[:cut]}\n{text[cut + 1:]}"


def _require_subtitle_source(result: TranslatedDocument, target_fmt: str) -> None:
    if result.document.fmt not in SUBTITLE_FORMATS:
        raise InputError(
            f"keluaran {target_fmt.upper()} butuh masukan ber-timing "
            f"(srt/vtt/ass; masukan ini {result.document.fmt}); "
            "pilih format html, txt, md, atau json"
        )


def _require_timing(number: int, paragraph: TranslatedParagraph) -> tuple[str, str]:
    meta = paragraph.source.meta
    start = str(meta.get("start") or "")
    end = str(meta.get("end") or "")
    if not start or not end:
        raise InputError(f"blok subtitle ke-{number} tidak punya timing")
    return start, end


def _srt_cue(number: int, paragraph: TranslatedParagraph) -> str:
    start, end = _require_timing(number, paragraph)
    text = wrap_cue(paragraph.target or paragraph.source.text)
    return f"{number}\n{start} --> {end}\n{text}\n"


def render_srt(result: TranslatedDocument) -> str:
    """Hasil terjemahan sebagai berkas SRT; nomor blok diurutkan dari 1."""
    _require_subtitle_source(result, "srt")
    cues = [
        _srt_cue(number, p)
        for number, p in enumerate(result.paragraphs, start=1)
    ]
    logger.debug("srt: %d blok", len(cues))
    return "\n".join(cues)


def render_vtt(result: TranslatedDocument) -> str:
    """Hasil terjemahan sebagai berkas WebVTT (``WEBVTT``)."""
    _require_subtitle_source(result, "vtt")
    cues: list[str] = ["WEBVTT\n"]
    for number, paragraph in enumerate(result.paragraphs, start=1):
        start, end = _require_timing(number, paragraph)
        vtt_start = start.replace(",", ".")
        vtt_end = end.replace(",", ".")
        settings = paragraph.source.meta.get("vtt_settings", "")
        tail = f" {settings}" if settings else ""
        text = wrap_cue(paragraph.target or paragraph.source.text)
        cues.append(f"{number}\n{vtt_start} --> {vtt_end}{tail}\n{text}\n")
    logger.debug("vtt: %d cue", len(cues) - 1)
    return "\n".join(cues)


def _srt_to_ass_time(stamp: str) -> str:
    hms, _, ms = stamp.replace(".", ",").partition(",")
    parts = hms.split(":")
    hours = int(parts[0]) if len(parts) == 3 else 0
    minutes = parts[-2] if len(parts) >= 2 else "00"
    seconds = parts[-1]
    centis = int((ms or "000")[:3].ljust(3, "0")) // 10
    return f"{hours}:{minutes}:{seconds}.{centis:02d}"


def render_ass(result: TranslatedDocument) -> str:
    """Hasil terjemahan sebagai berkas ASS (SubStation Alpha v4+)."""
    _require_subtitle_source(result, "ass")
    lines = [ASS_DEFAULT_HEADER.rstrip("\n")]
    for number, paragraph in enumerate(result.paragraphs, start=1):
        start, end = _require_timing(number, paragraph)
        ass_start = _srt_to_ass_time(start)
        ass_end = _srt_to_ass_time(end)
        style = str(paragraph.source.meta.get("ass_style") or "Default").replace(",", " ")
        actor = str(paragraph.source.meta.get("ass_actor") or "").replace(",", " ")
        wrapped = wrap_cue(strip_format_tags(paragraph.target or paragraph.source.text))
        body = wrapped.replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{ass_start},{ass_end},{style},{actor},0,0,0,,{body}"
        )
    logger.debug("ass: %d baris dialog", len(lines) - 1)
    return "\n".join(lines) + "\n"
''')

MODUL['jptrans.writers.text'] = (
    False,
r'''"""Penulis teks: TXT polos, Markdown, dan JSON lengkap.

- ``txt``: satu paragraf terjemahan per blok; ``bilingual=True`` menaruh baris
  Jepang asli tepat di atas terjemahannya (cocok untuk belajar).
- ``md``: judul ``#``, bab ``##``, paragraf, lalu tabel glosarium.
- ``json``: seluruh hasil (kalimat, status, mesin, glosarium, statistik) agar
  bisa diproses ulang oleh skrip lain.

Cue subtitle dua pembicara tampil satu baris per pembicara (``- Ya.`` lalu
``- Tidak.``) di ketiga format: baris baru di TXT dan JSON, jeda baris keras
``\\`` di Markdown.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict

from ..models import ENTITY_KINDS, GlossaryEntry, TranslatedDocument, TranslatedParagraph

logger = logging.getLogger(__name__)

JSON_FORMAT = "jptrans-result"
JSON_VERSION = 1
_MD_SPECIAL_RE = re.compile(r"([\\`*_\[\]<>|])")
# Penanda blok di awal baris: judul/kutipan/daftar, dan daftar bernomor "1." / "1)".
_MD_LEADING_MARK_RE = re.compile(r"^([#>+-])")
_MD_ORDERED_RE = re.compile(r"^(\d+)([.)])")
MD_HARD_BREAK = "\\\n"
"""Jeda baris keras CommonMark (garis miring terbalik di akhir baris)."""
_MD_GLOSSARY_HEAD = {
    "id": ("Glosarium", "| Tulisan | Bacaan | Dipakai | Jenis |"),
    "en": ("Glossary", "| Written | Reading | Rendered as | Type |"),
}


def paragraph_text(paragraph: TranslatedParagraph) -> str:
    """Teks terjemahan paragraf; teks asli bila tidak ada terjemahan sama sekali."""
    return paragraph.target or paragraph.source.text


def sorted_glossary(entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
    """Urutkan entri menurut jenis (orang, tempat, ...) lalu bacaan."""
    order = {kind: pos for pos, kind in enumerate(ENTITY_KINDS)}
    return sorted(entries, key=lambda e: (order.get(e.kind, len(order)), e.reading or e.surface))


def rendered_form(entry: GlossaryEntry, result: TranslatedDocument) -> str:
    """Bentuk nama yang dipakai di terjemahan, untuk tabel glosarium.

    Prioritas: ``result.stats["rendered"][surface]`` (diisi pipeline dari
    ``style.Renderer``), lalu ``render_id``/``render_en``, lalu ``romaji``.
    """
    rendered = result.stats.get("rendered")
    if isinstance(rendered, dict) and rendered.get(entry.surface):
        return str(rendered[entry.surface])
    return entry.render_for(result.target_lang) or entry.romaji or "-"


def render_txt(result: TranslatedDocument, *, bilingual: bool = False) -> str:
    """Terjemahan sebagai teks polos, paragraf dipisah satu baris kosong.

    Args:
        result: Hasil pipeline.
        bilingual: Bila ``True``, tiap paragraf diawali baris Jepang aslinya.
    """
    blocks = []
    for paragraph in result.paragraphs:
        text = paragraph_text(paragraph)
        blocks.append(f"{paragraph.source.text}\n{text}" if bilingual else text)
    return "\n\n".join(blocks) + "\n"


def md_escape(text: str) -> str:
    """Escape karakter Markdown agar teks tampil apa adanya."""
    escaped = _MD_SPECIAL_RE.sub(r"\\\1", text.replace("\n", " "))
    escaped = _MD_LEADING_MARK_RE.sub(r"\\\1", escaped)
    return _MD_ORDERED_RE.sub(r"\1\\\2", escaped)


def render_md(result: TranslatedDocument) -> str:
    """Terjemahan sebagai Markdown: judul, paragraf (bab jadi ``##``), glosarium."""
    lines = [f"# {md_escape(result.document.title)}", ""]
    for paragraph in result.paragraphs:
        text = _md_paragraph(paragraph)
        lines += [f"## {text}" if paragraph.source.kind == "heading" else text, ""]
    if result.glossary:
        heading, columns = _MD_GLOSSARY_HEAD.get(result.target_lang, _MD_GLOSSARY_HEAD["en"])
        lines += [f"## {heading}", "", columns, "| --- | --- | --- | --- |"]
        for entry in sorted_glossary(result.glossary):
            cells = (entry.surface, entry.reading, rendered_form(entry, result), entry.kind)
            lines.append("| " + " | ".join(md_escape(cell) for cell in cells) + " |")
        lines.append("")
    return "\n".join(lines)


def _md_paragraph(paragraph: TranslatedParagraph) -> str:
    """Satu paragraf Markdown; giliran cue dua pembicara dipisah jeda baris keras."""
    if not paragraph.is_dialogue:
        return md_escape(paragraph_text(paragraph))
    return MD_HARD_BREAK.join(md_escape(line) for line in paragraph.target.split("\n"))


def _paragraph_dict(paragraph: TranslatedParagraph) -> dict:
    """Bentuk JSON satu paragraf; ``turns`` hanya ada untuk cue dua pembicara."""
    data = {
        "kind": paragraph.source.kind,
        "meta": paragraph.source.meta,
        "source": paragraph.source.text,
        "target": paragraph.target,
        "sentences": [asdict(s) for s in paragraph.sentences],
    }
    if paragraph.is_dialogue:
        data["turns"] = paragraph.turns
    return data


def result_to_dict(result: TranslatedDocument) -> dict:
    """Bentuk dict lengkap yang aman untuk ``json.dumps``."""
    doc = result.document
    return {
        "format": JSON_FORMAT,
        "version": JSON_VERSION,
        "title": doc.title,
        "source_lang": result.source_lang,
        "target_lang": result.target_lang,
        "source_format": doc.fmt,
        "source_path": doc.source_path,
        "paragraphs": [_paragraph_dict(p) for p in result.paragraphs],
        "glossary": [asdict(entry) for entry in result.glossary],
        "ruby": doc.ruby,
        "stats": result.stats,
    }


def render_json(result: TranslatedDocument) -> str:
    """Seluruh hasil sebagai JSON UTF-8 (huruf Jepang tidak di-escape)."""
    logger.debug("json: %d paragraf", len(result.paragraphs))
    # default=str menjaga agar nilai statistik yang tak terduga (Path, set) tidak
    # menggagalkan penulisan seluruh berkas.
    return json.dumps(result_to_dict(result), ensure_ascii=False, indent=2, default=str) + "\n"
''')

# Daftar berkas data kamus JSON paket jptrans.

DATA['data/foreign_names.json'] = r'''{
 "given": {
  "Aaron": [
   "アーロン"
  ],
  "Adam": [
   "アダム"
  ],
  "Adele": [
   "アデル"
  ],
  "Adrian": [
   "エイドリアン",
   "アドリアン"
  ],
  "Agatha": [
   "アガサ"
  ],
  "Agnes": [
   "アグネス"
  ],
  "Alan": [
   "アラン"
  ],
  "Albert": [
   "アルバート",
   "アルベルト"
  ],
  "Alessandro": [
   "アレッサンドロ"
  ],
  "Alex": [
   "アレックス"
  ],
  "Alexander": [
   "アレクサンダー",
   "アレキサンダー"
  ],
  "Alexandra": [
   "アレクサンドラ"
  ],
  "Alexei": [
   "アレクセイ"
  ],
  "Alfred": [
   "アルフレッド"
  ],
  "Alice": [
   "アリス"
  ],
  "Alicia": [
   "アリシア"
  ],
  "Alistair": [
   "アリステア"
  ],
  "Amelia": [
   "アメリア"
  ],
  "Amy": [
   "エイミー"
  ],
  "Anastasia": [
   "アナスタシア"
  ],
  "Andre": [
   "アンドレ"
  ],
  "Andrea": [
   "アンドレア"
  ],
  "Andrei": [
   "アンドレイ"
  ],
  "Andrew": [
   "アンドリュー"
  ],
  "Andromeda": [
   "アンドロメダ"
  ],
  "Angela": [
   "アンジェラ"
  ],
  "Angelica": [
   "アンジェリカ"
  ],
  "Anna": [
   "アンナ"
  ],
  "Anne": [
   "アンネ"
  ],
  "Annie": [
   "アニー"
  ],
  "Anthony": [
   "アンソニー"
  ],
  "Antoine": [
   "アントワーヌ"
  ],
  "Antonio": [
   "アントニオ"
  ],
  "Anya": [
   "アーニャ"
  ],
  "Aphrodite": [
   "アフロディーテ"
  ],
  "Apollo": [
   "アポロ"
  ],
  "Ares": [
   "アレス"
  ],
  "Ariel": [
   "アリエル"
  ],
  "Arnold": [
   "アーノルド"
  ],
  "Artemis": [
   "アルテミス"
  ],
  "Arthur": [
   "アーサー",
   "アルトゥール"
  ],
  "Ashley": [
   "アシュリー"
  ],
  "Asmodeus": [
   "アスモデウス"
  ],
  "Astrid": [
   "アストリッド"
  ],
  "Asuna": [
   "アスナ"
  ],
  "Athena": [
   "アテナ",
   "アテーナー"
  ],
  "Audrey": [
   "オードリー"
  ],
  "Augustus": [
   "アウグストゥス"
  ],
  "Azrael": [
   "アズラエル"
  ],
  "Baldur": [
   "バルドル"
  ],
  "Barbara": [
   "バーバラ"
  ],
  "Beatrice": [
   "ベアトリス",
   "ベアトリーチェ",
   "ベアトリクス"
  ],
  "Beelzebub": [
   "ベルゼブブ"
  ],
  "Belial": [
   "ベリアル"
  ],
  "Bella": [
   "ベラ"
  ],
  "Benedict": [
   "ベネディクト"
  ],
  "Benjamin": [
   "ベンジャミン"
  ],
  "Bernard": [
   "バーナード",
   "ベルナール"
  ],
  "Bianca": [
   "ビアンカ"
  ],
  "Boris": [
   "ボリス"
  ],
  "Brian": [
   "ブライアン"
  ],
  "Bridget": [
   "ブリジット"
  ],
  "Brunhilde": [
   "ブリュンヒルデ",
   "ブリュンヒルド"
  ],
  "Brutus": [
   "ブルータス"
  ],
  "Caesar": [
   "シーザー",
   "カエサル"
  ],
  "Camilla": [
   "カミラ"
  ],
  "Camille": [
   "カミーユ"
  ],
  "Carlos": [
   "カルロス"
  ],
  "Carmen": [
   "カルメン"
  ],
  "Caroline": [
   "キャロライン"
  ],
  "Cassandra": [
   "カサンドラ"
  ],
  "Cassiopeia": [
   "カシオペア"
  ],
  "Catherine": [
   "キャサリン",
   "カトリーヌ"
  ],
  "Cecilia": [
   "セシリア"
  ],
  "Cedric": [
   "セドリック"
  ],
  "Celestia": [
   "セレスティア"
  ],
  "Celine": [
   "セリーヌ"
  ],
  "Charles": [
   "チャールズ",
   "シャルル"
  ],
  "Charlotte": [
   "シャーロット",
   "シャルロット"
  ],
  "Chiara": [
   "キアラ"
  ],
  "Chloe": [
   "クロエ"
  ],
  "Chris": [
   "クリス"
  ],
  "Christian": [
   "クリスチャン",
   "クリスティアン"
  ],
  "Christina": [
   "クリスティーナ",
   "クリスティナ"
  ],
  "Christopher": [
   "クリストファー"
  ],
  "Cinderella": [
   "シンデレラ"
  ],
  "Claire": [
   "クレア",
   "クレール"
  ],
  "Clara": [
   "クララ"
  ],
  "Claude": [
   "クロード"
  ],
  "Claudia": [
   "クラウディア"
  ],
  "Cleopatra": [
   "クレオパトラ"
  ],
  "Colette": [
   "コレット"
  ],
  "Conrad": [
   "コンラッド",
   "コンラート"
  ],
  "Constance": [
   "コンスタンス"
  ],
  "Cordelia": [
   "コーデリア"
  ],
  "Cornelius": [
   "コーネリアス"
  ],
  "Cynthia": [
   "シンシア"
  ],
  "Cyril": [
   "シリル"
  ],
  "Daisy": [
   "デイジー"
  ],
  "Damien": [
   "ダミアン"
  ],
  "Daniel": [
   "ダニエル"
  ],
  "Dante": [
   "ダンテ"
  ],
  "Daphne": [
   "ダフネ"
  ],
  "Darius": [
   "ダリウス"
  ],
  "David": [
   "デイビッド",
   "デヴィッド",
   "ダビデ"
  ],
  "Dennis": [
   "デニス"
  ],
  "Diana": [
   "ダイアナ",
   "ディアナ"
  ],
  "Diego": [
   "ディエゴ"
  ],
  "Dietrich": [
   "ディートリッヒ",
   "ディートリヒ"
  ],
  "Dmitri": [
   "ドミトリー"
  ],
  "Dolores": [
   "ドロレス"
  ],
  "Dominic": [
   "ドミニク"
  ],
  "Donald": [
   "ドナルド"
  ],
  "Dorothy": [
   "ドロシー"
  ],
  "Douglas": [
   "ダグラス"
  ],
  "Duncan": [
   "ダンカン"
  ],
  "Edgar": [
   "エドガー"
  ],
  "Edith": [
   "エディス"
  ],
  "Edmund": [
   "エドマンド"
  ],
  "Edward": [
   "エドワード"
  ],
  "Edwin": [
   "エドウィン"
  ],
  "Eileen": [
   "アイリーン"
  ],
  "Elaine": [
   "エレイン"
  ],
  "Eleanor": [
   "エレノア"
  ],
  "Elena": [
   "エレナ"
  ],
  "Elias": [
   "エリアス"
  ],
  "Elijah": [
   "イライジャ"
  ],
  "Elise": [
   "エリーゼ"
  ],
  "Eliza": [
   "エリザ"
  ],
  "Elizabeth": [
   "エリザベス",
   "エリザベート"
  ],
  "Ellie": [
   "エリー"
  ],
  "Elliot": [
   "エリオット"
  ],
  "Elsa": [
   "エルザ",
   "エルサ"
  ],
  "Emil": [
   "エミール"
  ],
  "Emilia": [
   "エミリア"
  ],
  "Emily": [
   "エミリー"
  ],
  "Enzo": [
   "エンツォ"
  ],
  "Eric": [
   "エリック"
  ],
  "Erika": [
   "エリカ"
  ],
  "Eris": [
   "エリス"
  ],
  "Ernest": [
   "アーネスト"
  ],
  "Erwin": [
   "エルヴィン",
   "エルビン"
  ],
  "Esther": [
   "エスター"
  ],
  "Etienne": [
   "エティエンヌ"
  ],
  "Eugene": [
   "ユージーン"
  ],
  "Eva": [
   "エヴァ",
   "エバ"
  ],
  "Evelyn": [
   "エヴリン",
   "エブリン"
  ],
  "Fabian": [
   "ファビアン"
  ],
  "Faust": [
   "ファウスト"
  ],
  "Felix": [
   "フェリックス"
  ],
  "Ferdinand": [
   "フェルディナント",
   "フェルディナンド"
  ],
  "Fern": [
   "フェルン"
  ],
  "Fernando": [
   "フェルナンド"
  ],
  "Fiona": [
   "フィオナ"
  ],
  "Flora": [
   "フローラ"
  ],
  "Florence": [
   "フローレンス"
  ],
  "Francesca": [
   "フランチェスカ"
  ],
  "Francis": [
   "フランシス"
  ],
  "Francisco": [
   "フランシスコ"
  ],
  "Francois": [
   "フランソワ"
  ],
  "Frank": [
   "フランク"
  ],
  "Franz": [
   "フランツ"
  ],
  "Frederick": [
   "フレデリック"
  ],
  "Freya": [
   "フレイヤ",
   "フレイア"
  ],
  "Frieda": [
   "フリーダ"
  ],
  "Friedrich": [
   "フリードリヒ",
   "フリードリッヒ"
  ],
  "Frieren": [
   "フリーレン"
  ],
  "Fyodor": [
   "フョードル"
  ],
  "Gabriel": [
   "ガブリエル"
  ],
  "Gabriella": [
   "ガブリエラ"
  ],
  "Galahad": [
   "ガラハッド"
  ],
  "Gareth": [
   "ガレス"
  ],
  "Gaston": [
   "ガストン"
  ],
  "Gawain": [
   "ガウェイン"
  ],
  "Geoffrey": [
   "ジェフリー"
  ],
  "George": [
   "ジョージ"
  ],
  "Gerald": [
   "ジェラルド"
  ],
  "Gertrude": [
   "ガートルード"
  ],
  "Gideon": [
   "ギデオン"
  ],
  "Gilbert": [
   "ギルバート",
   "ジルベール"
  ],
  "Giovanni": [
   "ジョヴァンニ",
   "ジョバンニ"
  ],
  "Giuseppe": [
   "ジュゼッペ"
  ],
  "Gloria": [
   "グロリア"
  ],
  "Gordon": [
   "ゴードン"
  ],
  "Gottfried": [
   "ゴットフリート"
  ],
  "Grace": [
   "グレース",
   "グレイス"
  ],
  "Gregory": [
   "グレゴリー"
  ],
  "Greta": [
   "グレタ"
  ],
  "Gretel": [
   "グレーテル"
  ],
  "Guinevere": [
   "グィネヴィア",
   "グィネビア"
  ],
  "Gunther": [
   "グンター"
  ],
  "Gustav": [
   "グスタフ"
  ],
  "Hades": [
   "ハデス"
  ],
  "Hannah": [
   "ハンナ"
  ],
  "Hans": [
   "ハンス"
  ],
  "Hansel": [
   "ヘンゼル"
  ],
  "Harold": [
   "ハロルド"
  ],
  "Harriet": [
   "ハリエット"
  ],
  "Harry": [
   "ハリー"
  ],
  "Hazel": [
   "ヘーゼル"
  ],
  "Hector": [
   "ヘクター",
   "ヘクトル"
  ],
  "Heidi": [
   "ハイジ"
  ],
  "Heinrich": [
   "ハインリヒ",
   "ハインリッヒ"
  ],
  "Heiter": [
   "ハイター"
  ],
  "Helen": [
   "ヘレン"
  ],
  "Helena": [
   "ヘレナ"
  ],
  "Henry": [
   "ヘンリー"
  ],
  "Hera": [
   "ヘラ"
  ],
  "Hercules": [
   "ヘラクレス"
  ],
  "Hermes": [
   "ヘルメス"
  ],
  "Hilda": [
   "ヒルダ"
  ],
  "Himmel": [
   "ヒンメル"
  ],
  "Holly": [
   "ホリー"
  ],
  "Howard": [
   "ハワード"
  ],
  "Hugo": [
   "ヒューゴ",
   "ユーゴ"
  ],
  "Ian": [
   "イアン"
  ],
  "Icarus": [
   "イカロス"
  ],
  "Ingrid": [
   "イングリッド"
  ],
  "Irene": [
   "イレーネ"
  ],
  "Irina": [
   "イリーナ"
  ],
  "Iris": [
   "アイリス"
  ],
  "Isaac": [
   "アイザック",
   "イサク"
  ],
  "Isabel": [
   "イザベル"
  ],
  "Isabella": [
   "イザベラ"
  ],
  "Isolde": [
   "イゾルデ"
  ],
  "Ivan": [
   "イワン",
   "イヴァン"
  ],
  "Jack": [
   "ジャック"
  ],
  "Jacob": [
   "ジェイコブ",
   "ヤコブ"
  ],
  "Jacqueline": [
   "ジャクリーン"
  ],
  "James": [
   "ジェームズ",
   "ジェームス",
   "ジェイムズ"
  ],
  "Jane": [
   "ジェーン"
  ],
  "Janet": [
   "ジャネット"
  ],
  "Jason": [
   "ジェイソン"
  ],
  "Jasper": [
   "ジャスパー"
  ],
  "Javier": [
   "ハビエル"
  ],
  "Jean": [
   "ジャン"
  ],
  "Jennifer": [
   "ジェニファー"
  ],
  "Jeremy": [
   "ジェレミー"
  ],
  "Jerome": [
   "ジェローム"
  ],
  "Jessica": [
   "ジェシカ"
  ],
  "Joan": [
   "ジョーン"
  ],
  "Joanna": [
   "ジョアンナ"
  ],
  "Johann": [
   "ヨハン"
  ],
  "John": [
   "ジョン"
  ],
  "Jonathan": [
   "ジョナサン"
  ],
  "Jose": [
   "ホセ"
  ],
  "Joseph": [
   "ジョセフ",
   "ヨーゼフ"
  ],
  "Josephine": [
   "ジョセフィーヌ",
   "ジョセフィン"
  ],
  "Joshua": [
   "ジョシュア"
  ],
  "Juan": [
   "フアン"
  ],
  "Judith": [
   "ジュディス"
  ],
  "Julia": [
   "ジュリア"
  ],
  "Julian": [
   "ジュリアン"
  ],
  "Juliet": [
   "ジュリエット"
  ],
  "Julius": [
   "ユリウス"
  ],
  "Justin": [
   "ジャスティン"
  ],
  "Katarina": [
   "カタリナ"
  ],
  "Kate": [
   "ケイト"
  ],
  "Keith": [
   "キース"
  ],
  "Kelly": [
   "ケリー"
  ],
  "Kenneth": [
   "ケネス"
  ],
  "Kevin": [
   "ケビン",
   "ケヴィン"
  ],
  "Kirito": [
   "キリト"
  ],
  "Klaus": [
   "クラウス"
  ],
  "Kurt": [
   "クルト"
  ],
  "Lancelot": [
   "ランスロット"
  ],
  "Lara": [
   "ララ"
  ],
  "Laura": [
   "ローラ"
  ],
  "Lawrence": [
   "ローレンス"
  ],
  "Leon": [
   "レオン"
  ],
  "Leonard": [
   "レナード"
  ],
  "Leonardo": [
   "レオナルド"
  ],
  "Liesel": [
   "リーゼル"
  ],
  "Lilia": [
   "リリア"
  ],
  "Lilith": [
   "リリス"
  ],
  "Lily": [
   "リリー"
  ],
  "Linda": [
   "リンダ"
  ],
  "Loki": [
   "ロキ"
  ],
  "Lorelei": [
   "ローレライ"
  ],
  "Lorenzo": [
   "ロレンツォ"
  ],
  "Lotte": [
   "ロッテ"
  ],
  "Louise": [
   "ルイーズ"
  ],
  "Lucas": [
   "ルーカス",
   "ルカス"
  ],
  "Lucia": [
   "ルチア",
   "ルシア"
  ],
  "Lucifer": [
   "ルシファー",
   "ルシフェル"
  ],
  "Lucius": [
   "ルキウス"
  ],
  "Lucy": [
   "ルーシー"
  ],
  "Ludmila": [
   "リュドミラ"
  ],
  "Ludwig": [
   "ルートヴィヒ",
   "ルードヴィッヒ",
   "ルートビッヒ"
  ],
  "Luke": [
   "ルーク"
  ],
  "Lydia": [
   "リディア"
  ],
  "Magnus": [
   "マグナス"
  ],
  "Mammon": [
   "マモン"
  ],
  "Manuel": [
   "マヌエル"
  ],
  "Marco": [
   "マルコ"
  ],
  "Marcus": [
   "マーカス"
  ],
  "Margaret": [
   "マーガレット"
  ],
  "Maria": [
   "マリア"
  ],
  "Marianne": [
   "マリアンヌ"
  ],
  "Marie": [
   "マリー"
  ],
  "Marilyn": [
   "マリリン"
  ],
  "Mario": [
   "マリオ"
  ],
  "Martha": [
   "マーサ"
  ],
  "Martin": [
   "マーティン",
   "マルティン"
  ],
  "Mary": [
   "メアリー",
   "メアリ"
  ],
  "Matilda": [
   "マチルダ"
  ],
  "Matteo": [
   "マッテオ"
  ],
  "Matthew": [
   "マシュー"
  ],
  "Matthias": [
   "マティアス"
  ],
  "Maurice": [
   "モーリス"
  ],
  "Maximilian": [
   "マクシミリアン",
   "マキシミリアン"
  ],
  "Medusa": [
   "メデューサ"
  ],
  "Megan": [
   "メーガン"
  ],
  "Melissa": [
   "メリッサ"
  ],
  "Mephisto": [
   "メフィスト"
  ],
  "Merlin": [
   "マーリン"
  ],
  "Metatron": [
   "メタトロン"
  ],
  "Mia": [
   "ミア"
  ],
  "Michael": [
   "マイケル",
   "ミカエル"
  ],
  "Michelle": [
   "ミシェル"
  ],
  "Miguel": [
   "ミゲル"
  ],
  "Mikhail": [
   "ミハイル"
  ],
  "Minerva": [
   "ミネルヴァ",
   "ミネルバ"
  ],
  "Miranda": [
   "ミランダ"
  ],
  "Molly": [
   "モリー"
  ],
  "Monica": [
   "モニカ"
  ],
  "Mordred": [
   "モードレッド"
  ],
  "Morgan": [
   "モーガン"
  ],
  "Morgana": [
   "モルガナ"
  ],
  "Nadia": [
   "ナディア"
  ],
  "Nancy": [
   "ナンシー"
  ],
  "Napoleon": [
   "ナポレオン"
  ],
  "Natalia": [
   "ナタリア"
  ],
  "Natalie": [
   "ナタリー"
  ],
  "Natasha": [
   "ナターシャ"
  ],
  "Nathan": [
   "ネイサン"
  ],
  "Nathaniel": [
   "ナサニエル"
  ],
  "Nero": [
   "ネロ"
  ],
  "Nicholas": [
   "ニコラス"
  ],
  "Nicolas": [
   "ニコラ"
  ],
  "Nicole": [
   "ニコル"
  ],
  "Nikolai": [
   "ニコライ"
  ],
  "Nina": [
   "ニーナ"
  ],
  "Nora": [
   "ノーラ"
  ],
  "Norman": [
   "ノーマン"
  ],
  "Oberon": [
   "オベロン"
  ],
  "Octavia": [
   "オクタヴィア",
   "オクタビア"
  ],
  "Odin": [
   "オーディン"
  ],
  "Olga": [
   "オルガ"
  ],
  "Oliver": [
   "オリバー",
   "オリヴァー"
  ],
  "Olivia": [
   "オリヴィア",
   "オリビア"
  ],
  "Ophelia": [
   "オフィーリア",
   "オフィリア"
  ],
  "Orion": [
   "オリオン"
  ],
  "Orpheus": [
   "オルフェウス"
  ],
  "Oscar": [
   "オスカー"
  ],
  "Oswald": [
   "オズワルド"
  ],
  "Otto": [
   "オットー"
  ],
  "Owen": [
   "オーウェン"
  ],
  "Pablo": [
   "パブロ"
  ],
  "Pamela": [
   "パメラ"
  ],
  "Pandora": [
   "パンドラ"
  ],
  "Paolo": [
   "パオロ"
  ],
  "Pascal": [
   "パスカル"
  ],
  "Patricia": [
   "パトリシア"
  ],
  "Patrick": [
   "パトリック"
  ],
  "Paul": [
   "ポール"
  ],
  "Paula": [
   "ポーラ"
  ],
  "Pavel": [
   "パーヴェル",
   "パーベル"
  ],
  "Pedro": [
   "ペドロ"
  ],
  "Penelope": [
   "ペネロペ"
  ],
  "Percival": [
   "パーシヴァル",
   "パーシバル"
  ],
  "Persephone": [
   "ペルセポネ"
  ],
  "Perseus": [
   "ペルセウス"
  ],
  "Peter": [
   "ピーター"
  ],
  "Philip": [
   "フィリップ"
  ],
  "Phoebe": [
   "フィービー"
  ],
  "Pierre": [
   "ピエール"
  ],
  "Poseidon": [
   "ポセイドン"
  ],
  "Priscilla": [
   "プリシラ"
  ],
  "Prometheus": [
   "プロメテウス"
  ],
  "Rachel": [
   "レイチェル"
  ],
  "Ralph": [
   "ラルフ"
  ],
  "Raphael": [
   "ラファエル"
  ],
  "Rapunzel": [
   "ラプンツェル"
  ],
  "Raymond": [
   "レイモンド"
  ],
  "Rebecca": [
   "レベッカ"
  ],
  "Regina": [
   "レジーナ"
  ],
  "Reinhard": [
   "ラインハルト"
  ],
  "Remus": [
   "レムス"
  ],
  "Remy": [
   "レミー"
  ],
  "Rene": [
   "ルネ"
  ],
  "Ricardo": [
   "リカルド"
  ],
  "Richard": [
   "リチャード"
  ],
  "Rimuru": [
   "リムル"
  ],
  "Rita": [
   "リタ"
  ],
  "Robert": [
   "ロバート"
  ],
  "Roberto": [
   "ロベルト"
  ],
  "Robin": [
   "ロビン"
  ],
  "Roger": [
   "ロジャー"
  ],
  "Roland": [
   "ローランド"
  ],
  "Romulus": [
   "ロムルス"
  ],
  "Ronald": [
   "ロナルド"
  ],
  "Rosa": [
   "ローザ"
  ],
  "Rosalie": [
   "ロザリー"
  ],
  "Rose": [
   "ローズ"
  ],
  "Roxanne": [
   "ロクサーヌ"
  ],
  "Roxy": [
   "ロキシー"
  ],
  "Rudeus": [
   "ルーデウス"
  ],
  "Rudolf": [
   "ルドルフ"
  ],
  "Ruth": [
   "ルース"
  ],
  "Sabrina": [
   "サブリナ"
  ],
  "Samael": [
   "サマエル"
  ],
  "Samantha": [
   "サマンサ"
  ],
  "Samuel": [
   "サミュエル"
  ],
  "Sara": [
   "サラ"
  ],
  "Sebastian": [
   "セバスチャン",
   "セバスティアン"
  ],
  "Seraphina": [
   "セラフィナ"
  ],
  "Sergei": [
   "セルゲイ"
  ],
  "Sergio": [
   "セルジオ"
  ],
  "Sharon": [
   "シャロン"
  ],
  "Shirley": [
   "シャーリー"
  ],
  "Siegfried": [
   "ジークフリート",
   "ジークフリード"
  ],
  "Silas": [
   "サイラス"
  ],
  "Simon": [
   "サイモン",
   "シモン"
  ],
  "Simone": [
   "シモーヌ"
  ],
  "Sonia": [
   "ソニア"
  ],
  "Sophia": [
   "ソフィア"
  ],
  "Sophie": [
   "ソフィー"
  ],
  "Stark": [
   "シュタルク"
  ],
  "Stefan": [
   "シュテファン"
  ],
  "Stella": [
   "ステラ"
  ],
  "Stephanie": [
   "ステファニー"
  ],
  "Stephen": [
   "スティーブン",
   "スティーヴン"
  ],
  "Steve": [
   "スティーブ",
   "スティーヴ"
  ],
  "Susan": [
   "スーザン"
  ],
  "Sven": [
   "スヴェン"
  ],
  "Svetlana": [
   "スヴェトラーナ",
   "スベトラーナ"
  ],
  "Sylphiette": [
   "シルフィエット"
  ],
  "Sylvia": [
   "シルヴィア",
   "シルビア"
  ],
  "Tanya": [
   "ターニャ"
  ],
  "Teresa": [
   "テレサ"
  ],
  "Theodore": [
   "セオドア"
  ],
  "Thomas": [
   "トーマス",
   "トマス"
  ],
  "Tiffany": [
   "ティファニー"
  ],
  "Timothy": [
   "ティモシー"
  ],
  "Titania": [
   "ティターニア"
  ],
  "Tobias": [
   "トビアス"
  ],
  "Tom": [
   "トム"
  ],
  "Tony": [
   "トニー"
  ],
  "Tristan": [
   "トリスタン"
  ],
  "Ulrich": [
   "ウルリッヒ",
   "ウルリヒ"
  ],
  "Uriel": [
   "ウリエル"
  ],
  "Ursula": [
   "ウルスラ"
  ],
  "Uther": [
   "ウーサー"
  ],
  "Valentina": [
   "ヴァレンティナ",
   "バレンティナ"
  ],
  "Valentine": [
   "ヴァレンタイン"
  ],
  "Valerie": [
   "ヴァレリー"
  ],
  "Vanessa": [
   "ヴァネッサ",
   "バネッサ"
  ],
  "Vera": [
   "ヴェラ"
  ],
  "Veronica": [
   "ヴェロニカ",
   "ベロニカ"
  ],
  "Victor": [
   "ヴィクター",
   "ビクター",
   "ヴィクトル"
  ],
  "Victoria": [
   "ヴィクトリア",
   "ビクトリア"
  ],
  "Vincent": [
   "ヴィンセント",
   "ビンセント"
  ],
  "Violet": [
   "ヴァイオレット",
   "バイオレット"
  ],
  "Vivian": [
   "ヴィヴィアン",
   "ビビアン"
  ],
  "Vladimir": [
   "ウラジーミル",
   "ウラジミール"
  ],
  "Walter": [
   "ウォルター",
   "ヴァルター"
  ],
  "Wendy": [
   "ウェンディ"
  ],
  "Wilhelm": [
   "ヴィルヘルム",
   "ウィルヘルム"
  ],
  "Wilhelmina": [
   "ヴィルヘルミナ"
  ],
  "William": [
   "ウィリアム"
  ],
  "Wolfgang": [
   "ヴォルフガング"
  ],
  "Xavier": [
   "ザビエル",
   "ザヴィエル"
  ],
  "Yvonne": [
   "イヴォンヌ"
  ],
  "Zeus": [
   "ゼウス"
  ],
  "Zoe": [
   "ゾーイ",
   "ゾエ"
  ]
 },
 "family": {
  "Adams": [
   "アダムズ",
   "アダムス"
  ],
  "Ainsworth": [
   "エインズワース"
  ],
  "Allen": [
   "アレン"
  ],
  "Anderson": [
   "アンダーソン"
  ],
  "Bach": [
   "バッハ"
  ],
  "Baker": [
   "ベイカー",
   "ベーカー"
  ],
  "Bauer": [
   "バウアー"
  ],
  "Becker": [
   "ベッカー"
  ],
  "Beethoven": [
   "ベートーヴェン",
   "ベートーベン"
  ],
  "Bennett": [
   "ベネット"
  ],
  "Bianchi": [
   "ビアンキ"
  ],
  "Blackwood": [
   "ブラックウッド"
  ],
  "Bonaparte": [
   "ボナパルト"
  ],
  "Borgia": [
   "ボルジア"
  ],
  "Brooks": [
   "ブルックス"
  ],
  "Brown": [
   "ブラウン"
  ],
  "Campbell": [
   "キャンベル"
  ],
  "Carter": [
   "カーター"
  ],
  "Chopin": [
   "ショパン"
  ],
  "Churchill": [
   "チャーチル"
  ],
  "Clark": [
   "クラーク"
  ],
  "Collins": [
   "コリンズ"
  ],
  "Colombo": [
   "コロンボ"
  ],
  "Columbus": [
   "コロンブス"
  ],
  "Cooper": [
   "クーパー"
  ],
  "Copernicus": [
   "コペルニクス"
  ],
  "Crawford": [
   "クロフォード"
  ],
  "Darwin": [
   "ダーウィン"
  ],
  "Davis": [
   "デイビス",
   "デイヴィス"
  ],
  "Descartes": [
   "デカルト"
  ],
  "Diaz": [
   "ディアス"
  ],
  "Dickens": [
   "ディケンズ"
  ],
  "Doyle": [
   "ドイル"
  ],
  "Dracula": [
   "ドラキュラ"
  ],
  "Dubois": [
   "デュボワ"
  ],
  "Dumas": [
   "デュマ"
  ],
  "Edison": [
   "エジソン"
  ],
  "Edwards": [
   "エドワーズ"
  ],
  "Einstein": [
   "アインシュタイン"
  ],
  "Evans": [
   "エヴァンス",
   "エバンス"
  ],
  "Ferrari": [
   "フェラーリ"
  ],
  "Fischer": [
   "フィッシャー"
  ],
  "Fitzgerald": [
   "フィッツジェラルド"
  ],
  "Fontaine": [
   "フォンテーヌ"
  ],
  "Foster": [
   "フォスター"
  ],
  "Frankenstein": [
   "フランケンシュタイン"
  ],
  "Freud": [
   "フロイト"
  ],
  "Galileo": [
   "ガリレオ"
  ],
  "Garcia": [
   "ガルシア"
  ],
  "Goethe": [
   "ゲーテ"
  ],
  "Gomez": [
   "ゴメス"
  ],
  "Gonzalez": [
   "ゴンザレス"
  ],
  "Gulliver": [
   "ガリバー",
   "ガリヴァー"
  ],
  "Habsburg": [
   "ハプスブルク"
  ],
  "Hamilton": [
   "ハミルトン"
  ],
  "Harris": [
   "ハリス"
  ],
  "Harrison": [
   "ハリソン"
  ],
  "Hartmann": [
   "ハルトマン"
  ],
  "Hawthorne": [
   "ホーソーン"
  ],
  "Hegel": [
   "ヘーゲル"
  ],
  "Henderson": [
   "ヘンダーソン"
  ],
  "Hernandez": [
   "エルナンデス"
  ],
  "Hoffmann": [
   "ホフマン"
  ],
  "Holmes": [
   "ホームズ"
  ],
  "Hudson": [
   "ハドソン"
  ],
  "Ivanov": [
   "イワノフ"
  ],
  "Jackson": [
   "ジャクソン"
  ],
  "Jekyll": [
   "ジキル"
  ],
  "Johnson": [
   "ジョンソン"
  ],
  "Jones": [
   "ジョーンズ"
  ],
  "Kant": [
   "カント"
  ],
  "Kennedy": [
   "ケネディ"
  ],
  "Kepler": [
   "ケプラー"
  ],
  "Kingsley": [
   "キングズリー"
  ],
  "Klein": [
   "クライン"
  ],
  "Krause": [
   "クラウゼ"
  ],
  "Kruger": [
   "クルーガー"
  ],
  "Kuznetsov": [
   "クズネツォフ"
  ],
  "Lancaster": [
   "ランカスター"
  ],
  "Laurent": [
   "ローラン"
  ],
  "Liddell": [
   "リデル"
  ],
  "Lincoln": [
   "リンカーン"
  ],
  "Lockhart": [
   "ロックハート"
  ],
  "Lopez": [
   "ロペス"
  ],
  "Lupin": [
   "ルパン"
  ],
  "Magellan": [
   "マゼラン"
  ],
  "Marple": [
   "マープル"
  ],
  "Martinez": [
   "マルティネス"
  ],
  "Medici": [
   "メディチ"
  ],
  "Mitchell": [
   "ミッチェル"
  ],
  "Montgomery": [
   "モンゴメリー"
  ],
  "Moore": [
   "ムーア"
  ],
  "Moreau": [
   "モロー"
  ],
  "Moriarty": [
   "モリアーティ"
  ],
  "Morris": [
   "モリス"
  ],
  "Mozart": [
   "モーツァルト"
  ],
  "Muller": [
   "ミュラー"
  ],
  "Murphy": [
   "マーフィー"
  ],
  "Nelson": [
   "ネルソン"
  ],
  "Neumann": [
   "ノイマン"
  ],
  "Newton": [
   "ニュートン"
  ],
  "Nietzsche": [
   "ニーチェ"
  ],
  "O'Brien": [
   "オブライエン"
  ],
  "Pendragon": [
   "ペンドラゴン"
  ],
  "Perez": [
   "ペレス"
  ],
  "Peterson": [
   "ピーターソン"
  ],
  "Petrov": [
   "ペトロフ"
  ],
  "Picasso": [
   "ピカソ"
  ],
  "Poirot": [
   "ポワロ"
  ],
  "Popov": [
   "ポポフ"
  ],
  "Potter": [
   "ポッター"
  ],
  "Radcliffe": [
   "ラドクリフ"
  ],
  "Ramirez": [
   "ラミレス"
  ],
  "Richardson": [
   "リチャードソン"
  ],
  "Richter": [
   "リヒター"
  ],
  "Rivera": [
   "リベラ"
  ],
  "Robinson": [
   "ロビンソン"
  ],
  "Rodriguez": [
   "ロドリゲス"
  ],
  "Romano": [
   "ロマーノ"
  ],
  "Romanov": [
   "ロマノフ"
  ],
  "Rossi": [
   "ロッシ"
  ],
  "Rousseau": [
   "ルソー"
  ],
  "Sanchez": [
   "サンチェス"
  ],
  "Sanders": [
   "サンダース"
  ],
  "Schmidt": [
   "シュミット"
  ],
  "Schneider": [
   "シュナイダー"
  ],
  "Schubert": [
   "シューベルト"
  ],
  "Schwarz": [
   "シュヴァルツ",
   "シュバルツ"
  ],
  "Scott": [
   "スコット"
  ],
  "Shakespeare": [
   "シェイクスピア",
   "シェークスピア"
  ],
  "Sinclair": [
   "シンクレア"
  ],
  "Smirnov": [
   "スミルノフ"
  ],
  "Smith": [
   "スミス"
  ],
  "Stewart": [
   "スチュワート"
  ],
  "Stuart": [
   "スチュアート"
  ],
  "Sullivan": [
   "サリバン",
   "サリヴァン"
  ],
  "Taylor": [
   "テイラー"
  ],
  "Thompson": [
   "トンプソン"
  ],
  "Torres": [
   "トーレス"
  ],
  "Tudor": [
   "チューダー"
  ],
  "Turner": [
   "ターナー"
  ],
  "Verne": [
   "ヴェルヌ"
  ],
  "Volkov": [
   "ヴォルコフ"
  ],
  "Voltaire": [
   "ヴォルテール"
  ],
  "Wagner": [
   "ワーグナー",
   "ヴァーグナー"
  ],
  "Walker": [
   "ウォーカー"
  ],
  "Washington": [
   "ワシントン"
  ],
  "Watson": [
   "ワトソン"
  ],
  "Weber": [
   "ウェーバー",
   "ヴェーバー"
  ],
  "Wellington": [
   "ウェリントン"
  ],
  "Williams": [
   "ウィリアムズ",
   "ウィリアムス"
  ],
  "Wilson": [
   "ウィルソン"
  ],
  "Windsor": [
   "ウィンザー"
  ],
  "Zimmermann": [
   "ツィンマーマン"
  ]
 }
}
'''

DATA['data/given_names.json'] = r'''{
  "美咲": {"reading": "みさき", "gender": "f"},
  "陽菜": {"reading": "ひな", "gender": "f"},
  "結衣": {"reading": "ゆい", "gender": "f"},
  "結菜": {"reading": "ゆいな", "gender": "f"},
  "陽葵": {"reading": "ひまり", "gender": "f"},
  "芽依": {"reading": "めい", "gender": "f"},
  "莉子": {"reading": "りこ", "gender": "f"},
  "美羽": {"reading": "みう", "gender": "f"},
  "心春": {"reading": "こはる", "gender": "f"},
  "杏": {"reading": "あん", "gender": "f"},
  "愛": {"reading": "あい", "gender": "f"},
  "優奈": {"reading": "ゆうな", "gender": "f"},
  "美月": {"reading": "みづき", "gender": "f"},
  "結愛": {"reading": "ゆあ", "gender": "f"},
  "彩": {"reading": "あや", "gender": "f"},
  "花": {"reading": "はな", "gender": "f"},
  "美優": {"reading": "みゆ", "gender": "f"},
  "楓": {"reading": "かえで", "gender": ""},
  "七海": {"reading": "ななみ", "gender": "f"},
  "遥": {"reading": "はるか", "gender": "f"},
  "真央": {"reading": "まお", "gender": "f"},
  "明日香": {"reading": "あすか", "gender": "f"},
  "麻衣": {"reading": "まい", "gender": "f"},
  "舞": {"reading": "まい", "gender": "f"},
  "彩花": {"reading": "あやか", "gender": "f"},
  "沙織": {"reading": "さおり", "gender": "f"},
  "恵": {"reading": "めぐみ", "gender": "f"},
  "由美": {"reading": "ゆみ", "gender": "f"},
  "裕子": {"reading": "ゆうこ", "gender": "f"},
  "直美": {"reading": "なおみ", "gender": "f"},
  "久美子": {"reading": "くみこ", "gender": "f"},
  "恵子": {"reading": "けいこ", "gender": "f"},
  "洋子": {"reading": "ようこ", "gender": "f"},
  "陽子": {"reading": "ようこ", "gender": "f"},
  "幸子": {"reading": "さちこ", "gender": "f"},
  "和子": {"reading": "かずこ", "gender": "f"},
  "京子": {"reading": "きょうこ", "gender": "f"},
  "智子": {"reading": "ともこ", "gender": "f"},
  "真由美": {"reading": "まゆみ", "gender": "f"},
  "美穂": {"reading": "みほ", "gender": "f"},
  "香織": {"reading": "かおり", "gender": "f"},
  "由香": {"reading": "ゆか", "gender": "f"},
  "愛子": {"reading": "あいこ", "gender": "f"},
  "明美": {"reading": "あけみ", "gender": "f"},
  "典子": {"reading": "のりこ", "gender": "f"},
  "純子": {"reading": "じゅんこ", "gender": "f"},
  "順子": {"reading": "じゅんこ", "gender": "f"},
  "美紀": {"reading": "みき", "gender": "f"},
  "美樹": {"reading": "みき", "gender": "f"},
  "早紀": {"reading": "さき", "gender": "f"},
  "咲": {"reading": "さき", "gender": "f"},
  "沙希": {"reading": "さき", "gender": "f"},
  "千夏": {"reading": "ちなつ", "gender": "f"},
  "夏美": {"reading": "なつみ", "gender": "f"},
  "菜々子": {"reading": "ななこ", "gender": "f"},
  "奈々": {"reading": "なな", "gender": "f"},
  "菜摘": {"reading": "なつみ", "gender": "f"},
  "綾香": {"reading": "あやか", "gender": "f"},
  "絵里": {"reading": "えり", "gender": "f"},
  "恵美": {"reading": "えみ", "gender": "f"},
  "理恵": {"reading": "りえ", "gender": "f"},
  "里美": {"reading": "さとみ", "gender": "f"},
  "聡子": {"reading": "さとこ", "gender": "f"},
  "紀子": {"reading": "のりこ", "gender": "f"},
  "真理子": {"reading": "まりこ", "gender": "f"},
  "麻美": {"reading": "あさみ", "gender": "f"},
  "亜美": {"reading": "あみ", "gender": "f"},
  "亜希子": {"reading": "あきこ", "gender": "f"},
  "明子": {"reading": "あきこ", "gender": "f"},
  "晶子": {"reading": "あきこ", "gender": "f"},
  "朋美": {"reading": "ともみ", "gender": "f"},
  "友美": {"reading": "ともみ", "gender": "f"},
  "美奈子": {"reading": "みなこ", "gender": "f"},
  "美香": {"reading": "みか", "gender": "f"},
  "美加": {"reading": "みか", "gender": "f"},
  "由紀": {"reading": "ゆき", "gender": "f"},
  "由紀子": {"reading": "ゆきこ", "gender": "f"},
  "雪": {"reading": "ゆき", "gender": "f"},
  "小雪": {"reading": "こゆき", "gender": "f"},
  "桃子": {"reading": "ももこ", "gender": "f"},
  "桃": {"reading": "もも", "gender": "f"},
  "百合": {"reading": "ゆり", "gender": "f"},
  "百合子": {"reading": "ゆりこ", "gender": "f"},
  "小百合": {"reading": "さゆり", "gender": "f"},
  "千尋": {"reading": "ちひろ", "gender": "f"},
  "千里": {"reading": "ちさと", "gender": "f"},
  "千春": {"reading": "ちはる", "gender": "f"},
  "春香": {"reading": "はるか", "gender": "f"},
  "春菜": {"reading": "はるな", "gender": "f"},
  "陽菜子": {"reading": "ひなこ", "gender": "f"},
  "日菜": {"reading": "ひな", "gender": "f"},
  "雛": {"reading": "ひな", "gender": "f"},
  "瞳": {"reading": "ひとみ", "gender": "f"},
  "文香": {"reading": "ふみか", "gender": "f"},
  "史子": {"reading": "ふみこ", "gender": "f"},
  "冬美": {"reading": "ふゆみ", "gender": "f"},
  "秋子": {"reading": "あきこ", "gender": "f"},
  "芽衣": {"reading": "めい", "gender": "f"},
  "萌": {"reading": "もえ", "gender": "f"},
  "萌香": {"reading": "もえか", "gender": "f"},
  "桜": {"reading": "さくら", "gender": "f"},
  "咲良": {"reading": "さくら", "gender": "f"},
  "紗希": {"reading": "さき", "gender": "f"},
  "紗耶": {"reading": "さや", "gender": "f"},
  "沙耶": {"reading": "さや", "gender": "f"},
  "清香": {"reading": "さやか", "gender": "f"},
  "彩乃": {"reading": "あやの", "gender": "f"},
  "綾乃": {"reading": "あやの", "gender": "f"},
  "詩織": {"reading": "しおり", "gender": "f"},
  "志保": {"reading": "しほ", "gender": "f"},
  "静香": {"reading": "しずか", "gender": "f"},
  "雫": {"reading": "しずく", "gender": "f"},
  "菫": {"reading": "すみれ", "gender": "f"},
  "鈴": {"reading": "すず", "gender": "f"},
  "涼子": {"reading": "りょうこ", "gender": "f"},
  "玲奈": {"reading": "れな", "gender": "f"},
  "麗奈": {"reading": "れいな", "gender": "f"},
  "玲子": {"reading": "れいこ", "gender": "f"},
  "怜奈": {"reading": "れな", "gender": "f"},
  "莉奈": {"reading": "りな", "gender": "f"},
  "里奈": {"reading": "りな", "gender": "f"},
  "梨花": {"reading": "りか", "gender": "f"},
  "理沙": {"reading": "りさ", "gender": "f"},
  "梨沙": {"reading": "りさ", "gender": "f"},
  "瑠璃": {"reading": "るり", "gender": "f"},
  "留美": {"reading": "るみ", "gender": "f"},
  "若菜": {"reading": "わかな", "gender": "f"},
  "和香": {"reading": "わか", "gender": "f"},
  "未来": {"reading": "みらい", "gender": "f"},
  "美里": {"reading": "みさと", "gender": "f"},
  "美波": {"reading": "みなみ", "gender": "f"},
  "みのり": {"reading": "みのり", "gender": "f"},
  "穂乃香": {"reading": "ほのか", "gender": "f"},
  "穂香": {"reading": "ほのか", "gender": "f"},
  "乃愛": {"reading": "のあ", "gender": "f"},
  "望美": {"reading": "のぞみ", "gender": "f"},
  "希美": {"reading": "のぞみ", "gender": "f"},
  "菜月": {"reading": "なつき", "gender": "f"},
  "夏帆": {"reading": "かほ", "gender": "f"},
  "果歩": {"reading": "かほ", "gender": "f"},
  "佳奈": {"reading": "かな", "gender": "f"},
  "加奈": {"reading": "かな", "gender": "f"},
  "香奈": {"reading": "かな", "gender": "f"},
  "可奈子": {"reading": "かなこ", "gender": "f"},
  "佳子": {"reading": "よしこ", "gender": "f"},
  "良子": {"reading": "よしこ", "gender": "f"},
  "芳子": {"reading": "よしこ", "gender": "f"},
  "恭子": {"reading": "きょうこ", "gender": "f"},
  "貴子": {"reading": "たかこ", "gender": "f"},
  "孝子": {"reading": "たかこ", "gender": "f"},
  "珠美": {"reading": "たまみ", "gender": "f"},
  "環": {"reading": "たまき", "gender": "f"},
  "千代": {"reading": "ちよ", "gender": "f"},
  "千鶴": {"reading": "ちづる", "gender": "f"},
  "鶴子": {"reading": "つるこ", "gender": "f"},
  "艶子": {"reading": "つやこ", "gender": "f"},
  "椿": {"reading": "つばき", "gender": "f"},
  "朱里": {"reading": "あかり", "gender": "f"},
  "明里": {"reading": "あかり", "gender": "f"},
  "灯": {"reading": "あかり", "gender": "f"},
  "茜": {"reading": "あかね", "gender": "f"},
  "杏奈": {"reading": "あんな", "gender": "f"},
  "杏子": {"reading": "きょうこ", "gender": "f"},
  "安奈": {"reading": "あんな", "gender": "f"},
  "愛理": {"reading": "あいり", "gender": "f"},
  "愛梨": {"reading": "あいり", "gender": "f"},
  "亜衣": {"reading": "あい", "gender": "f"},
  "亜由美": {"reading": "あゆみ", "gender": "f"},
  "歩美": {"reading": "あゆみ", "gender": "f"},
  "鮎美": {"reading": "あゆみ", "gender": "f"},
  "郁恵": {"reading": "いくえ", "gender": "f"},
  "泉美": {"reading": "いずみ", "gender": "f"},
  "伊織": {"reading": "いおり", "gender": ""},
  "栞": {"reading": "しおり", "gender": "f"},
  "詩": {"reading": "うた", "gender": "f"},
  "詠美": {"reading": "えいみ", "gender": "f"},
  "英子": {"reading": "えいこ", "gender": "f"},
  "絵美": {"reading": "えみ", "gender": "f"},
  "恵理子": {"reading": "えりこ", "gender": "f"},
  "江里子": {"reading": "えりこ", "gender": "f"},
  "薫子": {"reading": "かおるこ", "gender": "f"},
  "香澄": {"reading": "かすみ", "gender": "f"},
  "霞": {"reading": "かすみ", "gender": "f"},
  "佳織": {"reading": "かおり", "gender": "f"},
  "和恵": {"reading": "かずえ", "gender": "f"},
  "加代子": {"reading": "かよこ", "gender": "f"},
  "佳代": {"reading": "かよ", "gender": "f"},
  "喜美子": {"reading": "きみこ", "gender": "f"},
  "君子": {"reading": "きみこ", "gender": "f"},
  "久美": {"reading": "くみ", "gender": "f"},
  "紅葉": {"reading": "もみじ", "gender": "f"},
  "胡桃": {"reading": "くるみ", "gender": "f"},
  "来未": {"reading": "くるみ", "gender": "f"},
  "恵梨香": {"reading": "えりか", "gender": "f"},
  "絵梨花": {"reading": "えりか", "gender": "f"},
  "光子": {"reading": "みつこ", "gender": "f"},
  "美智子": {"reading": "みちこ", "gender": "f"},
  "道子": {"reading": "みちこ", "gender": "f"},
  "みゆき": {"reading": "みゆき", "gender": "f"},
  "美幸": {"reading": "みゆき", "gender": "f"},
  "深雪": {"reading": "みゆき", "gender": "f"},
  "結": {"reading": "ゆい", "gender": "f"},
  "優子": {"reading": "ゆうこ", "gender": "f"},
  "優花": {"reading": "ゆうか", "gender": "f"},
  "優香": {"reading": "ゆうか", "gender": "f"},
  "夕子": {"reading": "ゆうこ", "gender": "f"},
  "陽向": {"reading": "ひなた", "gender": "f"},
  "日向子": {"reading": "ひなこ", "gender": "f"},
  "弥生": {"reading": "やよい", "gender": "f"},
  "八重": {"reading": "やえ", "gender": "f"},
  "葉子": {"reading": "ようこ", "gender": "f"},
  "蓉子": {"reading": "ようこ", "gender": "f"},
  "頼子": {"reading": "よりこ", "gender": "f"},
  "礼子": {"reading": "れいこ", "gender": "f"},
  "蘭": {"reading": "らん", "gender": "f"},
  "麗": {"reading": "れい", "gender": "f"},
  "鈴音": {"reading": "すずね", "gender": "f"},
  "寧々": {"reading": "ねね", "gender": "f"},
  "音羽": {"reading": "おとは", "gender": "f"},
  "乙葉": {"reading": "おとは", "gender": "f"},
  "小春": {"reading": "こはる", "gender": "f"},
  "琴音": {"reading": "ことね", "gender": "f"},
  "心": {"reading": "こころ", "gender": "f"},
  "真白": {"reading": "ましろ", "gender": "f"},
  "茉莉": {"reading": "まり", "gender": "f"},
  "麻里": {"reading": "まり", "gender": "f"},
  "真理": {"reading": "まり", "gender": "f"},
  "万里子": {"reading": "まりこ", "gender": "f"},
  "摩耶": {"reading": "まや", "gender": "f"},
  "真耶": {"reading": "まや", "gender": "f"},
  "美雪": {"reading": "みゆき", "gender": "f"},
  "海香": {"reading": "みか", "gender": "f"},
  "蓮": {"reading": "れん", "gender": "m"},
  "悠真": {"reading": "ゆうま", "gender": "m"},
  "湊": {"reading": "みなと", "gender": "m"},
  "陽翔": {"reading": "はると", "gender": "m"},
  "大翔": {"reading": "ひろと", "gender": "m"},
  "樹": {"reading": "いつき", "gender": "m"},
  "悠斗": {"reading": "ゆうと", "gender": "m"},
  "陽太": {"reading": "ようた", "gender": "m"},
  "颯太": {"reading": "そうた", "gender": "m"},
  "大和": {"reading": "やまと", "gender": "m"},
  "翔太": {"reading": "しょうた", "gender": "m"},
  "拓海": {"reading": "たくみ", "gender": "m"},
  "健太": {"reading": "けんた", "gender": "m"},
  "大輔": {"reading": "だいすけ", "gender": "m"},
  "翔": {"reading": "しょう", "gender": "m"},
  "健": {"reading": "けん", "gender": "m"},
  "太郎": {"reading": "たろう", "gender": "m"},
  "一郎": {"reading": "いちろう", "gender": "m"},
  "健一": {"reading": "けんいち", "gender": "m"},
  "浩二": {"reading": "こうじ", "gender": "m"},
  "和也": {"reading": "かずや", "gender": "m"},
  "達也": {"reading": "たつや", "gender": "m"},
  "拓也": {"reading": "たくや", "gender": "m"},
  "直樹": {"reading": "なおき", "gender": "m"},
  "哲也": {"reading": "てつや", "gender": "m"},
  "隆": {"reading": "たかし", "gender": "m"},
  "剛": {"reading": "つよし", "gender": "m"},
  "大樹": {"reading": "だいき", "gender": "m"},
  "亮": {"reading": "りょう", "gender": "m"},
  "遼": {"reading": "りょう", "gender": "m"},
  "恭介": {"reading": "きょうすけ", "gender": "m"},
  "蒼太": {"reading": "そうた", "gender": "m"},
  "悠人": {"reading": "ゆうと", "gender": "m"},
  "陸": {"reading": "りく", "gender": "m"},
  "海斗": {"reading": "かいと", "gender": "m"},
  "優斗": {"reading": "ゆうと", "gender": "m"},
  "奏太": {"reading": "そうた", "gender": "m"},
  "隼人": {"reading": "はやと", "gender": "m"},
  "雄大": {"reading": "ゆうだい", "gender": "m"},
  "康介": {"reading": "こうすけ", "gender": "m"},
  "修": {"reading": "おさむ", "gender": "m"},
  "稔": {"reading": "みのる", "gender": "m"},
  "弘": {"reading": "ひろし", "gender": "m"},
  "博": {"reading": "ひろし", "gender": "m"},
  "浩": {"reading": "ひろし", "gender": "m"},
  "清": {"reading": "きよし", "gender": "m"},
  "茂": {"reading": "しげる", "gender": "m"},
  "進": {"reading": "すすむ", "gender": "m"},
  "正": {"reading": "ただし", "gender": "m"},
  "明": {"reading": "あきら", "gender": "m"},
  "昴": {"reading": "すばる", "gender": "m"},
  "晴人": {"reading": "はると", "gender": "m"},
  "春斗": {"reading": "はると", "gender": "m"},
  "遥斗": {"reading": "はると", "gender": "m"},
  "陽斗": {"reading": "はると", "gender": "m"},
  "結翔": {"reading": "ゆいと", "gender": "m"},
  "蒼": {"reading": "そう", "gender": "m"},
  "颯": {"reading": "はやて", "gender": "m"},
  "律": {"reading": "りつ", "gender": "m"},
  "悠太": {"reading": "ゆうた", "gender": "m"},
  "祐太": {"reading": "ゆうた", "gender": "m"},
  "雄太": {"reading": "ゆうた", "gender": "m"},
  "勇太": {"reading": "ゆうた", "gender": "m"},
  "優太": {"reading": "ゆうた", "gender": "m"},
  "亮太": {"reading": "りょうた", "gender": "m"},
  "涼太": {"reading": "りょうた", "gender": "m"},
  "良太": {"reading": "りょうた", "gender": "m"},
  "翔平": {"reading": "しょうへい", "gender": "m"},
  "祥平": {"reading": "しょうへい", "gender": "m"},
  "修平": {"reading": "しゅうへい", "gender": "m"},
  "航平": {"reading": "こうへい", "gender": "m"},
  "耕平": {"reading": "こうへい", "gender": "m"},
  "洋平": {"reading": "ようへい", "gender": "m"},
  "純平": {"reading": "じゅんぺい", "gender": "m"},
  "大介": {"reading": "だいすけ", "gender": "m"},
  "圭介": {"reading": "けいすけ", "gender": "m"},
  "啓介": {"reading": "けいすけ", "gender": "m"},
  "健介": {"reading": "けんすけ", "gender": "m"},
  "俊介": {"reading": "しゅんすけ", "gender": "m"},
  "駿介": {"reading": "しゅんすけ", "gender": "m"},
  "雄介": {"reading": "ゆうすけ", "gender": "m"},
  "裕介": {"reading": "ゆうすけ", "gender": "m"},
  "祐介": {"reading": "ゆうすけ", "gender": "m"},
  "竜介": {"reading": "りゅうすけ", "gender": "m"},
  "龍之介": {"reading": "りゅうのすけ", "gender": "m"},
  "慎之介": {"reading": "しんのすけ", "gender": "m"},
  "新之助": {"reading": "しんのすけ", "gender": "m"},
  "金之助": {"reading": "きんのすけ", "gender": "m"},
  "健二": {"reading": "けんじ", "gender": "m"},
  "健司": {"reading": "けんじ", "gender": "m"},
  "賢治": {"reading": "けんじ", "gender": "m"},
  "憲二": {"reading": "けんじ", "gender": "m"},
  "誠二": {"reading": "せいじ", "gender": "m"},
  "英二": {"reading": "えいじ", "gender": "m"},
  "栄治": {"reading": "えいじ", "gender": "m"},
  "雄二": {"reading": "ゆうじ", "gender": "m"},
  "裕二": {"reading": "ゆうじ", "gender": "m"},
  "祐二": {"reading": "ゆうじ", "gender": "m"},
  "勇二": {"reading": "ゆうじ", "gender": "m"},
  "修二": {"reading": "しゅうじ", "gender": "m"},
  "秀二": {"reading": "しゅうじ", "gender": "m"},
  "晋三": {"reading": "しんぞう", "gender": "m"},
  "健三": {"reading": "けんぞう", "gender": "m"},
  "二郎": {"reading": "じろう", "gender": "m"},
  "次郎": {"reading": "じろう", "gender": "m"},
  "三郎": {"reading": "さぶろう", "gender": "m"},
  "四郎": {"reading": "しろう", "gender": "m"},
  "五郎": {"reading": "ごろう", "gender": "m"},
  "太一": {"reading": "たいち", "gender": "m"},
  "雄一": {"reading": "ゆういち", "gender": "m"},
  "祐一": {"reading": "ゆういち", "gender": "m"},
  "裕一": {"reading": "ゆういち", "gender": "m"},
  "優一": {"reading": "ゆういち", "gender": "m"},
  "浩一": {"reading": "こういち", "gender": "m"},
  "幸一": {"reading": "こういち", "gender": "m"},
  "光一": {"reading": "こういち", "gender": "m"},
  "晃一": {"reading": "こういち", "gender": "m"},
  "誠一": {"reading": "せいいち", "gender": "m"},
  "真一": {"reading": "しんいち", "gender": "m"},
  "慎一": {"reading": "しんいち", "gender": "m"},
  "伸一": {"reading": "しんいち", "gender": "m"},
  "純一": {"reading": "じゅんいち", "gender": "m"},
  "俊一": {"reading": "しゅんいち", "gender": "m"},
  "健太郎": {"reading": "けんたろう", "gender": "m"},
  "慎太郎": {"reading": "しんたろう", "gender": "m"},
  "晋太郎": {"reading": "しんたろう", "gender": "m"},
  "浩太郎": {"reading": "こうたろう", "gender": "m"},
  "幸太郎": {"reading": "こうたろう", "gender": "m"},
  "龍太郎": {"reading": "りゅうたろう", "gender": "m"},
  "雄一郎": {"reading": "ゆういちろう", "gender": "m"},
  "和彦": {"reading": "かずひこ", "gender": "m"},
  "克彦": {"reading": "かつひこ", "gender": "m"},
  "信彦": {"reading": "のぶひこ", "gender": "m"},
  "晴彦": {"reading": "はるひこ", "gender": "m"},
  "秀彦": {"reading": "ひでひこ", "gender": "m"},
  "正彦": {"reading": "まさひこ", "gender": "m"},
  "雅彦": {"reading": "まさひこ", "gender": "m"},
  "敏彦": {"reading": "としひこ", "gender": "m"},
  "俊彦": {"reading": "としひこ", "gender": "m"},
  "隆之": {"reading": "たかゆき", "gender": "m"},
  "貴之": {"reading": "たかゆき", "gender": "m"},
  "博之": {"reading": "ひろゆき", "gender": "m"},
  "裕之": {"reading": "ひろゆき", "gender": "m"},
  "宏之": {"reading": "ひろゆき", "gender": "m"},
  "正之": {"reading": "まさゆき", "gender": "m"},
  "雅之": {"reading": "まさゆき", "gender": "m"},
  "和之": {"reading": "かずゆき", "gender": "m"},
  "秀之": {"reading": "ひでゆき", "gender": "m"},
  "智之": {"reading": "ともゆき", "gender": "m"},
  "知之": {"reading": "ともゆき", "gender": "m"},
  "康之": {"reading": "やすゆき", "gender": "m"},
  "正樹": {"reading": "まさき", "gender": "m"},
  "雅樹": {"reading": "まさき", "gender": "m"},
  "和樹": {"reading": "かずき", "gender": "m"},
  "一樹": {"reading": "かずき", "gender": "m"},
  "大貴": {"reading": "だいき", "gender": "m"},
  "拓真": {"reading": "たくま", "gender": "m"},
  "琢磨": {"reading": "たくま", "gender": "m"},
  "一真": {"reading": "かずま", "gender": "m"},
  "和真": {"reading": "かずま", "gender": "m"},
  "数馬": {"reading": "かずま", "gender": "m"},
  "竜也": {"reading": "たつや", "gender": "m"},
  "龍也": {"reading": "たつや", "gender": "m"},
  "達彦": {"reading": "たつひこ", "gender": "m"},
  "武": {"reading": "たけし", "gender": "m"},
  "猛": {"reading": "たけし", "gender": "m"},
  "毅": {"reading": "たけし", "gender": "m"},
  "勝": {"reading": "まさる", "gender": "m"},
  "勉": {"reading": "つとむ", "gender": "m"},
  "努": {"reading": "つとむ", "gender": "m"},
  "学": {"reading": "まなぶ", "gender": "m"},
  "豊": {"reading": "ゆたか", "gender": "m"},
  "実": {"reading": "みのる", "gender": "m"},
  "昇": {"reading": "のぼる", "gender": "m"},
  "登": {"reading": "のぼる", "gender": "m"},
  "守": {"reading": "まもる", "gender": "m"},
  "衛": {"reading": "まもる", "gender": "m"},
  "誠": {"reading": "まこと", "gender": "m"},
  "仁": {"reading": "じん", "gender": "m"},
  "隼": {"reading": "しゅん", "gender": "m"},
  "駿": {"reading": "しゅん", "gender": "m"},
  "瞬": {"reading": "しゅん", "gender": "m"},
  "俊": {"reading": "しゅん", "gender": "m"},
  "迅": {"reading": "じん", "gender": "m"},
  "謙": {"reading": "けん", "gender": "m"},
  "研": {"reading": "けん", "gender": "m"},
  "賢": {"reading": "けん", "gender": "m"},
  "憲": {"reading": "けん", "gender": "m"},
  "譲": {"reading": "ゆずる", "gender": "m"},
  "創": {"reading": "はじめ", "gender": "m"},
  "肇": {"reading": "はじめ", "gender": "m"},
  "一": {"reading": "はじめ", "gender": "m"},
  "元": {"reading": "はじめ", "gender": "m"},
  "匠": {"reading": "たくみ", "gender": "m"},
  "巧": {"reading": "たくみ", "gender": "m"},
  "功": {"reading": "いさお", "gender": "m"},
  "勲": {"reading": "いさお", "gender": "m"},
  "勇": {"reading": "いさむ", "gender": "m"},
  "勇人": {"reading": "はやと", "gender": "m"},
  "隼斗": {"reading": "はやと", "gender": "m"},
  "颯人": {"reading": "はやと", "gender": "m"},
  "蒼空": {"reading": "そら", "gender": "m"},
  "大空": {"reading": "そら", "gender": "m"},
  "陸斗": {"reading": "りくと", "gender": "m"},
  "陸人": {"reading": "りくと", "gender": "m"},
  "理人": {"reading": "りひと", "gender": "m"},
  "律希": {"reading": "りつき", "gender": "m"},
  "凌": {"reading": "りょう", "gender": "m"},
  "涼介": {"reading": "りょうすけ", "gender": "m"},
  "亮介": {"reading": "りょうすけ", "gender": "m"},
  "良介": {"reading": "りょうすけ", "gender": "m"},
  "恵介": {"reading": "けいすけ", "gender": "m"},
  "啓太": {"reading": "けいた", "gender": "m"},
  "圭太": {"reading": "けいた", "gender": "m"},
  "慶太": {"reading": "けいた", "gender": "m"},
  "敬太": {"reading": "けいた", "gender": "m"},
  "恵太": {"reading": "けいた", "gender": "m"},
  "航": {"reading": "わたる", "gender": "m"},
  "渉": {"reading": "わたる", "gender": "m"},
  "亘": {"reading": "わたる", "gender": "m"},
  "航太": {"reading": "こうた", "gender": "m"},
  "康太": {"reading": "こうた", "gender": "m"},
  "幸太": {"reading": "こうた", "gender": "m"},
  "晃太": {"reading": "こうた", "gender": "m"},
  "光太": {"reading": "こうた", "gender": "m"},
  "浩太": {"reading": "こうた", "gender": "m"},
  "耕太": {"reading": "こうた", "gender": "m"},
  "直人": {"reading": "なおと", "gender": "m"},
  "尚人": {"reading": "なおと", "gender": "m"},
  "直也": {"reading": "なおや", "gender": "m"},
  "尚也": {"reading": "なおや", "gender": "m"},
  "秀樹": {"reading": "ひでき", "gender": "m"},
  "英樹": {"reading": "ひでき", "gender": "m"},
  "秀人": {"reading": "ひでと", "gender": "m"},
  "英人": {"reading": "ひでと", "gender": "m"},
  "悠希": {"reading": "ゆうき", "gender": "m"},
  "雄貴": {"reading": "ゆうき", "gender": "m"},
  "裕貴": {"reading": "ゆうき", "gender": "m"},
  "勇樹": {"reading": "ゆうき", "gender": "m"},
  "祐樹": {"reading": "ゆうき", "gender": "m"},
  "真人": {"reading": "まさと", "gender": "m"},
  "正人": {"reading": "まさと", "gender": "m"},
  "雅人": {"reading": "まさと", "gender": "m"},
  "薫": {"reading": "かおる", "gender": ""},
  "光": {"reading": "ひかる", "gender": ""},
  "翼": {"reading": "つばさ", "gender": ""},
  "葵": {"reading": "あおい", "gender": ""},
  "歩": {"reading": "あゆむ", "gender": ""},
  "渚": {"reading": "なぎさ", "gender": ""},
  "真琴": {"reading": "まこと", "gender": ""},
  "瑞希": {"reading": "みずき", "gender": ""},
  "優希": {"reading": "ゆうき", "gender": ""},
  "晶": {"reading": "あきら", "gender": ""},
  "忍": {"reading": "しのぶ", "gender": ""},
  "純": {"reading": "じゅん", "gender": ""},
  "司": {"reading": "つかさ", "gender": ""},
  "和美": {"reading": "かずみ", "gender": ""},
  "智": {"reading": "さとし", "gender": ""},
  "勇気": {"reading": "ゆうき", "gender": ""},
  "祐希": {"reading": "ゆうき", "gender": ""},
  "遊": {"reading": "ゆう", "gender": ""},
  "悠里": {"reading": "ゆうり", "gender": ""},
  "夕陽": {"reading": "ゆうひ", "gender": ""},
  "千秋": {"reading": "ちあき", "gender": ""},
  "凛": {"reading": "りん", "gender": ""},
  "涼": {"reading": "りょう", "gender": ""},
  "晴": {"reading": "はる", "gender": ""},
  "春": {"reading": "はる", "gender": ""},
  "真": {"reading": "まこと", "gender": ""},
  "望": {"reading": "のぞむ", "gender": ""},
  "蛍": {"reading": "ほたる", "gender": ""},
  "楓真": {"reading": "ふうま", "gender": ""},
  "空": {"reading": "そら", "gender": ""},
  "海": {"reading": "うみ", "gender": ""},
  "静": {"reading": "しずか", "gender": ""},
  "栄": {"reading": "さかえ", "gender": ""},
  "輝": {"reading": "ひかる", "gender": ""},
  "七瀬": {"reading": "ななせ", "gender": ""},
  "陽": {"reading": "ひなた", "gender": ""},
  "日向": {"reading": "ひなた", "gender": ""},
  "悠": {"reading": "ゆう", "gender": ""},
  "優": {"reading": "ゆう", "gender": ""},
  "碧": {"reading": "あおい", "gender": ""},
  "鞠": {"reading": "まり", "gender": ""},
  "玲": {"reading": "れい", "gender": ""},
  "圭": {"reading": "けい", "gender": "m"},
  "潤": {"reading": "じゅん", "gender": "m"},
  "舜": {"reading": "しゅん", "gender": "m"},
  "徹": {"reading": "とおる", "gender": "m"},
  "治": {"reading": "おさむ", "gender": "m"},
  "直": {"reading": "なお", "gender": ""}
}
'''

DATA['data/kanji_readings.json'] = r'''{
 "on": {
  "一": ["いち", "いつ"],
  "二": ["に", "じ"],
  "三": ["さん"],
  "四": ["し"],
  "五": ["ご"],
  "六": ["ろく"],
  "七": ["しち"],
  "八": ["はち"],
  "九": ["く", "きゅう"],
  "十": ["じゅう"],
  "百": ["ひゃく"],
  "千": ["せん"],
  "万": ["まん", "ばん"],
  "億": ["おく"],
  "兆": ["ちょう"],
  "零": ["れい"],
  "山": ["さん"],
  "川": ["せん"],
  "田": ["でん"],
  "野": ["や"],
  "原": ["げん"],
  "林": ["りん"],
  "森": ["しん"],
  "木": ["もく", "ぼく"],
  "竹": ["ちく"],
  "松": ["しょう"],
  "杉": ["さん"],
  "桜": ["おう"],
  "梅": ["ばい"],
  "桃": ["とう"],
  "柳": ["りゅう"],
  "桐": ["とう"],
  "楓": ["ふう"],
  "椿": ["ちん"],
  "菊": ["きく"],
  "蘭": ["らん"],
  "蓮": ["れん"],
  "葵": ["き"],
  "萩": ["しゅう"],
  "藤": ["とう"],
  "葉": ["よう"],
  "花": ["か"],
  "草": ["そう"],
  "芝": ["し"],
  "苗": ["びょう"],
  "稲": ["とう"],
  "米": ["べい", "まい"],
  "麦": ["ばく"],
  "豆": ["とう", "ず"],
  "栗": ["りつ"],
  "柿": ["し"],
  "橘": ["きつ"],
  "楠": ["なん"],
  "椎": ["つい"],
  "檜": ["かい"],
  "桧": ["かい"],
  "柏": ["はく"],
  "樹": ["じゅ"],
  "枝": ["し"],
  "根": ["こん"],
  "株": ["しゅ"],
  "芽": ["が"],
  "実": ["じつ"],
  "種": ["しゅ"],
  "穂": ["すい"],
  "稔": ["ねん", "じん"],
  "菜": ["さい"],
  "茉": ["まつ"],
  "莉": ["り"],
  "杏": ["きょう", "あん"],
  "柚": ["ゆう"],
  "桂": ["けい"],
  "楊": ["よう"],
  "榎": ["か"],
  "棚": ["ほう"],
  "堀": ["くつ"],
  "池": ["ち"],
  "沼": ["しょう"],
  "湖": ["こ"],
  "海": ["かい"],
  "浜": ["ひん"],
  "浦": ["ほ"],
  "島": ["とう"],
  "嶋": ["とう"],
  "岡": ["こう"],
  "丘": ["きゅう"],
  "岳": ["がく"],
  "峰": ["ほう"],
  "峯": ["ほう"],
  "坂": ["はん"],
  "谷": ["こく"],
  "沢": ["たく"],
  "澤": ["たく"],
  "滝": ["ろう"],
  "瀧": ["ろう"],
  "泉": ["せん"],
  "井": ["せい", "しょう"],
  "江": ["こう"],
  "河": ["か"],
  "津": ["しん"],
  "港": ["こう"],
  "湊": ["そう"],
  "渡": ["と"],
  "橋": ["きょう"],
  "石": ["せき", "しゃく", "こく"],
  "岩": ["がん"],
  "磯": ["き"],
  "崎": ["き"],
  "埼": ["き"],
  "岬": ["こう"],
  "村": ["そん"],
  "町": ["ちょう"],
  "里": ["り"],
  "郷": ["きょう", "ごう"],
  "都": ["と", "つ"],
  "京": ["きょう", "けい"],
  "市": ["し"],
  "区": ["く"],
  "県": ["けん"],
  "州": ["しゅう"],
  "国": ["こく"],
  "邦": ["ほう"],
  "城": ["じょう"],
  "宮": ["きゅう", "ぐう", "く"],
  "神": ["しん", "じん"],
  "社": ["しゃ"],
  "寺": ["じ"],
  "院": ["いん"],
  "殿": ["でん", "てん"],
  "門": ["もん"],
  "戸": ["こ"],
  "家": ["か", "け"],
  "屋": ["おく"],
  "倉": ["そう"],
  "蔵": ["ぞう"],
  "庫": ["こ", "く"],
  "館": ["かん"],
  "堂": ["どう"],
  "塚": ["ちょう"],
  "垣": ["えん"],
  "堤": ["てい"],
  "関": ["かん"],
  "所": ["しょ"],
  "場": ["じょう"],
  "地": ["ち", "じ"],
  "土": ["ど", "と"],
  "道": ["どう"],
  "路": ["ろ"],
  "街": ["がい"],
  "駅": ["えき"],
  "口": ["こう", "く"],
  "内": ["ない", "だい"],
  "外": ["がい", "げ"],
  "上": ["じょう", "しょう"],
  "下": ["か", "げ"],
  "中": ["ちゅう"],
  "前": ["ぜん"],
  "後": ["ご", "こう"],
  "左": ["さ"],
  "右": ["う", "ゆう"],
  "東": ["とう"],
  "西": ["せい", "さい"],
  "南": ["なん", "な"],
  "北": ["ほく"],
  "央": ["おう"],
  "間": ["かん", "けん"],
  "奥": ["おう"],
  "端": ["たん"],
  "辺": ["へん"],
  "際": ["さい"],
  "側": ["そく"],
  "脇": ["きょう"],
  "横": ["おう"],
  "縦": ["じゅう"],
  "角": ["かく"],
  "隅": ["ぐう"],
  "向": ["こう"],
  "表": ["ひょう"],
  "裏": ["り"],
  "近": ["きん"],
  "遠": ["えん", "おん"],
  "高": ["こう"],
  "低": ["てい"],
  "深": ["しん"],
  "浅": ["せん"],
  "長": ["ちょう"],
  "短": ["たん"],
  "広": ["こう"],
  "狭": ["きょう"],
  "大": ["だい", "たい"],
  "小": ["しょう"],
  "太": ["たい", "た"],
  "細": ["さい"],
  "新": ["しん"],
  "古": ["こ"],
  "旧": ["きゅう"],
  "元": ["げん", "がん"],
  "本": ["ほん"],
  "末": ["まつ"],
  "初": ["しょ"],
  "始": ["し"],
  "終": ["しゅう"],
  "今": ["こん", "きん"],
  "昔": ["せき"],
  "朝": ["ちょう"],
  "昼": ["ちゅう"],
  "夕": ["せき"],
  "夜": ["や"],
  "晩": ["ばん"],
  "春": ["しゅん"],
  "夏": ["か", "げ"],
  "秋": ["しゅう"],
  "冬": ["とう"],
  "日": ["にち", "じつ"],
  "月": ["げつ", "がつ"],
  "年": ["ねん"],
  "時": ["じ"],
  "星": ["せい", "しょう"],
  "空": ["くう"],
  "天": ["てん"],
  "雲": ["うん"],
  "雨": ["う"],
  "雪": ["せつ"],
  "霜": ["そう"],
  "露": ["ろ"],
  "霧": ["む"],
  "風": ["ふう", "ふ"],
  "雷": ["らい"],
  "光": ["こう"],
  "陽": ["よう"],
  "晴": ["せい"],
  "曇": ["どん"],
  "虹": ["こう"],
  "氷": ["ひょう"],
  "水": ["すい"],
  "火": ["か"],
  "金": ["きん", "こん"],
  "銀": ["ぎん"],
  "銅": ["どう"],
  "鉄": ["てつ"],
  "玉": ["ぎょく"],
  "珠": ["しゅ"],
  "宝": ["ほう"],
  "砂": ["さ", "しゃ"],
  "岸": ["がん"],
  "波": ["は"],
  "潮": ["ちょう"],
  "汐": ["せき"],
  "渚": ["しょ"],
  "湾": ["わん"],
  "泊": ["はく"],
  "船": ["せん"],
  "舟": ["しゅう"],
  "赤": ["せき"],
  "青": ["せい", "しょう"],
  "白": ["はく", "びゃく"],
  "黒": ["こく"],
  "紅": ["こう", "く"],
  "緑": ["りょく"],
  "紫": ["し"],
  "黄": ["おう", "こう"],
  "茶": ["ちゃ", "さ"],
  "藍": ["らん"],
  "翠": ["すい"],
  "碧": ["へき"],
  "朱": ["しゅ"],
  "蒼": ["そう"],
  "灰": ["かい"],
  "彩": ["さい"],
  "色": ["しょく", "しき"],
  "鳥": ["ちょう"],
  "鶴": ["かく"],
  "亀": ["き"],
  "鷹": ["よう"],
  "鷲": ["しゅう"],
  "鳩": ["きゅう"],
  "鷺": ["ろ"],
  "雀": ["じゃく"],
  "燕": ["えん"],
  "鶏": ["けい"],
  "鴨": ["おう"],
  "雁": ["がん"],
  "隼": ["しゅん"],
  "鳳": ["ほう"],
  "凰": ["おう"],
  "龍": ["りゅう"],
  "竜": ["りゅう"],
  "虎": ["こ"],
  "獅": ["し"],
  "熊": ["ゆう"],
  "鹿": ["ろく"],
  "猪": ["ちょ"],
  "兎": ["と"],
  "馬": ["ば"],
  "駒": ["く"],
  "牛": ["ぎゅう"],
  "羊": ["よう"],
  "犬": ["けん"],
  "狐": ["こ"],
  "狸": ["り"],
  "猿": ["えん"],
  "蛇": ["じゃ", "だ"],
  "鯉": ["り"],
  "鮎": ["でん"],
  "鯨": ["げい"],
  "貝": ["ばい"],
  "蝶": ["ちょう"],
  "蛍": ["けい"],
  "蜂": ["ほう"],
  "蟹": ["かい"],
  "亥": ["がい"],
  "寅": ["いん"],
  "辰": ["しん"],
  "巳": ["し"],
  "卯": ["ぼう"],
  "丑": ["ちゅう"],
  "酉": ["ゆう"],
  "戌": ["じゅつ"],
  "午": ["ご"],
  "未": ["み", "び"],
  "申": ["しん"],
  "子": ["し", "す"],
  "人": ["じん", "にん"],
  "男": ["だん", "なん"],
  "女": ["じょ", "にょ"],
  "父": ["ふ"],
  "母": ["ぼ"],
  "兄": ["けい", "きょう"],
  "弟": ["てい", "だい"],
  "姉": ["し"],
  "妹": ["まい"],
  "夫": ["ふ", "ふう"],
  "妻": ["さい"],
  "姫": ["き"],
  "君": ["くん"],
  "王": ["おう"],
  "皇": ["こう", "おう"],
  "帝": ["てい"],
  "后": ["こう", "ご"],
  "妃": ["ひ"],
  "臣": ["しん", "じん"],
  "民": ["みん"],
  "公": ["こう"],
  "侯": ["こう"],
  "伯": ["はく"],
  "爵": ["しゃく"],
  "主": ["しゅ", "す"],
  "氏": ["し"],
  "姓": ["せい", "しょう"],
  "名": ["めい", "みょう"],
  "友": ["ゆう"],
  "朋": ["ほう"],
  "仁": ["じん", "に"],
  "義": ["ぎ"],
  "礼": ["れい", "らい"],
  "智": ["ち"],
  "知": ["ち"],
  "信": ["しん"],
  "誠": ["せい"],
  "忠": ["ちゅう"],
  "孝": ["こう"],
  "悌": ["てい"],
  "徳": ["とく"],
  "勇": ["ゆう"],
  "武": ["ぶ", "む"],
  "剛": ["ごう"],
  "健": ["けん"],
  "強": ["きょう", "ごう"],
  "勝": ["しょう"],
  "賢": ["けん"],
  "聡": ["そう"],
  "慧": ["けい", "え"],
  "哲": ["てつ"],
  "敏": ["びん"],
  "秀": ["しゅう"],
  "英": ["えい"],
  "俊": ["しゅん"],
  "傑": ["けつ"],
  "優": ["ゆう"],
  "良": ["りょう"],
  "善": ["ぜん"],
  "吉": ["きち", "きつ"],
  "喜": ["き"],
  "嘉": ["か"],
  "慶": ["けい"],
  "福": ["ふく"],
  "幸": ["こう"],
  "祥": ["しょう"],
  "祐": ["ゆう"],
  "佑": ["ゆう", "う"],
  "輔": ["ほ", "ふ"],
  "介": ["かい"],
  "助": ["じょ"],
  "亮": ["りょう"],
  "允": ["いん"],
  "丞": ["じょう"],
  "典": ["てん"],
  "則": ["そく"],
  "紀": ["き"],
  "規": ["き"],
  "憲": ["けん"],
  "範": ["はん"],
  "法": ["ほう"],
  "律": ["りつ", "りち"],
  "儀": ["ぎ"],
  "宣": ["せん"],
  "伸": ["しん"],
  "延": ["えん"],
  "展": ["てん"],
  "暢": ["ちょう"],
  "修": ["しゅう", "しゅ"],
  "治": ["じ", "ち"],
  "政": ["せい", "しょう"],
  "正": ["せい", "しょう"],
  "昌": ["しょう"],
  "雅": ["が"],
  "将": ["しょう"],
  "匡": ["きょう"],
  "真": ["しん"],
  "直": ["ちょく", "じき"],
  "尚": ["しょう"],
  "猛": ["もう"],
  "功": ["こう", "く"],
  "勲": ["くん"],
  "績": ["せき"],
  "栄": ["えい"],
  "繁": ["はん"],
  "茂": ["も"],
  "盛": ["せい", "じょう"],
  "豊": ["ほう", "ぶ"],
  "富": ["ふ", "ふう"],
  "裕": ["ゆう"],
  "寛": ["かん"],
  "弘": ["こう", "ぐ"],
  "宏": ["こう"],
  "浩": ["こう"],
  "博": ["はく", "ばく"],
  "洋": ["よう"],
  "拓": ["たく"],
  "啓": ["けい"],
  "恵": ["けい", "え"],
  "愛": ["あい"],
  "恋": ["れん"],
  "美": ["び"],
  "麗": ["れい"],
  "華": ["か", "け"],
  "香": ["こう", "きょう"],
  "芳": ["ほう"],
  "薫": ["くん"],
  "舞": ["ぶ"],
  "歌": ["か"],
  "詩": ["し"],
  "琴": ["きん"],
  "笛": ["てき"],
  "鈴": ["れい", "りん"],
  "音": ["おん", "いん"],
  "響": ["きょう"],
  "奏": ["そう"],
  "楽": ["がく", "らく"],
  "心": ["しん"],
  "思": ["し"],
  "想": ["そう", "そ"],
  "念": ["ねん"],
  "志": ["し"],
  "意": ["い"],
  "希": ["き", "け"],
  "望": ["ぼう", "もう"],
  "夢": ["む"],
  "願": ["がん"],
  "祈": ["き"],
  "叶": ["きょう"],
  "結": ["けつ"],
  "絆": ["はん"],
  "縁": ["えん"],
  "和": ["わ", "お"],
  "平": ["へい", "びょう"],
  "安": ["あん"],
  "康": ["こう"],
  "泰": ["たい"],
  "静": ["せい", "じょう"],
  "穏": ["おん"],
  "寧": ["ねい"],
  "清": ["せい", "しょう"],
  "浄": ["じょう"],
  "澄": ["ちょう"],
  "純": ["じゅん"],
  "潔": ["けつ"],
  "淳": ["じゅん"],
  "敦": ["とん"],
  "篤": ["とく"],
  "厚": ["こう"],
  "温": ["おん"],
  "暖": ["だん"],
  "熱": ["ねつ"],
  "冷": ["れい"],
  "涼": ["りょう"],
  "爽": ["そう"],
  "快": ["かい"],
  "明": ["めい", "みょう"],
  "朗": ["ろう"],
  "晃": ["こう"],
  "昭": ["しょう"],
  "晶": ["しょう"],
  "彰": ["しょう"],
  "章": ["しょう"],
  "顕": ["けん"],
  "耀": ["よう"],
  "輝": ["き"],
  "煌": ["こう"],
  "照": ["しょう"],
  "暉": ["き"],
  "旭": ["きょく"],
  "昇": ["しょう"],
  "登": ["と", "とう"],
  "進": ["しん"],
  "歩": ["ほ", "ぶ"],
  "走": ["そう"],
  "飛": ["ひ"],
  "翔": ["しょう"],
  "翼": ["よく"],
  "羽": ["う"],
  "遊": ["ゆう", "ゆ"],
  "悠": ["ゆう"],
  "遥": ["よう"],
  "遙": ["よう"],
  "永": ["えい"],
  "久": ["きゅう", "く"],
  "恒": ["こう"],
  "常": ["じょう"],
  "継": ["けい"],
  "嗣": ["し"],
  "次": ["じ", "し"],
  "続": ["ぞく"],
  "紡": ["ぼう"],
  "織": ["しょく", "しき"],
  "糸": ["し"],
  "絹": ["けん"],
  "綾": ["りょう"],
  "紗": ["さ", "しゃ"],
  "絵": ["かい", "え"],
  "衣": ["い", "え"],
  "袖": ["しゅう"],
  "帆": ["はん"],
  "航": ["こう"],
  "渉": ["しょう"],
  "亘": ["こう"],
  "達": ["たつ", "だち"],
  "到": ["とう"],
  "至": ["し"],
  "極": ["きょく", "ごく"],
  "究": ["きゅう"],
  "研": ["けん"],
  "磨": ["ま"],
  "学": ["がく"],
  "習": ["しゅう"],
  "教": ["きょう"],
  "育": ["いく"],
  "養": ["よう"],
  "成": ["せい", "じょう"],
  "就": ["しゅう", "じゅ"],
  "為": ["い"],
  "作": ["さく", "さ"],
  "造": ["ぞう"],
  "創": ["そう"],
  "建": ["けん", "こん"],
  "立": ["りつ", "りゅう"],
  "起": ["き"],
  "興": ["こう", "きょう"],
  "発": ["はつ", "ほつ"],
  "生": ["せい", "しょう"],
  "活": ["かつ"],
  "命": ["めい", "みょう"],
  "寿": ["じゅ", "す"],
  "齢": ["れい"],
  "老": ["ろう"],
  "若": ["じゃく"],
  "稚": ["ち"],
  "幼": ["よう"],
  "少": ["しょう"],
  "多": ["た"],
  "全": ["ぜん"],
  "満": ["まん"],
  "充": ["じゅう"],
  "足": ["そく"],
  "有": ["ゆう", "う"],
  "在": ["ざい"],
  "存": ["そん", "ぞん"],
  "保": ["ほ"],
  "守": ["しゅ", "す"],
  "衛": ["えい"],
  "護": ["ご"],
  "防": ["ぼう"],
  "救": ["きゅう"],
  "援": ["えん"],
  "支": ["し"],
  "扶": ["ふ"],
  "導": ["どう"],
  "迪": ["てき"],
  "径": ["けい"],
  "理": ["り"],
  "論": ["ろん"],
  "説": ["せつ"],
  "語": ["ご"],
  "話": ["わ"],
  "言": ["げん", "ごん"],
  "詞": ["し"],
  "文": ["ぶん", "もん"],
  "書": ["しょ"],
  "史": ["し"],
  "記": ["き"],
  "録": ["ろく"],
  "紙": ["し"],
  "筆": ["ひつ"],
  "墨": ["ぼく"],
  "画": ["が", "かく"],
  "写": ["しゃ"],
  "映": ["えい"],
  "影": ["えい"],
  "鏡": ["きょう"],
  "佐": ["さ"],
  "加": ["か"],
  "伊": ["い"],
  "斉": ["せい", "さい"],
  "斎": ["さい"],
  "部": ["ぶ"],
  "阿": ["あ"],
  "須": ["す", "しゅ"],
  "工": ["こう", "く"],
  "菅": ["かん"],
  "片": ["へん"],
  "丸": ["がん"],
  "尾": ["び"],
  "能": ["のう"],
  "濱": ["ひん"],
  "濵": ["ひん"],
  "那": ["な", "だ"],
  "奈": ["な"],
  "乃": ["ない", "だい"],
  "之": ["し"],
  "也": ["や"],
  "哉": ["さい"],
  "斗": ["と"],
  "汰": ["た"],
  "陸": ["りく", "ろく"],
  "颯": ["さつ", "そう"],
  "凛": ["りん"],
  "凜": ["りん"],
  "琉": ["りゅう", "る"],
  "瑠": ["る", "りゅう"],
  "璃": ["り"],
  "咲": ["しょう"],
  "笑": ["しょう"],
  "澪": ["れい"],
  "雫": ["だ"],
  "紬": ["ちゅう"],
  "栞": ["かん"],
  "萌": ["ほう"],
  "茜": ["せん"],
  "絢": ["けん"],
  "瑞": ["ずい"],
  "朔": ["さく"],
  "晄": ["こう"],
  "柊": ["しゅう"],
  "梓": ["し"],
  "樺": ["か"],
  "椋": ["りょう"],
  "槙": ["てん"],
  "槇": ["てん"],
  "牧": ["ぼく"],
  "蒔": ["じ"],
  "巻": ["かん"],
  "麻": ["ま"],
  "摩": ["ま"],
  "弥": ["み", "び"],
  "彌": ["み", "び"],
  "数": ["すう", "す"],
  "親": ["しん"],
  "周": ["しゅう"],
  "慎": ["しん"],
  "誓": ["せい"],
  "幹": ["かん"],
  "己": ["こ", "き"],
  "身": ["しん"],
  "視": ["し"],
  "見": ["けん"],
  "蜜": ["みつ"],
  "密": ["みつ"],
  "倫": ["りん"],
  "宙": ["ちゅう"],
  "昊": ["こう"],
  "穹": ["きゅう"],
  "飴": ["い"],
  "綺": ["き"],
  "采": ["さい"],
  "円": ["えん"],
  "休": ["きゅう"],
  "校": ["こう"],
  "車": ["しゃ"],
  "手": ["しゅ"],
  "出": ["しゅつ", "すい"],
  "早": ["そう"],
  "虫": ["ちゅう"],
  "入": ["にゅう"],
  "目": ["もく", "ぼく"],
  "力": ["りょく", "りき"],
  "引": ["いん"],
  "園": ["えん"],
  "何": ["か"],
  "科": ["か"],
  "回": ["かい", "え"],
  "会": ["かい", "え"],
  "顔": ["がん"],
  "汽": ["き"],
  "帰": ["き"],
  "弓": ["きゅう"],
  "魚": ["ぎょ"],
  "形": ["けい", "ぎょう"],
  "計": ["けい"],
  "交": ["こう"],
  "考": ["こう"],
  "行": ["こう", "ぎょう", "あん"],
  "合": ["ごう"],
  "才": ["さい"],
  "算": ["さん"],
  "止": ["し"],
  "矢": ["し"],
  "自": ["じ", "し"],
  "室": ["しつ"],
  "弱": ["じゃく"],
  "首": ["しゅ"],
  "週": ["しゅう"],
  "食": ["しょく"],
  "図": ["ず", "と"],
  "声": ["せい"],
  "切": ["せつ", "さい"],
  "線": ["せん"],
  "組": ["そ"],
  "体": ["たい", "てい"],
  "台": ["だい", "たい"],
  "通": ["つう"],
  "店": ["てん"],
  "点": ["てん"],
  "電": ["でん"],
  "刀": ["とう"],
  "当": ["とう"],
  "答": ["とう"],
  "頭": ["とう", "ず"],
  "同": ["どう"],
  "読": ["どく"],
  "肉": ["にく"],
  "売": ["ばい"],
  "買": ["ばい"],
  "半": ["はん"],
  "番": ["ばん"],
  "分": ["ぶん", "ふん", "ぶ"],
  "聞": ["ぶん", "もん"],
  "方": ["ほう"],
  "毎": ["まい"],
  "鳴": ["めい"],
  "毛": ["もう"],
  "用": ["よう"],
  "曜": ["よう"],
  "来": ["らい"],
  "悪": ["あく", "お"],
  "暗": ["あん"],
  "医": ["い"],
  "委": ["い"],
  "員": ["いん"],
  "飲": ["いん"],
  "運": ["うん"],
  "泳": ["えい"],
  "化": ["か", "け"],
  "荷": ["か"],
  "界": ["かい"],
  "開": ["かい"],
  "階": ["かい"],
  "寒": ["かん"],
  "感": ["かん"],
  "漢": ["かん"],
  "期": ["き", "ご"],
  "客": ["きゃく", "かく"],
  "急": ["きゅう"],
  "級": ["きゅう"],
  "球": ["きゅう"],
  "去": ["きょ", "こ"],
  "業": ["ぎょう", "ごう"],
  "曲": ["きょく"],
  "局": ["きょく"],
  "苦": ["く"],
  "具": ["ぐ"],
  "係": ["けい"],
  "軽": ["けい"],
  "血": ["けつ"],
  "決": ["けつ"],
  "号": ["ごう"],
  "祭": ["さい"],
  "仕": ["し", "じ"],
  "死": ["し"],
  "使": ["し"],
  "指": ["し"],
  "歯": ["し"],
  "事": ["じ", "ず"],
  "持": ["じ"],
  "式": ["しき"],
  "者": ["しゃ"],
  "取": ["しゅ"],
  "酒": ["しゅ"],
  "受": ["じゅ"],
  "拾": ["しゅう", "じゅう"],
  "集": ["しゅう"],
  "住": ["じゅう"],
  "重": ["じゅう", "ちょう"],
  "宿": ["しゅく"],
  "暑": ["しょ"],
  "消": ["しょう"],
  "商": ["しょう"],
  "乗": ["じょう"],
  "植": ["しょく"],
  "世": ["せい", "せ"],
  "整": ["せい"],
  "相": ["そう", "しょう"],
  "送": ["そう"],
  "息": ["そく"],
  "速": ["そく"],
  "族": ["ぞく"],
  "他": ["た"],
  "打": ["だ"],
  "対": ["たい", "つい"],
  "待": ["たい"],
  "代": ["だい", "たい"],
  "第": ["だい"],
  "題": ["だい"],
  "炭": ["たん"],
  "談": ["だん"],
  "着": ["ちゃく"],
  "注": ["ちゅう"],
  "柱": ["ちゅう"],
  "丁": ["ちょう", "てい"],
  "帳": ["ちょう"],
  "調": ["ちょう"],
  "追": ["つい"],
  "定": ["てい", "じょう"],
  "庭": ["てい"],
  "転": ["てん"],
  "度": ["ど", "と"],
  "投": ["とう"],
  "湯": ["とう"],
  "等": ["とう"],
  "動": ["どう"],
  "童": ["どう"],
  "農": ["のう"],
  "配": ["はい"],
  "倍": ["ばい"],
  "箱": ["そう"],
  "反": ["はん"],
  "板": ["はん"],
  "皮": ["ひ"],
  "悲": ["ひ"],
  "鼻": ["び"],
  "秒": ["びょう"],
  "病": ["びょう"],
  "品": ["ひん"],
  "負": ["ふ"],
  "服": ["ふく"],
  "物": ["ぶつ", "もつ"],
  "返": ["へん"],
  "勉": ["べん"],
  "放": ["ほう"],
  "味": ["み"],
  "面": ["めん"],
  "問": ["もん"],
  "役": ["やく", "えき"],
  "薬": ["やく"],
  "由": ["ゆ", "ゆう"],
  "油": ["ゆ"],
  "予": ["よ"],
  "様": ["よう"],
  "落": ["らく"],
  "流": ["りゅう", "る"],
  "旅": ["りょ"],
  "両": ["りょう"],
  "列": ["れつ"],
  "練": ["れん"],
  "案": ["あん"],
  "以": ["い"],
  "位": ["い"],
  "囲": ["い"],
  "胃": ["い"],
  "印": ["いん"],
  "塩": ["えん"],
  "果": ["か"],
  "貨": ["か"],
  "課": ["か"],
  "改": ["かい"],
  "械": ["かい"],
  "害": ["がい"],
  "各": ["かく"],
  "覚": ["かく"],
  "完": ["かん"],
  "官": ["かん"],
  "管": ["かん"],
  "観": ["かん"],
  "季": ["き"],
  "旗": ["き"],
  "器": ["き"],
  "機": ["き"],
  "議": ["ぎ"],
  "求": ["きゅう"],
  "泣": ["きゅう"],
  "給": ["きゅう"],
  "挙": ["きょ"],
  "漁": ["ぎょ", "りょう"],
  "共": ["きょう"],
  "協": ["きょう"],
  "競": ["きょう", "けい"],
  "訓": ["くん"],
  "軍": ["ぐん"],
  "郡": ["ぐん"],
  "型": ["けい"],
  "景": ["けい"],
  "芸": ["げい"],
  "欠": ["けつ"],
  "験": ["けん", "げん"],
  "固": ["こ"],
  "好": ["こう"],
  "候": ["こう"],
  "告": ["こく"],
  "差": ["さ"],
  "最": ["さい"],
  "材": ["ざい"],
  "昨": ["さく"],
  "札": ["さつ"],
  "刷": ["さつ"],
  "殺": ["さつ"],
  "察": ["さつ"],
  "参": ["さん"],
  "産": ["さん"],
  "散": ["さん"],
  "残": ["ざん"],
  "士": ["し"],
  "司": ["し", "じ"],
  "試": ["し"],
  "児": ["じ", "に"],
  "辞": ["じ"],
  "失": ["しつ"],
  "借": ["しゃく"],
  "祝": ["しゅく", "しゅう"],
  "順": ["じゅん"],
  "唱": ["しょう"],
  "焼": ["しょう"],
  "象": ["しょう", "ぞう"],
  "賞": ["しょう"],
  "省": ["せい", "しょう"],
  "席": ["せき"],
  "積": ["せき"],
  "折": ["せつ"],
  "節": ["せつ", "せち"],
  "戦": ["せん"],
  "選": ["せん"],
  "然": ["ぜん", "ねん"],
  "争": ["そう"],
  "巣": ["そう"],
  "束": ["そく"],
  "卒": ["そつ"],
  "孫": ["そん"],
  "帯": ["たい"],
  "隊": ["たい"],
  "単": ["たん"],
  "置": ["ち"],
  "仲": ["ちゅう"],
  "貯": ["ちょ"],
  "腸": ["ちょう"],
  "停": ["てい"],
  "底": ["てい"],
  "的": ["てき"],
  "伝": ["でん"],
  "徒": ["と"],
  "努": ["ど"],
  "灯": ["とう"],
  "働": ["どう"],
  "特": ["とく"],
  "得": ["とく"],
  "毒": ["どく"],
  "敗": ["はい"],
  "飯": ["はん"],
  "費": ["ひ"],
  "必": ["ひつ"],
  "票": ["ひょう"],
  "標": ["ひょう"],
  "不": ["ふ", "ぶ"],
  "付": ["ふ"],
  "府": ["ふ"],
  "副": ["ふく"],
  "粉": ["ふん"],
  "兵": ["へい", "ひょう"],
  "別": ["べつ"],
  "変": ["へん"],
  "便": ["べん", "びん"],
  "包": ["ほう"],
  "脈": ["みゃく"],
  "無": ["む", "ぶ"],
  "約": ["やく"],
  "要": ["よう"],
  "浴": ["よく"],
  "利": ["り"],
  "料": ["りょう"],
  "量": ["りょう"],
  "輪": ["りん"],
  "類": ["るい"],
  "令": ["れい"],
  "例": ["れい"],
  "歴": ["れき"],
  "連": ["れん"],
  "労": ["ろう"],
  "圧": ["あつ"],
  "移": ["い"],
  "因": ["いん"],
  "営": ["えい"],
  "易": ["えき", "い"],
  "益": ["えき"],
  "液": ["えき"],
  "演": ["えん"],
  "応": ["おう"],
  "往": ["おう"],
  "恩": ["おん"],
  "可": ["か"],
  "仮": ["か", "け"],
  "価": ["か"],
  "過": ["か"],
  "賀": ["が"],
  "解": ["かい", "げ"],
  "格": ["かく", "こう"],
  "確": ["かく"],
  "額": ["がく"],
  "刊": ["かん"],
  "慣": ["かん"],
  "眼": ["がん", "げん"],
  "基": ["き"],
  "寄": ["き"],
  "技": ["ぎ"],
  "逆": ["ぎゃく"],
  "居": ["きょ"],
  "許": ["きょ"],
  "境": ["きょう", "けい"],
  "均": ["きん"],
  "禁": ["きん"],
  "句": ["く"],
  "群": ["ぐん"],
  "経": ["けい", "きょう"],
  "件": ["けん"],
  "券": ["けん"],
  "険": ["けん"],
  "検": ["けん"],
  "限": ["げん"],
  "現": ["げん"],
  "減": ["げん"],
  "故": ["こ"],
  "個": ["こ"],
  "効": ["こう"],
  "耕": ["こう"],
  "鉱": ["こう"],
  "構": ["こう"],
  "講": ["こう"],
  "混": ["こん"],
  "査": ["さ"],
  "再": ["さい", "さ"],
  "災": ["さい"],
  "採": ["さい"],
  "財": ["ざい", "さい"],
  "罪": ["ざい"],
  "雑": ["ざつ", "ぞう"],
  "酸": ["さん"],
  "賛": ["さん"],
  "師": ["し"],
  "資": ["し"],
  "飼": ["し"],
  "示": ["じ", "し"],
  "似": ["じ"],
  "識": ["しき"],
  "質": ["しつ", "しち"],
  "舎": ["しゃ"],
  "謝": ["しゃ"],
  "授": ["じゅ"],
  "述": ["じゅつ"],
  "術": ["じゅつ"],
  "準": ["じゅん"],
  "序": ["じょ"],
  "招": ["しょう"],
  "承": ["しょう"],
  "証": ["しょう"],
  "条": ["じょう"],
  "状": ["じょう"],
  "情": ["じょう", "せい"],
  "職": ["しょく"],
  "制": ["せい"],
  "性": ["せい", "しょう"],
  "勢": ["せい"],
  "精": ["せい", "しょう"],
  "製": ["せい"],
  "税": ["ぜい"],
  "責": ["せき"],
  "接": ["せつ"],
  "設": ["せつ"],
  "舌": ["ぜつ"],
  "絶": ["ぜつ"],
  "銭": ["せん"],
  "祖": ["そ"],
  "素": ["そ", "す"],
  "総": ["そう"],
  "像": ["ぞう"],
  "増": ["ぞう"],
  "測": ["そく"],
  "属": ["ぞく"],
  "率": ["そつ", "りつ"],
  "損": ["そん"],
  "退": ["たい"],
  "貸": ["たい"],
  "態": ["たい"],
  "団": ["だん", "とん"],
  "断": ["だん"],
  "築": ["ちく"],
  "張": ["ちょう"],
  "提": ["てい"],
  "程": ["てい"],
  "適": ["てき"],
  "敵": ["てき"],
  "統": ["とう"],
  "独": ["どく"],
  "任": ["にん"],
  "燃": ["ねん"],
  "破": ["は"],
  "犯": ["はん"],
  "判": ["はん", "ばん"],
  "版": ["はん"],
  "比": ["ひ"],
  "肥": ["ひ"],
  "非": ["ひ"],
  "備": ["び"],
  "俵": ["ひょう"],
  "評": ["ひょう"],
  "貧": ["ひん", "びん"],
  "布": ["ふ"],
  "婦": ["ふ"],
  "復": ["ふく"],
  "複": ["ふく"],
  "仏": ["ぶつ"],
  "編": ["へん"],
  "弁": ["べん"],
  "墓": ["ぼ"],
  "報": ["ほう"],
  "貿": ["ぼう"],
  "暴": ["ぼう"],
  "務": ["む"],
  "迷": ["めい"],
  "綿": ["めん"],
  "輸": ["ゆ"],
  "余": ["よ"],
  "預": ["よ"],
  "容": ["よう"],
  "略": ["りゃく"],
  "留": ["りゅう", "る"],
  "領": ["りょう"],
  "異": ["い"],
  "遺": ["い", "ゆい"],
  "域": ["いき"],
  "宇": ["う"],
  "沿": ["えん"],
  "我": ["が"],
  "拡": ["かく"],
  "革": ["かく"],
  "閣": ["かく"],
  "割": ["かつ"],
  "干": ["かん"],
  "看": ["かん"],
  "簡": ["かん"],
  "危": ["き"],
  "机": ["き"],
  "揮": ["き"],
  "貴": ["き"],
  "疑": ["ぎ"],
  "吸": ["きゅう"],
  "供": ["きょう", "く"],
  "胸": ["きょう"],
  "勤": ["きん", "ごん"],
  "筋": ["きん"],
  "系": ["けい"],
  "敬": ["けい"],
  "警": ["けい"],
  "劇": ["げき"],
  "激": ["げき"],
  "穴": ["けつ"],
  "権": ["けん", "ごん"],
  "源": ["げん"],
  "厳": ["げん", "ごん"],
  "呼": ["こ"],
  "誤": ["ご"],
  "降": ["こう"],
  "鋼": ["こう"],
  "刻": ["こく"],
  "穀": ["こく"],
  "骨": ["こつ"],
  "困": ["こん"],
  "座": ["ざ"],
  "済": ["さい"],
  "裁": ["さい"],
  "策": ["さく"],
  "冊": ["さつ", "さく"],
  "蚕": ["さん"],
  "私": ["し"],
  "姿": ["し"],
  "誌": ["し"],
  "磁": ["じ"],
  "射": ["しゃ"],
  "捨": ["しゃ"],
  "尺": ["しゃく"],
  "収": ["しゅう"],
  "宗": ["しゅう", "そう"],
  "衆": ["しゅう", "しゅ"],
  "従": ["じゅう", "しょう"],
  "縮": ["しゅく"],
  "熟": ["じゅく"],
  "処": ["しょ"],
  "署": ["しょ"],
  "諸": ["しょ"],
  "除": ["じょ"],
  "傷": ["しょう"],
  "障": ["しょう"],
  "蒸": ["じょう"],
  "針": ["しん"],
  "垂": ["すい"],
  "推": ["すい"],
  "寸": ["すん"],
  "聖": ["せい", "しょう"],
  "専": ["せん"],
  "洗": ["せん"],
  "染": ["せん"],
  "窓": ["そう"],
  "装": ["そう", "しょう"],
  "層": ["そう"],
  "操": ["そう"],
  "臓": ["ぞう"],
  "尊": ["そん"],
  "宅": ["たく"],
  "担": ["たん"],
  "探": ["たん"],
  "誕": ["たん"],
  "段": ["だん"],
  "値": ["ち"],
  "著": ["ちょ"],
  "庁": ["ちょう"],
  "頂": ["ちょう"],
  "賃": ["ちん"],
  "痛": ["つう"],
  "討": ["とう"],
  "党": ["とう"],
  "糖": ["とう"],
  "難": ["なん"],
  "乳": ["にゅう"],
  "認": ["にん"],
  "納": ["のう", "とう"],
  "脳": ["のう"],
  "派": ["は"],
  "拝": ["はい"],
  "背": ["はい"],
  "肺": ["はい"],
  "俳": ["はい"],
  "班": ["はん"],
  "否": ["ひ"],
  "批": ["ひ"],
  "秘": ["ひ"],
  "腹": ["ふく"],
  "奮": ["ふん"],
  "並": ["へい"],
  "陛": ["へい"],
  "閉": ["へい"],
  "補": ["ほ"],
  "暮": ["ぼ"],
  "訪": ["ほう"],
  "亡": ["ぼう"],
  "忘": ["ぼう"],
  "棒": ["ぼう"],
  "枚": ["まい"],
  "幕": ["まく", "ばく"],
  "盟": ["めい"],
  "模": ["も", "ぼ"],
  "訳": ["やく"],
  "郵": ["ゆう"],
  "欲": ["よく"],
  "翌": ["よく"],
  "乱": ["らん"],
  "卵": ["らん"],
  "覧": ["らん"],
  "臨": ["りん"],
  "亜": ["あ"],
  "哀": ["あい"],
  "握": ["あく"],
  "依": ["い", "え"],
  "威": ["い"],
  "偉": ["い"],
  "維": ["い"],
  "緯": ["い"],
  "壱": ["いち"],
  "芋": ["う"],
  "陰": ["いん"],
  "隠": ["いん"],
  "鋭": ["えい"],
  "越": ["えつ"],
  "煙": ["えん"],
  "鉛": ["えん"],
  "汚": ["お"],
  "押": ["おう"],
  "憶": ["おく"],
  "菓": ["か"],
  "暇": ["か"],
  "箇": ["か"],
  "戒": ["かい"],
  "皆": ["かい"],
  "壊": ["かい"],
  "較": ["かく"],
  "獲": ["かく"],
  "刈": ["がい"],
  "甘": ["かん"],
  "汗": ["かん"],
  "乾": ["かん", "けん"],
  "勧": ["かん"],
  "歓": ["かん"],
  "監": ["かん"],
  "環": ["かん"],
  "鑑": ["かん"],
  "含": ["がん"],
  "奇": ["き"],
  "鬼": ["き"],
  "幾": ["き"],
  "戯": ["ぎ"],
  "詰": ["きつ"],
  "却": ["きゃく"],
  "脚": ["きゃく"],
  "及": ["きゅう"],
  "朽": ["きゅう"],
  "巨": ["きょ"],
  "拠": ["きょ", "こ"],
  "距": ["きょ"],
  "御": ["ぎょ", "ご"],
  "凶": ["きょう"],
  "叫": ["きょう"],
  "狂": ["きょう"],
  "況": ["きょう"],
  "恐": ["きょう"],
  "驚": ["きょう"],
  "仰": ["ぎょう", "こう"],
  "駆": ["く"],
  "屈": ["くつ"],
  "掘": ["くつ"],
  "傾": ["けい"],
  "迎": ["げい"],
  "撃": ["げき"],
  "肩": ["けん"],
  "兼": ["けん"],
  "剣": ["けん"],
  "軒": ["けん"],
  "圏": ["けん"],
  "堅": ["けん"],
  "遣": ["けん"],
  "玄": ["げん"],
  "枯": ["こ"],
  "誇": ["こ"],
  "鼓": ["こ"],
  "互": ["ご"],
  "抗": ["こう"],
  "攻": ["こう"],
  "更": ["こう"],
  "荒": ["こう"],
  "項": ["こう"],
  "稿": ["こう"],
  "豪": ["ごう"],
  "婚": ["こん"],
  "鎖": ["さ"],
  "歳": ["さい", "せい"],
  "載": ["さい"],
  "剤": ["ざい"],
  "惨": ["さん"],
  "旨": ["し"],
  "伺": ["し"],
  "刺": ["し"],
  "脂": ["し"],
  "雌": ["し"],
  "執": ["しつ", "しゅう"],
  "斜": ["しゃ"],
  "煮": ["しゃ"],
  "釈": ["しゃく"],
  "寂": ["じゃく", "せき"],
  "狩": ["しゅ"],
  "趣": ["しゅ"],
  "需": ["じゅ"],
  "襲": ["しゅう"],
  "柔": ["じゅう", "にゅう"],
  "獣": ["じゅう"],
  "瞬": ["しゅん"],
  "旬": ["じゅん", "しゅん"],
  "巡": ["じゅん"],
  "盾": ["じゅん"],
  "召": ["しょう"],
  "床": ["しょう"],
  "称": ["しょう"],
  "紹": ["しょう"],
  "詳": ["しょう"],
  "丈": ["じょう"],
  "畳": ["じょう"],
  "殖": ["しょく"],
  "飾": ["しょく"],
  "触": ["しょく"],
  "侵": ["しん"],
  "振": ["しん"],
  "浸": ["しん"],
  "寝": ["しん"],
  "震": ["しん"],
  "薪": ["しん"],
  "尽": ["じん"],
  "陣": ["じん"],
  "尋": ["じん"],
  "吹": ["すい"],
  "是": ["ぜ"],
  "征": ["せい"],
  "跡": ["せき"],
  "占": ["せん"],
  "扇": ["せん"],
  "鮮": ["せん"],
  "訴": ["そ"],
  "僧": ["そう"],
  "燥": ["そう"],
  "騒": ["そう"],
  "贈": ["ぞう", "そう"],
  "即": ["そく"],
  "俗": ["ぞく"],
  "耐": ["たい"],
  "替": ["たい"],
  "濁": ["だく"],
  "脱": ["だつ"],
  "丹": ["たん"],
  "淡": ["たん"],
  "嘆": ["たん"],
  "弾": ["だん"],
  "恥": ["ち"],
  "致": ["ち"],
  "遅": ["ち"],
  "蓄": ["ちく"],
  "沖": ["ちゅう"],
  "跳": ["ちょう"],
  "徴": ["ちょう"],
  "沈": ["ちん"],
  "珍": ["ちん"],
  "抵": ["てい"],
  "摘": ["てき"],
  "滴": ["てき"],
  "添": ["てん"],
  "吐": ["と"],
  "途": ["と"],
  "奴": ["ど"],
  "怒": ["ど"],
  "逃": ["とう"],
  "倒": ["とう"],
  "唐": ["とう"],
  "透": ["とう"],
  "盗": ["とう"],
  "塔": ["とう"],
  "踏": ["とう"],
  "闘": ["とう"],
  "胴": ["どう"],
  "突": ["とつ"],
  "鈍": ["どん"],
  "弐": ["に"],
  "悩": ["のう"],
  "濃": ["のう"],
  "杯": ["はい"],
  "輩": ["はい"],
  "拍": ["はく", "ひょう"],
  "迫": ["はく"],
  "薄": ["はく"],
  "爆": ["ばく"],
  "髪": ["はつ"],
  "抜": ["ばつ"],
  "罰": ["ばつ", "ばち"],
  "般": ["はん"],
  "販": ["はん"],
  "搬": ["はん"],
  "盤": ["ばん"],
  "彼": ["ひ"],
  "疲": ["ひ"],
  "被": ["ひ"],
  "避": ["ひ"],
  "微": ["び"],
  "匹": ["ひつ"],
  "描": ["びょう"],
  "怖": ["ふ"],
  "浮": ["ふ"],
  "普": ["ふ"],
  "腐": ["ふ"],
  "敷": ["ふ"],
  "膚": ["ふ"],
  "賦": ["ふ"],
  "幅": ["ふく"],
  "払": ["ふつ"],
  "噴": ["ふん"],
  "柄": ["へい"],
  "壁": ["へき"],
  "捕": ["ほ"],
  "舗": ["ほ"],
  "抱": ["ほう"],
  "砲": ["ほう"],
  "忙": ["ぼう"],
  "坊": ["ぼう"],
  "肪": ["ぼう"],
  "冒": ["ぼう"],
  "傍": ["ぼう"],
  "帽": ["ぼう"],
  "凡": ["ぼん", "はん"],
  "盆": ["ぼん"],
  "慢": ["まん"],
  "漫": ["まん"],
  "妙": ["みょう"],
  "眠": ["みん"],
  "矛": ["む"],
  "娘": ["じょう"],
  "網": ["もう"],
  "黙": ["もく"],
  "紋": ["もん"],
  "躍": ["やく"],
  "雄": ["ゆう"],
  "与": ["よ"],
  "誉": ["よ"],
  "溶": ["よう"],
  "腰": ["よう"],
  "踊": ["よう"],
  "謡": ["よう"],
  "頼": ["らい"],
  "絡": ["らく"],
  "欄": ["らん"],
  "離": ["り"],
  "粒": ["りゅう"],
  "慮": ["りょ"],
  "療": ["りょう"],
  "隣": ["りん"],
  "涙": ["るい"],
  "隷": ["れい"],
  "暦": ["れき"],
  "劣": ["れつ"],
  "烈": ["れつ"],
  "郎": ["ろう"],
  "惑": ["わく"],
  "腕": ["わん"],
  "斐": ["ひ"],
  "惟": ["い", "ゆい"],
  "李": ["り"],
  "侑": ["ゆう"],
  "怜": ["れい"],
  "玲": ["れい"],
  "琳": ["りん"],
  "瑛": ["えい"],
  "瑶": ["よう"],
  "瑚": ["こ"],
  "珊": ["さん"],
  "琥": ["こ"],
  "珀": ["はく"],
  "遼": ["りょう"],
  "諒": ["りょう"],
  "稜": ["りょう"],
  "綸": ["りん"],
  "紘": ["こう"],
  "繭": ["けん"],
  "菫": ["きん"],
  "蕾": ["らい"],
  "薇": ["び"],
  "葦": ["い"],
  "芦": ["ろ"],
  "蘇": ["そ", "す"],
  "茅": ["ぼう"],
  "萱": ["けん"],
  "荻": ["てき"],
  "蔦": ["ちょう"],
  "葛": ["かつ"],
  "蒲": ["ほ", "ぶ"],
  "菖": ["しょう"],
  "芹": ["きん"],
  "蓉": ["よう"],
  "芙": ["ふ"],
  "苺": ["ばい"],
  "蓬": ["ほう"],
  "杜": ["と", "ず"],
  "柑": ["かん"],
  "槻": ["き"],
  "樟": ["しょう"],
  "欅": ["きょ"],
  "楢": ["しゅう"],
  "梢": ["しょう"],
  "桔": ["きつ"],
  "梗": ["こう"],
  "榛": ["しん"],
  "椰": ["や"],
  "檀": ["だん", "たん"],
  "櫻": ["おう"],
  "楼": ["ろう"],
  "琢": ["たく"],
  "瑳": ["さ"],
  "鐘": ["しょう"],
  "錦": ["きん"],
  "鎌": ["れん"],
  "鍋": ["か"],
  "鍵": ["けん"],
  "錬": ["れん"],
  "鎮": ["ちん"],
  "嵐": ["らん"],
  "嶺": ["れい", "りょう"],
  "嵩": ["すう"],
  "峻": ["しゅん"],
  "巌": ["がん"],
  "渓": ["けい"],
  "洸": ["こう"],
  "湧": ["ゆう"],
  "漣": ["れん"],
  "滉": ["こう"],
  "潤": ["じゅん"],
  "瀬": ["らい"],
  "灘": ["たん"],
  "汀": ["てい"],
  "沙": ["さ", "しゃ"],
  "洲": ["しゅう"],
  "湘": ["しょう"],
  "滋": ["じ"],
  "渥": ["あく"],
  "溢": ["いつ"],
  "漆": ["しつ"],
  "濠": ["ごう"],
  "燈": ["とう"],
  "炎": ["えん"],
  "焔": ["えん"],
  "熙": ["き"],
  "燦": ["さん"],
  "昂": ["こう"],
  "晟": ["せい"],
  "晏": ["あん"],
  "暁": ["ぎょう"],
  "曙": ["しょ"],
  "旺": ["おう"],
  "昴": ["ぼう"],
  "晋": ["しん"],
  "晨": ["しん"],
  "肇": ["ちょう"],
  "胡": ["こ", "ご"],
  "脩": ["しゅう"],
  "舜": ["しゅん"],
  "艶": ["えん"],
  "芯": ["しん"],
  "苑": ["えん", "おん"],
  "荘": ["そう", "しょう"],
  "莞": ["かん"],
  "萬": ["まん", "ばん"],
  "衿": ["きん"],
  "襟": ["きん"],
  "詢": ["じゅん"],
  "諄": ["じゅん"],
  "謙": ["けん"],
  "讃": ["さん"],
  "貫": ["かん"],
  "赳": ["きゅう"],
  "迅": ["じん"],
  "逸": ["いつ"],
  "郁": ["いく"],
  "醇": ["じゅん"],
  "釣": ["ちょう"],
  "銑": ["せん"],
  "鎧": ["がい"],
  "閃": ["せん"],
  "閑": ["かん"],
  "隆": ["りゅう"],
  "雛": ["すう"],
  "霞": ["か"],
  "靖": ["せい"],
  "鞠": ["きく"],
  "頌": ["しょう"],
  "馨": ["けい"],
  "駿": ["しゅん"],
  "魁": ["かい"],
  "鯛": ["ちょう"],
  "鴻": ["こう"],
  "鵬": ["ほう"],
  "鷗": ["おう"],
  "鴎": ["おう"],
  "麒": ["き"],
  "麟": ["りん"],
  "黎": ["れい"],
  "黛": ["たい"],
  "鼎": ["てい"],
  "甫": ["ほ"],
  "亨": ["きょう", "こう"],
  "亙": ["こう"],
  "伍": ["ご"],
  "伶": ["れい"],
  "倖": ["こう"],
  "偲": ["し"],
  "凌": ["りょう"],
  "凱": ["がい"],
  "勁": ["けい"],
  "匠": ["しょう"],
  "卓": ["たく"],
  "叡": ["えい"],
  "圭": ["けい"],
  "堯": ["ぎょう"],
  "壮": ["そう"],
  "奎": ["けい"],
  "嬉": ["き"],
  "孜": ["し"],
  "宥": ["ゆう"],
  "巧": ["こう"],
  "巴": ["は"],
  "弦": ["げん"],
  "彗": ["すい"],
  "徠": ["らい"],
  "恭": ["きょう"],
  "悟": ["ご"],
  "惇": ["じゅん"],
  "慈": ["じ"],
  "憧": ["しょう", "どう"],
  "懐": ["かい"],
  "拳": ["けん"],
  "捷": ["しょう"],
  "旦": ["たん", "だん"],
  "曽": ["そう", "ぞ"],
  "杵": ["しょ"],
  "梧": ["ご"],
  "梨": ["り"],
  "樂": ["がく", "らく"],
  "槐": ["かい"],
  "檎": ["きん", "ご"],
  "爾": ["じ", "に"],
  "珂": ["か"],
  "皐": ["こう"],
  "眞": ["しん"],
  "睦": ["ぼく"],
  "矩": ["く"],
  "碩": ["せき"],
  "禄": ["ろく"],
  "禎": ["てい"],
  "稀": ["き"],
  "穣": ["じょう"],
  "竣": ["しゅん"],
  "笙": ["しょう"],
  "篠": ["しょう"],
  "綜": ["そう"],
  "緋": ["ひ"],
  "縞": ["こう"],
  "胤": ["いん"],
  "蕉": ["しょう"],
  "薙": ["てい"],
  "詠": ["えい"],
  "譲": ["じょう"],
  "邑": ["ゆう"],
  "醍": ["だい"],
  "醐": ["ご"],
  "馳": ["ち"],
  "鮫": ["こう"],
  "乙": ["おつ"],
  "仙": ["せん"],
  "佳": ["か"],
  "克": ["こく"],
  "函": ["かん"],
  "堺": ["かい"],
  "如": ["じょ", "にょ"],
  "媛": ["えん"],
  "尼": ["に"],
  "岐": ["き", "ぎ"],
  "幌": ["こう"],
  "彦": ["げん"],
  "忍": ["にん"],
  "柴": ["さい"],
  "桑": ["そう"],
  "樋": ["とう"],
  "樽": ["そん"],
  "毅": ["き"],
  "気": ["き", "け"],
  "渋": ["じゅう"],
  "潟": ["せき"],
  "甲": ["こう", "かん"],
  "瞳": ["どう"],
  "縄": ["じょう"],
  "耶": ["や"],
  "茨": ["し"],
  "袋": ["たい"],
  "覇": ["は"],
  "阜": ["ふ"],
  "阪": ["はん"],
  "韓": ["かん"],
  "伴": ["はん", "ばん"],
  "企": ["き"],
  "幡": ["はん", "まん"],
  "筑": ["ちく"],
  "播": ["は", "ばん"],
  "騨": ["だ"],
  "摂": ["せつ"],
  "但": ["たん"],
  "享": ["きょう"],
  "喬": ["きょう"],
  "冴": ["ご"],
  "楪": ["ちょう"],
  "楸": ["しゅう"],
  "櫂": ["とう"],
  "煉": ["れん"],
  "燿": ["よう"],
  "祢": ["ね", "でい"],
  "禰": ["ね", "でい"],
  "狼": ["ろう"],
  "彪": ["ひょう"],
  "鶯": ["おう"],
  "玖": ["きゅう", "く"],
  "廉": ["れん"],
  "崚": ["りょう"],
  "尭": ["ぎょう"],
  "毬": ["きゅう"],
  "絃": ["げん"],
  "唄": ["ばい"],
  "蔭": ["いん"],
  "塙": ["かく"],
  "籠": ["ろう"],
  "釜": ["ふ"],
  "窪": ["わ"],
  "薮": ["そう"],
  "藪": ["そう"],
  "鍬": ["しゅう"],
  "梶": ["び"],
  "杭": ["こう"],
  "橡": ["しょう"],
  "苔": ["たい"],
  "蘆": ["ろ"],
  "薗": ["えん"],
  "巽": ["そん"],
  "雉": ["ち"],
  "鵜": ["てい"],
  "徹": ["てつ"],
  "宍": ["にく"],
  "蛭": ["しつ", "てつ"],
  "鱒": ["そん"],
  "鰐": ["がく"],
  "烏": ["う", "お"],
  "鴉": ["あ"],
  "鵺": ["や"],
  "屍": ["し"]
 },
 "kun": {
  "一": ["かず", "ひと", "はじめ"],
  "二": ["ふた", "ふ", "つぐ"],
  "三": ["み", "みつ", "さぶ"],
  "四": ["よ", "よん"],
  "五": ["いつ"],
  "六": ["む"],
  "七": ["なな"],
  "八": ["や", "やつ"],
  "九": ["ここの"],
  "十": ["とお", "と"],
  "百": ["もも"],
  "千": ["ち", "かず", "ゆき"],
  "万": ["かず", "よろず"],
  "山": ["やま"],
  "川": ["かわ"],
  "田": ["た"],
  "野": ["の"],
  "原": ["はら"],
  "林": ["はやし"],
  "森": ["もり"],
  "木": ["き", "こ"],
  "竹": ["たけ"],
  "松": ["まつ"],
  "杉": ["すぎ"],
  "桜": ["さくら"],
  "梅": ["うめ"],
  "桃": ["もも"],
  "柳": ["やなぎ"],
  "桐": ["きり"],
  "楓": ["かえで"],
  "椿": ["つばき"],
  "蓮": ["はす"],
  "葵": ["あおい", "まもる"],
  "萩": ["はぎ"],
  "藤": ["ふじ"],
  "葉": ["は"],
  "花": ["はな"],
  "草": ["くさ"],
  "芝": ["しば"],
  "苗": ["なえ"],
  "稲": ["いね", "いな"],
  "米": ["よね", "こめ"],
  "麦": ["むぎ"],
  "豆": ["まめ"],
  "栗": ["くり"],
  "柿": ["かき"],
  "橘": ["たちばな"],
  "榊": ["さかき"],
  "楠": ["くす", "くすのき"],
  "樫": ["かし"],
  "椎": ["しい"],
  "檜": ["ひのき"],
  "桧": ["ひのき"],
  "柏": ["かしわ"],
  "樹": ["き", "いつき", "しげ"],
  "枝": ["えだ"],
  "根": ["ね"],
  "株": ["かぶ"],
  "芽": ["め"],
  "実": ["み", "みのる", "さね"],
  "種": ["たね"],
  "穂": ["ほ"],
  "稔": ["みのる", "とし"],
  "菜": ["な"],
  "茉": ["ま"],
  "杏": ["あんず"],
  "柚": ["ゆず"],
  "桂": ["かつら"],
  "楊": ["やなぎ"],
  "榎": ["えのき"],
  "棚": ["たな"],
  "堀": ["ほり"],
  "池": ["いけ"],
  "沼": ["ぬま"],
  "湖": ["みずうみ"],
  "海": ["うみ", "み"],
  "浜": ["はま"],
  "浦": ["うら"],
  "島": ["しま"],
  "嶋": ["しま"],
  "岡": ["おか"],
  "丘": ["おか"],
  "岳": ["たけ"],
  "峰": ["みね"],
  "峯": ["みね"],
  "坂": ["さか"],
  "谷": ["たに", "や"],
  "沢": ["さわ"],
  "澤": ["さわ"],
  "滝": ["たき"],
  "瀧": ["たき"],
  "泉": ["いずみ"],
  "井": ["い"],
  "江": ["え"],
  "河": ["かわ"],
  "津": ["つ"],
  "港": ["みなと"],
  "湊": ["みなと"],
  "渡": ["わたる", "わた"],
  "橋": ["はし"],
  "石": ["いし"],
  "岩": ["いわ"],
  "磯": ["いそ"],
  "崎": ["さき"],
  "埼": ["さい", "さき"],
  "岬": ["みさき"],
  "畑": ["はた", "はたけ"],
  "畠": ["はた", "はたけ"],
  "村": ["むら"],
  "町": ["まち"],
  "里": ["さと"],
  "郷": ["さと"],
  "都": ["みやこ"],
  "京": ["みやこ"],
  "市": ["いち"],
  "州": ["す", "くに"],
  "国": ["くに"],
  "邦": ["くに"],
  "城": ["しろ", "き"],
  "宮": ["みや"],
  "神": ["かみ", "かん", "こう"],
  "社": ["やしろ", "こそ"],
  "寺": ["てら"],
  "殿": ["との", "どの"],
  "門": ["かど", "と"],
  "戸": ["と", "べ"],
  "家": ["いえ", "や"],
  "屋": ["や"],
  "倉": ["くら"],
  "蔵": ["くら"],
  "庫": ["くら"],
  "館": ["たて", "やかた"],
  "塚": ["つか"],
  "垣": ["かき"],
  "堤": ["つつみ"],
  "関": ["せき"],
  "所": ["ところ"],
  "場": ["ば"],
  "土": ["つち"],
  "道": ["みち"],
  "路": ["みち", "じ"],
  "街": ["まち"],
  "口": ["くち", "ぐち"],
  "内": ["うち"],
  "外": ["そと", "と", "ほか"],
  "上": ["うえ", "かみ", "うわ"],
  "下": ["した", "しも"],
  "中": ["なか"],
  "前": ["まえ", "さき"],
  "後": ["うしろ", "あと", "のち"],
  "左": ["ひだり"],
  "右": ["みぎ"],
  "東": ["ひがし", "あずま", "はる"],
  "西": ["にし"],
  "南": ["みなみ"],
  "北": ["きた"],
  "央": ["なか"],
  "間": ["ま", "あい"],
  "奥": ["おく"],
  "端": ["はし", "はた"],
  "辺": ["べ", "あたり"],
  "際": ["きわ"],
  "側": ["がわ", "かわ"],
  "脇": ["わき"],
  "横": ["よこ"],
  "縦": ["たて"],
  "角": ["かど", "すみ", "つの"],
  "隅": ["すみ"],
  "向": ["むかい", "むこう"],
  "表": ["おもて"],
  "裏": ["うら"],
  "近": ["ちか"],
  "遠": ["とお"],
  "高": ["たか"],
  "低": ["ひく"],
  "深": ["ふか", "み"],
  "浅": ["あさ"],
  "長": ["なが", "おさ"],
  "短": ["みじか"],
  "広": ["ひろ"],
  "狭": ["せま"],
  "大": ["おお", "ひろ", "まさる"],
  "小": ["こ", "お", "ちい"],
  "太": ["ふと"],
  "細": ["ほそ"],
  "新": ["あら", "にい", "あたらし"],
  "古": ["ふる"],
  "元": ["もと", "はじめ"],
  "本": ["もと"],
  "末": ["すえ"],
  "初": ["はつ", "うい"],
  "始": ["はじめ"],
  "終": ["おわり"],
  "今": ["いま"],
  "昔": ["むかし"],
  "朝": ["あさ", "とも"],
  "昼": ["ひる"],
  "夕": ["ゆう"],
  "夜": ["よ", "よる"],
  "春": ["はる"],
  "夏": ["なつ"],
  "秋": ["あき"],
  "冬": ["ふゆ"],
  "日": ["ひ", "か", "あき"],
  "月": ["つき"],
  "年": ["とし"],
  "時": ["とき"],
  "星": ["ほし"],
  "空": ["そら"],
  "天": ["あま", "あめ", "たか"],
  "雲": ["くも"],
  "雨": ["あめ"],
  "雪": ["ゆき"],
  "霜": ["しも"],
  "露": ["つゆ"],
  "霧": ["きり"],
  "風": ["かぜ", "かざ"],
  "雷": ["いかずち"],
  "光": ["ひかり", "ひかる", "みつ", "てる"],
  "陽": ["ひ", "はる", "あき", "きよ"],
  "晴": ["はる"],
  "曇": ["くもり"],
  "虹": ["にじ"],
  "氷": ["こおり", "ひ"],
  "水": ["みず", "み"],
  "火": ["ひ", "ほ"],
  "金": ["かね", "かな"],
  "銀": ["しろがね"],
  "銅": ["あかがね"],
  "鉄": ["くろがね", "かね"],
  "玉": ["たま"],
  "珠": ["たま"],
  "宝": ["たから"],
  "砂": ["すな"],
  "岸": ["きし"],
  "波": ["なみ"],
  "潮": ["しお"],
  "汐": ["しお"],
  "渚": ["なぎさ"],
  "泊": ["とまり"],
  "船": ["ふね", "ふな"],
  "舟": ["ふね", "ふな"],
  "赤": ["あか"],
  "青": ["あお"],
  "白": ["しろ", "しら"],
  "黒": ["くろ"],
  "紅": ["べに", "くれない"],
  "緑": ["みどり"],
  "紫": ["むらさき"],
  "黄": ["き"],
  "藍": ["あい"],
  "翠": ["みどり"],
  "碧": ["あお", "みどり"],
  "朱": ["あけ"],
  "蒼": ["あお"],
  "灰": ["はい"],
  "彩": ["あや", "いろどり"],
  "色": ["いろ"],
  "鳥": ["とり", "と"],
  "鶴": ["つる"],
  "亀": ["かめ"],
  "鷹": ["たか"],
  "鷲": ["わし"],
  "鳩": ["はと"],
  "鷺": ["さぎ"],
  "雀": ["すずめ"],
  "燕": ["つばめ", "つばくろ"],
  "鶏": ["とり", "にわとり"],
  "鴨": ["かも"],
  "雁": ["かり"],
  "隼": ["はやぶさ", "はや"],
  "鳳": ["おおとり"],
  "龍": ["たつ"],
  "竜": ["たつ"],
  "虎": ["とら"],
  "熊": ["くま"],
  "鹿": ["しか", "か"],
  "猪": ["い", "いのしし"],
  "兎": ["うさぎ"],
  "馬": ["うま", "ま"],
  "駒": ["こま"],
  "牛": ["うし"],
  "羊": ["ひつじ"],
  "犬": ["いぬ"],
  "狐": ["きつね"],
  "狸": ["たぬき"],
  "猿": ["さる"],
  "蛇": ["へび"],
  "鯉": ["こい"],
  "鮎": ["あゆ"],
  "鯨": ["くじら"],
  "貝": ["かい"],
  "蛍": ["ほたる"],
  "蜂": ["はち"],
  "蟹": ["かに"],
  "亥": ["い"],
  "寅": ["とら"],
  "辰": ["たつ"],
  "巳": ["み"],
  "卯": ["う"],
  "丑": ["うし"],
  "酉": ["とり"],
  "戌": ["いぬ"],
  "午": ["うま"],
  "未": ["ひつじ"],
  "申": ["さる", "のぶ"],
  "子": ["こ", "ね"],
  "人": ["ひと", "と"],
  "男": ["お", "おとこ"],
  "女": ["め", "おんな"],
  "父": ["ちち"],
  "母": ["はは", "も"],
  "兄": ["あに", "え"],
  "弟": ["おとうと", "おと"],
  "姉": ["あね"],
  "妹": ["いもうと"],
  "夫": ["お", "おっと"],
  "妻": ["つま"],
  "姫": ["ひめ"],
  "君": ["きみ"],
  "王": ["きみ"],
  "皇": ["すめら"],
  "帝": ["みかど"],
  "后": ["きさき"],
  "妃": ["きさき"],
  "臣": ["おみ"],
  "民": ["たみ"],
  "公": ["きみ", "とも"],
  "主": ["ぬし", "もり", "かず"],
  "氏": ["うじ"],
  "名": ["な"],
  "友": ["とも"],
  "朋": ["とも"],
  "仁": ["ひと", "まさし", "ひとし"],
  "義": ["よし"],
  "礼": ["あや", "のり"],
  "智": ["とも", "さとし", "さと"],
  "知": ["とも", "さと", "のり"],
  "信": ["のぶ", "まこと"],
  "誠": ["まこと", "のぶ", "たか"],
  "忠": ["ただ"],
  "孝": ["たか", "のり"],
  "悌": ["やす"],
  "徳": ["のり", "なる"],
  "勇": ["いさむ", "いさ"],
  "武": ["たけ", "たけし"],
  "剛": ["たけし", "つよし"],
  "健": ["たけ", "たけし"],
  "強": ["つよ", "つよし"],
  "勝": ["かつ", "まさる", "すぐる"],
  "賢": ["かしこ", "まさる", "さとし"],
  "聡": ["さとし", "とし", "あき"],
  "慧": ["さとし"],
  "哲": ["さとし", "あきら", "のり"],
  "敏": ["とし", "さとし"],
  "秀": ["ひで", "ほ"],
  "英": ["ひで", "ふさ", "はなぶさ"],
  "俊": ["とし", "すぐる"],
  "傑": ["すぐる"],
  "優": ["まさる", "やさし"],
  "良": ["よし", "ら", "なが"],
  "善": ["よし"],
  "吉": ["よし"],
  "喜": ["よし", "のぶ"],
  "嘉": ["よし", "ひろ"],
  "慶": ["よし", "のり"],
  "福": ["とみ", "よし"],
  "幸": ["さち", "ゆき", "さき", "みゆき"],
  "祥": ["さち", "よし"],
  "祐": ["すけ", "ひろ", "さち"],
  "佑": ["すけ", "たすく"],
  "輔": ["すけ", "たすく"],
  "介": ["すけ"],
  "助": ["すけ", "たすく"],
  "亮": ["あきら", "すけ"],
  "允": ["まさ", "のぶ", "ただ"],
  "丞": ["すけ"],
  "典": ["のり"],
  "則": ["のり"],
  "紀": ["のり", "とし"],
  "規": ["のり", "ただ"],
  "憲": ["のり"],
  "範": ["のり"],
  "法": ["のり"],
  "律": ["のり", "ただす"],
  "儀": ["のり"],
  "宣": ["のぶ", "のり"],
  "伸": ["のぶ"],
  "延": ["のぶ"],
  "展": ["のぶ", "ひろ"],
  "暢": ["のぶ"],
  "修": ["おさむ", "のぶ", "なお"],
  "治": ["はる", "おさむ"],
  "政": ["まさ", "まつりごと"],
  "正": ["まさ", "ただし", "ただ"],
  "昌": ["まさ", "あきら"],
  "雅": ["まさ", "みやび"],
  "将": ["まさ", "すすむ"],
  "匡": ["まさ", "ただし"],
  "真": ["ま", "まこと", "さね", "ただ"],
  "直": ["なお", "ただ"],
  "尚": ["なお", "ひさ", "たか"],
  "猛": ["たけ", "たけし"],
  "功": ["いさお"],
  "勲": ["いさお"],
  "績": ["いさお"],
  "栄": ["さかえ", "はる", "しげ", "ひで", "よし"],
  "繁": ["しげ", "しげる"],
  "茂": ["しげ", "しげる"],
  "盛": ["もり"],
  "豊": ["とよ", "ゆたか"],
  "富": ["とみ", "と"],
  "裕": ["ひろ", "ゆたか"],
  "寛": ["ひろ", "ひろし"],
  "弘": ["ひろ", "ひろし"],
  "宏": ["ひろ", "ひろし"],
  "浩": ["ひろ", "ひろし"],
  "博": ["ひろ", "ひろし"],
  "洋": ["ひろ", "ひろし"],
  "拓": ["ひろ", "ひらく"],
  "啓": ["ひろ", "ひらく", "あきら"],
  "恵": ["めぐみ", "めぐ", "さと"],
  "愛": ["まな", "めぐ", "ちか"],
  "恋": ["こい"],
  "美": ["み", "よし", "はる"],
  "麗": ["うらら"],
  "華": ["はな"],
  "香": ["か", "かおり", "かおる"],
  "芳": ["よし", "か", "かおる"],
  "薫": ["かおる", "かおり"],
  "舞": ["まい"],
  "歌": ["うた"],
  "詩": ["うた"],
  "琴": ["こと"],
  "笛": ["ふえ"],
  "鈴": ["すず"],
  "音": ["おと", "ね"],
  "響": ["ひびき", "ひびく"],
  "奏": ["かなで"],
  "楽": ["たの"],
  "心": ["こころ"],
  "思": ["おもい"],
  "想": ["おもい"],
  "志": ["こころざし", "ゆき", "むね"],
  "希": ["のぞみ", "まれ"],
  "望": ["のぞみ", "のぞむ", "もち"],
  "夢": ["ゆめ"],
  "願": ["ねがい"],
  "祈": ["いのり"],
  "叶": ["かな", "かなえ"],
  "結": ["ゆい", "ゆう", "むすび"],
  "絆": ["きずな"],
  "縁": ["ゆかり", "えにし", "より"],
  "和": ["かず", "やす", "なごみ", "のどか", "まさ"],
  "平": ["たいら", "ひら"],
  "安": ["やす"],
  "康": ["やす"],
  "泰": ["やす", "ひろ"],
  "静": ["しず", "しずか"],
  "穏": ["やす"],
  "寧": ["やす", "しず"],
  "清": ["きよ", "きよし", "すが"],
  "浄": ["きよ"],
  "澄": ["すみ", "きよ"],
  "純": ["すみ", "あつ", "いと"],
  "潔": ["きよし", "いさぎよ"],
  "淳": ["あつ", "あつし"],
  "敦": ["あつ", "あつし"],
  "篤": ["あつ", "あつし"],
  "厚": ["あつ", "あつし"],
  "温": ["あつ", "はる", "ゆたか"],
  "暖": ["はる", "あたた"],
  "熱": ["あつ"],
  "涼": ["すず"],
  "爽": ["さわ", "さやか"],
  "快": ["はや", "よし"],
  "明": ["あき", "あきら", "あか"],
  "朗": ["あき", "あきら", "お"],
  "晃": ["あき", "あきら", "てる"],
  "昭": ["あき", "あきら", "てる"],
  "晶": ["あき", "あきら", "まさ"],
  "彰": ["あき", "あきら"],
  "章": ["あき", "あや", "ふみ"],
  "顕": ["あき", "あきら"],
  "耀": ["あき", "てる"],
  "輝": ["てる", "かがやき", "ひかる"],
  "煌": ["きら", "あき"],
  "照": ["てる"],
  "暉": ["てる", "あき"],
  "旭": ["あさひ", "あき", "てる"],
  "昇": ["のぼる", "のり"],
  "登": ["のぼる", "のり", "なり"],
  "進": ["すすむ", "ゆき", "のぶ"],
  "歩": ["あゆみ", "あゆむ", "あゆ"],
  "走": ["はしる"],
  "飛": ["と", "とび"],
  "翔": ["かける", "と"],
  "翼": ["つばさ"],
  "羽": ["は", "わ", "はね"],
  "遊": ["あそび"],
  "悠": ["はるか", "ひさ", "ゆ"],
  "遥": ["はるか", "はる"],
  "遙": ["はるか", "はる"],
  "永": ["なが", "とわ", "ひさ"],
  "久": ["ひさ", "ひさし"],
  "恒": ["つね", "ひさ"],
  "常": ["つね", "とこ"],
  "継": ["つぐ", "つね"],
  "嗣": ["つぐ"],
  "次": ["つぐ", "つぎ"],
  "続": ["つぐ"],
  "紡": ["つむぎ", "つむ"],
  "織": ["おり"],
  "糸": ["いと"],
  "絹": ["きぬ"],
  "綾": ["あや"],
  "紗": ["すず"],
  "衣": ["ころも", "きぬ"],
  "袖": ["そで"],
  "帆": ["ほ"],
  "航": ["わたる"],
  "渉": ["わたる"],
  "亘": ["わたる", "のぶ"],
  "達": ["みち", "さと", "いたる"],
  "到": ["いたる"],
  "至": ["いたる", "のり"],
  "極": ["きわみ"],
  "究": ["きわむ"],
  "研": ["みがく"],
  "磨": ["みがく"],
  "学": ["まなぶ", "さと"],
  "習": ["ならい"],
  "教": ["のり", "おしえ"],
  "育": ["はぐくむ", "なる"],
  "養": ["やす"],
  "成": ["なり", "しげ", "なる"],
  "就": ["なり"],
  "為": ["ため", "なり"],
  "作": ["つくり"],
  "造": ["つくり", "なり"],
  "創": ["はじめ", "つくる"],
  "建": ["たつ", "たけ"],
  "立": ["たつ", "たち"],
  "起": ["おき"],
  "興": ["おき"],
  "生": ["いき", "なま", "お", "う", "き", "なり"],
  "活": ["いく"],
  "命": ["みこと", "のぶ"],
  "寿": ["ひさ", "ひさし", "とし", "ことぶき"],
  "老": ["おい"],
  "若": ["わか"],
  "稚": ["わか"],
  "幼": ["おさな"],
  "少": ["すく"],
  "多": ["おお", "まさ"],
  "全": ["まさ", "たもつ"],
  "満": ["みつ", "みちる", "みつる"],
  "充": ["みつ", "あつ", "みつる"],
  "足": ["あし", "たり"],
  "有": ["あり"],
  "在": ["あり"],
  "存": ["あり"],
  "保": ["やす", "もり", "たもつ"],
  "守": ["もり", "まもる"],
  "衛": ["もり", "まもる"],
  "護": ["まもる", "もり"],
  "救": ["すくい"],
  "支": ["ささえ"],
  "扶": ["すけ", "たすく"],
  "導": ["みち"],
  "迪": ["みち", "すすむ"],
  "径": ["みち"],
  "理": ["おさむ", "まさ", "みち", "あや"],
  "語": ["かたり"],
  "話": ["はなし"],
  "言": ["こと"],
  "詞": ["ことば"],
  "文": ["ふみ", "あや"],
  "書": ["ふみ"],
  "史": ["ふみ", "ちか"],
  "記": ["のり", "しるす"],
  "紙": ["かみ"],
  "筆": ["ふで"],
  "墨": ["すみ"],
  "画": ["え"],
  "映": ["うつり", "はゆ", "てる"],
  "影": ["かげ"],
  "鏡": ["かがみ"],
  "佐": ["すけ"],
  "加": ["ます", "くわえ"],
  "伊": ["これ", "ただ"],
  "斉": ["ひとし", "なり"],
  "斎": ["いつき"],
  "部": ["べ"],
  "工": ["たくみ"],
  "菅": ["すが", "すげ"],
  "片": ["かた"],
  "丸": ["まる"],
  "尾": ["お"],
  "能": ["よし", "たか"],
  "濱": ["はま"],
  "濵": ["はま"],
  "那": ["とも"],
  "乃": ["の"],
  "之": ["の", "ゆき", "これ"],
  "也": ["なり"],
  "哉": ["や", "かな", "ちか"],
  "斗": ["ます"],
  "陸": ["くが", "みち"],
  "颯": ["はやて"],
  "咲": ["さき", "さく", "えみ"],
  "笑": ["えみ", "わら", "え"],
  "凪": ["なぎ"],
  "澪": ["みお"],
  "雫": ["しずく"],
  "紬": ["つむぎ"],
  "栞": ["しおり"],
  "萌": ["もえ", "めぐみ"],
  "茜": ["あかね"],
  "絢": ["あや"],
  "瑞": ["みず", "たま"],
  "朔": ["はじめ", "もと"],
  "晄": ["あき", "あきら", "ひかる"],
  "椛": ["もみじ"],
  "柊": ["ひいらぎ"],
  "梓": ["あずさ"],
  "樺": ["かば"],
  "椋": ["むく"],
  "槙": ["まき"],
  "槇": ["まき"],
  "牧": ["まき"],
  "蒔": ["まき"],
  "巻": ["まき"],
  "麻": ["あさ", "お"],
  "弥": ["や", "いや", "ひさ", "わたる"],
  "彌": ["や", "いや", "ひさ"],
  "数": ["かず"],
  "親": ["ちか"],
  "周": ["ちか", "まこと", "あまね", "かね"],
  "慎": ["まこと", "ちか", "のり"],
  "誓": ["ちかい", "ちか"],
  "幹": ["みき", "もと"],
  "己": ["おのれ"],
  "身": ["み"],
  "視": ["み"],
  "見": ["み"],
  "密": ["ひそか"],
  "倫": ["みち", "とも", "のり"],
  "宙": ["そら", "ひろし"],
  "昊": ["そら"],
  "穹": ["そら"],
  "飴": ["あめ"],
  "綺": ["あや"],
  "采": ["あや"],
  "円": ["まる", "まど", "つぶら"],
  "休": ["やす"],
  "車": ["くるま"],
  "手": ["て", "た"],
  "出": ["で", "いで", "いず"],
  "早": ["はや", "さ"],
  "虫": ["むし"],
  "入": ["いり", "い"],
  "目": ["め", "ま"],
  "力": ["ちから", "つとむ"],
  "引": ["ひき"],
  "園": ["その"],
  "何": ["なに"],
  "科": ["しな"],
  "回": ["まわり"],
  "会": ["あい"],
  "顔": ["かお"],
  "帰": ["かえる"],
  "弓": ["ゆみ"],
  "魚": ["うお", "な", "さかな"],
  "形": ["かた", "かたち", "なり"],
  "計": ["かず"],
  "交": ["かわし", "まじわり"],
  "考": ["たか"],
  "行": ["ゆき", "いく", "みち", "つら"],
  "合": ["あい"],
  "才": ["とし"],
  "算": ["かず"],
  "止": ["とめ"],
  "矢": ["や"],
  "自": ["より"],
  "室": ["むろ"],
  "弱": ["よわ"],
  "首": ["くび", "おびと"],
  "食": ["け"],
  "図": ["はかり"],
  "声": ["こえ"],
  "切": ["きり"],
  "組": ["くみ"],
  "体": ["からだ"],
  "台": ["うてな"],
  "通": ["みち", "とおる", "ゆき"],
  "店": ["みせ", "たな"],
  "刀": ["かたな"],
  "当": ["まさ"],
  "頭": ["かしら", "あたま", "かみ"],
  "同": ["おな", "とも"],
  "読": ["よみ"],
  "半": ["なか"],
  "番": ["つがい"],
  "分": ["わけ"],
  "聞": ["きく"],
  "方": ["かた", "え", "まさ"],
  "毎": ["つね"],
  "鳴": ["なる"],
  "毛": ["け"],
  "用": ["もち"],
  "曜": ["てる"],
  "来": ["き", "く"],
  "悪": ["わる"],
  "暗": ["くら"],
  "員": ["かず"],
  "運": ["かず"],
  "荷": ["に"],
  "開": ["ひらき", "はる"],
  "寒": ["さむ"],
  "期": ["とき"],
  "球": ["たま"],
  "業": ["なり"],
  "曲": ["まがり"],
  "苦": ["にが"],
  "具": ["とも"],
  "係": ["かかり"],
  "軽": ["かる"],
  "血": ["ち"],
  "祭": ["まつり"],
  "皿": ["さら"],
  "仕": ["つかえ"],
  "指": ["ゆび", "さし"],
  "歯": ["は"],
  "事": ["こと"],
  "持": ["もち"],
  "式": ["のり"],
  "者": ["もの"],
  "取": ["とり"],
  "酒": ["さか", "さけ"],
  "受": ["うけ"],
  "拾": ["ひろい"],
  "集": ["つどい", "あつむ"],
  "住": ["すみ"],
  "重": ["しげ", "え", "おも"],
  "宿": ["やど"],
  "暑": ["あつ"],
  "商": ["あき"],
  "乗": ["のり"],
  "植": ["うえ"],
  "世": ["よ"],
  "整": ["ひとし"],
  "相": ["あい", "すけ"],
  "息": ["いき"],
  "速": ["はや"],
  "他": ["ほか"],
  "打": ["うち"],
  "待": ["まち"],
  "代": ["よ", "しろ"],
  "炭": ["すみ"],
  "着": ["き"],
  "柱": ["はしら"],
  "調": ["つぎ", "しげ"],
  "追": ["おい"],
  "定": ["さだ", "さだむ"],
  "庭": ["にわ"],
  "度": ["のり"],
  "湯": ["ゆ"],
  "等": ["ひとし", "など"],
  "童": ["わらべ"],
  "箱": ["はこ"],
  "反": ["そり"],
  "板": ["いた"],
  "皮": ["かわ"],
  "鼻": ["はな"],
  "品": ["しな"],
  "服": ["はとり"],
  "物": ["もの"],
  "勉": ["つとむ"],
  "味": ["あじ"],
  "面": ["おも", "つら"],
  "薬": ["くすり"],
  "由": ["よし", "より"],
  "油": ["あぶら"],
  "様": ["さま"],
  "落": ["おち"],
  "流": ["ながれ"],
  "旅": ["たび"],
  "両": ["もろ"],
  "列": ["つら"],
  "練": ["ねり"],
  "以": ["もち"],
  "位": ["くらい"],
  "囲": ["かこい"],
  "印": ["しるし"],
  "塩": ["しお"],
  "果": ["はた"],
  "改": ["あらた"],
  "各": ["おのおの"],
  "覚": ["さとる"],
  "完": ["さだ", "ひろ"],
  "官": ["おおやけ"],
  "管": ["くだ"],
  "観": ["み"],
  "季": ["すえ", "とし"],
  "旗": ["はた"],
  "器": ["うつわ"],
  "機": ["はた"],
  "求": ["もとむ"],
  "泣": ["なき"],
  "給": ["たまう"],
  "挙": ["あげ"],
  "漁": ["すなどり"],
  "共": ["とも"],
  "協": ["かのう"],
  "競": ["きそい"],
  "訓": ["のり"],
  "軍": ["いくさ"],
  "郡": ["こおり"],
  "型": ["かた"],
  "景": ["かげ", "ひろ"],
  "芸": ["き"],
  "欠": ["かけ"],
  "固": ["かた"],
  "好": ["よし", "この", "すみ"],
  "候": ["そうろう"],
  "告": ["つぐ"],
  "最": ["も"],
  "材": ["き"],
  "札": ["ふだ"],
  "参": ["み"],
  "産": ["うぶ"],
  "残": ["のこり"],
  "士": ["お"],
  "司": ["つかさ", "もり"],
  "児": ["こ"],
  "祝": ["いわい", "はふり"],
  "順": ["のぶ", "より"],
  "焼": ["やき"],
  "象": ["かた"],
  "省": ["み"],
  "積": ["つみ"],
  "折": ["おり"],
  "節": ["ふし", "みさお", "たか"],
  "戦": ["いくさ"],
  "選": ["えらみ", "かず"],
  "然": ["しか"],
  "巣": ["す"],
  "束": ["つか"],
  "孫": ["まご"],
  "帯": ["おび"],
  "置": ["おき"],
  "仲": ["なか"],
  "底": ["そこ"],
  "的": ["まと"],
  "伝": ["つたえ"],
  "努": ["つとむ"],
  "灯": ["ひ", "あかり"],
  "得": ["え"],
  "飯": ["いい", "めし"],
  "標": ["しな"],
  "付": ["つけ"],
  "副": ["そえ"],
  "粉": ["こ"],
  "別": ["わけ"],
  "包": ["かね"],
  "要": ["かなめ"],
  "利": ["とし"],
  "量": ["かず"],
  "輪": ["わ"],
  "令": ["のり"],
  "連": ["つら", "むらじ"],
  "移": ["うつり"],
  "因": ["よる"],
  "営": ["いとなみ"],
  "易": ["やす"],
  "益": ["ます"],
  "演": ["のぶ"],
  "往": ["ゆき"],
  "恩": ["めぐみ"],
  "可": ["よし"],
  "仮": ["かり"],
  "価": ["あたい"],
  "賀": ["よし"],
  "格": ["ただし"],
  "確": ["かた"],
  "額": ["ぬか"],
  "眼": ["まなこ", "め"],
  "基": ["もと"],
  "寄": ["より"],
  "技": ["わざ"],
  "逆": ["さか"],
  "居": ["い", "おり"],
  "許": ["もと"],
  "境": ["さかい"],
  "均": ["ひとし"],
  "群": ["むら"],
  "経": ["つね", "のり"],
  "現": ["あり"],
  "故": ["ふる"],
  "耕": ["たがやし"],
  "再": ["ふたたび"],
  "財": ["たから"],
  "罪": ["つみ"],
  "師": ["もろ"],
  "資": ["もと"],
  "飼": ["かい"],
  "示": ["しめ"],
  "似": ["に"],
  "識": ["さと"],
  "質": ["ただ"],
  "舎": ["や", "いえ"],
  "授": ["さずけ"],
  "述": ["のぶ"],
  "術": ["すべ"],
  "準": ["のり"],
  "序": ["つぐ"],
  "招": ["まねき"],
  "承": ["うけ", "つぐ"],
  "証": ["あかし"],
  "条": ["えだ"],
  "情": ["なさけ"],
  "職": ["もと"],
  "制": ["のり"],
  "性": ["さが"],
  "勢": ["いきおい", "なり"],
  "精": ["きよ"],
  "接": ["つぎ"],
  "設": ["もうけ"],
  "舌": ["した"],
  "絶": ["たえ"],
  "銭": ["ぜに"],
  "祖": ["おや"],
  "素": ["もと"],
  "総": ["ふさ"],
  "増": ["ます"],
  "測": ["はかり"],
  "貸": ["かし"],
  "団": ["まどか"],
  "築": ["きずき"],
  "張": ["はり"],
  "程": ["ほど"],
  "敵": ["かたき"],
  "統": ["すべ", "のり"],
  "独": ["ひとり"],
  "任": ["ただ", "たか", "とう"],
  "破": ["やぶり"],
  "比": ["ひさ"],
  "肥": ["こえ"],
  "備": ["そなえ"],
  "俵": ["たわら"],
  "布": ["ぬの"],
  "仏": ["ほとけ"],
  "編": ["あみ"],
  "墓": ["はか"],
  "務": ["つとむ"],
  "迷": ["まよい"],
  "綿": ["わた"],
  "余": ["あまり"],
  "容": ["かた"],
  "留": ["とめ"],
  "異": ["こと"],
  "宇": ["たか", "のき"],
  "沿": ["そい"],
  "我": ["われ"],
  "拡": ["ひろ"],
  "革": ["かわ"],
  "割": ["わり"],
  "干": ["ほし"],
  "机": ["つくえ"],
  "貴": ["たか"],
  "供": ["とも"],
  "胸": ["むね"],
  "勤": ["つとむ"],
  "筋": ["すじ"],
  "敬": ["たか", "ひろ", "のり"],
  "穴": ["あな"],
  "源": ["みなもと", "もと"],
  "厳": ["いず", "いつ", "よし"],
  "呼": ["よび"],
  "降": ["ふり"],
  "鋼": ["はがね"],
  "刻": ["とき"],
  "骨": ["ほね"],
  "座": ["くら"],
  "済": ["すみ", "なり"],
  "裁": ["たち"],
  "蚕": ["かいこ"],
  "私": ["わたくし"],
  "姿": ["すがた"],
  "射": ["いり"],
  "捨": ["すて"],
  "収": ["おさむ"],
  "宗": ["むね"],
  "衆": ["もろ"],
  "従": ["より"],
  "諸": ["もろ"],
  "針": ["はり"],
  "垂": ["たれ"],
  "聖": ["きよ", "ひじり", "さと"],
  "専": ["もっぱら"],
  "染": ["そめ"],
  "窓": ["まど"],
  "操": ["みさお"],
  "尊": ["たか", "たける"],
  "宅": ["いえ"],
  "値": ["あたい"],
  "著": ["あき"],
  "頂": ["いただき"],
  "届": ["とどけ"],
  "乳": ["ち"],
  "納": ["おさむ"],
  "背": ["せ"],
  "腹": ["はら"],
  "並": ["なみ"],
  "補": ["すけ"],
  "暮": ["くれ"],
  "枚": ["ひら"],
  "訳": ["わけ"],
  "卵": ["たまご"],
  "亜": ["つぐ"],
  "扱": ["あつかい"],
  "依": ["より"],
  "威": ["たけ"],
  "偉": ["いさむ", "より"],
  "維": ["これ"],
  "壱": ["かず"],
  "芋": ["いも"],
  "陰": ["かげ"],
  "鋭": ["とし"],
  "越": ["こし", "こえ"],
  "煙": ["けむり"],
  "鉛": ["なまり"],
  "押": ["おし"],
  "暇": ["ひま"],
  "皆": ["みな"],
  "刈": ["かり", "かる"],
  "甘": ["あま"],
  "汗": ["あせ"],
  "乾": ["いぬい"],
  "勧": ["すすむ"],
  "歓": ["よし"],
  "環": ["たまき"],
  "鑑": ["あき"],
  "鬼": ["おに"],
  "幾": ["いく"],
  "詰": ["つめ"],
  "脚": ["あし"],
  "及": ["しき"],
  "巨": ["おお"],
  "御": ["み", "お"],
  "仰": ["あおぎ"],
  "駆": ["かけ"],
  "掘": ["ほり"],
  "繰": ["くり"],
  "迎": ["むかえ"],
  "肩": ["かた"],
  "兼": ["かね"],
  "剣": ["つるぎ"],
  "軒": ["のき"],
  "堅": ["かた"],
  "玄": ["はる", "くろ"],
  "枯": ["かれ"],
  "誇": ["ほこり"],
  "鼓": ["つづみ"],
  "互": ["たがい"],
  "更": ["さら"],
  "荒": ["あら"],
  "豪": ["たけし"],
  "込": ["こみ"],
  "鎖": ["くさり"],
  "歳": ["とし"],
  "旨": ["むね"],
  "脂": ["あぶら"],
  "雌": ["め"],
  "煮": ["に"],
  "寂": ["さび"],
  "狩": ["かり"],
  "襲": ["かさね"],
  "柔": ["やわら"],
  "獣": ["けもの"],
  "巡": ["めぐり"],
  "盾": ["たて"],
  "召": ["めし"],
  "床": ["とこ", "ゆか"],
  "丈": ["たけ"],
  "畳": ["たたみ"],
  "飾": ["かざり"],
  "振": ["ふり"],
  "薪": ["まき"],
  "尽": ["つくし"],
  "尋": ["ひろ"],
  "吹": ["ふき"],
  "是": ["これ", "ただし"],
  "征": ["ゆき"],
  "跡": ["あと"],
  "占": ["しめ"],
  "扇": ["おうぎ"],
  "鮮": ["あざやか"],
  "贈": ["おくり"],
  "替": ["かえ"],
  "丹": ["に", "あか"],
  "淡": ["あわ"],
  "弾": ["たま"],
  "致": ["むね"],
  "遅": ["おそ"],
  "沖": ["おき"],
  "珍": ["うず"],
  "摘": ["つみ"],
  "滴": ["しずく"],
  "添": ["そえ"],
  "途": ["みち"],
  "奴": ["やっこ"],
  "唐": ["から"],
  "透": ["すき"],
  "峠": ["とうげ"],
  "杯": ["さかずき"],
  "輩": ["ともがら"],
  "迫": ["さこ", "せこ"],
  "薄": ["うす"],
  "髪": ["かみ"],
  "抜": ["ぬき"],
  "彼": ["かれ"],
  "浮": ["うき"],
  "普": ["ひろ"],
  "敷": ["しき"],
  "幅": ["はば"],
  "払": ["はらい"],
  "柄": ["がら", "つか", "え"],
  "壁": ["かべ"],
  "抱": ["だき"],
  "傍": ["かたわら"],
  "妙": ["たえ"],
  "眠": ["ねむり"],
  "矛": ["ほこ"],
  "娘": ["むすめ"],
  "網": ["あみ"],
  "紋": ["あや"],
  "雄": ["お", "おす", "たけ", "かつ"],
  "与": ["あたえ", "とも"],
  "誉": ["ほまれ", "たか"],
  "腰": ["こし"],
  "踊": ["おどり"],
  "謡": ["うた"],
  "頼": ["より"],
  "粒": ["つぶ"],
  "隣": ["となり"],
  "涙": ["なみだ"],
  "暦": ["こよみ"],
  "烈": ["つよし", "いさお"],
  "郎": ["お"],
  "腕": ["うで"],
  "斐": ["あや"],
  "惟": ["これ", "ただ"],
  "李": ["すもも", "もも"],
  "侑": ["すすむ", "ゆき"],
  "怜": ["さと"],
  "玲": ["あきら"],
  "瑛": ["あきら", "てる"],
  "瑶": ["たま"],
  "遼": ["はるか"],
  "諒": ["まこと", "あき"],
  "稜": ["かど"],
  "綸": ["いと"],
  "紘": ["ひろ"],
  "繭": ["まゆ"],
  "菫": ["すみれ"],
  "蕾": ["つぼみ"],
  "薇": ["ぜんまい"],
  "葦": ["あし", "よし"],
  "芦": ["あし", "よし"],
  "茅": ["かや", "ち"],
  "萱": ["かや"],
  "荻": ["おぎ"],
  "蔦": ["つた"],
  "葛": ["くず", "かず"],
  "蒲": ["かま", "がま"],
  "菖": ["あやめ"],
  "芹": ["せり"],
  "苺": ["いちご"],
  "蓬": ["よもぎ"],
  "杜": ["もり"],
  "柾": ["まさ", "まさき"],
  "槻": ["つき"],
  "樟": ["くす"],
  "欅": ["けやき"],
  "楢": ["なら"],
  "梢": ["こずえ"],
  "榛": ["はしばみ", "はる"],
  "檀": ["まゆみ"],
  "櫻": ["さくら"],
  "楼": ["たかどの"],
  "琢": ["みがく"],
  "鐘": ["かね"],
  "錦": ["にしき"],
  "鎌": ["かま"],
  "鍋": ["なべ"],
  "鍵": ["かぎ"],
  "鎮": ["しず", "しずめ"],
  "嵐": ["あらし"],
  "嶺": ["みね", "ね"],
  "嵩": ["たか", "かさ"],
  "峻": ["たかし", "みね"],
  "巌": ["いわお", "いわ"],
  "渓": ["たに"],
  "洸": ["ひろ", "たけし"],
  "湧": ["わく", "わき"],
  "漣": ["さざなみ"],
  "滉": ["ひろ"],
  "潤": ["うるう"],
  "瀬": ["せ"],
  "灘": ["なだ"],
  "汀": ["みぎわ", "なぎさ"],
  "沙": ["すな"],
  "洲": ["す", "くに"],
  "滋": ["しげ", "しげる"],
  "渥": ["あつ"],
  "溢": ["みつる"],
  "漆": ["うるし"],
  "濠": ["ほり"],
  "燈": ["ひ", "あかり"],
  "炎": ["ほのお", "ほむら"],
  "焔": ["ほのお", "ほむら"],
  "熙": ["ひろ", "ひろし"],
  "燦": ["あきら"],
  "昂": ["たかし", "あき"],
  "晟": ["あきら"],
  "晏": ["やす", "はる"],
  "暁": ["あかつき", "あき", "さとる"],
  "曙": ["あけぼの", "あけ"],
  "旺": ["あきら"],
  "昴": ["すばる"],
  "晋": ["すすむ", "ゆき"],
  "晨": ["あき", "とき"],
  "肇": ["はじめ"],
  "胡": ["えびす"],
  "脩": ["おさむ", "なが"],
  "舜": ["きよ"],
  "艶": ["つや"],
  "苑": ["その"],
  "萬": ["かず", "よろず"],
  "衿": ["えり"],
  "襟": ["えり"],
  "詢": ["まこと"],
  "諄": ["あつ", "まこと"],
  "謙": ["ゆずる", "かね", "のり"],
  "讃": ["たたえ"],
  "貫": ["ぬき", "つらぬき"],
  "赳": ["たけし", "たけ"],
  "迅": ["はや", "とし"],
  "逸": ["はや", "はやる"],
  "郁": ["かおる", "ふみ"],
  "醇": ["あつ"],
  "釣": ["つり"],
  "鎧": ["よろい"],
  "閃": ["ひらめき"],
  "閑": ["しず"],
  "隆": ["たか", "たかし"],
  "雛": ["ひな"],
  "霞": ["かすみ"],
  "靖": ["やす", "やすし"],
  "鞠": ["まり"],
  "頌": ["うた"],
  "馨": ["かおる", "かおり"],
  "駿": ["はやお", "とし"],
  "魁": ["いさお", "さきがけ"],
  "鯛": ["たい"],
  "鴻": ["ひろし"],
  "鵬": ["おおとり"],
  "鷗": ["かもめ"],
  "鴎": ["かもめ"],
  "黛": ["まゆずみ"],
  "鼎": ["かなえ"],
  "甫": ["はじめ", "すけ"],
  "亨": ["とおる"],
  "亙": ["わたる"],
  "倖": ["さち"],
  "偲": ["しのぶ"],
  "凌": ["しのぐ"],
  "勁": ["つよし"],
  "匠": ["たくみ"],
  "卓": ["たかし", "すぐる"],
  "叡": ["さとし", "あきら"],
  "圭": ["かど", "きよし"],
  "堯": ["たかし"],
  "壮": ["たけし", "まさ"],
  "嬉": ["よし"],
  "孜": ["つとむ"],
  "宥": ["ひろ"],
  "巧": ["たくみ"],
  "巴": ["ともえ"],
  "弦": ["つる", "いと"],
  "恭": ["やす", "たか"],
  "悟": ["さとる", "さとし"],
  "惇": ["あつ", "あつし"],
  "慈": ["しげ", "やす"],
  "憧": ["あこがれ"],
  "懐": ["なつ"],
  "拳": ["こぶし"],
  "捷": ["かつ", "まさる"],
  "旦": ["あさ", "あき"],
  "曽": ["かつ"],
  "杵": ["きね"],
  "梨": ["なし"],
  "槐": ["えんじゅ"],
  "爾": ["しか"],
  "皐": ["さつき"],
  "眞": ["ま", "まこと"],
  "睦": ["むつ", "むつみ", "ちか"],
  "矩": ["のり", "かね"],
  "碩": ["ひろ"],
  "禄": ["よし", "とみ"],
  "禎": ["さだ", "よし"],
  "稀": ["まれ"],
  "穣": ["みのる"],
  "笹": ["ささ"],
  "篠": ["しの"],
  "緋": ["あけ"],
  "縞": ["しま"],
  "胤": ["たね"],
  "薙": ["なぎ"],
  "詠": ["うた"],
  "譲": ["ゆずる"],
  "邑": ["むら"],
  "馳": ["はせ"],
  "鮫": ["さめ"],
  "乙": ["おと"],
  "佳": ["よし"],
  "克": ["かつ"],
  "函": ["はこ"],
  "堺": ["さかい"],
  "如": ["ゆき"],
  "媛": ["ひめ"],
  "尼": ["あま"],
  "幌": ["ほろ"],
  "彦": ["ひこ"],
  "忍": ["しのぶ", "しの"],
  "柴": ["しば"],
  "栃": ["とち"],
  "桑": ["くわ"],
  "樋": ["ひ", "とい"],
  "樽": ["たる"],
  "毅": ["たけし", "つよし", "たけ"],
  "気": ["おき"],
  "渋": ["しぶ"],
  "潟": ["かた", "がた"],
  "甲": ["かぶと", "きのえ"],
  "瞳": ["ひとみ"],
  "縄": ["なわ"],
  "茨": ["いばら"],
  "袋": ["ふくろ"],
  "辻": ["つじ"],
  "阜": ["おか"],
  "阪": ["さか"],
  "韓": ["から"],
  "伴": ["とも"],
  "幡": ["はた"],
  "筑": ["つく"],
  "但": ["ただ"],
  "喬": ["たか"],
  "冴": ["さえ"],
  "楪": ["ゆずりは"],
  "楸": ["ひさぎ"],
  "櫂": ["かい"],
  "燿": ["てる", "あき"],
  "狼": ["おおかみ"],
  "彪": ["あや", "たけ"],
  "鶯": ["うぐいす"],
  "廉": ["やす", "きよ"],
  "尭": ["たか"],
  "毬": ["まり"],
  "絃": ["いと"],
  "唄": ["うた"],
  "蔭": ["かげ"],
  "塙": ["はなわ"],
  "籠": ["かご", "こ"],
  "釜": ["かま"],
  "窪": ["くぼ"],
  "薮": ["やぶ"],
  "藪": ["やぶ"],
  "鍬": ["くわ"],
  "栂": ["つが", "とが"],
  "梶": ["かじ"],
  "杭": ["くい"],
  "橡": ["とち"],
  "苔": ["こけ"],
  "蘆": ["あし"],
  "薗": ["その"],
  "巽": ["たつみ"],
  "雉": ["きじ"],
  "鵜": ["う"],
  "徹": ["とおる"],
  "宍": ["しし"],
  "蛭": ["ひる"],
  "鴫": ["しぎ"],
  "鱒": ["ます"],
  "鰐": ["わに"],
  "烏": ["からす"],
  "鴉": ["からす"],
  "鵺": ["ぬえ"],
  "屍": ["しかばね"]
 }
}
'''

DATA['data/loanwords.json'] = r'''[
 "アイス",
 "アイツ",
 "アイテム",
 "アイデア",
 "アイドル",
 "アカウント",
 "アタイ",
 "アタシ",
 "アナタ",
 "アニメ",
 "アパート",
 "アプリ",
 "アホ",
 "アルバイト",
 "アンタ",
 "アーマー",
 "イケメン",
 "イス",
 "イヌ",
 "イベント",
 "イメージ",
 "イヤ",
 "イヤホン",
 "インターネット",
 "ウィザード",
 "ウェブサイト",
 "ウサギ",
 "ウザ",
 "ウソ",
 "ウチ",
 "ウルフ",
 "エアコン",
 "エスカレーター",
 "エネルギー",
 "エピソード",
 "エラー",
 "エルフ",
 "エレベーター",
 "オイラ",
 "オッケー",
 "オフィス",
 "オマエ",
 "オレ",
 "オーク",
 "オーケー",
 "カバン",
 "カフェ",
 "カメラ",
 "カラー",
 "カレンダー",
 "カレー",
 "カーテン",
 "カード",
 "ガチ",
 "ガラス",
 "キサマ",
 "キス",
 "キッチン",
 "キツネ",
 "キミ",
 "キモ",
 "キャプテン",
 "キャラ",
 "キャラクター",
 "キャリーケース",
 "キャンプ",
 "キロ",
 "キング",
 "ギター",
 "ギフト",
 "ギルド",
 "クイーン",
 "クエスト",
 "クソ",
 "クッキー",
 "クラス",
 "クラスメイト",
 "クリック",
 "グラウンド",
 "グラム",
 "ケンカ",
 "ケーキ",
 "ケース",
 "ゲスト",
 "ゲート",
 "ゲーム",
 "コア",
 "コイツ",
 "コメント",
 "コンビニ",
 "コンピュータ",
 "コンピューター",
 "コーチ",
 "コート",
 "コーヒー",
 "ゴブリン",
 "ゴルフ",
 "ゴール",
 "ゴーレム",
 "サイズ",
 "サイト",
 "サッカー",
 "サラダ",
 "サンキュー",
 "サンドイッチ",
 "サンプル",
 "サービス",
 "システム",
 "シャツ",
 "シャワー",
 "ショック",
 "ショップ",
 "シールド",
 "シーン",
 "ジャケット",
 "ジャンプ",
 "ジュース",
 "ジョギング",
 "ジョブ",
 "ジョーク",
 "スイッチ",
 "スカート",
 "スキル",
 "スキー",
 "スケジュール",
 "スケルトン",
 "スコア",
 "スタイル",
 "スタジオ",
 "スタッフ",
 "スタート",
 "ステージ",
 "ステータス",
 "ストップ",
 "ストレス",
 "ストーブ",
 "ストーリー",
 "スニーカー",
 "スピード",
 "スポーツ",
 "スマイル",
 "スマホ",
 "スマートフォン",
 "スライム",
 "スーツ",
 "スーツケース",
 "スーパー",
 "スープ",
 "ズボン",
 "センス",
 "センター",
 "センチ",
 "セーター",
 "ソイツ",
 "ソファ",
 "ソード",
 "ゾンビ",
 "タイプ",
 "タイミング",
 "タオル",
 "タクシー",
 "タバコ",
 "タワー",
 "ターゲット",
 "ダイエット",
 "ダガー",
 "ダメ",
 "ダンジョン",
 "ダンス",
 "チェック",
 "チケット",
 "チャイム",
 "チャット",
 "チャンス",
 "チョコ",
 "チョコレート",
 "チーズ",
 "チーム",
 "ツッコミ",
 "ティッシュ",
 "テスト",
 "テニス",
 "テメェ",
 "テメエ",
 "テレビ",
 "テーブル",
 "テープ",
 "デザイン",
 "デザート",
 "デバフ",
 "デパート",
 "データ",
 "デート",
 "デーモン",
 "トイレ",
 "トラック",
 "トラブル",
 "トレーニング",
 "トンネル",
 "ドア",
 "ドラゴン",
 "ドラマ",
 "ドリンク",
 "ドル",
 "ドワーフ",
 "ナイト",
 "ナイフ",
 "ニュース",
 "ネクタイ",
 "ネコ",
 "ネズミ",
 "ネックレス",
 "ネット",
 "ノリ",
 "ノート",
 "ハイ",
 "ハウス",
 "ハグ",
 "ハロー",
 "ハンカチ",
 "ハンター",
 "ハート",
 "バイク",
 "バイバイ",
 "バカ",
 "バス",
 "バスケ",
 "バター",
 "バッグ",
 "バフ",
 "バランス",
 "バレー",
 "パスポート",
 "パスワード",
 "パソコン",
 "パニック",
 "パパ",
 "パワー",
 "パン",
 "パーカー",
 "パーセント",
 "パーティ",
 "パーティー",
 "パートナー",
 "ヒマ",
 "ヒロイン",
 "ヒール",
 "ヒーロー",
 "ビニール",
 "ビル",
 "ビーチ",
 "ビール",
 "ピアノ",
 "ピザ",
 "ピンチ",
 "ファイル",
 "ファン",
 "フォルダ",
 "フルーツ",
 "ブレザー",
 "ブーツ",
 "プラスチック",
 "プラン",
 "プリンス",
 "プリンセス",
 "プレゼント",
 "プロ",
 "プログラム",
 "プロフィール",
 "プール",
 "ベッド",
 "ベンチ",
 "ベース",
 "ペット",
 "ペン",
 "ページ",
 "ホテル",
 "ホント",
 "ホーム",
 "ホール",
 "ボク",
 "ボケ",
 "ボス",
 "ボタン",
 "ボート",
 "ボール",
 "ポイント",
 "ポケット",
 "ポスター",
 "ポーション",
 "ポータル",
 "マジ",
 "マジック",
 "マスク",
 "マナ",
 "マナー",
 "マネージャー",
 "ママ",
 "マンガ",
 "マンション",
 "マント",
 "マーケット",
 "ミス",
 "ミッション",
 "ミラー",
 "ミリ",
 "ミルク",
 "ミンナ",
 "ムカ",
 "ムリ",
 "メイド",
 "メガネ",
 "メッセージ",
 "メニュー",
 "メモ",
 "メンバー",
 "メートル",
 "メール",
 "モンスター",
 "ヤツ",
 "ヤバ",
 "ユニコーン",
 "ユーモア",
 "ライト",
 "ライバル",
 "ラジオ",
 "ラスボス",
 "ランク",
 "ランチ",
 "ランニング",
 "ランプ",
 "ラーメン",
 "リスト",
 "リボン",
 "リュック",
 "リンク",
 "リーダー",
 "ルーム",
 "ルール",
 "レストラン",
 "レベル",
 "ロビー",
 "ローブ",
 "ロープ",
 "ワイバーン",
 "ワイン",
 "ワシ",
 "ワタシ",
 "ヴァンパイア"
]
'''

DATA['data/name_words.json'] = r'''{
  "飛鳥": ["あすか"],
  "五月女": ["さおとめ", "そうとめ"],
  "不知火": ["しらぬい"],
  "百目鬼": ["どどめき"],
  "九十九": ["つくも"],
  "十六夜": ["いざよい"],
  "月見里": ["やまなし"],
  "八月一日": ["ほずみ"],
  "雲雀": ["ひばり"],
  "時雨": ["しぐれ"],
  "皐月": ["さつき"],
  "五月": ["さつき"],
  "長谷": ["はせ"],
  "日下": ["くさか"],
  "紫苑": ["しおん"],
  "乙女": ["おとめ"],
  "我孫子": ["あびこ"],
  "仁": ["じん", "ひとし", "まさし"],
  "乾": ["いぬい"],
  "巻": ["まき"],
  "開": ["かい", "ひらく"],
  "弾": ["だん"],
  "貫": ["かん", "とおる"],
  "渡": ["わたる", "わたり"],
  "響": ["ひびき"],
  "拓": ["たく", "ひらく"],
  "鳴": ["めい", "なる"],
  "通": ["とおる"],
  "保": ["たもつ"],
  "満": ["みつる"]
}
'''

DATA['data/places.json'] = r'''{
  "日本": {
    "id": "Jepang",
    "en": "Japan",
    "reading": "にほん"
  },
  "中国": {
    "id": "Tiongkok",
    "en": "China",
    "reading": "ちゅうごく"
  },
  "韓国": {
    "id": "Korea Selatan",
    "en": "South Korea",
    "reading": "かんこく"
  },
  "台湾": {
    "id": "Taiwan",
    "en": "Taiwan",
    "reading": "たいわん"
  },
  "北海道": {
    "id": "Hokkaido",
    "en": "Hokkaido",
    "reading": "ほっかいどう"
  },
  "青森": {
    "id": "Aomori",
    "en": "Aomori",
    "reading": "あおもり"
  },
  "岩手": {
    "id": "Iwate",
    "en": "Iwate",
    "reading": "いわて"
  },
  "宮城": {
    "id": "Miyagi",
    "en": "Miyagi",
    "reading": "みやぎ"
  },
  "秋田": {
    "id": "Akita",
    "en": "Akita",
    "reading": "あきた"
  },
  "山形": {
    "id": "Yamagata",
    "en": "Yamagata",
    "reading": "やまがた"
  },
  "福島": {
    "id": "Fukushima",
    "en": "Fukushima",
    "reading": "ふくしま"
  },
  "茨城": {
    "id": "Ibaraki",
    "en": "Ibaraki",
    "reading": "いばらき"
  },
  "栃木": {
    "id": "Tochigi",
    "en": "Tochigi",
    "reading": "とちぎ"
  },
  "群馬": {
    "id": "Gunma",
    "en": "Gunma",
    "reading": "ぐんま"
  },
  "埼玉": {
    "id": "Saitama",
    "en": "Saitama",
    "reading": "さいたま"
  },
  "千葉": {
    "id": "Chiba",
    "en": "Chiba",
    "reading": "ちば"
  },
  "東京": {
    "id": "Tokyo",
    "en": "Tokyo",
    "reading": "とうきょう"
  },
  "神奈川": {
    "id": "Kanagawa",
    "en": "Kanagawa",
    "reading": "かながわ"
  },
  "新潟": {
    "id": "Niigata",
    "en": "Niigata",
    "reading": "にいがた"
  },
  "富山": {
    "id": "Toyama",
    "en": "Toyama",
    "reading": "とやま"
  },
  "石川": {
    "id": "Ishikawa",
    "en": "Ishikawa",
    "reading": "いしかわ"
  },
  "福井": {
    "id": "Fukui",
    "en": "Fukui",
    "reading": "ふくい"
  },
  "山梨": {
    "id": "Yamanashi",
    "en": "Yamanashi",
    "reading": "やまなし"
  },
  "長野": {
    "id": "Nagano",
    "en": "Nagano",
    "reading": "ながの"
  },
  "岐阜": {
    "id": "Gifu",
    "en": "Gifu",
    "reading": "ぎふ"
  },
  "静岡": {
    "id": "Shizuoka",
    "en": "Shizuoka",
    "reading": "しずおか"
  },
  "愛知": {
    "id": "Aichi",
    "en": "Aichi",
    "reading": "あいち"
  },
  "三重": {
    "id": "Mie",
    "en": "Mie",
    "reading": "みえ"
  },
  "滋賀": {
    "id": "Shiga",
    "en": "Shiga",
    "reading": "しが"
  },
  "京都": {
    "id": "Kyoto",
    "en": "Kyoto",
    "reading": "きょうと"
  },
  "大阪": {
    "id": "Osaka",
    "en": "Osaka",
    "reading": "おおさか"
  },
  "兵庫": {
    "id": "Hyogo",
    "en": "Hyogo",
    "reading": "ひょうご"
  },
  "奈良": {
    "id": "Nara",
    "en": "Nara",
    "reading": "なら"
  },
  "和歌山": {
    "id": "Wakayama",
    "en": "Wakayama",
    "reading": "わかやま"
  },
  "鳥取": {
    "id": "Tottori",
    "en": "Tottori",
    "reading": "とっとり"
  },
  "島根": {
    "id": "Shimane",
    "en": "Shimane",
    "reading": "しまね"
  },
  "岡山": {
    "id": "Okayama",
    "en": "Okayama",
    "reading": "おかやま"
  },
  "広島": {
    "id": "Hiroshima",
    "en": "Hiroshima",
    "reading": "ひろしま"
  },
  "山口": {
    "id": "Yamaguchi",
    "en": "Yamaguchi",
    "reading": "やまぐち"
  },
  "徳島": {
    "id": "Tokushima",
    "en": "Tokushima",
    "reading": "とくしま"
  },
  "香川": {
    "id": "Kagawa",
    "en": "Kagawa",
    "reading": "かがわ"
  },
  "愛媛": {
    "id": "Ehime",
    "en": "Ehime",
    "reading": "えひめ"
  },
  "高知": {
    "id": "Kochi",
    "en": "Kochi",
    "reading": "こうち"
  },
  "福岡": {
    "id": "Fukuoka",
    "en": "Fukuoka",
    "reading": "ふくおか"
  },
  "佐賀": {
    "id": "Saga",
    "en": "Saga",
    "reading": "さが"
  },
  "長崎": {
    "id": "Nagasaki",
    "en": "Nagasaki",
    "reading": "ながさき"
  },
  "熊本": {
    "id": "Kumamoto",
    "en": "Kumamoto",
    "reading": "くまもと"
  },
  "大分": {
    "id": "Oita",
    "en": "Oita",
    "reading": "おおいた"
  },
  "宮崎": {
    "id": "Miyazaki",
    "en": "Miyazaki",
    "reading": "みやざき"
  },
  "鹿児島": {
    "id": "Kagoshima",
    "en": "Kagoshima",
    "reading": "かごしま"
  },
  "沖縄": {
    "id": "Okinawa",
    "en": "Okinawa",
    "reading": "おきなわ"
  },
  "横浜": {
    "id": "Yokohama",
    "en": "Yokohama",
    "reading": "よこはま"
  },
  "名古屋": {
    "id": "Nagoya",
    "en": "Nagoya",
    "reading": "なごや"
  },
  "札幌": {
    "id": "Sapporo",
    "en": "Sapporo",
    "reading": "さっぽろ"
  },
  "神戸": {
    "id": "Kobe",
    "en": "Kobe",
    "reading": "こうべ"
  },
  "仙台": {
    "id": "Sendai",
    "en": "Sendai",
    "reading": "せんだい"
  },
  "川崎": {
    "id": "Kawasaki",
    "en": "Kawasaki",
    "reading": "かわさき"
  },
  "横須賀": {
    "id": "Yokosuka",
    "en": "Yokosuka",
    "reading": "よこすか"
  },
  "鎌倉": {
    "id": "Kamakura",
    "en": "Kamakura",
    "reading": "かまくら"
  },
  "箱根": {
    "id": "Hakone",
    "en": "Hakone",
    "reading": "はこね"
  },
  "金沢": {
    "id": "Kanazawa",
    "en": "Kanazawa",
    "reading": "かなざわ"
  },
  "函館": {
    "id": "Hakodate",
    "en": "Hakodate",
    "reading": "はこだて"
  },
  "小樽": {
    "id": "Otaru",
    "en": "Otaru",
    "reading": "おたる"
  },
  "博多": {
    "id": "Hakata",
    "en": "Hakata",
    "reading": "はかた"
  },
  "渋谷": {
    "id": "Shibuya",
    "en": "Shibuya",
    "reading": "しぶや"
  },
  "新宿": {
    "id": "Shinjuku",
    "en": "Shinjuku",
    "reading": "しんじゅく"
  },
  "池袋": {
    "id": "Ikebukuro",
    "en": "Ikebukuro",
    "reading": "いけぶくろ"
  },
  "秋葉原": {
    "id": "Akihabara",
    "en": "Akihabara",
    "reading": "あきはばら"
  },
  "原宿": {
    "id": "Harajuku",
    "en": "Harajuku",
    "reading": "はらじゅく"
  },
  "銀座": {
    "id": "Ginza",
    "en": "Ginza",
    "reading": "ぎんざ"
  },
  "浅草": {
    "id": "Asakusa",
    "en": "Asakusa",
    "reading": "あさくさ"
  },
  "六本木": {
    "id": "Roppongi",
    "en": "Roppongi",
    "reading": "ろっぽんぎ"
  },
  "品川": {
    "id": "Shinagawa",
    "en": "Shinagawa",
    "reading": "しながわ"
  },
  "上野": {
    "id": "Ueno",
    "en": "Ueno",
    "reading": "うえの"
  },
  "富士": {
    "id": "Fuji",
    "en": "Fuji",
    "reading": "ふじ"
  },
  "関東": {
    "id": "Kanto",
    "en": "Kanto",
    "reading": "かんとう"
  },
  "関西": {
    "id": "Kansai",
    "en": "Kansai",
    "reading": "かんさい"
  },
  "九州": {
    "id": "Kyushu",
    "en": "Kyushu",
    "reading": "きゅうしゅう"
  },
  "四国": {
    "id": "Shikoku",
    "en": "Shikoku",
    "reading": "しこく"
  },
  "江戸": {
    "id": "Edo",
    "en": "Edo",
    "reading": "えど"
  },
  "盛岡": {
    "id": "Morioka",
    "en": "Morioka",
    "reading": "もりおか"
  },
  "水戸": {
    "id": "Mito",
    "en": "Mito",
    "reading": "みと"
  },
  "宇都宮": {
    "id": "Utsunomiya",
    "en": "Utsunomiya",
    "reading": "うつのみや"
  },
  "前橋": {
    "id": "Maebashi",
    "en": "Maebashi",
    "reading": "まえばし"
  },
  "甲府": {
    "id": "Kofu",
    "en": "Kofu",
    "reading": "こうふ"
  },
  "津": {
    "id": "Tsu",
    "en": "Tsu",
    "reading": "つ"
  },
  "大津": {
    "id": "Otsu",
    "en": "Otsu",
    "reading": "おおつ"
  },
  "松江": {
    "id": "Matsue",
    "en": "Matsue",
    "reading": "まつえ"
  },
  "高松": {
    "id": "Takamatsu",
    "en": "Takamatsu",
    "reading": "たかまつ"
  },
  "松山": {
    "id": "Matsuyama",
    "en": "Matsuyama",
    "reading": "まつやま"
  },
  "那覇": {
    "id": "Naha",
    "en": "Naha",
    "reading": "なは"
  },
  "北九州": {
    "id": "Kitakyushu",
    "en": "Kitakyushu",
    "reading": "きたきゅうしゅう"
  },
  "堺": {
    "id": "Sakai",
    "en": "Sakai",
    "reading": "さかい"
  },
  "浜松": {
    "id": "Hamamatsu",
    "en": "Hamamatsu",
    "reading": "はままつ"
  },
  "相模原": {
    "id": "Sagamihara",
    "en": "Sagamihara",
    "reading": "さがみはら"
  },
  "船橋": {
    "id": "Funabashi",
    "en": "Funabashi",
    "reading": "ふなばし"
  },
  "川口": {
    "id": "Kawaguchi",
    "en": "Kawaguchi",
    "reading": "かわぐち"
  },
  "八王子": {
    "id": "Hachioji",
    "en": "Hachioji",
    "reading": "はちおうじ"
  },
  "姫路": {
    "id": "Himeji",
    "en": "Himeji",
    "reading": "ひめじ"
  },
  "東大阪": {
    "id": "Higashiosaka",
    "en": "Higashiosaka",
    "reading": "ひがしおおさか"
  },
  "西宮": {
    "id": "Nishinomiya",
    "en": "Nishinomiya",
    "reading": "にしのみや"
  },
  "市川": {
    "id": "Ichikawa",
    "en": "Ichikawa",
    "reading": "いちかわ"
  },
  "倉敷": {
    "id": "Kurashiki",
    "en": "Kurashiki",
    "reading": "くらしき"
  },
  "福山": {
    "id": "Fukuyama",
    "en": "Fukuyama",
    "reading": "ふくやま"
  },
  "尼崎": {
    "id": "Amagasaki",
    "en": "Amagasaki",
    "reading": "あまがさき"
  },
  "町田": {
    "id": "Machida",
    "en": "Machida",
    "reading": "まちだ"
  },
  "豊田": {
    "id": "Toyota",
    "en": "Toyota",
    "reading": "とよた"
  },
  "藤沢": {
    "id": "Fujisawa",
    "en": "Fujisawa",
    "reading": "ふじさわ"
  },
  "枚方": {
    "id": "Hirakata",
    "en": "Hirakata",
    "reading": "ひらかた"
  },
  "豊中": {
    "id": "Toyonaka",
    "en": "Toyonaka",
    "reading": "とよなか"
  },
  "一宮": {
    "id": "Ichinomiya",
    "en": "Ichinomiya",
    "reading": "いちのみや"
  },
  "岡崎": {
    "id": "Okazaki",
    "en": "Okazaki",
    "reading": "おかざき"
  },
  "高崎": {
    "id": "Takasaki",
    "en": "Takasaki",
    "reading": "たかさき"
  },
  "吹田": {
    "id": "Suita",
    "en": "Suita",
    "reading": "すいた"
  },
  "高槻": {
    "id": "Takatsuki",
    "en": "Takatsuki",
    "reading": "たかつき"
  },
  "旭川": {
    "id": "Asahikawa",
    "en": "Asahikawa",
    "reading": "あさひかわ"
  },
  "郡山": {
    "id": "Koriyama",
    "en": "Koriyama",
    "reading": "こおりやま"
  },
  "川越": {
    "id": "Kawagoe",
    "en": "Kawagoe",
    "reading": "かわごえ"
  },
  "所沢": {
    "id": "Tokorozawa",
    "en": "Tokorozawa",
    "reading": "ところざわ"
  },
  "越谷": {
    "id": "Koshigaya",
    "en": "Koshigaya",
    "reading": "こしがや"
  },
  "松戸": {
    "id": "Matsudo",
    "en": "Matsudo",
    "reading": "まつど"
  },
  "久留米": {
    "id": "Kurume",
    "en": "Kurume",
    "reading": "くるめ"
  },
  "春日井": {
    "id": "Kasugai",
    "en": "Kasugai",
    "reading": "かすがい"
  },
  "四日市": {
    "id": "Yokkaichi",
    "en": "Yokkaichi",
    "reading": "よっかいち"
  },
  "下関": {
    "id": "Shimonoseki",
    "en": "Shimonoseki",
    "reading": "しものせき"
  }
}
'''

DATA['data/surnames.json'] = r'''{
  "佐藤": "さとう",
  "鈴木": "すずき",
  "高橋": "たかはし",
  "田中": "たなか",
  "伊藤": "いとう",
  "渡辺": "わたなべ",
  "山本": "やまもと",
  "中村": "なかむら",
  "小林": "こばやし",
  "加藤": "かとう",
  "吉田": "よしだ",
  "山田": "やまだ",
  "佐々木": "ささき",
  "山口": "やまぐち",
  "松本": "まつもと",
  "井上": "いのうえ",
  "木村": "きむら",
  "林": "はやし",
  "斎藤": "さいとう",
  "斉藤": "さいとう",
  "清水": "しみず",
  "山崎": "やまざき",
  "森": "もり",
  "池田": "いけだ",
  "橋本": "はしもと",
  "阿部": "あべ",
  "石川": "いしかわ",
  "山下": "やました",
  "中島": "なかじま",
  "石井": "いしい",
  "小川": "おがわ",
  "前田": "まえだ",
  "岡田": "おかだ",
  "長谷川": "はせがわ",
  "藤田": "ふじた",
  "後藤": "ごとう",
  "近藤": "こんどう",
  "村上": "むらかみ",
  "遠藤": "えんどう",
  "青木": "あおき",
  "坂本": "さかもと",
  "福田": "ふくだ",
  "太田": "おおた",
  "西村": "にしむら",
  "藤井": "ふじい",
  "金子": "かねこ",
  "岡本": "おかもと",
  "藤原": "ふじわら",
  "中野": "なかの",
  "三浦": "みうら",
  "原田": "はらだ",
  "中川": "なかがわ",
  "松田": "まつだ",
  "竹内": "たけうち",
  "小野": "おの",
  "田村": "たむら",
  "中山": "なかやま",
  "和田": "わだ",
  "石田": "いしだ",
  "森田": "もりた",
  "上田": "うえだ",
  "原": "はら",
  "内田": "うちだ",
  "柴田": "しばた",
  "酒井": "さかい",
  "宮崎": "みやざき",
  "横山": "よこやま",
  "高木": "たかぎ",
  "安藤": "あんどう",
  "宮本": "みやもと",
  "大野": "おおの",
  "小島": "こじま",
  "谷口": "たにぐち",
  "今井": "いまい",
  "工藤": "くどう",
  "増田": "ますだ",
  "丸山": "まるやま",
  "杉山": "すぎやま",
  "村田": "むらた",
  "大塚": "おおつか",
  "新井": "あらい",
  "小山": "こやま",
  "平野": "ひらの",
  "藤本": "ふじもと",
  "上野": "うえの",
  "野口": "のぐち",
  "武田": "たけだ",
  "松井": "まつい",
  "千葉": "ちば",
  "岩崎": "いわさき",
  "菅原": "すがわら",
  "木下": "きのした",
  "久保": "くぼ",
  "佐野": "さの",
  "野村": "のむら",
  "松尾": "まつお",
  "市川": "いちかわ",
  "菊地": "きくち",
  "菊池": "きくち",
  "杉本": "すぎもと",
  "古川": "ふるかわ",
  "大西": "おおにし",
  "島田": "しまだ",
  "水野": "みずの",
  "桜井": "さくらい",
  "高野": "たかの",
  "山内": "やまうち",
  "西田": "にしだ",
  "飯田": "いいだ",
  "西川": "にしかわ",
  "小松": "こまつ",
  "北村": "きたむら",
  "安田": "やすだ",
  "五十嵐": "いがらし",
  "川口": "かわぐち",
  "平田": "ひらた",
  "関": "せき",
  "中田": "なかた",
  "久保田": "くぼた",
  "服部": "はっとり",
  "川村": "かわむら",
  "岩田": "いわた",
  "辻": "つじ",
  "本田": "ほんだ",
  "樋口": "ひぐち",
  "秋山": "あきやま",
  "中西": "なかにし",
  "吉村": "よしむら",
  "田口": "たぐち",
  "大久保": "おおくぼ",
  "永井": "ながい",
  "中原": "なかはら",
  "松岡": "まつおか",
  "荒木": "あらき",
  "浅野": "あさの",
  "大川": "おおかわ",
  "星野": "ほしの",
  "黒田": "くろだ",
  "堀": "ほり",
  "尾崎": "おざき",
  "望月": "もちづき",
  "永田": "ながた",
  "松下": "まつした",
  "大橋": "おおはし",
  "片山": "かたやま",
  "岡崎": "おかざき",
  "川上": "かわかみ",
  "石原": "いしはら",
  "松浦": "まつうら",
  "小池": "こいけ",
  "内藤": "ないとう",
  "宮田": "みやた",
  "桑原": "くわばら",
  "高山": "たかやま",
  "早川": "はやかわ",
  "小西": "こにし",
  "坂口": "さかぐち",
  "吉野": "よしの",
  "森本": "もりもと",
  "大島": "おおしま",
  "北川": "きたがわ",
  "宮下": "みやした",
  "平井": "ひらい",
  "小田": "おだ",
  "西山": "にしやま",
  "野田": "のだ",
  "須藤": "すどう",
  "大竹": "おおたけ",
  "浜田": "はまだ",
  "田辺": "たなべ",
  "吉岡": "よしおか",
  "福島": "ふくしま",
  "小沢": "おざわ",
  "中井": "なかい",
  "上原": "うえはら",
  "栗原": "くりはら",
  "矢野": "やの",
  "白石": "しらいし",
  "小野寺": "おのでら",
  "岩本": "いわもと",
  "杉浦": "すぎうら",
  "本間": "ほんま",
  "松村": "まつむら",
  "今村": "いまむら",
  "富田": "とみた",
  "篠原": "しのはら",
  "横田": "よこた",
  "西尾": "にしお",
  "川崎": "かわさき",
  "堀内": "ほりうち",
  "前川": "まえかわ",
  "森川": "もりかわ",
  "土屋": "つちや",
  "小泉": "こいずみ",
  "高瀬": "たかせ",
  "朝倉": "あさくら",
  "霧島": "きりしま",
  "神崎": "かんざき",
  "天野": "あまの",
  "結城": "ゆうき",
  "一ノ瀬": "いちのせ",
  "二宮": "にのみや",
  "白鳥": "しらとり",
  "有馬": "ありま",
  "宮沢": "みやざわ",
  "黒川": "くろかわ",
  "綾瀬": "あやせ",
  "如月": "きさらぎ",
  "早乙女": "さおとめ",
  "西園寺": "さいおんじ",
  "九条": "くじょう",
  "小鳥遊": "たかなし",
  "鳴海": "なるみ",
  "水瀬": "みなせ",
  "桐生": "きりゅう",
  "町田": "まちだ",
  "松山": "まつやま",
  "藤沢": "ふじさわ",
  "福山": "ふくやま",
  "高松": "たかまつ",
  "船橋": "ふなばし",
  "前橋": "まえばし",
  "高崎": "たかさき",
  "川越": "かわごえ",
  "浜松": "はままつ",
  "大津": "おおつ",
  "松江": "まつえ",
  "水戸": "みと",
  "豊田": "とよだ",
  "松戸": "まつど",
  "盛岡": "もりおか",
  "宇都宮": "うつのみや",
  "吹田": "すいた",
  "高槻": "たかつき",
  "郡山": "こおりやま",
  "一宮": "いちのみや",
  "西宮": "にしのみや",
  "豊中": "とよなか",
  "春日井": "かすがい",
  "尼崎": "あまがさき",
  "長野": "ながの",
  "福井": "ふくい",
  "富山": "とみやま",
  "岡山": "おかやま",
  "広島": "ひろしま",
  "福岡": "ふくおか",
  "熊本": "くまもと",
  "秋田": "あきた",
  "山形": "やまがた",
  "宮城": "みやぎ",
  "香川": "かがわ",
  "長崎": "ながさき",
  "金沢": "かなざわ",
  "渋谷": "しぶや",
  "品川": "しながわ",
  "鎌倉": "かまくら",
  "奈良": "なら",
  "佐賀": "さが",
  "島根": "しまね",
  "東雲": "しののめ",
  "御堂": "みどう",
  "安曇": "あずみ",
  "神楽": "かぐら",
  "宍戸": "ししど",
  "烏丸": "からすま"
}
'''

pasang()

if __name__ == "__main__":
    sys.exit(main())
