"""Document exporters (.docx writer, zero-LLM re-export from stored paragraphs, and tranX v3 <ruby> HTML)."""

from __future__ import annotations

import base64
import io
from collections.abc import Sequence
from typing import Any

import docx
from jptrans.config import Config
from jptrans.models import (
    Document,
    GlossaryEntry,
    Paragraph,
    SentencePair,
    TranslatedDocument,
    TranslatedParagraph,
)
from jptrans.writers import CONTENT_TYPES, render_output, register_writer

_WRITER_REGISTERED = False

TRANX_READER_CSS = """
<style id="tranx-v3-reader-override">
  :root {
    --tx-bg: #FAFBFA;
    --tx-surface: #FFFFFF;
    --tx-border: #DEE3E0;
    --tx-text: #141917;
    --tx-muted: #4F5855;
    --tx-accent: #17695B;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --tx-bg: #171B1A;
      --tx-surface: #1F2423;
      --tx-border: #2B3230;
      --tx-text: #E7ECEA;
      --tx-muted: #A5AEAA;
      --tx-accent: #5DC3AC;
    }
  }
  html[data-tranx-v3="Gelap"] {
    --tx-bg: #171B1A;
    --tx-surface: #1F2423;
    --tx-border: #2B3230;
    --tx-text: #E7ECEA;
    --tx-muted: #A5AEAA;
    --tx-accent: #5DC3AC;
  }
  body {
    background: var(--tx-bg) !important;
    color: var(--tx-text) !important;
    font-family: Charter, Georgia, Cambria, serif !important;
    max-width: 920px !important;
    margin: 0 auto !important;
    padding: 24px 20px 64px !important;
  }
  ruby { line-height: 2.1; }
  rt {
    font-size: 0.55em;
    color: var(--tx-muted);
    user-select: none;
    -webkit-user-select: none;
  }
</style>
"""


def render_docx_bytes(result: TranslatedDocument) -> bytes:
    """Build a binary .docx file from a TranslatedDocument."""
    out_doc = docx.Document()
    if result.document.title:
        out_doc.add_heading(result.document.title, level=0)
    for tpara in result.paragraphs:
        text = tpara.target or tpara.source.text
        if not text:
            continue
        if tpara.source.kind == "heading":
            out_doc.add_heading(text, level=2)
        else:
            out_doc.add_paragraph(text)
    buf = io.BytesIO()
    out_doc.save(buf)
    return buf.getvalue()


def _render_docx_text_bridge(result: TranslatedDocument) -> str:
    return base64.b64encode(render_docx_bytes(result)).decode("ascii")


def register_custom_writers() -> None:
    global _WRITER_REGISTERED
    if _WRITER_REGISTERED:
        return
    register_writer(
        "docx",
        _render_docx_text_bridge,
        suffixes=(".docx",),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    _WRITER_REGISTERED = True


def export_translated_document(
    result: TranslatedDocument,
    fmt: str,
    *,
    bilingual: bool = False,
    theme: str | None = None,
) -> tuple[bytes, str, str]:
    """Render TranslatedDocument to (bytes, content_type, extension) without LLM calls."""
    register_custom_writers()
    clean_fmt = fmt.strip().lower().lstrip(".")
    if clean_fmt == "docx":
        return (
            render_docx_bytes(result),
            CONTENT_TYPES["docx"],
            "docx",
        )

    rendered = render_output(result, clean_fmt, bilingual=bilingual)
    if clean_fmt == "html":
        if theme in ("Terang", "Gelap"):
            rendered = rendered.replace("<html", f'<html data-tranx-v3="{theme}"', 1)
        if "</head>" in rendered:
            rendered = rendered.replace("</head>", f"{TRANX_READER_CSS}</head>", 1)
    ctype = CONTENT_TYPES.get(clean_fmt, "text/plain; charset=utf-8")
    if "charset" not in ctype and clean_fmt != "json":
        ctype = f"{ctype}; charset=utf-8"
    return rendered.encode("utf-8"), ctype, clean_fmt


def rebuild_translated_document_from_paras(
    *,
    title: str,
    target_lang: str,
    fmt: str,
    stored_paras: Sequence[dict[str, Any]],
    glossary_entries: Sequence[GlossaryEntry] = (),
    ruby: dict[str, str] | None = None,
    cfg: Config | None = None,
) -> TranslatedDocument:
    """Reconstruct TranslatedDocument from persisted Firestore paras with 0 LLM calls."""
    del cfg
    ordered = sorted(stored_paras, key=lambda r: int(r.get("i", 0)))
    doc_paras: list[Paragraph] = []
    trans_paras: list[TranslatedParagraph] = []

    for row in ordered:
        src_text = str(row.get("src", ""))
        kind = str(row.get("kind", "text"))
        meta = dict(row.get("meta") or {})
        para_obj = Paragraph(text=src_text, kind=kind, meta=meta)
        doc_paras.append(para_obj)

        raw_sents = row.get("sentences")
        sent_pairs: list[SentencePair] = []
        if isinstance(raw_sents, list) and raw_sents:
            for s in raw_sents:
                sent_pairs.append(
                    SentencePair(
                        source=str(s.get("src") or s.get("source") or ""),
                        target=str(s.get("dst") or s.get("target") or ""),
                        engine=str(s.get("engine") or row.get("model") or "tranx_llm"),
                        status=str(s.get("status") or "ok"),
                        turn=int(s.get("turn", 0)),
                    )
                )
        else:
            sent_pairs.append(
                SentencePair(
                    source=src_text,
                    target=str(row.get("dst", "")),
                    engine=str(row.get("model") or "tranx_llm"),
                )
            )
        trans_paras.append(TranslatedParagraph(source=para_obj, sentences=sent_pairs))

    doc = Document(
        title=title,
        paragraphs=doc_paras,
        ruby=dict(ruby or {}),
        fmt=fmt or "txt",
    )
    return TranslatedDocument(
        document=doc,
        paragraphs=trans_paras,
        source_lang="ja",
        target_lang=target_lang,
        glossary=list(glossary_entries),
    )
