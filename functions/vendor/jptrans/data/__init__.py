"""Data bawaan jptrans: nama keluarga, tempat terkenal, dan kata serapan.

Berkas JSON dibaca lewat ``importlib.resources`` agar tetap bisa dibaca saat
program dijalankan dari zipapp (``jptrans.pyz``). Hasilnya di-cache dan
dibekukan (``MappingProxyType``, ``tuple``, ``frozenset``) sehingga tidak ada
state global yang bisa berubah.

Isi berkas:

- ``surnames.json``: ``{"佐藤": "さとう", ...}``, hanya nama keluarga dengan
  bacaan yang jelas dominan (河野, 東, 菅野 yang punya dua bacaan umum sengaja
  tidak dimasukkan). Kota/prefektur bawaan yang juga nama keluarga umum (町田,
  広島, 豊田) ikut dimuat dengan bacaan nama keluarganya (豊田 とよだ).
- ``places.json``: ``{"東京": {"id": "Tokyo", "en": "Tokyo", "reading": "とうきょう"}}``.
  Ejaan mapan tanpa makron. Prefektur disimpan tanpa 県/府/都 agar sufiksnya
  dirender oleh ``style.SUFFIX_RULES`` (千葉県 → Prefektur Chiba). Berisi
  prefektur, ibu kota prefektur, dan 50 kota terbesar (kota tanpa sufiks 市,
  agar 豊田市 → Kota Toyota). Kata yang juga kata umum (日光 "sinar matahari",
  柏 "pohon ek") dan kota bertulisan hiragana (さいたま, いわき; 咲いたまま)
  sengaja tidak dimasukkan. Dua prefektur yang juga kata umum (大分 "cukup",
  三重 "tiga lapis") dimuat agar 47 prefektur lengkap, tetapi tercatat di
  ``AMBIGUOUS_PLACES``: ``protect.EntityMatcher`` hanya memaskingnya bila
  diikuti sufiks tempat (大分県, 三重県, 大分駅). Tempat
  yang juga nama keluarga di ``surnames.json`` (山口, 千葉, 町田) ditafsir
  sebagai orang oleh ``protect.EntityMatcher`` hanya bila konteksnya orang
  (山口家, 千葉さん).
- ``loanwords.json``: daftar katakana umum yang bukan nama (ドア, ギルド, ...).
- ``foreign_names.json``: ``{"given": {"Elizabeth": ["エリザベス", "エリザベート"]},
  "family": {"Smith": ["スミス"]}}``. Nama depan dan nama keluarga Barat/fantasi
  umum yang disusun sendiri dari pengetahuan umum; katakana pertama adalah bentuk
  utama, sisanya varian lazim. Satu katakana hanya punya satu ejaan Latin. Bacaan
  yang juga nama Jepang lazim dengan ejaan berbeda (レイ Rei/Ray, リナ, ルイ, アン)
  dan kata serapan di ``loanwords.json`` sengaja tidak dimasukkan.
- ``given_names.json``: ``{"美咲": {"reading": "みさき", "gender": "f"}, ...}``.
  Nama depan Jepang umum (lebih dari 500) dengan bacaan dan gender ``m``/``f``,
  disusun sendiri dari pengetahuan umum; nama uniseks (薫, 翼, 真琴) bergender
  ``""``. Tidak ada yang tumpang tindih dengan ``surnames.json``. Dipakai
  ``gender.infer_gender`` untuk menebak gender nama tanpa gender di glosarium.
  Bacaan yang lazim untuk kedua gender (れい: 麗 perempuan, 零/怜 laki-laki)
  dicatat di ``UNISEX_READINGS`` agar indeks bacaan tidak menebaknya.

- ``kanji_readings.json``: ``{"on": {"藤": ["とう"]}, "kun": {"藤": ["ふじ"]}}``.
  Bacaan hiragana sekitar 1800 kanji yang lazim di nama orang dan tempat
  (jōyō dan jinmeiyō yang umum), disusun sendiri dari pengetahuan umum. ``on``
  berisi bacaan on (dalam hiragana), ``kun`` berisi bacaan kun dan nanori (bacaan
  khusus nama: 和 かず, 司 つかさ) tanpa okurigana. Hanya bacaan yang berguna
  untuk nama; bacaan langka sengaja dibuang. Satu bacaan hanya di satu golongan.
- ``name_words.json``: ``{"飛鳥": ["あすか"], "乾": ["いぬい"], ...}``. Bacaan kata utuh nama
  yang tidak bisa disusun dari bacaan per kanji (jukujikun dan nanori lazim: 飛鳥 あすか,
  五月女 さおとめ, 不知火 しらぬい, 仁 ひとし), serta nama satu kanji yang juga batang kata kerja
  di ``VERB_STEMS`` (乾 いぬい, 開 かい/ひらく, 弾 だん). Digabung dengan
  ``NAME_WORD_READINGS`` oleh ``name_word_readings``; dipakai untuk memvalidasi jawaban
  mesin dan untuk menandai tulisan sebagai nama yang dikenal, bukan untuk merender.

Turunan: ``kanji_readings()`` dan ``kanji_reading_kinds()`` memakai
``kanji_readings.json``; kanji yang tidak ada di sana memakai bacaan yang
diturunkan dari ``surnames.json`` dan ``places.json`` (lihat
``_derived_kanji_readings``). Hasilnya hanya dipakai sebagai *kandidat* untuk
memvalidasi jawaban mesin berhuruf kecil (``pipeline.candidate_readings``), bukan
untuk merender nama atau menebak bacaan kota yang tidak dikenal.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from ..errors import JptransError

logger = logging.getLogger(__name__)

SURNAMES_FILE = "surnames.json"
PLACES_FILE = "places.json"
LOANWORDS_FILE = "loanwords.json"
FOREIGN_NAMES_FILE = "foreign_names.json"
GIVEN_NAMES_FILE = "given_names.json"
KANJI_READINGS_FILE = "kanji_readings.json"
NAME_WORDS_FILE = "name_words.json"
ON = "on"
KUN = "kun"
UNISEX_READINGS = frozenset("""
    れい るい いずみ ちひろ はるか なつき いおり かえで ゆき まお みき あすか ましろ みらい のあ
    みなみ ちはる みづき みずき りつ いつき れん すばる しょう ひろみ かずみ まさみ かつみ ひでみ
    なおみ なお ひかる かおる あきら まこと じゅん しのぶ ゆう ゆうき つかさ あおい ひなた
""".split())
"""Bacaan nama depan yang lazim untuk kedua gender, apa pun gender tulisan di kamus.

Indeks bacaan (``given_name_genders_by_reading``) memberi gender kosong untuk
bacaan ini. Gender dari tulisan yang ada di kamus (麗, 遥) tetap dipakai; daftar
ini hanya menghentikan tebakan untuk tulisan lain (零, 怜) dan nama kana.
"""
KANA_NAME_READINGS = frozenset("""
    みく かなで つむぎ みお いろは こはく しおん まどか ほむら まみ みどり つばめ たま けい あずさ
    かのん ここあ さほ すみか ちか ちせ とうか なぎ のどか はづき ひより ふうか まひろ みこと
    みやび もか ゆずは ゆの りおん りの ゆかり いちか かりん きらら こなつ さくや しの ちとせ
    なのは のの はるひ ひびき まなみ みつき むぎ めぐる よる あきと いぶき がく げん こたろう
    ごう さすけ しんじ せいや そうま たいが てつ とうま はくと ふうが まさむね むさし らいと
    りゅう きりと けんしん こてつ さく ちから てんま ひろむ ほくと みちる ゆうせい あすま
    あまね とわ せつな かなた なると
    れい れな りな りん えみ るい るか あん ゆりあ れお のあ るな えま あんり えみり せな
""".split())
"""Bacaan nama Jepang yang lazim ditulis kana tetapi tidak ada di ``given_names.json``.

Dipakai ``romaji.looks_japanese`` agar nama katakana seperti ミク, マドカ, シオン tidak
ditanyakan ke mesin (シオン bisa dijawab ``Zion``). Baris terakhir adalah bacaan yang
juga nama asing dengan ejaan lain (レイ, ルカ, レオ, エマ); seperti di
``foreign_names.json``, bentuk ini sengaja dibiarkan Hepburn.
"""
COMMON_NAME_READINGS = frozenset("""
    あいか あいな あさひ あずみ あやこ あやめ あゆ あゆか いつみ うらら えつこ えりな かずは
    かなえ かなみ かのこ きく きぬ きみえ きよ きよみ くにこ こずえ ことり さえ さちえ さつき
    さと さな さなえ しずえ しずこ じゅり すみこ せつこ たえ たえこ ちえ ちえこ ちさ ちづ ちはや
    ちほ ちよこ つね とめ ともえ なえ なつ なつこ なほ なみ なみえ にな のぶこ のりえ はつ はつえ
    はるこ ひさこ ひでこ ひろこ ふき ふさ ふじこ ふみ ふみえ まき まきこ まさえ まさこ ますみ
    まち まつ まつこ まな まなか まほ まゆ まゆこ みえ みえこ みさ みさお みちよ みつえ みね みや
    みやこ みよ みよこ もとこ ももか やすこ やすえ ゆな ゆいか ゆきえ ゆきの ゆず ゆずか ゆめ ゆら
    よしえ よしの よね りお りさこ りほ りよ れいか わかこ うめ たけ さよ すず ちず
    あきお あきひろ あつし いわお えいすけ かい かいり かつお かつや かつのり かずお かずひろ
    かずのり かずよし かんじ きいち くにお けんご けんじろう けんと こうき さだお さとる しげお
    しげのぶ しゅう しゅうと しゅうま しょうご しょうじ しんご しんや すぐる そういち たいせい
    たいよう たかお たかのり たかひろ たけお たけひこ たけのり たけまさ ただお たつお たつろう
    ちゅうや てつお てつじ てるお とおる としお としひろ としや としゆき ともかず ともや なおゆき
    のぶお のぶなが のぶひろ のぶゆき のぶよし のりお のりひろ のりゆき ひでお ひでよし ひろき
    ひろかず ひろみち ひろや ふみお ふみや まさお まさかず まさし まさのぶ まさひろ まさみち
    まさや まさよし まなと みちお みつお みつる もとき やすお やすし やすひろ やすのり ゆうご
    ゆうや ゆきお ゆきひろ よういち ようすけ よしあき よしお よしかず よしのぶ よしひろ よしゆき
    りゅうじ りゅうせい りゅうと りょうじ りょうま りょうへい いえやす
""".split())
"""Bacaan nama depan Jepang yang lazim (termasuk nama lama seperti ウメ, トメ, キヨ).

Pelengkap ``given_names.json`` (yang hanya memuat tulisan kanji yang umum) untuk
``romaji.looks_japanese``: tanpa daftar ini nama katakana seperti マキ, ユナ, ノブナガ
ditanyakan ke mesin dan jawaban yang salah (``Mackie``, ``Una``) menggantikan
Hepburn yang sudah benar.
"""
NAME_ELEMENTS = frozenset("""
    あき あつ いえ いさ えい えつ かず かつ かね きみ きよ くに けい けん こう さだ さと しげ
    しず しょう しん すけ すみ たか たけ ただ たつ ちか つぐ つね てつ てる とし とみ とも なお
    なが なり のぶ のり はる ひさ ひこ ひで ひと ひろ ふみ まさ みち みつ むね もと もり やす
    ゆう ゆき よう よし より りゅう りょう しゅう じゅん だい ろう たろう じろう ぞう へい のすけ
""".split())
"""Unsur nama Jepang dua kana atau lebih yang lazim dirangkai (のぶ + なが, よう + すけ).

``romaji.looks_japanese`` menerima bacaan yang tersusun dari DUA unsur ini (ノブナガ,
ヒデヨシ, マサヒロ) atau satu unsur + satu kana penutup (エツ + コ, ヒデ + オ). Unsurnya
sengaja tidak memuat potongan yang lazim di nama asing (たち, まる, ごん), supaya
タチアナ, マルコ, ゴンサロ tetap dianggap asing.
"""
KANJI_VARIANTS: Mapping[str, str] = MappingProxyType({
    "髙": "高", "﨑": "崎", "嵜": "崎", "齋": "斎", "齊": "斉", "邊": "辺", "邉": "辺", "條": "条",
    "廣": "広", "國": "国", "曾": "曽", "栁": "柳", "冨": "富", "瀨": "瀬", "惠": "恵", "德": "徳",
    "黑": "黒", "藏": "蔵", "實": "実", "壽": "寿", "榮": "栄", "縣": "県", "佛": "仏", "舘": "館",
    "邨": "村", "嶌": "島", "驒": "騨", "圓": "円", "淺": "浅", "增": "増",
})
"""Bentuk kanji lama/varian yang lazim di nama keluarga → bentuk bakunya (髙橋 = 高橋).

``kanji_reading_kinds`` memberi varian bacaan bentuk bakunya, dan
``pipeline.candidate_readings`` mencari kata utuh dalam bentuk baku (渡邊 → 渡辺
わたなべ)."""
NAME_WORD_READINGS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "日向": ("ひなた", "ひゅうが", "ひむかい"), "河野": ("こうの", "かわの"),
    "菅野": ("かんの", "すがの"), "織田": ("おだ",), "伊達": ("だて",), "大和": ("やまと",),
    "北条": ("ほうじょう",), "八幡": ("はちまん", "やはた", "やわた"), "大伴": ("おおとも",),
    "飛騨": ("ひだ",), "播磨": ("はりま",), "筑紫": ("つくし",), "服部": ("はっとり",),
    "鷹司": ("たかつかさ",), "若宮": ("わかみや",), "藤堂": ("とうどう",),
    "二階堂": ("にかいどう",), "東海林": ("しょうじ", "とうかいりん"), "小鳥遊": ("たかなし",),
    "四月一日": ("わたぬき",), "百目鬼": ("どうめき", "どめき"), "御手洗": ("みたらい",),
    "勅使河原": ("てしがわら",), "日下部": ("くさかべ",), "綾小路": ("あやのこうじ",),
    "吉良": ("きら",), "浅井": ("あさい", "あざい"), "新田": ("にった", "しんでん"),
    "大和田": ("おおわだ",), "陽菜": ("ひな", "はるな"), "結菜": ("ゆいな", "ゆな"),
    "大翔": ("ひろと", "はると", "やまと"), "陽翔": ("はると", "ひなと", "あきと"),
    "翔": ("しょう", "かける"), "光": ("ひかる", "ひかり", "こう"), "蒼": ("あおい", "そう"),
    "優": ("ゆう", "まさる", "すぐる"), "心": ("こころ", "しん"), "尾道": ("おのみち",),
})
"""Bacaan kata utuh untuk memvalidasi jawaban mesin berhuruf kecil, bukan untuk merender.

Isinya bacaan yang tidak bisa disusun dari bacaan per kanji (日向 ひなた, 服部
はっとり, 小鳥遊 たかなし), nama yang bacaan rangkaiannya menyesatkan (鷹司: たか + し
akan meloloskan ``takashi``), dan bacaan ganda yang lazim dari kata yang juga ada di
``surnames.json``/``given_names.json`` dengan satu bacaan saja (河野, 陽菜). Kata utuh
yang dikenal hanya menerima bacaannya sendiri (``pipeline.candidate_readings``). Kode lain
membacanya lewat ``name_word_readings``, yang menambahkan isi ``name_words.json``."""
AMBIGUOUS_PLACES = frozenset({"大分", "三重"})
"""Tempat di ``places.json`` yang juga kata umum (大分 だいぶ "cukup", 三重 "tiga lapis").

``protect.EntityMatcher`` hanya memaskingnya bila langsung diikuti sufiks tempat
(大分県, 三重県, 大分市, 大分駅); tanpa sufiks teksnya dikirim apa adanya ke mesin."""
VERB_STEMS: Mapping[str, frozenset[str]] = MappingProxyType({
    "く": frozenset("行書聞置泣鳴抱働驚吹履吐弾焼巻招拭敷突着付就解説届続動乾叩嘆浮退剥向効"
                   "欠割裂貫省除背赴炊覗湧沸引開歩咲響輝磨抜描拓導囁呟頷傾築裁欺掃焚轢挽聴"
                   "利噴葺撒蒔妬渇飽溶梳穿点憑衝措"),
    "た": frozenset("見出寝着居似煮来経得干射立待持勝打保育討撃放断絶建発裁"),
    "さ": frozenset("許話貸返消押離逃殺隠戻出指刺増減回写移残倒化渡治直示越超試申足外壊成為流"
                   "放通癒冒犯侵汚潰記挿差推崩遺帰還課干下映"),
})
"""Batang kata kerja satu kanji → kana okurigana yang sama dengan awal honorifik ber-ん.

行 + くん di 行くんですか adalah 行く + ん (penjelas), 来 + たん di 来たんですか adalah
来た + ん (juga 待 + たん: negasi lisan 待たん), dan 許 + さん di 許さん adalah negasi lisan
許さん. Kunci = honorifik tanpa ん. Tabel ini hanya mencatat bahwa tulisan itu BISA dibaca
kata kerja; kanji yang juga lazim sebagai nama satu huruf (歩, 咲, 響, 輝, 開, 弾, 乾, 渡, 治,
直) sengaja ikut dimuat. Nama atau kata kerja diputuskan dari konteks oleh
``style.verb_run_before_honorific`` (jenis konteks sebelum dan sesudah honorifik di
``style.VERB_CONTEXT_TABLE``, dibandingkan dengan tingkat nama tulisan itu: dikenal di data
lewat ``style.is_known_name`` atau terbukti di dokumen)."""
COMMON_ENGLISH_WORDS = frozenset("""
    a an and as at be by do go gone went in is it me my no of on or so to up we us he she
    key dock shock line fall come came eat drink read run walk say said word back home way
    row see look sea sun moon star sky tree road path field stone rock wood fire water rain
    snow wind light dark day night year life love heart mind soul hand eye head red blue
    white black green gold silver king queen god demon devil dragon bird fish cat dog wolf
    bear fox horse tiger deer flower rose lily bell door gate house town city village castle
    temple shrine bridge river lake hill mountain island port bay shore spring summer autumn
    winter morning noon evening dream hope truth peace war blade sword arrow shield ship cloud
    cloudy field mound hall shop store yes yeah not all one two three ten going coming
    paw toe her him his our raw saw law jaw car bar far jar tar
""".split())
"""Kata Inggris umum yang tidak diterima sebagai ejaan nama dari mesin.

Mesin sering menjawab arti, bukan bunyi (行 → ``go``, 言 → ``gone``, 帰 → ``key``).
Dipakai ``pipeline.clean_name`` untuk nama satu kanji yang tidak dikenal utuh di data
proyek (bacaan on dua kana seperti ぎょう untuk 行 adalah kandidat, jadi daftar ini yang
menolak ``go``), dan untuk tiap kata jawaban bila data tidak punya kandidat bacaan sama
sekali (``Home`` untuk 猫屋). Nama yang dikenal (杏 あん) tetap boleh berbunyi seperti
kata Inggris."""
MIN_GROUP_WORDS = 2
"""Jumlah kata minimum yang berbagi kanji awal/akhir agar bacaan kanji itu diturunkan."""
MIN_SUBTRACT_KANA = 2
"""Bacaan kanji sependek ini (田 た) tidak dipakai untuk mengurangi: terlalu mudah salah potong."""


def surnames() -> Mapping[str, str]:
    """Kembalikan peta nama keluarga ke bacaan hiragana (``佐藤`` → ``さとう``)."""
    return _load(SURNAMES_FILE)


def places() -> Mapping[str, Mapping[str, str]]:
    """Kembalikan peta tempat terkenal ke ejaan ``id``/``en`` dan ``reading``."""
    return _load(PLACES_FILE)


def loanwords() -> frozenset[str]:
    """Kembalikan himpunan katakana umum yang bukan nama."""
    return frozenset(_load(LOANWORDS_FILE))


@lru_cache(maxsize=None)
def foreign_names() -> Mapping[str, str]:
    """Kembalikan peta katakana nama asing ke ejaan Latinnya (``エリザベート`` → ``Elizabeth``).

    Nama depan dan nama keluarga digabung, karena bagian nama (dipisah ・)
    dicari satu per satu.

    Raises:
        JptransError: Berkas rusak atau satu katakana punya dua ejaan berbeda.
    """
    merged: dict[str, str] = {}
    for group in _load(FOREIGN_NAMES_FILE).values():
        for latin, forms in group.items():
            for kana in forms:
                if merged.setdefault(kana, latin) != latin:
                    raise JptransError(f"{FOREIGN_NAMES_FILE}: {kana} punya dua ejaan")
    return MappingProxyType(merged)


def given_names() -> Mapping[str, Mapping[str, str]]:
    """Kembalikan peta nama depan ke ``reading`` dan ``gender`` (``美咲`` → みさき, f)."""
    return _load(GIVEN_NAMES_FILE)


@lru_cache(maxsize=None)
def name_word_readings() -> Mapping[str, tuple[str, ...]]:
    """Bacaan kata utuh nama: ``NAME_WORD_READINGS`` digabung dengan ``name_words.json``.

    Bacaan dari kedua sumber disatukan tanpa duplikat (百目鬼: どうめき, どめき, どどめき).

    Raises:
        JptransError: ``name_words.json`` rusak (bukan peta tulisan → daftar bacaan).
    """
    merged = {surface: list(readings) for surface, readings in NAME_WORD_READINGS.items()}
    raw = _load(NAME_WORDS_FILE)
    if not isinstance(raw, Mapping):
        raise JptransError(f"{NAME_WORDS_FILE} harus objek JSON")
    for surface, readings in raw.items():
        if not isinstance(readings, tuple) or not all(isinstance(r, str) for r in readings):
            raise JptransError(f"{NAME_WORDS_FILE}: bacaan {surface} harus daftar string")
        items = merged.setdefault(surface, [])
        items.extend(reading for reading in readings if reading not in items)
    return MappingProxyType({surface: tuple(items) for surface, items in merged.items()})


@lru_cache(maxsize=None)
def name_readings() -> frozenset[str]:
    """Semua bacaan nama utuh yang dikenal data proyek (hiragana, tanpa spasi).

    Gabungan bacaan ``surnames.json``, ``given_names.json``, ``name_word_readings``
    (``NAME_WORD_READINGS`` + ``name_words.json``), ``KANA_NAME_READINGS``, dan
    ``COMMON_NAME_READINGS``. Dipakai
    ``pipeline.candidate_readings`` untuk mengizinkan rangkaian bacaan on/kun campuran
    yang memang bacaan nama (御堂 みどう, 美堂 みどう).
    """
    found = set(surnames().values())
    found.update(info["reading"] for info in given_names().values())
    found.update(reading for items in name_word_readings().values() for reading in items)
    found.update(KANA_NAME_READINGS | COMMON_NAME_READINGS)
    return frozenset(reading for reading in found if reading)


@lru_cache(maxsize=None)
def given_name_genders_by_reading() -> Mapping[str, str]:
    """Peta bacaan hiragana nama depan → gender, untuk nama kana (ミサキ) atau kanji lain.

    Bila tulisan-tulisan dengan bacaan yang sama tidak sepakat (まこと: 誠 laki-laki,
    真琴 uniseks), atau bacaannya ada di ``UNISEX_READINGS`` (れい), gendernya
    kosong: bacaan saja tidak cukup sebagai bukti.

    Returns:
        Peta bacaan → ``"m"``, ``"f"``, atau ``""`` (beku).
    """
    found: dict[str, set[str]] = {}
    for info in given_names().values():
        found.setdefault(info["reading"], set()).add(info["gender"])
    for reading in UNISEX_READINGS:
        found.setdefault(reading, set()).add("")
    return MappingProxyType({reading: genders.pop() if len(genders) == 1 else ""
                             for reading, genders in found.items()})


@lru_cache(maxsize=None)
def kanji_reading_kinds() -> Mapping[str, Mapping[str, str]]:
    """Peta kanji → (bacaan hiragana → golongan ``"on"``, ``"kun"``, atau ``""``).

    Isi ``kanji_readings.json`` (kun dan nanori dulu, lalu on), ditambah bentuk
    varian ``KANJI_VARIANTS`` dengan bacaan bentuk bakunya (髙 = 高). Kanji yang tidak
    ada di berkas itu memakai bacaan turunan ``_derived_kanji_readings`` dengan
    golongan ``""`` (tidak diketahui). Bacaan turunan TIDAK ditambahkan ke kanji
    yang sudah ada di berkas: turunan seperti 宮 → のみや (dari 二宮, 西宮) akan
    membuat jawaban salah ``wakanomiya`` untuk 若宮 lolos.

    Raises:
        JptransError: Berkas rusak atau bacaan yang sama ada di dua golongan.
    """
    raw = _load(KANJI_READINGS_FILE)
    merged: dict[str, dict[str, str]] = {}
    for kind in (KUN, ON):
        for kanji, readings in raw[kind].items():
            for reading in readings:
                if merged.setdefault(kanji, {}).setdefault(reading, kind) != kind:
                    raise JptransError(f"{KANJI_READINGS_FILE}: {kanji} {reading} ganda")
    for variant, standard in KANJI_VARIANTS.items():
        if variant not in merged and standard in merged:
            merged[variant] = dict(merged[standard])
    for kanji, readings in _derived_kanji_readings().items():
        if kanji not in merged:
            merged[kanji] = {reading: "" for reading in readings}
    return MappingProxyType({kanji: MappingProxyType(items) for kanji, items in merged.items()})


@lru_cache(maxsize=None)
def kanji_readings() -> Mapping[str, tuple[str, ...]]:
    """Peta kanji → tuple bacaan hiragana (``kanji_reading_kinds`` tanpa golongan)."""
    return MappingProxyType({kanji: tuple(items)
                             for kanji, items in kanji_reading_kinds().items()})


@lru_cache(maxsize=None)
def _derived_kanji_readings() -> Mapping[str, tuple[str, ...]]:
    """Turunkan bacaan hiragana per kanji dari nama keluarga dan tempat bawaan.

    Tiga sumber, semuanya dari data proyek sendiri:

    1. Kata satu kanji (林 はやし, 森 もり).
    2. Awalan bersama: kata-kata yang diawali kanji yang sama (高橋 たかはし,
       高田 たかだ, 高木 たかぎ) memberi bacaan awalan bersama yang terpanjang
       (高 → たか). Hal yang sama untuk akhiran (二宮, 西宮 → 宮 → のみや).
       Minimal ``MIN_GROUP_WORDS`` kata, agar satu kata tidak dipotong asal.
    3. Pengurangan: kata dua kanji yang bacaan salah satu kanjinya sudah
       diketahui (minimal ``MIN_SUBTRACT_KANA`` kana) memberi bacaan kanji yang
       lain (宮本 みやもと − 宮 みや → 本 もと).

    Bacaan ini perkiraan dan hanya dipakai untuk kanji yang tidak ada di
    ``kanji_readings.json`` (lihat ``kanji_reading_kinds``).

    Returns:
        Peta kanji → tuple bacaan (tanpa duplikat, urutan stabil).
    """
    words = dict(surnames())
    words.update((surface, place["reading"]) for surface, place in places().items())
    found: dict[str, list[str]] = {}

    def add(kanji: str, reading: str) -> None:
        """Tambahkan ``reading`` ke bacaan ``kanji`` bila belum ada (urutan masuk dijaga)."""
        if reading and reading not in found.setdefault(kanji, []):
            found[kanji].append(reading)

    for surface, reading in words.items():
        if len(surface) == 1:
            add(surface, reading)
    for pick, shared in ((lambda w: w[0], _common_prefix), (lambda w: w[-1], _common_suffix)):
        groups: dict[str, list[str]] = {}
        for surface, reading in words.items():
            if len(surface) > 1:
                groups.setdefault(pick(surface), []).append(reading)
        for kanji, readings in groups.items():
            if len(readings) >= MIN_GROUP_WORDS:
                add(kanji, shared(readings))
    base = {kanji: [r for r in items if len(r) >= MIN_SUBTRACT_KANA]
            for kanji, items in found.items()}
    for surface, reading in words.items():
        if len(surface) != 2:
            continue
        head, tail = surface
        for known in base.get(head, ()):
            if reading.startswith(known) and len(reading) > len(known):
                add(tail, reading[len(known):])
        for known in base.get(tail, ()):
            if reading.endswith(known) and len(reading) > len(known):
                add(head, reading[:-len(known)])
    return MappingProxyType({kanji: tuple(items) for kanji, items in found.items()})


def _common_prefix(readings: list[str]) -> str:
    """Awalan bersama terpanjang dari beberapa bacaan."""
    first, last = min(readings), max(readings)
    size = 0
    while size < min(len(first), len(last)) and first[size] == last[size]:
        size += 1
    return first[:size]


def _common_suffix(readings: list[str]) -> str:
    """Akhiran bersama terpanjang dari beberapa bacaan."""
    return _common_prefix([reading[::-1] for reading in readings])[::-1]


@lru_cache(maxsize=None)
def _load(name: str) -> Any:
    """Baca satu berkas JSON bawaan sekali saja, lalu bekukan isinya.

    Raises:
        JptransError: Berkas tidak ada atau rusak (paket terpasang tidak utuh).
    """
    try:
        raw = files(__name__).joinpath(name).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise JptransError(f"data bawaan {name} tidak bisa dibaca: {exc}") from exc
    logger.debug("data bawaan %s dimuat", name)
    return _freeze(data)


def _freeze(value: Any) -> Any:
    """Ubah dict dan list bersarang menjadi bentuk yang tidak bisa diubah."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
