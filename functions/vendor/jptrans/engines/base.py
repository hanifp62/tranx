"""Kontrak bersama semua mesin penerjemah dan fungsi bantu kecilnya.

Mesin hanya menerjemahkan daftar teks yang sudah dimasking. Tangga
fallback (batch, per kalimat, presubstitusi, mesin berikutnya) milik
``pipeline.py``, sehingga tiap mesin tetap kecil dan mudah diuji.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from ..errors import EngineError

logger = logging.getLogger(__name__)


@runtime_checkable
class Engine(Protocol):
    """Antarmuka yang dipenuhi setiap mesin penerjemah.

    Attributes:
        name: Nama pendek mesin (``mymemory``, ``google``, ``deepl``, ``llm``, ``fake``).
        max_chars: Batas karakter per permintaan.
        max_items: Batas kalimat per permintaan (1 berarti tanpa batching).
    """

    name: str
    max_chars: int
    max_items: int

    def cache_tag(self) -> str:
        """Penanda versi mesin yang masuk ke kunci cache."""
        ...

    def available(self) -> tuple[bool, str]:
        """Kembalikan (bisa dipakai?, alasan singkat untuk pengguna)."""
        ...

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Terjemahkan ``texts``; hasil wajib sepanjang masukan.

        Args:
            texts: Kalimat termasking.
            src: Kode bahasa sumber (``ja``).
            tgt: Kode bahasa sasaran (``id`` atau ``en``).
            hints: Baris glosarium untuk mesin yang bisa memakainya (LLM).

        Raises:
            EngineError: Permintaan gagal atau jumlah hasil tidak cocok.
        """
        ...


def require_same_length(engine: str, texts: Sequence[str], results: Sequence[str]) -> list[str]:
    """Pastikan mesin mengembalikan satu hasil untuk tiap masukan.

    Args:
        engine: Nama mesin untuk pesan galat.
        texts: Masukan yang dikirim.
        results: Hasil dari mesin.

    Returns:
        ``results`` sebagai list.

    Raises:
        EngineError: Panjang keduanya berbeda.
    """
    if len(results) != len(texts):
        raise EngineError(engine, f"mengembalikan {len(results)} hasil untuk {len(texts)} teks")
    return list(results)


def lang_code(engine: str, codes: Mapping[str, str], lang: str) -> str:
    """Terjemahkan kode bahasa jptrans ke kode milik layanan.

    Args:
        engine: Nama mesin untuk pesan galat.
        codes: Pemetaan kode jptrans ke kode layanan.
        lang: Kode jptrans (``ja``, ``id``, ``en``).

    Returns:
        Kode bahasa versi layanan.

    Raises:
        EngineError: Bahasa tidak didukung mesin ini.
    """
    try:
        return codes[lang]
    except KeyError as exc:
        raise EngineError(engine, f"bahasa {lang!r} tidak didukung") from exc


def env_value(*names: str) -> str:
    """Ambil nilai environment variable pertama yang tidak kosong.

    Key dibaca langsung dari environment, tidak pernah dari berkas config.

    Args:
        *names: Nama variabel, urut prioritas.

    Returns:
        Nilai tanpa spasi tepi, atau string kosong.
    """
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""
