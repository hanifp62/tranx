"""Deteksi entitas (nama orang, tempat, organisasi, istilah) secara bertingkat.

Setiap tingkat menghasilkan *sinyal* ber-skor untuk satu tulisan; sinyal
terkuat menentukan jenis dan skor dasar, lalu bonus frekuensi ditambahkan.

=====  ===========================================  ======================
Tier   Sinyal                                       Skor (konstanta)
=====  ===========================================  ======================
T1     ruby berbacaan hiragana + sinyal nama        ``SCORE_RUBY_NAME``
T1     ruby berbacaan hiragana saja                 ``SCORE_RUBY_PLAIN``
T1     ruby berbacaan katakana (gloss: 本気《マジ》)  ``SCORE_RUBY_GLOSS``
T2     nama + honorifik (田中さん, アリスちゃん)       ``SCORE_HONORIFIC``
T2     nama + gelar (佐藤部長, エリザ王女)            ``SCORE_TITLE``
T2     pola pembicara di awal baris (アリス「…」)     ``SCORE_SPEAKER``
T2     nama + sufiks tempat (吉祥寺駅)                ``SCORE_PLACE``
T2     kota setelah 都道府県 (愛知県刈谷市)             ``SCORE_PLACE``
T2     nama + sufiks organisasi (星見魔法学園)         ``SCORE_ORG``
T2     run katakana bukan kata serapan              ``SCORE_KATAKANA`` + ulang
T3     Janome ``名詞,固有名詞,人名/地域/組織``          ``+JANOME_BONUS``
=====  ===========================================  ======================

Bobot ini **asumsi desain** dari prototipe riset (LAPORAN_RISET 4.1), belum
dikalibrasi dengan korpus beranotasi. Semua angka ada di kepala modul agar
mudah disetel.

Dua keputusan untuk mencegah salah kunci:

- Bonus frekuensi hanya untuk sinyal nama. Ruby tanpa sinyal nama dan run
  katakana tidak mendapat bonus umum, karena furigana juga dipakai untuk kata
  sulit (憂鬱《ゆううつ》) yang bisa muncul berkali-kali tanpa menjadi nama.
  Run katakana sudah punya bonus ulang sendiri.
- Kata kekerabatan, sapaan, gelar, dan kata ganti (お兄ちゃん, 皆さん,
  お疲れ様, 校長先生, 君 sebagai "kamu") tidak pernah menjadi nama. Begitu
  juga kata berawalan sopan お/ご (お隣さん, ご苦労様) dan pekerjaan
  berakhiran 屋/員 (八百屋さん, 駅員さん).
- Run kanji sebelum honorifik bisa memuat kata lain di depannya
  (昨日田中さん): bila ekornya nama keluarga yang dikenal, hanya ekor itu
  yang menjadi nama. Run lebih dari empat kanji (長谷川美咲さん) hanya
  diterima bila diawali nama keluarga yang dikenal.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Container, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import NamedTuple

from . import data
from .config import Config
from .disambig import (
    HONORIFIC_SURFACES,
    TITLE_WORDS,
    VERB_AFTER_CHARS,
    VERB_CONTEXT_CHARS,
    honorific_fits,
    honorific_names_person,
    honorific_proves_name,
    is_known_name,
    is_verb_stem,
    verb_run_before_honorific,
)
from .models import ORG, PERSON, PLACE, TERM, Candidate, Document, GlossaryEntry
from .names import ambiguous_given_name, has_surname_head, split_family_reading
from .textnorm import (
    KANJI,
    KATAKANA,
    KATAKANA_RUN_RE,
    is_hiragana_text,
    kata_to_hira,
    search_key,
)

logger = logging.getLogger(__name__)

SCORE_RUBY_NAME = 0.8
SCORE_RUBY_PLAIN = 0.5
SCORE_RUBY_GLOSS = 0.3
SCORE_HONORIFIC = 0.85
SCORE_TITLE = 0.7
SCORE_SPEAKER = 0.75
SCORE_PLACE = 0.6
SCORE_ORG = 0.55
SCORE_FOREIGN_NAME = 0.65
SCORE_KATAKANA = 0.35
KATAKANA_REPEAT_BONUS = 0.1
KATAKANA_REPEAT_LIMIT = 3
FREQUENCY_BONUS = 0.05
FREQUENCY_BONUS_MAX = 0.15
JANOME_BONUS = 0.2
SCORE_JANOME_ONLY = 0.4
SCORE_MAX = 0.99
MAX_PLAIN_KANJI_NAME = 4
"""Run kanji yang lebih panjang hanya nama bila diawali nama keluarga (長谷川美咲)."""
MAX_KANJI_NAME = 6
POLITE_PREFIXES = frozenset("おご")
SHOUT_MARKS = "ーｰ"
"""Tanda panjang yang dibuang dari ujung run katakana teriakan (リンーー → リン)."""
OCCUPATION_ENDINGS = ("屋", "員")
"""Akhiran pekerjaan (八百屋, 駅員); nama keluarga seperti 土屋 tetap diterima."""

PLACE_SUFFIXES = ("駅", "市", "町", "村", "県", "都", "府", "区", "城", "山", "川", "島",
                  "国", "港", "寺", "神社")
FACILITY_WORDS = ("空港",)
"""Kata fasilitas berakhiran sufiks tempat (空港 = 空 + 港): 明日空港 adalah kata waktu + 空港, bukan
tempat bernama 明日空 (``is_time_word_place``)."""
MUNICIPALITY_SUFFIXES = ("市", "区", "町", "村")
"""Sufiks kota/distrik yang boleh menempel langsung setelah 都道府県 (愛知県刈谷市, 東京都港区)."""
NOT_MUNICIPALITY_STARTS = frozenset("内全各同当他隣両近旧外第")
"""Awal kata yang membuat ``都内各区``/``県内全町``/``県第一区`` frasa biasa, bukan nama kota."""
ADMIN_UNIT_CHARS = "都道府県市区町村"
"""Huruf unit wilayah; nama kota setelah 都道府県 tidak diawali salah satunya."""
GENERIC_MUNICIPALITY_WORDS = ("地区", "学区", "校区", "選挙区", "特区", "管区")
"""Kata umum berakhiran 区 yang bisa menyusul 都道府県 (愛知県地区大会, 東京都知事選挙区)."""
ORG_SUFFIXES = ("学園", "学院", "高校", "中学", "大学", "騎士団", "団", "組", "会", "部",
                "社", "商会", "ギルド")

HONORIFIC_EXCEPTIONS = (
    "お兄ちゃん", "お姉ちゃん", "お兄さん", "お姉さん", "兄さん", "姉さん", "兄ちゃん",
    "姉ちゃん", "お父さん", "お母さん", "父さん", "母さん", "お嬢様", "王様", "神様",
    "皆さん", "皆様", "みんな", "お疲れ様", "お疲れさま", "ご馳走様", "ご馳走さま",
    "お客様", "お客さん", "奥様", "奥さん", "貴様", "俺様", "ご苦労様", "ご苦労さま", "御苦労様",
    "お世話様", "ご愁傷様",
)
"""Frasa utuh yang berakhiran honorifik tetapi bukan nama (dari SPEC)."""

NOT_NAMES = frozenset({
    # Kata ganti dan kata waktu (今日君は = "kamu hari ini", bukan "Kyō-kun").
    "俺", "僕", "私", "彼", "彼女", "貴方", "貴女", "自分", "皆", "誰", "何",
    "拙者", "儂", "吾輩", "小生", "余", "朕", "某", "妾",
    "今", "今日", "明日", "昨日", "毎日", "今度", "今回", "本当", "時", "前", "後", "頃",
    # Kekerabatan.
    "兄", "姉", "弟", "妹", "父", "母", "祖父", "祖母", "叔父", "叔母", "伯父", "伯母",
    "爺", "婆", "息子", "娘", "夫", "妻", "旦那", "奥", "嫁", "坊", "嬢", "赤",
    # Gelar dan peran (校長先生, 勇者様, お客様).
    "王", "王子", "王女", "女王", "姫", "神", "女神", "魔王", "勇者", "聖女", "殿", "陛下",
    "殿下", "先生", "先輩", "後輩", "校長", "担任", "店長", "部長", "社長", "課長", "会長",
    "隊長", "団長", "師匠", "医者", "博士", "主人", "客", "大家", "店員", "警官", "運転手",
    "看護師", "生徒", "学生", "一人", "二人", "人", "子", "子供", "女", "男",
    "主", "若", "彼氏", "奥方", "大工", "猫", "犬", "隣",
})
"""Kata kanji yang sering mendahului honorifik tetapi bukan nama diri."""

MIN_VERB_STEM_RUBY = 2
"""Panjang minimal bacaan ruby batang kata kerja satu kanji agar menjadi bukti nama
(``_ruby_attests``)."""

TIME_PREFIXES = (
    "毎日", "毎朝", "毎晩", "毎週", "毎月", "毎年", "今日", "明日", "昨日", "今朝", "今夜", "今晩",
    "今週", "来週", "先週", "今月", "来月", "先月", "今年", "来年", "去年",
    "毎回", "毎度", "毎時", "毎夜", "毎週末", "今週末", "来週末", "先週末", "週末", "先日", "前日",
    "翌日", "当日", "後日", "一昨日", "明後日", "一昨年", "再来週", "再来月", "再来年", "昨夜", "昨晩",
    "昨年", "明朝", "明晩", "翌朝", "翌週", "翌月", "翌年", "夕方", "早朝", "深夜", "夜中", "午前",
    "午後", "平日", "休日", "祝日", "連休", "今回", "前回", "次回", "最近",
    "今度", "本日", "先程", "後程", "今後", "年末", "年始", "月末", "月初", "正月", "元日", "元旦",
    "朝晩", "毎夕", "一日中", "日中", "夜間", "昼間", "終日", "土日", "放課後", "正午", "今朝方",
    "朝方", "夕刻", "当日中", "今頃", "当時", "現在", "以前", "以後", "将来",
    # Musim berawalan 今/来/昨/毎/去 (今夏, 来春, 毎冬) dan kata waktu lain (putaran 2).
    *(head + season for head in "今来昨毎去" for season in "春夏秋冬"),
    "今夕", "今宵", "先々週", "先々月", "先々日", "隔週", "隔日", "隔月", "隔年", "連日", "連夜",
    "年内", "月内", "週内", "年中",
)
"""Kata waktu/frekuensi yang bisa menempel ke depan tempat + sufiks tanpa partikel (毎日駅まで,
明日吉祥寺駅で, 先日駅で). Nama hari (月曜, 日曜日) ditangani ``_WEEKDAY_RE``. Dicocokkan
terpanjang dulu (毎週末 sebelum 毎週)."""

_TIME_WORDS_LONGEST = tuple(sorted(TIME_PREFIXES, key=len, reverse=True))
TIME_TAIL_KANJI = frozenset("朝昼夜晩夕中頃末")
"""Satu kanji waktu yang menempel ke kata waktu (明日朝, 昨日夜, 今日中): sisa ini bukan nama tempat
(``_without_time_word``), berbeda dengan sisa satu huruf lain (明日香村)."""
_WEEKDAY_RE = re.compile("毎?[月火水木金土日]曜日?")
"""Nama hari, boleh berawalan 毎 (毎日曜 = setiap Minggu, 毎土曜日)."""
_DURATION_NUMERALS = "〇一二三四五六七八九十百千数何"
_DURATION_RE = re.compile(
    f"[{_DURATION_NUMERALS}]+(?:(?:[日週年]|[かヶカケヵ]月)(?:間[前後]?|[前後中])"
    "|時間[前後中]?|[分秒](?:間[前後]?|[前後]))"
)
"""Lama waktu berangka + 前/後/中/間 (三日前, 二週間後, 数年前, 三か月後, 二時間後, 三十分前).
Tanpa ekor itu bukan kata waktu: 二日市, 四日市, 十日町 adalah nama tempat."""
_COUNTER_BEFORE_RE = re.compile(f"[{_DURATION_NUMERALS}]+[かカケヵ]$")
"""Angka + か/ヶ (hiragana/katakana) tepat sebelum kandidat: 三か月後駅 terpotong menjadi 月後駅."""

GENERIC_COMPOUNDS = frozenset({
    "城下町", "田舎町", "生徒会", "委員会", "新聞部", "運動部", "文芸部", "冒険者ギルド",
    "新聞社", "出版社", "通信社", "株式会社", "有限会社", "旅行会社", "保険会社",
})
"""Kata majemuk umum yang kebetulan berakhiran sufiks tempat/organisasi."""

JANOME_KINDS = {"人名": PERSON, "地域": PLACE, "組織": ORG}
"""Pemetaan POS IPADIC (dipakai Janome) ke jenis entitas."""

ALIAS_TAG = "alias:"
"""Awalan bukti untuk alias sejati (mis. ｱﾘｽ untuk アリス); dibaca ``candidates_to_entries``."""

_KANJI_NAME = f"(?<![{KANJI}])[{KANJI}]{{1,{MAX_KANJI_NAME}}}"
_KATAKANA_NAME = f"(?<![{KATAKANA}]){KATAKANA_RUN_RE.pattern}"
_HONORIFIC_RE = re.compile(
    f"(?P<name>{_KANJI_NAME}|{_KATAKANA_NAME})"
    f"(?P<hon>{'|'.join(sorted(HONORIFIC_SURFACES, key=len, reverse=True))})"
)
# Nama sesingkat mungkin (lazy) agar 田中副社長 menjadi 田中 + 副社長, bukan 田中副 + 社長.
_TITLE_RE = re.compile(
    f"(?P<name>(?<![{KANJI}])[{KANJI}]{{2,{MAX_KANJI_NAME}}}?|{_KATAKANA_NAME})"
    f"(?P<title>{'|'.join(sorted(TITLE_WORDS, key=len, reverse=True))})"
)
_SPEAKER_RE = re.compile(f"^(?P<name>[{KANJI}]{{1,4}}|{KATAKANA_RUN_RE.pattern})[：:]?「")
# Kata waktu boleh mendahului nama 2-4 kanji (毎週末吉祥寺駅); ``_without_time_word`` membuangnya.
_TIME_PREFIX = f"(?:{_WEEKDAY_RE.pattern}|{'|'.join(_TIME_WORDS_LONGEST)})?"
# Ekor alamat yang boleh menempel sesudah sufiks tempat (松本市出身, 長野県松本市在住); selain itu
# kanji sesudah sufiks membatalkan (松本市内). Sama dengan ``protect.ADDRESS_TAILS``.
ADDRESS_TAILS = ("出身", "在住", "在勤", "生まれ", "育ち", "産")
_PLACE_END = (f"(?!(?!{'|'.join(tail for tail in ADDRESS_TAILS if tail != '産')}"
              f"|産(?![{KANJI}]))[{KANJI}])")
_SUFFIX_BASE = f"(?P<base>(?<![{KANJI}]){_TIME_PREFIX}[{KANJI}]{{2,4}}|{_KATAKANA_NAME})"
# Organisasi tanpa awalan kata waktu: 毎日新聞社 adalah nama, bukan 毎日 + 新聞社.
_ORG_BASE = f"(?P<base>(?<![{KANJI}])[{KANJI}]{{2,4}}|{_KATAKANA_NAME})"
_PLACE_RE = re.compile(f"{_SUFFIX_BASE}(?P<suf>{'|'.join(PLACE_SUFFIXES)}){_PLACE_END}")
_ORG_RE = re.compile(
    f"{_ORG_BASE}(?P<suf>{'|'.join(sorted(ORG_SUFFIXES, key=len, reverse=True))})"
    f"(?![{KANJI}])"
)
# Kota setelah unit wilayah (愛知県刈谷市, 東京都港区): unit wilayah itu sendiri harus
# didahului kanji (bagian nama prefektur), agar 都内 di awal kalimat tidak ikut. Nama
# kotanya tidak diawali huruf unit wilayah dan tidak memuat 市/区, agar 京都市中京区,
# 学園都市第七学区, 都道府県市区町村, dan 大阪府大阪市北区 tidak menjadi kandidat palsu.
_ADMIN_CHILD_RE = re.compile(
    f"(?<=[{KANJI}][都道府県])(?![{ADMIN_UNIT_CHARS}])"
    f"(?P<base>(?:(?![市区])[{KANJI}]){{1,4}})"
    f"(?P<suf>{'|'.join(MUNICIPALITY_SUFFIXES)}){_PLACE_END}"
)
_KANJI_CHAR_RE = re.compile(f"[{KANJI}]")
_KATAKANA_WORD_RE = re.compile(f"[{KATAKANA}]+")


class _Signal(NamedTuple):
    """Satu bukti bahwa ``surface`` adalah entitas."""

    surface: str
    kind: str
    score: float
    evidence: str
    reading: str = ""
    frequency_bonus: bool = True


@dataclass
class _Found:
    """Gabungan sinyal untuk satu tulisan; sinyal terkuat menentukan jenis."""

    kind: str
    score: float
    frequency_bonus: bool
    reading: str = ""
    extra: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def absorb(self, signal: _Signal) -> None:
        """Masukkan sinyal baru; ganti jenis dan skor bila lebih kuat."""
        if signal.score > self.score:
            self.kind, self.score = signal.kind, signal.score
            self.frequency_bonus = signal.frequency_bonus
        self.reading = self.reading or signal.reading
        if signal.evidence not in self.evidence:
            self.evidence.append(signal.evidence)


def detect_entities(
    doc: Document, known: set[str] | None = None, *, use_janome: bool = False
) -> list[Candidate]:
    """Cari kandidat entitas di seluruh dokumen.

    Args:
        doc: Dokumen hasil pembaca; ``doc.ruby`` dipakai sebagai T1.
        known: Tulisan yang sudah ada di glosarium; dilewati. Tempat bawaan
            dari ``data/places.json`` juga selalu dilewati.
        use_janome: Pakai Janome (T3) bila terpasang.

    Returns:
        Kandidat terurut dari skor tertinggi, sudah melalui ``merge_aliases``.
    """
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    skip = set(known or ()) | set(data.places())
    found: dict[str, _Found] = {}
    _absorb_all(found, _honorific_signals(text, attested_names(text, doc.ruby)))
    _absorb_all(found, _title_signals(text))
    _absorb_all(found, _speaker_signals(paragraph.text for paragraph in doc.paragraphs))
    named = set(found)
    _absorb_all(found, _suffix_signals(text, skip))
    _absorb_all(found, _katakana_signals(text, skip))
    _absorb_all(found, _ruby_signals(doc.ruby, named))
    if use_janome:
        _apply_janome(found, text)
    candidates = [
        _finalize(surface, item, text, doc.ruby)
        for surface, item in found.items()
        if surface not in skip
    ]
    logger.info("deteksi entitas: %d kandidat dari %d karakter", len(candidates), len(text))
    return merge_aliases(candidates)


def attested_names(text: str, ruby: Mapping[str, str] | None = None) -> frozenset[str]:
    """Tulisan yang di ``text`` terbukti nama, untuk aturan kata kerja + ん dokumen ini.

    Bukti: run kanji + honorifik ber-ん yang disusul huruf yang hanya mungkin untuk nama
    (``style.honorific_names_person``: 乾くんが, 開くん、, 治さんは), atau tulisan berkanji
    yang punya ruby hiragana di dokumen (歩《あゆむ》; untuk batang kata kerja satu kanji hanya bacaan
    nama yang dikenal, lihat ``_ruby_attests``). Kemunculan lain yang konteksnya
    ambigu (乾くんだ！) lalu dibaca nama juga, baik di deteksi maupun di masking
    (``protect.EntityMatcher``), sehingga satu dokumen konsisten.

    Args:
        text: Seluruh teks dokumen.
        ruby: Pasangan furigana dokumen.
    """
    found = {base for base, reading in (ruby or {}).items()
             if _KANJI_CHAR_RE.search(base) and is_hiragana_text(reading)
             and _ruby_attests(base, reading)}
    for match in _HONORIFIC_RE.finditer(text):
        after = text[match.end():match.end() + VERB_CONTEXT_CHARS]
        if _KANJI_CHAR_RE.match(match["name"]) and honorific_names_person(match["hon"], after):
            found.add(match["name"])
    return frozenset(found)


def _ruby_attests(base: str, reading: str) -> bool:
    """Ruby ``base``《``reading``》 membuktikan nama untuk ``attested_names``.

    Ruby kata biasa selalu bukti. Untuk satu kanji yang juga batang kata kerja (``is_verb_stem``)
    ruby di EPUB/Aozora sering hanya bacaan batang kata kerja itu (咲《さ》く, 歩《ある》く,
    渡《わた》す), jadi bacaannya harus bacaan nama yang dikenal untuk kanji itu
    (``data.kanji_readings``, ``data.name_word_readings``, ``data.given_names``), minimal
    ``MIN_VERB_STEM_RUBY`` kana, dan bukan awalan bacaan nama lain yang lebih panjang (わた dari
    わたる). 歩《あゆむ》 dan 咲《さき》 tetap bukti.
    """
    if len(base) != 1 or not is_verb_stem(base):
        return True
    known = set(data.kanji_readings().get(base, ())) | set(data.name_word_readings().get(base, ()))
    given = data.given_names().get(base)
    if given and given.get("reading"):
        known.add(given["reading"])
    return (len(reading) >= MIN_VERB_STEM_RUBY and reading in known
            and not any(other != reading and other.startswith(reading) for other in known))


def honorific_name_counts(doc: Document) -> Counter[str]:
    """Jumlah kemunculan nama + honorifik per tulisan (sama dengan deteksi T2 honorifik).

    Dipakai ``pipeline.Translator`` untuk menilai seberapa kuat bukti entri satu kanji.
    """
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    named = attested_names(text, doc.ruby)
    return Counter(signal.surface for signal in _honorific_signals(text, named))


def strong_name_counts(doc: Document) -> Counter[str]:
    """Jumlah kemunculan nama + honorifik yang konteksnya nama tegas, per tulisan.

    Tegas menurut ``style.honorific_proves_name``: honorifik yang tidak mungkin okurigana kata
    kerja untuk kanji itu (咲ちゃん, 歩さま, 輝さん), huruf sesudah honorifik yang hanya mungkin untuk
    nama (歩くんが, 歩くん、, 渡さんが来た), atau panggilan dengan koma/seru di posisi panggilan
    (渡さん、おはよう, おい歩くん！). Negasi sesudah topik (娘は渡さん！) dan kemunculan yang
    dibaca nama hanya karena aturan konteks (やっぱり歩くんだ, まさか歩くんか) tidak dihitung.
    Dipakai ``pipeline.Translator`` untuk entri satu kanji yang juga batang kata kerja.
    """
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    counts: Counter[str] = Counter()
    for match in _HONORIFIC_RE.finditer(text):
        hon = match["hon"]
        if not honorific_fits(hon, text, match.end()) or _is_exception(
                text, match.start(), match.end()):
            continue
        after = text[match.end():match.end() + VERB_CONTEXT_CHARS]
        before = text[max(0, match.start() - VERB_CONTEXT_CHARS):match.start()]
        if honorific_proves_name(match["name"], hon, before, after):
            counts[match["name"]] += 1
    return counts


def merge_aliases(cands: Iterable[Candidate]) -> list[Candidate]:
    """Gabungkan alias sejati dan tautkan nama keluarga dengan nama lengkap.

    - Tulisan dengan ``search_key`` sama (ｱﾘｽ dan アリス) digabung menjadi satu
      kandidat; tulisan lain dicatat sebagai bukti ``alias:...`` dan menjadi
      ``GlossaryEntry.aliases``.
    - PERSON yang merupakan awalan atau akhiran PERSON lain (田中 / 太郎 dan
      田中太郎) **tetap kandidat terpisah**, karena alias glosarium dirender
      identik: menggabungkannya akan membuat 田中さん tampil sebagai
      "Tanaka Tarō-san". Keduanya hanya ditautkan lewat bukti, dan bacaan
      bagian itu diturunkan dari bacaan nama lengkap bila bacaan itu
      berspasi (``たなか たろう`` → 田中 ``たなか``, 太郎 ``たろう``).

    Args:
        cands: Kandidat hasil deteksi (tidak diubah).

    Returns:
        Daftar kandidat baru terurut dari skor tertinggi.
    """
    merged: dict[str, Candidate] = {}
    for cand in sorted(cands, key=_rank):
        key = search_key(cand.surface)
        main = merged.get(key)
        if main is None:
            merged[key] = replace(cand, evidence=list(cand.evidence))
            continue
        main.count += cand.count
        main.reading = main.reading or cand.reading
        main.evidence.append(f"{ALIAS_TAG}{cand.surface}")
    people = [cand for cand in merged.values() if cand.kind == PERSON]
    for short in people:
        for full in people:
            if full is short:
                continue
            if full.surface.startswith(short.surface):
                _link_part(short, full, given=False)
            elif full.surface.endswith(short.surface):
                _link_part(short, full, given=True)
    return sorted(merged.values(), key=_rank)


def candidates_to_entries(
    cands: Iterable[Candidate], cfg: Config
) -> tuple[list[GlossaryEntry], list[GlossaryEntry]]:
    """Ubah kandidat menjadi entri glosarium menurut ambang di ``cfg``.

    Args:
        cands: Kandidat dari ``detect_entities``.
        cfg: Konfigurasi (``auto_lock_threshold``, ``candidate_threshold``).

    Returns:
        Pasangan (entri terkunci ``confirmed=True``, entri untuk ditinjau
        ``confirmed=False``), keduanya ``source="auto"``. Kandidat di bawah
        ``candidate_threshold`` dibuang.
    """
    locked: list[GlossaryEntry] = []
    review: list[GlossaryEntry] = []
    for cand in cands:
        if cand.score >= cfg.auto_lock_threshold:
            locked.append(_to_entry(cand, confirmed=True))
        elif cand.score >= cfg.candidate_threshold:
            review.append(_to_entry(cand, confirmed=False))
    return locked, review


def _absorb_all(found: dict[str, _Found], signals: Iterable[_Signal]) -> None:
    """Masukkan semua sinyal ke tabel ``found``."""
    for signal in signals:
        item = found.get(signal.surface)
        if item is None:
            found[signal.surface] = item = _Found(
                signal.kind, signal.score, signal.frequency_bonus
            )
        item.absorb(signal)


def _honorific_signals(text: str, named: frozenset[str] = frozenset()) -> Iterator[_Signal]:
    """T2: nama kanji atau katakana 2+ huruf yang diikuti honorifik.

    ``named`` adalah tulisan yang terbukti nama di dokumen ini (``attested_names``).
    """
    surnames = data.surnames()
    for match in _HONORIFIC_RE.finditer(text):
        hon = match["hon"]
        if not honorific_fits(hon, text, match.end()) or _is_exception(
                text, match.start(), match.end()):
            continue
        if match.start() > 0 and text[match.start() - 1] in POLITE_PREFIXES \
                and match["name"] not in surnames:
            continue  # お隣さん, ご苦労様: kata biasa berawalan sopan, bukan nama
        before = text[max(0, match.start() - VERB_CONTEXT_CHARS):match.start()]
        after = text[match.end():match.end() + VERB_AFTER_CHARS]
        if _verb_ending(match["name"], hon, after, before, named):
            continue  # 行くんですか, 駅まで歩くんですか, 許さんと言った: kata kerja + ん
        name = _person_part(match["name"], surnames)
        if name is None or _is_not_name(name):
            continue
        yield _Signal(name, PERSON, SCORE_HONORIFIC, f"honorifik:{hon}", surnames.get(name, ""))


def _title_signals(text: str) -> Iterator[_Signal]:
    """T2: nama yang diikuti gelar jabatan (佐藤部長, 佐藤恒治社長, エリザ王女).

    Run kanji hanya diterima bila diawali nama keluarga yang dikenal, karena
    gelar juga mengikuti kata biasa (営業部長, 副社長). Tempat bawaan + sufiks
    tempat (千葉県知事, 広島県知事) bukan nama walau 千葉/広島 juga nama keluarga.
    """
    surnames = data.surnames()
    for match in _TITLE_RE.finditer(text):
        name = match["name"]
        if _KANJI_CHAR_RE.match(name) and not (name in surnames or _starts_with_surname(name)):
            continue
        if _is_builtin_place_with_suffix(name):
            continue
        if _is_not_name(name):
            continue
        yield _Signal(name, PERSON, SCORE_TITLE, f"gelar:{match['title']}",
                      surnames.get(name, ""))


def _speaker_signals(paragraphs: Iterable[str]) -> Iterator[_Signal]:
    """T2: baris naskah ``名前「…」`` atau ``名前：「…」``."""
    for paragraph in paragraphs:
        match = _SPEAKER_RE.match(paragraph)
        if match and not _is_not_name(match["name"]):
            yield _Signal(match["name"], PERSON, SCORE_SPEAKER, "pembicara")


def _suffix_signals(text: str, skip: set[str]) -> Iterator[_Signal]:
    """T2: tulisan + sufiks tempat (PLACE) atau organisasi (ORG).

    Kandidatnya tulisan utuh (吉祥寺駅). Bila bagian depannya sudah dikenal
    (東京駅 dengan 東京 di glosarium atau tempat bawaan), tidak ada kandidat
    baru: ``protect.EntityMatcher`` sudah menangani 東京 + sufiks 駅.

    Kota yang menempel langsung setelah 都道府県 (愛知県刈谷市) tidak tertangkap
    pola biasa karena didahului kanji, jadi dicari dengan ``_ADMIN_CHILD_RE``.
    Bila kotanya sudah dikenal (豊田), ``protect`` merangkai alamatnya sendiri.
    Kata umum (都内各区, 県第一区, 地区, 選挙区) tidak menjadi kandidat.
    """
    for match in _ADMIN_CHILD_RE.finditer(text):
        base, surface = match["base"], match.group()
        if base in skip or base[0] in NOT_MUNICIPALITY_STARTS \
                or surface.endswith(GENERIC_MUNICIPALITY_WORDS) \
                or _unit_inside_city_name(text, match.start(), skip):
            continue
        yield _Signal(surface, PLACE, SCORE_PLACE, f"sufiks:{match['suf']}:alamat")
    for pattern, kind, score in ((_PLACE_RE, PLACE, SCORE_PLACE), (_ORG_RE, ORG, SCORE_ORG)):
        for match in pattern.finditer(text):
            base, surface = match["base"], match.group()
            if kind == PLACE:
                if is_time_word_place(_counter_before(text, match.start()) + surface):
                    continue
                base = _without_time_word(base)
                surface = surface[len(surface) - len(base) - len(match["suf"]):]
            if not base or base in skip or _is_common_katakana(base) \
                    or surface in GENERIC_COMPOUNDS or _starts_with_known_admin_unit(base, skip):
                continue
            yield _Signal(surface, kind, score, f"sufiks:{match['suf']}")


def _counter_before(text: str, start: int) -> str:
    """Angka + か/ヶ tepat sebelum ``start`` (三か, 二ヶ), atau kosong (``_COUNTER_BEFORE_RE``).

    Huruf か/ヶ bukan kanji, jadi pola tempat bisa mulai di 月 (三か月後駅 → 月後駅); dengan awalan
    ini kandidat dikenali sebagai lama waktu (``is_time_word_place``).
    """
    found = _COUNTER_BEFORE_RE.search(text, max(0, start - 8), start)
    return found.group() if found is not None else ""


def _without_time_word(base: str) -> str:
    """``base`` tanpa kata waktu di depannya (``_time_word_prefix``): 毎日 dari 毎日駅 (kosong, bukan
    stasiun), 明日 dari 明日吉祥寺駅 (吉祥寺), 毎週末 dari 毎週末吉祥寺駅. Kata keterangan waktu
    tanpa partikel lazim menempel ke tempat tujuan (毎日駅まで歩く) dan bukan bagian nama tempat.

    Bila yang tersisa hanya satu huruf, kata waktu itu bagian nama tempat (明日香村, bukan
    明日 + 香村), jadi ``base`` dikembalikan utuh, kecuali huruf itu kanji waktu
    (``TIME_TAIL_KANJI``: 明日朝駅, 昨日夜駅), yang menghasilkan kosong.
    """
    prefix = _time_word_prefix(base)
    rest = base[len(prefix):]
    if prefix and rest in TIME_TAIL_KANJI:
        return ""
    return base if len(rest) == 1 else rest


def _time_word_prefix(base: str) -> str:
    """Deretan kata waktu di awal ``base`` (毎週 + 土曜日, 来週 + 月曜日), atau kosong.

    Tiap kata adalah yang terpanjang dari ``TIME_PREFIXES``, nama hari (``_WEEKDAY_RE``), atau
    lama waktu berangka (``_DURATION_RE``: 三日前, 二週間後).
    """
    end = 0
    while end < len(base):
        found = _WEEKDAY_RE.match(base, end) or _DURATION_RE.match(base, end)
        word = found.group() if found is not None else next(
            (word for word in _TIME_WORDS_LONGEST if base.startswith(word, end)), "")
        if not word:
            break
        end += len(word)
    return base[:end]


def is_time_word_place(surface: str) -> bool:
    """Apakah ``surface`` hanya kata waktu (boleh + kanji waktu) + sufiks tempat (毎日駅, 来週駅,
    日曜日駅, 今日町, 明日朝駅).

    Tulisan seperti itu bukan nama tempat: kata keterangan waktu tanpa partikel yang menempel
    ke sufiks (毎日駅まで走る = "setiap hari sampai stasiun"). Dipakai deteksi entitas (lewat
    ``_without_time_word``) dan ``pipeline.masking_map`` untuk entri otomatis lama. 新宿駅,
    明日香村, dan 駅 saja bukan.
    """
    for suffix in sorted(PLACE_SUFFIXES + FACILITY_WORDS, key=len, reverse=True):
        base = surface[:-len(suffix)]
        if surface.endswith(suffix) and base:
            prefix = _time_word_prefix(base)
            return bool(prefix) and (prefix == base or base[len(prefix):] in TIME_TAIL_KANJI)
    return False


def _unit_inside_city_name(text: str, start: int, skip: set[str]) -> bool:
    """Huruf 都道府県 sebelum ``start`` adalah awal nama kota, bukan unit wilayah.

    東京都府中市: 府 didahului 東京都 (tempat dikenal + unit wilayah), jadi 府 adalah
    huruf pertama 府中, bukan sufiks prefektur; kandidat ``中市`` palsu. 京都府京田辺市
    tetap diterima karena di depan 都 hanya ada 京, bukan tempat dikenal.
    """
    before = start - 2
    if before < 0 or text[before] not in ADMIN_UNIT_CHARS[:4]:
        return False
    return any(text[max(0, before - size):before] in skip for size in range(1, 5))


def _starts_with_known_admin_unit(base: str, skip: set[str]) -> bool:
    """Awal ``base`` adalah tempat dikenal + 都/道/府/県 (東京都港 dari 東京都港区).

    Kandidat seperti ``東京都港区`` menutupi 東京 di masking (kecocokan terpanjang
    yang ditolak tidak jatuh ke entri pendek), sehingga alamat keluar setengah
    Latin (``東京都Distrik Minato``). Kotanya sudah ditangkap ``_ADMIN_CHILD_RE``
    (``港区``) dan protect merangkai alamatnya sendiri.
    """
    return any(ch in ADMIN_UNIT_CHARS[:4] and base[:index] in skip
               for index, ch in enumerate(base) if index)


def _katakana_signals(text: str, skip: Container[str] = frozenset()) -> Iterator[_Signal]:
    """T2: kata katakana utuh yang bukan kata serapan umum atau onomatope.

    Ekor ー teriakan dibuang dulu (``_shout_base``): リンーー menjadi リン, dan ハルトー menjadi
    ハルト bila ハルト sudah dikenal (``skip``) atau muncul tanpa ー di teks yang sama
    (ハルトーっ！ ... ハルトが来た), agar teriakan tidak menjadi entri sampah.
    """
    found = [match.group() for match in KATAKANA_RUN_RE.finditer(text)
             if match.start() == 0 or not _KATAKANA_WORD_RE.match(text[match.start() - 1])]
    plain = frozenset(run for run in found if not run.endswith(tuple(SHOUT_MARKS)))
    runs = Counter(_shout_base(run, skip, plain) for run in found)
    foreign = data.foreign_names()
    for run, count in runs.items():
        if _is_common_katakana(run):
            continue
        parts = [p for p in search_key(run).split("・") if p]
        if parts and all(part in foreign for part in parts):
            yield _Signal(run, PERSON, SCORE_FOREIGN_NAME, f"nama-asing×{count}")
            continue
        repeat = KATAKANA_REPEAT_BONUS * min(count - 1, KATAKANA_REPEAT_LIMIT)
        yield _Signal(run, TERM, SCORE_KATAKANA + repeat, f"katakana×{count}",
                      frequency_bonus=False)


def _shout_base(run: str, skip: Container[str], plain: Container[str] = frozenset()) -> str:
    """Run katakana tanpa ekor ー teriakan (``SHOUT_MARKS``), bila ekor itu memang teriakan.

    Dua ー atau lebih selalu teriakan (リンーー → リン). Satu ー hanya dibuang bila tulisan
    dasarnya sudah dikenal (``skip``) atau muncul tanpa ー di dokumen yang sama (``plain``):
    ハルトー → ハルト. Kata seperti メーカー atau nama マリー tetap utuh.
    """
    base = run.rstrip(SHOUT_MARKS)
    tail = len(run) - len(base)
    if len(base) < 2 or not tail:
        return run
    return base if tail >= 2 or base in skip or base in plain else run


def _ruby_signals(ruby: Mapping[str, str], named: set[str]) -> Iterator[_Signal]:
    """T1: pasangan furigana dengan tulisan berkanji.

    Bacaan katakana di atas kanji (本気《マジ》) adalah gloss, bukan bacaan;
    bacaan hiragana tanpa sinyal nama bisa saja kata sulit biasa. Ruby batang kata kerja satu
    kanji yang hanya bacaan batang itu (咲《さ》, 歩《ある》; ``_ruby_attests``) dilewati: itu
    bacaan sebagian kata kerja, bukan kata.
    """
    for base, reading in ruby.items():
        if not _KANJI_CHAR_RE.search(base) or not reading:
            continue
        if is_hiragana_text(reading) and not _ruby_attests(base, reading):
            continue
        if _KATAKANA_WORD_RE.fullmatch(reading):
            yield _Signal(base, TERM, SCORE_RUBY_GLOSS, f"ruby-gloss:{reading}",
                          frequency_bonus=False)
        elif base in named:
            yield _Signal(base, PERSON, SCORE_RUBY_NAME, "ruby", reading)
        else:
            yield _Signal(base, _kind_by_suffix(base), SCORE_RUBY_PLAIN, "ruby", reading,
                          frequency_bonus=False)


def _apply_janome(found: dict[str, _Found], text: str) -> None:
    """T3 opsional: tambah skor tulisan yang ditandai Janome sebagai nama diri."""
    for surface, kind in sorted(set(_janome_proper_nouns(text))):
        item = found.get(surface)
        if item is None:
            found[surface] = item = _Found(kind, SCORE_JANOME_ONLY, frequency_bonus=True)
        else:
            item.extra = JANOME_BONUS
        item.evidence.append(f"janome:{kind}")


def _janome_proper_nouns(text: str) -> list[tuple[str, str]]:
    """Daftar (tulisan, jenis) untuk token ``名詞,固有名詞,人名/地域/組織``.

    Returns:
        Daftar kosong bila Janome tidak terpasang.
    """
    try:
        from janome.tokenizer import Tokenizer
    except ImportError:
        logger.info("Janome tidak terpasang; tingkat T3 dilewati")
        return []
    nouns = []
    for token in Tokenizer().tokenize(text):
        pos = token.part_of_speech.split(",")
        if pos[:2] == ["名詞", "固有名詞"] and len(pos) > 2 and pos[2] in JANOME_KINDS:
            nouns.append((token.surface, JANOME_KINDS[pos[2]]))
    return nouns


def _finalize(surface: str, item: _Found, text: str, ruby: Mapping[str, str]) -> Candidate:
    """Hitung skor akhir dan bacaan; bacaan ruby mengalahkan bacaan surnames.json."""
    count = max(text.count(surface), 1)
    bonus = min(FREQUENCY_BONUS * (count - 1), FREQUENCY_BONUS_MAX)
    if not item.frequency_bonus:
        bonus = 0.0
    score = min(round(item.score + bonus + item.extra, 4), SCORE_MAX)
    reading = _hiragana_reading(ruby.get(surface, "")) or item.reading
    if item.kind == PERSON:
        reading = split_family_reading(surface, reading)
    return Candidate(surface, item.kind, score, reading, count, list(item.evidence))


def _hiragana_reading(reading: str) -> str:
    """Bacaan ruby hanya dipakai bila berupa hiragana (bukan gloss katakana)."""
    return reading if is_hiragana_text(reading) else ""


def _is_not_name(name: str) -> bool:
    """Kata umum, gelar, kekerabatan, pekerjaan, kata serapan katakana, atau kata waktu.

    Kata waktu ``TIME_PREFIXES`` yang bukan nama dikenal (毎朝ちゃんと磨くんだ: 毎朝 + ちゃんと
    kata keterangan, bukan "Maiasa-chan") tidak pernah nama orang.
    """
    if name in NOT_NAMES or _is_common_katakana(name):
        return True
    if name in TIME_PREFIXES and not is_known_name(name):
        return True
    return name.endswith(OCCUPATION_ENDINGS) and name not in data.surnames()


def _verb_ending(run: str, hon: str, after: str, before: str, named: frozenset[str]) -> bool:
    """Run kanji + honorifik yang sebenarnya kata kerja + okurigana + ん.

    ``style.verb_run_before_honorific`` dengan ``NOT_NAMES`` sebagai awalan bukan nama:
    行くんですか, 駅まで歩くんですか, 明日行くん, dan kata waktu/tempat + 行くんだ
    (来週行くんだ) bukan nama; partikel nama sesudah honorifik (雅行くんが, 開くんが), posisi
    panggilan/atributif (おい、乾くん！, 弟の歩くんです), dan nama dua kanji (大輝くんです)
    membuatnya tetap nama.
    """
    return verb_run_before_honorific(run, hon, after, NOT_NAMES, before=before, named=named)


def _person_part(name: str, surnames: Mapping[str, str]) -> str | None:
    """Bagian nama orang dari run sebelum honorifik, atau ``None`` bila bukan nama."""
    if not _KANJI_CHAR_RE.match(name) or name in surnames or _starts_with_surname(name):
        return name
    given = data.given_names()
    if name in given:
        return name
    for idx in range(1, len(name)):
        tail = name[idx:]
        if tail in surnames or (
            len(tail) >= 2 and tail in given and not ambiguous_given_name(tail)
        ):
            return tail
    return name if len(name) <= MAX_PLAIN_KANJI_NAME else None


def _starts_with_surname(name: str) -> bool:
    """Run kanji diawali nama keluarga yang sah (lihat ``names.has_surname_head``)."""
    return has_surname_head(name)


def _is_builtin_place_with_suffix(name: str) -> bool:
    """Tempat bawaan diikuti sufiks tempat (千葉県, 広島市): bukan nama orang."""
    places = data.places()
    return any(
        name.endswith(suffix) and name[:-len(suffix)] in places for suffix in PLACE_SUFFIXES
    )


def _is_exception(text: str, start: int, end: int) -> bool:
    """Kecocokan ``text[start:end]`` adalah ekor frasa di ``HONORIFIC_EXCEPTIONS``."""
    return any(
        end - start <= len(phrase) <= end and text.startswith(phrase, end - len(phrase))
        for phrase in HONORIFIC_EXCEPTIONS
    )


def _is_common_katakana(word: str) -> bool:
    """Kata serapan, gabungan kata serapan (モンスターハウス), atau onomatope."""
    key = search_key(word).replace("・", "")
    if not _KATAKANA_WORD_RE.fullmatch(key):
        return False
    words = data.loanwords()
    return key in words or _is_loanword_compound(key, words) or _looks_like_sfx(key)


def _is_loanword_compound(word: str, words: frozenset[str]) -> bool:
    """Apakah ``word`` bisa dipecah habis menjadi kata-kata serapan (DP sederhana)."""
    reachable = [True] + [False] * len(word)
    for start in range(len(word)):
        if reachable[start]:
            for end in range(start + 2, len(word) + 1):
                if word[start:end] in words:
                    reachable[end] = True
    return reachable[-1]


def _looks_like_sfx(word: str) -> bool:
    """Onomatope: pengulangan (ドキドキ), satu huruf berulang (ゴゴゴ), atau berakhir ッ."""
    if word.endswith("ッ"):
        return True
    core = word.replace("ー", "")
    half = len(core) // 2
    repeated = len(core) >= 4 and len(core) % 2 == 0 and core[:half] == core[half:]
    return repeated or len(set(core)) == 1


def _kind_by_suffix(surface: str) -> str:
    """Tebak jenis dari sufiks: tempat, organisasi, atau orang."""
    if surface.endswith(PLACE_SUFFIXES):
        return PLACE
    if surface.endswith(ORG_SUFFIXES):
        return ORG
    return PERSON


def _link_part(short: Candidate, full: Candidate, *, given: bool) -> None:
    """Tautkan nama keluarga atau nama depan dengan nama lengkap tanpa menggabungkan rendernya.

    Bacaan bagian itu diturunkan dari bacaan nama lengkap yang berspasi:
    ``かんざき ゆうま`` memberi 神崎 → かんざき dan 悠真 → ゆうま.
    """
    parts = full.reading.split()
    if not short.reading and len(parts) >= 2:
        short.reading = parts[1 if given else 0]
    note = f"bagian-dari:{full.surface}"
    if note not in short.evidence:
        short.evidence.append(note)


def _rank(cand: Candidate) -> tuple[float, int, str]:
    """Urutan: skor tertinggi, lalu paling sering, lalu tulisan."""
    return (-cand.score, -cand.count, cand.surface)


def _to_entry(cand: Candidate, *, confirmed: bool) -> GlossaryEntry:
    """Bangun entri glosarium otomatis dari kandidat."""
    aliases = tuple(e[len(ALIAS_TAG):] for e in cand.evidence if e.startswith(ALIAS_TAG))
    return GlossaryEntry(
        surface=cand.surface,
        kind=cand.kind,
        reading=kata_to_hira(cand.reading),
        aliases=aliases,
        confirmed=confirmed,
        source="auto",
        score=cand.score,
    )
