"""Hierarki galat jptrans.

Semua galat yang sengaja dilempar program turun dari ``JptransError``.
CLI memetakan tiap jenis galat ke kode keluar yang berbeda, sehingga
skrip lain (misalnya cron atau batch) bisa membedakan "masukan salah"
dari "semua mesin penerjemah gagal".
"""

from __future__ import annotations

import logging

# Modul ini hanya mendefinisikan galat dan tidak menulis log sendiri (galat dicatat
# oleh pemanggilnya); logger tetap ada sesuai aturan proyek "satu logger per modul".
logger = logging.getLogger(__name__)

# Saran untuk Python yang sistem berkasnya bukan UTF-8 (Linux dengan locale C,
# PYTHONUTF8=0, dan PYTHONCOERCECLOCALE=0): nama berkas Jepang tidak bisa dipakai.
NON_UTF8_FS_HINT = (
    "sistem berkas Python ini tidak memakai UTF-8 sehingga nama berkas Jepang tidak "
    "bisa dipakai; jalankan dengan PYTHONUTF8=1 atau locale UTF-8 (mis. LANG=C.UTF-8)"
)


class JptransError(Exception):
    """Induk semua galat yang diketahui program ini."""

    exit_code = 1


class InputError(JptransError):
    """Berkas masukan tidak bisa dibaca: encoding, format, atau ber-DRM."""

    exit_code = 1


class ConfigError(JptransError):
    """Nilai konfigurasi atau argumen tidak valid."""

    exit_code = 2


class EngineError(JptransError):
    """Satu mesin penerjemah gagal memproses permintaan.

    Galat ini bersifat lokal: pipeline akan mencoba mesin berikutnya.
    """

    exit_code = 3

    def __init__(self, engine: str, message: str) -> None:
        super().__init__(f"[{engine}] {message}")
        self.engine = engine


class EngineUnavailable(EngineError):
    """Mesin tidak bisa dipakai sama sekali (tidak ada key, tidak diizinkan)."""


class QuotaExceeded(EngineError):
    """Kuota mesin habis. Mesin ini tidak dicoba lagi selama sesi berjalan."""


class AllEnginesFailed(JptransError):
    """Tidak ada satu pun mesin yang berhasil menerjemahkan."""

    exit_code = 3


class PlaceholderError(JptransError):
    """Penanda entitas hilang dari hasil terjemahan mesin."""

    def __init__(self, missing: list[int]) -> None:
        super().__init__(f"penanda hilang: {missing}")
        self.missing = missing
