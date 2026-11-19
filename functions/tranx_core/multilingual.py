"""Bidirectional & auto-detect multilingual translation (auto/id/en/ja -> id/en/ja) with glossary placeholder protection."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from typing import Any

from jptrans.config import Config
from jptrans.engines.google import GoogleEngine
from jptrans.errors import InputError
from jptrans.models import Document, GlossaryEntry, Paragraph, SentencePair, TranslatedDocument, TranslatedParagraph
from jptrans.net import post_json
from jptrans.textnorm import contains_japanese

from .cache import LayeredTranslationCache
from .config import AppSettings, runtime_home
from .engines import UsageTracker

ALL_SOURCE_LANGS: tuple[str, ...] = ("auto", "ja", "id", "en")
ALL_TARGET_LANGS: tuple[str, ...] = ("id", "en", "ja")
ALL_MODE_PAIRS: tuple[str, ...] = (
    "auto-id",
    "auto-en",
    "auto-ja",
    "ja-id",
    "ja-en",
    "id-ja",
    "id-en",
    "en-id",
    "en-ja",
)

LANG_ENGLISH_NAMES = {
    "ja": "Japanese",
    "id": "Indonesian",
    "en": "English",
}

_ID_STOPWORDS = frozenset(
    {
        "yang", "dan", "di", "ke", "dari", "ini", "itu", "untuk", "dengan", "tidak", "tak",
        "bisa", "ada", "saya", "aku", "kamu", "kau", "dia", "ia", "kami", "kita", "mereka",
        "dalam", "pada", "adalah", "sudah", "akan", "atau", "karena", "seperti", "juga",
        "oleh", "tentang", "lebih", "sangat", "hanya", "saja", "telah", "dapat", "bagaimana",
        "mengapa", "kenapa", "kapan", "selamat", "pagi", "malam", "siang", "sore", "terima",
        "kasih", "tetap", "bukan", "belum", "masih", "lagi", "baru", "semua", "setiap",
        "ketika", "saat", "waktu", "hari", "orang", "cerita", "bab", "halaman", "buku",
        "baca", "pergi", "datang", "tetapi", "tapi", "namun", "jika", "kalau", "agar",
        "mau", "ingin", "harus", "boleh", "perlu", "jadi", "sesuai", "berubah", "halo",
    }
)
_EN_STOPWORDS = frozenset(
    {
        "the", "and", "to", "of", "in", "is", "it", "you", "that", "for", "with", "on",
        "are", "this", "have", "from", "not", "but", "what", "all", "were", "when", "we",
        "your", "can", "their", "would", "there", "been", "has", "more", "who", "will",
        "about", "into", "than", "morning", "hello", "good", "chapter", "next", "previous",
        "page", "story", "read", "book", "novel", "was", "she", "he", "they", "while",
    }
)
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']+")


def classify_paragraph_language(text: str) -> str:
    """Classify a single paragraph as 'ja', 'id', 'en', 'mixed-ja', 'mixed-latin', or 'unknown'."""
    sample = (text or "").strip()
    if not sample:
        return "unknown"
    has_cjk = contains_japanese(sample)
    tokens = [w.lower() for w in _WORD_RE.findall(sample[:4000])]
    if has_cjk:
        latin_multi = sum(1 for t in tokens if len(t) >= 2)
        return "mixed-ja" if latin_multi >= 2 else "ja"
    if not tokens:
        return "unknown"

    id_score = sum(1.2 for t in tokens if t in _ID_STOPWORDS)
    en_score = sum(1.2 for t in tokens if t in _EN_STOPWORDS)
    for t in tokens:
        if len(t) >= 5 and (
            t.endswith(("nya", "kan", "lah", "kah"))
            or t.startswith(("meny", "meng", "memb", "mend", "ber", "ter"))
        ):
            id_score += 0.7
        if len(t) >= 5 and t.endswith(("tion", "ment", "ing", "ness")):
            en_score += 0.7

    if id_score > 0 and en_score == 0:
        return "id"
    if en_score > 0 and id_score == 0:
        return "en"
    if id_score > 0 and en_score > 0:
        if id_score >= en_score * 1.8:
            return "id"
        if en_score >= id_score * 1.8:
            return "en"
        return "mixed-latin"
    return "unknown"


def detect_source_language(text: str, fallback: str = "ja") -> str:
    """Detect whether input text is Japanese ('ja'), Indonesian ('id'), or English ('en')."""
    sample = (text or "").strip()
    if not sample:
        return fallback if fallback in ALL_TARGET_LANGS else "ja"
    if contains_japanese(sample):
        return "ja"

    tokens = [w.lower() for w in _WORD_RE.findall(sample[:4000])]
    if not tokens:
        return fallback if fallback in ALL_TARGET_LANGS else "id"

    id_score = sum(1.2 for t in tokens if t in _ID_STOPWORDS)
    en_score = sum(1.2 for t in tokens if t in _EN_STOPWORDS)
    for t in tokens:
        if len(t) >= 5 and (
            t.endswith(("nya", "kan", "lah", "kah"))
            or t.startswith(("meny", "meng", "memb", "mend", "ber", "ter"))
        ):
            id_score += 0.7
        if len(t) >= 5 and t.endswith(("tion", "ment", "ing", "ness")):
            en_score += 0.7

    if id_score > en_score:
        return "id"
    if en_score > id_score:
        return "en"
    return fallback if fallback in ALL_TARGET_LANGS else "id"


def parse_mode_pair(
    mode: str,
    *,
    sample_text: str = "",
    default_source: str = "auto",
    default_target: str = "id",
) -> tuple[str, str, str]:
    """Return (requested_src, effective_src, target_lang) for any supported mode."""
    clean = (mode or "").strip().lower()
    if clean in ("id", "en", "ja"):
        req_src = default_source if default_source in ALL_SOURCE_LANGS else "auto"
        tgt = clean
    elif "-" in clean:
        left, right = clean.split("-", 1)
        if left not in ALL_SOURCE_LANGS or right not in ALL_TARGET_LANGS:
            raise InputError(f"Pasangan bahasa tidak didukung: {mode!r}")
        if left != "auto" and left == right:
            raise InputError(f"Bahasa sumber dan tujuan harus berbeda: {mode!r}")
        req_src, tgt = left, right
    else:
        if not clean:
            req_src = default_source if default_source in ALL_SOURCE_LANGS else "auto"
            tgt = default_target if default_target in ALL_TARGET_LANGS else "id"
        else:
            raise InputError(f"Mode bahasa tidak dikenal: {mode!r}")

    if req_src == "auto":
        fallback = "ja" if tgt != "ja" else "id"
        eff_src = detect_source_language(sample_text, fallback=fallback)
    else:
        eff_src = req_src

    return req_src, eff_src, tgt


def _build_glossary_replacements(
    entries: Sequence[GlossaryEntry], src_lang: str, tgt_lang: str
) -> list[tuple[str, str]]:
    """Build longest-first (source_term -> target_term) pairs from user glossary entries."""
    pairs: list[tuple[str, str]] = []
    for e in entries:
        if e.source == "builtin":
            continue
        id_form = e.render_id or e.romaji or e.surface
        en_form = e.render_en or e.romaji or e.surface
        ja_form = e.surface

        if src_lang == "ja":
            src_terms = [e.surface, *e.aliases]
        elif src_lang == "id":
            src_terms = [id_form, e.romaji, *e.aliases]
        else:
            src_terms = [en_form, e.romaji, *e.aliases]

        tgt_term = ja_form if tgt_lang == "ja" else (id_form if tgt_lang == "id" else en_form)
        for st in src_terms:
            clean_st = (st or "").strip()
            if len(clean_st) >= 2 and tgt_term.strip():
                pairs.append((clean_st, tgt_term.strip()))

    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def _mask_with_glossary(
    text: str, pairs: Sequence[tuple[str, str]]
) -> tuple[str, dict[str, str]]:
    masked = text
    token_map: dict[str, str] = {}
    idx = 1
    for src_term, tgt_term in pairs:
        if src_term in masked:
            tok = f"[[E{idx}]]"
            masked = masked.replace(src_term, tok)
            token_map[tok] = tgt_term
            idx += 1
    return masked, token_map


def _unmask_tokens(text: str, token_map: Mapping[str, str]) -> str:  # type: ignore[name-defined]
    out = text
    for tok, val in token_map.items():
        out = out.replace(tok, val)
        # Also tolerate spacing mutations like [[ E1 ]] from free MT engines
        num = tok[3:-2]
        out = re.sub(rf"\[\[\s*E\s*{re.escape(num)}\s*\]\]", val, out, flags=re.I)
    return out


from collections.abc import Mapping  # noqa: E402


def translate_multilingual_paragraphs(
    *,
    paragraphs: Sequence[Paragraph],
    src_lang: str,
    tgt_lang: str,
    settings: AppSettings,
    glossary_entries: Sequence[GlossaryEntry] = (),
    cache: LayeredTranslationCache | None = None,
    api_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    llm_transport: Any = None,
) -> tuple[list[TranslatedParagraph], str]:
    """Translate paragraphs for non-(ja->id/en) pairs using LLM (if configured) or Google GTX fallback."""
    if not paragraphs:
        return [], settings.llm_models[0]

    if src_lang == tgt_lang:
        same_out = [
            TranslatedParagraph(
                source=p,
                sentences=[SentencePair(source=p.text, target=p.text, status="ok", engine="identity")],
            )
            for p in paragraphs
        ]
        return same_out, "identity"

    # Strict target-language guarantee: paragraphs already purely in tgt_lang stay verbatim
    already_target: dict[int, str] = {}
    work_indices: list[int] = []
    for idx, p in enumerate(paragraphs):
        cls = classify_paragraph_language(p.text)
        if cls == tgt_lang:
            already_target[idx] = p.text
        else:
            work_indices.append(idx)

    if not work_indices:
        same_out = [
            TranslatedParagraph(
                source=p,
                sentences=[SentencePair(source=p.text, target=p.text, status="ok", engine="identity")],
            )
            for p in paragraphs
        ]
        return same_out, "identity"

    pairs = _build_glossary_replacements(glossary_entries, src_lang, tgt_lang)
    masked_items: list[str] = []
    maps: list[dict[str, str]] = []
    for idx in work_indices:
        m_txt, t_map = _mask_with_glossary(paragraphs[idx].text, pairs)
        masked_items.append(m_txt)
        maps.append(t_map)

    clean_key = (api_key or "").strip()
    used_engine = "google:gtx"
    raw_outputs: list[str] = []

    if clean_key or llm_transport is not None:
        model = settings.llm_models[0]
        used_engine = f"tranx_llm:{model}"
        src_label = LANG_ENGLISH_NAMES.get(src_lang, "the detected source language")
        tgt_label = LANG_ENGLISH_NAMES.get(tgt_lang, "Indonesian")
        sys_prompt = (
            f"You are an expert literary and technical translator into natural, accurate {tgt_label}. "
            f"Translate from {src_label} or any detected language into {tgt_label} without summarizing.\n"
            "Rules:\n"
            f"1. Ensure 100% of every output item is written in {tgt_label}. Keep any portion already in {tgt_label} intact and never translate it into another language.\n"
            "2. Keep placeholders such as [[E1]] or [[E2]] verbatim in their grammatically natural position.\n"
            "3. Preserve line breaks within each item.\n"
            '4. Reply ONLY with a JSON object: {"translations": [{"id": 1, "text": "..."}]} matching input ids.'
        )
        req_items = [{"id": idx + 1, "text": txt} for idx, txt in enumerate(masked_items)]
        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": "Input:\n" + json.dumps(req_items, ensure_ascii=False)},
            ],
        }
        char_count = sum(len(x) for x in masked_items)
        if usage_tracker is not None:
            usage_tracker.check_and_record(
                model=model,
                chars=char_count,
                calls=1,
                char_cap=settings.daily_char_cap,
                call_cap=settings.daily_call_cap,
            )
        if llm_transport is not None:
            resp_data = llm_transport(payload)
        else:
            endpoint = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
            raw_resp = post_json(
                endpoint,
                payload,
                headers={"Authorization": f"Bearer {clean_key}"},
                timeout=90.0,
                engine="tranx_llm",
            )
            resp_data = json.loads(raw_resp)
        content = resp_data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        by_id = {int(row["id"]): str(row["text"]) for row in parsed.get("translations", [])}
        raw_outputs = [by_id.get(i + 1, masked_items[i]) for i in range(len(masked_items))]
    else:
        g_cfg = Config(
            source_lang="ja",
            target_lang="id",
            allow_unofficial=True,
            home=runtime_home(),
        )
        g_eng = GoogleEngine(g_cfg)
        raw_outputs = g_eng.translate(masked_items, src_lang, tgt_lang)

    translated_by_idx: dict[int, str] = dict(already_target)
    for work_pos, orig_idx in enumerate(work_indices):
        translated_by_idx[orig_idx] = _unmask_tokens(raw_outputs[work_pos], maps[work_pos])

    result_paras: list[TranslatedParagraph] = []
    for idx, p in enumerate(paragraphs):
        final_dst = translated_by_idx.get(idx, p.text)
        eng_label = "identity" if idx in already_target else used_engine
        result_paras.append(
            TranslatedParagraph(
                source=p,
                sentences=[
                    SentencePair(
                        source=p.text,
                        target=final_dst,
                        status="ok",
                        engine=eng_label,
                    )
                ],
            )
        )
    return result_paras, used_engine


def translate_multilingual_document(
    *,
    doc: Document,
    src_lang: str,
    tgt_lang: str,
    settings: AppSettings,
    glossary_entries: Sequence[GlossaryEntry] = (),
    cache: LayeredTranslationCache | None = None,
    api_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    llm_transport: Any = None,
) -> tuple[TranslatedDocument, str]:
    tparas, used_model = translate_multilingual_paragraphs(
        paragraphs=doc.paragraphs,
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        settings=settings,
        glossary_entries=glossary_entries,
        cache=cache,
        api_key=api_key,
        usage_tracker=usage_tracker,
        llm_transport=llm_transport,
    )
    tdoc = TranslatedDocument(
        document=doc,
        paragraphs=tparas,
        source_lang=src_lang,
        target_lang=tgt_lang,
        glossary=list(glossary_entries),
    )
    return tdoc, used_model
