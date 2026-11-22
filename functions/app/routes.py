"""Flask HTTP routes (/v1/*) and Cloud Storage background document processor."""

from __future__ import annotations

import base64
import binascii
import concurrent.futures
import contextvars
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import weakref
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request, stream_with_context
from werkzeug.exceptions import HTTPException

from tranx_core import (
    JPTRANS_VERSION,
    SUPPORTED_MODES,
    SUPPORTED_UI_LANGS,
    AllEnginesFailed,
    AppSettings,
    DailyCapExceeded,
    EngineError,
    FirestoreGlossary,
    GeminiSpeechTranscriber,
    GeminiVisionExtractor,
    InputError,
    LayeredTranslationCache,
    SSRFBlockedError,
    SpeechTranscriber,
    VisionExtractor,
    WebGateBlockedError,
    build_engine_chain,
    chat_config,
    effective_settings_for_key_source,
    export_translated_document,
    fetch_image_safely,
    fetch_url_safely,
    inspect_zip_archive,
    lookup_new_names_for_text,
    parse_aozora,
    parse_mode_pair,
    parse_mode_target,
    read_document_safely,
    read_text,
    rebuild_translated_document_from_paras,
    stream_document_chunks,
    stream_fast_chat,
    supported_formats_metadata,
    transcribe_short_audio,
    translate_image_bytes,
    translate_web_page,
)
from tranx_core.doc_readers import read_docx_document
from tranx_core.speech_stt import ALLOWED_SPEECH_LANGS

from .store import (
    CURRENT_USER_UID,
    AuthError,
    Repository,
    get_current_uid,
    scoped_user_uid,
    validate_doc_id,
)

MAX_STORAGE_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_HTTP_PAYLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_SPEECH_UPLOAD_BYTES = 4 * 1024 * 1024  # 4 MB
ALLOWED_RESUME_SUFFIXES = frozenset({".txt", ".epub", ".pdf", ".docx", ".srt", ".ass", ".ssa", ".vtt", ".md", ".html", ".htm", ".xhtml"})
ALLOWED_TONE_OVERRIDES = frozenset({"auto", "novel", "casual", "formal"})
_API_LOGGER = logging.getLogger("tranx.api")
_BG_CACHE_LOCK = threading.Lock()
_BG_SHARED_CACHES: weakref.WeakKeyDictionary[Any, LayeredTranslationCache] = weakref.WeakKeyDictionary()
_SAFE_CSP_HOST_RE = re.compile(r"^[a-z0-9.-]{1,253}$")


def _resolve_effective_settings(repo: Repository) -> tuple[AppSettings, str | None, str]:
    api_key, key_source = repo.get_api_key()
    settings = effective_settings_for_key_source(repo.get_settings(), key_source)
    return settings, api_key, key_source


def _public_app_origin() -> str:
    raw = (os.environ.get("TRANX_PUBLIC_ORIGIN") or "https://tranx-hanif-id.web.app").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://tranx-hanif-id.web.app"


def _get_bg_shared_cache(repo: Repository) -> LayeredTranslationCache:
    store = repo.cache_store
    with _BG_CACHE_LOCK:
        try:
            cached = _BG_SHARED_CACHES.get(store)
            if cached is None:
                cached = LayeredTranslationCache(store, namespace_fn=get_current_uid)
                _BG_SHARED_CACHES[store] = cached
            return cached
        except TypeError:
            return LayeredTranslationCache(store, namespace_fn=get_current_uid)


class _RepoUsageAdapter:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def check_and_record(
        self, *, model: str, chars: int, calls: int, char_cap: int, call_cap: int
    ) -> None:
        self._repo.check_and_record_usage(
            model=model, chars=chars, calls=calls, char_cap=char_cap, call_cap=call_cap
        )


PROD_ALLOWED_ORIGINS = frozenset(
    {
        "https://tranx-hanif-id.web.app",
        "https://tranx-hanif-id.firebaseapp.com",
    }
)
LOCAL_DEV_ORIGINS = frozenset(
    {
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
    }
)
DEFAULT_ALLOWED_ORIGINS = PROD_ALLOWED_ORIGINS | LOCAL_DEV_ORIGINS


def _allowed_origins() -> frozenset[str]:
    base = PROD_ALLOWED_ORIGINS if os.environ.get("K_SERVICE") else DEFAULT_ALLOWED_ORIGINS
    extra = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    if not extra.strip():
        return base
    custom = {o.strip().rstrip("/") for o in extra.split(",") if o.strip()}
    return base | custom


def _extract_client_ip() -> str:
    """Extract client IP safely without trusting attacker-spoofed leftmost X-Forwarded-For entries.

    Behind Google Front End (Cloud Run / Cloud Functions Gen-2), the verified peer IP is appended
    at the rightmost position of X-Forwarded-For. Reading index [-1] defeats header-rotation bypasses.
    """
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return (request.remote_addr or "unknown").strip() or "unknown"


def _extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _ndjson_line(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


class _SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter protecting 5-10+ concurrent users & auth endpoints."""

    def __init__(self, *, default_rpm: int = 120, auth_rpm: int = 15, window_sec: float = 60.0) -> None:
        self._default_rpm = max(1, default_rpm)
        self._auth_rpm = max(1, auth_rpm)
        self._window_sec = max(1.0, window_sec)
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, *, is_auth: bool = False) -> tuple[bool, int, int, int]:
        limit = self._auth_rpm if is_auth else self._default_rpm
        now = time.monotonic()
        cutoff = now - self._window_sec
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(self._window_sec - (now - bucket[0])) + 1)
                return False, 0, limit, retry_after
            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            # Bound tracked key map to avoid memory growth under IP churn
            if len(self._hits) > 512:
                stale_keys = [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]
                for sk in stale_keys:
                    self._hits.pop(sk, None)
            return True, remaining, limit, 0


def create_flask_app(
    repo: Repository,
    *,
    manifest_hash: str = "verified",
    llm_transport: Any = None,
    vision_extractor_factory: Callable[[str], VisionExtractor] | None = None,
    speech_transcriber_factory: Callable[[str], SpeechTranscriber] | None = None,
    web_fetcher: Any = fetch_url_safely,
    image_fetcher: Any = fetch_image_safely,
    rate_limit_rpm: int = 120,
    auth_rate_limit_rpm: int = 15,
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_HTTP_PAYLOAD_BYTES
    shared_cache = LayeredTranslationCache(repo.cache_store, namespace_fn=get_current_uid)
    usage_adapter = _RepoUsageAdapter(repo)
    rate_limiter = _SlidingWindowRateLimiter(
        default_rpm=rate_limit_rpm,
        auth_rpm=auth_rate_limit_rpm,
    )
    media_proxy_limiter = _SlidingWindowRateLimiter(
        default_rpm=30,
        auth_rpm=15,
    )
    media_proxy_semaphore = threading.BoundedSemaphore(4)

    @app.teardown_request
    def _reset_user_context(_exc: Any = None) -> None:
        CURRENT_USER_UID.set("")

    def _get_request_id() -> str:
        existing = request.environ.get("tranx.request_id")
        if isinstance(existing, str) and existing:
            return existing
        tp = (request.headers.get("traceparent") or "").strip()
        if tp:
            parts = tp.split("-")
            if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{16,32}", parts[1]):
                rid = parts[1].lower()
                request.environ["tranx.request_id"] = rid
                return rid
        raw_hdr = (request.headers.get("X-Request-Id") or "").strip()
        if raw_hdr and re.fullmatch(r"[A-Za-z0-9_.:-]{6,64}", raw_hdr):
            request.environ["tranx.request_id"] = raw_hdr
            return raw_hdr
        rid = secrets.token_hex(8)
        request.environ["tranx.request_id"] = rid
        return rid

    @app.before_request
    def _handle_options_and_rate_limit() -> Any:
        rid = _get_request_id()
        if request.method == "OPTIONS":
            return "", 204
        # Fetch Metadata + Origin CSRF defense on browser state-changing calls
        # (preserves non-browser X-Inbox-Token webhooks on /v1/inbox)
        if request.method in ("POST", "DELETE", "PUT", "PATCH"):
            is_inbox_webhook = request.path == "/v1/inbox" and bool(request.headers.get("X-Inbox-Token"))
            sec_fetch_site = (request.headers.get("Sec-Fetch-Site") or "").strip().lower()
            origin = (request.headers.get("Origin") or "").strip().rstrip("/").lower()
            allowed_origins_lc = {o.lower() for o in _allowed_origins()}
            if not is_inbox_webhook and (sec_fetch_site == "cross-site" or bool(origin)) and origin not in allowed_origins_lc:
                return (
                    jsonify(
                        {
                            "error": {
                                "code": "CSRF_BLOCKED",
                                "message": "Permintaan lintas situs ditolak demi keamanan.",
                                "requestId": rid,
                            }
                        }
                    ),
                    403,
                )
        if request.path == "/v1/healthz":
            return None
        client_ip = _extract_client_ip()
        is_auth_ep = request.path.startswith("/v1/auth:pair")
        bucket_key = f"{'auth' if is_auth_ep else 'api'}:{client_ip}"
        allowed, remaining, limit, retry_after = rate_limiter.check(bucket_key, is_auth=is_auth_ep)
        # Single-owner defense: enforce a global rate limit on /v1/auth:pair across all IPs combined
        # so distributed brute-force against a 6-digit pairing code is impossible.
        if allowed and request.path == "/v1/auth:pair":
            g_allowed, g_remaining, g_limit, g_retry = rate_limiter.check(
                "global:auth:pair", is_auth=True
            )
            if not g_allowed:
                allowed, remaining, limit, retry_after = False, 0, g_limit, g_retry
            else:
                remaining = min(remaining, g_remaining)
        request.environ["tranx.rl_limit"] = str(limit)
        request.environ["tranx.rl_remaining"] = str(remaining)
        if not allowed:
            resp = jsonify(
                {
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Terlalu banyak permintaan dalam waktu singkat. Coba lagi sebentar.",
                        "retryAfter": retry_after,
                        "requestId": rid,
                    }
                }
            )
            resp.status_code = 429
            resp.headers["Retry-After"] = str(retry_after)
            resp.headers["X-RateLimit-Limit"] = str(limit)
            resp.headers["X-RateLimit-Remaining"] = "0"
            return resp
        return None

    @app.after_request
    def _add_cors_and_security_headers(resp: Response) -> Response:
        origin = (request.headers.get("Origin") or "").strip().rstrip("/")
        allowed = _allowed_origins()
        if origin and origin in allowed:
            resp.headers["Access-Control-Allow-Origin"] = origin
        else:
            resp.headers.setdefault(
                "Access-Control-Allow-Origin", "https://tranx-hanif-id.web.app"
            )
        resp.headers["Vary"] = "Origin"
        resp.headers.setdefault(
            "Access-Control-Allow-Headers", "Authorization, Content-Type, X-Inbox-Token, X-Request-Id, traceparent"
        )
        resp.headers.setdefault(
            "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
        )
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        resp.headers.setdefault("X-Request-Id", _get_request_id())
        if request.path.startswith("/v1/"):
            resp.headers.setdefault("Cache-Control", "no-store")
            resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if "tranx.rl_limit" in request.environ:
            resp.headers.setdefault("X-RateLimit-Limit", request.environ["tranx.rl_limit"])
            resp.headers.setdefault("X-RateLimit-Remaining", request.environ["tranx.rl_remaining"])
        return resp

    @app.errorhandler(AuthError)
    def _handle_auth_error(err: AuthError) -> tuple[Response, int]:
        return jsonify({"error": {"code": err.code, "message": err.message, "requestId": _get_request_id()}}), err.status

    @app.errorhandler(SSRFBlockedError)
    def _handle_ssrf_error(err: SSRFBlockedError) -> tuple[Response, int]:
        return jsonify({"error": {"code": "BLOCKED_URL", "message": str(err), "requestId": _get_request_id()}}), 403

    @app.errorhandler(WebGateBlockedError)
    def _handle_gate_error(err: WebGateBlockedError) -> tuple[Response, int]:
        return jsonify({"error": {"code": "SITE_GATE", "message": str(err), "requestId": _get_request_id()}}), 422

    @app.errorhandler(InputError)
    def _handle_input_error(err: InputError) -> tuple[Response, int]:
        return jsonify({"error": {"code": "INVALID_INPUT", "message": str(err), "requestId": _get_request_id()}}), 400

    @app.errorhandler(413)
    def _handle_payload_too_large(_err: Any) -> tuple[Response, int]:
        return (
            jsonify(
                {
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "Ukuran muatan permintaan melebihi batas aman 25 MB.",
                        "requestId": _get_request_id(),
                    }
                }
            ),
            413,
        )

    @app.errorhandler(DailyCapExceeded)
    def _handle_cap_error(err: DailyCapExceeded) -> tuple[Response, int]:
        return (
            jsonify(
                {
                    "error": {
                        "code": "DAILY_CAP_REACHED",
                        "message": "Batas pemakaian harian tercapai.",
                        "charsUsed": err.chars_used,
                        "charCap": err.char_cap,
                        "requestId": _get_request_id(),
                    }
                }
            ),
            429,
        )

    @app.errorhandler(AllEnginesFailed)
    @app.errorhandler(EngineError)
    def _handle_engine_error(err: Exception) -> tuple[Response, int]:
        rid = _get_request_id()
        _API_LOGGER.warning("Upstream engine failure [%s]: %s", rid, type(err).__name__)
        return (
            jsonify(
                {
                    "error": {
                        "code": "ENGINE_UNAVAILABLE",
                        "message": "Layanan mesin terjemahan sedang sibuk atau tidak dapat dijangkau. Coba lagi sebentar.",
                        "requestId": rid,
                    }
                }
            ),
            503,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected_error(err: Exception) -> tuple[Response, int]:
        rid = _get_request_id()
        if isinstance(err, HTTPException):
            status_code = int(err.code or 500)
            code_name = "NOT_FOUND" if status_code == 404 else ("METHOD_NOT_ALLOWED" if status_code == 405 else "HTTP_ERROR")
            return (
                jsonify(
                    {
                        "error": {
                            "code": code_name,
                            "message": str(err.description or err.name),
                            "requestId": rid,
                        }
                    }
                ),
                status_code,
            )
        _API_LOGGER.exception("Unhandled API error [%s]: %s", rid, type(err).__name__)
        return (
            jsonify(
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Terjadi kesalahan internal server.",
                        "requestId": rid,
                    }
                }
            ),
            500,
        )

    @app.route("/v1/<path:_any>", methods=["OPTIONS"])
    def _options_preflight(_any: str) -> tuple[str, int]:
        return "", 204

    def _require_owner() -> dict[str, Any]:
        return repo.verify_owner_token(_extract_bearer_token())

    def _bind_stream(uid: str, gen: Any) -> Any:
        with scoped_user_uid(uid):
            yield from gen

    @app.get("/v1/healthz")
    def healthz() -> tuple[str, int]:
        return "", 204

    @app.get("/v1/meta")
    def get_meta() -> Response:
        _require_owner()
        settings, _, key_source = _resolve_effective_settings(repo)
        return jsonify(
            {
                "modes": list(SUPPORTED_MODES),
                "uiLangs": list(SUPPORTED_UI_LANGS),
                "models": settings.llm_models,
                "formats": supported_formats_metadata(),
                "limits": {
                    "chatMaxChars": settings.chat_max_chars,
                    "longMaxChars": settings.long_max_chars,
                    "maxUploadMb": settings.max_upload_mb,
                    "dailyCharCap": settings.daily_char_cap,
                    "dailyCallCap": settings.daily_call_cap,
                },
                "usageToday": repo.get_usage_today(),
                "keyStatus": {"configured": key_source != "missing", "source": key_source},
                "jptrans": {"version": JPTRANS_VERSION, "manifest": manifest_hash},
            }
        )

    @app.post("/v1/engine:key")
    def set_engine_key() -> Response:
        _require_owner()
        body = request.get_json(silent=True) or {}
        raw_key = str(body.get("apiKey") or "")
        repo.set_vault_api_key(raw_key)
        _, key_source = repo.get_api_key()
        return jsonify({"configured": key_source != "missing", "source": key_source})

    @app.post("/v1/engine:check")
    def check_engines() -> Response:
        _require_owner()
        settings, api_key, _ = _resolve_effective_settings(repo)
        cfg = chat_config(settings, "id")
        engines = build_engine_chain(
            cfg,
            settings,
            api_key=api_key,
            usage_tracker=usage_adapter,
            transport=llm_transport,
        )
        sample_sentences = ["おはようございます。", "千早は小さく笑った。", "次の駅で降ります。"]
        pairs = list(zip(engines, settings.llm_models))

        def _probe_one(item: tuple[Any, str]) -> tuple[str, dict[str, Any], dict[str, Any]]:
            eng, model_name = item
            t0 = time.monotonic()
            try:
                out = eng.translate(sample_sentences, "ja", "id")
                ms = round((time.monotonic() - t0) * 1000)
                return (
                    model_name,
                    {"model": model_name, "ok": True, "ms": ms, "sample": " ".join(out)},
                    {"ok": True, "lastError": None, "ms": ms},
                )
            except Exception as exc:
                ms = round((time.monotonic() - t0) * 1000)
                _API_LOGGER.warning("Model health probe failed (%s): %s", model_name, type(exc).__name__)
                safe_err = f"Model tidak merespons ({type(exc).__name__})"
                return (
                    model_name,
                    {"model": model_name, "ok": False, "ms": ms, "error": safe_err},
                    {"ok": False, "lastError": safe_err, "ms": ms},
                )

        report: list[dict[str, Any]] = []
        status_map: dict[str, Any] = {}
        if len(pairs) > 1 and llm_transport is None:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(pairs))) as pool:
                futs = [pool.submit(contextvars.copy_context().run, _probe_one, p) for p in pairs]
                for fut in futs:
                    model_name, row, st_row = fut.result()
                    report.append(row)
                    status_map[model_name] = st_row
        else:
            for p in pairs:
                model_name, row, st_row = _probe_one(p)
                report.append(row)
                status_map[model_name] = st_row

        repo.update_engine_status(status_map)
        return jsonify({"models": report})

    @app.post("/v1/chat")
    def post_chat() -> Response:
        claims = _require_owner()
        user_uid = str(claims["uid"])
        body = request.get_json(silent=True) or {}
        cid = validate_doc_id(str(body.get("cid") or f"c_{secrets.token_hex(6)}"), "cid")
        user_mid = validate_doc_id(str(body.get("clientMsgId") or f"m_{secrets.token_hex(6)}_u"), "clientMsgId")
        asst_mid = validate_doc_id(f"{user_mid}_r", "clientMsgId")
        mode = str(body.get("mode") or "ja-id").strip()
        text = str(body.get("text") or "")
        clean_text = text.strip()
        if not clean_text:
            raise InputError("Teks masukan kosong.")
        raw_tone = str(body.get("tone") or "auto").strip().lower()
        tone = raw_tone if raw_tone in ALLOWED_TONE_OVERRIDES else "auto"
        requested_title_id = body.get("titleId")
        if requested_title_id is not None and str(requested_title_id).strip():
            requested_title_id = validate_doc_id(str(requested_title_id), "titleId")
        inbox_id = body.get("inboxId")
        if inbox_id is not None and str(inbox_id).strip():
            inbox_id = validate_doc_id(str(inbox_id), "inboxId")

        settings, api_key, _ = _resolve_effective_settings(repo)
        if len(clean_text) > settings.chat_max_chars:
            raise InputError(f"Teks melampaui batas {settings.chat_max_chars} karakter untuk obrolan cepat.")
        parse_mode_pair(
            mode,
            sample_text=clean_text,
            default_source=settings.default_source,
            default_target=settings.default_target,
        )
        first_line = (clean_text.splitlines() or ["Percakapan"])[0][:80]
        tid, title_name, style = repo.ensure_title(requested_title_id, first_line, kind="lepas")
        glossary = FirestoreGlossary.load_from_backend(
            tid, repo.glossary_backend, fallback_title=title_name
        )

        repo.ensure_conversation(
            cid,
            title=first_line,
            title_id=tid,
            mode=mode,
            active_tab="teks",
            preview=first_line,
        )
        repo.save_message(
            cid,
            user_mid,
            {
                "role": "user",
                "kind": "text",
                "mode": mode,
                "text": text,
                "state": "done",
            },
            is_new=True,
        )
        if inbox_id:
            repo.delete_inbox_item(str(inbox_id))

        def _generate() -> Any:
            full_dst = ""
            sentences: list[dict[str, Any]] = []
            used_model = settings.llm_models[0]
            ms = 0
            err_code = None

            for ev in stream_fast_chat(
                text=text,
                mode=mode,
                title_name=title_name,
                settings=settings,
                glossary=glossary,
                cache=shared_cache,
                style=style,
                api_key=api_key,
                usage_tracker=usage_adapter,
                llm_transport=llm_transport,
                tone_override=tone,
            ):
                if ev["type"] == "meta":
                    ev = {**ev, "cid": cid, "mid": asst_mid, "titleId": tid}
                elif ev["type"] == "done":
                    full_dst = ev.get("fullDst", "")
                    sentences = ev.get("sentences", [])
                    used_model = ev.get("model", used_model)
                    ms = int(ev.get("ms", 0))
                    ev = {**ev, "cid": cid, "mid": asst_mid, "titleId": tid}
                elif ev["type"] == "error":
                    err_code = ev.get("code", "ERROR")
                yield _ndjson_line(ev)

            if err_code is None:
                repo.save_message(
                    cid,
                    asst_mid,
                    {
                        "role": "assistant",
                        "kind": "text",
                        "mode": mode,
                        "titleId": tid,
                        "srcText": text,
                        "text": full_dst,
                        "sentences": sentences,
                        "state": "done",
                        "model": used_model,
                        "ms": ms,
                    },
                )
                repo.ensure_conversation(
                    cid,
                    title=first_line,
                    title_id=tid,
                    mode=mode,
                    active_tab="teks",
                    preview=full_dst or first_line,
                )
            else:
                repo.save_message(
                    cid,
                    asst_mid,
                    {
                        "role": "assistant",
                        "kind": "text",
                        "mode": mode,
                        "titleId": tid,
                        "srcText": text,
                        "text": "",
                        "state": "error",
                        "error": err_code,
                    },
                )

        return Response(
            stream_with_context(_bind_stream(user_uid, _generate())),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-store, no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/names:lookup")
    def post_names_lookup() -> Response:
        _require_owner()
        body = request.get_json(silent=True) or {}
        cid = str(body.get("cid") or "").strip()
        mid = str(body.get("mid") or "").strip()
        raw_text = str(body.get("text") or "").strip()
        mode = str(body.get("mode") or "ja-id").strip()
        title_id = body.get("titleId")

        if not raw_text and cid and mid:
            msg = repo.get_message(cid, mid) or {}
            raw_text = str(msg.get("srcText") or msg.get("text") or "")
            mode = str(msg.get("mode") or mode)

        if not raw_text:
            return jsonify({"entries": []})

        settings, api_key, _ = _resolve_effective_settings(repo)
        tid, title_name, style = repo.ensure_title(title_id, "Percakapan")
        glossary = FirestoreGlossary.load_from_backend(
            tid, repo.glossary_backend, fallback_title=title_name
        )
        entries = lookup_new_names_for_text(
            text=raw_text,
            mode=mode,
            title_name=title_name,
            settings=settings,
            glossary=glossary,
            cache=shared_cache,
            style=style,
            api_key=api_key,
            usage_tracker=usage_adapter,
            llm_transport=llm_transport,
        )
        return jsonify({"titleId": tid, "entries": entries})

    @app.post("/v1/speech:transcribe")
    def post_speech_transcribe() -> tuple[Response, int] | Response:
        _require_owner()
        uploaded = request.files.get("audio")
        if uploaded is None:
            return jsonify({"error": {"code": "MISSING_AUDIO", "message": "Berkas audio belum dilampirkan."}}), 400
        audio_bytes = uploaded.read(MAX_SPEECH_UPLOAD_BYTES + 1)
        if len(audio_bytes) > MAX_SPEECH_UPLOAD_BYTES:
            return jsonify({"error": {"code": "AUDIO_TOO_LARGE", "message": "Ukuran klip suara maksimal 4 MB."}}), 413

        mime = uploaded.mimetype or "audio/webm"
        lang = str(request.form.get("lang") or "ja-JP").strip()
        if lang not in ALLOWED_SPEECH_LANGS:
            raise InputError(f"Kode bahasa dikte tidak didukung: {lang!r}")
        settings, api_key, _ = _resolve_effective_settings(repo)
        factory = speech_transcriber_factory or (lambda k: GeminiSpeechTranscriber(k))
        transcriber = factory(api_key or "")
        result = transcribe_short_audio(
            audio_bytes=audio_bytes,
            mime_type=mime,
            lang=lang,
            settings=settings,
            transcriber=transcriber,
            usage_tracker=usage_adapter,
        )
        return jsonify(result)

    @app.post("/v1/image:translate")
    def post_image_translate() -> Response:
        _require_owner()
        body = request.get_json(silent=True) or {}
        cid = validate_doc_id(str(body.get("cid") or f"c_{secrets.token_hex(6)}"), "cid")
        mid = validate_doc_id(str(body.get("clientMsgId") or f"img_{secrets.token_hex(6)}"), "clientMsgId")
        mode = str(body.get("mode") or "ja-id").strip()
        title_id = body.get("titleId")
        if title_id is not None and str(title_id).strip():
            title_id = validate_doc_id(str(title_id), "titleId")
        file_name = str(body.get("fileName") or "gambar.png")

        storage_path = body.get("storagePath")
        image_b64 = body.get("imageB64")
        if storage_path:
            image_bytes = repo.read_storage_blob(str(storage_path))
        elif isinstance(image_b64, str) and image_b64.strip():
            raw_b64 = image_b64.split(",", 1)[-1].strip()
            if len(raw_b64) > int(20 * 1024 * 1024 * 4 / 3) + 16:
                raise InputError("Ukuran gambar terlalu besar.")
            try:
                image_bytes = base64.b64decode(raw_b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise InputError("Format base64 gambar tidak sah.") from exc
        else:
            raise InputError("Sertakan storagePath atau imageB64 untuk menerjemahkan gambar.")

        settings, api_key, _ = _resolve_effective_settings(repo)
        tid, title_name, style = repo.ensure_title(title_id, file_name, kind="komik")
        glossary = FirestoreGlossary.load_from_backend(
            tid, repo.glossary_backend, fallback_title=title_name
        )
        v_factory = vision_extractor_factory or (lambda k: GeminiVisionExtractor(k))
        vision_res = translate_image_bytes(
            image_bytes=image_bytes,
            mode=mode,
            title_name=title_name,
            settings=settings,
            glossary=glossary,
            cache=shared_cache,
            extractor=v_factory(api_key or ""),
            style=style,
            api_key=api_key,
            usage_tracker=usage_adapter,
            llm_transport=llm_transport,
        )

        repo.ensure_conversation(
            cid,
            title=file_name,
            title_id=tid,
            mode=mode,
            active_tab="gambar",
            preview=vision_res["fullDst"] or file_name,
        )
        repo.save_message(
            cid,
            mid,
            {
                "role": "assistant",
                "kind": "image",
                "mode": mode,
                "fileName": file_name,
                "imageResult": vision_res,
                "state": "done",
                "model": vision_res["model"],
            },
        )
        return jsonify({"cid": cid, "mid": mid, "titleId": tid, **vision_res})

    @app.post("/v1/translate")
    def post_translate_long() -> Response:
        claims = _require_owner()
        user_uid = str(claims["uid"])
        body = request.get_json(silent=True) or {}
        cid = validate_doc_id(str(body.get("cid") or f"c_{secrets.token_hex(6)}"), "cid")
        mid = validate_doc_id(str(body.get("clientMsgId") or f"doc_{secrets.token_hex(6)}"), "clientMsgId")
        mode = str(body.get("mode") or "ja-id").strip()
        raw_tone = str(body.get("tone") or "auto").strip().lower()
        tone = raw_tone if raw_tone in ALLOWED_TONE_OVERRIDES else "auto"
        source = body.get("source") or {}
        title_id = body.get("titleId")
        if title_id is not None and str(title_id).strip():
            title_id = validate_doc_id(str(title_id), "titleId")

        settings, api_key, _ = _resolve_effective_settings(repo)

        if isinstance(source.get("aozoraUrl"), str) and source["aozoraUrl"].strip():
            aozora_url = source["aozoraUrl"].strip()
            fetched = web_fetcher(aozora_url)
            doc = parse_aozora(fetched.text, urlsplit(aozora_url).hostname or "Aozora")
            doc_label = doc.title or "Aozora"
        else:
            raw_text = str(source.get("text") or "").strip()
            if not raw_text:
                raise InputError("Teks sumber kosong.")
            if len(raw_text) > settings.long_max_chars:
                raise InputError(f"Teks melebihi batas {settings.long_max_chars} karakter.")
            doc_label = raw_text.splitlines()[0][:80]
            doc = read_text(raw_text, doc_label)

        sample_long = "\n".join(p.text for p in doc.paragraphs[:6])
        parse_mode_pair(
            mode,
            sample_text=sample_long,
            default_source=settings.default_source,
            default_target=settings.default_target,
        )

        tid, title_name, style = repo.ensure_title(title_id, doc_label, kind="novel")
        glossary = FirestoreGlossary.load_from_backend(
            tid, repo.glossary_backend, fallback_title=title_name
        )
        repo.ensure_conversation(
            cid,
            title=doc_label,
            title_id=tid,
            mode=mode,
            active_tab="teks",
            preview=doc_label,
        )
        repo.save_message(
            cid,
            mid,
            {
                "role": "assistant",
                "kind": "long",
                "mode": mode,
                "titleId": tid,
                "fmt": doc.fmt,
                "ruby": doc.ruby,
                "total": len(doc.paragraphs),
                "done": 0,
                "state": "running",
            },
        )

        def _save_chunk_cb(rows: list[tuple[int, dict[str, Any]]], _done: int) -> None:
            repo.save_paras_batch(cid, mid, rows)

        def _stream() -> Any:
            final_state = "done"
            done_paras = 0
            for ev in stream_document_chunks(
                doc=doc,
                mode=mode,
                settings=settings,
                glossary=glossary,
                cache=shared_cache,
                on_chunk_saved=_save_chunk_cb,
                style=style,
                api_key=api_key,
                usage_tracker=usage_adapter,
                llm_transport=llm_transport,
                tone_override=tone,
            ):
                if ev["type"] == "meta":
                    ev = {**ev, "cid": cid, "mid": mid, "titleId": tid}
                elif ev["type"] in ("done", "error"):
                    final_state = str(ev.get("state") or ("done" if ev["type"] == "done" else "error"))
                    done_paras = int(ev.get("doneParas", done_paras))
                yield _ndjson_line(ev)

            repo.save_message(
                cid,
                mid,
                {
                    "done": done_paras,
                    "state": final_state,
                },
            )

        return Response(
            stream_with_context(_bind_stream(user_uid, _stream())),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-store, no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/translate:resume")
    def post_translate_resume() -> Response:
        claims = _require_owner()
        user_uid = str(claims["uid"])
        body = request.get_json(silent=True) or {}
        cid = str(body.get("cid") or "").strip()
        mid = str(body.get("mid") or "").strip()
        msg = repo.get_message(cid, mid)
        if msg is None:
            raise InputError("Pesan yang akan dilanjutkan tidak ditemukan.")

        mode = str(msg.get("mode") or "ja-id")
        tid = str(msg.get("titleId") or "")
        existing_paras = repo.list_paras(cid, mid)
        raw_src = str(body.get("text") or msg.get("srcText") or "")
        if not raw_src and msg.get("jobId"):
            job = repo.get_job(str(msg["jobId"])) or {}
            storage_in = job.get("storageInputPath") or job.get("storagePath")
            if storage_in:
                blob_bytes = repo.read_storage_blob(str(storage_in))
                if len(blob_bytes) > MAX_STORAGE_UPLOAD_BYTES:
                    raise InputError("Ukuran berkas melebihi batas aman 50 MB.")
                raw_suffix = Path(str(job.get("fileName") or "berkas.txt")).suffix.lower()
                suffix = raw_suffix if raw_suffix in ALLOWED_RESUME_SUFFIXES else ".txt"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                    tf.write(blob_bytes)
                    tmp_path = Path(tf.name)
                try:
                    if suffix == ".docx":
                        inspect_zip_archive(tmp_path)
                        doc = read_docx_document(tmp_path, title=str(job.get("fileName") or "Dokumen"), already_validated=True)
                    else:
                        if suffix == ".epub":
                            inspect_zip_archive(tmp_path)
                        doc = read_document_safely(tmp_path, title=str(job.get("fileName") or "Dokumen"))
                finally:
                    tmp_path.unlink(missing_ok=True)
            else:
                raise InputError("Sumber berkas untuk dilanjutkan sudah tidak tersedia.")
        else:
            if not raw_src:
                raise InputError("Teks sumber untuk dilanjutkan tidak tersedia.")
            doc = read_text(raw_src, "Lanjutan")

        settings, api_key, _ = _resolve_effective_settings(repo)
        tid, title_name, style = repo.ensure_title(tid or None, doc.title)
        glossary = FirestoreGlossary.load_from_backend(
            tid, repo.glossary_backend, fallback_title=title_name
        )

        def _save_chunk_cb(rows: list[tuple[int, dict[str, Any]]], _done: int) -> None:
            repo.save_paras_batch(cid, mid, rows)

        def _stream() -> Any:
            final_state = "done"
            done_paras = len(existing_paras)
            for ev in stream_document_chunks(
                doc=doc,
                mode=mode,
                settings=settings,
                glossary=glossary,
                cache=shared_cache,
                existing_paras=existing_paras,
                on_chunk_saved=_save_chunk_cb,
                style=style,
                api_key=api_key,
                usage_tracker=usage_adapter,
                llm_transport=llm_transport,
            ):
                if ev["type"] in ("done", "error"):
                    final_state = str(ev.get("state") or "done")
                    done_paras = int(ev.get("doneParas", done_paras))
                yield _ndjson_line(ev)
            repo.save_message(cid, mid, {"done": done_paras, "state": final_state})

        return Response(
            stream_with_context(_bind_stream(user_uid, _stream())),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-store, no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/messages/<mid>/export")
    def get_message_export(mid: str) -> Response:
        _require_owner()
        cid = str(request.args.get("cid") or "").strip()
        fmt = str(request.args.get("fmt") or "txt").strip().lower()
        bilingual = str(request.args.get("bilingual") or "").lower() in ("1", "true", "yes")
        theme = request.args.get("theme")

        msg = repo.get_message(cid, mid)
        if msg is None:
            raise InputError("Pesan tidak ditemukan.")

        settings = repo.get_settings()
        mode = str(msg.get("mode") or "ja-id")
        target_lang = parse_mode_target(mode, settings.default_target)
        tid = str(msg.get("titleId") or "")
        glossary_entries = ()
        title_name = str(msg.get("fileName") or "Hasil Terjemahan")
        if tid:
            glossary = FirestoreGlossary.load_from_backend(
                tid, repo.glossary_backend, fallback_title=title_name
            )
            title_name = glossary.title
            glossary_entries = glossary.non_builtin_entries()

        paras_map = repo.list_paras(cid, mid)
        if paras_map:
            stored_rows = list(paras_map.values())
        else:
            stored_rows = [
                {
                    "i": 0,
                    "src": str(msg.get("srcText") or ""),
                    "dst": str(msg.get("text") or ""),
                    "sentences": msg.get("sentences") or [],
                }
            ]

        rebuilt = rebuild_translated_document_from_paras(
            title=title_name,
            target_lang=target_lang,
            fmt=str(msg.get("fmt") or "txt"),
            stored_paras=stored_rows,
            glossary_entries=glossary_entries,
            ruby=msg.get("ruby") or {},
        )
        out_bytes, ctype, ext = export_translated_document(
            rebuilt, fmt, bilingual=bilingual, theme=theme
        )
        inline = str(request.args.get("inline") or "") in ("1", "true")
        safe_mid = re.sub(r"[^A-Za-z0-9_-]", "", mid)[:64] or "export"
        disp = "inline" if inline else f'attachment; filename="tranx-{safe_mid}.{ext}"'
        export_headers = {"Content-Disposition": disp, "Content-Type": ctype}
        if ctype.startswith("text/html"):
            export_headers["Content-Security-Policy"] = (
                "sandbox; default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; object-src 'none'; base-uri 'none';"
            )
        return Response(
            out_bytes,
            mimetype=ctype.split(";", 1)[0],
            headers=export_headers,
        )

    @app.post("/v1/links:preview")
    def post_links_preview() -> Response:
        _require_owner()
        body = request.get_json(silent=True) or {}
        cid = validate_doc_id(str(body.get("cid") or f"c_{secrets.token_hex(6)}"), "cid")
        mid = validate_doc_id(str(body.get("clientMsgId") or f"lnk_{secrets.token_hex(6)}"), "clientMsgId")
        mode = str(body.get("mode") or "ja-id").strip()
        url = str(body.get("url") or "").strip()
        title_id = body.get("titleId")
        if title_id is not None and str(title_id).strip():
            title_id = validate_doc_id(str(title_id), "titleId")

        settings, api_key, _ = _resolve_effective_settings(repo)
        host_hint = urlsplit(url).hostname or "Tautan Web"
        tid, title_name, style = repo.ensure_title(title_id, host_hint, kind="web")
        glossary = FirestoreGlossary.load_from_backend(
            tid, repo.glossary_backend, fallback_title=title_name
        )

        web_res = translate_web_page(
            url=url,
            mode=mode,
            title_id=tid,
            view="translated",
            settings=settings,
            glossary=glossary,
            cache=shared_cache,
            style=style,
            fetcher=web_fetcher,
            api_key=api_key,
            usage_tracker=usage_adapter,
            llm_transport=llm_transport,
        )
        locked_raw = web_res.get("lockedNames")
        locked_count = len(locked_raw) if isinstance(locked_raw, list) else int(locked_raw or 0)
        preview_payload = {
            "mid": mid,
            "cid": cid,
            "titleId": tid,
            "url": web_res["finalUrl"],
            "host": web_res["host"],
            "isAozora": web_res["isAozora"],
            "titleSrc": web_res["titleSrc"],
            "titleDst": web_res["titleDst"],
            "excerptSrc": web_res["excerptSrc"],
            "excerptDst": web_res["excerptDst"],
            "paragraphCount": web_res["paragraphCount"],
            "lockedNames": locked_count,
            "readerSupported": True,
        }
        repo.ensure_conversation(
            cid,
            title=web_res["titleDst"] or host_hint,
            title_id=tid,
            mode=mode,
            active_tab="link",
            preview=web_res["excerptDst"] or web_res["titleDst"],
        )
        repo.save_message(
            cid,
            mid,
            {
                "role": "assistant",
                "kind": "link",
                "mode": mode,
                "titleId": tid,
                "linkPreview": preview_payload,
                "state": "done",
            },
        )
        return jsonify(preview_payload)

    @app.get("/v1/media:proxy")
    def get_media_proxy() -> Response | tuple[Response, int]:
        _require_owner()
        client_ip = _extract_client_ip()
        ok_rl, _, _, retry_after = media_proxy_limiter.check(f"media:{client_ip}", is_auth=False)
        if not ok_rl:
            resp = jsonify(
                {
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Terlalu banyak permintaan gambar dalam waktu singkat. Coba lagi sebentar.",
                        "retryAfter": retry_after,
                    }
                }
            )
            resp.headers["Retry-After"] = str(retry_after)
            return resp, 429
        url = str(request.args.get("url") or "").strip()
        if not url:
            raise InputError("Sertakan parameter url gambar.")
        if not media_proxy_semaphore.acquire(blocking=False):
            return (
                jsonify(
                    {
                        "error": {
                            "code": "PROXY_BUSY",
                            "message": "Antrean pengunduhan gambar sedang penuh. Coba lagi sebentar.",
                        }
                    }
                ),
                503,
            )
        try:
            fetched = image_fetcher(url)
        finally:
            media_proxy_semaphore.release()
        return Response(
            fetched.data,
            mimetype=fetched.content_type,
            headers={
                "Content-Type": fetched.content_type,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, max-age=600, no-transform",
                "Cross-Origin-Resource-Policy": "cross-origin",
                "Content-Security-Policy": "default-src 'none'; sandbox;",
            },
        )

    @app.get("/v1/web")
    def get_translated_web() -> Response:
        _require_owner()
        url = str(request.args.get("url") or "").strip()
        mode = str(request.args.get("mode") or "ja-id").strip()
        title_id = request.args.get("titleId")
        view = str(request.args.get("view") or "translated").strip().lower()

        settings, api_key, _ = _resolve_effective_settings(repo)
        host_hint = urlsplit(url).hostname or "Tautan Web"
        tid, title_name, style = repo.ensure_title(title_id, host_hint, kind="web")
        glossary = FirestoreGlossary.load_from_backend(
            tid, repo.glossary_backend, fallback_title=title_name
        )
        web_res = translate_web_page(
            url=url,
            mode=mode,
            title_id=tid,
            view=view,
            settings=settings,
            glossary=glossary,
            cache=shared_cache,
            style=style,
            fetcher=web_fetcher,
            api_key=api_key,
            usage_tracker=usage_adapter,
            llm_transport=llm_transport,
            viewer_route_prefix=f"{_public_app_origin()}/web",
        )
        final_host = (urlsplit(str(web_res.get("finalUrl") or "")).hostname or "").lower()
        style_src = (
            f"style-src 'unsafe-inline' https://{final_host}"
            if final_host and _SAFE_CSP_HOST_RE.fullmatch(final_host)
            else "style-src 'unsafe-inline'"
        )
        return Response(
            web_res["html"],
            mimetype="text/html",
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Security-Policy": f"sandbox allow-top-navigation-by-user-activation; default-src 'none'; {style_src}; img-src https: data:; script-src 'none'; object-src 'none'; base-uri 'none';",
            },
        )

    @app.post("/v1/titles:merge")
    def post_titles_merge() -> Response:
        _require_owner()
        body = request.get_json(silent=True) or {}
        from_id = str(body.get("fromTitleId") or "").strip()
        to_id = str(body.get("toTitleId") or "").strip()
        if not from_id or not to_id or from_id == to_id:
            raise InputError("Pilih dua judul berbeda untuk digabungkan.")
        return jsonify(repo.merge_titles(from_id, to_id))

    @app.post("/v1/auth:pairCode")
    def post_auth_pair_code() -> Response:
        claims = _require_owner()
        return jsonify(repo.create_pair_code(str(claims["uid"])))

    @app.post("/v1/auth:pair")
    def post_auth_pair() -> Response:
        body = request.get_json(silent=True) or {}
        custom_token = repo.redeem_pair_code(str(body.get("code") or ""))
        return jsonify({"customToken": custom_token})

    @app.post("/v1/auth:revoke")
    def post_auth_revoke() -> tuple[str, int]:
        claims = _require_owner()
        repo.revoke_all_sessions(str(claims["uid"]))
        return "", 204

    @app.post("/v1/inbox:token")
    def post_inbox_token() -> Response:
        _require_owner()
        created = repo.create_inbox_token()
        return jsonify(created)

    @app.post("/v1/inbox")
    def post_inbox_push() -> tuple[Response, int]:
        raw_token = request.headers.get("X-Inbox-Token") or ""
        body = request.get_json(silent=True) or {}
        inbox_id = repo.push_inbox_item(raw_token, body)
        return jsonify({"id": inbox_id}), 201

    @app.delete("/v1/inbox/<inbox_id>")
    def delete_inbox(inbox_id: str) -> tuple[str, int]:
        _require_owner()
        repo.delete_inbox_item(inbox_id)
        return "", 204

    @app.get("/v1/backup")
    def get_backup() -> Response:
        _require_owner()
        payload = json.dumps(repo.export_backup(), ensure_ascii=False, indent=2)
        return Response(
            payload.encode("utf-8"),
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="tranx-backup.json"'},
        )

    @app.delete("/v1/conversations/<cid>")
    def delete_conversation(cid: str) -> tuple[str, int]:
        _require_owner()
        repo.delete_conversation_cascade(cid)
        return "", 204

    return app


def process_uploaded_document_blob(
    repo: Repository,
    *,
    object_name: str,
    llm_transport: Any = None,
) -> dict[str, Any]:
    """Background Cloud Storage handler for uploads/{uid}/{jobId}/{fileName}."""
    parts = (object_name or "").strip("/").split("/")
    if len(parts) < 3 or parts[0] != "uploads":
        return {"skipped": True, "reason": "not_uploads_prefix"}

    uid, job_id, file_name = parts[1], parts[2], "/".join(parts[3:])
    with scoped_user_uid(uid):
        return _process_uploaded_document_blob_scoped(
            repo,
            uid=uid,
            job_id=job_id,
            file_name=file_name,
            object_name=object_name,
            llm_transport=llm_transport,
        )


def _process_uploaded_document_blob_scoped(
    repo: Repository,
    *,
    uid: str,
    job_id: str,
    file_name: str,
    object_name: str,
    llm_transport: Any = None,
) -> dict[str, Any]:
    job_id = validate_doc_id(job_id, "jobId")
    job = repo.get_job(job_id) or {}
    cid = validate_doc_id(str(job.get("cid") or f"c_{job_id}"), "cid")
    mid = validate_doc_id(str(job.get("mid") or f"m_{job_id}"), "mid")
    mode = str(job.get("mode") or "ja-id")
    title_id = job.get("titleId")
    if title_id is not None and str(title_id).strip():
        title_id = validate_doc_id(str(title_id), "titleId")

    try:
        repo.assert_uid_allowed(uid)
    except AuthError as exc:
        repo.save_job(job_id, {"state": "error", "errorCode": exc.code, "message": exc.message})
        repo.save_message(cid, mid, {"role": "assistant", "kind": "document", "jobId": job_id, "state": "error", "error": exc.message})
        return {"state": "error", "errorCode": exc.code, "message": exc.message}

    suffix = Path(file_name).suffix.lower()
    if suffix not in ALLOWED_RESUME_SUFFIXES:
        err_msg = f"Format dokumen {suffix or '(tanpa ekstensi)'} tidak didukung."
        repo.save_job(job_id, {"state": "error", "errorCode": "UNSUPPORTED_FORMAT", "message": err_msg})
        repo.save_message(cid, mid, {"role": "assistant", "kind": "document", "jobId": job_id, "state": "error", "error": err_msg})
        return {"state": "error", "errorCode": "UNSUPPORTED_FORMAT", "message": err_msg}

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tmp_path = Path(tf.name)
        dl_to_file = getattr(repo, "download_storage_blob_to_file", None)
        if callable(dl_to_file):
            dl_to_file(object_name, tmp_path, max_bytes=MAX_STORAGE_UPLOAD_BYTES)
        else:
            raw_bytes = repo.read_storage_blob(object_name)
            if len(raw_bytes) > MAX_STORAGE_UPLOAD_BYTES:
                raise InputError("FILE_TOO_LARGE")
            tmp_path.write_bytes(raw_bytes)

        if suffix == ".docx":
            inspect_zip_archive(tmp_path)
            doc = read_docx_document(tmp_path, title=Path(file_name).stem, already_validated=True)
        else:
            if suffix == ".epub":
                inspect_zip_archive(tmp_path)
            doc = read_document_safely(tmp_path, title=Path(file_name).stem)
    except InputError as exc:
        if str(exc) == "FILE_TOO_LARGE":
            err_msg = "Ukuran berkas melebihi batas aman 50 MB."
            repo.save_job(job_id, {"state": "error", "errorCode": "FILE_TOO_LARGE", "message": err_msg})
            repo.save_message(cid, mid, {"role": "assistant", "kind": "document", "jobId": job_id, "state": "error", "error": err_msg})
            return {"state": "error", "errorCode": "FILE_TOO_LARGE", "message": err_msg}
        err_msg = str(exc)
        repo.save_job(job_id, {"state": "error", "errorCode": "UNREADABLE_DOCUMENT", "message": err_msg})
        repo.save_message(cid, mid, {"role": "assistant", "kind": "document", "jobId": job_id, "state": "error", "error": err_msg})
        return {"state": "error", "message": err_msg}
    except Exception as exc:
        _API_LOGGER.exception("Document blob processing failed for %s: %s", job_id, type(exc).__name__)
        err_msg = "Berkas dokumen tidak dapat dibaca atau diproses."
        repo.save_job(job_id, {"state": "error", "errorCode": "UNREADABLE_DOCUMENT", "message": err_msg})
        repo.save_message(cid, mid, {"role": "assistant", "kind": "document", "jobId": job_id, "state": "error", "error": err_msg})
        return {"state": "error", "message": err_msg}
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    settings, api_key, _ = _resolve_effective_settings(repo)
    tid, title_name, style = repo.ensure_title(title_id, Path(file_name).stem, kind="dokumen")
    glossary = FirestoreGlossary.load_from_backend(
        tid, repo.glossary_backend, fallback_title=title_name
    )
    cache = _get_bg_shared_cache(repo)
    usage_adapter = _RepoUsageAdapter(repo)

    repo.ensure_conversation(
        cid,
        title=file_name,
        title_id=tid,
        mode=mode,
        active_tab="dokumen",
        preview=file_name,
    )
    repo.save_job(
        job_id,
        {
            "cid": cid,
            "mid": mid,
            "titleId": tid,
            "state": "running",
            "doneParas": 0,
            "totalParas": len(doc.paragraphs),
            "fmt": doc.fmt,
        },
    )
    repo.save_message(
        cid,
        mid,
        {
            "role": "assistant",
            "kind": "document",
            "mode": mode,
            "titleId": tid,
            "jobId": job_id,
            "fileName": file_name,
            "fmt": doc.fmt,
            "ruby": doc.ruby,
            "total": len(doc.paragraphs),
            "done": 0,
            "state": "running",
        },
    )

    existing_paras = repo.list_paras(cid, mid)
    persisted_mem: dict[int, dict[str, Any]] = dict(existing_paras)

    def _should_stop() -> bool:
        cur = repo.get_job(job_id) or {}
        return cur.get("state") == "stopped"

    def _on_chunk(rows: list[tuple[int, dict[str, Any]]], done_now: int) -> None:
        repo.save_paras_batch(cid, mid, rows)
        for p_idx, p_row in rows:
            persisted_mem[p_idx] = p_row
        repo.save_job(job_id, {"doneParas": done_now, "totalParas": len(doc.paragraphs)})

    final_state = "done"
    done_count = len(existing_paras)
    output_storage_path: str | None = None
    try:
        for ev in stream_document_chunks(
            doc=doc,
            mode=mode,
            settings=settings,
            glossary=glossary,
            cache=cache,
            existing_paras=existing_paras,
            on_chunk_saved=_on_chunk,
            should_stop=_should_stop,
            style=style,
            api_key=api_key,
            usage_tracker=usage_adapter,
            llm_transport=llm_transport,
        ):
            if ev["type"] in ("done", "error"):
                final_state = str(ev.get("state") or ("done" if ev["type"] == "done" else "error"))
                done_count = int(ev.get("doneParas", done_count))

        if final_state == "done":
            target_lang = parse_mode_target(mode, settings.default_target)
            out_fmt = suffix.lstrip(".")
            if out_fmt in ("epub", "pdf", "htm", "xhtml"):
                out_fmt = "html"
            elif out_fmt == "ssa":
                out_fmt = "ass"
            rebuilt = rebuild_translated_document_from_paras(
                title=title_name,
                target_lang=target_lang,
                fmt=doc.fmt,
                stored_paras=list(persisted_mem.values()),
                glossary_entries=glossary.non_builtin_entries(),
                ruby=doc.ruby,
            )
            out_bytes, out_ctype, ext = export_translated_document(rebuilt, out_fmt)
            safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file_name).stem).strip("._")[:200] or "dokumen"
            output_storage_path = f"outputs/{uid}/{job_id}/{safe_stem}.{target_lang}.{ext}"
            repo.write_storage_blob(output_storage_path, out_bytes, out_ctype)
    except Exception as exc:
        _API_LOGGER.exception("Background document worker failed for %s: %s", job_id, type(exc).__name__)
        final_state = "partial" if done_count > 0 else "error"
        err_msg = "Terjadi kendala saat memproses atau mengekspor dokumen."
        repo.save_job(
            job_id,
            {
                "state": final_state,
                "doneParas": done_count,
                "totalParas": len(doc.paragraphs),
                "errorCode": "JOB_FAILED",
                "message": err_msg,
            },
        )
        repo.save_message(
            cid,
            mid,
            {
                "done": done_count,
                "state": final_state,
                "error": err_msg,
            },
        )
        return {"state": final_state, "doneParas": done_count, "outputPath": None, "message": err_msg}

    repo.save_job(
        job_id,
        {
            "state": final_state,
            "doneParas": done_count,
            "totalParas": len(doc.paragraphs),
            "storageOutputPath": output_storage_path,
        },
    )
    repo.save_message(
        cid,
        mid,
        {
            "done": done_count,
            "state": final_state,
            "storageOutputPath": output_storage_path,
        },
    )
    return {"state": final_state, "doneParas": done_count, "outputPath": output_storage_path}
