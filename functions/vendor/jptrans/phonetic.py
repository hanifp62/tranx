"""Validasi fonetik ejaan nama dari mesin terhadap bacaan kana (fungsi murni).

Mesin penerjemah kadang menjawab nama dengan arti, bukan bunyi: ミサキ → ``Cape``
(misaki = tanjung), レオン → ``Lion``, リリア → ``Lily of the valley``. Modul ini
memeriksa apakah jawaban *terdengar* seperti katakana/bacaannya.

Cara kerja (keputusan desain, ambang bisa dikalibrasi):

1. ``normalize`` mengubah ejaan Latin menjadi bentuk kasar bunyi: huruf kecil
   tanpa diakritik, lalu kelompok bunyi yang tidak dibedakan katakana disamakan
   (r~l, b~v, s~sh~th, t~ts~ch, h~f, k~c~q~ck, g~j, z~s). ``h`` bisu setelah
   vokal (John, Satoh) dan ``r`` non-rotik setelah vokal (Lucifer, Charlotte)
   dibuang, huruf ganda diringkas, dan vokal akhir ``e``/``o``/``u`` setelah
   konsonan dibuang di KEDUA sisi: itu vokal epentetik katakana (スミス sumisu)
   atau ``e`` bisu bahasa Inggris (Alice).
2. ``similarity`` = 1 − jarak edit berbobot / panjang terpanjang. Vokal ``u``/``o``/``i``
   di antara dua konsonan pada sisi katakana murah dihapus (``EPENTHETIC_COST``,
   ヴィクトリア vi-ku-toria ↔ Victoria); s↔t setengah harga (``NEAR_COST``,
   シャーロット ↔ Charlotte). Perubahan vokal lain berharga penuh, sehingga
   レオン/Lion (e ↔ i) ditolak.
3. Kerangka konsonan (vokal dibuang) juga harus mirip (``MIN_SKELETON_SIMILARITY``),
   agar jawaban dengan vokal kebetulan sama tetapi konsonan lain tidak lolos.

Contoh keputusan: アリス/``Alicia`` DITOLAK (kemiripan 0,67). Alicia ditulis
アリシア dalam katakana; アリス tidak punya suku kata -シア, jadi Alicia adalah
nama lain, bukan ejaan lain dari Alice.

Jawaban yang seluruhnya huruf kapital (``FELICIA``) dijadikan Title Case per kata
(``Felicia``, ``O'BRIEN`` → ``O'Brien``), dan jawaban berhuruf kecil dikapitalkan
(``scheherazade`` → ``Scheherazade``) lalu tetap harus lolos validasi bunyi.
``is_hepburn_echo`` mengenali jawaban yang hanya mengulang Hepburn bagian itu
(リョーマ/``Ryoma``): itu tanda nama Jepang, sehingga pipeline memakai Hepburn
sesuai mode romanisasi.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from . import data
from .romaji import is_latin, kana_to_romaji
from .textnorm import kata_to_hira, strip_diacritics, widen_halfwidth_kana

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.82
"""Kemiripan minimum seluruh bunyi (vokal ikut dihitung).

0,82 (bukan 0,8) agar satu vokal akhir yang hilang pada nama lima huruf tidak
lolos: リリア/``Lily`` (riria ↔ riri, 0,8) ditolak, sedangkan Charlotte (0,9) dan
Smith (0,95) tetap diterima.
"""
MIN_SKELETON_SIMILARITY = 0.75
"""Kemiripan minimum kerangka konsonan."""
EUROPEAN_MIN_SIMILARITY = 0.86
"""Kemiripan minimum untuk ejaan Eropa (``_sounds_european``), lebih ketat dari ``MIN_SIMILARITY``.

Dikalibrasi pada pasangan silang kamus ``foreign_names.json`` (katakana x nama Latin lain): pada
0,82 jalur ini meloloskan 11 pasangan salah (ロナルド/``Donald`` 0,821, ドナルド/``Ronald``,
モルガナ/``Morgan`` 0,844, ジェラルド/``Gertrude`` 0,857); pada 0,86 nol. Pasangan benar yang
dikorbankan (ヴォルコフ/``Volkov``, ハプスブルク/``Habsburg``, ヴォルフガング/``Wolfgang``) tetap
ditolak seperti sebelumnya.
"""
EPENTHETIC_COST = 0.25
NEAR_COST = 0.5
VOWELS = frozenset("aeiou")
EPENTHETIC_VOWELS = frozenset("uoi")
FINAL_SILENT_VOWELS = frozenset("eou")
R_VOWEL_SPELLINGS: dict[str, frozenset[str]] = {
    "e": frozenset({"a", "ae", "ai", "ay", "ea", "ei"}),
    "o": frozenset({"o", "oa", "oo", "ou"}),
    "i": frozenset({"ea", "ee", "ei", "ie"}),
    "u": frozenset({"oo", "ou", "u", "ue"}),
}
"""Vokal katakana sebelum ア akhir → ejaan vokal Inggris di depan ``-r``/``-re`` non-rotik.

エア: Clare, Sinclair, Alistair; オア: Theodore, Eleonore; イア: Napier, Greer; ウア: Moore.
``e`` tunggal (``-er``) sengaja tidak ada di イア, jadi オリヴィア/``Oliver`` tetap ditolak.
"""

# Urutan penting: gugus tiga huruf dulu, lalu dua huruf.
_CLUSTERS = (
    ("tch", "t"), ("sch", "s"), ("sh", "s"), ("th", "s"), ("ch", "t"), ("ph", "f"),
    ("ck", "k"), ("qu", "ku"), ("dg", "g"), ("ts", "t"), ("wh", "w"),
)
_LETTERS = str.maketrans({"q": "k", "x": "ks", "j": "g", "v": "b", "l": "r", "f": "h",
                          "z": "s"})
# Ejaan vokal bahasa Inggris → bunyi yang ditulis katakana (hanya untuk sisi jawaban).
_ENGLISH_VOWELS = (
    (re.compile(r"ie$|ey$|ee|ea"), "i"), (re.compile(r"oo|ew"), "u"),
    (re.compile(r"au|aw"), "o"), (re.compile(r"ay"), "ei"),
    (re.compile(r"[eiuao]r$|[eiua]r(?![aeiouy])"), "a"), (re.compile(r"or(?![aeiouy])"), "o"),
)
_SOFT_C_RE = re.compile(r"c(?=[eiy])")
_INITIAL_SILENT_RE = re.compile(r"^(?:k(?=n)|w(?=r)|g(?=h))")
_GH_RE = re.compile(r"(?<=.)gh")
_Y_GLIDE_RE = re.compile(r"y(?=[aeiou])")
_SILENT_H_RE = re.compile(r"(?<=[aeiou])h(?![aeiou])")
_NON_ROTIC_R_RE = re.compile(r"(?<=[aeiou])r(?![aeiou])")
_DOUBLE_RE = re.compile(r"(.)\1+")
_PART_SEPARATOR_RE = re.compile(r"[\s・·]+")
_WORD_START_RE = re.compile(r"(^|['’\-])(\w)")
_LONG_VOWEL_RE = re.compile(r"ou|([aeiou])\1+")
# Satu kata romanisasi Jepang (Hepburn, juga Kunrei/wāpuro): suku kata konsonan(+y) + vokal,
# ん (n, atau m sebelum b/p/m), dengan konsonan ganda (sokuon) sudah diringkas lebih dulu.
_ROMANIZED_WORD_RE = re.compile(r"(?:(?:sh|ch|ts|[kgsztdnhbpmr]y?|[jfwy])?[aiueo]|n|m(?=[bpm]))+")
_GEMINATE_RE = re.compile(r"([kgsztdhbpcfjmn])\1|t(?=ch)")
_NATIVE_KANA_RE = re.compile("[ァィゥェォヮヴヵヶ]")
# Hepburn menulis ん sebagai m di depan b/p/m (Namba, Jimbo, Homma).
_HEPBURN_M_RE = re.compile(r"m(?=[bpm])", re.IGNORECASE)
# Ejaan ``-r``/``-re`` di akhir kata (Theodore, Sinclair); grup 1 = vokal di depan r.
_R_ENDING_RE = re.compile(r"(?<![aeiouy])([aeiouy]+)re?$")
_TRAILING = " \t.。,、!！?？"
# Katakana dengan ル + konsonan atau ル di akhir (ヒルデガルト, ゲオルグ, ベルント, ロルフ): ejaan aslinya
# punya r/l di akhir suku kata, yang bahasa Eropa ucapkan (bukan r non-rotik bahasa Inggris).
# ル + ー/vokal (ルーク, ルイ) bukan akhir suku kata.
_CODA_LIQUID_KANA_RE = re.compile("ル(?![ーァアィイゥウェエォオャュョヮ・])")
# Jawaban dengan r/l di akhir suku kata: disusul konsonan atau akhir kata (Bernd, Georg, Rolf).
_CODA_LIQUID_SPELLING_RE = re.compile(r"[rl]+(?![aeiouy])")
_LIQUID_MARK = "L"
"""Penanda sementara ``l`` di ``_normalize`` (huruf besar: tidak ada sesudah ``casefold``)."""
_CONSONANT_RUN_RE = re.compile("[b-df-hj-np-tv-z]*")
"""Deretan huruf mati (y termasuk) di awal teks, untuk ``_romaji_onset`` dan ``_codas_align``."""
_DEVOICED = str.maketrans({"d": "t", "g": "k", "b": "p"})
"""Pelemahan konsonan akhir bahasa Jerman: Bernd → ベルント, Gertrud → ゲルトルート."""
EUROPEAN_DECOY_WORDS = frozenset("""
    cult cults curd curds mild wild gold hold bold cold fold told sold mold gelt geld gourd halt
    malt salt hart hard card cart dart part mart art bolt colt jolt volt belt felt melt pelt welt
    milk silk bulk hulk golf gulf self shelf elf herd nerd bird word lord cord hurt girl karma kart
    park fork cork work pork turn burn horn corn worn barn yarn film helm elm palm calm realm
    tart hilt berth birth mirth girth earth worth north forth hertz
    sort shirk elk kelt mirk
""".split())
"""Kata Inggris umum ber-r/l + konsonan yang bunyinya sama dengan bacaan katakana ber-ル+konsonan
(クルト/``Cult``, ミルト/``Mild``, ゴルト/``Gold``, ベルト/``Belt``): bunyi tidak bisa membedakannya dari
nama Eropa, jadi jalur Eropa menolaknya (``data.COMMON_ENGLISH_WORDS`` juga). Nama yang juga kata
(Wolf, Mark, Ford, Curt) sengaja tidak ada."""
_EUROPEAN_ONSETS: dict[str, tuple[str, ...]] = {
    "": ("a", "e", "i", "o", "u", "y", "h"), "k": ("k", "c", "q"), "g": ("g",),
    "s": ("s", "z", "c"), "sh": ("sch", "sh", "s", "ch", "c"), "z": ("z", "s", "x"),
    "j": ("j", "g", "y", "dj", "zh"), "t": ("t",), "d": ("d",), "ch": ("ch", "c", "tsch", "cz"),
    "ts": ("ts", "z", "tz", "c"), "n": ("n", "kn"), "h": ("h",), "f": ("f", "ph"), "b": ("b",),
    "p": ("p",), "m": ("m",), "y": ("y", "j", "i"), "r": ("r", "l", "wr", "rh"),
    "w": ("w", "v", "o", "u"), "v": ("v", "w"),
}
"""Huruf awal ejaan yang sejalan dengan konsonan awal katakana di jalur Eropa (kosong = vokal;
Spanyol menulis h bisu: エルナンデス/``Hernandez``). ゴ/ゲ tidak ditulis j (ゴルト/``Jolt``), ハ tidak ditulis f
(ハルト/``Fardo``). Konsonan katakana lain cukup sama huruf pertamanya."""
_EUROPEAN_CODA_FITS: dict[str, tuple[str, ...]] = {
    "": ("",), "t": ("t", "d"), "d": ("d", "t"), "k": ("k", "c", "g", "q"), "g": ("g",),
    "f": ("f", "ph", "v", "w"), "b": ("b", "v", "w"), "v": ("v", "w", "f"), "w": ("w", "v"),
    "s": ("s", "z", "c", "x"), "z": ("z", "s"), "sh": ("sch", "sh", "s", "c", "ch"),
    "ch": ("ch", "tsch", "c", "cz"), "ts": ("ts", "tz", "z"), "j": ("j", "g", "s", "z"),
    "h": ("h", "ch"), "p": ("p", "b"), "r": ("r", "l"),
}
"""Huruf ejaan sesudah r/l akhir suku kata yang sejalan dengan konsonan sesudah ル (kosong = akhir
kata). ト boleh d (pelemahan Jerman: Hildegard, Ewald), ク boleh g (Georg ゲオルク), tetapi ト tidak
ch (ハルト/``Halch``). Konsonan katakana lain cukup sama huruf pertamanya."""


def normalize(latin: str, english: bool = False) -> str:
    """Ubah satu kata Latin menjadi bentuk bunyi kasar untuk dibandingkan.

    Args:
        latin: Kata Latin (boleh berhuruf kapital dan berdiakritik).
        english: Tafsirkan juga ejaan vokal bahasa Inggris (ee/ea → i, oo → u,
            au → o, er/ar/ir/ur di depan konsonan atau di akhir → a, ...). Hanya
            untuk jawaban mesin; romanisasi Hepburn sudah fonemis.

    Returns:
        Huruf a-z saja; kosong bila tidak ada huruf Latin.
    """
    return _normalize(latin, english)


def _normalize(latin: str, english: bool = False, *, keep_l: bool = False,
               keep_r: bool = False, devoice: bool = False, keep_e: bool = False) -> str:
    """Isi ``normalize`` dengan pilihan ejaan Eropa (hanya untuk ``_sounds_european``).

    Args:
        latin: Kata Latin.
        english: Lihat ``normalize``.
        keep_l: ``l`` di akhir suku kata tidak dibuang bersama ``r`` non-rotik (Rolf, Arnold).
        keep_r: ``r`` di akhir suku kata dipertahankan (Hildegard, Georg, Bernd).
        devoice: Konsonan akhir d/g/b dibaca t/k/p (Bernd, Gertrud).
        keep_e: ``e`` akhir sesudah konsonan tidak dibuang (ejaan Eropa mengucapkannya:
            Gertrude ≠ Gertrud, George ≠ Georg).
    """
    text = "".join(ch for ch in strip_diacritics(latin.casefold()) if "a" <= ch <= "z")
    text = _INITIAL_SILENT_RE.sub("", text)
    text = _GH_RE.sub("", text)
    text = _SILENT_H_RE.sub("", text)
    if english:
        for pattern, sound in _ENGLISH_VOWELS:
            text = pattern.sub(sound, text)
    for cluster, sound in _CLUSTERS:
        text = text.replace(cluster, sound)
    if keep_l:
        text = text.replace("l", _LIQUID_MARK)
    text = _SOFT_C_RE.sub("s", text).replace("c", "k").translate(_LETTERS)
    text = _Y_GLIDE_RE.sub("", text).replace("y", "i")
    text = _DOUBLE_RE.sub(r"\1", text).replace("ou", "o")
    if len(text) > 2 and text[-1] in FINAL_SILENT_VOWELS and text[-2] not in VOWELS \
            and not (keep_e and text[-1] == "e"):
        text = text[:-1]
    if not keep_r:
        text = _NON_ROTIC_R_RE.sub("", text)
    if devoice and text:
        text = text[:-1] + text[-1].translate(_DEVOICED)
    if keep_l and keep_r:
        return text.replace(_LIQUID_MARK, "r")
    text = text.replace(_LIQUID_MARK, "r")
    return _DOUBLE_RE.sub(r"\1", text)


def similarity(reference: str, answer: str, english: bool = False) -> float:
    """Kemiripan bunyi dua kata Latin, 0 sampai 1.

    Args:
        reference: Romanisasi bacaan kana (sisi yang boleh punya vokal epentetik).
        answer: Ejaan dari mesin.
        english: Teruskan ke ``normalize`` untuk sisi jawaban.

    Returns:
        ``1 − jarak / panjang`` setelah ``normalize``; 0 bila keduanya kosong.
    """
    return _ratio(normalize(reference), normalize(answer, english), epenthetic=True)


def skeleton_similarity(reference: str, answer: str, english: bool = False) -> float:
    """Kemiripan kerangka konsonan (vokal dibuang); 1 bila keduanya tanpa konsonan."""
    ref = _consonants(normalize(reference))
    ans = _consonants(normalize(answer, english))
    if not ref and not ans:
        return 1.0
    return _ratio(ref, ans, epenthetic=False)


def sounds_alike(reference: str, answer: str) -> bool:
    """``True`` bila ``answer`` lolos kedua ambang, dibaca sebagai Hepburn atau Inggris."""
    return any(similarity(reference, answer, english) >= MIN_SIMILARITY
               and skeleton_similarity(reference, answer, english) >= MIN_SKELETON_SIMILARITY
               for english in (False, True))


def validate_foreign_name(kana: str, answer: str) -> str | None:
    """Terima ejaan nama asing dari mesin hanya bila bentuk dan bunyinya cocok.

    Syarat: jumlah kata jawaban sama dengan jumlah bagian katakana (dipisah ・
    atau spasi), tiap kata huruf Latin, dan tiap kata ``sounds_alike`` dengan
    romanisasi Hepburn bagiannya. Kata yang seluruhnya huruf kapital (minimal
    dua huruf) dijadikan Title Case lebih dulu; kata berawalan huruf kecil
    dikapitalkan di awal kata dan sesudah ``-`` atau ``'`` (``scheherazade`` →
    ``Scheherazade``, ``jean-luc`` → ``Jean-Luc``, ``o'brien`` → ``O'Brien``).
    Huruf kecil aman diterima di sini karena syarat bunyi tetap berlaku: kata
    biasa yang artinya saja yang cocok (レオン/``lion``) tetap ditolak.

    Args:
        kana: Tulisan katakana, misalnya ``ジョン・スミス``; setengah lebar
            (``ｼﾞｮﾝ･ｽﾐｽ``) dilebarkan dulu.
        answer: Keluaran mesin, misalnya ``"John Smith."``; ・ dan · dianggap spasi.

    Returns:
        Nama Latin dengan satu spasi antar-bagian, atau ``None`` bila ditolak.
    """
    parts = [part for part in _PART_SEPARATOR_RE.split(widen_halfwidth_kana(kana)) if part]
    words = _PART_SEPARATOR_RE.split(answer.strip(_TRAILING))
    words = [_capitalize_lower(_title_if_shouting(word)) for word in words if word]
    if not parts or len(words) != len(parts) or not is_latin(" ".join(words)):
        return None
    for part, word in zip(parts, words):
        raw_word = "".join(
            ch for ch in strip_diacritics(word.casefold()) if "a" <= ch <= "z"
        )
        reference = kana_to_romaji(part, "plain")
        slavic_devoiced = (
            part.endswith("フ")
            and raw_word.endswith("v")
            and sounds_alike(reference, word[:-1] + "f")
        )
        if (
            not word[0].isupper()
            or raw_word in data.COMMON_ENGLISH_WORDS
            or not (
                sounds_alike(reference, word)
                or slavic_devoiced
                or _sounds_european(part, reference, word)
            )
            or not _keeps_final_vowels(reference, word)
        ):
            return None
    return " ".join(words)


def _sounds_european(kana: str, reference: str, word: str) -> bool:
    """``word`` cocok dengan ``reference`` bila r/l akhir suku kata diucapkan (ejaan Eropa).

    ``normalize`` membuang ``r`` sesudah vokal sebagai ``r`` non-rotik bahasa Inggris
    (Charlotte シャーロット), dan ``l`` ikut terbuang karena l↔r disamakan lebih dulu. Ejaan
    Jerman/Eropa justru mengucapkannya dan katakana menulisnya ル: ヒルデガルト/``Hildegard``,
    ゲオルグ/``Georg``, ベルント/``Bernd``, ロルフ/``Rolf``. Syarat jalur ini (semua):

    - katakana memuat ル + konsonan atau ル di akhir (``_CODA_LIQUID_KANA_RE``; ルーク tidak);
    - r/l akhir suku kata di ejaan sejajar dengan ル itu (``_codas_align``): huruf sesudahnya
      sejalan dengan konsonan sesudah ル (``_EUROPEAN_CODA_FITS``; Rainfall, Marshiness, Halch
      untuk ラインハルト, マルティネス, ハルト tidak);
    - bunyi cocok (``_european_variants``) dengan ambang ``EUROPEAN_MIN_SIMILARITY`` (lebih
      ketat), tanpa potongan biaya s↔t, ambang kerangka sama dengan ``sounds_alike``, dan
      konsonan akhir sama bila bacaan berakhir konsonan (Martinet untuk マルティネス tidak);
    - bukan kata Inggris yang sebunyi dengan nama (``EUROPEAN_DECOY_WORDS``: Cult, Mild, Gold,
      dan ``data.COMMON_ENGLISH_WORDS``);
    - katakana bukan bacaan nama Jepang yang dikenal (``data.name_readings``: ハルト = Haruto,
      bukan ``Halt``/``Hart``);
    - huruf awal ejaan sejalan dengan konsonan awal katakana (``_EUROPEAN_ONSETS``: ゴルト bukan
      ``Jolt``, ハルト bukan ``Fardo``).

    Hanya ``validate_foreign_name`` yang memakainya; ``matches_reading`` (nama Jepang) tidak.
    """
    raw = "".join(ch for ch in unicodedata.normalize("NFD", word.casefold()) if "a" <= ch <= "z")
    letters = raw.replace("y", "i")
    codas = [_romaji_onset(kana_to_romaji(kana[m.end():], "plain"))
             for m in _CODA_LIQUID_KANA_RE.finditer(kana)]
    if (not codas or raw in EUROPEAN_DECOY_WORDS or raw in data.COMMON_ENGLISH_WORDS
            or kata_to_hira(kana) in data.name_readings()
            or not _onset_fits(_romaji_onset(reference), raw)):
        return False
    # th Jerman/Belanda dibaca t (Berthold ベルトルト, Lothar ロタール).
    spellings = [spelling for spelling in dict.fromkeys((letters, letters.replace("th", "t")))
                 if _codas_align(codas, spelling)]
    ref = _normalize(reference, keep_e=True)
    ref_skeleton = _consonants(ref)
    variants = {form for spelling in spellings
                for form in _european_variants(spelling, german_w="ヴ" in kana)}
    for answer in variants:
        if (_ratio(ref, answer, epenthetic=True, near=False) >= EUROPEAN_MIN_SIMILARITY
                and _ratio(ref_skeleton, _consonants(answer), epenthetic=False)
                >= MIN_SKELETON_SIMILARITY
                and (ref[-1] in VOWELS or answer[-1:].translate(_DEVOICED)
                     == ref[-1].translate(_DEVOICED))):
            return True
    return False


def _european_variants(letters: str, *, german_w: bool = False) -> set[str]:
    """Bentuk bunyi ejaan Eropa ``letters`` untuk ``_sounds_european``.

    ``l`` dipertahankan, lalu ``r`` juga, masing-masing dengan dan tanpa pelemahan konsonan akhir
    (``_DEVOICED``). ``e`` akhir dipertahankan (Gertrude dan George bukan Gertrud dan Georg);
    sesudah n/m boleh juga dibuang (Verne ヴェルヌ, Persephone ペルセポネ). ei boleh dibaca ai
    (Reinhard ラインハルト), z boleh dibaca ts (Mozart モーツァルト), dan dt dibaca t (Arndt アルント).
    Bila ``german_w`` (katakana memuat ヴ), w juga boleh dibaca v (Ewald エーヴァルト, Waltraud
    ヴァルトラウト); tanpa ヴ tidak (シューベルト bukan ``Swelt``). Pemanggil sudah mengganti y dengan
    i (Halyard bukan ハラルト).
    """
    keep_e = (True, False) if len(letters) > 2 and letters[-2:] in ("ne", "me") else (True,)
    spellings = {letters, letters.replace("ei", "ai")}
    spellings |= {spelling.replace("z", "ts") for spelling in spellings}
    spellings |= {spelling.replace("dt", "t") for spelling in spellings}
    if german_w:
        spellings |= {spelling.replace("w", "v") for spelling in spellings}
    spellings |= {
        spelling[:-1] + "f" for spelling in spellings if spelling.endswith("v")
    }
    return {_normalize(spelling, keep_l=True, keep_r=keep_r, devoice=devoice, keep_e=final_e)
            for spelling in spellings for keep_r in (False, True) for devoice in (False, True)
            for final_e in keep_e}


def _onset_fits(kana_onset: str, raw: str) -> bool:
    """Huruf awal ejaan ``raw`` sejalan dengan konsonan awal katakana (``_EUROPEAN_ONSETS``).

    ``sh``/``sch`` di awal ejaan hanya untuk シ/シャ (ゾルト bukan ``Short``).
    """
    if raw.startswith(("sh", "sch")) and kana_onset != "sh":
        return False
    return raw.startswith(_EUROPEAN_ONSETS.get(kana_onset, (kana_onset[:1],)))


def _romaji_onset(romaji: str) -> str:
    """Konsonan awal ``romaji`` (sh/ch/ts utuh, selain itu satu huruf), kosong bila diawali vokal.

    ``kya`` → ``k``, ``nto`` (ン + ト) → ``n``, ``shi`` → ``sh``, ``a`` → kosong.
    """
    run = _CONSONANT_RUN_RE.match(romaji)
    cluster = run.group() if run is not None else ""
    return next((digraph for digraph in ("sh", "ch", "ts") if cluster.startswith(digraph)),
                cluster[:1])


def _codas_align(codas: list[str], letters: str) -> bool:
    """Konsonan sesudah tiap ル akhir suku kata (``codas``, dari ``_romaji_onset``) sejalan berurutan
    dengan huruf sesudah r/l akhir suku kata di ``letters`` (``_EUROPEAN_CODA_FITS``). ``r`` ejaan
    yang tidak berpasangan boleh dilewati: katakana menulisnya ー (Arnold アーノルド)."""
    pending = list(codas)
    for match in _CODA_LIQUID_SPELLING_RE.finditer(letters):
        run = _CONSONANT_RUN_RE.match(letters, match.end())
        cluster = run.group() if run is not None else ""
        if pending and _coda_fits(pending[0], cluster):
            pending.pop(0)
        elif match.group() != "r":
            return False
    return not pending


def _coda_fits(kana_consonant: str, cluster: str) -> bool:
    """Huruf ejaan ``cluster`` sesudah r/l sejalan dengan konsonan katakana sesudah ル."""
    allowed = _EUROPEAN_CODA_FITS.get(kana_consonant, (kana_consonant[:1],))
    return cluster == "" if not kana_consonant else cluster.startswith(allowed)


def _keeps_final_vowels(reference: str, word: str) -> bool:
    """Vokal akhir bacaan yang menyusul vokal lain (オリヴィエ ``...ie``) harus terwakili jawaban.

    Vokal itu suku kata sendiri, bukan vokal epentetik, jadi padanan Inggris yang
    membuangnya adalah nama lain: オリヴィエ/``Oliver`` ditolak, ``Olivier`` lolos.
    Jawaban dianggap mewakilinya bila (a) bentuk normalnya (Hepburn atau Inggris) berakhir
    vokal itu tepat sesudah vokal lain (マリア/``Maria``, ノア/``Noah``, ローレライ/``Lorelei``,
    カシオペア/``Cassiopeia``), atau (b) vokal akhirnya ア untuk ``-r`` non-rotik Inggris
    yang vokal di depannya cocok (``_keeps_r_vowel``: セオドア/``Theodore``, シンクレア/
    ``Sinclair``, アリステア/``Alistair``). オリヴィア/``Oliver`` tetap ditolak: ``-er``
    tidak pernah ditulis イア.
    """
    ref = normalize(reference)
    if len(ref) < 2 or ref[-1] not in VOWELS or ref[-2] not in VOWELS or ref[-1] == ref[-2]:
        return True
    for english in (False, True):
        answer = normalize(word, english)
        if len(answer) > 1 and answer[-1] == ref[-1] and answer[-2] in VOWELS:
            return True
    return _keeps_r_vowel(ref, word)


def _keeps_r_vowel(ref: str, word: str) -> bool:
    """Bacaan ``...Va`` (エア, オア, イア, ウア) sebagai ``-r``/``-re`` non-rotik jawaban.

    Katakana menulis ``-r`` non-rotik sesudah vokal sebagai ア, dan vokal sebelum ア
    mengikuti ejaan vokal di depan ``r`` (``R_VOWEL_SPELLINGS``): ``Theodore`` → セオドア
    (``o``), ``Sinclair`` → シンクレア (``ai``), ``Moore`` → ムーア (``oo``).
    """
    letters = "".join(ch for ch in unicodedata.normalize("NFD", word.casefold())
                      if "a" <= ch <= "z")
    match = _R_ENDING_RE.search(letters)
    return (ref[-1] == "a" and match is not None
            and match.group(1) in R_VOWEL_SPELLINGS.get(ref[-2], frozenset()))


def is_hepburn_echo(kana: str, word: str) -> bool:
    """Apakah ``word`` hanya mengulang romanisasi Hepburn ``kana``.

    Dibandingkan tanpa diakritik dan tanpa membedakan panjang vokal (``ou``,
    ``oo``, ``uu``, ... dianggap satu vokal): リョーマ/``Ryoma``, ``Ryouma``,
    dan ``Ryōma`` sama. Jawaban seperti itu menandakan nama Jepang yang ditulis
    katakana, bukan ejaan asing (フェリシア/``Felicia`` bukan gema).

    Args:
        kana: Satu bagian nama katakana tanpa ・.
        word: Satu kata jawaban mesin.
    """
    reference = _collapse_long_vowels(kana_to_romaji(widen_halfwidth_kana(kana), "plain"))
    return bool(reference) and _collapse_long_vowels(word) == reference


def is_near_echo(kana: str, word: str) -> bool:
    """Gema Hepburn yang hanya berbeda karena konsonan ganda (アマネ/``Amanne``, ラナ/``Ranna``).

    Hanya untuk katakana dengan kana Jepang biasa (tanpa ァィゥェォ kecil, ヴ, ヵ, ヶ).
    ``Hannah`` (ハンナ) dan ``Lana`` (ラナ) bukan gema. Fungsi ini hanya pendeteksi; yang
    memutuskan adalah ``pipeline.merge_foreign_answer``, dan gema diganti Hepburn hanya bila
    bagian katakana itu juga ``romaji.looks_japanese``: アマネ/``Amanne`` menjadi ``Amane``,
    sedangkan ラナ/``Ranna`` dan アナ/``Anna`` (nama Barat berkana biasa) dipakai apa adanya.
    """
    if not kana or _NATIVE_KANA_RE.search(widen_halfwidth_kana(kana)):
        return False
    reference = _collapse_long_vowels(kana_to_romaji(widen_halfwidth_kana(kana), "plain"))
    return bool(reference) and _GEMINATE_RE.sub(r"\1", _collapse_long_vowels(word)) == \
        _GEMINATE_RE.sub(r"\1", reference)


def looks_romanized(name: str) -> bool:
    """Apakah setiap kata ``name`` tersusun dari suku kata romanisasi Jepang saja.

    Diakritik (ō, ū) dan apostrof ``n'`` dibuang, konsonan ganda (``pp``, ``tch``) diringkas,
    lalu tiap kata harus habis dipecah menjadi suku kata konsonan(+y) + vokal atau ``n``
    (``m`` sebelum b/p/m: Shimbashi). ``Azumino``, ``Beppu``, ``Jun'ichirō`` lolos;
    ``Cloudy``, ``Field``, ``Mount Fuji`` tidak. Dipakai ``pipeline.clean_name`` hanya bila
    data proyek tidak punya kandidat bacaan sama sekali.
    """
    words = name.split()
    if not words:
        return False
    for word in words:
        decomposed = unicodedata.normalize("NFD", word.casefold())
        letters = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        letters = _GEMINATE_RE.sub(r"\1", letters.replace("'", "").replace("’", ""))
        if not _ROMANIZED_WORD_RE.fullmatch(letters):
            return False
    return True


def matches_reading(reading: str, answer: str) -> bool:
    """Periksa apakah ejaan (huruf besar atau kecil) terdengar seperti bacaan kana.

    Bila jumlah kata sama, tiap kata dibandingkan dengan pasangannya; bila tidak,
    seluruh bacaan dibandingkan dengan seluruh jawaban tanpa spasi. Jawaban juga
    dicoba dengan ``m`` di depan b/p/m dibaca ``n`` (Hepburn ん: ``Namba`` = なんば,
    ``Homma`` = ほんま); bentuk aslinya tetap dicoba lebih dulu (``Emma`` = えま).

    Args:
        reading: Bacaan kana, boleh berspasi (``やまだ たろう``).
        answer: Ejaan Latin dari mesin.
    """
    ref_words = [kana_to_romaji(word, "plain") for word in reading.split()]
    if not ref_words or not answer.split():
        return False
    for form in dict.fromkeys((answer, _HEPBURN_M_RE.sub("n", answer))):
        ans_words = form.split()
        if len(ref_words) == len(ans_words):
            if all(sounds_alike(ref, ans) for ref, ans in zip(ref_words, ans_words)):
                return True
        elif sounds_alike("".join(ref_words), "".join(ans_words)):
            return True
    return False


def _title_if_shouting(word: str) -> str:
    """``FELICIA`` → ``Felicia``, ``O'BRIEN`` → ``O'Brien``; kata lain dibiarkan."""
    if not word.isupper() or sum(ch.isalpha() for ch in word) < 2:
        return word
    return _WORD_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), word.lower())


def _capitalize_lower(word: str) -> str:
    """``jean-luc`` → ``Jean-Luc``; kata yang sudah berawalan kapital dibiarkan (``McCartney``)."""
    if not word[:1].islower():
        return word
    return _WORD_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), word)


def _collapse_long_vowels(latin: str) -> str:
    """Huruf a-z tanpa diakritik dengan vokal panjang diringkas (ryōma, ryouma → ryoma)."""
    decomposed = unicodedata.normalize("NFD", latin.casefold())
    letters = "".join(ch for ch in decomposed if "a" <= ch <= "z")
    return _LONG_VOWEL_RE.sub(lambda m: m.group()[0], letters)


def _consonants(text: str) -> str:
    """Buang vokal dari teks yang sudah dinormalisasi."""
    return "".join(ch for ch in text if ch not in VOWELS)


def _ratio(ref: str, ans: str, *, epenthetic: bool, near: bool = True) -> float:
    """``1 − jarak edit berbobot / panjang terpanjang``, minimal 0 (``near``: lihat
    ``_substitution``)."""
    longest = max(len(ref), len(ans))
    if longest == 0:
        return 0.0
    return max(0.0, 1.0 - _distance(ref, ans, epenthetic, near) / longest)


def _distance(ref: str, ans: str, epenthetic: bool, near: bool = True) -> float:
    """Jarak Levenshtein berbobot (lihat docstring modul)."""
    previous = [float(j) for j in range(len(ans) + 1)]
    for i, ref_ch in enumerate(ref, start=1):
        drop = EPENTHETIC_COST if epenthetic and _is_epenthetic(ref, i - 1) else 1.0
        current = [previous[0] + drop]
        for j, ans_ch in enumerate(ans, start=1):
            current.append(min(previous[j] + drop, current[j - 1] + 1.0,
                               previous[j - 1] + _substitution(ref_ch, ans_ch, near)))
        previous = current
    return previous[-1]


def _is_epenthetic(text: str, index: int) -> bool:
    """Vokal u/o/i yang diapit dua konsonan: kemungkinan sisipan katakana."""
    return (text[index] in EPENTHETIC_VOWELS and 0 < index < len(text) - 1
            and text[index - 1] not in VOWELS and text[index + 1] not in VOWELS)


def _substitution(left: str, right: str, near: bool = True) -> float:
    """Biaya mengganti satu huruf: 0 sama, ``NEAR_COST`` untuk s↔t (bila ``near``), selain itu 1."""
    if left == right:
        return 0.0
    return NEAR_COST if near and {left, right} == {"s", "t"} else 1.0
