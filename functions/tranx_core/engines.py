"""Custom ThinkLLM engine wrapping jptrans.engines.llm.LLMEngine with 5,000-char batches, model fallback, and WIB daily cost guard."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
import threading
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from jptrans.config import Config
from jptrans.engines import Engine, register_engine
from jptrans.engines.llm import (
    LLMEngine,
    build_payload,
    message_content,
    parse_translations,
)
from jptrans.errors import EngineError, EngineUnavailable, QuotaExceeded
from jptrans.net import http_status

from .config import AppSettings
from .literary_polish import (
    build_literary_system_prompt,
    naturalize_paragraphs,
    profile_document,
)

WIB = ZoneInfo("Asia/Jakarta")


class DailyCapExceeded(QuotaExceeded):
    """Raised when the owner's daily WIB character or call brake is reached."""

    def __init__(
        self,
        *,
        chars_used: int,
        char_cap: int,
        calls_used: int,
        call_cap: int,
    ) -> None:
        super().__init__(
            "tranx_llm",
            f"DAILY_CAP_REACHED ({chars_used}/{char_cap} chars, {calls_used}/{call_cap} calls)",
        )
        self.chars_used = chars_used
        self.char_cap = char_cap
        self.calls_used = calls_used
        self.call_cap = call_cap


class UsageTracker(Protocol):
    def check_and_record(
        self,
        *,
        model: str,
        chars: int,
        calls: int,
        char_cap: int,
        call_cap: int,
    ) -> None: ...


class InMemoryUsageTracker:
    """Thread-safe WIB daily counter for tests and emulator mode."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_day: dict[str, dict[str, Any]] = {}

    @staticmethod
    def today_key(now: datetime | None = None) -> str:
        current = (now or datetime.now(WIB)).astimezone(WIB)
        return current.strftime("%Y%m%d")

    def snapshot(self, day_key: str | None = None) -> dict[str, Any]:
        key = day_key or self.today_key()
        with self._lock:
            entry = self.by_day.get(key, {"chars": 0, "calls": 0, "byModel": {}})
            return {
                "day": key,
                "chars": int(entry["chars"]),
                "calls": int(entry["calls"]),
                "byModel": dict(entry["byModel"]),
            }

    def check_and_record(
        self,
        *,
        model: str,
        chars: int,
        calls: int,
        char_cap: int,
        call_cap: int,
    ) -> None:
        key = self.today_key()
        with self._lock:
            bucket = self.by_day.setdefault(key, {"chars": 0, "calls": 0, "byModel": {}})
            next_chars = int(bucket["chars"]) + max(chars, 0)
            next_calls = int(bucket["calls"]) + max(calls, 0)
            if next_chars > char_cap or next_calls > call_cap:
                raise DailyCapExceeded(
                    chars_used=int(bucket["chars"]),
                    char_cap=char_cap,
                    calls_used=int(bucket["calls"]),
                    call_cap=call_cap,
                )
            bucket["chars"] = next_chars
            bucket["calls"] = next_calls
            by_model = bucket["byModel"].setdefault(model, {"chars": 0, "calls": 0})
            by_model["chars"] += max(chars, 0)
            by_model["calls"] += max(calls, 0)


class ThinkLLM(LLMEngine):
    """LLMEngine subclass raising batch ceiling to 5,000 chars and adding reasoning_effort + daily cap."""

    name = "tranx_llm"
    max_chars = 5000
    max_items = 250
    uses_hints = True

    def __init__(
        self,
        cfg: Config,
        *,
        api_key: str | None = None,
        engine_name: str = "tranx_llm",
        reasoning_effort: str | None = None,
        usage_tracker: UsageTracker | None = None,
        char_cap: int = 300000,
        call_cap: int = 2000,
        transport: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        super().__init__(cfg, api_key=api_key)
        self.name = engine_name
        self.reasoning_effort = (reasoning_effort or "").strip() or None
        self._usage_tracker = usage_tracker
        self._char_cap = char_cap
        self._call_cap = call_cap
        self._transport = transport
        self.call_count = 0
        self.chars_sent = 0

    def cache_tag(self) -> str:
        base = f"{super().cache_tag()}:v5discourse"
        if self.reasoning_effort:
            return f"{base}:re={self.reasoning_effort}"
        return base

    def _post(self, payload: dict[str, Any]) -> Any:
        if self._transport is not None:
            return self._transport(payload)
        return super()._post(payload)

    def translate(
        self,
        texts: list[str],
        src: str,
        tgt: str,
        hints: Sequence[str] = (),
    ) -> list[str]:
        if self.key_exposed:
            raise EngineUnavailable(self.name, "API key requires HTTPS")
        if not (self._key or self.is_local or self._transport is not None):
            raise EngineUnavailable(self.name, "LLM_KEY belum dikonfigurasi")

        batch_chars = sum(len(t) for t in texts)
        if self._usage_tracker is not None:
            self._usage_tracker.check_and_record(
                model=self.model,
                chars=batch_chars,
                calls=1,
                char_cap=self._char_cap,
                call_cap=self._call_cap,
            )

        payload = build_payload(self.model, texts, src, tgt, hints)
        profile = profile_document(texts, src, tgt)
        if payload.get("messages") and isinstance(payload["messages"], list):
            src_label = {"ja": "Japanese", "id": "Indonesian", "en": "English"}.get(src, src)
            tgt_label = {"ja": "Japanese", "id": "Indonesian", "en": "English"}.get(tgt, tgt)
            base_sys = str(payload["messages"][0].get("content") or "").strip()
            lit_prompt = build_literary_system_prompt(src_label, tgt_label, profile)
            # Preserve jptrans strict 1-to-1 item cardinality & baked [[E#]] honorific rules alongside literary craft
            payload["messages"][0]["content"] = (
                f"{base_sys}\n\nLiterary Craft Guidance (preserve exact 1-to-1 item count and existing [[E#]] tokens without adding duplicate honorifics):\n{lit_prompt}"
                if base_sys
                else lit_prompt
            )
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        self.call_count += 1
        self.chars_sent += batch_chars

        try:
            data = self._post(payload)
        except EngineError as exc:
            if http_status(exc) != 400:
                raise
            # Strip unsupported optional fields on HTTP 400 and retry once
            fallback = {
                k: v
                for k, v in payload.items()
                if k not in ("response_format", "reasoning_effort")
            }
            try:
                data = self._post(fallback)
            except EngineError as retry_exc:
                if http_status(retry_exc) == 400:
                    raise EngineUnavailable(self.name, str(retry_exc)) from retry_exc
                raise

        raw_list = parse_translations(message_content(data), len(texts))
        hint_targets: list[str] = []
        for h in hints:
            s = str(h or "").strip()
            for sep in ("->", "=>", "="):
                if sep in s:
                    rhs = s.split(sep, 1)[1].strip().strip("\"'")
                    if len(rhs) >= 2:
                        hint_targets.append(rhs)
                    break
        glossary_vals = tuple(dict.fromkeys(hint_targets))
        return naturalize_paragraphs(texts, raw_list, profile, glossary_values=glossary_vals)


def build_engine_chain(
    cfg: Config,
    settings: AppSettings,
    *,
    api_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    transport: Callable[[dict[str, Any]], Any] | None = None,
) -> list[Engine]:
    """Create ordered ThinkLLM fallback instances matching settings.llm_models."""
    chain: list[Engine] = []
    for idx, model_name in enumerate(settings.llm_models):
        model_cfg = replace(cfg, llm_model=model_name)
        effort = settings.reasoning_effort.get(model_name)
        engine_label = "tranx_llm" if idx == 0 else f"tranx_llm_{idx + 1}"
        chain.append(
            ThinkLLM(
                model_cfg,
                api_key=api_key,
                engine_name=engine_label,
                reasoning_effort=effort,
                usage_tracker=usage_tracker,
                char_cap=settings.daily_char_cap,
                call_cap=settings.daily_call_cap,
                transport=transport,
            )
        )
    return chain


def register_default_tranx_engine(api_key_getter: Callable[[], str | None]) -> None:
    """Register 'tranx_llm' in jptrans global engine registry during @init."""

    def _factory(cfg: Config) -> Engine:
        return ThinkLLM(cfg, api_key=api_key_getter())

    register_engine("tranx_llm", _factory)
