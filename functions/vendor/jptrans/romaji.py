"""Romanisasi kana ke huruf Latin (Hepburn sesuai pedoman pemerintah Jepang 2025).

Tabel dibuat sendiri (bebas lisensi, tanpa pykakasi yang GPL). Aturan yang
dipakai mengikuti 令和7年内閣告示第4号 dan Q&A Bunka-cho (Feb 2026):

- ン selalu ``n`` (Shinbashi, bukan Shimbashi). Sebelum vokal atau ``y``
  diberi apostrof agar tidak ambigu: けんいち → ``ken'ichi``.
- Sokuon (っ/ッ) menggandakan konsonan berikutnya: がっこう → ``gakkō``.
  **Pilihan desain:** sebelum ``ch`` ditulis ``tch`` (マッチャ → ``matcha``),
  bukan ``cch`` seperti contoh resmi ``maccha``, karena ``tch`` lebih alami
  bagi pembaca dan merupakan ejaan internasional yang juga dihormati pedoman.
  Sokuon di akhir kata atau sebelum vokal (あっ) tidak ditulis.
- Tiga mode vokal panjang:

  ``macron``
      おう/おお → ō, うう → ū, ああ → ā, ええ → ē, ー → makron vokal sebelumnya
      (サーベル → ``sāberu``). えい tetap ``ei`` dan いい tetap ``ii``.
  ``kana``
      Ditulis apa adanya per kana; ー mengulang vokal (``saaberu``, ``satou``).
  ``plain``
      Tanda panjang dibuang (``tokyo``, ``sato``). Tidak resmi dan bisa
      bertabrakan (おおの dan おの sama-sama ``ono``), jadi kunci glosarium
      harus tetap bacaan kana, bukan hasil romanisasi.

Batas morfem: aturan kana tidak bisa melihat batas kata di dalam bacaan.
``おう`` selalu digabung menjadi ō (こういち ``Kōichi``, こうえん ``kōen``, そうえん
``sōen``, とうえい ``tōei``), KECUALI ``うえ``/``うお`` yang berada di akhir kata
(sebelum spasi, ・, tanda baca, atau akhir teks) atau yang menutup bacaan nama
keluarga di ``surnames.json`` (いのうえ ``Inoue``, juga いのうえさん). Kata kerja
seperti おもう tetap menjadi ``omō``. Penggabungan sebelum え/お hanya untuk
hiragana: ``ウエ``/``ウオ`` katakana adalah bunyi we/wo kata serapan
(ソフトウエア ``sofutouea``, オウエン ``Ouen``), jadi tetap dua suku kata.

Suku kata yang sudah dipanjangkan tidak menyerap vokal berikutnya: ほうおう
menjadi ``hōō`` (macron), ``hoo`` (plain), ``houou`` (kana). Mode plain selalu
sama dengan mode macron tanpa makron.

Nama asing katakana (``romanize_foreign``): tiap bagian nama (dipisah ・) dicari
di ``data/foreign_names.json`` (アリス → Alice); bagian yang tidak ada memakai
Hepburn. ``looks_japanese`` menandai bagian nama katakana yang tampak nama Jepang
(ハルカ, ユミコ); bagian di luar kamus yang tidak tampak Jepang ditanyakan ke mesin
(``pipeline.needs_foreign_lookup``).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache

from . import data
from .errors import ConfigError
from .textnorm import hira_to_kata, kata_to_hira, widen_halfwidth_kana

logger = logging.getLogger(__name__)

MODES = ("macron", "kana", "plain")

SOKUON = "ッ"
LONG_MARK = "ー"
SYLLABIC_N = "ン"

_MONOGRAPHS: dict[str, str] = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヰ": "i", "ヱ": "e", "ヲ": "o", SYLLABIC_N: "n",
    "ヴ": "vu", "ヷ": "va", "ヸ": "vi", "ヹ": "ve", "ヺ": "vo",
    # Kana kecil yang berdiri sendiri (ねぇ, ちょっ, ヶ月) dan katakana fonetis Ainu (ㇰ-ㇿ).
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ャ": "ya", "ュ": "yu", "ョ": "yo", "ヮ": "wa", "ヵ": "ka", "ヶ": "ke",
    "ㇰ": "ku", "ㇱ": "shi", "ㇲ": "su", "ㇳ": "to", "ㇴ": "nu",
    "ㇵ": "ha", "ㇶ": "hi", "ㇷ": "fu", "ㇸ": "he", "ㇹ": "ho",
    "ㇺ": "mu", "ㇻ": "ra", "ㇼ": "ri", "ㇽ": "ru", "ㇾ": "re", "ㇿ": "ro",
}

_KATAKANA_DAKUTEN = str.maketrans(
    "カキクケコサシスセソタチツテトハヒフヘホウ",
    "ガギグゲゴザジズゼゾダヂヅデドバビブベボヴ",
)
_KATAKANA_UNVOICE = str.maketrans(
    "ガギグゲゴザジズゼゾダヂヅデドバビブベボヴ",
    "カキクケコサシスセソタチツテトハヒフヘホウ",
)

# Yōon: kana baris -i + ャュョェ kecil. Akar konsonan digabung dengan vokalnya.
_YOON_STEMS = {
    "キ": "ky", "ギ": "gy", "シ": "sh", "ジ": "j", "チ": "ch", "ヂ": "j",
    "ニ": "ny", "ヒ": "hy", "ビ": "by", "ピ": "py", "ミ": "my", "リ": "ry",
}
_YOON_SMALL = {"ャ": "a", "ュ": "u", "ョ": "o", "ェ": "e"}

# Kombinasi untuk kata serapan dan nama asing.
_LOANWORD_DIGRAPHS = {
    "ファ": "fa", "フィ": "fi", "フェ": "fe", "フォ": "fo",
    "フャ": "fya", "フュ": "fyu", "フョ": "fyo",
    "ティ": "ti", "ディ": "di", "トゥ": "tu", "ドゥ": "du",
    "テュ": "tyu", "デュ": "dyu", "テョ": "tyo", "デョ": "dyo",
    "ウィ": "wi", "ウェ": "we", "ウォ": "wo", "イェ": "ye",
    "ヴァ": "va", "ヴィ": "vi", "ヴェ": "ve", "ヴォ": "vo",
    "ヴャ": "vya", "ヴュ": "vyu", "ヴョ": "vyo",
    "ツァ": "tsa", "ツィ": "tsi", "ツェ": "tse", "ツォ": "tso",
    "クァ": "kwa", "クィ": "kwi", "クェ": "kwe", "クォ": "kwo", "グァ": "gwa",
    "スィ": "si", "ズィ": "zi", "スュ": "syu", "ズュ": "zyu",
}

_DIGRAPHS: dict[str, str] = {
    **{stem + small: root + vowel
       for stem, root in _YOON_STEMS.items()
       for small, vowel in _YOON_SMALL.items()},
    **_LOANWORD_DIGRAPHS,
}

_BARE_VOWELS = frozenset("アイウエオァィゥェォ")
# Vokal yang bisa membuat う sebelumnya menjadi suku kata sendiri (い-の-う-え, Inoue),
# tetapi hanya di batas morfem (lihat ``_morpheme_boundary``).
_SPLITTING_VOWELS = frozenset("エオェォ")
_MACRONS = {"a": "ā", "i": "ī", "u": "ū", "e": "ē", "o": "ō"}
# Pasangan (vokal terakhir, vokal baru) yang dibaca sebagai satu vokal panjang.
# えい dan いい sengaja tidak ada: pedoman menulisnya ei dan ii.
_LONG_PAIRS = frozenset({("a", "a"), ("u", "u"), ("e", "e"), ("o", "o"), ("o", "u")})

_NAME_SEPARATOR_RE = re.compile(r"[\s・]+")
_LATIN_SYMBOLS = frozenset(" -'‐’̄")


def kana_to_romaji(kana: str, mode: str = "macron") -> str:
    """Romanisasi hiragana dan katakana dengan pencocokan terpanjang.

    Digraf (きゃ, しゅ, ちょ, ファ, ティ, ヴァ, ...) dicocokkan lebih dulu daripada
    kana tunggal. Karakter non-kana (kanji, Latin, tanda baca) dibiarkan.

    Args:
        kana: Bacaan atau teks yang memuat kana.
        mode: ``macron``, ``kana``, atau ``plain`` (lihat docstring modul).

    Returns:
        Teks Latin huruf kecil.

    Raises:
        ConfigError: ``mode`` tidak dikenal.
    """
    if mode not in MODES:
        raise ConfigError(f"mode romaji {mode!r} tidak valid; pilihan: {', '.join(MODES)}")
    widened = _expand_kana_iteration(widen_halfwidth_kana(kana))
    units = _split_units(hira_to_kata(widened))
    katakana = _katakana_units(widened, units)
    pieces: list[str] = []
    geminate = False
    # True bila suku kata terakhir sudah dipanjangkan: vokal berikutnya suku kata baru.
    lengthened = False
    for index, unit in enumerate(units):
        if unit == SOKUON:
            geminate = True
            continue
        if unit == LONG_MARK:
            _lengthen(pieces, mode)
            geminate = False
            lengthened = True
            continue
        roma = _MONOGRAPHS.get(unit) or _DIGRAPHS.get(unit)
        if roma is None:
            pieces.append(unit)
            geminate = lengthened = False
            continue
        if geminate:
            roma = _geminate(roma)
            geminate = False
        if pieces and pieces[-1] == "n" and roma[0] in "aiueoy":
            pieces[-1] = "n'"
        if (mode != "kana" and unit in _BARE_VOWELS and not lengthened
                and _extends_vowel(pieces, roma, units, index, katakana[index])):
            _lengthen(pieces, mode)
            lengthened = True
            continue
        pieces.append(roma)
        lengthened = False
    return "".join(pieces)


def romanize_name(reading: str, mode: str) -> str:
    """Romanisasi bacaan nama lalu kapitalkan tiap kata.

    Kata dipisah oleh spasi (biasa atau lebar penuh) dan ・, misalnya
    ``やまだ たろう`` → ``Yamada Tarō`` dan ``ジョン・スミス`` → ``Jon Sumisu``
    (Hepburn murni; ejaan nama asing ada di ``romanize_foreign``).

    Args:
        reading: Bacaan kana.
        mode: ``macron``, ``kana``, atau ``plain``.

    Returns:
        Nama Latin dengan huruf kapital di awal tiap kata.

    Raises:
        ConfigError: ``mode`` tidak dikenal.
    """
    words = _NAME_SEPARATOR_RE.split(kana_to_romaji(reading, mode))
    return " ".join(word[:1].upper() + word[1:] for word in words if word)


NAME_TAIL_KANA = frozenset("こみかなえよのほりやとたきじおまねせ")
"""Satu kana yang lazim menutup nama Jepang (子 美 香 奈 恵 代 乃 穂 里 也 斗 太 樹 二 夫 ...)."""
NAME_HEAD_KANA = frozenset("みまさちこあ")
"""Satu kana yang lazim membuka nama Jepang (美 真 沙 千 小 亜): ミユキ, マユミ."""
_NON_NATIVE_KANA = frozenset("ぁぃぅぇぉゎゔゕゖ")
_VOWEL_KANA = {"a": "あ", "i": "い", "u": "う", "e": "い", "o": "う"}


def looks_japanese(kana: str) -> bool:
    """Perkirakan apakah tulisan katakana SATU bagian nama adalah nama Jepang.

    Bacaannya (hiragana; ー diganti vokal panjangnya, ユーキ → ゆうき, コータ →
    こうた) harus memakai kana Jepang biasa (tanpa ァィゥェォ kecil dan ヴ) dan
    berbentuk salah satu dari:

    - bacaan utuh dari data proyek: nama depan ``given_names.json`` (ハルカ,
      ユキ, サクラ), nama keluarga ``surnames.json`` (タナカ), tempat,
      ``data.KANA_NAME_READINGS`` (ミク, マドカ, dan bentuk ambigu レオ, ルカ), atau
      ``data.COMMON_NAME_READINGS`` (マキ, ユナ, ウメ, ヨウスケ);
    - dua unsur ``data.NAME_ELEMENTS`` (のぶ + なが, ひで + よし, まさ + ひろ), atau
      satu unsur + satu kana penutup ``NAME_TAIL_KANA`` (えつ + こ);
    - bacaan utuh + satu kana penutup ``NAME_TAIL_KANA`` (ユミ + コ, アヤ + ネ,
      リョウ + マ), dengan "bacaan utuh" boleh juga dua kana pertama sebuah nama
      depan (あや dari あやの);
    - satu kana pembuka ``NAME_HEAD_KANA`` + bacaan utuh (マ + ユミ).

    Ini heuristik: nama asing yang kebetulan berbentuk sama (カレン = か + れん)
    dianggap Jepang dan tetap Hepburn (Karen); nama Jepang yang tidak dikenali
    hanya menambah satu pertanyaan nama yang jawabannya disaring gema Hepburn.

    Args:
        kana: Satu bagian nama (tanpa ・); setengah lebar dan hiragana diterima.
    """
    reading = _name_reading(kana)
    if not reading or any(ch in _NON_NATIVE_KANA for ch in reading):
        return False
    whole, heads = _japanese_name_pieces()
    if reading in whole:
        return True
    if reading[-1] in NAME_TAIL_KANA and (reading[:-1] in whole or reading[:-1] in heads
                                          or reading[:-1] in data.NAME_ELEMENTS):
        return True
    if any(reading[:cut] in data.NAME_ELEMENTS and reading[cut:] in data.NAME_ELEMENTS
           for cut in range(2, len(reading) - 1)):
        return True
    return reading[0] in NAME_HEAD_KANA and reading[1:] in whole


def _name_reading(kana: str) -> str:
    """Bacaan hiragana tanpa ー: tanda panjang diganti vokal suku kata sebelumnya."""
    hira = kata_to_hira(_expand_kana_iteration(widen_halfwidth_kana(kana).strip()))
    out: list[str] = []
    for ch in hira:
        if ch == LONG_MARK:
            if not out:
                return ""
            vowel = kana_to_romaji(out[-1], "kana")[-1:]
            ch = _VOWEL_KANA.get(vowel, "")
            if not ch:
                return ""
        elif not ("ぁ" <= ch <= "ゖ"):
            return ""
        out.append(ch)
    return "".join(out)


@lru_cache(maxsize=None)
def _japanese_name_pieces() -> tuple[frozenset[str], frozenset[str]]:
    """Bacaan nama utuh dari data proyek dan awalan dua kana nama depan."""
    given = {info["reading"] for info in data.given_names().values()}
    whole = frozenset(given | set(data.surnames().values())
                      | {place["reading"] for place in data.places().values()}
                      | data.UNISEX_READINGS | data.KANA_NAME_READINGS
                      | data.COMMON_NAME_READINGS)
    heads = frozenset(reading[:2] for reading in given if len(reading) >= 3)
    return whole, heads


def foreign_spelling(part: str) -> str | None:
    """Ejaan Latin satu bagian nama asing dari kamus bawaan, atau ``None``.

    Args:
        part: Satu bagian nama katakana tanpa ・ (``エリザベート``); hiragana dan
            katakana setengah lebar dinormalisasi dulu.
    """
    return data.foreign_names().get(hira_to_kata(widen_halfwidth_kana(part.strip())))


def romanize_foreign(name: str, mode: str) -> str:
    """Romanisasi nama asing per bagian: kamus dulu, Hepburn untuk sisanya.

    ``ジョン・スミス`` → ``John Smith``; ``ジョン・サトウ`` → ``John Satō`` (mode
    macron). Bagian dipisah ・ atau spasi.

    Args:
        name: Tulisan atau bacaan katakana.
        mode: Mode romanisasi untuk bagian yang tidak ada di kamus.

    Raises:
        ConfigError: ``mode`` tidak dikenal.
    """
    parts = [part for part in _NAME_SEPARATOR_RE.split(name) if part]
    return " ".join(foreign_spelling(part) or romanize_name(part, mode) for part in parts)


def is_latin(text: str) -> bool:
    """Periksa apakah teks hanya berisi huruf Latin dan pemisah nama.

    Yang diizinkan: huruf Latin (termasuk ā ō é), spasi, tanda hubung,
    apostrof (' atau ’), dan makron gabung (U+0304). Angka dan tanda baca
    lain ditolak, sehingga jawaban mesin seperti ``Tanaka.`` dianggap tidak
    bersih.

    Args:
        text: Teks yang diperiksa, biasanya ejaan nama dari mesin.

    Returns:
        ``True`` bila teks memuat minimal satu huruf Latin dan tidak ada
        karakter lain di luar daftar di atas.
    """
    has_letter = False
    for ch in text:
        if ch.isalpha() and unicodedata.name(ch, "").startswith("LATIN "):
            has_letter = True
        elif ch not in _LATIN_SYMBOLS:
            return False
    return has_letter


def _split_units(kata: str) -> list[str]:
    """Pecah teks katakana menjadi unit kana, digraf lebih dulu."""
    units: list[str] = []
    index = 0
    while index < len(kata):
        pair = kata[index:index + 2]
        step = 2 if pair in _DIGRAPHS else 1
        units.append(kata[index:index + step])
        index += step
    return units


def _geminate(roma: str) -> str:
    """Gandakan konsonan awal suku kata setelah sokuon (ch → tch)."""
    if roma[0] in "aiueo":
        return roma
    if roma.startswith("ch"):
        return "t" + roma
    return roma[0] + roma


def _katakana_units(text: str, units: list[str]) -> list[bool]:
    """Tandai unit ``_split_units`` yang aslinya ditulis katakana.

    ``hira_to_kata`` memetakan satu karakter ke satu karakter, jadi posisi unit
    di teks katakana sama dengan posisinya di ``text``.
    """
    flags: list[bool] = []
    offset = 0
    for unit in units:
        flags.append("ァ" <= text[offset] <= "ヺ")
        offset += len(unit)
    return flags


_MORPHEME_SPLIT_HEADS = frozenset({
    "まつう", "はるう", "つるう", "ひろお", "くろお", "しろお", "むろお", "よこお", "もとお",
})


def _expand_kana_iteration(text: str) -> str:
    """Urai tanda ulang kana ``ゝゞヽヾ`` berdasarkan huruf sebelumnya (みすゞ -> みすず)."""
    chars = list(text)
    for idx in range(1, len(chars)):
        mark = chars[idx]
        prev = chars[idx - 1]
        is_hira = "ぁ" <= prev <= "ゖ"
        is_kata = "ァ" <= prev <= "ヺ"
        if not (is_hira or is_kata):
            continue
        if mark in ("ゝ", "ヽ"):
            unvoiced_kata = hira_to_kata(prev).translate(_KATAKANA_UNVOICE)
            chars[idx] = kata_to_hira(unvoiced_kata) if is_hira else unvoiced_kata
        elif mark in ("ゞ", "ヾ"):
            voiced_kata = hira_to_kata(prev).translate(_KATAKANA_DAKUTEN)
            chars[idx] = kata_to_hira(voiced_kata) if is_hira else voiced_kata
    return "".join(chars)


def _extends_vowel(pieces: list[str], vowel: str, units: list[str], index: int,
                   katakana: bool = False) -> bool:
    """Tentukan apakah vokal tunggal ``units[index]`` memperpanjang vokal sebelumnya.

    ``katakana`` menandai bahwa vokal itu ditulis katakana; ウ katakana sebelum
    エ/オ tidak pernah dipanjangkan (bunyi we/wo kata serapan).
    """
    if not pieces or (pieces[-1][-1], vowel) not in _LONG_PAIRS:
        return False
    if not katakana and _is_compound_vowel_split(units, index):
        return False
    following = units[index + 1] if index + 1 < len(units) else ""
    if pieces[-1][-1] == "o" and vowel == "u" and following in _SPLITTING_VOWELS:
        # いのうえ: う-え di batas morfem adalah dua suku kata (Inoue, bukan Inōe).
        return not katakana and not _morpheme_boundary(units, index + 1)
    return True


def _is_compound_vowel_split(units: list[str], index: int) -> bool:
    """Cegah penggabungan vokal lintas morfem pada marga seperti 松浦, 広岡, 横尾."""
    start = index
    while start > 0 and _is_kana_unit(units[start - 1]):
        start -= 1
    prefix_hira = kata_to_hira("".join(units[start:index + 1]))
    return prefix_hira in _MORPHEME_SPLIT_HEADS


def _morpheme_boundary(units: list[str], index: int) -> bool:
    """Apakah ``units[index]`` (え/お setelah おう) menutup sebuah kata atau nama keluarga.

    Ya bila setelahnya bukan kana lagi (akhir teks, spasi, ・, tanda baca), atau
    bila bacaan dari awal kata sampai ``units[index]`` adalah bacaan nama keluarga
    di ``surnames.json`` yang berakhir うえ/うお (いのうえ + さん).
    """
    if index + 1 >= len(units) or not _is_kana_unit(units[index + 1]):
        return True
    start = index
    while start > 0 and _is_kana_unit(units[start - 1]):
        start -= 1
    return kata_to_hira("".join(units[start:index + 1])) in _surname_ue_readings()


def _is_kana_unit(unit: str) -> bool:
    """Unit hasil ``_split_units`` yang berupa kana (termasuk ッ dan ー)."""
    return unit in _MONOGRAPHS or unit in _DIGRAPHS or unit in (SOKUON, LONG_MARK)


@lru_cache(maxsize=1)
def _surname_ue_readings() -> frozenset[str]:
    """Bacaan nama keluarga bawaan yang berakhir うえ atau うお (いのうえ)."""
    return frozenset(reading for reading in data.surnames().values()
                     if reading.endswith(("うえ", "うお")))


def _lengthen(pieces: list[str], mode: str) -> None:
    """Panjangkan vokal terakhir sesuai mode (ā, aa, atau tetap a)."""
    if not pieces or pieces[-1][-1] not in _MACRONS:
        return
    last = pieces[-1]
    if mode == "macron":
        pieces[-1] = last[:-1] + _MACRONS[last[-1]]
    elif mode == "kana":
        pieces[-1] = last + last[-1]
