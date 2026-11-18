"""Mode Gambar: Gemini Vision structured OCR -> pixel [x, y, w, h] -> jptrans parse_pages + translate_document."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from jptrans.errors import EngineError, InputError
from jptrans.pipeline import Translator
from jptrans.readers.pages import parse_pages
from PIL import Image

from .cache import LayeredTranslationCache
from .config import AppSettings, TitleStyle, long_config, parse_mode_target
from .engines import UsageTracker, build_engine_chain
from .glossary_store import FirestoreGlossary, glossary_entry_to_dict

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB
ALLOWED_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

VISION_SYSTEM_PROMPT = (
    "Extract all visible Japanese text blocks/speech bubbles from the image in natural "
    "reading order (right-to-left, top-to-bottom for manga; top-to-bottom for UI/screenshots). "
    "Return strict JSON: {\"bubbles\": [{\"id\": 1, \"box_2d\": [ymin, xmin, ymax, xmax], \"text\": \"...\"}]} "
    "where coordinates are integers normalized 0..1000. Omit empty blocks."
)


@dataclass(frozen=True)
class RawVisionBubble:
    id: int
    box_2d: tuple[float, float, float, float]  # (ymin, xmin, ymax, xmax) in 0..1000
    text: str


class VisionExtractor(Protocol):
    def extract_bubbles(
        self, image_bytes: bytes, mime_type: str, model: str
    ) -> list[RawVisionBubble]: ...


def denormalize_box_to_xywh(
    box_2d: Sequence[float], width: int, height: int
) -> list[int]:
    """Convert Gemini [ymin, xmin, ymax, xmax] (0..1000) to jptrans [x, y, w, h] pixels."""
    if len(box_2d) != 4:
        raise InputError("Koordinat box_2d Vision harus memiliki 4 angka [ymin, xmin, ymax, xmax]")
    ymin, xmin, ymax, xmax = [float(v) for v in box_2d]
    if xmax < xmin:
        xmin, xmax = xmax, xmin
    if ymax < ymin:
        ymin, ymax = ymax, ymin

    x = max(0, min(width - 1, round((xmin / 1000.0) * width)))
    y = max(0, min(height - 1, round((ymin / 1000.0) * height)))
    x2 = max(x + 1, min(width, round((xmax / 1000.0) * width)))
    y2 = max(y + 1, min(height, round((ymax / 1000.0) * height)))
    return [int(x), int(y), int(x2 - x), int(y2 - y)]


def inspect_image_dimensions(image_bytes: bytes) -> tuple[int, int, str]:
    if not image_bytes:
        raise InputError("Berkas gambar kosong")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise InputError("Ukuran gambar melebihi batas 20 MB")
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise InputError(
                    f"Format gambar {fmt or 'tidak dikenal'} belum didukung; gunakan PNG, JPG, atau WEBP"
                )
            width, height = img.size
    except InputError:
        raise
    except Exception as exc:
        raise InputError("Berkas gambar rusak atau tidak dapat dibaca") from exc
    if width <= 0 or height <= 0:
        raise InputError("Dimensi gambar tidak sah")
    mime = "image/jpeg" if fmt == "JPEG" else f"image/{fmt.lower()}"
    return width, height, mime


class GeminiVisionExtractor:
    """Calls Gemini generateContent REST endpoint for structured Japanese text-box detection."""

    def __init__(
        self,
        api_key: str,
        *,
        api_root: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 45.0,
    ) -> None:
        self._api_key = api_key.strip()
        self._api_root = api_root.rstrip("/")
        self._timeout = timeout

    def extract_bubbles(
        self, image_bytes: bytes, mime_type: str, model: str
    ) -> list[RawVisionBubble]:
        if not self._api_key:
            raise EngineError("vision", "LLM_KEY belum dikonfigurasi")
        clean_model = model.removeprefix("models/")
        url = f"{self._api_root}/models/{clean_model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": VISION_SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                        {"text": "Detect all Japanese text boxes and speech bubbles."},
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
            },
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
                raw_resp = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise EngineError("vision", f"Gemini Vision HTTP {exc.code}") from exc
        except Exception as exc:
            raise EngineError("vision", f"Gagal memanggil Gemini Vision: {exc}") from exc

        try:
            text_part = raw_resp["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text_part)
        except Exception as exc:
            raise EngineError("vision", "Respons Gemini Vision bukan JSON valid") from exc

        bubbles_raw = parsed.get("bubbles") if isinstance(parsed, dict) else []
        if not isinstance(bubbles_raw, list):
            return []

        bubbles: list[RawVisionBubble] = []
        for idx, item in enumerate(bubbles_raw, start=1):
            if not isinstance(item, dict):
                continue
            txt = str(item.get("text") or "").strip()
            box = item.get("box_2d")
            if not txt or not isinstance(box, list) or len(box) != 4:
                continue
            bubbles.append(
                RawVisionBubble(
                    id=int(item.get("id") or idx),
                    box_2d=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
                    text=txt,
                )
            )
        return bubbles


def translate_image_bytes(
    *,
    image_bytes: bytes,
    mode: str,
    title_name: str,
    settings: AppSettings,
    glossary: FirestoreGlossary,
    cache: LayeredTranslationCache,
    extractor: VisionExtractor,
    style: TitleStyle | None = None,
    api_key: str | None = None,
    usage_tracker: UsageTracker | None = None,
    llm_transport: Any = None,
) -> dict[str, Any]:
    """Run Vision OCR -> pixel [x,y,w,h] -> jptrans parse_pages + translate_document."""
    width, height, mime = inspect_image_dimensions(image_bytes)
    vision_model = settings.llm_models[0]
    if usage_tracker is not None:
        usage_tracker.check_and_record(
            model=vision_model,
            chars=500,
            calls=1,
            char_cap=settings.daily_char_cap,
            call_cap=settings.daily_call_cap,
        )

    raw_bubbles = extractor.extract_bubbles(image_bytes, mime, vision_model)
    if not raw_bubbles:
        return {
            "width": width,
            "height": height,
            "blocks": [],
            "fullSrc": "",
            "fullDst": "",
            "lockedNames": [],
            "model": vision_model,
        }

    pages_bubbles: list[dict[str, Any]] = []
    for pos, b in enumerate(raw_bubbles, start=1):
        xywh = denormalize_box_to_xywh(b.box_2d, width, height)
        pages_bubbles.append({"id": pos, "text": b.text, "box": xywh})

    pages_data = {
        "title": title_name,
        "pages": [{"page": 1, "image": "upload", "bubbles": pages_bubbles}],
    }
    doc = parse_pages(pages_data, title_name)

    target_lang = parse_mode_target(mode, settings.default_target)
    cfg = long_config(settings, target_lang, style=style)
    engines = build_engine_chain(
        cfg,
        settings,
        api_key=api_key,
        usage_tracker=usage_tracker,
        transport=llm_transport,
    )
    with Translator(cfg, engines, cache, glossary) as tr:
        result = tr.translate_document(doc)

    blocks_out: list[dict[str, Any]] = []
    for idx, tpara in enumerate(result.paragraphs, start=1):
        box = tpara.source.meta.get("box") or [0, 0, width, height]
        blocks_out.append(
            {
                "id": int(tpara.source.meta.get("bubble", idx)),
                "box": [int(v) for v in box],
                "src": tpara.source.text,
                "dst": tpara.target or tpara.source.text,
            }
        )

    locked = [
        glossary_entry_to_dict(e)
        for e in glossary.non_builtin_entries()
        if e.confirmed
    ]
    return {
        "width": width,
        "height": height,
        "blocks": blocks_out,
        "fullSrc": "\n".join(b["src"] for b in blocks_out),
        "fullDst": "\n".join(b["dst"] for b in blocks_out),
        "lockedNames": locked,
        "model": vision_model,
    }
