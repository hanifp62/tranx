# Security Policy

## Security Architecture

`tranX` is designed as a single-owner personal translation platform with defense-in-depth controls across client, hosting, and backend layers:

1. **Single-Owner Authorization**:
   - Cloud Firestore (`firestore.rules`) and Cloud Storage (`storage.rules`) enforce strict single-owner access and explicit schema validation.
   - Secondary devices are paired only via short-lived one-time 6-digit pairing codes (`/v1/auth:pairCode`), protected by rightmost `X-Forwarded-For` anti-spoofing, a global `/v1/auth:pair` rate limit across all IPs, and automatic code invalidation after 5 failed attempts.
   - Production Cloud Functions (`K_SERVICE` set) restrict CORS exclusively to production origins (never reflecting `localhost` origins).
2. **Secret Isolation & Runtime Firebase Config**:
   - No API keys, OAuth tokens, private keys, or service account files are committed to this repository or baked into production `web/dist/assets/*.js` bundles.
   - On Firebase Hosting, the frontend fetches Firebase Web SDK client configuration dynamically at runtime from the reserved same-origin endpoint `/__/firebase/init.json` (`cache: 'no-store'`), excluded from service worker SPA navigation fallback.
   - Because Firebase Web SDK client identifiers are public by design once delivered to a browser, actual protection is enforced server-side via Firestore/Storage Security Rules, disabled Anonymous and Email/Password auth providers, and Google Cloud Console API Key HTTP Referrer + API restrictions.
   - Optional user-supplied Gemini API keys are stored only in the owner's protected Firestore `/settings/secrets` document and never persisted in `localStorage`.
   - Automated CI (`web-build-and-pwa` and `security-and-hygiene` jobs in `.github/workflows/ci.yml`) and `tools/verify_integrity.py` continuously verify zero leaked secrets in tracked files and zero baked keys or sourcemaps in production bundles.
3. **Browser & HTTP Transport Hardening (`firebase.json`)**:
   - Strict `Content-Security-Policy` (no `'unsafe-inline'` scripts, `script-src` jsDelivr scoped to `https://cdn.jsdelivr.net/npm/`, HTTPS-only `img-src`, `upgrade-insecure-requests`, explicit `connect-src` allowlist, `object-src 'none'`, `frame-ancestors 'none'`).
   - `Strict-Transport-Security` (`max-age=63072000; includeSubDomains; preload`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-Permitted-Cross-Domain-Policies: none`, `Cross-Origin-Opener-Policy: same-origin-allow-popups`, `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-cache` on HTML entrypoints (`/`, `/web`, `/index.html`), and strict `Referrer-Policy` / `Permissions-Policy`.
4. **Input, Fetch, Sanitizer & Document Safety**:
   - SSRF private-IP / metadata-host blocking and URL scheme allowlisting (`http:` / `https:` only; zero `javascript:` URIs).
   - Zero `.innerHTML` sinks in `web/src/`; translated site HTML sanitizers strip executable tags, `meta[http-equiv="set-cookie"]`, non-stylesheet `<link>` tags, `formaction`, `xlink:href`, and unsafe CSS directives on both client and backend.
   - Magic-byte file validation and ZIP bomb / decompression guards for uploaded `.docx`, `.epub`, and `.pdf` documents (50 MB storage cap).
   - Sliding-window per-route rate limiting (`120 req/min` standard, `15 req/min` auth routes) and endpoint circuit breakers.

## Reporting a Vulnerability

If you discover a security vulnerability in this repository:

1. **Do not** open a public GitHub issue containing exploit details or sensitive payloads.
2. Report it privately using GitHub Security Advisories (**Security -> Advisories -> Report a vulnerability**) or contact the maintainer directly.
3. Include clear reproduction steps, affected files or endpoints, and potential impact. Valid reports will be acknowledged and remediated promptly.
