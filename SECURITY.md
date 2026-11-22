# Security Policy

## Security Architecture

`tranX` is designed as a multi-account, cross-device translation platform with strict per-user tenant isolation and defense-in-depth controls across client, hosting, rules, and backend layers:

1. **Per-User Multi-Account Isolation (Zero Horizontal IDOR)**:
   - Every verified Google user receives an isolated Cloud Firestore subtree (`/users/{uid}/...`) and Cloud Storage namespace (`/uploads/{uid}/...`, `/outputs/{uid}/...`) enforced at the database/storage rules layer (`firestore.rules`, `storage.rules`) via `request.auth.uid == uid`, `isSafeDocId`, strict `hasOnlyAllowedFields`, and session revocation enforcement (`isSessionNotRevoked` checking `users/{uid}/serverSecrets/session.revokedBefore` vs `request.auth.token.auth_time`).
   - Anonymous accounts and unverified email accounts are rejected on both client and server (including Storage triggers via `assert_uid_allowed`). Self-hosters who want private allowlist mode can optionally configure `VITE_ALLOWED_EMAILS` / `ALLOWED_EMAILS` via environment variables without committing personal email PII to the repository.
   - Google Sign-In uses clean `prompt: 'select_account'` with zero hardcoded `login_hint`, completes both popup and redirect (`getRedirectResult`) flows cleanly, and clears in-memory + IndexedDB per-user caches on sign-out or account switch.
   - Secondary devices are paired per user via short-lived one-time 6-digit pairing codes (`/v1/auth:pairCode`), protected by rightmost `X-Forwarded-For` anti-spoofing, a global `/v1/auth:pair` rate limit across all IPs, and transactional 5-attempt lockout (`pairMeta/guard`).
   - Production Cloud Functions (`K_SERVICE` set) restrict CORS exclusively to production origins (never reflecting `localhost` origins), enforce server-key model & daily-cap ceilings (`effective_settings_for_key_source`), and isolate per-user translation memory caches by `uid`.
2. **Secret Isolation, Zero PII & Runtime Firebase Config**:
   - No API keys, OAuth tokens, private keys, service account files, or personal email addresses are committed to this repository or baked into production `web/dist/assets/*.js` bundles.
   - On Firebase Hosting, the frontend preloads and fetches Firebase Web SDK client configuration dynamically at runtime from the reserved same-origin endpoint `/__/firebase/init.json` (`cache: 'default'` with `sessionStorage` tab cache), excluded from service worker SPA navigation fallback.
   - Because Firebase Web SDK client identifiers are public by design once delivered to a browser (and included by Firebase Auth's OAuth popup handler `/__/auth/handler?apiKey=...`), actual protection is enforced server-side via per-user Firestore/Storage Security Rules, disabled Anonymous and Email/Password auth providers, and Google Cloud Console API Key HTTP Referrer + API restrictions.
   - Optional user-supplied Gemini API keys are stored strictly in each user's isolated Firestore document (`/users/{uid}/serverSecrets/llm` on Cloud Functions with legacy `/settings/secrets` cleanup, or `/users/{uid}/settings/secrets` on Spark Direct Mode) and never persisted in `localStorage`.
   - Automated CI (`web-build-and-pwa` and `security-and-hygiene` jobs in `.github/workflows/ci.yml`) and `tools/verify_integrity.py` continuously verify zero leaked secrets, zero hardcoded personal Gmail PII, zero `login_hint`, zero baked keys or sourcemaps in production bundles, zero heavy lazy chunk preload leaks, and zero high/critical production dependency vulnerabilities (`npm audit --omit=dev --audit-level=high`).
3. **Browser & HTTP Transport Hardening (`firebase.json`, `functions/app/routes.py`)**:
   - Strict `Content-Security-Policy` (no `'unsafe-inline'` scripts, `script-src` jsDelivr scoped to `https://cdn.jsdelivr.net/npm/`, `font-src` scoped to `'self' data: https://fonts.gstatic.com`, HTTPS-only `img-src`, `upgrade-insecure-requests`, explicit `connect-src` allowlist including `https://fonts.gstatic.com` for Workbox font caching, `object-src 'none'`, `frame-ancestors 'none'`).
   - `Strict-Transport-Security` (`max-age=63072000; includeSubDomains; preload`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-Permitted-Cross-Domain-Policies: none`, `Cross-Origin-Opener-Policy: same-origin-allow-popups`, `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-cache` on HTML entrypoints (`/`, `/web`, `/index.html`), universal `Cache-Control: no-store` across `/v1/*` API responses & streams, W3C `traceparent`/`X-Request-Id` correlation, Fetch Metadata (`Sec-Fetch-Site`) + `Origin` CSRF rejection on mutating API routes, and RFC 9116 `/.well-known/security.txt`.
4. **Input, Fetch, Media Proxy, Routing & Document Safety**:
   - Strict Hosting & SPA route allowlisting (`firebase.json`, `web/src/lib/routeGuard.ts`, `web/public/404.html`) returning true HTTP `404` for malformed, dotfile, or irrelevant paths (`///`, `/...`, `/.env`, `/laravel`, `/wp-admin`, encoded traversal, `/r/` self-loops).
   - Anti-SSRF IP-pinned fetching (`functions/tranx_core/web_translator.py`) and URL validator (`normalizeWebUrl`) enforcing TLS 1.2+ floor, `Connection: close` with safe response/socket cleanup, CRLF/NUL smuggling guards on URL/host/path/`Location`, and blocking private, loopback, link-local, CGNAT, RFC 6890 (`198.18.0.0/15`, `100::/64`, `::/96`), NAT64 embedded IPv4 (`64:ff9b::/96`, `64:ff9b:1::/48`), site-local, and IPv6 tunnel ranges.
   - Authenticated `GET /v1/media:proxy` enforces anti-SSRF IP pinning, per-IP rate limiting + concurrency semaphore, 15 MB stream cap, magic-byte & Pillow decompression-bomb validation (`<= 36 MP`), `X-Content-Type-Options: nosniff`, `Cross-Origin-Resource-Policy: cross-origin`, `Cache-Control: private, max-age=600, no-transform`, and sandboxed CSP. Client-side remote image loading never leaks URLs containing signed/auth query parameters to third-party CORS proxies.
   - Zero `.innerHTML` sinks in `web/src/`; translated site HTML sanitizers strip executable tags, `meta[http-equiv="set-cookie"]`, non-stylesheet `<link>` tags, `formaction`, `xlink:href`, and unsafe CSS directives on both client and backend.
   - Magic-byte file validation (`%PDF-`, `PK\x03\x04`), exact on-disk local-header Fifield overlapping-entry ZIP bomb guard, and streaming `O(64 KB)` `expat` DOCTYPE/XXE scanning across `.xml`/`.rels`/`.opf`/`.xhtml`/`.ncx`/`.html`/`.htm`/`.svg` on both upload and `/v1/translate:resume` (50 MB storage cap, 32 MB single XML cap).
   - Complete shared-device local & in-memory cache wipe (`clearLocalUserCaches` + `clearPerfCacheDb` + translation/discourse memory hooks) on sign-out or account switch, plus PII-free `ErrorBoundary` local recovery.
   - Sliding-window per-route rate limiting (`120 req/min` standard, `15 req/min` auth routes, `30 req/min` media proxy) and single-probe half-open endpoint circuit breakers.

## Reporting a Vulnerability

If you discover a security vulnerability in this repository:

1. **Do not** open a public GitHub issue containing exploit details or sensitive payloads.
2. Report it privately using GitHub Security Advisories (**Security -> Advisories -> Report a vulnerability**) or contact the maintainer directly.
3. Include clear reproduction steps, affected files or endpoints, and potential impact. Valid reports will be acknowledged and remediated promptly.
