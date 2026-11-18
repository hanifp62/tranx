"""Penulis HTML bilingual: keluaran utama untuk membaca di HP.

Hasilnya satu berkas mandiri yang bisa dibuka di browser mana pun tanpa
Python, tanpa internet, dan tanpa JavaScript:

- Tiap paragraf adalah ``<details>``; ketuk terjemahan untuk menampilkan teks
  Jepang aslinya (lengkap dengan ``<ruby>`` furigana). Teks asli diletakkan di
  dalam ``<summary>`` dan disembunyikan dengan CSS, sehingga mode "tampilkan
  semua" dan mode dua kolom berdampingan cukup memakai checkbox CSS tanpa
  menggandakan teks.
- Tipografi nyaman untuk novel, mode gelap mengikuti ``prefers-color-scheme``,
  dua kolom (CSS grid) hanya di layar lebar.
- Bagian akhir: tabel glosarium, statistik, dan atribusi mesin.

Semua teks dari dokumen melewati ``html.escape``. Tag format subtitle SRT
(``<i>``, ``{\\an8}``, ``<font ...>``) milik pemutar video, jadi di halaman baca
hasil SRT tag itu dibuang dari terjemahan dan teks asli (``TAG_FORMATS``).
"""

from __future__ import annotations

import html
import logging
import re
from collections import Counter
from collections.abc import Callable

from .. import __version__
from ..models import (
    DIALOGUE_DASH, STATUS_CACHED, STATUS_FAILED, STATUS_OK, STATUS_PARTIAL, STATUS_PLAIN,
    STATUS_PRESUB, Paragraph, SentencePair, TranslatedDocument, TranslatedParagraph,
    strip_format_tags,
)
from ..textnorm import contains_japanese
from .text import paragraph_text, rendered_form, sorted_glossary

logger = logging.getLogger(__name__)

STATUS_ORDER = (STATUS_OK, STATUS_CACHED, STATUS_PRESUB, STATUS_PLAIN, STATUS_PARTIAL,
                STATUS_FAILED)
# Kunci stats yang tidak dicetak mentah: "rendered" adalah peta glosarium untuk tabel;
# jumlah per status dan per mesin sudah tampil sebagai ubin dan baris "Mesin".
HIDDEN_STATS = frozenset({"rendered", "by_status", "by_engine"})
# Status yang diberi penanda visual di teks (kelas CSS = nama status) dan dijelaskan di legenda.
MARKED_STATUSES = (STATUS_FAILED, STATUS_PRESUB, STATUS_PARTIAL)
TAG_FORMATS = frozenset({"srt", "vtt", "ass"})
"""Format masukan yang tag formatnya (``<i>``, ``{\\an8}``) tidak ditampilkan di HTML."""
MIN_RUBY_BASE = 2   # ruby satu kanji (日《ひ》) mudah salah bila ditempel di semua kemunculan

UI = {
    "id": {
        "lang_names": {"ja": "Jepang", "id": "Indonesia", "en": "Inggris"},
        "paragraphs": "paragraf", "sentences": "kalimat",
        "hint": "Ketuk paragraf untuk melihat teks Jepang aslinya.",
        "show_all": "Tampilkan teks asli", "side_by_side": "Berdampingan",
        "th_auto": "Tema: Otomatis", "th_light": "Terang", "th_dark": "Gelap",
        "toc": "Daftar isi", "page": "Halaman", "glossary": "Glosarium",
        "surface": "Tulisan", "reading": "Bacaan", "used": "Dipakai", "kind": "Jenis",
        "review": "perlu ditinjau", "stats": "Statistik", "engines": "Mesin",
        "total": "Total kalimat", "credits": "Atribusi",
        "failed_title": "Gagal diterjemahkan; teks asli dipertahankan",
        "presub_title": "Lewat jalur cadangan (nama disisipkan sebelum diterjemahkan); "
                        "periksa ulang",
        "partial_title": "Sebagian kalimat masih berhuruf Jepang",
        "legend": "Tanda:",
        "failed_note": "Kalimat bertanda kuning gagal diterjemahkan semua mesin "
                       "dan ditampilkan dalam bahasa aslinya.",
        "disclaimer": "Terjemahan mesin. Nama, tempat, dan istilah dijaga oleh glosarium "
                      "jptrans, tetapi makna kalimat bisa keliru.",
        "made_by": "Dibuat dengan jptrans",
        "engine_notes": {"google": "endpoint tidak resmi", "fake": "uji, bukan terjemahan nyata"},
        "yes": "ya", "no": "tidak",
        "kinds": {"PERSON": "orang", "PLACE": "tempat", "ORG": "organisasi",
                  "TERM": "istilah", "CULTURE": "budaya"},
        "status": {STATUS_OK: "diterjemahkan", STATUS_CACHED: "dari cache",
                   STATUS_PRESUB: "jalur cadangan", STATUS_PLAIN: "tanpa teks Jepang",
                   STATUS_PARTIAL: "sebagian masih Jepang", STATUS_FAILED: "gagal"},
        "stat_labels": {"chars_sent": "Karakter terkirim", "elapsed": "Waktu (detik)",
                        "seconds": "Waktu (detik)", "new_entries": "Entri glosarium baru",
                        "requests": "Permintaan", "by_engine": "Per mesin",
                        "by_status": "Per status"},
    },
    "en": {
        "lang_names": {"ja": "Japanese", "id": "Indonesian", "en": "English"},
        "paragraphs": "paragraphs", "sentences": "sentences",
        "hint": "Tap a paragraph to see the original Japanese.",
        "show_all": "Show original", "side_by_side": "Side by side",
        "th_auto": "Theme: Auto", "th_light": "Light", "th_dark": "Dark",
        "toc": "Contents", "page": "Page", "glossary": "Glossary",
        "surface": "Written", "reading": "Reading", "used": "Rendered as", "kind": "Type",
        "review": "needs review", "stats": "Statistics", "engines": "Engines",
        "total": "Total sentences", "credits": "Credits",
        "failed_title": "Translation failed; original text kept",
        "presub_title": "Fallback path (names inserted before translation); please check",
        "partial_title": "Part of the sentence is still in Japanese",
        "legend": "Marks:",
        "failed_note": "Sentences highlighted in yellow failed on every engine "
                       "and are shown in the original language.",
        "disclaimer": "Machine translation. Names, places and terms are kept consistent by "
                      "the jptrans glossary, but sentence meaning may be wrong.",
        "made_by": "Made with jptrans",
        "engine_notes": {"google": "unofficial endpoint", "fake": "test, not a real translation"},
        "yes": "yes", "no": "no",
        "kinds": {"PERSON": "person", "PLACE": "place", "ORG": "organization",
                  "TERM": "term", "CULTURE": "culture"},
        "status": {STATUS_OK: "translated", STATUS_CACHED: "from cache",
                   STATUS_PRESUB: "fallback path", STATUS_PLAIN: "no Japanese text",
                   STATUS_PARTIAL: "partly Japanese", STATUS_FAILED: "failed"},
        "stat_labels": {"chars_sent": "Characters sent", "elapsed": "Time (seconds)",
                        "seconds": "Time (seconds)", "new_entries": "New glossary entries",
                        "requests": "Requests", "by_engine": "By engine",
                        "by_status": "By status"},
    },
}

ENGINE_NAMES = {
    "deepl": "DeepL API (deepl.com)",
    "mymemory": "MyMemory (mymemory.translated.net)",
    "google": "Google Translate (translate.googleapis.com)",
    "llm": "LLM (OpenAI-compatible API)",
    "libretranslate": "LibreTranslate",
    "fake": "FakeEngine",
}

CSS = """
:root{color-scheme:light dark;--bg:#faf7f2;--fg:#22201c;--muted:#6b665d;--line:#878074;
--card:#f2ede4;--accent:#3d5bd9;--accent-fg:#fff;--warn:#8a5a0b;--warn-bg:#fdf3d7;
--info:#3d5bd9;
--serif:ui-serif,Georgia,"Noto Serif","Times New Roman",serif;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",sans-serif;
--ja:"Hiragino Mincho ProN","Yu Mincho","Noto Serif JP","Noto Serif CJK JP",serif}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e7e3db;--muted:#9b968c;
--line:#6d7380;--card:#1f2227;--accent:#93a4ff;--accent-fg:#16181c;--warn:#e0b45a;
--warn-bg:#4d3b14;--info:#93a4ff}}
:root:has(#th-light:checked){color-scheme:light;--bg:#faf7f2;--fg:#22201c;--muted:#6b665d;
--line:#878074;--card:#f2ede4;--accent:#3d5bd9;--accent-fg:#fff;--warn:#8a5a0b;
--warn-bg:#fdf3d7;--info:#3d5bd9}
:root:has(#th-dark:checked){color-scheme:dark;--bg:#16181c;--fg:#e7e3db;--muted:#9b968c;
--line:#6d7380;--card:#1f2227;--accent:#93a4ff;--accent-fg:#16181c;--warn:#e0b45a;
--warn-bg:#4d3b14;--info:#93a4ff}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);overflow-wrap:break-word;
font:400 clamp(17px,1rem + .3vw,20px)/1.75 var(--serif);padding:0 16px 3rem;
padding:0 max(16px,env(safe-area-inset-right)) 3rem max(16px,env(safe-area-inset-left))}
header,main,nav,footer{max-width:40rem;margin:0 auto}
header{padding:2.5rem 0 1rem;font-family:var(--sans)}
h1{font:700 1.6em/1.25 var(--serif);margin:0 0 .4rem;letter-spacing:-.01em}
h1:lang(ja){letter-spacing:0}
.meta,.hint,.legend{color:var(--muted);font-size:.8em;margin:.2rem 0}
.legend .key{color:var(--fg);margin-right:.9em;padding:0 .2em;display:inline-block}
:lang(ja){font-family:var(--ja);line-break:strict}
.opt{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}
.toggles{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0 0}
.toggles label{font:500 .78em/1.2 var(--sans);border:1px solid var(--line);border-radius:999px;
padding:.4em 1.1em;cursor:pointer;user-select:none;background:var(--card);min-height:44px;
display:inline-flex;align-items:center}
#opt-orig:checked~header label[for=opt-orig],#opt-sbs:checked~header label[for=opt-sbs],
#th-auto:checked~header label[for=th-auto],#th-light:checked~header label[for=th-light],
#th-dark:checked~header label[for=th-dark]{
background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}
#opt-orig:focus-visible~header label[for=opt-orig],
#opt-sbs:focus-visible~header label[for=opt-sbs],
#th-auto:focus-visible~header label[for=th-auto],
#th-light:focus-visible~header label[for=th-light],
#th-dark:focus-visible~header label[for=th-dark]{outline:2px solid var(--accent);outline-offset:2px}
label[for=opt-sbs],#opt-sbs{display:none}
nav.toc{font-family:var(--sans);font-size:.85em;margin-bottom:1.5rem}
nav.toc summary{cursor:pointer;color:var(--muted);min-height:44px;display:flex;
align-items:center;gap:.4em}
nav.toc summary::before{content:"\\25B8";font-size:.8em}
nav.toc details[open] summary::before{content:"\\25BE"}
nav.toc summary::-webkit-details-marker{display:none}
nav.toc ol{margin:0 0 .5rem;padding-left:1.4rem}
nav.toc a{display:flex;align-items:center;min-height:44px;line-height:1.3}
a{color:var(--accent)}
a:focus-visible,nav.toc summary:focus-visible{outline:2px solid var(--accent);
outline-offset:2px;border-radius:4px}
main{padding-top:.5rem}
details.p{margin:0 0 1.05em calc(-.6em - 3px);border-left:3px solid transparent;
transition:border-color .15s}
details.p>summary{display:block;list-style:none;cursor:pointer;padding:.15em .6em;
border-radius:6px;overflow-wrap:anywhere}
details.p>summary::-webkit-details-marker{display:none}
details.p>summary:hover{background:var(--card)}
details.p>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
details.p[open]{border-left-color:var(--accent)}
details.hd{margin-top:1.6em}
.hd .tr{font:700 1.25em/1.4 var(--serif);margin:0 0 .2em;display:block}
.orig{display:none;color:var(--muted);font-size:.95em;margin-top:.35em;padding-top:.35em;
border-top:1px dashed var(--line)}
details.p[open] .orig,#opt-orig:checked~main .orig{display:block}
ruby{ruby-align:center}rt{font-size:.55em;color:var(--muted)}
.ts{display:block;font:500 .7em/1.4 var(--sans);color:var(--muted);margin-bottom:.1em;
font-variant-numeric:tabular-nums}
.failed,.k-failed{background:var(--warn-bg);border-bottom:2px solid var(--warn);border-radius:3px;
-webkit-print-color-adjust:exact;print-color-adjust:exact}
.failed::before,.k-failed::before{content:"\\26A0\\FE0E\\00A0";color:var(--warn);
font-family:var(--sans)}
.presub,.k-presub{text-decoration:underline dotted var(--info) 2px;text-underline-offset:.25em}
.partial,.k-partial{text-decoration:underline wavy var(--warn) 1.5px;text-underline-offset:.25em}
.gloss{color:var(--muted);font-style:italic}
.page-mark{font:600 .75em/1 var(--sans);color:var(--muted);text-transform:uppercase;
letter-spacing:.08em;margin:2.2em 0 1em;display:flex;align-items:center;gap:.75em}
.page-mark::after{content:"";flex:1;border-top:1px solid var(--line)}
footer{font-family:var(--sans);font-size:.85em;margin-top:3rem;border-top:1px solid var(--line)}
footer h2{font:700 1.15em/1.3 var(--sans);margin:2rem 0 .8rem}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:.5em .6em;border-bottom:1px solid var(--line);vertical-align:top}
td{overflow-wrap:anywhere}td:last-child,th{white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:.85em}
td:first-child{font-size:1.1em}
.badge{display:inline-block;font-size:.72em;padding:.1em .5em;border-radius:999px;
background:var(--warn-bg);color:var(--fg);margin-left:.3em;white-space:nowrap}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(7.5rem,1fr));gap:.6rem}
.tile{background:var(--card);border-radius:10px;padding:.7em .8em}
.tile b{display:block;font-size:1.5em;line-height:1.2;font-variant-numeric:tabular-nums}
.tile span{color:var(--muted);font-size:.85em}
.tile.bad b{color:var(--warn)}
dl.kv{display:grid;grid-template-columns:auto 1fr;gap:.3em 1em;margin:1rem 0}
dl.kv dt{color:var(--muted)}dl.kv dd{margin:0;min-width:0}
.credit{color:var(--muted)}
@media (max-width:30rem){th,td{padding:.45em .35em}td:first-child{font-size:1em}
dl.kv{grid-template-columns:1fr;gap:0}dl.kv dd{margin-bottom:.5em}}
@media (min-width:60rem){label[for=opt-sbs]{display:inline-flex}#opt-sbs{display:block}
#opt-sbs:checked~header,#opt-sbs:checked~main,#opt-sbs:checked~nav,
#opt-sbs:checked~footer{max-width:72rem}
#opt-sbs:checked~main details.p>summary{display:grid;grid-template-columns:1fr 1fr;gap:2.5rem}
#opt-sbs:checked~main details.p>summary>*{min-width:0}
#opt-sbs:checked~main .orig{display:block;margin:0;padding:0;border:0}}
@media print{:root,:root:has(#th-dark:checked){color-scheme:light;--bg:#fff;--fg:#000;
--muted:#555;--line:#767676;--card:#f3f3f3;--accent:#1a3fb0;--accent-fg:#fff;
--warn:#7a4d00;--warn-bg:#fff1c2;--info:#1a3fb0}
body{font-size:11pt;padding:0}
.toggles,.hint,nav.toc{display:none}
header,main,nav,footer{max-width:none}
details.p .orig{display:block}
details.p{border-left:0;margin-left:0;break-inside:avoid}
details.p>summary{padding:0}
.scroll{overflow:visible}
a{color:inherit;text-decoration:none}
.tile{border:1px solid var(--line)}}
"""


def render_html(result: TranslatedDocument) -> str:
    """Bangun halaman HTML bilingual mandiri dari hasil terjemahan.

    Bentuk nama di tabel glosarium diambil dari ``result.stats["rendered"]``
    (``{tulisan: bentuk_akhir}``) bila pipeline menyediakannya, lalu dari
    ``render_id``/``render_en`` dan ``romaji`` entri.

    Args:
        result: Hasil pipeline.

    Returns:
        Dokumen HTML lengkap sebagai string.
    """
    ui = UI.get(result.target_lang, UI["en"])
    title = result.document.title or "jptrans"
    ruby = RubyIndex.from_result(result)
    glosses = GlossMarker.from_result(result)
    body = [
        '<input type="checkbox" id="opt-orig" class="opt">',
        '<input type="checkbox" id="opt-sbs" class="opt">',
        '<input type="radio" name="theme" id="th-auto" class="opt" checked>',
        '<input type="radio" name="theme" id="th-light" class="opt">',
        '<input type="radio" name="theme" id="th-dark" class="opt">',
        _header(result, title, ui),
        _toc(result.paragraphs, ui),
        _main(result.paragraphs, ruby, glosses, ui,
              _untagged if result.document.fmt in TAG_FORMATS else _as_is),
        _footer(result, ui),
    ]
    logger.debug("html: %d paragraf", len(result.paragraphs))
    return (
        f'<!DOCTYPE html>\n<html lang="{_esc(result.target_lang)}">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f'<meta name="generator" content="jptrans {_esc(__version__)}">\n'
        f"<title>{_esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        + "\n".join(part for part in body if part)
        + "\n</body>\n</html>\n"
    )


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _header(result: TranslatedDocument, title: str, ui: dict) -> str:
    names = ui["lang_names"]
    sentence_count = sum(len(p.sentences) for p in result.paragraphs)
    meta = (
        f"{names.get(result.source_lang, result.source_lang)} → "
        f"{names.get(result.target_lang, result.target_lang)} · "
        f"{len(result.paragraphs)} {ui['paragraphs']} · {sentence_count} {ui['sentences']}"
    )
    return (
        f"<header>\n<h1{_lang_ja(title)}>{_esc(title)}</h1>\n"
        f'<p class="meta">{_esc(meta)}</p>\n<p class="hint">{_esc(ui["hint"])}</p>\n'
        + _legend(result.paragraphs, ui)
        + '<div class="toggles">'
        f'<label for="opt-orig">{_esc(ui["show_all"])}</label>'
        f'<label for="opt-sbs">{_esc(ui["side_by_side"])}</label>'
        f'<label for="th-auto">{_esc(ui["th_auto"])}</label>'
        f'<label for="th-light">{_esc(ui["th_light"])}</label>'
        f'<label for="th-dark">{_esc(ui["th_dark"])}</label>'
        "</div>\n</header>"
    )


def _lang_ja(text: str) -> str:
    """Atribut ``lang="ja"`` bila teks memuat huruf Jepang (judul, nilai statistik).

    Tanpa atribut ini browser memilih glif CJK menurut bahasa halaman (``id``/``en``),
    sehingga kanji bisa tampil dengan bentuk Tionghoa dan fon Mincho tidak dipakai.
    """
    return ' lang="ja"' if contains_japanese(text) else ""


def _legend(paragraphs: list[TranslatedParagraph], ui: dict) -> str:
    """Legenda penanda status, hanya untuk status yang benar-benar ada di dokumen."""
    present = count_statuses(paragraphs)
    keys = [
        f'<span class="key k-{status}" title="{_esc(ui[status + "_title"])}">'
        f'{_esc(ui["status"][status])}</span>'
        for status in MARKED_STATUSES if present.get(status)
    ]
    if not keys:
        return ""
    return f'<p class="legend">{_esc(ui["legend"])} {"".join(keys)}</p>\n'


def _toc(paragraphs: list[TranslatedParagraph], ui: dict) -> str:
    links = [
        f'<li><a href="#p{number}">{_esc(paragraph_text(p))}</a></li>'
        for number, p in enumerate(paragraphs, start=1) if p.source.kind == "heading"
    ]
    if len(links) < 2:
        return ""
    return (
        f'<nav class="toc"><details><summary>{_esc(ui["toc"])}</summary>'
        f'<ol>{"".join(links)}</ol></details></nav>'
    )


def _as_is(text: str) -> str:
    """Teks apa adanya (format selain SRT: ``<i>`` di teks adalah isi, bukan tag)."""
    return text


def _untagged(text: str) -> str:
    """Teks tanpa tag format SRT dan tanpa spasi tepi yang ditinggalkannya."""
    return strip_format_tags(text).strip()


def _main(paragraphs: list[TranslatedParagraph], ruby: RubyIndex, glosses: GlossMarker,
          ui: dict, clean: Callable[[str], str] = _as_is) -> str:
    """Isi ``<main>``: semua paragraf, dengan penanda halaman bila nomor halaman berganti.

    ``clean`` membersihkan teks sumber sebelum ditampilkan (``_untagged`` untuk subtitle).
    """
    parts = ["<main>"]
    current_page = None
    for number, paragraph in enumerate(paragraphs, start=1):
        page = paragraph.source.meta.get("page")
        if page is not None and page != current_page:
            parts.append(f'<p class="page-mark">{_esc(ui["page"])} {_esc(page)}</p>')
            current_page = page
        parts.append(_paragraph(number, paragraph, ruby, glosses, ui, clean))
    parts.append("</main>")
    return "\n".join(parts)


def _paragraph(number: int, paragraph: TranslatedParagraph, ruby: RubyIndex,
               glosses: GlossMarker, ui: dict, clean: Callable[[str], str] = _as_is) -> str:
    """Satu paragraf sebagai ``<details>``: terjemahan di ``summary``, teks asli tersembunyi.

    Cue dua pembicara (``is_dialogue``) menampilkan tiap baris asli di baris sendiri.
    """
    source = paragraph.source
    heading = source.kind == "heading"
    translation = _timestamp(source) + _sentences_html(paragraph, glosses, ui, clean)
    role_attr = ' role="heading" aria-level="2"' if heading else ""
    css = "p hd" if heading else "p"
    if paragraph.is_dialogue:
        # Cue dua pembicara: tiap baris asli tetap baris sendiri.
        original = "<br>".join(ruby.markup(clean(line)) for line in source.text.split("\n"))
    else:
        original = ruby.markup(clean(source.text))
    return (
        f'<details class="{css}" id="p{number}"><summary>'
        f'<span class="tr"{role_attr}>{translation}</span>'
        f'<span class="orig" lang="ja">{original}</span>'
        "</summary></details>"
    )


def _timestamp(source: Paragraph) -> str:
    start = source.meta.get("start")
    if not isinstance(start, str):
        return ""
    return f'<span class="ts">{_esc(start.split(",")[0])}</span>'


def _sentences_html(paragraph: TranslatedParagraph, glosses: GlossMarker, ui: dict,
                    clean: Callable[[str], str] = _as_is) -> str:
    """Terjemahan paragraf; cue dua pembicara menjadi satu baris ``- …`` per giliran.

    ``clean`` membuang tag format SRT; kalimat yang isinya hanya tag tidak ditampilkan.
    """
    groups = paragraph.turn_sentences()
    if not groups:
        return _esc(clean(paragraph.source.text))
    lines = [" ".join(_sentence_html(sentence, glosses, ui, clean) for sentence in group
                      if clean(sentence.target or sentence.source))
             for group in groups]
    if paragraph.is_dialogue:
        return "<br>".join(_esc(DIALOGUE_DASH) + line for line in lines)
    return " ".join(lines)


def _sentence_html(sentence: SentencePair, glosses: GlossMarker, ui: dict,
                   clean: Callable[[str], str] = _as_is) -> str:
    """Satu kalimat terjemahan: gloss ditandai, status bermasalah diberi penanda.

    ``failed`` menampilkan teks asli (``lang="ja"``); ``presub`` dan ``partial`` tetap
    terjemahan tetapi perlu diperiksa, jadi diberi garis bawah dan ``title`` penjelas.
    """
    # Target kosong hanya sampai ke sini untuk giliran cue dua pembicara; sumbernya ditampilkan.
    if sentence.status == STATUS_FAILED:
        text = _esc(clean(sentence.target or sentence.source))
        return (f'<span class="failed" lang="ja" title="{_esc(ui["failed_title"])}">'
                f"{text}</span>")
    text = glosses.markup(clean(sentence.target or sentence.source))
    if sentence.status in (STATUS_PRESUB, STATUS_PARTIAL):
        title = ui[sentence.status + "_title"]
        text = f'<span class="{sentence.status}" title="{_esc(title)}">{text}</span>'
    return text


class GlossMarker:
    """Penanda gloss kemunculan pertama: ``(arti)`` dari glosarium dibungkus ``span.gloss``.

    Renderer gaya (``style.Renderer``) menyisipkan gloss sebagai teks biasa
    ``Nama (arti)``; di HTML gloss itu diberi warna redup agar terbaca sebagai
    keterangan, bukan bagian kalimat.

    Attributes:
        pattern: Regex semua bentuk ``(arti)`` untuk bahasa sasaran, atau ``None``.
    """

    def __init__(self, glosses: list[str]) -> None:
        alternatives = sorted({f"({gloss})" for gloss in glosses if gloss}, key=len,
                              reverse=True)
        self.pattern = re.compile("|".join(map(re.escape, alternatives))) if alternatives else None

    @classmethod
    def from_result(cls, result: TranslatedDocument) -> GlossMarker:
        """Ambil gloss bahasa sasaran dari glosarium hasil."""
        return cls([entry.gloss_for(result.target_lang) for entry in result.glossary])

    def markup(self, text: str) -> str:
        """Escape ``text`` dan bungkus setiap ``(arti)`` yang dikenal dengan ``span.gloss``."""
        if self.pattern is None:
            return _esc(text)
        parts, last = [], 0
        for match in self.pattern.finditer(text):
            parts.append(_esc(text[last:match.start()]))
            parts.append(f'<span class="gloss">{_esc(match.group(0))}</span>')
            last = match.end()
        parts.append(_esc(text[last:]))
        return "".join(parts)


class RubyIndex:
    """Penanda furigana: membungkus basis yang dikenal dengan ``<ruby>``.

    Attributes:
        readings: Peta ``{basis: bacaan}``.
    """

    def __init__(self, readings: dict[str, str]) -> None:
        self.readings = {base: reading for base, reading in readings.items()
                         if base and reading and base != reading}
        # Basis terpanjang dulu agar 田中太郎 tidak terpotong menjadi 田中 + 太郎.
        alternatives = sorted(self.readings, key=len, reverse=True)
        self.pattern = re.compile("|".join(map(re.escape, alternatives))) if alternatives else None

    @classmethod
    def from_result(cls, result: TranslatedDocument) -> RubyIndex:
        """Gabungkan ruby dokumen dengan bacaan glosarium (glosarium menang)."""
        readings = {base: reading for base, reading in result.document.ruby.items()
                    if len(base) >= MIN_RUBY_BASE}
        readings.update({entry.surface: entry.reading for entry in result.glossary
                         if entry.reading})
        return cls(readings)

    def markup(self, text: str) -> str:
        """Escape ``text`` dan sisipkan ``<ruby>`` (dengan ``<rp>`` sebagai cadangan)."""
        if self.pattern is None:
            return _esc(text)
        parts, last = [], 0
        for match in self.pattern.finditer(text):
            base = match.group(0)
            parts.append(_esc(text[last:match.start()]))
            parts.append(f"<ruby>{_esc(base)}<rp>(</rp><rt>{_esc(self.readings[base])}</rt>"
                         "<rp>)</rp></ruby>")
            last = match.end()
        parts.append(_esc(text[last:]))
        return "".join(parts)


def _footer(result: TranslatedDocument, ui: dict) -> str:
    return "\n".join(part for part in (
        "<footer>",
        _glossary_table(result, ui),
        _stats_section(result, ui),
        _credits(result, ui),
        "</footer>",
    ) if part)


def _glossary_table(result: TranslatedDocument, ui: dict) -> str:
    if not result.glossary:
        return ""
    rows = []
    for entry in sorted_glossary(result.glossary):
        badge = "" if entry.confirmed else f'<span class="badge">{_esc(ui["review"])}</span>'
        rows.append(
            f'<tr><td lang="ja">{_esc(entry.surface)}</td>'
            f'<td lang="ja">{_esc(entry.reading)}</td>'
            f"<td>{_esc(rendered_form(entry, result))}{badge}</td>"
            f'<td>{_esc(ui["kinds"].get(entry.kind, entry.kind))}</td></tr>'
        )
    head = "".join(f"<th>{_esc(ui[key])}</th>" for key in ("surface", "reading", "used", "kind"))
    return (
        f'<section id="glossary"><h2>{_esc(ui["glossary"])}</h2><div class="scroll">'
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        "</div></section>"
    )


def count_statuses(paragraphs: list[TranslatedParagraph]) -> Counter[str]:
    """Jumlah kalimat per status, dihitung langsung dari hasil."""
    return Counter(s.status for p in paragraphs for s in p.sentences)


def count_engines(paragraphs: list[TranslatedParagraph]) -> Counter[str]:
    """Jumlah kalimat per mesin (kalimat tanpa mesin, mis. ``plain``, tidak dihitung)."""
    return Counter(s.engine for p in paragraphs for s in p.sentences if s.engine)


def _stats_section(result: TranslatedDocument, ui: dict) -> str:
    statuses = count_statuses(result.paragraphs)
    tiles = [_tile(sum(statuses.values()), ui["total"])]
    for status in STATUS_ORDER:
        if statuses.get(status):
            tiles.append(_tile(statuses[status], ui["status"][status],
                               bad=status in (STATUS_FAILED, STATUS_PARTIAL)))
    rows = []
    engines = count_engines(result.paragraphs)
    if engines:
        rows.append((ui["engines"], ", ".join(f"{name} ({n})" for name, n in engines.items())))
    for key, value in result.stats.items():
        if key not in HIDDEN_STATS:
            rows.append((ui["stat_labels"].get(key, key.replace("_", " ")),
                         format_stat(value, ui)))
    details = "".join(f"<dt>{_esc(label)}</dt><dd{_lang_ja(value)}>{_esc(value)}</dd>"
                      for label, value in rows)
    note = ""
    if statuses.get(STATUS_FAILED):
        note = f'<p class="credit">{_esc(ui["failed_note"])}</p>'
    return (
        f'<section id="stats"><h2>{_esc(ui["stats"])}</h2>'
        f'<div class="tiles">{"".join(tiles)}</div>'
        + (f'<dl class="kv">{details}</dl>' if details else "")
        + note + "</section>"
    )


def _tile(number: int, label: str, *, bad: bool = False) -> str:
    css = "tile bad" if bad else "tile"
    return f'<div class="{css}"><b>{number}</b><span>{_esc(label)}</span></div>'


def format_stat(value: object, ui: dict) -> str:
    """Ubah satu nilai statistik menjadi teks singkat yang mudah dibaca."""
    if isinstance(value, bool):
        return ui["yes"] if value else ui["no"]
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return ", ".join(f"{key}: {format_stat(item, ui)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return ", ".join(format_stat(item, ui) for item in value)
    return str(value)


def _credits(result: TranslatedDocument, ui: dict) -> str:
    lines = []
    for name in count_engines(result.paragraphs):
        note = ui["engine_notes"].get(name)
        label = ENGINE_NAMES.get(name, name)
        lines.append(f"{label} ({note})" if note else label)
    listing = "".join(f"<li>{_esc(line)}</li>" for line in lines)
    return (
        f'<section id="credits"><h2>{_esc(ui["credits"])}</h2>'
        + (f"<ul>{listing}</ul>" if listing else "")
        + f'<p class="credit">{_esc(ui["disclaimer"])}</p>'
        f'<p class="credit">{_esc(ui["made_by"])} {_esc(__version__)}</p></section>'
    )
