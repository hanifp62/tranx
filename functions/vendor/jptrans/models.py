"""Model data yang dipakai bersama oleh semua modul.

Modul lain hanya bertukar objek dari berkas ini, sehingga pembaca
(readers), mesin (engines), dan penulis (writers) tidak saling bergantung.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

# Modul data murni yang saat ini tidak menulis log; logger tetap ada sesuai aturan
# proyek "satu logger per modul", agar log yang kelak ditambahkan ikut hierarki jptrans.*.
logger = logging.getLogger(__name__)

# Jenis entitas yang dikenali.
PERSON = "PERSON"   # nama orang
PLACE = "PLACE"     # nama tempat
ORG = "ORG"         # organisasi, sekolah, kelompok
TERM = "TERM"       # istilah khusus karya: jurus, sihir, benda
CULTURE = "CULTURE"  # istilah budaya: onigiri, chuunibyou
ENTITY_KINDS = (PERSON, PLACE, ORG, TERM, CULTURE)

# Status terjemahan satu kalimat.
STATUS_OK = "ok"            # diterjemahkan dengan penanda utuh
STATUS_CACHED = "cached"    # diambil dari cache
STATUS_PRESUB = "presub"    # lewat jalur cadangan: nama Latin disisipkan dulu
STATUS_PLAIN = "plain"      # kalimat tanpa huruf Jepang, disalin apa adanya
STATUS_FAILED = "failed"    # semua mesin gagal; teks asli dipertahankan
STATUS_PARTIAL = "partial"  # jawaban terbaik masih bersisa huruf Jepang (tak ada yang bersih)

DIALOGUE_DASH = "- "
"""Awalan tiap baris pembicara di cue subtitle dua pembicara (selalu ``-`` ASCII)."""

# Tag format SRT. Satu sumber untuk semua regex tag di ``models`` dan ``segment``.
SIMPLE_TAG_NAMES = "[ibus]"
"""Nama tag format tanpa atribut (``<i>``, ``<b>``, ``<u>``, ``<s>``); pola regex."""
FORMAT_TAG_NAMES = rf"(?:{SIMPLE_TAG_NAMES}|font)"
"""Nama semua tag format SRT yang dikenal, termasuk ``<font ...>``; pola regex."""
_TAG_TAIL = r"(?:\s[^<>\n]*)?>"
OVERRIDE_TAG = r"\{\\[^{}\n]*\}"
"""Override posisi/gaya ASS di SRT (``{\\an8}``); tidak berpasangan."""
OPENING_TAG = rf"<{FORMAT_TAG_NAMES}{_TAG_TAIL}"
"""Tag pembuka, boleh beratribut (``<i>``, ``<font color="red">``)."""
CLOSING_TAG = rf"</{FORMAT_TAG_NAMES}{_TAG_TAIL}"
"""Tag penutup dengan bentuk yang sama dengan pembuka: ``</i>``, ``</i >``, dan juga
``</i atribut>`` (atribut di tag penutup diabaikan peramban, jadi tetap tag)."""
SIMPLE_OPENING_TAG = f"<{SIMPLE_TAG_NAMES}>"
"""Tag pembuka tanpa atribut; hanya tag ini yang boleh digabung lintas baris."""
FORMAT_TAG = f"{OVERRIDE_TAG}|{OPENING_TAG}|{CLOSING_TAG}"
"""Satu tag format SRT: override ``{\\an8}``, pembuka ``<i>``/``<font ...>``, atau penutup
``</i>``/``</font>``."""

LEADING_TAGS_RE = re.compile(f"(?:{OVERRIDE_TAG}|{OPENING_TAG})+", re.IGNORECASE)
"""Tag format SRT pembuka di awal baris: override ``{\\an8}`` dan ``<i>``/``<b>``/``<u>``/
``<s>``/``<font ...>``. Tag ini milik tampilan, jadi tanda dialog ditulis sesudahnya."""


def split_leading_tags(text: str) -> tuple[str, str]:
    """Pisah tag format pembuka di awal ``text`` dari isinya.

    Returns:
        ``(tag, sisa)``; ``tag`` kosong bila ``text`` tidak diawali tag.
    """
    match = LEADING_TAGS_RE.match(text)
    end = match.end() if match else 0
    return text[:end], text[end:]


_TAG_AT_RE = re.compile(rf"\s*(?:{FORMAT_TAG})", re.IGNORECASE)
_ANY_TAG_RE = re.compile(FORMAT_TAG, re.IGNORECASE)


def split_format_tags(text: str) -> tuple[str, str, str]:
    """Pisah tag format di tepi ``text``: ``(tag depan, isi, tag belakang)``.

    Tag depan dan belakang boleh pembuka maupun penutup. Spasi di antara tag dan
    isi dibuang (``<i> はい </i>`` memberi ``("<i>", "はい", "</i>")``), sehingga
    menyusun ulang ``depan + terjemahan + belakang`` tidak pernah memberi spasi
    sebelum ``</i>``. Teks yang isinya hanya tag memberi isi kosong dan semua
    tagnya di bagian depan.

    Tag tepi hanya dilepas bila isinya tidak lagi memuat tag. Bila pasangan tag
    hanya separuh berada di tepi (``<i>行くぞ</i>。``, ``今日は<i>魔法だ</i>``),
    melepas separuhnya membuat mesin menerima tag tanpa pasangan dan keluaran
    yang tidak seimbang. Dalam kasus itu hanya override ``{\\an8}`` di depan yang
    dilepas (override tidak berpasangan); sisanya, termasuk pasangan tag yang
    utuh, menjadi isi: ``{\\an8}<i>行くぞ</i>。`` memberi
    ``("{\\an8}", "<i>行くぞ</i>。", "")``.

    Pemindaian linear (tanpa regex yang mundur di seluruh teks), jadi cue raksasa
    dari unggahan tidak memperlambat server.

    Returns:
        Tiga bagian; menggabungkannya memberi ``text`` tanpa spasi di sekitar tag.
    """
    lead: list[str] = []
    ends: list[int] = []
    start = 0
    while match := _TAG_AT_RE.match(text, start):
        lead.append(match.group().strip())
        start = match.end()
        ends.append(start)
    trail: list[str] = []
    end = len(text)
    while True:
        while end > start and text[end - 1].isspace():
            end -= 1
        if end <= start or text[end - 1] not in ">}":
            break
        opener = text.rfind("<" if text[end - 1] == ">" else "{", start, end)
        if opener < 0 or not _ANY_TAG_RE.fullmatch(text, opener, end):
            break
        trail.insert(0, text[opener:end])
        end = opener
    body = text[start:end].strip()
    if body and _ANY_TAG_RE.search(body):
        overrides = 0
        while overrides < len(lead) and lead[overrides].startswith("{"):
            overrides += 1
        start = ends[overrides - 1] if overrides else 0
        return "".join(lead[:overrides]), text[start:].strip(), ""
    return "".join(lead), body, "".join(trail)


def strip_format_tags(text: str) -> str:
    """Buang semua tag format SRT dari ``text`` (untuk tampilan baca HTML)."""
    return _ANY_TAG_RE.sub("", text)


def dialogue_line(turn: str) -> str:
    """Satu baris pembicara: ``DIALOGUE_DASH`` sesudah tag pembuka (``{\\an8}- Ya.``)."""
    tags, body = split_leading_tags(turn)
    return tags + DIALOGUE_DASH + body.lstrip()


@dataclass(frozen=True)
class GlossaryEntry:
    """Satu entri glosarium: sumber kebenaran untuk sebuah nama atau istilah.

    Attributes:
        surface: Bentuk tulisan Jepang, misalnya ``田中`` atau ``紅蓮爆炎斬``.
        kind: Salah satu dari ``ENTITY_KINDS``.
        reading: Bacaan kana (``たなか``). Dipakai untuk romanisasi.
        romaji: Ejaan Latin pilihan pengguna. Mengalahkan romanisasi otomatis.
            Nama lengkap ditulis "Keluarga Diri" (``Yamada Tarō``).
        render_id: Bentuk akhir untuk bahasa Indonesia (mis. ``Akademi Sihir``).
        render_en: Bentuk akhir untuk bahasa Inggris.
        gloss_id: Arti untuk ditampilkan sekali pada kemunculan pertama (ID).
        gloss_en: Arti untuk kemunculan pertama (EN).
        gender: ``"m"``, ``"f"``, atau kosong. Dipakai mode honorifik localize.
        aliases: Bentuk tulisan lain untuk entitas yang sama.
        allow_compound: Izinkan pencocokan walau langsung diikuti kanji.
        confirmed: ``True`` bila sudah diperiksa pengguna atau dikunci otomatis.
        source: Asal entri: ``user``, ``ruby``, ``heuristic``, ``engine``, ...
        score: Skor keyakinan deteksi (0 sampai 1).
    """

    surface: str
    kind: str = PERSON
    reading: str = ""
    romaji: str = ""
    render_id: str = ""
    render_en: str = ""
    gloss_id: str = ""
    gloss_en: str = ""
    gender: str = ""
    aliases: tuple[str, ...] = ()
    allow_compound: bool = False
    confirmed: bool = True
    source: str = "user"
    score: float = 1.0

    def render_for(self, lang: str) -> str:
        """Kembalikan bentuk akhir khusus bahasa, atau string kosong."""
        return self.render_id if lang == "id" else self.render_en

    def gloss_for(self, lang: str) -> str:
        """Kembalikan gloss kemunculan pertama untuk bahasa sasaran."""
        return self.gloss_id if lang == "id" else self.gloss_en


@dataclass(frozen=True)
class Slot:
    """Satu entitas yang dimasking di dalam kalimat.

    Attributes:
        entry: Entri glosarium asal.
        honorific: Kunci romaji honorifik (``san``, ``senpai``), atau kosong.
        suffix: Sufiks Jepang setelah nama/honorifik (``達``, ``家``, ``駅``).
        parents: Unit wilayah yang mendahului tempat ini dalam satu alamat,
            terluar dulu, sebagai pasangan ``(entri, sufiks)``.
    """

    entry: GlossaryEntry
    honorific: str = ""
    suffix: str = ""
    parents: tuple[tuple[GlossaryEntry, str], ...] = ()


@dataclass
class Masked:
    """Hasil masking satu teks beserta peta slot penanda ``[[E#]]``."""

    original: str
    text: str
    slots: dict[int, Slot]


@dataclass
class Candidate:
    """Kandidat entitas hasil deteksi otomatis, sebelum masuk glosarium."""

    surface: str
    kind: str
    score: float
    reading: str = ""
    count: int = 0
    evidence: list[str] = field(default_factory=list)


@dataclass
class Paragraph:
    """Satu paragraf atau satu unit teks dari dokumen sumber.

    ``meta`` menyimpan data khusus format, misalnya nomor dan waktu
    subtitle (``{"index": 3, "start": "00:00:01,000", ...}``) atau
    nomor halaman dan balon pada komik.
    """

    text: str
    kind: str = "text"   # "text" atau "heading"
    meta: dict = field(default_factory=dict)


@dataclass
class Document:
    """Dokumen sumber yang sudah dibaca dan diurai.

    Attributes:
        title: Judul karya; menentukan berkas glosarium yang dipakai.
        paragraphs: Isi dokumen berurutan.
        ruby: Pasangan furigana ``{tulisan: bacaan}`` dari Aozora atau EPUB.
        source_path: Lokasi berkas asal.
        fmt: Format asal: ``txt``, ``aozora``, ``epub``, ``srt``, ``pages``.
    """

    title: str
    paragraphs: list[Paragraph]
    ruby: dict[str, str] = field(default_factory=dict)
    source_path: str = ""
    fmt: str = "txt"


@dataclass
class SentencePair:
    """Pasangan kalimat sumber dan terjemahannya.

    ``turn`` adalah nomor giliran pembicara di dalam paragraf (mulai 0). Hanya
    cue subtitle dua pembicara (``- はい`` / ``- いいえ``) yang punya giliran
    lebih dari satu; paragraf lain selalu 0.
    """

    source: str
    target: str
    engine: str = ""
    status: str = STATUS_OK
    turn: int = 0


@dataclass
class TranslatedParagraph:
    """Paragraf sumber beserta kalimat-kalimat terjemahannya."""

    source: Paragraph
    sentences: list[SentencePair] = field(default_factory=list)

    @property
    def is_dialogue(self) -> bool:
        """Paragraf ini cue dua pembicara atau lebih (ada kalimat dengan ``turn > 0``)."""
        return any(sentence.turn > 0 for sentence in self.sentences)

    def turn_sentences(self) -> list[list[SentencePair]]:
        """Kalimat yang dikelompokkan per giliran pembicara, berurutan.

        Paragraf biasa memberi satu kelompok tanpa kalimat bertarget kosong
        (atau tidak ada kelompok bila tidak ada terjemahan). Cue dua pembicara
        menyimpan semua kalimat, supaya jumlah baris tetap sama dengan jumlah
        pembicara walau ada terjemahan kosong.
        """
        dialogue = self.is_dialogue
        groups: dict[int, list[SentencePair]] = {}
        for sentence in self.sentences:
            if sentence.target or dialogue:
                groups.setdefault(sentence.turn, []).append(sentence)
        return [groups[turn] for turn in sorted(groups)]

    @property
    def turns(self) -> list[str]:
        """Terjemahan per giliran pembicara (kalimat dalam satu giliran dipisah spasi).

        Kalimat bertarget kosong diganti teks sumbernya, jadi tidak ada giliran
        yang lenyap dari cue dua pembicara.
        """
        return [" ".join(s.target or s.source for s in group).strip()
                for group in self.turn_sentences()]

    @property
    def target(self) -> str:
        """Teks terjemahan utuh paragraf ini.

        Cue dua pembicara menjadi satu baris per giliran berawalan
        ``DIALOGUE_DASH`` (``- Ya.\\n- Tidak.``), ditaruh sesudah tag format
        pembuka (``dialogue_line``); paragraf lain satu baris.
        """
        if self.is_dialogue:
            return "\n".join(dialogue_line(turn) for turn in self.turns)
        return " ".join(s.target for s in self.sentences if s.target).strip()


@dataclass
class TranslatedDocument:
    """Hasil akhir pipeline, siap ditulis oleh writer mana pun."""

    document: Document
    paragraphs: list[TranslatedParagraph]
    source_lang: str
    target_lang: str
    glossary: list[GlossaryEntry] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def target(self) -> str:
        """Teks terjemahan gabungan seluruh paragraf, dipisah baris kosong."""
        return "\n\n".join(p.target or p.source.text for p in self.paragraphs)
