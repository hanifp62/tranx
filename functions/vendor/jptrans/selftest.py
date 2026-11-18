"""Rangkaian pengujian unit dan integrasi otomatis bawaan ``jptrans``.

Dapat dijalankan langsung lewat ``python3 translator.py test -v`` tanpa pustaka
pihak ketiga dan tanpa koneksi internet. Menguji 5 kriteria rekayasa skrip
profesional: keandalan/idempotensi/pembersihan sumber daya, kebersihan modular,
keamanan konfigurasi, observabilitas/kode keluar, serta akurasi linguistik
dan dukungan lintas format.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import tempfile
import time
import unittest
import zipfile
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from . import cli, coref, data, disambig, gender, models, ner, net, phonetic
from . import postprocess, protect, readings, residue, romaji, segment, server
from . import style, textnorm
from .cache import TranslationCache, make_key
from .config import Config, load_config, load_dotenv
from .engines.fake import FakeEngine
from .engines.libretranslate import LibreTranslateEngine
from .engines.llm import LLMEngine, parse_translations, resolve_model_for_host
from .errors import AllEnginesFailed, ConfigError, EngineUnavailable, InputError
from .errors import QuotaExceeded
from .glossary import Glossary
from .pipeline import Translator
from .readers import read_document, read_text
from .readers.epub import extract_xhtml
from .readers.pages import clean_ocr_text
from .readers.subtitle import parse_ass, parse_srt, parse_vtt
from .readers.txt import detect_encoding
from .writers import render_output
from .writers.subtitle import wrap_cue

logger = logging.getLogger(__name__)


class ReliabilityAndCacheTests(unittest.TestCase):
    """Kriteria 1: Graceful failure, idempotensi, dan pembersihan sumber daya."""

    def test_sqlite_wal_idempotency_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.sqlite3"
            with TranslationCache(db_path) as cache:
                key = make_key("fake:v1", "ja", "id", "[[E1]]は来た。")
                cache.put(key, "fake", "ja", "id", "[[E1]] datang.")
                cache.put(key, "fake", "ja", "id", "[[E1]] datang.")
                self.assertEqual(cache.get(key), "[[E1]] datang.")
                self.assertEqual(cache.stats()["entries"], 1)
                assert cache._conn is not None
                mode = cache._conn.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            cache.close()
            self.assertIsNone(cache._conn)

    def test_cache_clear_and_batch_put_many(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with TranslationCache(Path(tmp) / "cache.sqlite3") as cache:
                rows = [
                    (make_key("fake", "ja", "id", f"s{i}"), "fake", "ja", "id", f"t{i}")
                    for i in range(4)
                ]
                cache.put_many(rows)
                self.assertEqual(cache.stats()["entries"], 4)
                removed = cache.clear()
                self.assertEqual(removed, 4)
                self.assertEqual(cache.stats()["entries"], 0)

    def test_corrupted_placeholder_does_not_poison_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            bad_engine = FakeEngine(
                translations={
                    "[[E1]]は走った。": "Dia berlari tanpa token.",
                    "Tanaka-san は走った。": "Tanaka-san berlari cepat.",
                }
            )
            glossary = Glossary("uji", [models.GlossaryEntry("田中", reading="たなか")])
            doc = read_text("田中さんは走った。", "uji")
            with TranslationCache(cfg.cache_path) as cache:
                translator = Translator(cfg, [bad_engine], cache, glossary)
                res = translator.translate_document(doc)
                self.assertEqual(res.paragraphs[0].target, "Tanaka-san berlari cepat.")
                self.assertEqual(
                    res.paragraphs[0].sentences[0].status, models.STATUS_PRESUB
                )
                masked_key = translator._key(
                    bad_engine,
                    "[[E1]]は走った。",
                    {1: models.Slot(glossary.get("田中") or models.GlossaryEntry("田中"), "san")},
                )
                self.assertIsNone(cache.get(masked_key))

    def test_idempotent_repeated_translation_and_slot_cache_separation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            engine = FakeEngine(
                translations={
                    "[[E1]]に電話した。": "Menghubungi [[E1]].",
                }
            )
            glossary = Glossary("seri")
            doc = read_text("田中さんに電話した。田中家に電話した。", "seri")
            with TranslationCache(cfg.cache_path) as cache:
                first = Translator(cfg, [engine], cache, glossary).translate_document(doc)
                count_after_first = len(glossary)
                second = Translator(cfg, [engine], cache, glossary).translate_document(doc)
                self.assertEqual(len(glossary), count_after_first)
                self.assertEqual(first.paragraphs[0].target, second.paragraphs[0].target)
                self.assertIn("Tanaka-san", second.paragraphs[0].target)
                self.assertIn("keluarga Tanaka", second.paragraphs[0].target)
                self.assertEqual(
                    second.paragraphs[0].sentences[0].status, models.STATUS_CACHED
                )

    def test_all_engines_failed_raises_clean_error(self) -> None:
        class BrokenEngine(FakeEngine):
            def translate(self, texts, src, tgt, hints=()):  # type: ignore[override]
                raise EngineUnavailable("broken", "jaringan terputus")

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            with TranslationCache(None) as cache:
                translator = Translator(cfg, [BrokenEngine()], cache, Glossary("uji"))
                with self.assertRaises(AllEnginesFailed):
                    translator.translate_text("こんにちは。")


class SecurityAndConfigTests(unittest.TestCase):
    """Kriteria 3: Keamanan rahasia, .env, validasi tipe, dan sanitasi input."""

    def test_dotenv_loader_parses_safely_without_overwriting_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "# komentar\n"
                "JPTRANS_TEST_ALPHA='nilai_satu'\n"
                "export JPTRANS_TEST_BETA=\"nilai_dua\" # komentar tepi\n"
                "JPTRANS_TEST_GAMMA=\"nilai # tiga\"\n"
                "INVALID-KEY=abaikan\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ, {"JPTRANS_TEST_ALPHA": "dari_shell"}, clear=False
            ):
                os.environ.pop("JPTRANS_TEST_BETA", None)
                os.environ.pop("JPTRANS_TEST_GAMMA", None)
                added = load_dotenv(env_file)
                self.assertEqual(added, 2)
                self.assertEqual(os.environ["JPTRANS_TEST_ALPHA"], "dari_shell")
                self.assertEqual(os.environ["JPTRANS_TEST_BETA"], "nilai_dua")
                self.assertEqual(os.environ["JPTRANS_TEST_GAMMA"], "nilai # tiga")
                os.environ.pop("JPTRANS_TEST_BETA", None)
                os.environ.pop("JPTRANS_TEST_GAMMA", None)

    def test_config_rejects_secrets_and_string_booleans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            secret_cfg = Path(tmp) / "secret.json"
            secret_cfg.write_text('{"deepl_api_key": "rahasia"}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(secret_cfg)

            bad_bool = Path(tmp) / "bool.json"
            bad_bool.write_text('{"allow_unofficial": "false"}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(bad_bool)

    def test_llm_security_provider_model_and_thinking_fence_parser(self) -> None:
        cfg_insecure = Config(llm_base_url="http://example.com/v1")
        llm_insecure = LLMEngine(cfg_insecure, api_key="sk-secret")
        ok, _ = llm_insecure.available()
        self.assertFalse(ok)
        with self.assertRaises(EngineUnavailable):
            llm_insecure.translate(["テスト"], "ja", "id")

        self.assertEqual(
            resolve_model_for_host("gemini-2.5-flash", "api.groq.com"),
            "llama-3.3-70b-versatile",
        )
        self.assertEqual(
            resolve_model_for_host("gemini-2.5-flash", "localhost"),
            "qwen2.5:7b",
        )
        raw_reply = (
            "<think>analisis internal</think>\n"
            "Berikut hasilnya:\n```JSON\n"
            '{"translations": [{"id": "1", "text": "Halo [[E1]]!"}]}\n```'
        )
        self.assertEqual(parse_translations(raw_reply, 1), ["Halo [[E1]]!"])

    def test_net_http_402_and_404_classification(self) -> None:
        err_402 = HTTPError(
            "https://openrouter.ai/api", 402, "Payment Required", Message(), None
        )
        err_404 = HTTPError(
            "https://example.com/v1", 404, "Not Found", Message(), None
        )
        self.assertIsInstance(net._classify(err_402, "llm").error, QuotaExceeded)
        self.assertIsInstance(net._classify(err_404, "llm").error, EngineUnavailable)

    def test_libretranslate_security_and_response(self) -> None:
        engine = LibreTranslateEngine(
            base_url="http://remote.example.com", api_key="secret"
        )
        self.assertFalse(engine.available()[0])
        local_engine = LibreTranslateEngine(base_url="http://localhost:5000")
        self.assertTrue(local_engine.available()[0])

    def test_server_ipv6_host_rebinding_guard(self) -> None:
        self.assertEqual(server.host_name("[::1]:8765"), "::1")
        self.assertEqual(server.host_name("[::1]"), "::1")
        self.assertEqual(server.host_name("[::1]evil.com"), "")
        self.assertEqual(server.host_name("127.0.0.1:8765"), "127.0.0.1")
        self.assertTrue(server._is_private_lan_ip("192.168.1.25"))
        self.assertFalse(server._is_private_lan_ip("evil.com"))


class LinguisticAndModularTests(unittest.TestCase):
    """Kriteria 2 & Akurasi: Modularitas, romaji, fonetik, NER, gender, dan gaya."""

    def test_offline_full_kanji_name_resolution(self) -> None:
        entry = models.GlossaryEntry(surface="山田太郎", kind=models.PERSON)
        completed = readings.complete_reading(entry, {})
        self.assertEqual(completed.reading, "やまだ たろう")
        cfg_id = Config(target_lang="id")
        cfg_en = Config(target_lang="en")
        self.assertEqual(style.Renderer(cfg_id)(models.Slot(completed, "san")), "Yamada Tarō-san")
        self.assertEqual(style.Renderer(cfg_en)(models.Slot(completed, "san")), "Tarō Yamada-san")

    def test_romaji_ainu_iteration_marks_and_morpheme_boundaries(self) -> None:
        self.assertEqual(romaji.romanize_name("アシㇼパ", "macron"), "Ashiripa")
        self.assertEqual(romaji.romanize_name("みすゞ", "macron"), "Misuzu")
        self.assertEqual(romaji.kana_to_romaji("こゝろ", "macron"), "kokoro")
        self.assertEqual(romaji.kana_to_romaji("づゝ", "plain"), "zutsu")
        self.assertTrue(romaji.looks_japanese("ミスヾ"))
        self.assertEqual(romaji.kana_to_romaji("アンーイ", "plain"), "an'i")
        self.assertEqual(romaji.romanize_name("まつうら", "macron"), "Matsuura")
        self.assertEqual(romaji.romanize_name("ひろおか", "macron"), "Hirooka")
        self.assertEqual(romaji.romanize_name("よこお", "macron"), "Yokoo")
        self.assertEqual(romaji.romanize_name("ゆうき", "macron"), "Yūki")
        self.assertEqual(romaji.romanize_name("おおさか", "macron"), "Ōsaka")

    def test_phonetic_rejects_english_decoys_and_accepts_slavic(self) -> None:
        self.assertIsNone(phonetic.validate_foreign_name("キール", "Key"))
        self.assertIsNone(phonetic.validate_foreign_name("シール", "Sea"))
        self.assertIsNone(phonetic.validate_foreign_name("ポール", "Paw"))
        self.assertEqual(phonetic.validate_foreign_name("ポール", "Paul"), "Paul")
        self.assertEqual(phonetic.validate_foreign_name("シャーロット", "Charlotte"), "Charlotte")
        self.assertEqual(phonetic.validate_foreign_name("オルロフ", "Orlov"), "Orlov")
        self.assertEqual(phonetic.validate_foreign_name("カルポフ", "Karpov"), "Karpov")
        self.assertEqual(phonetic.validate_foreign_name("ヴォルコフ", "Volkov"), "Volkov")
        self.assertEqual(phonetic.validate_foreign_name("ロマノフ", "Romanov"), "Romanov")
        self.assertEqual(phonetic.validate_foreign_name("イヴァノフ", "Ivanov"), "Ivanov")

    def test_ner_fantasy_names_loanwords_pronouns_and_titles(self) -> None:
        doc = read_text(
            "フリーレンは笑った。キミはアルバイトだ。拙者も行く。"
            "原画監督と関連会社社長が来た。結局美咲さんが勝った。",
            "ner_uji",
        )
        cands = {c.surface: c for c in ner.detect_entities(doc)}
        self.assertIn("フリーレン", cands)
        self.assertEqual(cands["フリーレン"].kind, models.PERSON)
        self.assertGreaterEqual(cands["フリーレン"].score, 0.6)
        self.assertIn("美咲", cands)
        for non_entity in ("キミ", "アルバイト", "拙者", "原画", "関連会社", "結局美咲"):
            self.assertNotIn(non_entity, cands)

    def test_gender_and_localized_honorific_accuracy(self) -> None:
        aoi = models.GlossaryEntry("蒼", kind=models.PERSON, reading="あおい")
        self.assertEqual(gender.infer_gender(aoi)[0], "")
        megumi_kun = models.GlossaryEntry("恵", kind=models.PERSON)
        self.assertEqual(gender.infer_gender(megumi_kun, kun=True)[0], "")

        cfg_loc_id = Config(target_lang="id", honorific_style="localize")
        cfg_loc_en = Config(target_lang="en", honorific_style="localize")
        elisabeth = models.GlossaryEntry("エリザベート", kind=models.PERSON)
        self.assertEqual(
            style.Renderer(cfg_loc_id)(models.Slot(elisabeth, "sama")),
            "Elizabeth-sama",
        )
        sakura_f = models.GlossaryEntry("さくら", kind=models.PERSON, gender="f")
        self.assertEqual(
            style.Renderer(cfg_loc_en)(models.Slot(sakura_f, "dono")),
            "Lady Sakura",
        )

        cfg_keep = Config(target_lang="id", honorific_style="keep")
        tanaka = models.GlossaryEntry("田中", kind=models.PERSON, reading="たなか")
        self.assertEqual(
            style.Renderer(cfg_keep)(models.Slot(tanaka, "san", "家")),
            "rumah Tanaka-san",
        )
        self.assertEqual(
            style.Renderer(cfg_keep)(models.Slot(tanaka, "", "家")),
            "keluarga Tanaka",
        )

    def test_protect_annotated_llm_tokens_and_postprocess_rules(self) -> None:
        tanaka = models.GlossaryEntry("田中", kind=models.PERSON, reading="たなか")
        masked = models.Masked("田中さん", "[[E1]]", {1: models.Slot(tanaka, "san")})
        restored = protect.restore("Halo [[E1:田中]]!", masked, lambda _s: "Tanaka-san")
        self.assertEqual(restored, "Halo Tanaka-san!")

        self.assertEqual(
            postprocess.tidy("The the Tanaka family arrived.", "en"),
            "The Tanaka family arrived.",
        )
        self.assertEqual(
            postprocess.fix_names("Tokyonya indah.", ["Tokyo"], "id"),
            "Tokyo-nya indah.",
        )
        self.assertEqual(
            postprocess.fix_pronouns("The victory was his and they cheered.", "f"),
            "The victory was hers and they cheered.",
        )
        self.assertEqual(
            postprocess.lower_after_comma("Misaki-chan, It’s morning!", "en", ["Misaki-chan"]),
            "Misaki-chan, it’s morning!",
        )
        self.assertEqual(
            postprocess.lower_after_vocative(
                "Yui, Lombok itu indah.", "id", ["Yui"], frozenset(), "ロンボクは綺麗だ。"
            ),
            "Yui, Lombok itu indah.",
        )

    def test_segmentation_quotes_fullwidth_period_and_ellipsis(self) -> None:
        self.assertEqual(
            segment.split_sentences("「行くぞ！」とりあえず走った。"),
            ["「行くぞ！」", "とりあえず走った。"],
        )
        self.assertEqual(
            segment.split_sentences("「バカ！」が口癖だ。"),
            ["「バカ！」が口癖だ。"],
        )
        self.assertEqual(
            segment.split_sentences("値は3．14である．次の文．"),
            ["値は3．14である．", "次の文．"],
        )
        self.assertEqual(segment.unwrap_lines("これは……\n本当？"), "これは……本当？")
        self.assertEqual(textnorm.strip_diacritics("Satō Tarō"), "Sato Taro")


class ReadersWritersAndCliTests(unittest.TestCase):
    """Kriteria 4 & 5: Pembaca/penulis lintas format, logging, dan kode keluar."""

    def test_encoding_detection_utf8_with_latin_accents_and_eucjp(self) -> None:
        utf8_bytes = "Résumé 東京の桜が咲いた。\n".encode("utf-8")
        self.assertEqual(detect_encoding(utf8_bytes), "utf-8")
        self.assertEqual(detect_encoding(b"\xc3\xbb\n"), "euc_jp")
        with self.assertRaises(InputError):
            detect_encoding(b"abc\x00def")

    def test_web_novel_brackets_and_scene_breaks_not_eaten_by_aozora(self) -> None:
        novel = (
            "彼は《火炎魔法》と《ファイアボール》を放った。\n"
            "----------\n次の場面。\n----------\n終わり。"
        )
        doc = read_text(novel, "webnovel")
        self.assertEqual(doc.fmt, "txt")
        joined = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("《火炎魔法》", joined)
        self.assertIn("《ファイアボール》", joined)
        self.assertIn("次の場面。", joined)

        aozora_latin = read_text("NHK《エヌエイチケイ》の放送。", "aozora_uji")
        self.assertEqual(aozora_latin.fmt, "aozora")
        self.assertEqual(aozora_latin.ruby.get("NHK"), "エヌエイチケイ")

    def test_xhtml_ruby_okurigana_and_standalone_html_reader(self) -> None:
        paras, pairs = extract_xhtml(
            "<p><ruby>見<rt>み</rt>える</ruby>と<ruby>悠<rt>ゆう</rt>真<rt>ま</rt></ruby></p>"
        )
        self.assertEqual(paras[0].text, "見えると悠真")
        self.assertIn(("見", "み"), pairs)
        self.assertIn(("悠真", "ゆうま"), pairs)
        self.assertNotIn(("見える", "み"), pairs)

        with tempfile.TemporaryDirectory() as tmp:
            html_file = Path(tmp) / "bab1.html"
            html_file.write_text(
                "<html><head><title>Judul HTML</title></head>"
                "<body><p>田中さんが来た。</p></body></html>",
                encoding="utf-8",
            )
            doc = read_document(html_file)
            self.assertEqual(doc.title, "Judul HTML")
            self.assertEqual(doc.paragraphs[0].text, "田中さんが来た。")

    def test_srt_vtt_ass_roundtrip_and_tag_safe_wrapping(self) -> None:
        tagged = (
            '<font color="yellow">Kalimat terjemahan ini cukup panjang '
            "sekali untuk diuji hari ini.</font>"
        )
        wrapped = wrap_cue(tagged, width=42)
        self.assertIn("\n", wrapped)
        self.assertTrue(wrapped.startswith('<font color="yellow">'))

        vtt_src = (
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.500\n"
            "<v 田中><ruby>東京<rp>(</rp><rt>とうきょう</rt><rp>)</rp></ruby>へ行く。\n"
        )
        doc_vtt = parse_vtt(vtt_src, "ep1")
        self.assertEqual(doc_vtt.paragraphs[0].text, "東京へ行く。")
        self.assertEqual(doc_vtt.ruby.get("東京"), "とうきょう")

        ass_src = (
            "[Script Info]\nTitle: Ep1\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:03.50,Default,Tanaka,0,0,0,,{\\an8}こんにちは。\\N元気？\n"
        )
        doc_ass = parse_ass(ass_src, "ep1")
        self.assertEqual(doc_ass.paragraphs[0].text, "こんにちは。\n元気？")

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            with TranslationCache(None) as cache:
                translator = Translator(cfg, [FakeEngine()], cache, Glossary("ep1"))
                res_vtt = translator.translate_document(doc_vtt)
                out_vtt = render_output(res_vtt, "vtt")
                self.assertTrue(out_vtt.startswith("WEBVTT"))
                out_srt = render_output(res_vtt, "srt")
                self.assertEqual(len(parse_srt(out_srt, "ep1").paragraphs), 1)
                out_ass = render_output(res_vtt, "ass")
                self.assertIn("Dialogue:", out_ass)
                out_html = render_output(res_vtt, "html")
                self.assertIn("<!DOCTYPE html>", out_html)

    def test_ocr_paragraph_preservation(self) -> None:
        cleaned = clean_ocr_text("田中 さん\n来た\n\n美咲 さん")
        self.assertEqual(cleaned, "田中さん来た\n\n美咲さん")

    def test_structured_logging_and_cli_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "run.jsonl"
            inp = tmp_path / "bab.txt"
            out = tmp_path / "bab_id.txt"
            inp.write_text("山田太郎さんは東京駅に行った。\n", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"JPTRANS_HOME": tmp}, clear=False),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code_ok = cli.main([
                    "-v", "--log-json", "--log-file", str(log_path),
                    "translate", str(inp), "--engine", "fake",
                    "--to", "id", "--format", "txt", "-o", str(out),
                ])
                self.assertEqual(code_ok, 0)
                self.assertIn("Yamada Tarō-san", out.read_text(encoding="utf-8"))
                log_lines = [
                    json.loads(line)
                    for line in log_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertTrue(any("timestamp" in row for row in log_lines))

                code_missing = cli.main(["-q", "translate", str(tmp_path / "404.txt")])
                self.assertEqual(code_missing, 1)

                code_bad_arg = cli.main(["--opsi-tidak-ada"])
                self.assertEqual(code_bad_arg, 2)

                with mock.patch("sys.stderr", None):
                    code_no_stderr = cli.main(["-q", "doctor"])
                self.assertEqual(code_no_stderr, 0)

                code_cache = cli.main(["cache", "stats"])
                self.assertEqual(code_cache, 0)
                code_clear = cli.main(["cache", "clear"])
                self.assertEqual(code_clear, 0)
            cli.configure_logging(quiet=True)

    def test_epub_xxe_rejection_and_glossary_cli_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_epub = tmp_path / "xxe.epub"
            with zipfile.ZipFile(bad_epub, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe "boom">]>'
                    "<container>&xxe;</container>",
                )
            with self.assertRaises(InputError):
                read_document(bad_epub)

            exp_file = tmp_path / "ekspor.json"
            with (
                mock.patch.dict(os.environ, {"JPTRANS_HOME": tmp}, clear=False),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    cli.main([
                        "glossary", "add", "--title", "SeriA", "紅蓮斬",
                        "--kind", "TERM", "--render-id", "Tebasan Teratai Merah",
                    ]),
                    0,
                )
                self.assertEqual(
                    cli.main(["glossary", "show", "--title", "SeriA"]), 0
                )
                self.assertEqual(
                    cli.main([
                        "glossary", "export", "--title", "SeriA", str(exp_file)
                    ]),
                    0,
                )
                self.assertEqual(
                    cli.main([
                        "glossary", "import", "--title", "SeriB", str(exp_file)
                    ]),
                    0,
                )
                self.assertEqual(
                    cli.main(["glossary", "remove", "--title", "SeriA", "紅蓮斬"]),
                    0,
                )
            cli.configure_logging(quiet=True)

    def test_disambig_coref_and_residue_modules(self) -> None:
        self.assertTrue(
            disambig.verb_run_before_honorific(
                "行", "くん", "ですか", before="駅まで"
            )
        )
        self.assertFalse(
            disambig.verb_run_before_honorific(
                "歩", "くん", "が来た", before=""
            )
        )
        self.assertFalse(
            disambig.verb_run_before_honorific(
                "歩", "くん", "だ", before="犯人は"
            )
        )
        misaki = models.GlossaryEntry("美咲", kind=models.PERSON, gender="f")
        masked = models.Masked(
            "美咲は時計を見た。",
            "[[E1]]は時計を見た。",
            {1: models.Slot(misaki)},
        )
        self.assertEqual(
            coref.pronoun_gender(masked, [masked], lambda e: e.gender), "f"
        )
        self.assertEqual(coref.explicit_pronoun("彼女は笑った。"), ("f", 1))
        self.assertEqual(coref.explicit_pronoun("彼女ができた。"), ("", 0))
        self.assertFalse(residue.has_japanese_residue("Halo [[E1]]!", "[[E1]]！"))
        self.assertTrue(residue.has_japanese_residue("Halo 未翻訳!", "テスト"))

    def test_local_web_server_security_and_lifecycle(self) -> None:
        class DummyServer:
            def __init__(self, cfg: Config) -> None:
                self.cfg = cfg
                self.token = "tok_uji_rahasia"
                self.allowed_hosts = frozenset({"127.0.0.1", "localhost", "::1"})
                self.allow_lan = False
                self.jobs = server.JobManager(
                    cfg, engine_builder=lambda _c: [FakeEngine()]
                )
                self.jobs.start()

        class NonClosingBytesIO(io.BytesIO):
            def close(self) -> None:
                self.flush()

        class MemorySocket:
            def __init__(self, raw_req: bytes) -> None:
                self._in = io.BytesIO(raw_req)
                self._out = NonClosingBytesIO()

            def settimeout(self, _timeout: float | None) -> None:
                pass

            def recv_into(self, buffer: bytearray | memoryview) -> int:
                return self._in.readinto(buffer)

            def makefile(self, mode: str, *_args: object, **_kwargs: object) -> io.BytesIO:
                return io.BytesIO() if "r" in mode else self._out

            def sendall(self, data: bytes) -> None:
                self._out.write(data)

            @property
            def response_bytes(self) -> bytes:
                return self._out.getvalue()

        def send_raw_http(dummy: DummyServer, raw_req: bytes) -> tuple[int, bytes]:
            mem_sock = MemorySocket(raw_req)
            addr = ("127.0.0.1", 12345)
            server.RequestHandler(mem_sock, addr, dummy)  # type: ignore[arg-type]
            raw_resp = mem_sock.response_bytes
            head, _, payload = raw_resp.partition(b"\r\n\r\n")
            status_code = int(head.splitlines()[0].split()[1])
            return status_code, payload

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            dummy = DummyServer(cfg)
            try:
                code_root, html_body = send_raw_http(
                    dummy, b"GET / HTTP/1.0\r\nHost: 127.0.0.1:8765\r\n\r\n"
                )
                self.assertEqual(code_root, 200)
                self.assertIn(b"<!DOCTYPE html>", html_body)
                self.assertIn(b'id="theme"', html_body)
                self.assertNotIn(b'href="#"', html_body)

                code_rebind, _ = send_raw_http(
                    dummy, b"GET / HTTP/1.0\r\nHost: [::1]evil.com\r\n\r\n"
                )
                self.assertEqual(code_rebind, 403)

                body = json.dumps({"text": "田中さんは来た。", "to": "id"}).encode()
                code_no_tok, _ = send_raw_http(
                    dummy,
                    b"POST /api/jobs HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body,
                )
                self.assertEqual(code_no_tok, 401)

                code_ok, job_resp = send_raw_http(
                    dummy,
                    b"POST /api/jobs HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    b"X-Token: tok_uji_rahasia\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body,
                )
                self.assertEqual(code_ok, 202)
                job_id = json.loads(job_resp.decode())["id"]

                status = ""
                for _ in range(30):
                    info = dummy.jobs.summary(job_id)
                    assert info is not None
                    status = info["status"]
                    if status in ("done", "failed"):
                        break
                    time.sleep(0.05)
                self.assertEqual(status, "done")

                dl_req = (
                    f"GET /api/jobs/{job_id}/download?fmt=txt HTTP/1.0\r\n"
                    "Host: 127.0.0.1\r\n"
                    "X-Token: tok_uji_rahasia\r\n\r\n"
                ).encode("ascii")
                code_dl, dl_body = send_raw_http(dummy, dl_req)
                self.assertEqual(code_dl, 200)
                self.assertIn("Tanaka-san", dl_body.decode("utf-8"))

                code_meta, meta_body = send_raw_http(
                    dummy,
                    b"GET /api/meta HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                    b"X-Token: tok_uji_rahasia\r\n\r\n",
                )
                self.assertEqual(code_meta, 200)
                meta_obj = json.loads(meta_body.decode("utf-8"))
                self.assertIn("id", meta_obj["languages"])
                self.assertTrue(any(e["name"] == "fake" for e in meta_obj["engines"]))

                sync_body = json.dumps({
                    "text": "田中さんは来た。",
                    "to": "id",
                    "honorifics": "drop",
                }).encode("utf-8")
                code_sync, sync_resp = send_raw_http(
                    dummy,
                    b"POST /api/translate HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    b"X-Token: tok_uji_rahasia\r\n"
                    + f"Content-Length: {len(sync_body)}\r\n\r\n".encode("ascii")
                    + sync_body,
                )
                self.assertEqual(code_sync, 200)
                sync_json = json.loads(sync_resp.decode("utf-8"))
                self.assertIn("Tanaka", sync_json["target"])
                self.assertNotIn("Tanaka-san", sync_json["target"])
            finally:
                dummy.jobs.stop()

    def test_epub_spine_relative_and_root_hrefs_with_html_themes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = Path(tmp) / "novel.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0"?>'
                    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>'
                    "</container>",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    '<?xml version="1.0"?>'
                    '<package xmlns="http://www.idpf.org/2007/opf">'
                    "<metadata><dc:title xmlns:dc=\"http://purl.org/dc/elements/1.1/\">"
                    "Novel Uji</dc:title></metadata>"
                    "<manifest>"
                    '<item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>'
                    '<item id="c2" href="/OEBPS/chap2.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                    "</manifest>"
                    '<spine><itemref idref="c1"/><itemref idref="c2"/></spine>'
                    "</package>",
                )
                zf.writestr(
                    "OEBPS/chap1.xhtml",
                    "<html><body><h1>第一章</h1>"
                    "<p><ruby>神崎<rt>かんざき</rt></ruby>"
                    "<ruby>悠真<rt>ゆうま</rt></ruby>さんは来た。</p></body></html>",
                )
                zf.writestr(
                    "OEBPS/chap2.xhtml",
                    "<html><body><h1>第二章</h1><p>東京は広い。</p></body></html>",
                )
            doc = read_document(epub_path)
            self.assertEqual(doc.title, "Novel Uji")
            self.assertEqual(len(doc.paragraphs), 4)
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            with TranslationCache(None) as cache:
                translator = Translator(cfg, [FakeEngine()], cache, Glossary("Novel Uji"))
                res = translator.translate_document(doc)
                html_out = render_output(res, "html")
                self.assertIn('id="th-dark"', html_out)
                self.assertIn('id="th-light"', html_out)
                self.assertIn("Kanzaki Yūma-san", html_out)

    def test_stdin_input_format_override_and_exit_code_three(self) -> None:
        srt_bytes = (
            "1\n00:00:01,000 --> 00:00:02,500\nこんにちは。\n"
        ).encode("utf-8")

        class FakeStdin:
            def __init__(self, payload: bytes) -> None:
                self.buffer = io.BytesIO(payload)

        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"JPTRANS_HOME": tmp}, clear=False),
                mock.patch("sys.stdin", FakeStdin(srt_bytes)),
                contextlib.redirect_stdout(stdout_buf),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = cli.main([
                    "-q", "translate", "-", "--input-format", "srt",
                    "--format", "vtt", "--engine", "fake", "--to", "id",
                ])
                self.assertEqual(code, 0)
                self.assertTrue(stdout_buf.getvalue().startswith("WEBVTT"))

                with mock.patch(
                    "jptrans.engines.fake.FakeEngine.translate",
                    side_effect=EngineUnavailable("fake", "mati"),
                ):
                    inp = Path(tmp) / "gagal.txt"
                    inp.write_text("こんにちは。\n", encoding="utf-8")
                    code_fail_all = cli.main([
                        "-q", "translate", str(inp), "--engine", "fake", "--no-cache",
                    ])
                    self.assertEqual(code_fail_all, 3)
            cli.configure_logging(quiet=True)

    def test_project_module_logger_invariants(self) -> None:
        import sys as _sys

        for name, mod in list(_sys.modules.items()):
            if mod is None or not (name == "jptrans" or name.startswith("jptrans.")):
                continue
            if name == "jptrans.__main__":
                continue
            mod_logger = getattr(mod, "logger", None)
            self.assertIsInstance(mod_logger, logging.Logger, f"{name} tanpa logger")

    def test_sdk_public_facade_and_plugin_registries(self) -> None:
        import jptrans
        from .config import REGISTERED_OUTPUT_FORMATS
        from .engines import ENGINE_FACTORIES
        from .readers import INPUT_FORMAT_READERS, READERS
        from .writers import CONTENT_TYPES, RENDERERS, SUFFIX_FORMATS

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(target_lang="id", engines=["fake"], home=Path(tmp))
            res = jptrans.translate_text(
                "山田太郎さんは東京駅に行った。", cfg=cfg, use_cache=False
            )
            self.assertIn("Yamada Tarō-san", res.target)

            with jptrans.create_translator(cfg, title="sdk_uji") as tr:
                res2 = tr.translate_text("美咲ちゃんが笑った。")
                self.assertIn("Misaki-chan", res2.target)
            self.assertIsNone(tr.cache._conn)

            inp_path = Path(tmp) / "sdk_in.txt"
            out_path = Path(tmp) / "sdk_out.txt"
            inp_path.write_text("田中さんは来た。\n", encoding="utf-8")
            res3 = jptrans.translate_file(inp_path, output=out_path, cfg=cfg)
            self.assertIn("Tanaka-san", res3.target)
            self.assertIn("Tanaka-san", out_path.read_text(encoding="utf-8"))

            try:
                jptrans.register_engine("fake_ext", lambda _c: FakeEngine(tag="ext"))
                jptrans.register_reader(
                    ".jptx",
                    lambda p, t, _e: read_text(p.read_text(encoding="utf-8"), t or p.stem),
                )
                jptrans.register_writer(
                    "jptout",
                    lambda r: f"OUT:{r.target}\n",
                    content_type="text/x-jpt",
                )
                ext_in = Path(tmp) / "bab.jptx"
                ext_out = Path(tmp) / "bab.jptout"
                ext_in.write_text("田中さんは来た。\n", encoding="utf-8")
                ext_cfg = Config(
                    target_lang="id",
                    engines=["fake_ext"],
                    output_format="jptout",
                    home=Path(tmp),
                )
                jptrans.translate_file(ext_in, output=ext_out, cfg=ext_cfg)
                rendered_ext = ext_out.read_text(encoding="utf-8")
                self.assertTrue(rendered_ext.startswith("OUT:"))
                self.assertIn("Tanaka-san", rendered_ext)
            finally:
                ENGINE_FACTORIES.pop("fake_ext", None)
                READERS.pop(".jptx", None)
                INPUT_FORMAT_READERS.pop("jptx", None)
                RENDERERS.pop("jptout", None)
                CONTENT_TYPES.pop("jptout", None)
                SUFFIX_FORMATS.pop(".jptout", None)
                if "jptout" in REGISTERED_OUTPUT_FORMATS:
                    REGISTERED_OUTPUT_FORMATS.remove("jptout")

    def test_unpack_bundle_to_multifile_package(self) -> None:
        loader = getattr(__import__("jptrans").__spec__, "loader", None)
        if not hasattr(loader, "ekstrak_paket"):
            return
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "extracted"
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code_ok = cli.main(["-q", "unpack", str(dest)])
                self.assertEqual(code_ok, 0)
                self.assertTrue((dest / "jptrans" / "__init__.py").is_file())
                self.assertTrue((dest / "jptrans" / "data" / "surnames.json").is_file())
                code_dup = cli.main(["-q", "unpack", str(dest)])
                self.assertEqual(code_dup, 2)
                code_force = cli.main(["-q", "unpack", str(dest), "--force"])
                self.assertEqual(code_force, 0)
            cli.configure_logging(quiet=True)


def run_tests(verbosity: int = 1, pattern: str = "") -> bool:
    """Jalankan seluruh TestCase di modul ini dan kembalikan ``True`` bila lulus."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__, fromlist=["*"]))
    if pattern:
        filtered = unittest.TestSuite()
        for group in suite:
            for case in group:
                if pattern.lower() in case.id().lower():
                    filtered.addTest(case)
        suite = filtered
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return result.wasSuccessful()
