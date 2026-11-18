"""Perapian hasil terjemahan: tanda baca, kutip, dan tata bahasa di sekitar nama.

Masalah yang ditangani berasal dari keluaran mesin sungguhan
(LAPORAN_RISET 6.1 dan KRITIK_RISET no. 13):

- tanda baca Jepang yang tertinggal (、。！？「」（）) dan spasi lebar penuh U+3000,
- kutip campur gaya LaTeX ````…''``, kutip keriting “…”, dan kutip lurus,
- spasi hilang setelah kutip penutup (``sekolah?"kata Tanaka``),
- artikel bahasa Inggris sebelum nama (``the Tanaka``) dan posesif terpisah
  (``Tanaka 's``),
- klitik bahasa Indonesia yang menempel ke nama (``Tanakanya`` → ``Tanaka-nya``,
  EYD V tanda hubung aturan 5 dan 7),
- huruf kecil di awal kalimat (Google: おはようございます。 → ``good morning.``),
- huruf kapital palsu setelah koma (Google: 美咲ちゃん、おはよう！ →
  ``Misaki-chan, Good morning!``), lihat ``lower_after_comma``,
- kata ganti orang ketiga bergender salah dalam bahasa Inggris (美咲 perempuan →
  ``checked his watch``), lihat ``fix_pronouns``. Kapan kata ganti boleh diubah
  diputuskan pemanggil (``pipeline.pronoun_gender``).
- tanda panjang ``ー`` dan tilde ``〜``/``～`` yang ikut tersalin di belakang huruf Latin
  (``Haiー!``, ``Tunggu〜!``), lihat ``normalize_latin_marks``.

Semua fungsi murni dan idempoten: memanggilnya dua kali memberi hasil sama.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Collection, Iterable, Sequence

from .phonetic import similarity, skeleton_similarity
from .romaji import kana_to_romaji
from .style import DASH_BREAKS

logger = logging.getLogger(__name__)

_JAPANESE_PUNCT = str.maketrans({
    "、": ", ", "，": ", ", "。": ". ", "！": "! ", "？": "? ",
    "「": '"', "」": '"', "『": '"', "』": '"', "（": "(", "）": ")",
    "\u3000": " ",
})
_LATEX_QUOTES_RE = re.compile(r"``(.*?)''")
_CURLY_DOUBLE = str.maketrans({"“": '"', "”": '"', "„": '"'})
_QUOTE_PAIR_RE = re.compile(r'"([^"\n]*)"')
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([,.!?;:%)\]}])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[{])[ \t]+")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_DOUBLE_THE_RE = re.compile(r"\b(the)\s+the\b", re.IGNORECASE)
_LEADING_LOWER_RE = re.compile(
    r"""^([\s"'“‘(\[«""" + re.escape(DASH_BREAKS) + r"""]*)([a-z])"""
)
# Huruf Latin (ASCII sampai Latin Extended-B) tepat sebelum tanda panjang atau tilde.
_LATIN = "A-Za-z\u00c0-\u024f"
_JAPANESE_AFTER_MARK = r"(?![ーｰぁ-ゖァ-ヺｦ-ﾝ\u3400-\u9fff])"
_LONG_MARK_RE = re.compile(rf"(?<=[{_LATIN}])([ーｰ]+){_JAPANESE_AFTER_MARK}")
_DASH_FOLLOWER_RE = re.compile(rf"[ \t]*[{_LATIN}]")
_LATIN_WORD_LEFT_RE = re.compile(rf"[{_LATIN}]*$")
_LATIN_WORD_RIGHT_RE = re.compile(rf"[{_LATIN}]*")
# Rangkaian tilde yang menempel di huruf Latin/angka, boleh bercampur ``~`` dan ``ー`` di
# belakangnya (``Tunggu〜〜!``, ``Hei〜ー!``, ``Tunggu~〜!``); ``ー`` yang disusul huruf
# Jepang tidak ikut (``Kaito〜ーっ``). Juga rangkaian tepat sebelum huruf Latin/angka.
_TILDE_RE = re.compile(
    rf"(?<=[{_LATIN}0-9])~*[〜～](?:[〜～~]|[ーｰ]+{_JAPANESE_AFTER_MARK})*"
    rf"|[〜～][〜～~]*(?=[{_LATIN}0-9])")
_VOWELS = frozenset("aiueoAIUEO")
_EM_DASH = "\u2014"
_EN_ARTICLES = r"(?:[Tt]he|[Aa]n?)"
_ID_CLITICS = r"(?:nya|ku|mu)"

COMMON_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset("""
        Good Thank Thanks Yes No Please The But And Then It It's This That That's What What's
        Why How Where When Who Let's Let Sorry Hello Hi Hey Okay We You You're He She They My
        Your Our Their Is Are Was Were Do Does Did Don't Can Can't Could Would Should So Or If
        Because Well Oh Ah Um Uh Wait Come See Welcome Excuse There Here Now Just
        Really Maybe Of In On At To For With Not Even Still Also Too Very All Some Again Right
        Huh Wow Any Everyone Everything Nothing Something Someone Let's
    """.split()),
    "id": frozenset("""
        Selamat Terima Ya Iya Tidak Bukan Tapi Tetapi Lalu Kemudian Aku Kamu Dia Saya Itu Ini
        Apa Apakah Kenapa Mengapa Bagaimana Siapa Di Ke Dari Dan Atau Jadi Maaf Tolong Ayo
        Halo Hai Oke Baik Kita Kami Mereka Sudah Belum Jangan Ada Senang Sampai Permisi Benar
        Begitu Nah Eh Ah Oh Hm Sekarang Nanti Juga Masih Hanya Kalau Jika Karena Silakan Boleh
        Bisa Mau Akan Sedang Sangat Sekali Wah Aduh Yuk Sama Semua Seperti Untuk Dengan Pada
    """.split()),
}
"""Kata fungsi/kata umum yang hurufnya diturunkan bila muncul kapital setelah koma.

Sengaja tanpa kata yang juga lazim sebagai nama diri (May, Will, Grace, Mari,
kota Nice, permainan Go) dan tanpa "I". Daftar terpisah per bahasa sasaran.
"""
_ROMAJI_KIN = frozenset("""
    Onii Onee Nii Nee Ani Aniki Ane Aneki Okaa Otou Kaa Tou Ojii Obaa Jii Baa Oji Oba
    Oniichan Oneechan Oniisan Oneesan Niisan Neesan Okaasan Otousan Kaasan Tousan Ojiisan
    Obaasan Ojiichan Obaachan Ojisan Obasan
""".split())
"""Sapaan kekerabatan Jepang romaji; bentuk bertanda hubung dicocokkan lewat bagian depannya
(``Onii-chan`` → ``Onii``), karena kata sesudah sapaan berhenti di tanda hubung."""
ALWAYS_CAPITAL: dict[str, frozenset[str]] = {
    "en": frozenset("""
        Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April
        May June July August September October November December Christmas Xmas Easter
        Halloween Thanksgiving Valentine Hanukkah Ramadan Eid Diwali Obon Tanabata Santa
        English Japanese Chinese Korean French German Spanish Italian Russian Portuguese Dutch
        Arabic Hindi Thai Vietnamese Indonesian Malay Filipino Greek Turkish Latin Swedish
        Norwegian Danish Finnish Irish Scottish Welsh American British Canadian
        Australian Mexican Brazilian Indian European Asian African Western Japan America
        England France Germany China Korea Europe Asia Africa Italy Spain Russia Canada India
        Brazil Mexico Australia Indonesia Thailand Vietnam Taiwan Singapore Philippines Egypt
        Greece Hawaii London Paris Tokyo Osaka Kyoto Seoul God Lord Jesus Christ Buddha
        Allah Bible Christian Buddhist Muslim Catholic Shinto Mom Mommy Mum Mummy Dad Daddy
        Mama Papa Mother Father Grandma Grandpa Granny Grandmother Grandfather Aunt Auntie
        Uncle Brother Sister Master Boss Captain Mr Mrs Ms Mx Dr Prof Professor Sir Madam
        Mt St Ste Jr Sr Ft Sensei Senpai
    """.split()) | _ROMAJI_KIN,
    "id": frozenset("""
        Senin Selasa Rabu Kamis Jumat Jum'at Sabtu Minggu Januari Februari Maret April Mei
        Juni Juli Agustus September Oktober November Desember Natal Paskah Lebaran Idulfitri
        Iduladha Imlek Nyepi Waisak Ramadan Ramadhan Halloween Valentine Tanabata Obon Jepang
        Inggris Indonesia Cina Tiongkok Korea Amerika Prancis Perancis Jerman Belanda Rusia
        Italia Spanyol Arab Eropa Asia Afrika Thailand Kanada India Brasil Meksiko Australia
        Vietnam Taiwan Singapura Filipina Mesir Yunani Hawaii London Paris Tokyo Osaka Kyoto
        Seoul Jakarta Bandung Surabaya Yogyakarta Bali Lombok Sumatra Sumatera Kalimantan
        Sulawesi Papua Aceh Medan Semarang Makassar Malang Bogor Depok Bekasi Tangerang
        Batam Palembang Denpasar Tuhan Allah Yesus Kristus Buddha
        Alkitab Alquran Islam Kristen Katolik Hindu Ibu Ayah Bapak Kakak Adik Nenek Kakek
        Paman Bibi Tante Om Mama Papa Bunda Abang Kak Bu Pak Dik Mbak Mas Bang Nek Kek Opa
        Oma Eyang Mbah Pakde Pakdhe Bude Budhe Paklik Bulik Uwak Akang Teteh Tuan Nyonya
        Nona Profesor Sensei Senpai Gn Jl
    """.split()) | _ROMAJI_KIN,
}
"""Kata yang tetap kapital sesudah sapaan (``lower_after_vocative``), sekalipun tanpa nama.

Nama hari, bulan, hari raya, bahasa/bangsa, negara dan kota utama (simetris en/id),
Tuhan dan kitab, sapaan kekerabatan (dipakai sebagai acuan atau sapaan, EYD: ``Ibu
memanggilmu``; juga romaji ``Onii-chan``), gelar sapaan, dan singkatan bertitik di depan
nama (``Mt. Takao``, ``St. Luke's``). Daftar ini hanya melindungi: kata di dalamnya
diperlakukan seperti sebelum aturan sapaan ada. Bahasa Inggris juga mengenali bentuk jamak
``-s`` (``Mondays``); bentuk berapostrof (ASCII atau ``’``) dicocokkan utuh (``Jum'at``) atau
lewat bagian sebelum apostrof (``Mom's``). ``Polish`` sengaja tidak ada (kata kerja
``polish``). Nama diri lain biasanya terlindungi oleh ``_echoes_lead`` atau ``proper_nouns``.
"""
_ID_KIN_COMMON = frozenset({"tiri", "kandung", "angkat"})
_COMMON_NOUN_AFTER: dict[str, dict[str, frozenset[str]]] = {
    "id": {"Minggu": frozenset({"depan", "lalu", "ini", "kemarin"}),
           "Ibu": frozenset({"kota", "jari", "pertiwi"}) | _ID_KIN_COMMON,
           "Ayah": _ID_KIN_COMMON, "Bapak": _ID_KIN_COMMON,
           "Adik": frozenset({"kelas", "tingkat", "ipar"}),
           "Kakak": frozenset({"kelas", "tingkat", "ipar"}),
           "Mas": frozenset({"kawin"})},
}
"""Kata ``ALWAYS_CAPITAL`` yang menjadi kata umum bila disusul kata tertentu (``Minggu
depan``, ``Ibu kota``, ``Adik kelas``, ``Mas kawin``); kata penyusul boleh berklitik
(``Ibu jarimu``). Bentuk ulang berhubung (``Ibu-ibu``) juga kata umum."""
_AFTER_COMMA_RE = re.compile(r"(?<=[,，]) +([A-Z][a-z]*(?:['’][a-z]+)?)\b")
_NEXT_WORD_RE = re.compile(r"\s+([A-Za-z])")
# Kata itu anggota daftar berkoma: diikuti koma, atau "and/or/dan/atau" + kata kapital.
_LIST_ITEM_RE = re.compile(r"[,，]|\s+(?:and|or|dan|atau)\s+[A-Z]")
# Sapaan di awal kalimat: boleh didahului spasi, kutip, kurung, tanda dialog
# (``style.DASH_BREAKS``, sama dengan ``pipeline._LEADING_VOCATIVE_RE``), dan tag format.
_VOCATIVE_PREFIX_RE = re.compile(
    r"""(?:[\s"'“‘(\[«""" + re.escape(DASH_BREAKS) + r"""]|<[^<>\n]*>|\{\\[^{}\n]*\})*""")
# Koma sesudah nama sapaan lalu kata berhuruf awal kapital (grup 1 = kata itu).
_VOCATIVE_WORD_RE = re.compile(rf"[ \t]*[,，][ \t]+([A-Z][{_LATIN}]*(?:['’][{_LATIN}]+)?)")
# Kata berkapital tepat sesudah kata berakhir huruf kecil/angka dan spasi (nama diri).
_MID_CAPITAL_RE = re.compile(
    rf"(?<=[a-z0-9ß-öø-ÿ])[ \t]+([A-Z][{_LATIN}]+(?:['’][{_LATIN}]+)?)")
_APOSTROPHE_RE = re.compile(r"['’]")
# Kata sesudah kata sapaan (huruf Latin beraksen ikut: ``Ōta``).
_VOCATIVE_NEXT_RE = re.compile(rf"\s+([{_LATIN}]+)")
_ID_CLITIC_END_RE = re.compile(rf"{_ID_CLITICS}$")
# Awal sumber sesudah sapaan (sudah NFKC): kata katakana (berhenti di ・) atau kata Latin.
_LEAD_KATAKANA_RE = re.compile("[ァ-ヺ][ァ-ヺー]*")
_LEAD_LATIN_RE = re.compile("[A-Za-z]{2,}")
LEAD_MIN_SIMILARITY = 0.6
"""Ambang ``similarity`` dan ``skeleton_similarity`` kata sesudah sapaan terhadap romanisasi
katakana di awal sumber (``_echoes_lead``). Lebih longgar dari ``phonetic.MIN_SIMILARITY``
karena hanya menentukan kapital, bukan menerima ejaan nama: ``India``/インド (0,6) lolos,
``Get``/ゲーム dan ``Need``/ネット (kerangka 0,5) tidak."""

PRONOUN_FORMS = {
    "m": {"she": "he", "hers": "his", "herself": "himself"},
    "f": {"he": "she", "himself": "herself"},
}
"""Pemetaan kata ganti orang ketiga tunggal ke gender sasaran (his/her diatur terpisah).

Kata ganti objek (him, dan her sebagai objek) sengaja tidak ada: objek hampir
selalu merujuk orang LAIN selain subjek bernama (``Misaki smiled at him``), dan
orang lain itu sering tersirat sehingga tidak terlihat oleh pemanggil.
"""
OBJECT_FOLLOWERS = frozenset("""
    to at in on into onto with without for from by about of over under up down out off away
    around through across along toward towards behind inside outside near beside like as than
    after before and or but so nor yet if when while because since until though although
    whether then there here now too enough today tonight tomorrow yesterday already
    still just once again anymore alone either neither not never a an the this that these those
    some any each all both my your his her our their its me you him them us it go come
    feel cry laugh know be sit stand stay leave think say speak wait try get make see do eat die
    fall immediately quietly tightly gently softly closely carefully quickly slowly firmly warmly
    directly
""".split())
"""Kata setelah "her" yang menandakan "her" objek (dibiarkan), bukan posesif (→ his).

"her" + kata lain (kata benda/adjektiva: ``her bag``, ``her old coat``,
``her very own``, ``her every move``) dianggap posesif. Kata yang bisa benda atau
kerja (smile, look, back) sengaja tidak dimasukkan: dalam narasi, ``her smile``
lebih sering posesif. ``home`` diatur terpisah (``_POSSESSIVE_HOME_AFTER``).
"""
DITRANSITIVE_VERBS = frozenset("""
    give gives gave given giving hand hands handed handing show shows showed shown showing
    tell tells told telling send sends sent sending offer offers offered offering buy buys
    bought buying bring brings brought bringing teach teaches taught teaching ask asks asked
    asking pass passes passed passing lend lends lent lending owe owes owed owing promise
    promises promised promising get gets got getting make makes made making leave leaves left
    leaving pay pays paid paying throw throws threw thrown toss tossed sell sells sold write
    wrote written cook cooked find found save saved wish wished
""".split())
"""Kata kerja dua objek: ``gave her flowers`` adalah objek, bukan posesif."""
_POSSESSIVE_HOME_AFTER = frozenset("""
    to at from into in inside outside near toward towards reach reached
""".split())
"""``her home`` posesif hanya setelah kata ini (``back to her home``; ``took her home`` objek)."""
_PRONOUN_RE = re.compile(r"\b(he|him|his|himself|she|her|hers|herself)\b", re.IGNORECASE)
PARTNER_WORDS = ("girlfriend", "boyfriend", "lover", "sweetheart", "partner", "gf", "bf",
                 "fiance", "fiancé", "fiancee", "fiancée", "darling")
"""Kata benda pacar: bila ada di terjemahan, 彼女/彼 di sumber berarti pacar
(``fix_explicit_pronouns``)."""
_PARTNER_RE = re.compile(r"\b(?:%s)s?\b" % "|".join(PARTNER_WORDS), re.IGNORECASE)
_FOLLOWING_WORD_RE = re.compile(r"[ \t]*([A-Za-z]+)")
_PRECEDING_WORD_RE = re.compile(r"([A-Za-z]+)[ \t]*$")


def tidy(text: str, lang: str, *, straight_quotes: bool = True) -> str:
    """Rapikan tanda baca dan spasi hasil terjemahan.

    Args:
        text: Teks terjemahan (boleh beberapa baris).
        lang: Bahasa sasaran (``id`` atau ``en``); aturan saat ini sama untuk
            keduanya, parameter disediakan agar pemanggil tidak perlu berubah
            bila aturan khusus bahasa ditambahkan.
        straight_quotes: Ubah ````…''`` dan “…” menjadi kutip lurus ``"…"``.

    Returns:
        Teks yang sudah dirapikan, per baris.
    """
    logger.debug("tidy %d karakter (%s)", len(text), lang)
    return "\n".join(_tidy_line(line, straight_quotes) for line in text.split("\n"))


def normalize_latin_marks(text: str) -> str:
    """Rapikan ``ー`` dan ``〜`` Jepang yang menempel di huruf Latin keluaran mesin.

    Mesin kadang menyalin tanda panjang dari ucapan yang dipanjangkan (はーい！ →
    ``Haiー!``). Tanda itu bukan huruf, jadi tidak dihitung sisa, tetapi tetap asing bagi
    pembaca. Aturannya:

    - ``ー``/``ｰ`` (berapa pun) sesudah vokal Latin tanpa diakritik menjadi satu vokal yang
      sama (``Haiー!`` → ``Haii!``), cara menulis pemanjangan yang lazim di subtitle
      Indonesia dan Inggris. Vokal tambahan berhuruf kapital hanya bila kata Latin tempat
      tanda itu menempel seluruhnya kapital dan lebih dari satu huruf (``NOー!`` →
      ``NOO!``); selain itu huruf kecil (``Eー?`` → ``Ee?``, ``Oーi!`` → ``Ooi!``);
    - sesudah konsonan, ``y``, atau vokal bermakron tanda itu dibuang (``Heyー!`` →
      ``Hey!``, ``Kōー`` → ``Kō``);
    - dua tanda atau lebih yang langsung diikuti kata Latin adalah tanda pisah
      (犯人はカイトーーいや → ``Kaitoーーno``), jadi menjadi em dash (``Kaito—no``);
    - rangkaian ``〜``/``～`` yang menempel di huruf Latin atau angka menjadi SATU ``~``,
      termasuk ``~`` dan ``ー`` yang bercampur di belakangnya (``Tunggu〜!`` dan
      ``Tunggu〜〜!`` → ``Tunggu~!``, ``Hei〜ー!`` → ``Hei~!``, ``3〜5`` → ``3~5``).

    Tanda yang diikuti huruf Jepang (``Kaitoーっ``) atau tidak menempel di huruf Latin
    (``ーはい``, ``ね〜``) tidak diubah: itu bagian dari sisa Jepang yang sudah ditangani
    pemeriksaan sisa di pipeline.
    """
    def replace(match: re.Match[str]) -> str:
        """Bentuk pengganti satu deretan tanda panjang Jepang di belakang huruf Latin."""
        marks = match.group(1)
        before = text[match.start() - 1]
        if len(marks) > 1 and _DASH_FOLLOWER_RE.match(text, match.end()):
            return _EM_DASH
        if before not in _VOWELS:
            return ""
        return before if _shouting_word(text, match.start(), match.end()) else before.lower()

    return _TILDE_RE.sub("~", _LONG_MARK_RE.sub(replace, text))


def _shouting_word(text: str, start: int, end: int) -> bool:
    """Kata Latin di sekitar ``text[start:end]`` seluruhnya kapital dan lebih dari satu huruf.

    ``NOー`` dan ``OーI`` kata teriakan (vokal tambahan kapital); ``Eー`` dan ``Oーi`` bukan.
    """
    left = _LATIN_WORD_LEFT_RE.search(text, 0, start)
    right = _LATIN_WORD_RIGHT_RE.match(text, end)
    word = (left.group() if left else "") + (right.group() if right else "")
    return len(word) > 1 and word.isupper()


def fix_names(text: str, names: list[str], lang: str) -> str:
    """Perbaiki tata bahasa di sekitar nama yang sudah dirender.

    - ``en``: buang ``the``/``a``/``an`` tepat sebelum nama (kecuali nama itu
      sendiri diawali "the", mis. "the Royal Capital"), dan rapatkan posesif
      ``Tanaka 's`` → ``Tanaka's``.
    - ``id``: klitik -nya/-ku/-mu yang menempel diberi tanda hubung.

    Args:
        text: Teks terjemahan.
        names: Bentuk nama final (hasil ``Renderer``) yang ada di teks.
        lang: Bahasa sasaran.

    Returns:
        Teks yang sudah diperbaiki.
    """
    for name in sorted(set(names), key=len, reverse=True):
        if not name:
            continue
        escaped = re.escape(name)
        if lang == "en":
            text = _fix_english(text, name, escaped)
        elif lang == "id":
            text = re.sub(rf"(?<!\w)({escaped}){_ID_CLITICS}\b", _hyphenate, text)
    return text


def capitalize_first(text: str) -> str:
    """Jadikan huruf kecil ASCII pertama kalimat huruf besar (boleh didahului kutip/kurung).

    Pemanggil hanya memakainya untuk kalimat yang sumbernya diawali huruf Jepang,
    sehingga nama produk berhuruf kecil di awal kalimat sumber (``jptrans``,
    ``iPhone``) tidak ikut diubah.

    Args:
        text: Satu kalimat terjemahan.

    Returns:
        Kalimat dengan huruf pertama kapital; teks lain tidak berubah.
    """
    return _LEADING_LOWER_RE.sub(lambda m: m.group(1) + m.group(2).upper(), text, count=1)


def lower_after_comma(text: str, lang: str, names: Sequence[str] = ()) -> str:
    """Turunkan huruf kapital palsu tepat setelah koma: ``Misaki-chan, Good morning!``.

    Kata diturunkan hanya bila semua syarat terpenuhi:

    - kata itu (atau bagian sebelum apostrof: ``It's``) ada di ``COMMON_WORDS[lang]``;
    - bukan "I" (``I``, ``I'm``) dan bukan awal nama hasil render (``names``);
    - koma langsung diikuti spasi lalu huruf, jadi awal kutipan baru
      (``, "Good morning!"``) tidak tersentuh;
    - kata berikutnya tidak berhuruf kapital (kecuali awal nama hasil render),
      agar judul bergaya Title Case (``Episode 1, The Beginning``) tidak rusak;
    - kata itu bukan anggota daftar berkoma (diikuti koma, atau ``and``/``or``/
      ``dan``/``atau`` + kata kapital), agar nama diri yang tidak dimasking
      (``Paris, Nice, and Lyon``) tidak ikut diturunkan.

    Args:
        text: Satu kalimat terjemahan.
        lang: Bahasa sasaran (``id`` atau ``en``); bahasa lain tidak diubah.
        names: Bentuk akhir entitas yang dipasang di kalimat itu.

    Returns:
        Teks dengan huruf kapital palsu setelah koma diturunkan.
    """
    words = COMMON_WORDS.get(lang)
    if not words:
        return text

    def lower(match: re.Match[str]) -> str:
        word = match.group(1)
        normalized_word = word.replace("’", "'")
        base = _APOSTROPHE_RE.split(word)[0]
        start, end = match.span(1)
        if (
            base == "I"
            or not (normalized_word in words or base in words)
            or _starts_name(text, start, names)
        ):
            return match.group(0)
        following = _NEXT_WORD_RE.match(text, end)
        if (following and following.group(1).isupper()
                and not _starts_name(text, following.start(1), names)):
            return match.group(0)
        if _LIST_ITEM_RE.match(text, end):
            return match.group(0)
        return match.group(0)[:start - match.start()] + word[0].lower() + word[1:]

    return _AFTER_COMMA_RE.sub(lower, text)


def lower_after_vocative(
    text: str, lang: str, names: Sequence[str] = (), proper: Collection[str] = frozenset(),
    lead: str = "",
) -> str:
    """Turunkan kapital kata pertama sesudah sapaan nama di awal kalimat (``Yūma, Tunggu``).

    Pemanggil (``Translator._finish``) memakainya hanya bila sumber diawali nama orang yang
    dimasking lalu ``、`` (悠真、ちょっと待って。), jadi kata sesudah ``Nama, `` adalah awal
    isi kalimat, bukan awal kalimat baru. Berbeda dari ``lower_after_comma``, kata itu tidak
    harus ada di ``COMMON_WORDS``. Kapital dipertahankan bila kata itu:

    - awal bentuk entitas lain hasil render (``Yui, Tokyo itu jauh.``);
    - kata ganti ``I`` beserta bentuk singkatnya (``Mei, I think so.``, ``I'm``);
    - berhuruf kapital sesudah huruf pertamanya: singkatan (``OK``, ``NHK``) termasuk bentuk
      jamak/posesifnya (``DVDs``, ``NHK's``), dan camelCase (``McDonald's``, ``YouTube``,
      ``O'Neill``), juga bila bagian sesudah tanda hubung berkapital (``Shangri-La``);
    - ada di ``proper``: kata yang di keluaran mesin dokumen yang sama muncul berkapital di
      tengah kalimat (``proper_nouns``), yaitu nama diri yang tidak dimasking;
    - ejaan kata katakana atau Latin yang mengawali sumber sesudah sapaan (``lead``,
      ``_echoes_lead``): nama diri yang tidak dimasking (ロンドン → ``London``);
    - ada di ``ALWAYS_CAPITAL[lang]`` (``_always_capital``), kecuali bentuk kata umumnya
      (``Minggu depan``, ``Ibu kota``, ``Ibu-ibu``);
    - disusul kata berkapital (``New York``), termasuk awal nama hasil render (gelar + nama:
      ``Yui, Professor Itō``, ``Rin, Kak Yuki``); hanya kata ``COMMON_WORDS`` yang disusul
      nama hasil render tetap diturunkan (``Rin, ayo Yuki``);
    - anggota daftar berkoma (``Paris, Nice, and Lyon``), sama seperti ``lower_after_comma``.

    Args:
        text: Satu kalimat terjemahan.
        lang: Bahasa sasaran (``id`` atau ``en``); bahasa lain tidak diubah.
        names: Bentuk akhir entitas yang dipasang di kalimat itu.
        proper: Kata nama diri dari ``proper_nouns``.
        lead: Sumber termasking sesudah ``、`` sapaan (``pipeline.vocative_lead``).

    Returns:
        Teks dengan kapital palsu sesudah sapaan diturunkan; teks lain tidak berubah.
    """
    if lang not in COMMON_WORDS:
        return text
    start = _VOCATIVE_PREFIX_RE.match(text).end()
    name = next((name for name in sorted(names, key=len, reverse=True)
                 if name and text.startswith(name, start)), "")
    match = _VOCATIVE_WORD_RE.match(text, start + len(name)) if name else None
    if match is None or _keeps_vocative_capital(match, lang, names, proper, lead):
        return text
    begin = match.start(1)
    return text[:begin] + text[begin].lower() + text[begin + 1:]


def _keeps_vocative_capital(match: re.Match[str], lang: str, names: Sequence[str],
                            proper: Collection[str], lead: str) -> bool:
    """Apakah kata sesudah sapaan (grup 1 ``match``) harus tetap kapital.

    Aturannya diuraikan di ``lower_after_vocative``; argumen sama dengan fungsi itu.
    """
    text, word = match.string, match.group(1)
    begin, end = match.span(1)
    base = _APOSTROPHE_RE.split(word)[0]
    common = base in COMMON_WORDS[lang]
    hyphen_capital = text[end:end + 1] == "-" and text[end + 1:end + 2].isupper()
    if (base == "I" or any(ch.isupper() for ch in word[1:]) or hyphen_capital
            or word in proper or base in proper or _starts_name(text, begin, names)
            or (not common and _echoes_lead(base, lead))
            or _always_capital(word, base, lang, text, end)):
        return True
    following = _VOCATIVE_NEXT_RE.match(text, end)
    if following and following.group(1)[0].isupper() and (
            not common or not _starts_name(text, following.start(1), names)):
        return True
    return _LIST_ITEM_RE.match(text, end) is not None


def _echoes_lead(base: str, lead: str) -> bool:
    """Apakah ``base`` ejaan kata yang mengawali sumber sesudah sapaan (nama tak dimasking).

    Sumber yang diawali kata Latin (``McDonald'sに``, ``Jr.の``) cocok bila ``base`` diawali
    kata itu (tanpa membedakan kapital). Sumber yang diawali katakana (``ロンドンは``) cocok
    bila romanisasi kata katakana pertamanya (berhenti di ``・``) mirip bunyi ``base``:
    ``similarity`` dan ``skeleton_similarity`` keduanya minimal ``LEAD_MIN_SIMILARITY``,
    dibaca sebagai Hepburn atau Inggris. Kata pinjaman umum juga cocok (コーヒー/``Coffee``),
    jadi kapitalnya dipertahankan seperti sebelum aturan sapaan ada.

    Args:
        base: Kata sesudah sapaan tanpa bagian berapostrof (``India`` dari ``India's``).
        lead: Sumber termasking sesudah ``、`` sapaan; kosong bila tidak diketahui.

    Returns:
        True bila kata itu tampak sebagai ejaan awal sumber.
    """
    head = unicodedata.normalize("NFKC", lead[:40]).lstrip()
    latin = _LEAD_LATIN_RE.match(head)
    if latin:
        return base.casefold().startswith(latin.group().casefold())
    kana = _LEAD_KATAKANA_RE.match(head)
    if kana is None:
        return False
    reading = kana_to_romaji(kana.group(), "plain")
    return any(similarity(reading, base, english) >= LEAD_MIN_SIMILARITY
               and skeleton_similarity(reading, base, english) >= LEAD_MIN_SIMILARITY
               for english in (False, True))


def _always_capital(word: str, base: str, lang: str, text: str, end: int) -> bool:
    """Apakah kata sesudah sapaan ada di ``ALWAYS_CAPITAL`` dan tidak dipakai sebagai kata umum.

    Kata umum: disusul kata ``_COMMON_NOUN_AFTER`` (boleh berklitik: ``Ibu jarimu``), atau
    bentuk ulang berhubung (``Ibu-ibu``, ``Minggu-minggu``). Apostrof tipografis ``’``
    disamakan dengan ``'`` (``Jum’at``).

    Args:
        word: Kata seperti tertulis (``Mom's``, ``Jum'at``).
        base: Bagian sebelum apostrof (``Mom``).
        lang: Bahasa sasaran.
        text: Kalimat utuh.
        end: Indeks akhir kata di ``text``.

    Returns:
        True bila kapitalnya harus dipertahankan.
    """
    words = ALWAYS_CAPITAL.get(lang, frozenset())
    word = word.replace("’", "'")
    plural = lang == "en" and base.endswith("s") and base[:-1] in words
    if not (word in words or base in words or plural):
        return False
    if text[end:end + len(base) + 1].casefold() == "-" + base.casefold():
        return False
    following = _VOCATIVE_NEXT_RE.match(text, end)
    if following is None:
        return True
    common_after = _COMMON_NOUN_AFTER.get(lang, {}).get(base, frozenset())
    after = following.group(1)
    return not (after in common_after or _ID_CLITIC_END_RE.sub("", after) in common_after)


def proper_nouns(texts: Iterable[str]) -> frozenset[str]:
    """Kata berkapital yang muncul di tengah kalimat di salah satu ``texts`` (nama diri).

    "Di tengah kalimat" berarti tepat sesudah kata yang berakhir huruf kecil atau angka dan
    spasi (``pergi ke Narnia``); kata sesudah koma, titik, kutip, penanda ``[[E1]]``, atau di
    awal teks tidak dihitung, jadi kapital palsu ``Nama, Tunggu`` di kalimat lain tidak
    dianggap nama diri. ``I`` dan bentuk singkatnya serta singkatan berhuruf kapital semua
    diabaikan (aturannya sendiri di ``lower_after_vocative``).

    Args:
        texts: Keluaran mesin (boleh masih berpenanda) untuk semua kalimat dokumen.

    Returns:
        Himpunan kata itu, persis seperti ditulis (``Narnia``).
    """
    found: set[str] = set()
    for text in texts:
        for match in _MID_CAPITAL_RE.finditer(text):
            word = match.group(1)
            if not word.isupper() and _APOSTROPHE_RE.split(word)[0] != "I":
                found.add(word)
    return frozenset(found)


def fix_pronouns(text: str, gender: str) -> str:
    """Samakan kata ganti orang ketiga tunggal bahasa Inggris dengan ``gender``.

    he/his/himself ↔ she/her/hers/herself, dengan kapitalisasi dipertahankan
    (``He`` → ``She``, ``HE'S`` → ``SHE'S``). Aturan:

    - Kata ganti objek tidak pernah diubah: ``him``, dan ``her`` yang objek
      (diikuti tanda baca, akhir teks, kata di ``OBJECT_FOLLOWERS``, atau
      didahului kata kerja dua objek: ``gave her flowers``). Objek hampir selalu
      merujuk orang lain selain subjek bernama, termasuk orang yang tersirat.
    - f → m: ``her`` posesif (diikuti kata benda/adjektiva) → ``his``; ``hers`` →
      ``his``; ``she`` → ``he``; ``herself`` → ``himself``.
    - m → f: ``his`` + tanda baca atau akhir teks → ``hers``; ``his`` + kata apa pun
      → ``her`` (``his home``, ``his very own`` tetap posesif); ``he`` → ``she``;
      ``himself`` → ``herself``.

    Teks di dalam kutip lurus (``"…"``, dialog) tidak diubah karena kata ganti di
    dialog bisa merujuk orang lain; kutip yang tidak ditutup dianggap berlanjut
    sampai akhir teks. Fungsi ini tidak memeriksa apakah kalimat memang hanya
    membicarakan satu orang; itu tugas pemanggil.

    Args:
        text: Satu kalimat terjemahan bahasa Inggris (kutip sudah diluruskan).
        gender: ``"m"`` atau ``"f"``; nilai lain membuat teks tidak berubah.

    Returns:
        Teks dengan kata ganti yang sudah disamakan.
    """
    if gender not in PRONOUN_FORMS:
        return text
    pieces = text.split('"')
    for index in range(0, len(pieces), 2):
        pieces[index] = _PRONOUN_RE.sub(lambda m: _swap_pronoun(m, gender), pieces[index])
    return '"'.join(pieces)


def fix_explicit_pronouns(text: str, gender: str, count: int) -> str:
    """Samakan SEMUA kata ganti orang ketiga tunggal Inggris dengan kata ganti eksplisit sumber.

    Dipakai bila kalimat sumber memuat 彼 atau 彼女 secara eksplisit (``pipeline.explicit_pronoun``):
    kata ganti di terjemahan adalah padanan langsung kata itu. Hanya berjalan bila jumlah kata
    ganti he/him/his/himself/she/her/hers/herself di ``text`` (termasuk di dalam kutip) sama
    dengan ``count``; selain itu teks dibiarkan, karena terjemahan menambah atau membuang rujukan
    (refleksif 自分, orang tersirat). Berbeda dengan ``fix_pronouns``, kata ganti objek ikut
    diubah: 彼を/彼に → ``him``, 彼女を → ``her``. Terjemahan yang memuat kata benda pacar
    (``PARTNER_WORDS``: ``his girlfriend``, ``her boyfriend``) dibiarkan: 彼女/彼 di sumber
    berarti pacar, dan kata ganti terjemahan merujuk subjek, bukan 彼女/彼.

    - m: ``her`` objek → ``him``, ``her`` posesif → ``his``, ``hers`` → ``his``, ``she`` →
      ``he``, ``herself`` → ``himself``.
    - f: ``him`` → ``her``, ``his`` → ``her``/``hers``, ``he`` → ``she``, ``himself`` →
      ``herself``.

    Args:
        text: Satu kalimat terjemahan bahasa Inggris.
        gender: ``"m"`` atau ``"f"``; nilai lain membuat teks tidak berubah.
        count: Jumlah kata ganti eksplisit di sumber.

    Returns:
        Teks dengan kata ganti yang sudah disamakan.
    """
    if (gender not in PRONOUN_FORMS or count < 1 or len(_PRONOUN_RE.findall(text)) != count
            or _PARTNER_RE.search(text)):
        return text
    return _PRONOUN_RE.sub(lambda m: _swap_pronoun(m, gender, objects=True), text)


_PREDICATIVE_COPULAS = frozenset({
    "is", "was", "were", "are", "be", "been", "not", "all", "always", "never",
})
_PREDICATIVE_CONJUNCTIONS = frozenset({
    "and", "or", "but", "yet", "so", "for", "nor", "alone", "too", "instead", "though",
})


def _swap_pronoun(match: re.Match[str], gender: str, *, objects: bool = False) -> str:
    """Ganti satu kata ganti bila gendernya berlawanan, dengan kapitalisasi semula."""
    word = match.group(1)
    lower = word.lower()
    if gender == "m" and lower == "her":
        if _is_object_her(match):
            if not objects:
                return word
            new = "him"
        else:
            new = "his"
    elif objects and gender == "f" and lower == "him":
        new = "her"
    elif gender == "f" and lower == "his":
        following = _FOLLOWING_WORD_RE.match(match.string, match.end())
        preceding = _PRECEDING_WORD_RE.search(match.string, 0, match.start())
        before = preceding.group(1).lower() if preceding else ""
        is_predicative = following is None or (
            following.group(1).lower() in _PREDICATIVE_CONJUNCTIONS
            and before in _PREDICATIVE_COPULAS
        )
        new = "hers" if is_predicative else "her"
    else:
        new = PRONOUN_FORMS[gender].get(lower, lower)
    if new == lower:
        return word
    if word.isupper() and len(word) > 1:
        return new.upper()
    return new.capitalize() if word[0].isupper() else new


def _is_object_her(match: re.Match[str]) -> bool:
    """Apakah ``her`` ini objek (dibiarkan), bukan posesif."""
    following = _FOLLOWING_WORD_RE.match(match.string, match.end())
    if following is None:
        return True
    after = following.group(1).lower()
    preceding = _PRECEDING_WORD_RE.search(match.string, 0, match.start())
    before = preceding.group(1).lower() if preceding else ""
    if after == "home":
        return before not in _POSSESSIVE_HOME_AFTER
    return after in OBJECT_FOLLOWERS or before in DITRANSITIVE_VERBS


def _starts_name(text: str, index: int, names: Sequence[str]) -> bool:
    """Apakah salah satu nama hasil render dimulai tepat di ``index``."""
    return any(name and text.startswith(name, index) for name in names)


def _tidy_line(line: str, straight_quotes: bool) -> str:
    """Rapikan satu baris (urutan langkah penting agar hasilnya idempoten)."""
    line = normalize_latin_marks(line).translate(_JAPANESE_PUNCT)
    if straight_quotes:
        line = _LATEX_QUOTES_RE.sub(r'"\1"', line).translate(_CURLY_DOUBLE)
    line = _QUOTE_PAIR_RE.sub(_space_quote_pair, line)
    line = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", line)
    line = _SPACE_AFTER_OPEN_RE.sub(r"\1", line)
    line = _DOUBLE_THE_RE.sub(r"\1", line)
    return _MULTI_SPACE_RE.sub(" ", line).strip()


def _space_quote_pair(match: re.Match[str]) -> str:
    """Rapatkan isi kutip dan beri spasi di luar kutip bila menempel ke huruf."""
    source = match.string
    before = " " if match.start() > 0 and source[match.start() - 1].isalnum() else ""
    after = " " if match.end() < len(source) and source[match.end()].isalnum() else ""
    return f'{before}"{match.group(1).strip()}"{after}'


def _fix_english(text: str, name: str, escaped: str) -> str:
    """Aturan bahasa Inggris untuk satu nama."""
    if not name.lower().startswith("the "):
        text = re.sub(rf"\b{_EN_ARTICLES}\s+(?={escaped}(?!\w))", "", text)
    return re.sub(rf"({escaped})\s+(['’]s)\b", r"\1\2", text)


def _hyphenate(match: re.Match[str]) -> str:
    """``Tanakanya`` → ``Tanaka-nya``."""
    name = match.group(1)
    return f"{name}-{match.group(0)[len(name):]}"
