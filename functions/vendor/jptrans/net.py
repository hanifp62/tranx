"""Lapisan HTTP bersama untuk semua mesin penerjemah.

Semua permintaan jaringan lewat ``http_request`` agar kebijakan yang sama
berlaku di mana-mana: User-Agent jujur, timeout, retry dengan exponential
backoff + jitter hanya untuk galat sementara (429, 5xx, timeout, koneksi
putus), dan pemetaan status HTTP ke galat jptrans:

========================  ===================================================
Status / kejadian         Galat yang dilempar
========================  ===================================================
429, 500, 502-504         dicoba ulang; bila tetap gagal ``EngineError``
timeout, koneksi putus    dicoba ulang; bila tetap gagal ``EngineUnavailable``
sertifikat TLS ditolak    ``EngineUnavailable`` tanpa retry, dengan petunjuk
402, 456 (DeepL)          ``QuotaExceeded`` tanpa retry
403/429 bertanda kuota    ``QuotaExceeded`` tanpa retry
401, 403 lain, 404        ``EngineUnavailable`` (key/endpoint/model tidak sah)
3xx (redirect)            ``EngineError``; redirect tidak pernah diikuti
4xx lain                  ``EngineError``
========================  ===================================================

Koneksi yang tetap gagal setelah semua percobaan ulang (HP sedang offline,
DNS gagal) mematikan mesin untuk sesi itu lewat ``EngineUnavailable``, agar
pipeline tidak mengulang belasan detik backoff untuk setiap kalimat.

Redirect sengaja tidak diikuti: ``urllib`` bawaan menyalin semua header,
termasuk ``Authorization``, ke host tujuan redirect (juga dari https ke http).
Badan respons dibatasi ``MAX_RESPONSE_BYTES``.

``urlopen`` adalah fungsi tingkat modul supaya tes bisa menggantinya dengan
``unittest.mock.patch("jptrans.net.urlopen")`` tanpa menyentuh jaringan.
"""

from __future__ import annotations

import json
import logging
import random
import ssl
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__
from .errors import EngineError, EngineUnavailable, QuotaExceeded

logger = logging.getLogger(__name__)

USER_AGENT = f"jptrans/{__version__} (+tugas-kuliah; python-urllib)"

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
QUOTA_STATUSES = frozenset({402, 456})
AUTH_STATUSES = frozenset({401, 403})
UNAVAILABLE_STATUSES = frozenset({404})
# Potongan teks (huruf kecil) di badan respons galat yang berarti kuota/saldo habis.
QUOTA_HINTS = (
    "quota",
    "exhausted",
    "used all available",
    "insufficient_quota",
    "insufficient_balance",
)
MAX_DELAY = 30.0
ERROR_BODY_LIMIT = 2048
MESSAGE_LIMIT = 160
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
CERTIFICATE_HINT = (
    "sertifikat TLS tidak bisa diverifikasi; di macOS jalankan 'Install Certificates.command' "
    "dari folder Python, atau periksa proxy jaringan"
)

# Galat pustaka yang berarti permintaan gagal di tengah jalan.
_NETWORK_ERRORS = (HTTPError, URLError, TimeoutError, ConnectionError, HTTPException)


class _NoRedirect(HTTPRedirectHandler):
    """Tolak redirect agar header ``Authorization`` tidak pernah pindah host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = build_opener(_NoRedirect)


def urlopen(request: Request, timeout: float) -> Any:
    """Buka ``request`` tanpa mengikuti redirect (status 3xx menjadi ``HTTPError``)."""
    return _OPENER.open(request, timeout=timeout)


@dataclass(frozen=True)
class _Failure:
    """Hasil klasifikasi satu kegagalan permintaan."""

    error: EngineError
    retryable: bool
    retry_after: float | None = None


def http_request(
    url: str,
    *,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    method: str | None = None,
    timeout: float = 20.0,
    retries: int = 3,
    backoff: float = 1.5,
    engine: str = "net",
) -> bytes:
    """Kirim satu permintaan HTTP dan kembalikan badan respons mentah.

    Args:
        url: Alamat lengkap, termasuk query string bila ada.
        data: Badan permintaan; bila diisi, metode bawaan menjadi POST.
        headers: Header tambahan. ``User-Agent`` diisi otomatis.
        method: Metode HTTP eksplisit (``GET``, ``POST``, ...).
        timeout: Batas waktu per percobaan, dalam detik.
        retries: Jumlah percobaan ulang setelah percobaan pertama.
        backoff: Jeda dasar backoff; jeda ke-n = ``backoff * 2**(n-1)`` + jitter.
        engine: Nama mesin untuk pesan galat dan log.

    Returns:
        Badan respons dalam bentuk bytes.

    Raises:
        QuotaExceeded: Status 456 atau 403 yang menyebut kuota.
        EngineUnavailable: Status 401 atau 403 lain, sertifikat TLS ditolak,
            atau koneksi yang tetap gagal setelah semua percobaan ulang.
        EngineError: Galat lain (termasuk redirect dan respons terlalu besar),
            atau galat HTTP sementara yang tetap terjadi setelah semua
            percobaan ulang.
    """
    request = _build_request(url, data, headers, method, engine)
    attempt = 0
    while True:
        attempt += 1
        try:
            with urlopen(request, timeout=timeout) as response:
                return _read_limited(response, engine)
        except _NETWORK_ERRORS as exc:
            failure = _classify(exc, engine)
            if not failure.retryable or attempt > retries:
                raise _final_error(failure, exc, engine) from exc
            delay = failure.retry_after
            if delay is None:
                delay = backoff_delay(attempt, backoff)
            logger.warning(
                "%s; percobaan ulang %d/%d dalam %.1f s", failure.error, attempt, retries, delay
            )
            time.sleep(delay)


def post_form(url: str, fields: Mapping[str, str], **kw: Any) -> bytes:
    """Kirim formulir ``application/x-www-form-urlencoded`` lewat POST.

    Args:
        url: Alamat tujuan.
        fields: Pasangan nama dan nilai formulir.
        **kw: Diteruskan ke ``http_request`` (``timeout``, ``engine``, ...).

    Returns:
        Badan respons mentah.
    """
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    headers.update(kw.pop("headers", None) or {})
    body = urlencode(fields).encode("ascii")
    return http_request(url, data=body, headers=headers, method="POST", **kw)


def post_json(
    url: str, payload: Any, headers: Mapping[str, str] | None = None, **kw: Any
) -> Any:
    """Kirim JSON lewat POST dan urai respons JSON-nya.

    Args:
        url: Alamat tujuan.
        payload: Objek yang bisa diserialisasi ``json.dumps``.
        headers: Header tambahan, misalnya ``Authorization``.
        **kw: Diteruskan ke ``http_request``.

    Returns:
        Objek Python hasil ``json.loads``.

    Raises:
        EngineError: Galat HTTP atau respons yang bukan JSON.
    """
    merged = {"Content-Type": "application/json", "Accept": "application/json"}
    merged.update(headers or {})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    raw = http_request(url, data=body, headers=merged, method="POST", **kw)
    return parse_json(raw, kw.get("engine", "net"))


def get_json(url: str, params: Mapping[str, str], **kw: Any) -> Any:
    """Kirim GET dengan query string dan urai respons JSON-nya.

    Args:
        url: Alamat dasar tanpa atau dengan query string.
        params: Parameter query; di-encode dengan ``urlencode``.
        **kw: Diteruskan ke ``http_request``.

    Returns:
        Objek Python hasil ``json.loads``.

    Raises:
        EngineError: Galat HTTP atau respons yang bukan JSON.
    """
    separator = "&" if "?" in url else "?"
    raw = http_request(url + separator + urlencode(params), method="GET", **kw)
    return parse_json(raw, kw.get("engine", "net"))


def parse_json(raw: bytes, engine: str = "net") -> Any:
    """Urai badan respons sebagai JSON UTF-8.

    Layanan gratis kadang membalas halaman HTML (captcha, blokir) dengan
    status 200, jadi kegagalan urai dianggap kegagalan mesin, bukan bug.

    Args:
        raw: Badan respons mentah.
        engine: Nama mesin untuk pesan galat.

    Returns:
        Objek Python hasil ``json.loads``.

    Raises:
        EngineError: Badan bukan JSON yang sah.
    """
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        kind = "HTML (mungkin captcha atau diblokir)" if _looks_like_html(raw) else "bukan JSON"
        raise EngineError(engine, f"respons {kind}, {len(raw)} byte") from exc


def http_status(error: BaseException) -> int | None:
    """Kembalikan status HTTP yang menyebabkan sebuah galat jptrans.

    ``http_request`` selalu memakai ``raise ... from exc``, sehingga
    ``HTTPError`` asli tersimpan di ``__cause__``. Mesin memakai ini untuk
    keputusan khusus, misalnya LLM yang mengulang tanpa ``response_format``
    ketika server membalas 400.

    Args:
        error: Galat yang ditangkap pemanggil.

    Returns:
        Kode status, atau ``None`` bila penyebabnya bukan respons HTTP.
    """
    cause = error.__cause__
    return cause.code if isinstance(cause, HTTPError) else None


def backoff_delay(attempt: int, backoff: float) -> float:
    """Hitung jeda exponential backoff dengan jitter acak.

    Args:
        attempt: Nomor percobaan yang baru gagal, mulai dari 1.
        backoff: Jeda dasar dalam detik.

    Returns:
        Jeda dalam detik, paling lama ``MAX_DELAY``.
    """
    base = backoff * 2 ** (attempt - 1)
    # Jitter mencegah banyak klien mencoba ulang pada detik yang sama.
    return min(MAX_DELAY, base + random.uniform(0, base / 2))


def parse_retry_after(headers: Message | None) -> float | None:
    """Baca header ``Retry-After`` berbentuk detik.

    Bentuk tanggal HTTP diabaikan karena jarang dipakai layanan ini.

    Args:
        headers: Header respons galat.

    Returns:
        Jeda dalam detik (0 sampai ``MAX_DELAY``), atau ``None``.
    """
    raw = headers.get("Retry-After") if headers is not None else None
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_DELAY)


class RateLimiter:
    """Menjaga jeda minimum antar-permintaan ke satu layanan.

    Dibuat satu per mesin. Aman dipakai beberapa thread sekaligus.

    Args:
        min_interval: Jeda minimum antar-panggilan ``wait`` (detik).
    """

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Tidur seperlunya agar jeda minimum terpenuhi.

        Returns:
            Lama tidur dalam detik (0 bila tidak perlu menunggu).
        """
        with self._lock:
            now = time.monotonic()
            delay = 0.0
            if self._last is not None:
                delay = max(0.0, self._last + self.min_interval - now)
            if delay:
                time.sleep(delay)
            self._last = time.monotonic()
            return delay


def server_message(body: bytes) -> str:
    """Ambil pesan galat singkat dari badan respons untuk ditampilkan.

    Args:
        body: Badan respons galat (boleh kosong).

    Returns:
        Pesan satu baris, paling panjang ``MESSAGE_LIMIT`` karakter.
    """
    if not body:
        return "tanpa pesan"
    if _looks_like_html(body):
        return "halaman HTML"
    text = body.decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            error = error.get("message")
        text = str(error or data.get("message") or data.get("responseDetails") or text)
    return " ".join(text.split())[:MESSAGE_LIMIT]


def _build_request(
    url: str,
    data: bytes | None,
    headers: Mapping[str, str] | None,
    method: str | None,
    engine: str,
) -> Request:
    merged = {"User-Agent": USER_AGENT}
    merged.update(headers or {})
    try:
        return Request(url, data=data, headers=merged, method=method)
    except ValueError as exc:
        raise EngineError(engine, f"URL tidak valid: {url.split('?', 1)[0]}") from exc


def _read_limited(response: Any, engine: str) -> bytes:
    """Baca badan respons sukses, paling banyak ``MAX_RESPONSE_BYTES``."""
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise EngineError(engine, f"respons melebihi {MAX_RESPONSE_BYTES} byte")
    return body


def _final_error(failure: _Failure, exc: BaseException, engine: str) -> EngineError:
    """Galat yang dilempar setelah percobaan terakhir.

    Galat koneksi (bukan respons HTTP) yang menetap berarti jaringan tidak
    bisa dipakai, jadi dinaikkan ke ``EngineUnavailable`` agar mesin dimatikan.
    """
    if failure.retryable and not isinstance(exc, HTTPError):
        return EngineUnavailable(engine, f"koneksi gagal: {_reason(exc)}")
    return failure.error


def _classify(exc: BaseException, engine: str) -> _Failure:
    """Petakan galat pustaka ke galat jptrans dan tentukan perlu retry atau tidak."""
    if isinstance(_cause(exc), ssl.SSLCertVerificationError):
        return _Failure(EngineUnavailable(engine, CERTIFICATE_HINT), retryable=False)
    if not isinstance(exc, HTTPError):
        return _Failure(EngineError(engine, f"koneksi gagal: {_reason(exc)}"), retryable=True)
    code = exc.code
    body = _read_error_body(exc)
    detail = f"HTTP {code}: {server_message(body)}"
    if (
        code in QUOTA_STATUSES
        or (code == 403 and _mentions_quota(body))
        or (code == 429 and b"insufficient_quota" in body.lower())
    ):
        return _Failure(
            QuotaExceeded(engine, f"kuota habis ({detail})"), retryable=False
        )
    if code in AUTH_STATUSES:
        return _Failure(
            EngineUnavailable(engine, f"akses ditolak ({detail})"),
            retryable=False,
        )
    if code in UNAVAILABLE_STATUSES:
        return _Failure(
            EngineUnavailable(engine, f"endpoint/model tidak ditemukan ({detail})"),
            retryable=False,
        )
    if code in RETRY_STATUSES:
        delay = parse_retry_after(exc.headers)
        return _Failure(EngineError(engine, detail), retryable=True, retry_after=delay)
    return _Failure(EngineError(engine, detail), retryable=False)


def _read_error_body(exc: HTTPError) -> bytes:
    """Baca awal badan respons galat, lalu tutup koneksinya (kode status tetap ada)."""
    try:
        return exc.read(ERROR_BODY_LIMIT) or b""
    except (OSError, HTTPException, ValueError):
        return b""
    finally:
        exc.close()


def _mentions_quota(body: bytes) -> bool:
    lowered = body.decode("utf-8", "replace").lower()
    return any(hint in lowered for hint in QUOTA_HINTS)


def _looks_like_html(raw: bytes) -> bool:
    return raw[:200].lstrip().startswith(b"<")


def _cause(exc: BaseException) -> BaseException:
    """Penyebab asli galat koneksi (``URLError.reason`` bila berupa galat)."""
    reason = getattr(exc, "reason", None) if isinstance(exc, URLError) else None
    return reason if isinstance(reason, BaseException) else exc


def _reason(exc: BaseException) -> str:
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, str):
        return reason
    return f"{type(reason).__name__}: {reason}" if str(reason) else type(reason).__name__
