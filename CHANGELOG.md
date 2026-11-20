# Changelog

All notable changes to `tranX` are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.1] - 2026-11-20

### Security
- Removed baked Firebase Web SDK API keys from static `web/dist/assets/*.js` bundles by bootstrapping runtime config from Firebase Hosting's reserved `/__/firebase/init.json` (`cache: 'no-store'`), and added `/^\/__\//` to Workbox `navigateFallbackDenylist`.
- Hardened CI (`web-build-and-pwa`) to fail builds if any `AIza...` key or `.map` sourcemap appears in `web/dist/assets/`.
- Fixed backend `X-Forwarded-For` rate-limit bypass by reading rightmost GFE-appended peer IP, added a global `/v1/auth:pair` rate-limit bucket across all IPs, fixed active 6-digit pair-code lockout after 5 wrong guesses across both `InMemoryRepository` and `FirestoreRepository`, sanitized `verify_owner_token` 401 error messages, and disabled `localhost` CORS origins when `K_SERVICE` is set in production.
- Eliminated the last `.innerHTML` sink in `web/src/lib/directEngine.ts` (replaced with safe DOM node construction) and hardened client + server HTML sanitizers against `meta[http-equiv="set-cookie"]`, non-stylesheet `<link>` tags, `formaction`, `xlink:href`, and unsafe CSS directives.
- Hardened Firebase Hosting headers (`firebase.json`): added `Cache-Control: no-cache` for `/` and `/web`, removed cleartext `http:` from CSP `img-src`, scoped jsDelivr `script-src`/`connect-src` to `https://cdn.jsdelivr.net/npm/`, added `upgrade-insecure-requests`, and added `X-Permitted-Cross-Domain-Policies: none`.
- Patched all 8 npm dependency advisories (`@grpc/grpc-js`, `serialize-javascript`, `glob`/`minimatch`) to `0 vulnerabilities` via `npm audit fix` and lockfile overrides in `web/package.json`.

## [2.2.0] - 2026-11-19

### Added
- Automated GitHub Actions CI workflow (`.github/workflows/ci.yml`) covering integrity/selftests, backend `pytest`, frontend TypeScript + PWA build validation, and secret/path hygiene guards.
- Pull request checklist template (`.github/PULL_REQUEST_TEMPLATE.md`), `SECURITY.md`, `CHANGELOG.md`, and MIT `LICENSE`.
- Hardware-adaptive resilience module (`web/src/lib/resilience.ts`) with `AdaptiveTokenBucket`, `EndpointCircuitBreaker`, `BoundedLruCache`, and device runtime profiling.
- Sliding-window backend rate limiting (`120/min` general, `15/min` heavy routes) for stable 5-10 concurrent user capacity.
- Persistent IndexedDB v2 cache (`web/src/lib/perfCache.ts`) with automatic cache migration and poisoned-403 entry purging.
- Synchronous `<head>` PWA install event capture (`web/public/pwa-capture.js`) with unified prompt store and late-prompt mobile waiting (`1200ms`).
- Universal multi-site Ebook and Translated Site extractor covering Kakuyomu (full `/episode_sidebar` expansion up to 1,500 chapters), Syosetu, RoyalRoad, Aozora Bunko (Shift_JIS), NovelBin, AO3, Wikipedia, and WordPress.
- Dedicated Playwright regression coverage across 7 full test suites (desktop, tablet, mobile, WCAG 2.2 AA, CloudFront 403 rescue, 84/92-chapter translation, and PWA installability).

### Changed
- Upgraded desktop `/web` reader with single-row 3-zone toolbar, true 2-column side-by-side bilingual layout, aligned `56px` optical top rail, and multi-breakpoint scaling (`768px`, `1024px`, `1440px+`).
- Overhauled mobile navigation with compact header, accessible hamburger drawer, bottom sheets, `>= 44x44px` touch targets, and zero horizontal overflow.
- Replaced intrusive PWA install notification banner with a compact header/drawer/account Install App button that auto-hides once installed and restores after mobile uninstall.
- Made E2E QA screenshot artifact paths fully portable (`QA_ARTIFACT_DIR` / `test-results/qa`) and sanitized `web/.env.example`.

### Fixed
- Eliminated Chrome Web App Manifest `share_target.enctype` warning and duplicate Workbox precache entries (`0` manifest errors, `0` installability errors in live Chrome CDP checks).
- Preserved Chrome `UserActivation` by invoking `beforeinstallprompt.prompt()` synchronously before closing menus or hiding install triggers.
- Fixed CloudFront 403 blank/error site pages, truncated 7-chapter Kakuyomu TOCs, mutated GTX paragraph markers, and partial chapter translations via automatic mop-up retry waves.
- Kept "Open auto-translated site" navigation strictly inside the app instead of spawning external browser tabs.

## [2.1.0] - 2026-11-19

### Added
- Initial `tranX` cross-device PWA and Firebase Gen-2 backend stack wrapping `jptrans 1.1.0` (`translator.py` locked intact with deterministic SHA-256 vendoring).
- 9 bidirectional language pairs (`ID`/`EN`/`JA` + `auto` detect) with bidirectional character name glossary and Spark Direct Engine fallback.
- Client-side WASM OCR (`tesseract.js`), PDF CJK extraction (`pdfjs-dist`), and DOCX/EPUB/SRT/VTT/ASS/HTML document translation.
- Hardened CSP, CORS, SSRF, XSS, and ZIP/magic-byte security guards with single-owner Firestore and Storage rules.
