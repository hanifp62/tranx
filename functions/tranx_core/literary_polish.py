"""Multi-level Skopos-driven literary & discourse naturalizer for tranX backend (tranx_core, v4).

Mirrors web/src/lib/literaryPolish.ts without touching the SHA-256 locked
functions/vendor/jptrans/ package. Enforces:
1. Author-Purpose-Reader Skopos Document Profiling (10+ genres, Reiss text type,
   Nida dynamic/formal equivalence, Newmark semantic/communicative, House overt/covert,
   complexity calibration L1-L5 across EN/ID/JA).
2. 6-Block Skopos system prompt instructions for Gemini/OpenAI-compatible LLMs.
3. FormatShield span protection (code, LaTeX, URLs, emails, DOIs, filenames like app.py/Node.js,
   Markdown prefixes/tables, subtitle timestamps, placeholders) + EYD V & KBBI VI rules.
4. 12-Invariant ConservationGate & MQM Core scorer with atomic rollback on violation.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

_LEGAL_RE = re.compile(
    r"(?:Pasal\s+\d+|Ayat\s*\(\d+\)|Undang-Undang|Whereas\b|Hereinafter|SHALL\s+NOT|MUST\s+NOT|第\d+条|利用規約|免責事項|個人情報保護)"
)
_DEONTIC_RE = re.compile(r"\b(?:SHALL\s+NOT|MUST\s+NOT|SHALL|MUST|MAY\s+NOT|wajib|dilarang)\b")
_TECH_RE = re.compile(
    r"(?:```|`[^`\n]{2,60}`|\b(?:HTTP|JSON|API|SDK|CLI|REST|GraphQL|RFC\s*\d+|localhost|npm|git|endpoint|payload)\b|関数|引数|エラー|仕様書)"
)
_ACADEMIC_RE = re.compile(
    r"(?:\b(?:Abstract|Methodology|Hypothesis|Conclusion|et\s+al\.|doi:|Abstrak|Metodologi|Hipotesis|Kesimpulan)\b|要旨|考察|参考文献|\([A-Z][a-z]+,\s*\d{4}\))"
)
_BUSINESS_RE = re.compile(
    r"(?:拝啓|敬具|お世話になっております|ご確認(?:いただけ|くださ)|いただけますでしょうか|申し上げます|存じます|\b(?:Dengan\s+hormat|Bapak/Ibu|Mohon\s+kesediaan|Hormat\s+kami|Dear\s+Sir|Sincerely,|Pursuant\s+to)\b)"
)
_NEWS_RE = re.compile(
    r"(?:\b(?:JAKARTA|TOKYO|WASHINGTON|REUTERS|AP|AFP|dilaporkan|menurut\s+sumber|juru\s+bicara|spokesperson|according\s+to\s+officials)\b|【[^】]{2,16}】|報道によると)"
)
_SCHOOL_RE = re.compile(r"(?:教室|クラスメイト|高校|中学|生徒会|部活|先輩|後輩|担任|放課後|登校|制服|学園)")
_ARCHAIC_RE = re.compile(
    r"(?:殿下|陛下|王女|騎士|貴族|魔法|ギルド|冒険者|魔王|勇者|侍女|執事|公爵|伯爵|旦那様|お嬢様|拙者|余は|そなた|貴殿|ござる|\b(?:thou|thee|thy|behold|your majesty|paduka|baginda|hamba|beta|engkau|tiada|hendak)\b)",
    re.IGNORECASE,
)
_COMIC_SFX_RE = re.compile(r"(?:ゴゴゴ|ドゴォ|バンッ|ドンッ|ガシャン|バシッ|ザッ|ヒュッ|《[^》]{1,24}》|【[^】]{1,24}】)")
_QUOTE_LINE_RE = re.compile(r'^\s*[「『"“]')
_JA_POLITE_END_RE = re.compile(r"(?:です|ます|ました|でした|ません|ましょう|ございます|ください)[。！？!?…」』\"\s]*$")
_JA_1P_CASUAL_RE = re.compile(r"(?:俺|僕|あたし|うち|わし|自分)(?:は|が|の|も|を|に)")

_FORMAT_SHIELD_INLINE_RE = re.compile(
    r"```[\s\S]*?```|`[^`\n]{1,240}`|(?m:^\$\$[\s\S]{1,1200}?^\$\$)|\$\$[^\n$]{1,240}\$\$|\$(?![\s\d])[^$\n]{1,120}(?<!\s)\$|"
    r"\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}|\{\\[^}\n]{1,60}\}|"
    r"\[\[[EHIC]\d+\]\]|(?<=\])\(https?://[^\s)]+\)|https?://[^\s)>\"'」』]+|"
    r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,6}\b|\b10\.\d{4,9}/[^\s),;]+|"
    r"\[\^[^\]]+\]|\[\d{1,3}\]|※\d+|"
    r"\b[A-Za-z][A-Za-z0-9_-]*\.(?:py|ts|tsx|js|jsx|mjs|cjs|json|yaml|yml|toml|md|html|css|scss|sql|sh|go|rs|java|kt|rb|php|vue|svelte|env|lock|txt|pdf|epub|docx|png|jpg|jpeg|webp)\b"
)
_FORMAT_SHIELD_LINE_PREFIX_RE = re.compile(
    r"^(?:```[^\n]*|#{1,6}[ \t]+|>[ \t]+|(?:[-*+]|\d+\.)[ \t]+|"
    r"\|?(?:[ \t]*:?-{2,}:?[ \t]*\|)+[ \t]*$|"
    r"[ \t\u3000]*(?:\*{3,}|-{3,}|={3,}|◆{2,}|◇{2,})[ \t\u3000]*$)",
    re.MULTILINE,
)
_PROTECTED_SPAN_RE = re.compile(r"(\u27E6F\d+\u27E7|\[\[[EHIC]\d+\]\]|`[^`\n]+`|https?://[^\s)>\"']+)")
_QUOTE_SPAN_RE = re.compile(r'("[^"\n]{1,600}")')
_NUM_RE = re.compile(r"(?:\b|(?<=Rp))\d+(?:[.,]\d+)*%?(?![A-Za-z0-9_])")
_UNIT_CURRENCY_RE = re.compile(
    r"(?:\bRp(?=\d)|[$€£¥%]|\b(?:kg|km|cm|mm|mg|ml|mL|MHz|GHz|MB|GB|TB|ms|kWh)\b|°[CF])"
)
_DEONTIC_MANDATORY_RE = re.compile(r"\b(?:wajib|harus|dilarang|shall|must|prohibited)\b", re.IGNORECASE)
_ID_NEG_RE = re.compile(r"\b(?:tidak|tak|bukan|belum|jangan|tanpa|tiada|nggak|gak|dilarang)\b", re.IGNORECASE)
_EN_NEG_RE = re.compile(r"\b(?:not|never|no|without|neither|nor)\b|n't\b", re.IGNORECASE)
_JA_NEG_RE = re.compile(r"(?:ない|ません|なかった|ませんでした|ず|ぬ)")
_KNOWN_DOT_ABBREV_RE = re.compile(
    r"(?:^|[\s(])(?:e\.g|i\.e|U\.S|U\.K|a\.m|p\.m|vs|etc|St|Dr|Mr|Mrs|Ms|Prof|Jr|Sr|dll|dsb|dkk|hlm|No|Tn|Ny|Nn|Sdr|Sdri|Jl|Kp|v\d+)$",
    re.IGNORECASE,
)

_ABSTRACT_SEBUAH = (
    "perasaan|kebenaran|kebohongan|keheningan|kesunyian|harapan|mimpi|senyuman|senyum|"
    "tawa|masalah|tantangan|peluang|kesempatan|pilihan|keputusan|perubahan|ide|gagasan|"
    "pendapat|alasan|tanda|bukti|fakta|rahasia|kenangan|keajaiban|tragedi|kesalahan|"
    "kegagalan|keberhasilan|kemenangan|kekalahan|ancaman|risiko|bahaya|solusi|jawaban|"
    "pertanyaan|pengalaman|pengetahuan|informasi|data|nasihat|saran|bantuan|dukungan|"
    "perhatian|cinta|kasih|kebencian|kemarahan|ketakutan|keraguan|kepercayaan"
)
_SAFE_OLEHNYA = (
    "dibuka|ditutup|diambil|dipegang|ditarik|didorong|dilihat|ditatap|dibaca|ditulis|"
    "dikatakan|diucapkan|dijawab|ditanya|didengar|dirasakan|dipikirkan|diingat|dilupakan|"
    "disimpan|diletakkan|dilemparkan|diberikan|diterima|dikirim|dipilih|dibeli|dibuat|"
    "diubah|dihapus|ditemukan|dicari|dikejar|ditangkap|dilepaskan|dipeluk|disentuh"
)
_SPEECH_VERBS = (
    "kata|ujar|jawab|sahut|balas|tanya|gumam|bisik|seru|teriak|bentak|pekik|celetuk|"
    "lanjut|potong|seloroh|cibir|gerutu|desah|desis|keluh|ucap|tutur|tegas|sambung|timpal"
)
_REDUPL_BLOCK = frozenset({"kupu", "laba", "mata", "cumi", "ubur", "kura", "oleh", "hati"})
_BODY_COMPOUND_BLOCK = frozenset(
    {
        "pencaharian",
        "uang",
        "pelajaran",
        "kuliah",
        "air",
        "angin",
        "pisau",
        "rantai",
        "hati",
        "terbanyak",
        "mayoritas",
        "bulat",
        "hukum",
        "usaha",
        "dan",
        "atau",
        "serta",
        "yang",
        "untuk",
        "dari",
        "pada",
        "dengan",
        "seperti",
        "sebagai",
        "tetapi",
        "tapi",
        "namun",
        "karena",
        "sambil",
        "lalu",
        "kemudian",
        "ini",
        "itu",
        "tersebut",
        "sendiri",
        "saja",
        "lagi",
        "juga",
        "akan",
        "bisa",
        "dapat",
        "harus",
        "telah",
        "sudah",
        "belum",
        "tidak",
        "bukan",
        "masih",
        "sedang",
        "adalah",
        "merupakan",
        "menjadi",
        "ketika",
        "saat",
        "jika",
        "kalau",
        "agar",
        "supaya",
        "bahwa",
        "hingga",
        "sampai",
        "tanpa",
        "dalam",
        "oleh",
        "membuat",
        "memberi",
        "melihat",
        "mendengar",
        "berbicara",
        "berkata",
        "berjalan",
        "berdiri",
        "duduk",
        "pergi",
        "datang",
        "punya",
        "tahu",
        "ingin",
        "suka",
    }
)

_KBBI_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpraktek\b", re.I), "praktik"),
    (re.compile(r"\bresiko\b", re.I), "risiko"),
    (re.compile(r"\banalisa\b", re.I), "analisis"),
    (re.compile(r"\bsistim\b", re.I), "sistem"),
    (re.compile(r"\bkwalitas\b", re.I), "kualitas"),
    (re.compile(r"\bkwantitas\b", re.I), "kuantitas"),
    (re.compile(r"\baktifitas\b", re.I), "aktivitas"),
    (re.compile(r"\befektifitas\b", re.I), "efektivitas"),
    (re.compile(r"\bnafas\b", re.I), "napas"),
    (re.compile(r"\bbernafas\b", re.I), "bernapas"),
    (re.compile(r"\bijin\b", re.I), "izin"),
    (re.compile(r"\bmengijinkan\b", re.I), "mengizinkan"),
    (re.compile(r"\bobyek\b", re.I), "objek"),
    (re.compile(r"\bsubyek\b", re.I), "subjek"),
    (re.compile(r"\bjadual\b", re.I), "jadwal"),
    (re.compile(r"\bantri\b", re.I), "antre"),
    (re.compile(r"\bapotik\b", re.I), "apotek"),
    (re.compile(r"\batlit\b", re.I), "atlet"),
    (re.compile(r"\bhakekat\b", re.I), "hakikat"),
    (re.compile(r"\bsekedar\b", re.I), "sekadar"),
    (re.compile(r"\bte(?:k?h)nik\b", re.I), "teknik"),
    (re.compile(r"\bterimakasih\b", re.I), "terima kasih"),
)

# Precompiled hot-path regexes & translation tables (v2.5.1 perf optimization)
_FULLWIDTH_DIGITS_TRANS = str.maketrans("０１２３４５６７８９", "0123456789")
_SCENE_BREAK_RE = re.compile(r"^[\s\u3000]*(?:[*＊◇◆☆■□・―\-=]{2,}|※)[\s\u3000]*$")
_WS_COLLAPSE_RE = re.compile(r"[ \t]{2,}")
_JA_CJK_SPACE_RE = re.compile(
    r"([\u3040-\u30ff\u3400-\u9fff。、！？「」『』])[ \t]+(?=[\u3040-\u30ff\u3400-\u9fff。、！？「」『』])"
)
_EMDASH_PAIR_RE = re.compile(r"[ \t]*\u2014[ \t]*([^\u2014\n]{2,90}?)[ \t]*\u2014[ \t]*")
_EMDASH_TRAIL_RE = re.compile(r'([A-Za-z0-9])\u2014(["”!?]|$)')
_EMDASH_ANY_RE = re.compile(r"[ \t]*\u2014[ \t]*")
_DASH_RUN_RE = re.compile(r"[\u2015\u2500]{2,}")
_OPEN_BACKTICK_QUOTE_RE = re.compile(r"``[ \t]*")
_CLOSE_SINGLE_QUOTE_RE = re.compile(r"[ \t]*''")
_ELLIPSIS_RUN_RE = re.compile(r"…{2,}|\.{4,}")
_BANG_Q_DOT_RE = re.compile(r"([!?])\.")
_DOUBLE_COMMA_RE = re.compile(r",[ \t]*,+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([,.;:?!])")
_SPACE_AFTER_BANG_Q_RE = re.compile(r"([!?])(?=[A-Za-zÀ-ÿ])")
_GLUED_DOT_CAP_RE = re.compile(r"([a-zà-ÿ]{3,})\.(?=[A-ZÀ-Ý])")
_PLACEHOLDER_LEAK_RE = re.compile(r"\[\[[EHIC]\d+\]\]|\u27E6F\d+\u27E7")
_THOUSAND_SEP_RE = re.compile(r"[.,](?=\d{3}(?:\D|$))")
_STRUCTURAL_PREFIX_RE = re.compile(r"^(\s*(?:```|#{1,6}\s+|>\s+|(?:[-*+]|\d+\.)\s+))")

_ID_TEMPAT_DIMANA_RE = re.compile(r"\btempat\s+di\s+mana\b", re.I)
_ID_LOC_DIMANA_RE = re.compile(
    r"\b(kota|negara|desa|rumah|gedung|kantor|sekolah|kampus|kafe|kamar|ruangan|pulau|jalan|lokasi|wilayah|daerah|area|titik)\s+di\s+mana\b",
    re.I,
)
_ID_TIME_DIMANA_RE = re.compile(r"\b(saat|waktu|masa|era|zaman|hari|momen|periode|tahap|fase)\s+di\s+mana\b", re.I)
_ID_STATE_DIMANA_RE = re.compile(r"\b(situasi|kondisi|keadaan|kasus|skenario|proses|sistem|dunia)\s+di\s+mana\b", re.I)
_ID_YANG_MANA_RE = re.compile(
    r'(?<!^)(?<!\.\s)(?<!"\s)(?<!\btahu\s)(?<!\bpilih\s)(?<!\bentah\s)(?<!\bbingung\s)(?<!\btanya\s)(?<!\blihat\s),?\s*\byang\s+mana\b(?!\s*(?:yang|ini|itu|lebih|paling|satu|pula|sih|ya)?\s*\?)',
    re.I,
)
_ID_ADALAH_MERUPAKAN_RE = re.compile(r"\badalah\s+merupakan\b", re.I)
_ID_DIKARENAKAN_OLEH_RE = re.compile(r"\bdikarenakan\s+oleh\b", re.I)
_ID_FAKTA_BAHWA_RE = re.compile(r"\b(?:sebagai\s+akibat\s+dari|karena|berkat)\s+fakta\s+bahwa\b", re.I)
_ID_CANNOT_HELP_RE = re.compile(r"\btidak\s+(?:bisa|dapat)\s+membantu\s+(?:tetapi|tapi|selain)\s+([a-z]+)", re.I)
_ID_DOUBLE_NEG_RE = re.compile(
    r"\btidak\s+(?:bisa|dapat)\s+tidak\s+(melakukan|mengakui|merasa|tersenyum|tertawa|menangis|mengagumi|setuju|memikirkan|mengingat|tertarik|mengubah)\b",
    re.I,
)
_ID_TELAH_TIDAK_PERNAH_RE = re.compile(r"\btelah\s+tidak\s+pernah\b", re.I)
_ID_TIDAK_TERBATAS_RE = re.compile(r"\btidak\s+terbatas\s+pada\s+(bagus|baik|benar|salah|mahal|murah|mudah|sulit)\b", re.I)
_ID_INVESTIGASI_RE = re.compile(r"\bmelakukan\s+investigasi\s+(?:terhadap|atas|tentang)\b", re.I)
_ID_PENGAMATAN_RE = re.compile(r"\bmelakukan\s+pengamatan\s+(?:terhadap|atas)\b", re.I)
_ID_KEPUTUSAN_RE = re.compile(r"\bmembuat\s+(?:sebuah\s+)?keputusan\s+untuk\b", re.I)
_ID_SEBUAH_ABSTRACT_RE = re.compile(
    rf"(?<!\bhanya\s)(?<!\bcuma\s)(?<!\bsatu\s)(?<!\bsekadar\s)\bsebuah\s+({_ABSTRACT_SEBUAH})\b(?!\s+(?:tunggal|satu-satunya|tersendiri))",
    re.I,
)
_ID_BODY_PART_RE = re.compile(
    r"(?<!\btidak\s)(?<!\btak\s)(?<!\bbelum\s)(?<!\btanpa\s)\b(?:memiliki|mempunyai|punya)\s+(mata|rambut|wajah|kulit|suara|tubuh|badan|hidung|bibir|alis)\s+(?:yang\s+)?([a-z]{3,})\b",
    re.I,
)
_ID_ADALAH_IMP_RE = re.compile(
    r"(?:^|(?<=[.!?]\s))Adalah\s+(penting|sulit|mudah|mustahil|wajar|jelas|mungkin|benar|salah)\s+(untuk|bahwa)\b"
)
_ID_OLEHNYA_RE = re.compile(rf"\b({_SAFE_OLEHNYA})\s+olehnya\b(?!\s*(?:sendiri|,\s*bukan))", re.I)
_ID_DIHUJANI_RE = re.compile(r"\bdihujani\s+oleh\s+hujan\b", re.I)
_ID_MESKIPUN_TAPI_RE = re.compile(r"\b(Meskipun|Walaupun|Kendati)\s+([^,.!?]{3,80}),\s+(?:tetapi|tapi|namun)\s+", re.I)
_ID_KARENA_MAKA_RE = re.compile(r"\b(Karena|Sebab)\s+([^,.!?]{3,80}),\s+maka\s+", re.I)
_ID_DALAM_RANGKA_RE = re.compile(r"\b(?:dalam\s+rangka\s+untuk|untuk\s+tujuan\s+untuk)\b", re.I)
_ID_PARA_REDUPL_RE = re.compile(r"\b(para)\s+([a-z]{3,})-\2\b", re.I)
_ID_SANGAT_SEKALI_RE = re.compile(r"\bsangat\s+([a-z]{3,})\s+sekali\b", re.I)
_ID_JATUH_CINTA_RE = re.compile(r"\bjatuh\s+cinta\s+dengan\b", re.I)
_ID_LOOKING_FWD_RE = re.compile(r"\bmelihat\s+ke\s+depan\s+untuk\b", re.I)
_ID_MAHAESA_RE = re.compile(r"\bMahaesa\b", re.I)
_ID_MAHA_SPACED_RE = re.compile(r"\bMaha\s+(Kuasa|Tahu|Besar|Adil|Kasih|Suci|Tinggi|Mulia|Agung|Bijaksana)\b", re.I)
_ID_DI_LOC_RE = re.compile(r"\bdi(sini|situ|sana|mana|atas|bawah|dalam|luar|depan|belakang|samping|antara|tengah|sekitar)\b", re.I)
_ID_KE_LOC_RE = re.compile(r"\bke(sini|situ|sana|mana|atas|bawah|dalam|depan|belakang|samping|tengah)\b", re.I)
_ID_PUN_RE = re.compile(r"\b(apa|siapa|kapan|berapa|satu|dua|sedikit|banyak|juga|ia|dia|aku|kamu|kami|kita|mereka)pun\b", re.I)
_ID_DIMANAPUN_RE = re.compile(r"\bdi\s*manapun\b", re.I)
_ID_KEMANAPUN_RE = re.compile(r"\bke\s*manapun\b", re.I)
_ID_RP_SPACE_RE = re.compile(r"\bRp\.?\s+(\d)")
_ID_RP_DOT_RE = re.compile(r"\bRp\.(\d)")
_ID_KEPADA_IA_RE = re.compile(r"\b(kepada|oleh)\s+ia\b", re.I)
_ID_DENGAN_IA_RE = re.compile(
    r"\b(dengan|untuk|dari|pada)\s+ia\b(?=[,.;:!?\s]*(?:$|dan\b|atau\b|tapi\b|namun\b|karena\b|lalu\b|kemudian\b|sambil\b))",
    re.I,
)
_EN_SHALL_MUST_POS_RE = re.compile(r"\b(?:SHALL|MUST)(?!\s+NOT)\b")
_EN_SHALL_MUST_NEG_RE = re.compile(r"\b(?:SHALL|MUST)\s+NOT\b")
_ID_PARTY_AKAN_RE = re.compile(r"\b(Pihak|Pengguna|Penyedia|Pemohon|Pembeli|Penjual|Penerima|Kontraktor)\s+akan\b")
_ID_PARTY_TDK_AKAN_RE = re.compile(r"\b(Pihak|Pengguna|Penyedia|Pemohon|Pembeli|Penjual|Penerima|Kontraktor)\s+tidak\s+akan\b")
_ID_SEDANGKAN_RE = re.compile(r"(?:^|(?<=[.!?]\s))(?:Sedangkan\s+untuk|Adapun\s+mengenai)\s+([^,.\n]{2,36}),\s+")
_ID_OLEH_KARENA_RE = re.compile(r"(?:^|(?<=[.!?]\s))Oleh\s+karena\s+itu,\s+")
_ID_DGN_KATA_LAIN_RE = re.compile(r"(?:^|(?<=[.!?]\s))Dengan\s+kata\s+lain,\s+")
_ID_SUPERIOR_RE = re.compile(r"(?:-sensei|-sama|\b(?:Pak|Bu|Bapak|Ibu|Tuan|Nyonya|Profesor|Dokter|Paduka)\b)", re.I)
_ID_KEPADA_SAYA_RE = re.compile(r"\bkepada\s+saya\b", re.I)
_ID_UNTUK_SAYA_RE = re.compile(r"\buntuk\s+saya\b", re.I)
_ID_SAYA_CAP_RE = re.compile(r"\bSaya\b")
_ID_SAYA_LOW_RE = re.compile(r"\bsaya\b")
_ID_ANDA_CAP_RE = re.compile(r"\bAnda\b")
_ID_ANDA_LOW_RE = re.compile(r"\banda\b")
_ID_AKU_ANY_RE = re.compile(r"\baku\b", re.I)
_ID_ANDA_ANY_RE = re.compile(r"\banda\b", re.I)
_ID_DIALOG_PERIOD_RE = re.compile(rf'("[^"\n]*?(?<!\.))\."[ \t]+({_SPEECH_VERBS})(nya|ku|mu)?\b', re.I)
_ID_DIALOG_BANG_RE = re.compile(rf'("[^"\n]+[!?])"[ \t]+({_SPEECH_VERBS})(nya|ku|mu)?\b', re.I)
_EN_DOUBLE_HEDGE_RE = re.compile(r"\bIt\s+is\s+(?:thought|believed)\s+that\s+it\s+can\s+be\s+said\s+that\b", re.I)
_EN_AS_FOR_RE = re.compile(r"\bAs\s+for\s+(he|she|they|I|we),\s+\1\b", re.I)
_EN_MARRYING_RE = re.compile(r"\b(?:is|was)\s+marrying\s+(\d+\s+(?:years|months|days)\s+ago)\b", re.I)
_EN_THE_THE_RE = re.compile(r"\bthe\s+the\b", re.I)
_EN_APOS_SPACE_RE = re.compile(r"([A-Za-z])\s+'s\b")
_EN_UNCOUNTABLE_FIXES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{bad}\b", re.I), good)
    for bad, good in (
        ("informations", "information"),
        ("advices", "advice"),
        ("equipments", "equipment"),
        ("furnitures", "furniture"),
        ("knowledges", "knowledge"),
        ("luggages", "luggage"),
    )
)
_EN_RESEARCHES_RE = re.compile(r"\b(many|several|these|some|all|the)\s+researches\b", re.I)
_JA_HALF_Q_RE = re.compile(r"([\u3040-\u30ff\u3400-\u9fff])\?")
_JA_HALF_BANG_RE = re.compile(r"([\u3040-\u30ff\u3400-\u9fff])!")
_JA_CHAN_RE = re.compile(r"[\u4e00-\u9fffァ-ヶー]ちゃん(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])")
_JA_KUN_RE = re.compile(r"[\u4e00-\u9fffァ-ヶー](?:くん|君)(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])")
_JA_SAN_RE = re.compile(r"[\u4e00-\u9fffァ-ヶー]さん(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])")
_ID_HONORIFIC_LEAK_RE = re.compile(r"\b(?:Tuan|Nyonya|Bapak|Ibu|Nona|Saudara|Saudari)\s+([A-Z][a-z]{2,20})\b")
_QE_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_QE_KANJI_RE = re.compile(r"[\u4e00-\u9fff]")
_QE_WS_RE = re.compile(r"\s+")
_QE_JA_CLEAN_RE = re.compile(r"[\s「」『』、。！？…・]")
_QE_LATIN_CLEAN_RE = re.compile(r"[^a-zà-ÿ0-9\s]")
_QE_CJK_ONLY_RE = re.compile(r"[^\u3040-\u30ff\u4e00-\u9fff]")
_QE_STRONG_PROOF_RE = re.compile(r"\b(?:proves?|conclusively|definitely)\b|証明", re.I)


@dataclass(frozen=True)
class SourceComplexityMetrics:
    score: int
    tier: str  # L1..L5
    avg_sentence_len: float
    lexical_density: float


@dataclass(frozen=True)
class DiscourseProfile:
    src_lang: str
    tgt_lang: str
    domain: str
    genre: str
    register: str
    pov: str
    allow_casual_dialogue: bool
    allow_id_pronoun_soften: bool
    narrator_id_1p: str
    reiss_type: str = "informative"
    skopos_goal: str = "Clear, accurate, natural prose calibrated to source complexity"
    translation_method: str = "balanced"
    house_mode: str = "covert"
    cultural_filter: str = "light"
    metaphor_policy: str = "adapt_stock"
    source_complexity: int = 45
    source_tier: str = "L3"
    target_complexity_band: tuple[int, int] = (24, 72)
    max_target_asl_words: int = 19
    length_budget_ratio: float | None = None
    strict_deontic_modals: bool = False


def _clamp_num(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _preserve_case(orig: str, repl: str) -> str:
    if not orig or not repl:
        return repl
    if "A" <= orig[0] <= "Z":
        return repl[0].upper() + repl[1:]
    if "a" <= orig[0] <= "z":
        return repl[0].lower() + repl[1:]
    return repl


def _count_en_syllables(word: str) -> int:
    clean = re.sub(r"[^a-z]", "", word.lower())
    if len(clean) <= 3:
        return 1
    clean = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", clean)
    clean = re.sub(r"^y", "", clean)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", clean)))


def compute_source_complexity(paragraphs: Sequence[str], src_lang: str) -> SourceComplexityMetrics:
    joined = "\n".join(p.strip() for p in paragraphs if p and p.strip())[:8000]
    if not joined:
        return SourceComplexityMetrics(score=40, tier="L2", avg_sentence_len=12.0, lexical_density=0.3)

    if src_lang == "ja":
        sents = [s.strip() for s in re.split(r"[。！？\n]+", joined) if s.strip()]
        total_chars = len(re.sub(r"\s+", "", joined))
        asl = total_chars / max(len(sents), 1)
        kanji = len(re.findall(r"[\u4e00-\u9fff]", joined))
        kanji_ratio = kanji / max(total_chars, 1)
        kango = len(re.findall(r"[\u4e00-\u9fff]{3,}", joined))
        kango_rate = kango / max(len(sents), 1)
        score = round(_clamp_num(asl * 0.72 + kanji_ratio * 110.0 + kango_rate * 7.5, 5.0, 99.0))
        lexical = round(kanji_ratio, 3)
    else:
        sents = [s.strip() for s in re.split(r"[.!?\n]+", joined) if s.strip()]
        words = re.findall(r"[A-Za-zÀ-ÿ']+", joined)
        w_count = max(len(words), 1)
        asl = w_count / max(len(sents), 1)
        if src_lang == "id":
            complex_w = sum(1 for w in words if len(re.findall(r"[aiueoAIUEO]+", w)) >= 4 or len(w) >= 10)
            ratio = complex_w / w_count
            score = round(_clamp_num(asl * 1.85 + ratio * 155.0, 5.0, 99.0))
            lexical = round(ratio, 3)
        else:
            syllables = sum(_count_en_syllables(w) for w in words)
            syl_per_word = syllables / w_count
            fk_grade = 0.39 * asl + 11.8 * syl_per_word - 15.59
            score = round(_clamp_num((fk_grade - 2.0) * 6.8, 5.0, 99.0))
            lexical = round(sum(1 for w in words if len(w) >= 8) / w_count, 3)

    if score <= 24:
        tier = "L1"
    elif score <= 49:
        tier = "L2"
    elif score <= 69:
        tier = "L3"
    elif score <= 84:
        tier = "L4"
    else:
        tier = "L5"
    return SourceComplexityMetrics(
        score=int(score),
        tier=tier,
        avg_sentence_len=round(asl, 2),
        lexical_density=lexical,
    )


def protect_format_spans(text: str) -> tuple[str, dict[str, str]]:
    """Replace immutable code, math, URLs, filenames, timestamps, and Markdown prefixes with tokens."""
    if not text:
        return text, {}
    restore_map: dict[str, str] = {}
    counter = [0]

    def _make_tok(m: re.Match[str]) -> str:
        tok = f"\u27E6F{counter[0]}\u27E7"
        restore_map[tok] = m.group(0)
        counter[0] += 1
        return tok

    shielded = _FORMAT_SHIELD_INLINE_RE.sub(_make_tok, text)
    shielded = _FORMAT_SHIELD_LINE_PREFIX_RE.sub(_make_tok, shielded)
    return shielded, restore_map


def restore_format_spans(text: str, restore_map: dict[str, str]) -> str:
    if not text or not restore_map:
        return text
    out = text
    for tok, val in reversed(list(restore_map.items())):
        out = out.replace(tok, val)
    return out


_SKOPOS_MAP: dict[str, tuple[str, str, str, str, str, str, tuple[int, int], int, float | None]] = {
    "children_ya": (
        "expressive",
        "Warm, concrete, easy-to-follow story tailored for young readers",
        "communicative",
        "covert",
        "full",
        "adapt_stock",
        (8, 38),
        13,
        None,
    ),
    "fiction_novel": (
        "expressive",
        "Immersive natural novel prose preserving author voice and cultural flavor",
        "balanced",
        "overt",
        "light",
        "preserve_image",
        (24, 60),
        18,
        None,
    ),
    "fiction_dialogue_heavy": (
        "expressive",
        "Lively character-driven dialogue with natural spoken cadence",
        "communicative",
        "overt",
        "light",
        "adapt_stock",
        (20, 52),
        16,
        None,
    ),
    "classic_literary": (
        "expressive",
        "Author-centered literary fidelity preserving rhythm, imagery, and depth",
        "semantic",
        "overt",
        "none",
        "preserve_image",
        (48, 86),
        24,
        None,
    ),
    "manga_comic_sfx": (
        "audiomedial",
        "Punchy, compact speech-bubble dialogue & crisp comic SFX matching visual space",
        "communicative",
        "overt",
        "light",
        "adapt_stock",
        (12, 42),
        11,
        1.18,
    ),
    "subtitle_script": (
        "audiomedial",
        "Concise instant-comprehension spoken lines fitting subtitle timing",
        "communicative",
        "covert",
        "full",
        "adapt_stock",
        (12, 42),
        12,
        1.08,
    ),
    "news_wire": (
        "informative",
        "Crisp objective journalistic clarity preserving attribution and hedging",
        "communicative",
        "covert",
        "full",
        "adapt_stock",
        (45, 72),
        22,
        None,
    ),
    "essay_journalism": (
        "informative",
        "Fluid, articulate editorial prose preserving argument flow and nuance",
        "balanced",
        "covert",
        "light",
        "preserve_image",
        (42, 74),
        22,
        None,
    ),
    "business_formal": (
        "operative",
        "Courteous, clear executive communication aligned to target business etiquette",
        "communicative",
        "covert",
        "full",
        "flatten_literal",
        (50, 80),
        21,
        None,
    ),
    "technical_docs": (
        "operative",
        "Exact technical accuracy, scannable instructions, and immutable code/CLI syntax",
        "semantic",
        "covert",
        "light",
        "flatten_literal",
        (52, 84),
        20,
        None,
    ),
    "academic_research": (
        "informative",
        "Scholarly rigor preserving epistemic hedging, terminology, and citations",
        "semantic",
        "overt",
        "light",
        "preserve_image",
        (65, 96),
        26,
        None,
    ),
    "legal_policy": (
        "operative",
        "Zero-drift statutory precision preserving deontic modals, clauses, and polarity",
        "semantic",
        "overt",
        "none",
        "flatten_literal",
        (78, 100),
        30,
        None,
    ),
    "general": (
        "informative",
        "Clear, accurate, natural prose calibrated to source complexity",
        "balanced",
        "covert",
        "light",
        "adapt_stock",
        (24, 72),
        19,
        None,
    ),
}


def profile_document(
    paragraphs: Sequence[str],
    src_lang: str,
    tgt_lang: str,
    tone_override: str = "auto",
    *,
    title_kind: str | None = None,
    doc_format: str | None = None,
) -> DiscourseProfile:
    sample = [p.strip() for p in paragraphs if p and p.strip()][:36]
    joined = "\n".join(sample)
    total = max(len(sample), 1)
    quote_lines = sum(
        1 for p in sample if _QUOTE_LINE_RE.search(p) or re.search(r'[「『"“][^」』"”]{2,}[」』"”]', p)
    )
    dialogue_ratio = quote_lines / total
    ja_polite_ratio = (
        sum(1 for p in sample if _JA_POLITE_END_RE.search(p)) / total if src_lang == "ja" else 0.0
    )

    legal_hits = len(_LEGAL_RE.findall(joined))
    deontic_hits = len(_DEONTIC_RE.findall(joined))
    tech_hits = len(_TECH_RE.findall(joined))
    academic_hits = len(_ACADEMIC_RE.findall(joined))
    business_hits = len(_BUSINESS_RE.findall(joined))
    news_hits = len(_NEWS_RE.findall(joined))
    school_hits = len(_SCHOOL_RE.findall(joined))
    archaic_hits = len(_ARCHAIC_RE.findall(joined))
    comic_hits = len(_COMIC_SFX_RE.findall(joined))
    complexity = compute_source_complexity(sample, src_lang)

    genre = "general"
    register = "literary_neutral"
    domain = "slice_of_life"

    school_thresh = 1 if len(sample) <= 6 else 2
    if doc_format in ("srt", "vtt", "ass", "ssa"):
        genre, register = "subtitle_script", "intimate_casual"
    elif title_kind == "komik" or doc_format == "image":
        genre, register = "manga_comic_sfx", "intimate_casual"
    elif legal_hits >= 2 or (legal_hits >= 1 and deontic_hits >= 2):
        genre, register, domain = "legal_policy", "formal_legal_tech", "formal_nonfiction"
    elif (tech_hits >= 3 or "```" in joined) and dialogue_ratio < 0.2:
        genre, register, domain = "technical_docs", "formal_legal_tech", "formal_nonfiction"
    elif academic_hits >= 2 and dialogue_ratio < 0.2:
        genre, register, domain = "academic_research", "formal_academic", "formal_nonfiction"
    elif business_hits >= 1 and dialogue_ratio < 0.25:
        genre, register, domain = "business_formal", "formal_academic", "workplace_modern"
    elif news_hits >= 2 and dialogue_ratio < 0.25:
        genre, register, domain = "news_wire", "semi_formal_editorial", "formal_nonfiction"
    elif comic_hits >= 2 and total <= 24:
        genre, register = "manga_comic_sfx", "intimate_casual"
    elif dialogue_ratio >= 0.14 or school_hits >= school_thresh or archaic_hits >= 2 or _JA_1P_CASUAL_RE.search(joined):
        genre = "fiction_dialogue_heavy" if dialogue_ratio >= 0.35 else "fiction_novel"
        if archaic_hits >= 2:
            domain, register = "historical_fantasy", "novel_archaic"
        elif school_hits >= school_thresh:
            domain = "school_peer"
            register = "intimate_casual" if ja_polite_ratio < 0.45 else "literary_neutral"
        elif complexity.tier in ("L4", "L5") and dialogue_ratio < 0.2:
            genre, register = "classic_literary", "literary_neutral"
        else:
            register = "intimate_casual" if ja_polite_ratio < 0.35 else "literary_neutral"
    elif len(joined) >= 240 and dialogue_ratio < 0.08:
        genre, register, domain = "essay_journalism", "semi_formal_editorial", "formal_nonfiction"

    if tone_override == "formal":
        register = "formal_legal_tech" if (legal_hits >= 2 or tech_hits >= 3) else "formal_academic"
    elif tone_override == "novel" and genre not in ("legal_policy", "technical_docs", "academic_research"):
        genre = "fiction_dialogue_heavy" if dialogue_ratio >= 0.35 else "fiction_novel"
        register = "literary_neutral"
    elif (
        tone_override == "casual"
        and legal_hits < 2
        and not (legal_hits >= 1 and deontic_hits >= 2)
        and academic_hits < 2
        and tech_hits < 3
        and "```" not in joined
    ):
        genre, register = "fiction_dialogue_heavy", "intimate_casual"

    is_formal = register in ("formal_academic", "formal_legal_tech") or genre in (
        "legal_policy",
        "academic_research",
        "technical_docs",
        "business_formal",
    )
    pov = "1P_CASUAL" if _JA_1P_CASUAL_RE.search(joined) else "3P_LIMITED"
    allow_casual = (not is_formal) and register != "novel_archaic" and genre in (
        "children_ya",
        "fiction_novel",
        "fiction_dialogue_heavy",
        "manga_comic_sfx",
        "subtitle_script",
    )
    allow_soften = (
        tgt_lang == "id"
        and (not is_formal)
        and business_hits == 0
        and genre in ("children_ya", "fiction_novel", "fiction_dialogue_heavy", "manga_comic_sfx", "subtitle_script")
        and register in ("intimate_casual", "literary_neutral")
        and ja_polite_ratio < 0.45
    )
    narrator_1p = "saya" if is_formal else ("aku" if pov == "1P_CASUAL" or allow_soften else "preserve")

    reiss, goal, method, house, cfilter, metaphor, band, asl, len_ratio = _SKOPOS_MAP[genre]
    g_min, g_max = band
    t_min = round(_clamp_num(min(complexity.score - 8, g_max - 10), g_min, g_max))
    t_max = round(_clamp_num(max(complexity.score + 8, g_min + 10), g_min, g_max))
    strict_deontic = genre == "legal_policy" or (genre == "technical_docs" and deontic_hits >= 1)

    return DiscourseProfile(
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        domain=domain,
        genre=genre,
        register=register,
        pov=pov,
        allow_casual_dialogue=allow_casual,
        allow_id_pronoun_soften=allow_soften,
        narrator_id_1p=narrator_1p,
        reiss_type=reiss,
        skopos_goal=goal,
        translation_method=method,
        house_mode=house,
        cultural_filter=cfilter,
        metaphor_policy=metaphor,
        source_complexity=complexity.score,
        source_tier=complexity.tier,
        target_complexity_band=(int(t_min), int(t_max)),
        max_target_asl_words=asl,
        length_budget_ratio=len_ratio,
        strict_deontic_modals=strict_deontic,
    )


def build_literary_system_prompt(src_label: str, tgt_label: str, profile: DiscourseProfile) -> str:
    if profile.tgt_lang == "id":
        if profile.genre == "legal_policy":
            reg_note = (
                "Maintain statutory Indonesian (EYD V & KBBI VI). Preserve deontic modals "
                "(shall -> wajib, shall not/must not -> dilarang, may -> dapat) and clause numbers without casualizing."
            )
        elif profile.register in ("formal_academic", "formal_legal_tech"):
            reg_note = (
                "Maintain formal Indonesian (EYD V & KBBI VI: praktik, risiko, analisis, sistem, kualitas, aktivitas), "
                "preserve epistemic hedging, citations, CLI/code tokens, and formal connectors without casualizing."
            )
        elif profile.register == "novel_archaic" or profile.genre == "classic_literary":
            reg_note = (
                "Use dignified literary/historical Indonesian (aku/engkau/kau/ia, tiada/hendak). "
                "Forbid modern urban slang."
            )
        elif profile.genre in ("manga_comic_sfx", "subtitle_script"):
            reg_note = (
                "Write punchy, compact spoken Indonesian fitting speech bubbles or subtitle timing "
                "with natural interjections and concise comic SFX."
            )
        else:
            reg_note = (
                "Write natural, expressive Indonesian prose and live dialogue (EYD V & KBBI VI): flowing narration "
                "(aku/ia, active verbs), authentic speech inside quotes, varied speech verbs "
                "(ujar/sahut/tanya/gumam/bisik/seru), and NEVER translate Japanese classmate -san/-kun/-chan into Tuan/Nyonya."
            )
        anti_calque = (
            "Avoid stiff calques: non-interrogative 'di mana'/'yang mana', 'adalah merupakan', "
            "'tidak bisa membantu tetapi', redundant 'sebuah' before abstract nouns, "
            "'memiliki mata/rambut' (use bermata/berambut), and 'dibuka olehnya' (use dibukanya). "
            "Apply EYD V (di sini, apa pun, Rp50.000, Maha Esa)."
        )
    elif profile.tgt_lang == "en":
        reg_note = (
            f"Write natural, idiomatic English matching register={profile.register}. "
            "Master articles, aspect, and uncountable nouns (information, advice, equipment, research)."
        )
        anti_calque = "Avoid 'As for X,' topic-fronting, double hedging, and unnatural literalisms."
    else:
        reg_note = f"Write natural Japanese matching genre={profile.genre} and register={profile.register}."
        anti_calque = "Omit redundant subject pronouns once established and avoid inanimate passive calques."

    budget_note = (
        f" Keep output concise (target <= {round(profile.length_budget_ratio * 100)}% of source length)."
        if profile.length_budget_ratio
        else ""
    )
    return (
        f"You are a master translator producing accurate, natural, author-faithful {tgt_label} "
        f"from {src_label} without summarizing, omitting, or hallucinating.\n"
        f"[Skopos] domain={profile.domain}, genre={profile.genre}, reiss={profile.reiss_type}, method={profile.translation_method}, "
        f"house={profile.house_mode}, cultural_filter={profile.cultural_filter}, pov={profile.pov}. "
        f"Goal: {profile.skopos_goal}. Match reader complexity to source tier {profile.source_tier} "
        f"(band {profile.target_complexity_band[0]}-{profile.target_complexity_band[1]}, "
        f"avg sentence <= {profile.max_target_asl_words} words).{budget_note}\n"
        f"[Register & Grammar] {reg_note} {anti_calque}\n"
        f"[Fidelity & Format] Ensure 100% of every item is in {tgt_label}. Keep segments already in {tgt_label} intact. "
        "Preserve all numbers, dates, currencies, SI units, polarity, Markdown/code/LaTeX/tables/URLs, and placeholders ([[E1]], [[E2]]) verbatim. "
        "NEVER emit U+2014 em-dashes; use commas, ellipses ('...'), or crisp sentence breaks.\n"
        'Reply ONLY with JSON: {"translations": [{"id": 1, "text": "..."}]} matching input ids.'
    )


def build_self_repair_prompt(
    src_label: str,
    tgt_label: str,
    profile: DiscourseProfile,
    items: Sequence[dict[str, object]],
) -> str:
    """Build a bounded single-pass QE self-repair prompt mirroring web/src/lib/literaryPolish.ts."""
    lines = [
        f"You are a senior {tgt_label} translation editor repairing specific MQM/QE defects from {src_label}.",
        f"[Profile] genre={profile.genre}, register={profile.register}, goal={profile.skopos_goal}.",
        "Fix ONLY the listed defects while keeping every number, unit, glossary term, polarity, and formatting span verbatim.",
        "NEVER emit U+2014 em-dashes. Reply ONLY with JSON: {\"translations\": [{\"id\": 1, \"text\": \"...\"}]}.",
        "",
        "Items to repair:",
    ]
    for it in items:
        lines.append(
            f"- id={it['id']} | defects={it['defects']} | source={it['src']} | draft={it['draft']}"
        )
    return "\n".join(lines)


def sanitize_zero_em_dash(text: str, tgt_lang: str) -> str:
    if not text:
        return text
    shielded, restore_map = protect_format_spans(text)
    if tgt_lang == "ja":
        out = shielded.replace("\u2014", "……")
        out = _JA_CJK_SPACE_RE.sub(r"\1", out)
        return restore_format_spans(_WS_COLLAPSE_RE.sub(" ", out).strip(), restore_map)

    out = shielded.replace("\u3000", " ")
    out = _EMDASH_PAIR_RE.sub(r", \1, ", out)
    out = _EMDASH_TRAIL_RE.sub(r"\1...\2", out)
    out = _EMDASH_ANY_RE.sub(", ", out)
    out = _DASH_RUN_RE.sub("...", out)
    out = _OPEN_BACKTICK_QUOTE_RE.sub('"', out)
    out = _CLOSE_SINGLE_QUOTE_RE.sub('"', out)
    out = out.replace("“", '"').replace("”", '"')
    out = _ELLIPSIS_RUN_RE.sub("...", out)
    out = _BANG_Q_DOT_RE.sub(r"\1", out)
    out = _DOUBLE_COMMA_RE.sub(",", out)
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    out = _SPACE_AFTER_BANG_Q_RE.sub(r"\1 ", out)

    def _safe_dot_space(m: re.Match[str]) -> str:
        word = m.group(1)
        ctx = out[max(0, m.start() - 8) : m.start() + len(word)]
        if _KNOWN_DOT_ABBREV_RE.search(ctx):
            return m.group(0)
        return f"{word}. "

    out = _GLUED_DOT_CAP_RE.sub(_safe_dot_space, out)
    out = _WS_COLLAPSE_RE.sub(" ", out).strip()
    return restore_format_spans(out, restore_map)


def _split_spans(text: str) -> list[tuple[str, str]]:
    rough: list[tuple[str, str]] = []
    pos = 0
    for m in _PROTECTED_SPAN_RE.finditer(text):
        if m.start() > pos:
            rough.append(("narration", text[pos : m.start()]))
        rough.append(("protected", m.group(0)))
        pos = m.end()
    if pos < len(text):
        rough.append(("narration", text[pos:]))

    spans: list[tuple[str, str]] = []
    for kind, chunk in rough:
        if kind == "protected":
            spans.append((kind, chunk))
            continue
        qpos = 0
        for qm in _QUOTE_SPAN_RE.finditer(chunk):
            if qm.start() > qpos:
                spans.append(("narration", chunk[qpos : qm.start()]))
            spans.append(("dialogue", qm.group(0)))
            qpos = qm.end()
        if qpos < len(chunk):
            spans.append(("narration", chunk[qpos:]))
    return spans


def _naturalize_id_span(
    text: str,
    span_kind: str,
    profile: DiscourseProfile,
    src_text: str,
    had_ja_keigo: bool,
    neg_delta: list[int],
) -> str:
    t = text
    is_formal = profile.register in ("formal_academic", "formal_legal_tech") or profile.genre in (
        "legal_policy",
        "academic_research",
        "technical_docs",
        "business_formal",
    )
    is_fiction = profile.genre in (
        "children_ya",
        "fiction_novel",
        "fiction_dialogue_heavy",
        "manga_comic_sfx",
        "subtitle_script",
    )

    t = _ID_TEMPAT_DIMANA_RE.sub(lambda m: _preserve_case(m.group(0), "tempat"), t)
    t = _ID_LOC_DIMANA_RE.sub(r"\1 tempat", t)
    t = _ID_TIME_DIMANA_RE.sub(r"\1 ketika", t)
    if profile.genre != "legal_policy":
        t = _ID_STATE_DIMANA_RE.sub(r"\1 saat", t)
    t = _ID_YANG_MANA_RE.sub(" yang", t)
    t = _ID_ADALAH_MERUPAKAN_RE.sub(
        lambda m: _preserve_case(m.group(0), "adalah" if is_fiction else "merupakan"),
        t,
    )
    t = _ID_DIKARENAKAN_OLEH_RE.sub(
        lambda m: _preserve_case(m.group(0), "disebabkan oleh" if is_formal else "karena"),
        t,
    )
    t = _ID_FAKTA_BAHWA_RE.sub(lambda m: _preserve_case(m.group(0), "karena"), t)
    t = _ID_CANNOT_HELP_RE.sub(
        lambda m: _preserve_case(
            m.group(0),
            f"{'tak kuasa' if is_fiction else 'tak bisa'} menahan diri untuk {m.group(1)}",
        ),
        t,
    )
    if not is_formal:

        def _double_neg_repl(m: re.Match[str]) -> str:
            neg_delta[0] -= 1
            return _preserve_case(m.group(0), f"mau tak mau {m.group(1)}")

        t = _ID_DOUBLE_NEG_RE.sub(_double_neg_repl, t)
    t = _ID_TELAH_TIDAK_PERNAH_RE.sub(lambda m: _preserve_case(m.group(0), "belum pernah"), t)
    t = _ID_TIDAK_TERBATAS_RE.sub(lambda m: _preserve_case(m.group(0), f"belum tentu {m.group(1)}"), t)
    if not is_formal:
        t = _ID_INVESTIGASI_RE.sub(lambda m: _preserve_case(m.group(0), "menyelidiki"), t)
        t = _ID_PENGAMATAN_RE.sub(lambda m: _preserve_case(m.group(0), "mengamati"), t)
    t = _ID_KEPUTUSAN_RE.sub(lambda m: _preserve_case(m.group(0), "memutuskan untuk"), t)
    t = _ID_SEBUAH_ABSTRACT_RE.sub(lambda m: _preserve_case(m.group(0), m.group(1)), t)

    def _body_repl(m: re.Match[str]) -> str:
        bp = m.group(1).lower()
        adj = m.group(2)
        if adj.lower() in _BODY_COMPOUND_BLOCK:
            return m.group(0)
        out_phrase = f"berambut {adj}" if bp == "rambut" else f"ber{bp} {adj}"
        return _preserve_case(m.group(0), out_phrase)

    t = _ID_BODY_PART_RE.sub(_body_repl, t)
    t = _ID_ADALAH_IMP_RE.sub(lambda m: f"{m.group(1)[0].upper()}{m.group(1)[1:]} {m.group(2)}", t)
    t = _ID_OLEHNYA_RE.sub(r"\1nya", t)
    t = _ID_DIHUJANI_RE.sub(lambda m: _preserve_case(m.group(0), "kehujanan"), t)
    t = _ID_MESKIPUN_TAPI_RE.sub(r"\1 \2, ", t)
    t = _ID_KARENA_MAKA_RE.sub(r"\1 \2, ", t)
    t = _ID_DALAM_RANGKA_RE.sub(lambda m: _preserve_case(m.group(0), "untuk"), t)
    t = _ID_PARA_REDUPL_RE.sub(
        lambda m: m.group(0) if m.group(2).lower() in _REDUPL_BLOCK else f"{m.group(1)} {m.group(2)}",
        t,
    )
    t = _ID_SANGAT_SEKALI_RE.sub(lambda m: _preserve_case(m.group(0), f"sangat {m.group(1)}"), t)
    t = _ID_JATUH_CINTA_RE.sub(lambda m: _preserve_case(m.group(0), "jatuh cinta pada"), t)
    t = _ID_LOOKING_FWD_RE.sub(lambda m: _preserve_case(m.group(0), "menantikan"), t)

    # EYD V & KBBI VI rules (universal across registers)
    t = _ID_MAHAESA_RE.sub(lambda m: _preserve_case(m.group(0), "Maha Esa"), t)
    t = _ID_MAHA_SPACED_RE.sub(lambda m: _preserve_case(m.group(0), f"Maha{m.group(1).lower()}"), t)
    t = _ID_DI_LOC_RE.sub(lambda m: _preserve_case(m.group(0), f"di {m.group(1).lower()}"), t)
    t = _ID_KE_LOC_RE.sub(lambda m: _preserve_case(m.group(0), f"ke {m.group(1).lower()}"), t)
    t = _ID_PUN_RE.sub(lambda m: _preserve_case(m.group(0), f"{m.group(1).lower()} pun"), t)
    t = _ID_DIMANAPUN_RE.sub(lambda m: _preserve_case(m.group(0), "di mana pun"), t)
    t = _ID_KEMANAPUN_RE.sub(lambda m: _preserve_case(m.group(0), "ke mana pun"), t)
    for pat, repl in _KBBI_FIXES:
        t = pat.sub(lambda m, r=repl: _preserve_case(m.group(0), r), t)
    t = _ID_RP_SPACE_RE.sub(r"Rp\1", t)
    t = _ID_RP_DOT_RE.sub(r"Rp\1", t)
    # Purwo (1984) Indonesian deixis: unconditional for kepada/oleh; clause-final guarded for untuk/dari/dengan/pada
    t = _ID_KEPADA_IA_RE.sub(lambda m: _preserve_case(m.group(0), f"{m.group(1).lower()}nya"), t)
    t = _ID_DENGAN_IA_RE.sub(lambda m: _preserve_case(m.group(0), f"{m.group(1).lower()}nya"), t)
    if profile.strict_deontic_modals and profile.src_lang == "en" and _EN_SHALL_MUST_POS_RE.search(src_text):
        t = _ID_PARTY_AKAN_RE.sub(r"\1 wajib", t)
    if profile.strict_deontic_modals and profile.src_lang == "en" and _EN_SHALL_MUST_NEG_RE.search(src_text):
        t = _ID_PARTY_TDK_AKAN_RE.sub(r"\1 dilarang", t)

    # Source-anchored JA idiom, yojijukugo & mimetic rescue (full TS/Python parity!)
    if profile.src_lang == "ja" and src_text:
        for ja_pat, lit_pat, nat_repl in _JA_IDIOM_GTX_ID_FIXES:
            if ja_pat.search(src_text):
                def _idiom_repl(m: re.Match[str], repl: str = nat_repl) -> str:
                    resolved = repl.replace("$1", m.group(1)) if ("$1" in repl and m.lastindex) else repl
                    nxt = _preserve_case(m.group(0), resolved)
                    neg_delta[0] += _count_negations(nxt, "id") - _count_negations(m.group(0), "id")
                    return nxt
                t = lit_pat.sub(_idiom_repl, t)
        for ja_pat, romaji_pat, nat_id in _JA_MIMETIC_ID_FIXES:
            if ja_pat.search(src_text) and romaji_pat.search(t):
                t = romaji_pat.sub(lambda m, r=nat_id: _preserve_case(m.group(0), r), t)

    if is_fiction and not is_formal:
        if span_kind == "narration":
            t = _ID_SEDANGKAN_RE.sub(r"Soal \1, ", t)
        t = _ID_OLEH_KARENA_RE.sub("Jadi, " if span_kind == "dialogue" else "Karena itu, ", t)
        t = _ID_DGN_KATA_LAIN_RE.sub("Maksudnya, " if span_kind == "dialogue" else "Artinya, ", t)
        has_superior = bool(_ID_SUPERIOR_RE.search(t))
        if profile.allow_id_pronoun_soften and not had_ja_keigo and not has_superior:
            t = _ID_KEPADA_SAYA_RE.sub(lambda m: _preserve_case(m.group(0), "padaku"), t)
            t = _ID_UNTUK_SAYA_RE.sub(lambda m: _preserve_case(m.group(0), "untukku"), t)
            t = _ID_SAYA_CAP_RE.sub("Aku", t)
            t = _ID_SAYA_LOW_RE.sub("aku", t)
            if span_kind == "dialogue":
                t = _ID_ANDA_CAP_RE.sub("Kamu", t)
                t = _ID_ANDA_LOW_RE.sub("kamu", t)
        elif (
            span_kind == "dialogue"
            and not had_ja_keigo
            and not has_superior
            and _ID_AKU_ANY_RE.search(t)
            and _ID_ANDA_ANY_RE.search(t)
        ):
            t = _ID_ANDA_CAP_RE.sub("Kamu", t)
            t = _ID_ANDA_LOW_RE.sub("kamu", t)
    return t


def _naturalize_en_span(text: str) -> str:
    t = _EN_DOUBLE_HEDGE_RE.sub(lambda m: _preserve_case(m.group(0), "It appears that"), text)
    t = _EN_AS_FOR_RE.sub(lambda m: m.group(1)[0].upper() + m.group(1)[1:], t)
    t = _EN_MARRYING_RE.sub(r"got married \1", t)
    t = _EN_THE_THE_RE.sub("the", t)
    t = _EN_APOS_SPACE_RE.sub(r"\1's", t)
    for pat, good in _EN_UNCOUNTABLE_FIXES:
        t = pat.sub(lambda m, g=good: _preserve_case(m.group(0), g), t)
    t = _EN_RESEARCHES_RE.sub(r"\1 research", t)
    return t


def _naturalize_ja_span(text: str) -> str:
    t = _JA_HALF_Q_RE.sub(r"\1？", text)
    t = _JA_HALF_BANG_RE.sub(r"\1！", t)
    t = t.replace("とても非常に", "非常に").replace("すごくとても", "とても")
    return t


def _fix_id_dialogue_punctuation(text: str) -> str:
    # Rule 1: Period before closing quote followed by speech verb -> comma (ellipsis-safe via (?<!\.))
    out = _ID_DIALOG_PERIOD_RE.sub(
        lambda m: f'{m.group(1)}," {m.group(2).lower()}{m.group(3) or ""}',
        text,
    )
    # Rule 2: Exclamation/question mark inside quote followed by capitalized speech verb -> lowercase verb
    out = _ID_DIALOG_BANG_RE.sub(
        lambda m: f'{m.group(1)}" {m.group(2).lower()}{m.group(3) or ""}',
        out,
    )
    return out


def _count_negations(text: str, tgt_lang: str) -> int:
    if tgt_lang == "id":
        return len(_ID_NEG_RE.findall(text))
    if tgt_lang == "en":
        return len(_EN_NEG_RE.findall(text))
    return len(_JA_NEG_RE.findall(text))


def _normalized_num_multiset(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for raw in _NUM_RE.findall(text):
        norm = _THOUSAND_SEP_RE.sub("", raw).replace(",", ".")
        counts[norm] += 1
    return counts


def _extract_structural_prefix(line: str) -> str:
    m = _STRUCTURAL_PREFIX_RE.match(line)
    return m.group(1).strip() if m else ""


def verify_meaning_conservation(
    pre_nat: str,
    post_nat: str,
    tgt_lang: str,
    expected_neg_delta: int = 0,
    glossary_values: Sequence[str] = (),
    *,
    strict_deontic_modals: bool = False,
    shielded_post: str | None = None,
) -> bool:
    if not post_nat.strip() and pre_nat.strip():
        return False
    if "\u2014" in post_nat:
        chk_shielded = shielded_post if shielded_post is not None else protect_format_spans(post_nat)[0]
        if "\u2014" in chk_shielded:
            return False
    if _PLACEHOLDER_LEAK_RE.search(post_nat):
        return False
    pre_lines = pre_nat.split("\n")
    post_lines = post_nat.split("\n")
    if len(pre_lines) != len(post_lines):
        return False
    if len(pre_nat) >= 24:
        ratio = len(post_nat) / max(len(pre_nat), 1)
        if ratio < 0.55 or ratio > 1.55:
            return False
    pre_nums = _normalized_num_multiset(pre_nat)
    if pre_nums:
        post_nums = _normalized_num_multiset(post_nat)
        for num, needed in pre_nums.items():
            if post_nums[num] < needed:
                return False
    pre_units = _UNIT_CURRENCY_RE.findall(pre_nat)
    if pre_units and len(_UNIT_CURRENCY_RE.findall(post_nat)) < len(pre_units):
        return False
    for val in glossary_values:
        if len(val) >= 2 and val in pre_nat and val not in post_nat:
            return False
    if _count_negations(post_nat, tgt_lang) - _count_negations(pre_nat, tgt_lang) != expected_neg_delta:
        return False
    for pre_l, post_l in zip(pre_lines, post_lines):
        if "|" in pre_l:
            pre_pipes = pre_l.count("|")
            if pre_pipes >= 2 and pre_pipes != post_l.count("|"):
                return False
        pre_pref = _extract_structural_prefix(pre_l)
        if pre_pref and _extract_structural_prefix(post_l) != pre_pref:
            return False
    if strict_deontic_modals:
        pre_mod = len(_DEONTIC_MANDATORY_RE.findall(pre_nat))
        if pre_mod > 0 and len(_DEONTIC_MANDATORY_RE.findall(post_nat)) < pre_mod:
            return False
    return True


_JA_IDIOM_GTX_ID_FIXES: tuple[tuple[re.Pattern[str], re.Pattern[str], str], ...] = (
    (re.compile(r"胸を(?:なで|撫で)下ろ"), re.compile(r"\bmengusap dada(?:nya)? ke bawah\b", re.I), "menghela napas lega"),
    (re.compile(r"背筋が凍る|鳥肌が立つ"), re.compile(r"\btulang belakang(?:nya|ku)? membeku\b", re.I), "bulu kuduknya meremang"),
    (re.compile(r"生唾を飲み込"), re.compile(r"\bmenelan ludah mentah\b", re.I), "menelan ludah dengan gugup"),
    (re.compile(r"頭が真っ白"), re.compile(r"\bkepala(?:nya|ku)? menjadi putih(?: bersih)?\b", re.I), "pikirannya mendadak kosong"),
    (re.compile(r"仕方がない|しょうがない"), re.compile(r"\btidak ada cara(?:\s+lain)?(?=[.!,?]|$)", re.I), "mau bagaimana lagi"),
    (re.compile(r"とは限らない"), re.compile(r"\btidak terbatas pada (bagus|baik|benar|salah|mahal|murah|mudah|sulit)\b", re.I), "belum tentu $1"),
    (re.compile(r"腹を(?:括|くく)"), re.compile(r"\bmengikat perut(?:nya|ku)?\b", re.I), "membulatkan tekad"),
    (re.compile(r"鼻で笑"), re.compile(r"\btertawa dengan hidung(?:nya)?\b", re.I), "mendengus sinis"),
    (re.compile(r"一期一会"), re.compile(r"\bsatu periode satu pertemuan\b", re.I), "pertemuan sekali seumur hidup"),
    (re.compile(r"一石二鳥"), re.compile(r"\bsatu batu dua burung\b", re.I), "sekali langkah dua hasil tercapai"),
    (re.compile(r"井の中の蛙"), re.compile(r"\bkatak di dalam sumur\b", re.I), "bagai katak dalam tempurung"),
    (re.compile(r"覆水盆に返らず"), re.compile(r"\bair yang tumpah tidak kembali ke nampan\b", re.I), "nasi sudah menjadi bubur"),
)

_JA_MIMETIC_ID_FIXES: tuple[tuple[re.Pattern[str], re.Pattern[str], str], ...] = (
    (re.compile(r"ドキドキ|どきどき"), re.compile(r"\bdoki[-\s]?doki\b", re.I), "berdebar kencang"),
    (re.compile(r"ワクワク|わくわく"), re.compile(r"\bwaku[-\s]?waku\b", re.I), "penuh semangat"),
    (re.compile(r"ハラハラ|はらはら"), re.compile(r"\bhara[-\s]?hara\b", re.I), "cemas bukan main"),
    (re.compile(r"ニヤリ|にやり"), re.compile(r"\bniyari\b", re.I), "menyeringai tipis"),
    (re.compile(r"クスクス|くすくす"), re.compile(r"\bkusu[-\s]?kusu\b", re.I), "terkekeh pelan"),
    (re.compile(r"ボロボロ|ぼろぼろ"), re.compile(r"\bboro[-\s]?boro\b", re.I), "compang-camping"),
    (re.compile(r"ギリギリ|ぎりぎり"), re.compile(r"\bgiri[-\s]?giri\b", re.I), "nyaris saja"),
    (re.compile(r"ガタガタ|がたがた"), re.compile(r"\bgata[-\s]?gata\b", re.I), "gemetar hebat"),
    (re.compile(r"シーン|しーん"), re.compile(r"\bshiin\b", re.I), "hening seketika"),
)

_JA_SONKEIGO_RE = re.compile(
    r"(?:おっしゃ(?:る|いま|った|って)|いらっしゃ(?:る|いま|った|って)|ご覧にな|召し上が|ご存じ|なさ(?:る|いま|った|って)|お[\u4e00-\u9fff]{1,3}にな(?:る|り|った)|ご[\u4e00-\u9fff]{2,4}にな(?:る|り|った))"
)
_JA_KENJOUGO_RE = re.compile(
    r"(?:申し上げ|いたし(?:ます|ました)|参り(?:ます|ました)|伺(?:い|いま|った)|拝見|存じ上げ|恐れ入(?:り|る)|いただけ(?:ます|る|ません)|させていただ)"
)
_JA_TEINEIGO_RE = re.compile(
    r"(?:です|ます|ました|でした|ません|ましょう|ございます|申し訳|お客様|ください)(?:か|よ|ね|よね|かね|わ|な|ぞ|さ|けど|けれど|が|から|ので)?(?=[。！？!?…」』\"\s、]|$)"
)
_JA_BIKAGO_ONLY_RE = re.compile(r"(?:ご飯|お茶|お酒|お金|お菓子|お水|お花|お弁当|お肉|お魚|お皿|お風呂|お手洗い)")


@dataclass(frozen=True)
class JaKeigoInfo:
    tier: str
    elevates_referent: bool
    humbles_speaker: bool
    locks_polite_register: bool


def classify_ja_keigo(src_line: str) -> JaKeigoInfo:
    """Bunka Shingikai (2007) 5-tier Japanese honorific classifier (bikago is register-neutral)."""
    s = (src_line or "").strip()
    if not s:
        return JaKeigoInfo("plain", False, False, False)
    elev = bool(_JA_SONKEIGO_RE.search(s))
    humble = bool(_JA_KENJOUGO_RE.search(s))
    if elev:
        return JaKeigoInfo("sonkeigo", True, humble, True)
    if humble:
        return JaKeigoInfo("kenjougo", False, True, True)
    if _JA_TEINEIGO_RE.search(s):
        return JaKeigoInfo("teineigo", False, False, True)
    if _JA_BIKAGO_ONLY_RE.search(s):
        return JaKeigoInfo("bikago", False, False, False)
    return JaKeigoInfo("plain", False, False, False)


_JA_PEER_HONORIFIC_RE = re.compile(r"[\u4e00-\u9fffァ-ヶー](?:さん|くん|君|ちゃん)(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])")
_JA_LORD_HONORIFIC_RE = re.compile(r"(?:様|さま|殿|どの|旦那|奥様|お嬢様|陛下|殿下)")


def repair_gtx_honorific_leaks(text: str, src_line: str, profile: DiscourseProfile) -> str:
    if (
        profile.src_lang != "ja"
        or profile.tgt_lang != "id"
        or profile.domain in ("historical_fantasy", "formal_nonfiction")
    ):
        return text
    if not _JA_PEER_HONORIFIC_RE.search(src_line or "") or _JA_LORD_HONORIFIC_RE.search(src_line or ""):
        return text
    is_chan = bool(_JA_CHAN_RE.search(src_line))
    is_kun = bool(_JA_KUN_RE.search(src_line))
    has_san = bool(_JA_SAN_RE.search(src_line))
    suffix = "-chan" if (is_chan and not has_san) else ("-kun" if (is_kun and not has_san) else "-san")
    return _ID_HONORIFIC_LEAK_RE.sub(rf"\1{suffix}", text)


_KANJI_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_SMALL = {"十": 10, "百": 100, "千": 1000}
_KANJI_BIG = {"万": 10_000, "億": 100_000_000}
_KANJI_NUM_RE = re.compile(r"[一二三四五六七八九十百千万億〇零]{2,}|[三四五六七八九](?=[人日回個本枚冊歳年分時円万億])")
_KANJI_LEXICAL_IDIOMS_RE = re.compile(r"(?:万一|一切|一般|一生|一時|一斉|一目|一同|一方|一応|十分|百発百中|一石二鳥|一期一会|十人十色|一目瞭然|一朝一夕|四面楚歌|七転び八起き)")
_DEONTIC_LATTICE = {
    "prohibition": {
        "en": re.compile(r"\b(?:SHALL\s+NOT|MUST\s+NOT|PROHIBITED|FORBIDDEN|MAY\s+NOT)\b", re.I),
        "id": re.compile(r"\b(?:dilarang|tidak\s+boleh|haram)\b", re.I),
        "ja": re.compile(r"(?:してはならない|してはいけません|禁止する|禁止される)"),
    },
    "obligation": {
        "en": re.compile(r"\b(?:SHALL(?!\s+NOT)|MUST(?!\s+NOT)|REQUIRED\s+TO)\b", re.I),
        "id": re.compile(r"\b(?:wajib|harus|diwajibkan)\b", re.I),
        "ja": re.compile(r"(?:しなければならない|しなければなりません|義務付ける|ものとする)"),
    },
    "permission": {
        "en": re.compile(r"\b(?:MAY(?!\s+NOT)|may(?!\s+not)|PERMITTED\s+TO|ENTITLED\s+TO|permitted\s+to|entitled\s+to)\b"),
        "id": re.compile(r"\b(?:dapat|berhak|diperbolehkan|boleh)\b", re.I),
        "ja": re.compile(r"(?:ことができる|してよい|許可される)"),
    },
    "recommendation": {
        "en": re.compile(r"\b(?:SHOULD(?!\s+NOT)|RECOMMENDED)\b", re.I),
        "id": re.compile(r"\b(?:sebaiknya|disarankan|dianjurkan|seyogianya)\b", re.I),
        "ja": re.compile(r"(?:すべきである|することが望ましい|推奨される)"),
    },
}
_ACADEMIC_HEDGE_SRC_RE = re.compile(
    r"\b(?:suggests?|indicates?|may\s+(?:indicate|suggest|imply)|appears?\s+to|could\s+be|tends?\s+to|potentially)\b|示唆され|と思われる|可能性がある|考えられる",
    re.I,
)
_ACADEMIC_BOOSTER_TGT_RE = re.compile(
    r"\b(?:membuktikan|terbukti\s+pasti|pasti\s+menunjukkan|proves?\s+conclusively|undoubtedly\s+proves?|definitely\s+proves?)\b|証明している|確実に証明",
    re.I,
)


def _parse_kanji_num(raw: str) -> int | None:
    if raw and re.fullmatch(r"[一二三四五六七八九〇零]{2,}", raw):
        acc = 0
        for ch in raw:
            acc = acc * 10 + _KANJI_DIGITS[ch]
        return acc if acc > 0 else None
    total = 0
    section = 0
    digit = 0
    seen = False
    for ch in raw:
        if ch in _KANJI_DIGITS:
            digit = _KANJI_DIGITS[ch]
            seen = True
        elif ch in _KANJI_SMALL:
            section += (1 if digit == 0 else digit) * _KANJI_SMALL[ch]
            digit = 0
            seen = True
        elif ch in _KANJI_BIG:
            section += digit
            total += (1 if section == 0 else section) * _KANJI_BIG[ch]
            section = 0
            digit = 0
            seen = True
        else:
            return None
    val = total + section + digit
    return val if (seen and val > 0) else None


def _extract_canonical_nums(text: str) -> Counter[str]:
    norm = text.translate(_FULLWIDTH_DIGITS_TRANS)
    counts = _normalized_num_multiset(norm)
    without_idioms = _KANJI_LEXICAL_IDIOMS_RE.sub(" ", norm)
    for kh in _KANJI_NUM_RE.findall(without_idioms):
        val = _parse_kanji_num(kh)
        if val is not None:
            counts[str(val)] += 1
    return counts


def detect_repetition_loop(tgt_text: str, src_text: str, tgt_lang: str) -> tuple[bool, str]:
    shielded, _ = protect_format_spans(tgt_text)
    if tgt_lang == "ja":
        clean_ja = _QE_JA_CLEAN_RE.sub("", shielded)
        if len(clean_ja) < 36:
            return False, ""
        grams = Counter(clean_ja[i : i + 4] for i in range(len(clean_ja) - 3))
        max_c = max(grams.values(), default=0)
        uniq = len(grams) / max(1, len(clean_ja) - 3)
        if max_c >= 4 and uniq < 0.48:
            return True, f"JA 4-gram degeneration (max={max_c}, uniq={uniq:.2f})"
        return False, ""

    words = [w for w in _QE_LATIN_CLEAN_RE.sub(" ", shielded.lower()).split() if w]
    if len(words) < 9:
        return False, ""
    for n in range(3, 7):
        if len(words) < n * 3:
            continue
        for i in range(0, len(words) - n * 3 + 1):
            p1 = " ".join(words[i : i + n])
            p2 = " ".join(words[i + n : i + n * 2])
            if p1 == p2 and p2 == " ".join(words[i + n * 2 : i + n * 3]):
                return True, f"Consecutive {n}-gram repetition loop"
    tgt_3g = Counter(" ".join(words[i : i + 3]) for i in range(len(words) - 2))
    uniq_ratio = len(tgt_3g) / max(1, len(words) - 2)
    src_cjk = _QE_CJK_ONLY_RE.sub("", src_text)
    if len(src_cjk) >= 16:
        src_grams = {src_cjk[i : i + 3] for i in range(len(src_cjk) - 2)}
        src_uniq = len(src_grams) / max(1, len(src_cjk) - 2)
    else:
        src_words = [w for w in _QE_LATIN_CLEAN_RE.sub(" ", src_text.lower()).split() if w]
        src_uniq = len(set(src_words)) / len(src_words) if len(src_words) >= 12 else 0.85
    if len(words) >= 20 and uniq_ratio < 0.45 and src_uniq >= 0.55:
        return True, f"3-gram diversity collapse (ratio={uniq_ratio:.2f})"
    return False, ""


def evaluate_source_target_qe(
    src_text: str,
    tgt_text: str,
    profile: DiscourseProfile,
    glossary_values: Sequence[str] = (),
    glossary_pairs: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Reference-free Source->Target QE (Specia 2018 / Nababan 3:2:1 / ISO 5060:2024)."""
    defects: list[dict[str, Any]] = []

    def _add(category: str, severity: str, detail: str) -> None:
        weight = 30 if severity == "critical" else (12 if severity == "major" else 4)
        defects.append({"category": category, "severity": severity, "weight": weight, "detail": detail})

    clean_src = (src_text or "").strip()
    clean_tgt = (tgt_text or "").strip()
    if not clean_src:
        return {"ok": True, "needsSelfRepair": False, "qeRiskScore": 0, "defects": []}
    if not clean_tgt:
        _add("accuracy_omission", "critical", "Translated output is empty")

    shielded_tgt, _ = protect_format_spans(clean_tgt)
    if profile.tgt_lang != "ja" and len(clean_tgt) >= 6:
        kana = len(_QE_KANA_RE.findall(shielded_tgt))
        kanji = len(_QE_KANJI_RE.findall(shielded_tgt))
        non_ws = max(1, len(_QE_WS_RE.sub("", shielded_tgt)))
        if kana >= 3 or (kana + kanji) / non_ws > 0.08:
            _add("accuracy_untranslated", "critical", "Untranslated Japanese script leaked")

    if len(clean_src) >= 24 and clean_tgt:
        if profile.src_lang == "ja" and profile.tgt_lang != "ja":
            ja_chars = max(1, len(_QE_WS_RE.sub("", clean_src)))
            tgt_words = max(1, len(clean_tgt.split()))
            fert = tgt_words / ja_chars
            if ja_chars >= 30 and fert < 0.16:
                _add("accuracy_omission", "critical", f"Severe JA->{profile.tgt_lang} undertranslation")
            elif ja_chars >= 25 and fert > 2.2:
                _add("accuracy_addition", "major", f"Suspected JA->{profile.tgt_lang} overtranslation")
        elif profile.src_lang != "ja" and profile.tgt_lang != "ja":
            sw = max(1, len(clean_src.split()))
            tw = max(1, len(clean_tgt.split()))
            if sw >= 12 and (tw / sw) < 0.4:
                _add("accuracy_omission", "critical", "Severe undertranslation")
            elif sw >= 12 and (tw / sw) > 2.4:
                _add("accuracy_addition", "major", "Suspected overtranslation")

    src_nums = _extract_canonical_nums(clean_src)
    if src_nums:
        tgt_nums = _extract_canonical_nums(clean_tgt)
        for num, needed in src_nums.items():
            if tgt_nums[num] < needed:
                _add("accuracy_number_unit", "critical", f"Source numeric value missing: {num}")
                break

    if glossary_pairs:
        for src_term, tgt_term in glossary_pairs:
            if len(src_term) >= 2 and len(tgt_term) >= 2 and src_term in clean_src and tgt_term not in clean_tgt:
                _add("terminology", "major", f"Glossary anchor missing: {src_term} -> {tgt_term}")
                break
    else:
        for val in glossary_values:
            if len(val) >= 2 and val in clean_src and val not in clean_tgt:
                _add("terminology", "major", f"Glossary anchor missing: {val}")
                break

    if profile.strict_deontic_modals and profile.genre in ("legal_policy", "technical_docs"):
        src_p = len(_DEONTIC_LATTICE["prohibition"][profile.src_lang].findall(clean_src))
        tgt_p = len(_DEONTIC_LATTICE["prohibition"][profile.tgt_lang].findall(clean_tgt))
        src_o = len(_DEONTIC_LATTICE["obligation"][profile.src_lang].findall(clean_src))
        tgt_o = len(_DEONTIC_LATTICE["obligation"][profile.tgt_lang].findall(clean_tgt))
        src_perm = len(_DEONTIC_LATTICE["permission"][profile.src_lang].findall(clean_src))
        src_rec = len(_DEONTIC_LATTICE["recommendation"][profile.src_lang].findall(clean_src))
        tgt_rec = len(_DEONTIC_LATTICE["recommendation"][profile.tgt_lang].findall(clean_tgt))
        if src_p > 0 and tgt_p == 0:
            _add("accuracy_modal", "critical", "Legal PROHIBITION modal dropped")
        if src_o > 0 and tgt_o == 0:
            _add("accuracy_modal", "critical", "Legal OBLIGATION modal dropped")
        if src_perm > 0 and src_o == 0 and tgt_o > 0:
            _add("accuracy_modal", "major", "Legal PERMISSION modal escalated to OBLIGATION")
        if src_rec > 0 and src_o == 0 and tgt_rec == 0 and tgt_o > 0:
            _add("accuracy_modal", "minor", "Legal RECOMMENDATION modal escalated to OBLIGATION")

    if profile.genre == "academic_research":
        if _ACADEMIC_HEDGE_SRC_RE.search(clean_src) and _ACADEMIC_BOOSTER_TGT_RE.search(clean_tgt):
            if not _QE_STRONG_PROOF_RE.search(clean_src):
                _add("accuracy_hedging", "major", "Academic epistemic hedge escalated to certainty booster")

    has_loop, loop_detail = detect_repetition_loop(clean_tgt, clean_src, profile.tgt_lang)
    if has_loop:
        _add("fluency_repetition_loop", "critical", loop_detail)

    risk = sum(int(d["weight"]) for d in defects)
    return {"ok": len(defects) == 0, "needsSelfRepair": risk >= 25, "qeRiskScore": risk, "defects": defects}


def naturalize_paragraph(
    src_text: str,
    raw_translated: str,
    profile: DiscourseProfile,
    glossary_values: Sequence[str] = (),
) -> str:
    if not raw_translated or not raw_translated.strip():
        return raw_translated
    base = sanitize_zero_em_dash(raw_translated, profile.tgt_lang)
    keigo = classify_ja_keigo(src_text or "") if profile.src_lang == "ja" else None
    had_ja_keigo = bool(keigo and keigo.locks_polite_register)
    neg_delta = [0]
    shielded, restore_map = protect_format_spans(base)
    shielded = repair_gtx_honorific_leaks(shielded, src_text or "", profile)
    parts: list[str] = []
    for kind, chunk in _split_spans(shielded):
        if kind == "protected":
            parts.append(chunk)
        elif profile.tgt_lang == "id":
            parts.append(_naturalize_id_span(chunk, kind, profile, src_text or "", had_ja_keigo, neg_delta))
        elif profile.tgt_lang == "en":
            parts.append(_naturalize_en_span(chunk))
        elif profile.tgt_lang == "ja":
            parts.append(_naturalize_ja_span(chunk))
        else:
            parts.append(chunk)

    joined_shielded = "".join(parts)
    if profile.tgt_lang == "id":
        joined_shielded = _fix_id_dialogue_punctuation(joined_shielded)
    restored = restore_format_spans(joined_shielded, restore_map)
    candidate = sanitize_zero_em_dash(restored, profile.tgt_lang)
    if verify_meaning_conservation(
        base,
        candidate,
        profile.tgt_lang,
        neg_delta[0],
        glossary_values,
        strict_deontic_modals=profile.strict_deontic_modals,
        shielded_post=joined_shielded,
    ):
        return candidate
    return base


def naturalize_paragraphs(
    src_paragraphs: Sequence[str],
    raw_outputs: Sequence[str],
    profile: DiscourseProfile,
    glossary_values: Sequence[str] = (),
) -> list[str]:
    """Sequence-aware paragraph naturalizer mirroring web/src/lib/literaryPolish.ts."""
    out: list[str] = []
    for idx, raw_out in enumerate(raw_outputs):
        src = src_paragraphs[idx] if idx < len(src_paragraphs) else ""
        if _SCENE_BREAK_RE.match((src or "").strip()):
            out.append(sanitize_zero_em_dash(raw_out, profile.tgt_lang))
        else:
            out.append(naturalize_paragraph(src, raw_out, profile, glossary_values=glossary_values))
    return out
