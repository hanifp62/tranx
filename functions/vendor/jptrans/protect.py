"""Melindungi entitas dari mesin penerjemah dengan penanda ``[[E1]]``.

Alur per kalimat:

1. ``EntityMatcher.mask``: setiap nama dari glosarium (beserta honorifik dan
   sufiks yang menempel, mis. 田中さん達 atau 東京駅) diganti satu penanda.
   Slot yang sama (entri + honorifik + sufiks) memakai nomor yang sama.
2. Teks berpenanda dikirim ke mesin.
3. ``restore``: penanda dicari dengan regex toleran (mesin kadang menulis
   ``[E1]``, ``[[ e1 ]]``, atau ``［［Ｅ１］］``), lalu diganti hasil ``Renderer``.
   Pemulihan berdasarkan NOMOR, bukan posisi, karena mesin memindahkan
   urutan penanda mengikuti tata bahasa sasaran.
4. Bila ada penanda yang hilang: ``PlaceholderError``. Pipeline lalu memakai
   jalur cadangan ``presubstitute`` (bentuk Latin final disisipkan ke teks
   Jepang) dan memeriksa hasilnya dengan ``check_presubstituted``.

Format ``[[E1]]`` dipilih dari eksperimen (LAPORAN_RISET 6.1): lolos 27/27
di Google dan 4/4 di MyMemory, sedangkan angka polos dan karakter PUA rusak.
"""

from __future__ import annotations

import enum
import html
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping

from . import data
from .disambig import (
    HONORIFIC_SURFACES,
    PEOPLE_SUFFIXES,
    PLACE_KINDS,
    PLACE_SUFFIXES,
    TITLE_WORDS,
    VERB_AFTER_CHARS,
    VERB_CONTEXT_CHARS,
    honorific_fits,
    is_known_name,
    is_verb_stem,
    verb_run_before_honorific,
)
from .errors import PlaceholderError
from .glossary import BUILTIN_SOURCE, STRONG_SOURCE_MARK, USER_SOURCE
from .models import PERSON, PLACE, GlossaryEntry, Masked, Slot
from .textnorm import (
    is_hiragana,
    is_kana,
    is_kanji,
    is_katakana,
    narrow_katakana,
    search_key,
    strip_diacritics,
)

logger = logging.getLogger(__name__)

TOKEN_TEMPLATE = "[[E{}]]"
TOKEN_RE = re.compile(
    r"\[(?:\s*\[)?\s*E\s*(\d+)\s*(?:[:=][^\[\]\n]{0,60})?\](?:\s*\])?",
    re.IGNORECASE,
)
"""Penanda toleran: ``[[E1]]``, ``[E1]``, ``[[ e1 ]]``, termasuk anotasi ``[[E1:nama]]``."""

# Bentuk lebar penuh yang kadang dikembalikan mesin: ［［Ｅ１］］.
_FULLWIDTH_TOKEN_CHARS = str.maketrans(
    {
        "［": "[",
        "］": "]",
        "Ｅ": "E",
        "ｅ": "e",
        "：": ":",
        "＝": "=",
        **{chr(0xFF10 + d): str(d) for d in range(10)},
    }
)
EXACT_TOKEN_RE = re.compile(r"\[\[E(\d+)\]\]")
"""Penanda persis seperti yang dibuat ``mask`` (``TOKEN_TEMPLATE``); grup 1 = nomor."""
# Penanda beserta tanda panjang yang menempel di belakangnya (``[[E1]]ー,``): mesin
# menyalin ー dari sumber (美咲ー、) atau menambahkannya sendiri. Grup ``tail`` = tanda itu;
# yang dipertahankan diputuskan satu aturan, ``_marker_tail``.
_MARKER_TAIL = r"(?P<tail>[ーｰ]*)"
_TOKEN_TAIL_RE = re.compile(TOKEN_RE.pattern + _MARKER_TAIL, TOKEN_RE.flags)
_EXACT_TOKEN_TAIL_RE = re.compile(EXACT_TOKEN_RE.pattern + _MARKER_TAIL, EXACT_TOKEN_RE.flags)
# Huruf (Latin atau Jepang) sesudah ``ーー`` di keluaran mesin: tanda pisah (``[[E1]]ーーno``,
# ``[[E1]]ーーいや``), bukan teriakan.
_LETTER_AFTER_DASH_RE = re.compile(r"[ \t]*[^\W\d_]")
_SPACES_RE = re.compile(r"[ \t\u3000]{2,}")
# ら hanya jamak bila tidak memulai kata lain (アリスらしい, 田中られる).
_SUFFIX_LOOKAHEAD = {"ら": "(?![しれ])"}
# Penanda di awal teks (boleh didahului kutip/kurung) dirender dengan huruf kapital.
_SENTENCE_START_RE = re.compile(r"""[\s"'“‘(\[«]*""")
_LONG_VOWELS = frozenset("ーｰ")
_SOKUON = frozenset("ッｯっ")
# Ekor teriakan setelah nama: deretan tanda panjang dan sokuon (アリスーッ！, アリスーー).
# っ hiragana (ユキっ！, ユキーっ！) hanya dihitung bila ekornya diserap ke slot
# (``_shout_end``); batas kanan nama (``_shouted``) hanya mengenal ー/ッ.
_SHOUT_TAIL_RE = {
    False: re.compile("[ーｰッｯ]+"),
    True: re.compile("[ーｰッｯっ]+"),
}
# Satu ー saja hanya teriakan bila langsung diikuti tanda seru/tanya, elipsis, atau ～
# (マリー！). Sebelum partikel, huruf lain, 、。」, atau akhir teks kata+ー lebih sering
# kata lain (マリーは = Marie, ミラー。 = cermin), jadi ditolak.
_SHOUT_END_CHARS = frozenset("！？!?…‥～〜‼⁉♪")
# Yang boleh menyusul ekor teriakan agar ekornya masuk slot: tanda teriakan, tanda baca
# penutup, kurung/kutip penutup, spasi, atau akhir teks. Sebelum huruf lain ーー adalah
# tanda pisah (田中ーーいや) dan ッ/っ awal kata berikutnya (ユキッて, 田中ッ子): dibiarkan.
_SHOUT_FOLLOWERS = _SHOUT_END_CHARS | frozenset("、。，．,.､｡」』）)］]】〉》〕\"'”’ \t\u3000\r\n")
# Honorifik ber-ん yang bisa dipanjangkan saat berteriak (田中さーん, ケンちゃーん).
_ELONGATED_HONORIFICS = ("さん", "くん", "ちゃん", "たん")
# Huruf unit kota/kabupaten di dalam sisa alamat (松本市内, 木曽郡上松町, 廿日市市).
_ADDRESS_UNIT_CHARS = frozenset("市区町村郡")
# Huruf kana yang tetap bagian nama tempat di tengah alamat (鎌ケ谷市, 市ヶ谷).
_ADDRESS_INNER_CHARS = frozenset("ヶケヵ")
_BARE_NAME_FOLLOWERS = frozenset("がはものにをへとやでかよねだじなっ")
"""Hiragana yang boleh menyusul nama satu kanji tanpa honorifik (翔が, 哲って, 開の).

Hiragana lain sesudah entri satu kanji non-pengguna adalah okurigana (来る, 持ち主, 見せて,
歩いて): kanjinya bagian kata kerja/kata biasa, bukan nama. Dipakai ``_bare_word``."""
_BARE_NAME_PARTICLES = ("まで", "しか", "さえ", "すら", "こそ", "ばかり", "ほど", "くらい",
                        "ぐらい")
"""Partikel berhuruf banyak yang awalnya tidak ada di ``_BARE_NAME_FOLLOWERS`` tetapi lazim
sesudah nama (翔まで, 哲しか, 玲さえ, 舜こそ, 潤ばかり, 徹ほど, 慧くらい)."""
_TTE_STEMS = frozenset("立待持勝打保育討撃放断絶建発裁治直通帰入取切言会渡回移残戻減写映成下")
"""Kanji kata kerja yang bentuk -te/-ta-nya kanji + って/った (勝って, 待って, 治って, 渡った).

Sesudah kanji lain, って adalah partikel kutipan (歩って誰？, 響って呼んで), jadi nama yang
dikenal tetap dimasking. Dipakai ``_bare_word``."""
# ら/たち setelah tempat bawaan hanya jamak orang bila disusul partikel ini atau bukan kana;
# selain itu ia awal kata lain (福島らへん, 宮崎らーめん, 千葉たちうお).
_PLURAL_KANA = frozenset({"ら", "たち"})
_PLURAL_FOLLOWERS = frozenset("はがをにのともでやかへだ")
_NOT_PLURAL_WORDS = ("へん",)
# Akhir unit wilayah: nama tempat sesudahnya adalah kata baru (愛知県豊田市, 北海道札幌市).
_ADMIN_ENDINGS = frozenset("都道府県")
# Nama tempat tanpa sufiks yang sendiri sudah unit wilayah (北海道). 京都/東京 sengaja tidak:
# 都 di situ bagian nama kota, bukan sufiks wilayah (京都大阪 bukan alamat).
_ADMIN_NAME_ENDINGS = ("道",)
# Sufiks kota yang boleh menjadi bagian kunci peta masking (松本市 → entri 松本).
_MUNICIPALITY_ENDINGS = frozenset("市区町村")
ADDRESS_TAILS = ("出身", "在住", "在勤", "生まれ", "育ち", "産")
"""Kata yang boleh menempel langsung sesudah tempat atau alamat tanpa membatalkannya.

静岡県浜松市出身 dan 愛知県豊田市在住 tetap satu alamat (``Kota Hamamatsu, Prefektur Shizuoka``),
静岡県出身 dan 浜松出身 tetap dimasking; ekornya diterjemahkan mesin. 産 hanya bila tidak
disusul kanji (静岡県産のお茶, bukan 静岡県産業). Kanji lain (松本市内, 札幌市中央区) tetap
membatalkan seperti sebelumnya. Lihat ``_address_tail``."""
HOUSE_CHI = "ち"
"""Bentuk lisan 家 sesudah honorifik orang: 田中さんち = rumah (keluarga) Tanaka-san."""
HOUSE_TEXT = "の家"
"""Pengganti ``HOUSE_CHI`` di teks termasking: ``[[E1]]の家`` (mesin menerima kalimat gramatikal)."""
_HOUSE_HONORIFICS = frozenset({"san", "kun", "chan"})
FESTIVAL_HONORIFIC = "くん"
KUNCHI_FESTIVALS = frozenset({"長崎", "唐津"})
"""Tempat yang + くんち adalah nama festival (長崎くんち, 唐津くんち): tempat itu tidak dibaca nama
keluarga + くん, sehingga ち juga bukan "rumah" (``EntityMatcher._accept``). Tempat bawaan lain
yang juga nama keluarga tetap dibaca orang + rumah (千葉くんちに = ke rumah Chiba-kun)."""
_HOUSE_FOLLOWERS = frozenset("のにでへはもをとよねさぞだじ、。，．,.！？!?…‥」』）) \t\u3000\r\n")
"""Huruf sesudah ち yang menandakan 〜さんち "rumah" (田中さんちに, 田中さんちだよ, 田中さんちじゃない),
bukan ちょっと/ちゃんと. Kanji sesudahnya juga (田中さんち行こう: partikel lisan yang dihilangkan)."""
_HOUSE_UNLESS: dict[str, tuple[str, ...]] = {
    "が": ("う", "わ", "え", "っ", "い", "お"),
    "か": ("い", "く", "け", "か", "っ", "づ", "よ"),
    "な": ("み",),
    "く": ("し", "わ", "ち", "び"),
    "ま": ("ち", "き", "み"),
    "や": ("ほ",),
}
"""Huruf sesudah ち yang menandakan rumah KECUALI disusul huruf di sini, karena ち lalu menjadi awal
kata lain: ちがう/ちがった (違う), ちかい/ちかく (近い), ちなみに, ちくしょう, ちくわ, ちまちま, ちまき,
ちやほや. Bentuk rumah: 田中さんちが近い, 田中さんちかな, 田中さんちから (dari rumah), 田中さんちなの,
田中さんちくらい, 田中さんちまで, 田中さんちや公園."""
_HOUSE_ONLY_IF: dict[str, tuple[str, ...]] = {"っ": ("て",)}
"""Huruf sesudah ち yang menandakan rumah HANYA bila disusul huruf di sini: 田中さんちって (rumah),
tetapi ちっとも, ちっちゃい, ちっこい, ちっさい adalah kata lain."""


class _NotAddress(enum.Enum):
    """Jenis penanda ``_NOT_ADDRESS`` (satu anggota, agar bisa diberi type hint)."""

    TOKEN = enum.auto()


_NOT_ADDRESS = _NotAddress.TOKEN
"""Hasil ``EntityMatcher._address``: aturan alamat tidak berlaku, pemeriksaan biasa berlanjut."""


class EntityMatcher:
    """Pencari entitas glosarium di teks Jepang.

    Regex berupa alternasi semua tulisan (terpanjang dulu) diikuti honorifik
    dan sufiks opsional: ``(?P<name>...)(?P<hon>...)?(?P<suf>...)?``.

    Aturan batas kata (bahasa Jepang tidak memakai spasi):

    - Nama yang diawali kanji ditolak bila karakter sebelumnya kanji
      (小田中 bukan 小 + 田中), kecuali tempat setelah unit wilayah
      都/道/府/県 (愛知県豊田市).
    - Tanpa honorifik/sufiks, nama yang diakhiri kanji ditolak bila diikuti
      kanji (田中央 bukan 田中 + 央), kecuali orang yang diikuti gelar
      ``TITLE_WORDS`` (佐藤部長): gelarnya dibiarkan untuk mesin.
    - Nama katakana ditolak bila diapit katakana lain (アリス di dalam アリスト),
      kecuali teriakan ーー/ッ setelah nama (アリスーッ！). Satu ー hanya
      teriakan bila langsung diikuti tanda seru/tanya, elipsis, atau ～
      (マリー！ dengan glosarium yang hanya punya マリ) dan nama+ー bukan kata
      serapan di ``loanwords.json`` (ミラー！ = cermin). Sebelum partikel,
      huruf lain, 、。」, atau akhir teks tetap menolak (マリーは = nama lain,
      ミラー。). Entri yang lebih panjang selalu menang karena alternasi regex
      terpanjang dulu. Tanda teriakan ikut masuk slot dan tidak dirender
      (``アリスーーッ！`` → ``[[E1]]！`` → ``Alice!``; juga 田中ーッ！), jadi
      mesin tidak pernah menerima ー/ッ yang menempel ke penanda.
    - Kunci peta = tulisan entri tempat + 市/区/町/村 (``pipeline.admin_stem_entry``:
      kunci 松本市, entri 松本) menghasilkan ``Slot(松本, "", "市")``.
    - Unit wilayah yang langsung diikuti tempat dikenal yang tidak bisa dirender
      (愛知県 + 刈谷市 tanpa bacaan) tidak dimasking: seluruh alamat dikirim
      apa adanya ke mesin, bukan ``Aichi県刈谷市``.
    - Tempat bawaan yang tulisannya juga nama keluarga di ``surnames.json``
      (山口, 千葉, 町田, 豊田) dicocokkan sebagai orang bila langsung diikuti
      honorifik, sufiks orang (家, 一家, 達, たち, ら), atau gelar
      (山口家 → keluarga Yamaguchi). ら/たち hanya dihitung bila disusul
      partikel atau bukan kana (福島らへん, 宮崎らーめん tetap tempat).
      Konteks lain tetap tempat (山口県, 千葉駅, 山口に). Entri pengguna tidak
      pernah ditafsir ulang.
    - Rangkaian alamat: tempat yang diakhiri unit wilayah 都/道/府/県 (北海道,
      愛知県) dan langsung diikuti tempat lain yang dikenal menjadi SATU slot
      (``Slot.parents``), dirender dari unit terkecil: ``Kota Toyota,
      Prefektur Aichi``. Rangkaian dibatalkan bila sesudahnya masih ada kanji
      (北海道札幌市中央区): sisa itu akan menempel ke unit terbesar. Pengecualian:
      ``ADDRESS_TAILS`` (静岡県浜松市出身, 愛知県豊田市在住) tidak membatalkan rangkaian,
      sufiks tempat (静岡県出身), maupun tempat tanpa sufiks (浜松出身).
    - 〜さんち/〜くんち/〜ちゃんち (田中さんちの犬): ち sesudah orang + honorifik itu, bila
      disusul partikel/kopula/tanda baca/kanji (``_house_chi``), diganti ``HOUSE_TEXT``
      (``[[E1]]の家の犬``); ちがう/ちかく/ちょっと tidak. Tempat bawaan + くんち (長崎くんち,
      festival) tetap tempat tanpa honorifik: ``[[E1]]くんち``.
    - Honorifik kanji yang diikuti kanji (殿下, 君子, 様子) bukan honorifik.
    - Sufiks jamak/keluarga untuk PERSON atau nama yang berhonorifik
      (千葉さん達); sufiks tempat hanya untuk PLACE dan ORG; sufiks yang
      diikuti kanji (田中達也) bukan sufiks. Sufiks yang tidak cocok
      diabaikan, lalu batas kanan diperiksa seperti biasa. Untuk tempat,
      sufiks yang menempel ke kata lain (星見市内, 東京駅前) dibiarkan di teks
      dan namanya tetap dimasking.
    - Katakana setengah lebar (ｱﾘｽ) cocok dengan entri lebar penuh.
    - ``allow_compound`` pada entri mematikan semua pemeriksaan batas.
    - Entri orang satu kanji yang bukan milik pengguna diperiksa konteksnya
      (``_not_this_entity``): kata kerja + ん (駅まで歩くんですか) dan okurigana (持ってきた)
      tidak dimasking.

    Args:
        surface_map: Tulisan (surface dan alias) → entri, biasanya dari
            ``Glossary.surface_map()``.
        named: Tulisan yang terbukti nama di dokumen ini (``ner.attested_names``);
            kemunculan yang konteksnya ambigu ikut dibaca nama.
    """

    def __init__(self, surface_map: Mapping[str, GlossaryEntry],
                 named: frozenset[str] = frozenset()) -> None:
        self._named = named
        self._entries = _with_halfwidth_forms(surface_map)
        self._pattern = _build_pattern(self._entries) if self._entries else None
        self._as_person = _surname_readings_of_builtin_places(self._entries.values())

    def mask(
        self, text: str, can_render: Callable[[GlossaryEntry], bool] | None = None
    ) -> Masked:
        """Ganti setiap entitas dengan penanda ``[[E#]]``.

        Args:
            text: Kalimat Jepang.
            can_render: Penyaring entri; entri yang ditolak tidak dimasking.

        Returns:
            Teks berpenanda beserta slotnya. Tanpa entitas, ``text`` sama
            dengan ``original`` dan ``slots`` kosong.
        """
        if self._pattern is None:
            return Masked(original=text, text=text, slots={})
        ids: dict[Slot, int] = {}
        pieces: list[str] = []
        emitted = 0
        match = self._pattern.search(text)
        while match is not None:
            found = self._accept(text, match, can_render)
            if found is None:
                # Kecocokan ditolak: coba lagi mulai karakter berikutnya.
                match = self._pattern.search(text, match.start() + 1)
                continue
            slot, end = found
            if slot is None:
                # Alamat yang sengaja dibiarkan utuh untuk mesin (``_address``).
                match = self._pattern.search(text, end)
                continue
            number = ids.setdefault(slot, len(ids) + 1)
            pieces += [text[emitted:match.start()], TOKEN_TEMPLATE.format(number)]
            emitted = end
            if _house_chi(text, end, slot):
                # 田中さんちに → [[E1]]の家に: ち bukan sisa nama, tetapi "rumah".
                pieces.append(HOUSE_TEXT)
                emitted = end + len(HOUSE_CHI)
            match = self._pattern.search(text, emitted)
        pieces.append(text[emitted:])
        slots = {number: slot for slot, number in ids.items()}
        return Masked(original=text, text="".join(pieces), slots=slots)

    def _accept(
        self,
        text: str,
        match: re.Match[str],
        can_render: Callable[[GlossaryEntry], bool] | None,
    ) -> tuple[Slot | None, int] | None:
        """Periksa satu kecocokan regex; kembalikan (slot, posisi akhir) atau ``None``.

        Slot ``None`` berarti teks sampai posisi akhir sengaja tidak dimasking dan
        pencarian dilanjutkan dari sana (alamat yang tidak bisa dirangkai).
        """
        name = match["name"]
        entry = self._entries[name]
        if can_render is not None and not can_render(entry):
            return None
        hon = match["hon"] or ""
        suffix = match["suf"] or ""
        if hon == FESTIVAL_HONORIFIC and entry.kind == PLACE and name in KUNCHI_FESTIVALS \
                and text.startswith(HOUSE_CHI, match.end("hon")):
            # 長崎くんち, 唐津くんち: nama festival (tempat + くんち), bukan orang + rumah.
            hon = ""
        if _not_this_entity(entry, text, match, self._named):
            return None
        inner = _inner_suffix(name, entry)
        if inner or not honorific_fits(hon, text, match.end("hon")):
            hon, suffix = "", ""
        name_end = match.end("name")
        # Batas kiri memakai entri asli: tempat bawaan setelah 都道府県 tetap diterima
        # walau konteksnya orang (千葉県山口さん, perilaku lama).
        if not entry.allow_compound and _blocked_left(text, match.start(), name, entry):
            return None
        entry = self._person_in_context(entry, hon, suffix, text, match)
        if inner and name_end < len(text) and is_kanji(text[name_end]) \
                and not _address_tail(text, name_end):
            # 松本市内, 松本市民: seperti 星見市内, sufiks yang menempel ke kata lain
            # dibiarkan di teks dan nama kotanya tetap dimasking. 松本市出身 tidak.
            return Slot(entry), name_end - len(inner)
        open_right = False
        if suffix and not _suffix_fits(suffix, entry, hon, text, match.end("suf")):
            address = self._address(entry, name, hon, suffix, text, match.end("suf"), can_render)
            if address is not _NOT_ADDRESS:
                return address
            open_right = suffix in PLACE_SUFFIXES and entry.kind in PLACE_KINDS
            suffix = ""
        if not entry.allow_compound:
            open_right = (open_right or bool(hon or suffix) or _titled(text, name_end, entry)
                          or (entry.kind in PLACE_KINDS and _address_tail(text, name_end)))
            if not open_right and _blocked_right(text, name_end, name):
                address = self._address(entry, name, hon, "", text, name_end, can_render)
                if address is not _NOT_ADDRESS:
                    return address
                if _shout_end(text, name_end, name) == name_end:
                    return None
        slot = Slot(entry, HONORIFIC_SURFACES.get(_plain_honorific(hon), ""), suffix or inner)
        end = name_end + len(hon) + len(suffix)
        return slot, _shout_end(text, end, suffix or hon or name)

    def _person_in_context(
        self, entry: GlossaryEntry, hon: str, suffix: str, text: str, match: re.Match[str]
    ) -> GlossaryEntry:
        """Tafsirkan tempat bawaan yang juga nama keluarga sebagai orang bila konteksnya orang.

        Konteks orang: honorifik (山口さん), sufiks orang yang benar-benar
        sufiks (山口家, 千葉一家, 石川達; bukan 山口達也; ら/たち hanya sebelum
        partikel atau bukan kana, bukan 福島らへん), atau gelar (石川部長).
        Tanpa konteks itu entri tempat dikembalikan apa adanya (山口県, 山口に).
        """
        person = self._as_person.get(entry.surface) if entry.kind == PLACE else None
        if person is None or entry.source != BUILTIN_SOURCE:
            return entry
        if hon:
            return person
        if suffix in PEOPLE_SUFFIXES:
            end = match.end("suf")
            fits = _suffix_fits(suffix, person, "", text, end) and (
                suffix not in _PLURAL_KANA or _plural_boundary(text, end))
            return person if fits else entry
        if not suffix and _titled(text, match.end("name"), person):
            return person
        return entry

    def _chain(
        self,
        entry: GlossaryEntry,
        suffix: str,
        text: str,
        match: re.Match[str] | None,
        can_render: Callable[[GlossaryEntry], bool] | None,
    ) -> tuple[Slot, int] | None:
        """Rangkai unit wilayah dengan tempat dikenal yang langsung mengikutinya.

        Hanya dipanggil ``_address`` setelah ``_admin_unit`` memastikan ``entry`` +
        ``suffix`` (愛知 + 県, atau 北海道 tanpa sufiks) berakhir dengan unit wilayah
        都/道/府/県. ``match`` adalah kecocokan glosarium tepat sesudahnya (dicari sekali
        oleh ``_address``) dan harus berupa tempat dikenal yang diterima aturan biasa
        (boleh berangkai lagi). Orang, honorifik, dan sufiks orang tidak pernah menjadi
        bagian alamat. Rangkaian yang langsung disusul kanji (北海道札幌市中央区,
        愛知県豊田市内) dibatalkan: sisa 市中央区 akan menempel ke unit terbesar
        ("Sapporo, Hokkaido市中央区"), jadi unitnya dimasking sendiri-sendiri seperti
        sebelum ada rangkaian.

        Returns:
            (slot gabungan, posisi akhir), atau ``None`` bila bukan rangkaian alamat.
        """
        found = self._accept(text, match, can_render) if match is not None else None
        if found is None or found[0] is None:
            return None
        child, end = found
        if child.entry.kind != PLACE or child.honorific or child.suffix in PEOPLE_SUFFIXES:
            return None
        if end < len(text) and is_kanji(text[end]) and not _address_tail(text, end):
            return None
        parents = ((entry, suffix), *child.parents)
        return Slot(child.entry, "", child.suffix, parents), end

    def _address(
        self,
        entry: GlossaryEntry,
        name: str,
        hon: str,
        suffix: str,
        text: str,
        pos: int,
        can_render: Callable[[GlossaryEntry], bool] | None,
    ) -> tuple[Slot | None, int] | _NotAddress | None:
        """Aturan alamat untuk ``entry`` + ``suffix`` yang menempel ke kata di ``pos``.

        Dipanggil saat batas kanan atau sufiks menolak kecocokan biasa. Hasilnya, dengan
        urutan pemeriksaan:

        1. Rangkaian alamat (``_chain``): ``(slot gabungan, akhir)``.
        2. Alamat yang dibiarkan utuh: ``(None, akhir)``. Unit wilayah BAWAAN (prefektur
           nyata 長野 + 県, atau 北海道) yang langsung diikuti kanji yang memuat unit kota
           ``市区町村郡`` tetapi tidak diawali tempat dikenal yang bisa dirender:
           長野県松本市内 (deteksi entitas tidak menangkap 松本市 sebelum 内), 長野県松本市民,
           広島県廿日市市 (nama kota mengandung 市), 長野県木曽郡上松町, 東京都府中市.
           Dulu prefekturnya tetap dimasking dan sisanya dikirim mentah, sehingga mesin
           yang menggemakan teks menghasilkan ``Nagano県松本市内``. Kini seluruh alamat
           (sampai akhir deretan kanji) dikirim apa adanya ke mesin, yang mengenal
           prefektur nyata, jadi keluarannya selalu satu bentuk. Prefektur dari glosarium
           pengguna (fiktif) tetap dimasking: melindungi nama lebih penting.
        3. Unit wilayah yang langsung diikuti tempat dikenal yang TIDAK bisa dirender
           (愛知県刈谷市 dengan entri 刈谷市 tanpa bacaan, ``unknown_reading="keep"`` atau
           jawaban mesin ditolak): ``None``, kecocokan ditolak. Bila 愛知 tetap dimasking,
           keluarannya setengah Latin (``Aichi県刈谷市`` dengan mesin yang menggemakan
           teks); seluruh alamat dibiarkan Jepang dan dikirim utuh ke mesin, sama seperti
           nama lain yang tidak bisa dirender.
        4. Selain itu ``_NOT_ADDRESS``: aturan alamat tidak berlaku dan ``_accept``
           melanjutkan pemeriksaan biasa. Bila yang menyusul tempat dikenal yang bisa
           dirender (愛知県豊田市内, 北海道札幌市中央区), unitnya dimasking sendiri-sendiri.
        """
        if not _admin_unit(entry, name, hon, suffix):
            return _NOT_ADDRESS
        match = self._pattern.match(text, pos) if self._pattern is not None else None
        chained = self._chain(entry, suffix, text, match, can_render)
        if chained is not None:
            return chained
        child = self._entries[match["name"]] if match is not None else None
        child = child if child is not None and child.kind == PLACE else None
        renderable = child is not None and (can_render is None or can_render(child))
        if entry.source == BUILTIN_SOURCE and not renderable:
            end = _address_run_end(text, pos)
            if end is not None:
                return None, end
        if child is not None and not renderable:
            return None
        return _NOT_ADDRESS


def missing_tokens(translated: str, masked: Masked) -> list[int]:
    """Nomor penanda asli yang tidak ditemukan di keluaran mesin (tanpa merender).

    Args:
        translated: Keluaran mentah mesin.
        masked: Hasil masking kalimat yang sama.

    Returns:
        Nomor yang hilang, terurut; kosong berarti semua penanda utuh.
    """
    return _missing(_count_tokens(_normalized(translated)), masked)


def restore(translated: str, masked: Masked, render: Callable[[Slot], str]) -> str:
    """Ganti penanda di hasil mesin dengan bentuk akhir dari ``render``.

    Semua nomor asli wajib ada. Penanda karangan mesin dibuang; penanda yang
    muncul lebih sering dari aslinya dicatat sebagai warning dan tetap
    dirender. ``render`` baru dipanggil setelah validasi lolos, sehingga
    status gloss kemunculan pertama tidak tercemar oleh percobaan yang gagal.

    Args:
        translated: Keluaran mentah mesin (boleh mengandung entitas HTML).
        masked: Hasil ``EntityMatcher.mask`` untuk kalimat yang sama.
        render: Pembuat bentuk akhir, biasanya ``style.Renderer``.

    Returns:
        Teks terjemahan dengan nama final dan spasi ganda dirapikan.

    Raises:
        PlaceholderError: Ada nomor penanda asli yang tidak ditemukan.
    """
    text = _normalized(translated)
    found = _count_tokens(text)
    missing = _missing(found, masked)
    if missing:
        raise PlaceholderError(missing)
    _warn_unexpected(found, masked)

    def substitute(match: re.Match[str]) -> str:
        """Bentuk akhir satu penanda (kapital di awal kalimat) plus ekor yang dipertahankan."""
        tail = _marker_tail(text, match)
        slot = masked.slots.get(int(match.group(1)))
        if slot is None:
            return tail
        form = render(slot)
        if _SENTENCE_START_RE.fullmatch(text, 0, match.start()):
            form = form[:1].upper() + form[1:]
        return form + tail

    return _squeeze_spaces(_TOKEN_TAIL_RE.sub(substitute, text))


def _marker_tail(text: str, match: re.Match[str], *, masked: bool = False) -> str:
    """Tanda panjang di belakang penanda yang dipertahankan; selebihnya dibuang.

    Satu aturan untuk ``restore`` (keluaran mesin, ``_TOKEN_TAIL_RE``) dan ``presubstitute``
    (teks termasking, ``_EXACT_TOKEN_TAIL_RE``, ``masked=True``). Satu ``ー``/``ｰ`` tepat di
    belakang nama selalu dibuang: itu teriakan yang tidak dirender, sama seperti yang sudah
    diserap slot (``美咲ー！`` → ``Misaki!``), jadi ``[[E1]]ー, tunggu!`` menjadi ``Misaki,
    tunggu!``, bukan ``Misakii``. ``ーー`` atau lebih adalah tanda pisah dan dipertahankan
    bila disusul kata, Latin atau Jepang, boleh didahului spasi (``[[E1]]ーーno`` →
    ``Misaki—no`` di pascaproses; ``[[E1]]ーーいや`` tetap apa adanya).

    Bedanya disengaja: di teks termasking ``_shout_end`` sudah menyerap ``ーー`` teriakan
    (yang disusul tanda baca, spasi, atau akhir teks) ke dalam slot, jadi ``ーー`` yang
    tersisa di belakang penanda selalu dipertahankan, juga sebelum angka atau simbol
    (``美咲ーー123`` dikirim `` Misaki ーー123``). Di keluaran mesin ``ーー`` sebelum angka,
    simbol, atau tanda baca bisa tambahan mesin sendiri, jadi dibuang.
    """
    tail = match.group("tail")
    if len(tail) < 2:
        return ""
    return tail if masked or _LETTER_AFTER_DASH_RE.match(text, match.end()) else ""


def presubstitute(masked: Masked, render: Callable[[Slot], str]) -> tuple[str, list[str]]:
    """Jalur cadangan: sisipkan bentuk Latin final langsung ke teks Jepang.

    Contoh: ``[[E1]]は東京へ`` → ``Tanaka-san は東京へ``. Mesin terbukti
    mempertahankan bentuk Latin seperti ini (LAPORAN_RISET 6.1).

    Args:
        masked: Hasil masking.
        render: Pembuat bentuk akhir.

    Returns:
        Pasangan (teks untuk dikirim ke mesin, daftar bentuk yang wajib
        muncul di hasil terjemahan tanpa duplikat).
    """
    required: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        """Bentuk Latin satu penanda berspasi, dan catat bentuk itu di ``required``."""
        form = render(masked.slots[int(match.group(1))])
        if form not in required:
            required.append(form)
        # Satu ー sisa di belakang nama (美咲ー、) tidak dikirim, seperti di ``restore``;
        # ーー sebelum huruf adalah tanda pisah dan tetap dikirim.
        return f" {form} " + _marker_tail(masked.text, match, masked=True)

    return _squeeze_spaces(_EXACT_TOKEN_TAIL_RE.sub(substitute, masked.text)), required


def check_presubstituted(translated: str, required: list[str]) -> list[str]:
    """Cari bentuk wajib yang hilang dari hasil jalur cadangan.

    Perbandingan mengabaikan huruf besar/kecil dan diakritik (ō ≈ o), karena
    mesin kadang menulis ulang ``Satō`` menjadi ``Sato``.

    Args:
        translated: Keluaran mesin.
        required: Bentuk dari ``presubstitute``.

    Returns:
        Bentuk yang tidak ditemukan; kosong berarti lolos.
    """
    haystack = _loose(html.unescape(translated))
    return [form for form in required if _loose(form) not in haystack]


def _build_pattern(entries: Mapping[str, GlossaryEntry]) -> re.Pattern[str]:
    """Rakit regex nama + honorifik + sufiks, alternatif terpanjang dulu."""
    names = _alternation(entries)
    # Honorifik yang dipanjangkan (さーん, ちゃーーん) dicoba dulu; kuncinya dinormalkan
    # ``_plain_honorific`` saat membuat slot.
    elongated = "|".join(re.escape(hon[:-1]) + "[ーｰ]+" + re.escape(hon[-1])
                         for hon in _ELONGATED_HONORIFICS if hon in HONORIFIC_SURFACES)
    hons = f"{elongated}|{_alternation(HONORIFIC_SURFACES)}" if elongated else _alternation(
        HONORIFIC_SURFACES)
    suffixes = _alternation({**PEOPLE_SUFFIXES, **PLACE_SUFFIXES}, _SUFFIX_LOOKAHEAD)
    return re.compile(f"(?P<name>{names})(?P<hon>{hons})?(?P<suf>{suffixes})?")


def _alternation(words: Iterable[str], lookahead: Mapping[str, str] | None = None) -> str:
    """Gabungkan kata menjadi alternasi regex, terpanjang dulu.

    Args:
        words: Kata-kata (kunci dict juga boleh).
        lookahead: Syarat tambahan per kata, mis. ``{"ら": "(?![しれ])"}``.
    """
    extra = lookahead or {}
    ordered = sorted(words, key=len, reverse=True)
    return "|".join(re.escape(word) + extra.get(word, "") for word in ordered)


def _with_halfwidth_forms(surface_map: Mapping[str, GlossaryEntry]) -> dict[str, GlossaryEntry]:
    """Tambahkan bentuk katakana setengah lebar (ｱﾘｽ) untuk tiap tulisan katakana."""
    entries = dict(surface_map)
    for surface, entry in surface_map.items():
        entries.setdefault(narrow_katakana(surface), entry)
    return entries


def _suffix_fits(suffix: str, entry: GlossaryEntry, hon: str, text: str, end: int) -> bool:
    """Periksa apakah sufiks benar-benar sufiks, bukan awal kata lain.

    Sufiks jamak/keluarga untuk orang, atau untuk nama apa pun yang sudah
    berhonorifik (千葉さん達 walau 千葉 juga nama prefektur). Sufiks tempat
    hanya untuk tempat/organisasi. Sufiks yang langsung diikuti kanji
    dianggap bagian kata majemuk: 田中達也 (nama Tatsuya), 田中家具店, 東京都庁, kecuali sufiks
    tempat yang disusul ``ADDRESS_TAILS`` (静岡県出身, 浜松市在住).
    """
    if end < len(text) and is_kanji(text[end]) and not (
            suffix in PLACE_SUFFIXES and entry.kind in PLACE_KINDS and _address_tail(text, end)):
        return False
    if suffix in PEOPLE_SUFFIXES:
        return entry.kind == PERSON or bool(hon)
    return entry.kind in PLACE_KINDS


def _address_tail(text: str, pos: int) -> bool:
    """Teks di ``pos`` diawali salah satu ``ADDRESS_TAILS`` (出身, 在住, 生まれ, 産 + bukan kanji)."""
    for tail in ADDRESS_TAILS:
        if text.startswith(tail, pos):
            after = pos + len(tail)
            return tail != "産" or after >= len(text) or not is_kanji(text[after])
    return False


def _house_chi(text: str, end: int, slot: Slot) -> bool:
    """``ち`` di ``end`` adalah 家 lisan sesudah orang + さん/くん/ちゃん (田中さんちの犬).

    Syaratnya ち disusul partikel, kopula, tanda baca, kanji, atau akhir teks
    (``_HOUSE_FOLLOWERS``), atau が/か/な/く/ま/や yang tidak memulai kata lain (``_HOUSE_UNLESS``),
    atau って (``_HOUSE_ONLY_IF``). Jadi 田中さんちょっと (= 田中さん、ちょっと), 福井さんちゃんと,
    田中さんちがう (= 違う), 田中さんちかく (= 近く), dan 田中さんちっこい tidak terkena. 長崎くんち
    (festival) sudah menjadi tempat tanpa honorifik di ``EntityMatcher._accept``
    (``KUNCHI_FESTIVALS``).
    """
    if (slot.entry.kind != PERSON or slot.honorific not in _HOUSE_HONORIFICS or slot.suffix
            or not text.startswith(HOUSE_CHI, end)):
        return False
    after = end + len(HOUSE_CHI)
    if after >= len(text) or text[after] in _HOUSE_FOLLOWERS or is_kanji(text[after]):
        return True
    only = _HOUSE_ONLY_IF.get(text[after])
    if only is not None:
        return text.startswith(only, after + 1)
    unless = _HOUSE_UNLESS.get(text[after])
    return unless is not None and not text.startswith(unless, after + 1)


def _surname_readings_of_builtin_places(
    entries: Iterable[GlossaryEntry],
) -> dict[str, GlossaryEntry]:
    """Entri orang pengganti untuk tempat bawaan yang juga nama keluarga (山口, 千葉).

    Entri ini hanya dipakai ``EntityMatcher`` saat konteksnya orang; tidak
    pernah masuk glosarium, sehingga entri tempat bawaan tetap utuh.

    Returns:
        Tulisan → ``GlossaryEntry`` PERSON berbacaan ``surnames.json``.
    """
    surnames = data.surnames()
    return {
        entry.surface: GlossaryEntry(
            entry.surface, kind=PERSON, reading=surnames[entry.surface], source=BUILTIN_SOURCE
        )
        for entry in entries
        if entry.kind == PLACE and entry.source == BUILTIN_SOURCE and entry.surface in surnames
    }


def _blocked_left(text: str, start: int, name: str, entry: GlossaryEntry) -> bool:
    """Tolak bila nama menyambung ke kata di kirinya (小田中, アリスト)."""
    if start == 0:
        return False
    if entry.kind in PLACE_KINDS and text[start - 1] in _ADMIN_ENDINGS:
        return False
    return _same_script(text[start - 1], name[0])


def _blocked_right(text: str, end: int, name: str) -> bool:
    """Tolak bila nama menyambung ke kata di kanannya (田中央, アリスト)."""
    if end >= len(text) or _shouted(text, end):
        return False
    return _same_script(text[end], name[-1])


def _shouted(text: str, end: int) -> bool:
    """Nama diikuti ーー/ッ/ーッ lalu bukan katakana: teriakan, bukan kata yang lebih panjang."""
    return _strong_shout_end(text, end, hiragana_sokuon=False,
                             follower_ok=lambda ch: not is_katakana(ch)) is not None


def _strong_shout_end(
    text: str, end: int, *, hiragana_sokuon: bool, follower_ok: Callable[[str], bool]
) -> int | None:
    """Akhir ekor teriakan "kuat" yang mulai di ``end``, satu sumber aturan teriakan.

    Ekor kuat adalah deretan ー/ッ (ditambah っ bila ``hiragana_sokuon``) yang
    minimal dua huruf atau berakhir sokuon: ``ーー``, ``ッ``, ``ーッ``. Satu ー saja
    bukan ekor kuat; ia ditangani ``_single_long_vowel_shout``.

    Args:
        text: Teks sumber.
        end: Posisi tepat sesudah nama atau honorifik.
        hiragana_sokuon: Hitung juga っ hiragana sebagai bagian ekor.
        follower_ok: Syarat huruf sesudah ekor; akhir teks selalu diterima.

    Returns:
        Posisi sesudah ekor, atau ``None`` bila tidak ada ekor kuat yang diterima.
    """
    tail = _SHOUT_TAIL_RE[hiragana_sokuon].match(text, end)
    if tail is None:
        return None
    run, after = tail.group(), tail.end()
    if len(run) < 2 and run[-1] not in _SOKUON:
        return None
    if after < len(text) and not follower_ok(text[after]):
        return None
    return after


def _single_long_vowel_shout(text: str, end: int, name: str, any_script: bool = False) -> bool:
    """Nama katakana + SATU ー lalu tanda seru/tanya, elipsis, atau ～ (マリー！, マリー…).

    Hanya dipanggil untuk kecocokan terpanjang di posisinya, jadi entri lain
    yang lebih panjang (マリー) sudah lebih dulu dicoba. ーー dan ーッ ditangani
    ``_strong_shout_end``. Nama+ー yang merupakan kata serapan (ミラー, ハンター) bukan
    teriakan.

    Args:
        any_script: Terima juga nama yang tidak berakhir katakana (田中ー！); dipakai
            ``_shout_end`` untuk menyerap teriakan, bukan untuk batas kanan.
    """
    if not (any_script or is_katakana(name[-1])):
        return False
    if end >= len(text) or text[end] not in _LONG_VOWELS:
        return False
    after = end + 1
    if after >= len(text) or text[after] not in _SHOUT_END_CHARS:
        return False
    return search_key(name + text[end]) not in data.loanwords()


def _shout_end(text: str, end: int, name: str) -> int:
    """Posisi akhir teriakan setelah nama/honorifik, atau ``end`` bila tidak ada teriakan.

    Teriakan ikut masuk slot dan tidak dirender: ``アリスーーッ！`` → ``[[E1]]！`` →
    ``Alice!``, juga setelah honorifik (``ユキちゃんーー！`` → ``Yuki-chan!``) dan
    dengan っ hiragana (``ユキっ！``, ``ユキさまーっ！``). Dengan begitu mesin tidak
    pernah menerima (dan menggemakan) ー/ッ yang menempel ke penanda. Bentuk
    teriakan: deretan ー/ッ/っ yang minimal dua huruf atau berakhir ッ/っ, atau SATU
    ー sebelum ``_SHOUT_END_CHARS`` yang bukan kata serapan (``name`` + ー).

    Ekornya hanya diserap bila disusul ``_SHOUT_FOLLOWERS`` (tanda teriakan, tanda
    baca, kurung/kutip penutup, spasi, akhir teks). Sebelum huruf lain ekor itu
    bukan teriakan dan dibiarkan di teks: ーー sebagai tanda pisah (``田中ーーいや``)
    dan ッ/っ awal partikel atau kata (``ユキッて``, ``ユキって``, ``田中ッ子``).
    """
    after = _strong_shout_end(text, end, hiragana_sokuon=True,
                              follower_ok=_SHOUT_FOLLOWERS.__contains__)
    if after is not None:
        return after
    return end + 1 if _single_long_vowel_shout(text, end, name, any_script=True) else end


def _not_this_entity(
    entry: GlossaryEntry, text: str, match: re.Match[str], named: frozenset[str] = frozenset()
) -> bool:
    """Kecocokan yang konteksnya menunjukkan kata biasa, bukan entri ini.

    - Entri orang yang bukan milik pengguna, diikuti honorifik yang sebenarnya okurigana + ん:
      aturan konteks yang sama dengan deteksi (``style.verb_run_before_honorific``), dengan
      ``named`` dan entri berbacaan (治 おさむ dari ruby, data, atau glosarium) sebagai nama
      yang terbukti (tingkat nama 2). Pengecualian: entri satu kanji yang juga batang kata
      kerja (``_verb_stem_entry``: 歩, 咲, 輝 dari jalan sebelumnya) hanya terbukti lewat
      ``named`` dokumen ini, karena bacaannya dari data tidak lebih kuat dari tingkat 1 dan
      entri itu bisa berasal dari salah baca di dokumen lain. 行くんですか, 駅まで歩くんですか,
      dan entri lama 来週行 di 来週行くんだ tidak dimasking; おい、乾くん！, 開くんが, dan
      弟の歩くんです tetap dimasking.
    - Entri orang satu kanji yang bukan milik pengguna, tanpa honorifik, dalam konteks kata
      biasa (``_bare_word``: 来るんだ, 持ってきた, 持ち主, 話は終わりだ). Entri batang kata kerja
      bertanda bukti tegas (``_strong_names``: 磨 dari 磨くんが dan 磨くん、) dianggap nama di sini.
    - Tempat bawaan yang juga kata umum (``data.AMBIGUOUS_PLACES``: 大分 "cukup", 三重
      "tiga lapis") tanpa sufiks tempat (大分よくなった, 三重の塔). 大分県, 三重県, 大分駅,
      dan 大分市 tetap tempat.

    Entri pengguna tidak pernah ditafsir ulang.
    """
    if entry.kind == PERSON and entry.source != USER_SOURCE:
        known = named | {match["name"]} if entry.reading else named
        hon = match["hon"] or ""
        if hon:
            end = match.end("hon")
            before = text[max(0, match.start() - VERB_CONTEXT_CHARS):match.start()]
            level = named if _verb_stem_entry(entry) else known
            if verb_run_before_honorific(match["name"], hon, text[end:end + VERB_AFTER_CHARS],
                                         before=before, named=level):
                return True
        elif not match["suf"] and _bare_word(match["name"], text, match.end("name"),
                                             known | _strong_names(entry)):
            return True
    return (entry.source == BUILTIN_SOURCE and entry.surface in data.AMBIGUOUS_PLACES
            and (match["suf"] or "") not in PLACE_SUFFIXES)


def _strong_names(entry: GlossaryEntry) -> frozenset[str]:
    """Tulisan entri yang tersimpan dengan bukti nama tegas (``glossary.STRONG_SOURCE_MARK``):
    boleh dimasking tanpa honorifik sebelum partikel nama (磨が, 磨と), bukan sebelum okurigana."""
    return frozenset({entry.surface}) if STRONG_SOURCE_MARK in entry.source else frozenset()


def _verb_stem_entry(entry: GlossaryEntry) -> bool:
    """Entri satu kanji yang kanjinya juga batang kata kerja (``style.is_verb_stem``: 歩, 渡)."""
    return len(entry.surface) == 1 and is_verb_stem(entry.surface)


def _bare_word(name: str, text: str, end: int, named: frozenset[str]) -> bool:
    """Kanji tunggal tanpa honorifik yang menjadi bagian kata kerja atau kata biasa.

    Batang kata kerja (``style.is_verb_stem``) yang tidak dikenal sebagai nama
    (``style.is_known_name`` atau ``named``) tidak pernah dimasking tanpa honorifik: 話は,
    持って, 来な. Kanji lain ditolak bila disusul hiragana okurigana, yaitu hiragana di luar
    ``_BARE_NAME_FOLLOWERS`` dan ``_BARE_NAME_PARTICLES`` (歩いて, 見る), atau って/った sesudah
    kanji yang bentuk -te/-ta-nya ``_TTE_STEMS`` (勝って, 治って, 渡った, 渡ったら). Nama satu
    kanji sebelum partikel tetap dimasking: 翔が, 哲って, 歩って誰, 翔ったら, 開の, 翔まで,
    哲しか, 慧くらい.
    """
    if len(name) != 1:
        return False
    if is_verb_stem(name) and name not in named and not is_known_name(name):
        return True
    if end >= len(text) or not is_hiragana(text[end]):
        return False
    if text.startswith(("って", "った"), end):
        return name in _TTE_STEMS
    if text.startswith(_BARE_NAME_PARTICLES, end):
        return False
    return text[end] not in _BARE_NAME_FOLLOWERS


def _plain_honorific(hon: str) -> str:
    """Honorifik tanpa tanda panjang teriakan: ``さーーん`` → ``さん``."""
    return "".join(ch for ch in hon if ch not in _LONG_VOWELS)


def _address_run_end(text: str, pos: int) -> int | None:
    """Akhir deretan kanji alamat mulai ``pos`` bila memuat unit kota ``市区町村郡``.

    Deretan berisi kanji dan ``ヶケヵ`` (鎌ケ谷市). ``None`` bila ``pos`` bukan kanji atau
    deretannya tidak memuat unit kota.
    """
    if pos >= len(text) or not is_kanji(text[pos]):
        return None
    end = pos
    while end < len(text) and (is_kanji(text[end]) or text[end] in _ADDRESS_INNER_CHARS):
        end += 1
    return end if _ADDRESS_UNIT_CHARS.intersection(text[pos:end]) else None


def _admin_unit(entry: GlossaryEntry, name: str, hon: str, suffix: str) -> bool:
    """Tempat yang berakhir unit wilayah 都/道/府/県 (愛知 + 県, atau 北海道 tanpa sufiks)."""
    if hon or entry.kind != PLACE:
        return False
    return suffix in _ADMIN_ENDINGS or (not suffix and name.endswith(_ADMIN_NAME_ENDINGS))


def _inner_suffix(name: str, entry: GlossaryEntry) -> str:
    """Sufiks kota di dalam kunci peta masking (松本市 → entri 松本 + ``市``), atau kosong.

    ``pipeline.admin_stem_entry`` menyimpan kota bersufiks dari deteksi entitas
    sebagai entri bertulisan nama saja dengan kunci tulisan utuh; sufiksnya
    dirender ``Renderer`` (``Kota Matsumoto``).
    """
    if (entry.kind == PLACE and len(name) == len(entry.surface) + 1
            and name.startswith(entry.surface) and name[-1] in _MUNICIPALITY_ENDINGS):
        return name[-1]
    return ""


def _plural_boundary(text: str, end: int) -> bool:
    """ら/たち berakhir di ``end`` dan yang menyusul partikel, tanda baca, atau akhir teks.

    Menolak awal kata lain: 福島らへん (sekitar), 宮崎らーめん, 千葉たちうお.
    """
    if end >= len(text) or not is_kana(text[end]):
        return True
    return text[end] in _PLURAL_FOLLOWERS and not text.startswith(_NOT_PLURAL_WORDS, end)


def _titled(text: str, end: int, entry: GlossaryEntry) -> bool:
    """Nama orang yang langsung diikuti gelar jabatan (佐藤部長, 田中社長)."""
    return entry.kind == PERSON and text.startswith(TITLE_WORDS, end)


def _same_script(neighbor: str, edge: str) -> bool:
    """Dua karakter sama-sama kanji atau sama-sama katakana."""
    return (is_kanji(neighbor) and is_kanji(edge)) or (
        is_katakana(neighbor) and is_katakana(edge)
    )


def _warn_unexpected(found: Counter[int], masked: Masked) -> None:
    """Catat penanda karangan mesin dan penanda yang terduplikasi."""
    expected = Counter(int(n) for n in EXACT_TOKEN_RE.findall(masked.text))
    invented = sorted(set(found) - set(masked.slots))
    if invented:
        logger.warning("penanda karangan mesin dibuang: %s", invented)
    for number in sorted(masked.slots):
        if found[number] > expected[number]:
            logger.warning(
                "penanda E%d muncul %d kali (asli %d)", number, found[number], expected[number]
            )


def _normalized(translated: str) -> str:
    """Keluaran mesin tanpa entitas HTML dan dengan penanda lebar penuh dinormalkan."""
    return html.unescape(translated).translate(_FULLWIDTH_TOKEN_CHARS)


def _count_tokens(text: str) -> Counter[int]:
    """Hitung kemunculan tiap nomor penanda (regex toleran)."""
    return Counter(int(m.group(1)) for m in TOKEN_RE.finditer(text))


def _missing(found: Counter[int], masked: Masked) -> list[int]:
    return sorted(set(masked.slots) - set(found))


def _squeeze_spaces(text: str) -> str:
    """Rapikan spasi ganda dan spasi di tepi tiap baris."""
    lines = (_SPACES_RE.sub(" ", line).strip(" \t") for line in text.split("\n"))
    return "\n".join(lines)


def _loose(text: str) -> str:
    """Bentuk longgar untuk perbandingan: tanpa diakritik, casefold, spasi tunggal."""
    return " ".join(strip_diacritics(text).casefold().split())
