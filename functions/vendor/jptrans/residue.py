"""Sisa huruf Jepang di keluaran mesin: gema, huruf sisa, judul 『…』, dan emotikon.

Pipeline memakai modul ini untuk memutuskan apakah keluaran mesin sudah benar-benar
diterjemahkan (``pipeline.Translator._accept_outputs``, ``_has_residue``, dan jalur
cadangan ``_presubstitute``). API publiknya:

- ``looks_untranslated(raw, sent)``: keluaran kosong atau gema persis masukan.
- ``residue_letters(raw, sent, keep)``: jumlah huruf Jepang sisa (nol = bersih).
- ``has_japanese_residue(raw, sent, keep)``: ``residue_letters(...) > 0``.
- ``japanese_letters(text)``: jumlah huruf Jepang (kana atau kanji) di teks.

Yang tidak dihitung sisa: penanda ``[[E#]]`` (juga bentuk lebar penuh dan berisi
tambahan mesin), tulisan ``keep`` beserta potongannya, kutipan judul 『…』 yang disalin
dari sumber, emotikon yang disalin dari sumber, tanda baca Jepang, dan deretan ``〇``.
Karakter kompatibilitas (㌔, ㋐, ⽇) dihitung menurut bentuk NFKC-nya. Modul ini
dipisah dari ``pipeline`` (dulu fungsi-fungsinya ada di sana) tanpa perubahan perilaku.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable

from .protect import EXACT_TOKEN_RE
from .textnorm import HIRAGANA, KANJI, KATAKANA, contains_japanese, is_hiragana_text

logger = logging.getLogger(__name__)

# Setiap huruf Jepang di keluaran mesin adalah sisa, kecuali yang berasal dari bagian
# di bawah ini (lihat ``residue_letters``).
_LOOSE_TOKEN_RE = re.compile(r"[\[［]{2}\s*[EＥ]\s*[0-9０-９]+[^\[\]［］\n]{0,40}[\]］]{2}")
"""Penanda ``[[E#]]``, juga bentuk lebar penuh atau berisi tambahan mesin (``[[E1:田中]]``)."""
_TITLE_QUOTE_RE = re.compile(r"『[^『』\n]{1,60}』")
"""Kutipan judul 『…』; hanya dibebaskan bila disalin utuh dari sumber (``_is_title_quote``)."""
_EMOTICON_RE = re.compile(r"[^\sA-Za-z0-9()（）]{0,2}[(（][^()（）\n]{1,16}[)）]"
                          r"[^\sA-Za-z0-9()（）]{0,2}")
"""Calon emotikon: isi kurung pendek plus "lengan" sampai 2 karakter (ヽ(・∀・)ノ, (つ´∀`)つ)."""
EMOTICON_ARM_LETTERS = frozenset("つっノﾉゞヾヽシｼミﾐヘﾍ")
"""Huruf Jepang yang lazim menjadi "lengan" emotikon; huruf lengan lain (``ね(^^)``) dihitung."""
EMOTICON_MARKS = frozenset("´`｀∀ωДдﾟ°・･＾^;；_＿≧≦▽∇ε◕‿◡•ᴗ゜｡〃<>＜＞*＊ー～〜∩⊂⊃﹏")
"""Simbol khas emotikon; calon tanpa satu pun simbol ini (``(笑)``) bukan emotikon."""
_COMPAT_RE = re.compile("[\u2e80-\u2fdf\u3200-\u33ff]")
"""Karakter kompatibilitas: radikal (⺀-⿕) dan huruf/kata berlingkaran atau berkotak (㋐ ㌔ ㍻)."""
_RADICALS_END = "\u2fdf"
_RADICAL_AS_KANJI = "\u4e00"
"""Pengganti radikal tanpa dekomposisi NFKC (⻑), agar dihitung satu kanji."""
PLACEHOLDER_MARKS = frozenset("〇")
"""``〇`` (U+3007) dihitung kanji oleh ``textnorm``, tetapi deretan ``〇〇`` adalah tanda sensor."""
_JAPANESE_RUN_RE = re.compile(f"[{HIRAGANA}{KATAKANA}{KANJI}]+")


def looks_untranslated(raw: str, sent: str) -> bool:
    """Kenali keluaran mesin yang hanya mengembalikan masukannya, atau kosong.

    Google kadang mengembalikan satu baris batch tanpa diterjemahkan, dan
    MyMemory kadang memantulkan masukan apa adanya. Keluaran kosong (atau
    hanya spasi) untuk kalimat berhuruf Jepang juga bukan terjemahan: bila
    diterima, kalimatnya lenyap dari hasil dengan status ``ok``. Keluaran
    seperti itu dianggap gagal agar kalimatnya dicoba ulang sendiri atau
    diteruskan ke mesin berikutnya. Kalimat yang isinya hanya penanda
    (``[[E1]]``) memang boleh kembali sama persis.

    Args:
        raw: Keluaran mentah mesin.
        sent: Teks termasking yang dikirim.

    Returns:
        ``True`` bila ``sent`` berisi huruf Jepang dan ``raw`` kosong atau sama
        dengan ``sent`` setelah semua spasi diabaikan.
    """
    if not contains_japanese(EXACT_TOKEN_RE.sub("", sent)):
        return False
    bare = "".join(raw.split())
    return not bare or bare == "".join(sent.split())


def japanese_letters(text: str) -> int:
    """Jumlah huruf Jepang (kana atau kanji) di teks; tanda baca Jepang tidak dihitung."""
    return sum(1 for ch in text if contains_japanese(ch))


def has_japanese_residue(raw: str, sent: str, keep: Iterable[str] = ()) -> bool:
    """Kenali keluaran yang masih memuat huruf Jepang, sekecil apa pun.

    ``looks_untranslated`` hanya menangkap gema persis; fungsi ini menangkap
    sisa apa saja, dari klausa yang disalin utuh sampai satu kata
    (``Dia makan 寿司.``). Lihat ``residue_letters`` untuk bagian yang tidak dihitung.

    Args:
        raw: Keluaran mentah mesin.
        sent: Teks yang dikirim (termasking).
        keep: Tulisan Jepang yang boleh tetap ada di keluaran.

    Returns:
        ``True`` bila ``residue_letters`` lebih dari nol.
    """
    return residue_letters(raw, sent, keep) > 0


def residue_letters(raw: str, sent: str, keep: Iterable[str] = ()) -> int:
    """Hitung huruf Jepang sisa di keluaran mesin.

    Setiap huruf Jepang (kana atau kanji) di keluaran dihitung, kecuali yang
    berasal dari:

    - penanda ``[[E#]]``, termasuk bentuk lebar penuh (``［［E1］］``) dan penanda yang
      diberi tambahan oleh mesin (``[[E1:田中]]``);
    - tulisan ``keep``, yaitu entri yang sengaja dibiarkan Jepang (tidak bisa
      dirender, mis. nama tanpa bacaan dengan ``unknown_reading="keep"``, atau bentuk
      akhir berhuruf Jepang di jalur cadangan), beserta potongannya (``美咲`` dari
      ``朝倉美咲``);
    - kutipan judul 『…』 yang disalin utuh dari sumber dan bukan ucapan
      (``_is_title_quote``);
    - emotikon yang disalin utuh dari sumber (``_is_emoticon``: ``(つ´∀`)つ``,
      ``ヽ(・∀・)ノ``).

    Tanda baca Jepang tanpa huruf (「」、。・ー) memang tidak pernah dihitung, begitu
    juga deretan ``〇`` saja (pengganti nama yang disensor, ``〇〇さん``). Karakter
    kompatibilitas dihitung menurut bentuk NFKC-nya (``_fold_compat``: ㌔ = キロ, ㋐ = ア,
    ⽇ = 日; ㎏ dan ㉑ bukan huruf Jepang).

    Tulisan ``keep`` hanya berlaku bila muncul di kalimat ``sent`` itu sendiri, dan
    potongannya hanya bila panjangnya minimal dua huruf atau bukan hiragana (``美咲``
    dan ``鬼`` boleh, ``の`` dari ``鬼の手`` tidak).

    Args:
        raw: Keluaran mentah mesin.
        sent: Teks yang dikirim (termasking).
        keep: Tulisan Jepang yang boleh tetap ada di keluaran.

    Returns:
        Jumlah huruf Jepang sisa; nol berarti keluaran bersih.
    """
    raw, sent = _fold_compat(raw), _fold_compat(sent)
    allowed = sorted({folded for folded in map(_fold_compat, keep) if folded and folded in sent},
                     key=len, reverse=True)

    def strip(text: str) -> str:
        """Ganti penanda (juga bentuk longgarnya) dan tulisan ``allowed`` dengan spasi."""
        text = _LOOSE_TOKEN_RE.sub(" ", text)
        for surface in allowed:
            text = text.replace(surface, " ")
        return text

    source, output = strip(sent), strip(raw)
    if not contains_japanese(output):
        return 0
    output = _TITLE_QUOTE_RE.sub(
        lambda m: " " if _is_title_quote(m.group(0), source) else m.group(0), output)
    output = _EMOTICON_RE.sub(lambda m: _drop_emoticon(m.group(0), source), output)
    count = 0
    for run in _JAPANESE_RUN_RE.findall(output):
        core = run.strip("ー・ｰ･")
        if core and (set(core) <= PLACEHOLDER_MARKS
                     or (_free_fragment(core) and any(core in surface for surface in allowed))):
            continue
        count += japanese_letters(run)
    return count


def _free_fragment(core: str) -> bool:
    """Potongan tulisan keep yang boleh dibebaskan: dua huruf atau lebih, atau bukan hiragana.

    Hiragana tunggal (の, と) adalah partikel yang bisa muncul di mana saja, jadi
    tidak dibebaskan walau ada di dalam tulisan keep (鬼の手).
    """
    return japanese_letters(core) >= 2 or not is_hiragana_text(core)


def _fold_compat(text: str) -> str:
    """Ganti karakter kompatibilitas Jepang dengan bentuk NFKC-nya untuk penghitungan sisa.

    ㌔ menjadi キロ, ㋐ menjadi ア, ⽇ menjadi 日, ㍻ menjadi 平成; ㎏ dan ㉑ menjadi huruf
    Latin dan angka. Radikal tanpa dekomposisi (⻑, ⺅) dihitung satu kanji. Hanya dipakai
    di dalam ``residue_letters``; teks keluaran tidak diubah.
    """
    def fold(match: re.Match[str]) -> str:
        """Bentuk NFKC satu karakter kompatibilitas; radikal tanpa dekomposisi jadi 一."""
        char = match.group(0)
        folded = unicodedata.normalize("NFKC", char)
        if folded == char and char <= _RADICALS_END:
            return _RADICAL_AS_KANJI
        return folded

    return _COMPAT_RE.sub(fold, text)


def _is_title_quote(quote: str, source: str) -> bool:
    """Kutipan 『…』 disalin utuh dari sumber dan isinya bukan ucapan.

    Ucapan di dalam 『』 (kutipan di dalam kutipan, suara telepon) kebanyakan
    hiragana (『待って』); judul karya memuat kanji atau katakana dan paling banyak
    separuh hurufnya hiragana (『ノルウェイの森』, 『君の名は。』).
    """
    if quote not in source:
        return False
    letters = [ch for ch in quote if contains_japanese(ch)]
    hiragana = sum(1 for ch in letters if is_hiragana_text(ch))
    return bool(letters) and hiragana * 2 <= len(letters)


def _drop_emoticon(candidate: str, source: str) -> str:
    """Buang emotikon dari calon ``_EMOTICON_RE`` bila disalin utuh dari sumber.

    "Lengan" regex bisa ikut menelan tanda baca atau huruf di sebelahnya
    (``(つ´∀`)つ。``, ``ね(^^)``), jadi dicoba dari bentuk terpanjang sampai inti
    kurungnya; yang pertama lolos ``_is_emoticon`` dan lengannya hanya memuat huruf
    lengan lazim (``EMOTICON_ARM_LETTERS``) saja yang dibuang, sisanya tetap dihitung.
    """
    opener = min(i for i in (candidate.find("("), candidate.find("（")) if i >= 0)
    closer = max(candidate.rfind(")"), candidate.rfind("）"))
    for start in range(opener + 1):
        for end in range(len(candidate), closer, -1):
            piece = candidate[start:end]
            arms = candidate[start:opener] + candidate[closer + 1:end]
            if (all(ch in EMOTICON_ARM_LETTERS for ch in arms if contains_japanese(ch))
                    and _is_emoticon(piece, source)):
                return candidate[:start] + " " + candidate[end:]
    return candidate


def _is_emoticon(candidate: str, source: str) -> bool:
    """Calon emotikon disalin utuh dari sumber, bersimbol khas, dan hurufnya tunggal.

    Huruf Jepang di emotikon selalu berdiri sendiri sebagai gambar (つ, ノ, ゞ);
    dua huruf berurutan (``(すし)``) berarti kata, bukan emotikon.
    """
    if candidate not in source or not EMOTICON_MARKS.intersection(candidate):
        return False
    return all(japanese_letters(run) <= 1 for run in _JAPANESE_RUN_RE.findall(candidate))
