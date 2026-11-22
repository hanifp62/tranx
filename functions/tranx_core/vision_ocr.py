"""Mode Gambar: Gemini Vision structured OCR -> pixel [x, y, w, h] -> jptrans parse_pages + translate_document."""

from __future__ import annotations

import base64
import io
import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from jptrans.errors import EngineError, InputError
from jptrans.pipeline import Translator
from jptrans.readers.pages import parse_pages
from PIL import Image, ImageOps, PngImagePlugin

from .cache import LayeredTranslationCache
from .config import AppSettings, TitleStyle, long_config
from .engines import DailyCapExceeded, UsageTracker, build_engine_chain
from .glossary_store import FirestoreGlossary, glossary_entry_to_dict
from .literary_polish import sanitize_zero_em_dash
from .multilingual import parse_mode_pair, translate_multilingual_document

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_IMAGE_WIDTH = 8192
MAX_IMAGE_HEIGHT = 65536
MAX_IMAGE_PIXELS = 36_000_000
MAX_IMAGE_FRAMES = 1
ALLOWED_IMAGE_FORMATS = ("PNG", "JPEG", "WEBP", "GIF")
_VALID_KINDS = frozenset({"dialogue", "thought", "shout", "narration", "sfx", "status_window", "caption", "aside", "sign"})
_VALID_SHAPES = frozenset({"oval", "rect", "jagged", "cloud", "unbordered"})
_VALID_BG_TONES = frozenset({"light", "dark", "artwork", "colored"})
_VALID_WRITING_DIRS = frozenset({"vertical", "horizontal"})
_VALID_SFX_IMPORTANCE = frozenset({"none", "ambient", "impact", "narrative", "major", "minor", "plot_critical"})
_THINK_TAG_RE = re.compile(r"<think>[\s\S]*?</think>", re.I)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)

# Configure Pillow global anti-bomb ceilings once at module import (thread-safe under concurrency=20)
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
PngImagePlugin.MAX_TEXT_CHUNK = 64 * 1024
PngImagePlugin.MAX_TEXT_MEMORY = 256 * 1024

VISION_SYSTEM_PROMPT = (
    "Extract ALL visible text blocks, comic/manga speech bubbles, RPG status windows, and major SFX "
    "in natural reading order (right-to-left, top-to-bottom for manga; vertical top-to-bottom for webtoons; "
    "left-to-right for Western comics/UI). Ignore tiny Japanese furigana beside kanji. "
    'Return strict JSON: {"bubbles": [{"id": 1, "box_2d": [ymin, xmin, ymax, xmax], "text": "...", '
    '"kind": "dialogue|thought|shout|narration|sfx|status_window|caption|aside", '
    '"shape": "oval|rect|jagged|cloud|unbordered", "bgTone": "light|dark|colored", '
    '"writingDir": "vertical|horizontal", "sfxImportance": "plot_critical|ambient"}]} '
    "where coordinates are integers normalized 0..1000. Omit empty blocks."
)


@dataclass(frozen=True)
class RawVisionBubble:
    id: int
    box_2d: tuple[float, float, float, float]  # (ymin, xmin, ymax, xmax) in 0..1000
    text: str
    kind: str | None = None
    shape: str | None = None
    bg_tone: str | None = None
    writing_dir: str | None = None
    sfx_importance: str | None = None


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


def _box_iou_xywh(a: Sequence[int], b: Sequence[int]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax1 + aw, bx1 + bw)
    iy2 = min(ay1 + ah, by1 + bh)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return float(inter) / float(union) if union > 0 else 0.0


def _nms_and_xy_cut_bubbles(
    items: list[tuple[list[int], RawVisionBubble]],
    width: int,
    height: int,
    *,
    is_rtl: bool,
) -> list[tuple[list[int], RawVisionBubble]]:
    """Deduplicate overlapping Vision detections (IoU >= 0.55) and sort via recursive XY-Cut."""
    if len(items) <= 1:
        return items

    kept: list[tuple[list[int], RawVisionBubble]] = []
    for xywh, raw in items:
        merged = False
        for i, (ex_box, ex_raw) in enumerate(kept):
            if _box_iou_xywh(ex_box, xywh) >= 0.55:
                if len(raw.text) > len(ex_raw.text):
                    kept[i] = (xywh, raw)
                merged = True
                break
        if not merged:
            kept.append((xywh, raw))

    def _xy_cut(group: list[tuple[list[int], RawVisionBubble]], depth: int) -> list[tuple[list[int], RawVisionBubble]]:
        if len(group) <= 1:
            return group
        if depth < 6:
            # Horizontal gutter split (panel rows)
            by_y = sorted(group, key=lambda it: it[0][1])
            best_y_gap = 0
            best_y_idx = -1
            run_max_y = by_y[0][0][1] + by_y[0][0][3]
            for idx in range(1, len(by_y)):
                gap = by_y[idx][0][1] - run_max_y
                if gap > best_y_gap:
                    best_y_gap = gap
                    best_y_idx = idx
                run_max_y = max(run_max_y, by_y[idx][0][1] + by_y[idx][0][3])
            if best_y_idx > 0 and best_y_gap >= max(12, int(height * 0.012)):
                return _xy_cut(by_y[:best_y_idx], depth + 1) + _xy_cut(by_y[best_y_idx:], depth + 1)

            # Vertical gutter split (panel columns)
            by_x = sorted(group, key=lambda it: it[0][0])
            best_x_gap = 0
            best_x_idx = -1
            run_max_x = by_x[0][0][0] + by_x[0][0][2]
            for idx in range(1, len(by_x)):
                gap = by_x[idx][0][0] - run_max_x
                if gap > best_x_gap:
                    best_x_gap = gap
                    best_x_idx = idx
                run_max_x = max(run_max_x, by_x[idx][0][0] + by_x[idx][0][2])
            if best_x_idx > 0 and best_x_gap >= max(12, int(width * 0.014)):
                left_part = _xy_cut(by_x[:best_x_idx], depth + 1)
                right_part = _xy_cut(by_x[best_x_idx:], depth + 1)
                return (right_part + left_part) if is_rtl else (left_part + right_part)

        band_h = max(60, int(height * 0.16))
        return sorted(
            group,
            key=lambda it: (
                int((it[0][1] + it[0][3] / 2) // band_h),
                -(it[0][0] + it[0][2] / 2) if is_rtl else (it[0][0] + it[0][2] / 2),
            ),
        )

    return _xy_cut(kept, 0)


def _sample_outer_halo_bg(
    img_rgb: Image.Image | None,
    box: Sequence[int],
    *,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    px_access: Any = None,
) -> tuple[str, list[int]] | None:
    if img_rgb is None or len(box) != 4:
        return None
    w, h = img_rgb.size
    if w <= 0 or h <= 0:
        return None
    bx = round(box[0] * scale_x)
    by = round(box[1] * scale_y)
    bw = max(1, round(box[2] * scale_x))
    bh = max(1, round(box[3] * scale_y))
    margin = max(2, min(8, round(min(bw, bh) * 0.14)))
    sx = max(0, min(w - 1, bx - margin))
    sy = max(0, min(h - 1, by - margin))
    ex = max(sx, min(w - 1, bx + bw + margin))
    ey = max(sy, min(h - 1, by + bh + margin))
    step_x = max(1, (ex - sx) // 14)
    step_y = max(1, (ey - sy) // 14)
    pixels = px_access if px_access is not None else img_rgb.load()
    rs: list[int] = []
    gs: list[int] = []
    bs: list[int] = []
    for x in range(sx, ex + 1, step_x):
        for y in (sy, ey):
            r, g, b = pixels[x, y]
            rs.append(r)
            gs.append(g)
            bs.append(b)
    for y in range(sy + step_y, ey, step_y):
        for x in (sx, ex):
            r, g, b = pixels[x, y]
            rs.append(r)
            gs.append(g)
            bs.append(b)
    if len(rs) < 6:
        return None
    rs.sort()
    gs.sort()
    bs.sort()
    mr, mg, mb = rs[len(rs) // 2], gs[len(gs) // 2], bs[len(bs) // 2]
    lum = 0.2126 * mr + 0.7152 * mg + 0.0722 * mb
    spread = max(mr, mg, mb) - min(mr, mg, mb)
    tone = "dark" if lum < 92 else ("colored" if spread > 28 else "light")
    return tone, [int(mr), int(mg), int(mb)]


def _inspect_and_normalize_image(image_bytes: bytes) -> tuple[int, int, str, bytes]:
    """Validate image bytes and normalize EXIF orientation (2..8) so Vision boxes align 1:1."""
    if not image_bytes:
        raise InputError("Berkas gambar kosong")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise InputError("Ukuran gambar melebihi batas 20 MB")
    try:
        with Image.open(io.BytesIO(image_bytes), formats=ALLOWED_IMAGE_FORMATS) as img:
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise InputError(
                    f"Format gambar {fmt or 'tidak dikenal'} belum didukung; gunakan PNG, JPG, WEBP, atau GIF"
                )
            n_frames = int(getattr(img, "n_frames", 1) or 1)
            if n_frames > MAX_IMAGE_FRAMES:
                raise InputError("Gambar animasi multi-frame belum didukung")
            exif_orient = img.getexif().get(274, 1) if hasattr(img, "getexif") else 1
            width, height = img.size
            if exif_orient in (5, 6, 7, 8):
                width, height = height, width
            if width <= 0 or height <= 0:
                raise InputError("Dimensi gambar tidak sah")
            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT or (width * height) > MAX_IMAGE_PIXELS:
                raise InputError("Resolusi gambar melampaui batas aman 36 megapiksel (lebar maks 8192 px, tinggi maks 65536 px)")
            ocr_bytes = image_bytes
            out_fmt = fmt
            if exif_orient in (2, 3, 4, 5, 6, 7, 8):
                # Bound working copy <= 4096px / 16 MP before exif_transpose to avoid peak RAM spikes on 36 MP uploads
                work_img: Image.Image = img
                if max(img.size) > 4096 or (img.size[0] * img.size[1]) > 16_000_000:
                    scale_lim = min(
                        4096.0 / max(img.size),
                        math.sqrt(16_000_000.0 / max(1, img.size[0] * img.size[1])),
                    )
                    work_img = img.copy()
                    work_img.thumbnail(
                        (max(1, int(img.size[0] * scale_lim)), max(1, int(img.size[1] * scale_lim))),
                        Image.Resampling.LANCZOS,
                    )
                transposed = ImageOps.exif_transpose(work_img)
                try:
                    width, height = transposed.size
                    buf = io.BytesIO()
                    if fmt == "JPEG":
                        transposed.convert("RGB").save(buf, format="JPEG", quality=92)
                    else:
                        transposed.save(buf, format="PNG")
                        out_fmt = "PNG"
                    ocr_bytes = buf.getvalue()
                finally:
                    if transposed is not work_img:
                        transposed.close()
                    if work_img is not img:
                        work_img.close()
    except InputError:
        raise
    except Image.DecompressionBombError as exc:
        raise InputError("Resolusi gambar melampaui batas aman 36 megapiksel") from exc
    except Exception as exc:
        raise InputError("Berkas gambar rusak atau tidak dapat dibaca") from exc
    mime = "image/jpeg" if out_fmt == "JPEG" else f"image/{out_fmt.lower()}"
    return width, height, mime, ocr_bytes


def inspect_image_dimensions(image_bytes: bytes) -> tuple[int, int, str]:
    width, height, mime, _ = _inspect_and_normalize_image(image_bytes)
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
                        {"text": "Detect all visible comic/manga text boxes, speech bubbles, captions, status windows, and SFX."},
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
            parts = raw_resp["candidates"][0]["content"]["parts"]
            text_part = ""
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str) and part["text"].strip():
                        text_part = part["text"]
                        break
            cleaned_part = _THINK_TAG_RE.sub("", text_part).strip()
            fence_match = _JSON_FENCE_RE.search(cleaned_part)
            if fence_match:
                cleaned_part = fence_match.group(1).strip()
            parsed = json.loads(cleaned_part)
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
            try:
                coords = tuple(float(v) for v in box)
                if not all(math.isfinite(c) for c in coords):
                    continue
                raw_id = item.get("id")
                bubble_id = int(raw_id) if raw_id is not None else idx
            except (TypeError, ValueError):
                continue
            raw_kind = item.get("kind")
            raw_shape = item.get("shape")
            raw_bg = item.get("bgTone")
            raw_dir = item.get("writingDir")
            raw_sfx = item.get("sfxImportance")
            bubbles.append(
                RawVisionBubble(
                    id=bubble_id,
                    box_2d=(coords[0], coords[1], coords[2], coords[3]),
                    text=txt,
                    kind=raw_kind if isinstance(raw_kind, str) and raw_kind in _VALID_KINDS else None,
                    shape=raw_shape if isinstance(raw_shape, str) and raw_shape in _VALID_SHAPES else None,
                    bg_tone=raw_bg if isinstance(raw_bg, str) and raw_bg in _VALID_BG_TONES else None,
                    writing_dir=raw_dir if isinstance(raw_dir, str) and raw_dir in _VALID_WRITING_DIRS else None,
                    sfx_importance=raw_sfx if isinstance(raw_sfx, str) and raw_sfx in _VALID_SFX_IMPORTANCE else None,
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
    width, height, mime, ocr_bytes = _inspect_and_normalize_image(image_bytes)
    models_to_try = list(settings.llm_models) or ["gemini-2.5-flash-lite"]
    vision_model = models_to_try[0]
    raw_bubbles: list[RawVisionBubble] = []
    last_err: Exception | None = None
    for candidate_model in models_to_try:
        if usage_tracker is not None:
            usage_tracker.check_and_record(
                model=candidate_model,
                chars=500,
                calls=1,
                char_cap=settings.daily_char_cap,
                call_cap=settings.daily_call_cap,
            )
        try:
            raw_bubbles = extractor.extract_bubbles(ocr_bytes, mime, candidate_model)
            vision_model = candidate_model
            last_err = None
            break
        except DailyCapExceeded:
            raise
        except EngineError as exc:
            last_err = exc
            continue
    if last_err is not None:
        raise last_err
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

    sample_src_pre = "\n".join(b.text for b in raw_bubbles[:5])
    _, eff_src, target_lang = parse_mode_pair(
        mode,
        sample_text=sample_src_pre,
        default_source=settings.default_source,
        default_target=settings.default_target,
    )

    paired_raw = [(denormalize_box_to_xywh(b.box_2d, width, height), b) for b in raw_bubbles]
    ordered_pairs = _nms_and_xy_cut_bubbles(paired_raw, width, height, is_rtl=(eff_src == "ja"))

    pages_bubbles: list[dict[str, Any]] = []
    raw_by_pos: dict[int, RawVisionBubble] = {}
    for pos, (xywh, b) in enumerate(ordered_pairs, start=1):
        pages_bubbles.append({"id": pos, "text": b.text, "box": xywh})
        raw_by_pos[pos] = b

    pages_data = {
        "title": title_name,
        "pages": [{"page": 1, "image": "upload", "bubbles": pages_bubbles}],
    }
    doc = parse_pages(pages_data, title_name)

    if eff_src == "ja" and target_lang in ("id", "en"):
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
    else:
        result, _ = translate_multilingual_document(
            doc=doc,
            src_lang=eff_src,
            tgt_lang=target_lang,
            settings=settings,
            glossary_entries=glossary.non_builtin_entries(),
            cache=cache,
            api_key=api_key,
            usage_tracker=usage_tracker,
            llm_transport=llm_transport,
            title_kind="komik",
        )

    needs_halo = any(
        (raw_by_pos.get(int(tp.source.meta.get("bubble", i))) is None)
        or not raw_by_pos[int(tp.source.meta.get("bubble", i))].bg_tone
        for i, tp in enumerate(result.paragraphs, start=1)
    )
    img_rgb: Image.Image | None = None
    halo_px: Any = None
    halo_sx = 1.0
    halo_sy = 1.0
    if needs_halo:
        try:
            with Image.open(io.BytesIO(ocr_bytes), formats=ALLOWED_IMAGE_FORMATS) as raw_im:
                raw_im.thumbnail((1600, 1600))
                img_rgb = raw_im.convert("RGB")
                halo_px = img_rgb.load()
                if width > 0 and height > 0:
                    halo_sx = img_rgb.size[0] / float(width)
                    halo_sy = img_rgb.size[1] / float(height)
        except Exception:
            img_rgb = None
            halo_px = None

    blocks_out: list[dict[str, Any]] = []
    for idx, tpara in enumerate(result.paragraphs, start=1):
        box = tpara.source.meta.get("box") or [0, 0, width, height]
        bubble_id = int(tpara.source.meta.get("bubble", idx))
        raw_src = raw_by_pos.get(bubble_id)
        box_ints = [int(v) for v in box]
        dst_clean = sanitize_zero_em_dash(tpara.target or tpara.source.text, target_lang)
        blk_dict: dict[str, Any] = {
            "id": bubble_id,
            "box": box_ints,
            "src": tpara.source.text,
            "dst": dst_clean,
        }
        if raw_src is not None:
            if raw_src.kind:
                blk_dict["kind"] = raw_src.kind
            if raw_src.shape:
                blk_dict["shape"] = raw_src.shape
            if raw_src.bg_tone:
                blk_dict["bgTone"] = raw_src.bg_tone
            if raw_src.writing_dir:
                blk_dict["writingDir"] = raw_src.writing_dir
            if raw_src.sfx_importance:
                blk_dict["sfxImportance"] = raw_src.sfx_importance
        if "bgTone" not in blk_dict:
            halo = _sample_outer_halo_bg(
                img_rgb,
                box_ints,
                scale_x=halo_sx,
                scale_y=halo_sy,
                px_access=halo_px,
            )
            if halo is not None:
                blk_dict["bgTone"] = halo[0]
                blk_dict["bgRgb"] = halo[1]
        blocks_out.append(blk_dict)
    if img_rgb is not None:
        img_rgb.close()

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
