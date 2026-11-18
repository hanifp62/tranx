"""Two-level translation cache: thread-safe in-process LRU backed by pluggable store."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Sequence
from typing import Protocol

from jptrans.cache import TranslationCache


class CacheStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def put_many(self, rows: Sequence[tuple[str, str, str, str, str]]) -> None: ...


class InMemoryCacheStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, str, str, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._data.get(key)
            return None if row is None else row[3]

    def put_many(self, rows: Sequence[tuple[str, str, str, str, str]]) -> None:
        with self._lock:
            for key, engine, src, tgt, value in rows:
                self._data[key] = (engine, src, tgt, value)


class LayeredTranslationCache(TranslationCache):
    """jptrans.TranslationCache adapter with bounded memory LRU + optional persistent store."""

    def __init__(
        self,
        store: CacheStore | None = None,
        *,
        max_memory_entries: int = 2048,
    ) -> None:
        super().__init__(None)
        self._store = store
        self._max_entries = max(max_memory_entries, 64)
        self._lru: OrderedDict[str, str] = OrderedDict()
        self._lru_lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lru_lock:
            if key in self._lru:
                self._lru.move_to_end(key)
                self._hits += 1
                return self._lru[key]

        if self._store is not None:
            persisted = self._store.get(key)
            if persisted is not None:
                with self._lru_lock:
                    self._put_lru(key, persisted)
                    self._hits += 1
                return persisted

        with self._lru_lock:
            self._misses += 1
        return None

    def put_many(self, rows: Sequence[tuple[str, str, str, str, str]]) -> None:
        if not rows:
            return
        with self._lru_lock:
            for key, _engine, _src, _tgt, value in rows:
                self._put_lru(key, value)
        if self._store is not None:
            self._store.put_many(rows)

    def clear(self) -> int:
        with self._lru_lock:
            removed = len(self._lru)
            self._lru.clear()
            return removed

    def _put_lru(self, key: str, value: str) -> None:
        self._lru[key] = value
        self._lru.move_to_end(key)
        while len(self._lru) > self._max_entries:
            self._lru.popitem(last=False)
