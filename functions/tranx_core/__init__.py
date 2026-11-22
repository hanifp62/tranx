"""tranx_core: single boundary package encapsulating jptrans 1.1.0 for Cloud Functions."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parents[1] / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

from jptrans import __version__ as JPTRANS_VERSION  # noqa: E402
from jptrans.errors import (  # noqa: E402
    AllEnginesFailed,
    ConfigError,
    EngineError,
    EngineUnavailable,
    InputError,
    JptransError,
    QuotaExceeded,
)
from jptrans.readers import INPUT_FORMAT_READERS, READERS, read_document, read_text  # noqa: E402
from jptrans.readers.aozora import parse_aozora  # noqa: E402
from jptrans.writers import RENDERERS  # noqa: E402

from .cache import CacheStore, InMemoryCacheStore, LayeredTranslationCache
from .config import (
    ALLOWED_SERVER_KEY_MODELS,
    DEFAULT_MODELS,
    SUPPORTED_MODES,
    SUPPORTED_SOURCES,
    SUPPORTED_TARGETS,
    SUPPORTED_UI_LANGS,
    AppSettings,
    TitleStyle,
    chat_config,
    effective_settings_for_key_source,
    long_config,
    parse_mode_target,
)
from .multilingual import (
    ALL_MODE_PAIRS,
    detect_source_language,
    parse_mode_pair,
    translate_multilingual_document,
    translate_multilingual_paragraphs,
)
from .doc_readers import inspect_zip_archive, read_document_safely, register_custom_readers, sanitize_vtt_content
from .engines import (
    DailyCapExceeded,
    InMemoryUsageTracker,
    ThinkLLM,
    UsageTracker,
    build_engine_chain,
    register_default_tranx_engine,
)
from .export import (
    export_translated_document,
    rebuild_translated_document_from_paras,
    register_custom_writers,
    render_docx_bytes,
)
from .glossary_store import (
    GLOSSARY_ENTRY_FIELDS,
    FirestoreGlossary,
    GlossaryBackend,
    InMemoryGlossaryBackend,
    dict_to_glossary_entry,
    glossary_doc_id,
    glossary_entry_to_dict,
)
from .speech_stt import (
    GeminiSpeechTranscriber,
    SpeechTranscriber,
    transcribe_short_audio,
)
from .stream import (
    lookup_new_names_for_text,
    stream_document_chunks,
    stream_fast_chat,
)
from .verify import verify_vendor_manifest
from .vision_ocr import (
    GeminiVisionExtractor,
    RawVisionBubble,
    VisionExtractor,
    denormalize_box_to_xywh,
    inspect_image_dimensions,
    translate_image_bytes,
)
from .web_translator import (
    FetchedImage,
    FetchedPage,
    SSRFBlockedError,
    WebGateBlockedError,
    fetch_image_safely,
    fetch_url_safely,
    translate_web_page,
    validate_and_resolve_url,
)


def init_tranx_core(api_key_getter: Callable[[], str | None] = lambda: None) -> str:
    """Deferred runtime bootstrap for @init: verify manifest and register plugins."""
    manifest_hash = verify_vendor_manifest()
    register_custom_readers()
    register_custom_writers()
    register_default_tranx_engine(api_key_getter)
    return manifest_hash


def supported_formats_metadata() -> dict[str, list[str]]:
    register_custom_readers()
    register_custom_writers()
    return {
        "documentInputs": sorted(READERS.keys()),
        "documentOutputs": sorted(RENDERERS.keys()),
        "imageInputs": [".png", ".jpg", ".jpeg", ".webp"],
    }


__all__ = [
    "ALLOWED_SERVER_KEY_MODELS",
    "ALL_MODE_PAIRS",
    "AllEnginesFailed",
    "AppSettings",
    "CacheStore",
    "ConfigError",
    "DEFAULT_MODELS",
    "DailyCapExceeded",
    "EngineError",
    "EngineUnavailable",
    "FetchedImage",
    "FetchedPage",
    "FirestoreGlossary",
    "GLOSSARY_ENTRY_FIELDS",
    "GeminiSpeechTranscriber",
    "GeminiVisionExtractor",
    "GlossaryBackend",
    "INPUT_FORMAT_READERS",
    "InMemoryCacheStore",
    "InMemoryGlossaryBackend",
    "InMemoryUsageTracker",
    "InputError",
    "JPTRANS_VERSION",
    "JptransError",
    "LayeredTranslationCache",
    "QuotaExceeded",
    "READERS",
    "RENDERERS",
    "RawVisionBubble",
    "SSRFBlockedError",
    "SUPPORTED_MODES",
    "SUPPORTED_SOURCES",
    "SUPPORTED_TARGETS",
    "SUPPORTED_UI_LANGS",
    "SpeechTranscriber",
    "ThinkLLM",
    "TitleStyle",
    "UsageTracker",
    "VisionExtractor",
    "WebGateBlockedError",
    "build_engine_chain",
    "chat_config",
    "denormalize_box_to_xywh",
    "detect_source_language",
    "dict_to_glossary_entry",
    "effective_settings_for_key_source",
    "export_translated_document",
    "fetch_image_safely",
    "fetch_url_safely",
    "glossary_doc_id",
    "glossary_entry_to_dict",
    "init_tranx_core",
    "inspect_image_dimensions",
    "inspect_zip_archive",
    "long_config",
    "lookup_new_names_for_text",
    "parse_aozora",
    "parse_mode_pair",
    "parse_mode_target",
    "read_document",
    "read_document_safely",
    "read_text",
    "rebuild_translated_document_from_paras",
    "register_custom_readers",
    "register_custom_writers",
    "register_default_tranx_engine",
    "render_docx_bytes",
    "sanitize_vtt_content",
    "stream_document_chunks",
    "stream_fast_chat",
    "supported_formats_metadata",
    "transcribe_short_audio",
    "translate_image_bytes",
    "translate_multilingual_document",
    "translate_multilingual_paragraphs",
    "translate_web_page",
    "validate_and_resolve_url",
    "verify_vendor_manifest",
]
