"""Configuration builders mapping tranX settings and title styles to jptrans.Config."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VENDOR_DIR = Path(__file__).resolve().parents[1] / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

from jptrans.config import (  # noqa: E402
    DEFAULT_LLM_BASE_URL,
    HONORIFIC_STYLES,
    LANGS,
    NAME_ORDERS,
    ROMANIZATIONS,
    Config,
)

DEFAULT_MODELS: tuple[str, ...] = ("gemini-2.5-flash-lite", "gemini-2.5-flash")
SUPPORTED_MODES: tuple[str, ...] = ("ja-id", "ja-en")
SUPPORTED_UI_LANGS: tuple[str, ...] = ("id", "en")


@dataclass(frozen=True)
class TitleStyle:
    honorific_style: str = "keep"
    name_order: str | None = None
    romanization: str = "macron"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TitleStyle:
        if not raw:
            return cls()
        hon = raw.get("honorific_style", "keep")
        if hon not in HONORIFIC_STYLES:
            hon = "keep"
        order = raw.get("name_order")
        if order not in NAME_ORDERS:
            order = None
        rom = raw.get("romanization", "macron")
        if rom not in ROMANIZATIONS:
            rom = "macron"
        return cls(honorific_style=hon, name_order=order, romanization=rom)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "honorific_style": self.honorific_style,
            "name_order": self.name_order,
            "romanization": self.romanization,
        }


@dataclass
class AppSettings:
    llm_models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))
    reasoning_effort: dict[str, str] = field(default_factory=dict)
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    chat_max_chars: int = 5000
    long_max_chars: int = 60000
    max_upload_mb: int = 50
    daily_char_cap: int = 300000
    daily_call_cap: int = 2000
    default_target: str = "id"
    ui_lang: str = "id"
    theme: str = "system"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> AppSettings:
        if not raw:
            return cls()
        models = [
            str(m).strip()
            for m in (raw.get("llmModels") or DEFAULT_MODELS)
            if str(m).strip()
        ] or list(DEFAULT_MODELS)
        effort_raw = raw.get("reasoningEffort")
        effort = (
            {str(k): str(v) for k, v in effort_raw.items() if isinstance(v, str)}
            if isinstance(effort_raw, dict)
            else {}
        )
        target = str(raw.get("defaultTarget") or "id")
        if target not in LANGS:
            target = "id"
        ui_lang = str(raw.get("uiLang") or "id")
        if ui_lang not in SUPPORTED_UI_LANGS:
            ui_lang = "id"
        theme = str(raw.get("theme") or "system")
        if theme not in ("system", "light", "dark"):
            theme = "system"
        return cls(
            llm_models=models,
            reasoning_effort=effort,
            llm_base_url=str(raw.get("llmBaseUrl") or DEFAULT_LLM_BASE_URL),
            chat_max_chars=min(max(int(raw.get("chatMaxChars", 5000)), 200), 5000),
            long_max_chars=min(max(int(raw.get("longMaxChars", 60000)), 1000), 60000),
            max_upload_mb=min(max(int(raw.get("maxUploadMb", 50)), 1), 50),
            daily_char_cap=max(int(raw.get("dailyCharCap", 300000)), 1000),
            daily_call_cap=max(int(raw.get("dailyCallCap", 2000)), 10),
            default_target=target,
            ui_lang=ui_lang,
            theme=theme,
        )

    def to_firestore_dict(self) -> dict[str, Any]:
        return {
            "llmModels": list(self.llm_models),
            "reasoningEffort": dict(self.reasoning_effort),
            "chatMaxChars": self.chat_max_chars,
            "longMaxChars": self.long_max_chars,
            "maxUploadMb": self.max_upload_mb,
            "dailyCharCap": self.daily_char_cap,
            "dailyCallCap": self.daily_call_cap,
            "defaultTarget": self.default_target,
            "uiLang": self.ui_lang,
            "theme": self.theme,
        }


def parse_mode_target(mode: str, default_target: str = "id") -> str:
    clean = (mode or "").strip().lower()
    if clean in ("ja-en", "en"):
        return "en"
    if clean in ("ja-id", "id"):
        return "id"
    if default_target in LANGS:
        return default_target
    raise ValueError(f"Mode bahasa tidak didukung: {mode!r}")


def runtime_home() -> Path:
    base = Path(tempfile.gettempdir()) / "tranx-jptrans"
    base.mkdir(parents=True, exist_ok=True)
    return base


def chat_config(
    settings: AppSettings,
    target_lang: str,
    style: TitleStyle | None = None,
    engines: Sequence[str] = ("tranx_llm",),
) -> Config:
    """Fast 1-call chat config: skips inline unknown-reading LLM round-trip."""
    st = style or TitleStyle()
    return Config(
        source_lang="ja",
        target_lang=target_lang,
        honorific_style=st.honorific_style,
        name_order=st.name_order,
        romanization=st.romanization,
        unknown_reading="keep",
        foreign_names="dict",
        first_gloss=False,
        auto_detect=True,
        engines=list(engines),
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_models[0],
        request_delay=0.0,
        output_format="html",
        home=runtime_home(),
    )


def long_config(
    settings: AppSettings,
    target_lang: str,
    style: TitleStyle | None = None,
    engines: Sequence[str] = ("tranx_llm",),
    output_format: str = "html",
) -> Config:
    """Full document/image/web config with engine kanji reading resolution."""
    st = style or TitleStyle()
    return Config(
        source_lang="ja",
        target_lang=target_lang,
        honorific_style=st.honorific_style,
        name_order=st.name_order,
        romanization=st.romanization,
        unknown_reading="engine",
        foreign_names="auto",
        first_gloss=True,
        auto_detect=True,
        engines=list(engines),
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_models[0],
        request_delay=0.0,
        output_format=output_format,
        home=runtime_home(),
    )
