"""Mesin DeepL API (Free atau Pro) lewat ``POST /v2/translate``.

Key dibaca dari ``DEEPL_API_KEY``. Key berakhiran ``:fx`` milik paket Free
(500.000 karakter per bulan) dan memakai host ``api-free.deepl.com``.
Format permintaan (dicek di developers.deepl.com, 2026-11-15)::

    POST /v2/translate
    Authorization: DeepL-Auth-Key <key>
    {"text": ["...", "..."], "source_lang": "JA", "target_lang": "ID"}

    -> {"translations": [{"detected_source_language": "JA", "text": "..."}]}

Penanda ``[[E1]]`` dikirim apa adanya, sama seperti di mesin lain. Status
456 (kuota habis) dipetakan ``net.py`` menjadi ``QuotaExceeded``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..config import Config
from ..errors import EngineError, EngineUnavailable
from ..net import post_json
from .base import env_value, lang_code, require_same_length

logger = logging.getLogger(__name__)

KEY_ENV = "DEEPL_API_KEY"
FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"
SOURCE_CODES = {"ja": "JA"}
TARGET_CODES = {"id": "ID", "en": "EN-US"}


class DeepLEngine:
    """Penerjemah DeepL dengan batch hingga 50 kalimat per permintaan.

    Args:
        cfg: Konfigurasi program (saat ini tidak ada opsi khusus).
        api_key: Key eksplisit; bawaan dibaca dari ``DEEPL_API_KEY``.
    """

    name = "deepl"
    max_chars = 30000
    max_items = 50

    def __init__(self, cfg: Config | None = None, *, api_key: str | None = None) -> None:
        self._key = env_value(KEY_ENV) if api_key is None else api_key.strip()

    @property
    def endpoint(self) -> str:
        """URL ``/v2/translate`` yang sesuai jenis key."""
        return FREE_URL if self._key.endswith(":fx") else PRO_URL

    def cache_tag(self) -> str:
        """Kembalikan ``"deepl:v2"``."""
        return "deepl:v2"

    def available(self) -> tuple[bool, str]:
        """Tersedia bila ``DEEPL_API_KEY`` diset."""
        if not self._key:
            return False, f"{KEY_ENV} belum diset (daftar DeepL API Free: 500.000 karakter/bulan)"
        plan = "Free" if self._key.endswith(":fx") else "Pro"
        return True, f"key DeepL API {plan}"

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Terjemahkan satu batch dalam satu permintaan.

        Raises:
            EngineUnavailable: Key tidak ada atau ditolak.
            QuotaExceeded: Kuota bulanan habis (456).
            EngineError: Bahasa tidak didukung atau respons tidak sah.
        """
        if not self._key:
            raise EngineUnavailable(self.name, f"{KEY_ENV} belum diset")
        payload = {
            "text": list(texts),
            "source_lang": lang_code(self.name, SOURCE_CODES, src),
            "target_lang": lang_code(self.name, TARGET_CODES, tgt),
        }
        headers = {"Authorization": f"DeepL-Auth-Key {self._key}"}
        data = post_json(self.endpoint, payload, headers=headers, engine=self.name)
        return require_same_length(self.name, texts, parse_response(data))


def parse_response(data: Any) -> list[str]:
    """Ambil daftar terjemahan dari respons DeepL.

    Args:
        data: Objek JSON yang sudah diurai.

    Returns:
        Teks terjemahan, urut sesuai masukan.

    Raises:
        EngineError: Struktur ``translations`` tidak sesuai.
    """
    items = data.get("translations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise EngineError(DeepLEngine.name, "respons tanpa daftar 'translations'")
    texts = [item.get("text") if isinstance(item, dict) else None for item in items]
    if not all(isinstance(text, str) for text in texts):
        raise EngineError(DeepLEngine.name, "ada terjemahan tanpa teks")
    return texts
