# tranX

Aplikasi web progresif (PWA) lintas perangkat milik pribadi untuk menerjemahkan teks, gambar, dokumen, dan halaman web dua arah antara bahasa **Indonesia**, **Inggris**, dan **Jepang** (dilengkapi mode **Deteksi bahasa** otomatis dan tombol **Tukar bahasa**) sambil menjaga konsistensi ejaan nama tokoh dari kalimat ke kalimat.

## Arsitektur Inti

- **Matriks 9 Pasangan Bahasa Dua Arah & Deteksi Otomatis**: Mendukung penuh `auto-id`, `auto-en`, `auto-ja`, `ja-id`, `ja-en`, `id-ja`, `id-en`, `en-id`, dan `en-ja`, lengkap dengan pelindung glosarium dua arah (`Chihaya` <-> `千早`), indikator bahasa terdeteksi waktu nyata, dan dikte suara adaptif (`id-ID`, `en-US`, `ja-JP`).
- **Mesin Terjemahan (`translator.py` / `jptrans 1.1.0` + `multilingual.py`)**: Berkas tunggal `translator.py` di akar repositori dijaga utuh tanpa modifikasi dan diekstrak secara deterministik ke `functions/vendor/jptrans/` melalui `tools/vendor_jptrans.py` lengkap dengan verifikasi SHA-256 (`MANIFEST.sha256`).
- **Arsitektur Dua Tingkat Tahan Gangguan (Cloud Functions Gen-2 + Browser Direct Engine)**:
  - Saat Cloud Functions Gen-2 (`python312`, region `asia-southeast2` Jakarta) aktif, klien memakai rute `/v1/*` penuh (`/v1/chat`, `/v1/translate`, `/v1/image:translate`, `/v1/speech:transcribe`, `/v1/links:preview`, `/v1/web`, dan `on_document_uploaded`).
  - Saat proyek Firebase berjalan pada paket gratis **Spark** (tanpa Cloud Functions), pemutus arus `/v1/healthz` secara otomatis mengalihkan eksekusi ke mesin langsung di peramban (`web/src/lib/directEngine.ts`) untuk teks, dokumen (`.txt`, `.md`, `.srt`, `.vtt`, `.ass`, `.html`, `.docx`, `.epub`), gambar, dan pembaca tautan web bebas galat CORS (`r.jina.ai` + `googleapis.com`), tetap tersinkron penuh ke Cloud Firestore.
- **Antarmuka Ruang Baca (`web/`)**: Dibangun dengan React 19, Vite 6, TypeScript, dan Workbox PWA mengikuti sistem desain `tranX v3` (*Ruang Baca Tinta Sumi & Kaca Optik*, tema `Terang` dan `Gelap`, bahasa antarmuka `Indonesia` dan `English`).
- **Keamanan Pemilik Tunggal**: Seluruh aturan `firestore.rules`, `storage.rules`, dan verifikasi token HTTP mengunci akses ke akun pemilik tunggal atau perangkat kedua yang dipasangkan lewat kode 6 angka sekali pakai (`/v1/auth:pairCode`), serta menyimpan kunci API Gemini secara terisolasi di dokumen Firestore `/settings/secrets` milik pemilik tanpa `localStorage`.

## Struktur Direktori

```text
.
├── translator.py              # Mesin sumber jptrans 1.1.0 (dikunci utuh)
├── tools/
│   ├── vendor_jptrans.py      # Ekstraktor modul vendor + MANIFEST.sha256
│   └── verify_integrity.py    # Pemeriksa MD5, 32 selftest, batas impor AST, dan kebersihan kode
├── functions/
│   ├── main.py                # Titik masuk Cloud Functions Gen-2 (asia-southeast2)
│   ├── tranx_core/            # Adaptor mesin, matriks 9 bahasa, glosarium 14 kolom, OCR, dokumen, web, suara
│   ├── app/                   # Repositori Firestore/InMemory dan rute Flask /v1/*
│   └── tests/                 # Uji unit dan kontrak rute HTTP (pytest)
├── web/
│   ├── src/                   # Aplikasi PWA React 19 + directEngine Spark + sistem token tranX v3
│   └── e2e/                   # Uji klik menyeluruh, matriks bahasa, dan audit WCAG 2.2 AA (Playwright + axe-core)
├── firestore.rules            # Aturan keamanan Cloud Firestore pemilik tunggal (9 mode bahasa)
├── firestore.indexes.json     # Indeks komposit riwayat disematkan & TTL
├── storage.rules              # Aturan keamanan Cloud Storage (batas unggah 50 MB)
└── firebase.json              # Konfigurasi Hosting (+ CSP Direct Engine), Firestore, Storage, Auth, dan Functions
```

## Perintah Pengembangan & Verifikasi

1. **Verifikasi kemurnian mesin dan integritas kode:**
   ```bash
   npm run verify:integrity
   ```
2. **Jalankan uji unit dan rute backend (`functions/tests`):**
   ```bash
   npm run test:backend
   ```
3. **Bangun bundel produksi PWA (`web/dist`):**
   ```bash
   npm run build:web
   ```
4. **Jalankan uji E2E lintas ukuran layar dan aksesibilitas:**
   ```bash
   npm run test:e2e
   ```

## Konfigurasi Kunci Model & Deploy

1. Masuk ke aplikasi menggunakan akun Google pemilik (`https://tranx-hanif-id.web.app`).
2. Buka **Setelan -> Lanjutan**, masukkan kunci API Gemini Anda bila ingin memakai kualitas model penuh (disimpan aman ke Firestore `/settings/secrets`), lalu tekan **Cek mesin sekarang**. Tanpa kunci API sekalipun, terjemahan teks, dokumen, dan tautan web langsung berjalan instan.
3. Untuk memperbarui aturan Firestore dan bundel Hosting pada paket Spark maupun Blaze:
   ```bash
   firebase deploy --only firestore,hosting --project tranx-hanif-id
   ```
4. Opsional (paket **Blaze**): aktifkan Cloud Functions Gen-2 dan Cloud Storage penuh dengan menjalankan:
   ```bash
   firebase deploy --only functions,storage --project tranx-hanif-id
   ```
