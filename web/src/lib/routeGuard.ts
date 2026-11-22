/**
 * Canonical route validator for tranX.
 * Rejects repeated slashes, dot segments, encoded traversal, dotfiles, and irrelevant paths
 * so malformed URLs (e.g. "///", "/...", "/.env", "/laravel", "/foo.bar") render a clean 404
 * instead of silently opening the main translator application.
 */

import { toSafeHttpUrl } from './langUtils';

const SAFE_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;

// Static exact routes (strictly no trailing slash except root "/")
const EXACT_VALID_ROUTES = new Set([
  '/',
  '/masuk',
  '/masuk/kode',
  '/berkas',
  '/kamus',
  '/web',
  '/share',
  '/open',
]);

// Suspicious patterns that must NEVER resolve to the main app
const ENCODED_TRAVERSAL_RE = /%(?:25)?(?:2e|2f|5c|00)/i;
const MULTI_SLASH_RE = /\/{2,}/;
const BACKSLASH_RE = /\\/;
const CTRL_CHAR_RE = /[\x00-\x1f\x7f]/;
const SELF_HOST_RE = /^(?:tranx-hanif-id\.web\.app|tranx-hanif-id\.firebaseapp\.com)$/i;

export interface RouteValidationResult {
  valid: boolean;
  canonicalKind:
    | 'home'
    | 'login'
    | 'pair'
    | 'files'
    | 'glossary'
    | 'conversation'
    | 'reader'
    | 'web'
    | 'share'
    | 'open'
    | 'redirect'
    | 'not_found';
  reason?: string;
}

/**
 * Validates raw browser pathname (before any router normalization) against the strict tranX route table.
 */
export function validateAppRoute(rawPathname: string): RouteValidationResult {
  const path = typeof rawPathname === 'string' ? rawPathname : '';
  if (!path || !path.startsWith('/')) {
    return { valid: false, canonicalKind: 'not_found', reason: 'missing_leading_slash' };
  }
  if (
    path.length > 2048 ||
    BACKSLASH_RE.test(path) ||
    CTRL_CHAR_RE.test(path) ||
    /%00|%25(?:2e|2f|5c|00)/i.test(path)
  ) {
    return { valid: false, canonicalKind: 'not_found', reason: 'unsafe_encoding_or_length' };
  }

  // Handle intentional instant URL shortcut "/r/<public-http-url>" separately
  // because valid URLs contain "https://" (or percent-encoded "https%3A%2F%2F...") after "/r/".
  if (path.startsWith('/r/')) {
    const rawTail = path.slice(3);
    if (!rawTail || rawTail.startsWith('/') || rawTail.startsWith('.') || rawTail.includes('..')) {
      return { valid: false, canonicalKind: 'not_found', reason: 'invalid_redirect_tail' };
    }
    let decodedTail = rawTail;
    try {
      decodedTail = decodeURIComponent(rawTail);
    } catch {
      return { valid: false, canonicalKind: 'not_found', reason: 'malformed_uri_component' };
    }
    if (
      !decodedTail ||
      decodedTail.includes('..') ||
      BACKSLASH_RE.test(decodedTail) ||
      CTRL_CHAR_RE.test(decodedTail) ||
      /[\s<>'"`]/.test(decodedTail)
    ) {
      return { valid: false, canonicalKind: 'not_found', reason: 'invalid_redirect_chars' };
    }
    const safeUrl = toSafeHttpUrl(decodedTail);
    if (!safeUrl) {
      return { valid: false, canonicalKind: 'not_found', reason: 'unsafe_redirect_target' };
    }
    try {
      const parsed = new URL(safeUrl);
      // Must be a real dotted public domain (e.g. kakuyomu.jp), never single-word noise like "/r/laravel" or self-loop
      if (
        !parsed.hostname.includes('.') ||
        parsed.hostname.startsWith('.') ||
        parsed.hostname.endsWith('.') ||
        SELF_HOST_RE.test(parsed.hostname)
      ) {
        return { valid: false, canonicalKind: 'not_found', reason: 'non_domain_redirect_host' };
      }
      return { valid: true, canonicalKind: 'redirect' };
    } catch {
      return { valid: false, canonicalKind: 'not_found', reason: 'unparseable_redirect_url' };
    }
  }

  // Reject encoded traversal/slashes/dots on all standard app routes
  if (ENCODED_TRAVERSAL_RE.test(path)) {
    return { valid: false, canonicalKind: 'not_found', reason: 'unsafe_encoding_or_length' };
  }

  // Reject any repeated slashes ("//", "///", "/web//"), dot segments ("/.", "/.."), or dot-bearing paths ("/...", "/.env", "/a.b")
  if (MULTI_SLASH_RE.test(path)) {
    return { valid: false, canonicalKind: 'not_found', reason: 'repeated_slash' };
  }
  if (path.length > 1 && path.endsWith('/')) {
    return { valid: false, canonicalKind: 'not_found', reason: 'trailing_slash' };
  }
  if (path.includes('.')) {
    return { valid: false, canonicalKind: 'not_found', reason: 'dot_in_app_route' };
  }

  if (EXACT_VALID_ROUTES.has(path)) {
    switch (path) {
      case '/':
        return { valid: true, canonicalKind: 'home' };
      case '/masuk':
        return { valid: true, canonicalKind: 'login' };
      case '/masuk/kode':
        return { valid: true, canonicalKind: 'pair' };
      case '/berkas':
        return { valid: true, canonicalKind: 'files' };
      case '/kamus':
        return { valid: true, canonicalKind: 'glossary' };
      case '/web':
        return { valid: true, canonicalKind: 'web' };
      case '/share':
        return { valid: true, canonicalKind: 'share' };
      case '/open':
        return { valid: true, canonicalKind: 'open' };
    }
  }

  const segments = path.slice(1).split('/');
  if (segments.some((seg) => !seg)) {
    return { valid: false, canonicalKind: 'not_found', reason: 'empty_segment' };
  }

  // /kamus/:titleId
  if (segments.length === 2 && segments[0] === 'kamus' && SAFE_ID_RE.test(segments[1])) {
    return { valid: true, canonicalKind: 'glossary' };
  }

  // /c/:cid
  if (segments.length === 2 && segments[0] === 'c' && SAFE_ID_RE.test(segments[1])) {
    return { valid: true, canonicalKind: 'conversation' };
  }

  // /c/:cid/m/:mid/baca
  if (
    segments.length === 5 &&
    segments[0] === 'c' &&
    SAFE_ID_RE.test(segments[1]) &&
    segments[2] === 'm' &&
    SAFE_ID_RE.test(segments[3]) &&
    segments[4] === 'baca'
  ) {
    return { valid: true, canonicalKind: 'reader' };
  }

  return { valid: false, canonicalKind: 'not_found', reason: 'unknown_route' };
}

export function isValidAppRoute(rawPathname: string): boolean {
  return validateAppRoute(rawPathname).valid;
}
