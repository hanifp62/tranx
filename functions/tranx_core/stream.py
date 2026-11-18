"""Streaming executors for fast 1-call chat, chunked long text/documents, idempotent resume, and async NameChip lookup."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from jptrans.models import Document, Paragraph, Slot
from jptrans.pipeline import Translator
from jptrans.readers import read_text
from jptrans.style import Renderer

from .cache import LayeredTranslationCache
from .config import AppSettings, TitleStyle, chat_config, long_config
from .engines import DailyCapExceeded, UsageTracker, build_engine_chain
from .glossary_store import FirestoreGlossary, glossary_entry_to_dict
from .multilingual import parse_mode_pair, translate_multilingual_document

DEFAULT_CHUNK_PARAS = 8


def stream_fast_chat(
    *,
    text: str,
    mode: str,
    title_name: str,
    settings: AppSettings,
    glossary: FirestoreGlossary,
    cache: LayeredTranslationCache,
    style: TitleStyle | None = None,
    api_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    llm_transport: Any = None,
) -> Iterator[dict[str, Any]]:
    """Stream NDJSON events for fast chat (<= 5,000 chars) in a single LLM batch call."""
    clean = (text or "").strip()
    if not clean:
        yield {"type": "error", "code": "EMPTY_TEXT", "message": "Teks masukan kosong."}
        return
    if len(clean) > settings.chat_max_chars:
        yield {
            "type": "error",
            "code": "TEXT_TOO_LONG_FOR_CHAT",
            "message": f"Teks melampaui {settings.chat_max_chars} karakter; gunakan aliran naskah panjang.",
        }
        return

    started = time.monotonic()
    req_src, eff_src, target_lang = parse_mode_pair(
        mode,
        sample_text=clean,
        default_source=settings.default_source,
        default_target=settings.default_target,
    )
    doc = read_text(clean, title_name)
    yield {
        "type": "meta",
        "mode": f"{req_src}-{target_lang}",
        "detectedSource": eff_src,
        "totalParas": len(doc.paragraphs),
        "model": settings.llm_models[0],
    }

    try:
        if eff_src == "ja" and target_lang in ("id", "en"):
            cfg = chat_config(settings, target_lang, style=style)
            engines = build_engine_chain(
                cfg,
                settings,
                api_key=api_key,
                usage_tracker=usage_tracker,
                transport=llm_transport,
            )
            with Translator(cfg, engines, cache, glossary) as tr:
                result = tr.translate_document(doc)
        else:
            result, _ = translate_multilingual_document(
                doc=doc,
                src_lang=eff_src,
                tgt_lang=target_lang,
                settings=settings,
                glossary_entries=glossary.non_builtin_entries(),
                cache=cache,
                api_key=api_key,
                usage_tracker=usage_tracker,
                llm_transport=llm_transport,
            )
    except DailyCapExceeded as exc:
        yield {
            "type": "error",
            "code": "DAILY_CAP_REACHED",
            "message": "Batas pemakaian harian tercapai. Sesuaikan batas di Setelan -> Lanjutan.",
            "charsUsed": exc.chars_used,
            "charCap": exc.char_cap,
        }
        return
    except Exception as exc:
        yield {
            "type": "error",
            "code": "ENGINE_FAILED",
            "message": str(exc),
        }
        return

    sentences_flat: list[dict[str, Any]] = []
    used_model = settings.llm_models[0]
    for p_idx, tpara in enumerate(result.paragraphs):
        dst_text = tpara.target or tpara.source.text
        for s in tpara.sentences:
            if s.engine:
                used_model = s.engine
            sentences_flat.append(
                {
                    "src": s.source,
                    "dst": s.target,
                    "status": s.status,
                    "engine": s.engine,
                }
            )
        yield {
            "type": "seg",
            "i": p_idx,
            "src": tpara.source.text,
            "dst": dst_text,
        }

    elapsed_ms = round((time.monotonic() - started) * 1000)
    yield {
        "type": "done",
        "fullDst": result.target,
        "detectedSource": eff_src,
        "sentences": sentences_flat,
        "ms": elapsed_ms,
        "model": used_model,
    }


def lookup_new_names_for_text(
    *,
    text: str,
    mode: str,
    title_name: str,
    settings: AppSettings,
    glossary: FirestoreGlossary,
    cache: LayeredTranslationCache,
    style: TitleStyle | None = None,
    api_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    llm_transport: Any = None,
) -> list[dict[str, Any]]:
    """Run jptrans.Translator.prepare(doc) after Japanese chat completes to resolve new kanji names for NameChip."""
    _, eff_src, target_lang = parse_mode_pair(
        mode,
        sample_text=text,
        default_source=settings.default_source,
        default_target=settings.default_target,
    )
    if eff_src != "ja" or target_lang not in ("id", "en"):
        return []
    before_surfaces = {e.surface for e in glossary.non_builtin_entries()}
    cfg = long_config(settings, target_lang, style=style)
    engines = build_engine_chain(
        cfg,
        settings,
        api_key=api_key,
        usage_tracker=usage_tracker,
        transport=llm_transport,
    )
    doc = read_text(text, title_name)
    renderer = Renderer(cfg)

    with Translator(cfg, engines, cache, glossary) as tr:
        prepared = tr.prepare(doc)

    chips: list[dict[str, Any]] = []
    for entry in prepared:
        if entry.source == "builtin":
            continue
        rendered_dst = renderer(Slot(entry=entry)) or entry.render_for(target_lang) or entry.romaji or entry.surface
        item = glossary_entry_to_dict(entry)
        item["dst"] = rendered_dst
        item["new"] = entry.surface not in before_surfaces
        chips.append(item)
    return chips


def stream_document_chunks(
    *,
    doc: Document,
    mode: str,
    settings: AppSettings,
    glossary: FirestoreGlossary,
    cache: LayeredTranslationCache,
    existing_paras: Mapping[int, dict[str, Any]] | None = None,
    on_para_saved: Callable[[int, dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    style: TitleStyle | None = None,
    chunk_size: int = DEFAULT_CHUNK_PARAS,
    api_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    llm_transport: Any = None,
) -> Iterator[dict[str, Any]]:
    """Translate a Document in resumable paragraph chunks, skipping already persisted paragraphs."""
    started = time.monotonic()
    sample_text = "\n".join(p.text for p in doc.paragraphs[:6])
    req_src, eff_src, target_lang = parse_mode_pair(
        mode,
        sample_text=sample_text,
        default_source=settings.default_source,
        default_target=settings.default_target,
    )
    persisted = dict(existing_paras or {})
    total = len(doc.paragraphs)

    yield {
        "type": "meta",
        "mode": f"{req_src}-{target_lang}",
        "detectedSource": eff_src,
        "title": doc.title,
        "fmt": doc.fmt,
        "totalParas": total,
        "resumedFrom": len(persisted),
    }

    if not (eff_src == "ja" and target_lang in ("id", "en")):
        pending_indices = [i for i in range(total) if i not in persisted]
        done_count = len(persisted)
        for offset in range(0, len(pending_indices), max(chunk_size, 1)):
            if should_stop is not None and should_stop():
                yield {
                    "type": "done",
                    "state": "stopped",
                    "doneParas": done_count,
                    "totalParas": total,
                    "ms": round((time.monotonic() - started) * 1000),
                }
                return
            batch_indices = pending_indices[offset : offset + max(chunk_size, 1)]
            sub_doc = Document(
                title=doc.title,
                paragraphs=[doc.paragraphs[idx] for idx in batch_indices],
                ruby=doc.ruby,
                source_path=doc.source_path,
                fmt=doc.fmt,
            )
            try:
                sub_result, used_m = translate_multilingual_document(
                    doc=sub_doc,
                    src_lang=eff_src,
                    tgt_lang=target_lang,
                    settings=settings,
                    glossary_entries=glossary.non_builtin_entries(),
                    cache=cache,
                    api_key=api_key,
                    usage_tracker=usage_tracker,
                    llm_transport=llm_transport,
                )
            except DailyCapExceeded as exc:
                yield {
                    "type": "error",
                    "code": "DAILY_CAP_REACHED",
                    "state": "partial",
                    "doneParas": done_count,
                    "totalParas": total,
                    "message": "Batas pemakaian harian tercapai.",
                    "charsUsed": exc.chars_used,
                    "charCap": exc.char_cap,
                }
                return
            except Exception as exc:
                yield {
                    "type": "error",
                    "code": "ENGINE_FAILED",
                    "state": "partial" if done_count > 0 else "error",
                    "doneParas": done_count,
                    "totalParas": total,
                    "message": str(exc),
                }
                return
            for global_idx, tpara in zip(batch_indices, sub_result.paragraphs):
                para_payload = {
                    "i": global_idx,
                    "src": tpara.source.text,
                    "dst": tpara.target or tpara.source.text,
                    "kind": tpara.source.kind,
                    "meta": dict(tpara.source.meta),
                    "sentences": [
                        {"src": s.source, "dst": s.target, "status": s.status, "engine": s.engine, "turn": s.turn}
                        for s in tpara.sentences
                    ],
                    "model": used_m,
                }
                persisted[global_idx] = para_payload
                done_count += 1
                if on_para_saved is not None:
                    on_para_saved(global_idx, para_payload)
                yield {"type": "para", **para_payload, "doneParas": done_count, "totalParas": total}
        yield {
            "type": "done",
            "state": "done",
            "detectedSource": eff_src,
            "doneParas": done_count,
            "totalParas": total,
            "ms": round((time.monotonic() - started) * 1000),
        }
        return

    cfg = long_config(settings, target_lang, style=style)
    engines = build_engine_chain(
        cfg,
        settings,
        api_key=api_key,
        usage_tracker=usage_tracker,
        transport=llm_transport,
    )

    with Translator(cfg, engines, cache, glossary) as tr:
        try:
            active_entries = tr.prepare(doc)
        except DailyCapExceeded as exc:
            yield {
                "type": "error",
                "code": "DAILY_CAP_REACHED",
                "state": "partial" if persisted else "stopped",
                "doneParas": len(persisted),
                "totalParas": total,
                "message": "Batas pemakaian harian tercapai.",
                "charsUsed": exc.chars_used,
                "charCap": exc.char_cap,
            }
            return

        yield {
            "type": "names",
            "entries": [
                glossary_entry_to_dict(e)
                for e in active_entries
                if e.source != "builtin"
            ],
        }

        pending_indices = [i for i in range(total) if i not in persisted]
        done_count = len(persisted)

        for offset in range(0, len(pending_indices), max(chunk_size, 1)):
            if should_stop is not None and should_stop():
                yield {
                    "type": "done",
                    "state": "stopped",
                    "doneParas": done_count,
                    "totalParas": total,
                    "ms": round((time.monotonic() - started) * 1000),
                }
                return

            batch_indices = pending_indices[offset : offset + max(chunk_size, 1)]
            sub_doc = Document(
                title=doc.title,
                paragraphs=[doc.paragraphs[idx] for idx in batch_indices],
                ruby=doc.ruby,
                source_path=doc.source_path,
                fmt=doc.fmt,
            )
            # Translate batch with fresh inner Translator sharing already-prepared glossary & cache
            batch_cfg = chat_config(settings, target_lang, style=style)
            batch_engines = build_engine_chain(
                batch_cfg,
                settings,
                api_key=api_key,
                usage_tracker=usage_tracker,
                transport=llm_transport,
            )
            try:
                with Translator(batch_cfg, batch_engines, cache, glossary) as batch_tr:
                    sub_result = batch_tr.translate_document(sub_doc)
            except DailyCapExceeded as exc:
                yield {
                    "type": "error",
                    "code": "DAILY_CAP_REACHED",
                    "state": "partial",
                    "doneParas": done_count,
                    "totalParas": total,
                    "message": "Batas pemakaian harian tercapai. Bagian yang selesai tetap tersimpan.",
                    "charsUsed": exc.chars_used,
                    "charCap": exc.char_cap,
                }
                return
            except Exception as exc:
                yield {
                    "type": "error",
                    "code": "ENGINE_FAILED",
                    "state": "partial" if done_count > 0 else "error",
                    "doneParas": done_count,
                    "totalParas": total,
                    "message": str(exc),
                }
                return

            for global_idx, tpara in zip(batch_indices, sub_result.paragraphs):
                para_payload = {
                    "i": global_idx,
                    "src": tpara.source.text,
                    "dst": tpara.target or tpara.source.text,
                    "kind": tpara.source.kind,
                    "meta": dict(tpara.source.meta),
                    "sentences": [
                        {
                            "src": s.source,
                            "dst": s.target,
                            "status": s.status,
                            "engine": s.engine,
                            "turn": s.turn,
                        }
                        for s in tpara.sentences
                    ],
                    "model": settings.llm_models[0],
                }
                persisted[global_idx] = para_payload
                done_count += 1
                if on_para_saved is not None:
                    on_para_saved(global_idx, para_payload)
                yield {"type": "para", **para_payload, "doneParas": done_count, "totalParas": total}

    yield {
        "type": "done",
        "state": "done",
        "doneParas": done_count,
        "totalParas": total,
        "ms": round((time.monotonic() - started) * 1000),
    }
