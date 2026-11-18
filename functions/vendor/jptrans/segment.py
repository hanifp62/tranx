"""Segmentasi teks Jepang: dokumen → paragraf → kalimat → batch permintaan.

Aturan kalimat dirancang untuk light novel dan web novel:

- Kalimat berakhir pada 。！？!? hanya bila tidak berada di dalam kurung
  (「」『』（）【】〈〉《》).
- Kutipan 「」『』 yang selesai dengan tanda akhir (「はい。」) menutup kalimat,
  kecuali langsung diikuti partikel kutipan と/って (「本当に？！」と彼は言った。).
  Kurung biasa (彼（本当に？）は) tidak menutup kalimat.
- Elipsis …/‥ tidak memutus kalimat (これは……本当？ tetap satu kalimat).
- Tanda akhir berturut-turut (！？, 。」) tetap bagian kalimat yang sama.
- Kutipan tanpa penutup tidak boleh menelan sisa paragraf: bagian sejak
  kurung yang tak tertutup disegmentasi ulang tanpa menghitung kurung.
- Cue subtitle dua pembicara (``- はい\\n- いいえ``) dipecah per giliran oleh
  ``split_speaker_turns`` sebelum dipecah per kalimat, dan tag format SRT di tepi
  potongan kalimat ditempelkan ke kalimatnya oleh ``attach_format_tags``.
- Tanda pisah di akhir baris yang disusul tanda pisah di awal baris berikutnya
  (``行こうと思ったけど—\\n—やっぱりやめた。``) adalah sambungan kalimat satu pembicara,
  bukan dialog (``continues_with_dash``); sambungannya ditulis sekali. Di cue yang baris
  pertamanya bertanda, tanda panjang + spasi (``— 行こうと—\\n— やめろ！``) tetap giliran baru.

Semua fungsi murni dan tidak mengubah isi teks; menggabungkan kembali hasil
``split_sentences`` memberi paragraf asli tanpa spasi di tepi kalimat.
"""

from __future__ import annotations

import logging
import re

from .errors import ConfigError
from .models import (
    CLOSING_TAG, OPENING_TAG, OVERRIDE_TAG, SIMPLE_OPENING_TAG, split_leading_tags,
)
from .protect import EXACT_TOKEN_RE

logger = logging.getLogger(__name__)

OPENING_BRACKETS = "「『（【〈《"
CLOSING_BRACKETS = "」』）】〉》"
QUOTE_CLOSERS = "」』"
"""Penutup kutipan dialog; kurung biasa （） tidak pernah mengakhiri kalimat."""
SENTENCE_ENDERS = "。．！？!?‼⁇⁈⁉"
ELLIPSES = "…‥"
QUOTE_PARTICLES = ("と", "って")
"""Partikel setelah 」 yang menandakan kutipan masih bagian kalimat (と言った, って)."""
_NON_QUOTATIVE_TO_WORDS = (
    "とりあえず",
    "とにかく",
    "ところで",
    "とっさに",
    "とうとう",
    "とても",
    "とはいえ",
    "ともかく",
    "ときどき",
    "とたんに",
)
_QUOTE_CASE_TAILS = ("が", "を", "とは", "とか", "なんて", "など")

DIALOGUE_DASHES = "-－―‐\u2013\u2014"
"""Tanda dialog subtitle di awal baris: ``-`` ASCII, ``－`` lebar penuh, ``―``, ``‐``,
en dash (U+2013), dan em dash (U+2014)."""

LONG_DASHES = "\u2013\u2014\u2015"
"""Tanda pisah panjang (en dash, em dash, ``―``). Di awal baris hanya tanda dialog bila baris
berisi pertama cue juga bertanda (tanpa gaya Netflix), karena tanda ini juga dipakai untuk
menyambung kalimat (``けど—\\n—やっぱり``, ``彼は言った\\n— 本当だ。``)."""

HYPHEN_DASHES = "-－‐"
"""Tanda dialog jenis tanda hubung; hanya kelas ini yang mengenal gaya Netflix."""

KANA_DASH = "ー"
"""Tanda panjang katakana (U+30FC) yang dipakai hasil OCR sebagai tanda dialog (``ー はい``).
Hanya dihitung bila SEMUA baris cue diawali ``ー`` + spasi (``uses_kana_dash``)."""

_KANA_DASH_RE = re.compile(r"ー[ \u3000]+[^\sー]")
_SPACES = " \u3000"
_OPENING_TAG_RE = re.compile(f"{OVERRIDE_TAG}|{OPENING_TAG}", re.IGNORECASE)
_CLOSING_TAG_RE = re.compile(CLOSING_TAG, re.IGNORECASE)
_CLOSING_TAGS_RE = re.compile(f"(?:{CLOSING_TAG})+", re.IGNORECASE)
_SIMPLE_OPEN_RE = re.compile(f"(?:{SIMPLE_OPENING_TAG})+", re.IGNORECASE)
_TAG_NAME_RE = re.compile(r"</?([a-z]+)", re.IGNORECASE)

_CHUNK_DELIMITERS = "、，,"
_DIGITS = "0123456789０１２３４５６７８９"
_CJK_START = "\u2e80"
"""Titik awal blok CJK (radikal, kana, kanji, tanda baca lebar penuh)."""


def split_paragraphs(text: str) -> list[str]:
    """Pisah teks menjadi paragraf: satu baris tidak kosong = satu paragraf.

    Novel Jepang memakai satu baris per paragraf, jadi baris kosong hanya
    pemisah. Spasi (termasuk spasi lebar penuh U+3000 untuk indentasi) di
    kedua tepi baris dibuang; baris yang hanya berisi spasi diabaikan.

    Args:
        text: Isi dokumen dengan baris baru apa pun (``\\n``, ``\\r\\n``).

    Returns:
        Daftar paragraf tanpa indentasi, berurutan.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def unwrap_lines(text: str) -> str:
    """Gabungkan baris yang patah hanya karena tampilan menjadi satu baris.

    Subtitle dua baris (``今日は佐藤先輩と\\n魔法の練習``) dan teks OCR memecah
    satu kalimat di tengah. Bila tiap baris dikirim terpisah, mesin
    menerjemahkan dua potongan tanpa konteks. Bahasa Jepang tidak memakai
    spasi antarkata, jadi sambungan antara dua huruf CJK tidak diberi spasi;
    sambungan lain (teks Latin, baris dialog ``- はい``) diberi satu spasi.

    Args:
        text: Isi satu paragraf, boleh mengandung ``\\n``.

    Returns:
        Teks satu baris; baris kosong dibuang.
    """
    joined = ""
    for line in (part.strip() for part in text.split("\n")):
        if not line:
            continue
        if joined:
            both_cjk = _is_cjk_join(joined[-1]) and _is_cjk_join(line[0])
            joined += "" if both_cjk else " "
        joined += line
    return joined


def _is_cjk_join(ch: str) -> bool:
    return ch >= _CJK_START or ch in "…‥―\u2014"


def dialogue_line_text(line: str, *, kana_dash: bool = False) -> str | None:
    """Isi baris dialog subtitle tanpa tandanya, atau ``None`` bila bukan baris dialog.

    Baris dialog diawali satu tanda dari ``DIALOGUE_DASHES``, boleh disusul
    spasi (``- はい``, ``－はい``, ``―　はい``, ``— はい``), lalu isi yang tidak kosong.
    Yang bukan tanda dialog: tanda ganda (``――そうか``, ``——``, gaya jeda di naskah
    Jepang), tanda yang langsung menempel ke angka (``-5度``, ``–5度``), dan tanda
    tanpa isi. Tag format SRT pembuka (``{\\an8}- はい``, ``<i>- はい</i>``) dilewati
    saat mencari tanda dan dikembalikan di depan isi (``{\\an8}はい``).

    Args:
        line: Satu baris yang sudah dibuang spasi tepinya.
        kana_dash: Terima juga ``ー`` + spasi (``ー はい``) sebagai tanda. Pemanggil
            hanya menyalakannya bila semua baris cue memakai bentuk itu
            (``uses_kana_dash``), karena ``ー`` di awal kalimat biasanya bagian kata
            (``ーっ``, ``ーー``).
    """
    tags, body = split_leading_tags(line)
    if kana_dash and _KANA_DASH_RE.match(body):
        return tags + body[1:].strip(_SPACES)
    if len(body) < 2 or body[0] not in DIALOGUE_DASHES:
        return None
    if body[1] in DIALOGUE_DASHES or body[1] in _DIGITS:
        return None
    rest = body[1:].strip()
    return tags + rest if rest else None


def uses_kana_dash(lines: list[str]) -> bool:
    """Semua baris berisi diawali ``ー`` + spasi + isi (sesudah tag pembuka), minimal dua baris.

    Gaya OCR menulis tanda dialog sebagai ``ー はい`` / ``ー いいえ``. Satu baris saja
    yang tidak memakai bentuk itu (``ーっ、痛い！``, ``ーー``, baris tanpa tanda, atau
    tanda dialog lain) mematikan aturan ini untuk seluruh cue.
    """
    content = [line for line in lines if line and not is_mark_only_line(line)]
    return len(content) >= 2 and all(
        _KANA_DASH_RE.match(split_leading_tags(line)[1]) for line in content)


def is_mark_only_line(line: str) -> bool:
    """Baris yang hanya berisi tag format pembuka, tanda dialog, dan spasi (``- ``, ``{\\an8}``)."""
    return not split_leading_tags(line)[1].strip(DIALOGUE_DASHES + " \u3000")


def split_speaker_turns(text: str) -> list[str]:
    """Pisah cue subtitle menjadi giliran pembicara, tiap giliran satu baris.

    Setiap baris yang diawali tanda dialog (``dialogue_line_text``) memulai
    giliran baru; baris tanpa tanda ikut giliran sebelumnya (``join_tagged_lines``).
    Baris pertama tanpa tanda juga satu giliran (gaya Netflix, ``本当に？\\n- 本当だよ。``),
    tetapi tanda ``LONG_DASHES`` hanya memulai giliran bila baris berisi pertama
    juga bertanda, jadi ``彼は言った\\n— 本当だ。`` tetap satu giliran. Baris sambungan
    (``continues_with_dash``, ``けど—\\n—やっぱり``) langsung digabung dengan
    ``join_dash_connector``; baris tanda saja di antaranya dilewati (``_absorb_connector``).
    Di cue bertanda, elipsis (``— そうか……\\n— うん。``) dan tanda panjang + spasi sesudah
    tanda panjang (``— 行こうと—\\n— やめろ！``) bukan sambungan. ``ー`` + spasi hanya tanda bila
    semua baris memakainya (``uses_kana_dash``). Tanda dialog hanya dibuang bila hasilnya minimal
    dua giliran; cue satu giliran (``- はい``, ``— けど—\\n—やめた。``) tetap membawa tandanya.

    Baris yang hanya berisi tanda atau tag (``is_mark_only_line``) tidak pernah
    menjadi giliran: sebelum baris berisi pertama, tandanya dibuang dan tagnya
    pindah ke depan baris berisi itu (``{\\an8}\\n- はい``); di cue dua
    pembicara baris seperti itu dibuang. Cue yang isinya hanya tanda
    dikembalikan apa adanya lewat ``unwrap_lines``.

    Args:
        text: Isi satu cue, boleh mengandung ``\\n``.

    Returns:
        Daftar giliran tanpa ``\\n``; kosong bila ``text`` kosong.
    """
    lines = [part.strip() for part in text.split("\n")]
    kana_dash = uses_kana_dash(lines)
    carried = ""
    kept: list[str] = []
    turns: list[list[str]] = []
    long_marks = False
    for line in lines:
        if not line:
            continue
        if is_mark_only_line(line) and not turns:
            carried += split_leading_tags(line)[0]
            continue
        if carried:
            line, carried = carried + line, ""
        if kept and _absorb_connector(kept, turns[-1], line, marked_cue=long_marks):
            continue
        kept.append(line)
        spoken = dialogue_line_text(line, kana_dash=kana_dash)
        if not turns:
            long_marks = spoken is not None
        elif not long_marks and split_leading_tags(line)[1][:1] in LONG_DASHES:
            spoken = None
        if spoken is not None or not turns:
            turns.append([line if spoken is None else spoken])
        else:
            turns[-1].append(line)
    if not turns:
        joined = unwrap_lines(text)
        return [joined] if joined else []
    if len(turns) < 2:
        return [join_tagged_lines(kept)]
    return [join_tagged_lines([line for line in lines if not is_mark_only_line(line)])
            for lines in turns]


def _absorb_connector(kept: list[str], turn: list[str], line: str, *,
                      marked_cue: bool) -> bool:
    """Gabungkan ``line`` ke baris berisi terakhir bila ``continues_with_dash`` benar.

    Baris yang isinya hanya tanda (``is_mark_only_line``) di antara kedua bagian
    sambungan dilewati saat membandingkan dan dibuang dari ``kept`` dan ``turn``; tag
    pembukanya dipindah ke depan ``line``. Jadi ``けど—\\n—\\n—やっぱり`` menjadi
    ``けど—やっぱり``, bukan ``けど— — —やっぱり``. Baris tanda seperti itu selalu ada di
    ekor ``turn`` karena tidak pernah memulai giliran.

    Args:
        kept: Baris berisi cue sejauh ini (diubah di tempat).
        turn: Giliran terakhir (diubah di tempat).
        line: Baris baru.
        marked_cue: Baris berisi pertama cue bertanda dialog (lihat ``continues_with_dash``).

    Returns:
        ``True`` bila ``line`` sudah digabung dan tidak perlu diproses lagi.
    """
    marks = 0
    while marks < len(kept) and is_mark_only_line(kept[-1 - marks]):
        marks += 1
    if marks == len(kept):
        return False
    if not continues_with_dash(kept[-1 - marks], line, marked_cue=marked_cue):
        return False
    if marks:
        line = "".join(split_leading_tags(mark)[0] for mark in kept[-marks:]) + line
        del kept[-marks:], turn[-marks:]
    kept[-1] = join_dash_connector(kept[-1], line)
    turn[-1] = join_dash_connector(turn[-1], line)
    return True


def continues_with_dash(previous: str, line: str, *, marked_cue: bool = False) -> bool:
    """``line`` menyambung kalimat ``previous`` lewat tanda pisah, bukan giliran baru.

    Konvensi subtitle: tanda pisah di akhir baris yang disusul tanda pisah di awal
    baris berikutnya adalah satu kalimat yang dipatah (``行こうと思ったけど—\\n—やっぱり``).

    - Kelas ``LONG_DASHES``: ``line`` diawali tanda panjang dan ``previous`` diakhiri
      tanda panjang. Elipsis di akhir ``previous`` (``それは……\\n—嘘だ``)
      hanya sambungan bila ``marked_cue`` salah dan ``previous`` bukan baris dialog: di cue
      yang baris berisi pertamanya bertanda (``— そうか……\\n— うん。``) elipsis berarti
      pembicara menggantung lalu pembicara lain menjawab, jadi tetap dua giliran. Di cue
      seperti itu tanda panjang + spasi di awal ``line`` (``— 行こうと—\\n— やめろ！``) adalah
      penanda pembicara baru (ucapan dipotong orang lain), bukan sambungan; hanya tanda
      tanpa spasi (``— 行こうと—\\n—やっぱりやめた。``) yang menyambung. Spasi berarti whitespace
      apa pun (``str.isspace``: juga NBSP, tab, spasi tipis), sama dengan ``dialogue_line_text``.
      Di cue campuran (baris pertama tanpa tanda, ``行こうと—\\n— やめろ！``) spasi tidak dihitung.
    - Kelas ``HYPHEN_DASHES``: ``previous`` diakhiri tanda hubung dan bukan baris
      dialog, dan ``line`` adalah baris dialog bertanda hubung (``でも-\\n-やめた。``).
      Di cue yang barisnya bertanda (``- 行こうと-\\n- やめろ！``) tanda di akhir baris
      berarti ucapan dipotong pembicara lain, jadi tetap dua giliran. Angka negatif
      (``-5度``) bukan sambungan.

    Tag penutup di akhir ``previous`` dan tag pembuka di awal ``line`` dilewati.
    Baris yang isinya hanya tanda (``is_mark_only_line``), di sisi mana pun, tidak
    pernah dihitung sambungan.
    """
    body = split_leading_tags(line)[1]
    if is_mark_only_line(line) or is_mark_only_line(previous):
        return False
    tail = previous[:trailing_tags_start(previous, _CLOSING_TAG_RE)].rstrip()
    if not tail:
        return False
    if body[0] in LONG_DASHES:
        if tail[-1] in ELLIPSES:
            return not marked_cue and dialogue_line_text(previous) is None
        if marked_cue and len(body) > 1 and body[1].isspace():
            # Penanda pembicara "— A" di cue bertanda: ucapan sebelumnya dipotong orang lain.
            return False
        return tail[-1] in LONG_DASHES
    return (body[0] in HYPHEN_DASHES and tail[-1] in HYPHEN_DASHES
            and dialogue_line_text(line) is not None and dialogue_line_text(previous) is None)


def join_dash_connector(previous: str, line: str) -> str:
    """Sambung ``line`` ke ``previous`` sehingga tanda sambungnya hanya tertulis sekali.

    Tanda pisah di awal ``line`` (seluruh deretannya, ``――``) dan whitespace sesudahnya
    (spasi, U+3000, NBSP, tab) dibuang, lalu kedua baris ditempel tanpa spasi: tanda di
    akhir ``previous`` sudah menjadi pemisahnya (``けど—`` + ``—やっぱり`` memberi
    ``けど—やっぱり``). Tag yang sama
    di kedua sisi sambungan digabung seperti ``join_tagged_lines``. Dipanggil hanya
    bila ``continues_with_dash(previous, line)`` benar.
    """
    tags, body = split_leading_tags(line)
    dashes = LONG_DASHES if body[:1] in LONG_DASHES else HYPHEN_DASHES
    previous, line = _merge_tag_seam(previous, tags + body.lstrip(dashes).lstrip())
    return previous + line


def join_tagged_lines(lines: list[str]) -> str:
    """``unwrap_lines`` untuk baris subtitle yang masing-masing dibungkus tag yang sama.

    ``<i>今日は</i>`` / ``<i>練習だ</i>`` menjadi ``<i>今日は練習だ</i>``: tag penutup di
    akhir satu baris dan tag pembuka sederhana yang sama (``<i>``, ``<b>``, ``<u>``,
    ``<s>`` tanpa atribut) di awal baris berikutnya dibuang (``_merge_tag_seam``),
    sehingga mesin tidak menerima ``今日は</i> <i>練習だ``. Tag dengan atribut
    (``<font color=...>``) atau urutan yang berbeda tidak digabung.

    Args:
        lines: Baris satu giliran, sudah dibuang spasi tepinya.

    Returns:
        Teks satu baris hasil ``unwrap_lines``.
    """
    merged: list[str] = []
    for line in lines:
        if merged:
            merged[-1], line = _merge_tag_seam(merged[-1], line)
        merged.append(line)
    return unwrap_lines("\n".join(merged))


def _merge_tag_seam(previous: str, line: str) -> tuple[str, str]:
    """Buang tag penutup di akhir ``previous`` dan tag pembuka yang sama di awal ``line``.

    Hanya bila urutan nama tagnya cermin (``</b></i>`` dengan ``<i><b>``) dan kedua sisi
    masih punya isi; selain itu kedua baris dikembalikan apa adanya.
    """
    cut = trailing_tags_start(previous, _CLOSING_TAG_RE)
    closing = previous[cut:]
    opening = _SIMPLE_OPEN_RE.match(line)
    if (closing and opening
            and _tag_names(closing) == _tag_names(opening.group())[::-1]
            and previous[:cut].strip() and line[opening.end():].strip()):
        return previous[:cut].rstrip(), line[opening.end():].lstrip()
    return previous, line


def trailing_tags_start(text: str, tag_re: re.Pattern[str]) -> int:
    """Posisi awal deretan tag ``tag_re`` yang menempel di akhir ``text`` (tanpa spasi).

    Dipindai mundur satu tag demi satu tag dengan ``rfind`` dan ``fullmatch``, jadi
    waktunya linear. Regex berjangkar ``(...)+$`` dengan ``search`` dicoba dari tiap
    posisi dan menjadi kuadratik pada cue raksasa berisi ribuan tag. Awal satu tag
    selalu ``<`` atau ``{`` terakhir sebelum ``>`` atau ``}`` penutupnya (atribut dan
    override tidak boleh memuatnya), jadi hasilnya sama dengan regex itu.

    Args:
        text: Teks yang diperiksa.
        tag_re: Pola satu tag (dicocokkan dengan ``fullmatch``).

    Returns:
        ``len(text)`` bila ``text`` tidak diakhiri tag seperti itu.
    """
    end = len(text)
    while end and text[end - 1] in ">}":
        opener = text.rfind("<" if text[end - 1] == ">" else "{", 0, end)
        if opener < 0 or not tag_re.fullmatch(text, opener, end):
            break
        end = opener
    return end


def _tag_names(tags: str) -> list[str]:
    """Nama tag berurutan, huruf kecil (``</b></i>`` memberi ``["b", "i"]``)."""
    return [name.lower() for name in _TAG_NAME_RE.findall(tags)]


def attach_format_tags(pieces: list[str]) -> list[str]:
    """Tempelkan tag format SRT di tepi potongan kalimat ke kalimat pemiliknya.

    ``split_sentences`` memotong sesudah tanda akhir, jadi ``<i>田中さん、早く！</i>``
    memberi ``<i>田中さん、早く！`` dan ``</i>`` sebagai kalimat sendiri. Di sini tag
    penutup di awal potongan pindah ke akhir potongan sebelumnya, dan tag pembuka di
    akhir potongan pindah ke awal potongan berikutnya; potongan yang lalu kosong
    dibuang. Hasilnya tiap kalimat membawa tagnya sendiri (``<i>田中さん、早く！</i>``)
    dan pipeline bisa melepasnya sebelum dikirim ke mesin (``models.split_format_tags``).

    Args:
        pieces: Kalimat hasil ``split_sentences`` dari satu giliran.

    Returns:
        Kalimat tanpa potongan yang isinya hanya tag (kecuali semuanya hanya tag).
    """
    result = list(pieces)
    for index in range(1, len(result)):
        closing = _CLOSING_TAGS_RE.match(result[index])
        owner = next((i for i in range(index - 1, -1, -1) if result[i]), None)
        if closing and owner is not None:
            result[owner] += closing.group()
            result[index] = result[index][closing.end():].lstrip()
    for index in range(len(result) - 2, -1, -1):
        cut = trailing_tags_start(result[index], _OPENING_TAG_RE)
        owner = next((i for i in range(index + 1, len(result)) if result[i]), None)
        if cut < len(result[index]) and owner is not None:
            result[owner] = result[index][cut:] + result[owner]
            result[index] = result[index][:cut].rstrip()
    kept = [piece for piece in result if piece]
    return kept if kept else [piece for piece in pieces if piece]


def split_sentences(paragraph: str) -> list[str]:
    """Pisah satu paragraf menjadi kalimat.

    Args:
        paragraph: Satu paragraf hasil ``split_paragraphs``.

    Returns:
        Daftar kalimat tanpa spasi tepi; kalimat kosong dibuang.
    """
    ends, unclosed_at = _sentence_ends(paragraph, track_brackets=True)
    if unclosed_at is not None:
        logger.debug("kurung tanpa penutup di posisi %d; segmentasi ulang", unclosed_at)
        tail_ends, _ = _sentence_ends(paragraph[unclosed_at:], track_brackets=False)
        ends += [unclosed_at + end for end in tail_ends]
    return _cut(paragraph, ends)


def make_batches(items: list[str], max_chars: int, max_items: int) -> list[list[int]]:
    """Kelompokkan indeks item menjadi batch permintaan ke mesin.

    Panjang batch dihitung sebagai jumlah panjang item ditambah satu pemisah
    ``\\n`` di antara item. Item yang sendirian sudah melebihi ``max_chars``
    tetap menjadi batch sendiri; pemanggil yang memotongnya.

    Args:
        items: Teks yang akan dikirim, berurutan.
        max_chars: Batas karakter per permintaan.
        max_items: Batas jumlah item per permintaan.

    Returns:
        Daftar batch; tiap batch berisi indeks ``items`` yang berurutan.

    Raises:
        ConfigError: ``max_chars`` atau ``max_items`` kurang dari 1.
    """
    _require_positive(max_chars=max_chars, max_items=max_items)
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for index, item in enumerate(items):
        if current and (size + 1 + len(item) > max_chars or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        size += len(item) + (1 if current else 0)
        current.append(index)
    if current:
        batches.append(current)
    return batches


def chunk_long_text(text: str, max_chars: int) -> list[str]:
    """Potong teks yang terlalu panjang menjadi potongan ``<= max_chars``.

    Titik potong dipilih di 、 atau spasi terakhir dalam jendela ``max_chars``
    (tanda tetap ikut potongan kiri). Bila tidak ada, teks dipotong paksa,
    tetapi tidak pernah di tengah penanda ``[[E1]]``. Menggabungkan hasilnya
    dengan ``"".join`` memberi teks asli.

    Args:
        text: Kalimat (boleh sudah dimasking).
        max_chars: Panjang maksimum tiap potongan.

    Returns:
        Daftar potongan; kosong bila ``text`` kosong.

    Raises:
        ConfigError: ``max_chars`` kurang dari 1.
    """
    _require_positive(max_chars=max_chars)
    chunks: list[str] = []
    start = 0
    while len(text) - start > max_chars:
        cut = _chunk_cut(text, start, start + max_chars)
        chunks.append(text[start:cut])
        start = cut
    if start < len(text):
        chunks.append(text[start:])
    return chunks


def _sentence_ends(text: str, *, track_brackets: bool) -> tuple[list[int], int | None]:
    """Cari posisi akhir tiap kalimat.

    Returns:
        Pasangan (posisi akhir kalimat, posisi kurung pembuka yang tidak
        pernah ditutup atau ``None``).
    """
    ends: list[int] = []
    depth = 0
    unclosed_at: int | None = None
    index = 0
    while index < len(text):
        ch = text[index]
        candidate = False
        if track_brackets and ch in OPENING_BRACKETS:
            if depth == 0:
                unclosed_at = index
            depth += 1
        elif track_brackets and ch in CLOSING_BRACKETS and depth > 0:
            depth -= 1
            candidate = depth == 0 and ch in QUOTE_CLOSERS and _ends_with_terminal(text[:index])
        elif ch in SENTENCE_ENDERS and depth == 0 and not _is_inline_symbol(text, index):
            candidate = True
        if depth == 0:
            unclosed_at = None
        if candidate:
            end = _absorb_terminals(text, index + 1)
            if not _continues_after_quote(text, end):
                ends.append(end)
                index = end
                continue
        index += 1
    return ends, unclosed_at


def _ends_with_terminal(text: str) -> bool:
    """Periksa apakah isi kutipan diakhiri tanda akhir atau elipsis (。」, ……」)."""
    inner = text.rstrip(CLOSING_BRACKETS)
    return bool(inner) and inner[-1] in SENTENCE_ENDERS + ELLIPSES


def _absorb_terminals(text: str, index: int) -> int:
    """Lewati tanda akhir dan kurung penutup berturut-turut (！？, 。」)."""
    while index < len(text) and text[index] in SENTENCE_ENDERS + CLOSING_BRACKETS:
        index += 1
    return index


def _is_inline_symbol(text: str, index: int) -> bool:
    ch = text[index]
    if ch == "!" and text[index + 1:index + 2] == "=":
        return True
    if ch == "．" and 0 < index < len(text) - 1:
        return text[index - 1] in _DIGITS and text[index + 1] in _DIGITS
    return False


def _continues_after_quote(text: str, end: int) -> bool:
    """Periksa apakah kutipan yang baru ditutup masih berlanjut sebagai satu kalimat."""
    if text[end - 1] not in CLOSING_BRACKETS:
        return False
    tail = text[end:].lstrip()
    if tail.startswith(_NON_QUOTATIVE_TO_WORDS):
        return False
    if tail.startswith(QUOTE_PARTICLES):
        return True
    if end < len(text) and not text[end].isspace():
        if tail.startswith(_QUOTE_CASE_TAILS):
            return True
        if tail.startswith("は") and tail[1:2] not in "いあぁっは！!？?、。":
            return True
    return False


def _cut(text: str, ends: list[int]) -> list[str]:
    """Potong teks pada posisi ``ends`` dan buang potongan kosong."""
    pieces = []
    start = 0
    for end in [*ends, len(text)]:
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        start = end
    return pieces


def _chunk_cut(text: str, start: int, limit: int) -> int:
    """Pilih posisi potong di ``(start, limit]`` untuk ``chunk_long_text``."""
    window = text[start:limit]
    delimiter = max(
        (i for i, ch in enumerate(window) if ch in _CHUNK_DELIMITERS or ch.isspace()),
        default=-1,
    )
    if delimiter >= 0:
        return start + delimiter + 1
    for marker in EXACT_TOKEN_RE.finditer(text, start):
        if marker.start() >= limit:
            break
        if marker.end() > limit:
            # Penanda yang lebih panjang dari max_chars dibiarkan utuh.
            return marker.start() if marker.start() > start else marker.end()
    return limit


def _require_positive(**limits: int) -> None:
    """Lempar ``ConfigError`` bila ada batas yang kurang dari 1."""
    for name, value in limits.items():
        if value < 1:
            raise ConfigError(f"{name} harus minimal 1, bukan {value}")
