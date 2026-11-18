"""Speech-to-text fallback using Gemini Audio Flash-Lite for browsers lacking Web Speech API."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Protocol

from jptrans.errors import EngineError, InputError

from .config import AppSettings
from .engines import UsageTracker

MAX_AUDIO_BYTES = 4 * 1024 * 1024  # 4 MB
ALLOWED_AUDIO_MIMES = frozenset(
    {
        "audio/webm",
        "audio/mp4",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/ogg",
    }
)


class SpeechTranscriber(Protocol):
    def transcribe(self, audio_bytes: bytes, mime_type: str, lang: str, model: str) -> str: ...


class GeminiSpeechTranscriber:
    def __init__(
        self,
        api_key: str,
        *,
        api_root: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key.strip()
        self._api_root = api_root.rstrip("/")
        self._timeout = timeout

    def transcribe(self, audio_bytes: bytes, mime_type: str, lang: str, model: str) -> str:
        if not self._api_key:
            raise EngineError("speech", "LLM_KEY belum dikonfigurasi")
        clean_model = model.removeprefix("models/")
        url = f"{self._api_root}/models/{clean_model}:generateContent"
        lang_hint = "Japanese (日本語)" if lang.startswith("ja") else lang
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64.b64encode(audio_bytes).decode("ascii"),
                            }
                        },
                        {
                            "text": (
                                f"Transcribe the spoken audio accurately in {lang_hint}. "
                                "Return only the raw transcription text without commentary."
                            )
                        },
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.0},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise EngineError("speech", f"Gemini Audio HTTP {exc.code}") from exc
        except Exception as exc:
            raise EngineError("speech", f"Gagal mentranskripsi suara: {exc}") from exc

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return str(text).strip()
        except Exception as exc:
            raise EngineError("speech", "Respons transkripsi suara kosong") from exc


def transcribe_short_audio(
    *,
    audio_bytes: bytes,
    mime_type: str,
    lang: str,
    settings: AppSettings,
    transcriber: SpeechTranscriber,
    usage_tracker: UsageTracker | None = None,
) -> dict[str, str | int]:
    if not audio_bytes:
        raise InputError("Klip suara kosong")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise InputError("Ukuran klip suara melebihi batas 4 MB")

    base_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if base_mime not in ALLOWED_AUDIO_MIMES:
        raise InputError(f"Format audio {base_mime!r} tidak didukung")

    started = time.monotonic()
    model = settings.llm_models[0]
    if usage_tracker is not None:
        usage_tracker.check_and_record(
            model=model,
            chars=300,
            calls=1,
            char_cap=settings.daily_char_cap,
            call_cap=settings.daily_call_cap,
        )
    text = transcriber.transcribe(audio_bytes, base_mime, lang or "ja-JP", model)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    return {"text": text, "lang": lang or "ja-JP", "ms": elapsed_ms}
