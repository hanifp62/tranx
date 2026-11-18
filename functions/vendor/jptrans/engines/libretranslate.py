"""Mesin LibreTranslate lewat ``POST {base_url}/translate``.

Mendukung server LibreTranslate mandiri (lokal) maupun instans daring.
Alamat dibaca dari ``LIBRETRANSLATE_URL`` dan kunci opsional dari
``LIBRETRANSLATE_API_KEY``; kunci ditolak bila dikirim lewat HTTP polos
ke host selain localhost.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from ..config import Config
from ..errors import EngineError, EngineUnavailable
from ..net import post_json
from .base import env_value, lang_code, require_same_length
from .llm import LOCAL_HOSTS

logger = logging.getLogger(__name__)

URL_ENV = "LIBRETRANSLATE_URL"
KEY_ENV = "LIBRETRANSLATE_API_KEY"
LANG_CODES = {"ja": "ja", "id": "id", "en": "en"}
INSECURE_KEY_MESSAGE = (
    "LIBRETRANSLATE_URL harus https untuk mengirim API key ke server bukan lokal"
)


class LibreTranslateEngine:
    """Penerjemah LibreTranslate dengan dukungan batch daftar teks."""

    name = "libretranslate"
    max_chars = 5000
    max_items = 25

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        raw_url = env_value(URL_ENV) if base_url is None else base_url.strip()
        self.base_url = raw_url.rstrip("/")
        self._key = env_value(KEY_ENV) if api_key is None else api_key.strip()
        parts = urlsplit(self.base_url) if self.base_url else None
        self._host = (parts.hostname or "").lower() if parts else ""
        self._scheme = parts.scheme.lower() if parts else ""

    @property
    def endpoint(self) -> str:
        """URL ``/translate`` lengkap."""
        return f"{self.base_url}/translate"

    @property
    def is_local(self) -> bool:
        return self._host in LOCAL_HOSTS

    @property
    def key_exposed(self) -> bool:
        return bool(self._key) and self._scheme != "https" and not self.is_local

    def cache_tag(self) -> str:
        """Penanda cache per host LibreTranslate."""
        return f"{self.name}:{self._host or 'default'}"

    def available(self) -> tuple[bool, str]:
        """Tersedia bila ``LIBRETRANSLATE_URL`` diset dengan aman."""
        if not self.base_url:
            return False, f"{URL_ENV} belum diset"
        if self._scheme not in {"http", "https"} or not self._host:
            return False, f"{URL_ENV} tidak valid"
        if self.key_exposed:
            return False, INSECURE_KEY_MESSAGE
        return True, f"endpoint {self._host}"

    def translate(
        self,
        texts: list[str],
        src: str,
        tgt: str,
        hints: Sequence[str] = (),
    ) -> list[str]:
        """Terjemahkan daftar teks dalam satu panggilan ``/translate``."""
        ok, reason = self.available()
        if not ok:
            raise EngineUnavailable(self.name, reason)
        payload: dict[str, Any] = {
            "q": texts[0] if len(texts) == 1 else list(texts),
            "source": lang_code(self.name, LANG_CODES, src),
            "target": lang_code(self.name, LANG_CODES, tgt),
            "format": "text",
        }
        if self._key:
            payload["api_key"] = self._key
        data = post_json(self.endpoint, payload, engine=self.name)
        return require_same_length(self.name, texts, parse_response(data))


def parse_response(data: Any) -> list[str]:
    """Ambil hasil terjemahan tunggal atau daftar dari respons LibreTranslate."""
    translated = (
        data.get("translatedText") if isinstance(data, dict) else None
    )
    if isinstance(translated, str):
        return [translated]
    if isinstance(translated, list) and all(
        isinstance(item, str) for item in translated
    ):
        return list(translated)
    raise EngineError(
        LibreTranslateEngine.name,
        "respons tanpa 'translatedText' yang sah",
    )
