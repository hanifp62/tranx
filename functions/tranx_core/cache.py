"""Two-level translation cache: thread-safe in-process LRU backed by pluggable store."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
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

    def get_many(self, keys: Sequence[str]) -> dict[str, str]:
        if not keys:
            return {}
        out: dict[str, str] = {}
        with self._lock:
            for key in keys:
                row = self._data.get(key)
                if row is not None:
                    out[key] = row[3]
        return out

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
        namespace_fn: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(None)
        self._store = store
        self._max_entries = max(max_memory_entries, 64)
        self._namespace_fn = namespace_fn
        self._lru: OrderedDict[str, str] = OrderedDict()
        self._lru_lock = threading.Lock()

    def _mem_key(self, key: str) -> str:
        if self._namespace_fn is None:
            return key
        return f"{self._namespace_fn()}:{key}"

    def get(self, key: str) -> str | None:
        mkey = self._mem_key(key)
        with self._lru_lock:
            if mkey in self._lru:
                self._lru.move_to_end(mkey)
                self._hits += 1
                return self._lru[mkey]

        if self._store is not None:
            persisted = self._store.get(key)
            if persisted is not None:
                with self._lru_lock:
                    self._put_lru(mkey, persisted)
                    self._hits += 1
                return persisted

        with self._lru_lock:
            self._misses += 1
        return None

    def get_many(self, keys: Sequence[str]) -> dict[str, str]:
        """Batch lookup resolving L1 hits first, then a single store.get_many() call for misses."""
        if not keys:
            return {}
        found: dict[str, str] = {}
        missed_keys: list[str] = []
        seen_missed: set[str] = set()
        with self._lru_lock:
            for key in keys:
                mkey = self._mem_key(key)
                if mkey in self._lru:
                    self._lru.move_to_end(mkey)
                    self._hits += 1
                    found[key] = self._lru[mkey]
                elif key not in seen_missed:
                    seen_missed.add(key)
                    missed_keys.append(key)
        if missed_keys and self._store is not None:
            store_get_many = getattr(self._store, "get_many", None)
            fetched: dict[str, str] = {}
            if callable(store_get_many):
                fetched = dict(store_get_many(missed_keys))
            else:
                for key in missed_keys:
                    val = self._store.get(key)
                    if val is not None:
                        fetched[key] = val
            with self._lru_lock:
                for key in missed_keys:
                    if key in fetched:
                        self._put_lru(self._mem_key(key), fetched[key])
                        self._hits += 1
                        found[key] = fetched[key]
                    else:
                        self._misses += 1
        elif missed_keys:
            with self._lru_lock:
                self._misses += len(missed_keys)
        return found

    def put_many(self, rows: Sequence[tuple[str, str, str, str, str]]) -> None:
        if not rows:
            return
        with self._lru_lock:
            for key, _engine, _src, _tgt, value in rows:
                self._put_lru(self._mem_key(key), value)
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
