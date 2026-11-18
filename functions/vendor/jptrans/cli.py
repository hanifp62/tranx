"""Antarmuka baris perintah (CLI) dan konfigurasi logging terstruktur ``jptrans``.

Subperintah: ``translate``, ``detect``, ``ocr``, ``glossary``, ``cache``,
``serve``, ``doctor``, dan ``test``. Hanya modul ini yang menulis ke stdout/stderr
pengguna; seluruh modul pustaka melapor lewat pustaka ``logging`` berstempel waktu.

Kode keluar (standar otomasi CLI dan CI/CD):
- ``0``   : berhasil
- ``1``   : galat berkas masukan atau galat runtime umum
- ``2``   : argumen CLI atau konfigurasi tidak sah
- ``3``   : seluruh mesin penerjemah gagal
- ``130`` : dihentikan pengguna (Ctrl+C / SIGINT)
- ``141`` : pipa keluaran ditutup pembaca lebih dulu (SIGPIPE)
"""

from __future__ import annotations

import argparse
import datetime
import json
import locale
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import __version__, unpack_package
from .cache import PERSISTENT_CACHE, TranslationCache
from .config import (
    FOREIGN_NAMES,
    HONORIFIC_STYLES,
    LANGS,
    NAME_ORDERS,
    REGISTERED_OUTPUT_FORMATS,
    ROMANIZATIONS,
    Config,
    load_config,
)
from .engines import build_engines, describe_engines
from .errors import NON_UTF8_FS_HINT, ConfigError, InputError, JptransError
from .glossary import USER_SOURCE, Glossary, default_glossary_path
from .models import ENTITY_KINDS, Document, GlossaryEntry, TranslatedDocument
from .ner import candidates_to_entries, detect_entities
from .pipeline import Progress, Translator, estimate, janome_available
from .readers import INPUT_FORMAT_READERS, read_document, read_text
from .readers.pages import ocr_images_to_pages
from .readers.txt import decode_bytes
from .style import Renderer
from .textnorm import kata_to_hira
from .writers import SUFFIX_FORMATS, render_output, write_output

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_TEST_FAILED = 1
EXIT_INTERRUPTED = 130
EXIT_BROKEN_PIPE = 141
MAX_PORT = 65535
STDIN = "-"
STDOUT = "-"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
ONLINE_TEST_TEXT = "こんにちは。"

EPILOG = """\
contoh pemakaian:
  Windows : py translator.py translate .\\bab1.txt --to id -o .\\bab1_id.html
  macOS   : python3 translator.py translate novel.epub --to en -o novel_en.html
  Linux   : python3 translator.py translate episode01.vtt --to id
  Android : python ~/translator.py translate ~/storage/downloads/bab1.txt -o \\
              ~/storage/downloads/bab1_id.html
  iOS     : python3 translator.py translate bab1.txt --to id
  Luring  : python3 translator.py translate bab1.txt --engine fake
  Web LAN : python3 translator.py serve --lan
  Uji unit: python3 translator.py test -v

Kunci API dibaca dari variabel lingkungan atau berkas .env: DEEPL_API_KEY,
JPTRANS_LLM_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY,
OPENAI_API_KEY, LIBRETRANSLATE_API_KEY, MYMEMORY_EMAIL (opsional).
"""


class JsonLogFormatter(logging.Formatter):
    """Pemformat satu objek JSON per baris log untuk pemantauan terstruktur."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.datetime.fromtimestamp(
            record.created, tz=datetime.timezone.utc
        ).isoformat(timespec="milliseconds")
        payload: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    """Bangun parser argumen utama lengkap dengan seluruh subperintah."""
    parser = argparse.ArgumentParser(
        prog="translator.py",
        description=(
            "Terjemahkan novel, komik, subtitle, dan dokumen Jepang ke bahasa "
            "Indonesia atau Inggris dengan pelindungan nama bergaya subtitle."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"jptrans {__version__}",
        help="tampilkan versi lalu keluar",
    )
    _add_global_options(parser, defaults=True)
    common = argparse.ArgumentParser(add_help=False)
    _add_global_options(common, defaults=False)

    commands = parser.add_subparsers(
        dest="command", metavar="PERINTAH", required=True
    )
    _add_translate(commands, common)
    _add_detect(commands, common)
    _add_ocr(commands, common)
    _add_glossary(commands, common)
    _add_cache(commands, common)
    _add_serve(commands, common)
    _add_doctor(commands, common)
    _add_test(commands, common)
    _add_unpack(commands, common)
    return parser


def _add_global_options(
    parser: argparse.ArgumentParser, *, defaults: bool
) -> None:
    def default(value: Any) -> Any:
        return value if defaults else argparse.SUPPRESS

    group = parser.add_argument_group("opsi umum")
    group.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=default(0),
        help="tampilkan log INFO (-vv untuk DEBUG)",
    )
    group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=default(False),
        help="hanya tampilkan pesan galat",
    )
    group.add_argument(
        "--log-file",
        type=Path,
        default=default(None),
        help="tulis log juga ke berkas ini (UTF-8)",
    )
    group.add_argument(
        "--log-json",
        action="store_true",
        default=default(False),
        help="format log sebagai JSON terstruktur per baris",
    )
    group.add_argument(
        "--debug",
        action="store_true",
        default=default(False),
        help="log level DEBUG dan traceback penuh saat galat",
    )
    group.add_argument(
        "--config",
        type=Path,
        default=default(None),
        help="berkas config JSON (bawaan: <JPTRANS_HOME>/config.json)",
    )


def _add_translate(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "translate",
        parents=[common],
        help="terjemahkan berkas dokumen atau aliran stdin",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub.add_argument(
        "input",
        help="berkas .txt/.md/.html/.epub/.srt/.vtt/.ass/.json, atau - (stdin)",
    )
    sub.add_argument(
        "-o",
        "--output",
        help="berkas keluaran, atau - untuk stdout",
    )
    sub.add_argument(
        "--to", dest="target_lang", choices=LANGS, help="bahasa sasaran"
    )
    sub.add_argument(
        "--title", help="judul karya; menentukan berkas glosarium"
    )
    sub.add_argument(
        "--engine",
        dest="engines",
        action="extend",
        nargs="+",
        metavar="NAMA",
        help="urutan mesin, mis. --engine deepl mymemory",
    )
    sub.add_argument(
        "--llm-model",
        dest="llm_model",
        help="nama model LLM untuk mesin llm (mis. gemini-2.5-flash)",
    )
    sub.add_argument(
        "--llm-base-url",
        dest="llm_base_url",
        help="endpoint dasar API OpenAI-compatible untuk mesin llm",
    )
    sub.add_argument(
        "--input-format",
        choices=tuple(sorted(INPUT_FORMAT_READERS)),
        help="paksa pembaca format masukan tertentu",
    )
    sub.add_argument(
        "--format",
        choices=tuple(REGISTERED_OUTPUT_FORMATS),
        help="format keluaran",
    )
    sub.add_argument(
        "--glossary",
        type=Path,
        help="berkas glosarium yang dibaca dan diperbarui",
    )
    sub.add_argument(
        "--honorifics",
        dest="honorific_style",
        choices=HONORIFIC_STYLES,
        help="keep: Tanaka-san, localize: Pak Tanaka, drop: Tanaka",
    )
    sub.add_argument(
        "--name-order",
        choices=NAME_ORDERS,
        help="jp: Yamada Tarō, western: Tarō Yamada",
    )
    sub.add_argument(
        "--romaji",
        dest="romanization",
        choices=ROMANIZATIONS,
        help="macron: Satō, kana: Satou, plain: Sato",
    )
    sub.add_argument(
        "--foreign-names",
        choices=FOREIGN_NAMES,
        help="nama asing katakana: auto, dict, atau hepburn",
    )
    sub.add_argument(
        "--allow-unofficial",
        action="store_true",
        default=None,
        help="izinkan endpoint Google tidak resmi",
    )
    sub.add_argument(
        "--no-detect",
        action="store_true",
        help="matikan deteksi entitas otomatis",
    )
    sub.add_argument(
        "--no-cache",
        action="store_true",
        help="pakai cache sementara di memori",
    )
    sub.add_argument(
        "--dry-run",
        action="store_true",
        help="perkirakan kalimat, karakter, dan kuota tanpa memanggil mesin",
    )
    sub.add_argument(
        "--limit",
        type=_positive_int,
        metavar="N",
        help="terjemahkan hanya N paragraf pertama",
    )
    sub.add_argument(
        "--encoding",
        help="paksa encoding berkas teks (mis. cp932, euc_jp, utf-8)",
    )
    sub.add_argument(
        "--bilingual",
        action="store_true",
        help="format txt: tulis baris Jepang asli di atas terjemahan",
    )
    sub.set_defaults(handler=cmd_translate)


def _add_detect(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "detect",
        parents=[common],
        help="tampilkan kandidat nama dan istilah di sebuah berkas",
    )
    sub.add_argument("input", help="berkas masukan, atau - untuk stdin")
    sub.add_argument("--title", help="judul karya")
    sub.add_argument("--glossary", type=Path, help="berkas glosarium")
    sub.add_argument("--encoding", help="paksa encoding berkas teks")
    sub.add_argument(
        "--input-format",
        choices=tuple(sorted(INPUT_FORMAT_READERS)),
        help="paksa pembaca format masukan tertentu",
    )
    sub.add_argument(
        "--save",
        action="store_true",
        help="simpan kandidat ke berkas glosarium",
    )
    sub.set_defaults(handler=cmd_detect)


def _add_ocr(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "ocr",
        parents=[common],
        help="ekstrak teks folder gambar komik/dokumen ke pages.json via Tesseract",
    )
    sub.add_argument("folder", type=Path, help="folder berisi gambar halaman")
    sub.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("pages.json"),
        help="lokasi berkas pages.json keluaran (bawaan: pages.json)",
    )
    sub.add_argument(
        "--lang",
        default="jpn_vert",
        help="model bahasa Tesseract (bawaan: jpn_vert; horizontal: jpn)",
    )
    sub.set_defaults(handler=cmd_ocr)


def _add_glossary(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "glossary", parents=[common], help="kelola glosarium per judul"
    )
    target = argparse.ArgumentParser(add_help=False)
    where = target.add_argument_group("glosarium")
    where.add_argument("--title", help="judul karya (berkas bawaan per judul)")
    where.add_argument("--glossary", type=Path, help="lokasi berkas glosarium")
    actions = sub.add_subparsers(dest="action", metavar="AKSI", required=True)

    show = actions.add_parser(
        "show", parents=[common, target], help="tampilkan isi glosarium"
    )
    show.set_defaults(handler=cmd_glossary_show)

    add = actions.add_parser(
        "add", parents=[common, target], help="tambah atau ubah satu entri"
    )
    add.add_argument("surface", help="tulisan Jepang, mis. 田中")
    add.add_argument(
        "--kind",
        choices=ENTITY_KINDS,
        default=ENTITY_KINDS[0],
        help="jenis entri",
    )
    add.add_argument("--reading", default="", help="bacaan kana, mis. たなか")
    add.add_argument(
        "--romaji", default="", help="ejaan Latin pilihan, mis. Tanaka"
    )
    add.add_argument("--render-id", default="", help="bentuk akhir Indonesia")
    add.add_argument("--render-en", default="", help="bentuk akhir Inggris")
    add.add_argument(
        "--gloss-id", default="", help="arti kemunculan pertama (ID)"
    )
    add.add_argument(
        "--gloss-en", default="", help="arti kemunculan pertama (EN)"
    )
    add.add_argument(
        "--gender",
        choices=("m", "f", "x", ""),
        default="",
        help="m, f, atau x (jangan ditebak)",
    )
    add.add_argument(
        "--alias",
        dest="aliases",
        action="append",
        default=[],
        help="tulisan lain untuk entitas yang sama",
    )
    add.add_argument(
        "--allow-compound",
        action="store_true",
        help="cocokkan walau menempel ke kanji lain",
    )
    add.set_defaults(handler=cmd_glossary_add)

    remove = actions.add_parser(
        "remove", parents=[common, target], help="hapus satu entri"
    )
    remove.add_argument("surface", help="tulisan atau alias")
    remove.set_defaults(handler=cmd_glossary_remove)

    export = actions.add_parser(
        "export",
        parents=[common, target],
        help="salin glosarium ke berkas JSON lain",
    )
    export.add_argument("path", type=Path, help="berkas tujuan")
    export.set_defaults(handler=cmd_glossary_export)

    imp = actions.add_parser(
        "import",
        parents=[common, target],
        help="gabungkan entri dari berkas JSON ke glosarium",
    )
    imp.add_argument("path", type=Path, help="berkas glosarium sumber")
    imp.set_defaults(handler=cmd_glossary_import)


def _add_cache(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "cache", parents=[common], help="lihat statistik atau bersihkan cache"
    )
    actions = sub.add_subparsers(dest="action", metavar="AKSI", required=True)
    stats_cmd = actions.add_parser(
        "stats", parents=[common], help="tampilkan jumlah entri cache per mesin"
    )
    stats_cmd.set_defaults(handler=cmd_cache_stats)
    clear_cmd = actions.add_parser(
        "clear", parents=[common], help="kosongkan seluruh isi cache terjemahan"
    )
    clear_cmd.set_defaults(handler=cmd_cache_clear)


def _add_serve(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "serve", parents=[common], help="jalankan antarmuka web lokal"
    )
    sub.add_argument(
        "--host", default="127.0.0.1", help="alamat bind (bawaan 127.0.0.1)"
    )
    sub.add_argument(
        "--port",
        type=_port,
        default=8765,
        help="port (bawaan 8765; 0 = pilih otomatis)",
    )
    sub.add_argument(
        "--lan",
        action="store_true",
        help="bind 0.0.0.0 agar dapat diakses perangkat di jaringan LAN yang sama",
    )
    sub.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="buka peramban secara otomatis setelah server siap",
    )
    sub.set_defaults(handler=cmd_serve)


def _add_doctor(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "doctor",
        parents=[common],
        help="periksa versi Python, folder data, mesin, dan plugin",
    )
    sub.add_argument(
        "--online",
        action="store_true",
        help="uji koneksi nyata ke tiap mesin yang tersedia",
    )
    sub.set_defaults(handler=cmd_doctor)


def _add_test(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "test",
        parents=[common],
        help="jalankan rangkaian unit test otomatis bawaan",
    )
    sub.add_argument(
        "-k",
        "--pattern",
        default="",
        help="jalankan hanya pengujian yang namanya memuat pola ini",
    )
    sub.set_defaults(handler=cmd_test)


def _add_unpack(commands: Any, common: argparse.ArgumentParser) -> None:
    sub = commands.add_parser(
        "unpack",
        parents=[common],
        help="ekstrak skrip tunggal ini menjadi paket multi-berkas jptrans/",
    )
    sub.add_argument(
        "dest",
        type=Path,
        help="folder induk tujuan (akan membuat <dest>/jptrans/...)",
    )
    sub.add_argument(
        "--force",
        action="store_true",
        help="timpa berkas yang sudah ada di folder tujuan",
    )
    sub.set_defaults(handler=cmd_unpack)


def _port(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"bukan bilangan bulat: {text!r}"
        ) from exc
    if not 0 <= value <= MAX_PORT:
        raise argparse.ArgumentTypeError(f"port harus 0 sampai {MAX_PORT}")
    return value


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"bukan bilangan bulat: {text!r}"
        ) from exc
    if value < 1:
        raise argparse.ArgumentTypeError("harus minimal 1")
    return value


def main(argv: list[str] | None = None) -> int:
    """Titik masuk utama CLI; mengembalikan kode keluar numerik."""
    _use_utf8_stdout()
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_OK
    stdout = _StdoutWatch(sys.stdout)
    try:
        configure_logging(
            args.verbose,
            args.quiet,
            args.log_file,
            args.debug,
            log_json=args.log_json,
        )
        with stdout:
            code: int = args.handler(args)
            if sys.stdout is not None:
                sys.stdout.flush()
        return code
    except BrokenPipeError:
        if not stdout.broken:
            raise
        _silence_stdout()
        return EXIT_BROKEN_PIPE
    except KeyboardInterrupt:
        _err(
            "\nDihentikan. Kalimat yang sudah selesai tersimpan di cache; "
            "jalankan perintah yang sama untuk melanjutkan."
        )
        return EXIT_INTERRUPTED
    except JptransError as exc:
        if args.debug:
            traceback.print_exc()
        _err(f"galat: {exc}")
        return exc.exit_code
    except UnicodeEncodeError:
        if _filesystem_is_utf8():
            raise
        if args.debug:
            traceback.print_exc()
        _err(f"galat: {NON_UTF8_FS_HINT}")
        return JptransError.exit_code


def configure_logging(
    verbose: int = 0,
    quiet: bool = False,
    log_file: Path | None = None,
    debug: bool = False,
    *,
    log_json: bool = False,
) -> None:
    """Pasang handler log berstempel waktu (atau JSON) pada logger ``jptrans``."""
    if debug or verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.ERROR if quiet else logging.WARNING
    root = logging.getLogger("jptrans")
    for handler in [
        h for h in root.handlers if getattr(h, "_jptrans_cli", False)
    ]:
        root.removeHandler(handler)
        handler.close()
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(
                f"berkas log {log_file} tidak bisa dibuka: {exc}"
            ) from exc
    formatter: logging.Formatter = (
        JsonLogFormatter()
        if log_json
        else logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    )
    for handler in handlers:
        handler.setFormatter(formatter)
        handler._jptrans_cli = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)


def cmd_translate(args: argparse.Namespace) -> int:
    """Subperintah ``translate``."""
    cfg = _load_config(args, _translate_overrides(args))
    doc = _read_input(
        args.input, args.title, args.encoding, args.input_format
    )
    if args.limit:
        doc.paragraphs = doc.paragraphs[: args.limit]
    glossary_path = args.glossary or default_glossary_path(cfg, doc.title)
    glossary = Glossary.load(glossary_path, doc.title)
    if args.dry_run:
        _print_estimate(estimate(doc, cfg, glossary))
        return EXIT_OK
    engines = build_engines(cfg)
    logger.info("mesin aktif: %s", ", ".join(engine.name for engine in engines))
    has_tty = sys.stderr is not None and sys.stderr.isatty()
    progress = None if args.quiet or not has_tty else _show_progress
    with TranslationCache(None if args.no_cache else cfg.cache_path) as cache:
        translator = Translator(
            cfg,
            engines,
            cache,
            glossary,
            progress=progress,
            glossary_path=glossary_path,
        )
        result = translator.translate_document(doc)
    if progress is not None:
        _err("")
    destination = _write_result(result, args, cfg)
    if not args.quiet:
        _print_summary(result, destination, to_stderr=destination is None)
    return EXIT_OK


def _translate_overrides(args: argparse.Namespace) -> dict[str, Any]:
    engines = None
    if args.engines:
        engines = [
            name.strip()
            for item in args.engines
            for name in item.split(",")
            if name.strip()
        ]
    return {
        "target_lang": args.target_lang,
        "engines": engines,
        "llm_model": args.llm_model,
        "llm_base_url": args.llm_base_url,
        "honorific_style": args.honorific_style,
        "name_order": args.name_order,
        "romanization": args.romanization,
        "foreign_names": args.foreign_names,
        "allow_unofficial": args.allow_unofficial,
        "auto_detect": False if args.no_detect else None,
        "output_format": args.format,
    }


def _write_result(
    result: TranslatedDocument, args: argparse.Namespace, cfg: Config
) -> Path | None:
    to_stdout = args.output == STDOUT or (
        args.output is None and args.input == STDIN
    )
    out = None if to_stdout or args.output is None else Path(args.output)
    fmt = args.format or (
        SUFFIX_FORMATS.get(out.suffix.lower()) if out else None
    )
    fmt = fmt or cfg.output_format
    if to_stdout:
        if sys.stdout is not None:
            sys.stdout.write(
                render_output(result, fmt, bilingual=args.bilingual)
            )
        return None
    if out is None:
        source = Path(args.input)
        out = source.with_name(f"{source.stem}.{cfg.target_lang}.{fmt}")
    return write_output(result, out, fmt, bilingual=args.bilingual)


def _print_summary(
    result: TranslatedDocument, out: Path | None, *, to_stderr: bool
) -> None:
    stats = result.stats
    statuses = ", ".join(
        f"{name} {count}" for name, count in stats["by_status"].items()
    )
    total = sum(stats["by_status"].values())
    lines = [
        f"Selesai: {total} kalimat ({statuses or '-'}) "
        f"dalam {stats['seconds']} detik."
    ]
    if stats.get("by_engine"):
        engines = ", ".join(
            f"{name} {count}" for name, count in stats["by_engine"].items()
        )
        lines.append(
            f"Mesin: {engines}; {stats['requests']} permintaan, "
            f"{stats['chars_sent']} karakter terkirim."
        )
    if stats.get("new_entries"):
        lines.append(
            f"Glosarium: {stats['new_entries']} entri baru (periksa dengan "
            f"'python3 translator.py glossary show "
            f"--title \"{result.document.title}\"')."
        )
    failed = stats["by_status"].get("failed", 0)
    if failed:
        lines.append(
            f"Peringatan: {failed} kalimat gagal diterjemahkan "
            "dan ditampilkan asli."
        )
    partial = stats["by_status"].get("partial", 0)
    if partial:
        lines.append(
            f"Peringatan: {partial} kalimat masih memuat huruf Jepang."
        )
    if out is not None:
        lines.append(f"Keluaran: {out}")
    for line in lines:
        (_err if to_stderr else print)(line)


def _print_estimate(info: dict) -> None:
    print(f"Judul        : {info['title']}")
    print(f"Paragraf     : {info['paragraphs']}")
    print(
        f"Kalimat      : {info['sentences']} "
        f"({info['translatable']} diterjemahkan, {info['plain']} disalin)"
    )
    print(
        f"Karakter     : {info['source_chars']} asli, "
        f"{info['masked_chars']} setelah masking"
    )
    print(
        f"Entitas      : {info['entities']} dimasking, "
        f"{info['new_entries']} entri baru dari deteksi"
    )
    if info["unrenderable"]:
        print(
            f"Tanpa bacaan : {', '.join(info['unrenderable'])} "
            "(ejaan ditanyakan ke mesin)"
        )
    print("Permintaan per mesin:")
    for engine in info["engines"]:
        state = "siap" if engine["available"] else "tidak tersedia"
        print(
            f"  {engine['name']:<15} {engine['requests']:>5}  "
            f"({state}: {engine['reason']})"
        )
    print("Perkiraan kuota gratis (bila semua dikirim ke satu mesin):")
    for name, quota in info["quota"].items():
        print(
            f"  {name:<15} {quota['percent']:>6}% dari "
            f"{quota['limit']} karakter/{quota['period']}"
        )


def _show_progress(progress: Progress) -> None:
    if sys.stderr is not None:
        sys.stderr.write(
            f"\r[{progress.done}/{progress.total}] {progress.message:<12}"
        )
        sys.stderr.flush()


def cmd_detect(args: argparse.Namespace) -> int:
    """Subperintah ``detect``."""
    cfg = _load_config(args)
    doc = _read_input(
        args.input, args.title, args.encoding, args.input_format
    )
    glossary_path = args.glossary or default_glossary_path(cfg, doc.title)
    glossary = Glossary.load(glossary_path, doc.title)
    known = set(glossary.surface_map(confirmed_only=False))
    candidates = detect_entities(doc, known, use_janome=janome_available())
    locked, review = candidates_to_entries(candidates, cfg)
    status = {entry.surface: "kunci" for entry in locked}
    status.update({entry.surface: "tinjau" for entry in review})
    rows = [
        (
            f"{cand.score:.2f}",
            cand.kind,
            status.get(cand.surface, "-"),
            cand.reading,
            str(cand.count),
            cand.surface,
        )
        for cand in candidates
    ]
    _print_table(("skor", "jenis", "status", "bacaan", "jumlah", "tulisan"), rows)
    print(
        f"{len(candidates)} kandidat: "
        f"{len(locked)} dikunci, {len(review)} perlu ditinjau."
    )
    if args.save:
        added = sum(glossary.upsert(entry) for entry in locked + review)
        glossary.save(glossary_path)
        print(f"{added} entri disimpan ke {glossary_path}")
    return EXIT_OK


def cmd_ocr(args: argparse.Namespace) -> int:
    """Subperintah ``ocr``: jalankan Tesseract pada folder gambar ke ``pages.json``."""
    _load_config(args)
    out = ocr_images_to_pages(args.folder, args.output, args.lang)
    print(f"Hasil OCR disimpan ke {out}")
    return EXIT_OK


def cmd_glossary_show(args: argparse.Namespace) -> int:
    """Subperintah ``glossary show``."""
    cfg, path, glossary = _open_glossary(args)
    renderer = Renderer(cfg)
    rows = [
        (
            entry.surface,
            entry.kind,
            entry.reading,
            renderer.base_name(entry) or "?",
            "ya" if entry.confirmed else "tinjau",
            entry.source,
        )
        for entry in glossary
    ]
    print(f"Glosarium '{glossary.title}' ({path}): {len(glossary)} entri")
    if rows:
        _print_table(
            ("tulisan", "jenis", "bacaan", "bentuk", "pasti", "asal"), rows
        )
    return EXIT_OK


def cmd_glossary_add(args: argparse.Namespace) -> int:
    """Subperintah ``glossary add``."""
    _, path, glossary = _open_glossary(args)
    entry = GlossaryEntry(
        surface=args.surface.strip(),
        kind=args.kind,
        reading=kata_to_hira(args.reading),
        romaji=args.romaji,
        render_id=args.render_id,
        render_en=args.render_en,
        gloss_id=args.gloss_id,
        gloss_en=args.gloss_en,
        gender=args.gender,
        aliases=tuple(args.aliases),
        allow_compound=args.allow_compound,
        confirmed=True,
        source=USER_SOURCE,
    )
    if not entry.surface:
        raise ConfigError("tulisan entri tidak boleh kosong")
    glossary.upsert(entry, overwrite_confirmed=True)
    glossary.save(path)
    print(f"Entri {entry.surface} disimpan ke {path}")
    return EXIT_OK


def cmd_glossary_remove(args: argparse.Namespace) -> int:
    """Subperintah ``glossary remove``."""
    _, path, glossary = _open_glossary(args)
    if not glossary.remove(args.surface):
        raise InputError(f"entri {args.surface} tidak ada di {path}")
    glossary.save(path)
    print(f"Entri {args.surface} dihapus dari {path}")
    return EXIT_OK


def cmd_glossary_export(args: argparse.Namespace) -> int:
    """Subperintah ``glossary export``."""
    _, path, glossary = _open_glossary(args)
    glossary.save(args.path)
    print(f"{len(glossary)} entri dari {path} diekspor ke {args.path}")
    return EXIT_OK


def cmd_glossary_import(args: argparse.Namespace) -> int:
    """Subperintah ``glossary import``."""
    _, path, glossary = _open_glossary(args)
    if not args.path.is_file():
        raise InputError(f"berkas glosarium tidak ditemukan: {args.path}")
    incoming = Glossary.load(args.path)
    added = sum(glossary.upsert(entry) for entry in incoming)
    glossary.save(path)
    print(f"{added} dari {len(incoming)} entri diimpor ke {path}")
    return EXIT_OK


def _open_glossary(
    args: argparse.Namespace,
) -> tuple[Config, Path, Glossary]:
    cfg = _load_config(args)
    if args.glossary is None and not args.title:
        raise ConfigError("sebutkan --title JUDUL atau --glossary BERKAS")
    path = args.glossary or default_glossary_path(cfg, args.title)
    return cfg, path, Glossary.load(path, args.title)


def cmd_cache_stats(args: argparse.Namespace) -> int:
    """Subperintah ``cache stats``."""
    cfg = _load_config(args)
    with TranslationCache(cfg.cache_path) as cache:
        info = cache.stats()
    print(f"Lokasi : {info['path']}")
    print(f"Total  : {info['entries']} entri")
    if info["per_engine"]:
        for engine, count in sorted(info["per_engine"].items()):
            print(f"  {engine:<15} {count}")
    return EXIT_OK


def cmd_cache_clear(args: argparse.Namespace) -> int:
    """Subperintah ``cache clear``."""
    cfg = _load_config(args)
    with TranslationCache(cfg.cache_path) as cache:
        removed = cache.clear()
    print(f"Cache dibersihkan: {removed} entri dihapus dari {cfg.cache_path}")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Subperintah ``serve``."""
    from .server import serve

    cfg = _load_config(args)
    serve(
        cfg,
        args.host,
        args.port,
        lan=args.lan,
        open_browser=args.open_browser,
        on_ready=_announce_server,
    )
    return EXIT_OK


def _announce_server(url: str, lan: bool) -> None:
    print(
        f"jptrans {__version__} siap. "
        "Buka alamat ini di browser (berisi token rahasia):"
    )
    print(f"  {url}")
    if lan:
        print(
            "Mode LAN aktif: siapa pun di jaringan lokal yang memiliki "
            "tautan bertoken ini dapat memakai server."
        )
    print("Tekan Ctrl+C untuk berhenti.")


def cmd_doctor(args: argparse.Namespace) -> int:
    """Subperintah ``doctor``."""
    cfg = _load_config(args)
    print(f"jptrans  : {__version__}")
    print(f"Python   : {platform.python_version()} ({sys.executable})")
    print(f"Platform : {platform.platform()}")
    fs_note = "" if _filesystem_is_utf8() else f" ({NON_UTF8_FS_HINT})"
    print(
        f"Encoding : nama berkas {sys.getfilesystemencoding()}, "
        f"locale {locale.getencoding()}, "
        f"mode UTF-8 {'aktif' if sys.flags.utf8_mode else 'mati'}{fs_note}"
    )
    print(
        f"Data     : {cfg.home} "
        f"({'ada' if cfg.home.is_dir() else 'belum dibuat'})"
    )
    cache_note = (
        ""
        if PERSISTENT_CACHE
        else " (sqlite3 tidak ada: cache hanya di memori)"
    )
    print(f"Cache    : {cfg.cache_path}{cache_note}")
    print(f"Glosarium: {cfg.glossary_dir}")
    print("Mesin:")
    for name, available, reason in describe_engines(cfg):
        print(f"  [{'ok' if available else '--'}] {name:<15} {reason}")
    tesseract = shutil.which("tesseract")
    print("Plugin opsional:")
    janome = (
        "terpasang"
        if janome_available()
        else "tidak ada (pip install janome)"
    )
    print(f"  janome    : {janome}")
    print(
        f"  tesseract : "
        f"{tesseract or 'tidak ada (OCR komik tidak tersedia)'}"
    )
    if args.online:
        _doctor_online(cfg)
    return EXIT_OK


def _doctor_online(cfg: Config) -> None:
    print("Uji koneksi:")
    try:
        engines = build_engines(
            cfg, [name for name, ok, _ in describe_engines(cfg) if ok]
        )
    except ConfigError as exc:
        print(f"  {exc}")
        return
    for engine in engines:
        started = time.monotonic()
        try:
            result = engine.translate([ONLINE_TEST_TEXT], "ja", cfg.target_lang)
        except JptransError as exc:
            print(f"  [gagal] {engine.name}: {exc}")
            continue
        elapsed = time.monotonic() - started
        print(f"  [ok] {engine.name}: {result[0]!r} ({elapsed:.1f} s)")


def cmd_test(args: argparse.Namespace) -> int:
    """Subperintah ``test``: jalankan suite pengujian otomatis bawaan."""
    from .selftest import run_tests

    verbosity = 2 if args.verbose else (0 if args.quiet else 1)
    ok = run_tests(verbosity=verbosity, pattern=args.pattern)
    return EXIT_OK if ok else EXIT_TEST_FAILED


def cmd_unpack(args: argparse.Namespace) -> int:
    """Subperintah ``unpack``: ekstrak paket ``jptrans`` untuk pengembangan aplikasi."""
    written = unpack_package(args.dest, overwrite=args.force)
    print(f"{len(written)} berkas paket diekstrak ke {Path(args.dest) / 'jptrans'}")
    return EXIT_OK


def _load_config(
    args: argparse.Namespace, overrides: dict[str, Any] | None = None
) -> Config:
    return load_config(args.config, overrides)


def _read_input(
    source: str,
    title: str | None,
    encoding: str | None,
    input_format: str | None = None,
) -> Document:
    if source != STDIN:
        return read_document(
            Path(source),
            title=title,
            encoding=encoding,
            input_format=input_format,
        )
    raw = (
        sys.stdin.buffer.read()
        if hasattr(sys.stdin, "buffer")
        else sys.stdin.read().encode()
    )
    if input_format and input_format != "auto":
        with tempfile.TemporaryDirectory(prefix="jptrans-stdin-") as folder:
            temp_path = Path(folder) / f"stdin.{input_format}"
            temp_path.write_bytes(raw)
            doc = read_document(
                temp_path,
                title=title or "stdin",
                encoding=encoding,
                input_format=input_format,
            )
            doc.source_path = ""
            return doc
    return read_text(decode_bytes(raw, encoding), title or "stdin")


def _print_table(
    header: Sequence[str], rows: Sequence[Sequence[str]]
) -> None:
    widths = [
        max(_width(row[i]) for row in [header, *rows])
        for i in range(len(header))
    ]
    for row in [header, *rows]:
        print(
            "  ".join(
                _pad(cell, width) for cell, width in zip(row, widths)
            ).rstrip()
        )


def _width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text
    )


def _pad(text: str, width: int) -> str:
    return text + " " * (width - _width(text))


def _err(message: str) -> None:
    if sys.stderr is not None:
        print(message, file=sys.stderr)


def _silence_stdout() -> None:
    logger.debug("stdout ditutup pembaca; sisa keluaran dibuang")
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        if sys.stdout is not None:
            os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        logger.debug("stdout tidak bisa dialihkan ke devnull")
    finally:
        os.close(devnull)


class _StdoutWatch:
    """Pembungkus ``sys.stdout`` yang mendeteksi ``BrokenPipeError`` pada stdout."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.broken = False

    def __enter__(self) -> _StdoutWatch:
        if self.stream is not None:
            sys.stdout = self  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: object) -> None:
        if sys.stdout is self:
            sys.stdout = self.stream

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)

    def write(self, text: str) -> int:
        return self._guard(self.stream.write, text)

    def writelines(self, lines: Any) -> None:
        self._guard(self.stream.writelines, lines)

    def flush(self) -> None:
        self._guard(self.stream.flush)

    def _guard(self, method: Callable[..., Any], *args: Any) -> Any:
        try:
            return method(*args)
        except BrokenPipeError:
            self.broken = True
            raise


def _filesystem_is_utf8() -> bool:
    return sys.getfilesystemencoding().lower().replace("-", "") == "utf8"


def _use_utf8_stdout() -> None:
    for stream, errors in (
        (sys.stdout, "surrogateescape"),
        (sys.stderr, "backslashreplace"),
    ):
        reconfigure: Callable[..., None] | None = getattr(
            stream, "reconfigure", None
        )
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors=errors)
            except (OSError, ValueError):
                logger.debug("stream tidak bisa dikonfigurasi ulang ke UTF-8")


if __name__ == "__main__":
    sys.exit(main())
