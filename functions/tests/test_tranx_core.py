"""Comprehensive offline unit and contract tests for tranx_core (AC-API-01..08 & security guards)."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import docx
import pytest
from PIL import Image
from pypdf import PdfWriter

FN_DIR = Path(__file__).resolve().parents[1]
if str(FN_DIR) not in sys.path:
    sys.path.insert(0, str(FN_DIR))

from tranx_core import (  # noqa: E402
    AppSettings,
    DailyCapExceeded,
    FetchedPage,
    FirestoreGlossary,
    GLOSSARY_ENTRY_FIELDS,
    InMemoryCacheStore,
    InMemoryGlossaryBackend,
    InMemoryUsageTracker,
    InputError,
    LayeredTranslationCache,
    RawVisionBubble,
    SSRFBlockedError,
    TitleStyle,
    WebGateBlockedError,
    denormalize_box_to_xywh,
    dict_to_glossary_entry,
    export_translated_document,
    init_tranx_core,
    inspect_zip_archive,
    lookup_new_names_for_text,
    read_document,
    read_text,
    rebuild_translated_document_from_paras,
    stream_document_chunks,
    stream_fast_chat,
    transcribe_short_audio,
    translate_image_bytes,
    translate_web_page,
    validate_and_resolve_url,
)


class FakeOpenAITransport:
    """Deterministic OpenAI chat/completions stub preserving 1-indexed [[E1]]..[[En]] placeholders and leaving zero Japanese residue."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.mapping = mapping or {}

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        import re

        self.calls.append(payload)
        user_msg = payload["messages"][1]["content"]
        raw_json = user_msg.split("Input:\n", 1)[1]
        items = json.loads(raw_json)
        translations = []
        for item in items:
            src = item["text"]
            if src in self.mapping:
                dst = self.mapping[src]
            elif src == "[[E1]]は走った。":
                dst = "[[E1]] berlari."
            elif src == "「[[E1]]は小さく笑った。」":
                dst = "“[[E1]] tersenyum kecil.”"
            elif src == "次の話へ進む。":
                dst = "Lanjut ke bab berikutnya."
            else:
                # Keep all [[E#]] tokens intact and convert remaining CJK to Latin Indonesian stub
                tokens = re.findall(r"\[\[E\d+\]\]", src)
                para_num = re.search(r"第(\d+)段落", src)
                tag = f"Paragraf {para_num.group(1)} " if para_num else "Kalimat terjemahan "
                dst = (tag + " ".join(tokens)).strip() + "."
            translations.append({"id": item["id"], "text": dst})
        return {
            "choices": [
                {
                    "message": {"content": json.dumps({"translations": translations}, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ]
        }


def test_init_and_manifest_verification() -> None:
    digest = init_tranx_core(lambda: "dummy-key")
    assert len(digest) == 16
    assert len(GLOSSARY_ENTRY_FIELDS) == 14


def test_glossary_14_fields_and_user_lock_precedence(tmp_path: Path) -> None:
    """AC-API-03: user-confirmed entries are never overwritten by auto/engine mutations."""
    backend = InMemoryGlossaryBackend()
    backend.set_title("rashomon", "Rashomon")

    user_entry = dict_to_glossary_entry(
        {
            "surface": "歩",
            "kind": "PERSON",
            "reading": "あゆむ",
            "romaji": "Ayumu",
            "render_id": "Ayumu",
            "render_en": "Ayumu",
            "gender": "m",
            "confirmed": True,
            "source": "user",
            "updatedAt": "2026-11-19T00:00:00Z",  # stripped cleanly
        }
    )
    glos = FirestoreGlossary("rashomon", "Rashomon", backend=backend, include_builtins=False)
    assert glos.upsert(user_entry) is True
    glos.save(tmp_path / "must_not_be_created.json")
    assert not (tmp_path / "must_not_be_created.json").exists()

    # Simulate an automatic engine/heuristic entry trying to overwrite user entry
    auto_collision = dict_to_glossary_entry(
        {
            "surface": "歩",
            "kind": "PERSON",
            "reading": "あるく",
            "romaji": "Aruku",
            "confirmed": True,
            "source": "engine",
        }
    )
    assert glos.upsert(auto_collision, overwrite_confirmed=True) is False
    assert glos.remove("歩") is False

    reloaded = FirestoreGlossary.load_from_backend("rashomon", backend)
    got = reloaded.get("歩")
    assert got is not None
    assert got.romaji == "Ayumu"
    assert got.source == "user"

    # Reject unknown schema fields like render_ja or suggested
    with pytest.raises(InputError):
        dict_to_glossary_entry({"surface": "千早", "render_ja": "千早"})


def test_fast_chat_4500_chars_uses_single_llm_call() -> None:
    """AC-API-01: Japanese chat up to 5,000 chars completes in exactly 1 LLM call."""
    settings = AppSettings(chat_max_chars=5000)
    cache = LayeredTranslationCache(InMemoryCacheStore())
    backend = InMemoryGlossaryBackend()
    glos = FirestoreGlossary("chat1", "Obrolan", backend=backend)
    glos.upsert(
        dict_to_glossary_entry(
            {"surface": "鴉羽", "romaji": "Karasuba", "source": "user", "confirmed": True}
        )
    )
    glos.upsert(
        dict_to_glossary_entry(
            {"surface": "美咲", "romaji": "Misaki", "source": "user", "confirmed": True}
        )
    )

    # Build ~4,400 chars (> old 4,000 limit, <= 5,000 limit) across 30 sentences
    sentence = "「鴉羽さん、もう帰るの？」と美咲が聞いた。" + ("あ" * 120) + "。"
    long_chat = "\n".join([sentence] * 28)
    assert 4000 < len(long_chat) <= 5000

    transport = FakeOpenAITransport()
    events = list(
        stream_fast_chat(
            text=long_chat,
            mode="ja-id",
            title_name="Obrolan",
            settings=settings,
            glossary=glos,
            cache=cache,
            llm_transport=transport,
        )
    )
    assert events[0]["type"] == "meta"
    assert events[-1]["type"] == "done"
    assert len(transport.calls) == 1
    assert "Karasuba-san" in events[-1]["fullDst"]


def test_ayumu_kun_disambiguation_and_async_name_lookup() -> None:
    settings = AppSettings()
    cache = LayeredTranslationCache(InMemoryCacheStore())
    glos = FirestoreGlossary("novel1", "Novel", backend=InMemoryGlossaryBackend())
    glos.upsert(
        dict_to_glossary_entry(
            {"surface": "歩", "reading": "あゆむ", "romaji": "Ayumu", "gender": "m", "source": "user", "confirmed": True}
        )
    )
    transport = FakeOpenAITransport()
    events = list(
        stream_fast_chat(
            text="歩くんは走った。",
            mode="ja-id",
            title_name="Novel",
            settings=settings,
            glossary=glos,
            cache=cache,
            style=TitleStyle(honorific_style="keep"),
            llm_transport=transport,
        )
    )
    assert events[-1]["fullDst"] == "Ayumu-kun berlari."

    chips = lookup_new_names_for_text(
        text="歩くんは走った。",
        mode="ja-id",
        title_name="Novel",
        settings=settings,
        glossary=glos,
        cache=cache,
        llm_transport=transport,
    )
    assert any(c["surface"] == "歩" and "Ayumu" in c["dst"] for c in chips)


def test_resumable_document_stream_skips_persisted_paras() -> None:
    """AC-API-02: Resuming after interruption translates ONLY remaining paragraphs."""
    settings = AppSettings()
    cache = LayeredTranslationCache()  # fresh empty cache on second device
    glos = FirestoreGlossary("doc1", "Bab 1", backend=InMemoryGlossaryBackend(), include_builtins=False)

    six_paras_text = "\n\n".join([f"第{i}段落の日本語テストです。" for i in range(1, 7)])
    doc = read_text(six_paras_text, "Bab 1")
    assert len(doc.paragraphs) == 6

    saved: dict[int, dict[str, Any]] = {}
    first_transport = FakeOpenAITransport()

    # Stop after first chunk of 3 paragraphs
    def _save_cb(idx: int, payload: dict[str, Any]) -> None:
        saved[idx] = payload

    gen = stream_document_chunks(
        doc=doc,
        mode="ja-id",
        settings=settings,
        glossary=glos,
        cache=cache,
        on_para_saved=_save_cb,
        should_stop=lambda: len(saved) >= 3,
        chunk_size=3,
        llm_transport=first_transport,
    )
    first_events = list(gen)
    assert first_events[-1]["state"] == "stopped"
    assert len(saved) == 3

    # Resume on a brand-new cache & transport: only paras 3, 4, 5 may hit LLM
    second_transport = FakeOpenAITransport()
    resume_events = list(
        stream_document_chunks(
            doc=doc,
            mode="ja-id",
            settings=settings,
            glossary=glos,
            cache=LayeredTranslationCache(),
            existing_paras=saved,
            on_para_saved=_save_cb,
            chunk_size=3,
            llm_transport=second_transport,
        )
    )
    assert resume_events[0]["resumedFrom"] == 3
    assert resume_events[-1]["state"] == "done"
    assert len(saved) == 6
    assert len(second_transport.calls) == 1
    sent_payload = second_transport.calls[0]["messages"][1]["content"]
    assert "第1段落" not in sent_payload
    assert "第4段落" in sent_payload


def test_vision_ocr_xywh_conversion_and_glossary_consistency() -> None:
    """AC-API-05: Vision [ymin,xmin,ymax,xmax] converts to [x,y,w,h] for parse_pages."""
    assert denormalize_box_to_xywh([100, 200, 300, 700], 1000, 2000) == [200, 200, 500, 400]

    img = Image.new("RGB", (800, 1200), color=(250, 251, 250))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    class StubVision:
        def extract_bubbles(self, image_bytes: bytes, mime_type: str, model: str) -> list[RawVisionBubble]:
            assert mime_type == "image/png"
            return [
                RawVisionBubble(id=1, box_2d=(100, 250, 250, 750), text="「千早は小さく笑った。」")
            ]

    glos = FirestoreGlossary("manga1", "Manga", backend=InMemoryGlossaryBackend(), include_builtins=False)
    glos.upsert(
        dict_to_glossary_entry({"surface": "千早", "romaji": "Chihaya", "source": "user", "confirmed": True})
    )
    out = translate_image_bytes(
        image_bytes=buf.getvalue(),
        mode="ja-id",
        title_name="Manga",
        settings=AppSettings(),
        glossary=glos,
        cache=LayeredTranslationCache(),
        extractor=StubVision(),
        llm_transport=FakeOpenAITransport(),
    )
    assert out["width"] == 800 and out["height"] == 1200
    assert out["blocks"][0]["box"] == [200, 120, 400, 180]
    assert "Chihaya" in out["blocks"][0]["dst"]


def test_docx_pdf_readers_zip_security_and_zero_llm_export(tmp_path: Path) -> None:
    """AC-API-06: .docx/.pdf reading, zip-traversal/XXE rejection, and 0-LLM re-export."""
    init_tranx_core()

    # 1. Create real .docx file
    docx_path = tmp_path / "naskah.docx"
    wdoc = docx.Document()
    wdoc.add_heading("第一章", level=1)
    wdoc.add_paragraph("千早は小さく笑った。")
    wdoc.save(str(docx_path))

    parsed_docx = read_document(docx_path)
    assert parsed_docx.fmt == "docx"
    assert len(parsed_docx.paragraphs) == 2

    # 2. Create real valid .pdf file
    pdf_path = tmp_path / "kosong.pdf"
    pw = PdfWriter()
    pw.add_blank_page(width=300, height=300)
    with pdf_path.open("wb") as f:
        pw.write(f)
    parsed_pdf = read_document(pdf_path)
    assert parsed_pdf.fmt == "pdf"

    # 3. Malicious zip path traversal & XXE must be rejected
    evil_zip = tmp_path / "evil.docx"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("../secret.txt", "boom")
    with pytest.raises(InputError):
        inspect_zip_archive(evil_zip)

    xxe_zip = tmp_path / "xxe.docx"
    with zipfile.ZipFile(xxe_zip, "w") as zf:
        zf.writestr("word/document.xml", '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><w/>')
    with pytest.raises(InputError):
        inspect_zip_archive(xxe_zip)

    # 4. Zero-LLM re-export from stored paras into HTML (<ruby>) and DOCX
    stored_paras = [
        {"i": 0, "src": "千早は小さく笑った。", "dst": "Chihaya tersenyum kecil.", "kind": "text", "meta": {}}
    ]
    rebuilt = rebuild_translated_document_from_paras(
        title="Bab Uji",
        target_lang="id",
        fmt="docx",
        stored_paras=stored_paras,
        ruby={"千早": "ちはや"},
    )
    html_bytes, html_ctype, _ = export_translated_document(rebuilt, "html", theme="Gelap")
    html_str = html_bytes.decode("utf-8")
    assert "text/html" in html_ctype
    assert 'data-tranx-v3="Gelap"' in html_str
    assert "<ruby>" in html_str
    assert "Chihaya tersenyum kecil." in html_str

    docx_bytes, docx_ctype, ext = export_translated_document(rebuilt, "docx")
    assert ext == "docx"
    assert "officedocument" in docx_ctype
    reopened = docx.Document(io.BytesIO(docx_bytes))
    assert any("Chihaya tersenyum kecil." in p.text for p in reopened.paragraphs)


@pytest.mark.parametrize(
    "blocked_url,resolved_ip",
    [
        ("http://127.0.0.1/admin", "127.0.0.1"),
        ("http://169.254.169.254/computeMetadata/v1/", "169.254.169.254"),
        ("https://internal.example.com/", "10.0.0.5"),
        ("https://cgnat.example.com/", "100.64.1.2"),
        ("https://ipv6loop.example.com/", "::1"),
        ("https://ipv6priv.example.com/", "fc00::1"),
        ("file:///etc/passwd", "93.184.216.34"),
        ("https://example.com:8443/secret", "93.184.216.34"),
    ],
)
def test_anti_ssrf_blocks_private_loopback_metadata_and_bad_ports(
    blocked_url: str, resolved_ip: str
) -> None:
    with pytest.raises(SSRFBlockedError):
        validate_and_resolve_url(blocked_url, resolver=lambda _h, _p: [resolved_ip])


def test_web_translator_sanitizes_scripts_injects_base_and_rewrites_links() -> None:
    """AC-API-07: Mode Link translates DOM text via jptrans, strips XSS, and rewrites <a href>."""
    sample_html = """
    <html>
      <head><title>羅生門</title><script>alert('xss')</script></head>
      <body onload="evil()">
        <h1>羅生門</h1>
        <p>「千早は小さく笑った。」</p>
        <a href="/chapter-2.html" onclick="steal()">次の話へ進む。</a>
        <a href="javascript:alert(1)">Bad</a>
      </body>
    </html>
    """

    def fake_fetcher(url: str) -> FetchedPage:
        return FetchedPage(
            final_url=url,
            host="novel.example.jp",
            content_type="text/html",
            text=sample_html,
        )

    glos = FirestoreGlossary("web1", "Rashomon", backend=InMemoryGlossaryBackend(), include_builtins=False)
    glos.upsert(
        dict_to_glossary_entry({"surface": "千早", "romaji": "Chihaya", "source": "user", "confirmed": True})
    )
    glos.upsert(
        dict_to_glossary_entry({"surface": "羅生門", "render_id": "Gerbang Rashomon", "kind": "PLACE", "source": "user", "confirmed": True})
    )

    res = translate_web_page(
        url="https://novel.example.jp/chapter-1.html",
        mode="ja-id",
        title_id="web1",
        view="translated",
        settings=AppSettings(),
        glossary=glos,
        cache=LayeredTranslationCache(),
        fetcher=fake_fetcher,
        llm_transport=FakeOpenAITransport(),
    )
    html_out = res["html"]
    assert "<script" not in html_out
    assert "onload=" not in html_out
    assert "onclick=" not in html_out
    assert "javascript:" not in html_out
    assert '<base href="https://novel.example.jp/chapter-1.html"' in html_out
    assert "/web?url=https%3A%2F%2Fnovel.example.jp%2Fchapter-2.html&amp;mode=ja-id&amp;titleId=web1" in html_out or "/web?url=https%3A%2F%2Fnovel.example.jp%2Fchapter-2.html&mode=ja-id&titleId=web1" in html_out
    assert "Chihaya tersenyum kecil." in html_out


def test_speech_stt_validation_and_daily_cap_brake() -> None:
    """AC-API-08 & NFR-COST: Speech fallback validates size/MIME and respects WIB daily brake."""
    class StubSpeech:
        def transcribe(self, audio_bytes: bytes, mime_type: str, lang: str, model: str) -> str:
            return "千早は小さく笑った。"

    tracker = InMemoryUsageTracker()
    out = transcribe_short_audio(
        audio_bytes=b"OggS-fake-audio",
        mime_type="audio/ogg; codecs=opus",
        lang="ja-JP",
        settings=AppSettings(daily_char_cap=1000, daily_call_cap=10),
        transcriber=StubSpeech(),
        usage_tracker=tracker,
    )
    assert out["text"] == "千早は小さく笑った。"

    with pytest.raises(InputError):
        transcribe_short_audio(
            audio_bytes=b"x" * (4 * 1024 * 1024 + 1),
            mime_type="audio/webm",
            lang="ja-JP",
            settings=AppSettings(),
            transcriber=StubSpeech(),
        )

    with pytest.raises(DailyCapExceeded):
        tracker.check_and_record(
            model="gemini-2.5-flash-lite",
            chars=2000,
            calls=1,
            char_cap=1000,
            call_cap=10,
        )
