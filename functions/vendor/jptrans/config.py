"""Konfigurasi program dan pemuat variabel lingkungan ``.env``.

Urutan prioritas nilai: argumen CLI > variabel lingkungan proses > berkas ``.env``
> berkas ``config.json`` > nilai bawaan dataclass. Kunci API tidak pernah
disimpan di objek ``Config`` atau ditulis ke disk; mesin membacanya langsung
dari ``os.environ``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .textnorm import decode_unicode_text

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1
LANGS = ("id", "en")
HONORIFIC_STYLES = ("keep", "localize", "drop")
NAME_ORDERS = ("jp", "western")
ROMANIZATIONS = ("macron", "kana", "plain")
UNKNOWN_READING = ("keep", "engine")
FOREIGN_NAMES = ("auto", "dict", "hepburn")
OUTPUT_FORMATS = ("html", "txt", "md", "json", "srt", "vtt", "ass")
REGISTERED_OUTPUT_FORMATS: list[str] = list(OUTPUT_FORMATS)
DEFAULT_ENGINES = ("deepl", "llm", "google", "mymemory")
DEFAULT_LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_LLM_MODEL = "gemini-2.5-flash"

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_SUFFIXES = (
    "_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
)


def effective_name_order(name_order: str | None, lang: str) -> str:
    """Urutan nama efektif: pilihan eksplisit, atau ``jp`` (ID) / ``western`` (EN)."""
    if name_order:
        return name_order
    return "jp" if lang == "id" else "western"


def default_home() -> Path:
    """Folder data jptrans: ``$JPTRANS_HOME`` atau ``~/.jptrans``."""
    env = os.environ.get("JPTRANS_HOME")
    return Path(env).expanduser() if env else Path.home() / ".jptrans"


def load_dotenv(dotenv_path: Path | None = None, *, override: bool = False) -> int:
    """Muat berkas ``.env`` secara aman tanpa ``eval`` ke ``os.environ``.

    Baris kosong, komentar ``#``, serta kunci tidak sah dilewati. Tanda kutip
    tunggal atau ganda yang berpasangan di tepi nilai dikupas. Secara bawaan
    variabel lingkungan yang sudah ada di shell tidak ditimpa (``override=False``).

    Returns:
        Jumlah variabel baru yang berhasil dimasukkan ke ``os.environ``.
    """
    paths = (
        [dotenv_path]
        if dotenv_path is not None
        else [Path.cwd() / ".env", default_home() / ".env"]
    )
    loaded = 0
    for candidate in paths:
        if not candidate.is_file():
            continue
        try:
            content = decode_unicode_text(candidate.read_bytes())
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("berkas .env %s dilewati: %s", candidate, exc)
            continue
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, value = line.split("=", 1)
            key = key.strip()
            if not _ENV_KEY_RE.match(key):
                continue
            cleaned = _strip_env_quotes(value.strip())
            if override or key not in os.environ:
                os.environ[key] = cleaned
                loaded += 1
    return loaded


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] in ("'", '"'):
        quote_ch = value[0]
        end = value.find(quote_ch, 1)
        if end >= 1:
            rest = value[end + 1:].strip()
            if not rest or rest.startswith("#"):
                return value[1:end]
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    return value


@dataclass
class Config:
    """Semua pengaturan yang memengaruhi proses dan hasil terjemahan."""

    source_lang: str = "ja"
    target_lang: str = "id"
    honorific_style: str = "keep"
    name_order: str | None = None
    romanization: str = "macron"
    unknown_reading: str = "engine"
    foreign_names: str = "auto"
    first_gloss: bool = True
    engines: list[str] = field(default_factory=lambda: list(DEFAULT_ENGINES))
    allow_unofficial: bool = False
    auto_detect: bool = True
    auto_lock_threshold: float = 0.6
    candidate_threshold: float = 0.35
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    request_delay: float = 1.0
    output_format: str = "html"
    home: Path = field(default_factory=default_home)
    config_version: int = CONFIG_VERSION

    def __post_init__(self) -> None:
        self.home = Path(self.home).expanduser()
        self.validate()

    @property
    def cache_path(self) -> Path:
        """Lokasi berkas cache sqlite3."""
        return self.home / "cache.sqlite3"

    @property
    def glossary_dir(self) -> Path:
        """Folder glosarium per judul."""
        return self.home / "glossaries"

    def validate(self) -> None:
        """Periksa tipe, rentang, dan pilihan semua field; lempar ``ConfigError``."""
        _choice("target_lang", self.target_lang, LANGS)
        _choice("honorific_style", self.honorific_style, HONORIFIC_STYLES)
        if self.name_order is not None:
            _choice("name_order", self.name_order, NAME_ORDERS)
        _choice("romanization", self.romanization, ROMANIZATIONS)
        _choice("unknown_reading", self.unknown_reading, UNKNOWN_READING)
        _choice("foreign_names", self.foreign_names, FOREIGN_NAMES)
        _choice(
            "output_format",
            self.output_format,
            tuple(REGISTERED_OUTPUT_FORMATS),
        )
        for flag in ("first_gloss", "allow_unofficial", "auto_detect"):
            _boolean(flag, getattr(self, flag))
        for text_field in ("llm_base_url", "llm_model"):
            val = getattr(self, text_field)
            if not isinstance(val, str) or not val.strip():
                raise ConfigError(f"{text_field} harus string tidak kosong")
        if self.source_lang != "ja":
            raise ConfigError("source_lang saat ini hanya mendukung 'ja'")
        if not isinstance(self.engines, list) or not all(
            isinstance(name, str) for name in self.engines
        ):
            raise ConfigError(
                'engines harus daftar nama mesin, mis. ["deepl", "mymemory"]'
            )
        if not self.engines:
            raise ConfigError("daftar engines tidak boleh kosong")
        for name in (
            "auto_lock_threshold",
            "candidate_threshold",
            "request_delay",
        ):
            _number(name, getattr(self, name))
        for name in ("auto_lock_threshold", "candidate_threshold"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ConfigError(
                    f"{name} harus di antara 0 dan 1, bukan {value}"
                )
        if self.candidate_threshold > self.auto_lock_threshold:
            raise ConfigError(
                "candidate_threshold tidak boleh melebihi auto_lock_threshold"
            )
        if self.request_delay < 0:
            raise ConfigError("request_delay tidak boleh negatif")


def _boolean(name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise ConfigError(
            f"{name} harus boolean (true/false), bukan {value!r}"
        )


def _number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} harus angka, bukan {value!r}")


def _choice(name: str, value: object, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ConfigError(
            f"{name}={value!r} tidak valid; pilihan: {', '.join(allowed)}"
        )


_ENV_MAP = {
    "JPTRANS_TARGET": "target_lang",
    "JPTRANS_ENGINES": "engines",
    "JPTRANS_LLM_BASE_URL": "llm_base_url",
    "JPTRANS_LLM_MODEL": "llm_model",
    "JPTRANS_ALLOW_UNOFFICIAL": "allow_unofficial",
}


def load_config(
    path: Path | None = None, overrides: dict[str, Any] | None = None
) -> Config:
    """Muat konfigurasi dengan urutan prioritas default < file < .env < env < CLI."""
    load_dotenv()
    values: dict[str, Any] = {}
    file_path = path or default_home() / "config.json"
    if file_path.is_file():
        values.update(_read_config_file(file_path))
    elif path is not None:
        raise ConfigError(f"berkas config tidak ditemukan: {path}")

    for env_name, key in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw:
            values[key] = _parse_env(key, raw)

    for key, value in (overrides or {}).items():
        if value is not None:
            values[key] = value

    known = {f.name for f in fields(Config)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ConfigError(f"kunci config tidak dikenal: {', '.join(unknown)}")
    try:
        return Config(**values)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"config tidak valid: {exc}") from exc


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(decode_unicode_text(path.read_bytes()))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"tidak bisa membaca {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} harus berisi objek JSON")
    secrets = [
        k for k in data if k.lower().endswith(_SECRET_SUFFIXES)
    ]
    if secrets:
        raise ConfigError(
            f"{path} memuat rahasia ({', '.join(secrets)}); "
            "simpan kunci di variabel lingkungan atau .env"
        )
    logger.debug("config dimuat dari %s", path)
    return data


def _parse_env(key: str, raw: str) -> Any:
    if key == "engines":
        return [name.strip() for name in raw.split(",") if name.strip()]
    if key == "allow_unofficial":
        lowered = raw.strip().lower()
        if lowered in {"1", "true", "yes", "ya"}:
            return True
        if lowered in {"0", "false", "no", "tidak"}:
            return False
        raise ConfigError(
            f"JPTRANS_ALLOW_UNOFFICIAL={raw!r} harus true/false atau 1/0"
        )
    return raw
