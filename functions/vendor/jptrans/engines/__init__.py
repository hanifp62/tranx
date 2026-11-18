"""Registri mesin penerjemah.

``build_engines`` mengubah daftar nama di config menjadi objek mesin yang
siap dipakai, dengan urutan yang sama, dan melewati mesin yang tidak
tersedia (key belum diset, endpoint tidak resmi belum diizinkan).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from ..config import Config
from ..errors import ConfigError
from .base import Engine, env_value
from .deepl import DeepLEngine
from .fake import REPLIES_ENV, FakeEngine, load_replies, replies_tag
from .google import GoogleEngine
from .libretranslate import LibreTranslateEngine
from .llm import LLMEngine
from .mymemory import MyMemoryEngine

logger = logging.getLogger(__name__)

__all__ = [
    "DeepLEngine",
    "ENGINE_FACTORIES",
    "Engine",
    "FakeEngine",
    "GoogleEngine",
    "LLMEngine",
    "LibreTranslateEngine",
    "MyMemoryEngine",
    "build_engines",
    "describe_engines",
    "normalize_engine_names",
    "register_engine",
]


def _make_fake(_cfg: Config) -> Engine:
    """``FakeEngine``; dengan ``JPTRANS_FAKE_REPLIES`` memakai jawaban berskrip dari berkas.

    Jawaban berskrip mendapat tag cache sendiri (``replies_tag``), jadi tidak tertukar
    dengan gema bawaan yang sudah ada di cache.

    Raises:
        ConfigError: Berkas jawaban tidak sah (``load_replies``).
    """
    path = env_value(REPLIES_ENV)
    if not path:
        return FakeEngine()
    replies = load_replies(path)
    return FakeEngine(translations=replies, tag=replies_tag(replies))


ENGINE_FACTORIES: dict[str, Callable[[Config], Engine]] = {
    "fake": _make_fake,
    "mymemory": MyMemoryEngine,
    "google": GoogleEngine,
    "deepl": DeepLEngine,
    "llm": LLMEngine,
    "libretranslate": LibreTranslateEngine,
}

NO_ENGINE_HINT = (
    "set DEEPL_API_KEY atau JPTRANS_LLM_API_KEY/GEMINI_API_KEY, pakai --engine mymemory, "
    "atau izinkan Google tidak resmi dengan --allow-unofficial"
)


def build_engines(cfg: Config, names: Sequence[str] | None = None) -> list[Engine]:
    """Buat daftar mesin yang tersedia sesuai urutan yang diminta.

    Args:
        cfg: Konfigurasi program.
        names: Nama mesin; ``None`` berarti ``cfg.engines``. Nama ganda dibuang.

    Returns:
        Mesin yang ``available()``-nya benar, urut sesuai ``names``.

    Raises:
        ConfigError: Ada nama tak dikenal, daftar kosong, atau tidak ada
            satu pun mesin yang tersedia.
    """
    wanted = normalize_engine_names(cfg.engines if names is None else names)
    engines = []
    for name in wanted:
        engine = ENGINE_FACTORIES[name](cfg)
        ok, reason = engine.available()
        if ok:
            logger.debug("mesin %s dipakai: %s", name, reason)
            engines.append(engine)
        else:
            logger.info("mesin %s dilewati: %s", name, reason)
    if not engines:
        raise ConfigError(f"tidak ada mesin yang tersedia ({', '.join(wanted)}); {NO_ENGINE_HINT}")
    return engines


def describe_engines(cfg: Config) -> list[tuple[str, bool, str]]:
    """Status semua mesin terdaftar, untuk perintah ``doctor``.

    Args:
        cfg: Konfigurasi program.

    Returns:
        Daftar ``(nama, tersedia, alasan)`` untuk setiap mesin di registri.
    """
    return [(name, *factory(cfg).available()) for name, factory in ENGINE_FACTORIES.items()]


def normalize_engine_names(names: Sequence[str]) -> list[str]:
    """Rapikan daftar nama mesin: tanpa spasi tepi, huruf kecil, tanpa duplikat.

    Dipakai ``build_engines``, ``pipeline.estimate`` (``--dry-run``), dan
    server agar ketiganya menerima dan menolak nama yang sama.

    Args:
        names: Nama mesin dari CLI, config, atau permintaan web.

    Returns:
        Nama terdaftar, urutan pertama dipertahankan.

    Raises:
        ConfigError: Daftar kosong atau ada nama yang tidak dikenal.
    """
    wanted = list(dict.fromkeys(name.strip().lower() for name in names if name.strip()))
    if not wanted:
        raise ConfigError("daftar mesin kosong")
    unknown = [name for name in wanted if name not in ENGINE_FACTORIES]
    if unknown:
        raise ConfigError(
            f"mesin tidak dikenal: {', '.join(unknown)}; pilihan: {', '.join(ENGINE_FACTORIES)}"
        )
    return wanted


def register_engine(name: str, factory: Callable[[Config], Engine]) -> None:
    """Daftarkan mesin penerjemah kustom ke registri global ``ENGINE_FACTORIES``."""
    clean = name.strip().lower()
    if not clean or not all(ch.isalnum() or ch in "-_" for ch in clean):
        raise ConfigError(f"nama mesin tidak sah: {name!r}")
    if not callable(factory):
        raise ConfigError(f"factory mesin {clean!r} harus dapat dipanggil")
    ENGINE_FACTORIES[clean] = factory
    logger.debug("mesin kustom terdaftar: %s", clean)
