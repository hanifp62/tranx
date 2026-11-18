"""Mesin Google Translate lewat endpoint TIDAK resmi ``translate_a/single``.

Peringatan yang juga ditampilkan di log saat mesin diaktifkan:

- Endpoint ini tidak didokumentasikan Google dan bisa berubah atau
  diblokir kapan saja (status 429 atau halaman captcha HTML).
- ``https://translate.googleapis.com/robots.txt`` berisi
  ``Disallow: /translate_a/``, dan Google Terms melarang akses otomatis
  yang melanggar instruksi semacam itu.

Karena itu mesin ini mati secara bawaan dan hanya hidup dengan
``allow_unofficial`` (``--allow-unofficial``). User-Agent tetap jujur.

Beberapa kalimat dikirim sekaligus, digabung dengan ``\\n``. Hasil dipecah
kembali per baris; bila jumlah baris berbeda, ``EngineError`` dilempar
agar pipeline mengulang per kalimat.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..config import Config
from ..errors import EngineError, EngineUnavailable
from ..net import parse_json, post_form
from .base import require_same_length

logger = logging.getLogger(__name__)

ENDPOINT = "https://translate.googleapis.com/translate_a/single"
UNOFFICIAL_NOTE = (
    "endpoint Google tidak resmi (robots.txt: Disallow: /translate_a/), bisa berhenti kapan saja"
)


class GoogleEngine:
    """Penerjemah lewat ``translate_a/single?client=gtx`` (opt-in).

    Args:
        cfg: Konfigurasi; mesin hanya hidup bila ``cfg.allow_unofficial``.
    """

    name = "google"
    max_chars = 1500
    max_items = 40

    def __init__(self, cfg: Config) -> None:
        self._allowed = cfg.allow_unofficial
        if self._allowed:
            logger.warning("google: memakai %s", UNOFFICIAL_NOTE)

    def cache_tag(self) -> str:
        """Kembalikan ``"google:gtx"``."""
        return "google:gtx"

    def available(self) -> tuple[bool, str]:
        """Tersedia hanya bila pengguna mengizinkan endpoint tidak resmi."""
        if not self._allowed:
            return False, f"{UNOFFICIAL_NOTE}; aktifkan dengan --allow-unofficial"
        return True, UNOFFICIAL_NOTE

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Terjemahkan satu batch dalam satu permintaan POST.

        Teks yang sendiri berisi baris baru (misalnya subtitle dua baris)
        tidak bisa dipecah ulang dengan aman, jadi batch seperti itu
        dikirim satu per satu.

        Raises:
            EngineUnavailable: ``allow_unofficial`` mati.
            EngineError: Respons bukan JSON, struktur aneh, atau jumlah baris beda.
        """
        if not self._allowed:
            raise EngineUnavailable(self.name, "endpoint tidak resmi belum diizinkan")
        if len(texts) > 1 and any("\n" in text for text in texts):
            logger.debug("google: batch berisi baris baru, dikirim per teks")
            return [self._request(text, src, tgt) for text in texts]
        if len(texts) == 1:
            return [self._request(texts[0], src, tgt)]
        joined = self._request("\n".join(texts), src, tgt)
        return require_same_length(self.name, texts, joined.split("\n"))

    def _request(self, text: str, src: str, tgt: str) -> str:
        fields = {"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text}
        raw = post_form(ENDPOINT, fields, engine=self.name)
        return extract_text(parse_json(raw, self.name))


def extract_text(data: Any) -> str:
    """Gabungkan segmen terjemahan dari respons gtx.

    Bentuk respons: ``[[["terjemahan", "asli", ...], ...], null, "ja", ...]``.

    Args:
        data: Objek JSON yang sudah diurai.

    Returns:
        Terjemahan utuh.

    Raises:
        EngineError: Struktur tidak sesuai atau terjemahan kosong.
    """
    try:
        pieces = [segment[0] for segment in data[0] if segment and isinstance(segment[0], str)]
    except (TypeError, IndexError, KeyError) as exc:
        raise EngineError(GoogleEngine.name, "struktur respons tidak dikenal") from exc
    text = "".join(pieces)
    if not text.strip():
        raise EngineError(GoogleEngine.name, "terjemahan kosong")
    return text
