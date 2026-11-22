"""Repository layer isolating Firebase Admin SDK (Auth, Firestore, Storage) with a full multi-tenant InMemoryRepository twin."""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import os
import re
import secrets
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from tranx_core import (
    AppSettings,
    CacheStore,
    DailyCapExceeded,
    GlossaryBackend,
    InMemoryCacheStore,
    InMemoryGlossaryBackend,
    InMemoryUsageTracker,
    InputError,
    TitleStyle,
    dict_to_glossary_entry,
    glossary_doc_id,
    glossary_entry_to_dict,
)

_SAFE_STORAGE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,255}$")
_SAFE_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def validate_doc_id(raw: str | None, field: str = "id") -> str:
    clean = (raw or "").strip()
    if not clean or clean in (".", "..") or not _SAFE_DOC_ID_RE.fullmatch(clean):
        raise InputError(f"Identifier {field} tidak sah.")
    return clean


def _validate_user_storage_path(storage_path: str, uid: str) -> str:
    clean = (storage_path or "").strip()
    if not clean or "\x00" in clean or "\\" in clean or "%" in clean or clean.startswith("/"):
        raise InputError("Jalur berkas Storage tidak sah.")
    parts = clean.split("/")
    if len(parts) != 4 or parts[0] not in ("uploads", "outputs") or parts[1] != uid:
        raise AuthError(403, "FORBIDDEN_STORAGE_PATH", "Akses berkas Storage lintas pengguna ditolak.")
    if any(p in ("", ".", "..") or not _SAFE_STORAGE_SEGMENT_RE.match(p) for p in parts[2:]):
        raise InputError("Nama berkas Storage tidak sah.")
    return clean

CURRENT_USER_UID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "tranx_current_uid", default=""
)


def get_current_uid() -> str:
    return CURRENT_USER_UID.get()


def _require_current_uid(uid: str | None = None) -> str:
    target = (uid if uid is not None else get_current_uid()).strip()
    if not target:
        raise AuthError(401, "UNAUTHENTICATED", "Konteks pengguna tidak ditemukan.")
    return target


@contextlib.contextmanager
def scoped_user_uid(uid: str) -> Iterator[None]:
    tok = CURRENT_USER_UID.set(uid)
    try:
        yield
    finally:
        CURRENT_USER_UID.reset(tok)


def _allowed_emails_from_env() -> frozenset[str] | None:
    raw = (os.environ.get("ALLOWED_EMAILS") or "").strip()
    if not raw:
        return None
    items = frozenset(e.strip().lower() for e in raw.split(",") if e.strip())
    return items or None


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class Repository(Protocol):
    cache_store: CacheStore
    glossary_backend: GlossaryBackend

    def verify_owner_token(self, token: str) -> dict[str, Any]: ...
    def assert_uid_allowed(self, uid: str) -> None: ...
    def get_api_key(self) -> tuple[str | None, str]: ...
    def set_vault_api_key(self, api_key: str) -> None: ...
    def get_settings(self) -> AppSettings: ...
    def save_settings(self, patch: dict[str, Any]) -> AppSettings: ...
    def update_engine_status(self, statuses: dict[str, Any]) -> None: ...
    def check_and_record_usage(
        self, *, model: str, chars: int, calls: int, char_cap: int, call_cap: int
    ) -> None: ...
    def get_usage_today(self) -> dict[str, Any]: ...
    def ensure_title(
        self, title_id: str | None, fallback_name: str, kind: str = "lepas"
    ) -> tuple[str, str, TitleStyle]: ...
    def merge_titles(self, from_id: str, to_id: str) -> dict[str, Any]: ...
    def ensure_conversation(
        self,
        cid: str,
        *,
        title: str,
        title_id: str,
        mode: str,
        active_tab: str = "teks",
        preview: str = "",
    ) -> None: ...
    def save_message(
        self, cid: str, mid: str, payload: dict[str, Any], *, is_new: bool = False
    ) -> None: ...
    def get_message(self, cid: str, mid: str) -> dict[str, Any] | None: ...
    def save_para(self, cid: str, mid: str, idx: int, payload: dict[str, Any]) -> None: ...
    def save_paras_batch(
        self, cid: str, mid: str, items: Sequence[tuple[int, dict[str, Any]]]
    ) -> None: ...
    def list_paras(self, cid: str, mid: str) -> dict[int, dict[str, Any]]: ...
    def delete_conversation_cascade(self, cid: str) -> None: ...
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def save_job(self, job_id: str, payload: dict[str, Any]) -> None: ...
    def read_storage_blob(self, storage_path: str) -> bytes: ...
    def download_storage_blob_to_file(
        self, storage_path: str, dest_path: Path, *, max_bytes: int
    ) -> int: ...
    def write_storage_blob(
        self, storage_path: str, data: bytes, content_type: str
    ) -> None: ...
    def create_pair_code(self, owner_uid: str) -> dict[str, Any]: ...
    def redeem_pair_code(self, code: str) -> str: ...
    def revoke_all_sessions(self, owner_uid: str) -> None: ...
    def create_inbox_token(self) -> dict[str, str]: ...
    def push_inbox_item(self, raw_token: str, item: dict[str, Any]) -> str: ...
    def delete_inbox_item(self, inbox_id: str) -> None: ...
    def export_backup(self) -> dict[str, Any]: ...


class _InMemoryUserState:
    def __init__(self) -> None:
        self.cache_store = InMemoryCacheStore()
        self.glossary_backend = InMemoryGlossaryBackend()
        self.usage = InMemoryUsageTracker()
        self.vault_api_key: str | None = None
        self.settings_raw: dict[str, Any] = AppSettings().to_firestore_dict()
        self.engine_status: dict[str, Any] = {}
        self.titles: dict[str, dict[str, Any]] = {}
        self.conversations: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, dict[str, dict[str, Any]]] = {}
        self.paras: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.inbox_items: dict[str, dict[str, Any]] = {}


class _TenantInMemoryCacheStore:
    def __init__(self, repo: InMemoryRepository) -> None:
        self._repo = repo

    def get(self, key: str) -> str | None:
        return self._repo._state().cache_store.get(key)

    def put_many(self, rows: Sequence[tuple[str, str, str, str, str]]) -> None:
        self._repo._state().cache_store.put_many(rows)


class _TenantInMemoryGlossaryBackend:
    def __init__(self, repo: InMemoryRepository) -> None:
        self._repo = repo

    def set_title(self, title_id: str, name: str) -> None:
        self._repo._state().glossary_backend.set_title(title_id, name)

    def load_entries(self, title_id: str) -> tuple[str, list[dict[str, Any]]]:
        return self._repo._state().glossary_backend.load_entries(title_id)

    def commit_mutations(
        self,
        title_id: str,
        upserts: dict[str, dict[str, Any]],
        removals: set[str],
    ) -> None:
        self._repo._state().glossary_backend.commit_mutations(title_id, upserts, removals)


class InMemoryRepository:
    """Complete deterministic multi-tenant in-memory repository for unit and contract tests."""

    def __init__(self, *, env_api_key: str | None = "test-llm-key") -> None:
        self._env_api_key = env_api_key
        self._users: dict[str, _InMemoryUserState] = {}
        self.cache_store: CacheStore = _TenantInMemoryCacheStore(self)
        self.glossary_backend: Any = _TenantInMemoryGlossaryBackend(self)
        self.blobs: dict[str, tuple[bytes, str]] = {}
        self.pair_codes: dict[str, dict[str, Any]] = {}
        self._pair_failed_attempts: int = 0
        self.inbox_tokens: dict[str, dict[str, Any]] = {}
        self.revoked_uids: set[str] = set()

    def _state(self, uid: str | None = None) -> _InMemoryUserState:
        target = uid or get_current_uid() or "owner-1"
        st = self._users.get(target)
        if st is None:
            st = _InMemoryUserState()
            self._users[target] = st
        return st

    @property
    def settings_raw(self) -> dict[str, Any]:
        return self._state().settings_raw

    @settings_raw.setter
    def settings_raw(self, value: dict[str, Any]) -> None:
        self._state().settings_raw = value

    @property
    def engine_status(self) -> dict[str, Any]:
        return self._state().engine_status

    @property
    def titles(self) -> dict[str, dict[str, Any]]:
        return self._state().titles

    @property
    def conversations(self) -> dict[str, dict[str, Any]]:
        return self._state().conversations

    @property
    def messages(self) -> dict[str, dict[str, dict[str, Any]]]:
        return self._state().messages

    @property
    def paras(self) -> dict[tuple[str, str], dict[int, dict[str, Any]]]:
        return self._state().paras

    @property
    def jobs(self) -> dict[str, dict[str, Any]]:
        return self._state().jobs

    @property
    def inbox_items(self) -> dict[str, dict[str, Any]]:
        return self._state().inbox_items

    def verify_owner_token(self, token: str) -> dict[str, Any]:
        allowlist = _allowed_emails_from_env()
        if token == "valid-owner-token":
            email = "user1@example.com"
            if allowlist is not None and email not in allowlist:
                raise AuthError(403, "ACCOUNT_RESTRICTED", "Akun tidak terdaftar dalam daftar izin.")
            CURRENT_USER_UID.set("owner-1")
            return {"uid": "owner-1", "email": email, "email_verified": True}
        if token == "valid-paired-token":
            CURRENT_USER_UID.set("owner-1")
            return {"uid": "owner-1", "paired": True}
        if token == "valid-user-b-token":
            email = "user2@example.com"
            if allowlist is not None and email not in allowlist:
                raise AuthError(403, "ACCOUNT_RESTRICTED", "Akun tidak terdaftar dalam daftar izin.")
            CURRENT_USER_UID.set("user-b")
            return {"uid": "user-b", "email": email, "email_verified": True}
        if token == "anon-token":
            raise AuthError(403, "ANONYMOUS_FORBIDDEN", "Login anonim tidak diizinkan.")
        if token == "unverified-token":
            raise AuthError(403, "EMAIL_UNVERIFIED", "Email akun Google belum terverifikasi.")
        if token == "stranger-token":
            email = "stranger@example.com"
            if allowlist is not None and email not in allowlist:
                raise AuthError(403, "ACCOUNT_RESTRICTED", "Akun tidak terdaftar dalam daftar izin.")
            CURRENT_USER_UID.set("stranger-1")
            return {"uid": "stranger-1", "email": email, "email_verified": True}
        raise AuthError(401, "UNAUTHENTICATED", "Token sesi tidak sah atau kedaluwarsa.")

    def assert_uid_allowed(self, uid: str) -> None:
        clean_uid = (uid or "").strip()
        if not clean_uid:
            raise AuthError(403, "ACCOUNT_RESTRICTED", "Identitas akun tidak sah.")
        allowlist = _allowed_emails_from_env()
        if allowlist is None:
            return
        uid_emails = {
            "owner-1": "user1@example.com",
            "user-b": "user2@example.com",
            "stranger-1": "stranger@example.com",
        }
        email = uid_emails.get(clean_uid, "")
        if email not in allowlist:
            raise AuthError(403, "ACCOUNT_RESTRICTED", "Akun tidak terdaftar dalam daftar izin.")

    def get_api_key(self) -> tuple[str | None, str]:
        st = self._state()
        if st.vault_api_key:
            return st.vault_api_key, "vault"
        if self._env_api_key:
            return self._env_api_key, "env"
        return None, "missing"

    def set_vault_api_key(self, api_key: str) -> None:
        self._state().vault_api_key = api_key.strip() or None

    def get_settings(self) -> AppSettings:
        return AppSettings.from_dict(self._state().settings_raw)

    def save_settings(self, patch: dict[str, Any]) -> AppSettings:
        st = self._state()
        merged = {**st.settings_raw, **patch}
        validated = AppSettings.from_dict(merged)
        st.settings_raw = validated.to_firestore_dict()
        return validated

    def update_engine_status(self, statuses: dict[str, Any]) -> None:
        self._state().engine_status = dict(statuses)

    def check_and_record_usage(
        self, *, model: str, chars: int, calls: int, char_cap: int, call_cap: int
    ) -> None:
        self._state().usage.check_and_record(
            model=model,
            chars=chars,
            calls=calls,
            char_cap=char_cap,
            call_cap=call_cap,
        )

    def get_usage_today(self) -> dict[str, Any]:
        return self._state().usage.snapshot()

    def ensure_title(
        self, title_id: str | None, fallback_name: str, kind: str = "lepas"
    ) -> tuple[str, str, TitleStyle]:
        st = self._state()
        tid = validate_doc_id(title_id, "titleId") if (title_id or "").strip() else f"t_{secrets.token_hex(6)}"
        existing = st.titles.get(tid)
        if existing is None:
            name = (fallback_name or "Percakapan").strip()[:200]
            style = TitleStyle()
            st.titles[tid] = {
                "name": name,
                "kind": kind,
                "auto": title_id is None,
                "sources": [],
                "style": style.to_dict(),
            }
            st.glossary_backend.set_title(tid, name)
            return tid, name, style
        style = TitleStyle.from_dict(existing.get("style"))
        return tid, str(existing.get("name") or fallback_name), style

    def merge_titles(self, from_id: str, to_id: str) -> dict[str, Any]:
        from_id = validate_doc_id(from_id, "fromTitleId")
        to_id = validate_doc_id(to_id, "toTitleId")
        st = self._state()
        _, src_entries = st.glossary_backend.load_entries(from_id)
        _, dst_entries = st.glossary_backend.load_entries(to_id)
        dst_by_surface = {r["surface"]: r for r in dst_entries}
        upserts: dict[str, dict[str, Any]] = {}
        conflicts: list[str] = []
        merged = 0
        for row in src_entries:
            entry = dict_to_glossary_entry(row)
            surf = entry.surface
            existing = dst_by_surface.get(surf)
            if existing is not None:
                if existing.get("source") == "user" and existing.get("confirmed"):
                    if entry.romaji != existing.get("romaji"):
                        conflicts.append(surf)
                    continue
            doc_id = glossary_doc_id(surf)
            upserts[doc_id] = glossary_entry_to_dict(entry)
            merged += 1
        if upserts:
            st.glossary_backend.commit_mutations(to_id, upserts, set())
        if from_id in st.titles:
            st.titles[from_id]["mergedInto"] = to_id
        for conv in st.conversations.values():
            if conv.get("titleId") == from_id:
                conv["titleId"] = to_id
        return {"merged": merged, "conflicts": conflicts}

    def ensure_conversation(
        self,
        cid: str,
        *,
        title: str,
        title_id: str,
        mode: str,
        active_tab: str = "teks",
        preview: str = "",
    ) -> None:
        cid = validate_doc_id(cid, "cid")
        title_id = validate_doc_id(title_id, "titleId")
        st = self._state()
        now_iso = datetime.now(timezone.utc).isoformat()
        existing = st.conversations.get(cid)
        if existing is None:
            st.conversations[cid] = {
                "title": title[:160],
                "titleId": title_id,
                "mode": mode,
                "activeTab": active_tab,
                "pinned": False,
                "pinnedAt": None,
                "preview": preview[:200],
                "createdAt": now_iso,
                "updatedAt": now_iso,
            }
        else:
            existing["mode"] = mode
            existing["activeTab"] = active_tab
            if preview:
                existing["preview"] = preview[:200]
            existing["updatedAt"] = now_iso

    def save_message(
        self, cid: str, mid: str, payload: dict[str, Any], *, is_new: bool = False
    ) -> None:
        del is_new
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        st = self._state()
        bucket = st.messages.setdefault(cid, {})
        existing = bucket.get(mid, {})
        bucket[mid] = {**existing, **payload}

    def get_message(self, cid: str, mid: str) -> dict[str, Any] | None:
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        return self._state().messages.get(cid, {}).get(mid)

    def save_para(self, cid: str, mid: str, idx: int, payload: dict[str, Any]) -> None:
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        self._state().paras.setdefault((cid, mid), {})[idx] = dict(payload)

    def save_paras_batch(
        self, cid: str, mid: str, items: Sequence[tuple[int, dict[str, Any]]]
    ) -> None:
        if not items:
            return
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        bucket = self._state().paras.setdefault((cid, mid), {})
        for idx, payload in items:
            bucket[idx] = dict(payload)

    def list_paras(self, cid: str, mid: str) -> dict[int, dict[str, Any]]:
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        return dict(self._state().paras.get((cid, mid), {}))

    def delete_conversation_cascade(self, cid: str) -> None:
        cid = validate_doc_id(cid, "cid")
        st = self._state()
        st.conversations.pop(cid, None)
        msgs = st.messages.pop(cid, {})
        for mid in msgs:
            st.paras.pop((cid, mid), None)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job_id = validate_doc_id(job_id, "jobId")
        return self._state().jobs.get(job_id)

    def save_job(self, job_id: str, payload: dict[str, Any]) -> None:
        job_id = validate_doc_id(job_id, "jobId")
        st = self._state()
        existing = st.jobs.get(job_id, {})
        st.jobs[job_id] = {**existing, **payload}

    def read_storage_blob(self, storage_path: str) -> bytes:
        safe_path = _validate_user_storage_path(storage_path, get_current_uid() or "owner-1")
        item = self.blobs.get(safe_path)
        if item is None:
            raise InputError("Berkas sumber tidak ditemukan di Storage.")
        return item[0]

    def download_storage_blob_to_file(
        self, storage_path: str, dest_path: Path, *, max_bytes: int
    ) -> int:
        data = self.read_storage_blob(storage_path)
        if len(data) > max_bytes:
            raise InputError("FILE_TOO_LARGE")
        dest_path.write_bytes(data)
        return len(data)

    def write_storage_blob(
        self, storage_path: str, data: bytes, content_type: str
    ) -> None:
        safe_path = _validate_user_storage_path(storage_path, get_current_uid() or "owner-1")
        self.blobs[safe_path] = (data, content_type)

    def create_pair_code(self, owner_uid: str) -> dict[str, Any]:
        code = f"{secrets.randbelow(900000) + 100000:06d}"
        expires_at = time.time() + 120.0
        for stale_code in [k for k, v in self.pair_codes.items() if v.get("uid") == owner_uid]:
            self.pair_codes.pop(stale_code, None)
        self.pair_codes[code] = {
            "uid": owner_uid,
            "expiresAt": expires_at,
            "attempts": 0,
        }
        return {
            "code": code,
            "expiresAt": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }

    def redeem_pair_code(self, code: str) -> str:
        clean = (code or "").strip()
        if len(clean) != 6 or not clean.isdigit():
            raise AuthError(400, "INVALID_FORMAT", "Kode pasangan harus terdiri atas 6 angka.")
        record = self.pair_codes.get(clean)
        if record is None:
            self._pair_failed_attempts += 1
            if self._pair_failed_attempts >= 5:
                self.pair_codes.clear()
                self._pair_failed_attempts = 0
            raise AuthError(401, "INVALID_PAIR_CODE", "Kode pasangan tidak ditemukan atau sudah dipakai.")
        if time.time() > record["expiresAt"]:
            self.pair_codes.pop(clean, None)
            raise AuthError(401, "PAIR_CODE_EXPIRED", "Kode pasangan sudah kedaluwarsa.")
        self.pair_codes.pop(clean, None)
        self._pair_failed_attempts = 0
        return f"custom-token-for-{record['uid']}"

    def revoke_all_sessions(self, owner_uid: str) -> None:
        self.revoked_uids.add(owner_uid)
        for c in [k for k, v in self.pair_codes.items() if v.get("uid") == owner_uid]:
            self.pair_codes.pop(c, None)
        for tid in [k for k, v in self.inbox_tokens.items() if v.get("uid") == owner_uid]:
            self.inbox_tokens.pop(tid, None)

    def create_inbox_token(self) -> dict[str, str]:
        uid = get_current_uid() or "owner-1"
        existing_for_user = [k for k, v in self.inbox_tokens.items() if v.get("uid") == uid]
        if len(existing_for_user) >= 5:
            raise InputError("Batas maksimum 5 token Pintasan aktif tercapai.")
        token_id = f"inb_{secrets.token_hex(6)}"
        raw_secret = f"txi_{secrets.token_urlsafe(24)}"
        digest = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        self.inbox_tokens[digest] = {
            "id": token_id,
            "uid": uid,
            "hash": digest,
            "windowHour": "",
            "windowCount": 0,
        }
        return {"id": token_id, "token": raw_secret}

    def push_inbox_item(self, raw_token: str, item: dict[str, Any]) -> str:
        if not raw_token:
            raise AuthError(401, "MISSING_INBOX_TOKEN", "Header X-Inbox-Token wajib diisi.")
        digest = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        matched_rec = self.inbox_tokens.get(digest)
        if matched_rec is None or not secrets.compare_digest(matched_rec["hash"], digest):
            raise AuthError(401, "INVALID_INBOX_TOKEN", "Token Pintasan tidak dikenal.")

        hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        if matched_rec["windowHour"] != hour_key:
            matched_rec["windowHour"] = hour_key
            matched_rec["windowCount"] = 0
        if matched_rec["windowCount"] >= 30:
            raise AuthError(429, "INBOX_RATE_LIMIT", "Batas 30 kiriman Pintasan per jam tercapai.")
        matched_rec["windowCount"] += 1

        target_uid = str(matched_rec.get("uid") or get_current_uid())
        inbox_id = f"item_{secrets.token_hex(6)}"
        self._state(target_uid).inbox_items[inbox_id] = {
            "text": str(item.get("text") or "")[:60000],
            "url": str(item.get("url") or "")[:2048] or None,
            "title": str(item.get("title") or "")[:200] or None,
            "processed": False,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        return inbox_id

    def delete_inbox_item(self, inbox_id: str) -> None:
        inbox_id = validate_doc_id(inbox_id, "inboxId")
        self._state().inbox_items.pop(inbox_id, None)

    def export_backup(self) -> dict[str, Any]:
        st = self._state()
        glossaries = {}
        for tid in st.titles:
            _, entries = st.glossary_backend.load_entries(tid)
            glossaries[tid] = entries
        return {
            "version": "2.2",
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "settings": st.settings_raw,
            "titles": st.titles,
            "glossaries": glossaries,
            "conversations": st.conversations,
            "messages": st.messages,
        }


class _FirestoreCacheStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    def _col(self) -> Any:
        return self._db.collection("users").document(_require_current_uid()).collection("cacheEntries")

    def get(self, key: str) -> str | None:
        snap = self._col().document(key).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        val = data.get("value")
        return str(val) if isinstance(val, str) else None

    def get_many(self, keys: Sequence[str]) -> dict[str, str]:
        if not keys:
            return {}
        col = self._col()
        out: dict[str, str] = {}
        unique_keys = list(dict.fromkeys(keys))
        for start in range(0, len(unique_keys), 100):
            refs = [col.document(k) for k in unique_keys[start : start + 100]]
            for snap in self._db.get_all(refs):
                if snap.exists:
                    data = snap.to_dict() or {}
                    val = data.get("value")
                    if isinstance(val, str):
                        out[snap.id] = val
        return out

    def put_many(self, rows: Sequence[tuple[str, str, str, str, str]]) -> None:
        if not rows:
            return
        col = self._col()
        now = datetime.now(timezone.utc)
        for start in range(0, len(rows), 400):
            batch = self._db.batch()
            for key, engine, src, tgt, value in rows[start : start + 400]:
                ref = col.document(key)
                batch.set(
                    ref,
                    {
                        "engine": engine,
                        "src": src,
                        "tgt": tgt,
                        "value": value,
                        "updatedAt": now,
                    },
                )
            batch.commit()


class _FirestoreGlossaryBackend:
    def __init__(self, db: Any) -> None:
        self._db = db

    def _titles_col(self) -> Any:
        return self._db.collection("users").document(_require_current_uid()).collection("titles")

    def load_entries(self, title_id: str) -> tuple[str, list[dict[str, Any]]]:
        t_col = self._titles_col()
        t_snap = t_col.document(title_id).get()
        title_name = title_id
        if t_snap.exists:
            title_name = str((t_snap.to_dict() or {}).get("name") or title_id)
        docs = t_col.document(title_id).collection("glossary").stream()
        rows: list[dict[str, Any]] = [d.to_dict() or {} for d in docs if d.exists]
        return title_name, rows

    def commit_mutations(
        self,
        title_id: str,
        upserts: dict[str, dict[str, Any]],
        removals: set[str],
    ) -> None:
        from google.cloud import firestore as gc_fs

        t_col = self._titles_col()
        col = t_col.document(title_id).collection("glossary")
        now = datetime.now(timezone.utc)
        all_ids_sorted = sorted(set(upserts.keys()) | set(removals))
        if not all_ids_sorted:
            return

        # Chunk <= 200 documents per Firestore transaction (safe under 500-op ceiling)
        for start in range(0, len(all_ids_sorted), 200):
            chunk_ids = all_ids_sorted[start : start + 200]
            chunk_removals = [doc_id for doc_id in chunk_ids if doc_id in removals]
            chunk_upserts = [(doc_id, upserts[doc_id]) for doc_id in chunk_ids if doc_id in upserts]

            @gc_fs.transactional
            def _txn(
                transaction: Any,
                _chunk_ids: list[str] = chunk_ids,
                _chunk_removals: list[str] = chunk_removals,
                _chunk_upserts: list[tuple[str, dict[str, Any]]] = chunk_upserts,
            ) -> None:
                snapshots = {
                    doc_id: col.document(doc_id).get(transaction=transaction)
                    for doc_id in _chunk_ids
                }
                for doc_id in _chunk_removals:
                    snap = snapshots[doc_id]
                    if snap.exists:
                        cur = snap.to_dict() or {}
                        if cur.get("source") == "user" and cur.get("confirmed") is True:
                            continue
                        transaction.delete(col.document(doc_id))
                for doc_id, incoming in _chunk_upserts:
                    snap = snapshots[doc_id]
                    if snap.exists:
                        cur = snap.to_dict() or {}
                        if (
                            cur.get("source") == "user"
                            and cur.get("confirmed") is True
                            and incoming.get("source") != "user"
                        ):
                            continue
                    transaction.set(col.document(doc_id), {**incoming, "updatedAt": now})
                transaction.set(
                    t_col.document(title_id),
                    {"updatedAt": now},
                    merge=True,
                )

            _txn(self._db.transaction())


class FirestoreRepository:
    """Production multi-tenant Firebase Admin repository isolated under /users/{uid}/..."""

    def __init__(self, *, env_api_key_getter: Callable[[], str | None] = lambda: None) -> None:
        from firebase_admin import auth as fb_auth
        from firebase_admin import firestore as fb_fs
        from firebase_admin import storage as fb_storage

        self._auth = fb_auth
        self._db = fb_fs.client()
        self._storage = fb_storage
        self._env_key_getter = env_api_key_getter
        self.cache_store = _FirestoreCacheStore(self._db)
        self.glossary_backend = _FirestoreGlossaryBackend(self._db)

    def _user_root(self, uid: str | None = None) -> Any:
        return self._db.collection("users").document(_require_current_uid(uid))

    def assert_uid_allowed(self, uid: str) -> None:
        clean_uid = _require_current_uid(uid)
        try:
            user_rec = self._auth.get_user(clean_uid)
        except Exception as exc:
            raise AuthError(403, "ACCOUNT_RESTRICTED", "Akun pengguna tidak ditemukan atau tidak sah.") from exc
        if getattr(user_rec, "disabled", False):
            raise AuthError(403, "ACCOUNT_DISABLED", "Akun dinonaktifkan.")
        claims = getattr(user_rec, "custom_claims", None) or {}
        is_paired = claims.get("paired") is True or claims.get("owner") is True
        if not getattr(user_rec, "email_verified", False) and not is_paired:
            raise AuthError(403, "EMAIL_UNVERIFIED", "Email akun belum terverifikasi.")
        allowlist = _allowed_emails_from_env()
        if allowlist is not None:
            email_val = str(getattr(user_rec, "email", "") or "").strip().lower()
            if email_val not in allowlist:
                raise AuthError(403, "ACCOUNT_RESTRICTED", "Akun tidak terdaftar dalam daftar izin.")

    def verify_owner_token(self, token: str) -> dict[str, Any]:
        if not token:
            raise AuthError(401, "UNAUTHENTICATED", "Header Authorization Bearer wajib disertakan.")
        try:
            decoded = self._auth.verify_id_token(token, check_revoked=True)
        except Exception as exc:
            raise AuthError(401, "INVALID_TOKEN", "Token sesi tidak sah atau kedaluwarsa.") from exc

        firebase_claim = decoded.get("firebase") or {}
        if firebase_claim.get("sign_in_provider") == "anonymous":
            raise AuthError(403, "ANONYMOUS_FORBIDDEN", "Login anonim ditolak.")

        is_paired = decoded.get("paired") is True or decoded.get("owner") is True
        is_verified_email = decoded.get("email_verified") is True
        if not (is_verified_email or is_paired):
            raise AuthError(403, "EMAIL_UNVERIFIED", "Email akun Google belum terverifikasi.")

        allowlist = _allowed_emails_from_env()
        if allowlist is not None:
            email_val = str(decoded.get("email") or "").strip().lower()
            if not email_val and is_paired:
                try:
                    user_rec = self._auth.get_user(str(decoded["uid"]))
                    email_val = str(getattr(user_rec, "email", "") or "").strip().lower()
                except Exception:
                    email_val = ""
            if email_val not in allowlist:
                raise AuthError(403, "ACCOUNT_RESTRICTED", "Akun tidak terdaftar dalam daftar izin.")

        uid = str(decoded["uid"])
        CURRENT_USER_UID.set(uid)
        return decoded

    def get_api_key(self) -> tuple[str | None, str]:
        root = self._user_root()
        # 1. Server-only vault takes priority over legacy client-readable settings/secrets
        vault_snap = root.collection("serverSecrets").document("llm").get()
        if vault_snap.exists:
            val = (vault_snap.to_dict() or {}).get("apiKey")
            if isinstance(val, str) and val.strip():
                return val.strip(), "vault"
        sec_snap = root.collection("settings").document("secrets").get()
        if sec_snap.exists:
            val = (sec_snap.to_dict() or {}).get("geminiApiKey")
            if isinstance(val, str) and val.strip():
                return val.strip(), "vault"
        # 2. Optional server-level fallback key if configured by deployer
        env_key = self._env_key_getter()
        if env_key:
            return env_key, "env"
        return None, "missing"

    def set_vault_api_key(self, api_key: str) -> None:
        clean = api_key.strip()
        server_ref = self._user_root().collection("serverSecrets").document("llm")
        client_ref = self._user_root().collection("settings").document("secrets")
        if clean:
            server_ref.set({"apiKey": clean, "updatedAt": datetime.now(timezone.utc)})
            client_ref.delete()
        else:
            server_ref.delete()
            client_ref.delete()

    def get_settings(self) -> AppSettings:
        snap = self._user_root().collection("settings").document("app").get()
        return AppSettings.from_dict(snap.to_dict() if snap.exists else None)

    def save_settings(self, patch: dict[str, Any]) -> AppSettings:
        cur = self.get_settings().to_firestore_dict()
        validated = AppSettings.from_dict({**cur, **patch})
        data = {**validated.to_firestore_dict(), "updatedAt": datetime.now(timezone.utc)}
        self._user_root().collection("settings").document("app").set(data, merge=True)
        return validated

    def update_engine_status(self, statuses: dict[str, Any]) -> None:
        self._user_root().collection("settings").document("engineStatus").set(
            {"byModel": statuses, "updatedAt": datetime.now(timezone.utc)}
        )

    def check_and_record_usage(
        self, *, model: str, chars: int, calls: int, char_cap: int, call_cap: int
    ) -> None:
        from google.cloud import firestore as gc_fs

        day_key = InMemoryUsageTracker.today_key()
        ref = self._user_root().collection("usage").document(day_key)

        @gc_fs.transactional
        def _txn(transaction: Any) -> None:
            snap = ref.get(transaction=transaction)
            cur = (snap.to_dict() or {}) if snap.exists else {"chars": 0, "calls": 0, "byModel": {}}
            used_chars = int(cur.get("chars", 0))
            used_calls = int(cur.get("calls", 0))
            if used_chars + max(chars, 0) > char_cap or used_calls + max(calls, 0) > call_cap:
                raise DailyCapExceeded(
                    chars_used=used_chars,
                    char_cap=char_cap,
                    calls_used=used_calls,
                    call_cap=call_cap,
                )
            by_model = dict(cur.get("byModel") or {})
            m_entry = dict(by_model.get(model) or {"chars": 0, "calls": 0})
            m_entry["chars"] = int(m_entry.get("chars", 0)) + max(chars, 0)
            m_entry["calls"] = int(m_entry.get("calls", 0)) + max(calls, 0)
            by_model[model] = m_entry
            transaction.set(
                ref,
                {
                    "chars": used_chars + max(chars, 0),
                    "calls": used_calls + max(calls, 0),
                    "byModel": by_model,
                    "updatedAt": datetime.now(timezone.utc),
                },
            )

        _txn(self._db.transaction())

    def get_usage_today(self) -> dict[str, Any]:
        day_key = InMemoryUsageTracker.today_key()
        snap = self._user_root().collection("usage").document(day_key).get()
        cur = (snap.to_dict() or {}) if snap.exists else {"chars": 0, "calls": 0, "byModel": {}}
        return {
            "day": day_key,
            "chars": int(cur.get("chars", 0)),
            "calls": int(cur.get("calls", 0)),
            "byModel": dict(cur.get("byModel") or {}),
        }

    def ensure_title(
        self,
        title_id: str | None,
        fallback_name: str,
        kind: str = "lepas",
        _seen: set[str] | None = None,
    ) -> tuple[str, str, TitleStyle]:
        seen = _seen if _seen is not None else set()
        raw_tid = (title_id or "").strip()
        tid = validate_doc_id(raw_tid, "titleId") if raw_tid else f"t_{secrets.token_hex(6)}"
        ref = self._user_root().collection("titles").document(tid)
        snap = ref.get()
        now = datetime.now(timezone.utc)
        if not snap.exists:
            name = (fallback_name or "Percakapan").strip()[:200]
            style = TitleStyle()
            ref.set(
                {
                    "name": name,
                    "kind": kind,
                    "auto": title_id is None,
                    "sources": [],
                    "style": style.to_dict(),
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
            return tid, name, style
        data = snap.to_dict() or {}
        if data.get("mergedInto"):
            target_id = str(data["mergedInto"])
            if target_id in seen or len(seen) >= 5:
                raise InputError("Rantai penggabungan judul melingkar terdeteksi.")
            seen.add(tid)
            return self.ensure_title(target_id, fallback_name, kind, _seen=seen)
        style = TitleStyle.from_dict(data.get("style"))
        return tid, str(data.get("name") or fallback_name), style

    def merge_titles(self, from_id: str, to_id: str) -> dict[str, Any]:
        from_id = validate_doc_id(from_id, "fromTitleId")
        to_id = validate_doc_id(to_id, "toTitleId")
        _, src_rows = self.glossary_backend.load_entries(from_id)
        _, dst_rows = self.glossary_backend.load_entries(to_id)
        dst_map = {r.get("surface"): r for r in dst_rows if r.get("surface")}
        upserts: dict[str, dict[str, Any]] = {}
        conflicts: list[str] = []
        merged = 0
        for row in src_rows:
            entry = dict_to_glossary_entry(row)
            cur = dst_map.get(entry.surface)
            if cur and cur.get("source") == "user" and cur.get("confirmed") is True:
                if cur.get("romaji") != entry.romaji:
                    conflicts.append(entry.surface)
                continue
            upserts[glossary_doc_id(entry.surface)] = glossary_entry_to_dict(entry)
            merged += 1
        if upserts:
            self.glossary_backend.commit_mutations(to_id, upserts, set())
        now = datetime.now(timezone.utc)
        root = self._user_root()
        root.collection("titles").document(from_id).set(
            {"mergedInto": to_id, "updatedAt": now}, merge=True
        )
        conv_refs = [
            conv.reference
            for conv in root.collection("conversations").where("titleId", "==", from_id).stream()
        ]
        for start in range(0, len(conv_refs), 400):
            batch = self._db.batch()
            for cref in conv_refs[start : start + 400]:
                batch.update(cref, {"titleId": to_id, "updatedAt": now})
            batch.commit()
        return {"merged": merged, "conflicts": conflicts}

    def ensure_conversation(
        self,
        cid: str,
        *,
        title: str,
        title_id: str,
        mode: str,
        active_tab: str = "teks",
        preview: str = "",
    ) -> None:
        cid = validate_doc_id(cid, "cid")
        title_id = validate_doc_id(title_id, "titleId")
        ref = self._user_root().collection("conversations").document(cid)
        snap = ref.get()
        now = datetime.now(timezone.utc)
        if not snap.exists:
            ref.set(
                {
                    "title": (title or "Percakapan baru")[:160],
                    "titleId": title_id,
                    "mode": mode,
                    "activeTab": active_tab,
                    "pinned": False,
                    "pinnedAt": None,
                    "preview": preview[:200],
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
        else:
            patch: dict[str, Any] = {
                "mode": mode,
                "activeTab": active_tab,
                "updatedAt": now,
            }
            if preview:
                patch["preview"] = preview[:200]
            ref.update(patch)

    def save_message(
        self, cid: str, mid: str, payload: dict[str, Any], *, is_new: bool = False
    ) -> None:
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        now = datetime.now(timezone.utc)
        ref = (
            self._user_root()
            .collection("conversations")
            .document(cid)
            .collection("messages")
            .document(mid)
        )
        data = {**payload, "updatedAt": now}
        if "createdAt" not in data:
            if is_new or not ref.get().exists:
                data["createdAt"] = now
        ref.set(data, merge=True)

    def get_message(self, cid: str, mid: str) -> dict[str, Any] | None:
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        snap = (
            self._user_root()
            .collection("conversations")
            .document(cid)
            .collection("messages")
            .document(mid)
            .get()
        )
        return snap.to_dict() if snap.exists else None

    def save_para(self, cid: str, mid: str, idx: int, payload: dict[str, Any]) -> None:
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        key = f"{idx:04d}"
        ref = (
            self._user_root()
            .collection("conversations")
            .document(cid)
            .collection("messages")
            .document(mid)
            .collection("paras")
            .document(key)
        )
        ref.set(payload)

    def save_paras_batch(
        self, cid: str, mid: str, items: Sequence[tuple[int, dict[str, Any]]]
    ) -> None:
        if not items:
            return
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        col = (
            self._user_root()
            .collection("conversations")
            .document(cid)
            .collection("messages")
            .document(mid)
            .collection("paras")
        )
        for start in range(0, len(items), 400):
            batch = self._db.batch()
            for idx, payload in items[start : start + 400]:
                batch.set(col.document(f"{idx:04d}"), payload)
            batch.commit()

    def list_paras(self, cid: str, mid: str) -> dict[int, dict[str, Any]]:
        cid = validate_doc_id(cid, "cid")
        mid = validate_doc_id(mid, "mid")
        col = (
            self._user_root()
            .collection("conversations")
            .document(cid)
            .collection("messages")
            .document(mid)
            .collection("paras")
        )
        out: dict[int, dict[str, Any]] = {}
        for d in col.stream():
            if d.exists:
                row = d.to_dict() or {}
                raw_i = row.get("i")
                try:
                    idx = int(raw_i) if raw_i is not None else int(d.id)
                except (TypeError, ValueError):
                    continue
                out[idx] = row
        return out

    def delete_conversation_cascade(self, cid: str) -> None:
        cid = validate_doc_id(cid, "cid")
        conv_ref = self._user_root().collection("conversations").document(cid)
        refs_to_delete: list[Any] = []
        for msg_doc in conv_ref.collection("messages").stream():
            for para_doc in msg_doc.reference.collection("paras").stream():
                refs_to_delete.append(para_doc.reference)
            refs_to_delete.append(msg_doc.reference)
        refs_to_delete.append(conv_ref)
        for start in range(0, len(refs_to_delete), 400):
            batch = self._db.batch()
            for r in refs_to_delete[start : start + 400]:
                batch.delete(r)
            batch.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job_id = validate_doc_id(job_id, "jobId")
        snap = self._user_root().collection("jobs").document(job_id).get()
        return snap.to_dict() if snap.exists else None

    def save_job(self, job_id: str, payload: dict[str, Any]) -> None:
        job_id = validate_doc_id(job_id, "jobId")
        now = datetime.now(timezone.utc)
        data = {
            **payload,
            "updatedAt": now,
            "expireAt": now + timedelta(days=7),
        }
        self._user_root().collection("jobs").document(job_id).set(data, merge=True)

    def read_storage_blob(self, storage_path: str) -> bytes:
        safe_path = _validate_user_storage_path(storage_path, _require_current_uid())
        bucket = self._storage.bucket()
        blob = bucket.blob(safe_path)
        if not blob.exists():
            raise InputError("Berkas sumber tidak ditemukan di Storage.")
        return blob.download_as_bytes()

    def download_storage_blob_to_file(
        self, storage_path: str, dest_path: Path, *, max_bytes: int
    ) -> int:
        safe_path = _validate_user_storage_path(storage_path, _require_current_uid())
        bucket = self._storage.bucket()
        blob = bucket.blob(safe_path)
        blob.reload()
        size = int(getattr(blob, "size", 0) or 0)
        if size > max_bytes:
            raise InputError("FILE_TOO_LARGE")
        blob.download_to_filename(str(dest_path))
        actual = dest_path.stat().st_size
        if actual > max_bytes:
            dest_path.unlink(missing_ok=True)
            raise InputError("FILE_TOO_LARGE")
        return actual

    def write_storage_blob(
        self, storage_path: str, data: bytes, content_type: str
    ) -> None:
        safe_path = _validate_user_storage_path(storage_path, _require_current_uid())
        bucket = self._storage.bucket()
        blob = bucket.blob(safe_path)
        blob.upload_from_string(data, content_type=content_type)

    def create_pair_code(self, owner_uid: str) -> dict[str, Any]:
        expires = datetime.now(timezone.utc) + timedelta(seconds=120)
        # Keep only one active pairing code per user at a time
        for stale in self._db.collection("pairCodes").where("uid", "==", owner_uid).stream():
            stale.reference.delete()
        for _ in range(5):
            code = f"{secrets.randbelow(900000) + 100000:06d}"
            ref = self._db.collection("pairCodes").document(code)
            if not ref.get().exists:
                ref.set(
                    {
                        "uid": owner_uid,
                        "expiresAt": expires,
                        "attempts": 0,
                    }
                )
                return {"code": code, "expiresAt": expires.isoformat()}
        raise AuthError(503, "PAIR_CODE_COLLISION", "Gagal membuat kode pasangan, coba lagi.")

    def redeem_pair_code(self, code: str) -> str:
        from google.cloud import firestore as gc_fs

        clean = (code or "").strip()
        if len(clean) != 6 or not clean.isdigit():
            raise AuthError(400, "INVALID_FORMAT", "Kode pasangan harus terdiri atas 6 angka.")
        ref = self._db.collection("pairCodes").document(clean)
        guard_ref = self._db.collection("pairMeta").document("guard")

        @gc_fs.transactional
        def _consume(txn: Any) -> tuple[str | None, bool]:
            snap = ref.get(transaction=txn)
            g_snap = guard_ref.get(transaction=txn)
            now = datetime.now(timezone.utc)
            if not snap.exists:
                g_data = (g_snap.to_dict() or {}) if g_snap.exists else {}
                win_start = g_data.get("windowStart")
                failed = int(g_data.get("failedAttempts", 0))
                if not isinstance(win_start, datetime) or (now - win_start).total_seconds() > 120:
                    failed = 0
                    win_start = now
                failed += 1
                should_purge = failed >= 5
                txn.set(
                    guard_ref,
                    {
                        "failedAttempts": 0 if should_purge else failed,
                        "windowStart": now if should_purge else win_start,
                        "updatedAt": now,
                    },
                )
                return None, should_purge
            rec = snap.to_dict() or {}
            attempts = int(rec.get("attempts", 0))
            expires_at = rec.get("expiresAt")
            if attempts >= 5 or (expires_at and now > expires_at):
                txn.delete(ref)
                raise AuthError(401, "PAIR_CODE_EXPIRED", "Kode pasangan sudah kedaluwarsa.")
            txn.delete(ref)
            txn.set(
                guard_ref,
                {"failedAttempts": 0, "windowStart": now, "updatedAt": now},
            )
            return str(rec["uid"]), False

        uid, should_purge = _consume(self._db.transaction())
        if uid is None:
            if should_purge:
                stale_snaps = list(self._db.collection("pairCodes").limit(50).stream())
                if stale_snaps:
                    batch = self._db.batch()
                    for st_doc in stale_snaps:
                        batch.delete(st_doc.reference)
                    batch.commit()
            raise AuthError(401, "INVALID_PAIR_CODE", "Kode pasangan salah atau sudah dipakai.")

        allowlist = _allowed_emails_from_env()
        if allowlist is not None:
            user_rec = self._auth.get_user(uid)
            email_val = str(getattr(user_rec, "email", "") or "").strip().lower()
            if email_val not in allowlist:
                raise AuthError(403, "ACCOUNT_RESTRICTED", "Akun tidak terdaftar dalam daftar izin.")
        custom_bytes = self._auth.create_custom_token(uid, {"paired": True})
        return custom_bytes.decode("utf-8") if isinstance(custom_bytes, bytes) else str(custom_bytes)

    def revoke_all_sessions(self, owner_uid: str) -> None:
        self._auth.revoke_refresh_tokens(owner_uid)
        now = datetime.now(timezone.utc)
        # Close 60-minute ID token grace window directly in Firestore Security Rules via serverSecrets/session
        self._user_root(owner_uid).collection("serverSecrets").document("session").set(
            {"revokedBefore": int(time.time()), "updatedAt": now}
        )
        for col_name in ("inboxTokens", "pairCodes"):
            for doc_snap in self._db.collection(col_name).where("uid", "==", owner_uid).stream():
                doc_snap.reference.delete()

    def create_inbox_token(self) -> dict[str, str]:
        uid = _require_current_uid()
        existing = list(self._db.collection("inboxTokens").where("uid", "==", uid).stream())
        if len(existing) >= 5:
            raise InputError("Batas maksimum 5 token Pintasan aktif tercapai. Cabut token lama terlebih dahulu.")
        token_id = f"inb_{secrets.token_hex(6)}"
        raw_secret = f"txi_{secrets.token_urlsafe(24)}"
        digest = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        self._db.collection("inboxTokens").document(digest).set(
            {
                "id": token_id,
                "uid": uid,
                "hash": digest,
                "windowHour": "",
                "windowCount": 0,
                "createdAt": datetime.now(timezone.utc),
            }
        )
        return {"id": token_id, "token": raw_secret}

    def push_inbox_item(self, raw_token: str, item: dict[str, Any]) -> str:
        from google.cloud import firestore as gc_fs

        if not raw_token:
            raise AuthError(401, "MISSING_INBOX_TOKEN", "Header X-Inbox-Token wajib diisi.")
        digest = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        ref = self._db.collection("inboxTokens").document(digest)
        hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")

        @gc_fs.transactional
        def _consume_quota(txn: Any) -> str:
            snap = ref.get(transaction=txn)
            if not snap.exists:
                raise AuthError(401, "INVALID_INBOX_TOKEN", "Token Pintasan tidak sah.")
            rec = snap.to_dict() or {}
            if not isinstance(rec.get("hash"), str) or not secrets.compare_digest(rec["hash"], digest):
                raise AuthError(401, "INVALID_INBOX_TOKEN", "Token Pintasan tidak sah.")
            target = str(rec.get("uid") or "").strip()
            if not target:
                raise AuthError(401, "INVALID_INBOX_TOKEN", "Token Pintasan tidak terikat ke akun.")
            count = int(rec.get("windowCount", 0)) if rec.get("windowHour") == hour_key else 0
            if count >= 30:
                raise AuthError(429, "INBOX_RATE_LIMIT", "Batas 30 kiriman Pintasan per jam tercapai.")
            txn.update(ref, {"windowHour": hour_key, "windowCount": count + 1})
            return target

        target_uid = _consume_quota(self._db.transaction())

        now = datetime.now(timezone.utc)
        inbox_ref = self._user_root(target_uid).collection("inbox").document()
        inbox_ref.set(
            {
                "text": str(item.get("text") or "")[:60000],
                "url": str(item.get("url") or "")[:2048] or None,
                "title": str(item.get("title") or "")[:200] or None,
                "processed": False,
                "createdAt": now,
                "expireAt": now + timedelta(days=7),
            }
        )
        return inbox_ref.id

    def delete_inbox_item(self, inbox_id: str) -> None:
        inbox_id = validate_doc_id(inbox_id, "inboxId")
        self._user_root().collection("inbox").document(inbox_id).delete()

    def export_backup(self) -> dict[str, Any]:
        root = self._user_root()
        titles_out: dict[str, Any] = {}
        glossaries_out: dict[str, Any] = {}
        for tdoc in root.collection("titles").stream():
            titles_out[tdoc.id] = _json_safe(tdoc.to_dict() or {})
            _, entries = self.glossary_backend.load_entries(tdoc.id)
            glossaries_out[tdoc.id] = [_json_safe(e) for e in entries]

        convs_out: dict[str, Any] = {}
        for cdoc in root.collection("conversations").stream():
            convs_out[cdoc.id] = _json_safe(cdoc.to_dict() or {})

        return {
            "version": "2.2",
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "settings": self.get_settings().to_firestore_dict(),
            "titles": titles_out,
            "glossaries": glossaries_out,
            "conversations": convs_out,
        }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    return obj
