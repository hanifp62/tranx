"""Bidirectional & auto-detect multilingual translation (auto/id/en/ja -> id/en/ja) with glossary placeholder protection."""

from __future__ import annotations

import concurrent.futures
import contextvars
import hashlib
import json
import re
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
from .engines import DailyCapExceeded, UsageTracker
from .literary_polish import (
    DiscourseProfile,
    build_literary_system_prompt,
    build_self_repair_prompt,
    evaluate_source_target_qe,
    naturalize_paragraph,
    naturalize_paragraphs,
    profile_document,
    sanitize_zero_em_dash,
)

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
        "bisa", "dapat", "ada", "saya", "aku", "kamu", "kau", "dia", "ia", "kami", "kita",
        "mereka", "dalam", "pada", "adalah", "ialah", "sudah", "telah", "akan", "sedang",
        "atau", "karena", "sebab", "seperti", "juga", "oleh", "tentang", "lebih", "sangat",
        "hanya", "saja", "cuma", "selamat", "pagi", "malam", "siang", "sore", "terima",
        "kasih", "bagaimana", "mengapa", "kenapa", "kapan", "dimana", "apa", "siapa", "berapa",
        "tetap", "bukan", "belum", "masih", "lagi", "baru", "lama", "semua", "seluruh",
        "setiap", "ketika", "saat", "waktu", "hari", "orang", "rumah", "jalan", "cerita",
        "bab", "halaman", "buku", "baca", "membaca", "tulis", "menulis", "pergi", "datang",
        "lihat", "melihat", "kata", "berkata", "bilang", "sambil", "lalu", "kemudian",
        "setelah", "sebelum", "sampai", "hingga", "sejak", "selama", "tanpa", "antara",
        "tetapi", "tapi", "namun", "jika", "kalau", "bila", "agar", "supaya", "buat",
        "mau", "ingin", "harus", "boleh", "perlu", "pernah", "pun", "jadi", "menjadi",
        "sesuai", "berubah", "kakek", "nenek", "anak", "ibu", "ayah", "teman", "besar",
        "kecil", "baik", "buruk", "cantik", "indah", "tenang", "pelan", "cepat", "halo",
        "tolong", "maaf", "ya", "iya", "tidaklah", "disini", "disana", "sini", "sana",
    }
)
_EN_STOPWORDS = frozenset(
    {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not",
        "on", "with", "he", "as", "you", "do", "at", "this", "but", "his", "by", "from",
        "they", "we", "say", "her", "she", "or", "an", "will", "my", "one", "all", "would",
        "there", "their", "what", "so", "up", "out", "if", "about", "who", "get", "which",
        "go", "me", "when", "make", "can", "like", "time", "no", "just", "him", "know",
        "take", "into", "year", "your", "good", "some", "could", "them", "see", "other",
        "than", "then", "now", "look", "only", "come", "its", "over", "think", "also",
        "back", "after", "use", "two", "how", "our", "work", "first", "well", "way", "even",
        "new", "want", "because", "any", "these", "give", "day", "most", "us", "is", "are",
        "was", "were", "been", "has", "had", "does", "did", "more", "very", "much", "still",
        "hello", "morning", "evening", "night", "please", "thank", "thanks", "chapter",
        "episode", "next", "previous", "story", "page", "read", "reading", "book", "novel",
        "while", "under", "opened", "stood", "quietly", "listening", "rain", "letter",
    }
)
_EN_CONTRACTIONS = frozenset(
    {
        "don't", "can't", "won't", "isn't", "aren't", "it's", "i'm", "you're",
        "we're", "they're", "didn't", "wasn't", "couldn't", "wouldn't",
    }
)
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']+")


def _score_latin_words(sample: str) -> tuple[float, float, int]:
    """Score Indonesian vs English cues mirroring web/src/lib/langUtils.ts."""
    tokens = [w.lower() for w in _WORD_RE.findall(sample[:4000])]
    id_score = 0.0
    en_score = 0.0
    id_stop_hits = 0
    en_stop_hits = 0
    for t in tokens:
        if t in _ID_STOPWORDS:
            id_score += 1.2
            id_stop_hits += 1
        if t in _EN_STOPWORDS:
            en_score += 1.2
            en_stop_hits += 1
        if (
            t not in _EN_STOPWORDS
            and len(t) >= 6
            and (
                t.endswith(("nya", "kan", "lah", "kah"))
                or t.startswith(("meny", "meng", "memb", "mend", "berk", "bert", "terj", "terk", "terl", "terd"))
            )
        ):
            id_score += 0.65
        if t not in _ID_STOPWORDS and (
            (len(t) >= 5 and t.endswith(("tion", "ment", "ing", "ness")))
            or t in _EN_CONTRACTIONS
        ):
            en_score += 0.7
    if id_stop_hits == 0 and id_score < 1.5:
        id_score = 0.0
    if en_stop_hits == 0 and en_score < 1.5:
        en_score = 0.0
    return id_score, en_score, len(tokens)


def classify_paragraph_language(text: str) -> str:
    """Classify a single paragraph as 'ja', 'id', 'en', 'mixed-ja', 'mixed-latin', or 'unknown'."""
    sample = (text or "").strip()
    if not sample:
        return "unknown"
    has_cjk = contains_japanese(sample)
    if has_cjk:
        latin_multi = sum(1 for w in _WORD_RE.findall(sample[:4000]) if len(w) >= 2)
        return "mixed-ja" if latin_multi >= 2 else "ja"

    id_score, en_score, word_count = _score_latin_words(sample)
    if word_count == 0:
        return "unknown"

    if id_score >= 1.2 and en_score == 0.0 and (word_count <= 4 or id_score >= 2.0):
        return "id"
    if en_score >= 1.2 and id_score == 0.0 and (word_count <= 4 or en_score >= 2.0):
        return "en"
    if id_score > 0.0 and en_score > 0.0:
        if id_score >= 2.4 and id_score >= en_score * 2.2:
            return "id"
        if en_score >= 2.4 and en_score >= id_score * 2.2:
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

    id_score, en_score, word_count = _score_latin_words(sample)
    if word_count == 0:
        return fallback if fallback in ALL_TARGET_LANGS else "id"
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


_ASCII_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\s'-]*")
_THINK_STRIP_RE = re.compile(r"<think>[\s\S]*?</think>", re.I)
_FENCE_STRIP_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
_UNMASK_TOKEN_RE = re.compile(r"\[\[\s*E\s*(\d+)\s*\]\]", re.I)
_VALID_TONES = frozenset({"auto", "novel", "casual", "formal"})


def _compile_glossary_masker(
    pairs: Sequence[tuple[str, str]],
) -> tuple[re.Pattern[str] | None, dict[str, str]]:
    """Compile a single longest-first alternation regex for glossary masking (O(N) vs O(N*G))."""
    if not pairs:
        return None, {}
    dedup_map: dict[str, str] = {}
    branches: list[str] = []
    for src_term, tgt_term in pairs:
        if src_term in dedup_map:
            continue
        dedup_map[src_term] = tgt_term
        esc = re.escape(src_term)
        if _ASCII_TERM_RE.fullmatch(src_term):
            branches.append(rf"(?<![A-Za-z0-9_]){esc}(?![A-Za-z0-9_])")
        else:
            branches.append(esc)
    if not branches:
        return None, {}
    return re.compile("|".join(branches)), dedup_map


def _mask_with_glossary(
    text: str,
    pairs: Sequence[tuple[str, str]],
    *,
    compiled: tuple[re.Pattern[str] | None, dict[str, str]] | None = None,
) -> tuple[str, dict[str, str]]:
    pattern, dedup_map = compiled if compiled is not None else _compile_glossary_masker(pairs)
    if pattern is None:
        return text, {}
    term_to_tok: dict[str, str] = {}
    token_map: dict[str, str] = {}
    idx = [1]

    def _repl(m: re.Match[str]) -> str:
        matched = m.group(0)
        tok = term_to_tok.get(matched)
        if tok is None:
            tok = f"[[E{idx[0]}]]"
            idx[0] += 1
            term_to_tok[matched] = tok
            token_map[tok] = dedup_map[matched]
        return tok

    masked = pattern.sub(_repl, text)
    return masked, token_map


def _unmask_tokens(text: str, token_map: dict[str, str]) -> str:
    if not token_map or not text:
        return text
    by_num = {tok[3:-2]: val for tok, val in token_map.items()}
    return _UNMASK_TOKEN_RE.sub(lambda m: by_num.get(m.group(1), m.group(0)), text)


def _call_llm_json_chat(
    *,
    model: str,
    temperature: float,
    sys_prompt: str,
    user_content: str,
    settings: AppSettings,
    clean_key: str,
    usage_tracker: UsageTracker | None,
    llm_transport: Any,
    char_count: int,
    skip_usage_record: bool = False,
) -> dict[int, str]:
    """Call an OpenAI-compatible/Gemini chat completion endpoint with a single usage charge outside HTTP-400 format fallback."""
    if usage_tracker is not None and not skip_usage_record:
        usage_tracker.check_and_record(
            model=model,
            chars=char_count,
            calls=1,
            char_cap=settings.daily_char_cap,
            call_cap=settings.daily_call_cap,
        )
    last_exc: Exception | None = None
    for use_json_fmt in (True, False):
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        if use_json_fmt:
            payload["response_format"] = {"type": "json_object"}
        try:
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
                resp_data = json.loads(raw_resp) if isinstance(raw_resp, (str, bytes, bytearray)) else raw_resp
            if not isinstance(resp_data, dict):
                raise ValueError("LLM response payload is not a JSON object")
            content = str(resp_data["choices"][0]["message"]["content"] or "")
            cleaned_json = _THINK_STRIP_RE.sub("", content).strip()
            fence_match = _FENCE_STRIP_RE.search(cleaned_json)
            if fence_match:
                cleaned_json = fence_match.group(1).strip()
            parsed = json.loads(cleaned_json)
            return {
                int(row["id"]): str(row["text"])
                for row in parsed.get("translations", [])
                if isinstance(row, dict) and "id" in row and "text" in row and str(row["text"]).strip()
            }
        except Exception as exc:
            if isinstance(exc, DailyCapExceeded):
                raise
            last_exc = exc
            if use_json_fmt and "400" in str(exc):
                continue
            break
    if last_exc is not None:
        raise last_exc
    return {}


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
    doc_format: str | None = None,
    title_kind: str | None = None,
    profile: DiscourseProfile | None = None,
    tone_override: str = "auto",
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

    # Strict target-language guarantee: paragraphs clearly already purely in tgt_lang stay verbatim
    already_target: dict[int, str] = {}
    work_indices: list[int] = []
    for idx, p in enumerate(paragraphs):
        cls = classify_paragraph_language(p.text)
        # Only skip when paragraph unmistakably matches tgt_lang (avoid false skip on short explicit-source fragments)
        if cls == tgt_lang and (src_lang == "auto" or len(p.text.strip()) >= 12 or cls == "ja"):
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

    clean_tone = tone_override if tone_override in _VALID_TONES else "auto"
    active_profile = profile or profile_document(
        [p.text for p in paragraphs],
        src_lang,
        tgt_lang,
        tone_override=clean_tone,
        doc_format=doc_format,
        title_kind=title_kind,
    )
    pairs = _build_glossary_replacements(glossary_entries, src_lang, tgt_lang)
    compiled_masker = _compile_glossary_masker(pairs)
    glossary_values = tuple(v for _, v in pairs)
    masked_items: list[str] = []
    maps: list[dict[str, str]] = []
    for idx in work_indices:
        m_txt, t_map = _mask_with_glossary(paragraphs[idx].text, pairs, compiled=compiled_masker)
        masked_items.append(m_txt)
        maps.append(t_map)

    clean_key = (api_key or "").strip()
    models_to_try = list(settings.llm_models) or ["gemini-2.5-flash-lite"]
    primary_model = models_to_try[0] if (clean_key or llm_transport is not None) else "google:gtx"
    used_engine = "google:gtx"
    llm_engine_used = ""
    had_llm_outputs = False
    raw_outputs: list[str] = [""] * len(masked_items)
    cache_ns = f"ml:{src_lang}:{tgt_lang}:{primary_model}:{active_profile.genre}:{active_profile.register}:{clean_tone}:v5.1"

    def _ml_cache_key(txt: str) -> str:
        return hashlib.sha256(f"{cache_ns}|{txt}".encode("utf-8")).hexdigest()

    item_keys = [_ml_cache_key(m_txt) for m_txt in masked_items]
    cached_hits = cache.get_many(item_keys) if cache is not None else {}
    uncached_positions: list[int] = []
    for pos, key in enumerate(item_keys):
        hit = cached_hits.get(key)
        if hit:
            raw_outputs[pos] = hit
        else:
            uncached_positions.append(pos)

    if not uncached_positions:
        used_engine = "cache"
    else:
        # Chunk uncached paragraphs into bounded batches (max 25 items / 4500 chars)
        batches: list[list[int]] = []
        cur_batch: list[int] = []
        cur_chars = 0
        for pos in uncached_positions:
            item_len = len(masked_items[pos])
            if cur_batch and (len(cur_batch) >= 25 or cur_chars + item_len > 4500):
                batches.append(cur_batch)
                cur_batch = []
                cur_chars = 0
            cur_batch.append(pos)
            cur_chars += item_len
        if cur_batch:
            batches.append(cur_batch)

        llm_ok = False
        if clean_key or llm_transport is not None:
            src_label = LANG_ENGLISH_NAMES.get(src_lang, "the detected source language")
            tgt_label = LANG_ENGLISH_NAMES.get(tgt_lang, "Indonesian")
            sys_prompt = build_literary_system_prompt(src_label, tgt_label, active_profile)
            temp = 0.15 if active_profile.register in ("formal_academic", "formal_legal_tech") else 0.25

            # Pre-reserve aggregate quota once before parallel fan-out to avoid Firestore usage/{day} txn contention
            pre_reserved = False
            if usage_tracker is not None and len(batches) > 1:
                total_batch_chars = sum(len(masked_items[p]) for b in batches for p in b)
                usage_tracker.check_and_record(
                    model=models_to_try[0],
                    chars=total_batch_chars,
                    calls=len(batches),
                    char_cap=settings.daily_char_cap,
                    call_cap=settings.daily_call_cap,
                )
                pre_reserved = True

            def _run_llm_batch(batch_positions: list[int]) -> tuple[bool, str, list[tuple[int, str]], list[tuple[str, str, str, str, str]]]:
                batch_texts = [masked_items[p] for p in batch_positions]
                req_items = [{"id": i + 1, "text": txt} for i, txt in enumerate(batch_texts)]
                char_count = sum(len(x) for x in batch_texts)
                user_content = "Input:\n" + json.dumps(req_items, ensure_ascii=False)
                for m_idx, model in enumerate(models_to_try):
                    try:
                        by_id = _call_llm_json_chat(
                            model=model,
                            temperature=temp,
                            sys_prompt=sys_prompt,
                            user_content=user_content,
                            settings=settings,
                            clean_key=clean_key,
                            usage_tracker=usage_tracker,
                            llm_transport=llm_transport,
                            char_count=char_count,
                            skip_usage_record=(pre_reserved and m_idx == 0),
                        )
                        if not by_id:
                            continue
                        assigned: list[tuple[int, str]] = []
                        cache_rows: list[tuple[str, str, str, str, str]] = []
                        all_present = True
                        for idx_in_batch, pos in enumerate(batch_positions):
                            out_val = by_id.get(idx_in_batch + 1)
                            if out_val:
                                assigned.append((pos, out_val))
                                if cache is not None:
                                    cache_rows.append((item_keys[pos], f"tranx_llm:{model}", src_lang, tgt_lang, out_val))
                            else:
                                all_present = False
                        return all_present, f"tranx_llm:{model}", assigned, cache_rows
                    except DailyCapExceeded:
                        raise
                    except Exception:
                        continue
                return False, "", [], []

            batch_results: list[tuple[bool, str, list[tuple[int, str]], list[tuple[str, str, str, str, str]]]] = []
            if len(batches) > 1 and llm_transport is None:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(batches))) as pool:
                    futs = [pool.submit(contextvars.copy_context().run, _run_llm_batch, b) for b in batches]
                    for fut in futs:
                        batch_results.append(fut.result())
            else:
                for b in batches:
                    batch_results.append(_run_llm_batch(b))

            all_batches_ok = True
            all_cache_rows: list[tuple[str, str, str, str, str]] = []
            for b_ok, b_eng, assigned, c_rows in batch_results:
                for pos, out_val in assigned:
                    raw_outputs[pos] = out_val
                    had_llm_outputs = True
                all_cache_rows.extend(c_rows)
                if b_eng:
                    used_engine = b_eng
                    llm_engine_used = b_eng
                if not b_ok:
                    all_batches_ok = False
            if cache is not None and all_cache_rows:
                cache.put_many(all_cache_rows)
            llm_ok = all_batches_ok

        if not llm_ok:
            g_cfg = Config(
                source_lang="ja",
                target_lang="id",
                allow_unofficial=True,
                home=runtime_home(),
            )
            g_eng = GoogleEngine(g_cfg)
            missing_pos = [pos for pos in uncached_positions if not raw_outputs[pos]]
            if missing_pos:
                g_out = g_eng.translate([masked_items[p] for p in missing_pos], src_lang, tgt_lang)
                cache_rows_g: list[tuple[str, str, str, str, str]] = []
                for idx_g, pos in enumerate(missing_pos):
                    candidate_g = g_out[idx_g] if idx_g < len(g_out) else ""
                    if candidate_g and candidate_g.strip():
                        raw_outputs[pos] = candidate_g
                        if cache is not None and candidate_g.strip() != masked_items[pos].strip():
                            cache_rows_g.append((item_keys[pos], "google:gtx", src_lang, tgt_lang, candidate_g))
                if cache is not None and cache_rows_g:
                    cache.put_many(cache_rows_g)
                if not had_llm_outputs:
                    used_engine = "google:gtx"

    translated_by_idx: dict[int, str] = dict(already_target)
    work_srcs = [paragraphs[orig_idx].text for orig_idx in work_indices]
    work_unmasked = [
        _unmask_tokens(raw_outputs[pos] or masked_items[pos], maps[pos])
        for pos in range(len(work_indices))
    ]
    polished_work = naturalize_paragraphs(work_srcs, work_unmasked, active_profile, glossary_values=glossary_values)

    # Bounded single-pass QE self-repair when LLM is configured (mirrors TS literaryPolish v5)
    if (clean_key or llm_transport is not None) and (had_llm_outputs or used_engine.startswith("tranx_llm:")):
        repair_candidates: list[dict[str, object]] = []
        repair_positions: list[int] = []
        base_risks: dict[int, int] = {}
        for work_pos, cand_dst in enumerate(polished_work):
            qe = evaluate_source_target_qe(
                work_srcs[work_pos],
                cand_dst,
                active_profile,
                glossary_values=glossary_values,
                glossary_pairs=pairs,
            )
            if qe.get("needsSelfRepair"):
                risk_val = int(qe.get("qeRiskScore", 0))
                base_risks[work_pos] = risk_val
                defects_list = qe.get("defects") or []
                defect_summary = "; ".join(str(d.get("detail", "")) for d in defects_list[:3] if isinstance(d, dict))
                repair_positions.append(work_pos)
                repair_candidates.append(
                    {
                        "id": len(repair_positions),
                        "src": work_srcs[work_pos],
                        "draft": cand_dst,
                        "defects": defect_summary,
                    }
                )
                if len(repair_candidates) >= 6:
                    break
        if repair_candidates:
            src_label = LANG_ENGLISH_NAMES.get(src_lang, "the detected source language")
            tgt_label = LANG_ENGLISH_NAMES.get(tgt_lang, "Indonesian")
            repair_prompt = build_self_repair_prompt(src_label, tgt_label, active_profile, repair_candidates)
            repair_source = llm_engine_used or used_engine
            repair_model = repair_source.split(":", 1)[1] if ":" in repair_source else models_to_try[0]
            try:
                repaired_map = _call_llm_json_chat(
                    model=repair_model,
                    temperature=0.1,
                    sys_prompt=repair_prompt,
                    user_content="Repair the items listed in the system prompt and return JSON.",
                    settings=settings,
                    clean_key=clean_key,
                    usage_tracker=usage_tracker,
                    llm_transport=llm_transport,
                    char_count=sum(len(str(it["src"])) for it in repair_candidates),
                )
                for req_idx, work_pos in enumerate(repair_positions, start=1):
                    fixed_raw = repaired_map.get(req_idx)
                    if not fixed_raw:
                        continue
                    fixed_nat = naturalize_paragraph(
                        work_srcs[work_pos],
                        sanitize_zero_em_dash(fixed_raw, tgt_lang),
                        active_profile,
                        glossary_values=glossary_values,
                    )
                    after_qe = evaluate_source_target_qe(
                        work_srcs[work_pos],
                        fixed_nat,
                        active_profile,
                        glossary_values=glossary_values,
                        glossary_pairs=pairs,
                    )
                    if int(after_qe.get("qeRiskScore", 999)) < base_risks[work_pos]:
                        polished_work[work_pos] = fixed_nat
            except DailyCapExceeded:
                raise
            except Exception:
                pass

    for work_pos, orig_idx in enumerate(work_indices):
        translated_by_idx[orig_idx] = polished_work[work_pos]

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
    title_kind: str | None = None,
    profile: DiscourseProfile | None = None,
    tone_override: str = "auto",
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
        doc_format=doc.fmt,
        title_kind=title_kind,
        profile=profile,
        tone_override=tone_override,
    )
    tdoc = TranslatedDocument(
        document=doc,
        paragraphs=tparas,
        source_lang=src_lang,
        target_lang=tgt_lang,
        glossary=list(glossary_entries),
    )
    return tdoc, used_model
