# Security Policy

## Security Architecture

`tranX` is designed as a single-owner personal translation platform with defense-in-depth controls across client, hosting, and backend layers:

1. **Single-Owner Authorization**:
   - Cloud Firestore (`firestore.rules`) and Cloud Storage (`storage.rules`) enforce strict single-owner access and explicit schema validation.
   - Secondary devices are paired only via short-lived one-time 6-digit pairing codes (`/v1/auth:pairCode`).
2. **Secret Isolation**:
   - No API keys, OAuth tokens, private keys, or service account files are committed to this repository.
   - Optional user-supplied Gemini API keys are stored only in the owner's protected Firestore `/settings/secrets` document and never persisted in `localStorage`.
   - Automated CI (`security-and-hygiene` job in `.github/workflows/ci.yml`) and `tools/verify_integrity.py` continuously scan tracked files for secret patterns and local filesystem paths.
3. **Browser & HTTP Transport Hardening (`firebase.json`)**:
   - Strict `Content-Security-Policy` (no `'unsafe-inline'` scripts, explicit `connect-src` allowlist, `object-src 'none'`, `frame-ancestors 'none'`).
   - `Strict-Transport-Security` (`max-age=63072000; includeSubDomains; preload`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin-allow-popups`, `Cross-Origin-Resource-Policy: same-origin`, and strict `Referrer-Policy` / `Permissions-Policy`.
4. **Input, Fetch & Document Safety**:
   - SSRF private-IP / metadata-host blocking and URL scheme allowlisting (`http:` / `https:` only; zero `javascript:` URIs).
   - Magic-byte file validation and ZIP bomb / decompression guards for uploaded `.docx`, `.epub`, and `.pdf` documents (50 MB storage cap).
   - Sliding-window per-route rate limiting (`120 req/min` standard, `15 req/min` heavy web/document routes) and endpoint circuit breakers.

## Reporting a Vulnerability

If you discover a security vulnerability in this repository:

1. **Do not** open a public GitHub issue containing exploit details or sensitive payloads.
2. Report it privately using GitHub Security Advisories (**Security -> Advisories -> Report a vulnerability**) or contact the maintainer directly.
3. Include clear reproduction steps, affected files or endpoints, and potential impact. Valid reports will be acknowledged and remediated promptly.
