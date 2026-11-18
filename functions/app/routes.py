"""Flask HTTP routes (/v1/*) and Cloud Storage background document processor."""

from __future__ import annotations

import base64
import json
import secrets
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request, stream_with_context

from tranx_core import (
    JPTRANS_VERSION,
    SUPPORTED_MODES,
    SUPPORTED_UI_LANGS,
    DailyCapExceeded,
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
    export_translated_document,
    fetch_url_safely,
    inspect_zip_archive,
    lookup_new_names_for_text,
    parse_aozora,
    parse_mode_target,
    read_document,
    read_text,
    rebuild_translated_document_from_paras,
    stream_document_chunks,
    stream_fast_chat,
    supported_formats_metadata,
    transcribe_short_audio,
    translate_image_bytes,
    translate_web_page,
)

from .store import AuthError, Repository

MAX_STORAGE_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


class _RepoUsageAdapter:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def check_and_record(
        self, *, model: str, chars: int, calls: int, char_cap: int, call_cap: int
    ) -> None:
        self._repo.check_and_record_usage(
            model=model, chars=chars, calls=calls, char_cap=char_cap, call_cap=call_cap
        )


def _extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    query_token = request.args.get("token") or ""
    return query_token.strip()


def _ndjson_line(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


def create_flask_app(
    repo: Repository,
    *,
    manifest_hash: str = "verified",
    llm_transport: Any = None,
    vision_extractor_factory: Callable[[str], VisionExtractor] | None = None,
    speech_transcriber_factory: Callable[[str], SpeechTranscriber] | None = None,
    web_fetcher: Any = fetch_url_safely,
) -> Flask:
    app = Flask(__name__)
    shared_cache = LayeredTranslationCache(repo.cache_store)
    usage_adapter = _RepoUsageAdapter(repo)

    @app.before_request
    def _handle_options_preflight() -> tuple[str, int] | None:
        if request.method == "OPTIONS":
            return "", 204
        return None

    @app.after_request
    def _add_cors_and_security_headers(resp: Response) -> Response:
        origin = request.headers.get("Origin") or "*"
        resp.headers.setdefault("Access-Control-Allow-Origin", origin)
        resp.headers.setdefault(
            "Access-Control-Allow-Headers", "Authorization, Content-Type, X-Inbox-Token"
        )
        resp.headers.setdefault(
            "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
        )
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    @app.errorhandler(AuthError)
    def _handle_auth_error(err: AuthError) -> tuple[Response, int]:
        return jsonify({"error": {"code": err.code, "message": err.message}}), err.status

    @app.errorhandler(SSRFBlockedError)
    def _handle_ssrf_error(err: SSRFBlockedError) -> tuple[Response, int]:
        return jsonify({"error": {"code": "BLOCKED_URL", "message": str(err)}}), 403

    @app.errorhandler(WebGateBlockedError)
    def _handle_gate_error(err: WebGateBlockedError) -> tuple[Response, int]:
        return jsonify({"error": {"code": "SITE_GATE", "message": str(err)}}), 422

    @app.errorhandler(InputError)
    def _handle_input_error(err: InputError) -> tuple[Response, int]:
        return jsonify({"error": {"code": "INVALID_INPUT", "message": str(err)}}), 400

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
                    }
                }
            ),
            429,
        )

    @app.route("/v1/<path:_any>", methods=["OPTIONS"])
    def _options_preflight(_any: str) -> tuple[str, int]:
        return "", 204

    def _require_owner() -> dict[str, Any]:
        return repo.verify_owner_token(_extract_bearer_token())

    @app.get("/v1/healthz")
    def healthz() -> tuple[str, int]:
        return "", 204

    @app.get("/v1/meta")
    def get_meta() -> Response:
        _require_owner()
        settings = repo.get_settings()
        _, key_source = repo.get_api_key()
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
        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()
        cfg = chat_config(settings, "id")
        engines = build_engine_chain(
            cfg,
            settings,
            api_key=api_key,
            usage_tracker=usage_adapter,
            transport=llm_transport,
        )
        sample_sentences = ["おはようございます。", "千早は小さく笑った。", "次の駅で降ります。"]
        report: list[dict[str, Any]] = []
        status_map: dict[str, Any] = {}

        for eng, model_name in zip(engines, settings.llm_models):
            t0 = time.monotonic()
            try:
                out = eng.translate(sample_sentences, "ja", "id")
                ms = round((time.monotonic() - t0) * 1000)
                row = {"model": model_name, "ok": True, "ms": ms, "sample": " ".join(out)}
                status_map[model_name] = {"ok": True, "lastError": None, "ms": ms}
            except Exception as exc:
                ms = round((time.monotonic() - t0) * 1000)
                row = {"model": model_name, "ok": False, "ms": ms, "error": str(exc)}
                status_map[model_name] = {"ok": False, "lastError": str(exc), "ms": ms}
            report.append(row)

        repo.update_engine_status(status_map)
        return jsonify({"models": report})

    @app.post("/v1/chat")
    def post_chat() -> Response:
        _require_owner()
        body = request.get_json(silent=True) or {}
        cid = str(body.get("cid") or f"c_{secrets.token_hex(6)}").strip()
        user_mid = str(body.get("clientMsgId") or f"m_{secrets.token_hex(6)}_u").strip()
        asst_mid = f"{user_mid}_r"
        mode = str(body.get("mode") or "ja-id").strip()
        text = str(body.get("text") or "")
        requested_title_id = body.get("titleId")
        inbox_id = body.get("inboxId")

        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()
        first_line = (text.strip().splitlines() or ["Percakapan"])[0][:80]
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
            stream_with_context(_generate()),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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

        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()
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
        audio_bytes = uploaded.read()
        if len(audio_bytes) > 4 * 1024 * 1024:
            return jsonify({"error": {"code": "AUDIO_TOO_LARGE", "message": "Ukuran klip suara maksimal 4 MB."}}), 413

        mime = uploaded.mimetype or "audio/webm"
        lang = str(request.form.get("lang") or "ja-JP")
        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()
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
        cid = str(body.get("cid") or f"c_{secrets.token_hex(6)}").strip()
        mid = str(body.get("clientMsgId") or f"img_{secrets.token_hex(6)}").strip()
        mode = str(body.get("mode") or "ja-id").strip()
        title_id = body.get("titleId")
        file_name = str(body.get("fileName") or "gambar.png")

        storage_path = body.get("storagePath")
        image_b64 = body.get("imageB64")
        if storage_path:
            image_bytes = repo.read_storage_blob(str(storage_path))
        elif isinstance(image_b64, str) and image_b64.strip():
            raw_b64 = image_b64.split(",", 1)[-1]
            image_bytes = base64.b64decode(raw_b64)
        else:
            raise InputError("Sertakan storagePath atau imageB64 untuk menerjemahkan gambar.")

        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()
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
        _require_owner()
        body = request.get_json(silent=True) or {}
        cid = str(body.get("cid") or f"c_{secrets.token_hex(6)}").strip()
        mid = str(body.get("clientMsgId") or f"doc_{secrets.token_hex(6)}").strip()
        mode = str(body.get("mode") or "ja-id").strip()
        source = body.get("source") or {}
        title_id = body.get("titleId")

        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()

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

        def _save_para_cb(idx: int, para_payload: dict[str, Any]) -> None:
            repo.save_para(cid, mid, idx, para_payload)

        def _stream() -> Any:
            final_state = "done"
            done_paras = 0
            for ev in stream_document_chunks(
                doc=doc,
                mode=mode,
                settings=settings,
                glossary=glossary,
                cache=shared_cache,
                on_para_saved=_save_para_cb,
                style=style,
                api_key=api_key,
                usage_tracker=usage_adapter,
                llm_transport=llm_transport,
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
            stream_with_context(_stream()),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/translate:resume")
    def post_translate_resume() -> Response:
        _require_owner()
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
                suffix = Path(str(job.get("fileName") or "berkas.txt")).suffix or ".txt"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                    tf.write(blob_bytes)
                    tmp_path = Path(tf.name)
                try:
                    doc = read_document(tmp_path, title=str(job.get("fileName") or "Dokumen"))
                finally:
                    tmp_path.unlink(missing_ok=True)
            else:
                raise InputError("Sumber berkas untuk dilanjutkan sudah tidak tersedia.")
        else:
            if not raw_src:
                raise InputError("Teks sumber untuk dilanjutkan tidak tersedia.")
            doc = read_text(raw_src, "Lanjutan")

        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()
        tid, title_name, style = repo.ensure_title(tid or None, doc.title)
        glossary = FirestoreGlossary.load_from_backend(
            tid, repo.glossary_backend, fallback_title=title_name
        )

        def _save_para_cb(idx: int, para_payload: dict[str, Any]) -> None:
            repo.save_para(cid, mid, idx, para_payload)

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
                on_para_saved=_save_para_cb,
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
            stream_with_context(_stream()),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
        disp = "inline" if inline else f'attachment; filename="tranx-{mid}.{ext}"'
        return Response(
            out_bytes,
            mimetype=ctype.split(";", 1)[0],
            headers={"Content-Disposition": disp, "Content-Type": ctype},
        )

    @app.post("/v1/links:preview")
    def post_links_preview() -> Response:
        _require_owner()
        body = request.get_json(silent=True) or {}
        cid = str(body.get("cid") or f"c_{secrets.token_hex(6)}").strip()
        mid = str(body.get("clientMsgId") or f"lnk_{secrets.token_hex(6)}").strip()
        mode = str(body.get("mode") or "ja-id").strip()
        url = str(body.get("url") or "").strip()
        title_id = body.get("titleId")

        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()
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
            "lockedNames": web_res["lockedNames"],
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

    @app.get("/v1/web")
    def get_translated_web() -> Response:
        _require_owner()
        url = str(request.args.get("url") or "").strip()
        mode = str(request.args.get("mode") or "ja-id").strip()
        title_id = request.args.get("titleId")
        view = str(request.args.get("view") or "translated").strip().lower()

        settings = repo.get_settings()
        api_key, _ = repo.get_api_key()
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
        )
        return Response(
            web_res["html"],
            mimetype="text/html",
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Security-Policy": "sandbox allow-forms allow-same-origin; script-src 'none'; object-src 'none';",
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
    job = repo.get_job(job_id) or {}
    cid = str(job.get("cid") or f"c_{job_id}")
    mid = str(job.get("mid") or f"m_{job_id}")
    mode = str(job.get("mode") or "ja-id")
    title_id = job.get("titleId")

    raw_bytes = repo.read_storage_blob(object_name)
    if len(raw_bytes) > MAX_STORAGE_UPLOAD_BYTES:
        repo.save_job(job_id, {"state": "error", "errorCode": "FILE_TOO_LARGE"})
        return {"state": "error", "errorCode": "FILE_TOO_LARGE"}

    suffix = Path(file_name).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(raw_bytes)
        tmp_path = Path(tf.name)

    try:
        if suffix in (".epub", ".docx"):
            inspect_zip_archive(tmp_path)
        doc = read_document(tmp_path, title=Path(file_name).stem)
    except Exception as exc:
        repo.save_job(job_id, {"state": "error", "errorCode": "UNREADABLE_DOCUMENT", "message": str(exc)})
        repo.save_message(cid, mid, {"role": "assistant", "kind": "document", "jobId": job_id, "state": "error", "error": str(exc)})
        return {"state": "error", "message": str(exc)}
    finally:
        tmp_path.unlink(missing_ok=True)

    settings = repo.get_settings()
    api_key, _ = repo.get_api_key()
    tid, title_name, style = repo.ensure_title(title_id, Path(file_name).stem, kind="dokumen")
    glossary = FirestoreGlossary.load_from_backend(
        tid, repo.glossary_backend, fallback_title=title_name
    )
    cache = LayeredTranslationCache(repo.cache_store)
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

    def _should_stop() -> bool:
        cur = repo.get_job(job_id) or {}
        return cur.get("state") == "stopped"

    def _on_para(idx: int, payload: dict[str, Any]) -> None:
        repo.save_para(cid, mid, idx, payload)
        repo.save_job(job_id, {"doneParas": idx + 1, "totalParas": len(doc.paragraphs)})

    final_state = "done"
    done_count = len(existing_paras)
    for ev in stream_document_chunks(
        doc=doc,
        mode=mode,
        settings=settings,
        glossary=glossary,
        cache=cache,
        existing_paras=existing_paras,
        on_para_saved=_on_para,
        should_stop=_should_stop,
        style=style,
        api_key=api_key,
        usage_tracker=usage_adapter,
        llm_transport=llm_transport,
    ):
        if ev["type"] in ("done", "error"):
            final_state = str(ev.get("state") or ("done" if ev["type"] == "done" else "error"))
            done_count = int(ev.get("doneParas", done_count))

    output_storage_path = None
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
            stored_paras=list(repo.list_paras(cid, mid).values()),
            glossary_entries=glossary.non_builtin_entries(),
            ruby=doc.ruby,
        )
        out_bytes, out_ctype, ext = export_translated_document(rebuilt, out_fmt)
        stem = Path(file_name).stem
        output_storage_path = f"outputs/{uid}/{job_id}/{stem}.{target_lang}.{ext}"
        repo.write_storage_blob(output_storage_path, out_bytes, out_ctype)

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
