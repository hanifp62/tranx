"""Repository layer isolating Firebase Admin SDK (Auth, Firestore, Storage) with a full InMemoryRepository twin."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from tranx_core import (
    AppSettings,
    CacheStore,
    DailyCapExceeded,
    GlossaryBackend,
    InMemoryCacheStore,
    InMemoryGlossaryBackend,
    InMemoryUsageTracker,
    TitleStyle,
    dict_to_glossary_entry,
    glossary_doc_id,
    glossary_entry_to_dict,
)

OWNER_EMAIL = "hanifp633@gmail.com"


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
    def save_message(self, cid: str, mid: str, payload: dict[str, Any]) -> None: ...
    def get_message(self, cid: str, mid: str) -> dict[str, Any] | None: ...
    def save_para(self, cid: str, mid: str, idx: int, payload: dict[str, Any]) -> None: ...
    def list_paras(self, cid: str, mid: str) -> dict[int, dict[str, Any]]: ...
    def delete_conversation_cascade(self, cid: str) -> None: ...
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def save_job(self, job_id: str, payload: dict[str, Any]) -> None: ...
    def read_storage_blob(self, storage_path: str) -> bytes: ...
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


class InMemoryRepository:
    """Complete deterministic in-memory repository for unit and contract tests."""

    def __init__(self, *, env_api_key: str | None = "test-llm-key") -> None:
        self.cache_store = InMemoryCacheStore()
        self.glossary_backend = InMemoryGlossaryBackend()
        self._usage = InMemoryUsageTracker()
        self._env_api_key = env_api_key
        self._vault_api_key: str | None = None
        self.settings_raw: dict[str, Any] = AppSettings().to_firestore_dict()
        self.engine_status: dict[str, Any] = {}
        self.titles: dict[str, dict[str, Any]] = {}
        self.conversations: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, dict[str, dict[str, Any]]] = {}
        self.paras: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.blobs: dict[str, tuple[bytes, str]] = {}
        self.pair_codes: dict[str, dict[str, Any]] = {}
        self.inbox_tokens: dict[str, dict[str, Any]] = {}
        self.inbox_items: dict[str, dict[str, Any]] = {}
        self.revoked_uids: set[str] = set()

    def verify_owner_token(self, token: str) -> dict[str, Any]:
        if token == "valid-owner-token":
            return {"uid": "owner-1", "email": OWNER_EMAIL, "email_verified": True}
        if token == "valid-paired-token":
            return {"uid": "owner-1", "owner": True}
        if token == "anon-token":
            raise AuthError(403, "ANONYMOUS_FORBIDDEN", "Login anonim tidak diizinkan.")
        if token == "stranger-token":
            raise AuthError(403, "NOT_OWNER", "Akun ini bukan pemilik tranX.")
        raise AuthError(401, "UNAUTHENTICATED", "Token sesi tidak sah atau kedaluwarsa.")

    def get_api_key(self) -> tuple[str | None, str]:
        if self._env_api_key:
            return self._env_api_key, "env"
        if self._vault_api_key:
            return self._vault_api_key, "vault"
        return None, "missing"

    def set_vault_api_key(self, api_key: str) -> None:
        self._vault_api_key = api_key.strip() or None

    def get_settings(self) -> AppSettings:
        return AppSettings.from_dict(self.settings_raw)

    def save_settings(self, patch: dict[str, Any]) -> AppSettings:
        merged = {**self.settings_raw, **patch}
        validated = AppSettings.from_dict(merged)
        self.settings_raw = validated.to_firestore_dict()
        return validated

    def update_engine_status(self, statuses: dict[str, Any]) -> None:
        self.engine_status = dict(statuses)

    def check_and_record_usage(
        self, *, model: str, chars: int, calls: int, char_cap: int, call_cap: int
    ) -> None:
        self._usage.check_and_record(
            model=model,
            chars=chars,
            calls=calls,
            char_cap=char_cap,
            call_cap=call_cap,
        )

    def get_usage_today(self) -> dict[str, Any]:
        return self._usage.snapshot()

    def ensure_title(
        self, title_id: str | None, fallback_name: str, kind: str = "lepas"
    ) -> tuple[str, str, TitleStyle]:
        tid = (title_id or "").strip() or f"t_{secrets.token_hex(6)}"
        existing = self.titles.get(tid)
        if existing is None:
            name = (fallback_name or "Percakapan").strip()[:200]
            style = TitleStyle()
            self.titles[tid] = {
                "name": name,
                "kind": kind,
                "auto": title_id is None,
                "sources": [],
                "style": style.to_dict(),
            }
            self.glossary_backend.set_title(tid, name)
            return tid, name, style
        style = TitleStyle.from_dict(existing.get("style"))
        return tid, str(existing.get("name") or fallback_name), style

    def merge_titles(self, from_id: str, to_id: str) -> dict[str, Any]:
        _, src_entries = self.glossary_backend.load_entries(from_id)
        _, dst_entries = self.glossary_backend.load_entries(to_id)
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
            self.glossary_backend.commit_mutations(to_id, upserts, set())
        if from_id in self.titles:
            self.titles[from_id]["mergedInto"] = to_id
        for conv in self.conversations.values():
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
        now_iso = datetime.now(timezone.utc).isoformat()
        existing = self.conversations.get(cid)
        if existing is None:
            self.conversations[cid] = {
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

    def save_message(self, cid: str, mid: str, payload: dict[str, Any]) -> None:
        bucket = self.messages.setdefault(cid, {})
        existing = bucket.get(mid, {})
        bucket[mid] = {**existing, **payload}

    def get_message(self, cid: str, mid: str) -> dict[str, Any] | None:
        return self.messages.get(cid, {}).get(mid)

    def save_para(self, cid: str, mid: str, idx: int, payload: dict[str, Any]) -> None:
        self.paras.setdefault((cid, mid), {})[idx] = dict(payload)

    def list_paras(self, cid: str, mid: str) -> dict[int, dict[str, Any]]:
        return dict(self.paras.get((cid, mid), {}))

    def delete_conversation_cascade(self, cid: str) -> None:
        self.conversations.pop(cid, None)
        msgs = self.messages.pop(cid, {})
        for mid in msgs:
            self.paras.pop((cid, mid), None)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def save_job(self, job_id: str, payload: dict[str, Any]) -> None:
        existing = self.jobs.get(job_id, {})
        self.jobs[job_id] = {**existing, **payload}

    def read_storage_blob(self, storage_path: str) -> bytes:
        item = self.blobs.get(storage_path)
        if item is None:
            raise FileNotFoundError(f"Objek Storage tidak ditemukan: {storage_path}")
        return item[0]

    def write_storage_blob(
        self, storage_path: str, data: bytes, content_type: str
    ) -> None:
        self.blobs[storage_path] = (data, content_type)

    def create_pair_code(self, owner_uid: str) -> dict[str, Any]:
        code = f"{secrets.randbelow(900000) + 100000:06d}"
        expires_at = time.time() + 120.0
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
        record = self.pair_codes.get(clean)
        if record is None:
            raise AuthError(401, "INVALID_PAIR_CODE", "Kode pasangan tidak ditemukan atau sudah dipakai.")
        record["attempts"] += 1
        if record["attempts"] > 5 or time.time() > record["expiresAt"]:
            self.pair_codes.pop(clean, None)
            raise AuthError(401, "PAIR_CODE_EXPIRED", "Kode pasangan sudah kedaluwarsa.")
        self.pair_codes.pop(clean, None)
        return f"custom-token-for-{record['uid']}"

    def revoke_all_sessions(self, owner_uid: str) -> None:
        self.revoked_uids.add(owner_uid)

    def create_inbox_token(self) -> dict[str, str]:
        token_id = f"inb_{secrets.token_hex(6)}"
        raw_secret = f"txi_{secrets.token_urlsafe(24)}"
        digest = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        self.inbox_tokens[token_id] = {
            "hash": digest,
            "windowHour": "",
            "windowCount": 0,
        }
        return {"id": token_id, "token": raw_secret}

    def push_inbox_item(self, raw_token: str, item: dict[str, Any]) -> str:
        if not raw_token:
            raise AuthError(401, "MISSING_INBOX_TOKEN", "Header X-Inbox-Token wajib diisi.")
        digest = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        matched_rec = None
        for rec in self.inbox_tokens.values():
            if secrets.compare_digest(rec["hash"], digest):
                matched_rec = rec
                break
        if matched_rec is None:
            raise AuthError(401, "INVALID_INBOX_TOKEN", "Token Pintasan tidak dikenal.")

        hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        if matched_rec["windowHour"] != hour_key:
            matched_rec["windowHour"] = hour_key
            matched_rec["windowCount"] = 0
        if matched_rec["windowCount"] >= 30:
            raise AuthError(429, "INBOX_RATE_LIMIT", "Batas 30 kiriman Pintasan per jam tercapai.")
        matched_rec["windowCount"] += 1

        inbox_id = f"item_{secrets.token_hex(6)}"
        self.inbox_items[inbox_id] = {
            "text": str(item.get("text") or "")[:60000],
            "url": str(item.get("url") or "")[:2048] or None,
            "title": str(item.get("title") or "")[:200] or None,
            "processed": False,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        return inbox_id

    def delete_inbox_item(self, inbox_id: str) -> None:
        self.inbox_items.pop(inbox_id, None)

    def export_backup(self) -> dict[str, Any]:
        glossaries = {}
        for tid in self.titles:
            _, entries = self.glossary_backend.load_entries(tid)
            glossaries[tid] = entries
        return {
            "version": "2.1",
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "settings": self.settings_raw,
            "titles": self.titles,
            "glossaries": glossaries,
            "conversations": self.conversations,
            "messages": self.messages,
        }


class _FirestoreCacheStore:
    def __init__(self, db: Any) -> None:
        self._col = db.collection("cacheEntries")

    def get(self, key: str) -> str | None:
        snap = self._col.document(key).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        val = data.get("value")
        return str(val) if isinstance(val, str) else None

    def put_many(self, rows: Sequence[tuple[str, str, str, str, str]]) -> None:
        if not rows:
            return
        batch = self._col._client.batch()
        now = datetime.now(timezone.utc)
        for key, engine, src, tgt, value in rows[:400]:
            ref = self._col.document(key)
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

    def load_entries(self, title_id: str) -> tuple[str, list[dict[str, Any]]]:
        t_snap = self._db.collection("titles").document(title_id).get()
        title_name = title_id
        if t_snap.exists:
            title_name = str((t_snap.to_dict() or {}).get("name") or title_id)
        docs = self._db.collection("titles").document(title_id).collection("glossary").stream()
        rows = [d.to_dict() for d in docs if d.exists]
        return title_name, rows

    def commit_mutations(
        self,
        title_id: str,
        upserts: dict[str, dict[str, Any]],
        removals: set[str],
    ) -> None:
        from google.cloud import firestore as gc_fs

        col = self._db.collection("titles").document(title_id).collection("glossary")
        now = datetime.now(timezone.utc)

        @gc_fs.transactional
        def _txn(transaction: Any) -> None:
            all_ids = sorted(set(upserts.keys()) | set(removals))
            snapshots = {doc_id: col.document(doc_id).get(transaction=transaction) for doc_id in all_ids}
            for doc_id in removals:
                snap = snapshots[doc_id]
                if snap.exists:
                    cur = snap.to_dict() or {}
                    if cur.get("source") == "user" and cur.get("confirmed") is True:
                        continue
                    transaction.delete(col.document(doc_id))
            for doc_id, incoming in upserts.items():
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
                self._db.collection("titles").document(title_id),
                {"updatedAt": now},
                merge=True,
            )

        _txn(self._db.transaction())


class FirestoreRepository:
    """Production Firebase Admin repository (Auth + Firestore + Cloud Storage)."""

    def __init__(self, *, env_api_key_getter=lambda: None) -> None:
        from firebase_admin import auth as fb_auth
        from firebase_admin import firestore as fb_fs
        from firebase_admin import storage as fb_storage

        self._auth = fb_auth
        self._db = fb_fs.client()
        self._storage = fb_storage
        self._env_key_getter = env_api_key_getter
        self.cache_store = _FirestoreCacheStore(self._db)
        self.glossary_backend = _FirestoreGlossaryBackend(self._db)

    def verify_owner_token(self, token: str) -> dict[str, Any]:
        if not token:
            raise AuthError(401, "UNAUTHENTICATED", "Header Authorization Bearer wajib disertakan.")
        try:
            decoded = self._auth.verify_id_token(token, check_revoked=True)
        except Exception as exc:
            raise AuthError(401, "INVALID_TOKEN", f"Token sesi tidak sah: {exc}") from exc

        firebase_claim = decoded.get("firebase") or {}
        if firebase_claim.get("sign_in_provider") == "anonymous":
            raise AuthError(403, "ANONYMOUS_FORBIDDEN", "Login anonim ditolak.")

        is_verified_email = (
            decoded.get("email") == OWNER_EMAIL and decoded.get("email_verified") is True
        )
        is_paired_owner = decoded.get("owner") is True
        if not (is_verified_email or is_paired_owner):
            raise AuthError(403, "NOT_OWNER", "Akses ditolak: bukan akun pemilik.")

        uid = str(decoded["uid"])
        owner_ref = self._db.collection("settings").document("owner")
        owner_snap = owner_ref.get()
        if not owner_snap.exists:
            owner_ref.set(
                {
                    "uid": uid,
                    "email": OWNER_EMAIL,
                    "lockedAt": datetime.now(timezone.utc),
                }
            )
        else:
            locked_uid = (owner_snap.to_dict() or {}).get("uid")
            if locked_uid and locked_uid != uid:
                raise AuthError(403, "UID_MISMATCH", "UID tidak cocok dengan pemilik terdaftar.")
        return decoded

    def get_api_key(self) -> tuple[str | None, str]:
        env_key = self._env_key_getter()
        if env_key:
            return env_key, "env"
        snap = self._db.collection("serverSecrets").document("llm").get()
        if snap.exists:
            val = (snap.to_dict() or {}).get("apiKey")
            if isinstance(val, str) and val.strip():
                return val.strip(), "vault"
        return None, "missing"

    def set_vault_api_key(self, api_key: str) -> None:
        clean = api_key.strip()
        ref = self._db.collection("serverSecrets").document("llm")
        if clean:
            ref.set({"apiKey": clean, "updatedAt": datetime.now(timezone.utc)})
        else:
            ref.delete()

    def get_settings(self) -> AppSettings:
        snap = self._db.collection("settings").document("app").get()
        return AppSettings.from_dict(snap.to_dict() if snap.exists else None)

    def save_settings(self, patch: dict[str, Any]) -> AppSettings:
        cur = self.get_settings().to_firestore_dict()
        validated = AppSettings.from_dict({**cur, **patch})
        data = {**validated.to_firestore_dict(), "updatedAt": datetime.now(timezone.utc)}
        self._db.collection("settings").document("app").set(data, merge=True)
        return validated

    def update_engine_status(self, statuses: dict[str, Any]) -> None:
        self._db.collection("settings").document("engineStatus").set(
            {"byModel": statuses, "updatedAt": datetime.now(timezone.utc)}
        )

    def check_and_record_usage(
        self, *, model: str, chars: int, calls: int, char_cap: int, call_cap: int
    ) -> None:
        from google.cloud import firestore as gc_fs

        day_key = InMemoryUsageTracker.today_key()
        ref = self._db.collection("usage").document(day_key)

        @gc_fs.transactional
        def _txn(transaction: Any) -> None:
            snap = ref.get(transaction=transaction)
            cur = snap.to_dict() if snap.exists else {"chars": 0, "calls": 0, "byModel": {}}
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
        snap = self._db.collection("usage").document(day_key).get()
        cur = snap.to_dict() if snap.exists else {"chars": 0, "calls": 0, "byModel": {}}
        return {
            "day": day_key,
            "chars": int(cur.get("chars", 0)),
            "calls": int(cur.get("calls", 0)),
            "byModel": dict(cur.get("byModel") or {}),
        }

    def ensure_title(
        self, title_id: str | None, fallback_name: str, kind: str = "lepas"
    ) -> tuple[str, str, TitleStyle]:
        tid = (title_id or "").strip() or f"t_{secrets.token_hex(6)}"
        ref = self._db.collection("titles").document(tid)
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
            return self.ensure_title(str(data["mergedInto"]), fallback_name, kind)
        style = TitleStyle.from_dict(data.get("style"))
        return tid, str(data.get("name") or fallback_name), style

    def merge_titles(self, from_id: str, to_id: str) -> dict[str, Any]:
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
        self._db.collection("titles").document(from_id).set(
            {"mergedInto": to_id, "updatedAt": now}, merge=True
        )
        for conv in self._db.collection("conversations").where("titleId", "==", from_id).stream():
            conv.reference.update({"titleId": to_id, "updatedAt": now})
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
        ref = self._db.collection("conversations").document(cid)
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

    def save_message(self, cid: str, mid: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        ref = self._db.collection("conversations").document(cid).collection("messages").document(mid)
        data = {**payload, "updatedAt": now}
        if "createdAt" not in data:
            data["createdAt"] = now
        ref.set(data, merge=True)

    def get_message(self, cid: str, mid: str) -> dict[str, Any] | None:
        snap = (
            self._db.collection("conversations")
            .document(cid)
            .collection("messages")
            .document(mid)
            .get()
        )
        return snap.to_dict() if snap.exists else None

    def save_para(self, cid: str, mid: str, idx: int, payload: dict[str, Any]) -> None:
        key = f"{idx:04d}"
        ref = (
            self._db.collection("conversations")
            .document(cid)
            .collection("messages")
            .document(mid)
            .collection("paras")
            .document(key)
        )
        ref.set(payload)

    def list_paras(self, cid: str, mid: str) -> dict[int, dict[str, Any]]:
        col = (
            self._db.collection("conversations")
            .document(cid)
            .collection("messages")
            .document(mid)
            .collection("paras")
        )
        out: dict[int, dict[str, Any]] = {}
        for d in col.stream():
            if d.exists:
                row = d.to_dict() or {}
                idx = int(row.get("i", int(d.id)))
                out[idx] = row
        return out

    def delete_conversation_cascade(self, cid: str) -> None:
        conv_ref = self._db.collection("conversations").document(cid)
        for msg_doc in conv_ref.collection("messages").stream():
            for para_doc in msg_doc.reference.collection("paras").stream():
                para_doc.reference.delete()
            msg_doc.reference.delete()
        conv_ref.delete()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        snap = self._db.collection("jobs").document(job_id).get()
        return snap.to_dict() if snap.exists else None

    def save_job(self, job_id: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        data = {
            **payload,
            "updatedAt": now,
            "expireAt": now + timedelta(days=7),
        }
        self._db.collection("jobs").document(job_id).set(data, merge=True)

    def read_storage_blob(self, storage_path: str) -> bytes:
        bucket = self._storage.bucket()
        blob = bucket.blob(storage_path)
        if not blob.exists():
            raise FileNotFoundError(f"Berkas tidak ditemukan di Storage: {storage_path}")
        return blob.download_as_bytes()

    def write_storage_blob(
        self, storage_path: str, data: bytes, content_type: str
    ) -> None:
        bucket = self._storage.bucket()
        blob = bucket.blob(storage_path)
        blob.upload_from_string(data, content_type=content_type)

    def create_pair_code(self, owner_uid: str) -> dict[str, Any]:
        code = f"{secrets.randbelow(900000) + 100000:06d}"
        expires = datetime.now(timezone.utc) + timedelta(seconds=120)
        self._db.collection("pairCodes").document(code).set(
            {
                "uid": owner_uid,
                "expiresAt": expires,
                "attempts": 0,
            }
        )
        return {"code": code, "expiresAt": expires.isoformat()}

    def redeem_pair_code(self, code: str) -> str:
        clean = (code or "").strip()
        if len(clean) != 6 or not clean.isdigit():
            raise AuthError(400, "INVALID_FORMAT", "Kode pasangan harus terdiri atas 6 angka.")
        ref = self._db.collection("pairCodes").document(clean)
        snap = ref.get()
        if not snap.exists:
            raise AuthError(401, "INVALID_PAIR_CODE", "Kode pasangan salah atau sudah dipakai.")
        rec = snap.to_dict() or {}
        attempts = int(rec.get("attempts", 0)) + 1
        expires_at = rec.get("expiresAt")
        now = datetime.now(timezone.utc)
        if attempts > 5 or (expires_at and now > expires_at):
            ref.delete()
            raise AuthError(401, "PAIR_CODE_EXPIRED", "Kode pasangan sudah kedaluwarsa.")
        ref.delete()
        custom_bytes = self._auth.create_custom_token(str(rec["uid"]), {"owner": True})
        return custom_bytes.decode("utf-8") if isinstance(custom_bytes, bytes) else str(custom_bytes)

    def revoke_all_sessions(self, owner_uid: str) -> None:
        self._auth.revoke_refresh_tokens(owner_uid)

    def create_inbox_token(self) -> dict[str, str]:
        token_id = f"inb_{secrets.token_hex(6)}"
        raw_secret = f"txi_{secrets.token_urlsafe(24)}"
        digest = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        self._db.collection("inboxTokens").document(token_id).set(
            {
                "hash": digest,
                "windowHour": "",
                "windowCount": 0,
                "createdAt": datetime.now(timezone.utc),
            }
        )
        return {"id": token_id, "token": raw_secret}

    def push_inbox_item(self, raw_token: str, item: dict[str, Any]) -> str:
        if not raw_token:
            raise AuthError(401, "MISSING_INBOX_TOKEN", "Header X-Inbox-Token wajib diisi.")
        digest = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        matched_doc = None
        for d in self._db.collection("inboxTokens").stream():
            rec = d.to_dict() or {}
            if isinstance(rec.get("hash"), str) and secrets.compare_digest(rec["hash"], digest):
                matched_doc = d
                break
        if matched_doc is None:
            raise AuthError(401, "INVALID_INBOX_TOKEN", "Token Pintasan tidak sah.")

        rec = matched_doc.to_dict() or {}
        hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        count = int(rec.get("windowCount", 0)) if rec.get("windowHour") == hour_key else 0
        if count >= 30:
            raise AuthError(429, "INBOX_RATE_LIMIT", "Batas 30 kiriman Pintasan per jam tercapai.")
        matched_doc.reference.update({"windowHour": hour_key, "windowCount": count + 1})

        now = datetime.now(timezone.utc)
        inbox_ref = self._db.collection("inbox").document()
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
        self._db.collection("inbox").document(inbox_id).delete()

    def export_backup(self) -> dict[str, Any]:
        titles_out: dict[str, Any] = {}
        glossaries_out: dict[str, Any] = {}
        for tdoc in self._db.collection("titles").stream():
            titles_out[tdoc.id] = _json_safe(tdoc.to_dict() or {})
            _, entries = self.glossary_backend.load_entries(tdoc.id)
            glossaries_out[tdoc.id] = [_json_safe(e) for e in entries]

        convs_out: dict[str, Any] = {}
        for cdoc in self._db.collection("conversations").stream():
            convs_out[cdoc.id] = _json_safe(cdoc.to_dict() or {})

        return {
            "version": "2.1",
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
