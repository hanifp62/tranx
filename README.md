# tranX

Cross-device Progressive Web App (PWA) for translating text, images, documents, and web novel / ebook pages across **Indonesian**, **English**, and **Japanese** with automatic language detection, bidirectional character name consistency, and full offline-ready standalone installation.

Live application: [tranx-hanif-id.web.app](https://tranx-hanif-id.web.app)

## Highlights

- **9 Bidirectional Language Pairs + Auto-Detect**: Full support for `auto-id`, `auto-en`, `auto-ja`, `ja-id`, `ja-en`, `id-ja`, `id-en`, `en-id`, and `en-ja`, including real-time detected language indicator, instant swap, bidirectional character name glossary (`Chihaya` <-> `千早`), and adaptive voice dictation (`id-ID`, `en-US`, `ja-JP`).
- **4 Isolated Workspaces**: Dedicated workflows for **Text**, **Image** (zero-key client WASM OCR + overlay canvas), **Document** (`.txt`, `.md`, `.srt`, `.vtt`, `.ass`, `.html`, `.docx`, `.epub`, `.pdf` with CJK font support), and **Link / Ebook Reader**.
- **Universal Multi-Site Ebook & Translated Site Reader**:
  - In-app **Ebook Reader** (1-column focused reading + 2-column side-by-side desktop bilingual view) and **Translated Site** view with automatic chapter detection and navigation across Kakuyomu (full `/episode_sidebar` expansion up to 1,500 chapters), Syosetu, RoyalRoad, Aozora Bunko (Shift_JIS), NovelBin, AO3, Wikipedia, and WordPress sites.
  - Self-healing IndexedDB v2 cache (`tranx_perf_cache_v1`) that automatically purges poisoned HTTP 403/WAF blocks, retries with `X-No-Cache`, rescues CloudFront 403 pages, and runs untranslated mop-up retry waves.
- **High-Throughput Resilient Architecture**:
  - Dual-tier execution: Firebase Cloud Functions Gen-2 (`python312`, `asia-southeast2`) when running on Blaze, with automatic `/v1/healthz` circuit-breaker fallback to the browser Direct Engine (`web/src/lib/directEngine.ts`) on Firebase Spark.
  - Hardware-adaptive token bucket, endpoint circuit breaker, bounded LRU caches, sliding-window rate limiting (`120/min` general, `15/min` heavy web/document routes), and 3x parallel translation pool for smooth 5-10 concurrent user operation.
- **Installable Cross-Device PWA**:
  - Zero-warning W3C Web App Manifest, Workbox service worker precaching, synchronous `<head>` `beforeinstallprompt` capture (`/pwa-capture.js`), 1-click native installation on Desktop and Android Chrome, automatic hide when installed, and responsive mobile/tablet/desktop layouts verified against WCAG 2.2 Level AA.

## Architecture & Repository Layout

```text
tranx/
├── translator.py                  # Core jptrans 1.1.0 engine source (locked intact, MD5 verified)
├── tools/
│   ├── vendor_jptrans.py          # Deterministic vendor extractor + MANIFEST.sha256 generator
│   └── verify_integrity.py        # MD5, 32 selftests, AST boundary, secret & hygiene gate
├── functions/
│   ├── main.py                    # Firebase Cloud Functions Gen-2 entrypoint (asia-southeast2)
│   ├── requirements.txt           # Python 3.12 backend dependencies
│   ├── app/                       # Flask /v1/* routes, rate limiter, Firestore/InMemory store
│   ├── tranx_core/                # Translation adapter, 9-pair matrix, glossary, OCR, docs, web
│   ├── vendor/                    # Deterministically extracted jptrans modules + MANIFEST.sha256
│   └── tests/                     # Unit and HTTP route contract test suite (pytest)
├── web/
│   ├── index.html                 # App shell with synchronous /pwa-capture.js head hook
│   ├── public/                    # PWA capture script, SVG favicon, 192/512 icons, screenshots
│   ├── src/
│   │   ├── App.tsx                # Main application shell (Text, Image, Document, Link workspaces)
│   │   ├── components/            # SubViews (desktop/mobile reader), Modals, ImageOverlayCanvas
│   │   ├── lib/                   # directEngine, api, resilience, perfCache (IDB v2), pwaInstall
│   │   ├── i18n/                  # Indonesian & English UI string tables
│   │   └── styles/                # tranX v3 design tokens & responsive Light/Dark stylesheets
│   ├── e2e/                       # Playwright E2E, mobile/desktop QA & axe-core WCAG 2.2 AA suite
│   ├── vite.config.ts             # Vite 6 + vite-plugin-pwa manifest & Workbox configuration
│   └── .env.example               # Template environment variables (safe placeholder values)
├── .github/
│   ├── workflows/ci.yml           # Automated integrity, pytest, web build & secret hygiene CI
│   └── PULL_REQUEST_TEMPLATE.md   # Pull request verification checklist
├── firebase.json                  # Hosting headers (CSP/HSTS/COOP/CORP), rewrites, Firestore, Auth
├── firestore.rules                # Per-user isolated multi-account Cloud Firestore security rules
├── firestore.indexes.json         # Composite indexes for pinned history and TTL cleanup
├── storage.rules                  # Per-user isolated Cloud Storage rules (50 MB upload cap)
├── SECURITY.md                    # Security architecture and vulnerability reporting policy
├── CHANGELOG.md                   # Structured release history
└── LICENSE                        # MIT License
```

## Quick Start

### Prerequisites

- **Node.js 22+** and **npm**
- **Python 3.12+**
- Optional: **Firebase CLI** (`firebase-tools`) for hosting/rules deployment

### 1. Clone & Configure Environment

```bash
git clone https://github.com/hanifp62/tranx.git
cd tranx
cp web/.env.example web/.env.local
```

Populate `web/.env.local` with your Firebase Web SDK project values for local development only. On Firebase Hosting, production builds omit `VITE_FIREBASE_API_KEY` completely and load Firebase Web SDK client configuration at runtime via same-origin `/__/firebase/init.json` so zero API keys are ever baked into static `web/dist/assets/*.js` bundles. Never commit `.env.local` or `.env.production` files.

### 2. Install Dependencies

```bash
# Frontend PWA
npm ci --prefix web

# Backend Cloud Functions & tests (virtualenv recommended)
python3.12 -m venv functions/venv
functions/venv/bin/pip install -r functions/requirements.txt pytest
```

### 3. Run Locally

```bash
npm run dev:web
```

## Verification & Quality Gates

Every change should pass all four checks before merging or deploying:

```bash
# 1. Verify translator.py MD5 purity, 52 vendor SHA-256 files, 32/32 selftests, AST & secret hygiene
npm run verify:integrity

# 2. Run backend unit and HTTP contract tests (30 tests)
npm run test:backend

# 3. Typecheck and build production PWA bundle
npm run build:web

# 4. Run Playwright cross-viewport E2E & WCAG 2.2 AA accessibility suite (7 suites)
npm run test:e2e
```

## Deployment

### Firebase Spark Plan (Hosting + Firestore Rules + Direct Engine)

```bash
npm run build:web
firebase deploy --only firestore,hosting --project <your-firebase-project-id>
```

### Firebase Blaze Plan (Full Cloud Functions Gen-2 + Cloud Storage)

```bash
firebase deploy --only functions,storage --project <your-firebase-project-id>
```

Optional Gemini API keys can be configured inside the app under **Settings -> Advanced** and are stored strictly inside each user's isolated Firestore `/users/{uid}/settings/secrets` document rather than browser `localStorage`. Any verified Google account can sign in across multiple devices with complete tenant isolation; self-hosters who want private allowlist mode can optionally set `VITE_ALLOWED_EMAILS` / `ALLOWED_EMAILS`.

## License

Released under the [MIT License](LICENSE).
