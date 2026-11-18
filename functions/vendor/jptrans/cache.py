"""Cache terjemahan berbasis sqlite3 dengan mode WAL dan cadangan memori.

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
