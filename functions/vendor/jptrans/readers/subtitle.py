"""Pembaca subtitle SRT, WebVTT (``.vtt``), dan ASS/SSA (``.ass``/``.ssa``).

Setiap blok atau baris dialog subtitle diubah menjadi ``Paragraph`` dengan
``meta={"index", "start", "end", ...}`` agar penulis subtitle bisa memulihkan
timing aslinya secara presisi maupun mengonversi lintas format subtitle.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import InputError
from ..models import Document, Paragraph
from .txt import read_text_file

logger = logging.getLogger(__name__)

SUBTITLE_FORMATS = frozenset({"srt", "vtt", "ass"})

_SRT_TIME = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
_SRT_TIMING_RE = re.compile(_SRT_TIME + r"\s*-->\s*" + _SRT_TIME)
_VTT_TIME = r"(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{1,3})"
_VTT_TIMING_RE = re.compile(
    _VTT_TIME + r"\s*-->\s*" + _VTT_TIME + r"(?:[ \t]+([^\n]*))?"
)
_BLOCK_SPLIT_RE = re.compile(r"\n[ \t]*\n")
_VTT_SKIP_HEADS = ("NOTE", "STYLE", "REGION")
_VTT_RUBY_RE = re.compile(
    r"<ruby\b[^>]*>(.*?)</ruby>", re.IGNORECASE | re.DOTALL
)
_VTT_RT_PAIR_RE = re.compile(
    r"([^<]+?)(?:<rp\b[^>]*>.*?</rp>)*<rt\b[^>]*>(.*?)</rt>(?:<rp\b[^>]*>.*?</rp>)*",
    re.IGNORECASE | re.DOTALL,
)
_VTT_INLINE_TAG_RE = re.compile(
    r"<(?:/?(?:c|v|lang|ruby|rt|rp)(?:\.[^>\n]*)?(?:\s[^>\n]*)?|\d{2}:\d{2}(?::\d{2})?\.\d{3})>",
    re.IGNORECASE,
)
_ASS_OVERRIDE_RE = re.compile(r"\{[^{}\n]*\}")


def format_timestamp(
    hours: str, minutes: str, seconds: str, millis: str
) -> str:
    """Bentuk baku SRT ``HH:MM:SS,mmm``; ``"5"`` milidetik berarti 500 ms."""
    h = int(hours) if hours else 0
    return f"{h:02d}:{minutes}:{seconds},{millis.ljust(3, '0')}"


def parse_srt(text: str, title: str) -> Document:
    """Urai isi berkas SRT menjadi ``Document`` (satu paragraf per cue)."""
    paragraphs: list[Paragraph] = []
    for number, block in enumerate(_BLOCK_SPLIT_RE.split(text.strip()), start=1):
        paragraph = _parse_srt_block(block.strip("\n"), number)
        if paragraph is not None:
            paragraphs.append(paragraph)
    if not paragraphs:
        raise InputError("tidak ada blok subtitle SRT yang sah di berkas ini")
    logger.debug("srt: %d blok", len(paragraphs))
    return Document(title=title, paragraphs=paragraphs, fmt="srt")


def _parse_srt_block(block: str, number: int) -> Paragraph | None:
    lines = block.split("\n")
    timing_at = next(
        (i for i, line in enumerate(lines) if _SRT_TIMING_RE.search(line)), None
    )
    if timing_at is None:
        logger.warning("blok SRT ke-%d tanpa baris timing, dilewati", number)
        return None
    match = _SRT_TIMING_RE.search(lines[timing_at])
    assert match is not None
    times = match.groups()
    index_line = lines[timing_at - 1].strip() if timing_at else ""
    text = "\n".join(
        line.strip() for line in lines[timing_at + 1:] if line.strip()
    )
    if not text:
        return None
    meta = {
        "index": int(index_line) if index_line.isdigit() else number,
        "start": format_timestamp(*times[:4]),
        "end": format_timestamp(*times[4:]),
    }
    return Paragraph(text=text, meta=meta)


def parse_vtt(text: str, title: str) -> Document:
    """Urai isi berkas WebVTT (``.vtt``) beserta furigana ``<ruby>`` menjadi ``Document``."""
    stripped = text.lstrip("\ufeff").lstrip()
    if not stripped.startswith("WEBVTT"):
        raise InputError("berkas WebVTT harus diawali header WEBVTT")
    blocks = _BLOCK_SPLIT_RE.split(stripped)
    paragraphs: list[Paragraph] = []
    ruby: dict[str, str] = {}
    cue_num = 0
    for block in blocks[1:]:
        clean = block.strip("\n")
        if not clean or clean.startswith(_VTT_SKIP_HEADS):
            continue
        cue_num += 1
        paragraph = _parse_vtt_block(clean, cue_num, ruby)
        if paragraph is not None:
            paragraphs.append(paragraph)
    if not paragraphs:
        raise InputError("tidak ada cue WebVTT yang sah di berkas ini")
    logger.debug("vtt: %d cue, %d ruby", len(paragraphs), len(ruby))
    return Document(title=title, paragraphs=paragraphs, ruby=ruby, fmt="vtt")


def _strip_vtt_ruby(line: str, ruby: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        pairs = _VTT_RT_PAIR_RE.findall(inner)
        if not pairs:
            return _VTT_INLINE_TAG_RE.sub("", inner)
        base = "".join(b.strip() for b, _r in pairs)
        reading = "".join(r.strip() for _b, r in pairs)
        if base and reading:
            ruby.setdefault(base, reading)
        leftover = _VTT_RT_PAIR_RE.sub("", inner)
        return base + _VTT_INLINE_TAG_RE.sub("", leftover)

    return _VTT_RUBY_RE.sub(repl, line)


def _parse_vtt_block(
    block: str, number: int, ruby: dict[str, str]
) -> Paragraph | None:
    lines = block.split("\n")
    timing_at = next(
        (i for i, line in enumerate(lines) if _VTT_TIMING_RE.search(line)), None
    )
    if timing_at is None:
        return None
    match = _VTT_TIMING_RE.search(lines[timing_at])
    assert match is not None
    h1, m1, s1, ms1, h2, m2, s2, ms2, settings = match.groups()
    cue_id = lines[timing_at - 1].strip() if timing_at else ""
    raw_lines = [
        _VTT_INLINE_TAG_RE.sub("", _strip_vtt_ruby(line, ruby)).strip()
        for line in lines[timing_at + 1:]
    ]
    text = "\n".join(line for line in raw_lines if line)
    if not text:
        return None
    meta: dict[str, object] = {
        "index": int(cue_id) if cue_id.isdigit() else number,
        "start": format_timestamp(h1 or "0", m1, s1, ms1),
        "end": format_timestamp(h2 or "0", m2, s2, ms2),
    }
    if settings and settings.strip():
        meta["vtt_settings"] = settings.strip()
    return Paragraph(text=text, meta=meta)


def parse_ass(text: str, title: str) -> Document:
    """Urai berkas subtitle ASS/SSA (``[Events]`` ``Dialogue:``) menjadi ``Document``."""
    lines = text.splitlines()
    in_events = False
    columns = [
        "layer", "start", "end", "style", "name",
        "marginl", "marginr", "marginv", "effect", "text",
    ]
    paragraphs: list[Paragraph] = []
    header_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_events = stripped.lower() == "[events]"
            if not in_events and not paragraphs:
                header_lines.append(line)
            continue
        if not in_events:
            if not paragraphs:
                header_lines.append(line)
            continue
        lower = stripped.lower()
        if lower.startswith("format:"):
            parsed_cols = [
                col.strip().lower()
                for col in stripped.split(":", 1)[1].split(",")
            ]
            if "text" in parsed_cols and "start" in parsed_cols and "end" in parsed_cols:
                columns = parsed_cols
            continue
        if not lower.startswith("dialogue:"):
            continue
        payload = stripped.split(":", 1)[1].lstrip()
        parts = payload.split(",", len(columns) - 1)
        if len(parts) < len(columns):
            continue
        row = dict(zip(columns, parts))
        raw_dialogue = (
            row["text"]
            .replace("\\N", "\n")
            .replace("\\n", "\n")
            .replace("\\h", " ")
        )
        clean_text = _ASS_OVERRIDE_RE.sub("", raw_dialogue).strip()
        if not clean_text:
            continue
        start_srt = _ass_time_to_srt(row["start"].strip())
        end_srt = _ass_time_to_srt(row["end"].strip())
        meta = {
            "index": len(paragraphs) + 1,
            "start": start_srt,
            "end": end_srt,
            "ass_style": row.get("style", "Default").strip() or "Default",
            "ass_actor": row.get("name", "").strip(),
        }
        paragraphs.append(Paragraph(text=clean_text, meta=meta))
    if not paragraphs:
        raise InputError("tidak ada baris Dialogue ASS/SSA yang sah di berkas ini")
    logger.debug("ass: %d baris dialog", len(paragraphs))
    return Document(title=title, paragraphs=paragraphs, fmt="ass")


def _ass_time_to_srt(stamp: str) -> str:
    match = re.match(r"^(\d+):(\d{2}):(\d{2})[.,](\d{1,3})$", stamp)
    if not match:
        raise InputError(f"waktu ASS/SSA tidak sah: {stamp!r}")
    h, m, s, frac = match.groups()
    ms = f"{int(frac) * 10:03d}" if len(frac) == 2 else frac.ljust(3, "0")
    return f"{int(h):02d}:{m}:{s},{ms[:3]}"


def read_srt(
    path: Path, title: str | None = None, encoding: str | None = None
) -> Document:
    """Baca berkas ``.srt`` dari disk."""
    path = Path(path)
    doc = parse_srt(read_text_file(path, encoding), title or path.stem)
    doc.source_path = str(path)
    return doc


def read_vtt(
    path: Path, title: str | None = None, encoding: str | None = None
) -> Document:
    """Baca berkas ``.vtt`` (WebVTT) dari disk."""
    path = Path(path)
    doc = parse_vtt(read_text_file(path, encoding), title or path.stem)
    doc.source_path = str(path)
    return doc


def read_ass(
    path: Path, title: str | None = None, encoding: str | None = None
) -> Document:
    """Baca berkas ``.ass`` atau ``.ssa`` dari disk."""
    path = Path(path)
    doc = parse_ass(read_text_file(path, encoding), title or path.stem)
    doc.source_path = str(path)
    return doc
