# tranX

Cross-device Progressive Web App (PWA) for translating text, images, documents, and web novel / ebook pages across **Indonesian**, **English**, and **Japanese** with automatic language detection, bidirectional character name consistency, and full offline-ready standalone installation.

Live application: [tranx-hanif-id.web.app](https://tranx-hanif-id.web.app)

## Highlights

- **Translation Excellence v5 (Discourse Coherence, Reference-Free QE & TS/Python Parity)**:
  - Author-Purpose-Reader discourse profiling across 13 genres (`fiction_novel`, `fiction_dialogue_heavy`, `classic_literary`, `manga_comic_sfx`, `subtitle_script`, `news_wire`, `essay_journalism`, `business_formal`, `technical_docs`, `academic_research`, `legal_policy`, `children_ya`, `general`) grounded in Nida, Newmark, Reiss/Vermeer/Nord Skopos, Baker, House, Grosz/Walker Centering Theory, and MQM Core.
  - 5-tier Bunka Shingikai Japanese Keigo classifier (`bikago` register-neutral vs `sonkeigo` referent elevation), Centering Theory zero-anaphora `[Discourse Anchor]`, 18+ Yojijukugo & Kotowaza entries, Hamano/Akita unseen phonological mimetic detector, Purwo Indonesian oblique deixis guard, intra-quote T-V register alignment, `FormatShield` syntax protection, EYD V & KBBI VI rules, zero raw `U+2014` em-dashes, 12-invariant `ConservationGate`, and Reference-Free Source->Target QE (3:2:1 Nababan/ISO 5060:2024, positional/unit Kanji numeral conservation, 4-class Legal/RFC 2119 deontic lattice, academic epistemic hedging guard, CJK-aware repetition-loop detector, and bounded single-pass MQM self-repair).
- **9 Bidirectional Language Pairs + Auto-Detect**: Full support for `auto-id`, `auto-en`, `auto-ja`, `ja-id`, `ja-en`, `id-ja`, `id-en`, `en-id`, and `en-ja`, including real-time detected language indicator, instant swap, bidirectional character name glossary (`Chihaya` <-> `千早`), and adaptive voice dictation (`id-ID`, `en-US`, `ja-JP`).
- **4 Isolated Workspaces**: Dedicated workflows for **Text**, **Image** (zero-key client WASM OCR with Canvas 2D preprocessing + pre-sampled feathered gradient overlay canvas), **Document** (`.txt`, `.md`, `.srt`, `.vtt`, `.ass`, `.html`, `.docx`, EPUB 3.3 `<spine>` + furigana stripping, multi-column XY-Cut `.pdf` with hyphenation repair & running header/footer stripping, balanced 42/18 CPL subtitle export), and **Link / Ebook / Manga Reader**.
- **Link Mode Manga, Comic & Direct-Image Scanner**:
  - Automatically detects direct comic/manga image URLs (including extensionless CDNs such as `pbs.twimg.com`, `i.redd.it`, `i.imgur.com`, `uploads.mangadex.org`, `pstatic.net`, `catbox.moe`, `imgchest.com`, `cdn.discordapp.com`) and HTML manga/webtoon/manhwa/manhua chapter galleries while filtering logos, ads, avatars, and spinners.
  - Supports multi-row variance gutter-snapped vertical strip slicing (up to `65536px` / `36 MP` without truncation), per-box orientation transitive union-find OCR clustering, Recursive XY-Cut panel-gutter reading order (`rtl_manga`, `webtoon_strip`, `four_koma`, `ltr_comic`), Western ALL-CAPS normalization, DRM canvas detection with clipboard `Ctrl+V` / upload rescue, pre-sampled edge-aware feathered gradient overlay typesetting with screentone alpha preservation, EXIF-aware server Vision OCR NMS/XY-Cut, and backend anti-SSRF `GET /v1/media:proxy`.
- **Universal Multi-Site Ebook Reader & WCAG 2.2 AA/AAA HCI Studio**:
  - Two-tier Adaptive Surface Architecture with 6 WCAG AA/AAA eye-comfort reading themes (`Paper`, `Sepia`, `Sage`, `Dusk`, `Midnight OLED`, `E-Ink`), 14 lazy-loaded publisher reading fonts (`font-optical-sizing: auto`, Dark/OLED `>= 16px` floor + halation tracking + variable `GRAD -25`), full WCAG 1.4.12 spacing sliders (`letterSpacing`, `wordSpacing`, `paragraphSpacing`, `fontSize` up to `32px`), 1-tap **Dyslexia Comfort Preset**, **Digital Reading Ruler** (`off`/`bar`/`shade`/`underline`), **Handedness Tap-Zones** (`edges`/`right-hand`/`left-hand`) with `180ms` post-scroll tap lockout, non-linear scrubber Jump-Back return pill, GPU-accelerated drag-follow **Slide** and **3D Book-Flip** animations, **Auto-Gulir**, Zen Focus mode, and full cross-device Firestore sync across `/web` and `/c/.../baca`.
  - Automatic chapter detection across Kakuyomu (full `/episode_sidebar` expansion up to 1,500 chapters), Syosetu, RoyalRoad, Aozora Bunko (Shift_JIS), NovelBin, AO3, Wikipedia, and WordPress, backed by a relaxed-durability self-healing IndexedDB v2.5 cache (`tranx_perf_cache_v1`) with dynamic 50% `QuotaExceededError` recovery and named circuit breakers.
- **Expressive Podcast Audio Narration Studio v2.5 ("Dengarkan")**:
  - Automatic 8-format document classifier (`fiction_novel`, `news_editorial`, `academic_paper`, `technical_docs`, `script_dialogue`, `poetry_verse`, `list_instructions`, `letter_quote`) with manual studio override, Two-Pass Fiction Speaker Attribution Sieve (`single`/`persona`/`multi_voice` Cast Mode), rate-adaptive `<11s` anti-stall chunking with `2.8s` launch watchdog + cloud-to-local auto-fallback, 45-second Stevens power-law (`p^1.55`) sleep fade with pause-preserving countdown, two-tier macro scene-break pauses, Kestrel trilingual text normalization (SemVer, phone numbers, dates, scientific notation, fractions, contextual regnal Roman numerals, Vance irregular JA counters), and 44x44px Voice Preview.
- **Hardened Multi-Account OWASP 2025 Security & Strict HTTP 404 Routing**:
  - Strict route allowlist (`web/src/lib/routeGuard.ts`) plus true static HTTP `404` (`web/public/404.html`), RFC 9116 `/.well-known/security.txt`, Fetch Metadata + `Origin` CSRF defense, universal `/v1/*` `Cache-Control: no-store`, W3C `traceparent`/`X-Request-Id` correlation, TLS 1.2+ floor, RFC 6890/NAT64 SSRF blocking, exact on-disk local-header Fifield overlapping-entry ZIP bomb guard, and streaming `O(64 KB)` `expat` XXE protection.
  - Dual-tier execution: Firebase Cloud Functions Gen-2 (`python312`, `asia-southeast2`) on Blaze, with automatic `/v1/healthz` circuit-breaker fallback to the browser Direct Engine (`web/src/lib/directEngine.ts`) on Firebase Spark.
- **Installable Cross-Device PWA & Performance Hygiene (v2.5.1)**:
  - Decoupled pure `langUtils`, `tonePrefs`, and `ebookStorage` entry modules and dynamically split `firebase/firestore` (`450.63 kB` `firebase-db` removed from boot bundle & `modulePreload`), pairing `<link rel="preload" href="/__/firebase/init.json">` and deferred `/pwa-capture.js` with `IntersectionObserver` offscreen manga canvas dehydration, Workbox `CacheFirst` runtime caching for app chunks & `fonts.gstatic.com`, non-blocking service-worker update banner, 40 MiB Firestore offline cache cap, PII-free `ErrorBoundary` recovery with full shared-device cache wipe on sign-out, WCAG 2.2 AA `useDialogFocusTrap` across all dialogs/sheets, and verified sub-1s Cold LCP (`924 ms`) / `120 ms` Warm SW LCP / `0` CLS across `320px` to `1440px`.

## Architecture & Repository Layout

```text
tranx/
├── translator.py                  # Core jptrans 1.1.0 engine source (locked intact, MD5 verified)
├── tools/
│   ├── vendor_jptrans.py          # Deterministic vendor extractor + MANIFEST.sha256 generator
│   └── verify_integrity.py        # MD5, 32 selftests, AST boundary, secret & hygiene gate
├── functions/
│   ├── main.py                    # Firebase Cloud Functions Gen-2 entrypoint (asia-southeast2)
│   ├── requirements.txt           # Python 3.12 backend dependencies (incl. Pillow)
│   ├── app/                       # Flask /v1/* routes (incl. /v1/media:proxy), rate limiter, store
│   ├── tranx_core/                # Translation adapter, literary_polish v5, 9-pair matrix, OCR, web
│   ├── vendor/                    # Deterministically extracted jptrans modules + MANIFEST.sha256
│   └── tests/                     # Unit, literary polish & HTTP route contract suite (47 pytest)
├── web/
│   ├── index.html                 # App shell with /__/firebase/init.json preload & deferred /pwa-capture.js
│   ├── public/                    # 404.html, .well-known/security.txt, pwa-capture.js, SVG favicon, icons
│   ├── src/
│   │   ├── App.tsx                # Main application shell (Text, Image, Document, Link workspaces)
│   │   ├── components/            # SubViews, MangaLinkReader, EbookAppearancePanel, ImageOverlayCanvas, Modals, NotFoundView, ErrorBoundary
│   │   ├── lib/                   # directEngine, literaryPolish v5, podcastNarrator v2.5, mangaScanner, ebookPrefs, ebookService, ebookStorage, langUtils, tonePrefs, routeGuard, useDialogFocusTrap, api, firebase, resilience, perfCache, pwaInstall
│   │   ├── i18n/                  # Indonesian & English UI string tables
│   │   └── styles/                # tranX design tokens & responsive Light/Dark/Ebook/Manga stylesheets
│   ├── e2e/                       # Playwright E2E, Chaos & axe-core WCAG 2.2 AA (18 suites)
│   ├── vite.config.ts             # Vite 6 + vite-plugin-pwa manifest & Workbox configuration
│   └── .env.example               # Template environment variables (safe placeholder values)
├── .github/
│   ├── workflows/ci.yml           # Automated integrity, pytest, web build, npm audit, 404 & secret hygiene CI
│   └── PULL_REQUEST_TEMPLATE.md   # Pull request verification checklist
├── firebase.json                  # Hosting headers (CSP/HSTS/COOP/CORP), strict rewrites, Firestore
├── firestore.rules                # Per-user isolated multi-account Cloud Firestore security rules
├── firestore.indexes.json         # Composite indexes for pinned history and TTL cleanup
├── storage.rules                  # Per-user isolated Cloud Storage rules (50 MB upload cap)
├── pyrightconfig.json             # Portable Python 3.12 type-check configuration for functions/ & tools/
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

# 2. Run backend unit, literary polish, and HTTP contract tests (47 tests)
npm run test:backend

# 3. Typecheck and build production PWA bundle
npm run build:web

# 4. Run Playwright cross-viewport E2E, Chaos & WCAG 2.2 AA accessibility suite (18 suites)
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

Optional Gemini API keys can be configured inside the app under **Settings -> Advanced** and are stored strictly inside each user's isolated Firestore document (`/users/{uid}/serverSecrets/llm` on Blaze Cloud Functions or `/users/{uid}/settings/secrets` on Spark Direct Mode) rather than browser `localStorage`. Any verified Google account can sign in across multiple devices with complete tenant isolation; self-hosters who want private allowlist mode can optionally set `VITE_ALLOWED_EMAILS` / `ALLOWED_EMAILS`.

## License

Released under the [MIT License](LICENSE).
