"""Masukan komik: ``pages.json`` dari OCR mana pun, plus pembuat opsional via Tesseract.

Standard library tidak bisa men-decode JPEG/PNG, apalagi menemukan balon
dialog. Karena itu jptrans tidak melakukan OCR sendiri; ia menerima teks per
balon dalam format netral::

    {"title": "...", "pages": [{"page": 1, "image": "001.jpg",
      "bubbles": [{"id": 1, "text": "...", "box": [x, y, w, h]}]}]}

Format ini bisa dibuat oleh manga-ocr, mokuro, layanan cloud, atau ketikan
tangan. Tiap balon menjadi satu ``Paragraph`` dengan
``meta={"page", "bubble", "image", "box"}``, sehingga pipeline terjemahan untuk
komik sama persis dengan novel.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..errors import InputError, JptransError
from ..models import Document, Paragraph
from ..textnorm import decode_unicode_text

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")
OCR_TIMEOUT_SECONDS = 120
TESSERACT_HINT = (
    "Tesseract tidak ditemukan. Pasang dulu beserta data bahasa Jepang:\n"
    "  macOS   : brew install tesseract tesseract-lang\n"
    "  Debian  : sudo apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert\n"
    "  Windows : installer UB Mannheim (github.com/UB-Mannheim/tesseract), centang Japanese\n"
    "  Termux  : pkg install tesseract, lalu unduh jpn_vert.traineddata dari tessdata_best\n"
    "            ke $PREFIX/share/tessdata"
)
# Tesseract jpn sering menyisipkan spasi atau baris baru di antara karakter Jepang.
_CJK_GAP_RE = re.compile(
    r"(?<=[^\x00-\x7f])(?:[ \t]*\n[ \t]*(?!\n)|[ \t]+)(?=[^\x00-\x7f])"
)
_DIGITS_RE = re.compile(r"(\d+)")


def parse_pages(data: Any, title: str) -> Document:
    """Ubah objek ``pages.json`` yang sudah di-parse menjadi ``Document``.

    Args:
        data: Hasil ``json.loads``.
        title: Judul cadangan bila ``data`` tidak memuat ``"title"``.

    Returns:
        Dokumen dengan ``fmt="pages"``; balon tanpa teks dilewati.

    Raises:
        InputError: Struktur tidak sesuai format (pesan menyebut letak galatnya).
    """
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        raise InputError('pages.json harus berupa objek dengan daftar "pages"')
    paragraphs: list[Paragraph] = []
    for page_pos, page in enumerate(data["pages"], start=1):
        paragraphs.extend(_page_paragraphs(page, page_pos))
    doc_title = data.get("title") if isinstance(data.get("title"), str) else ""
    logger.debug("pages: %d halaman, %d balon", len(data["pages"]), len(paragraphs))
    return Document(title=doc_title or title, paragraphs=paragraphs, fmt="pages")


def _page_paragraphs(page: Any, page_pos: int) -> list[Paragraph]:
    where = f"halaman ke-{page_pos}"
    if not isinstance(page, dict) or not isinstance(page.get("bubbles", []), list):
        raise InputError(f'pages.json {where}: harus objek dengan daftar "bubbles"')
    page_no = _as_int(page.get("page", page_pos), f"{where}: page")
    image = page.get("image", "")
    if not isinstance(image, str):
        raise InputError(f"pages.json {where}: image harus teks")
    result = []
    for bubble_pos, bubble in enumerate(page.get("bubbles", []), start=1):
        spot = f"{where} balon ke-{bubble_pos}"
        if not isinstance(bubble, dict) or not isinstance(bubble.get("text", ""), str):
            raise InputError(f"pages.json {spot}: harus objek dengan text berupa teks")
        text = bubble.get("text", "").strip()
        if not text:
            continue
        meta = {
            "page": page_no,
            "bubble": _as_int(bubble.get("id", bubble_pos), f"{spot}: id"),
            "image": image,
            "box": _as_box(bubble.get("box"), spot),
        }
        result.append(Paragraph(text=text, meta=meta))
    return result


def _as_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"pages.json {where} harus bilangan bulat, bukan {value!r}")
    return value


def _as_box(value: Any, where: str) -> list[float] | None:
    if value is None:
        return None
    numbers_ok = isinstance(value, list) and all(
        isinstance(n, (int, float)) and not isinstance(n, bool) for n in value
    )
    if not numbers_ok or len(value) != 4:
        raise InputError(f"pages.json {where}: box harus [x, y, w, h]")
    return list(value)


def read_pages(path: Path, title: str | None = None) -> Document:
    """Baca berkas ``pages.json`` dari disk (UTF-8, boleh ber-BOM, atau UTF-16 ber-BOM).

    Args:
        path: Lokasi berkas.
        title: Judul; bawaan ``"title"`` di berkas, lalu nama berkas.

    Raises:
        InputError: Berkas tidak bisa dibaca, bukan JSON, atau strukturnya salah.
    """
    path = Path(path)
    try:
        text = decode_unicode_text(path.read_bytes())
    except OSError as exc:
        raise InputError(f"tidak bisa membaca {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise InputError(f"{path.name} harus UTF-8 atau UTF-16 ber-BOM "
                         f"(byte ke-{exc.start})") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path.name} bukan JSON yang sah (baris {exc.lineno})") from exc
    doc = parse_pages(data, path.stem)
    if title:
        doc.title = title
    doc.source_path = str(path)
    return doc


def natural_key(name: str) -> list[int | str]:
    """Kunci urut alami: ``2.jpg`` sebelum ``10.jpg``."""
    return [int(part) if part.isdigit() else part.casefold() for part in _DIGITS_RE.split(name)]


def list_images(folder: Path) -> list[Path]:
    """Gambar halaman di ``folder``, diurutkan secara alami."""
    images = [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(images, key=lambda p: natural_key(p.name))


def clean_ocr_text(text: str) -> str:
    """Rapikan keluaran Tesseract: hapus spasi/baris baru di antara karakter Jepang."""
    return _CJK_GAP_RE.sub("", text).strip()


def ocr_images_to_pages(folder: Path, out: Path, lang: str = "jpn_vert") -> Path:
    """Buat ``pages.json`` dari folder gambar komik dengan Tesseract (opsional).

    Satu halaman menjadi satu balon berisi seluruh teks halaman: memotong
    balon dialog butuh dekoder gambar (Pillow) atau detektor balon, yang
    sengaja tidak dijadikan dependensi. Akurasi Tesseract pada halaman manga
    utuh terbatas; hasilnya sebaiknya diperiksa sebelum diterjemahkan.

    Args:
        folder: Folder berisi gambar halaman (``001.jpg``, ``002.png``, ...).
        out: Lokasi ``pages.json`` yang akan ditulis.
        lang: Model Tesseract; ``jpn_vert`` untuk tategaki, ``jpn`` untuk horizontal.

    Returns:
        ``out`` setelah berkas ditulis.

    Raises:
        InputError: Tesseract tidak terpasang, folder kosong, atau OCR gagal.
        JptransError: Berkas keluaran tidak bisa ditulis.
    """
    tesseract = shutil.which("tesseract")
    if tesseract is None:
        raise InputError(TESSERACT_HINT)
    folder = Path(folder)
    if not folder.is_dir():
        raise InputError(f"folder gambar tidak ditemukan: {folder}")
    images = list_images(folder)
    if not images:
        raise InputError(f"tidak ada gambar ({', '.join(IMAGE_SUFFIXES)}) di {folder}")

    pages = []
    for number, image in enumerate(images, start=1):
        logger.info("OCR halaman %d/%d", number, len(images))
        text = clean_ocr_text(_run_tesseract(tesseract, image, lang))
        bubbles = [{"id": 1, "text": text, "box": None}] if text else []
        pages.append({"page": number, "image": image.name, "bubbles": bubbles})

    payload = {"title": folder.name, "pages": pages}
    out_path = Path(out)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise JptransError(f"tidak bisa menulis {out}: {exc.strerror or exc}") from exc
    return out_path


def _run_tesseract(tesseract: str, image: Path, lang: str) -> str:
    # psm 5 = satu blok teks vertikal; psm 6 = satu blok teks horizontal.
    psm = "5" if lang.endswith("_vert") else "6"
    command = [tesseract, str(image), "stdout", "-l", lang, "--psm", psm]
    try:
        done = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace",
            timeout=OCR_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise InputError(f"OCR {image.name} melebihi {OCR_TIMEOUT_SECONDS} detik") from exc
    except OSError as exc:
        raise InputError(f"tesseract tidak bisa dijalankan: {exc}") from exc
    if done.returncode != 0:
        detail = done.stderr.strip().splitlines()[-1:] or ["tanpa pesan"]
        raise InputError(f"tesseract gagal pada {image.name}: {detail[0]}")
    return done.stdout
