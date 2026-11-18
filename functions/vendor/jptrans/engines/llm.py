"""Mesin LLM lewat endpoint OpenAI-compatible ``{base_url}/chat/completions``.

Satu kelas melayani Gemini, Groq, OpenRouter, OpenAI, dan Ollama; kunci API
dipilih otomatis berdasarkan host agar kunci satu penyedia tidak terkirim ke
penyedia lain, dan server lokal boleh berjalan tanpa kunci API.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from ..config import DEFAULT_LLM_MODEL, Config
from ..errors import EngineError, EngineUnavailable
from ..net import http_status, post_json
from .base import env_value, lang_code

logger = logging.getLogger(__name__)

PROMPT_VERSION = "p1"
KEY_ENV = "JPTRANS_LLM_API_KEY"
PROVIDER_KEY_ENVS = {
    "generativelanguage.googleapis.com": "GEMINI_API_KEY",
    "api.groq.com": "GROQ_API_KEY",
    "openrouter.ai": "OPENROUTER_API_KEY",
    "api.openai.com": "OPENAI_API_KEY",
}
PROVIDER_DEFAULT_MODELS = {
    "generativelanguage.googleapis.com": "gemini-2.5-flash",
    "api.groq.com": "llama-3.3-70b-versatile",
    "openrouter.ai": "google/gemini-2.5-flash",
    "api.openai.com": "gpt-4o-mini",
}
LOCAL_DEFAULT_MODEL = "qwen2.5:7b"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
LANG_NAMES = {"ja": "Japanese", "id": "Indonesian", "en": "English"}
TIMEOUT = 90.0
JSON_RESPONSE_FORMAT = {"type": "json_object"}
INSECURE_KEY_MESSAGE = (
    "llm_base_url harus https untuk mengirim API key ke server bukan lokal"
)

SYSTEM_PROMPT = """\
You translate Japanese novels, manga and documents into {target}, in the style \
of a careful fansub or subtitle team: natural, faithful to tone and register, \
never summarised.
Rules:
1. Tokens such as [[E1]] or [[E2]] stand for protected names and terms. Copy \
every token exactly as written, once each. Never translate, explain, reorder \
inside, or drop a token.
2. Honorifics and titles are already inside the tokens, so do not add words \
like Mr., Tuan, Pak or -san around them. The glossary only tells you what \
each token refers to.
3. Translate every input item on its own. Do not merge, split, add or remove \
items, and keep line breaks inside an item.
4. Reply with one JSON object and nothing else: \
{{"translations": [{{"id": 1, "text": "..."}}]}} using exactly the input ids."""

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", re.DOTALL | re.IGNORECASE
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


def resolve_model_for_host(model: str, host: str) -> str:
    """Pilih model bawaan yang cocok dengan ``host`` bila pengguna memakai bawaan."""
    if model != DEFAULT_LLM_MODEL:
        return model
    if host in LOCAL_HOSTS:
        return LOCAL_DEFAULT_MODEL
    return PROVIDER_DEFAULT_MODELS.get(host, model)


class LLMEngine:
    """Penerjemah berbasis LLM dengan glosarium terstruktur di prompt."""

    name = "llm"
    max_chars = 4000
    max_items = 25
    uses_hints = True

    def __init__(self, cfg: Config, *, api_key: str | None = None) -> None:
        self.base_url = cfg.llm_base_url.rstrip("/")
        parts = urlsplit(self.base_url)
        self._host = (parts.hostname or "").lower()
        self._scheme = parts.scheme.lower()
        self.model = resolve_model_for_host(cfg.llm_model, self._host)
        self._key = (
            find_api_key(self._host) if api_key is None else api_key.strip()
        )

    @property
    def endpoint(self) -> str:
        """URL ``chat/completions`` lengkap."""
        return f"{self.base_url}/chat/completions"

    @property
    def is_local(self) -> bool:
        """``True`` bila server berjalan di komputer lokal (mis. Ollama)."""
        return self._host in LOCAL_HOSTS

    def cache_tag(self) -> str:
        """Kembalikan penanda unik ``llm:<host>:<model>:<versi prompt>``."""
        host_tag = self._host or "default"
        return f"{self.name}:{host_tag}:{self.model}:{PROMPT_VERSION}"

    @property
    def key_exposed(self) -> bool:
        """``True`` bila kunci akan terkirim tanpa TLS ke server bukan lokal."""
        return bool(self._key) and self._scheme != "https" and not self.is_local

    def available(self) -> tuple[bool, str]:
        """Tersedia bila ada kunci API yang cocok (lewat HTTPS), atau server lokal."""
        if self.key_exposed:
            return False, INSECURE_KEY_MESSAGE
        if self._key or self.is_local:
            return True, f"model {self.model} di {self._host or self.base_url}"
        provider_env = PROVIDER_KEY_ENVS.get(self._host)
        hint = f"{KEY_ENV} atau {provider_env}" if provider_env else KEY_ENV
        return False, f"{hint} belum diset untuk {self._host or self.base_url}"

    def translate(
        self,
        texts: list[str],
        src: str,
        tgt: str,
        hints: Sequence[str] = (),
    ) -> list[str]:
        """Terjemahkan satu batch kalimat dalam satu panggilan chat."""
        if self.key_exposed:
            raise EngineUnavailable(self.name, INSECURE_KEY_MESSAGE)
        if not (self._key or self.is_local):
            raise EngineUnavailable(self.name, f"{KEY_ENV} belum diset")
        payload = build_payload(self.model, texts, src, tgt, hints)
        try:
            data = self._post(payload)
        except EngineError as exc:
            if http_status(exc) != 400:
                raise
            logger.info(
                "llm: server menolak response_format (400), diulang tanpa field itu"
            )
            fallback = {
                key: value
                for key, value in payload.items()
                if key != "response_format"
            }
            try:
                data = self._post(fallback)
            except EngineError as retry_exc:
                if http_status(retry_exc) == 400:
                    raise EngineUnavailable(
                        self.name, str(retry_exc)
                    ) from retry_exc
                raise
        return parse_translations(message_content(data), len(texts))

    def _post(self, payload: dict[str, Any]) -> Any:
        headers = (
            {"Authorization": f"Bearer {self._key}"} if self._key else {}
        )
        return post_json(
            self.endpoint,
            payload,
            headers=headers,
            timeout=TIMEOUT,
            engine=self.name,
        )


def find_api_key(host: str) -> str:
    """Cari kunci API LLM di environment yang cocok dengan ``host``."""
    provider_env = PROVIDER_KEY_ENVS.get(host)
    return (
        env_value(KEY_ENV, provider_env)
        if provider_env
        else env_value(KEY_ENV)
    )


def sanitize_hint_line(line: str) -> str:
    """Bersihkan karakter kontrol dari baris petunjuk glosarium untuk LLM."""
    return _CONTROL_CHARS_RE.sub(" ", line).strip()[:240]


def build_payload(
    model: str,
    texts: Sequence[str],
    src: str,
    tgt: str,
    hints: Sequence[str] = (),
) -> dict[str, Any]:
    """Susun badan permintaan JSON ``chat/completions``."""
    lang_code(LLMEngine.name, LANG_NAMES, src)
    target = lang_code(LLMEngine.name, LANG_NAMES, tgt)
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(target=target)},
            {"role": "user", "content": build_user_message(texts, hints)},
        ],
        "response_format": JSON_RESPONSE_FORMAT,
    }


def build_user_message(
    texts: Sequence[str], hints: Sequence[str] = ()
) -> str:
    """Bentuk pesan pengguna berisi glosarium tersanitasi dan masukan JSON."""
    items = [
        {"id": index, "text": text} for index, text in enumerate(texts, start=1)
    ]
    parts: list[str] = []
    clean_hints = [
        cleaned for h in hints if (cleaned := sanitize_hint_line(h))
    ]
    if clean_hints:
        parts.append("Glossary:\n" + "\n".join(clean_hints))
    parts.append("Input:\n" + json.dumps(items, ensure_ascii=False))
    return "\n\n".join(parts)


def message_content(data: Any) -> str:
    """Ambil teks pesan asisten pertama dari respons ``chat/completions``."""
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (TypeError, KeyError, IndexError) as exc:
        raise EngineError(
            LLMEngine.name, "respons tanpa choices[0].message"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        raise EngineError(
            LLMEngine.name, f"jawaban kosong (finish_reason={reason})"
        )
    return content


def parse_translations(content: str, expected: int) -> list[str]:
    """Urai dan validasi jawaban JSON model terhadap jumlah masukan."""
    cleaned = _extract_json_text(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise EngineError(
            LLMEngine.name, f"jawaban bukan JSON ({len(content)} karakter)"
        ) from exc
    items = data.get("translations") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise EngineError(
            LLMEngine.name, "jawaban tanpa daftar 'translations'"
        )
    by_id: dict[int, str] = {}
    for item in items:
        item_id, text = _parse_item(item)
        if item_id in by_id:
            raise EngineError(LLMEngine.name, f"id {item_id} muncul dua kali")
        by_id[item_id] = text
    wanted = set(range(1, expected + 1))
    missing = sorted(wanted - by_id.keys())
    extra = sorted(by_id.keys() - wanted)
    if missing or extra:
        raise EngineError(
            LLMEngine.name, f"id tidak cocok: hilang {missing}, asing {extra}"
        )
    return [by_id[index] for index in range(1, expected + 1)]


def _parse_item(item: object) -> tuple[int, str]:
    if not isinstance(item, dict):
        raise EngineError(LLMEngine.name, "butir jawaban bukan objek")
    raw_id, text = item.get("id"), item.get("text")
    if isinstance(raw_id, str) and raw_id.strip().isdigit():
        raw_id = int(raw_id)
    if (
        isinstance(raw_id, bool)
        or not isinstance(raw_id, int)
        or not isinstance(text, str)
    ):
        raise EngineError(
            LLMEngine.name,
            "butir jawaban butuh 'id' bilangan dan 'text' string",
        )
    return raw_id, text


def _extract_json_text(content: str) -> str:
    stripped = _THINK_RE.sub("", content).strip()
    fence = _FENCE_RE.search(stripped)
    if fence is not None:
        return fence.group(1).strip()
    if stripped.startswith(("{", "[")):
        return stripped
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        return stripped[first_brace:last_brace + 1]
    return stripped
