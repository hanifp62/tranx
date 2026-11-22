"""Unit tests for tranx_core.literary_polish (multi-level cohesion, safety guards, zero U+2014)."""

from __future__ import annotations

import sys
from pathlib import Path

FUNCTIONS_DIR = Path(__file__).resolve().parents[1]
if str(FUNCTIONS_DIR) not in sys.path:
    sys.path.insert(0, str(FUNCTIONS_DIR))

from tranx_core.literary_polish import (  # noqa: E402
    build_literary_system_prompt,
    classify_ja_keigo,
    compute_source_complexity,
    detect_repetition_loop,
    evaluate_source_target_qe,
    naturalize_paragraph,
    naturalize_paragraphs,
    profile_document,
    protect_format_spans,
    restore_format_spans,
    sanitize_zero_em_dash,
    verify_meaning_conservation,
)


def test_indonesian_anti_translationese_rules_and_idempotence():
    profile = profile_document(
        [
            '「ねえ、本当に大丈夫？」',
            '教室の窓から風が吹き込む。俺はゆっくり立ち上がった。',
        ],
        src_lang="ja",
        tgt_lang="id",
    )
    assert profile.genre in ("fiction_novel", "fiction_dialogue_heavy")
    assert profile.domain == "school_peer"

    stiff = (
        'Ini adalah merupakan kafe di mana kita bertemu, yang mana membuat sebuah perasaan aneh. '
        'Dia memiliki mata gelap dan rambut panjang. Pintu itu dibuka olehnya. '
        'Dia tidak bisa membantu tetapi tersenyum. Dia telah tidak pernah merasa seperti itu. '
        'Meskipun hujan deras, tetapi ia tetap pergi. "Aku mengerti." katanya.'
    )
    once = naturalize_paragraph("教室で彼は微笑んだ。", stiff, profile)
    twice = naturalize_paragraph("教室で彼は微笑んだ。", once, profile)
    assert once == twice, "Naturalizer must be strictly idempotent"
    assert "adalah merupakan" not in once
    assert "kafe tempat kita bertemu" in once
    assert "yang mana" not in once
    assert "sebuah perasaan" not in once
    assert "bermata gelap" in once
    assert "dibukanya" in once
    assert "tidak bisa membantu tetapi" not in once
    assert "belum pernah" in once
    assert ", tetapi" not in once
    assert '"Aku mengerti," katanya.' in once


def test_formal_legal_and_academic_docs_never_casualized():
    legal_paras = [
        "Pasal 1 Ayat (2) Undang-Undang Nomor 27 Tahun 2022 mengatur kewajiban pengendali data.",
        "Oleh karena itu, Saya dan Anda wajib mematuhi ketentuan sebagaimana dimaksud dalam Pasal 3.",
    ]
    profile = profile_document(legal_paras, src_lang="id", tgt_lang="id")
    assert profile.genre == "legal_policy"
    assert profile.register == "formal_legal_tech"
    assert not profile.allow_id_pronoun_soften

    out = naturalize_paragraph(legal_paras[1], legal_paras[1], profile)
    assert "Oleh karena itu," in out
    assert "Saya" in out
    assert "Anda" in out


def test_body_morphology_and_compound_guards():
    profile = profile_document(['"Halo!" serunya.'], src_lang="en", tgt_lang="id")
    assert "berambut hitam" in naturalize_paragraph("src", "Dia memiliki rambut hitam.", profile)
    assert "berrambut" not in naturalize_paragraph("src", "Dia memiliki rambut hitam.", profile)
    # Compound nouns must NOT be rewritten
    econ = naturalize_paragraph("src", "Negara itu memiliki mata uang stabil.", profile)
    assert "memiliki mata uang" in econ
    # "sudah tidak pernah" means no longer ever -> must NOT turn into "belum pernah"
    habit = naturalize_paragraph("src", "Dia sudah tidak pernah merokok lagi.", profile)
    assert "sudah tidak pernah" in habit


def test_meaning_conservation_blocks_negation_flip_and_preserves_glossary():
    profile = profile_document(['"Ayo pergi."'], src_lang="ja", tgt_lang="id")
    src = "彼女は12個のリンゴを買った。"
    raw = "Shiina-san membeli 12 apel dan tidak lupa membayar."
    out = naturalize_paragraph(src, raw, profile, glossary_values=("Shiina-san",))
    assert "Shiina-san" in out
    assert "12" in out
    assert "tidak" in out


def test_zero_em_dash_invariant_across_all_target_langs():
    for tgt in ("id", "en", "ja"):
        cleaned = sanitize_zero_em_dash("Tunggu\u2014apa itu\u2014katanya\u2014", tgt)
        assert "\u2014" not in cleaned


def test_literary_prompt_includes_profile_and_anti_calque():
    profile = profile_document(['「おはよう、椎名さん」', '教室の窓際で俺は小さく頷いた。'], "ja", "id")
    prompt = build_literary_system_prompt("Japanese", "Indonesian", profile)
    assert "domain=school_peer" in prompt
    assert "NEVER translate Japanese classmate -san/-kun/-chan" in prompt
    assert "U+2014" in prompt


def test_double_negative_id_r13_passes_meaning_conservation():
    profile = profile_document(['"Halo," katanya.', 'Dia menatap langit sore.'], "ja", "id")
    src = "彼女は思わず微笑まずにはいられなかった。"
    raw = "Ia tidak bisa tidak tersenyum ketika melihat sebuah perasaan aneh."
    out = naturalize_paragraph(src, raw, profile)
    assert "mau tak mau tersenyum" in out
    assert "sebuah perasaan" not in out


def test_v4_format_shield_preserves_filenames_code_abbrevs_and_tables():
    profile = profile_document(
        ["Run `npm test` on app.py and Node.js (e.g. REST API endpoints)."],
        "en",
        "id",
    )
    assert profile.genre == "technical_docs"
    raw = (
        "| Berkas | Runtime |\n"
        "| --- | --- |\n"
        "| app.py | Node.js |\n"
        "Jalankan `npm run build` di app.py (e.g. Node.js) untuk 120ms dan https://example.com/app.py."
    )
    shielded, rmap = protect_format_spans(raw)
    assert "app.py" not in shielded
    assert restore_format_spans(shielded, rmap) == raw

    out = naturalize_paragraph(raw, raw, profile)
    assert "app.py" in out
    assert "Node.js" in out
    assert "e.g." in out
    assert "`npm run build`" in out
    assert "https://example.com/app.py" in out
    assert "| --- | --- |" in out
    assert "app. py" not in out
    assert "Node. js" not in out


def test_v4_eyd_v_kbbi_vi_and_keluar_guard():
    profile = profile_document(['"Ayo kita mulai!" serunya.'], "en", "id")
    raw = (
        "Dia keluar dari ruangan lalu duduk disini untuk menguji praktek dan resiko sistim "
        "dengan biaya Rp. 50.000 kepada Tuhan Yang Mahaesa tanpa syarat apapun."
    )
    out = naturalize_paragraph("He exited the room.", raw, profile)
    assert "keluar dari ruangan" in out
    assert "ke luar dari ruangan" not in out
    assert "di sini" in out
    assert "praktik" in out
    assert "risiko" in out
    assert "sistem" in out
    assert "Rp50.000" in out
    assert "Maha Esa" in out
    assert "apa pun" in out


def test_v4_complexity_calibration_and_legal_deontic_conservation():
    simple = compute_source_complexity(["The cat sat on the mat. It was warm."], "en")
    dense = compute_source_complexity(
        [
            "Notwithstanding any statutory obligation hereinafter stipulated, "
            "the multidimensional epistemological characterization substantiates methodological convergence."
        ],
        "en",
    )
    assert simple.score < dense.score
    assert simple.tier in ("L1", "L2")
    assert dense.tier in ("L4", "L5")

    legal_prof = profile_document(
        ["Whereas hereinafter the Party SHALL NOT disclose confidential records under Pasal 4."],
        "en",
        "id",
    )
    assert legal_prof.genre == "legal_policy"
    assert legal_prof.strict_deontic_modals
    assert not verify_meaning_conservation(
        "Pihak wajib membayar Rp50.000 dalam 14 hari.",
        "Pihak dapat membayar Rp50.000 dalam 14 hari.",
        "id",
        strict_deontic_modals=True,
    )
    assert not verify_meaning_conservation(
        "Suhu mencapai 37,5°C dengan berat 12 kg.",
        "Suhu mencapai 37,5 dengan berat 12.",
        "id",
    )


def test_sesi2_regression_quotes_tempat_interrogative_ellipsis_and_closed_class():
    profile = profile_document(['"Halo," katanya, "apa kabar?"'], "en", "id")

    # H1: Multi-quote dialogue must NOT strip spaces around narrative tag between quotes
    multi_q = naturalize_paragraph("src", '"Halo," katanya, "apa kabar?"', profile)
    assert multi_q == '"Halo," katanya, "apa kabar?"'

    # H2: "tempat di mana" -> "tempat" (never "tempat tempat") and interrogative "yang mana?" preserved
    tempat = naturalize_paragraph("src", "Ini tempat di mana ia lahir.", profile)
    assert "tempat ia lahir" in tempat and "tempat tempat" not in tempat
    interrog = naturalize_paragraph("src", "Kamu pilih buku yang mana?", profile)
    assert "yang mana?" in interrog

    # H3: Ellipsis before speech verb stays intact; capitalized verb after ?/! lowercases
    ellip = naturalize_paragraph("src", '"Aku..." katanya. "Mau ke mana?" Tanyanya.', profile)
    assert '"Aku..." katanya.' in ellip
    assert '"Mau ke mana?" tanyanya.' in ellip

    # H6: Closed-class conjunction after body part must NEVER turn into "bermata dan"
    body = naturalize_paragraph("src", "Ia punya mata dan telinga yang tajam.", profile)
    assert "punya mata dan telinga" in body and "bermata dan" not in body

    # H7 & M3: Code block containing em-dash stays shielded and passes conservation; di manapun / ke manapun fixed
    code_dash = naturalize_paragraph("src", "Jalankan `echo a\u2014b` kemanapun dan dimanapun.", profile)
    assert "`echo a\u2014b`" in code_dash
    assert "ke mana pun" in code_dash and "di mana pun" in code_dash


def test_v5_keigo_5tier_purwo_deixis_yojijukugo_and_qe():
    # 1. 5-tier Japanese Keigo: bikago (gohan/ocha) must NOT lock polite register, sonkeigo elevates referent
    assert classify_ja_keigo("ご飯を食べた。").tier == "bikago"
    assert not classify_ja_keigo("ご飯を食べた。").locks_polite_register
    sonk = classify_ja_keigo("先生がいらっしゃいました。")
    assert sonk.tier == "sonkeigo" and sonk.elevates_referent and sonk.locks_polite_register
    assert classify_ja_keigo("確認いたします。").tier == "kenjougo"
    assert classify_ja_keigo("静かな夜です。").tier == "teineigo"

    # 2. Purwo oblique "ia" repair + Yojijukugo + Mimetic + Honorific parity
    prof = profile_document(['「おはよう、椎名さん」', '教室で俺は笑った。'], "ja", "id")
    out = naturalize_paragraph(
        "椎名さんは一期一会を胸にドキドキしながらご飯を食べた。",
        'Tuan Shiina berkata kepada ia, "Aku percaya Anda dan ini satu periode satu pertemuan yang bikin doki-doki."',
        prof,
    )
    assert "Shiina-san" in out and "Tuan Shiina" not in out
    assert "kepadanya" in out and "kepada ia" not in out
    assert "pertemuan sekali seumur hidup" in out
    assert "berdebar kencang" in out
    assert "kamu" in out.lower()

    # 3. Reference-Free QE: Kanji numeral conservation, repetition loop, 4-class legal deontic & academic hedging
    qe_ok = evaluate_source_target_qe("彼女は三百円を払った。", "Dia membayar 300 yen.", prof)
    assert qe_ok["ok"] and not qe_ok["needsSelfRepair"]

    qe_num_drop = evaluate_source_target_qe("彼女は三百円を払った。", "Dia membayar mahal sekali.", prof)
    assert not qe_num_drop["ok"] and qe_num_drop["needsSelfRepair"]

    loop_hit, _ = detect_repetition_loop(
        "dia berjalan perlahan dia berjalan perlahan dia berjalan perlahan dia berjalan perlahan ke taman kota",
        "He walked slowly to the city park.",
        "id",
    )
    assert loop_hit

    legal_prof = profile_document(["Whereas the Party SHALL NOT disclose data under Pasal 4."], "en", "id")
    qe_legal_bad = evaluate_source_target_qe(
        "The Party SHALL NOT disclose confidential keys.",
        "Pihak dapat menjaga rahasia kunci.",
        legal_prof,
    )
    assert not qe_legal_bad["ok"] and qe_legal_bad["needsSelfRepair"]

    acad_prof = profile_document(["Abstract: Methodology suggests a correlation (Smith, 2024)."], "en", "id")
    qe_hedge_bad = evaluate_source_target_qe(
        "The evidence suggests that warming may accelerate.",
        "Bukti tersebut membuktikan bahwa pemanasan pasti meningkat.",
        acad_prof,
    )
    assert not qe_hedge_bad["ok"]

    # 4. Sequence-aware naturalize_paragraphs preserves scene break
    seq_out = naturalize_paragraphs(["***", "教室で笑った。"], ["***", "Dia memiliki mata biru."], prof)
    assert seq_out[0] == "***" and "bermata biru" in seq_out[1]



