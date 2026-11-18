"""Disambiguasi konteks kata kerja + ん terhadap nama diri + honorifik.

Membedakan run kanji sebelum honorifik (``歩くんだ``, ``許さん``, ``来たんです``)
dari nama orang berhonorifik (``歩くん``, ``治さん``) berdasarkan tabel konteks
kiri/kanan ``VERB_CONTEXT_TABLE`` serta daftar kata peran, benda, dan sapaan.
"""

from __future__ import annotations

import logging
import re

from . import data
from .models import ORG, PLACE
from .textnorm import KANJI, KANJI_RE, KATAKANA, is_hiragana, is_kanji, is_katakana

logger = logging.getLogger(__name__)

HONORIFIC_SURFACES: dict[str, str] = {
    "さん": "san", "くん": "kun", "君": "kun", "ちゃん": "chan",
    "様": "sama", "さま": "sama", "先輩": "senpai", "先生": "sensei",
    "殿": "dono", "氏": "shi", "たん": "tan", "っち": "cchi",
}
"""Tulisan honorifik Jepang → kunci romaji yang disimpan di ``Slot.honorific``."""

# Templat sufiks: (bahasa Indonesia, bahasa Inggris); {name} = nama yang sudah dirender.
PEOPLE_SUFFIXES: dict[str, tuple[str, str]] = {
    "達": ("{name} dan yang lain", "{name} and the others"),
    "たち": ("{name} dan yang lain", "{name} and the others"),
    "ら": ("{name} dan yang lain", "{name} and the others"),
    "家": ("keluarga {name}", "the {name} family"),
    "一家": ("keluarga {name}", "the {name} family"),
}
"""Sufiks setelah nama orang: jamak dan keluarga."""

PLACE_SUFFIXES: dict[str, tuple[str, str]] = {
    "駅": ("Stasiun {name}", "{name} Station"),
    "市": ("Kota {name}", "{name} City"),
    "町": ("Kota {name}", "{name} Town"),
    "村": ("Desa {name}", "{name} Village"),
    "県": ("Prefektur {name}", "{name} Prefecture"),
    "府": ("Prefektur {name}", "{name} Prefecture"),
    "都": ("{name}", "{name}"),
    "区": ("Distrik {name}", "{name} Ward"),
    "城": ("Kastel {name}", "{name} Castle"),
    "山": ("Gunung {name}", "Mount {name}"),
    "川": ("Sungai {name}", "{name} River"),
    "島": ("Pulau {name}", "{name} Island"),
    "国": ("Negeri {name}", "Kingdom of {name}"),
    "港": ("Pelabuhan {name}", "Port of {name}"),
    "寺": ("Kuil {name}", "{name} Temple"),
    "神社": ("Kuil {name}", "{name} Shrine"),
    "学園": ("Akademi {name}", "{name} Academy"),
    "学院": ("Akademi {name}", "{name} Academy"),
    "高校": ("SMA {name}", "{name} High School"),
    "中学": ("SMP {name}", "{name} Middle School"),
    "大学": ("Universitas {name}", "{name} University"),
}
"""Sufiks jenis tempat/lembaga. 府 都 区 港 寺 神社 中学 大学 adalah tambahan di luar SPEC."""

SUFFIX_RULES: dict[str, tuple[str, str]] = {**PEOPLE_SUFFIXES, **PLACE_SUFFIXES}
"""Semua sufiks yang dikenali ``protect.EntityMatcher`` beserta templatnya."""

PLACE_KINDS = frozenset({PLACE, ORG})
"""Jenis entri yang boleh diikuti sufiks tempat (東京駅, 星見学園)."""

TITLE_WORDS: tuple[str, ...] = (
    "社長", "副社長", "部長", "課長", "係長", "会長", "店長", "校長", "教授", "博士", "刑事",
    "警部", "選手", "監督", "団長", "隊長", "艦長", "知事", "首相", "大臣", "議員", "容疑者",
    "王子", "王女", "姫", "陛下", "殿下",
)
"""Gelar/jabatan kanji yang ditulis langsung setelah nama (佐藤部長, エリザ王女).

Gelar tidak dirender ``Renderer``: ``protect`` hanya memasking namanya dan
membiarkan gelar di teks agar mesin menerjemahkannya (``Manajer [[E1]]``).
"""


NAME_PARTICLES = frozenset("がはともにをへの、，")
"""Huruf sesudah くん yang hanya mungkin untuk nama (乾くんが, 開くんと, 弾くんの番, 拓くん、).

Kata kerja + ん penjelas (行くんだ) tidak pernah langsung disusul partikel kasus atau koma."""
VERB_ENDING_FOLLOWERS = frozenset("だでじかよねぞやな")
"""Huruf sesudah ん yang khas kata kerja + ん penjelas (行くんだ, 行くんですか, 来たんじゃ, 行くんなら)."""
NEGATIVE_NAME_FOLLOWERS = frozenset("はもにをへっー")
"""Huruf sesudah さん/たん yang hanya mungkin untuk nama: negasi lisan (許さん, 待たん) boleh
disusul が, と, の？, で, atau 、 (貸さんが、, 待たんといけない), tetapi tidak disusul partikel ini."""
NEGATIVE_TAIL_RE = re.compile(
    r"ぞ|と(?:言|い[うってけか]|あか|おか)|の[？?か]|かった|で(?:ええ|いい|くれ|[！!])")
"""Ekor yang khas negasi lisan 〜さん/〜たん (bukti kuat): 許さんぞ, 許さんと言った, 話さんといて,
待たんといけない, 出さんの？, 許さんかった, 持たんでええ, 直さんでいい, 話さんでくれ, 放さんで！."""
WEAK_NEGATIVE_TAILS = ("から", "か", "よ", "で", "や", "ね", "な")
"""Ekor sesudah さん yang cocok untuk negasi lisan maupun nama (許さんから / 治さんから,
許さんよ / 直さんよ): bukti lemah, hanya berlaku untuk tulisan yang bukan nama dikenal."""
KUN_NAME_TAILS = ("から", "まで", "さえ", "しか", "ばかり", "くらい", "ぐらい", "ほど", "こそ", "より",
                  "すら", "でさえ", "ばっかり", "なんて", "なんか", "みたい", "たら")
"""Partikel sesudah くん yang hanya mungkin untuk nama (響くんから？, 弾くんまで泣いてる, 歩くんより
速い, 弾くんすら来なかった, 咲くんばっかり, 歩くんなんて呼んでた, 鳴くんたら遅い, 拓くんみたいに):
kata kerja + ん tidak pernah langsung disusul partikel ini."""
IDENTITY_SUBJECTS = (
    "これ", "それ", "あれ", "どれ", "こちら", "そちら", "あちら", "こっち", "そっち", "あっち",
    "こいつ", "そいつ", "あいつ", "この子", "その子", "あの子", "この人", "その人", "あの人", "の",
)
"""Kata penunjuk sebagai subjek/topik kalimat identitas (あれが蓮くんだ, それって乾くんじゃない？,
あの子、咲くんだよね): が/は/も/って/koma sesudahnya bukan bukti kata kerja, karena kalimatnya
menyebut siapa orang itu. ``の`` mewakili kalimat cleft 〜のは/〜のが (優勝したのは歩くんだ)."""
FIRST_PERSON_PRONOUNS = ("僕", "ぼく", "俺", "おれ", "私", "わたし", "あたし")
"""Kata ganti orang pertama: + は/も/って/koma adalah subjek kata kerja (僕は歩くんだ, 俺は渡さん！,
私は歩くんですよ), karena orang jarang menyebut dirinya dengan くん."""
PERSONAL_PRONOUNS = FIRST_PERSON_PRONOUNS + (
    "君", "きみ", "あなた", "あんた", "お前", "おまえ", "貴方", "貴様", "彼", "彼女",
)
"""Kata ganti orang. + が adalah pola identitas (君が治さんか); + も kasus (お前も歩くんだよ). + は
dan koma: orang pertama kasus, orang kedua/ketiga topik (君は歩くんだよ kata kerja untuk nama yang
hanya dikenal di data, あなたは歩くんですか nama bila 歩 sudah terbukti nama di dokumen)."""
INANIMATE_VERBS = frozenset({
    "咲く", "乾く", "響く", "鳴く", "届く", "湧く", "沸く", "効く", "噴く", "渇く", "裂く", "剥く",
})
"""Kata kerja (batang + okurigana) yang subjeknya hampir tidak pernah orang (花が咲く, 布団が乾く,
音が響く, 犬が鳴く). Kata ganti atau kata benda orang + は/が/も sebelum run seperti itu adalah
kalimat identitas (君は響くんだね？, お前は乾くんか？), bukan subjek kata kerja."""
PERSON_NOUNS = (
    "犯人", "主役", "主人公", "代表", "当番", "日直", "担任", "担当", "次", "一番", "答え", "正解", "正体",
    "名前", "相手", "本命", "彼氏", "恋人", "相棒", "走者", "勝者", "兄", "姉", "弟", "妹", "兄貴",
    "姉貴", "子", "真ん中", "キャプテン", "リーダー", "エース", "主将", "新人", "転校生",
    "人", "一人", "ひとり", "息子", "娘", "孫", "甥", "姪", "いとこ", "親友", "友達", "友人",
    "幼なじみ", "幼馴染", "同級生", "同期", "先輩", "後輩", "仲間", "隣", "席", "幹事", "司会",
    "監督", "審判", "顧問", "部長", "会長", "社長", "店長", "委員", "委員長", "議長", "係", "担当者",
    "優勝", "一位", "最後", "残り", "メンバー", "ゲスト", "ボーカル", "マネージャー", "アンカー",
    "センター", "コーチ", "パートナー", "ライバル", "ヒーロー", "ヒロイン", "キーパー",
    "ゴールキーパー", "ピッチャー", "キャッチャー", "ストライカー", "ドラマー", "ギタリスト",
    "ベーシスト", "オーナー", "スタッフ", "チャンピオン",
    "MVP", "ＭＶＰ", "先発", "控え", "補欠", "代打", "代役", "黒幕", "主犯", "後任", "前任",
    "ボス", "王子", "王様", "女王", "大将", "親分", "推し", "お目当て", "目当て", "狙い",
    "お気に入り", "相方", "スター", "アイドル", "クラスメイト", "チームメイト",
    "先生", "師匠", "鬼", "代わり", "代理", "見張り", "新入り", "書記", "会計", "先鋒", "次鋒",
    "中堅", "主砲", "守護神", "トップバッター", "主人", "本人", "少年", "少女", "青年", "人物", "大物",
    "キング", "クイーン", "プリンス", "プリンセス", "ボディーガード", "パイロット", "コック", "シェフ",
    "ナース", "ガイド", "モデル", "スパイ", "ホスト", "ルーキー", "黒子", "大黒柱", "跡取り",
)
"""Kata benda peran/orang yang, sebagai topik atau subjek, menunjuk satu orang tertentu (犯人は歩くんだ,
主役は開くんだよ, うちの兄が歩くんです, 幹事は歩くんです, 窓際の席は輝くんだよ): は/が/koma
sesudahnya adalah posisi nama. Harus kata utuh, bukan ekor kata kanji/katakana lain (帽子, 様子,
目次, 他人事). Daftar ini sengaja lebar: topik di luar daftar dibaca topik benda (ギターは弾くんだけど).
Peringkat bernomor (四番, 二番手, 三番目, 二位) dikenali lewat ``_RANK_RE``; kata dengan awalan
peran (真犯人, 副担任, 準優勝, 大本命) lewat ``ROLE_PREFIXES``."""
_RANK_RE = re.compile(r"[一二三四五六七八九十0-9０-９]+(?:番(?:手|目)?|位)$")
"""Nomor urut orang dalam tim/barisan (四番は歩くんです, 二番手は拓くんです, 二位は輝くんだ)."""
PERSON_NOUN_ENDINGS = (
    "候補", "部員", "委員長", "部長", "会長", "班長", "隊長", "団長", "選手", "者", "員", "役",
    "官", "師", "士", "友", "督", "将", "生徒", "年生", "校生", "学生", "入生", "級生", "業生",
    "主", "医", "番", "郎", "婿", "嫁", "賓", "手", "娘", "人", "代理", "係", "最下位", "長", "王",
    "謀",
)
"""Ekor kata orang yang boleh didahului kanji lain (優勝候補, 新入部員, 学級委員長, 参加者, 店員,
悪役, 教師, 弁護士, 一年生, 持ち主, 主治医, 店番, 新郎, 花婿, 主賓, 語り手, 看板娘, 差出人,
部長代理). Kata jamak (全員, 三人) dikecualikan oleh ``_PLURAL_ENDINGS``; kata benda biasa
berekor sama di ``NOT_PERSON_WORDS``."""
NOT_PERSON_WORDS = (
    "大人", "他人", "万人", "国人", "日本人", "上手", "下手", "切手", "派手", "両手", "右手", "左手", "片手",
    "交番", "順番", "民主", "自主", "空手", "勝手", "定番", "身長", "成長", "延長", "特長",
)
"""Kata berekor ``PERSON_NOUN_ENDINGS`` yang bukan satu orang tertentu (大人は歩くんだ: orang
dewasa pada umumnya, 日本人, 上手, 順番)."""
ROLE_PREFIXES = frozenset("真副新準大前元現次")
"""Awalan satu kanji yang boleh menempel ke kata ``PERSON_NOUNS`` tanpa mengubah arti "orang"
(真犯人, 副担任, 副キャプテン, 準優勝, 大本命, 新キャプテン, 前会長)."""
HONORIFIC_NOUN_TAILS = ("さん", "様", "さま", "ちゃん")
"""Honorifik yang menempel ke kata benda orang biasa (お客さん, 店員さん, 王子様, お姫様)."""
_POLITE_NOUN_RE = re.compile(f"(?:^|[^ぁ-ゖ])[おご][{KANJI}][ぁ-ゖ]?$")
"""Kata benda berawalan sopan お/ご sebelum honorifik (お客, お姫, お巡り): orang, bukan nama diri."""
THING_WORDS = (
    "花", "桜", "梅", "バラ", "窓", "扉", "ドア", "戸", "門", "蓋", "ふた", "箱", "傘", "本", "店",
    "幕", "鍵", "布団", "服", "シャツ", "セーター", "タオル", "靴", "髪", "喉", "土", "ペンキ",
    "ピアノ", "ギター", "バイオリン", "ヴァイオリン", "ベース", "チェロ", "琴", "楽器", "曲", "歌",
    "音", "声", "鐘", "ベル", "犬", "猫", "鳥", "虫", "蝉", "セミ", "カエル", "星", "月", "太陽",
    "目", "瞳", "手紙", "荷物", "金", "お金", "ネジ", "マフラー", "包帯", "時計", "電話", "スマホ",
    "携帯", "帰り", "行き", "ここ", "そこ", "あそこ", "今", "最近", "普段", "昔", "結局", "季節",
    "春", "夏", "秋", "冬", "週末", "平日", "休み", "午前", "午後", "夕方", "今朝", "今夜", "今晩",
    "夜中", "深夜", "雨", "雪", "晴れ", "土地", "癖", "病気", "勝負", "秘密", "誤字", "話",
    "宝石", "ダイヤ", "空", "海", "光", "水面", "笑顔", "未来", "雷", "太鼓", "笛", "鈴", "汗", "口",
    "チャイム", "サイレン", "アラーム", "返事", "メール", "連絡", "知らせ", "便り", "招待状",
    "手", "足", "体", "肌", "紙", "葉",
)
"""Kata benda/waktu/tempat yang lazim menjadi topik kata kerja (ギターは弾くんだけど, 洗濯物は
乾くんですか, 冬は乾くんですか, 帰りは歩くんですか, 金は渡さん): benda yang dimainkan, dibuka,
dikeringkan, berbunyi, bersinar, atau waktu/tempat. Harus kata utuh. Topik kata benda yang tidak
dikenali (bukan ``PERSON_NOUNS`` dan bukan benda) condong ke nama seperti baseline_v6."""
THING_ENDINGS = (
    "日", "曜", "朝", "昼", "夜", "晩", "時", "時間", "物", "道", "先", "年", "週", "月", "屋上",
    "器", "機", "庫", "具", "品", "剤", "薬", "料", "線", "室", "館", "場", "園", "車", "船", "布",
    "板", "瓶", "袋", "計", "灯", "球", "石", "草", "木", "魚", "川", "山", "橋", "駅", "会", "毯",
    "顔", "風", "楽", "茶", "酒", "水",
)
"""Ekor kata waktu/benda/tempat (金曜日, 雨の日, 毎朝, 十時, 洗濯物, 帰り道, ここから先, 今年,
楽器, 冷蔵庫, 三味線, 教室, 毛布, 朝顔, 教会): morfem benda, bukan daftar kata utuh."""
DEMONSTRATIVES = ("この", "その", "あの", "どの", "こんな", "そんな", "あんな", "どんな")
"""Kata penunjuk + kata benda bukan orang (この扉, その傘, あの店): benda tertentu, topik kata
kerja (この扉は開くんですか). Kata penunjuk + orang (この子, あの人) tetap ``IDENTITY_SUBJECTS``."""
GROUP_TOPICS = ("の", "メンバー", "二人", "ふたり", "代表", "候補", "当番", "犯人", "ペア", "コンビ")
"""Topik (sebelum は) yang menyebut sekelompok orang: ``topik は A と`` + run sesudahnya adalah daftar
nama (来たのは私と歩くんです, メンバーは僕と響くんだ), bukan と komitatif (友達と歩くんだ). ``の``
mewakili kalimat cleft 〜のは. Topik peran lain (``_person_head``: 主役は私と, 優勝は姉と) juga
daftar nama, kecuali ``ORDER_TOPICS``."""
AGENT_TOPICS = (
    "次", "最後", "最初", "今度", "一番", "兄", "姉", "弟", "妹", "兄貴", "姉貴", "息子", "娘", "孫",
    "甥", "姪", "いとこ", "親友", "友達", "友人", "幼なじみ", "幼馴染", "同級生", "同期", "先輩",
    "後輩", "仲間", "彼氏", "恋人", "相棒", "相方", "人", "一人", "ひとり", "子", "隣", "新人",
    "転校生", "クラスメイト", "チームメイト",
)
"""Topik yang, walau ada di ``PERSON_NOUNS``, bukan "posisi" yang diisi daftar nama: kata urutan
yang lazim berarti "berikutnya/akhirnya" (次は友達と歩くんだ) dan orang yang bertindak sendiri
(兄は友達と歩くんだ "kakak berjalan dengan teman"). + と sesudahnya tetap komitatif, sedangkan
topik posisi (主役は私と響くんです, 優勝は姉と輝くんでした) daftar nama."""
COMMON_HONORIFIC_WORDS = (
    "兄", "姉", "母", "父", "赤", "坊", "嬢", "奥", "客", "婆", "爺", "皆", "叔父", "叔母", "伯父",
    "伯母", "店員", "運転手",
)
"""Kata benda biasa yang lazim memakai honorifik (お兄ちゃん, お母さん, 赤ちゃん, 皆さん): + と/や
bukan perangkai nama (お兄ちゃんと歩くんだ kata kerja)."""
VOCATIVE_WORDS = TITLE_WORDS + ("先生", "先輩", "後輩", "師匠", "コーチ")
"""Gelar sapaan sebelum koma (先生、 部長、): yang menyusul adalah panggilan atau kalimat baru."""
INTERJECTIONS = ("おい", "ほら", "ねえ", "ねぇ", "なあ", "やあ", "ああ", "あれ", "あれっ", "えっ", "あっ",
                 "よし", "もしもし")
"""Seruan yang lazim tepat sebelum nama panggilan tanpa koma (ほら乾くんだよ)."""
GREETINGS = ("おはよう", "ありがとう", "こんにちは", "こんばんは", "さようなら", "ごめん", "おかえり",
             "ただいま", "おめでとう", "よろしく")
"""Salam yang lazim tepat sebelum nama panggilan tanpa koma (おはよう歩くん！)."""
SENTENCE_WORDS = INTERJECTIONS + GREETINGS + (
    "やはり", "やっぱり", "やっぱ", "まさか", "さすが", "なんだ", "そうだ", "また", "もしかして",
    "本当に", "ほんとに", "実は", "やっと", "ついに", "結局", "たぶん", "多分", "じゃあ", "では",
    "ところで", "それなら", "そういえば", "例えば", "たとえば",
)
"""Kata keterangan kalimat, seruan, dan salam yang berdiri sendiri (didahului awal teks atau
tanda baca) tepat sebelum run: posisi nama (やっぱり乾くんだ, まさか弾くんか, なんだ治さんか,
また開くんか, それなら直さんでもいい). Pengecualian: kata itu didahului benda + koma
(あの犬、本当に歩くんだね): benda itu topik yang partikelnya dilesapkan, jadi kata kerja."""
CONJUNCTIONS = ("それで", "そして", "でも", "だから", "しかし", "それに", "それから", "だけど",
                "けど", "けれど", "なのに")
"""Kata sambung antarklausa yang berdiri sendiri: yang menyusul lazimnya predikat klausa berikutnya
(だから歩くんだ, でも歩くんでしょ？, それで歩くんですか？), jadi dinilai topik (kata kerja kecuali
tulisannya terbukti nama di dokumen ini)."""
MANNER_WORDS = (
    "ちゃんと", "きちんと", "わざと", "っと", "まだ", "もう", "すぐ", "しっかり", "ゆっくり",
    "いつも", "なぜ", "どうして", "なんで", "いつ", "どこ", "どう", "たくさん", "いっぱい", "また",
    "必ず", "ただ", "誰も", "何も", "どれも",
)
"""Kata keterangan cara/waktu/jumlah dan kata tanya yang hanya menerangkan kata kerja (よく歩くんだ,
まだ待たんといけない, なぜ泣くんだ, たくさん歩くんだって, いっぱい咲くんだよ, 必ず輝くんだ, 誰も
通さん; ``っと`` mewakili ずっと, もっと, そっと, じっと, きっと). Kata berakhiran く (強く, 早く)
diperlakukan sama. ``また`` yang berdiri sendiri tetap ``SENTENCE_WORDS``."""
EPISTEMIC_WORDS = ("きっと", "たぶん", "やっぱり", "おそらく", "絶対に", "もしかして", "もしかしたら",
                   "まさか", "間違いなく")
"""Kata keterangan dugaan yang sesudah topik peran tetap posisi nama (犯人はきっと咲くんだ,
犯人はもしかして歩くん？, 犯人は間違いなく弾くんだよ). ``人`` umum (努力した人はきっと輝くんです:
orang pada umumnya) bukan topik peran di sini."""
TE_FORM_STEMS = frozenset("歌笑黙待持立走帰戻座祈願迷叫使払洗拾習誘張踊怒取作送守通言会思酔")
"""Kanji kata kerja yang bentuk -te-nya kanji + って (歌って, 笑って, 頑張って): って sesudahnya
bentuk て, jadi run berikutnya predikat (歌って歩くんだ, kasus). Sesudah kanji lain って adalah
penanda topik (窓って, 犯人って)."""
EVEN_QUOTE_HEADS = ("言", "い", "聞", "思", "知", "分", "わか", "話", "書", "信", "決", "噂", "こと",
                    "の", "よ", "ね", "さ", "ば")
"""Awal kata sesudah 〜くんだって yang menandai kutipan/kabar (歩くんだって言ってた, 輝くんだって
信じてる): kata kerja + ん + だって. Kata lain sesudahnya berarti "bahkan X" (歩くんだって疲れる)."""
_ATTRIBUTIVE_RE = re.compile(f"[{KANJI}ぁ-ゖ]い$")
"""Adjektiva -i atributif tepat sebelum run (強い輝くん, 優しい響くん): menerangkan kata benda
(nama), karena adjektiva tidak menerangkan kata kerja dalam bentuk -i. Kata ``NOT_ATTRIBUTIVE``
(ない/たい, くらい, いっぱい, seruan おい/はい) dikecualikan."""
NOT_ATTRIBUTIVE = ("ない", "たい", "くらい", "ぐらい", "いっぱい", "おい", "はい", "せい", "みたい")
_MIMETIC_RE = re.compile(
    r"(?:([ぁ-ゖ]{2})\1|([ァ-ヺ]{2})\2|[ぁ-ゖ][っん][ぁ-ゖ]り|[ァ-ヺ][ッン][ァ-ヺ]リ)$")
"""Onomatope/mimetik cara (とぼとぼ, ふらふら, キラキラ, のんびり, ゆっくり): keterangan kata kerja."""
_QUANTITY_RE = re.compile(
    r"[一二三四五六七八九十百千万何数半〇0-9０-９]+"
    r"(?:(?:円|歩|時間|日|回|度|個|本|枚|杯|分|秒|年|週間|か月|ヶ月|キロ|晩|滴|口|言|つ)[はも]|人も)$")
"""Bilangan + satuan + は/も (一円も, 一歩も, 一時間は, 一日も, 一人も): keterangan jumlah kata kerja
(一円も渡さん, 一日も保たん, 一人も通さん). 一番 (peringkat) dan 一人は (orang tertentu: 残りの
一人は咲くんだ) tidak termasuk."""
_PLURAL_ENDINGS = ("たち", "達", "ら", "ども", "全員", "みんな", "皆")
"""Akhiran jamak: subjek jamak (子どもたちが, 僕らが, 全員が) tidak pernah identitas satu nama."""
_PLURAL_PEOPLE_RE = re.compile(r"[二三四五六七八九十百何数0-9０-９]人$")
"""Bilangan orang lebih dari satu (三人は): jamak, bukan identitas satu nama."""
_CONJUNCTIVE_RE = re.compile(
    r"(?:なら|たら|だら|れば|けば|げば|せば|てば|ねば|べば|めば|えば|から|ので|のに|けど|けれど|"
    r"けれども|ても|でも|[うくぐすつぬぶむる]と|ないと)$")
"""Akhir anak kalimat kondisional/alasan/konsesif sebelum koma (傘がないなら、 雨がやんだら、
いいから、 疲れたけど、): run sesudah koma adalah predikat klausa utama (kata kerja), bukan
panggilan. Kata sambung yang berdiri sendiri (だから、 でも、 そういえば、) tetap ``SENTENCE_WORDS``."""
_FINAL_PARTICLES = frozenset("よねぞぜわ")
"""Partikel akhir kalimat tanpa tanda baca (待ってよ治さん！): run sesudahnya awal klausa baru."""
_CASE_TAILS = ("には", "では", "へは", "からは", "までは", "だけは", "にも", "でも", "ても", "へも",
               "ながら", "まま", "なら",
               "まで", "から", "より", "だけ", "ほど", "こそ", "しか", "さえ", "じゃ", "たら", "ば",
               "を", "に", "へ", "で")
_TOPIC_TAILS = ("って", "とは", "は")
_NOMINAL_NO = ("そんなの", "こんなの", "あんなの", "どんなの")
_REVEAL_CLAUSES = ("と思えば", "と思ったら")
"""Klausa "ternyata" (誰かと思えば乾くんか): yang menyusul adalah orang yang ditemukan, jadi panggilan."""
_COMMAS = frozenset("、，,")
_THING_TOPIC_RE = re.compile(f"[{KANJI}{KATAKANA}]は")
_TRAILING_WORD_RE = re.compile(f"[{KANJI}{KATAKANA}]+$")
VERB_CONTEXT_CHARS = 8
"""Jumlah huruf sebelum dan sesudah honorifik yang diberikan pemanggil (``ner``, ``protect``)
ke ``verb_run_before_honorific``; cukup untuk ekor seperti といけない dan subjek あの子は."""
VERB_AFTER_CHARS = 16
"""Jumlah huruf sesudah honorifik untuk ``verb_run_before_honorific`` (``ner``, ``protect``):
lebih panjang dari ``VERB_CONTEXT_CHARS`` agar bagian kalimat terbalik yang dipindah ke belakang
terlihat utuh (``ですかね、こんな雨の中``, ``ですね、意外と早く。``). Jendela sebelum run tetap
``VERB_CONTEXT_CHARS``."""
_BREAKS = frozenset("。．.！!？?…‥ー～〜」』）)］]】、，,「『（(\"'“”‘’ \t　\r\n")
DASH_BREAKS = "-－‐–—―"
"""Tanda dialog subtitle dan tanda pisah (sama dengan ``segment.DIALOGUE_DASHES``) SEBELUM run
adalah jeda (``_before_kind``): konteks dinilai dari kata sebelum tanda itu (``道を――歩くんだ`` kasus),
dan baru menjadi batas panggilan bila sebelumnya awal teks atau tanda baca (``－歩くん？``,
``「――歩くん？``). Sesudah honorifik tanda ini tetap netral (``行くん—`` bukan akhir), agar ``行``
tidak dibaca nama."""
_BEFORE_BREAKS = _BREAKS | frozenset(DASH_BREAKS)
_INVERTED_ARGUMENT_RE = re.compile(
    r"(?:だ|です)(?:か|よ|ね)?[、，](?P<arg>[^、，。！？!?…\s]{1,5}?(?:まで|[がをへにでも]))"
    r"[。．！!？?…‥」』]")
"""Argumen yang dipindah ke belakang kalimat sesudah kopula (``咲くんだ、桜が。``,
``歩くんですか、駅まで？``): sama dengan ``桜が咲くんだ`` dan ``駅まで歩くんですか``. Argumen harus
diakhiri partikel (が を へ に で も まで; bukan は) dan tanda akhir di dalam ``VERB_CONTEXT_CHARS``
huruf sesudah honorifik."""
_COPULA_COMMA = r"(?:だ|です|じゃない)(?:よね|かね|かな|か|よ|ね|な|ぞ|わ)?[、，]"
_TRAILING_POINTED_RE = re.compile(
    _COPULA_COMMA + f"(?:この|その|あの|こんな|そんな|あんな)(?P<noun>[{KANJI}{KATAKANA}ー]+)")
"""Kopula (atau ``じゃない``) + koma + kata penunjuk + kata benda di belakang kalimat
(``開くんだよ、この箱は。``, ``咲くんじゃないよ、その花は。``): calon kalimat terbalik dengan
topik/objek yang dipindah. Apa yang mengikuti kata benda diperiksa ``_pointed_thing``. Panggilan
tanpa kopula (``開くん、この箱どう？``) tidak cocok."""
POINTED_TAILS = "はをもが。．！!？?…‥」』"
"""Huruf sesudah kata benda ``_TRAILING_POINTED_RE`` yang menutup topik/objek yang dipindah
(``この箱は。``, ``そのギターを``, ``この扉が``, ``このドア！``). ``の`` (``このクラスの``,
``この写真の子は``) menerangkan kata lain, jadi bukan topik yang dipindah."""
POINTED_TIME_NOUNS = ("時間", "時期", "季節", "時", "頃", "日", "夜", "朝", "晩", "春", "夏", "秋",
                      "冬")
"""Kata waktu yang boleh disusul に/で (``この時間になると``, ``この季節に``): keterangan waktu
kata kerja. Kata benda lain + に/で (``このクラスで一番``, ``この大会で``) tidak dihitung."""
TRAIT_NOUNS = ("声", "字", "足音", "筆跡", "顔", "写真", "後ろ姿", "背中", "匂い", "絵", "手紙")
"""Ciri yang menunjuk orang (``歩くんだね、その声は。``, ``響くんだ、この字は。``): kalimat
identifikasi, jadi run tetap nama."""
_TRAILING_OBJECT_RE = re.compile(_COPULA_COMMA + r"(?P<obj>[^、，。！？!?…\s]{1,5})を")
"""Kopula + koma + objek を di belakang (``弾くんだよ、ギターを。``, ``弾くんだよ、ピアノを毎晩。``):
kata kerja, juga bila tanda akhir jatuh di luar ``VERB_AFTER_CHARS``. Objek orang
(``私を助けてくれたのは``, ``あの子を泣かせたのは``) adalah anak kalimat cleft, bukan objek run."""
_TRAILING_MANNER_RE = re.compile(
    _COPULA_COMMA + r"(?P<adv>[^、，。！？!?…\s]{0,5}く|ちゃんと|きちんと|しっかり|ゆっくり|必ず|いつも)"
    r"(?:[。．！!？?…‥」』]|$)")
"""Kopula + koma + kata keterangan cara di belakang (``乾くんですね、意外と早く。``,
``咲くんだね、ちゃんと。``): kata kerja. Salam berakhiran く (``君が輝くんだね、よろしく。``) dan
kata keterangan kalimat (``SENTENCE_ADVERBS``: ``おそらく``, ``間違いなく``) bukan keterangan cara."""
_CLAUSE_END_RE = re.compile(r"[。．！!？?…‥」』\n]")
_IDENTITY_DENIAL_RE = re.compile(
    f"じゃ(?:ない|なく)[^、，。！？!?]{{0,3}}[、，](?P<word>[{KANJI}{KATAKANA}ー]+)")
"""Pengingkaran identitas ``〜くんじゃないよ、別人だ``: yang diingkari orang, jadi run nama."""
IDENTITY_DENIAL_WORDS = ("別人", "本人", "他人", "偽者", "偽物", "人違い", "違う人")
"""Kata sesudah ``じゃない、`` yang menandai pengingkaran identitas (selain kata benda orang)."""
SENTENCE_ADVERBS = EPISTEMIC_WORDS + ("恐らく", "多分", "確かに", "とにかく", "ともかく", "実は")
"""Kata keterangan kalimat (dugaan/penegasan) di belakang kalimat (``犯人は拓くんだよ、絶対に。``,
``あれが拓くんだよ、間違いなく。``): tidak menerangkan run, jadi bukan bukti kata kerja."""

# Jenis konteks sebelum run (``_before_kind``).
BEFORE_CALL = "panggilan"
BEFORE_TOPIC = "topik"
BEFORE_SUBJECT = "subjek"
BEFORE_CASE = "kasus"
BEFORE_WITH = "komitatif"
BEFORE_WITH_SELF = "komitatif-diri"
BEFORE_ROLE = "peran"
BEFORE_OPEN_TOPIC = "topik-terbuka"
# Jenis konteks sesudah honorifik (``_after_kind``); ``None`` berarti pasti nama.
AFTER_COPULA = "kopula"
AFTER_STRONG_NEGATIVE = "negasi-kuat"
AFTER_EXCLAMATION = "seru"
AFTER_WEAK_NEGATIVE = "negasi-lemah"
AFTER_QUESTION = "tanya"
AFTER_NEUTRAL = "netral"
AFTER_END = "akhir"
AFTER_LINK = "sambung"
AFTER_FROM = "dari"
AFTER_EVEN = "bahkan"

VERB_CONTEXT_TABLE: dict[str, dict[str, int]] = {
    BEFORE_CALL: {AFTER_COPULA: 0, AFTER_STRONG_NEGATIVE: 0, AFTER_EXCLAMATION: 0,
                  AFTER_WEAK_NEGATIVE: 0, AFTER_QUESTION: 0, AFTER_NEUTRAL: 0, AFTER_END: -1,
                  AFTER_LINK: 0, AFTER_FROM: 0, AFTER_EVEN: 0},
    BEFORE_ROLE: {AFTER_COPULA: 0, AFTER_STRONG_NEGATIVE: 2, AFTER_EXCLAMATION: 1,
                  AFTER_WEAK_NEGATIVE: 0, AFTER_QUESTION: 0, AFTER_NEUTRAL: 0, AFTER_END: -1,
                  AFTER_LINK: 0, AFTER_FROM: 0, AFTER_EVEN: 0},
    BEFORE_OPEN_TOPIC: {AFTER_COPULA: 0, AFTER_STRONG_NEGATIVE: 1, AFTER_EXCLAMATION: 1,
                        AFTER_WEAK_NEGATIVE: 1, AFTER_QUESTION: 0, AFTER_NEUTRAL: 1, AFTER_END: 0,
                        AFTER_LINK: 0, AFTER_FROM: 0, AFTER_EVEN: 0},
    BEFORE_TOPIC: {AFTER_COPULA: 1, AFTER_STRONG_NEGATIVE: 1, AFTER_EXCLAMATION: 1,
                   AFTER_WEAK_NEGATIVE: 1, AFTER_QUESTION: 0, AFTER_NEUTRAL: 1, AFTER_END: 0,
                   AFTER_LINK: 1, AFTER_FROM: 0, AFTER_EVEN: 0},
    BEFORE_SUBJECT: {AFTER_COPULA: 2, AFTER_STRONG_NEGATIVE: 1, AFTER_EXCLAMATION: 1,
                     AFTER_WEAK_NEGATIVE: 1, AFTER_QUESTION: 1, AFTER_NEUTRAL: 1, AFTER_END: 0,
                     AFTER_LINK: 2, AFTER_FROM: 0, AFTER_EVEN: 1},
    BEFORE_CASE: {AFTER_COPULA: 2, AFTER_STRONG_NEGATIVE: 2, AFTER_EXCLAMATION: 2,
                  AFTER_WEAK_NEGATIVE: 2, AFTER_QUESTION: 1, AFTER_NEUTRAL: 2, AFTER_END: 0,
                  AFTER_LINK: 2, AFTER_FROM: 0, AFTER_EVEN: 2},
    BEFORE_WITH: {AFTER_COPULA: 2, AFTER_STRONG_NEGATIVE: 2, AFTER_EXCLAMATION: 2,
                  AFTER_WEAK_NEGATIVE: 2, AFTER_QUESTION: 1, AFTER_NEUTRAL: 2, AFTER_END: 0,
                  AFTER_LINK: 2, AFTER_FROM: 0, AFTER_EVEN: 2},
    BEFORE_WITH_SELF: {AFTER_COPULA: 2, AFTER_STRONG_NEGATIVE: 2, AFTER_EXCLAMATION: 2,
                       AFTER_WEAK_NEGATIVE: 2, AFTER_QUESTION: 1, AFTER_NEUTRAL: 2, AFTER_END: 0,
                       AFTER_LINK: 0, AFTER_FROM: 0, AFTER_EVEN: 0},
}
"""Aturan konteks kata kerja + ん: konteks sebelum x konteks sesudah → tingkat nama tertinggi yang
masih dibaca kata kerja.

Tingkat nama (``_name_level``): 0 tulisan bukan nama dikenal (行, 許, 待), 1 nama di data proyek
(``is_known_name``: 歩, 咲, 治, 乾), 2 terbukti nama di dokumen ini (``named``: honorifik + partikel
nama atau ruby di dokumen yang sama). Sel bernilai ``n`` berarti kata kerja untuk tingkat 0 sampai
``n``; -1 berarti selalu nama. Jadi ``駅まで歩くんですか`` (kasus x kopula = 2) dan ``桜が咲くんだ``
(subjek benda x kopula = 2) kata kerja walau kanjinya terbukti nama, ``ギターは弾くんだけど``
(topik benda x kopula = 1) kata kerja kecuali kanjinya terbukti nama di dokumen, ``主人公は響くんです``
dan ``弟の歩くんです`` (panggilan x kopula = 0) nama, sedangkan ``行くんですか`` dan ``行くん？`` (0)
tetap kata kerja karena 行 bukan nama. Topik x tanya dan semua baris x akhir bernilai 0
(``待って――歩くん？``, ``おはよう歩くん。``, ``起きて乾くん！``): くん langsung disusul ？ atau akhir
kalimat lebih lazim untuk panggilan. Kolom ``sambung`` (くん + で + kata: ``よく歩くんで足が``
kata kerja "karena", ``俺と弾くんでバンドを`` nama) dan ``dari`` (さん + から/や + kata: ``話さんから
安心して`` kata kerja hanya untuk tingkat 0, ``治さんから聞いた`` nama) membedakan dua pola yang
dulu dianggap pasti nama. Baris ``komitatif`` (と sesudah kata benda atau kata ganti orang kedua/
ketiga: ``友達と``, ``犬と``, ``彼女と``, ``お兄ちゃんと``) sama dengan kasus, termasuk
``毎日犬と歩くんで足が`` dan ``彼女と歩くんで緊張する`` (kata kerja "karena"). Baris
``komitatif-diri`` (kata ganti orang pertama + と: ``俺と``, ``私と``) sama dengan komitatif kecuali
kolom ``sambung``: ``俺と弾くんでバンドを作った`` nama ("aku dan Dan-kun"), ``僕と歩くんだ`` kata
kerja. Baris ``peran`` (kata benda orang sebagai topik/subjek: ``犯人は``, ``幹事は``, ``うちの兄が``)
sama dengan panggilan kecuali negasi kuat dan seru: ``お前に娘は渡さんぞ`` kata kerja (topik orang
sebagai objek), ``娘は渡さん！`` kata kerja kecuali 渡 terbukti nama di dokumen, ``犯人は渡さんだ``
nama. Baris ``topik-terbuka`` (kata benda yang bukan orang dan bukan benda/waktu/tempat yang
dikenali ``thing_head``: ``主砲は``, ``真犯人は`` di luar daftar, ``代わりは``) sama dengan topik
kecuali kolom kopula, tanya, sambung: nilainya 0 seperti baris topik baseline_v6, jadi
``主砲は歩くんです`` nama, sedangkan ``金は渡さん`` dan ``勝負は勝たんと`` tetap kata kerja. Kolom
``bahkan`` (〜くんだって/〜くんでも + kata yang bukan kutipan: ``でも歩くんだって疲れる``,
``強い歩くんでも勝てない``) nama di posisi panggilan, peran, dan topik, kata kerja sesudah kasus
(``毎日歩くんだって母が``)."""


def honorific_fits(hon: str, text: str, end: int) -> bool:
    """Periksa apakah honorifik kanji benar-benar honorifik, bukan awal kata lain.

    Honorifik kanji yang langsung diikuti kanji lain adalah bagian kata baru:
    殿下 (Yang Mulia), 君子 (nama Kimiko), 様子 (keadaan), 氏名 (nama lengkap).
    Sufiks orang tetap boleh menyusul (田中君達).

    Args:
        hon: Tulisan honorifik yang cocok (boleh kosong).
        text: Teks sumber.
        end: Posisi tepat setelah honorifik.
    """
    if not hon or not is_kanji(hon[-1]) or end >= len(text) or not is_kanji(text[end]):
        return True
    return text.startswith(tuple(PEOPLE_SUFFIXES), end)


def is_known_name(word: str) -> bool:
    """Tulisan dikenal sebagai nama utuh di data proyek.

    Sumbernya ``surnames.json``, ``given_names.json``, dan ``data.name_word_readings``
    (``NAME_WORD_READINGS`` + ``name_words.json``). Satu-satunya pemeriksaan "nama dikenal"
    untuk aturan kata kerja + ん.
    """
    return (word in data.surnames() or word in data.given_names()
            or word in data.name_word_readings())


def is_verb_stem(kanji: str) -> bool:
    """Kanji tunggal ini batang kata kerja di salah satu golongan ``data.VERB_STEMS``."""
    return any(kanji in stems for stems in data.VERB_STEMS.values())


def honorific_proves_name(run: str, hon: str, before: str, after: str) -> bool:
    """Run + honorifik ini konteks nama tegas, bukan hanya condong ke nama karena aturan konteks.

    Tegas bila honorifiknya tidak mungkin okurigana kata kerja untuk kanji terakhir run (咲ちゃん,
    歩さま, 輝さん: 輝 bukan batang 〜さん di ``data.VERB_STEMS``), bila huruf sesudahnya hanya
    mungkin untuk nama (``honorific_names_person``: 歩くんが, 歩くん、, 渡さんが来た), atau bila
    run + honorifik dipanggil dengan koma/seru di posisi panggilan (awal teks, tanda baca, seruan
    atau salam: 渡さん、おはよう, おい歩くん！). Negasi sesudah topik (娘は渡さん！, お前には
    渡さん！) dan kalimat yang hanya dibaca nama oleh aturan konteks (やっぱり歩くんだ) tidak tegas.
    っ sesudah honorifik (歩くんっすよ, 渡さんっ！) bukan bukti: yang dinilai hanya posisi
    panggilan dari huruf sesudah っ (巻くんっ！ di awal baris tegas, 娘は渡さんっ！ tidak).
    Dipakai ``ner.strong_name_counts`` untuk menyimpan entri batang kata kerja ke glosarium seri.
    """
    if not hon.endswith("ん") or run[-1:] not in data.VERB_STEMS.get(hon[:-1], frozenset()):
        return True
    if after[:1] == "っ":
        after = after[1:]
    elif honorific_names_person(hon, after):
        return True
    if after[:1] not in "、，,！!":
        return False
    trimmed = before.rstrip()
    return (not trimmed or trimmed[-1] in _BEFORE_BREAKS
            or _standalone(trimmed, INTERJECTIONS + GREETINGS) is not None)


def honorific_names_person(hon: str, after: str) -> bool:
    """Huruf sesudah honorifik ber-ん membuktikan nama (乾くんが, 開くん、, 治さんは, 治さんが来た)."""
    if len(hon) < 2 or not hon.endswith("ん"):
        return False
    return _after_kind(hon[:-1], after) is None


def _after_kind(okurigana: str, after: str) -> str | None:
    """Jenis konteks sesudah honorifik ber-ん; ``None`` bila konteks itu pasti nama.

    くん: lihat ``_after_kun_kind``. さん/たん (negasi lisan juga mungkin): lihat
    ``_after_negative_kind``.
    """
    if okurigana == "く":
        return _after_kun_kind(after)
    return _after_negative_kind(okurigana, after)


def _after_kun_kind(after: str) -> str | None:
    """Jenis konteks sesudah くん.

    ``NAME_PARTICLES``, っ, ー, ``KUN_NAME_TAILS`` (響くんから？, 弾くんまで), だけ yang bukan だけど
    (咲くんだけが), kanji/katakana langsung (partikel dilesapkan: 歩くん来るって, 咲くん派), dan
    や yang disusul kata (開くんや鳴ちゃん) pasti nama: kata kerja + ん tidak pernah langsung
    disusul kata. で yang disusul kata sambung (よく歩くんで足が "karena", 弾くんでバンド "dengan");
    ``VERB_ENDING_FOLLOWERS`` kopula (行くんだ); ？ tanya; tanda baca lain dan akhir teks akhir
    (乾くん！); selebihnya netral. っす/っしょ (歩くんっすよ: です lisan) kopula. だって/でも yang
    disusul kata bukan kutipan (歩くんだって疲れる, 歩くんでも勝てない: "bahkan X") ``bahkan``;
    だって + 言/聞/思 (歩くんだって言ってた) tetap kopula.
    """
    head = after[:1]
    if after.startswith(("っす", "っしょ")):
        return AFTER_COPULA
    if head in NAME_PARTICLES or head in "っー" or after.startswith(KUN_NAME_TAILS):
        return None
    if after.startswith("だけ") and not after.startswith(("だけど", "だけれど")):
        return None
    if _starts_with_word(after) or (head == "や" and _starts_with_word(after[1:])):
        return None
    for tail in ("だって", "でも"):
        rest = after[len(tail):]
        if after.startswith(tail) and _starts_with_word(rest) and not rest.startswith(
                EVEN_QUOTE_HEADS):
            return AFTER_EVEN
    if head == "で" and _starts_with_word(after[1:]):
        return AFTER_LINK
    if head in VERB_ENDING_FOLLOWERS:
        return AFTER_COPULA
    if head in "？?":
        return AFTER_QUESTION
    return AFTER_END if not head or head in _BREAKS else AFTER_NEUTRAL


def _after_negative_kind(okurigana: str, after: str) -> str | None:
    """Jenis konteks sesudah さん/たん.

    Pasti nama: ``NEGATIVE_NAME_FOLLOWERS``; の yang bukan tanya dan disusul kata (治さんの家);
    が yang langsung disusul predikat (治さんが来た; 貸さんが、 tidak); からも/からは (治さんからも);
    だ/じゃ/です sesudah さん. や atau から yang disusul kata ``dari`` (治さんから聞いた nama,
    話さんから安心して kata kerja: hanya tingkat 0 yang kata kerja). Lalu ``NEGATIVE_TAIL_RE``
    negasi kuat; の + akhir/よ/ね/だ/で (勝たんのよ, これは治さんのよ) dan ``WEAK_NEGATIVE_TAILS``
    sesudah さん negasi lemah; ！ seru; ？ tanya; sesudah たん ``VERB_ENDING_FOLLOWERS`` kopula
    (来たんだ). っ yang disusul tanda baca atau akhir teks (渡さんっ！) dinilai dari huruf
    sesudahnya; っ yang disusul huruf (治さんって) tetap pasti nama.
    """
    head, rest = after[:1], after[1:]
    if head == "っ" and (not rest or rest[0] in _BREAKS):
        return _after_negative_kind(okurigana, rest)
    strong = NEGATIVE_TAIL_RE.match(after) is not None
    if head in NEGATIVE_NAME_FOLLOWERS:
        return None
    if head == "の" and not strong:
        return AFTER_WEAK_NEGATIVE if not rest or rest[0] in "よねだでさ" or rest[0] in _BREAKS \
            else None
    if head == "が" and rest[:1] and rest[0] not in _BREAKS:
        return None
    if after.startswith("から") and after[2:3] in ("も", "は"):
        return None
    if (head == "や" and _starts_with_word(rest)) or (
            after.startswith("から") and _starts_with_word(after[2:])):
        return AFTER_FROM
    if okurigana == "さ" and (head in "だじ" or after.startswith(("です", "でし"))):
        return None
    if strong:
        return AFTER_STRONG_NEGATIVE
    if head in "！!":
        return AFTER_EXCLAMATION
    if head in "？?":
        return AFTER_QUESTION
    if okurigana == "さ" and after.startswith(WEAK_NEGATIVE_TAILS):
        return AFTER_WEAK_NEGATIVE
    if okurigana != "さ" and head in VERB_ENDING_FOLLOWERS:
        return AFTER_COPULA
    return AFTER_NEUTRAL


def _ends_with_break(text: str) -> bool:
    """``text`` berakhir tanda baca/jeda (``_BREAKS``). ー sesudah katakana adalah tanda panjang
    kata itu (ギター, セーター), bukan jeda: ギター弾くんだ adalah objek tanpa partikel."""
    if not text or text[-1] not in _BREAKS:
        return False
    return not (text[-1] == "ー" and len(text) > 1 and is_katakana(text[-2]))


def _starts_with_word(text: str) -> bool:
    """``text`` diawali kanji atau katakana (awal kata benda/kata kerja berikutnya)."""
    return bool(text) and (is_kanji(text[0]) or is_katakana(text[0]))


def _standalone(before: str, words: tuple[str, ...]) -> str | None:
    """Kata ``words`` yang berdiri sendiri di akhir ``before``, atau ``None``.

    Berdiri sendiri: didahului awal teks, tanda baca/spasi, atau ``DASH_BREAKS``, jadi でも di
    雨でも dan また di 今また bukan kata sambung/keterangan kalimat.
    """
    for word in words:
        if before.endswith(word):
            rest = before[:-len(word)]
            if not rest or rest[-1] in _BEFORE_BREAKS:
                return word
    return None


def _before_kind(before: str, verb: str = "") -> str:
    """Jenis konteks tepat sebelum run kanji; ``verb`` adalah batang + okurigana (咲く) atau kosong.

    - panggilan: awal teks, tanda baca, spasi, kanji (bagian nama lengkap), ``SENTENCE_WORDS``
      (kecuali sesudah benda + koma), の atributif, adjektiva -i atributif (強い輝くん), や
      perangkai, nama + honorifik + と/や (咲ちゃんと歩くん), partikel akhir よ/ね/ぞ/ぜ/わ, klausa
      ``_REVEAL_CLAUSES`` (誰かと思えば乾くんか), kata identitas (``_host_kind``: あれが, あの子、,
      君が, のは, 君は + kata kerja benda, cleft + kata dugaan: 勝つのはやっぱり), kata benda orang
      katakana tanpa partikel (うちのリーダー歩くん), dan daftar nama (``_with_kind``: 来たのは私と,
      主役は私と, 先生と + 咲く);
    - peran: kata benda orang + は/が/koma (``_host_kind``: 犯人は, うちの兄が, 幹事は, 四番は,
      真犯人は, お客さんは, あそこに立ってる人が), juga sesudah kata dugaan (犯人はきっと,
      犯人はもしかして);
    - topik terbuka: kata benda kanji atau katakana berakhiran ー yang bukan orang dan bukan
      benda/waktu/tempat yang dikenali + は/って/koma (``_noun_topic_kind``: 主砲は, 代わりは);
    - kasus: を, に, へ, まで, で, から, より, だけ, ほど, こそ, しか, さえ, じゃ, ながら, まま, なら
      (juga には, でも, ても, からは, だけは), bentuk kondisional/て (〜たら, 〜ば, 〜て, 押すと,
      どうやって, 歌って), kata ganti orang pertama + は/も/が (僕は, 僕が), kata ganti + も, bilangan
      + satuan + は/も (一円も), ``MANNER_WORDS``, onomatope (とぼとぼ, のんびり, キラキラ), dan kata
      berakhiran く;
    - komitatif: と sesudah kata benda atau kata ganti (友達と, お兄ちゃんと, 誰と); kata ganti
      orang pertama + と komitatif-diri (俺と);
    - subjek: が/も sesudah kata lain (桜が咲くん, 人が歩くん), katakana lain (juga yang
      berakhiran ー: ギター弾くん), そんなの;
    - topik: は/って/koma sesudah benda/waktu/tempat yang dikenali (``thing_head``: ギターは,
      冬は, この窓って, 窓、), orang umum atau jamak (人は, 僕らは), kata katakana tanpa ー akhir,
      kata ganti orang kedua/ketiga + は (君は), とは, ``CONJUNCTIONS`` yang berdiri sendiri
      (だから歩くん), dan hiragana lain.

    Deretan ``DASH_BREAKS`` (dan spasi di sekitarnya) tepat sebelum run adalah jeda: konteksnya
    kata sebelum tanda itu (``_before_dash_kind``).
    """
    trimmed = before.rstrip()
    if trimmed[-1:] and trimmed[-1] in DASH_BREAKS:
        return _before_dash_kind(trimmed.rstrip(DASH_BREAKS).rstrip(), verb)
    if before[-1:] in _COMMAS:
        return _comma_kind(before[:-1].rstrip(), verb)
    if not before or _ends_with_break(before) or is_kanji(before[-1]) or _joined_name(before):
        return BEFORE_CALL
    if _standalone(before, CONJUNCTIONS) is not None:
        return BEFORE_TOPIC
    word = _standalone(before, SENTENCE_WORDS)
    if word is not None:
        rest = before[:-len(word)].rstrip()
        if rest[-1:] in _COMMAS and _comma_kind(rest[:-1].rstrip()) not in (BEFORE_CALL,
                                                                            BEFORE_ROLE):
            return BEFORE_CASE
        return BEFORE_CALL
    if before.endswith(_NOMINAL_NO):
        return BEFORE_SUBJECT
    if before.endswith(_REVEAL_CLAUSES):
        return BEFORE_CALL
    return _word_kind(before, verb)


def _word_kind(before: str, verb: str = "") -> str:
    """Jenis konteks dari kata/partikel hiragana atau katakana di akhir ``before`` (lihat
    ``_before_kind``)."""
    if not is_hiragana(before[-1]):
        return _katakana_kind(before)
    if before.endswith(("って", "は", "が", "も")) and not before.endswith(_CASE_TAILS):
        particle = "って" if before.endswith("って") else before[-1]
        kind = _host_kind(before[:-len(particle)], particle, verb)
        if kind is not None:
            return kind
    if _QUANTITY_RE.search(before):
        return BEFORE_CASE
    epistemic = next((word for word in EPISTEMIC_WORDS if before.endswith(word)), None)
    if epistemic is not None:
        return _epistemic_kind(before[:-len(epistemic)], verb)
    if before[-1] == "と" and not before.endswith(MANNER_WORDS):
        return _with_kind(before[:-1], verb)
    if (before.endswith(MANNER_WORDS) or before.endswith(_CASE_TAILS) or before[-1] == "く"
            or _MIMETIC_RE.search(before)):
        return BEFORE_CASE
    if before[-1] == "て" and not before.endswith("って"):
        return BEFORE_CASE
    if before.endswith("って"):
        head = before[:-2]
        if head and (is_hiragana(head[-1]) or head[-1] in TE_FORM_STEMS):
            return BEFORE_CASE
        return _noun_topic_kind(head)
    if _ATTRIBUTIVE_RE.search(before) and not before.endswith(NOT_ATTRIBUTIVE):
        return BEFORE_CALL
    if before[-1] in "のや" or before[-1] in _FINAL_PARTICLES:
        return BEFORE_CALL
    if before.endswith("は") and not before.endswith("とは"):
        return _noun_topic_kind(before[:-1])
    if before.endswith(_TOPIC_TAILS):
        return BEFORE_TOPIC
    if before[-1] in "がも":
        return BEFORE_SUBJECT
    return BEFORE_TOPIC


def _epistemic_kind(head: str, verb: str = "") -> str:
    """Jenis konteks run sesudah kata dugaan ``EPISTEMIC_WORDS``; ``head`` teks sebelum kata itu.

    Sesudah topik peran, kata identitas, atau topik kata benda terbuka (犯人はきっと, 勝つのは
    やっぱり, 主砲はまさか) posisi nama tetap berlaku; selebihnya kata keterangan kata kerja
    (きっと咲くんだ, 努力した人はきっと輝くんです: ``人`` umum) kasus.
    """
    if head.endswith("は") and not _ends_with_word(head[:-1], ("人",)):
        kind = _host_kind(head[:-1], "は", verb) or _noun_topic_kind(head[:-1])
        if kind in (BEFORE_CALL, BEFORE_ROLE, BEFORE_OPEN_TOPIC):
            return kind
    return BEFORE_CASE


def _katakana_kind(before: str) -> str:
    """Jenis konteks run yang langsung didahului kata katakana (atau huruf non-kana lain).

    Kata benda orang katakana tanpa partikel adalah aposisi (うちのリーダー歩くんです, 新メンバー
    響くんだよ): panggilan. Onomatope (キラキラ輝くんだ) kasus. Kata katakana lain adalah objek
    atau subjek tanpa partikel (ギター弾くんだ, セーター乾くんですか): subjek.
    """
    match = re.search(f"[{KATAKANA}]+$", before)
    word = match.group() if match else ""
    if word and _person_head(word):
        return BEFORE_CALL
    if word and _MIMETIC_RE.search(word):
        return BEFORE_CASE
    return BEFORE_SUBJECT


def thing_head(host: str) -> bool:
    """``host`` berakhir dengan kata benda/waktu/tempat yang dikenali sebagai topik kata kerja.

    ``THING_WORDS`` (ギター, 窓, 帰り, 冬), ``THING_ENDINGS`` (金曜日, 雨の日, 洗濯物, 帰り道), atau
    kata penunjuk + kata benda (``DEMONSTRATIVES``: この扉, その傘, あの店). Kata benda orang
    diperiksa lebih dulu oleh pemanggil (``_person_head``).
    """
    if host.endswith(THING_WORDS) or host.endswith(THING_ENDINGS):
        return True
    match = _TRAILING_WORD_RE.search(host)
    return bool(match) and host[:match.start()].endswith(DEMONSTRATIVES)


def _noun_topic_kind(host: str) -> str:
    """Jenis konteks topik ``host`` + は/って/koma yang bukan kata identitas atau kata benda orang.

    Topik benda/waktu/tempat yang dikenali (``thing_head``: ギターは, 冬は, この扉は), topik
    jamak atau orang umum (僕らは, 人は, 大人は), kata hiragana (いつもは, それでも), dan kata katakana
    yang tidak berakhiran ー (シーツは, カーテンは: kebanyakan benda serapan; peran katakana yang lazim
    ada di ``PERSON_NOUNS``) adalah topik kata kerja. Kata benda kanji lain dan katakana berakhiran
    ー (主砲は, 先鋒は, 参謀は, ストライカーは: pola pelaku -er) adalah ``topik-terbuka``: lebih
    sering peran yang diisi nama, seperti di baseline_v6.
    """
    if (not host or thing_head(host) or host.endswith(_PLURAL_ENDINGS)
            or _PLURAL_PEOPLE_RE.search(host) or _ends_with_word(host, ("人",))
            or host.endswith(NOT_PERSON_WORDS)):
        return BEFORE_TOPIC
    if is_kanji(host[-1]) or host[-1] in "ーｰ":
        return BEFORE_OPEN_TOPIC
    return BEFORE_TOPIC


def _with_kind(host: str, verb: str = "") -> str:
    """Jenis konteks run sesudah ``host`` + と; ``verb`` seperti di ``_before_kind``.

    と sesudah bentuk kata kerja (押すと, 行かないと) kondisional: kasus. Sesudah topik kelompok
    atau posisi (``GROUP_TOPICS``, ``_person_head`` di luar ``AGENT_TOPICS``: 来たのは私と,
    メンバーは僕と, 主役は私と, 優勝は姉と) daftar nama: panggilan. Orang + と sebelum kata kerja
    yang subjeknya benda (``INANIMATE_VERBS``: 先生と咲くんかな) juga daftar nama. Kata ganti orang
    pertama + と (俺と, 私と): komitatif-diri. Selebihnya と komitatif sesudah kata benda/kata ganti
    (友達と, 犬と, 彼女と, お兄ちゃんと): komitatif.
    """
    if host.endswith("ない") or (host[-1:] and host[-1] in "うくぐすつぬぶむる"
                                and not _ends_with_word(host, PERSONAL_PRONOUNS)
                                and not host.endswith(IDENTITY_SUBJECTS)):
        return BEFORE_CASE
    topic = host.rfind("は")
    head = host[:topic] if topic > 0 else ""
    if head and (head.endswith(GROUP_TOPICS) or (
            _person_head(head) and not _ends_with_word(head, AGENT_TOPICS))):
        return BEFORE_CALL
    if verb in INANIMATE_VERBS and (_person_head(host) or _ends_with_word(
            host, PERSONAL_PRONOUNS + VOCATIVE_WORDS)):
        return BEFORE_CALL
    if _ends_with_word(host, FIRST_PERSON_PRONOUNS):
        return BEFORE_WITH_SELF
    return BEFORE_WITH


def _host_kind(host: str, particle: str, verb: str = "") -> str | None:
    """Jenis konteks kata ``host`` + ``particle`` (は/が/も/って, atau 、 untuk partikel yang
    dilesapkan), atau ``None`` bila ``host`` bukan kata identitas.

    ``IDENTITY_SUBJECTS`` panggilan. ``PERSONAL_PRONOUNS``: orang pertama + が kasus (僕が歩くんですか:
    orang tidak menyebut dirinya dengan くん); orang kedua/ketiga + が, atau kata ganti + は/koma
    sebelum kata kerja yang subjeknya bukan orang (``INANIMATE_VERBS``: 君は響くんだね？), panggilan;
    orang kedua/ketiga + は/koma topik (君は歩くんだよ); selebihnya kasus (僕は歩くんだ, お前も
    歩くんだよ). Kata benda orang (``_person_head``: 犯人は, うちの兄が, 幹事は, 残りの一人は,
    真犯人は, お客さんは) peran dengan は/が/koma, kecuali subjek jamak (全員が, 三人は) dan subjek が
    yang didahului topik benda di jendela yang sama (バイオリンはうちの姉が弾くんです: kalimat kata
    kerja). ``人`` tanpa penjelas + は/が (人は歩くんだよ, 夜中でも人が歩くんですか) adalah orang
    pada umumnya, bukan peran; ``人`` berpenjelas (好きな人は, あそこに立ってる人が) tetap peran.
    """
    if host.endswith(IDENTITY_SUBJECTS):
        return BEFORE_CALL
    if host.endswith(_PLURAL_ENDINGS) or _PLURAL_PEOPLE_RE.search(host):
        return None
    if _ends_with_word(host, PERSONAL_PRONOUNS):
        if particle == "が" and _ends_with_word(host, FIRST_PERSON_PRONOUNS):
            return BEFORE_CASE
        if particle == "が" or (particle != "も" and verb in INANIMATE_VERBS):
            return BEFORE_CALL
        if particle in ("は", "、") and not _ends_with_word(host, FIRST_PERSON_PRONOUNS):
            return BEFORE_TOPIC
        return BEFORE_CASE
    if particle in ("も", "って") or not _person_head(host):
        return None
    if _ends_with_word(host, ("人",)) and _bare_word_head(host[:-1]):
        return None
    if particle == "が" and _THING_TOPIC_RE.search(host):
        return BEFORE_SUBJECT
    return BEFORE_ROLE


def _bare_word_head(rest: str) -> bool:
    """Teks sebelum sebuah kata berakhir awal teks, tanda baca, atau partikel: kata itu tidak
    diterangkan kata lain (人 di 人は, 夜は人が; bukan di 好きな人は, 近所の人は)."""
    return not rest or rest[-1] in _BEFORE_BREAKS or rest[-1] in "もはにでがをとへや"


def _person_head(host: str) -> bool:
    """``host`` berakhir dengan kata benda orang/peran.

    ``PERSON_NOUNS`` sebagai kata utuh (juga dengan satu awalan ``ROLE_PREFIXES``: 真犯人,
    副担任), ``PERSON_NOUN_ENDINGS`` (持ち主, 主治医, 差出人; kecuali ``NOT_PERSON_WORDS``),
    peringkat (``_RANK_RE``), atau kata benda orang + honorifik (``HONORIFIC_NOUN_TAILS``: 店員さん,
    王子様, dan kata berawalan お/ご: お客さん, お巡りさん). ``席`` sesudah kata penunjuk (この席,
    その席) adalah kursi itu sendiri, bukan orang yang duduk di sana (窓際の席は輝くんだよ).
    """
    if host.endswith(("この席", "その席", "あの席")) or host.endswith(NOT_PERSON_WORDS):
        return False
    for tail in HONORIFIC_NOUN_TAILS:
        if host.endswith(tail) and len(host) > len(tail):
            stem = host[:-len(tail)]
            return _person_head(stem) or _POLITE_NOUN_RE.search(stem) is not None
    if (_ends_with_word(host, PERSON_NOUNS) or any(_compound_tail(host, tail)
                                                    for tail in PERSON_NOUN_ENDINGS)
            or _RANK_RE.search(host) is not None):
        return True
    for word in PERSON_NOUNS:
        rest = host[:-len(word)]
        if host.endswith(word) and rest[-1:] in ROLE_PREFIXES and (
                len(rest) == 1 or not (is_kanji(rest[-2]) or is_katakana(rest[-2]))):
            return True
    return False


def _compound_tail(host: str, tail: str) -> bool:
    """``host`` berakhir ``tail``; ekor satu huruf harus menempel ke kata di depannya (持ち主,
    運転手, 差出人), bukan berdiri sendiri sesudah partikel atau awal teks (手は, 猫の手は)."""
    if not host.endswith(tail):
        return False
    rest = host[:-len(tail)]
    return len(tail) > 1 or (bool(rest) and rest[-1] not in _BEFORE_BREAKS
                             and rest[-1] not in "のはがもをにへとでや")


def _ends_with_word(text: str, words: tuple[str, ...]) -> bool:
    """``text`` berakhir dengan salah satu ``words`` sebagai kata utuh (tidak didahului
    kanji/katakana: 子 di 背の高い子, bukan di 帽子)."""
    for word in words:
        if text.endswith(word):
            rest = text[:-len(word)]
            if not rest or not (is_kanji(rest[-1]) or is_katakana(rest[-1])):
                return True
    return False


def _comma_kind(rest: str, verb: str = "") -> str:
    """Jenis konteks run sesudah koma; ``rest`` adalah teks sebelum koma.

    Koma sering menggantikan partikel topik (窓、開くんですか, 布団、乾くんですかね): benda biasa
    sebelum koma adalah topik. Panggilan: awal teks/tanda baca, hiragana (seruan, salam, partikel
    akhir, kata sambung yang berdiri sendiri: やあ、 ねえ、 優しいね、 でも、), kata identitas atau kata
    benda orang (あの子、 犯人、), ``VOCATIVE_WORDS`` (先生、 部長、), dan nama dikenal dua huruf atau
    lebih (田中、; 桜、 dan 花、 satu kanji juga kata biasa, jadi topik). Anak kalimat
    kondisional/alasan/konsesif (``_CONJUNCTIVE_RE``: 傘がないなら、 雨がやんだら、 疲れたけど、)
    kasus. は/が/も sebelum koma dinilai seperti tanpa koma (窓は、 topik, あれは、 panggilan); kata
    ganti orang pertama + koma kasus (僕、). Kata benda lain sebelum koma dinilai
    ``_noun_topic_kind``: benda/waktu yang dikenali (洗濯物、 明日、) topik, selebihnya topik terbuka.
    """
    if not rest or rest[-1] in DASH_BREAKS or _ends_with_break(rest):
        return BEFORE_CALL
    if is_hiragana(rest[-1]):
        if rest[-1] in "はがも" and len(rest) > 1 and not is_hiragana(rest[-2]):
            return _host_kind(rest[:-1], rest[-1], verb) or (
                BEFORE_TOPIC if rest[-1] == "は" else BEFORE_SUBJECT)
        if _standalone(rest, SENTENCE_WORDS) is None and _CONJUNCTIVE_RE.search(rest):
            return BEFORE_CASE
        return _host_kind(rest, "、", verb) or BEFORE_CALL
    kind = _host_kind(rest, "、", verb)
    if kind is not None:
        return kind
    match = _TRAILING_WORD_RE.search(rest)
    word = match.group() if match else ""
    if word.endswith(VOCATIVE_WORDS) or _surname_head(word) or (
            len(word) > 1 and is_known_name(word)):
        return BEFORE_CALL
    return _noun_topic_kind(rest)


def _before_dash_kind(rest: str, verb: str = "") -> str:
    """Jenis konteks run yang didahului tanda pisah/dialog; ``rest`` adalah teks sebelum tanda itu.

    Awal teks atau tanda baca (``－歩くん？``, ``「――歩くん？``, ``　――歩くんだよね``) adalah
    panggilan. Kata berakhiran kanji tidak menjadi bagian nama karena dipisah tanda: nama dikenal
    (``田中――歩くん？``) panggilan, kata lain (``毎日――歩くんだ``) subjek seperti katakana.
    Selebihnya aturan biasa, jadi partikel sebelum jeda tetap dihitung (``道を――歩くんだ`` kasus,
    ``桜が――咲くんだ`` subjek, ``花は――咲くんだよ`` topik seperti ``花は咲くんだよ``). Bentuk
    って sebelum jeda (``待って――歩くん？``) adalah akhir klausa perintah, jadi topik, bukan bentuk
    て yang menerangkan run (``歌って歩くんだ`` kasus).
    """
    if not rest or rest[-1] in _BREAKS:
        return BEFORE_CALL
    if is_kanji(rest[-1]):
        word = KANJI_RE.findall(rest)[-1]
        return BEFORE_CALL if is_known_name(word) or _surname_head(word) else BEFORE_SUBJECT
    kind = _before_kind(rest, verb)
    return BEFORE_TOPIC if kind == BEFORE_CASE and rest.endswith("って") else kind


def _inverted_kind(before: str, after: str, kind: str) -> str:
    """Jenis konteks ``kind`` disesuaikan dengan bagian kalimat yang dipindah ke belakang run.

    Bukti kata kerja sesudah kopula + koma (``_trailing_verb``: penunjuk + benda, objek を,
    keterangan cara, argumen kasus) membuat konteks kasus, kecuali konteks sebelumnya sudah kuat
    menandai nama (``_strong_name_context``: ``犯人は拓くんだよ、この事件の。``, ``優勝したのは
    響くんだよ、しかも大差で。``) atau bagian belakang adalah anak kalimat cleft
    (``拓くんだよ、ボールを投げたのは。``). Penunjuk + benda tetap berlaku sesudah subjek orang + が
    (``うちの兄が弾くんです、そのピアノ。``). Hanya untuk run di awal klausa (``kind`` panggilan dan
    ``before`` kosong, tanda baca, atau tanda pisah saja): argumen lain mengikuti partikelnya,
    jadi ``咲くんだ、桜が。`` sama dengan ``桜が咲くんだ`` (subjek). Argumen berupa nama atau kata
    identitas (``歩くんだ、あいつが。``) tetap panggilan.
    """
    if _strong_name_context(before, kind) or _cleft_tail(after):
        return kind
    if _trailing_verb(after, pointed_only=kind == BEFORE_ROLE):
        return BEFORE_CASE
    match = _INVERTED_ARGUMENT_RE.match(after)
    if not match or kind == BEFORE_ROLE:
        return kind
    arg_kind = _before_kind(match["arg"])
    if arg_kind == BEFORE_CASE:
        return kind if match["arg"].startswith(SENTENCE_ADVERBS) else BEFORE_CASE
    rest = before.rstrip().rstrip(DASH_BREAKS).rstrip()
    if kind != BEFORE_CALL or (rest and rest[-1] not in _BREAKS):
        return kind
    return arg_kind


def _strong_name_context(before: str, kind: str) -> bool:
    """Konteks sebelum run sudah kuat menandai nama: topik peran + は (``犯人は``, ``委員長は``,
    ``次の主将は``) atau fokus cleft (``優勝したのは``, ``呼んだのは``, ``好きなのが``)."""
    rest = before.rstrip()
    return (kind == BEFORE_ROLE and rest.endswith("は")) or rest.endswith(("のは", "のが"))


def _cleft_tail(after: str) -> bool:
    """Bagian sesudah kopula + koma sampai akhir klausa adalah anak kalimat cleft ``…のは``/
    ``…のが`` (``拓くんです、この絵を描いたのは。``): run adalah fokus identitas, jadi nama."""
    comma = re.search("[、，]", after)
    if comma is None:
        return False
    clause = _CLAUSE_END_RE.split(after[comma.end():], maxsplit=1)[0]
    return "のは" in clause or "のが" in clause


def _trailing_verb(after: str, *, pointed_only: bool = False) -> bool:
    """Bagian belakang sesudah kopula + koma menandai kata kerja.

    Penunjuk + benda yang bukan orang/ciri orang (``_pointed_thing``); bila ``pointed_only``
    salah juga objek を yang bukan orang (``ギターを``) dan keterangan cara (``意外と早く``,
    ``ちゃんと``) yang bukan salam atau kata keterangan kalimat (``SENTENCE_ADVERBS``).
    """
    if _pointed_thing(after):
        return True
    if pointed_only:
        return False
    obj = _TRAILING_OBJECT_RE.match(after)
    if obj and not (_person_head(obj["obj"]) or _ends_with_word(obj["obj"], PERSONAL_PRONOUNS)):
        return True
    manner = _TRAILING_MANNER_RE.match(after)
    return bool(manner) and not manner["adv"].endswith(GREETINGS) and not manner[
        "adv"].startswith(SENTENCE_ADVERBS)


def _pointed_thing(after: str) -> bool:
    """Kopula + koma + penunjuk + benda yang dipindah dari depan (``開くんだよ、この箱は。``).

    Kata benda harus disusul ``POINTED_TAILS``/akhir teks, ``の中`` (``こんな雨の中を``), atau
    に/で sesudah kata waktu (``この時間になると``). Kata benda orang (``その人は``), ciri orang
    (``TRAIT_NOUNS``: ``その声は``), dan ``この中`` ("di antara ini") tidak dihitung.
    """
    match = _TRAILING_POINTED_RE.match(after)
    if match is None:
        return False
    noun, tail = match["noun"], after[match.end():]
    if noun.startswith("中") or _person_head(noun) or noun.endswith(TRAIT_NOUNS):
        return False
    if not tail or tail[0] in POINTED_TAILS or tail.startswith("の中"):
        return True
    return tail[0] in "にで" and noun.endswith(POINTED_TIME_NOUNS)


def _joined_name(before: str) -> bool:
    """``before`` berakhir dengan nama + honorifik + と/や (咲ちゃんと, 田中さんや): perangkai nama.

    Honorifik harus didahului kanji atau katakana (nama), jadi ちゃんと sesudah koma atau awal
    teks (傘、ちゃんと開くんですか) tetap kata keterangan. Kata benda biasa ber-honorifik
    (``COMMON_HONORIFIC_WORDS``: お兄ちゃんと, お母さんと, 赤ちゃんと) bukan nama. ちゃんと sesudah
    kata kanji yang bukan nama dikenal (毎日ちゃんと歩くんだ, 毎年ちゃんと咲くんです, 傘ちゃんと
    開くんですか: partikel dilesapkan) juga kata keterangan "dengan benar"; 咲ちゃんと (nama dikenal,
    ``is_known_name``/nama keluarga) dan katakana (カナちゃんと) tetap perangkai nama.
    """
    if before[-1] not in "とや":
        return False
    head = before[:-1]
    for hon in HONORIFIC_SURFACES:
        if head.endswith(hon) and _starts_with_word(head[-len(hon) - 1:-len(hon)]):
            host = head[:-len(hon)]
            if before.endswith("ちゃんと") and is_kanji(host[-1]):
                word = KANJI_RE.findall(host)[-1]
                return is_known_name(word) or _surname_head(word)
            return not host.endswith(COMMON_HONORIFIC_WORDS)
    return False


def _denies_identity(after: str) -> bool:
    """``after`` mengingkari identitas orang: ``じゃないよ、別人`` atau ``じゃない、本人に``
    (``IDENTITY_DENIAL_WORDS``) atau kata benda orang sesudah koma. Run sebelumnya nama
    (``彼は拓くんじゃないよ、別人だ。``); ``彼は歩くんじゃないよ、走るんだ`` tetap kata kerja.
    Kata benda orang + が/は adalah subjek klausa kontras baru (``花が咲くんじゃない、人が
    咲かせるんだ``, ``僕が歩くんじゃなくて、先生が歩くんだ``), bukan pengingkaran identitas."""
    match = _IDENTITY_DENIAL_RE.match(after)
    if match is None:
        return False
    if match["word"].startswith(IDENTITY_DENIAL_WORDS):
        return True
    return _person_head(match["word"]) and not after[match.end():].startswith(("が", "は"))


def _name_level(word: str, named: frozenset[str]) -> int:
    """Tingkat nama untuk ``VERB_CONTEXT_TABLE``: 2 ``named``, 1 ``is_known_name``, 0 lainnya."""
    if word in named:
        return 2
    return 1 if is_known_name(word) else 0


def _surname_head(prefix: str) -> bool:
    """``prefix`` adalah atau diawali nama keluarga dua kanji atau lebih (鈴木大 di 鈴木大輝)."""
    surnames = data.surnames()
    return prefix in surnames or any(prefix[:size] in surnames
                                     for size in range(2, len(prefix)))


def verb_run_before_honorific(
    run: str, hon: str, after: str = "", not_names: frozenset[str] = frozenset(), *,
    before: str = "", named: frozenset[str] = frozenset(),
) -> bool:
    """Apakah run kanji + ``hon`` sebenarnya (kata lain +) kata kerja + okurigana + ん.

    Satu aturan konteks (``VERB_CONTEXT_TABLE``). Syarat awal: kanji terakhir run adalah
    batang kata kerja di ``data.VERB_STEMS`` untuk okurigana honorifik itu (歩 + くん = 歩く + ん,
    待 + たん = 待たん, 許 + さん = 許さん), dan konteks sesudahnya tidak pasti nama
    (``_after_kind``: 乾くんが, 巻くんっ, 治さんは). Lalu:

    - run satu kanji: jenis konteks sebelumnya (``_before_kind``) x jenis konteks sesudahnya
      dibandingkan dengan tingkat nama kanji itu (``_name_level``);
    - run lebih panjang: nama bila run dikenal, terbukti (``named``), diawali nama keluarga
      (鈴木大輝), atau diawali satu kanji yang bukan ``not_names`` (大輝, 雅行, 英治: kanji awal
      nama). Awalan lain adalah kata keterangan/argumen tanpa partikel (明日行くん, 来週行くんだ,
      東京行くんだ, 毎朝歩くんだ, 絶対渡さん) dan dinilai seperti konteks kasus.

    Args:
        run: Run kanji tepat sebelum honorifik.
        hon: Honorifik yang cocok.
        after: Teks sesudah honorifik (beberapa huruf; kosong berarti akhir teks).
        not_names: Kata yang bukan nama diri (``ner.NOT_NAMES``).
        before: Teks tepat sebelum run (beberapa huruf; kosong berarti awal teks).
        named: Tulisan yang terbukti nama di dokumen ini atau berbacaan.
    """
    if not run or len(hon) < 2 or not hon.endswith("ん"):
        return False
    okurigana = hon[:-1]
    if run[-1] not in data.VERB_STEMS.get(okurigana, frozenset()):
        return False
    after_kind = _after_kind(okurigana, after)
    if after_kind is None or _denies_identity(after):
        return False
    prefix = run[:-1]
    if not prefix:
        before_kind = _inverted_kind(before, after, _before_kind(before, run[-1] + okurigana))
    elif (run in named or is_known_name(run) or _surname_head(prefix)
          or (len(prefix) == 1 and prefix not in not_names)):
        return False
    else:
        before_kind = BEFORE_CASE
    return VERB_CONTEXT_TABLE[before_kind][after_kind] >= _name_level(run[-1], named)

