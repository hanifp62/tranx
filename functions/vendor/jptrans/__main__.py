"""Menjalankan jptrans sebagai modul: ``python -m jptrans ...``.

Kode keluar dari ``cli.main`` diteruskan ke sistem operasi. Versi Python
diperiksa sebelum ``cli`` diimpor, karena modul lain memakai sintaks 3.10+
yang membuat Python lama berhenti dengan traceback yang membingungkan.
"""

from __future__ import annotations

import logging
import sys

# Logger modul ada karena aturan proyek: setiap modul src/jptrans punya
# ``logger = logging.getLogger(__name__)`` (diperiksa tests/test_code_rules.py), agar log
# yang kelak ditambahkan ikut hierarki ``jptrans.*``. Modul ini belum menulis log. Baris ini
# dan pemeriksaan versi di bawahnya sengaja hanya memakai sintaks yang juga dipahami
# Python lama, sehingga Python < 3.11 sampai ke pesan singkat, bukan SyntaxError.
logger = logging.getLogger(__name__)

MIN_PYTHON = (3, 11)

if sys.version_info < MIN_PYTHON:
    sys.exit("jptrans butuh Python 3.11 atau lebih baru (terpasang: %s)"
             % sys.version.split()[0])

from jptrans.cli import main  # noqa: E402 (sesudah pemeriksaan versi)

if __name__ == "__main__":
    sys.exit(main())
