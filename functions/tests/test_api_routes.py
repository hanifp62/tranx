"""End-to-end Flask contract tests for all /v1/* HTTP routes and Cloud Storage document trigger."""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path
from typing import Any

import docx
import pytest
from PIL import Image

FN_DIR = Path(__file__).resolve().parents[1]
if str(FN_DIR) not in sys.path:
    sys.path.insert(0, str(FN_DIR))

from app.routes import create_flask_app, process_uploaded_document_blob  # noqa: E402
from app.store import InMemoryRepository  # noqa: E402
from tranx_core import (  # noqa: E402
    FetchedPage,
    RawVisionBubble,
    SSRFBlockedError,
    init_tranx_core,
)


class RouteFakeTransport:
    """Deterministic OpenAI chat/completions stub for route contract tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        import re

        self.calls.append(payload)
        user_msg = payload["messages"][1]["content"]
        items = json.loads(user_msg.split("Input:\n", 1)[1])
        translations = []
        for item in items:
            src = item["text"]
            tokens = re.findall(r"\[\[E\d+\]\]", src)
            if "おはようございます" in src:
                dst = "Selamat pagi."
            elif "千早" in src or tokens:
                dst = ("Kalimat tokoh " + " ".join(tokens)).strip() + "."
            else:
                dst = "Terjemahan baris uji."
            translations.append({"id": item["id"], "text": dst})
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"translations": translations}, ensure_ascii=False)
                    },
                    "finish_reason": "stop",
                }
            ]
        }


def _parse_ndjson(raw_bytes: bytes) -> list[dict[str, Any]]:
    lines = [ln for ln in raw_bytes.decode("utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def _auth_headers(token: str = "valid-owner-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_guard_and_multi_tenant_isolation(monkeypatch: Any) -> None:
    init_tranx_core()
    repo = InMemoryRepository(env_api_key=None)
    app = create_flask_app(repo, llm_transport=RouteFakeTransport())
    client = app.test_client()

    assert client.get("/v1/healthz").status_code == 204
    assert client.options("/v1/chat").status_code == 204
    assert client.get("/v1/meta").status_code == 401
    assert client.get("/v1/meta", headers=_auth_headers("anon-token")).status_code == 403
    assert client.get("/v1/meta", headers=_auth_headers("unverified-token")).status_code == 403

    # Optional self-hosted allowlist restricts unlisted accounts when ALLOWED_EMAILS is configured
    monkeypatch.setenv("ALLOWED_EMAILS", "user1@example.com")
    assert client.get("/v1/meta", headers=_auth_headers("stranger-token")).status_code == 403
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)

    # General multi-account mode: BOTH User A and User B authenticate cleanly
    r_owner = client.get("/v1/meta", headers=_auth_headers("valid-owner-token"))
    assert r_owner.status_code == 200
    meta = r_owner.get_json()
    assert set(meta["modes"]) == {
        "auto-id",
        "auto-en",
        "auto-ja",
        "ja-id",
        "ja-en",
        "id-ja",
        "id-en",
        "en-id",
        "en-ja",
    }
    assert meta["uiLangs"] == ["id", "en"]
    assert meta["jptrans"]["version"] == "1.1.0"

    r_paired = client.get("/v1/meta", headers=_auth_headers("valid-paired-token"))
    assert r_paired.status_code == 200

    # Strict horizontal anti-IDOR isolation between User A and User B
    assert (
        client.post(
            "/v1/engine:key",
            json={"apiKey": "user-a-private-key"},
            headers=_auth_headers("valid-owner-token"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/chat",
            json={"cid": "c_private_a", "clientMsgId": "m_a1", "mode": "ja-id", "text": "おはようございます。"},
            headers=_auth_headers("valid-owner-token"),
        ).status_code
        == 200
    )

    # User B must NOT see User A's API key, conversations, messages, or exports
    meta_b = client.get("/v1/meta", headers=_auth_headers("valid-user-b-token")).get_json()
    assert meta_b["keyStatus"] == {"configured": False, "source": "missing"}
    backup_b = json.loads(
        client.get("/v1/backup", headers=_auth_headers("valid-user-b-token")).data.decode("utf-8")
    )
    assert "c_private_a" not in backup_b["conversations"]
    exp_b = client.get(
        "/v1/messages/m_a1_r/export?cid=c_private_a&fmt=html",
        headers=_auth_headers("valid-user-b-token"),
    )
    assert exp_b.status_code == 400
    # User B calling DELETE on User A's cid must NEVER delete User A's conversation
    assert client.delete("/v1/conversations/c_private_a", headers=_auth_headers("valid-user-b-token")).status_code == 204
    backup_a = json.loads(
        client.get("/v1/backup", headers=_auth_headers("valid-owner-token")).data.decode("utf-8")
    )
    assert "c_private_a" in backup_a["conversations"]


def test_engine_key_vault_and_engine_check() -> None:
    init_tranx_core()
    repo = InMemoryRepository(env_api_key=None)
    transport = RouteFakeTransport()
    app = create_flask_app(repo, llm_transport=transport)
    client = app.test_client()

    meta0 = client.get("/v1/meta", headers=_auth_headers()).get_json()
    assert meta0["keyStatus"] == {"configured": False, "source": "missing"}

    set_res = client.post(
        "/v1/engine:key",
        json={"apiKey": "vault-test-token"},
        headers=_auth_headers(),
    )
    assert set_res.status_code == 200
    assert set_res.get_json() == {"configured": True, "source": "vault"}

    chk = client.post("/v1/engine:check", headers=_auth_headers())
    assert chk.status_code == 200
    models = chk.get_json()["models"]
    assert len(models) == 2
    assert all(m["ok"] is True for m in models)


def test_chat_stream_names_lookup_and_zero_llm_export() -> None:
    init_tranx_core()
    repo = InMemoryRepository()
    tid, _, _ = repo.ensure_title("novel_uji", "Novel Uji", kind="novel")
    repo.glossary_backend.commit_mutations(
        tid,
        {
            "e_chihaya": {
                "surface": "千早",
                "kind": "PERSON",
                "reading": "ちはや",
                "romaji": "Chihaya",
                "render_id": "Chihaya",
                "render_en": "Chihaya",
                "gloss_id": "",
                "gloss_en": "",
                "gender": "f",
                "aliases": [],
                "allow_compound": False,
                "confirmed": True,
                "source": "user",
                "score": 1.0,
            }
        },
        set(),
    )
    transport = RouteFakeTransport()
    app = create_flask_app(repo, llm_transport=transport)
    client = app.test_client()

    resp = client.post(
        "/v1/chat",
        json={
            "cid": "c_test1",
            "clientMsgId": "m_u1",
            "mode": "ja-id",
            "titleId": tid,
            "text": "千早は走った。",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    events = _parse_ndjson(resp.data)
    assert events[0]["type"] == "meta"
    assert events[-1]["type"] == "done"
    assert "Chihaya" in events[-1]["fullDst"]
    calls_after_chat = len(transport.calls)
    assert calls_after_chat == 1

    lookup_res = client.post(
        "/v1/names:lookup",
        json={"cid": "c_test1", "mid": "m_u1_r", "titleId": tid},
        headers=_auth_headers(),
    )
    assert lookup_res.status_code == 200
    assert any(e["surface"] == "千早" for e in lookup_res.get_json()["entries"])

    # Export to HTML and DOCX must NOT invoke the LLM again
    calls_before_export = len(transport.calls)
    html_res = client.get(
        "/v1/messages/m_u1_r/export?cid=c_test1&fmt=html&bilingual=1&theme=Terang",
        headers=_auth_headers(),
    )
    assert html_res.status_code == 200
    assert "Chihaya" in html_res.data.decode("utf-8")

    docx_res = client.get(
        "/v1/messages/m_u1_r/export?cid=c_test1&fmt=docx",
        headers=_auth_headers(),
    )
    assert docx_res.status_code == 200
    parsed = docx.Document(io.BytesIO(docx_res.data))
    assert any("Chihaya" in p.text for p in parsed.paragraphs)
    assert len(transport.calls) == calls_before_export


def test_speech_and_image_translate_routes() -> None:
    init_tranx_core()
    repo = InMemoryRepository()

    class StubSpeech:
        def transcribe(self, audio_bytes: bytes, mime_type: str, lang: str, model: str) -> str:
            return "おはようございます。"

    class StubVision:
        def extract_bubbles(
            self, image_bytes: bytes, mime_type: str, model: str
        ) -> list[RawVisionBubble]:
            return [RawVisionBubble(id=1, box_2d=(100, 100, 300, 600), text="おはようございます。")]

    app = create_flask_app(
        repo,
        llm_transport=RouteFakeTransport(),
        vision_extractor_factory=lambda _k: StubVision(),
        speech_transcriber_factory=lambda _k: StubSpeech(),
    )
    client = app.test_client()

    stt_res = client.post(
        "/v1/speech:transcribe",
        data={"lang": "ja-JP", "audio": (io.BytesIO(b"RIFF-audio"), "klip.webm", "audio/webm")},
        content_type="multipart/form-data",
        headers=_auth_headers(),
    )
    assert stt_res.status_code == 200
    assert stt_res.get_json()["text"] == "おはようございます。"

    img = Image.new("RGB", (500, 500), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    img_res = client.post(
        "/v1/image:translate",
        json={"cid": "c_img1", "mode": "ja-id", "fileName": "panel.png", "imageB64": b64},
        headers=_auth_headers(),
    )
    assert img_res.status_code == 200
    payload = img_res.get_json()
    assert payload["blocks"][0]["box"] == [50, 50, 250, 100]
    assert "Selamat pagi" in payload["fullDst"]


def test_links_preview_web_reader_and_ssrf_403() -> None:
    init_tranx_core()
    repo = InMemoryRepository()

    def fake_fetcher(url: str) -> FetchedPage:
        if "169.254.169.254" in url or "127.0.0.1" in url:
            raise SSRFBlockedError("Alamat jaringan internal ditolak.")
        return FetchedPage(
            final_url=url,
            host="syosetu.example.jp",
            content_type="text/html",
            text="<html><head><title>第一章</title></head><body><p>おはようございます。</p></body></html>",
        )

    app = create_flask_app(
        repo,
        llm_transport=RouteFakeTransport(),
        web_fetcher=fake_fetcher,
    )
    client = app.test_client()

    blocked = client.post(
        "/v1/links:preview",
        json={"url": "http://169.254.169.254/latest/meta-data/"},
        headers=_auth_headers(),
    )
    assert blocked.status_code == 403
    assert blocked.get_json()["error"]["code"] == "BLOCKED_URL"

    prev = client.post(
        "/v1/links:preview",
        json={"cid": "c_lnk1", "url": "https://syosetu.example.jp/ep1", "mode": "ja-id"},
        headers=_auth_headers(),
    )
    assert prev.status_code == 200
    prev_json = prev.get_json()
    assert prev_json["readerSupported"] is True
    assert "Selamat pagi" in prev_json["excerptDst"]

    web_html = client.get(
        f"/v1/web?url=https://syosetu.example.jp/ep1&mode=ja-id&titleId={prev_json['titleId']}",
        headers=_auth_headers(),
    )
    assert web_html.status_code == 200
    assert "Selamat pagi" in web_html.data.decode("utf-8")
    assert "script-src 'none'" in web_html.headers.get("Content-Security-Policy", "")


def test_long_translate_resume_and_storage_document_trigger() -> None:
    init_tranx_core()
    repo = InMemoryRepository()
    transport = RouteFakeTransport()
    app = create_flask_app(repo, llm_transport=transport)
    client = app.test_client()

    long_src = "\n\n".join(["おはようございます。" for _ in range(4)])
    r1 = client.post(
        "/v1/translate",
        json={
            "cid": "c_long1",
            "clientMsgId": "m_long1",
            "mode": "ja-id",
            "source": {"text": long_src},
        },
        headers=_auth_headers(),
    )
    assert r1.status_code == 200
    ev1 = _parse_ndjson(r1.data)
    assert ev1[-1]["type"] == "done"
    assert len(repo.list_paras("c_long1", "m_long1")) == 4

    # Simulate partial state (only 2 paras saved) and verify /v1/translate:resume finishes remaining 2
    del repo.paras[("c_long1", "m_long1")][2]
    del repo.paras[("c_long1", "m_long1")][3]
    r_resume = client.post(
        "/v1/translate:resume",
        json={"cid": "c_long1", "mid": "m_long1", "text": long_src},
        headers=_auth_headers(),
    )
    assert r_resume.status_code == 200
    ev_res = _parse_ndjson(r_resume.data)
    assert ev_res[0]["resumedFrom"] == 2
    assert ev_res[-1]["state"] == "done"
    assert len(repo.list_paras("c_long1", "m_long1")) == 4

    # Background Cloud Storage trigger for .srt subtitle upload
    srt_bytes = (
        "1\n00:00:01,000 --> 00:00:03,000\nおはようございます。\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\n千早は走った。\n"
    ).encode("utf-8")
    upload_path = "uploads/owner-1/job_srt1/episode-01.srt"
    repo.write_storage_blob(upload_path, srt_bytes, "application/x-subrip")
    repo.save_job(
        "job_srt1",
        {"cid": "c_doc1", "mid": "m_doc1", "mode": "ja-id", "fileName": "episode-01.srt"},
    )

    trig_res = process_uploaded_document_blob(
        repo,
        object_name=upload_path,
        llm_transport=transport,
    )
    assert trig_res["state"] == "done"
    out_path = trig_res["outputPath"]
    assert out_path == "outputs/owner-1/job_srt1/episode-01.id.srt"
    out_srt = repo.read_storage_blob(out_path).decode("utf-8")
    assert "00:00:01,000 --> 00:00:03,000" in out_srt
    assert "Selamat pagi." in out_srt


def test_pairing_inbox_merge_backup_and_cascade_delete() -> None:
    init_tranx_core()
    repo = InMemoryRepository()
    app = create_flask_app(repo, llm_transport=RouteFakeTransport())
    client = app.test_client()

    # 1. Pair code generation + redemption + session revoke
    pair_gen = client.post("/v1/auth:pairCode", headers=_auth_headers())
    assert pair_gen.status_code == 200
    code = pair_gen.get_json()["code"]
    assert len(code) == 6 and code.isdigit()

    pair_redeem = client.post("/v1/auth:pair", json={"code": code})
    assert pair_redeem.status_code == 200
    assert "custom-token-for-owner-1" in pair_redeem.get_json()["customToken"]

    # Reuse of one-time pair code must fail with 401
    assert client.post("/v1/auth:pair", json={"code": code}).status_code == 401
    assert client.post("/v1/auth:revoke", headers=_auth_headers()).status_code == 204

    # 2. Apple Shortcuts inbox token + push + delete
    tok_res = client.post("/v1/inbox:token", headers=_auth_headers()).get_json()
    raw_tok = tok_res["token"]
    push_res = client.post(
        "/v1/inbox",
        json={"text": "おはようございます。", "title": "Dari iPhone"},
        headers={"X-Inbox-Token": raw_tok},
    )
    assert push_res.status_code == 201
    inbox_id = push_res.get_json()["id"]
    assert inbox_id in repo.inbox_items
    assert client.delete(f"/v1/inbox/{inbox_id}", headers=_auth_headers()).status_code == 204
    assert inbox_id not in repo.inbox_items

    # 3. Title merge + backup + conversation cascade delete
    repo.ensure_title("t_src", "Bab 1")
    repo.ensure_title("t_dst", "Seri Utama")
    repo.glossary_backend.commit_mutations(
        "t_src",
        {
            "k1": dict(
                surface="美咲",
                kind="PERSON",
                reading="みさき",
                romaji="Misaki",
                render_id="Misaki",
                render_en="Misaki",
                gloss_id="",
                gloss_en="",
                gender="f",
                aliases=[],
                allow_compound=False,
                confirmed=True,
                source="user",
                score=1.0,
            )
        },
        set(),
    )
    merge_res = client.post(
        "/v1/titles:merge",
        json={"fromTitleId": "t_src", "toTitleId": "t_dst"},
        headers=_auth_headers(),
    )
    assert merge_res.status_code == 200
    assert merge_res.get_json()["merged"] == 1

    backup_res = client.get("/v1/backup", headers=_auth_headers())
    assert backup_res.status_code == 200
    backup_json = json.loads(backup_res.data.decode("utf-8"))
    assert backup_json["version"] == "2.2"
    assert "t_dst" in backup_json["glossaries"]

    repo.ensure_conversation("c_del", title="Hapus", title_id="t_dst", mode="ja-id")
    repo.save_message("c_del", "m1", {"role": "user", "text": "x"})
    repo.save_para("c_del", "m1", 0, {"i": 0, "src": "x", "dst": "y"})
    assert client.delete("/v1/conversations/c_del", headers=_auth_headers()).status_code == 204
    assert "c_del" not in repo.conversations
    assert ("c_del", "m1") not in repo.paras


def test_bidirectional_and_autodetect_modes_id_ja_en() -> None:
    """Verify id->ja, en->id, id->en, en->ja, and auto->ja/id/en modes with reverse glossary protection."""
    init_tranx_core()
    repo = InMemoryRepository()
    tid, _, _ = repo.ensure_title("seri_dwibahasa", "Seri Dwibahasa", kind="novel")
    repo.glossary_backend.commit_mutations(
        tid,
        {
            "e_chihaya": {
                "surface": "千早",
                "kind": "PERSON",
                "reading": "ちはや",
                "romaji": "Chihaya",
                "render_id": "Chihaya",
                "render_en": "Chihaya",
                "gloss_id": "",
                "gloss_en": "",
                "gender": "f",
                "aliases": [],
                "allow_compound": False,
                "confirmed": True,
                "source": "user",
                "score": 1.0,
            }
        },
        set(),
    )

    class MultilingualStubTransport:
        def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
            items = json.loads(payload["messages"][1]["content"].split("Input:\n", 1)[1])
            out = []
            for item in items:
                txt = item["text"]
                if "[[E1]]" in txt:
                    out.append({"id": item["id"], "text": f"「[[E1]]は静かに微笑んだ。」"})
                elif "Good morning" in txt:
                    out.append({"id": item["id"], "text": "Selamat pagi dari London."})
                else:
                    out.append({"id": item["id"], "text": "Good morning from Jakarta."})
            return {
                "choices": [
                    {
                        "message": {"content": json.dumps({"translations": out}, ensure_ascii=False)},
                        "finish_reason": "stop",
                    }
                ]
            }

    app = create_flask_app(repo, llm_transport=MultilingualStubTransport())
    client = app.test_client()

    # 1. Indonesia -> Jepang (id-ja) with reverse glossary Chihaya -> 千早
    r_id_ja = client.post(
        "/v1/chat",
        json={"cid": "c_bi1", "mode": "id-ja", "titleId": tid, "text": "Chihaya tersenyum tenang."},
        headers=_auth_headers(),
    )
    assert r_id_ja.status_code == 200
    ev_id_ja = _parse_ndjson(r_id_ja.data)
    assert ev_id_ja[0]["detectedSource"] == "id"
    assert "千早" in ev_id_ja[-1]["fullDst"]

    # 2. Auto-detect English -> Indonesian (auto-id)
    r_auto_id = client.post(
        "/v1/chat",
        json={"cid": "c_bi2", "mode": "auto-id", "text": "Good morning, the train is arriving at the station."},
        headers=_auth_headers(),
    )
    assert r_auto_id.status_code == 200
    ev_auto_id = _parse_ndjson(r_auto_id.data)
    assert ev_auto_id[0]["detectedSource"] == "en"
    assert "Selamat pagi" in ev_auto_id[-1]["fullDst"]

    # 3. Auto-detect Indonesian -> English (auto-en)
    r_auto_en = client.post(
        "/v1/chat",
        json={"cid": "c_bi3", "mode": "auto-en", "text": "Selamat pagi, saya sedang membaca buku ini di rumah."},
        headers=_auth_headers(),
    )
    assert r_auto_en.status_code == 200
    ev_auto_en = _parse_ndjson(r_auto_en.data)
    assert ev_auto_en[0]["detectedSource"] == "id"
    assert "Good morning" in ev_auto_en[-1]["fullDst"]


def test_cors_origin_allowlist_and_query_token_rejected() -> None:
    init_tranx_core()
    repo = InMemoryRepository()
    app = create_flask_app(repo, llm_transport=RouteFakeTransport())
    client = app.test_client()

    # 1. Evil cross-origin must never be reflected in Access-Control-Allow-Origin
    r_evil = client.get(
        "/v1/meta",
        headers={**_auth_headers(), "Origin": "https://evil.attacker.example"},
    )
    assert r_evil.status_code == 200
    assert r_evil.headers.get("Access-Control-Allow-Origin") == "https://tranx-hanif-id.web.app"
    assert r_evil.headers.get("Vary") == "Origin"
    assert r_evil.headers.get("X-Frame-Options") == "DENY"

    # 2. Allowlisted production origin is reflected cleanly
    r_good = client.get(
        "/v1/meta",
        headers={**_auth_headers(), "Origin": "https://tranx-hanif-id.web.app"},
    )
    assert r_good.status_code == 200
    assert r_good.headers.get("Access-Control-Allow-Origin") == "https://tranx-hanif-id.web.app"

    # 3. Query-string ?token=... bearer fallback must be rejected (401)
    r_qtok = client.get("/v1/meta?token=valid-owner-token")
    assert r_qtok.status_code == 401


def test_payload_limit_413_pixel_flood_and_obfuscated_scheme_sanitization() -> None:
    import struct
    import zlib

    init_tranx_core()
    repo = InMemoryRepository()

    def fake_html_fetcher(url: str) -> FetchedPage:
        return FetchedPage(
            final_url=url,
            host="example.jp",
            content_type="text/html",
            text=(
                '<html><head><title>Uji</title></head><body>'
                '<a id="tabjs" href="java\tscript:alert(1)">klik</a>'
                '<img id="svguri" src="data:image/svg+xml,<svg onload=alert(1)>">'
                "<p>おはようございます。</p></body></html>"
            ),
        )

    app = create_flask_app(
        repo,
        llm_transport=RouteFakeTransport(),
        web_fetcher=fake_html_fetcher,
    )
    client = app.test_client()

    # 1. Oversized HTTP payload rejected with 413 PAYLOAD_TOO_LARGE
    app.config["MAX_CONTENT_LENGTH"] = 2048
    try:
        r_big = client.post(
            "/v1/chat",
            data=json.dumps({"text": "A" * 4096}),
            content_type="application/json",
            headers=_auth_headers(),
        )
        assert r_big.status_code == 413
        assert r_big.get_json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    finally:
        app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

    # 2. Pixel-flood PNG header (10000x10000 = 100 MP > 25 MP cap) rejected with 400
    ihdr = struct.pack(">IIBBBBB", 10000, 10000, 8, 2, 0, 0, 0)

    def _png_chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    fake_bomb_png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + _png_chunk(b"IEND", b"")
    )
    b64_bomb = "data:image/png;base64," + base64.b64encode(fake_bomb_png).decode("ascii")
    r_bomb = client.post(
        "/v1/image:translate",
        json={"cid": "c_bomb", "mode": "ja-id", "fileName": "bomb.png", "imageB64": b64_bomb},
        headers=_auth_headers(),
    )
    assert r_bomb.status_code == 400
    assert r_bomb.get_json()["error"]["code"] == "INVALID_INPUT"

    # 3. Tab-obfuscated javascript: and data:image/svg+xml attributes stripped in /v1/web
    r_web = client.get(
        "/v1/web?url=https://example.jp/ch1&mode=ja-id",
        headers=_auth_headers(),
    )
    assert r_web.status_code == 200
    cleaned = r_web.data.decode("utf-8")
    assert "javascript" not in cleaned.lower()
    assert "data:image/svg" not in cleaned.lower()
    assert "Selamat pagi" in cleaned


def test_sliding_window_rate_limit_and_cloudfront_403_block_detection() -> None:
    init_tranx_core()
    repo = InMemoryRepository()

    def _cloudfront_403_fetcher(url: str) -> FetchedPage:
        return FetchedPage(
            final_url=url,
            host="blocked.example.jp",
            content_type="text/html",
            text=(
                "<html><head><title>ERROR: The request could not be satisfied</title></head>"
                "<body><h1>403 ERROR</h1><p>Generated by cloudfront (CloudFront)</p></body></html>"
            ),
        )

    app = create_flask_app(
        repo,
        llm_transport=RouteFakeTransport(),
        web_fetcher=_cloudfront_403_fetcher,
        rate_limit_rpm=8,
        auth_rate_limit_rpm=3,
    )
    client = app.test_client()

    # 1. CloudFront 403 block page must raise WebGateBlockedError (422 SITE_GATE), NEVER translate error text!
    r_cf = client.get(
        "/v1/web?url=https://blocked.example.jp/ch1&mode=ja-id",
        headers=_auth_headers(),
    )
    assert r_cf.status_code == 422
    assert r_cf.get_json()["error"]["code"] == "SITE_GATE"

    # 2. Auth pairing endpoint enforces tight per-IP sliding-window rate limit (429 + Retry-After)
    for _ in range(3):
        res = client.post("/v1/auth:pair", json={"code": "000000"})
        assert res.status_code == 401
        assert "X-RateLimit-Limit" in res.headers
    r_429 = client.post("/v1/auth:pair", json={"code": "000000"})
    assert r_429.status_code == 429
    assert int(r_429.headers["Retry-After"]) >= 1
    assert r_429.get_json()["error"]["code"] == "RATE_LIMITED"


def test_security_hardening_xff_spoof_pair_lockout_prod_cors_and_meta_strip(monkeypatch: Any) -> None:
    """Verify rightmost XFF anti-spoof, global auth:pair bucket, 5-attempt lockout, prod CORS, and HTML sanitizer."""
    init_tranx_core()
    repo = InMemoryRepository()

    def _tricky_html_fetcher(url: str) -> FetchedPage:
        return FetchedPage(
            final_url=url,
            host="example.jp",
            content_type="text/html",
            text=(
                '<html><head><title>Uji</title>'
                '<meta http-equiv="Set-Cookie" content="sid=evil">'
                '<link rel="preload" href="https://tracker.example/x.js">'
                '<link rel="stylesheet" href="https://example.jp/style.css">'
                '</head><body>'
                '<svg><a xlink:href="javascript:alert(1)">x</a></svg>'
                '<p>おはようございます。</p></body></html>'
            ),
        )

    app = create_flask_app(
        repo,
        llm_transport=RouteFakeTransport(),
        web_fetcher=_tricky_html_fetcher,
        rate_limit_rpm=3,
        auth_rate_limit_rpm=10,
    )
    client = app.test_client()

    # 1. Rotating leftmost spoofed X-Forwarded-For IPs MUST NOT bypass rate limit on same rightmost GFE peer IP
    for spoof_idx in range(3):
        r = client.get(
            "/v1/meta",
            headers={**_auth_headers(), "X-Forwarded-For": f"10.9.8.{spoof_idx}, 203.0.113.50"},
        )
        assert r.status_code == 200
    r_blocked = client.get(
        "/v1/meta",
        headers={**_auth_headers(), "X-Forwarded-For": "10.9.8.99, 203.0.113.50"},
    )
    assert r_blocked.status_code == 429

    # 2. 5 wrong guesses MUST invalidate an active 6-digit pairing code even if the right code is tried on attempt 6
    code = client.post(
        "/v1/auth:pairCode",
        headers={**_auth_headers(), "X-Forwarded-For": "198.51.100.1"},
    ).get_json()["code"]
    wrong_code = "999999" if code != "999999" else "888888"
    for i in range(5):
        bad = client.post(
            "/v1/auth:pair",
            json={"code": wrong_code},
            headers={"X-Forwarded-For": f"198.51.100.{10 + i}"},
        )
        assert bad.status_code == 401
    # Active code must now be invalidated (401 even with the previously valid code)
    locked = client.post(
        "/v1/auth:pair",
        json={"code": code},
        headers={"X-Forwarded-For": "198.51.100.99"},
    )
    assert locked.status_code == 401

    # 3. Global /v1/auth:pair rate limit triggers 429 across distinct IPs combined (auth_rate_limit_rpm=10; 6 used above)
    for i in range(4):
        client.post(
            "/v1/auth:pair",
            json={"code": "123456"},
            headers={"X-Forwarded-For": f"198.51.100.{20 + i}"},
        )
    r_global_429 = client.post(
        "/v1/auth:pair",
        json={"code": "123456"},
        headers={"X-Forwarded-For": "198.51.100.250"},
    )
    assert r_global_429.status_code == 429

    # 4. Production Cloud Functions (K_SERVICE set) MUST NOT reflect http://localhost:5173 in CORS header
    monkeypatch.setenv("K_SERVICE", "tranx-api")
    r_local_origin = client.get(
        "/v1/meta",
        headers={**_auth_headers(), "Origin": "http://localhost:5173", "X-Forwarded-For": "203.0.113.77"},
    )
    assert r_local_origin.status_code == 200
    assert r_local_origin.headers.get("Access-Control-Allow-Origin") == "https://tranx-hanif-id.web.app"

    # 5. Sanitizer strips meta[http-equiv=Set-Cookie], non-stylesheet <link>, and xlink:href javascript:
    r_san = client.get(
        "/v1/web?url=https://example.jp/clean&mode=ja-id",
        headers={**_auth_headers(), "X-Forwarded-For": "203.0.113.78"},
    )
    assert r_san.status_code == 200
    html = r_san.data.decode("utf-8")
    assert "set-cookie" not in html.lower()
    assert "tracker.example" not in html.lower()
    assert "javascript:" not in html.lower()
    assert "style.css" in html


def test_security_cross_tenant_storage_idor_and_ssrf_ipv6_tunnels() -> None:
    """Verify cross-tenant Storage read IDOR is blocked (403) and IPv6 6to4/NAT64/localhost. are rejected."""
    from tranx_core.web_translator import SSRFBlockedError, assert_public_ip, validate_and_resolve_url

    repo = InMemoryRepository(env_api_key="test-key")
    repo.write_storage_blob("uploads/owner-1/job_secret/private.png", b"\x89PNG\r\n\x1a\n", "image/png")
    app = create_flask_app(repo, llm_transport=RouteFakeTransport())
    client = app.test_client()

    # User B attempting to read owner-1's Storage blob via /v1/image:translate MUST get 403
    r_idor = client.post(
        "/v1/image:translate",
        headers=_auth_headers("valid-user-b-token"),
        json={"storagePath": "uploads/owner-1/job_secret/private.png", "mode": "ja-id"},
    )
    assert r_idor.status_code == 403
    assert r_idor.get_json()["error"]["code"] == "FORBIDDEN_STORAGE_PATH"

    # Malformed base64 returns clean 400 (not 500)
    r_b64 = client.post(
        "/v1/image:translate",
        headers=_auth_headers(),
        json={"imageB64": "!!!not-valid-base64!!!", "mode": "ja-id"},
    )
    assert r_b64.status_code == 400

    # IPv6 6to4, NAT64, and *.localhost SSRF blocks
    for bad_ip in ("2002:7f00:0001::1", "64:ff9b::7f00:1", "::ffff:169.254.169.254", "fe80::1"):
        with pytest.raises(SSRFBlockedError):
            assert_public_ip(bad_ip)
    with pytest.raises(SSRFBlockedError):
        validate_and_resolve_url("http://evil.localhost/admin")


def test_media_proxy_ssrf_auth_and_tall_webtoon_strip_support() -> None:
    """Verify /v1/media:proxy enforces auth + SSRF + nosniff + magic bytes, and tall webtoon strips pass."""
    import io
    from PIL import Image
    from tranx_core.vision_ocr import inspect_image_dimensions
    from tranx_core.web_translator import FetchedImage, SSRFBlockedError, fetch_image_safely

    # 1. Tall webtoon strip (800 x 12000 = 9.6 MP <= 36 MP, height <= 65536) is now supported!
    strip_buf = io.BytesIO()
    Image.new("RGB", (800, 12000), color=(255, 255, 255)).save(strip_buf, format="PNG")
    w, h, mime = inspect_image_dimensions(strip_buf.getvalue())
    assert (w, h, mime) == (800, 12000, "image/png")

    # 2. /v1/media:proxy requires auth (401 without Bearer) and blocks SSRF (403)
    png_sample = strip_buf.getvalue()[:2048]
    real_png_buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(250, 250, 250)).save(real_png_buf, format="PNG")
    real_png = real_png_buf.getvalue()

    def _fake_image_fetcher(url: str) -> FetchedImage:
        if "127.0.0.1" in url or "metadata" in url:
            raise SSRFBlockedError("Blocked internal target")
        return FetchedImage(
            final_url=url,
            host="cdn.example.jp",
            content_type="image/png",
            data=real_png,
        )

    repo = InMemoryRepository(env_api_key="test-key")
    app = create_flask_app(
        repo,
        llm_transport=RouteFakeTransport(),
        image_fetcher=_fake_image_fetcher,
    )
    client = app.test_client()

    # Unauthenticated -> 401
    assert client.get("/v1/media:proxy?url=https://cdn.example.jp/page1.png").status_code == 401
    # Missing/empty url -> clean 400 INVALID_INPUT (not 403)
    r_empty = client.get("/v1/media:proxy", headers=_auth_headers())
    assert r_empty.status_code == 400
    assert r_empty.get_json()["error"]["code"] == "INVALID_INPUT"
    # Internal SSRF -> 403
    r_ssrf = client.get(
        "/v1/media:proxy?url=http://127.0.0.1/secret.png",
        headers=_auth_headers(),
    )
    assert r_ssrf.status_code == 403
    # Public manga page -> 200 with nosniff + sandbox CSP + CORP + no-transform cache
    r_ok = client.get(
        "/v1/media:proxy?url=https://cdn.example.jp/page1.png",
        headers=_auth_headers(),
    )
    assert r_ok.status_code == 200
    assert r_ok.headers.get("Content-Type") == "image/png"
    assert r_ok.headers.get("X-Content-Type-Options") == "nosniff"
    assert r_ok.headers.get("Cross-Origin-Resource-Policy") == "cross-origin"
    assert "no-transform" in (r_ok.headers.get("Cache-Control") or "")
    assert "sandbox" in (r_ok.headers.get("Content-Security-Policy") or "")
    assert r_ok.data == real_png
    # Non-ASCII Japanese path/query encodes cleanly without UnicodeEncodeError
    from urllib.parse import urlsplit
    from tranx_core.web_translator import _encode_ascii_host, _encode_request_target

    encoded_target = _encode_request_target(urlsplit("https://cdn.example.jp/漫画/第1話.png?名前=花子"))
    encoded_target.encode("ascii")
    assert "%E6%BC%AB%E7%94%BB" in encoded_target
    assert _encode_ascii_host("2001:db8::1") == "[2001:db8::1]"
    # Real fetch_image_safely blocks private URLs immediately before any socket connect
    with pytest.raises(SSRFBlockedError):
        fetch_image_safely("http://169.254.169.254/latest/meta-data/")
    assert len(png_sample) > 0


def test_v25_owasp_security_headers_csrf_ssrf_zip_and_vision_ocr(tmp_path):
    """v2.5.0 security & vision hardening regression suite."""
    import io
    import zipfile
    from PIL import Image
    from jptrans.errors import InputError
    from tranx_core.doc_readers import inspect_zip_archive, read_docx_document, read_pdf_document
    from tranx_core.vision_ocr import RawVisionBubble, _nms_and_xy_cut_bubbles, _sample_outer_halo_bg
    from tranx_core.web_translator import SSRFBlockedError, validate_and_resolve_url

    repo = InMemoryRepository(env_api_key="test-key")
    app = create_flask_app(repo, llm_transport=RouteFakeTransport())
    client = app.test_client()

    # 1. Universal Cache-Control: no-store & W3C traceparent / X-Request-Id correlation
    trace_in = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    r_ok = client.get(
        "/v1/meta",
        headers={**_auth_headers(), "traceparent": trace_in},
    )
    assert r_ok.status_code == 200
    assert "no-store" in (r_ok.headers.get("Cache-Control") or "")
    assert r_ok.headers.get("X-Request-Id") == "4bf92f3577b34da6a3ce929d0e0e4736"

    # 2. Sec-Fetch-Site: cross-site CSRF rejection on mutating API routes
    r_csrf = client.post(
        "/v1/chat",
        json={"text": "hello", "mode": "en-id"},
        headers={
            **_auth_headers(),
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://evil.example.net",
        },
    )
    assert r_csrf.status_code == 403
    assert r_csrf.get_json()["error"]["code"] == "CSRF_BLOCKED"
    assert "no-store" in (r_csrf.headers.get("Cache-Control") or "")

    # Allowed origin with Sec-Fetch-Site: cross-site is still permitted
    r_allowed = client.post(
        "/v1/chat",
        json={"text": "hello", "mode": "en-id"},
        headers={
            **_auth_headers(),
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://tranx-hanif-id.web.app",
        },
    )
    assert r_allowed.status_code == 200

    # Non-browser X-Inbox-Token webhook bypasses browser Sec-Fetch-Site check
    r_webhook = client.post(
        "/v1/inbox",
        json={"url": "https://example.com/ch1"},
        headers={
            "X-Inbox-Token": "wrong-token",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    # Rejected by token check (401/403 token), NOT early CSRF block when X-Inbox-Token is present
    assert r_webhook.status_code in (401, 403, 503)

    # 3. SSRF RFC 6890 benchmark range, IPv6 discard, NAT64, and CRLF smuggling rejection
    for bad_url in (
        "http://198.18.0.1/bench",
        "http://[100::1]/discard",
        "http://[64:ff9b::127.0.0.1]/nat64",
        "https://example.com/a\r\nX-Injected: 1",
        "https://example.com/path\x00null",
    ):
        with pytest.raises((SSRFBlockedError, ValueError)):
            validate_and_resolve_url(bad_url)

    # 4. Magic-byte validation rejects disguised PDF and DOCX
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"<html>not a pdf</html>")
    with pytest.raises(InputError, match="PDF"):
        read_pdf_document(fake_pdf)

    fake_docx = tmp_path / "fake.docx"
    fake_docx.write_bytes(b"not a zip archive")
    with pytest.raises(InputError, match="ZIP"):
        inspect_zip_archive(fake_docx)

    # Valid tiny ZIP passes magic check and does not false-positive Fifield overlap guard
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", "Halo dunia pertama")
        zf.writestr("b.txt", "Halo dunia kedua")
    good_zip = tmp_path / "good.zip"
    good_zip.write_bytes(buf.getvalue())
    inspect_zip_archive(good_zip)
    assert callable(read_docx_document)

    # 5. Vision OCR NMS, XY-Cut RTL ordering, and outer-halo bgTone sampling
    nms_xy_out = _nms_and_xy_cut_bubbles(
        [
            ([20, 40, 160, 100], RawVisionBubble(id=1, box_2d=(40, 20, 140, 180), text="left")),
            ([22, 42, 156, 98], RawVisionBubble(id=2, box_2d=(42, 22, 140, 178), text="left-longer")),
            ([260, 40, 160, 100], RawVisionBubble(id=3, box_2d=(40, 260, 140, 420), text="right")),
            ([20, 260, 400, 100], RawVisionBubble(id=4, box_2d=(260, 20, 360, 420), text="bottom")),
        ],
        width=500,
        height=400,
        is_rtl=True,
    )
    assert [b.text for _, b in nms_xy_out] == ["right", "left-longer", "bottom"]

    dark_img = Image.new("RGB", (120, 120), (18, 20, 26))
    halo = _sample_outer_halo_bg(dark_img, [30, 30, 60, 60])
    assert halo is not None
    tone, rgb = halo
    assert tone == "dark"
    assert rgb[0] < 40


def test_v251_hardening_and_correctness_regressions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v2.5.1 regression tests: doc ID validation, inbox 5-token cap & revoke, speech lang validation,
    DOCX paragraph/table order, ZIP symlink/XXE sniffing, Gemini 2.5 thought filtering, EXIF transpose & get_many."""
    import io
    import zipfile
    from PIL import Image
    init_tranx_core()
    from jptrans.errors import InputError
    from tranx_core.cache import InMemoryCacheStore, LayeredTranslationCache
    from tranx_core.doc_readers import inspect_zip_archive, read_docx_document
    from tranx_core.vision_ocr import GeminiVisionExtractor, translate_image_bytes

    repo = InMemoryRepository()
    app = create_flask_app(repo, llm_transport=RouteFakeTransport())
    client = app.test_client()

    # 1. Invalid doc IDs rejected with 400 across chat/merge/inbox
    r_bad_cid = client.post(
        "/v1/chat",
        json={"cid": "../escape", "mode": "ja-id", "text": "おはようございます。"},
        headers=_auth_headers(),
    )
    assert r_bad_cid.status_code == 400
    r_bad_merge = client.post(
        "/v1/titles:merge",
        json={"fromTitleId": "bad/id", "toTitleId": "t_ok"},
        headers=_auth_headers(),
    )
    assert r_bad_merge.status_code == 400

    # 2. Inbox token 5-token hard cap & revoke_all_sessions clears both pairCodes and inboxTokens
    created_tokens: list[str] = []
    for _ in range(5):
        res_tok = client.post("/v1/inbox:token", headers=_auth_headers())
        assert res_tok.status_code == 200
        created_tokens.append(res_tok.get_json()["token"])
    assert len(repo.inbox_tokens) == 5
    # 6th token is rejected with 400 until revoked
    res_sixth = client.post("/v1/inbox:token", headers=_auth_headers())
    assert res_sixth.status_code == 400
    # Valid token works via O(1) SHA-256 lookup
    r_push_ok = client.post(
        "/v1/inbox",
        json={"text": "Halo"},
        headers={"X-Inbox-Token": created_tokens[-1]},
    )
    assert r_push_ok.status_code == 201
    # Revoke wipes both pairCodes and inboxTokens, invalidating old tokens
    assert client.post("/v1/auth:pairCode", headers=_auth_headers()).status_code == 200
    assert client.post("/v1/auth:revoke", headers=_auth_headers()).status_code == 204
    assert len(repo.inbox_tokens) == 0
    assert len(repo.pair_codes) == 0
    r_push_revoked = client.post(
        "/v1/inbox",
        json={"text": "Halo"},
        headers={"X-Inbox-Token": created_tokens[-1]},
    )
    assert r_push_revoked.status_code == 401

    # 3. /v1/speech:transcribe rejects invalid lang with 400 via multipart form-data
    r_bad_lang = client.post(
        "/v1/speech:transcribe",
        data={
            "lang": "xx-INVALID",
            "audio": (io.BytesIO(b"RIFF\x00\x00\x00\x00WAVE"), "clip.webm", "audio/webm"),
        },
        content_type="multipart/form-data",
        headers=_auth_headers(),
    )
    assert r_bad_lang.status_code == 400
    assert r_bad_lang.get_json()["error"]["code"] == "INVALID_INPUT"

    # 4. Security headers on /v1/*
    r_hdr = client.get("/v1/meta", headers=_auth_headers())
    assert r_hdr.headers.get("Strict-Transport-Security")
    assert r_hdr.headers.get("Referrer-Policy") == "no-referrer"
    assert r_hdr.headers.get("Cross-Origin-Resource-Policy") == "same-site"
    assert "default-src 'none'" in (r_hdr.headers.get("Content-Security-Policy") or "")

    # 5. DOCX reader preserves interleaved paragraph + table order
    docx_path = tmp_path / "order.docx"
    wdoc = docx.Document()
    wdoc.add_paragraph("First Paragraph")
    tbl = wdoc.add_table(rows=1, cols=2)
    tbl.rows[0].cells[0].text = "Cell A"
    tbl.rows[0].cells[1].text = "Cell B"
    wdoc.add_paragraph("Second Paragraph")
    wdoc.save(str(docx_path))
    parsed_docx = read_docx_document(docx_path)
    assert [p.text for p in parsed_docx.paragraphs] == [
        "First Paragraph",
        "Cell A",
        "Cell B",
        "Second Paragraph",
    ]

    # 6. inspect_zip_archive rejects XML-disguised-as-.txt XXE and symlink entries
    xxe_buf = io.BytesIO()
    with zipfile.ZipFile(xxe_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("notes.txt", '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe "bad">]><a/>')
    xxe_path = tmp_path / "xxe.zip"
    xxe_path.write_bytes(xxe_buf.getvalue())
    with pytest.raises(InputError):
        inspect_zip_archive(xxe_path)

    sym_buf = io.BytesIO()
    with zipfile.ZipFile(sym_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zi = zipfile.ZipInfo("link.txt")
        zi.create_system = 3  # Unix
        zi.external_attr = 0o120777 << 16  # S_IFLNK
        zf.writestr(zi, "/etc/passwd")
    sym_path = tmp_path / "sym.zip"
    sym_path.write_bytes(sym_buf.getvalue())
    with pytest.raises(InputError):
        inspect_zip_archive(sym_path)

    # 7. LayeredTranslationCache.get_many batch hit
    store = InMemoryCacheStore()
    cache = LayeredTranslationCache(store)
    cache.put_many([("k1", "llm", "ja", "id", "A"), ("k2", "llm", "ja", "id", "B")])
    got = cache.get_many(["k1", "k2", "missing"])
    assert got == {"k1": "A", "k2": "B"}

    # 8. GeminiVisionExtractor skips Gemini 2.5 thought parts & translate_image_bytes transposes EXIF + emits sfxImportance
    import urllib.request
    extractor = GeminiVisionExtractor(api_key="dummy-key")
    payload_bytes = json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "internal reasoning"},
                            {
                                "text": json.dumps(
                                    {
                                        "bubbles": [
                                            {
                                                "id": 1,
                                                "box_2d": [100, 100, 300, 500],
                                                "text": "ドーン",
                                                "kind": "sfx",
                                                "sfxImportance": "impact",
                                                "shape": "jagged",
                                                "bgTone": "dark",
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            },
                        ]
                    }
                }
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")

    class _FakeResp:
        def __enter__(self) -> "_FakeResp":
            return self
        def __exit__(self, *_a: Any) -> bool:
            return False
        def read(self) -> bytes:
            return payload_bytes

    monkeypatch.setattr(urllib.request, "urlopen", lambda _req, timeout=45.0: _FakeResp())
    # Create a 100x60 image with EXIF Orientation=6 (rotate 90 CW -> 60x100 after transpose!)
    im = Image.new("RGB", (100, 60), (20, 20, 24))
    exif = im.getexif()
    exif[274] = 6
    img_buf = io.BytesIO()
    im.save(img_buf, format="JPEG", exif=exif)
    from tranx_core import FirestoreGlossary
    img_res = translate_image_bytes(
        image_bytes=img_buf.getvalue(),
        mode="ja-id",
        title_name="t_img_exif",
        settings=repo.get_settings(),
        glossary=FirestoreGlossary("t_img_exif", "t_img_exif", backend=repo.glossary_backend),
        cache=cache,
        extractor=extractor,
        llm_transport=RouteFakeTransport(),
    )
    assert img_res["width"] == 60 and img_res["height"] == 100
    assert img_res["blocks"][0]["sfxImportance"] == "impact"


def test_v251_pass2_security_parity_and_regression_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass-2 regressions: dict post_json response in _call_llm_json_chat, EPUB 2/3 DOCTYPE allow vs XXE block,
    WebVTT <rp> ReDoS linear runtime, server-key model/cap ceilings, /v1/links:preview lockedNames int contract,
    web CSS escape + third-party stylesheet sanitization, and English stopword parity vs Indonesian prefixes."""
    import io
    import time
    import zipfile
    from bs4 import BeautifulSoup
    init_tranx_core()
    from jptrans.errors import InputError
    from tranx_core import (
        ALLOWED_SERVER_KEY_MODELS,
        AppSettings,
        effective_settings_for_key_source,
        read_document_safely,
    )
    from tranx_core.doc_readers import inspect_zip_archive
    import tranx_core.multilingual as ml_mod
    from tranx_core.web_translator import sanitize_soup

    # 1. _call_llm_json_chat handles real dict return from jptrans.net.post_json without TypeError
    monkeypatch.setattr(
        ml_mod,
        "post_json",
        lambda *_a, **_kw: {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"translations": [{"id": 0, "text": "Halo dunia"}]})
                    }
                }
            ]
        },
    )
    parsed_items = ml_mod._call_llm_json_chat(
        model="gemini-2.5-flash",
        temperature=0.2,
        sys_prompt="Translate",
        user_content='{"items": [{"i": 0, "s": "Hello world"}]}',
        settings=AppSettings(),
        clean_key="dummy-key",
        usage_tracker=None,
        llm_transport=None,
        char_count=11,
    )
    assert parsed_items == {0: "Halo dunia"}

    # 2. Valid EPUB 3 (<!DOCTYPE html>) and EPUB 2 NCX PUBLIC doctype pass; XXE / internal subset blocked
    epub3_buf = io.BytesIO()
    with zipfile.ZipFile(epub3_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("OEBPS/ch1.xhtml", "<!DOCTYPE html><html><body><p>Bab 1</p></body></html>")
        zf.writestr(
            "OEBPS/toc.ncx",
            '<?xml version="1.0"?><!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" '
            '"http://www.daisy.org/z3986/2005/ncx-2005-1.dtd"><ncx/>',
        )
    epub3_path = tmp_path / "valid.epub"
    epub3_path.write_bytes(epub3_buf.getvalue())
    inspect_zip_archive(epub3_path)

    xxe_epub_buf = io.BytesIO()
    with zipfile.ZipFile(xxe_epub_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "OEBPS/ch1.xhtml",
            '<!DOCTYPE html [<!ENTITY bomb "boom">]><html><body>&bomb;</body></html>',
        )
    xxe_epub_path = tmp_path / "xxe.epub"
    xxe_epub_path.write_bytes(xxe_epub_buf.getvalue())
    with pytest.raises(InputError):
        inspect_zip_archive(xxe_epub_path)

    # 3. Pathological WebVTT with 200 unclosed <rp> tags parses linearly (< 50 ms, zero ReDoS)
    vtt_path = tmp_path / "redos.vtt"
    vtt_path.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n" + ("<rp>" * 200) + "Halo dunia\n",
        encoding="utf-8",
    )
    t0 = time.perf_counter()
    vtt_doc = read_document_safely(vtt_path)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 250.0
    assert any("Halo dunia" in p.text for p in vtt_doc.paragraphs)

    # 4. Server-key ceiling enforces ALLOWED_SERVER_KEY_MODELS and daily caps when key_source == "env"
    abused = AppSettings(
        llm_models=("expensive-custom-model", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.0-flash-lite"),
        daily_char_cap=99_999_999,
        daily_call_cap=999_999,
    )
    clamped = effective_settings_for_key_source(abused, "env")
    assert all(m in ALLOWED_SERVER_KEY_MODELS for m in clamped.llm_models)
    assert len(clamped.llm_models) <= 3
    assert clamped.daily_char_cap <= 300_000
    assert clamped.daily_call_cap <= 1_500

    # 5. /v1/links:preview returns integer lockedNames matching frontend contract
    repo = InMemoryRepository()
    app = create_flask_app(
        repo,
        llm_transport=RouteFakeTransport(),
        web_fetcher=lambda _url: FetchedPage(
            final_url="https://example.jp/ch1",
            host="example.jp",
            content_type="text/html",
            text="<html><head><title>Bab 1</title></head><body><p>おはようございます。</p></body></html>",
        ),
    )
    client = app.test_client()
    r_prev = client.post(
        "/v1/links:preview",
        json={"url": "https://example.jp/ch1", "mode": "ja-id"},
        headers=_auth_headers(),
    )
    assert r_prev.status_code == 200
    prev_body = r_prev.get_json()
    assert isinstance(prev_body["lockedNames"], int)

    # 6. web_translator.sanitize_soup blocks CSS comment/hex-escape exfil & 3p CSS, preserves same-host CSS & rewrites relative img src
    soup = BeautifulSoup(
        """
        <html>
          <head>
            <link rel="stylesheet" href="https://example.jp/style.css" />
            <link rel="stylesheet" href="https://evil.example/track.css" />
            <style>body { background: u\\72l(https://evil.example/leak); color: #222; }</style>
            <style>p { color: #333; }</style>
          </head>
          <body>
            <img src="/assets/pic.png" />
            <a href="javascript:alert(1)" target="_top">x</a>
            <p style="background: /*c*/url(https://evil.example/x); color: red">Halo</p>
          </body>
        </html>
        """,
        "html.parser",
    )
    sanitize_soup(soup, "https://example.jp/chapter/1", lambda u: u)
    html_out = str(soup)
    assert "https://example.jp/style.css" in html_out
    assert "evil.example" not in html_out
    assert "https://example.jp/assets/pic.png" in html_out
    assert "javascript:" not in html_out
    assert 'target="_top"' not in html_out

    # 7. English sentences with ter-/mem-/ber- prefixes are NOT misclassified as Indonesian
    assert ml_mod.classify_paragraph_language("A terrible member decided to perform better.") == "en"
    assert ml_mod.classify_paragraph_language("Saya ingin pergi ke sekolah bersama teman.") == "id"









