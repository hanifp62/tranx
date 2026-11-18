"""Penulis subtitle SRT, WebVTT (``.vtt``), dan ASS/SSA (``.ass``) bertiming asli.

Baris panjang dipotong pada spasi di luar tag format (``<i>``, ``<font ...>``,
``{\\an8}``) berdasarkan panjang teks tampak tanpa merusak atribut tag.
"""

from __future__ import annotations

import logging
import re

from ..errors import InputError
from ..models import TranslatedDocument, TranslatedParagraph, strip_format_tags
from ..readers.subtitle import SUBTITLE_FORMATS

logger = logging.getLogger(__name__)

MAX_LINE_CHARS = 42
_INLINE_TAG_SPAN_RE = re.compile(r"<[^<>\n]*>|\{\\[^{}\n]*\}")

ASS_DEFAULT_HEADER = """\
[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, \
BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,22,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,\
0,0,0,0,100,100,0,0,1,2,1,2,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def wrap_cue(text: str, width: int = MAX_LINE_CHARS) -> str:
    """Pecah teks cue satu baris menjadi dua baris seimbang di luar tag format."""
    if "\n" in text:
        return text
    visible = strip_format_tags(text)
    if len(visible) <= width or " " not in visible:
        return text
    tag_ranges = [m.span() for m in _INLINE_TAG_SPAN_RE.finditer(text)]
    candidate_spaces: list[tuple[int, int]] = []
    vis_pos = 0
    idx = 0
    tag_idx = 0
    while idx < len(text):
        while tag_idx < len(tag_ranges) and idx >= tag_ranges[tag_idx][1]:
            tag_idx += 1
        if tag_idx < len(tag_ranges) and tag_ranges[tag_idx][0] <= idx < tag_ranges[tag_idx][1]:
            idx = tag_ranges[tag_idx][1]
            continue
        if text[idx] == " ":
            candidate_spaces.append((idx, vis_pos))
        vis_pos += 1
        idx += 1
    if not candidate_spaces:
        return text
    middle = len(visible) / 2.0
    cut, _ = min(candidate_spaces, key=lambda item: abs(item[1] - middle))
    return f"{text[:cut]}\n{text[cut + 1:]}"


def _require_subtitle_source(result: TranslatedDocument, target_fmt: str) -> None:
    if result.document.fmt not in SUBTITLE_FORMATS:
        raise InputError(
            f"keluaran {target_fmt.upper()} butuh masukan ber-timing "
            f"(srt/vtt/ass; masukan ini {result.document.fmt}); "
            "pilih format html, txt, md, atau json"
        )


def _require_timing(number: int, paragraph: TranslatedParagraph) -> tuple[str, str]:
    meta = paragraph.source.meta
    start = str(meta.get("start") or "")
    end = str(meta.get("end") or "")
    if not start or not end:
        raise InputError(f"blok subtitle ke-{number} tidak punya timing")
    return start, end


def _srt_cue(number: int, paragraph: TranslatedParagraph) -> str:
    start, end = _require_timing(number, paragraph)
    text = wrap_cue(paragraph.target or paragraph.source.text)
    return f"{number}\n{start} --> {end}\n{text}\n"


def render_srt(result: TranslatedDocument) -> str:
    """Hasil terjemahan sebagai berkas SRT; nomor blok diurutkan dari 1."""
    _require_subtitle_source(result, "srt")
    cues = [
        _srt_cue(number, p)
        for number, p in enumerate(result.paragraphs, start=1)
    ]
    logger.debug("srt: %d blok", len(cues))
    return "\n".join(cues)


def render_vtt(result: TranslatedDocument) -> str:
    """Hasil terjemahan sebagai berkas WebVTT (``WEBVTT``)."""
    _require_subtitle_source(result, "vtt")
    cues: list[str] = ["WEBVTT\n"]
    for number, paragraph in enumerate(result.paragraphs, start=1):
        start, end = _require_timing(number, paragraph)
        vtt_start = start.replace(",", ".")
        vtt_end = end.replace(",", ".")
        settings = paragraph.source.meta.get("vtt_settings", "")
        tail = f" {settings}" if settings else ""
        text = wrap_cue(paragraph.target or paragraph.source.text)
        cues.append(f"{number}\n{vtt_start} --> {vtt_end}{tail}\n{text}\n")
    logger.debug("vtt: %d cue", len(cues) - 1)
    return "\n".join(cues)


def _srt_to_ass_time(stamp: str) -> str:
    hms, _, ms = stamp.replace(".", ",").partition(",")
    parts = hms.split(":")
    hours = int(parts[0]) if len(parts) == 3 else 0
    minutes = parts[-2] if len(parts) >= 2 else "00"
    seconds = parts[-1]
    centis = int((ms or "000")[:3].ljust(3, "0")) // 10
    return f"{hours}:{minutes}:{seconds}.{centis:02d}"


def render_ass(result: TranslatedDocument) -> str:
    """Hasil terjemahan sebagai berkas ASS (SubStation Alpha v4+)."""
    _require_subtitle_source(result, "ass")
    lines = [ASS_DEFAULT_HEADER.rstrip("\n")]
    for number, paragraph in enumerate(result.paragraphs, start=1):
        start, end = _require_timing(number, paragraph)
        ass_start = _srt_to_ass_time(start)
        ass_end = _srt_to_ass_time(end)
        style = str(paragraph.source.meta.get("ass_style") or "Default").replace(",", " ")
        actor = str(paragraph.source.meta.get("ass_actor") or "").replace(",", " ")
        wrapped = wrap_cue(strip_format_tags(paragraph.target or paragraph.source.text))
        body = wrapped.replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{ass_start},{ass_end},{style},{actor},0,0,0,,{body}"
        )
    logger.debug("ass: %d baris dialog", len(lines) - 1)
    return "\n".join(lines) + "\n"
