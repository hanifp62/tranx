"""jptrans: pustaka & SDK penerjemah dokumen Jepang bergaya subtitle.

Menyediakan API tingkat tinggi siap pakai untuk integrasi aplikasi desktop, web,
mobile, maupun backend:
- ``translate_text``: terjemahkan string Jepang secara instan.
- ``translate_file``: baca berkas dokumen/subtitle/EPUB, terjemahkan, dan tulis.
- ``create_translator``: buat objek ``Translator`` berstatus (glosarium + cache).
- ``register_engine`` / ``register_reader`` / ``register_writer``: titik ekstensi plugin.
- ``unpack_package``: ekstrak bundel satu berkas menjadi paket ``src/jptrans/``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

__version__ = "1.1.0"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

from .cache import TranslationCache  # noqa: E402
from .config import Config, load_config, load_dotenv  # noqa: E402
from .engines import Engine, build_engines, register_engine  # noqa: E402
from .errors import (  # noqa: E402
    AllEnginesFailed,
    ConfigError,
    EngineError,
    EngineUnavailable,
    InputError,
    JptransError,
    PlaceholderError,
    QuotaExceeded,
)
from .glossary import Glossary, default_glossary_path  # noqa: E402
from .models import (  # noqa: E402
    Candidate,
    Document,
    GlossaryEntry,
    Paragraph,
    SentencePair,
    TranslatedDocument,
    TranslatedParagraph,
)
from .ner import detect_entities  # noqa: E402
from .pipeline import Progress, Translator  # noqa: E402
from .readers import read_document, read_text, register_reader  # noqa: E402
from .writers import render_output, register_writer, write_output  # noqa: E402


def create_translator(
    cfg: Config | None = None,
    *,
    title: str = "teks",
    engines: Sequence[str] | None = None,
    cache: TranslationCache | None = None,
    use_cache: bool = True,
    glossary: Glossary | None = None,
    glossary_path: Path | None = None,
    progress: Callable[[Progress], None] | None = None,
) -> Translator:
    """Bangun instance ``Translator`` siap pakai (mendukung ``with create_translator(...)``)."""
    resolved_cfg = cfg or load_config()
    if engines is not None:
        resolved_cfg = replace(resolved_cfg, engines=list(engines))
    built_engines = build_engines(resolved_cfg)
    owns_cache = cache is None
    active_cache = (
        cache
        if cache is not None
        else TranslationCache(resolved_cfg.cache_path if use_cache else None)
    )
    try:
        g_path = glossary_path or default_glossary_path(resolved_cfg, title)
        active_glossary = (
            glossary if glossary is not None else Glossary.load(g_path, title)
        )
        return Translator(
            resolved_cfg,
            built_engines,
            active_cache,
            active_glossary,
            progress=progress,
            glossary_path=g_path,
            owns_cache=owns_cache,
        )
    except BaseException:
        if owns_cache:
            active_cache.close()
        raise


def translate_text(
    text: str,
    *,
    target_lang: str | None = None,
    title: str = "teks",
    cfg: Config | None = None,
    engines: Sequence[str] | None = None,
    glossary: Glossary | None = None,
    use_cache: bool = True,
) -> TranslatedDocument:
    """Terjemahkan teks Jepang langsung dalam satu pemanggilan fungsi SDK."""
    base_cfg = cfg or load_config()
    if target_lang is not None:
        base_cfg = replace(base_cfg, target_lang=target_lang)
    with create_translator(
        base_cfg,
        title=title,
        engines=engines,
        use_cache=use_cache,
        glossary=glossary,
    ) as translator:
        return translator.translate_text(text, title=title)


def translate_file(
    path: str | Path,
    *,
    output: str | Path | None = None,
    target_lang: str | None = None,
    output_format: str | None = None,
    title: str | None = None,
    encoding: str | None = None,
    input_format: str | None = None,
    bilingual: bool = False,
    cfg: Config | None = None,
    engines: Sequence[str] | None = None,
    use_cache: bool = True,
    progress: Callable[[Progress], None] | None = None,
) -> TranslatedDocument:
    """Baca berkas masukan, terjemahkan, dan tulis ke ``output`` bila diberikan."""
    base_cfg = cfg or load_config()
    if target_lang is not None:
        base_cfg = replace(base_cfg, target_lang=target_lang)
    doc = read_document(
        Path(path), title=title, encoding=encoding, input_format=input_format
    )
    with create_translator(
        base_cfg,
        title=doc.title,
        engines=engines,
        use_cache=use_cache,
        progress=progress,
    ) as translator:
        result = translator.translate_document(doc)
    if output is not None:
        write_output(result, Path(output), output_format, bilingual=bilingual)
    return result


def unpack_package(dest_dir: str | Path, *, overwrite: bool = False) -> list[Path]:
    """Ekstrak bundel satu berkas ``translator.py`` menjadi paket ``<dest_dir>/jptrans/``."""
    loader = getattr(__spec__, "loader", None)
    extractor = getattr(loader, "ekstrak_paket", None)
    if not callable(extractor):
        raise ConfigError(
            "paket jptrans sudah berbentuk folder multi-berkas di disk"
        )
    files: list[Path] = extractor(Path(dest_dir), timpa=overwrite)
    return files


__all__ = [
    "AllEnginesFailed",
    "Candidate",
    "Config",
    "ConfigError",
    "Document",
    "Engine",
    "EngineError",
    "EngineUnavailable",
    "Glossary",
    "GlossaryEntry",
    "InputError",
    "JptransError",
    "Paragraph",
    "PlaceholderError",
    "Progress",
    "QuotaExceeded",
    "SentencePair",
    "TranslatedDocument",
    "TranslatedParagraph",
    "TranslationCache",
    "Translator",
    "__version__",
    "create_translator",
    "detect_entities",
    "load_config",
    "load_dotenv",
    "read_document",
    "read_text",
    "register_engine",
    "register_reader",
    "register_writer",
    "render_output",
    "translate_file",
    "translate_text",
    "unpack_package",
    "write_output",
]
