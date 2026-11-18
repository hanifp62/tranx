"""Analisis wacana narasi, kata ganti orang ketiga, sapaan, dan petunjuk LLM.

Modul ini memisahkan bagian narasi dari dialog Jepang (「…」, 『…』), menentukan
gender kata ganti yang aman dikoreksi (``pronoun_gender`` dan
``explicit_pronoun``), serta merakit baris petunjuk glosarium untuk LLM.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence

from .disambig import DASH_BREAKS
from .models import PERSON, GlossaryEntry, Masked, Slot
from .protect import EXACT_TOKEN_RE
from .textnorm import contains_japanese

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "PERSON": "orang",
    "PLACE": "tempat",
    "ORG": "organisasi",
    "TERM": "istilah",
    "CULTURE": "budaya",
}
GENDER_LABELS = {"m": "laki-laki", "f": "perempuan"}
SPEAKER_QUOTES = ('"', "“", "「", "『", "«")

_LEADING_VOCATIVE_RE = re.compile(
    r"""[\s「『（(“"'"""
    + re.escape(DASH_BREAKS)
    + r"""]*\[\[E(\d+)\]\][ \t\u3000]*[、，,]"""
)

QUOTE_OPENERS = "「『（(“"
QUOTE_CLOSERS = "」』）)”"
OTHER_PERSON_WORDS = (
    "彼", "あいつ", "こいつ", "そいつ", "どいつ", "奴", "やつ", "少年", "少女", "青年", "男", "女",
    "子供", "子ども", "赤ちゃん", "この人", "その人", "あの人", "どの人", "誰", "者", "兄", "姉",
    "弟", "妹", "父", "母", "親", "先輩", "後輩", "先生", "友達", "友人", "仲間", "主人", "持ち主",
    "店員", "客", "王", "姫", "その", "あの",
    "運転手", "選手", "相手", "歌手", "助手", "投手", "騎手", "犯人", "老人", "恋人", "他人",
    "人々", "住人", "職人", "商人", "婦人", "夫人", "新人", "知人", "隣人", "証人", "囚人",
    "管理人", "番人", "人間", "店長", "店主", "社長", "部長", "校長", "課長", "会長", "隊長",
    "船長", "院長", "署長", "団長", "委員", "駅員", "社員", "職員", "係員", "警備員", "乗務員",
    "隊員", "部員", "警官", "警察", "刑事", "探偵", "上官", "教官", "医師", "教師", "講師",
    "看護師", "牧師", "漁師", "師匠", "生徒", "学生", "年生", "校生", "入生", "級生", "上司",
    "部下", "同僚", "家族", "夫婦", "旦那", "妻", "息子", "娘", "皆", "みんな", "全員", "相棒",
    "恩人", "兵", "騎士", "侍", "敵",
)
_OTHER_PERSON_RE = re.compile("|".join(map(re.escape, OTHER_PERSON_WORDS)))

NOT_SINGLE_PRONOUNS = (
    "彼ら", "彼等", "彼たち", "彼女ら", "彼女等", "彼女たち", "彼氏", "元彼",
    "今彼", "前彼", "旧彼",
)
_EXPLICIT_PRONOUN_RE = re.compile("彼女|彼")

PARTNER_VERBS = (
    "デート", "付き合", "付きあ", "つきあ", "ツキア", "別れ", "わかれ", "ワカレ", "振ら",
    "ふら", "フラ", "振っ", "ふっ", "フッ",
)
PARTNER_PHRASES = (
    "ができ", "が出来", "がデキ", "がいる", "がいない", "が居る", "が居な", "を作",
    "をつく", "を紹介", "持ち", "が欲し", "がほし", "欲し", "ほし",
)
_PARTNER_RE = re.compile(
    f"(?:彼女|彼)(?:(?:と|が|に|を|は|も|って)?(?:{'|'.join(PARTNER_VERBS)})"
    f"|{'|'.join(PARTNER_PHRASES)})"
)
_PRONOUN_FOLLOWERS = frozenset(
    "はがのをにともへでやかまっなしさこばすだじよね、。，．,.！？!?…‥」』）)～〜ー"
)
_APPOSITION_RE = re.compile(
    "(?:" + "|".join(map(re.escape, OTHER_PERSON_WORDS)) + r")の(?=\[\[E\d+\]\])"
)
_STRAY_HONORIFIC_RE = re.compile(r"(?<!\]\])(?:さん|くん|ちゃん|様|さま|殿|氏|君|たん)")
_VOCATIVE_RE = re.compile(
    r"\[\[E(\d+)\]\](?=[、，,！!？?]|$)|[、，,]\[\[E(\d+)\]\](?=[。．.！!？?…‥ー〜～]*$)"
)


def narrative_part(text: str) -> str:
    """Kembalikan bagian kalimat di luar kutipan 「」『』（） tempat narasi berada."""
    kept: list[str] = []
    depth = 0
    for ch in text:
        if ch in QUOTE_OPENERS:
            depth += 1
        elif ch in QUOTE_CLOSERS:
            if depth:
                depth -= 1
            else:
                kept.clear()
        elif not depth:
            kept.append(ch)
    return "".join(kept)


def pronoun_gender(
    masked: Masked,
    context: Sequence[Masked],
    gender_of: Callable[[GlossaryEntry], str],
    others: Sequence[str] = (),
) -> str:
    """Gender kata ganti orang ketiga yang aman dipaksakan pada terjemahan kalimat ini."""
    own = _narrative_persons(masked, others)
    if own is None:
        return ""
    if not own:
        if not contains_japanese(EXACT_TOKEN_RE.sub("", narrative_part(masked.text))):
            return ""
        for other in context:
            found = _narrative_persons(other, others)
            if found is None:
                return ""
            own.extend(found)
    if len(_distinct_people(own)) != 1:
        return ""
    genders = {gender_of(entry) for entry in own}
    return genders.pop() if len(genders) == 1 and genders <= {"m", "f"} else ""


def explicit_pronoun(text: str) -> tuple[str, int]:
    """Gender dan jumlah kata ganti orang ketiga tunggal eksplisit (彼, 彼女)."""
    if any(word in text for word in NOT_SINGLE_PRONOUNS) or _PARTNER_RE.search(text):
        return "", 0
    genders: list[str] = []
    for match in _EXPLICIT_PRONOUN_RE.finditer(text):
        after = text[match.end():match.end() + 1]
        if (
            after
            and after not in _PRONOUN_FOLLOWERS
            and not text.startswith("自身", match.end())
        ):
            return "", 0
        genders.append("f" if match.group() == "彼女" else "m")
    if not genders or len(set(genders)) != 1:
        return "", 0
    return genders[0], len(genders)


def _narrative_persons(
    masked: Masked, others: Sequence[str] = ()
) -> list[GlossaryEntry] | None:
    bare = EXACT_TOKEN_RE.sub("", _APPOSITION_RE.sub("", masked.text))
    if (
        _OTHER_PERSON_RE.search(bare)
        or _STRAY_HONORIFIC_RE.search(masked.text)
        or any(other and other in bare for other in others)
    ):
        return None
    narrative = narrative_part(masked.text)
    persons = {
        int(number)
        for number in EXACT_TOKEN_RE.findall(narrative)
        if (slot := masked.slots.get(int(number))) and slot.entry.kind == PERSON
    }
    for match in _VOCATIVE_RE.finditer(narrative):
        if int(match.group(1) or match.group(2)) in persons:
            return None
    return [masked.slots[number].entry for number in sorted(persons)]


def _distinct_people(entries: Iterable[GlossaryEntry]) -> list[str]:
    kept: list[str] = []
    for surface in sorted({entry.surface for entry in entries}, key=len, reverse=True):
        if not any(
            longer.startswith(surface) or longer.endswith(surface) for longer in kept
        ):
            kept.append(surface)
    return kept


def vocative_lead(masked: Masked) -> str | None:
    """Sumber termasking sesudah koma sapaan orang, atau ``None``."""
    match = _LEADING_VOCATIVE_RE.match(masked.text)
    slot = masked.slots.get(int(match.group(1))) if match else None
    if slot is None or slot.entry.kind != PERSON:
        return None
    return masked.text[match.end():]


def person_names(form: str, base: str | None) -> list[str]:
    """Bentuk nama orang yang diperiksa ``fix_names`` untuk satu slot."""
    names = [form] if form else []
    if base and base != form and form.startswith(base):
        names.append(base)
    return names


def person_forms(masked: Masked, render: Callable[[Slot], str]) -> list[str]:
    """Bentuk nama orang untuk ``fix_names`` di jalur cadangan ``presubstitute``."""
    return [
        render(slot)
        for slot in masked.slots.values()
        if slot.entry.kind == PERSON
    ]


def mark_speaker(text: str, names: Sequence[str]) -> str:
    """Beri titik dua setelah nama pembicara naskah (``Kenta "Hei"`` -> ``Kenta: "Hei"``)."""
    for name in names:
        if not text.startswith(name):
            continue
        rest = text[len(name):].lstrip()
        if rest.startswith(SPEAKER_QUOTES):
            return f"{name}: {rest}"
    return text


def hint_lines(
    texts: Sequence[str],
    slots: Sequence[Mapping[int, Slot]],
    render: Callable[[Slot], str],
    gender_of: Callable[[GlossaryEntry], str] | None = None,
) -> list[str]:
    """Baris glosarium untuk LLM, satu per penanda di tiap teks."""
    lines: list[str] = []
    for item, (text, item_slots) in enumerate(zip(texts, slots), start=1):
        for number in sorted({int(n) for n in EXACT_TOKEN_RE.findall(text)}):
            slot = item_slots.get(number)
            if slot is None:
                continue
            entry = slot.entry
            labels = [KIND_LABELS.get(entry.kind, entry.kind.lower())]
            gender = gender_of(entry) if gender_of is not None else entry.gender
            if gender in GENDER_LABELS:
                labels.append(GENDER_LABELS[gender])
            rendered = " ".join(render(slot).splitlines()).strip()
            lines.append(
                f"{item}: [[E{number}]] = {rendered} ({', '.join(labels)})"
            )
    return lines
