# tranX

Aplikasi web progresif (PWA) lintas perangkat milik pribadi untuk menerjemahkan teks, gambar, dokumen, dan halaman web berbahasa Jepang ke bahasa Indonesia atau Inggris dengan menjaga konsistensi ejaan nama tokoh dari kalimat ke kalimat.

## Arsitektur Inti

- **Mesin Terjemahan (`translator.py` / `jptrans 1.1.0`)**: Berkas tunggal `translator.py` di akar repositori dijaga utuh tanpa modifikasi dan diekstrak secara deterministik ke `functions/vendor/jptrans/` melalui `tools/vendor_jptrans.py` lengkap dengan verifikasi SHA-256 (`MANIFEST.sha256`).
- **Lapisan Adaptor Cloud (`functions/tranx_core/` & `functions/app/`)**: Berjalan di Cloud Functions for Firebase Gen-2 (`python312`, region `asia-southeast2` Jakarta) untuk streaming obrolan NDJSON (`/v1/chat`), naskah panjang (`/v1/translate` & `/v1/translate:resume`), OCR gambar (`/v1/image:translate`), dikte suara cadangan (`/v1/speech:transcribe`), pratinjau serta pembaca web aman anti-SSRF (`/v1/links:preview` & `/v1/web`), dan pemrosesan dokumen latar Cloud Storage (`on_document_uploaded` hingga 50 MB).
- **Antarmuka Ruang Baca (`web/`)**: Dibangun dengan React 19, Vite 6, TypeScript, dan Workbox PWA mengikuti sistem desain `tranX v3` (*Ruang Baca Tinta Sumi & Kaca Optik*, tema `Terang` dan `Gelap`, bahasa antarmuka `Indonesia` dan `English`).
- **Keamanan Pemilik Tunggal**: Seluruh aturan `firestore.rules`, `storage.rules`, dan verifikasi token HTTP mengunci akses ke akun pemilik tunggal atau perangkat kedua yang dipasangkan lewat kode 6 angka sekali pakai (`/v1/auth:pairCode`), tanpa menyimpan kunci API model di penyimpanan peramban.

## Struktur Direktori

```text
.
├── translator.py              # Mesin sumber jptrans 1.1.0 (dikunci utuh)
├── tools/
│   ├── vendor_jptrans.py      # Ekstraktor modul vendor + MANIFEST.sha256
│   └── verify_integrity.py    # Pemeriksa MD5, 32 selftest, batas impor AST, dan kebersihan kode
├── functions/
│   ├── main.py                # Titik masuk Cloud Functions Gen-2 (asia-southeast2)
│   ├── tranx_core/            # Adaptor mesin, glosarium 14 kolom, OCR, dokumen, web, dan suara
│   ├── app/                   # Repositori Firestore/InMemory dan rute Flask /v1/*
│   └── tests/                 # Uji unit dan kontrak rute HTTP (pytest)
├── web/
│   ├── src/                   # Aplikasi PWA React 19 + sistem token tranX v3
│   └── e2e/                   # Uji klik menyeluruh dan audit WCAG 2.2 AA (Playwright + axe-core)
├── firestore.rules            # Aturan keamanan Cloud Firestore pemilik tunggal
├── firestore.indexes.json     # Indeks komposit riwayat disematkan & TTL
├── storage.rules              # Aturan keamanan Cloud Storage (batas unggah 50 MB)
└── firebase.json              # Konfigurasi Hosting, Firestore, Storage, Auth, dan Functions
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

## Konfigurasi Kunci Model (Setelah Deploy)

1. Masuk ke aplikasi menggunakan akun Google pemilik.
2. Buka **Setelan -> Lanjutan**, masukkan kunci API Gemini berbayar Anda ke brankas server (`/v1/engine:key`), lalu tekan **Cek mesin sekarang** untuk memverifikasi latensi model.
3. Untuk mengaktifkan Cloud Functions Gen-2 dan Cloud Storage pada proyek Firebase baru, pastikan paket penagihan **Blaze (pay-as-you-go)** aktif pada proyek `tranx-hanif-id`, lalu jalankan:
   ```bash
   firebase deploy --only functions,storage --project tranx-hanif-id
   ```
