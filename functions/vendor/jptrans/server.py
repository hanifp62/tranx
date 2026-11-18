"""Antarmuka web lokal: satu halaman HTML untuk menerjemahkan dari browser HP.

Keamanan (LAPORAN_RISET 9.4, KRITIK_RISET no. 8 dan 21):

- Bind bawaan ``127.0.0.1``; ``--lan`` bind ``0.0.0.0`` dan mencetak IP LAN.
- Token acak ``secrets.token_urlsafe(24)`` dicetak di **fragment** URL
  (``http://host:port/#t=TOKEN``). Fragment tidak pernah dikirim browser ke
  server dan tidak masuk log. Halaman memindahkannya ke ``sessionStorage``,
  menghapusnya dari bilah alamat, lalu mengirimnya di header ``X-Token``.
  Semua endpoint ``/api/`` wajib token; dibandingkan dengan ``compare_digest``.
- Header ``Host`` harus salah satu host yang diizinkan (mencegah DNS
  rebinding). Tidak ada header CORS. ``Content-Length`` dibatasi 10 MB.
- ``BaseHTTPRequestHandler`` dipakai langsung; ``SimpleHTTPRequestHandler``
  sengaja dihindari karena menyajikan berkas apa pun dari disk.
- Terjemahan berjalan di SATU thread pekerja dengan ``queue.Queue`` (maks. 5
  antre), sehingga handler HTTP selalu cepat menjawab dan browser HP tidak
  timeout. Cache sqlite3 dibuka di thread pekerja itu sendiri.
- Klien lambat tidak bisa menahan server: tiap operasi soket punya batas
  waktu ``REQUEST_TIMEOUT``, dan di atasnya ada tenggat TOTAL per permintaan
  (``HEADER_TIMEOUT`` untuk baris permintaan + header, ``BODY_TIMEOUT`` untuk
  badan). Server berbicara HTTP/1.0 tanpa keep-alive, jadi satu koneksi
  melayani satu permintaan. Mengirim satu byte tiap beberapa detik tidak lagi
  memperpanjang koneksi.
  Koneksi serentak dibatasi ``MAX_CONNECTIONS`` total dan
  ``MAX_CONNECTIONS_PER_IP`` per alamat IP; koneksi di atas batas langsung
  dijawab ``503`` dengan ``Retry-After`` dari thread penerima (tanpa thread
  baru per koneksi, tanpa menunggu, soket non-blocking), arah tulisnya ditutup
  (FIN), lalu soket diserahkan ke satu thread penuai (``_LingerReaper``) yang
  membuang permintaan klien yang datang belakangan selama ``LINGER_SECONDS``
  sebelum menutupnya. Tanpa itu kernel menjawab permintaan yang tiba sesudah
  ``close`` dengan RST, dan klien kehilangan 503-nya (RFC 9112 bagian 9.6).
  Dokumen unggahan dibatasi ``MAX_JOB_PARAGRAPHS`` paragraf, dan isi
  unggahan dilepas dari memori setelah pekerjaan selesai.
- Di Windows ``SO_REUSEADDR`` mengizinkan proses lain bind port yang sedang
  dipakai, jadi opsi itu hanya dipasang di POSIX.
"""

from __future__ import annotations

import ipaddress
import io
import json
import logging
import os
import queue
import re
import secrets
import selectors
import socket
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any, cast
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__
from .cache import TranslationCache
from .config import HONORIFIC_STYLES, LANGS, NAME_ORDERS, ROMANIZATIONS, Config
from .engines import Engine, build_engines, describe_engines, normalize_engine_names
from .errors import ConfigError, InputError, JptransError
from .glossary import Glossary, default_glossary_path, slugify
from .models import Document, TranslatedDocument
from .pipeline import Progress, Translator
from .readers import READERS, read_document, read_text
from .writers import CONTENT_TYPES, RENDERERS, render_output
from .writers.text import result_to_dict

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 10 * 1024 * 1024
MAX_QUEUED = 5
MAX_KEPT_JOBS = 50
MAX_KEPT_RESULT_JOBS = 10
MAX_JOB_PARAGRAPHS = 100_000
REQUEST_TIMEOUT = 30
"""Detik tanpa data per operasi soket sebelum koneksi diputus."""
HEADER_TIMEOUT = 10.0
"""Tenggat total (detik) membaca baris permintaan + header (satu permintaan per koneksi)."""
BODY_TIMEOUT = 60.0
"""Tenggat total (detik) membaca badan permintaan (unggahan maks. ``MAX_BODY_BYTES``)."""
MAX_CONNECTIONS = 32
MAX_CONNECTIONS_PER_IP = 8
"""Browser memakai sekitar 6 koneksi per host; satu alamat tidak boleh memakai semua jatah."""
RETRY_AFTER_SECONDS = 5
_DRAIN_BYTES = 64 * 1024
LINGER_SECONDS = 2.0
"""Lama (detik) soket yang ditolak 503 tetap dibuka untuk membuang sisa permintaan klien."""
LINGER_MAX_SOCKETS = 64
"""Soket tertolak yang boleh ditahan bersamaan; bila penuh, soket langsung ditutup."""
LINGER_MAX_BYTES = 1024 * 1024
"""Byte yang dibuang per soket tertolak sebelum soket ditutup lebih awal."""
_LINGER_POLL = 0.1
UPLOAD_STEM = "upload"
TOKEN_BYTES = 24
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# Alamat TEST-NET-1 (RFC 5737): connect() UDP hanya memilih rute, tidak ada paket terkirim.
_ROUTE_PROBE = ("192.0.2.1", 80)
_JOB_PATH_RE = re.compile(r"^/api/jobs/(?P<id>[0-9a-f]{16})(?P<download>/download)?$")

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"

EngineBuilder = Callable[[Config], list[Engine]]


@dataclass(frozen=True)
class JobRequest:
    """Isi permintaan terjemahan dari browser.

    Attributes:
        title: Judul karya (menentukan glosarium).
        target: Bahasa sasaran.
        engines: Urutan mesin; kosong berarti ``cfg.engines``.
        text: Teks tempelan; kosong bila yang diunggah berkas.
        data: Isi berkas unggahan.
        filename: Nama berkas unggahan; sufiksnya menentukan pembaca.
    """

    title: str
    target: str
    engines: tuple[str, ...] = ()
    text: str = ""
    data: bytes = b""
    filename: str = ""
    honorific_style: str | None = None
    romanization: str | None = None
    name_order: str | None = None


@dataclass
class Job:
    """Satu pekerjaan terjemahan beserta statusnya."""

    id: str
    request: JobRequest
    status: str = QUEUED
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    title: str = ""
    result: TranslatedDocument | None = field(default=None, repr=False)
    html: str = field(default="", repr=False)
    finished: threading.Event = field(default_factory=threading.Event, repr=False)

    def state(self) -> dict[str, Any]:
        """Status singkat pekerjaan (tanpa hasil), aman disalin di bawah kunci."""
        title = (self.title or self.request.title
                 or Path(upload_basename(self.request.filename)).stem)
        return {
            "id": self.id, "title": title, "status": self.status,
            "done": self.done, "total": self.total, "message": self.message,
            "error": self.error,
        }


class JobManager:
    """Antrean pekerjaan dengan satu thread pekerja.

    Args:
        cfg: Konfigurasi dasar; bahasa dan mesin bisa diganti per pekerjaan.
        engine_builder: Pembuat daftar mesin (bisa diganti di tes).
        max_queued: Batas pekerjaan yang menunggu.
    """

    def __init__(
        self, cfg: Config, *, engine_builder: EngineBuilder = build_engines,
        max_queued: int = MAX_QUEUED,
    ) -> None:
        self.cfg = cfg
        self._build_engines = engine_builder
        self._queue: queue.Queue[Job] = queue.Queue(maxsize=max_queued)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._work, name="jptrans-worker", daemon=True)

    def start(self) -> None:
        """Jalankan thread pekerja."""
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Minta thread pekerja berhenti setelah pekerjaan yang sedang jalan."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def submit(self, request: JobRequest) -> Job | None:
        """Masukkan pekerjaan ke antrean.

        Returns:
            Pekerjaan baru, atau ``None`` bila antrean penuh.
        """
        job = Job(id=secrets.token_hex(8), request=request)
        with self._lock:
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                return None
            self._jobs[job.id] = job
            self._forget_old_jobs()
        logger.info("pekerjaan %s diantrekan (%s)", job.id, request.target)
        return job

    def run_sync(self, request: JobRequest, timeout: float = BODY_TIMEOUT) -> Job | None:
        """Antrekan pekerjaan lalu tunggu selesai untuk endpoint sinkron ``/api/translate``."""
        job = self.submit(request)
        if job is None:
            return None
        if not job.finished.wait(timeout):
            return None
        return job

    def summary(self, job_id: str) -> dict[str, Any] | None:
        """Status satu pekerjaan untuk ``GET /api/jobs/<id>``; hasil HTML bila selesai.

        Returns:
            Dict JSON, atau ``None`` bila pekerjaan tidak ada.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            info, result, page = job.state(), job.result, job.html
        if result is not None:
            # HTML dirender sekali oleh pekerja, bukan di setiap polling.
            info["html"] = page
            info["format"] = result.document.fmt
            info["stats"] = {key: value for key, value in result.stats.items()
                             if key != "rendered"}
        return info

    def result(self, job_id: str) -> TranslatedDocument | None:
        """Hasil pekerjaan yang sudah selesai, atau ``None``."""
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.result

    def _forget_old_jobs(self) -> None:
        finished = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in (DONE, FAILED)
        ]
        for job_id in finished[:-MAX_KEPT_RESULT_JOBS]:
            old = self._jobs[job_id]
            old.result = None
            old.html = ""
        for job_id in finished[:max(0, len(self._jobs) - MAX_KEPT_JOBS)]:
            del self._jobs[job_id]

    def _work(self) -> None:
        """Isi thread pekerja: cache sqlite3 dibuka di thread ini sendiri."""
        try:
            cache = TranslationCache(self.cfg.cache_path)
        except JptransError as exc:
            logger.error("pekerja tidak bisa membuka cache: %s", exc)
            cache = TranslationCache(None)
        with cache:
            while not self._stop.is_set():
                try:
                    job = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._run(job, cache)

    def _run(self, job: Job, cache: TranslationCache) -> None:
        self._update(job, status=RUNNING, message="mulai")
        try:
            result = self._translate(job, cache)
            page = render_output(result, "html")
        except JptransError as exc:
            self._update(job, status=FAILED, error=str(exc), message="gagal")
            logger.info("pekerjaan %s gagal: %s", job.id, exc)
        # Galat tak terduga tidak boleh mematikan satu-satunya thread pekerja.
        except Exception:  # noqa: BLE001
            logger.exception("pekerjaan %s gagal karena galat internal", job.id)
            self._update(job, status=FAILED, error="galat internal; lihat log server")
        else:
            self._update(job, status=DONE, result=result, html=page, message="selesai")
            logger.info("pekerjaan %s selesai", job.id)
        finally:
            # Unggahan (sampai 10 MB) tidak perlu disimpan setelah pekerjaan selesai.
            self._update(job, request=replace(job.request, data=b"", text=""))
            job.finished.set()

    def _translate(self, job: Job, cache: TranslationCache) -> TranslatedDocument:
        """Baca dokumen dulu agar judulnya (dan glosariumnya) sama dengan CLI."""
        request = job.request
        cfg = replace(
            self.cfg,
            target_lang=request.target,
            engines=list(request.engines) or self.cfg.engines,
            honorific_style=request.honorific_style or self.cfg.honorific_style,
            romanization=request.romanization or self.cfg.romanization,
            name_order=(
                request.name_order
                if request.name_order is not None
                else self.cfg.name_order
            ),
        )
        doc = _read_upload(request) if request.filename else read_text(request.text,
                                                                        request.title)
        if len(doc.paragraphs) > MAX_JOB_PARAGRAPHS:
            raise InputError(f"dokumen terlalu panjang (> {MAX_JOB_PARAGRAPHS} paragraf); "
                             "pecah dulu atau pakai CLI")
        self._update(job, title=doc.title)
        glossary = Glossary.load(default_glossary_path(cfg, doc.title), doc.title)

        def progress(state: Progress) -> None:
            self._update(job, done=state.done, total=state.total, message=state.message)

        translator = Translator(cfg, self._build_engines(cfg), cache, glossary, progress=progress)
        return translator.translate_document(doc)

    def _update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(job, name, value)


def _read_upload(request: JobRequest) -> Document:
    """Simpan unggahan ke berkas sementara, baca dengan pembaca yang sesuai, lalu hapus.

    Berkas sementara diperlukan karena pembaca EPUB memakai ``zipfile`` pada path.
    Judul mengikuti aturan CLI (``readers.read_document``): judul dari
    pengguna, lalu metadata/kepala berkas, lalu nama berkas asli.
    """
    original = Path(upload_basename(request.filename))
    with tempfile.TemporaryDirectory(prefix="jptrans-") as folder:
        path = Path(folder) / f"{UPLOAD_STEM}{original.suffix.lower()}"
        path.write_bytes(request.data)
        doc = read_document(path, title=request.title or None)
    if not request.title and doc.title == UPLOAD_STEM:
        doc.title = original.stem
    return doc


class JptransServer(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` yang membawa token, daftar host, dan antrean pekerjaan.

    Args:
        address: Pasangan (host, port); port 0 memilih port bebas.
        cfg: Konfigurasi program.
        allowed_hosts: Nilai header ``Host`` (tanpa port) yang diterima.
        engine_builder: Pembuat daftar mesin (bisa diganti di tes).
    """

    daemon_threads = True
    # Proses lain tidak boleh ikut bind di port yang sama. SO_REUSEPORT selalu mati;
    # SO_REUSEADDR hanya aman di POSIX (di Windows artinya "boleh berbagi port").
    allow_reuse_port = False
    allow_reuse_address = os.name != "nt"

    def __init__(
        self, address: tuple[str, int], cfg: Config, allowed_hosts: frozenset[str],
        *, engine_builder: EngineBuilder = build_engines, allow_lan: bool = False,
    ) -> None:
        # Dibuat sebelum bind: server_close() (dipanggil juga bila bind gagal) menghentikannya.
        self._reaper = _LingerReaper()
        super().__init__(address, RequestHandler)
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._per_ip: dict[str, int] = {}
        self._per_ip_lock = threading.Lock()
        self.cfg = cfg
        self.token = secrets.token_urlsafe(TOKEN_BYTES)
        self.allowed_hosts = allowed_hosts
        self.allow_lan = allow_lan
        self.jobs = JobManager(cfg, engine_builder=engine_builder)
        self.jobs.start()

    @property
    def port(self) -> int:
        """Port yang benar-benar dipakai (berguna bila diminta port 0)."""
        return self.server_address[1]

    def close(self) -> None:
        """Hentikan pekerja dan tutup soket."""
        self.jobs.stop()
        self.server_close()

    def server_close(self) -> None:
        """Tutup soket pendengar dan semua soket tertolak yang masih ditahan."""
        super().server_close()
        self._reaper.stop()

    def open_connections(self) -> int:
        """Jumlah koneksi yang sedang dilayani (untuk tes dan diagnosis)."""
        with self._per_ip_lock:
            return sum(self._per_ip.values())

    def process_request(self, request: Any, client_address: Any) -> None:
        """Layani koneksi di thread baru bila jatah total dan jatah IP-nya masih ada.

        Bila penuh, koneksi langsung dijawab 503 + ``Retry-After`` lalu
        diserahkan ke penuai (lihat ``_refuse_busy``); thread penerima tidak
        pernah menunggu jatah.
        """
        address = _client_ip(client_address)
        refusal = self._take_slot(address)
        if refusal:
            logger.warning("koneksi ditolak: %s", refusal)
            self._refuse_busy(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._return_slot(address)
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        """Jalankan handler lalu kembalikan jatah koneksi."""
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._return_slot(_client_ip(client_address))

    def _take_slot(self, address: str) -> str:
        """Ambil jatah untuk ``address``; kembalikan alasan penolakan atau string kosong."""
        with self._per_ip_lock:
            if self._per_ip.get(address, 0) >= MAX_CONNECTIONS_PER_IP:
                return f"sudah {MAX_CONNECTIONS_PER_IP} koneksi dari satu alamat"
            if not self._slots.acquire(blocking=False):
                return f"sudah {MAX_CONNECTIONS} koneksi terbuka"
            self._per_ip[address] = self._per_ip.get(address, 0) + 1
            return ""

    def _return_slot(self, address: str) -> None:
        with self._per_ip_lock:
            left = self._per_ip.get(address, 0) - 1
            if left > 0:
                self._per_ip[address] = left
            else:
                self._per_ip.pop(address, None)
            self._slots.release()

    def _refuse_busy(self, request: Any) -> None:
        """Kirim 503 singkat tanpa memblokir thread penerima, lalu serahkan ke penuai.

        Byte yang sudah tiba dikuras dulu (maks. ``_DRAIN_BYTES``), 503 dikirim,
        dan arah tulis ditutup (FIN) sehingga klien langsung melihat akhir
        balasan. Soketnya belum ditutup: permintaan klien bisa tiba beberapa
        milidetik setelah ``accept``, dan ``close`` sebelum itu membuat kernel
        membalas RST yang membuang 503 di sisi klien. Penuai membuang data itu
        lalu menutup soket. Bila penuai penuh atau soket sudah rusak, soket
        langsung ditutup seperti dulu.
        """
        try:
            request.setblocking(False)
            try:
                request.recv(_DRAIN_BYTES)
            except (BlockingIOError, InterruptedError):
                pass
            request.send(BUSY_RESPONSE)
            request.shutdown(socket.SHUT_WR)
        except OSError:
            self.shutdown_request(request)
            return
        if not self._reaper.add(request):
            self.shutdown_request(request)


class _LingerReaper:
    """Satu thread latar yang menahan soket tertolak sebentar sebelum menutupnya.

    Setiap soket dibaca tanpa blokir (lewat ``selectors``) dan isinya dibuang
    sampai klien menutup koneksi (EOF), ``LINGER_MAX_BYTES`` terlampaui, atau
    ``LINGER_SECONDS`` habis. Jumlah soket dibatasi ``LINGER_MAX_SOCKETS``;
    soket tidak memakai jatah ``MAX_CONNECTIONS``. Thread dibuat saat soket
    pertama datang dan diam (memblokir di antrean) bila tidak ada soket.
    """

    def __init__(self) -> None:
        self._incoming: queue.SimpleQueue[socket.socket | None] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._count = 0
        self._stopped = False
        self._thread: threading.Thread | None = None

    def pending(self) -> int:
        """Jumlah soket yang sedang ditahan (untuk tes dan diagnosis)."""
        with self._lock:
            return self._count

    def add(self, sock: socket.socket) -> bool:
        """Serahkan ``sock``; ``False`` bila penuh atau sudah dihentikan (pemanggil menutup)."""
        with self._lock:
            if self._stopped or self._count >= LINGER_MAX_SOCKETS:
                return False
            self._count += 1
            # Dimasukkan di bawah kunci agar tidak menyusul tanda berhenti dari stop().
            self._incoming.put(sock)
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="jptrans-linger", daemon=True)
                self._thread.start()
        return True

    def stop(self, timeout: float = 2.0) -> None:
        """Hentikan thread dan tutup semua soket yang masih ditahan."""
        with self._lock:
            self._stopped = True
            thread = self._thread
        if thread is not None:
            self._incoming.put(None)
            thread.join(timeout)

    def _run(self) -> None:
        """Putaran thread penuai: terima soket baru, buang datanya, tutup yang selesai."""
        selector = selectors.DefaultSelector()
        held: dict[socket.socket, list[float]] = {}  # soket -> [tenggat, byte dibuang]
        try:
            while True:
                if not self._admit(selector, held, block=not held):
                    return
                if not held:
                    continue
                now = time.monotonic()
                wait = min(_LINGER_POLL, max(0.0, min(v[0] for v in held.values()) - now))
                for key, _ in selector.select(wait):
                    self._drain(selector, held, cast(socket.socket, key.fileobj))
                now = time.monotonic()
                for sock in [s for s, v in held.items() if v[0] <= now]:
                    self._release(selector, held, sock)
        except Exception:  # noqa: BLE001 (thread latar tidak boleh mati diam-diam)
            logger.exception("penuai soket tertolak berhenti karena galat tak terduga")
        finally:
            for sock in list(held):
                self._release(selector, held, sock)
            selector.close()

    def _drain(self, selector: selectors.BaseSelector,
               held: dict[socket.socket, list[float]], sock: socket.socket) -> None:
        """Buang data yang tiba; tutup soket pada EOF, galat, atau batas byte."""
        try:
            data = sock.recv(_DRAIN_BYTES)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        held[sock][1] += len(data)
        if not data or held[sock][1] > LINGER_MAX_BYTES:
            self._release(selector, held, sock)

    def _admit(self, selector: selectors.BaseSelector,
               held: dict[socket.socket, list[float]], *, block: bool) -> bool:
        """Daftarkan soket baru dari antrean; ``False`` bila diminta berhenti."""
        while True:
            try:
                sock = self._incoming.get(block=block)
            except queue.Empty:
                return True
            if sock is None:
                return False
            block = False
            held[sock] = [time.monotonic() + LINGER_SECONDS, 0]
            try:
                selector.register(sock, selectors.EVENT_READ)
            except (OSError, ValueError):
                self._release(selector, held, sock)

    def _release(self, selector: selectors.BaseSelector,
                 held: dict[socket.socket, list[float]], sock: socket.socket) -> None:
        """Lepas ``sock`` dari selector, tutup, dan kurangi hitungan (sekali saja)."""
        if held.pop(sock, None) is None:
            return
        try:
            selector.unregister(sock)
        except (KeyError, ValueError, OSError):
            pass
        try:
            sock.close()
        except OSError:
            pass
        with self._lock:
            self._count -= 1


def _client_ip(client_address: Any) -> str:
    """Alamat IP dari ``client_address`` soket (tuple IPv4/IPv6 atau nilai lain)."""
    if isinstance(client_address, tuple) and client_address:
        return str(client_address[0])
    return str(client_address)


class _DeadlineReader(io.RawIOBase):
    """Pembaca soket mentah yang menolak membaca setelah tenggat total habis.

    Batas waktu soket per operasi diperpendek menjadi sisa tenggat, lalu
    dikembalikan ke ``REQUEST_TIMEOUT`` agar penulisan balasan tidak ikut
    terpotong. ``TimeoutError`` ditangani ``BaseHTTPRequestHandler``.
    """

    def __init__(self, sock: socket.socket, deadline: Callable[[], float]) -> None:
        super().__init__()
        self._sock = sock
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        remaining = self._deadline() - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("tenggat total permintaan habis")
        self._sock.settimeout(min(REQUEST_TIMEOUT, remaining))
        try:
            return self._sock.recv_into(buffer)
        finally:
            self._sock.settimeout(REQUEST_TIMEOUT)


class RequestHandler(BaseHTTPRequestHandler):
    """Router kecil untuk halaman dan API JSON."""

    server: JptransServer
    server_version = f"jptrans/{__version__}"
    sys_version = ""
    # StreamRequestHandler memasang batas waktu soket; TimeoutError ditangani http.server.
    timeout = REQUEST_TIMEOUT
    _deadline: float = 0.0
    """Waktu ``time.monotonic()`` saat tenggat fase baca yang sedang berjalan habis."""

    def setup(self) -> None:
        """Ganti ``rfile`` dengan pembaca bertenggat total (lihat ``_DeadlineReader``)."""
        super().setup()
        self._deadline = time.monotonic() + HEADER_TIMEOUT
        original = self.rfile
        self.rfile = io.BufferedReader(_DeadlineReader(self.connection, lambda: self._deadline))
        original.close()

    def handle_one_request(self) -> None:
        """Mulai tenggat header baru untuk setiap permintaan.

        Server berbicara HTTP/1.0 (``protocol_version`` bawaan), jadi koneksi
        ditutup setelah satu permintaan; penghitungan ulang ini hanya jaga-jaga
        bila ``protocol_version`` kelak dinaikkan dan keep-alive aktif.
        """
        self._deadline = time.monotonic() + HEADER_TIMEOUT
        super().handle_one_request()

    def do_GET(self) -> None:  # noqa: N802 (nama metode ditentukan http.server)
        """Halaman utama, status pekerjaan, dan unduhan hasil."""
        if not self._host_ok():
            return
        url = urlsplit(self.path)
        if url.path == "/":
            self._send(HTTPStatus.OK, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8",
                       extra={"Content-Security-Policy": PAGE_CSP})
            return
        if url.path == "/api/meta":
            if not self._token_ok():
                return
            self._json(HTTPStatus.OK, _server_meta(self.server.cfg))
            return
        match = _JOB_PATH_RE.match(url.path)
        if match is None:
            if url.path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "tidak ditemukan"})
            else:
                # Alamat yang diketik di browser: halaman galat kecil, bukan JSON mentah.
                # Jalur permintaan sengaja tidak ditampilkan ulang.
                self._send(HTTPStatus.NOT_FOUND, NOT_FOUND_HTML.encode("utf-8"),
                           "text/html; charset=utf-8",
                           extra={"Content-Security-Policy": ERROR_CSP})
            return
        if not self._token_ok():
            return
        if match["download"]:
            self._download(match["id"], parse_qs(url.query).get("fmt", ["html"])[0])
            return
        summary = self.server.jobs.summary(match["id"])
        if summary is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "pekerjaan tidak ditemukan"})
        else:
            self._json(HTTPStatus.OK, summary)

    def do_POST(self) -> None:  # noqa: N802
        """``POST /api/jobs`` (asinkron) dan ``POST /api/translate`` (JSON sinkron)."""
        if not self._host_ok():
            return
        url = urlsplit(self.path)
        if url.path not in ("/api/jobs", "/api/translate"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "tidak ditemukan"})
            return
        if not self._token_ok():
            return
        body = self._read_body()
        if body is None:
            return
        try:
            request = self._job_request(body, parse_qs(url.query))
        except ConfigError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if url.path == "/api/translate":
            self._translate_sync(request)
            return
        job = self.server.jobs.submit(request)
        if job is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "antrean penuh, coba lagi"},
                       extra={"Retry-After": str(RETRY_AFTER_SECONDS)})
        else:
            self._json(HTTPStatus.ACCEPTED, {"id": job.id, "status": job.status})

    def _translate_sync(self, request: JobRequest) -> None:
        job = self.server.jobs.run_sync(request)
        if job is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "antrean penuh atau waktu habis"},
                       extra={"Retry-After": str(RETRY_AFTER_SECONDS)})
            return
        if job.status != DONE or job.result is None:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": job.error or "terjemahan gagal"})
            return
        payload = {"target": job.result.target, **result_to_dict(job.result)}
        self._json(HTTPStatus.OK, payload)

    def _host_ok(self) -> bool:
        """Tolak header ``Host`` yang tidak dikenal (pertahanan DNS rebinding)."""
        host = self.headers.get("Host")
        if not host:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "header Host wajib"})
            return False
        parsed = host_name(host)
        if not parsed:
            self._json(HTTPStatus.FORBIDDEN, {"error": "host tidak diizinkan"})
            return False
        if parsed in self.server.allowed_hosts:
            return True
        if self.server.allow_lan and _is_private_lan_ip(parsed):
            return True
        self._json(HTTPStatus.FORBIDDEN, {"error": "host tidak diizinkan"})
        return False

    def _token_ok(self) -> bool:
        given = self.headers.get("X-Token", "")
        if secrets.compare_digest(given.encode("utf-8"), self.server.token.encode("utf-8")):
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "token salah atau tidak ada"})
        return False

    def _read_body(self) -> bytes | None:
        """Baca badan permintaan dengan batas ukuran; balas galat bila tidak sah."""
        raw = self.headers.get("Content-Length")
        if raw is None:
            self._json(HTTPStatus.LENGTH_REQUIRED, {"error": "Content-Length wajib"})
            return None
        try:
            length = int(raw)
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Content-Length tidak sah"})
            return None
        if length <= 0:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "badan permintaan kosong"})
            return None
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                       {"error": f"maksimal {MAX_BODY_BYTES // (1024 * 1024)} MB"})
            return None
        self._deadline = time.monotonic() + BODY_TIMEOUT
        data = self.rfile.read(length)
        if len(data) < length:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "badan permintaan terputus"})
            return None
        return data

    def _job_request(self, body: bytes, query: dict[str, list[str]]) -> JobRequest:
        """Ubah badan permintaan menjadi ``JobRequest`` yang sudah divalidasi.

        Raises:
            ConfigError: Isi permintaan tidak sah.
        """
        filename = unquote(self.headers.get("X-Filename", "")).strip()
        if filename:
            options = {key: values[-1] for key, values in query.items()}
            return parse_upload(filename, body, options, self.server.cfg)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            # RecursionError: JSON bersarang sangat dalam ([[[[...]]]]).
            raise ConfigError(f"badan bukan JSON UTF-8 yang sah: {type(exc).__name__}") from exc
        return parse_text_request(payload, self.server.cfg)

    def _download(self, job_id: str, fmt: str) -> None:
        result = self.server.jobs.result(job_id)
        if result is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "hasil belum ada"})
            return
        if fmt not in RENDERERS:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"format: {', '.join(RENDERERS)}"})
            return
        try:
            content = render_output(result, fmt)
        except JptransError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        name = f"{slugify(result.document.title)}.{result.target_lang}.{fmt}"
        encoded = quote(name, safe="")
        disposition = f"attachment; filename=\"jptrans.{fmt}\"; filename*=UTF-8''{encoded}"
        mime = CONTENT_TYPES.get(fmt, "application/octet-stream")
        self._send(HTTPStatus.OK, content.encode("utf-8"), f"{mime}; charset=utf-8",
                   extra={"Content-Disposition": disposition})

    def _json(self, status: HTTPStatus, payload: dict[str, Any],
              extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """Catat permintaan tanpa query string (tidak pernah memuat token)."""
        path = urlsplit(self.path).path if hasattr(self, "path") else "-"
        logger.info("%s %s %s", getattr(self, "command", "-"), path, code)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Alihkan log bawaan ``http.server`` (stderr) ke ``logging``."""
        logger.debug("http: %s", format % args)


def _busy_response(protocol: str) -> bytes:
    """Balasan 503 lengkap yang dikirim thread penerima saat jatah koneksi penuh.

    Args:
        protocol: Versi protokol di baris status, sama dengan balasan biasa server
            (``RequestHandler.protocol_version``, yaitu ``HTTP/1.0``).
    """
    body = json.dumps({"error": "server sibuk, coba lagi"}, ensure_ascii=False).encode("utf-8")
    head = (
        f"{protocol} 503 Service Unavailable\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Retry-After: {RETRY_AFTER_SECONDS}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "X-Content-Type-Options: nosniff\r\n\r\n"
    )
    return head.encode("ascii") + body


BUSY_RESPONSE = _busy_response(RequestHandler.protocol_version)


def _server_meta(cfg: Config) -> dict[str, Any]:
    """Metadata kapabilitas server untuk antarmuka web maupun klien aplikasi eksternal."""
    return {
        "version": __version__,
        "languages": list(LANGS),
        "honorific_styles": list(HONORIFIC_STYLES),
        "romanizations": list(ROMANIZATIONS),
        "name_orders": list(NAME_ORDERS),
        "input_formats": sorted(READERS),
        "output_formats": list(RENDERERS),
        "engines": [
            {"name": name, "available": ok, "reason": reason}
            for name, ok, reason in describe_engines(cfg)
        ],
    }


def _optional_choice(field_name: str, value: Any, choices: tuple[str, ...]) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in choices:
        raise ConfigError(f"{field_name!r} harus salah satu dari {', '.join(choices)}")
    return value


def parse_text_request(payload: Any, cfg: Config) -> JobRequest:
    """Validasi badan JSON ``{"text", "title", "to", "engine", ...}``."""
    if not isinstance(payload, dict):
        raise ConfigError("badan JSON harus objek")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ConfigError("'text' wajib berupa teks tidak kosong")
    return JobRequest(
        title=_title(payload.get("title"), "teks"),
        target=_target(payload.get("to"), cfg),
        engines=_engine_names(payload.get("engine")),
        text=text,
        honorific_style=_optional_choice(
            "honorifics", payload.get("honorifics"), HONORIFIC_STYLES
        ),
        romanization=_optional_choice("romaji", payload.get("romaji"), ROMANIZATIONS),
        name_order=_optional_choice(
            "name_order", payload.get("name_order"), NAME_ORDERS
        ),
    )


def parse_upload(filename: str, data: bytes, options: dict[str, str], cfg: Config) -> JobRequest:
    """Validasi unggahan berkas mentah; opsi dibaca dari query string."""
    name = upload_basename(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in READERS:
        raise ConfigError(f"format {suffix or '(tanpa sufiks)'} tidak didukung; "
                          f"pilih: {', '.join(sorted(READERS))}")
    return JobRequest(
        title=_title(options.get("title"), ""),
        target=_target(options.get("to"), cfg),
        engines=_engine_names(options.get("engine")),
        data=data,
        filename=name,
        honorific_style=_optional_choice(
            "honorifics", options.get("honorifics"), HONORIFIC_STYLES
        ),
        romanization=_optional_choice("romaji", options.get("romaji"), ROMANIZATIONS),
        name_order=_optional_choice(
            "name_order", options.get("name_order"), NAME_ORDERS
        ),
    )


def upload_basename(filename: str) -> str:
    """Nama dasar berkas unggahan, memisah di ``/`` maupun ``\\`` di semua platform.

    Browser lama di Windows mengirim path lengkap (``C:\\fakepath\\bab.txt``).
    ``Path`` di POSIX tidak menganggap ``\\`` pemisah, sehingga judul dan sufiks
    bisa berbeda dari server yang berjalan di Windows. ``PureWindowsPath``
    memisah keduanya dan membuang huruf drive.
    """
    return PureWindowsPath(filename).name


def _title(value: Any, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    if not isinstance(value, str):
        raise ConfigError("'title' harus teks")
    return value.strip() or fallback


def _target(value: Any, cfg: Config) -> str:
    target = cfg.target_lang if value in (None, "") else value
    if target not in LANGS:
        raise ConfigError(f"'to' harus salah satu dari {', '.join(LANGS)}")
    return target


def _engine_names(value: Any) -> tuple[str, ...]:
    if value in (None, "", []):
        return ()
    items = value.split(",") if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ConfigError("'engine' harus daftar nama mesin")
    names = [item for item in items if item.strip()]
    return tuple(normalize_engine_names(names)) if names else ()


def _is_private_lan_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def host_name(header: str) -> str:
    """Ambil nama host dari header ``Host`` secara ketat (mencegah bypass IPv6)."""
    header = header.strip().lower()
    if not header:
        return ""
    if header.startswith("["):
        inside, sep, rest = header[1:].partition("]")
        if not sep or not inside:
            return ""
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return ""
        return inside
    if ":" in header:
        name, port = header.rsplit(":", 1)
        return name if port.isdigit() and ":" not in name else ""
    return header


def lan_ip() -> str:
    """Tebak IP LAN komputer ini; ``127.0.0.1`` bila tidak ada jaringan."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(_ROUTE_PROBE)
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def allowed_hosts(bind_host: str, lan_address: str | None = None) -> frozenset[str]:
    """Daftar nilai ``Host`` yang diterima untuk alamat bind tertentu."""
    hosts = set(LOOPBACK_HOSTS)
    if bind_host not in ("0.0.0.0", "::", ""):
        hosts.add(bind_host.lower())
    if lan_address:
        hosts.add(lan_address)
    return frozenset(hosts)


def make_server(
    cfg: Config, host: str = "127.0.0.1", port: int = 8765, *, lan: bool = False,
    engine_builder: EngineBuilder = build_engines,
) -> JptransServer:
    """Buat server yang siap ``serve_forever`` (port 0 memilih port bebas, untuk tes).

    Raises:
        ConfigError: Port sedang dipakai atau alamat tidak bisa di-bind.
    """
    bind_host = "0.0.0.0" if lan else host
    lan_address = lan_ip() if lan else None
    try:
        return JptransServer(
            (bind_host, port),
            cfg,
            allowed_hosts(bind_host, lan_address),
            engine_builder=engine_builder,
            allow_lan=lan,
        )
    except OSError as exc:
        raise ConfigError(f"tidak bisa membuka server di {bind_host}:{port}: {exc}") from exc


def serve(
    cfg: Config, host: str = "127.0.0.1", port: int = 8765, *, lan: bool = False,
    open_browser: bool = False, on_ready: Callable[[str, bool], None] | None = None,
) -> None:
    """Jalankan server sampai Ctrl+C.

    Args:
        cfg: Konfigurasi program.
        host: Alamat bind.
        port: Port.
        lan: Bind ``0.0.0.0`` dan umumkan alamat IP LAN.
        open_browser: Buka browser bawaan ke URL bertoken.
        on_ready: Dipanggil dengan (URL bertoken, mode LAN) setelah server siap;
            CLI memakainya untuk mencetak URL. Tanpa callback, URL tidak
            ditampilkan di mana pun karena memuat token.
    """
    server = make_server(cfg, host, port, lan=lan)
    shown_host = lan_ip() if lan else ("127.0.0.1" if host in ("0.0.0.0", "") else host)
    url = f"http://{_url_host(shown_host)}:{server.port}/#t={server.token}"
    logger.info("server berjalan di %s:%d (lan=%s)", shown_host, server.port, lan)
    if on_ready is not None:
        on_ready(url, lan)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("server dihentikan")
    finally:
        server.close()


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


PAGE_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; frame-src 'self' blob:; img-src data: blob:; base-uri 'none'; "
            "form-action 'none'")

ERROR_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"

NOT_FOUND_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Halaman tidak ditemukan - jptrans</title>
<style>
:root { --bg: #fafaf7; --fg: #1d1d1b; --muted: #6b6b66; --accent: #2457a6; --line: #8e8d86; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --fg: #ecebe6; --muted: #a3a29c; --accent: #8db4f0; --line: #6c6b66; }
}
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 1rem; }
h1 { font-size: 1.4rem; margin: .5rem 0 1rem; }
p { color: var(--muted); }
a { color: var(--accent); min-height: 44px; display: inline-flex; align-items: center;
    padding: 0 .9rem; border: 1px solid var(--line); border-radius: .5rem; }
a:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
</style>
</head>
<body>
<main>
<h1>Halaman tidak ditemukan (404)</h1>
<p>Alamat ini tidak ada di server jptrans. Halaman penerjemah ada di alamat utama;
token tetap tersimpan selama tab browser ini terbuka.</p>
<p><a href="/">Kembali ke jptrans</a></p>
</main>
</body>
</html>
"""

PAGE_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>jptrans</title>
<style>
:root, :root[data-theme="light"] {
  color-scheme: light; --bg: #fafaf7; --fg: #1d1d1b; --muted: #6b6b66; --line: #8e8d86;
  --accent: #2457a6; --on-accent: #ffffff; --err: #b3261e; --err-bg: #fdecea;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark; --bg: #161615; --fg: #ecebe6; --muted: #a3a29c; --line: #6c6b66;
    --accent: #8db4f0; --on-accent: #161615; --err: #ff8a80; --err-bg: #3b1d1b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark; --bg: #161615; --fg: #ecebe6; --muted: #a3a29c; --line: #6c6b66;
  --accent: #8db4f0; --on-accent: #161615; --err: #ff8a80; --err-bg: #3b1d1b;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); overflow-wrap: break-word;
       font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 1rem 1rem 3rem; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: .75rem;
          margin: .25rem 0 1rem; flex-wrap: wrap; }
h1 { font-size: 1.4rem; margin: 0; }
label { display: block; font-weight: 600; margin: .75rem 0 .25rem; }
textarea, input, select, button { font: inherit; color: inherit; background: transparent;
  border: 1px solid var(--line); border-radius: .5rem; padding: .5rem .6rem; width: 100%;
  min-height: 44px; }
option { background: var(--bg); color: var(--fg); }
textarea { min-height: 10rem; resize: vertical; }
textarea:lang(ja) { font-family: "Hiragino Sans", "Yu Gothic", "Noto Sans JP", sans-serif; }
.row { display: grid; gap: .75rem; grid-template-columns: 1fr 1fr; }
.file-row { display: flex; gap: .5rem; align-items: center; }
button { background: var(--accent); color: var(--on-accent); border: 0; font-weight: 600;
         margin-top: 1rem; cursor: pointer; }
button.secondary { background: transparent; color: var(--fg); border: 1px solid var(--line);
                   margin-top: 0; width: auto; white-space: nowrap; padding: .5rem .9rem; }
button[disabled] { opacity: .5; cursor: not-allowed; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
#status { color: var(--muted); margin: 1rem 0; min-height: 1.5em; }
#status.err, .alert { color: var(--err); font-weight: 600; background: var(--err-bg);
                      border-left: 4px solid var(--err); border-radius: .5rem;
                      padding: .6rem .8rem; }
#links { display: flex; flex-wrap: wrap; gap: .5rem; margin: .75rem 0; }
iframe { width: 100%; height: 70vh; border: 1px solid var(--line); border-radius: .5rem;
         background: var(--bg); margin-top: .5rem; }
.hidden { display: none !important; }
@media (max-width: 30rem) { .row { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<main>
<div class="topbar">
  <h1>jptrans</h1>
  <button id="theme" type="button" class="secondary">Tema: Otomatis</button>
</div>
<p id="notoken" class="hidden alert" role="alert">Token tidak ada. Buka alamat lengkap
(dengan <code>#t=...</code>) yang dicetak di terminal.</p>
<form id="form">
  <label for="text">Teks Jepang</label>
  <textarea id="text" lang="ja" placeholder="田中さんは東京駅で佐藤先輩を待っていた。"></textarea>
  <label for="file">atau unggah berkas (.txt .md .html .epub .srt .vtt .ass .json)</label>
  <div class="file-row">
    <input id="file" type="file"
      accept=".txt,.md,.html,.htm,.xhtml,.epub,.srt,.vtt,.ass,.ssa,.json">
    <button id="clearfile" type="button" class="secondary hidden">Hapus berkas</button>
  </div>
  <div class="row">
    <div><label for="title">Judul (menentukan glosarium)</label>
      <input id="title" placeholder="teks"></div>
    <div><label for="to">Bahasa sasaran</label>
      <select id="to"><option value="id">Indonesia</option><option value="en">Inggris</option>
      </select></div>
  </div>
  <label for="engine">Mesin (kosong = bawaan, mis. deepl,mymemory atau fake)</label>
  <input id="engine" placeholder="">
  <button id="go" type="submit">Terjemahkan</button>
</form>
<p id="status" role="status">Tempel teks Jepang atau pilih berkas, lalu tekan Terjemahkan.</p>
<div id="links" class="hidden">
  <button type="button" class="secondary" data-fmt="html">Unduh HTML</button>
  <button type="button" class="secondary" data-fmt="txt">Unduh TXT</button>
  <button type="button" class="secondary" data-fmt="md">Unduh MD</button>
  <button type="button" class="secondary" data-fmt="json">Unduh JSON</button>
  <button type="button" class="secondary hidden" data-fmt="srt" id="srt">Unduh SRT</button>
  <button type="button" class="secondary hidden" data-fmt="vtt" id="vtt">Unduh VTT</button>
  <button type="button" class="secondary hidden" data-fmt="ass" id="ass">Unduh ASS</button>
</div>
<iframe id="view" class="hidden" sandbox title="Hasil terjemahan"></iframe>
</main>
<script>
"use strict";
const KEY = "jptrans-token";
const THEME_KEY = "jptrans-theme";
const THEMES = ["auto", "dark", "light"];
const THEME_LABELS = {auto: "Tema: Otomatis", dark: "Tema: Gelap", light: "Tema: Terang"};
const hash = new URLSearchParams(location.hash.slice(1));
if (hash.get("t")) {
  sessionStorage.setItem(KEY, hash.get("t"));
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem(KEY) || "";
const $ = (id) => document.getElementById(id);
if (!token) { $("notoken").classList.remove("hidden"); $("go").disabled = true; }
let jobId = null;

function applyTheme(mode) {
  if (mode === "dark" || mode === "light") {
    document.documentElement.dataset.theme = mode;
  } else {
    delete document.documentElement.dataset.theme;
    mode = "auto";
  }
  $("theme").textContent = THEME_LABELS[mode];
}
let currentTheme = localStorage.getItem(THEME_KEY) || "auto";
if (!THEMES.includes(currentTheme)) currentTheme = "auto";
applyTheme(currentTheme);
$("theme").addEventListener("click", () => {
  currentTheme = THEMES[(THEMES.indexOf(currentTheme) + 1) % THEMES.length];
  localStorage.setItem(THEME_KEY, currentTheme);
  applyTheme(currentTheme);
});

function api(path, options = {}) {
  options.headers = Object.assign({"X-Token": token}, options.headers || {});
  return fetch(path, options).then(async (response) => {
    if (!response.ok) {
      let message = response.statusText;
      try { message = (await response.json()).error || message; } catch (e) {}
      throw new Error(message);
    }
    return response;
  });
}

function say(text, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("err", error);
}

$("file").addEventListener("change", () => {
  $("clearfile").classList.toggle("hidden", !$("file").files.length);
});
$("clearfile").addEventListener("click", () => {
  $("file").value = "";
  $("clearfile").classList.add("hidden");
});

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("file").files[0];
  const options = {title: $("title").value.trim(), to: $("to").value,
                   engine: $("engine").value.trim()};
  let request;
  if (file) {
    const query = new URLSearchParams(options).toString();
    request = api("/api/jobs?" + query, {method: "POST", body: file,
      headers: {"X-Filename": encodeURIComponent(file.name),
                "Content-Type": "application/octet-stream"}});
  } else {
    const text = $("text").value;
    if (!text.trim()) { say("Isi teks atau pilih berkas dulu.", true); return; }
    const body = {text, title: options.title || "teks", to: options.to};
    if (options.engine) body.engine = options.engine.split(",");
    request = api("/api/jobs", {method: "POST", body: JSON.stringify(body),
      headers: {"Content-Type": "application/json"}});
  }
  $("go").disabled = true;
  $("links").classList.add("hidden");
  $("view").classList.add("hidden");
  try {
    jobId = (await (await request).json()).id;
    poll();
  } catch (error) { say("Gagal: " + error.message, true); $("go").disabled = false; }
});

async function poll() {
  try {
    const job = await (await api("/api/jobs/" + jobId)).json();
    if (job.status === "done") {
      say("Selesai.");
      $("view").srcdoc = job.html;
      $("view").classList.remove("hidden");
      const isSub = ["srt", "vtt", "ass"].includes(job.format);
      $("srt").classList.toggle("hidden", !isSub);
      $("vtt").classList.toggle("hidden", !isSub);
      $("ass").classList.toggle("hidden", !isSub);
      $("links").classList.remove("hidden");
      $("go").disabled = false;
      return;
    }
    if (job.status === "failed") {
      say("Gagal: " + job.error, true); $("go").disabled = false; return;
    }
    say(job.total ? `Menerjemahkan ${job.done}/${job.total} kalimat (${job.message})`
                  : "Menunggu giliran...");
    setTimeout(poll, 1000);
  } catch (error) { say("Gagal: " + error.message, true); $("go").disabled = false; }
}

$("links").addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-fmt]");
  if (!btn || !jobId) return;
  const fmt = btn.dataset.fmt;
  event.preventDefault();
  try {
    const response = await api(`/api/jobs/${jobId}/download?fmt=${fmt}`);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await response.blob());
    link.download = ($("title").value.trim() || "jptrans") + "." + fmt;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  } catch (error) { say("Gagal mengunduh: " + error.message, true); }
});
</script>
</body>
</html>
"""
