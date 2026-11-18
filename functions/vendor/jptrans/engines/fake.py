"""Mesin palsu yang deterministik, untuk tes dan demo tanpa jaringan.

Mesin ini tidak menerjemahkan apa pun. Secara bawaan ia hanya memberi
awalan pada teks dan membiarkan penanda ``[[E#]]`` utuh, sehingga hasil
akhir pipeline bisa diperiksa dengan pasti. Opsi lain meniru kelakuan
buruk mesin sungguhan: penanda hilang, urutan penanda berubah, atau galat.

Untuk menguji lewat CLI tanpa jaringan, ``--engine fake`` bisa diberi jawaban
berskrip dari berkas JSON ``{teks termasking: jawaban}`` yang ditunjuk
``JPTRANS_FAKE_REPLIES`` (``load_replies``). Jawaban berskrip diperlakukan
seperti jawaban mesin sungguhan (misalnya diperiksa sisa huruf Jepangnya) dan
disimpan di cache dengan tag sendiri (``replies_tag``), jadi tidak tertukar
dengan gema bawaan walau cache tidak dimatikan.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..errors import ConfigError
from ..protect import EXACT_TOKEN_RE, TOKEN_TEMPLATE

logger = logging.getLogger(__name__)

REPLIES_ENV = "JPTRANS_FAKE_REPLIES"
"""Variabel lingkungan berisi jalur berkas JSON jawaban berskrip untuk ``--engine fake``."""


@dataclass(frozen=True)
class FakeCall:
    """Rekaman satu panggilan ``FakeEngine.translate``."""

    texts: tuple[str, ...]
    src: str
    tgt: str
    hints: tuple[str, ...]


class FakeEngine:
    """Mesin uji yang hasilnya bisa ditebak.

    Args:
        prefix: Awalan tiap hasil; ``{tgt}`` diganti kode bahasa sasaran.
        drop_tokens: Nomor penanda yang dihapus dari hasil (menguji fallback).
        shuffle: Balik urutan penanda di tiap hasil (menguji restore berbasis ID).
        fail_with: Galat yang dilempar pada setiap panggilan.
        translations: Jawaban tetap ``{teks masukan: hasil}``; mengalahkan ``prefix``.
        tag: Tag cache pengganti ``"fake"`` (``replies_tag`` untuk jawaban berskrip CLI).

    Attributes:
        calls: Daftar ``FakeCall`` untuk asersi di tes.
        echoes_source: ``True``: gema bawaan (awalan + teks Jepang masukan, lihat
            ``echo``) sengaja memuat huruf Jepang, jadi pipeline tidak
            menganggap gema itu terjemahan bersisa (``residue.residue_letters``).
            Hanya keluaran yang sama persis dengan ``echo`` yang dibebaskan;
            jawaban ``translations`` dan jawaban cache lain tetap diperiksa.
            Subkelas yang meniru mesin sungguhan bisa mengubahnya menjadi ``False``.
    """

    name = "fake"
    echoes_source = True
    max_chars = 2000
    max_items = 50

    def __init__(
        self,
        prefix: str = "⟪{tgt}⟫ ",
        drop_tokens: Iterable[int] = (),
        shuffle: bool = False,
        fail_with: BaseException | None = None,
        translations: Mapping[str, str] | None = None,
        tag: str = "",
    ) -> None:
        """Siapkan mesin palsu.

        Args:
            prefix: Awalan gema; ``{tgt}`` diganti kode bahasa sasaran.
            drop_tokens: Nomor penanda yang dibuang dari setiap hasil.
            shuffle: Balik urutan penanda di setiap hasil (``reverse_tokens``).
            fail_with: Galat yang dilempar ``translate`` sebelum menjawab.
            translations: Jawaban tetap per teks masukan; teks lain digemakan.
            tag: Tag cache (lihat ``cache_tag``); kosong berarti ``"fake"``.
        """
        self.prefix = prefix
        self.drop_tokens = frozenset(drop_tokens)
        self.shuffle = shuffle
        self.fail_with = fail_with
        self.translations = dict(translations or {})
        self.tag = tag
        self.calls: list[FakeCall] = []

    def cache_tag(self) -> str:
        """Kembalikan ``tag`` bila diisi, selain itu ``"fake"``.

        ``translations`` yang diisi lewat kode tidak mengubah tag: di tes, jawaban itu
        meniru satu mesin yang sama di beberapa jalan (cache harus tetap kena). Jawaban
        berskrip dari ``JPTRANS_FAKE_REPLIES`` memakai tag sendiri (``replies_tag``).
        """
        return self.tag or self.name

    def available(self) -> tuple[bool, str]:
        """Selalu tersedia."""
        return True, "mesin uji deterministik tanpa jaringan"

    def translate(
        self, texts: list[str], src: str, tgt: str, hints: Sequence[str] = ()
    ) -> list[str]:
        """Kembalikan hasil palsu untuk tiap teks dan catat panggilannya.

        Raises:
            BaseException: ``fail_with`` bila diisi.
        """
        self.calls.append(FakeCall(tuple(texts), src, tgt, tuple(hints)))
        if self.fail_with is not None:
            raise self.fail_with
        return [self._fake_one(text, tgt) for text in texts]

    def echo(self, text: str, tgt: str) -> str:
        """Gema bawaan untuk ``text``: awalan + teks, setelah ``shuffle``/``drop_tokens``.

        Args:
            text: Teks masukan (termasking).
            tgt: Kode bahasa sasaran.

        Returns:
            Keluaran yang akan diberikan ``translate`` bila ``text`` tidak ada di
            ``translations``.
        """
        return self._distort(self.prefix.format(tgt=tgt) + text)

    def _fake_one(self, text: str, tgt: str) -> str:
        """Jawaban untuk satu teks: ``translations`` bila ada, selain itu gema ``echo``."""
        result = self.translations.get(text)
        if result is None:
            return self.echo(text, tgt)
        return self._distort(result)

    def _distort(self, result: str) -> str:
        """Terapkan ``shuffle`` dan ``drop_tokens`` ke satu hasil."""
        if self.shuffle:
            result = reverse_tokens(result)
        if self.drop_tokens:
            result = EXACT_TOKEN_RE.sub(
                lambda m: "" if int(m.group(1)) in self.drop_tokens else m.group(0), result
            )
        return result


def reverse_tokens(text: str) -> str:
    """Balik urutan penanda ``[[E#]]`` di dalam teks, sisanya tetap.

    Args:
        text: Teks berpenanda.

    Returns:
        Teks dengan penanda pertama bertukar tempat dengan yang terakhir, dst.
    """
    tokens = iter(reversed(EXACT_TOKEN_RE.findall(text)))
    return EXACT_TOKEN_RE.sub(lambda _m: TOKEN_TEMPLATE.format(next(tokens)), text)


def replies_tag(replies: Mapping[str, str]) -> str:
    """Tag cache untuk jawaban berskrip: ``fake+<12 heksa SHA-256 isi jawaban>``.

    Gema bawaan (tag ``"fake"``) dan tiap isi berkas jawaban punya ruang cache
    sendiri, jadi jawaban berskrip tidak tertutup gema yang sudah ada di cache dan
    tidak menetap di cache gema bawaan.

    Args:
        replies: Jawaban berskrip dari ``load_replies``.

    Returns:
        Tag cache.
    """
    payload = json.dumps(dict(replies), ensure_ascii=False, sort_keys=True)
    return f"{FakeEngine.name}+{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def load_replies(path: str | Path) -> dict[str, str]:
    """Baca jawaban berskrip ``{teks termasking: jawaban}`` untuk ``FakeEngine``.

    Isi berkas adalah data uji, bukan instruksi: hanya objek JSON berisi
    pasangan string yang diterima.

    Args:
        path: Berkas JSON (UTF-8).

    Returns:
        Peta teks masukan ke jawaban.

    Raises:
        ConfigError: Berkas tidak bisa dibaca, bukan JSON, atau bukan objek string ke string.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ConfigError(f"{REPLIES_ENV}: berkas {path} tidak bisa dibaca: {exc}") from exc
    if not isinstance(data, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in data.items()):
        raise ConfigError(f"{REPLIES_ENV}: {path} harus berisi objek JSON "
                          "{\"teks termasking\": \"jawaban\"}")
    logger.info("mesin fake memakai %d jawaban berskrip dari %s", len(data), REPLIES_ENV)
    return data
