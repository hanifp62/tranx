"""Mesin MyMemory: API resmi gratis tanpa key.

Batasnya kecil: 5.000 karakter per hari tanpa identitas (50.000 bila email
dikirim lewat ``de``) dan 500 karakter per permintaan. Server menghitung
batas itu per karakter, bukan per byte seperti tertulis di dokumentasinya,
jadi pemeriksaan memakai ``len(text)``. Satu permintaan berisi satu kalimat.

Bentuk respons (dicek 2026-11-15)::

    {"responseData": {"translatedText": "...", "match": 0.85},
     "quotaFinished": false, "responseDetails": "", "responseStatus": 200, ...}

``responseStatus`` kadang berupa string (``"403"``), jadi selalu diubah ke int.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..config import Config
from ..errors import EngineError, QuotaExceeded
from ..net import get_json
from .base import env_value

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mymemory.translated.net/get"
EMAIL_ENV = "MYMEMORY_EMAIL"
QUOTA_TEXT = "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"
QUOTA_STATUSES = frozenset({403, 429})
# Status 403 juga dipakai untuk galat masukan; pesan ini BUKAN tanda kuota habis.
NON_QUOTA_DETAILS = ("QUERY LENGTH LIMIT", "INVALID", "SELECT TWO DISTINCT LANGUAGES")


class MyMemoryEngine:
    """Penerjemah lewat ``api.mymemory.translated.net``.

    Args:
        cfg: Konfigurasi program (saat ini tidak ada opsi khusus).
        email: Email opsional untuk kuota lebih besar. Bawaan dibaca dari
            ``MYMEMORY_EMAIL``; tidak pernah dikirim bila tidak diset (opt-in),
            karena email itu sampai ke pihak ketiga.
    """

    name = "mymemory"
    max_chars = 500
    max_items = 1

    def __init__(self, cfg: Config | None = None, *, email: str | None = None) -> None:
        self._email = env_value(EMAIL_ENV) if email is None else email.strip()

    def cache_tag(self) -> str:
        """Kembalikan ``"mymemory"``."""
        return self.name

    def available(self) -> tuple[bool, str]:
        """Selalu tersedia; alasan menyebut kuota harian yang berlaku."""
        if self._email:
            return True, "tanpa key, dengan email (50.000 karakter/hari)"
        return True, "tanpa key (5.000 karakter/hari; set MYMEMORY_EMAIL untuk 50.000)"

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Terjemahkan tiap teks dengan satu permintaan per teks.

        Raises:
            QuotaExceeded: Kuota harian habis.
            EngineError: Teks terlalu panjang atau respons tidak sah.
        """
        return [self._translate_one(text, src, tgt) for text in texts]

    def _translate_one(self, text: str, src: str, tgt: str) -> str:
        if len(text) > self.max_chars:
            raise EngineError(self.name, f"teks {len(text)} karakter melebihi {self.max_chars}")
        params = {"q": text, "langpair": f"{src}|{tgt}"}
        if self._email:
            params["de"] = self._email
        return parse_response(get_json(ENDPOINT, params, engine=self.name))


def parse_response(data: Any) -> str:
    """Ambil terjemahan dari respons MyMemory yang sudah diurai.

    Args:
        data: Objek JSON dari ``/get``.

    Returns:
        Teks ``responseData.translatedText``.

    Raises:
        QuotaExceeded: ``responseStatus`` 429/403 (selain galat masukan),
            ``quotaFinished`` benar, atau teks peringatan kuota muncul.
        EngineError: Status selain 200, struktur aneh, atau terjemahan kosong.
    """
    if not isinstance(data, dict):
        raise EngineError(MyMemoryEngine.name, "struktur respons tidak dikenal")
    status = _status_code(data.get("responseStatus"))
    response_data = data.get("responseData")
    translated = response_data.get("translatedText") if isinstance(response_data, dict) else None
    translated = translated if isinstance(translated, str) else ""
    details = str(data.get("responseDetails") or "")
    if _is_quota_exhausted(status, data.get("quotaFinished"), translated, details):
        raise QuotaExceeded(MyMemoryEngine.name, f"kuota harian habis (status {status})")
    if status != 200:
        raise EngineError(MyMemoryEngine.name, f"responseStatus {status}: {details[:120]}")
    if not translated.strip():
        raise EngineError(MyMemoryEngine.name, "terjemahan kosong")
    return translated


def _is_quota_exhausted(status: int, finished: object, translated: str, details: str) -> bool:
    upper_details = details.upper()
    if QUOTA_TEXT in translated.upper() or QUOTA_TEXT in upper_details or finished is True:
        return True
    if status not in QUOTA_STATUSES:
        return False
    return not any(marker in upper_details for marker in NON_QUOTA_DETAILS)


def _status_code(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0
