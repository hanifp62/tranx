"""Penulis teks: TXT polos, Markdown, dan JSON lengkap.

- ``txt``: satu paragraf terjemahan per blok; ``bilingual=True`` menaruh baris
  Jepang asli tepat di atas terjemahannya (cocok untuk belajar).
- ``md``: judul ``#``, bab ``##``, paragraf, lalu tabel glosarium.
- ``json``: seluruh hasil (kalimat, status, mesin, glosarium, statistik) agar
  bisa diproses ulang oleh skrip lain.

Cue subtitle dua pembicara tampil satu baris per pembicara (``- Ya.`` lalu
``- Tidak.``) di ketiga format: baris baru di TXT dan JSON, jeda baris keras
``\\`` di Markdown.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict

from ..models import ENTITY_KINDS, GlossaryEntry, TranslatedDocument, TranslatedParagraph

logger = logging.getLogger(__name__)

JSON_FORMAT = "jptrans-result"
JSON_VERSION = 1
_MD_SPECIAL_RE = re.compile(r"([\\`*_\[\]<>|])")
# Penanda blok di awal baris: judul/kutipan/daftar, dan daftar bernomor "1." / "1)".
_MD_LEADING_MARK_RE = re.compile(r"^([#>+-])")
_MD_ORDERED_RE = re.compile(r"^(\d+)([.)])")
MD_HARD_BREAK = "\\\n"
"""Jeda baris keras CommonMark (garis miring terbalik di akhir baris)."""
_MD_GLOSSARY_HEAD = {
    "id": ("Glosarium", "| Tulisan | Bacaan | Dipakai | Jenis |"),
    "en": ("Glossary", "| Written | Reading | Rendered as | Type |"),
}


def paragraph_text(paragraph: TranslatedParagraph) -> str:
    """Teks terjemahan paragraf; teks asli bila tidak ada terjemahan sama sekali."""
    return paragraph.target or paragraph.source.text


def sorted_glossary(entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
    """Urutkan entri menurut jenis (orang, tempat, ...) lalu bacaan."""
    order = {kind: pos for pos, kind in enumerate(ENTITY_KINDS)}
    return sorted(entries, key=lambda e: (order.get(e.kind, len(order)), e.reading or e.surface))


def rendered_form(entry: GlossaryEntry, result: TranslatedDocument) -> str:
    """Bentuk nama yang dipakai di terjemahan, untuk tabel glosarium.

    Prioritas: ``result.stats["rendered"][surface]`` (diisi pipeline dari
    ``style.Renderer``), lalu ``render_id``/``render_en``, lalu ``romaji``.
    """
    rendered = result.stats.get("rendered")
    if isinstance(rendered, dict) and rendered.get(entry.surface):
        return str(rendered[entry.surface])
    return entry.render_for(result.target_lang) or entry.romaji or "-"


def render_txt(result: TranslatedDocument, *, bilingual: bool = False) -> str:
    """Terjemahan sebagai teks polos, paragraf dipisah satu baris kosong.

    Args:
        result: Hasil pipeline.
        bilingual: Bila ``True``, tiap paragraf diawali baris Jepang aslinya.
    """
    blocks = []
    for paragraph in result.paragraphs:
        text = paragraph_text(paragraph)
        blocks.append(f"{paragraph.source.text}\n{text}" if bilingual else text)
    return "\n\n".join(blocks) + "\n"


def md_escape(text: str) -> str:
    """Escape karakter Markdown agar teks tampil apa adanya."""
    escaped = _MD_SPECIAL_RE.sub(r"\\\1", text.replace("\n", " "))
    escaped = _MD_LEADING_MARK_RE.sub(r"\\\1", escaped)
    return _MD_ORDERED_RE.sub(r"\1\\\2", escaped)


def render_md(result: TranslatedDocument) -> str:
    """Terjemahan sebagai Markdown: judul, paragraf (bab jadi ``##``), glosarium."""
    lines = [f"# {md_escape(result.document.title)}", ""]
    for paragraph in result.paragraphs:
        text = _md_paragraph(paragraph)
        lines += [f"## {text}" if paragraph.source.kind == "heading" else text, ""]
    if result.glossary:
        heading, columns = _MD_GLOSSARY_HEAD.get(result.target_lang, _MD_GLOSSARY_HEAD["en"])
        lines += [f"## {heading}", "", columns, "| --- | --- | --- | --- |"]
        for entry in sorted_glossary(result.glossary):
            cells = (entry.surface, entry.reading, rendered_form(entry, result), entry.kind)
            lines.append("| " + " | ".join(md_escape(cell) for cell in cells) + " |")
        lines.append("")
    return "\n".join(lines)


def _md_paragraph(paragraph: TranslatedParagraph) -> str:
    """Satu paragraf Markdown; giliran cue dua pembicara dipisah jeda baris keras."""
    if not paragraph.is_dialogue:
        return md_escape(paragraph_text(paragraph))
    return MD_HARD_BREAK.join(md_escape(line) for line in paragraph.target.split("\n"))


def _paragraph_dict(paragraph: TranslatedParagraph) -> dict:
    """Bentuk JSON satu paragraf; ``turns`` hanya ada untuk cue dua pembicara."""
    data = {
        "kind": paragraph.source.kind,
        "meta": paragraph.source.meta,
        "source": paragraph.source.text,
        "target": paragraph.target,
        "sentences": [asdict(s) for s in paragraph.sentences],
    }
    if paragraph.is_dialogue:
        data["turns"] = paragraph.turns
    return data


def result_to_dict(result: TranslatedDocument) -> dict:
    """Bentuk dict lengkap yang aman untuk ``json.dumps``."""
    doc = result.document
    return {
        "format": JSON_FORMAT,
        "version": JSON_VERSION,
        "title": doc.title,
        "source_lang": result.source_lang,
        "target_lang": result.target_lang,
        "source_format": doc.fmt,
        "source_path": doc.source_path,
        "paragraphs": [_paragraph_dict(p) for p in result.paragraphs],
        "glossary": [asdict(entry) for entry in result.glossary],
        "ruby": doc.ruby,
        "stats": result.stats,
    }


def render_json(result: TranslatedDocument) -> str:
    """Seluruh hasil sebagai JSON UTF-8 (huruf Jepang tidak di-escape)."""
    logger.debug("json: %d paragraf", len(result.paragraphs))
    # default=str menjaga agar nilai statistik yang tak terduga (Path, set) tidak
    # menggagalkan penulisan seluruh berkas.
    return json.dumps(result_to_dict(result), ensure_ascii=False, indent=2, default=str) + "\n"
