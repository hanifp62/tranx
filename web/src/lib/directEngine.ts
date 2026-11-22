import type {
  ComicLayoutMode,
  GlossaryEntry,
  ImageTranslationResult,
  LinkPreviewPayload,
  MangaLinkMeta,
  ModePair,
  NameChipItem,
  NovelChapterLink,
  NovelNavigation,
  SentencePair,
  SourceLang,
  TargetLang,
  TitleKind,
  VisionBgTone,
  VisionBlock,
  VisionBlockKind,
  VisionBlockShape,
  WebReaderBundle,
} from '../types';
import {
  MAX_MANGA_STRIP_HEIGHT,
  MAX_MANGA_STRIP_PIXELS,
  clusterOcrBoxes,
  dedupeAndStitchTileBlocks,
  extractMangaPagesFromHtml,
  isLikelyDirectImageUrl,
  normalizeComicAllCaps,
  normalizeSocialImageUrl,
  planVerticalStripTiles,
  sortMangaReadingOrder,
  type RawOcrBox,
} from './mangaScanner';
import {
  getOwnerGeminiKey,
  loadGlossaryEntriesOnce,
  saveDirectJobRecord,
  saveTurnMessageDirect,
  upsertConversationMeta,
} from './firebase';
import {
  getStorageHealthSnapshot,
  idbDelete,
  idbGet,
  idbLoadRecent,
  idbPut,
  idbPutMany,
} from './perfCache';
import {
  buildLiterarySystemPrompt,
  buildSelfRepairPrompt,
  evaluateSourceTargetQe,
  naturalizeAndVerifyParagraph,
  preprocessSourceForMt,
  profileDocument,
  restorePreMtTokens,
  sanitizeZeroEmDashAndPunct,
  saveSeriesDiscourseMemory,
  type DiscourseProfile,
} from './literaryPolish';
import {
  AdaptiveTokenBucket,
  BoundedLruCache,
  EndpointCircuitBreaker,
  computeBackoffDelayMs,
  getDeviceRuntimeProfile,
  shouldShedBackgroundLoad,
  yieldToMain,
} from './resilience';

// Adaptive client-side rate limiters & named circuit breakers calibrated for 5-10 concurrent users
const gtxBucket = new AdaptiveTokenBucket(6, 3.5, 1.0);
const geminiBucket = new AdaptiveTokenBucket(4, 1.8, 0.5);
const jinaBucket = new AdaptiveTokenBucket(3, 1.4, 0.4);
const gtxPrimaryBreaker = new EndpointCircuitBreaker(3, 18_000, 'gtx_primary');
const gtxAltBreaker = new EndpointCircuitBreaker(3, 20_000, 'gtx_alt');
const geminiBreaker = new EndpointCircuitBreaker(2, 30_000, 'gemini_api');
const proxyBreakers = new Map<string, EndpointCircuitBreaker>();

function getProxyBreaker(hostKey: string): EndpointCircuitBreaker {
  let b = proxyBreakers.get(hostKey);
  if (!b) {
    b = new EndpointCircuitBreaker(2, 120_000, `proxy:${hostKey}`);
    proxyBreakers.set(hostKey, b);
  }
  return b;
}

function isMockOnlyLocalE2E(): boolean {
  if (typeof window === 'undefined') return false;
  const host = window.location.hostname;
  if (host !== 'localhost' && host !== '127.0.0.1') return false;
  try {
    const qs = new URLSearchParams(window.location.search);
    const isE2e = qs.get('e2e') === '1' || window.sessionStorage?.getItem('tranx_e2e') === '1';
    const isDirect =
      qs.get('direct') === '1' || window.sessionStorage?.getItem('tranx_e2e_direct') === '1';
    return isE2e && !isDirect;
  } catch {
    return false;
  }
}

import {
  CJK_RE,
  CJK_SPAN_RE,
  buildModePair,
  classifyParagraphLanguage,
  deriveSeriesTitleId,
  detectLanguageLocal,
  inspectBinaryMagicBytes,
  isSingleStandaloneUrl,
  normalizeWebUrl,
  parseModePair,
  scoreLatinWords,
  swapModePair,
  toSafeHttpUrl,
  validateUploadedFileMagic,
  type ParagraphLangClass,
} from './langUtils';

export {
  buildModePair,
  classifyParagraphLanguage,
  deriveSeriesTitleId,
  detectLanguageLocal,
  inspectBinaryMagicBytes,
  isSingleStandaloneUrl,
  normalizeWebUrl,
  parseModePair,
  swapModePair,
  toSafeHttpUrl,
  validateUploadedFileMagic,
  type ParagraphLangClass,
};

function extractGeminiResponseText(raw: unknown, fallback = '{}'): string {
  const parts = (raw as { candidates?: Array<{ content?: { parts?: Array<{ text?: string; thought?: boolean }> } }> })
    ?.candidates?.[0]?.content?.parts;
  if (!Array.isArray(parts)) return fallback;
  const chosen = parts.find((p) => !p?.thought && typeof p?.text === 'string' && p.text.trim());
  return chosen?.text ? String(chosen.text).trim() : fallback;
}

function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  return new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      globalThis.clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

function isStillUntranslatedForTarget(srcText: string, outText: string, tgt: TargetLang): boolean {
  const cleanSrc = (srcText || '').trim();
  const cleanOut = (outText || '').trim();
  if (!cleanSrc) return false;
  if (!cleanOut) return true;
  if (tgt !== 'ja' && CJK_RE.test(cleanSrc)) {
    const cjkChars = cleanOut.match(/[\u3040-\u309f\u30a0-\u30ff\u3400-\u9fff]/g) || [];
    if (cjkChars.length >= 2) return true;
    if (cjkChars.length >= 1 && cleanOut === cleanSrc) return true;
  }
  if (tgt === 'ja' && !CJK_RE.test(cleanSrc)) {
    const latinWords = (cleanSrc.match(/[A-Za-zÀ-ÿ]{3,}/g) || []).length;
    if (latinWords >= 2 && cleanOut === cleanSrc && !CJK_RE.test(cleanOut)) return true;
  }
  return false;
}

function buildGlossaryPairs(
  entries: GlossaryEntry[],
  srcLang: TargetLang,
  tgtLang: TargetLang
): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  for (const e of entries) {
    const idForm = e.render_id || e.romaji || e.surface;
    const enForm = e.render_en || e.romaji || e.surface;
    const jaForm = e.surface;

    const srcCandidates =
      srcLang === 'ja'
        ? [e.surface, ...e.aliases]
        : srcLang === 'id'
          ? [idForm, e.romaji, ...e.aliases]
          : [enForm, e.romaji, ...e.aliases];
    const tgtForm = tgtLang === 'ja' ? jaForm : tgtLang === 'id' ? idForm : enForm;

    for (const cand of srcCandidates) {
      const clean = (cand || '').trim();
      if (clean.length >= 2 && tgtForm.trim()) {
        pairs.push([clean, tgtForm.trim()]);
      }
    }
  }
  pairs.sort((a, b) => b[0].length - a[0].length);
  return pairs;
}

function maskWithGlossary(
  text: string,
  pairs: Array<[string, string]>
): { masked: string; map: Map<string, string>; matchedChips: NameChipItem[]; entriesRef?: GlossaryEntry[] } {
  let masked = text;
  const map = new Map<string, string>();
  let idx = 1;
  for (const [srcTerm, tgtTerm] of pairs) {
    if (!masked.includes(srcTerm)) continue;
    const isAsciiLatin = /^[A-Za-z0-9][A-Za-z0-9\s'-]*$/.test(srcTerm);
    if (isAsciiLatin) {
      const esc = srcTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const re = new RegExp(`(?<![A-Za-z0-9_])${esc}(?![A-Za-z0-9_])`, 'g');
      if (re.test(masked)) {
        const tok = `[[E${idx}]]`;
        masked = masked.replace(re, tok);
        map.set(tok, tgtTerm);
        idx += 1;
      }
    } else {
      const tok = `[[E${idx}]]`;
      masked = masked.split(srcTerm).join(tok);
      map.set(tok, tgtTerm);
      idx += 1;
    }
  }
  return { masked, map, matchedChips: [] };
}

function unmaskWithGlossary(text: string, map: Map<string, string>): string {
  let out = text;
  for (const [tok, val] of map.entries()) {
    out = out.split(tok).join(val);
    const num = tok.slice(3, -2);
    out = out.replace(new RegExp(`(?:\\[\\[|【【)\\s*E\\s*${num}\\s*(?:\\]\\]|】】)`, 'gi'), val);
  }
  return out;
}

/** Cleans machine-translation punctuation & spacing artifacts for crisp literary readability (strictly 0 U+2014). */
export function polishTranslatedProse(text: string, tgt: TargetLang): string {
  return sanitizeZeroEmDashAndPunct(text, tgt);
}

/** Runs async worker tasks with bounded concurrency while preserving output order. */
async function runConcurrentPool<T>(
  items: T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<void>
): Promise<void> {
  if (items.length === 0) return;
  const limit = Math.max(1, Math.min(concurrency, items.length));
  let nextIdx = 0;
  const runners = Array.from({ length: limit }, async () => {
    while (true) {
      const idx = nextIdx;
      nextIdx += 1;
      if (idx >= items.length) break;
      await worker(items[idx], idx);
    }
  });
  await Promise.all(runners);
}

const MAX_PARA_CACHE_MEM = 2400;
const paraTranslationCache = new Map<string, string>();
const pendingIdbParaWrites = new Map<string, string>();
let paraCacheHydrated = false;
let paraCacheFlushTimer: number | null = null;

export function clearInMemoryTranslationCaches(): void {
  paraTranslationCache.clear();
  pendingIdbParaWrites.clear();
  paraCacheHydrated = false;
  webArticleCache.clear();
  translatedWebCache.clear();
  translatedSiteHtmlCache.clear();
  seriesTocCache.clear();
  translatedChapterTitlesCache.clear();
  scannedMangaPageCache.clear();
  directExportCache.clear();
  terminateAllWarmTesseractWorkers();
  if (paraCacheFlushTimer !== null) {
    globalThis.clearTimeout(paraCacheFlushTimer);
    paraCacheFlushTimer = null;
  }
}

registerLocalCacheResetHook(clearInMemoryTranslationCaches);
registerLocalCacheResetHook(clearSeriesDiscourseMemory);

function hydrateParaCacheOnce(): void {
  if (paraCacheHydrated || typeof window === 'undefined') return;
  paraCacheHydrated = true;
  // Defer bounded IndexedDB warm hydration (500 most recent paragraphs) to idle callback
  const hydrateFromIdb = () => {
    void idbLoadRecent<string>('paras', 500).then((rows) => {
      for (const [k, v] of rows) {
        if (!paraTranslationCache.has(k) && typeof v === 'string') {
          paraTranslationCache.set(k, v);
        }
      }
    });
  };
  const winWithIdle = window as Window & {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
  };
  if (typeof winWithIdle.requestIdleCallback === 'function') {
    winWithIdle.requestIdleCallback(hydrateFromIdb, { timeout: 1500 });
  } else {
    globalThis.setTimeout(hydrateFromIdb, 350);
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      scannedMangaPageCache.trimToRatio(0.5);
      terminateAllWarmTesseractWorkers();
      if (paraTranslationCache.size > Math.floor(MAX_PARA_CACHE_MEM * 0.5)) {
        const target = Math.floor(MAX_PARA_CACHE_MEM * 0.5);
        while (paraTranslationCache.size > target) {
          const oldest = paraTranslationCache.keys().next().value;
          if (oldest === undefined) break;
          paraTranslationCache.delete(oldest);
        }
      }
    }
  });
}
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => {
    terminateAllWarmTesseractWorkers();
  });
}

function scheduleParaCacheFlush(): void {
  if (typeof window === 'undefined' || paraCacheFlushTimer !== null) return;
  paraCacheFlushTimer = window.setTimeout(() => {
    paraCacheFlushTimer = null;
    if (pendingIdbParaWrites.size > 0) {
      const batch = Array.from(pendingIdbParaWrites.entries());
      pendingIdbParaWrites.clear();
      void idbPutMany('paras', batch);
    }
  }, 1200);
}

function makeParaCacheKey(
  src: SourceLang,
  tgt: TargetLang,
  glossarySig: string,
  text: string
): string {
  return `${src}>${tgt}|${glossarySig}|${text}`;
}

function getCachedParaTranslation(key: string): string | undefined {
  hydrateParaCacheOnce();
  const hit = paraTranslationCache.get(key);
  if (hit !== undefined) {
    // LRU touch
    paraTranslationCache.delete(key);
    paraTranslationCache.set(key, hit);
  }
  return hit;
}

function setCachedParaTranslation(key: string, translated: string): void {
  if (!translated || key.length > 2400) return;
  hydrateParaCacheOnce();
  paraTranslationCache.delete(key);
  paraTranslationCache.set(key, translated);
  pendingIdbParaWrites.set(key, translated);
  if (paraTranslationCache.size > MAX_PARA_CACHE_MEM) {
    const oldestKey = paraTranslationCache.keys().next().value;
    if (oldestKey !== undefined) paraTranslationCache.delete(oldestKey);
  }
  scheduleParaCacheFlush();
}

// L2 cache hydration runs lazily on first translation lookup (0ms module-load side effect)

function hasTranslatableLetters(text: string): boolean {
  return /[\p{L}\p{N}\u3040-\u30ff\u3400-\u9fff]/u.test(text);
}

function cleanCjkSpacing(raw: string): string {
  return raw.replace(
    /([\u3000-\u30ff\u3400-\u9fff\uff00-\uffef])\s+(?=[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef])/g,
    '$1'
  );
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  outerSignal?: AbortSignal
): Promise<Response> {
  const ctrl = new AbortController();
  const onOuterAbort = () => ctrl.abort();
  if (outerSignal) {
    if (outerSignal.aborted) {
      ctrl.abort();
    } else {
      outerSignal.addEventListener('abort', onOuterAbort, { once: true });
    }
  }
  const timer = globalThis.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    globalThis.clearTimeout(timer);
    if (outerSignal) outerSignal.removeEventListener('abort', onOuterAbort);
  }
}

async function requestGtxSingleChunk(
  chunk: string,
  src: SourceLang,
  tgt: TargetLang,
  signal?: AbortSignal
): Promise<{ translated: string; detected?: TargetLang }> {
  const clean = chunk.trim();
  if (!clean || !hasTranslatableLetters(clean)) {
    return { translated: chunk };
  }

  const queryMeta = new URLSearchParams({
    client: 'gtx',
    sl: src,
    tl: tgt,
    dt: 't',
  });
  const bodyForm = new URLSearchParams({ q: clean });

  // Primary endpoint: translate.googleapis.com with token bucket, 429/5xx jitter retry, & circuit breaker
  if (!gtxPrimaryBreaker.isOpen()) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await gtxBucket.acquire(signal);
      try {
        const resp = await fetchWithTimeout(
          `https://translate.googleapis.com/translate_a/single?${queryMeta.toString()}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
            body: bodyForm.toString(),
          },
          9500,
          signal
        );
        if (resp.ok) {
          const data = await resp.json();
          const pieces: string[] = Array.isArray(data?.[0])
            ? data[0]
              .map((seg: unknown) =>
                Array.isArray(seg) && typeof seg[0] === 'string' ? seg[0] : ''
              )
              .filter(Boolean)
            : [];
          const serverSrc = String(data?.[2] || '').toLowerCase();
          const detected =
            serverSrc === 'ja' || serverSrc === 'id' || serverSrc === 'en'
              ? (serverSrc as TargetLang)
              : undefined;
          gtxBucket.onSuccess();
          gtxPrimaryBreaker.recordSuccess();
          return { translated: pieces.join(''), detected };
        }
        if (resp.status === 429 || resp.status >= 500) {
          const delayMs = computeBackoffDelayMs(attempt, resp.headers.get('Retry-After'), 400, 4000);
          gtxBucket.onThrottle(delayMs);
          if (resp.status === 429) {
            gtxPrimaryBreaker.recordFailure(Math.max(delayMs, 10_000));
            break; // Immediately fail over to healthy clients5 edge!
          }
          if (attempt === 0) {
            await abortableDelay(delayMs, signal);
            continue;
          }
        }
        gtxPrimaryBreaker.recordFailure();
        break;
      } catch (err) {
        if (signal?.aborted) throw err;
        gtxPrimaryBreaker.recordFailure();
        break;
      }
    }
  }

  // Fallback 1: Alternate fast Google Translate edge (clients5.google.com, already whitelisted in CSP)
  if (!gtxAltBreaker.isOpen()) {
    await gtxBucket.acquire(signal);
    try {
      const altMeta = new URLSearchParams({
        client: 'dict-chrome-ex',
        sl: src,
        tl: tgt,
      });
      const respAlt = await fetchWithTimeout(
        `https://clients5.google.com/translate_a/t?${altMeta.toString()}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
          body: bodyForm.toString(),
        },
        7500,
        signal
      );
      if (respAlt.ok) {
        const altData = await respAlt.json();
        if (Array.isArray(altData)) {
          const first = altData[0];
          if (typeof first === 'string' && first.trim()) {
            gtxBucket.onSuccess();
            gtxAltBreaker.recordSuccess();
            return { translated: first };
          }
          if (Array.isArray(first) && typeof first[0] === 'string' && first[0].trim()) {
            const detRaw = String(first[1] || '').toLowerCase();
            const detected =
              detRaw === 'ja' || detRaw === 'id' || detRaw === 'en'
                ? (detRaw as TargetLang)
                : undefined;
            gtxBucket.onSuccess();
            gtxAltBreaker.recordSuccess();
            return { translated: first[0], detected };
          }
        }
      } else if (respAlt.status === 429 || respAlt.status >= 500) {
        const delayMs = computeBackoffDelayMs(0, respAlt.headers.get('Retry-After'), 500, 6000);
        gtxBucket.onThrottle(delayMs);
        gtxAltBreaker.recordFailure(Math.max(delayMs, 12_000));
      } else {
        gtxAltBreaker.recordFailure();
      }
    } catch (err) {
      if (signal?.aborted) throw err;
      gtxAltBreaker.recordFailure();
    }
  }

  // Fallback 2: GET for short payloads
  if (clean.length <= 450 && !gtxPrimaryBreaker.isOpen()) {
    try {
      const qs = new URLSearchParams({
        client: 'gtx',
        sl: src,
        tl: tgt,
        dt: 't',
        q: clean,
      });
      const respGet = await fetchWithTimeout(
        `https://translate.googleapis.com/translate_a/single?${qs.toString()}`,
        { method: 'GET' },
        7500,
        signal
      );
      if (respGet.ok) {
        const data = await respGet.json();
        const pieces: string[] = Array.isArray(data?.[0])
          ? data[0]
            .map((seg: unknown) =>
              Array.isArray(seg) && typeof seg[0] === 'string' ? seg[0] : ''
            )
            .filter(Boolean)
          : [];
        return { translated: pieces.join('') };
      }
    } catch (err) {
      if (signal?.aborted) throw err;
    }
  }

  // Fallback 3: MyMemory public translation API for short chunks
  if (clean.length <= 480) {
    try {
      const effSrc = src === 'auto' ? detectLanguageLocal(clean, tgt === 'ja' ? 'id' : 'ja') : src;
      const mmQs = new URLSearchParams({
        q: clean,
        langpair: `${effSrc}|${tgt}`,
      });
      const mmResp = await fetchWithTimeout(
        `https://api.mymemory.translated.net/get?${mmQs.toString()}`,
        { method: 'GET' },
        7500,
        signal
      );
      if (mmResp.ok) {
        const mmData = await mmResp.json();
        const mmText = String(mmData?.responseData?.translatedText || '').trim();
        if (mmText) return { translated: mmText, detected: effSrc };
      }
    } catch (err) {
      if (signal?.aborted) throw err;
    }
  }

  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    throw new Error('Perangkat sedang offline. Periksa koneksi internet Anda lalu coba lagi.');
  }
  throw new Error('Layanan terjemahan sedang sibuk. Silakan coba sesaat lagi.');
}

async function translateBatchViaGoogleGtx(
  paragraphs: string[],
  src: SourceLang,
  tgt: TargetLang,
  signal?: AbortSignal,
  onSlotTranslated?: (slotIdx: number, translated: string) => void
): Promise<{ outputs: string[]; detected: TargetLang }> {
  const outputs = new Array<string>(paragraphs.length).fill('');
  let detected: TargetLang =
    src === 'auto'
      ? detectLanguageLocal(paragraphs.slice(0, 6).join('\n'), tgt === 'ja' ? 'id' : 'ja')
      : src;

  // Deduplicate identical lines within the same batch so repeated lines only translate once
  const uniqueMap = new Map<string, number[]>();
  const work: Array<{ text: string; slots: number[] }> = [];
  paragraphs.forEach((p, idx) => {
    const trimmed = p.trim();
    if (!trimmed || !hasTranslatableLetters(trimmed)) {
      outputs[idx] = p;
      onSlotTranslated?.(idx, p);
      return;
    }
    const existing = uniqueMap.get(trimmed);
    if (existing) {
      existing.push(idx);
    } else {
      const slots = [idx];
      uniqueMap.set(trimmed, slots);
      work.push({ text: trimmed, slots });
    }
  });

  const assignSlots = (slots: number[], translated: string) => {
    for (const s of slots) {
      outputs[s] = translated;
      onSlotTranslated?.(s, translated);
    }
  };

  // Pack dense, truncation-safe request batches (65% fewer upstream HTTP calls -> safe for 5-10 concurrent users!):
  // Batch 0 is a priority micro-batch (<= 8 items, <= 900 chars) for ~250ms Time-To-First-Paragraph,
  // followed by dense batches (<= 18 items, <= 2,000 chars) that never exceed GTX/clients5 POST truncation limits!
  const profile = getDeviceRuntimeProfile();
  const batches: Array<Array<{ text: string; slots: number[] }>> = [];
  let cursor = 0;
  while (cursor < work.length) {
    const isFirstFastBatch = batches.length === 0 && work.length > 8;
    const maxItems = isFirstFastBatch ? 8 : 18;
    const maxChars = isFirstFastBatch ? 900 : 2000;
    const batch: Array<{ text: string; slots: number[] }> = [];
    let charCount = 0;
    while (
      cursor < work.length &&
      batch.length < maxItems &&
      charCount + work[cursor].text.length <= maxChars
    ) {
      batch.push(work[cursor]);
      charCount += work[cursor].text.length + 12;
      cursor += 1;
      // Dialogue-preserving boundary split: once >= 72% full, prefer splitting after non-quote complete sentences
      if (
        !isFirstFastBatch &&
        batch.length >= 6 &&
        charCount >= maxChars * 0.72 &&
        cursor < work.length &&
        !/[「『"“]$/.test(batch[batch.length - 1].text) &&
        !/^[「『"“]/.test(work[cursor].text) &&
        /[。！？.!?]$/.test(batch[batch.length - 1].text)
      ) {
        break;
      }
    }
    if (batch.length === 0) {
      batch.push(work[cursor]);
      cursor += 1;
    }
    batches.push(batch);
  }

  // Tolerant marker splitter handles ASCII/fullwidth mutations GTX occasionally emits ([[#0]], [#0], 【#0】, [[＃0]])
  const MARKER_SPLIT_RE = /(?:\[\[|\[|【)\s*[#＃]\s*(\d+)\s*(?:\]\]|\]|】)/;
  const parseBatchMarkers = (raw: string, size: number): string[] => {
    const splitParts = raw.split(MARKER_SPLIT_RE);
    const parsed = new Array<string>(size).fill('');
    for (let p = 1; p + 1 < splitParts.length; p += 2) {
      const slot = Number(splitParts[p]);
      if (slot >= 0 && slot < size && !parsed[slot]) {
        parsed[slot] = splitParts[p + 1].trim();
      }
    }
    return parsed;
  };

  const retryItems: Array<{ text: string; slots: number[] }> = [];

  await runConcurrentPool(batches, profile.gtxConcurrency, async (batch) => {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

    if (batch.length === 1 && batch[0].text.length > 2000) {
      const parts = batch[0].text.split(/(?<=[。！？.!?\n])/);
      const subChunks: string[] = [];
      let acc = '';
      for (const part of parts) {
        if ((acc + part).length > 1500 && acc) {
          subChunks.push(acc);
          acc = part;
        } else {
          acc += part;
        }
      }
      if (acc) subChunks.push(acc);
      const translatedSubs = new Array<string>(subChunks.length).fill('');
      await runConcurrentPool(subChunks, Math.min(3, profile.gtxConcurrency), async (sc, scIdx) => {
        const r = await requestGtxSingleChunk(sc, src, tgt, signal);
        if (r.detected) detected = r.detected;
        translatedSubs[scIdx] = r.translated;
      });
      assignSlots(batch[0].slots, translatedSubs.join(' ').trim());
      return;
    }

    if (batch.length === 1) {
      try {
        const res = await requestGtxSingleChunk(batch[0].text, src, tgt, signal);
        if (res.detected) detected = res.detected;
        if (res.translated && !isStillUntranslatedForTarget(batch[0].text, res.translated, tgt)) {
          assignSlots(batch[0].slots, res.translated);
        } else {
          retryItems.push(batch[0]);
        }
      } catch (err) {
        if ((err as { name?: string })?.name === 'AbortError') throw err;
        if (work.length === 1) throw err;
        retryItems.push(batch[0]);
      }
      return;
    }

    const joined = batch.map((b, k) => `[[#${k}]] ${b.text}`).join('\n');
    try {
      const res = await requestGtxSingleChunk(joined, src, tgt, signal);
      if (res.detected) detected = res.detected;
      const batchOut = parseBatchMarkers(res.translated, batch.length);
      for (let bIdx = 0; bIdx < batch.length; bIdx += 1) {
        const candidate = batchOut[bIdx];
        if (candidate && !isStillUntranslatedForTarget(batch[bIdx].text, candidate, tgt)) {
          assignSlots(batch[bIdx].slots, candidate);
        } else {
          retryItems.push(batch[bIdx]);
        }
      }
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') throw err;
      for (const b of batch) {
        retryItems.push(b);
      }
    }
  });

  // Self-healing retry pass for any dropped/mangled/rate-limited slots: compact 5-item mini-batches then single fallback
  if (retryItems.length > 0 && !signal?.aborted) {
    const miniBatches: Array<Array<{ text: string; slots: number[] }>> = [];
    for (let i = 0; i < retryItems.length; i += 5) {
      miniBatches.push(retryItems.slice(i, i + 5));
    }
    let failedSingles = 0;
    let lastSingleErr: unknown = null;
    await runConcurrentPool(miniBatches, Math.min(2, profile.gtxConcurrency), async (mini) => {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const unresolved: Array<{ text: string; slots: number[] }> = [];
      if (mini.length > 1) {
        try {
          const joined = mini.map((b, k) => `[[#${k}]] ${b.text}`).join('\n');
          const res = await requestGtxSingleChunk(joined, src, tgt, signal);
          if (res.detected) detected = res.detected;
          const out = parseBatchMarkers(res.translated, mini.length);
          mini.forEach((item, idx) => {
            if (out[idx] && !isStillUntranslatedForTarget(item.text, out[idx], tgt)) {
              assignSlots(item.slots, out[idx]);
            } else {
              unresolved.push(item);
            }
          });
        } catch (err) {
          if ((err as { name?: string })?.name === 'AbortError') throw err;
          unresolved.push(...mini);
        }
      } else {
        unresolved.push(...mini);
      }
      for (const item of unresolved) {
        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
        try {
          const singleRes = await requestGtxSingleChunk(item.text, src, tgt, signal);
          if (singleRes.detected) detected = singleRes.detected;
          if (singleRes.translated) {
            assignSlots(item.slots, singleRes.translated);
          } else {
            failedSingles += 1;
            for (const s of item.slots) outputs[s] = item.text;
          }
        } catch (err) {
          if (signal?.aborted || (err as { name?: string })?.name === 'AbortError') {
            throw err;
          }
          failedSingles += 1;
          lastSingleErr = err;
          // Leave fallback text in outputs WITHOUT triggering cache callback
          for (const s of item.slots) outputs[s] = item.text;
        }
      }
    });
    // If EVERY single item in the entire job failed, surface real network/offline error instead of silently returning untranslated text
    if (failedSingles >= work.length && lastSingleErr) {
      throw lastSingleErr;
    }
  }

  return { outputs, detected };
}

async function translateViaGeminiDirect(
  paragraphs: string[],
  src: SourceLang,
  tgt: TargetLang,
  geminiKey: string,
  profile: DiscourseProfile,
  signal?: AbortSignal,
  onChunkDone?: (startOffset: number, chunkOutputs: string[]) => void
): Promise<string[]> {
  if (geminiBreaker.isOpen()) {
    throw new Error('Gemini cooldown active');
  }

  // Fast first chunk (16 items) for instant initial stream, followed by dense 55-item chunks (3x fewer RPM calls!)
  const runtimeProfile = getDeviceRuntimeProfile();
  const chunks: Array<{ start: number; slice: string[] }> = [];
  let pos = 0;
  while (pos < paragraphs.length) {
    const size = chunks.length === 0 && paragraphs.length > 18 ? 16 : 55;
    chunks.push({ start: pos, slice: paragraphs.slice(pos, pos + size) });
    pos += size;
  }

  const temp =
    profile.register === 'formal_legal_tech' || profile.register === 'formal_academic' ? 0.15 : 0.25;
  const allOut = new Array<string>(paragraphs.length);
  const poolCtrl = new AbortController();
  const onOuterAbort = () => poolCtrl.abort();
  if (signal?.aborted) {
    poolCtrl.abort();
  } else {
    signal?.addEventListener('abort', onOuterAbort, { once: true });
  }
  try {
    await runConcurrentPool(chunks, runtimeProfile.geminiConcurrency, async ({ start, slice }) => {
      if (poolCtrl.signal.aborted) {
        throw new DOMException('Aborted', 'AbortError');
      }
      await geminiBucket.acquire(poolCtrl.signal);
      const sysPrompt = buildLiterarySystemPrompt(src, tgt, profile, slice);
      const items = slice.map((text, idx) => ({ id: idx + 1, text }));

      // Sliding 2-paragraph lookback context (antar paragraf + antar bab!)
      const lookbackParts: string[] = [];
      if (start === 0 && profile.seriesClosingContext.length > 0) {
        for (const prevPair of profile.seriesClosingContext) {
          lookbackParts.push(`Prev chapter source: ${prevPair.src}\nPrev chapter translation: ${prevPair.dst}`);
        }
      } else if (start > 0) {
        const prevSlice = paragraphs.slice(Math.max(0, start - 2), start);
        prevSlice.forEach((p, idx) => {
          const translatedPrev = allOut[Math.max(0, start - 2) + idx];
          lookbackParts.push(
            translatedPrev
              ? `Prior paragraph: ${p.slice(0, 200)} => ${translatedPrev.slice(0, 200)}`
              : `Prior paragraph: ${p.slice(0, 200)}`
          );
        });
      }
      const contextHeader =
        lookbackParts.length > 0
          ? `Reference context (DO NOT translate, keep voice/pronouns consistent with this):\n${lookbackParts.join('\n')}\n\n`
          : '';

      const resp = await fetchWithTimeout(
        'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-goog-api-key': geminiKey,
          },
          body: JSON.stringify({
            systemInstruction: { parts: [{ text: sysPrompt }] },
            contents: [
              {
                role: 'user',
                parts: [{ text: `${contextHeader}Input:\n${JSON.stringify(items)}` }],
              },
            ],
            generationConfig: {
              responseMimeType: 'application/json',
              temperature: temp,
            },
          }),
        },
        18_000,
        poolCtrl.signal
      );
      if (!resp.ok) {
        if (resp.status === 429 || resp.status >= 500) {
          const retryMs = computeBackoffDelayMs(0, resp.headers.get('Retry-After'), 2000, 30_000);
          geminiBucket.onThrottle(retryMs);
          geminiBreaker.recordFailure(Math.max(retryMs, 25_000));
        } else {
          geminiBreaker.recordFailure();
        }
        poolCtrl.abort();
        throw new Error(`Gemini HTTP ${resp.status}`);
      }
      geminiBucket.onSuccess();
      geminiBreaker.recordSuccess();
      const raw = await resp.json();
      const rawTextPart = extractGeminiResponseText(raw, '{}');
      const textPart = rawTextPart.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '');
      const parsed = JSON.parse(textPart);
      const map = new Map<number, string>();
      for (const row of parsed.translations || []) {
        const txt = String(row?.text || '').trim();
        if (txt) map.set(Number(row.id), txt);
      }
      const missingCount = slice.reduce((acc, _orig, idx) => acc + (map.has(idx + 1) ? 0 : 1), 0);
      if (map.size === 0 || missingCount > Math.max(2, Math.floor(slice.length * 0.4))) {
        throw new Error('Respons JSON Gemini tidak lengkap; beralih ke mesin cadangan.');
      }
      const chunkOut = slice.map((orig, idx) => map.get(idx + 1) || orig);

      // v5 Reference-Free QE + Bounded Single-Pass MQM Self-Repair (Ki & Carpuat 2024, max 2 critical items/chunk)
      let repairsInChunk = 0;
      for (let idx = 0; idx < slice.length && repairsInChunk < 2; idx += 1) {
        const origLine = slice[idx];
        const draftLine = chunkOut[idx];
        const qe = evaluateSourceTargetQe({ srcText: origLine, tgtText: draftLine, profile });
        if (!qe.needsSelfRepair || geminiBreaker.isOpen() || poolCtrl.signal.aborted) continue;
        repairsInChunk += 1;
        try {
          const repairReq = buildSelfRepairPrompt({
            srcText: origLine,
            draftText: draftLine,
            qeReport: qe,
            profile,
          });
          await geminiBucket.acquire(poolCtrl.signal);
          const rResp = await fetchWithTimeout(
            'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent',
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'x-goog-api-key': geminiKey,
              },
              body: JSON.stringify({
                systemInstruction: { parts: [{ text: repairReq.systemPrompt }] },
                contents: [{ role: 'user', parts: [{ text: repairReq.userPrompt }] }],
                generationConfig: { responseMimeType: 'application/json', temperature: 0.1 },
              }),
            },
            12_000,
            poolCtrl.signal
          );
          if (rResp.ok) {
            const rJson = await rResp.json();
            const rRawPart = extractGeminiResponseText(rJson, '{}');
            const rTextPart = rRawPart.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '');
            const repaired = String(JSON.parse(rTextPart)?.text || '').trim();
            if (repaired) {
              const nextQe = evaluateSourceTargetQe({ srcText: origLine, tgtText: repaired, profile });
              if (nextQe.qeRiskScore < qe.qeRiskScore) {
                chunkOut[idx] = repaired;
              }
            }
          }
        } catch (err) {
          if (poolCtrl.signal.aborted || (err as { name?: string })?.name === 'AbortError') throw err;
          // Keep safe original draft if single-pass repair fails or times out
        }
      }

      chunkOut.forEach((txt, idx) => {
        allOut[start + idx] = txt;
      });
      onChunkDone?.(start, chunkOut);
      await yieldToMain();
    });
  } catch (err) {
    poolCtrl.abort();
    throw err;
  } finally {
    signal?.removeEventListener('abort', onOuterAbort);
  }
  return allOut;
}

async function translateMixedCjkLineToTarget(
  line: string,
  tgt: TargetLang,
  signal?: AbortSignal
): Promise<string> {
  if (tgt === 'ja') {
    const { idScore, enScore } = scoreLatinWords(line);
    const latinSrc: SourceLang = idScore > enScore ? 'id' : enScore > idScore ? 'en' : 'auto';
    try {
      const r = await requestGtxSingleChunk(line, latinSrc, 'ja', signal);
      return r.translated || line;
    } catch (err) {
      if (signal?.aborted || (err as { name?: string })?.name === 'AbortError') throw err;
      return line;
    }
  }

  // Replace every Japanese/CJK span inside the line with its target translation first
  const spans: string[] = [];
  const tokenLine = line.replace(CJK_SPAN_RE, (match) => {
    if (!hasTranslatableLetters(match)) return match;
    const idx = spans.length;
    spans.push(match);
    return `[[M${idx}]]`;
  });

  let merged = tokenLine;
  if (spans.length > 0) {
    const { outputs } = await translateBatchViaGoogleGtx(spans, 'ja', tgt, signal);
    outputs.forEach((tr, idx) => {
      merged = merged.split(`[[M${idx}]]`).join(tr || spans[idx]);
    });
  }

  // If the remaining Latin part is in a non-target language (e.g. English when tgt=id), translate it too
  const restClass = classifyParagraphLanguage(merged);
  if (
    (tgt === 'id' && (restClass === 'en' || restClass === 'mixed-latin')) ||
    (tgt === 'en' && (restClass === 'id' || restClass === 'mixed-latin'))
  ) {
    const secondSrc: SourceLang = restClass === 'en' ? 'en' : restClass === 'id' ? 'id' : 'auto';
    try {
      const r2 = await requestGtxSingleChunk(merged, secondSrc, tgt, signal);
      return r2.translated || merged;
    } catch (err) {
      if (signal?.aborted || (err as { name?: string })?.name === 'AbortError') throw err;
      return merged;
    }
  }
  return merged;
}

export async function translateParagraphsDirect(params: {
  paragraphs: string[];
  mode: ModePair;
  titleId?: string;
  titleKind?: TitleKind;
  docFormat?: 'txt' | 'md' | 'html' | 'epub' | 'pdf' | 'docx' | 'srt' | 'vtt' | 'image';
  signal?: AbortSignal;
  onProgress?: (partialOutputs: string[], doneCount: number, totalCount: number) => void;
}): Promise<{
  outputs: string[];
  detectedSource: TargetLang;
  model: string;
  matchedChips: NameChipItem[];
}> {
  const { src, tgt } = parseModePair(params.mode);
  const totalCount = params.paragraphs.length;
  const combinedSample = params.paragraphs.slice(0, 8).join('\n');
  let detectedSource: TargetLang =
    src === 'auto'
      ? detectLanguageLocal(combinedSample, tgt === 'ja' ? 'id' : 'ja')
      : src;

  // Eliminate waterfall: fetch glossary & Gemini key concurrently
  const [glossary, geminiKey] = await Promise.all([
    loadGlossaryEntriesOnce(params.titleId),
    getOwnerGeminiKey(),
  ]);

  const matchedChips: NameChipItem[] = [];
  for (const entry of glossary) {
    if (
      combinedSample.includes(entry.surface) ||
      (entry.render_id && combinedSample.includes(entry.render_id)) ||
      (entry.render_en && combinedSample.includes(entry.render_en))
    ) {
      matchedChips.push({
        surface: entry.surface,
        reading: entry.reading,
        romaji: entry.romaji,
        dst:
          tgt === 'ja'
            ? entry.surface
            : tgt === 'en'
              ? entry.render_en || entry.romaji
              : entry.render_id || entry.romaji,
        kind: entry.kind,
        confirmed: true,
        source: entry.source,
      });
    }
  }

  const allGlossaryPairs = [
    ...buildGlossaryPairs(glossary, 'ja', tgt),
    ...buildGlossaryPairs(glossary, 'id', tgt),
    ...buildGlossaryPairs(glossary, 'en', tgt),
  ];
  const dedupPairMap = new Map<string, string>();
  for (const [k, v] of allGlossaryPairs) {
    if (!dedupPairMap.has(k)) dedupPairMap.set(k, v);
  }
  const combinedGlossaryPairs = Array.from(dedupPairMap.entries()).sort(
    (a, b) => b[0].length - a[0].length
  );
  const glossaryValues = combinedGlossaryPairs.map(([, v]) => v);
  const discourseProfile = profileDocument({
    paragraphs: params.paragraphs,
    srcLang: detectedSource,
    tgtLang: tgt,
    seriesKey: params.titleId,
    titleKind: params.titleKind,
    docFormat: params.docFormat,
  });
  // Compact signature of active glossary + engine + discourse profile so cache invalidates automatically on tone/glossary/key change
  const glossarySig = `${discourseProfile.cacheFingerprint}|${geminiKey ? 'g' : 'x'}${combinedGlossaryPairs.length}:${combinedGlossaryPairs
    .slice(0, 12)
    .map(([k, v]) => `${k}=${v}`)
    .join(',')
    .slice(0, 120)}`;

  const outputs = new Array<string>(totalCount).fill('');
  const doneFlags = new Uint8Array(totalCount);
  let doneCount = 0;
  let lastProgressEmit = 0;

  const markDone = (idx: number, val: string, forceEmit = false) => {
    outputs[idx] = val;
    if (!doneFlags[idx]) {
      doneFlags[idx] = 1;
      doneCount += 1;
    }
    if (params.onProgress) {
      const now = performance.now();
      if (forceEmit || doneCount === totalCount || now - lastProgressEmit >= 120) {
        lastProgressEmit = now;
        params.onProgress(outputs.slice(), doneCount, totalCount);
      }
    }
  };

  const toTranslateIdx: number[] = [];
  const paraClasses: ParagraphLangClass[] = params.paragraphs.map((p) =>
    classifyParagraphLanguage(p)
  );

  // Strict target-language guarantee + L1/L2 persistent paragraph cache lookup
  params.paragraphs.forEach((rawPara, idx) => {
    const trimmed = rawPara.trim();
    const cls = paraClasses[idx];
    if (!trimmed || !hasTranslatableLetters(trimmed)) {
      markDone(idx, rawPara);
      return;
    }
    if (
      (tgt === 'id' && cls === 'id') ||
      (tgt === 'en' && cls === 'en') ||
      (tgt === 'ja' && cls === 'ja')
    ) {
      markDone(idx, rawPara);
      return;
    }
    const cacheKey = makeParaCacheKey(src, tgt, glossarySig, trimmed);
    const cached = getCachedParaTranslation(cacheKey);
    if (cached !== undefined && !isStillUntranslatedForTarget(trimmed, cached, tgt)) {
      markDone(idx, cached);
      return;
    }
    toTranslateIdx.push(idx);
  });

  if (toTranslateIdx.length === 0) {
    params.onProgress?.(outputs.slice(), totalCount, totalCount);
    return {
      outputs,
      detectedSource: doneCount > 0 && paraClasses.every((c) => c === tgt || c === 'unknown') ? tgt : detectedSource,
      model: 'cache',
      matchedChips,
    };
  }

  const detectedHonorificNames: Record<string, string> = {};
  const recentTags: string[] = [];
  const maskedEntries = toTranslateIdx.map((origIdx) => {
    const pre = preprocessSourceForMt(params.paragraphs[origIdx], discourseProfile, glossary);
    Object.assign(detectedHonorificNames, pre.detectedHonorificNames);
    const gMask = maskWithGlossary(pre.prepared, combinedGlossaryPairs);
    return {
      origIdx,
      cls: paraClasses[origIdx],
      cacheKey: makeParaCacheKey(src, tgt, glossarySig, params.paragraphs[origIdx].trim()),
      preRestoreMap: pre.restoreMap,
      hadJaKeigo: pre.hadJaKeigo,
      ...gMask,
    };
  });

  const finalizeParagraph = (
    entry: (typeof maskedEntries)[number],
    rawTranslated: string
  ): string => {
    const restored = restorePreMtTokens(
      unmaskWithGlossary(rawTranslated || entry.masked, entry.map),
      entry.preRestoreMap
    );
    return naturalizeAndVerifyParagraph({
      srcText: params.paragraphs[entry.origIdx],
      rawTranslated: restored,
      profile: discourseProfile,
      hadJaKeigo: entry.hadJaKeigo,
      glossaryValues,
      recentTags,
    });
  };

  if (geminiKey) {
    try {
      await translateViaGeminiDirect(
        maskedEntries.map((m) => m.masked),
        src,
        tgt,
        geminiKey,
        discourseProfile,
        params.signal,
        (startOffset, chunkOut) => {
          chunkOut.forEach((txt, offset) => {
            const m = maskedEntries[startOffset + offset];
            if (!m) return;
            const finalTxt = finalizeParagraph(m, txt);
            if (!isStillUntranslatedForTarget(params.paragraphs[m.origIdx], finalTxt, tgt)) {
              setCachedParaTranslation(m.cacheKey, finalTxt);
            }
            markDone(m.origIdx, finalTxt, offset === chunkOut.length - 1);
          });
        }
      );
      saveSeriesDiscourseMemory(
        params.titleId,
        discourseProfile,
        params.paragraphs,
        outputs,
        detectedHonorificNames
      );
      params.onProgress?.(outputs.slice(), totalCount, totalCount);
      return {
        outputs,
        detectedSource,
        model: 'gemini-2.5-flash-lite',
        matchedChips,
      };
    } catch (err) {
      if (params.signal?.aborted || (err as { name?: string })?.name === 'AbortError') {
        throw err;
      }
      // Fall through to Google GTX if Gemini key quota or network fails
    }
  }

  // Group non-target paragraphs by exact source language so mixed-language docs never confuse Google GTX
  const buckets: Record<SourceLang, typeof maskedEntries> = {
    ja: [],
    en: [],
    id: [],
    auto: [],
  };
  const mixedJaItems: typeof maskedEntries = [];

  for (const item of maskedEntries) {
    // Skip items already completed by earlier Gemini chunks before fallback
    if (doneFlags[item.origIdx]) continue;
    if (item.cls === 'mixed-ja') {
      mixedJaItems.push(item);
    } else if (item.cls === 'ja' && tgt !== 'ja') {
      buckets.ja.push(item);
    } else if (item.cls === 'en' && tgt !== 'en') {
      buckets.en.push(item);
    } else if (item.cls === 'id' && tgt !== 'id') {
      buckets.id.push(item);
    } else if (src !== 'auto' && src !== tgt) {
      buckets[src].push(item);
    } else {
      buckets.auto.push(item);
    }
  }

  // Run non-empty language buckets in parallel!
  const activeBuckets = (Object.entries(buckets) as Array<[SourceLang, typeof maskedEntries]>).filter(
    ([, items]) => items.length > 0
  );

  await Promise.all(
    activeBuckets.map(async ([bucketSrc, items]) => {
      const batchedRes = await translateBatchViaGoogleGtx(
        items.map((m) => m.masked),
        bucketSrc,
        tgt,
        params.signal,
        (slotIdx, translatedRaw) => {
          const item = items[slotIdx];
          if (!item) return;
          const finalTxt = finalizeParagraph(item, translatedRaw);
          if (!isStillUntranslatedForTarget(params.paragraphs[item.origIdx], finalTxt, tgt)) {
            setCachedParaTranslation(item.cacheKey, finalTxt);
          }
          markDone(item.origIdx, finalTxt);
        }
      );
      if (bucketSrc !== 'auto') {
        detectedSource = bucketSrc;
      } else {
        detectedSource = batchedRes.detected;
      }
      items.forEach((item, k) => {
        if (!doneFlags[item.origIdx]) {
          const fallbackRaw = batchedRes.outputs[k];
          const finalTxt = finalizeParagraph(item, fallbackRaw);
          // Do not poison L1/L2 cache with untranslated fallback strings that were never emitted via onSlotTranslated
          markDone(item.origIdx, finalTxt);
        }
      });
    })
  );

  if (mixedJaItems.length > 0) {
    await runConcurrentPool(mixedJaItems, getDeviceRuntimeProfile().gtxConcurrency, async (item) => {
      const tr = await translateMixedCjkLineToTarget(item.masked, tgt, params.signal);
      const finalTxt = finalizeParagraph(item, tr);
      if (!isStillUntranslatedForTarget(params.paragraphs[item.origIdx], finalTxt, tgt)) {
        setCachedParaTranslation(item.cacheKey, finalTxt);
      }
      markDone(item.origIdx, finalTxt);
      if (tgt !== 'ja') detectedSource = 'ja';
    });
  }

  saveSeriesDiscourseMemory(
    params.titleId,
    discourseProfile,
    params.paragraphs,
    outputs,
    detectedHonorificNames
  );
  params.onProgress?.(outputs.slice(), totalCount, totalCount);
  return {
    outputs,
    detectedSource,
    model: 'tranx-direct',
    matchedChips,
  };
}

interface CachedWebEntry {
  url: string;
  host: string;
  titleId: string;
  titleSrc: string;
  srcParas: string[];
  detectedSource: TargetLang;
  novelNav: NovelNavigation;
  comicMeta?: MangaLinkMeta;
  rawHtml?: string;
  rawMarkdown?: string;
  htmlFetchAttempted?: boolean;
}

// Bounded O(1) LRU caches prevent unbounded RAM growth & mobile PWA OOM eviction during long reading sessions
const initProfile = getDeviceRuntimeProfile();
const webArticleCache = new BoundedLruCache<string, CachedWebEntry>(
  Math.round(24 * initProfile.ramCacheScale)
);
const inFlightArticleFetches = new Map<string, Promise<CachedWebEntry>>();
const translatedWebCache = new BoundedLruCache<string, { heading: string; paras: string[] }>(
  Math.round(32 * initProfile.ramCacheScale)
);
const inFlightPreTranslations = new Set<string>();
const translatedSiteHtmlCache = new BoundedLruCache<string, string>(
  Math.round(16 * initProfile.ramCacheScale)
);
const seriesTocCache = new BoundedLruCache<
  string,
  { seriesTitle?: string; tocUrl: string; chapters: NovelChapterLink[]; authoritative?: boolean }
>(24);
const translatedChapterTitlesCache = new BoundedLruCache<string, Record<string, string>>(24);
const scannedMangaPageCache = new BoundedLruCache<string, ImageTranslationResult>(
  initProfile.isConstrained ? 4 : 8
);

// Release excess RAM caches gracefully when mobile PWA or tab moves to background
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      translatedSiteHtmlCache.trimToRatio(0.4);
      webArticleCache.trimToRatio(0.5);
    }
  });
}

const READING_PROGRESS_STORAGE_KEY = 'tranx_reading_progress_v1';
const READING_PROGRESS_MAX = 60;

export interface ReadingProgressEntry {
  url: string;
  chapterLabel?: string;
  titleDst?: string;
  updatedAt: number;
}

function readReadingProgressStore(): Record<string, ReadingProgressEntry> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(READING_PROGRESS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, ReadingProgressEntry>) : {};
  } catch {
    return {};
  }
}

export function saveReadingProgress(seriesKey: string, entry: ReadingProgressEntry): void {
  if (typeof window === 'undefined' || !seriesKey || !entry.url) return;
  try {
    const store = readReadingProgressStore();
    store[seriesKey] = {
      url: entry.url,
      ...(entry.chapterLabel ? { chapterLabel: entry.chapterLabel } : {}),
      ...(entry.titleDst ? { titleDst: entry.titleDst.slice(0, 120) } : {}),
      updatedAt: entry.updatedAt || Date.now(),
    };
    const keys = Object.keys(store);
    if (keys.length > READING_PROGRESS_MAX) {
      keys
        .sort((a, b) => (store[a]?.updatedAt || 0) - (store[b]?.updatedAt || 0))
        .slice(0, keys.length - READING_PROGRESS_MAX)
        .forEach((k) => {
          delete store[k];
        });
    }
    window.localStorage.setItem(READING_PROGRESS_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Ignore private-mode or quota errors
  }
}

export function getReadingProgress(seriesKey?: string | null): ReadingProgressEntry | null {
  if (!seriesKey) return null;
  const store = readReadingProgressStore();
  return store[seriesKey] || null;
}

/**
 * Automatically generates a Google Translate live-translated website URL
 * (e.g. https://kakuyomu-jp.translate.goog/...?_x_tr_sl=auto&_x_tr_tl=id&_x_tr_pto=wapp)
 * that works natively on both Desktop and Mobile browsers without any browser extension.
 */
export function buildAutoTranslatedSiteUrl(rawUrl: string, mode: ModePair): string | null {
  const safe = toSafeHttpUrl(rawUrl);
  if (!safe) return null;
  try {
    const u = new URL(safe);
    if (u.hostname.endsWith('.translate.goog')) return safe;
    const { src, tgt } = parseModePair(mode);
    const hostEncoded = u.hostname.replace(/-/g, '--').replace(/\./g, '-');
    if (/^[a-z0-9-]+$/i.test(hostEncoded) && hostEncoded.length <= 63 && !u.port) {
      const out = new URL(`https://${hostEncoded}.translate.goog${u.pathname}${u.search}${u.hash}`);
      out.searchParams.set('_x_tr_sl', src === 'auto' ? 'auto' : src);
      out.searchParams.set('_x_tr_tl', tgt);
      out.searchParams.set('_x_tr_hl', tgt);
      out.searchParams.set('_x_tr_pto', 'wapp');
      if (u.protocol === 'http:') out.searchParams.set('_x_tr_sch', 'http');
      return out.toString();
    }
    const fallback = new URL('https://translate.google.com/translate');
    fallback.searchParams.set('sl', src === 'auto' ? 'auto' : src);
    fallback.searchParams.set('tl', tgt);
    fallback.searchParams.set('hl', tgt);
    fallback.searchParams.set('u', safe);
    return fallback.toString();
  } catch {
    return null;
  }
}

function sanitizeNovelNav(nav: NovelNavigation): NovelNavigation {
  const clean: NovelNavigation = {
    isNovel: Boolean(nav.isNovel),
    prevUrl: nav.prevUrl || null,
    nextUrl: nav.nextUrl || null,
    tocUrl: nav.tocUrl || null,
    firstUrl: nav.firstUrl || null,
  };
  if (nav.isTocPage) clean.isTocPage = true;
  if (nav.seriesTitle && nav.seriesTitle.trim()) clean.seriesTitle = nav.seriesTitle.trim();
  if (nav.chapterLabel && nav.chapterLabel.trim()) clean.chapterLabel = nav.chapterLabel.trim();
  if (typeof nav.totalChapters === 'number' && nav.totalChapters > 0) {
    clean.totalChapters = nav.totalChapters;
  }
  if (typeof nav.currentIndex === 'number' && nav.currentIndex >= 0) {
    clean.currentIndex = nav.currentIndex;
  }
  if (Array.isArray(nav.chapters) && nav.chapters.length > 0) {
    clean.chapters = nav.chapters.map((ch) => {
      const row: NovelChapterLink = {
        title: (ch.title || '').trim() || 'Bab',
        url: ch.url,
      };
      if (ch.titleDst && ch.titleDst.trim()) row.titleDst = ch.titleDst.trim();
      if (ch.current) row.current = true;
      return row;
    });
  }
  return clean;
}

const NOVEL_HOST_RE =
  /(kakuyomu\.jp|syosetu\.com|syosetu\.org|alphapolis\.co\.jp|aozora\.gr\.jp|royalroad\.com|scribblehub\.com|archiveofourown\.org|fanfiction\.net|webnovel\.com|wuxiaworld\.|novelbin\.|novelfull\.|novelfire\.|freewebnovel\.|lightnovelworld\.|lightnovelpub\.|readnovelfull\.|boxnovel\.|wattpad\.com|tapas\.io|lightnovel|webnovel|novelupdates\.|wordpress\.com)/i;

const NON_NOVEL_HOST_RE =
  /(wikipedia\.org|wikimedia\.org|wiktionary\.org|bbc\.com|bbc\.co\.uk|cnn\.com|nytimes\.com|reuters\.com|theguardian\.com|nhk\.or\.jp|yahoo\.co\.jp|github\.com|stackoverflow\.com|reddit\.com|x\.com|twitter\.com|youtube\.com|kompas\.com|detik\.com|tempo\.co|cnnindonesia\.com)/i;

const NON_CHAPTER_PATH_RE =
  /\/(login|signin|sign-in|signup|sign-up|register|logout|account|profile|settings|search|cart|checkout|pricing|contact|about|privacy|privacypolicy|terms|tos|dmca|cookie|cookiepolicy|help|helpcenter|support|notifications|report|impression|novelreview|novelreport|ihantsuhou|favnovelmain|rank|ranking|tags?|categor(?:y|ies)|author|authors|mypage|advertising|ads)\b/i;

const NEXT_LINK_RE =
  /(次のエピソード|次の話|次のページ|次へ|次話|次の章|next\s*(chapter|episode|ep|page|part|post)|newer\s*post|bab\s*(berikutnya|selanjutnya)|halaman\s*(berikutnya|selanjutnya)|artikel\s*(berikutnya|selanjutnya)|cerita\s*(berikutnya|selanjutnya)|^next$|^selanjutnya$|^berikutnya$|^lanjutan$|^»$|^>>$|^→$)/i;
const PREV_LINK_RE =
  /(前のエピソード|前の話|前のページ|前へ|前話|前の章|prev(ious)?\s*(chapter|episode|ep|page|part|post)|older\s*post|bab\s*sebelumnya|halaman\s*sebelumnya|artikel\s*sebelumnya|cerita\s*sebelumnya|^prev$|^previous$|^sebelumnya$|^«$|^<<$|^←$)/i;
const TOC_LINK_RE =
  /(目次|エピソード一覧|作品トップ|table\s*of\s*contents|chapter\s*list|all\s*chapters|daftar\s*(isi|bab)|^toc$)/i;

function decodeHtmlEntities(input: string): string {
  if (!input || !input.includes('&')) return input;
  const named: Record<string, string> = {
    amp: '&',
    lt: '<',
    gt: '>',
    quot: '"',
    apos: "'",
    nbsp: ' ',
    ndash: '-',
    mdash: '-',
    hellip: '...',
    lsquo: "'",
    rsquo: "'",
    ldquo: '"',
    rdquo: '"',
    laquo: '<<',
    raquo: '>>',
  };
  return input
    .replace(/&#(\d+);/g, (_, dec) => {
      const code = Number(dec);
      return Number.isFinite(code) && code > 0 && code <= 0x10ffff
        ? String.fromCodePoint(code)
        : _;
    })
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => {
      const code = parseInt(hex, 16);
      return Number.isFinite(code) && code > 0 && code <= 0x10ffff
        ? String.fromCodePoint(code)
        : _;
    })
    .replace(/&([a-z]+);/gi, (m, name) => named[name.toLowerCase()] ?? m);
}

function getRegistrableDomain(hostname: string): string {
  const clean = hostname.toLowerCase().replace(/^www\./, '');
  const parts = clean.split('.').filter(Boolean);
  if (parts.length <= 2) return clean;
  const tail2 = parts.slice(-2).join('.');
  if (/^(co|ne|or|gr|ac|go|ed|lg)\.(jp|uk|id|kr|au|nz)$/i.test(tail2) && parts.length >= 3) {
    return parts.slice(-3).join('.');
  }
  return tail2;
}

function isSameRegistrableHost(urlA: string, urlB: string): boolean {
  try {
    return getRegistrableDomain(new URL(urlA).hostname) === getRegistrableDomain(new URL(urlB).hostname);
  } catch {
    return false;
  }
}

function isCandidateChapterUrl(candidateUrl: string, baseUrl: string): boolean {
  if (!isSameRegistrableHost(candidateUrl, baseUrl)) return false;
  try {
    const u = new URL(candidateUrl);
    if (NON_CHAPTER_PATH_RE.test(u.pathname)) return false;
    return true;
  } catch {
    return false;
  }
}

function hasMojibake(text: string): boolean {
  if (!text) return false;
  const matches = text.match(/\uFFFD/g);
  return Boolean(matches && matches.length >= 3);
}

function isChallengeOrBlockedPayload(title: string, html: string, content: string): boolean {
  const head = `${title}\n${content.slice(0, 1200)}\n${html.slice(0, 2800)}`;
  const hasChallengeMarker =
    /just a moment\.\.\.|attention required!\s*\|\s*cloudflare|checking your browser|enable javascript and cookies to continue|cf-browser-verification|cf-challenge|challenge-platform|verify you are human|please complete the security check|ddos-guard|access denied\s*\|\s*cloudflare|generated by cloudfront|403\s+(?:error|kesalahan|forbidden)\b|the request could not be satisfied|permintaan (?:itu )?tidak dapat dipenuhi|permintaan diblokir\.\s*kami tidak dapat terhubung|request blocked\.\s*we can['’]t connect to the server|cloudfront documentation|dokumentasi cloudfront|request unsuccessful\.\s*incapsula|access denied\b[\s\S]{0,220}reference\s*#|error\s+403\s+forbidden|^(?:error|kesalahan):\s*(?:the request could not be satisfied|permintaan (?:itu )?tidak dapat dipenuhi)|<title>\s*(?:error:\s*the request could not be satisfied|kesalahan:\s*permintaan (?:itu )?tidak dapat dipenuhi|403\s+(?:forbidden|error|kesalahan)|429\s+too many requests|503\s+service unavailable|access denied)\s*<\/title>/im.test(
      head
    );
  if (!hasChallengeMarker) return false;
  // Only flag if body text is small (real long articles discussing CloudFront/Cloudflare are > 3,500 chars!)
  if (content.length > 3500) return false;
  if (
    html.length > 30000 &&
    !/just a moment\.\.\.|attention required|the request could not be satisfied|permintaan (?:itu )?tidak dapat dipenuhi|403\s+(?:forbidden|error|kesalahan)|access denied/i.test(
      title
    )
  ) {
    return false;
  }
  return true;
}

function isBlockedArticleOrTranslation(
  title: string,
  paras: string[],
  rawHtml = ''
): boolean {
  const joinedParas = (paras || []).slice(0, 8).join('\n');
  if (isChallengeOrBlockedPayload(title || '', rawHtml || '', joinedParas)) return true;
  const trimmedTitle = (title || '').trim();
  if (
    paras.length <= 6 &&
    /^(?:error:\s*the request could not be satisfied|kesalahan:\s*permintaan (?:itu )?tidak dapat dipenuhi|403\s+(?:error|kesalahan|forbidden)|access denied)/i.test(
      trimmedTitle
    )
  ) {
    return true;
  }
  return false;
}

function deriveKnownTocInfo(rawUrl: string): { tocUrl: string; isTocPage: boolean } | null {
  try {
    const u = new URL(rawUrl);
    const host = u.hostname.toLowerCase();
    const path = u.pathname;

    if (host.includes('kakuyomu.jp')) {
      const ep = path.match(/^\/works\/(\d+)\/episodes\/\d+/);
      if (ep) return { tocUrl: `https://kakuyomu.jp/works/${ep[1]}`, isTocPage: false };
      const wk = path.match(/^\/works\/(\d+)\/?$/);
      if (wk) return { tocUrl: `https://kakuyomu.jp/works/${wk[1]}`, isTocPage: true };
    }
    if (host.includes('syosetu.com')) {
      const ep = path.match(/^\/(n[a-z0-9]+)\/(\d+)\/?$/i);
      if (ep) {
        const epNum = Number(ep[2]);
        const tocPage = epNum > 100 ? Math.floor((epNum - 1) / 100) + 1 : 1;
        return {
          tocUrl: tocPage > 1 ? `${u.origin}/${ep[1]}/?p=${tocPage}` : `${u.origin}/${ep[1]}/`,
          isTocPage: false,
        };
      }
      const wk = path.match(/^\/(n[a-z0-9]{4,})\/?$/i);
      if (wk) return { tocUrl: `${u.origin}/${wk[1]}/${u.search}`, isTocPage: true };
    }
    if (host.includes('syosetu.org')) {
      const ep = path.match(/^\/novel\/(\d+)\/\d+\.html$/i);
      if (ep) return { tocUrl: `${u.origin}/novel/${ep[1]}/`, isTocPage: false };
      const wk = path.match(/^\/novel\/(\d+)\/?$/i);
      if (wk) return { tocUrl: `${u.origin}/novel/${wk[1]}/`, isTocPage: true };
    }
    if (host.includes('alphapolis.co.jp')) {
      const ep = path.match(/^\/novel\/(\d+\/\d+)\/episode\/\d+/i);
      if (ep) return { tocUrl: `${u.origin}/novel/${ep[1]}`, isTocPage: false };
      const wk = path.match(/^\/novel\/(\d+\/\d+)\/?$/i);
      if (wk) return { tocUrl: `${u.origin}/novel/${wk[1]}`, isTocPage: true };
    }
    if (host.includes('royalroad.com')) {
      const ep = path.match(/^\/fiction\/(\d+)\/([^/]+)\/chapter\/\d+/i);
      if (ep) return { tocUrl: `${u.origin}/fiction/${ep[1]}/${ep[2]}`, isTocPage: false };
      const wk = path.match(/^\/fiction\/(\d+)\/([^/]+)\/?$/i);
      if (wk) return { tocUrl: `${u.origin}/fiction/${wk[1]}/${wk[2]}`, isTocPage: true };
    }
    if (host.includes('scribblehub.com')) {
      const ep = path.match(/^\/read\/(\d+)-([^/]+)\/chapter\/\d+/i);
      if (ep) return { tocUrl: `${u.origin}/series/${ep[1]}/${ep[2]}/`, isTocPage: false };
      const wk = path.match(/^\/series\/(\d+)\/([^/]+)\/?$/i);
      if (wk) return { tocUrl: `${u.origin}/series/${wk[1]}/${wk[2]}/`, isTocPage: true };
    }
    if (host.includes('archiveofourown.org')) {
      const ep = path.match(/^\/works\/(\d+)\/chapters\/\d+/i);
      if (ep) return { tocUrl: `${u.origin}/works/${ep[1]}/navigate`, isTocPage: false };
      const wk = path.match(/^\/works\/(\d+)\/navigate\/?$/i);
      if (wk) return { tocUrl: `${u.origin}/works/${wk[1]}/navigate`, isTocPage: true };
    }
    // Universal NovelBin / NovelFull / NovelFire / FreeWebNovel / LightNovelWorld / WuxiaWorld / Madara WP patterns
    const genericNovelEp = path.match(
      /^(\/(?:b|book|novel|series|story|fiction|read|manga|light-novel)\/[^/]+)\/(?:chapter|ch|ep|episode|bab|part)[-_/][^/]+/i
    );
    if (genericNovelEp) {
      return { tocUrl: `${u.origin}${genericNovelEp[1]}`, isTocPage: false };
    }
    const genericNovelToc = path.match(
      /^(\/(?:b|book|novel|series|story|light-novel)\/[^/]+)\/?$/i
    );
    if (genericNovelToc && NOVEL_HOST_RE.test(host)) {
      return { tocUrl: `${u.origin}${genericNovelToc[1]}`, isTocPage: true };
    }
  } catch {
    // ignore
  }
  return null;
}

// deriveSeriesTitleId is imported & re-exported from ./langUtils

function isKnownNovelUrl(rawUrl: string): boolean {
  try {
    const u = new URL(rawUrl);
    if (NOVEL_HOST_RE.test(u.hostname)) return true;
    return /\/(works\/\d+\/episodes\/\d+|episode[s]?\/\d+|chapter[-_/]?\d+|bab[-_/]?\d+|ch[-_/]?\d+|n[0-9a-z]{4,}\/\d+)/i.test(
      u.pathname
    );
  } catch {
    return false;
  }
}

function resolveSafeSiblingUrl(href: string, baseUrl: string): string | null {
  const cleanHref = (href || '').trim();
  if (!cleanHref || cleanHref.startsWith('#')) return null;
  try {
    const u = new URL(cleanHref, baseUrl);
    u.hash = '';
    return toSafeHttpUrl(u.toString());
  } catch {
    return null;
  }
}

function canonicalUrlKey(rawUrl: string): string {
  try {
    const u = new URL(rawUrl);
    return `${u.origin}${u.pathname.replace(/\/+$/, '')}${u.search}`;
  } catch {
    return rawUrl;
  }
}

function extractKakuyomuFromNextData(
  rawHtml: string,
  workId: string,
  currentEpId: string
): NovelNavigation | null {
  const match = rawHtml.match(
    /<script[^>]*id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i
  );
  if (!match) return null;
  try {
    const data = JSON.parse(match[1]);
    const apollo = data?.props?.pageProps?.__APOLLO_STATE__;
    if (!apollo || typeof apollo !== 'object') return null;

    const workObj = apollo[`Work:${workId}`] as
      | { title?: string; tableOfContentsV2?: Array<{ __ref?: string }> }
      | undefined;
    const seriesTitle = typeof workObj?.title === 'string' ? workObj.title.trim() : undefined;
    const orderedIds: string[] = [];
    const seen = new Set<string>();

    const pushEpRef = (ref: unknown) => {
      if (typeof ref === 'string' && ref.startsWith('Episode:')) {
        const epId = ref.slice('Episode:'.length);
        if (epId && !seen.has(epId)) {
          seen.add(epId);
          orderedIds.push(epId);
        }
      }
    };

    const pushTocChapterObj = (tocObj: unknown) => {
      if (!tocObj || typeof tocObj !== 'object') return;
      const unions = (tocObj as { episodeUnions?: Array<{ __ref?: string }> }).episodeUnions;
      if (Array.isArray(unions)) {
        for (const item of unions) pushEpRef(item?.__ref);
      }
    };

    // Follow authoritative Work.tableOfContentsV2 order first (preserves multi-arc volume order)
    if (Array.isArray(workObj?.tableOfContentsV2)) {
      for (const tocRef of workObj.tableOfContentsV2) {
        if (tocRef?.__ref && apollo[tocRef.__ref]) {
          pushTocChapterObj(apollo[tocRef.__ref]);
        }
      }
    }

    if (orderedIds.length === 0) {
      for (const [key, val] of Object.entries(apollo)) {
        if (key.startsWith('TableOfContentsChapter:')) {
          pushTocChapterObj(val);
        }
      }
    }

    if (orderedIds.length === 0) {
      for (const key of Object.keys(apollo)) {
        if (key.startsWith('Episode:')) pushEpRef(key);
      }
    }

    const chapters: NovelChapterLink[] = orderedIds.map((epId, idx) => {
      const epObj = apollo[`Episode:${epId}`] as { title?: string } | undefined;
      return {
        title: (epObj?.title || `Bab ${idx + 1}`).trim(),
        url: `https://kakuyomu.jp/works/${workId}/episodes/${epId}`,
        ...(currentEpId && epId === currentEpId ? { current: true } : {}),
      };
    });

    const curIdx = currentEpId ? chapters.findIndex((c) => c.current) : -1;
    const isTocPage = !currentEpId;
    return sanitizeNovelNav({
      isNovel: true,
      isTocPage,
      seriesTitle,
      totalChapters: chapters.length,
      ...(curIdx >= 0 ? { currentIndex: curIdx } : {}),
      chapterLabel:
        curIdx >= 0
          ? `${curIdx + 1} / ${chapters.length}`
          : chapters.length > 0
            ? `${chapters.length} bab`
            : undefined,
      firstUrl: chapters[0]?.url || null,
      prevUrl: curIdx > 0 ? chapters[curIdx - 1].url : null,
      nextUrl: isTocPage
        ? chapters[0]?.url || null
        : curIdx >= 0 && curIdx + 1 < chapters.length
          ? chapters[curIdx + 1].url
          : null,
      tocUrl: `https://kakuyomu.jp/works/${workId}`,
      chapters: chapters.slice(0, 1500),
    });
  } catch {
    return null;
  }
}

function extractKakuyomuEpisodeSidebar(
  rawHtml: string,
  workId: string,
  currentEpId: string
): NovelNavigation | null {
  if (!rawHtml || !workId) return null;
  const doc = new DOMParser().parseFromString(rawHtml, 'text/html');
  const anchors = Array.from(doc.querySelectorAll(`a[href*="/works/${workId}/episodes/"]`));
  if (anchors.length === 0) return null;
  const seen = new Set<string>();
  const chapters: NovelChapterLink[] = [];
  for (const a of anchors) {
    const href = a.getAttribute('href') || '';
    const m = href.match(new RegExp(`/works/${workId}/episodes/(\\d+)`));
    if (!m) continue;
    const epId = m[1];
    if (seen.has(epId)) continue;
    seen.add(epId);
    const clone = a.cloneNode(true) as Element;
    clone.querySelectorAll('time, .widget-toc-episode-datePublished').forEach((el) => el.remove());
    const label = decodeHtmlEntities((clone.textContent || '').replace(/\s+/g, ' ').trim())
      .replace(/\s*\d{4}年\d{1,2}月\d{1,2}日.*$/, '')
      .trim();
    if (TOC_CTA_SKIP_RE.test(label)) continue;
    chapters.push({
      title: label || `Bab ${chapters.length + 1}`,
      url: `https://kakuyomu.jp/works/${workId}/episodes/${epId}`,
      ...(currentEpId && epId === currentEpId ? { current: true } : {}),
    });
  }
  if (chapters.length === 0) return null;
  const curIdx = currentEpId ? chapters.findIndex((c) => c.current) : -1;
  const isTocPage = !currentEpId;
  return sanitizeNovelNav({
    isNovel: true,
    isTocPage,
    totalChapters: chapters.length,
    ...(curIdx >= 0 ? { currentIndex: curIdx } : {}),
    chapterLabel:
      curIdx >= 0
        ? `${curIdx + 1} / ${chapters.length}`
        : `${chapters.length} bab`,
    firstUrl: chapters[0]?.url || null,
    prevUrl: curIdx > 0 ? chapters[curIdx - 1].url : null,
    nextUrl: isTocPage
      ? chapters[0]?.url || null
      : curIdx >= 0 && curIdx + 1 < chapters.length
        ? chapters[curIdx + 1].url
        : null,
    tocUrl: `https://kakuyomu.jp/works/${workId}`,
    chapters: chapters.slice(0, 1500),
  });
}

function extractRoyalRoadFromScriptData(rawHtml: string, cleanUrl: string): NovelNavigation | null {
  if (!/royalroad\.com/i.test(cleanUrl)) return null;
  const match = rawHtml.match(/window\.chapters\s*=\s*(\[\s*\{[\s\S]*?\}\s*\])\s*;/);
  if (!match) return null;
  try {
    const items = JSON.parse(match[1]) as Array<{ title?: string; url?: string }>;
    if (!Array.isArray(items) || items.length === 0) return null;
    const curKey = canonicalUrlKey(cleanUrl);
    const chapters: NovelChapterLink[] = [];
    for (const item of items) {
      if (!item?.url) continue;
      const abs = resolveSafeSiblingUrl(item.url, cleanUrl);
      if (!abs) continue;
      chapters.push({
        title: decodeHtmlEntities((item.title || `Bab ${chapters.length + 1}`).trim()),
        url: abs,
        ...(canonicalUrlKey(abs) === curKey ? { current: true } : {}),
      });
    }
    if (chapters.length === 0) return null;
    const curIdx = chapters.findIndex((c) => c.current);
    const tocInfo = deriveKnownTocInfo(cleanUrl);
    const isTocPage = Boolean(tocInfo?.isTocPage) && curIdx < 0;
    return sanitizeNovelNav({
      isNovel: true,
      isTocPage,
      totalChapters: chapters.length,
      ...(curIdx >= 0 ? { currentIndex: curIdx } : {}),
      chapterLabel: curIdx >= 0 ? `${curIdx + 1} / ${chapters.length}` : `${chapters.length} bab`,
      firstUrl: chapters[0]?.url || null,
      prevUrl: curIdx > 0 ? chapters[curIdx - 1].url : null,
      nextUrl: isTocPage
        ? chapters[0]?.url || null
        : curIdx >= 0 && curIdx + 1 < chapters.length
          ? chapters[curIdx + 1].url
          : null,
      tocUrl: tocInfo?.tocUrl || null,
      chapters: chapters.slice(0, 1500),
    });
  } catch {
    return null;
  }
}

function extractChaptersFromSelectDropdowns(doc: Document, cleanUrl: string): NovelChapterLink[] {
  const curKey = canonicalUrlKey(cleanUrl);
  const base = new URL(cleanUrl);
  const ao3Work = base.hostname.includes('archiveofourown.org')
    ? base.pathname.match(/^\/works\/(\d+)/)
    : null;
  const ffStory = base.hostname.includes('fanfiction.net')
    ? base.pathname.match(/^\/s\/(\d+)\/\d+(\/[^/]*)?/)
    : null;

  const selects = Array.from(doc.querySelectorAll('select'));
  for (const sel of selects) {
    const opts = Array.from(sel.querySelectorAll('option'));
    if (opts.length < 2) continue;
    const meta = `${sel.id || ''} ${sel.name || ''} ${sel.className || ''}`.toLowerCase();
    const isExplicitChapSelect =
      /chap|episode|selected_id|single-chapter|chapter-jump|select-chapter/.test(meta);

    const parsed: NovelChapterLink[] = [];
    const seen = new Set<string>();
    for (const opt of opts) {
      const val = (opt.getAttribute('value') || '').trim();
      const label = decodeHtmlEntities((opt.textContent || '').replace(/\s+/g, ' ').trim());
      if (!val || val === '#' || val === '-1') continue;

      let abs: string | null = null;
      if (/^(https?:\/\/|\/)/i.test(val)) {
        abs = resolveSafeSiblingUrl(val, cleanUrl);
      } else if (ao3Work && /^\d+$/.test(val) && isExplicitChapSelect) {
        abs = `${base.origin}/works/${ao3Work[1]}/chapters/${val}`;
      } else if (ffStory && /^\d+$/.test(val) && isExplicitChapSelect) {
        abs = `${base.origin}/s/${ffStory[1]}/${val}${ffStory[2] || ''}`;
      } else if (isExplicitChapSelect && /^[a-z0-9/_-]+$/i.test(val)) {
        abs = resolveSafeSiblingUrl(val, cleanUrl);
      }

      if (!abs || !isCandidateChapterUrl(abs, cleanUrl)) continue;
      const key = canonicalUrlKey(abs);
      if (seen.has(key)) continue;
      seen.add(key);
      parsed.push({
        title: label || `Bab ${parsed.length + 1}`,
        url: abs,
        ...(opt.hasAttribute('selected') || key === curKey ? { current: true } : {}),
      });
    }

    if (parsed.length >= 2 && (isExplicitChapSelect || parsed.length >= 4)) {
      return parsed.slice(0, 1500);
    }
  }
  return [];
}

function deriveNumericChapterFallback(cleanUrl: string): Partial<NovelNavigation> {
  try {
    const u = new URL(cleanUrl);
    const host = u.hostname.toLowerCase();

    // Syosetu / Narou: https://ncode.syosetu.com/<ncode>/<num>/
    const syosetu = u.pathname.match(/^\/(n[a-z0-9]+)\/(\d+)\/?$/i);
    if (host.includes('syosetu.com') && syosetu) {
      const ncode = syosetu[1];
      const num = Number(syosetu[2]);
      const tocPage = num > 100 ? Math.floor((num - 1) / 100) + 1 : 1;
      return {
        isNovel: true,
        chapterLabel: `Bab ${num}`,
        prevUrl: num > 1 ? `${u.origin}/${ncode}/${num - 1}/` : null,
        nextUrl: `${u.origin}/${ncode}/${num + 1}/`,
        tocUrl: tocPage > 1 ? `${u.origin}/${ncode}/?p=${tocPage}` : `${u.origin}/${ncode}/`,
      };
    }

    // Hameln: https://syosetu.org/novel/<id>/<num>.html
    const hameln = u.pathname.match(/^\/novel\/(\d+)\/(\d+)\.html$/i);
    if (host.includes('syosetu.org') && hameln) {
      const id = hameln[1];
      const num = Number(hameln[2]);
      return {
        isNovel: true,
        chapterLabel: `Bab ${num}`,
        prevUrl: num > 1 ? `${u.origin}/novel/${id}/${num - 1}.html` : null,
        nextUrl: `${u.origin}/novel/${id}/${num + 1}.html`,
        tocUrl: `${u.origin}/novel/${id}/`,
      };
    }

    // FanFiction.net: https://www.fanfiction.net/s/<id>/<ch>/<slug>
    const ffnet = u.pathname.match(/^\/s\/(\d+)\/(\d+)(\/[^/]*)?$/i);
    if (host.includes('fanfiction.net') && ffnet) {
      const num = Number(ffnet[2]);
      const tail = ffnet[3] || '';
      return {
        isNovel: true,
        chapterLabel: `Bab ${num}`,
        prevUrl: num > 1 ? `${u.origin}/s/${ffnet[1]}/${num - 1}${tail}` : null,
        nextUrl: `${u.origin}/s/${ffnet[1]}/${num + 1}${tail}`,
      };
    }

    // Generic explicit chapter slug: /chapter-12, /bab-5, /episode-3
    const genericSlug = u.pathname.match(/^(.*\/(?:chapter|bab|episode|ep|ch)[-_/]?)(\d+)(\/?|\.html?)$/i);
    if (genericSlug) {
      const num = Number(genericSlug[2]);
      if (num >= 1 && num < 50000) {
        return {
          isNovel: true,
          chapterLabel: `Bab ${num}`,
          prevUrl: num > 1 ? `${u.origin}${genericSlug[1]}${num - 1}${genericSlug[3]}` : null,
          nextUrl: `${u.origin}${genericSlug[1]}${num + 1}${genericSlug[3]}`,
        };
      }
    }
  } catch {
    // ignore
  }
  return {};
}

const TOC_CTA_SKIP_RE =
  /^(最初から読む|1話から読む|一話から読む|1話目から読む|最新話|最新話を読む|続きを読む|start\s*reading|read\s*first|latest\s*chapter|continue\s*reading|baca\s*dari\s*awal)$/i;

function buildChaptersFromSiblingLinks(
  links: Array<{ title: string; url: string }>,
  cleanUrl: string,
  tocContextUrl?: string
): {
  chapters: NovelChapterLink[];
  prevUrl: string | null;
  nextUrl: string | null;
  firstUrl: string | null;
  currentIndex?: number;
  totalChapters?: number;
  chapterLabel?: string;
} {
  const curKey = canonicalUrlKey(cleanUrl);
  const basisUrl = tocContextUrl || cleanUrl;
  let siblingRe: RegExp | null = null;
  let hostLower = '';
  try {
    const u = new URL(basisUrl);
    hostLower = u.hostname.toLowerCase();
    const kaku = u.pathname.match(/^\/works\/(\d+)/);
    if (hostLower.includes('kakuyomu.jp') && kaku) {
      siblingRe = new RegExp(`^https?://[^/]*kakuyomu\\.jp/works/${kaku[1]}/episodes/\\d+`, 'i');
    } else if (hostLower.includes('syosetu.com')) {
      const syo = u.pathname.match(/^\/(n[a-z0-9]+)/i);
      if (syo) {
        siblingRe = new RegExp(`^https?://[^/]*syosetu\\.com/${syo[1]}/\\d+/?$`, 'i');
      }
    } else if (hostLower.includes('syosetu.org')) {
      const ham = u.pathname.match(/^\/novel\/(\d+)/);
      if (ham) {
        siblingRe = new RegExp(`^https?://[^/]*syosetu\\.org/novel/${ham[1]}/\\d+\\.html$`, 'i');
      }
    } else if (hostLower.includes('alphapolis.co.jp')) {
      const alpha = u.pathname.match(/^\/novel\/(\d+\/\d+)/);
      if (alpha) {
        siblingRe = new RegExp(
          `^https?://[^/]*alphapolis\\.co\\.jp/novel/${alpha[1]}/episode/\\d+`,
          'i'
        );
      }
    } else if (hostLower.includes('royalroad.com')) {
      const rr = u.pathname.match(/^\/fiction\/(\d+)/);
      if (rr) {
        siblingRe = new RegExp(`^https?://[^/]*royalroad\\.com/fiction/${rr[1]}/[^/]+/chapter/\\d+`, 'i');
      }
    } else if (hostLower.includes('scribblehub.com')) {
      const sh = u.pathname.match(/^\/(?:read|series)\/(\d+)/);
      if (sh) {
        siblingRe = new RegExp(`^https?://[^/]*scribblehub\\.com/read/${sh[1]}-[^/]+/chapter/\\d+`, 'i');
      }
    } else if (hostLower.includes('archiveofourown.org')) {
      const ao3 = u.pathname.match(/^\/works\/(\d+)/);
      if (ao3) {
        siblingRe = new RegExp(`^https?://[^/]*archiveofourown\\.org/works/${ao3[1]}/chapters/\\d+`, 'i');
      }
    } else {
      const novelRoot = u.pathname.match(/^(\/(?:b|book|novel|series|story|light-novel)\/[^/]+)/i);
      if (novelRoot) {
        const escaped = `${u.origin}${novelRoot[1]}/`.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        siblingRe = new RegExp(`^${escaped}[^/?#]+`, 'i');
      } else {
        const generic = u.pathname.match(
          /^(.*\/(?:chapter|bab|episode|episodes|ep|ch|part|bagian|cards)[-_/?]?)\d+/i
        );
        if (generic) {
          const escapedOrigin = `${u.origin}${generic[1]}`.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
          siblingRe = new RegExp(`^${escapedOrigin}\\d+`, 'i');
        }
      }
    }
  } catch {
    siblingRe = null;
  }

  const seen = new Set<string>();
  const chapters: NovelChapterLink[] = [];
  if (siblingRe) {
    for (const item of links) {
      if (!siblingRe.test(item.url)) continue;
      if (!isCandidateChapterUrl(item.url, basisUrl)) continue;
      const rawLabel = decodeHtmlEntities(
        item.title
          .replace(/\s*\d{4}年\d{1,2}月\d{1,2}日.*$/, '')
          .replace(/\s+/g, ' ')
          .trim()
      );
      if (TOC_CTA_SKIP_RE.test(rawLabel)) continue;
      const key = canonicalUrlKey(item.url);
      if (key === canonicalUrlKey(basisUrl) && deriveKnownTocInfo(basisUrl)?.isTocPage) continue;
      if (seen.has(key)) continue;
      seen.add(key);
      chapters.push({
        title: rawLabel || `Bab ${chapters.length + 1}`,
        url: item.url,
        ...(key === curKey ? { current: true } : {}),
      });
    }
  } else if (!NON_NOVEL_HOST_RE.test(hostLower)) {
    // Universal fallback for indie novel sites & blogs: cluster >= 3 links sharing an explicit chapter/episode/bab slug prefix
    const buckets = new Map<string, Array<{ title: string; url: string }>>();
    for (const item of links) {
      if (!isCandidateChapterUrl(item.url, basisUrl)) continue;
      try {
        const lu = new URL(item.url);
        const m = lu.pathname.match(
          /^(\/[^?#]*\/(?:chapter|chap|ch|episode|ep|bab|part|bagian|story|volume|vol)[-_/]?)([^/]+)\/?$/i
        );
        if (!m) continue;
        const prefix = `${lu.origin}${m[1].toLowerCase()}`;
        const list = buckets.get(prefix) || [];
        list.push(item);
        buckets.set(prefix, list);
      } catch {
        // ignore
      }
    }
    let bestBucket: Array<{ title: string; url: string }> = [];
    for (const list of buckets.values()) {
      if (list.length > bestBucket.length) bestBucket = list;
    }
    if (bestBucket.length >= 3) {
      for (const item of bestBucket) {
        const key = canonicalUrlKey(item.url);
        if (seen.has(key)) continue;
        seen.add(key);
        const rawLabel = decodeHtmlEntities(item.title.replace(/\s+/g, ' ').trim());
        if (TOC_CTA_SKIP_RE.test(rawLabel)) continue;
        chapters.push({
          title: rawLabel || `Bab ${chapters.length + 1}`,
          url: item.url,
          ...(key === curKey ? { current: true } : {}),
        });
      }
    }
  }

  const capped = chapters.slice(0, 1500);
  const curIdx = capped.findIndex((c) => c.current);
  const tocInfo = deriveKnownTocInfo(cleanUrl);
  const isToc = Boolean(tocInfo?.isTocPage) && curIdx < 0;
  return {
    chapters: capped,
    firstUrl: capped[0]?.url || null,
    prevUrl: curIdx > 0 ? capped[curIdx - 1].url : null,
    nextUrl: isToc
      ? capped[0]?.url || null
      : curIdx >= 0 && curIdx + 1 < capped.length
        ? capped[curIdx + 1].url
        : null,
    ...(curIdx >= 0 ? { currentIndex: curIdx } : {}),
    ...(capped.length > 0 ? { totalChapters: capped.length } : {}),
    chapterLabel:
      curIdx >= 0
        ? `${curIdx + 1} / ${capped.length}`
        : capped.length > 0
          ? `${capped.length} bab`
          : undefined,
  };
}

function extractNovelNavigationFromHtml(
  doc: Document,
  rawHtml: string,
  cleanUrl: string,
  extraLinks: Array<{ title: string; url: string }> = []
): NovelNavigation {
  const curKey = canonicalUrlKey(cleanUrl);
  const hostLower = (() => {
    try {
      return new URL(cleanUrl).hostname.toLowerCase();
    } catch {
      return '';
    }
  })();
  const isNonNovelHost = NON_NOVEL_HOST_RE.test(hostLower);
  const tocInfo = deriveKnownTocInfo(cleanUrl);
  const kakuEpMatch = cleanUrl.match(/kakuyomu\.jp\/works\/(\d+)\/episodes\/(\d+)/i);
  const kakuWorkMatch = !kakuEpMatch ? cleanUrl.match(/kakuyomu\.jp\/works\/(\d+)\/?$/i) : null;
  const nextDataNav = kakuEpMatch
    ? extractKakuyomuFromNextData(rawHtml, kakuEpMatch[1], kakuEpMatch[2])
    : kakuWorkMatch
      ? extractKakuyomuFromNextData(rawHtml, kakuWorkMatch[1], '')
      : extractRoyalRoadFromScriptData(rawHtml, cleanUrl);

  let prevUrl: string | null = nextDataNav?.prevUrl || null;
  let nextUrl: string | null = nextDataNav?.nextUrl || null;
  let tocUrl: string | null = nextDataNav?.tocUrl || tocInfo?.tocUrl || null;

  // W3C standard <link rel="prev|next">
  if (!prevUrl) {
    const linkPrev = doc.querySelector('link[rel="prev"], a[rel="prev"]')?.getAttribute('href');
    const resolved = linkPrev ? resolveSafeSiblingUrl(linkPrev, cleanUrl) : null;
    if (resolved && isCandidateChapterUrl(resolved, cleanUrl)) prevUrl = resolved;
  }
  if (!nextUrl) {
    const linkNext = doc.querySelector('link[rel="next"], a[rel="next"]')?.getAttribute('href');
    const resolved = linkNext ? resolveSafeSiblingUrl(linkNext, cleanUrl) : null;
    if (resolved && isCandidateChapterUrl(resolved, cleanUrl)) nextUrl = resolved;
  }

  // Site-specific & WordPress/novel pagination selectors
  if (!isNonNovelHost) {
    if (!prevUrl) {
      const el = doc.querySelector(
        '#contentMain-readPreviousEpisode, a[data-test="previous-episode-link"], .c-pager__item--before, .p-novel__pager-prev, #prev_chap, a.prev_page, a.prev-episode, .chapter-nav .prev a, .nav-previous a, .post-navigation .nav-previous a, a.prev.page-numbers'
      );
      const resolved = el?.getAttribute('href')
        ? resolveSafeSiblingUrl(el.getAttribute('href')!, cleanUrl)
        : null;
      if (resolved && isCandidateChapterUrl(resolved, cleanUrl)) prevUrl = resolved;
    }
    if (!nextUrl) {
      const el = doc.querySelector(
        '#contentMain-readNextEpisode, a[data-test="next-episode-link"], .c-pager__item--next, .p-novel__pager-next, #next_chap, a.next_page, a.next-episode, .chapter-nav .next a, .nav-next a, .post-navigation .nav-next a, a.next.page-numbers'
      );
      const resolved = el?.getAttribute('href')
        ? resolveSafeSiblingUrl(el.getAttribute('href')!, cleanUrl)
        : null;
      if (resolved && isCandidateChapterUrl(resolved, cleanUrl)) nextUrl = resolved;
    }
  }

  // Explicit TOC containers across novel platforms (Syosetu .p-eplist, Madara .wp-manga-chapter, NovelBin .list-chapter, etc.)
  const tocContainerLinks: Array<{ title: string; url: string }> = [];
  if (!isNonNovelHost) {
    for (const a of Array.from(
      doc.querySelectorAll(
        '.p-eplist a[href], .index_box a[href], .list-chapter a[href], .chapter-list a[href], #chapterlist a[href], .wp-manga-chapter a[href], .episode-list a[href], table#chapters a[href], ol.chapters a[href]'
      )
    )) {
      const abs = resolveSafeSiblingUrl(a.getAttribute('href') || '', cleanUrl);
      if (!abs || !isCandidateChapterUrl(abs, cleanUrl)) continue;
      const label = decodeHtmlEntities((a.textContent || '').replace(/\s+/g, ' ').trim());
      if (label && !TOC_CTA_SKIP_RE.test(label)) {
        tocContainerLinks.push({ title: label, url: abs });
      }
    }
  }

  const allAnchors: Array<{ title: string; url: string }> = [];
  for (const a of Array.from(doc.querySelectorAll('a[href]'))) {
    const abs = resolveSafeSiblingUrl(a.getAttribute('href') || '', cleanUrl);
    if (!abs) continue;
    const label = decodeHtmlEntities(
      (
        a.textContent ||
        a.getAttribute('aria-label') ||
        a.getAttribute('title') ||
        ''
      )
        .replace(/\s+/g, ' ')
        .trim()
    );
    const clsAndId = `${a.className || ''} ${a.id || ''}`;
    allAnchors.push({ title: label, url: abs });

    if (isNonNovelHost || canonicalUrlKey(abs) === curKey || !isCandidateChapterUrl(abs, cleanUrl)) {
      continue;
    }
    if (!nextUrl && label.length <= 48) {
      if (NEXT_LINK_RE.test(label) || /next[-_]?(ep|chap|page|post)|readNext/i.test(clsAndId)) {
        nextUrl = abs;
      }
    }
    if (!prevUrl && label.length <= 48) {
      if (
        PREV_LINK_RE.test(label) ||
        /prev(ious)?[-_]?(ep|chap|page|post)|readPrevious/i.test(clsAndId)
      ) {
        prevUrl = abs;
      }
    }
    if (!tocUrl && label.length <= 48 && TOC_LINK_RE.test(label)) {
      tocUrl = abs;
    }
  }

  // Merge links extracted by Jina Reader (data.links summary) as well
  for (const item of extraLinks) {
    const abs = resolveSafeSiblingUrl(item.url, cleanUrl);
    if (!abs) continue;
    const label = decodeHtmlEntities(item.title.replace(/\s+/g, ' ').trim());
    allAnchors.push({ title: label, url: abs });
    if (isNonNovelHost || canonicalUrlKey(abs) === curKey || !isCandidateChapterUrl(abs, cleanUrl)) {
      continue;
    }
    if (!nextUrl && label.length <= 48 && NEXT_LINK_RE.test(label)) nextUrl = abs;
    if (!prevUrl && label.length <= 48 && PREV_LINK_RE.test(label)) prevUrl = abs;
    if (!tocUrl && label.length <= 48 && TOC_LINK_RE.test(label)) tocUrl = abs;
  }

  const selectChapters = isNonNovelHost ? [] : extractChaptersFromSelectDropdowns(doc, cleanUrl);
  const siblingNav = buildChaptersFromSiblingLinks(allAnchors, cleanUrl);

  let chapters: NovelChapterLink[] = [];
  if (nextDataNav?.chapters && nextDataNav.chapters.length > 0) {
    chapters = nextDataNav.chapters;
  } else if (selectChapters.length >= Math.max(2, siblingNav.chapters.length)) {
    chapters = selectChapters;
  } else if (siblingNav.chapters.length >= 2) {
    chapters = siblingNav.chapters;
  } else if (tocContainerLinks.length >= 2) {
    const seenToc = new Set<string>();
    chapters = tocContainerLinks
      .filter((it) => {
        const k = canonicalUrlKey(it.url);
        if (seenToc.has(k)) return false;
        seenToc.add(k);
        return true;
      })
      .slice(0, 500)
      .map((it) => ({
        title: it.title,
        url: it.url,
        ...(canonicalUrlKey(it.url) === curKey ? { current: true } : {}),
      }));
  }

  const derivedCurIdx = chapters.findIndex((c) => c.current);
  if (!prevUrl && derivedCurIdx > 0) prevUrl = chapters[derivedCurIdx - 1].url;
  if (!nextUrl && derivedCurIdx >= 0 && derivedCurIdx + 1 < chapters.length) {
    nextUrl = chapters[derivedCurIdx + 1].url;
  }
  if (!prevUrl && siblingNav.prevUrl) prevUrl = siblingNav.prevUrl;
  if (!nextUrl && siblingNav.nextUrl) nextUrl = siblingNav.nextUrl;

  const fallback = isNonNovelHost ? {} : deriveNumericChapterFallback(cleanUrl);
  if (!prevUrl && fallback.prevUrl) prevUrl = fallback.prevUrl;
  if (!nextUrl && fallback.nextUrl) nextUrl = fallback.nextUrl;
  if (!tocUrl && fallback.tocUrl) tocUrl = fallback.tocUrl;

  const isNovel =
    !isNonNovelHost &&
    (Boolean(nextDataNav?.isNovel) ||
      Boolean(tocInfo) ||
      isKnownNovelUrl(cleanUrl) ||
      Boolean(fallback.isNovel) ||
      chapters.length >= 2 ||
      Boolean(prevUrl || nextUrl));

  const curIdx =
    nextDataNav?.currentIndex !== undefined
      ? nextDataNav.currentIndex
      : derivedCurIdx >= 0
        ? derivedCurIdx
        : siblingNav.currentIndex;
  const isTocPage =
    isNovel &&
    Boolean(
      nextDataNav?.isTocPage ||
      (tocInfo?.isTocPage && chapters.length >= 1) ||
      (chapters.length >= 5 && curIdx === undefined && !prevUrl)
    );
  if (isTocPage && !nextUrl && chapters[0]?.url) {
    nextUrl = chapters[0].url;
  }

  return sanitizeNovelNav({
    isNovel,
    isTocPage,
    seriesTitle: nextDataNav?.seriesTitle,
    chapterLabel:
      nextDataNav?.chapterLabel ||
      (curIdx !== undefined && chapters.length > 0
        ? `${curIdx + 1} / ${chapters.length}`
        : chapters.length > 0
          ? `${chapters.length} bab`
          : siblingNav.chapterLabel || fallback.chapterLabel),
    totalChapters: nextDataNav?.totalChapters || chapters.length || siblingNav.totalChapters,
    currentIndex: curIdx,
    firstUrl: nextDataNav?.firstUrl || chapters[0]?.url || siblingNav.firstUrl || null,
    prevUrl,
    nextUrl,
    tocUrl,
    chapters: chapters.length > 0 ? chapters : undefined,
  });
}

function extractNovelNavigationFromMarkdown(
  md: string,
  cleanUrl: string,
  extraLinks: Array<{ title: string; url: string }> = []
): NovelNavigation {
  const curKey = canonicalUrlKey(cleanUrl);
  const hostLower = (() => {
    try {
      return new URL(cleanUrl).hostname.toLowerCase();
    } catch {
      return '';
    }
  })();
  const isNonNovelHost = NON_NOVEL_HOST_RE.test(hostLower);
  const tocInfo = deriveKnownTocInfo(cleanUrl);
  const mdLinks: Array<{ title: string; url: string }> = [];
  const linkRe = /\[([^\]]{1,180})\]\((https?:\/\/[^)\s]+)\)/g;
  let m: RegExpExecArray | null;
  while ((m = linkRe.exec(md)) !== null) {
    const safe = resolveSafeSiblingUrl(m[2], cleanUrl);
    if (!safe) continue;
    mdLinks.push({ title: decodeHtmlEntities(m[1].replace(/\s+/g, ' ').trim()), url: safe });
  }
  for (const item of extraLinks) {
    const safe = resolveSafeSiblingUrl(item.url, cleanUrl);
    if (!safe) continue;
    mdLinks.push({ title: decodeHtmlEntities(item.title.replace(/\s+/g, ' ').trim()), url: safe });
  }

  let prevUrl: string | null = null;
  let nextUrl: string | null = null;
  let tocUrl: string | null = tocInfo?.tocUrl || null;

  if (!isNonNovelHost) {
    for (const item of mdLinks) {
      if (canonicalUrlKey(item.url) === curKey || !isCandidateChapterUrl(item.url, cleanUrl)) {
        continue;
      }
      if (!nextUrl && item.title.length <= 48 && NEXT_LINK_RE.test(item.title)) nextUrl = item.url;
      if (!prevUrl && item.title.length <= 48 && PREV_LINK_RE.test(item.title)) prevUrl = item.url;
      if (!tocUrl && item.title.length <= 48 && TOC_LINK_RE.test(item.title)) tocUrl = item.url;
    }
  }

  const siblingNav = isNonNovelHost
    ? { chapters: [], prevUrl: null, nextUrl: null, firstUrl: null }
    : buildChaptersFromSiblingLinks(mdLinks, cleanUrl);
  if (!prevUrl && siblingNav.prevUrl) prevUrl = siblingNav.prevUrl;
  if (!nextUrl && siblingNav.nextUrl) nextUrl = siblingNav.nextUrl;

  const fallback = isNonNovelHost ? {} : deriveNumericChapterFallback(cleanUrl);
  if (!prevUrl && fallback.prevUrl) prevUrl = fallback.prevUrl;
  if (!nextUrl && fallback.nextUrl) nextUrl = fallback.nextUrl;
  if (!tocUrl && fallback.tocUrl) tocUrl = fallback.tocUrl;

  const isNovel =
    !isNonNovelHost &&
    (Boolean(tocInfo) ||
      isKnownNovelUrl(cleanUrl) ||
      Boolean(fallback.isNovel) ||
      siblingNav.chapters.length >= 2 ||
      Boolean(prevUrl || nextUrl));

  return sanitizeNovelNav({
    isNovel,
    isTocPage: Boolean(tocInfo?.isTocPage && siblingNav.chapters.length >= 1),
    chapterLabel: siblingNav.chapterLabel || fallback.chapterLabel,
    totalChapters: siblingNav.totalChapters,
    currentIndex: siblingNav.currentIndex,
    firstUrl: siblingNav.firstUrl,
    prevUrl,
    nextUrl,
    tocUrl,
    chapters: siblingNav.chapters.length > 0 ? siblingNav.chapters : undefined,
  });
}

function applyChapterListToCurrentUrl(
  tocData: { seriesTitle?: string; tocUrl: string; chapters: NovelChapterLink[] },
  currentUrl: string
): NovelNavigation {
  const curKey = canonicalUrlKey(currentUrl);
  const tocInfo = deriveKnownTocInfo(currentUrl);
  const marked: NovelChapterLink[] = tocData.chapters.map((ch) => ({
    title: ch.title,
    ...(ch.titleDst ? { titleDst: ch.titleDst } : {}),
    url: ch.url,
    ...(canonicalUrlKey(ch.url) === curKey ? { current: true } : {}),
  }));
  const curIdx = marked.findIndex((c) => c.current);
  const isTocPage = Boolean(tocInfo?.isTocPage) && curIdx < 0;
  return sanitizeNovelNav({
    isNovel: true,
    isTocPage,
    seriesTitle: tocData.seriesTitle,
    totalChapters: marked.length,
    ...(curIdx >= 0 ? { currentIndex: curIdx } : {}),
    chapterLabel:
      curIdx >= 0
        ? `${curIdx + 1} / ${marked.length}`
        : marked.length > 0
          ? `${marked.length} bab`
          : undefined,
    firstUrl: marked[0]?.url || null,
    prevUrl: curIdx > 0 ? marked[curIdx - 1].url : null,
    nextUrl: isTocPage
      ? marked[0]?.url || null
      : curIdx >= 0 && curIdx + 1 < marked.length
        ? marked[curIdx + 1].url
        : null,
    tocUrl: tocData.tocUrl,
    chapters: marked,
  });
}

interface JinaFetchResult {
  title: string;
  finalUrl: string;
  html: string;
  content: string;
  links: Array<{ title: string; url: string }>;
}

function isSuspiciousTrackerPayload(
  requestedUrl: string,
  title: string,
  finalUrl: string,
  html: string,
  content: string
): boolean {
  const combined = `${title} ${content.slice(0, 300)} ${html.slice(0, 400)}`;
  if (/1x1 image|tacker probe|tracker probe|impact-ad\.jp|doubleclick\.net/i.test(combined)) {
    return true;
  }
  try {
    const reqHost = new URL(requestedUrl).hostname.toLowerCase().replace(/^www\./, '');
    const finHost = new URL(finalUrl).hostname.toLowerCase().replace(/^www\./, '');
    if (finHost && reqHost && finHost !== reqHost && !finHost.endsWith(`.${reqHost}`) && !reqHost.endsWith(`.${finHost}`)) {
      if (html.length < 2500 && content.length < 400) return true;
    }
  } catch {
    // ignore
  }
  return false;
}

async function fetchViaJinaInternal(
  cleanUrl: string,
  options: { format: 'html' | 'markdown'; noCache?: boolean; signal?: AbortSignal }
): Promise<JinaFetchResult | null> {
  // Never forward signed/tokenized URLs to public third-party reader proxies
  if (HAS_SENSITIVE_QUERY_RE.test(cleanUrl)) {
    return null;
  }
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-With-Links-Summary': 'true',
  };
  if (options.format === 'html') {
    headers['X-Return-Format'] = 'html';
  }
  if (options.noCache) {
    headers['X-No-Cache'] = 'true';
  }
  await jinaBucket.acquire(options.signal);
  const resp = await fetchWithTimeout(
    `https://r.jina.ai/${cleanUrl}`,
    {
      method: 'GET',
      headers,
    },
    15_000,
    options.signal
  );
  if (resp.status === 429 || resp.status >= 500) {
    const retryMs = computeBackoffDelayMs(0, resp.headers.get('Retry-After'), 1000, 8000);
    jinaBucket.onThrottle(retryMs);
    return null;
  }
  if (!resp.ok) return null;
  jinaBucket.onSuccess();
  const ctype = resp.headers.get('content-type') || '';
  if (ctype.includes('application/json')) {
    const json = await resp.json();
    const d = json?.data || {};
    const title = decodeHtmlEntities(String(d.title || '').trim());
    const finalUrl =
      (typeof d.finalUrl === 'string' && toSafeHttpUrl(d.finalUrl)) ||
      (typeof d.url === 'string' && toSafeHttpUrl(d.url)) ||
      cleanUrl;
    const html = typeof d.html === 'string' ? d.html : '';
    // Never substitute 1-line meta description as full article body when real HTML is returned
    const content =
      typeof d.content === 'string' && d.content.trim()
        ? d.content.trim()
        : !html && typeof d.description === 'string'
          ? d.description.trim()
          : '';
    const linksObj =
      d.links && typeof d.links === 'object' ? (d.links as Record<string, unknown>) : {};
    const links: Array<{ title: string; url: string }> = [];
    for (const [k, v] of Object.entries(linksObj)) {
      const safeLink = typeof v === 'string' ? toSafeHttpUrl(v) : null;
      if (safeLink) {
        links.push({ title: decodeHtmlEntities(k), url: safeLink });
      }
    }
    return { title, finalUrl, html, content, links };
  }
  const rawTxt = await resp.text();
  const titleMatch = rawTxt.match(/^Title:\s*(.+)$/m);
  return {
    title: decodeHtmlEntities(titleMatch ? titleMatch[1].trim() : ''),
    finalUrl: cleanUrl,
    html: options.format === 'html' && /<(html|body|article|div|p)\b/i.test(rawTxt) ? rawTxt : '',
    content: rawTxt,
    links: [],
  };
}

async function fetchViaJinaHtmlAndLinks(
  cleanUrl: string,
  options?: { noCache?: boolean; signal?: AbortSignal }
): Promise<JinaFetchResult | null> {
  try {
    const first = await fetchViaJinaInternal(cleanUrl, {
      format: 'html',
      noCache: Boolean(options?.noCache),
      signal: options?.signal,
    });
    if (
      first &&
      !options?.noCache &&
      (isSuspiciousTrackerPayload(cleanUrl, first.title, first.finalUrl, first.html, first.content) ||
        isChallengeOrBlockedPayload(first.title, first.html, first.content))
    ) {
      const fresh = await fetchViaJinaInternal(cleanUrl, {
        format: 'html',
        noCache: true,
        signal: options?.signal,
      });
      if (fresh) return fresh;
    }
    return first;
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError') throw err;
    return null;
  }
}

async function fetchViaJinaRenderedMarkdown(
  cleanUrl: string,
  options?: { noCache?: boolean; signal?: AbortSignal }
): Promise<JinaFetchResult | null> {
  try {
    const first = await fetchViaJinaInternal(cleanUrl, {
      format: 'markdown',
      noCache: Boolean(options?.noCache),
      signal: options?.signal,
    });
    if (
      first &&
      !options?.noCache &&
      (isSuspiciousTrackerPayload(cleanUrl, first.title, first.finalUrl, first.html, first.content) ||
        isChallengeOrBlockedPayload(first.title, first.html, first.content))
    ) {
      const fresh = await fetchViaJinaInternal(cleanUrl, {
        format: 'markdown',
        noCache: true,
        signal: options?.signal,
      });
      if (fresh) return fresh;
    }
    return first;
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError') throw err;
    return null;
  }
}

const MAIN_CONTENT_SELECTORS =
  '.widget-episodeBody, #novel_honbun, .p-novel__body, .js-novel-text, #honbun, #novelBoby, .novel-body, .episode-body, .main_text, .chapter-inner.chapter-content, .chapter-content, #chp_raw, .chp_raw, #chapters .userstuff, .userstuff.module, #storytext, #chr-content, #chapter-content, .reading-content, .chapter-c, .chapter__content, .cha-words, #chapter-container, #mw-content-text .mw-parser-output, .note-common-styles__textnote-body, .it-MdContent, .znc, .available-content, .body.markup, .markdown-body, [itemprop="articleBody"], .entry-content, .post-content, .post-body, .article-body, .article__body, article, main';

function scoreBestReadabilityRoot(doc: Document): Element | null {
  const candidates = Array.from(doc.querySelectorAll('article, main, section, div'));
  let bestEl: Element | null = null;
  let bestScore = 0;

  for (const el of candidates) {
    const clsAndId = `${el.className || ''} ${el.id || ''}`;
    if (/(sidebar|menu|navbar|footer|header|comment|related|recommend|widget|cookie|modal|popup|banner|breadcrumb)/i.test(clsAndId)) {
      continue;
    }
    const textLen = (el.textContent || '').replace(/\s+/g, ' ').trim().length;
    if (textLen < 160) continue;
    const pCount = el.querySelectorAll('p').length;
    const linkTextLen = Array.from(el.querySelectorAll('a')).reduce(
      (acc, a) => acc + ((a.textContent || '').trim().length || 0),
      0
    );
    const linkDensity = linkTextLen / Math.max(1, textLen);
    if (linkDensity > 0.55) continue;
    // Prefer denser, more specific containers over outer wrappers
    const depthBonus = el.tagName === 'ARTICLE' ? 1.25 : el.tagName === 'MAIN' ? 1.15 : 1;
    const score = (textLen * (1 - linkDensity) + pCount * 55) * depthBonus;
    if (score > bestScore) {
      bestScore = score;
      bestEl = el;
    }
  }
  return bestEl;
}

function extractNodeLinesPreservingBreaks(el: Element): string[] {
  const copy = el.cloneNode(true) as Element;
  copy.querySelectorAll('br').forEach((br) => {
    br.replaceWith(copy.ownerDocument.createTextNode('\n'));
  });
  return (copy.textContent || '')
    .split(/\r?\n+/)
    .map((line) => line.replace(/[\t\u00a0 ]+/g, ' ').trim())
    .filter((line) => line.length >= 1);
}

function extractCleanParagraphsFromHtml(doc: Document, titleHint = ''): string[] {
  const clone = doc.cloneNode(true) as Document;
  // Remove scripts, styles, chrome, ads, wiki clutter, and ruby readings (<rt>/<rp>) so prose stays clean
  clone
    .querySelectorAll(
      'script, style, noscript, svg, nav, footer, header, aside, form, rt, rp, [aria-hidden="true"], .widget-episodeNavigation, #contentMain-episodeNavigation, .c-pager, .p-novel__pager, .infobox, .navbox, .vertical-navbox, .sistersitebox, .hatnote, .mw-editsection, .reflist, .references, sup.reference, .toc, #toc, .noprint, .mw-jump-link, .sharedaddy, .jp-relatedposts, .comments-area, #comments, .cookie-banner, .advertisement, .ad-container'
    )
    .forEach((el) => el.remove());

  let root: Element | null = clone.querySelector(MAIN_CONTENT_SELECTORS);
  if (root && (root.textContent || '').replace(/\s+/g, ' ').trim().length < 80) {
    root = scoreBestReadabilityRoot(clone) || root;
  }
  if (!root) {
    root = scoreBestReadabilityRoot(clone) || clone.body;
  }
  if (!root) return [];

  const normTitle = decodeHtmlEntities(titleHint).replace(/\s+/g, ' ').trim().toLowerCase();
  const nodes = Array.from(root.querySelectorAll('h1, h2, h3, p, blockquote, li'));
  const paras: string[] = [];
  for (const n of nodes) {
    // Skip list items that are mostly navigation links
    if (n.tagName === 'LI') {
      const tLen = (n.textContent || '').trim().length;
      const aLen = Array.from(n.querySelectorAll('a')).reduce(
        (acc, a) => acc + ((a.textContent || '').trim().length || 0),
        0
      );
      if (tLen < 24 || aLen / Math.max(1, tLen) > 0.65) continue;
    }
    const hasBr = n.querySelector('br') !== null;
    const lines = hasBr
      ? extractNodeLinesPreservingBreaks(n)
      : [(n.textContent || '').replace(/\s+/g, ' ').trim()];
    for (const s of lines) {
      if (!s) continue;
      if (paras.length === 0 && normTitle && s.toLowerCase() === normTitle) continue;
      paras.push(s);
      if (paras.length >= 600) break;
    }
    if (paras.length >= 600) break;
  }

  if (paras.length >= 2) return paras;

  // Fallback for <br>-separated prose inside a single container (e.g. Aozora Bunko .main_text, Hameln #honbun, Blogger)
  const brLines = extractNodeLinesPreservingBreaks(root)
    .filter((s, idx) => s.length >= 1 && !(idx === 0 && normTitle && s.toLowerCase() === normTitle))
    .slice(0, 600);
  return brLines.length >= paras.length ? brLines : paras;
}

async function fetchKakuyomuEpisodeSidebarDirect(
  workId: string,
  sampleEpisodeUrl: string,
  currentUrl: string,
  signal?: AbortSignal
): Promise<NovelNavigation | null> {
  const epMatch = sampleEpisodeUrl.match(/kakuyomu\.jp\/works\/(\d+)\/episodes\/(\d+)/i);
  if (!epMatch || epMatch[1] !== workId) return null;
  const currentEpMatch = currentUrl.match(/kakuyomu\.jp\/works\/\d+\/episodes\/(\d+)/i);
  const currentEpId = currentEpMatch ? currentEpMatch[1] : '';
  const sidebarUrl = `https://kakuyomu.jp/works/${workId}/episodes/${epMatch[2]}/episode_sidebar`;

  const jinaHtml = await fetchViaJinaHtmlAndLinks(sidebarUrl, { signal }).catch(() => null);
  if (jinaHtml && !isChallengeOrBlockedPayload(jinaHtml.title, jinaHtml.html, jinaHtml.content)) {
    if (jinaHtml.html) {
      const parsed = extractKakuyomuEpisodeSidebar(jinaHtml.html, workId, currentEpId);
      if (parsed && (parsed.chapters?.length || 0) >= 2) return parsed;
    }
    if (jinaHtml.links.length > 0 || jinaHtml.content) {
      const mdNav = extractNovelNavigationFromMarkdown(
        jinaHtml.content,
        `https://kakuyomu.jp/works/${workId}`,
        jinaHtml.links
      );
      if ((mdNav.chapters?.length || 0) >= 2) {
        return applyChapterListToCurrentUrl(
          {
            seriesTitle: mdNav.seriesTitle,
            tocUrl: `https://kakuyomu.jp/works/${workId}`,
            chapters: mdNav.chapters || [],
          },
          currentUrl
        );
      }
    }
  }

  const jinaMd = await fetchViaJinaRenderedMarkdown(sidebarUrl, { signal }).catch(() => null);
  if (jinaMd && !isChallengeOrBlockedPayload(jinaMd.title, jinaMd.html, jinaMd.content)) {
    const mdNav = extractNovelNavigationFromMarkdown(
      jinaMd.content,
      `https://kakuyomu.jp/works/${workId}`,
      jinaMd.links
    );
    if ((mdNav.chapters?.length || 0) >= 2) {
      return applyChapterListToCurrentUrl(
        {
          seriesTitle: mdNav.seriesTitle,
          tocUrl: `https://kakuyomu.jp/works/${workId}`,
          chapters: mdNav.chapters || [],
        },
        currentUrl
      );
    }
  }
  return null;
}

async function fetchSeriesTocDirect(
  tocUrl: string,
  currentUrl: string
): Promise<NovelNavigation | null> {
  const safeToc = toSafeHttpUrl(tocUrl);
  if (!safeToc) return null;
  const cacheKey = canonicalUrlKey(safeToc);
  const kakuWorkMatch = safeToc.match(/kakuyomu\.jp\/works\/(\d+)\/?$/i);
  const kakuWorkId = kakuWorkMatch ? kakuWorkMatch[1] : '';
  const isTrustworthyToc = (rec?: { chapters?: NovelChapterLink[]; authoritative?: boolean } | null) => {
    const len = rec?.chapters?.length || 0;
    if (len < 2) return false;
    // Kakuyomu work pages collapse DOM links at ~7 visible episodes; never trust a <=10 chapter cache unless authoritative (__NEXT_DATA__ / episode_sidebar)
    if (kakuWorkId && len <= 10 && !rec?.authoritative) return false;
    return true;
  };

  const mem = seriesTocCache.get(cacheKey);
  if (isTrustworthyToc(mem)) {
    return applyChapterListToCurrentUrl(mem!, currentUrl);
  }
  const persistedToc = await idbGet<{
    seriesTitle?: string;
    tocUrl: string;
    chapters: NovelChapterLink[];
    authoritative?: boolean;
  }>('tocs', `toc::${cacheKey}`, 12 * 60 * 60 * 1000);
  if (isTrustworthyToc(persistedToc)) {
    seriesTocCache.set(cacheKey, persistedToc!);
    return applyChapterListToCurrentUrl(persistedToc!, currentUrl);
  }
  if (typeof window !== 'undefined') {
    try {
      const saved = window.sessionStorage.getItem(`tranx_toc_v3::${cacheKey}`);
      if (saved) {
        const parsed = JSON.parse(saved) as {
          seriesTitle?: string;
          tocUrl: string;
          chapters: NovelChapterLink[];
          authoritative?: boolean;
        };
        if (isTrustworthyToc(parsed)) {
          seriesTocCache.set(cacheKey, parsed);
          void idbPut('tocs', `toc::${cacheKey}`, parsed);
          return applyChapterListToCurrentUrl(parsed, currentUrl);
        }
      }
    } catch {
      // ignore storage errors
    }
  }

  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 22000);
  try {
    let bestNav: NovelNavigation | null = null;
    let fallbackTitle = '';
    let authoritative = false;

    // Primary: Jina Reader HTML + Links Summary with X-No-Cache (fast CORS, includes Kakuyomu __NEXT_DATA__, Syosetu TOC, RoyalRoad window.chapters!)
    const jinaRes = await fetchViaJinaHtmlAndLinks(safeToc, {
      noCache: true,
      signal: ctrl.signal,
    }).catch(() => null);

    if (
      jinaRes &&
      !isChallengeOrBlockedPayload(jinaRes.title, jinaRes.html, jinaRes.content) &&
      !hasMojibake(jinaRes.title + jinaRes.html.slice(0, 1200))
    ) {
      fallbackTitle = jinaRes.title
        .replace(/\s*[-–|]\s*(カクヨム|小説家になろう|ハーメルン|Kakuyomu|Royal Road|Scribble Hub).*$/i, '')
        .trim();
      if (jinaRes.html) {
        const doc = new DOMParser().parseFromString(jinaRes.html, 'text/html');
        bestNav = extractNovelNavigationFromHtml(doc, jinaRes.html, safeToc, jinaRes.links);
        if (
          kakuWorkId &&
          /__NEXT_DATA__/.test(jinaRes.html) &&
          (bestNav.chapters?.length || 0) >= 2
        ) {
          authoritative = true;
        }
      }
      if ((!bestNav || (bestNav.chapters?.length || 0) < 2) && (jinaRes.content || jinaRes.links.length > 0)) {
        const mdNav = extractNovelNavigationFromMarkdown(jinaRes.content, safeToc, jinaRes.links);
        if ((mdNav.chapters?.length || 0) > (bestNav?.chapters?.length || 0)) {
          bestNav = mdNav;
        }
      }
    }

    // Kakuyomu fast authoritative rescue: /episode_sidebar (37 KB, lists ALL 84-1500 episodes cleanly!)
    if (kakuWorkId && (!authoritative || (bestNav?.chapters?.length || 0) <= 10)) {
      const sampleEpUrl = /kakuyomu\.jp\/works\/\d+\/episodes\/\d+/i.test(currentUrl)
        ? currentUrl
        : bestNav?.chapters?.[0]?.url || '';
      if (sampleEpUrl) {
        const sidebarNav = await fetchKakuyomuEpisodeSidebarDirect(
          kakuWorkId,
          sampleEpUrl,
          currentUrl,
          ctrl.signal
        ).catch(() => null);
        if (sidebarNav && (sidebarNav.chapters?.length || 0) >= (bestNav?.chapters?.length || 0)) {
          bestNav = mergeNovelNav(sidebarNav, bestNav);
          authoritative = true;
        }
      }
    }

    // Secondary: Jina Rendered Markdown + Links Summary when HTML TOC was empty/challenged/mojibake
    if (!bestNav || (bestNav.chapters?.length || 0) < 2) {
      const mdRes = await fetchViaJinaRenderedMarkdown(safeToc, {
        noCache: true,
        signal: ctrl.signal,
      }).catch(() => null);
      if (mdRes && !isChallengeOrBlockedPayload(mdRes.title, mdRes.html, mdRes.content)) {
        if (!fallbackTitle && mdRes.title) {
          fallbackTitle = mdRes.title
            .replace(/\s*[-–|]\s*(カクヨム|小説家になろう|ハーメルン|Kakuyomu|Royal Road|Scribble Hub).*$/i, '')
            .trim();
        }
        const mdNav = extractNovelNavigationFromMarkdown(mdRes.content, safeToc, mdRes.links);
        if ((mdNav.chapters?.length || 0) > (bestNav?.chapters?.length || 0)) {
          bestNav = mdNav;
        }
      }
      // If Markdown gave us Episode 1 on Kakuyomu (only 7 visible), expand to ALL episodes via /episode_sidebar!
      if (kakuWorkId && !authoritative && bestNav?.chapters?.[0]?.url) {
        const sidebarNav = await fetchKakuyomuEpisodeSidebarDirect(
          kakuWorkId,
          bestNav.chapters[0].url,
          currentUrl,
          ctrl.signal
        ).catch(() => null);
        if (sidebarNav && (sidebarNav.chapters?.length || 0) > (bestNav.chapters?.length || 0)) {
          bestNav = mergeNovelNav(sidebarNav, bestNav);
          authoritative = true;
        }
      }
    }

    // Tertiary fallback: CORS HTML proxies if Jina didn't find >= 2 chapters (or Kakuyomu still partial!)
    if (!bestNav || (bestNav.chapters?.length || 0) < 2 || (kakuWorkId && !authoritative && (bestNav.chapters?.length || 0) <= 10)) {
      const raw = await fetchRawHtmlViaCorsProxy(safeToc, ctrl.signal).catch(() => null);
      if (raw && !isChallengeOrBlockedPayload('', raw, '')) {
        const doc = new DOMParser().parseFromString(raw, 'text/html');
        const proxyNav = extractNovelNavigationFromHtml(doc, raw, safeToc);
        if ((proxyNav.chapters?.length || 0) > (bestNav?.chapters?.length || 0)) {
          bestNav = proxyNav;
          if (kakuWorkId && /__NEXT_DATA__/.test(raw)) authoritative = true;
        }
      }
    }

    const bestChapters = bestNav?.chapters || [];
    if (bestChapters.length < 2) return null;

    const rawSeriesTitle = bestNav?.seriesTitle || fallbackTitle || '';
    const seriesTitle =
      rawSeriesTitle && !isChallengeOrBlockedPayload(rawSeriesTitle, '', '')
        ? rawSeriesTitle
        : undefined;
    const tocRecord = {
      ...(seriesTitle ? { seriesTitle } : {}),
      tocUrl: safeToc,
      chapters: bestChapters,
      authoritative: authoritative || !kakuWorkId || bestChapters.length > 10,
    };
    if (tocRecord.authoritative) {
      seriesTocCache.set(cacheKey, tocRecord);
      void idbPut('tocs', `toc::${cacheKey}`, tocRecord);
      if (typeof window !== 'undefined') {
        try {
          window.sessionStorage.setItem(`tranx_toc_v3::${cacheKey}`, JSON.stringify(tocRecord));
        } catch {
          // ignore quota
        }
      }
    }
    return applyChapterListToCurrentUrl(tocRecord, currentUrl);
  } finally {
    window.clearTimeout(timer);
  }
}

export async function translateChapterTitlesDirect(params: {
  chapters: NovelChapterLink[];
  mode: ModePair;
  titleId?: string;
  tocKey: string;
  seriesTitle?: string;
  signal?: AbortSignal;
  onProgress?: (partialMap: Record<string, string>, doneCount: number, totalCount: number) => void;
}): Promise<Record<string, string>> {
  const { chapters, mode, titleId, tocKey, seriesTitle, signal, onProgress } = params;
  if (!chapters.length || isMockOnlyLocalE2E()) return {};
  const { tgt } = parseModePair(mode);
  const cacheKey = `${tocKey}::${mode}`;
  let initialMap = translatedChapterTitlesCache.get(cacheKey);
  if (!initialMap) {
    const idbTitles = await idbGet<Record<string, string>>(
      'tocs',
      `titles::${cacheKey}`,
      24 * 60 * 60 * 1000
    );
    if (idbTitles && typeof idbTitles === 'object') {
      initialMap = idbTitles;
      translatedChapterTitlesCache.set(cacheKey, { ...idbTitles });
    }
  }
  const map: Record<string, string> = { ...(initialMap || {}) };

  const uniqueChapters: NovelChapterLink[] = [];
  const seenUrls = new Set<string>();
  for (const ch of chapters) {
    if (!ch.url || seenUrls.has(ch.url)) continue;
    seenUrls.add(ch.url);
    uniqueChapters.push(ch);
    // Self-heal any previously cached chapter title that was left untranslated in source script
    if (map[ch.url] && isStillUntranslatedForTarget(ch.title, map[ch.url], tgt)) {
      delete map[ch.url];
    }
  }
  if (
    map.__seriesTitle__ &&
    (isChallengeOrBlockedPayload(map.__seriesTitle__, '', '') ||
      (seriesTitle && isStillUntranslatedForTarget(seriesTitle, map.__seriesTitle__, tgt)))
  ) {
    delete map.__seriesTitle__;
  }

  const totalCount = uniqueChapters.length;
  const countTranslated = () =>
    uniqueChapters.reduce((acc, ch) => acc + (map[ch.url] ? 1 : 0), 0);

  const cleanSeriesTitle =
    seriesTitle && !isChallengeOrBlockedPayload(seriesTitle, '', '') ? seriesTitle.trim() : '';
  const needsSeries = Boolean(cleanSeriesTitle && !map.__seriesTitle__);
  if (countTranslated() >= totalCount && !needsSeries) {
    onProgress?.({ ...map }, totalCount, totalCount);
    return { ...map };
  }

  // Emit cached chapters immediately so UI updates with 0 delay
  const initialDone = countTranslated();
  if (initialDone > 0) {
    onProgress?.({ ...map }, initialDone, totalCount);
  }

  // Build priority-ordered list covering 100% of ALL chapters (visible window first, then every remaining chapter!)
  const curIdx = uniqueChapters.findIndex((c) => c.current);
  const priorityOrdered: NovelChapterLink[] = [];
  const queuedUrls = new Set<string>();
  const enqueueRange = (from: number, to: number) => {
    const start = Math.max(0, from);
    const end = Math.min(uniqueChapters.length, to);
    for (let i = start; i < end; i += 1) {
      const ch = uniqueChapters[i];
      if (!ch || queuedUrls.has(ch.url) || map[ch.url] || !ch.title.trim()) continue;
      queuedUrls.add(ch.url);
      priorityOrdered.push(ch);
    }
  };

  if (curIdx >= 0) {
    enqueueRange(curIdx - 12, curIdx + 33);
    enqueueRange(curIdx + 33, uniqueChapters.length);
    enqueueRange(0, curIdx - 12);
  } else {
    enqueueRange(0, uniqueChapters.length);
  }

  // Process ALL pending chapters in truncation-safe 54-chapter waves (1 paced wave at a time across adaptive 2-4 GTX workers)
  const WAVE_SIZE = 54;
  const waveSpecs: Array<{ chapters: NovelChapterLink[]; includeSeries: boolean }> = [];
  const waveCount = Math.max(1, Math.ceil(priorityOrdered.length / WAVE_SIZE));
  for (let w = 0; w < waveCount; w += 1) {
    const waveChapters = priorityOrdered.slice(w * WAVE_SIZE, (w + 1) * WAVE_SIZE);
    const includeSeries = w === 0 && needsSeries && Boolean(cleanSeriesTitle);
    if (waveChapters.length === 0 && !includeSeries) break;
    waveSpecs.push({ chapters: waveChapters, includeSeries });
  }

  const runWaves = async (
    specs: Array<{ chapters: NovelChapterLink[]; includeSeries: boolean }>,
    allowFallbackStore: boolean
  ) => {
    await runConcurrentPool(specs, 1, async ({ chapters: waveChapters, includeSeries }) => {
      if (signal?.aborted) return;
      const inputs = includeSeries
        ? [cleanSeriesTitle, ...waveChapters.map((c) => c.title.trim())]
        : waveChapters.map((c) => c.title.trim());

      try {
        const { outputs } = await translateParagraphsDirect({
          paragraphs: inputs,
          mode,
          titleId,
          signal,
        });
        if (signal?.aborted) return;
        let offset = 0;
        if (includeSeries) {
          const outSeries = outputs[0];
          if (
            outSeries &&
            (allowFallbackStore || !isStillUntranslatedForTarget(cleanSeriesTitle, outSeries, tgt))
          ) {
            map.__seriesTitle__ = outSeries;
          }
          offset = 1;
        }
        waveChapters.forEach((ch, idx) => {
          const translated = outputs[idx + offset];
          if (
            translated &&
            (allowFallbackStore || !isStillUntranslatedForTarget(ch.title, translated, tgt))
          ) {
            map[ch.url] = translated;
          }
        });
        translatedChapterTitlesCache.set(cacheKey, { ...map });
        onProgress?.({ ...map }, countTranslated(), totalCount);
      } catch (err) {
        if ((err as { name?: string })?.name === 'AbortError' || signal?.aborted) return;
        // Continue remaining waves gracefully if a single wave fails transiently
      }
    });
  };

  await runWaves(waveSpecs, false);

  // Automatic mop-up pass: retry any chapter titles that remained untranslated in compact 12-item batches
  if (!signal?.aborted) {
    const remaining = uniqueChapters.filter((ch) => ch.title.trim() && !map[ch.url]);
    const stillNeedsSeries = Boolean(cleanSeriesTitle && !map.__seriesTitle__);
    if (remaining.length > 0 || stillNeedsSeries) {
      const mopSpecs: Array<{ chapters: NovelChapterLink[]; includeSeries: boolean }> = [];
      const mopWaves = Math.max(1, Math.ceil(remaining.length / 12));
      for (let w = 0; w < mopWaves; w += 1) {
        const slice = remaining.slice(w * 12, (w + 1) * 12);
        const inc = w === 0 && stillNeedsSeries;
        if (slice.length === 0 && !inc) break;
        mopSpecs.push({ chapters: slice, includeSeries: inc });
      }
      await runWaves(mopSpecs, false);
    }
  }

  if (Object.keys(map).length > 0) {
    void idbPut('tocs', `titles::${cacheKey}`, { ...map });
  }
  return { ...map };
}

function mergeNovelNav(primary: NovelNavigation, secondary?: NovelNavigation | null): NovelNavigation {
  if (!secondary) return sanitizeNovelNav(primary);
  const chapters =
    (primary.chapters?.length || 0) >= (secondary.chapters?.length || 0)
      ? primary.chapters
      : secondary.chapters;
  const currentIndex =
    primary.currentIndex !== undefined ? primary.currentIndex : secondary.currentIndex;
  const totalChapters =
    (chapters?.length || 0) || primary.totalChapters || secondary.totalChapters;
  return sanitizeNovelNav({
    isNovel: primary.isNovel || secondary.isNovel,
    isTocPage: primary.isTocPage || secondary.isTocPage,
    seriesTitle: primary.seriesTitle || secondary.seriesTitle,
    chapterLabel: primary.chapterLabel || secondary.chapterLabel,
    totalChapters,
    currentIndex,
    firstUrl: primary.firstUrl || secondary.firstUrl || chapters?.[0]?.url || null,
    prevUrl: primary.prevUrl || secondary.prevUrl || null,
    nextUrl: primary.nextUrl || secondary.nextUrl || null,
    tocUrl: primary.tocUrl || secondary.tocUrl || null,
    chapters,
  });
}

async function decodeHtmlResponseWithCharset(resp: Response): Promise<string> {
  let bytes: Uint8Array;
  try {
    bytes = await readBoundedBytes(resp, 5 * 1024 * 1024, false);
  } catch {
    return '';
  }
  const ctype = resp.headers.get('content-type') || '';
  const headAscii = new TextDecoder('latin1').decode(bytes.subarray(0, Math.min(bytes.length, 2048)));
  const charsetMatch = `${ctype} ${headAscii}`.match(/charset\s*=\s*["']?([a-zA-Z0-9_-]+)/i);
  const rawCharset = (charsetMatch?.[1] || 'utf-8').toLowerCase();
  const normalizedCharset =
    rawCharset === 'sjis' || rawCharset === 'x-sjis' || rawCharset === 'shift_jis' || rawCharset === 'shift-jis'
      ? 'shift_jis'
      : rawCharset === 'eucjp' || rawCharset === 'euc-jp' || rawCharset === 'euc_jp'
        ? 'euc-jp'
        : 'utf-8';
  try {
    return new TextDecoder(normalizedCharset, { fatal: false }).decode(bytes);
  } catch {
    return new TextDecoder('utf-8', { fatal: false }).decode(bytes);
  }
}

async function fetchRawHtmlViaCorsProxy(
  cleanUrl: string,
  signal?: AbortSignal
): Promise<string | null> {
  // Never forward signed/tokenized URLs to public third-party CORS proxies
  if (HAS_SENSITIVE_QUERY_RE.test(cleanUrl)) {
    return null;
  }
  const proxies: Array<{ key: string; url: string }> = [
    { key: 'allorigins', url: `https://api.allorigins.win/raw?url=${encodeURIComponent(cleanUrl)}` },
    { key: 'codetabs', url: `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(cleanUrl)}` },
  ];
  const activeProxies = proxies.filter((p) => !getProxyBreaker(p.key).isOpen());
  if (activeProxies.length === 0) return null;

  // Race healthy proxies in parallel with per-proxy circuit breakers & CloudFront/WAF 403 rejection
  const attempts = activeProxies.map(async ({ key, url: endpoint }) => {
    const breaker = getProxyBreaker(key);
    try {
      const resp = await fetchWithTimeout(endpoint, { method: 'GET' }, 7000, signal);
      if (!resp.ok) {
        breaker.recordFailure();
        throw new Error(`HTTP ${resp.status}`);
      }
      const html = await decodeHtmlResponseWithCharset(resp);
      if (!html || !/<(html|body|article|div|p)\b/i.test(html)) {
        throw new Error('Non-HTML payload');
      }
      if (isChallengeOrBlockedPayload('', html, '')) {
        throw new Error('Blocked challenge/WAF payload');
      }
      breaker.recordSuccess();
      return html;
    } catch (err) {
      if (signal?.aborted) throw err;
      throw err;
    }
  });

  try {
    return await Promise.any(attempts);
  } catch (err) {
    if (signal?.aborted) {
      throw Object.assign(new Error('Aborted'), { name: 'AbortError' });
    }
    void err;
    return null;
  }
}

const MD_BOILERPLATE_LINE_RE =
  /^(skip to (main )?content|jump to content|toggle navigation|menu|log ?in|sign ?in|sign ?up|register|cookie policy|privacy policy|terms of service|all rights reserved|back to top|↑ページトップへ|閉じる|ログイン|ブックマークへ移動|ヘルプセンター)$/i;

function stripInlineMarkdownFormatting(text: string): string {
  return decodeHtmlEntities(text)
    .replace(/\*{4,}/g, ' ')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/__([^_\n]+)__/g, '$1')
    .replace(/(^|[\s([{"'“‘])\*([^*\n]+)\*(?=[\s)\]}.,!?;:"'”’]|$)/g, '$1$2')
    .replace(/(^|[\s([{"'“‘])_([^_\n]+)_(?=[\s)\]}.,!?;:"'”’]|$)/g, '$1$2')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/^>\s?/, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function cleanReaderMarkdownToParagraphs(md: string, titleHint = ''): string[] {
  const lines = md.split(/\r?\n/);
  const paras: string[] = [];
  let buf: string[] = [];
  const normTitle = decodeHtmlEntities(titleHint).replace(/\s+/g, ' ').trim().toLowerCase();

  const flush = () => {
    if (!buf.length) return;
    const joined = stripInlineMarkdownFormatting(buf.join(' '));
    buf = [];
    if (joined.length < 2) return;
    if (MD_BOILERPLATE_LINE_RE.test(joined)) return;
    if (paras.length === 0 && normTitle && joined.toLowerCase() === normTitle) return;
    paras.push(joined);
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flush();
      continue;
    }
    if (/^(Title|URL Source|Published Time|Markdown Content):/i.test(line)) continue;
    if (/^[-*_]{3,}$/.test(line) || /^\|[\s:|-]+\|$/.test(line)) {
      flush();
      continue;
    }
    if (/^!\[[^\]]*\]\([^)]+\)$/.test(line)) continue;

    // Strip linked images and markdown links while keeping readable anchor text
    const unlinked = line
      .replace(/\[!\[[^\]]*\]\([^)]+\)\]\([^)]+\)/g, '')
      .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .trim();
    if (!unlinked) continue;

    if (/^#{1,6}\s+/.test(unlinked)) {
      flush();
      const heading = stripInlineMarkdownFormatting(unlinked.replace(/^#{1,6}\s+/, ''));
      if (heading && !MD_BOILERPLATE_LINE_RE.test(heading)) {
        if (!(paras.length === 0 && normTitle && heading.toLowerCase() === normTitle)) {
          paras.push(heading);
        }
      }
    } else if (/^[-*+]\s+/.test(unlinked)) {
      flush();
      const bulletText = stripInlineMarkdownFormatting(unlinked.replace(/^[-*+]\s+/, ''));
      if (bulletText.length >= 2 && !MD_BOILERPLATE_LINE_RE.test(bulletText)) {
        paras.push(bulletText);
      }
    } else {
      buf.push(unlinked);
    }
  }
  flush();
  return paras.slice(0, 600);
}

async function fetchWebArticleDirect(
  rawUrl: string,
  options?: { needRawHtml?: boolean; signal?: AbortSignal }
): Promise<CachedWebEntry> {
  const cleanUrl = normalizeWebUrl(rawUrl);
  let cached = webArticleCache.get(cleanUrl);
  if (cached && isBlockedArticleOrTranslation(cached.titleSrc, cached.srcParas, '')) {
    webArticleCache.delete(cleanUrl);
    void idbDelete('articles', `art::${cleanUrl}`);
    cached = undefined;
  }
  if (cached?.rawHtml && isChallengeOrBlockedPayload('', cached.rawHtml, '')) {
    cached = { ...cached, rawHtml: undefined, htmlFetchAttempted: true };
    webArticleCache.set(cleanUrl, cached);
  }
  if (cached && (!options?.needRawHtml || cached.rawHtml || cached.htmlFetchAttempted)) {
    return cached;
  }

  if (!cached) {
    const idbArticle = await idbGet<CachedWebEntry>(
      'articles',
      `art::${cleanUrl}`,
      6 * 60 * 60 * 1000
    );
    if (idbArticle && Array.isArray(idbArticle.srcParas) && idbArticle.srcParas.length > 0) {
      // Self-heal: completely purge any poisoned CloudFront/WAF 403 article stored in IndexedDB!
      if (isBlockedArticleOrTranslation(idbArticle.titleSrc, idbArticle.srcParas, '')) {
        void idbDelete('articles', `art::${cleanUrl}`);
      } else {
        const cleanRawHtml =
          idbArticle.rawHtml && !isChallengeOrBlockedPayload('', idbArticle.rawHtml, '')
            ? idbArticle.rawHtml
            : undefined;
        const sanitizedEntry: CachedWebEntry = {
          ...idbArticle,
          rawHtml: cleanRawHtml,
          htmlFetchAttempted: true,
        };
        webArticleCache.set(cleanUrl, sanitizedEntry);
        webArticleCache.set(sanitizedEntry.url, sanitizedEntry);
        cached = sanitizedEntry;
        if (!options?.needRawHtml || cached.rawHtml || cached.htmlFetchAttempted) {
          return cached;
        }
      }
    }
  }

  const inflightKey = `${cleanUrl}::${Boolean(options?.needRawHtml)}`;
  const existingInflight = inFlightArticleFetches.get(inflightKey);
  if (existingInflight) {
    return existingInflight;
  }

  const work = fetchWebArticleDirectInner(cleanUrl, cached, options).finally(() => {
    inFlightArticleFetches.delete(inflightKey);
  });
  inFlightArticleFetches.set(inflightKey, work);
  return work;
}

async function fetchWebArticleDirectInner(
  cleanUrl: string,
  cached: CachedWebEntry | undefined,
  options?: { needRawHtml?: boolean; signal?: AbortSignal }
): Promise<CachedWebEntry> {
  const host = new URL(cleanUrl).hostname;
  const ctrl = new AbortController();
  const onOuterAbort = () => ctrl.abort();
  if (options?.signal) {
    if (options.signal.aborted) ctrl.abort();
    else options.signal.addEventListener('abort', onOuterAbort, { once: true });
  }
  const timer = window.setTimeout(() => ctrl.abort(), 24000);

  try {
    // Fast-path: Direct Image URL (manga page / comic strip / social image CDN)
    if (isLikelyDirectImageUrl(cleanUrl)) {
      const normalizedImgUrl = normalizeSocialImageUrl(cleanUrl);
      const fileLabel = safePathFileName(new URL(normalizedImgUrl).pathname, 'Gambar Komik');
      const comicMeta: MangaLinkMeta = {
        isComic: true,
        isDirectImage: true,
        layout: 'single_image',
        pageCount: 1,
        pages: [{ index: 0, url: normalizedImgUrl, alt: fileLabel }],
        drmProtected: false,
      };
      const entry: CachedWebEntry = {
        url: normalizedImgUrl,
        host,
        titleId: deriveSeriesTitleId(normalizedImgUrl),
        titleSrc: fileLabel,
        srcParas: [],
        detectedSource: 'ja',
        novelNav: sanitizeNovelNav({ isNovel: false }),
        comicMeta,
        htmlFetchAttempted: true,
      };
      webArticleCache.set(cleanUrl, entry);
      webArticleCache.set(normalizedImgUrl, entry);
      return entry;
    }

    let titleSrc = cached?.titleSrc || host;
    let srcParas: string[] = cached?.srcParas || [];
    let finalUrl = cached?.url || cleanUrl;
    let rawMarkdown = cached?.rawMarkdown || '';
    let rawHtml = cached?.rawHtml || '';
    let jinaLinks: Array<{ title: string; url: string }> = [];
    let navFromMd: NovelNavigation | null = null;
    let navFromHtml: NovelNavigation | null = null;
    let hitAntiBotChallenge = false;

    const knownToc = deriveKnownTocInfo(cleanUrl);

    // Primary fetch: Jina Reader HTML + Links Summary (preserves full DOM, __NEXT_DATA__, <select> chapters, & Situs Terjemahan layout!)
    const jinaPromise =
      srcParas.length > 0 && rawHtml
        ? Promise.resolve()
        : (async () => {
          const res = await fetchViaJinaHtmlAndLinks(cleanUrl, {
            noCache: Boolean(knownToc?.isTocPage),
            signal: ctrl.signal,
          });
          if (!res) return;
          const challengeDetected = isChallengeOrBlockedPayload(res.title, res.html, res.content);
          const mojibakeDetected = hasMojibake(`${res.title}\n${res.html.slice(0, 2000)}`);
          if (challengeDetected) {
            hitAntiBotChallenge = true;
            return;
          }
          if (mojibakeDetected) {
            // Shift_JIS / EUC-JP mojibake in HTML mode -> let Jina Rendered Markdown decode UTF-8 cleanly
            return;
          }
          if (res.title) titleSrc = res.title;
          if (
            res.finalUrl &&
            !isSuspiciousTrackerPayload(cleanUrl, res.title, res.finalUrl, res.html, res.content)
          ) {
            finalUrl = res.finalUrl;
          }
          if (res.html) rawHtml = res.html;
          if (res.content) rawMarkdown = res.content;
          if (res.links.length > 0) jinaLinks = res.links;
          if (res.content || res.links.length > 0) {
            navFromMd = extractNovelNavigationFromMarkdown(res.content, finalUrl, res.links);
          }
          if (res.content && srcParas.length === 0) {
            srcParas = cleanReaderMarkdownToParagraphs(res.content, titleSrc);
          }
        })();

    const earlyTocPromise =
      knownToc && !knownToc.isTocPage
        ? fetchSeriesTocDirect(knownToc.tocUrl, cleanUrl).catch(() => null)
        : Promise.resolve(null);

    const [, earlyTocNav] = await Promise.all([jinaPromise, earlyTocPromise]);

    if (rawHtml) {
      const doc = new DOMParser().parseFromString(rawHtml, 'text/html');
      navFromHtml = extractNovelNavigationFromHtml(doc, rawHtml, finalUrl, jinaLinks);
      if (!titleSrc || titleSrc === host) {
        const docTitle = decodeHtmlEntities((doc.title || '').trim());
        if (docTitle && !hasMojibake(docTitle)) titleSrc = docTitle;
      }
      const htmlParas = extractCleanParagraphsFromHtml(doc, titleSrc);
      if (htmlParas.length > srcParas.length || srcParas.length < 2) {
        if (htmlParas.length > 0) srcParas = htmlParas;
      }
    }

    // Automatic Smart Fallback: Jina Rendered Markdown mode!
    // Rescues Syosetu episodes (HTML=0), RoyalRoad (Cloudflare HTML), Aozora Bunko (Shift_JIS mojibake), and JS-rendered SPAs!
    const htmlYieldedPoorProse =
      srcParas.length < 2 && !(navFromHtml?.isTocPage && (navFromHtml.chapters?.length || 0) >= 2);
    if (htmlYieldedPoorProse) {
      const mdRes = await fetchViaJinaRenderedMarkdown(cleanUrl, {
        noCache: hitAntiBotChallenge,
        signal: ctrl.signal,
      });
      if (mdRes) {
        if (isChallengeOrBlockedPayload(mdRes.title, mdRes.html, mdRes.content)) {
          hitAntiBotChallenge = true;
        } else {
          hitAntiBotChallenge = false;
          if (mdRes.title && !hasMojibake(mdRes.title)) titleSrc = mdRes.title;
          if (
            mdRes.finalUrl &&
            !isSuspiciousTrackerPayload(cleanUrl, mdRes.title, mdRes.finalUrl, mdRes.html, mdRes.content)
          ) {
            finalUrl = mdRes.finalUrl;
          }
          if (mdRes.content) rawMarkdown = mdRes.content;
          if (mdRes.links.length > 0) {
            jinaLinks = [...jinaLinks, ...mdRes.links];
          }
          const mdParas = cleanReaderMarkdownToParagraphs(mdRes.content, titleSrc);
          if (mdParas.length > srcParas.length) {
            srcParas = mdParas;
            // Clear empty/shell rawHtml if HTML extraction failed so Situs Terjemahan renders clean semantic content
            if (rawHtml) {
              const checkDoc = new DOMParser().parseFromString(rawHtml, 'text/html');
              if (extractCleanParagraphsFromHtml(checkDoc, titleSrc).length < 2) {
                rawHtml = '';
              }
            }
          }
          if (mdRes.content || mdRes.links.length > 0) {
            const parsedMdNav = extractNovelNavigationFromMarkdown(
              mdRes.content,
              finalUrl,
              jinaLinks
            );
            navFromMd = navFromMd ? mergeNovelNav(parsedMdNav, navFromMd) : parsedMdNav;
          }
        }
      }
    }

    // Secondary Fallback: Parallel charset-aware CORS HTML proxies ONLY when prose is still empty (never overwrite working Ebook prose with a CloudFront 403 shell!)
    if (!rawHtml && srcParas.length === 0) {
      const htmlCtrl = new AbortController();
      const onInnerAbort = () => htmlCtrl.abort();
      ctrl.signal.addEventListener('abort', onInnerAbort, { once: true });
      const htmlTimer = window.setTimeout(() => htmlCtrl.abort(), 7000);
      try {
        const fetched = await fetchRawHtmlViaCorsProxy(cleanUrl, htmlCtrl.signal);
        if (
          fetched &&
          !hasMojibake(fetched.slice(0, 2000)) &&
          !isChallengeOrBlockedPayload('', fetched, '')
        ) {
          rawHtml = fetched;
          const doc = new DOMParser().parseFromString(rawHtml, 'text/html');
          navFromHtml = extractNovelNavigationFromHtml(doc, rawHtml, finalUrl, jinaLinks);
          if (!titleSrc || titleSrc === host) {
            const docTitle = decodeHtmlEntities((doc.title || '').trim());
            if (docTitle) titleSrc = docTitle;
          }
          const htmlParas = extractCleanParagraphsFromHtml(doc, titleSrc);
          if (htmlParas.length > srcParas.length) srcParas = htmlParas;
        }
      } catch {
        // Ignore slow proxy fallback
      } finally {
        window.clearTimeout(htmlTimer);
        ctrl.signal.removeEventListener('abort', onInnerAbort);
      }
    }

    // Never keep blocked CloudFront/Cloudflare/WAF HTML or error-page prose!
    if (rawHtml && isChallengeOrBlockedPayload('', rawHtml, '')) {
      rawHtml = '';
    }
    if (srcParas.length > 0 && isBlockedArticleOrTranslation(titleSrc, srcParas, '')) {
      srcParas = [];
      hitAntiBotChallenge = true;
    }

    const proseCharCount = srcParas.reduce((acc, p) => acc + p.length, 0);
    const comicMeta = extractMangaPagesFromHtml(rawHtml, finalUrl, {
      proseParagraphCount: srcParas.length,
      proseCharCount,
      jinaLinks,
    });

    if (srcParas.length === 0 && !comicMeta.isComic) {
      if (hitAntiBotChallenge) {
        throw new Error(
          `Situs ${host} memasang verifikasi keamanan / anti-bot (Cloudflare / CloudFront WAF) sehingga konten tidak dapat diambil otomatis. Buka situs asli atau salin teks halaman langsung ke tab Teks.`
        );
      }
      throw new Error(
        `Tidak ditemukan paragraf teks yang dapat dibaca pada ${host}. Halaman mungkin memerlukan login atau tantangan anti-bot.`
      );
    }

    const detectedSource = detectLanguageLocal(
      `${titleSrc}\n${srcParas.slice(0, 6).join('\n')}`,
      'ja'
    );
    let mergedNav = mergeNovelNav(
      navFromHtml || sanitizeNovelNav({ isNovel: isKnownNovelUrl(finalUrl) }),
      navFromMd || cached?.novelNav
    );
    if (earlyTocNav) {
      mergedNav = mergeNovelNav(earlyTocNav, mergedNav);
    } else if (
      mergedNav.tocUrl &&
      canonicalUrlKey(mergedNav.tocUrl) !== canonicalUrlKey(finalUrl) &&
      (mergedNav.chapters?.length || 0) < 2
    ) {
      const discoveredToc = await fetchSeriesTocDirect(mergedNav.tocUrl, finalUrl).catch(() => null);
      if (discoveredToc) {
        mergedNav = mergeNovelNav(discoveredToc, mergedNav);
      }
    }
    // Kakuyomu work TOC page rescue: if work page only exposed <= 10 collapsed DOM links (no __NEXT_DATA__),
    // expand to ALL 84-1500 chapters via Episode 1's lightweight /episode_sidebar!
    const kakuCurrentWork = finalUrl.match(/kakuyomu\.jp\/works\/(\d+)/i);
    if (
      kakuCurrentWork &&
      (mergedNav.chapters?.length || 0) <= 10 &&
      !/__NEXT_DATA__/.test(rawHtml)
    ) {
      const sampleEpUrl = /kakuyomu\.jp\/works\/\d+\/episodes\/\d+/i.test(finalUrl)
        ? finalUrl
        : mergedNav.chapters?.[0]?.url || '';
      if (sampleEpUrl) {
        const expanded = await fetchKakuyomuEpisodeSidebarDirect(
          kakuCurrentWork[1],
          sampleEpUrl,
          finalUrl,
          ctrl.signal
        ).catch(() => null);
        if (expanded && (expanded.chapters?.length || 0) > (mergedNav.chapters?.length || 0)) {
          mergedNav = mergeNovelNav(expanded, mergedNav);
        }
      }
    }
    // If current page itself IS a TOC page with chapters, store it in seriesTocCache for instant chapter navigation
    if (mergedNav.chapters && mergedNav.chapters.length >= 2 && mergedNav.tocUrl) {
      const tocKey = canonicalUrlKey(mergedNav.tocUrl);
      const isAuthoritative =
        !kakuCurrentWork || /__NEXT_DATA__/.test(rawHtml) || mergedNav.chapters.length > 10;
      if (isAuthoritative && !seriesTocCache.has(tocKey)) {
        seriesTocCache.set(tocKey, {
          ...(mergedNav.seriesTitle ? { seriesTitle: mergedNav.seriesTitle } : {}),
          tocUrl: mergedNav.tocUrl,
          chapters: mergedNav.chapters,
          authoritative: true,
        });
      }
    }

    const entry: CachedWebEntry = {
      url: finalUrl,
      host,
      titleId: deriveSeriesTitleId(finalUrl),
      titleSrc,
      srcParas,
      detectedSource,
      novelNav: mergedNav,
      comicMeta: comicMeta.isComic ? comicMeta : undefined,
      rawHtml: rawHtml || undefined,
      rawMarkdown: rawMarkdown || undefined,
      htmlFetchAttempted: true,
    };
    webArticleCache.set(cleanUrl, entry);
    webArticleCache.set(finalUrl, entry);
    // Persist lightweight copy to IndexedDB so Web & Installed PWA reopen chapters in < 25ms
    const persistCopy: CachedWebEntry = {
      ...entry,
      rawHtml: entry.rawHtml && entry.rawHtml.length <= 1_500_000 ? entry.rawHtml : undefined,
      rawMarkdown: undefined,
    };
    void idbPut('articles', `art::${cleanUrl}`, persistCopy);
    if (finalUrl !== cleanUrl) {
      void idbPut('articles', `art::${finalUrl}`, persistCopy);
    }
    return entry;
  } catch (err) {
    if (options?.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    if ((err as { name?: string })?.name === 'AbortError') {
      throw new Error(`Waktu tunggu habis saat mengambil halaman ${host}. Coba lagi.`);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
    if (options?.signal) {
      options.signal.removeEventListener('abort', onOuterAbort);
    }
  }
}

export function prefetchWebArticleDirect(rawUrl?: string | null): void {
  if (!rawUrl || isMockOnlyLocalE2E()) return;
  const safe = toSafeHttpUrl(rawUrl);
  if (!safe || webArticleCache.has(safe)) return;
  fetchWebArticleDirect(safe).catch(() => { });
}

/**
 * Fetches and pre-translates the upcoming chapter in idle background time so
 * clicking "Next chapter" opens instantaneously from memory + L2 cache.
 */
export function prefetchNextChapterTranslatedDirect(
  rawUrl?: string | null,
  mode: ModePair = 'auto-id',
  titleId?: string,
  view: 'reader' | 'site' = 'reader',
  theme?: 'Terang' | 'Gelap'
): void {
  if (
    !rawUrl ||
    isMockOnlyLocalE2E() ||
    shouldShedBackgroundLoad(getStorageHealthSnapshot().usageRatio)
  ) {
    return;
  }
  const safe = toSafeHttpUrl(rawUrl);
  if (!safe) return;
  const cacheKey = `${safe}::${mode}::${view}`;
  if (
    inFlightPreTranslations.has(cacheKey) ||
    (view === 'reader' && translatedWebCache.has(`${safe}::${mode}`)) ||
    (view === 'site' && translatedSiteHtmlCache.has(`${safe}::${mode}::${theme || 'auto'}::site`))
  ) {
    return;
  }

  inFlightPreTranslations.add(cacheKey);
  const runTask = () => {
    (async () => {
      try {
        const article = await fetchWebArticleDirect(safe, { needRawHtml: view === 'site' });
        const articleCacheKey = `${article.url}::${mode}`;
        let heading = article.titleSrc;
        let paras = article.srcParas.slice(0, 600);
        const existingTr = translatedWebCache.get(articleCacheKey);
        if (existingTr) {
          heading = existingTr.heading;
          paras = existingTr.paras;
        } else {
          const tid = titleId || article.titleId;
          const batch = [article.titleSrc, ...paras];
          const { outputs } = await translateParagraphsDirect({
            paragraphs: batch,
            mode,
            titleId: tid,
          });
          heading = outputs[0]?.replace(/^#{1,6}\s+/, '') || article.titleSrc;
          paras = outputs.slice(1).map((s) => s.replace(/^#{1,6}\s+/, ''));
          translatedWebCache.set(articleCacheKey, { heading, paras });
          translatedWebCache.set(`${safe}::${mode}`, { heading, paras });
        }
        if (view === 'site') {
          await buildTranslatedSiteHtmlDirect({
            article,
            mode,
            titleId: titleId || article.titleId,
            translatedHeading: heading,
            translatedParas: paras,
            theme,
          });
        }
      } catch {
        // Silent background optimization
      } finally {
        inFlightPreTranslations.delete(cacheKey);
      }
    })();
  };

  if (typeof window !== 'undefined') {
    const idleCb = (
      window as unknown as {
        requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
      }
    ).requestIdleCallback;
    if (typeof idleCb === 'function') {
      idleCb(runTask, { timeout: 900 });
    } else {
      window.setTimeout(runTask, 200);
    }
  }
}

function prewarmCurrentSiteHtmlDirect(params: {
  article: CachedWebEntry;
  mode: ModePair;
  titleId?: string;
  translatedHeading: string;
  translatedParas: string[];
  theme?: 'Terang' | 'Gelap';
}): void {
  if (shouldShedBackgroundLoad(getStorageHealthSnapshot().usageRatio)) return;
  const cacheKey = `${params.article.url}::${params.mode}::${params.theme || 'auto'}::site`;
  if (translatedSiteHtmlCache.has(cacheKey) || inFlightPreTranslations.has(cacheKey)) return;
  inFlightPreTranslations.add(cacheKey);
  const run = () => {
    void buildTranslatedSiteHtmlDirect(params)
      .catch(() => { })
      .finally(() => {
        inFlightPreTranslations.delete(cacheKey);
      });
  };
  if (typeof window !== 'undefined') {
    const idleCb = (
      window as unknown as {
        requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
      }
    ).requestIdleCallback;
    if (typeof idleCb === 'function') {
      idleCb(run, { timeout: 1200 });
    } else {
      window.setTimeout(run, 350);
    }
  }
}

export async function directPreviewLink(params: {
  cid: string;
  url: string;
  mode: ModePair;
  titleId?: string;
}): Promise<LinkPreviewPayload> {
  const article = await fetchWebArticleDirect(params.url);
  const tid = params.titleId || article.titleId;
  const mid = `lnk_${Date.now().toString(36)}`;

  // Comic / Manga / Direct-Image Link Path
  if (article.comicMeta?.isComic) {
    let firstImageResult: ImageTranslationResult | undefined;
    let titleDst = article.titleSrc;
    let detectedSource: TargetLang = article.detectedSource || 'ja';

    if (article.comicMeta.isDirectImage && article.comicMeta.pages[0]) {
      try {
        firstImageResult = await directScanRemoteMangaPage({
          imageUrl: article.comicMeta.pages[0].url,
          mode: params.mode,
          titleId: tid,
          layout: article.comicMeta.layout,
        });
      } catch {
        // Graceful fallback: open visual reader with paste/upload rescue if origin blocks CORS
      }
    } else if (article.titleSrc && article.titleSrc !== article.host) {
      const trTitle = await translateParagraphsDirect({
        paragraphs: [article.titleSrc],
        mode: params.mode,
        titleId: tid,
        titleKind: 'komik',
      });
      titleDst = trTitle.outputs[0]?.replace(/^#{1,6}\s+/, '') || article.titleSrc;
      detectedSource = trTitle.detectedSource;
    }

    const excerptSrc = firstImageResult?.fullSrc.slice(0, 260) || '';
    const excerptDst =
      firstImageResult?.fullDst.slice(0, 320) ||
      `Terdeteksi ${article.comicMeta.pageCount} halaman komik/manga. Buka Pembaca Komik Visual untuk memindai dan menerjemahkan dialog di atas gambar.`;

    const preview: LinkPreviewPayload = {
      mid,
      cid: params.cid,
      titleId: tid,
      url: article.url,
      host: article.host,
      isAozora: false,
      titleSrc: article.titleSrc,
      titleDst,
      excerptSrc,
      excerptDst,
      paragraphCount: firstImageResult ? firstImageResult.blocks.length : article.comicMeta.pageCount,
      lockedNames: 0,
      readerSupported: true,
      novelNav: article.novelNav,
      comicMeta: article.comicMeta,
      firstImageResult,
    };

    await Promise.all([
      upsertConversationMeta(params.cid, {
        title: titleDst,
        titleId: tid,
        mode: params.mode,
        detectedSource,
        activeTab: 'link',
        preview: excerptDst || titleDst,
      }),
      saveTurnMessageDirect(params.cid, mid, {
        role: 'assistant',
        kind: 'link',
        mode: params.mode,
        detectedSource,
        titleId: tid,
        srcText: article.url,
        text: firstImageResult?.fullDst || excerptDst,
        linkPreview: preview,
        state: 'done',
      }),
    ]);

    return preview;
  }

  const cappedParas = article.srcParas.slice(0, 160);
  const fullInputs = [article.titleSrc, ...cappedParas];
  const { outputs, detectedSource, matchedChips } = await translateParagraphsDirect({
    paragraphs: fullInputs,
    mode: params.mode,
    titleId: tid,
  });

  const titleDst = outputs[0]?.replace(/^#{1,6}\s+/, '') || article.titleSrc;
  const translatedParas = outputs.slice(1).map((s) => s.replace(/^#{1,6}\s+/, ''));
  translatedWebCache.set(`${article.url}::${params.mode}`, {
    heading: titleDst,
    paras: outputs.slice(1),
  });
  translatedWebCache.set(`${normalizeWebUrl(params.url)}::${params.mode}`, {
    heading: titleDst,
    paras: outputs.slice(1),
  });

  const excerptSrc = cappedParas
    .slice(0, 2)
    .map((s) => s.replace(/^#{1,6}\s+/, ''))
    .join(' ')
    .slice(0, 260);
  const excerptDst = translatedParas.slice(0, 3).join(' ').slice(0, 320);
  const fullTranslatedText = translatedParas.join('\n\n');
  const sentences: SentencePair[] = cappedParas.map((srcLine, idx) => ({
    i: idx,
    src: srcLine.replace(/^#{1,6}\s+/, ''),
    dst: translatedParas[idx] || srcLine,
  }));

  const preview: LinkPreviewPayload = {
    mid,
    cid: params.cid,
    titleId: tid,
    url: article.url,
    host: article.host,
    isAozora: article.host.includes('aozora.gr.jp'),
    titleSrc: article.titleSrc,
    titleDst,
    excerptSrc,
    excerptDst,
    paragraphCount: cappedParas.length,
    lockedNames: matchedChips.length,
    readerSupported: true,
    novelNav: article.novelNav,
  };

  await Promise.all([
    upsertConversationMeta(params.cid, {
      title: titleDst,
      titleId: tid,
      mode: params.mode,
      detectedSource,
      activeTab: 'link',
      preview: excerptDst || titleDst,
    }),
    saveTurnMessageDirect(params.cid, mid, {
      role: 'assistant',
      kind: 'link',
      mode: params.mode,
      detectedSource,
      titleId: tid,
      srcText: article.url,
      text: fullTranslatedText,
      sentences,
      linkPreview: preview,
      state: 'done',
    }),
  ]);

  if (article.novelNav.isNovel && !article.novelNav.isTocPage) {
    saveReadingProgress(article.novelNav.tocUrl || tid, {
      url: article.url,
      chapterLabel: article.novelNav.chapterLabel,
      titleDst,
      updatedAt: Date.now(),
    });
  }
  if (article.novelNav.nextUrl) {
    prefetchNextChapterTranslatedDirect(article.novelNav.nextUrl, params.mode, tid);
  }

  return preview;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function buildTranxWebHref(
  targetAbsUrl: string,
  mode: ModePair,
  view: 'reader' | 'site' | 'original',
  fallbackTitleId?: string
): string {
  const origin =
    typeof window !== 'undefined' && window.location.origin
      ? window.location.origin
      : 'https://tranx-hanif-id.web.app';
  const tid = deriveSeriesTitleId(targetAbsUrl) || fallbackTitleId || '';
  const qs = new URLSearchParams({
    url: targetAbsUrl,
    mode,
    view,
    ...(tid ? { titleId: tid } : {}),
  });
  return `${origin}/web?${qs.toString()}`;
}

async function buildTranslatedSiteHtmlDirect(params: {
  article: CachedWebEntry;
  mode: ModePair;
  titleId?: string;
  translatedHeading: string;
  translatedParas: string[];
  theme?: 'Terang' | 'Gelap';
  signal?: AbortSignal;
}): Promise<string> {
  const { article, mode, translatedHeading, translatedParas, theme, signal } = params;
  const cacheKey = `${article.url}::${mode}::${theme || 'auto'}::site`;
  const cachedHtml = translatedSiteHtmlCache.get(cacheKey);
  if (cachedHtml) return cachedHtml;

  const { tgt } = parseModePair(mode);
  const nav = article.novelNav;
  const navLabels =
    tgt === 'en'
      ? { prev: 'Previous chapter', toc: 'Chapters', next: 'Next chapter' }
      : tgt === 'ja'
        ? { prev: '前の話', toc: '目次', next: '次の話' }
        : { prev: 'Bab sebelumnya', toc: 'Daftar bab', next: 'Bab berikutnya' };
  const navButtonsHtml =
    nav.prevUrl || nav.nextUrl || nav.tocUrl
      ? `<div class="tranx-site-nav-bar" style="position:sticky;bottom:0;z-index:9999;background:#141917;color:#FAFBFA;padding:12px 16px;display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;border-top:1px solid #2B3230;font-family:Inter,-apple-system,sans-serif;font-size:14px;">
          ${nav.prevUrl
        ? `<a href="${escapeHtml(buildTranxWebHref(nav.prevUrl, mode, 'site', params.titleId))}" target="_top" rel="noopener noreferrer" style="color:#E7ECEA;text-decoration:none;padding:8px 14px;border:1px solid #3C4743;border-radius:10px;font-weight:600;">&#8592; ${navLabels.prev}</a>`
        : ''
      }
          ${nav.tocUrl
        ? `<a href="${escapeHtml(buildTranxWebHref(nav.tocUrl, mode, 'site', params.titleId))}" target="_top" rel="noopener noreferrer" style="color:#E7ECEA;text-decoration:none;padding:8px 14px;border:1px solid #3C4743;border-radius:10px;font-weight:600;">${navLabels.toc}</a>`
        : ''
      }
          ${nav.nextUrl
        ? `<a href="${escapeHtml(buildTranxWebHref(nav.nextUrl, mode, 'site', params.titleId))}" target="_top" rel="noopener noreferrer" style="background:#17695B;color:#FFFFFF;text-decoration:none;padding:8px 16px;border-radius:10px;font-weight:600;">${navLabels.next} &#8594;</a>`
        : ''
      }
        </div>`
      : '';

  if (article.rawHtml && !isChallengeOrBlockedPayload('', article.rawHtml, '')) {
    const doc = new DOMParser().parseFromString(article.rawHtml, 'text/html');

    // Remove all executable/embedded/redirect/mXSS tags AND JS-only loading curtains that stay white without JS
    doc
      .querySelectorAll(
        'script, noscript, iframe, frame, frameset, object, embed, applet, base, template, portal, math, svg, area, map, form, foreignobject, animate, animatemotion, animatetransform, set, use, meta[http-equiv], [id*="preloader"], [class*="preloader"], .page-loader, #loading-screen, .loading-overlay'
      )
      .forEach((el) => el.remove());

    // Sanitize attributes and rewrite every safe <a href> into tranX auto-translating /web links
    const hasUnsafeCssClient = (css: string): boolean => {
      if (!css) return false;
      const decoded = css
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\\([0-9a-fA-F]{1,6})[ \t\r\n\f]?/g, (_m, hex: string) => {
          const cp = parseInt(hex, 16);
          return cp > 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : '';
        })
        .replace(/\\([^\r\n\f0-9a-fA-F])/g, '$1');
      return /(?:@import\b|expression\s*\(|-moz-binding\s*:|behavior\s*:|\burl\s*\(|\bimage-set\s*\()/i.test(decoded);
    };
    const articleHost = (() => {
      try {
        return new URL(article.url).hostname.toLowerCase();
      } catch {
        return '';
      }
    })();
    const allElements = Array.from(doc.querySelectorAll('*'));
    for (const el of allElements) {
      const tag = el.tagName.toUpperCase();
      if (tag === 'STYLE') {
        const cssText = el.textContent || '';
        if (hasUnsafeCssClient(cssText)) {
          el.remove();
        }
        continue;
      }

      for (const attr of Array.from(el.attributes)) {
        const name = attr.name.toLowerCase();
        if (
          name.startsWith('on') ||
          name === 'srcdoc' ||
          name === 'formaction' ||
          name === 'ping' ||
          name === 'srcset' ||
          name === 'imagesrcset' ||
          name === 'dynsrc' ||
          name === 'lowsrc' ||
          name === 'background'
        ) {
          el.removeAttribute(attr.name);
          continue;
        }
        if (name === 'style') {
          if (hasUnsafeCssClient(attr.value)) {
            el.removeAttribute(attr.name);
          }
          continue;
        }
        if (
          name === 'href' ||
          name === 'src' ||
          name === 'action' ||
          name === 'xlink:href' ||
          name === 'poster'
        ) {
          const cleanedVal = attr.value.replace(/[\x00-\x20\x7f]+/g, '').toLowerCase();
          if (
            cleanedVal.startsWith('javascript:') ||
            cleanedVal.startsWith('vbscript:') ||
            cleanedVal.startsWith('file:') ||
            cleanedVal.startsWith('blob:') ||
            cleanedVal.startsWith('data:text/html') ||
            cleanedVal.startsWith('data:image/svg') ||
            cleanedVal.startsWith('data:application/')
          ) {
            el.removeAttribute(attr.name);
          }
        }
      }

      if (el.tagName === 'A') {
        el.removeAttribute('target');
        const rawHref = el.getAttribute('href') || '';
        const safeAbs = resolveSafeSiblingUrl(rawHref, article.url);
        if (safeAbs) {
          el.setAttribute('href', buildTranxWebHref(safeAbs, mode, 'site', params.titleId));
          el.setAttribute('target', '_top');
          el.setAttribute('rel', 'noopener noreferrer');
        } else {
          el.removeAttribute('href');
        }
      } else if (el.tagName === 'LINK') {
        const relTokens = (el.getAttribute('rel') || '').toLowerCase().split(/\s+/).filter(Boolean);
        if (!relTokens.includes('stylesheet')) {
          el.remove();
          continue;
        }
        const rawHref = el.getAttribute('href') || '';
        const safeAbs = resolveSafeSiblingUrl(rawHref, article.url);
        let sameHostHttps = false;
        if (safeAbs) {
          try {
            const u = new URL(safeAbs);
            sameHostHttps = u.protocol === 'https:' && (!articleHost || u.hostname.toLowerCase() === articleHost);
          } catch {
            sameHostHttps = false;
          }
        }
        if (safeAbs && sameHostHttps) {
          el.setAttribute('href', safeAbs);
        } else {
          el.remove();
        }
      } else if (
        el.tagName === 'IMG' ||
        el.tagName === 'SOURCE' ||
        el.tagName === 'VIDEO' ||
        el.tagName === 'AUDIO'
      ) {
        const currentSrc = (el.getAttribute('src') || '').trim();
        const lazySrc = (
          el.getAttribute('data-src') ||
          el.getAttribute('data-lazy-src') ||
          el.getAttribute('data-original') ||
          ''
        ).trim();
        const isPlaceholderDataUri = /^data:image\/(gif|svg\+xml);/i.test(currentSrc);
        const rawSrc = (!currentSrc || isPlaceholderDataUri) && lazySrc ? lazySrc : currentSrc || lazySrc;
        if (rawSrc) {
          if (rawSrc.toLowerCase().startsWith('data:')) {
            if (!/^data:image\/(?:png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=\s]+$/i.test(rawSrc)) {
              el.removeAttribute('src');
            }
          } else {
            const safeAbs = resolveSafeSiblingUrl(rawSrc, article.url);
            if (safeAbs) el.setAttribute('src', safeAbs);
            else el.removeAttribute('src');
          }
        }
        const rawPoster = el.getAttribute('poster') || '';
        if (rawPoster) {
          const safePoster = resolveSafeSiblingUrl(rawPoster, article.url);
          if (safePoster) el.setAttribute('poster', safePoster);
          else el.removeAttribute('poster');
        }
        const rawSrcset = el.getAttribute('srcset') || el.getAttribute('data-srcset') || '';
        if (rawSrcset) {
          const resolvedSrcset = rawSrcset
            .split(',')
            .map((entry) => {
              const parts = entry.trim().split(/\s+/);
              if (!parts[0]) return '';
              const safeAbs = resolveSafeSiblingUrl(parts[0], article.url);
              if (!safeAbs) return '';
              return parts.length > 1 ? `${safeAbs} ${parts.slice(1).join(' ')}` : safeAbs;
            })
            .filter(Boolean)
            .join(', ');
          if (resolvedSrcset) el.setAttribute('srcset', resolvedSrcset);
          else el.removeAttribute('srcset');
        }
      } else if (el.tagName === 'FORM') {
        el.removeAttribute('action');
      }
    }

    // Strip ruby readings (<rt>/<rp>) so translated text nodes don't mix furigana beside Latin prose
    doc.querySelectorAll('rt, rp').forEach((el) => el.remove());

    // Force responsive viewport + safe mobile reflow CSS without EVER hiding body/content wrappers (e.g. WordPress body.no-sidebar / .has-sidebar!)
    const head = doc.head || doc.createElement('head');
    if (!doc.head && doc.documentElement) {
      doc.documentElement.insertBefore(head, doc.body);
    }
    doc.querySelectorAll('meta[name="viewport"]').forEach((el) => el.remove());
    const vp = doc.createElement('meta');
    vp.setAttribute('name', 'viewport');
    vp.setAttribute('content', 'width=device-width, initial-scale=1.0');
    head.insertBefore(vp, head.firstChild);
    const safeStyle = doc.createElement('style');
    safeStyle.textContent = [
      '*,*::before,*::after{box-sizing:border-box !important;}',
      'html,body{display:block !important;visibility:visible !important;opacity:1 !important;max-width:100% !important;overflow-x:clip !important;overflow-y:auto !important;}',
      '[data-aos],.aos-init,.wow,.fade-in,.invisible-until-loaded{opacity:1 !important;visibility:visible !important;transform:none !important;}',
      'img,video,svg{max-width:100% !important;height:auto !important;}',
      '@media (max-width:767px){',
      '  html,body{margin:0 !important;padding:0 !important;width:100% !important;}',
      '  body{padding:0 12px 16px 12px !important;word-break:break-word !important;overflow-wrap:anywhere !important;}',
      '  main,article,section,header,nav,footer,div,p,h1,h2,h3,h4,ul,ol,table,pre,blockquote{max-width:100% !important;min-width:0 !important;}',
      '  [style*="width"]{max-width:100% !important;}',
      '  header,nav,[class*="breadcrumb"],[class*="Header"],[class*="header"]{flex-wrap:wrap !important;white-space:normal !important;overflow-wrap:anywhere !important;height:auto !important;}',
      '  h1,h2,h3,.widget-episodeTitle{font-size:clamp(18px,5.4vw,24px) !important;line-height:1.35 !important;white-space:normal !important;margin-left:0 !important;margin-right:0 !important;padding-left:0 !important;padding-right:0 !important;text-align:left !important;}',
      '  #contentMain,#contentMain-inner,.widget-episode,.widget-episodeTitle,.widget-episodeBody,#novel_honbun,.p-novel__body,#honbun,article,main{width:100% !important;max-width:100% !important;margin-left:0 !important;margin-right:0 !important;padding-left:2px !important;padding-right:2px !important;left:auto !important;right:auto !important;transform:none !important;}',
      '  #works-sidebar,.tranx-site-nav-bar,aside.sidebar:not(:has(article)):not(:has(main)){display:none !important;}',
      '}',
    ].join('\n');
    head.appendChild(safeStyle);

    // Collect visible text nodes prioritizing main article content FIRST (smart cap 360 nodes for 4x faster rendering)
    const skipParentTags = new Set([
      'SCRIPT',
      'STYLE',
      'NOSCRIPT',
      'CODE',
      'PRE',
      'TEXTAREA',
      'SVG',
      'MATH',
      'RT',
      'RP',
    ]);
    const MAX_SITE_NODES = 900;
    const textNodes: Text[] = [];
    const seenTextNodes = new Set<Text>();
    let totalRawTextChars = 0;

    const isSkippableChromeNode = (el: Element | null, allowFooter: boolean): boolean => {
      let cur = el;
      let depth = 0;
      while (cur && depth < 6) {
        if (
          cur.hasAttribute('hidden') ||
          cur.getAttribute('aria-hidden') === 'true' ||
          (!allowFooter && cur.tagName === 'FOOTER')
        ) {
          return true;
        }
        cur = cur.parentElement;
        depth += 1;
      }
      return false;
    };

    const collectFromSubtree = (rootEl: Node | null, allowFooter: boolean) => {
      if (!rootEl || textNodes.length >= MAX_SITE_NODES) return;
      const walker = doc.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node && textNodes.length < MAX_SITE_NODES) {
        const tn = node as Text;
        if (!seenTextNodes.has(tn)) {
          const parent = tn.parentElement;
          const val = (tn.nodeValue || '').trim();
          if (
            val.length >= 2 &&
            hasTranslatableLetters(val) &&
            (!parent || (!skipParentTags.has(parent.tagName) && !isSkippableChromeNode(parent, allowFooter)))
          ) {
            seenTextNodes.add(tn);
            textNodes.push(tn);
            totalRawTextChars += val.length;
          }
        }
        node = walker.nextNode();
      }
    };

    const mainRegion = doc.querySelector(MAIN_CONTENT_SELECTORS);
    if (mainRegion) collectFromSubtree(mainRegion, true);
    collectFromSubtree(doc.body || doc.documentElement, !mainRegion);

    // Guard against blank JS-only SPA shells (<div id="root"></div> with only 2 tiny nav links): require substantial body text mass!
    const expectedProseChars = translatedParas.reduce((acc, p) => acc + p.length, 0);
    const hasSubstantialDomBody =
      textNodes.length >= 2 &&
      (translatedParas.length < 2 ||
        totalRawTextChars >= Math.min(140, Math.floor(expectedProseChars * 0.28)));

    if (hasSubstantialDomBody) {
      // Cross-view 0ms reuse: resolve any DOM text node already translated in Ebook mode without re-calling GTX/Gemini!
      const normKey = (s: string) => s.replace(/\s+/g, ' ').trim();
      const ebookReuseMap = new Map<string, string>();
      if (article.titleSrc && translatedHeading) {
        ebookReuseMap.set(normKey(article.titleSrc), translatedHeading);
      }
      article.srcParas.forEach((srcP, idx) => {
        const dstP = translatedParas[idx];
        if (srcP && dstP) {
          ebookReuseMap.set(normKey(srcP.replace(/^#{1,6}\s+/, '')), dstP);
        }
      });

      const MAX_SITE_SYNC_NODES = 300;
      const pendingNodes: Text[] = [];
      const pendingTexts: string[] = [];
      for (const tn of textNodes) {
        const cleaned = normKey(tn.nodeValue || '');
        const hit = ebookReuseMap.get(cleaned);
        if (hit) {
          tn.nodeValue = hit;
        } else if (pendingTexts.length < MAX_SITE_SYNC_NODES) {
          pendingNodes.push(tn);
          pendingTexts.push((tn.nodeValue || '').trim());
        }
      }

      if (pendingTexts.length > 0) {
        const { outputs } = await translateParagraphsDirect({
          paragraphs: pendingTexts,
          mode,
          titleId: params.titleId || article.titleId,
          signal,
        });
        pendingNodes.forEach((tn, idx) => {
          if (outputs[idx]) {
            tn.nodeValue = outputs[idx];
          }
        });
      }

      if (doc.title) {
        doc.title = translatedHeading;
      }
      if ((nav.prevUrl || nav.nextUrl || nav.tocUrl) && doc.body) {
        const navBar = doc.createElement('div');
        navBar.setAttribute('class', 'tranx-site-nav-bar');
        navBar.setAttribute(
          'style',
          'position:sticky;bottom:0;z-index:9999;background:#141917;color:#FAFBFA;padding:12px 16px;display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;border-top:1px solid #2B3230;font-family:Inter,-apple-system,sans-serif;font-size:14px;'
        );
        const appendNavLink = (targetUrl: string, label: string, primary: boolean) => {
          const a = doc.createElement('a');
          a.setAttribute('href', buildTranxWebHref(targetUrl, mode, 'site', params.titleId));
          a.setAttribute('target', '_top');
          a.setAttribute('rel', 'noopener noreferrer');
          a.setAttribute(
            'style',
            primary
              ? 'background:#17695B;color:#FFFFFF;text-decoration:none;padding:8px 16px;border-radius:10px;font-weight:600;'
              : 'color:#E7ECEA;text-decoration:none;padding:8px 14px;border:1px solid #3C4743;border-radius:10px;font-weight:600;'
          );
          a.textContent = label;
          navBar.appendChild(a);
        };
        if (nav.prevUrl) appendNavLink(nav.prevUrl, `← ${navLabels.prev}`, false);
        if (nav.tocUrl) appendNavLink(nav.tocUrl, navLabels.toc, false);
        if (nav.nextUrl) appendNavLink(nav.nextUrl, `${navLabels.next} →`, true);
        doc.body.appendChild(navBar);
      }

      const serialized = `<!doctype html>\n${doc.documentElement.outerHTML}`;
      translatedSiteHtmlCache.set(cacheKey, serialized);
      return serialized;
    }
  }

  // Clean semantic fallback when CORS HTML proxy was blocked or page is a blank JS-only shell: matches active Light/Dark theme!
  const isJpBody = tgt === 'ja';
  const fontStack = isJpBody
    ? '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif'
    : 'Charter, Georgia, Cambria, serif';
  const isDarkFallback = theme === 'Gelap';
  const bgHex = isDarkFallback ? '#171B1A' : '#FAFBFA';
  const textHex = isDarkFallback ? '#E7ECEA' : '#141917';
  const borderHex = isDarkFallback ? '#2B3230' : '#DEE3E0';
  const metaHex = isDarkFallback ? '#A5AEAA' : '#4F5855';
  const linkHex = isDarkFallback ? '#5DC3AC' : '#17695B';
  const renderedParas = translatedParas
    .map((p) =>
      /^#{1,3}\s+/.test(p)
        ? `<h2>${escapeHtml(p.replace(/^#{1,6}\s+/, ''))}</h2>`
        : `<p>${escapeHtml(p)}</p>`
    )
    .join('\n');

  const translatedChapMap =
    nav.chapters && nav.chapters.length > 0
      ? await translateChapterTitlesDirect({
        chapters: nav.chapters,
        mode,
        titleId: params.titleId || article.titleId,
        tocKey: nav.tocUrl || article.url,
        seriesTitle: nav.seriesTitle,
        signal,
      })
      : {};

  const chaptersHtml =
    nav.chapters && nav.chapters.length > 0
      ? `<section style="margin-top:32px;padding-top:20px;border-top:1px solid ${borderHex};">
          <h2 style="font-family:Inter,-apple-system,sans-serif;font-size:16px;">${navLabels.toc} (${nav.chapters.length})</h2>
          <ul style="list-style:none;padding:0;margin:12px 0;display:flex;flex-direction:column;gap:8px;font-family:Inter,-apple-system,sans-serif;font-size:14px;">
            ${nav.chapters
        .map(
          (ch) =>
            `<li><a href="${escapeHtml(buildTranxWebHref(ch.url, mode, 'site', params.titleId))}" target="_top" rel="noopener noreferrer" style="color:${linkHex};font-weight:${ch.current ? '700' : '500'};text-decoration:none;">${escapeHtml(translatedChapMap[ch.url] || ch.titleDst || ch.title)}</a></li>`
        )
        .join('')}
          </ul>
        </section>`
      : '';

  const fallbackHtml = `<!doctype html>
<html lang="${tgt}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(translatedHeading)}</title>
<style>
  :root { color-scheme: ${isDarkFallback ? 'dark' : 'light dark'}; }
  body { margin: 0; padding: 24px 18px 24px; background: ${bgHex}; color: ${textHex}; font-family: ${fontStack}; font-size: 18px; line-height: 1.78; word-break: break-word; overflow-wrap: anywhere; }
  ${!theme
      ? '@media (prefers-color-scheme: dark) { body { background: #171B1A; color: #E7ECEA; } header { border-bottom-color: #2B3230 !important; } .meta { color: #A5AEAA !important; } }'
      : ''
    }
  article { max-width: 700px; margin: 0 auto 32px; }
  header { margin-bottom: 22px; padding-bottom: 14px; border-bottom: 1px solid ${borderHex}; }
  h1 { font-size: clamp(20px, 5.2vw, 26px); line-height: 1.32; margin: 0 0 8px 0; }
  p { margin: 0 0 16px 0; }
  .meta { font-family: Inter, -apple-system, sans-serif; font-size: 13px; color: ${metaHex}; }
  @media (max-width: 767px) { .tranx-site-nav-bar { display: none !important; } }
</style>
</head>
<body>
  <article>
    <header>
      <div class="meta">${escapeHtml(article.host)}</div>
      <h1>${escapeHtml(translatedHeading.replace(/^#{1,6}\s+/, ''))}</h1>
    </header>
    ${renderedParas}
    ${chaptersHtml}
  </article>
  ${navButtonsHtml}
</body>
</html>`;
  translatedSiteHtmlCache.set(cacheKey, fallbackHtml);
  return fallbackHtml;
}

export async function directFetchWebReaderBundle(params: {
  url: string;
  mode: ModePair;
  titleId?: string;
  view: 'reader' | 'site' | 'original';
  theme?: 'Terang' | 'Gelap';
  signal?: AbortSignal;
  onProgress?: (partialBundle: WebReaderBundle, doneCount: number, totalCount: number) => void;
}): Promise<WebReaderBundle> {
  const article = await fetchWebArticleDirect(params.url, {
    needRawHtml: params.view === 'site',
    signal: params.signal,
  });
  const tid = params.titleId || article.titleId;
  const cappedSrc = article.srcParas.slice(0, 600);
  const { tgt } = parseModePair(params.mode);

  let titleDst = article.titleSrc;
  let translatedParas = cappedSrc;

  if (article.comicMeta?.isComic && cappedSrc.length < 15) {
    let comicTitleDst = article.titleSrc;
    if (params.view !== 'original' && article.titleSrc && article.titleSrc !== article.host && !article.comicMeta.isDirectImage) {
      const tr = await translateParagraphsDirect({
        paragraphs: [article.titleSrc],
        mode: params.mode,
        titleId: tid,
        titleKind: 'komik',
        signal: params.signal,
      });
      comicTitleDst = tr.outputs[0]?.replace(/^#{1,6}\s+/, '') || article.titleSrc;
    }
    const firstUrl = article.comicMeta.pages[0]?.url;
    const cachedFirst = firstUrl ? scannedMangaPageCache.get(`${firstUrl}::${params.mode}`) : undefined;
    return {
      url: article.url,
      host: article.host,
      titleId: tid,
      detectedSource: article.detectedSource,
      titleSrc: article.titleSrc,
      titleDst: comicTitleDst,
      sentences: [],
      novelNav: article.novelNav,
      comicMeta: article.comicMeta,
      firstImageResult: cachedFirst,
    };
  }

  if (params.view !== 'original') {
    const cacheKey1 = `${article.url}::${params.mode}`;
    const cacheKey2 = `${normalizeWebUrl(params.url)}::${params.mode}`;
    let preTranslated = translatedWebCache.get(cacheKey1) || translatedWebCache.get(cacheKey2);
    if (
      preTranslated &&
      (isBlockedArticleOrTranslation(preTranslated.heading, preTranslated.paras) ||
        !Array.isArray(preTranslated.paras) ||
        preTranslated.paras.length < cappedSrc.length ||
        cappedSrc.some((s, i) => isStillUntranslatedForTarget(s, preTranslated!.paras[i] || '', tgt)))
    ) {
      if (isBlockedArticleOrTranslation(preTranslated.heading, preTranslated.paras)) {
        translatedWebCache.delete(cacheKey1);
        translatedWebCache.delete(cacheKey2);
        void idbDelete('articles', `tr::${cacheKey1}`);
        void idbDelete('articles', `tr::${cacheKey2}`);
      }
      preTranslated = undefined;
    }
    if (!preTranslated) {
      const idbTr =
        (await idbGet<{ heading: string; paras: string[] }>(
          'articles',
          `tr::${cacheKey1}`,
          12 * 60 * 60 * 1000
        )) ||
        (cacheKey2 !== cacheKey1
          ? await idbGet<{ heading: string; paras: string[] }>(
            'articles',
            `tr::${cacheKey2}`,
            12 * 60 * 60 * 1000
          )
          : undefined);
      if (idbTr && isBlockedArticleOrTranslation(idbTr.heading, idbTr.paras)) {
        void idbDelete('articles', `tr::${cacheKey1}`);
        void idbDelete('articles', `tr::${cacheKey2}`);
      } else if (idbTr && Array.isArray(idbTr.paras) && idbTr.paras.length >= cappedSrc.length) {
        const hasUntranslated = cappedSrc.some((s, i) =>
          isStillUntranslatedForTarget(s, idbTr.paras[i] || '', tgt)
        );
        if (!hasUntranslated) {
          preTranslated = idbTr;
          translatedWebCache.set(cacheKey1, idbTr);
          translatedWebCache.set(cacheKey2, idbTr);
        }
      }
    }
    if (preTranslated) {
      titleDst = preTranslated.heading;
      translatedParas = preTranslated.paras;
    } else {
      const batch = [article.titleSrc, ...cappedSrc];
      let lastStreamedPrefixLen = 0;
      const { outputs } = await translateParagraphsDirect({
        paragraphs: batch,
        mode: params.mode,
        titleId: tid,
        signal: params.signal,
        onProgress:
          params.onProgress && params.view === 'reader'
            ? (partialOutputs, doneCount, totalCount) => {
              // Emit longest contiguous translated prefix starting at index 0 so the reader streams cleanly top-to-bottom without untranslated flicker
              let prefixLen = 0;
              for (let idx = 0; idx < cappedSrc.length; idx += 1) {
                if (partialOutputs[idx + 1]) {
                  prefixLen = idx + 1;
                } else {
                  break;
                }
              }
              if (prefixLen === 0 || (prefixLen === lastStreamedPrefixLen && doneCount < totalCount)) {
                return;
              }
              lastStreamedPrefixLen = prefixLen;
              const partialTitle =
                partialOutputs[0]?.replace(/^#{1,6}\s+/, '') || article.titleSrc;
              const partialSentences: SentencePair[] = cappedSrc
                .slice(0, prefixLen)
                .map((srcLine, idx) => ({
                  i: idx,
                  src: srcLine.replace(/^#{1,6}\s+/, ''),
                  dst: (partialOutputs[idx + 1] || srcLine).replace(/^#{1,6}\s+/, ''),
                }));
              params.onProgress?.(
                {
                  url: article.url,
                  host: article.host,
                  titleId: tid,
                  detectedSource: article.detectedSource,
                  titleSrc: article.titleSrc,
                  titleDst: partialTitle,
                  sentences: partialSentences,
                  novelNav: article.novelNav,
                },
                Math.max(prefixLen, doneCount - 1),
                cappedSrc.length
              );
            }
            : undefined,
      });
      titleDst = outputs[0]?.replace(/^#{1,6}\s+/, '') || article.titleSrc;
      translatedParas = outputs.slice(1).map((s) => s.replace(/^#{1,6}\s+/, ''));
      const savedTr = { heading: titleDst, paras: translatedParas };
      const allClean =
        !isBlockedArticleOrTranslation(titleDst, translatedParas) &&
        !cappedSrc.some((s, i) => isStillUntranslatedForTarget(s, translatedParas[i] || '', tgt));
      if (allClean) {
        translatedWebCache.set(cacheKey1, savedTr);
        translatedWebCache.set(cacheKey2, savedTr);
        void idbPut('articles', `tr::${cacheKey1}`, savedTr);
      }
    }
  }

  const sentences: SentencePair[] = cappedSrc.map((srcLine, idx) => ({
    i: idx,
    src: srcLine.replace(/^#{1,6}\s+/, ''),
    dst: (translatedParas[idx] || srcLine).replace(/^#{1,6}\s+/, ''),
  }));

  let siteHtml: string | undefined;
  if (params.view === 'site') {
    siteHtml = await buildTranslatedSiteHtmlDirect({
      article,
      mode: params.mode,
      titleId: tid,
      translatedHeading: titleDst,
      translatedParas,
      theme: params.theme,
      signal: params.signal,
    });
  } else if (params.view === 'reader' && article.rawHtml) {
    // Silently pre-warm Site HTML in background idle time so tapping Ebook -> Site switches instantaneously!
    prewarmCurrentSiteHtmlDirect({
      article,
      mode: params.mode,
      titleId: tid,
      translatedHeading: titleDst,
      translatedParas,
      theme: params.theme,
    });
  }

  if (article.novelNav.isNovel && !article.novelNav.isTocPage) {
    saveReadingProgress(article.novelNav.tocUrl || tid, {
      url: article.url,
      chapterLabel: article.novelNav.chapterLabel,
      titleDst,
      updatedAt: Date.now(),
    });
  }
  if (article.novelNav.nextUrl) {
    prefetchNextChapterTranslatedDirect(
      article.novelNav.nextUrl,
      params.mode,
      tid,
      params.view === 'site' ? 'site' : 'reader',
      params.theme
    );
  }

  return {
    url: article.url,
    host: article.host,
    titleId: tid,
    detectedSource: article.detectedSource,
    titleSrc: article.titleSrc,
    titleDst,
    sentences,
    novelNav: article.novelNav,
    comicMeta: article.comicMeta,
    siteHtml,
  };
}

export async function directFetchTranslatedWebHtml(params: {
  url: string;
  mode: ModePair;
  titleId?: string;
  view: 'translated' | 'original' | 'site' | 'reader';
}): Promise<string> {
  const normalizedView =
    params.view === 'original' ? 'original' : params.view === 'site' ? 'site' : 'reader';
  const bundle = await directFetchWebReaderBundle({
    url: params.url,
    mode: params.mode,
    titleId: params.titleId,
    view: normalizedView === 'site' ? 'site' : normalizedView,
  });
  if (bundle.siteHtml) return bundle.siteHtml;

  const { tgt } = parseModePair(params.mode);
  const isJpBody = normalizedView === 'original' ? bundle.detectedSource === 'ja' : tgt === 'ja';
  const fontStack = isJpBody
    ? '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif'
    : 'Charter, Georgia, Cambria, serif';
  const headingText = normalizedView === 'original' ? bundle.titleSrc : bundle.titleDst;
  const renderedParas = bundle.sentences
    .map((s) => `<p>${escapeHtml(normalizedView === 'original' ? s.src : s.dst)}</p>`)
    .join('\n');

  return `<!doctype html>
<html lang="${tgt}">
<head>
<meta charset="utf-8">
<title>${escapeHtml(headingText)}</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; padding: 28px 20px 72px; background: #FAFBFA; color: #141917; font-family: ${fontStack}; font-size: 18px; line-height: 1.75; }
  @media (prefers-color-scheme: dark) { body { background: #171B1A; color: #E7ECEA; } header { border-bottom-color: #2B3230 !important; } .meta { color: #A5AEAA !important; } }
  article { max-width: 700px; margin: 0 auto; }
  header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #DEE3E0; }
  h1 { font-size: 26px; line-height: 1.3; margin: 0 0 8px 0; }
  p { margin: 0 0 16px 0; }
  .meta { font-family: Inter, -apple-system, sans-serif; font-size: 13px; color: #4F5855; }
  @media (max-width: 767px) { .tranx-site-nav-bar { display: none !important; } }
</style>
</head>
<body>
  <article>
    <header>
      <div class="meta">${escapeHtml(bundle.host)}</div>
      <h1>${escapeHtml(headingText)}</h1>
    </header>
    ${renderedParas}
  </article>
</body>
</html>`;
}

/* Native browser ZIP reader (supports STORED 0 and DEFLATE 8 via DecompressionStream) for .docx & .epub */
async function extractZipTextEntries(
  buffer: ArrayBuffer,
  predicate: (name: string) => boolean
): Promise<Map<string, string>> {
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  const out = new Map<string, string>();
  const decoder = new TextDecoder('utf-8');

  // Locate End of Central Directory (0x06054b50)
  let eocdOffset = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) {
      eocdOffset = i;
      break;
    }
  }
  if (eocdOffset < 0) throw new Error('Arsip dokumen rusak atau terenkripsi.');

  const MAX_ZIP_ENTRIES = 1500;
  const MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024;
  const totalEntries = view.getUint16(eocdOffset + 10, true);
  if (totalEntries > MAX_ZIP_ENTRIES) {
    throw new Error('Arsip dokumen memiliki terlalu banyak entri dan ditolak demi keamanan.');
  }
  let cdOffset = view.getUint32(eocdOffset + 16, true);
  let totalUncompressed = 0;

  const SAFE_EPUB_DOCTYPE_RE =
    /^<!doctype\s+(?:html\s*>|(?:html|ncx)\s+public\s+["'](?:-\/\/w3c\/\/dtd\s+x?html\s+[0-9.]+(?:\s+(?:strict|transitional|frameset))?\/\/en|-\/\/niso\/\/dtd\s+ncx\s+2005-1\/\/en)["'](?:\s+["']https?:\/\/(?:www\.w3\.org\/tr\/x?html[^"'\[\]<>]*|www\.daisy\.org\/z3986\/2005\/ncx-2005-1\.dtd)["'])?\s*>)$/i;

  const assertSafeArchiveXml = (entryName: string, decodedEntry: string): void => {
    if (/<!ENTITY\b/i.test(decodedEntry)) {
      throw new Error('Deklarasi DOCTYPE/entitas XML eksternal (XXE) ditolak demi keamanan.');
    }
    const doctypeMatches = decodedEntry.match(/<!DOCTYPE\b[^>]{0,512}>?/gi);
    if (!doctypeMatches) return;
    const allowEpubHtmlDoctype = /\.(?:xhtml|html|htm|ncx)$/i.test(entryName);
    if (!allowEpubHtmlDoctype) {
      throw new Error('Deklarasi DOCTYPE/entitas XML eksternal (XXE) ditolak demi keamanan.');
    }
    for (const frag of doctypeMatches) {
      if (frag.includes('[') || !SAFE_EPUB_DOCTYPE_RE.test(frag.trim())) {
        throw new Error('Deklarasi DOCTYPE/entitas XML eksternal (XXE) ditolak demi keamanan.');
      }
    }
  };

  const entrySpans: Array<[number, number]> = [];
  for (let e = 0; e < totalEntries && cdOffset + 46 <= bytes.length; e += 1) {
    if (view.getUint32(cdOffset, true) !== 0x02014b50) break;
    const method = view.getUint16(cdOffset + 10, true);
    const compSize = view.getUint32(cdOffset + 20, true);
    const uncompSize = view.getUint32(cdOffset + 24, true);
    const nameLen = view.getUint16(cdOffset + 28, true);
    const extraLen = view.getUint16(cdOffset + 30, true);
    const commentLen = view.getUint16(cdOffset + 32, true);
    const localHeaderOffset = view.getUint32(cdOffset + 42, true);

    const name = decoder.decode(bytes.subarray(cdOffset + 46, cdOffset + 46 + nameLen));
    cdOffset += 46 + nameLen + extraLen + commentLen;

    if (name.includes('..') || name.startsWith('/')) continue;
    if (localHeaderOffset + 30 > bytes.length) continue;
    if (view.getUint32(localHeaderOffset, true) !== 0x04034b50) {
      throw new Error('Header lokal berkas ZIP tidak sah.');
    }
    const lNameLen = view.getUint16(localHeaderOffset + 26, true);
    const lExtraLen = view.getUint16(localHeaderOffset + 28, true);
    const dataStart = localHeaderOffset + 30 + lNameLen + lExtraLen;
    if (dataStart < 0 || dataStart + compSize > bytes.length) continue;
    entrySpans.push([localHeaderOffset, dataStart + compSize]);

    if (!predicate(name)) continue;
    if (totalUncompressed + uncompSize > MAX_UNCOMPRESSED_BYTES) {
      throw new Error('Ukuran isi dokumen melebihi batas aman 50 MB.');
    }
    const rawSlice = bytes.subarray(dataStart, dataStart + compSize);

    if (method === 0) {
      totalUncompressed += rawSlice.byteLength;
      if (totalUncompressed > MAX_UNCOMPRESSED_BYTES) {
        throw new Error('Ukuran isi dokumen melebihi batas aman 50 MB.');
      }
      const decodedEntry = decoder.decode(rawSlice);
      assertSafeArchiveXml(name, decodedEntry);
      out.set(name, decodedEntry);
    } else if (method === 8 && typeof DecompressionStream !== 'undefined') {
      const ds = new DecompressionStream('deflate-raw');
      const writer = ds.writable.getWriter();
      void writer.write(rawSlice).then(() => writer.close()).catch(() => { });
      const reader = ds.readable.getReader();
      const chunks: Uint8Array[] = [];
      let entryBytes = 0;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) {
          entryBytes += value.byteLength;
          totalUncompressed += value.byteLength;
          if (totalUncompressed > MAX_UNCOMPRESSED_BYTES) {
            await Promise.allSettled([reader.cancel(), writer.abort()]);
            throw new Error('Ukuran isi dokumen melebihi batas aman 50 MB.');
          }
          chunks.push(value);
        }
      }
      const merged = new Uint8Array(entryBytes);
      let offset = 0;
      for (const c of chunks) {
        merged.set(c, offset);
        offset += c.byteLength;
      }
      const decodedEntry = decoder.decode(merged);
      assertSafeArchiveXml(name, decodedEntry);
      out.set(name, decodedEntry);
    }
  }
  entrySpans.sort((a, b) => a[0] - b[0]);
  for (let i = 1; i < entrySpans.length; i += 1) {
    if (entrySpans[i][0] < entrySpans[i - 1][1] && entrySpans[i][0] >= entrySpans[i - 1][0]) {
      throw new Error('Arsip ZIP memiliki entri tumpang tindih (potensi zip bomb).');
    }
  }
  return out;
}

// inspectBinaryMagicBytes & validateUploadedFileMagic are imported & re-exported from ./langUtils

interface ParsedDocUnit {
  prefix?: string;
  text: string;
}

async function decompressFlateBytes(
  raw: Uint8Array,
  maxBytes: number
): Promise<Uint8Array | null> {
  if (typeof DecompressionStream === 'undefined') return null;
  for (const format of ['deflate', 'deflate-raw'] as const) {
    try {
      const ds = new DecompressionStream(format);
      const writer = ds.writable.getWriter();
      writer.write(raw).catch(() => { });
      writer.close().catch(() => { });
      const reader = ds.readable.getReader();
      const chunks: Uint8Array[] = [];
      let total = 0;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) {
          total += value.byteLength;
          if (total > maxBytes) {
            await reader.cancel();
            throw new Error('Ukuran dekompresi PDF melebihi batas aman 50 MB.');
          }
          chunks.push(value);
        }
      }
      const out = new Uint8Array(total);
      let pos = 0;
      for (const c of chunks) {
        out.set(c, pos);
        pos += c.byteLength;
      }
      return out;
    } catch (err) {
      if (err instanceof Error && err.message.includes('50 MB')) throw err;
    }
  }
  return null;
}

function decodePdfLiteralString(inner: string): string {
  const bytes: number[] = [];
  for (let i = 0; i < inner.length; i += 1) {
    const ch = inner[i];
    if (ch !== '\\') {
      bytes.push(inner.charCodeAt(i) & 0xff);
      continue;
    }
    i += 1;
    if (i >= inner.length) break;
    const esc = inner[i];
    if (esc === 'n') bytes.push(10);
    else if (esc === 'r') bytes.push(13);
    else if (esc === 't') bytes.push(9);
    else if (esc === 'b') bytes.push(8);
    else if (esc === 'f') bytes.push(12);
    else if (esc === '(' || esc === ')' || esc === '\\') bytes.push(esc.charCodeAt(0));
    else if (esc === '\r') {
      if (inner[i + 1] === '\n') i += 1;
    } else if (esc === '\n') {
      // ignore escaped line wrap
    } else if (esc >= '0' && esc <= '7') {
      let oct = esc;
      if (inner[i + 1] >= '0' && inner[i + 1] <= '7') {
        oct += inner[++i];
        if (inner[i + 1] >= '0' && inner[i + 1] <= '7') oct += inner[++i];
      }
      bytes.push(parseInt(oct, 8) & 0xff);
    } else {
      bytes.push(esc.charCodeAt(0) & 0xff);
    }
  }
  if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    return new TextDecoder('utf-16be').decode(new Uint8Array(bytes.slice(2)));
  }
  return new TextDecoder('utf-8', { fatal: false }).decode(new Uint8Array(bytes));
}

function decodeHexToUnicode(hex: string, cmap: Map<string, string>): string {
  const clean = hex.replace(/\s+/g, '').toUpperCase();
  if (!clean) return '';
  if (cmap.size > 0) {
    let out = '';
    let idx = 0;
    while (idx < clean.length) {
      const k4 = clean.slice(idx, idx + 4);
      if (k4.length === 4 && cmap.has(k4)) {
        out += cmap.get(k4)!;
        idx += 4;
        continue;
      }
      const k2 = clean.slice(idx, idx + 2);
      if (k2.length === 2 && cmap.has(k2)) {
        out += cmap.get(k2)!;
        idx += 2;
        continue;
      }
      idx += 2;
    }
    if (out) return out;
  }
  const rawBytes = new Uint8Array(Math.floor(clean.length / 2));
  for (let i = 0; i < rawBytes.length; i += 1) {
    rawBytes[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16) || 0;
  }
  if (rawBytes.length >= 2 && rawBytes[0] === 0xfe && rawBytes[1] === 0xff) {
    return new TextDecoder('utf-16be').decode(rawBytes.subarray(2));
  }
  if (rawBytes.length >= 2 && rawBytes.length % 2 === 0 && rawBytes[0] !== 0x00) {
    return new TextDecoder('utf-8', { fatal: false }).decode(rawBytes);
  }
  if (rawBytes.length >= 2 && rawBytes.length % 2 === 0) {
    return new TextDecoder('utf-16be').decode(rawBytes);
  }
  return new TextDecoder('latin1').decode(rawBytes);
}

function parseCMapInto(streamText: string, cmap: Map<string, string>): void {
  const MAX_CMAP_ENTRIES = 65536;
  if (cmap.size >= MAX_CMAP_ENTRIES) return;
  const bfcharRe = /beginbfchar([\s\S]*?)endbfchar/g;
  let m: RegExpExecArray | null;
  while ((m = bfcharRe.exec(streamText)) !== null && cmap.size < MAX_CMAP_ENTRIES) {
    const pairRe = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g;
    let pm: RegExpExecArray | null;
    while ((pm = pairRe.exec(m[1])) !== null && cmap.size < MAX_CMAP_ENTRIES) {
      const srcHex = pm[1].toUpperCase();
      const dstHex = pm[2];
      const u16 = new Uint8Array(Math.floor(dstHex.length / 2));
      for (let i = 0; i < u16.length; i += 1) {
        u16[i] = parseInt(dstHex.slice(i * 2, i * 2 + 2), 16) || 0;
      }
      cmap.set(srcHex, new TextDecoder('utf-16be').decode(u16));
    }
  }
  const bfrangeRe = /beginbfrange([\s\S]*?)endbfrange/g;
  while ((m = bfrangeRe.exec(streamText)) !== null && cmap.size < MAX_CMAP_ENTRIES) {
    const rangeRe = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g;
    let rm: RegExpExecArray | null;
    while ((rm = rangeRe.exec(m[1])) !== null && cmap.size < MAX_CMAP_ENTRIES) {
      const start = parseInt(rm[1], 16);
      const end = Math.min(parseInt(rm[2], 16), start + 512);
      let codePoint = parseInt(rm[3], 16);
      const width = rm[1].length;
      for (let cur = start; cur <= end && cmap.size < MAX_CMAP_ENTRIES; cur += 1, codePoint += 1) {
        if (codePoint < 0 || codePoint > 0x10ffff || (codePoint >= 0xd800 && codePoint <= 0xdfff)) {
          continue;
        }
        cmap.set(
          cur.toString(16).toUpperCase().padStart(width, '0'),
          String.fromCodePoint(codePoint)
        );
      }
    }
  }
}

function extractTextFromPdfContentStream(content: string, cmap: Map<string, string>): string[] {
  const lines: string[] = [];
  const btEtRe = /\bBT\b([\s\S]*?)\bET\b/g;
  let blockMatch: RegExpExecArray | null;

  while ((blockMatch = btEtRe.exec(content)) !== null) {
    const block = blockMatch[1];
    let currentLine = '';
    let idx = 0;

    const readParen = (): string => {
      idx += 1;
      let depth = 1;
      let raw = '';
      while (idx < block.length && depth > 0) {
        const ch = block[idx];
        if (ch === '\\') {
          raw += ch + (block[idx + 1] || '');
          idx += 2;
          continue;
        }
        if (ch === '(') depth += 1;
        else if (ch === ')') {
          depth -= 1;
          if (depth === 0) {
            idx += 1;
            break;
          }
        }
        raw += ch;
        idx += 1;
      }
      return decodePdfLiteralString(raw);
    };

    const readHex = (): string => {
      const close = block.indexOf('>', idx + 1);
      if (close < 0) {
        idx = block.length;
        return '';
      }
      const hex = block.slice(idx + 1, close);
      idx = close + 1;
      return decodeHexToUnicode(hex, cmap);
    };

    let pendingStr = '';
    const numWindow: number[] = [];
    const stickyNumRe = /[-+]?\d+(?:\.\d+)?/y;
    const stickyTokRe = /[^\s()<>[\]/%]+/y;

    while (idx < block.length) {
      const ch = block[idx];
      if (/\s/.test(ch)) {
        idx += 1;
        continue;
      }
      if (ch === '%') {
        const nl = block.indexOf('\n', idx);
        idx = nl < 0 ? block.length : nl + 1;
        continue;
      }
      if (ch === '(') {
        pendingStr = readParen();
        continue;
      }
      if (ch === '<' && block[idx + 1] !== '<') {
        pendingStr = readHex();
        continue;
      }
      if (ch === '[') {
        idx += 1;
        let arrText = '';
        while (idx < block.length && block[idx] !== ']') {
          if (block[idx] === '(') arrText += readParen();
          else if (block[idx] === '<' && block[idx + 1] !== '<') arrText += readHex();
          else if (/[-+\d.]/.test(block[idx])) {
            stickyNumRe.lastIndex = idx;
            const numMatch = stickyNumRe.exec(block);
            if (numMatch) {
              const kern = Number(numMatch[0]);
              if (kern <= -180 && arrText && !arrText.endsWith(' ') && !CJK_RE.test(arrText.slice(-1))) {
                arrText += ' ';
              }
              idx = stickyNumRe.lastIndex;
            } else {
              idx += 1;
            }
          } else {
            idx += 1;
          }
        }
        if (block[idx] === ']') idx += 1;
        pendingStr = arrText;
        continue;
      }

      stickyTokRe.lastIndex = idx;
      const tokMatch = stickyTokRe.exec(block);
      if (!tokMatch) {
        idx += 1;
        continue;
      }
      const tok = tokMatch[0];
      idx = stickyTokRe.lastIndex;

      const asNum = Number(tok);
      if (!Number.isNaN(asNum)) {
        numWindow.push(asNum);
        if (numWindow.length > 6) numWindow.shift();
        continue;
      }

      if (tok === 'Tj' || tok === 'TJ') {
        currentLine += pendingStr;
        pendingStr = '';
      } else if (tok === "'" || tok === '"') {
        if (currentLine.trim()) lines.push(currentLine.trim());
        currentLine = pendingStr;
        pendingStr = '';
      } else if (tok === 'T*') {
        if (currentLine.trim()) lines.push(currentLine.trim());
        currentLine = '';
      } else if (tok === 'Td' || tok === 'TD') {
        const ty = numWindow.length >= 2 ? numWindow[numWindow.length - 1] : 0;
        if (Math.abs(ty) > 0.5 && currentLine.trim()) {
          lines.push(currentLine.trim());
          currentLine = '';
        }
      } else if (tok === 'Tm') {
        if (currentLine.trim()) {
          lines.push(currentLine.trim());
          currentLine = '';
        }
      }
      numWindow.length = 0;
    }

    if (currentLine.trim()) lines.push(currentLine.trim());
  }

  return lines;
}

async function extractPdfUnitsNative(buffer: ArrayBuffer): Promise<ParsedDocUnit[]> {
  const bytes = new Uint8Array(buffer);
  const latin = new TextDecoder('latin1').decode(bytes);
  if (/\/Encrypt\b/.test(latin.slice(0, 4096)) || /\/Encrypt\s+\d+\s+\d+\s+R/.test(latin)) {
    throw new Error('Berkas PDF terkunci sandi atau ber-DRM.');
  }

  const MAX_PDF_DECOMP_BYTES = 50 * 1024 * 1024;
  let totalDecompressed = 0;
  const decodedStreams: string[] = [];
  const cmap = new Map<string, string>();
  const latinDecoder = new TextDecoder('latin1');

  let searchFrom = 0;
  while (searchFrom < latin.length) {
    const streamKw = latin.indexOf('stream', searchFrom);
    if (streamKw < 0) break;
    const prevChar = streamKw > 0 ? latin[streamKw - 1] : ' ';
    const afterKw = streamKw + 6;
    const hasValidLead = prevChar === '>' || /\s/.test(prevChar);
    const eolLen =
      latin.slice(afterKw, afterKw + 2) === '\r\n'
        ? 2
        : latin[afterKw] === '\n' || latin[afterKw] === '\r'
          ? 1
          : 0;
    if (!hasValidLead || eolLen === 0) {
      searchFrom = afterKw;
      continue;
    }

    const dictStart = Math.max(0, latin.lastIndexOf('<<', streamKw));
    const dictStr = latin.slice(dictStart, streamKw);
    const dataStart = afterKw + eolLen;
    const endKw = latin.indexOf('endstream', dataStart);
    if (endKw < 0) break;
    searchFrom = endKw + 9;

    if (/\/Subtype\s*\/Image|\/Type\s*\/XRef|\/Length1\b|\/DCTDecode|\/JPXDecode/.test(dictStr)) {
      continue;
    }

    let dataEnd = endKw;
    if (latin.slice(dataEnd - 2, dataEnd) === '\r\n') dataEnd -= 2;
    else if (latin[dataEnd - 1] === '\n' || latin[dataEnd - 1] === '\r') dataEnd -= 1;
    if (dataEnd <= dataStart) continue;

    const rawSlice = bytes.subarray(dataStart, dataEnd);
    let streamStr = '';
    if (/\/FlateDecode\b/.test(dictStr)) {
      const inflated = await decompressFlateBytes(
        rawSlice,
        MAX_PDF_DECOMP_BYTES - totalDecompressed
      );
      if (!inflated) continue;
      totalDecompressed += inflated.byteLength;
      streamStr = latinDecoder.decode(inflated);
    } else {
      totalDecompressed += rawSlice.byteLength;
      if (totalDecompressed > MAX_PDF_DECOMP_BYTES) {
        throw new Error('Ukuran dekompresi PDF melebihi batas aman 50 MB.');
      }
      streamStr = latinDecoder.decode(rawSlice);
    }

    if (streamStr.includes('beginbfchar') || streamStr.includes('beginbfrange')) {
      parseCMapInto(streamStr, cmap);
    } else if (/\bBT\b/.test(streamStr)) {
      decodedStreams.push(streamStr);
    }
  }

  const allLines: string[] = [];
  for (const s of decodedStreams) {
    allLines.push(...extractTextFromPdfContentStream(s, cmap));
  }

  const units: ParsedDocUnit[] = [];
  let acc: string[] = [];
  for (const ln of allLines) {
    const clean = ln.replace(/\s+/g, ' ').trim();
    if (!clean) continue;
    acc.push(clean);
    if (/[.!?。！？]$/.test(clean) || acc.join(' ').length >= 280) {
      units.push({ text: acc.join(' ') });
      acc = [];
    }
  }
  if (acc.length > 0) units.push({ text: acc.join(' ') });
  return units;
}

interface WarmTesseractSlot {
  workerPromise: Promise<import('tesseract.js').Worker>;
  queue: Promise<unknown>;
  idleTimer: number | null;
}

const warmTesseractWorkers = new Map<string, WarmTesseractSlot>();

function getTesseractIdleTtlMs(): number {
  return getDeviceRuntimeProfile().isConstrained ? 25_000 : 60_000;
}

function terminateAllWarmTesseractWorkers(): void {
  for (const [, slot] of warmTesseractWorkers.entries()) {
    if (slot.idleTimer !== null) {
      globalThis.clearTimeout(slot.idleTimer);
      slot.idleTimer = null;
    }
    slot.workerPromise.then((w) => w.terminate()).catch(() => { });
  }
  warmTesseractWorkers.clear();
}

async function getWarmTesseractSlot(langs: string[]): Promise<WarmTesseractSlot> {
  const key = langs.join('+');
  const existing = warmTesseractWorkers.get(key);
  if (existing) {
    if (existing.idleTimer !== null) {
      globalThis.clearTimeout(existing.idleTimer);
      existing.idleTimer = null;
    }
    return existing;
  }

  // Cap resident WASM OCR workers strictly to 1 (~60-110 MB each) so mobile PWA never hits OOM
  if (warmTesseractWorkers.size >= 1) {
    terminateAllWarmTesseractWorkers();
  }

  const workerPromise = (async () => {
    const [{ createWorker }, workerUrlMod] = await Promise.all([
      import('tesseract.js'),
      import('tesseract.js/dist/worker.min.js?url'),
    ]);
    const resolvedWorkerUrl =
      typeof window !== 'undefined'
        ? new URL(workerUrlMod.default, window.location.origin).href
        : workerUrlMod.default;
    return createWorker(langs, 1, {
      workerPath: resolvedWorkerUrl,
      workerBlobURL: false,
      logger: () => { },
    });
  })();

  const slot: WarmTesseractSlot = {
    workerPromise,
    queue: Promise.resolve(),
    idleTimer: null,
  };
  warmTesseractWorkers.set(key, slot);

  workerPromise.catch(() => {
    if (warmTesseractWorkers.get(key) === slot) {
      warmTesseractWorkers.delete(key);
    }
  });
  return slot;
}

function scheduleTesseractIdleCleanup(key: string, slot: WarmTesseractSlot): void {
  if (typeof window === 'undefined') return;
  if (slot.idleTimer !== null) globalThis.clearTimeout(slot.idleTimer);
  slot.idleTimer = globalThis.setTimeout(() => {
    if (warmTesseractWorkers.get(key) !== slot) return;
    warmTesseractWorkers.delete(key);
    slot.workerPromise
      .then((w) => w.terminate())
      .catch(() => { });
  }, getTesseractIdleTtlMs()) as unknown as number;
}

async function preprocessImageForTesseract(
  imageSource: string | HTMLCanvasElement,
  imgW: number,
  imgH: number
): Promise<{ source: string | HTMLCanvasElement; scale: number; dispose: () => void }> {
  if (typeof document === 'undefined' || imgW <= 0 || imgH <= 0) {
    return { source: imageSource, scale: 1, dispose: () => { } };
  }
  const baseScale = Math.max(imgW, imgH) < 1100 ? 2 : 1;
  // Single uniform scale across both axes preserves aspect ratio & exact Tesseract OCR box coordinates
  const effScale = Math.min(baseScale, 2400 / imgW, 3200 / imgH);
  const targetW = Math.max(1, Math.round(imgW * effScale));
  const targetH = Math.max(1, Math.round(imgH * effScale));
  if (targetW * targetH > 6_400_000) {
    return { source: imageSource, scale: 1, dispose: () => { } };
  }
  try {
    let drawSource: CanvasImageSource;
    if (typeof imageSource === 'string') {
      drawSource = await new Promise<HTMLImageElement>((resolve, reject) => {
        const im = new Image();
        im.onload = () => resolve(im);
        im.onerror = () => reject(new Error('load failed'));
        im.src = imageSource;
      });
    } else {
      drawSource = imageSource;
    }
    const canvas = document.createElement('canvas');
    canvas.width = targetW;
    canvas.height = targetH;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) {
      canvas.width = 0;
      canvas.height = 0;
      return { source: imageSource, scale: 1, dispose: () => { } };
    }
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(drawSource, 0, 0, targetW, targetH);

    // Rec. 709 grayscale + 2%-98% contrast stretch + dark-bubble auto-inversion + mild 3x3 unsharp boost
    const imgData = ctx.getImageData(0, 0, targetW, targetH);
    const d = imgData.data;
    const hist = new Uint32Array(256);
    const lum = new Uint8Array(targetW * targetH);
    for (let i = 0, p = 0; i < d.length; i += 4, p += 1) {
      const y = Math.round(0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]);
      lum[p] = y;
      hist[y] += 1;
    }
    const totalPx = targetW * targetH;
    let acc = 0;
    let p02 = -1;
    let p50 = -1;
    let p98 = 255;
    for (let v = 0; v < 256; v += 1) {
      acc += hist[v];
      if (p02 === -1 && acc >= totalPx * 0.02) p02 = v;
      if (p50 === -1 && acc >= totalPx * 0.5) p50 = v;
      if (acc >= totalPx * 0.98) {
        p98 = v;
        break;
      }
    }
    if (p02 < 0) p02 = 0;
    if (p50 < 0) p50 = 128;
    const span = Math.max(16, p98 - p02);
    const invertDark = p50 < 110;
    const stretched = new Uint8Array(totalPx);
    for (let p = 0; p < totalPx; p += 1) {
      let val = Math.max(0, Math.min(255, Math.round(((lum[p] - p02) * 255) / span)));
      if (invertDark) val = 255 - val;
      stretched[p] = val;
    }
    // Lightweight 3x3 unsharp mask on interior pixels (amount=0.45)
    for (let y = 1; y < targetH - 1; y += 1) {
      const rowOff = y * targetW;
      for (let x = 1; x < targetW - 1; x += 1) {
        const idx = rowOff + x;
        const blur =
          (stretched[idx - targetW] +
            stretched[idx + targetW] +
            stretched[idx - 1] +
            stretched[idx + 1] +
            stretched[idx] * 2) /
          6;
        const sharp = Math.max(0, Math.min(255, Math.round(stretched[idx] + 0.45 * (stretched[idx] - blur))));
        const o = idx * 4;
        d[o] = sharp;
        d[o + 1] = sharp;
        d[o + 2] = sharp;
        d[o + 3] = 255;
      }
    }
    ctx.putImageData(imgData, 0, 0);
    return {
      source: canvas,
      scale: effScale,
      dispose: () => {
        canvas.width = 0;
        canvas.height = 0;
      },
    };
  } catch {
    return { source: imageSource, scale: 1, dispose: () => { } };
  }
}

async function runTesseractOcrBoxes(
  imageSource: string | HTMLCanvasElement,
  imgW: number,
  imgH: number,
  srcLang: SourceLang
): Promise<Array<{ id: number; box_2d: number[]; text: string }>> {
  const langs =
    srcLang === 'ja'
      ? ['jpn', 'eng']
      : srcLang === 'id'
        ? ['ind', 'eng']
        : srcLang === 'en'
          ? ['eng']
          : ['jpn', 'eng'];
  const key = langs.join('+');
  const slot = await getWarmTesseractSlot(langs);

  const runRecognize = async () => {
    if (slot.idleTimer !== null && typeof window !== 'undefined') {
      window.clearTimeout(slot.idleTimer);
      slot.idleTimer = null;
    }
    const prep = await preprocessImageForTesseract(imageSource, imgW, imgH);
    const effW = imgW * prep.scale;
    const effH = imgH * prep.scale;
    try {
      const worker = await slot.workerPromise;
      const { data } = await worker.recognize(
        prep.source,
        {},
        { text: true, blocks: true }
      );
      const out: Array<{ id: number; box_2d: number[]; text: string }> = [];
      const blocks = Array.isArray(data?.blocks) ? data.blocks : [];

      for (const blk of blocks) {
        const paras = Array.isArray(blk.paragraphs) ? blk.paragraphs : [];
        for (const para of paras) {
          if (typeof para.confidence === 'number' && para.confidence > 0 && para.confidence < 38) {
            continue;
          }
          const cleaned = cleanCjkSpacing((para.text || '').replace(/\s+/g, ' ').trim());
          if (!cleaned || !hasTranslatableLetters(cleaned)) continue;
          const bb = para.bbox || blk.bbox;
          if (bb) {
            const ymin = Math.max(0, Math.min(1000, Math.round((bb.y0 / effH) * 1000)));
            const xmin = Math.max(0, Math.min(1000, Math.round((bb.x0 / effW) * 1000)));
            const ymax = Math.max(0, Math.min(1000, Math.round((bb.y1 / effH) * 1000)));
            const xmax = Math.max(0, Math.min(1000, Math.round((bb.x1 / effW) * 1000)));
            out.push({ id: out.length + 1, box_2d: [ymin, xmin, ymax, xmax], text: cleaned });
          }
        }
      }

      if (out.length === 0 && data?.text) {
        const fallbackLines = data.text
          .split(/\r?\n/)
          .map((l) => cleanCjkSpacing(l.trim()))
          .filter((l) => l.length > 0 && hasTranslatableLetters(l));
        const count = Math.max(fallbackLines.length, 1);
        fallbackLines.forEach((line, idx) => {
          const ymin = Math.round(((idx + 0.3) / (count + 0.6)) * 1000);
          const ymax = Math.min(1000, ymin + Math.round(700 / count));
          out.push({ id: idx + 1, box_2d: [ymin, 50, ymax, 950], text: line });
        });
      }

      scheduleTesseractIdleCleanup(key, slot);
      return out;
    } catch (err) {
      if (warmTesseractWorkers.get(key) === slot) {
        warmTesseractWorkers.delete(key);
        slot.workerPromise
          .then((w) => w.terminate())
          .catch(() => { });
      }
      throw err;
    } finally {
      prep.dispose();
    }
  };

  const resultPromise = slot.queue.then(runRecognize, runRecognize);
  slot.queue = resultPromise.catch(() => { });
  return resultPromise;
}

async function extractPdfUnitsWithPdfJs(
  buffer: ArrayBuffer,
  mode: ModePair
): Promise<ParsedDocUnit[]> {
  const [pdfjs, workerUrlMod] = await Promise.all([
    import('pdfjs-dist'),
    import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
  ]);
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrlMod.default;

  const loadingTask = pdfjs.getDocument({
    data: new Uint8Array(buffer),
    cMapUrl: `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/standard_fonts/`,
  });
  try {
    const pdf = await loadingTask.promise;

    if (pdf.numPages > 500) {
      throw new Error(`PDF memiliki ${pdf.numPages} halaman (batas maksimum 500 halaman).`);
    }

    const maxPages = Math.min(pdf.numPages, 120);
    const pageLineGroups: string[][] = [];

    for (let p = 1; p <= maxPages; p += 1) {
      const page = await pdf.getPage(p);
      try {
        const viewport = page.getViewport({ scale: 1 });
        const pageW = Math.max(100, viewport.width || 612);
        const textContent = await page.getTextContent();

        type PdfGlyphSpan = { str: string; x: number; y: number; w: number; h: number };
        const spans: PdfGlyphSpan[] = [];
        for (const rawItem of textContent.items) {
          if (!('str' in rawItem)) continue;
          const s = rawItem.str || '';
          if (!s.trim()) continue;
          const x = Array.isArray(rawItem.transform) ? Number(rawItem.transform[4]) : 0;
          const y = Array.isArray(rawItem.transform) ? Number(rawItem.transform[5]) : 0;
          const h = Array.isArray(rawItem.transform)
            ? Math.max(8, Math.abs(Number(rawItem.transform[3]) || Number(rawItem.transform[0]) || 11))
            : 11;
          const w = typeof rawItem.width === 'number' && rawItem.width > 0 ? rawItem.width : s.length * (h * 0.48);
          spans.push({ str: s, x, y, w, h });
        }

        // Step 1: Strictly transitive Y-baseline clustering -> merge horizontally adjacent word spans into logical segments
        type PdfSegment = { text: string; x1: number; x2: number; y: number };
        const sortedByY = [...spans].sort((a, b) => b.y - a.y || a.x - b.x);
        const rows: PdfGlyphSpan[][] = [];
        for (const sp of sortedByY) {
          const lastRow = rows[rows.length - 1];
          if (!lastRow || Math.abs(lastRow[0].y - sp.y) > 4.5) {
            rows.push([sp]);
          } else {
            lastRow.push(sp);
          }
        }
        const mergedSegments: PdfSegment[] = [];
        for (const row of rows) {
          row.sort((a, b) => a.x - b.x);
          let segText = '';
          let segX1 = 0;
          let segX2 = 0;
          let segY = row[0].y;
          for (const sp of row) {
            if (!segText) {
              segText = sp.str;
              segX1 = sp.x;
              segX2 = sp.x + sp.w;
              segY = sp.y;
              continue;
            }
            const hGap = sp.x - segX2;
            const gutterThresh = Math.max(18, sp.h * 1.8);
            if (hGap > gutterThresh) {
              mergedSegments.push({ text: cleanCjkSpacing(segText.trim()), x1: segX1, x2: segX2, y: segY });
              segText = sp.str;
              segX1 = sp.x;
              segX2 = sp.x + sp.w;
            } else {
              const needsSpace = hGap > Math.max(1.2, sp.h * 0.14) && !segText.endsWith(' ') && !CJK_RE.test(sp.str);
              segText += needsSpace ? ` ${sp.str}` : sp.str;
              segX2 = Math.max(segX2, sp.x + sp.w);
            }
          }
          if (segText.trim()) {
            mergedSegments.push({ text: cleanCjkSpacing(segText.trim()), x1: segX1, x2: segX2, y: segY });
          }
        }

        // Step 2: Detect genuine 2-column gutter ONLY on merged line segments (never splits single-column word runs!)
        const gutterL = pageW * 0.45;
        const gutterR = pageW * 0.55;
        const crossingGutter = mergedSegments.filter((seg) => seg.x1 < gutterL && seg.x2 > gutterR);
        const leftSegs = mergedSegments.filter((seg) => seg.x2 <= gutterR);
        const rightSegs = mergedSegments.filter((seg) => seg.x1 >= gutterL);
        let dualRowCount = 0;
        for (const lSeg of leftSegs) {
          if (rightSegs.some((rSeg) => Math.abs(rSeg.y - lSeg.y) <= 6)) dualRowCount += 1;
        }
        const isTwoColumn =
          dualRowCount >= 4 &&
          leftSegs.length >= 4 &&
          rightSegs.length >= 4 &&
          crossingGutter.length <= Math.max(2, Math.floor(mergedSegments.length * 0.12));

        let pageLines: string[];
        if (isTwoColumn) {
          const colTop = Math.max(...leftSegs.map((s) => s.y), ...rightSegs.map((s) => s.y));
          const fullTop = crossingGutter.filter((s) => s.y > colTop + 6).map((s) => s.text);
          const fullBottom = crossingGutter.filter((s) => s.y <= colTop + 6).map((s) => s.text);
          pageLines = [
            ...fullTop,
            ...leftSegs.map((s) => s.text),
            ...rightSegs.map((s) => s.text),
            ...fullBottom,
          ];
        } else {
          pageLines = mergedSegments.map((s) => s.text);
        }

        pageLineGroups.push(pageLines);
      } finally {
        page.cleanup?.();
        prevY = sp.y;
      }
    }

    // Strip repeated running headers & footers appearing on >= 40% of pages (when >= 3 pages)
    const repeatedEdgeLines = new Set<string>();
    if (pageLineGroups.length >= 3) {
      const edgeFreq = new Map<string, number>();
      for (const pl of pageLineGroups) {
        if (pl.length < 3) continue;
        const norm = (s: string) => s.replace(/\d+/g, '#').trim().toLowerCase();
        const first = norm(pl[0]);
        const last = norm(pl[pl.length - 1]);
        if (first.length <= 90) edgeFreq.set(first, (edgeFreq.get(first) || 0) + 1);
        if (last.length <= 90 && last !== first) edgeFreq.set(last, (edgeFreq.get(last) || 0) + 1);
      }
      const minPages = Math.max(2, Math.ceil(pageLineGroups.length * 0.4));
      for (const [key, cnt] of edgeFreq.entries()) {
        if (cnt >= minPages) repeatedEdgeLines.add(key);
      }
    }

    const units: ParsedDocUnit[] = [];
    for (const pl of pageLineGroups) {
      const filtered = pl.filter((ln, idx) => {
        if ((idx === 0 || idx === pl.length - 1) && repeatedEdgeLines.size > 0) {
          const key = ln.replace(/\d+/g, '#').trim().toLowerCase();
          if (repeatedEdgeLines.has(key)) return false;
        }
        return Boolean(ln);
      });
      let paraBuf: string[] = [];
      const flushPara = () => {
        if (paraBuf.length === 0) return;
        let joined = paraBuf[0];
        for (let li = 1; li < paraBuf.length; li += 1) {
          const prev = paraBuf[li - 1];
          const next = paraBuf[li];
          if (/[A-Za-z]{2,}[-\u00AD]$/.test(prev) && /^[a-z]{2,}/.test(next)) {
            joined = joined.replace(/[-\u00AD]$/, '') + next;
          } else if (CJK_RE.test(prev.slice(-1)) && CJK_RE.test(next.slice(0, 1))) {
            joined += next;
          } else {
            joined += ` ${next}`;
          }
        }
        units.push({ text: cleanCjkSpacing(joined.trim()) });
        paraBuf = [];
      };
      for (const ln of filtered) {
        paraBuf.push(ln);
        if (/[.!?。！？」』]$/.test(ln) || paraBuf.join(' ').length >= 260) {
          flushPara();
        }
      }
      flushPara();
    }

    if (units.length > 0) {
      if (pdf.numPages > maxPages) {
        units.push({
          text: `[Catatan tranX: PDF memiliki ${pdf.numPages} halaman; mode peramban memproses ${maxPages} halaman pertama.]`,
        });
      }
      return units;
    }

    // Scanned image-only PDF: render pages to canvas and OCR via Tesseract (strict GPU cleanup in finally)
    const { src } = parseModePair(mode);
    const ocrPages = Math.min(pdf.numPages, 6);
    for (let p = 1; p <= ocrPages; p += 1) {
      const page = await pdf.getPage(p);
      const viewport = page.getViewport({ scale: 1.7 });
      const canvas = document.createElement('canvas');
      try {
        canvas.width = Math.max(1, Math.floor(viewport.width));
        canvas.height = Math.max(1, Math.floor(viewport.height));
        const ctx = canvas.getContext('2d');
        if (!ctx) continue;
        await page.render({ canvasContext: ctx, canvas, viewport }).promise;
        const boxes = await runTesseractOcrBoxes(canvas, canvas.width, canvas.height, src);
        for (const b of boxes) {
          if (b.text.trim()) units.push({ text: b.text.trim() });
        }
      } finally {
        canvas.width = 0;
        canvas.height = 0;
        page.cleanup?.();
      }
    }
    return units;
  } finally {
    await loadingTask.destroy().catch(() => { });
  }
}

function parseAssSubtitleUnits(rawText: string): {
  headerDoc: string;
  units: ParsedDocUnit[];
} {
  const lines = rawText.replace(/\r\n/g, '\n').split('\n');
  const headerLines: string[] = [];
  const units: ParsedDocUnit[] = [];
  let inEvents = false;
  let commaCount = 9;

  for (const line of lines) {
    const trimmed = line.trim();
    if (/^\[.*\]$/.test(trimmed)) {
      inEvents = trimmed.toLowerCase() === '[events]';
      headerLines.push(line);
      continue;
    }
    if (inEvents && /^format\s*:/i.test(trimmed)) {
      const cols = trimmed
        .slice(trimmed.indexOf(':') + 1)
        .split(',')
        .map((c) => c.trim());
      if (cols.length >= 2) commaCount = cols.length - 1;
      headerLines.push(line);
      continue;
    }
    if (inEvents && /^dialogue\s*:/i.test(trimmed)) {
      let pos = 0;
      let seenCommas = 0;
      while (pos < line.length && seenCommas < commaCount) {
        if (line[pos] === ',') seenCommas += 1;
        pos += 1;
      }
      if (seenCommas === commaCount) {
        const metaPrefix = line.slice(0, pos);
        const bodyRaw = line.slice(pos);
        const leadTagsMatch = bodyRaw.match(/^((?:\{[^}]*\})*)/);
        const leadTags = leadTagsMatch ? leadTagsMatch[1] : '';
        const spoken = bodyRaw
          .slice(leadTags.length)
          .replace(/\{[^}]*\}/g, '')
          .replace(/\\[Nn]/g, '\n')
          .trim();
        if (spoken) {
          units.push({
            prefix: `${metaPrefix}${leadTags}`,
            text: spoken,
          });
        }
        continue;
      }
    }
    headerLines.push(line);
  }

  return { headerDoc: headerLines.join('\n').trimEnd(), units };
}

async function parseDocumentUnitsInBrowser(
  file: File,
  mode: ModePair = 'auto-id'
): Promise<{
  fmt: string;
  headerDoc?: string;
  units: ParsedDocUnit[];
}> {
  const ext = (file.name.split('.').pop() || 'txt').toLowerCase();
  const fullBuf = await file.arrayBuffer();
  const magicErr = inspectBinaryMagicBytes(new Uint8Array(fullBuf), ext, 'dokumen');
  if (magicErr) {
    throw new Error(magicErr);
  }

  if (ext === 'docx') {
    const entries = await extractZipTextEntries(fullBuf, (n) => n === 'word/document.xml');
    const xml = entries.get('word/document.xml') || '';
    const dom = new DOMParser().parseFromString(xml, 'application/xml');
    const pNodes = Array.from(dom.getElementsByTagName('w:p'));
    const units: ParsedDocUnit[] = [];
    for (const p of pNodes) {
      const runs = Array.from(p.getElementsByTagName('w:t'))
        .map((t) => t.textContent || '')
        .join('')
        .trim();
      if (runs) units.push({ text: runs });
    }
    return { fmt: 'docx', units };
  }

  if (ext === 'epub') {
    // EPUB 3.3 compliant OPF <spine> reading order + <rt>/<rp> furigana stripping
    const entries = await extractZipTextEntries(
      fullBuf,
      (n) => /\.(?:xhtml|html|htm|opf|xml)$/i.test(n)
    );
    let orderedNames: string[] = [];
    const containerXml = entries.get('META-INF/container.xml') || '';
    const opfPathMatch = containerXml.match(/full-path=["']([^"']+\.opf)["']/i);
    const opfPath = opfPathMatch?.[1] || Array.from(entries.keys()).find((k) => /\.opf$/i.test(k)) || '';
    const opfXml = opfPath ? entries.get(opfPath) || '' : '';
    if (opfXml) {
      const opfDir = opfPath.includes('/') ? opfPath.slice(0, opfPath.lastIndexOf('/') + 1) : '';
      const opfDom = new DOMParser().parseFromString(opfXml, 'application/xml');
      const manifestMap = new Map<string, string>();
      const itemNodes = Array.from(opfDom.getElementsByTagNameNS('*', 'item'));
      itemNodes.forEach((el) => {
        const id = el.getAttribute('id') || '';
        const href = el.getAttribute('href') || '';
        const props = el.getAttribute('properties') || '';
        if (id && href && !/\bnav\b/i.test(props)) {
          try {
            const resolvedUrl = new URL(href, `https://epub.local/${opfDir}`);
            const rawPath = resolvedUrl.pathname.replace(/^\/+/, '');
            let normPath = rawPath;
            try {
              normPath = decodeURIComponent(rawPath);
            } catch {
              // keep raw encoded path if malformed percent sequence
            }
            manifestMap.set(id, normPath);
          } catch {
            // ignore invalid manifest href
          }
        }
      });
      Array.from(opfDom.getElementsByTagNameNS('*', 'itemref')).forEach((el) => {
        const idref = el.getAttribute('idref') || '';
        const resolved = manifestMap.get(idref);
        if (resolved && entries.has(resolved)) {
          orderedNames.push(resolved);
        }
      });
    }
    if (orderedNames.length === 0) {
      orderedNames = Array.from(entries.keys())
        .filter((n) => /\.(xhtml|html|htm)$/i.test(n) && !n.toLowerCase().includes('nav'))
        .sort();
    }

    const units: ParsedDocUnit[] = [];
    for (const name of orderedNames) {
      const doc = new DOMParser().parseFromString(entries.get(name) || '', 'text/html');
      // Remove ruby reading annotations (<rt>/<rp>) so Japanese novels translate base text cleanly
      doc.querySelectorAll('rt, rp').forEach((n) => n.remove());
      const blocks = Array.from(doc.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li, blockquote'));
      if (blocks.length > 0) {
        for (const b of blocks) {
          const txt = (b.textContent || '').trim();
          if (txt) units.push({ text: txt });
        }
      } else {
        // Fallback for non-semantic EPUB chapters wrapped exclusively in leaf <div> blocks
        const leafDivs = Array.from(doc.querySelectorAll('div')).filter(
          (d) => d.querySelector('div, p, h1, h2, h3, h4, h5, h6, li, blockquote') === null
        );
        for (const d of leafDivs) {
          const txt = (d.textContent || '').trim();
          if (txt) units.push({ text: txt });
        }
      }
    }
    return { fmt: 'epub', units };
  }

  if (ext === 'pdf') {
    try {
      const pdfJsUnits = await extractPdfUnitsWithPdfJs(fullBuf, mode);
      if (pdfJsUnits.length > 0) {
        return { fmt: 'pdf', units: pdfJsUnits };
      }
    } catch (err) {
      if (err instanceof Error && err.message.includes('batas maksimum')) throw err;
    }
    const nativeUnits = await extractPdfUnitsNative(fullBuf);
    if (nativeUnits.length > 0) {
      return { fmt: 'pdf', units: nativeUnits };
    }
    throw new Error('Berkas PDF tidak memiliki teks yang dapat dibaca.');
  }

  const rawText = new TextDecoder('utf-8', { fatal: false }).decode(fullBuf);
  if (ext === 'ass' || ext === 'ssa') {
    const { headerDoc, units } = parseAssSubtitleUnits(rawText);
    return { fmt: 'ass', headerDoc, units };
  }

  if (ext === 'srt' || ext === 'vtt') {
    const blocks = rawText.replace(/\r\n/g, '\n').split(/\n{2,}/);
    const units: ParsedDocUnit[] = [];
    for (const blk of blocks) {
      const lines = blk.trim().split('\n');
      const tsIdx = lines.findIndex((l) => l.includes('-->'));
      if (tsIdx >= 0 && tsIdx + 1 < lines.length) {
        units.push({
          prefix: lines.slice(0, tsIdx + 1).join('\n'),
          text: lines.slice(tsIdx + 1).join('\n').trim(),
        });
      }
    }
    return { fmt: ext, units };
  }

  if (ext === 'html' || ext === 'htm' || ext === 'xhtml') {
    const doc = new DOMParser().parseFromString(rawText, 'text/html');
    const blocks = Array.from(doc.querySelectorAll('h1, h2, h3, p, li'));
    const units = blocks
      .map((b) => ({ text: (b.textContent || '').trim() }))
      .filter((u) => u.text.length > 0);
    return { fmt: 'html', units };
  }

  const paras = rawText
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((text) => ({ text }));
  return { fmt: ext, units: paras };
}

const directExportCache = new BoundedLruCache<
  string,
  {
    fileName: string;
    fmt: string;
    headerDoc?: string;
    units: Array<{ prefix?: string; src: string; dst: string }>;
  }
>(6);

const CRC32_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32Bytes(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i += 1) {
    crc = CRC32_TABLE[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function escapeXml(raw: string): string {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function buildDocxArchiveBytes(
  title: string,
  rows: Array<{ src: string; dst: string }>,
  bilingual?: boolean
): Uint8Array {
  const enc = new TextEncoder();
  const bodyParas: string[] = [
    `<w:p><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t xml:space="preserve">${escapeXml(
      title
    )}</w:t></w:r></w:p>`,
  ];
  for (const r of rows) {
    if (bilingual && r.src) {
      bodyParas.push(
        `<w:p><w:r><w:rPr><w:color w:val="5C6661"/></w:rPr><w:t xml:space="preserve">${escapeXml(
          r.src
        )}</w:t></w:r></w:p>`
      );
    }
    for (const ln of (r.dst || '').split('\n')) {
      bodyParas.push(
        `<w:p><w:r><w:t xml:space="preserve">${escapeXml(ln)}</w:t></w:r></w:p>`
      );
    }
  }

  const files: Array<[string, Uint8Array]> = [
    [
      '[Content_Types].xml',
      enc.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
        '</Types>'
      ),
    ],
    [
      '_rels/.rels',
      enc.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
        '</Relationships>'
      ),
    ],
    [
      'word/document.xml',
      enc.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
        `<w:body>${bodyParas.join('')}<w:sectPr/></w:body></w:document>`
      ),
    ],
  ];

  const localChunks: Uint8Array[] = [];
  const cdChunks: Uint8Array[] = [];
  let localOffset = 0;

  for (const [name, content] of files) {
    const nameBytes = enc.encode(name);
    const crc = crc32Bytes(content);

    const lh = new Uint8Array(30 + nameBytes.length + content.length);
    const lhv = new DataView(lh.buffer);
    lhv.setUint32(0, 0x04034b50, true);
    lhv.setUint16(4, 20, true);
    lhv.setUint16(6, 0x0800, true);
    lhv.setUint16(8, 0, true);
    lhv.setUint32(14, crc, true);
    lhv.setUint32(18, content.length, true);
    lhv.setUint32(22, content.length, true);
    lhv.setUint16(26, nameBytes.length, true);
    lh.set(nameBytes, 30);
    lh.set(content, 30 + nameBytes.length);
    localChunks.push(lh);

    const cd = new Uint8Array(46 + nameBytes.length);
    const cdv = new DataView(cd.buffer);
    cdv.setUint32(0, 0x02014b50, true);
    cdv.setUint16(4, 20, true);
    cdv.setUint16(6, 20, true);
    cdv.setUint16(8, 0x0800, true);
    cdv.setUint16(10, 0, true);
    cdv.setUint32(16, crc, true);
    cdv.setUint32(20, content.length, true);
    cdv.setUint32(24, content.length, true);
    cdv.setUint16(28, nameBytes.length, true);
    cdv.setUint32(42, localOffset, true);
    cd.set(nameBytes, 46);
    cdChunks.push(cd);

    localOffset += lh.length;
  }

  const cdSize = cdChunks.reduce((acc, b) => acc + b.length, 0);
  const eocd = new Uint8Array(22);
  const ev = new DataView(eocd.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, files.length, true);
  ev.setUint16(10, files.length, true);
  ev.setUint32(12, cdSize, true);
  ev.setUint32(16, localOffset, true);

  const out = new Uint8Array(localOffset + cdSize + 22);
  let cursor = 0;
  for (const part of [...localChunks, ...cdChunks, eocd]) {
    out.set(part, cursor);
    cursor += part.length;
  }
  return out;
}

export async function directTranslateDocumentFile(params: {
  cid: string;
  mid: string;
  mode: ModePair;
  titleId?: string;
  file: File;
  onProgress?: (pct: number) => void;
}): Promise<string> {
  const jobId = `job_${Date.now().toString(36)}`;
  const { fmt, headerDoc, units } = await parseDocumentUnitsInBrowser(
    params.file,
    params.mode
  );
  if (units.length === 0) {
    throw new Error('Berkas tidak memiliki teks yang dapat diterjemahkan.');
  }

  const cappedUnits = units.slice(0, 200);
  await Promise.all([
    upsertConversationMeta(params.cid, {
      title: params.file.name,
      titleId: params.titleId || '',
      mode: params.mode,
      activeTab: 'dokumen',
      preview: params.file.name,
    }),
    saveDirectJobRecord({
      id: jobId,
      cid: params.cid,
      mid: params.mid,
      titleId: params.titleId,
      fileName: params.file.name,
      fileSize: params.file.size,
      fmt,
      state: 'running',
      doneParas: 0,
      totalParas: cappedUnits.length,
      updatedAt: Date.now(),
    }),
    saveTurnMessageDirect(params.cid, params.mid, {
      role: 'assistant',
      kind: 'document',
      mode: params.mode,
      titleId: params.titleId,
      fileName: params.file.name,
      fmt,
      jobId,
      done: 0,
      total: cappedUnits.length,
      text: '',
      state: 'running',
    }),
  ]);

  try {
    const { outputs, detectedSource } = await translateParagraphsDirect({
      paragraphs: cappedUnits.map((u) => u.text),
      mode: params.mode,
      titleId: params.titleId,
      onProgress: (_, done, total) => {
        const pct = Math.min(98, Math.max(8, Math.round((done / Math.max(1, total)) * 100)));
        params.onProgress?.(pct);
      },
    });

    const translatedRows: Array<{ prefix?: string; src: string; dst: string }> = cappedUnits.map(
      (u, idx) => ({
        prefix: u.prefix,
        src: u.text,
        dst: outputs[idx] || u.text,
      })
    );
    const detected: TargetLang = detectedSource;

    directExportCache.set(`${params.cid}:${params.mid}`, {
      fileName: params.file.name,
      fmt,
      headerDoc,
      units: translatedRows,
    });

    const sentences: SentencePair[] = translatedRows.map((r, i) => ({
      i,
      src: r.src,
      dst: r.dst,
    }));
    const fullDst = translatedRows.map((r) => r.dst).join('\n\n');

    await Promise.all([
      saveDirectJobRecord({
        id: jobId,
        cid: params.cid,
        mid: params.mid,
        titleId: params.titleId,
        fileName: params.file.name,
        fileSize: params.file.size,
        fmt,
        state: 'done',
        doneParas: translatedRows.length,
        totalParas: cappedUnits.length,
        updatedAt: Date.now(),
      }),
      saveTurnMessageDirect(params.cid, params.mid, {
        role: 'assistant',
        kind: 'document',
        mode: params.mode,
        detectedSource: detected,
        titleId: params.titleId,
        fileName: params.file.name,
        fmt,
        jobId,
        done: translatedRows.length,
        total: cappedUnits.length,
        text: fullDst,
        sentences,
        state: 'done',
      }),
      upsertConversationMeta(params.cid, {
        title: params.file.name,
        titleId: params.titleId || '',
        mode: params.mode,
        detectedSource: detected,
        activeTab: 'dokumen',
        preview: fullDst.slice(0, 180),
      }),
    ]);
    params.onProgress?.(100);

    return jobId;
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : 'Gagal menerjemahkan dokumen.';
    await Promise.allSettled([
      saveDirectJobRecord({
        id: jobId,
        cid: params.cid,
        mid: params.mid,
        titleId: params.titleId,
        fileName: params.file.name,
        fileSize: params.file.size,
        fmt,
        state: 'error',
        doneParas: 0,
        totalParas: cappedUnits.length,
        message: errMsg.slice(0, 500),
        updatedAt: Date.now(),
      }),
      saveTurnMessageDirect(params.cid, params.mid, {
        role: 'assistant',
        kind: 'document',
        mode: params.mode,
        titleId: params.titleId,
        fileName: params.file.name,
        fmt,
        jobId,
        done: 0,
        total: cappedUnits.length,
        text: '',
        error: errMsg.slice(0, 500),
        state: 'error',
      }),
    ]);
    throw err;
  }
}

export function buildDirectExportBlob(params: {
  cid: string;
  mid: string;
  fmt: string;
  fallbackSentences?: SentencePair[];
  fallbackText?: string;
  bilingual?: boolean;
  theme?: string;
}): { blob: Blob; filename: string } {
  const cached = directExportCache.get(`${params.cid}:${params.mid}`);
  const rows: Array<{ src: string; dst: string; prefix?: string }> =
    cached?.units?.length
      ? cached.units
      : params.fallbackSentences?.length
        ? params.fallbackSentences.map((s) => ({ src: s.src, dst: s.dst }))
        : [{ src: '', dst: params.fallbackText || '' }];

  const fmtSubtitleClock = (sec: number, sep: ',' | '.') => {
    const h = String(Math.floor(sec / 3600)).padStart(2, '0');
    const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0');
    const s = String(sec % 60).padStart(2, '0');
    return `${h}:${m}:${s}${sep}`;
  };

  // Balanced 2-line broadcast subtitle CPL wrapper (<= 42 CPL Latin / <= 18 CPL CJK, Netflix/BBC norms)
  const wrapSubtitleBalanced = (raw: string): string => {
    const clean = (raw || '').replace(/\r?\n/g, ' ').replace(/\s+/g, ' ').trim();
    if (!clean) return clean;
    const isCjk = CJK_RE.test(clean);
    const maxCpl = isCjk ? 18 : 42;
    if (clean.length <= maxCpl) return clean;
    const mid = Math.floor(clean.length / 2);
    if (isCjk) {
      const punctRe = /[、。！？]/g;
      let best = mid;
      let bestDist = Infinity;
      let pm: RegExpExecArray | null;
      while ((pm = punctRe.exec(clean)) !== null) {
        const idx = pm.index + 1;
        if (idx >= 6 && clean.length - idx >= 4 && Math.abs(idx - mid) < bestDist) {
          bestDist = Math.abs(idx - mid);
          best = idx;
        }
      }
      return `${clean.slice(0, best).trim()}\n${clean.slice(best).trim()}`;
    }
    const leftSp = clean.lastIndexOf(' ', mid);
    const rightSp = clean.indexOf(' ', mid);
    const splitAt =
      leftSp > 8 && (rightSp === -1 || mid - leftSp <= rightSp - mid)
        ? leftSp
        : rightSp > 8
          ? rightSp
          : -1;
    if (splitAt === -1) return clean;
    return `${clean.slice(0, splitAt).trim()}\n${clean.slice(splitAt + 1).trim()}`;
  };

  const ALLOWED_EXPORT_EXTS = new Set(['txt', 'html', 'srt', 'vtt', 'ass', 'docx', 'md', 'json']);
  const rawExt = params.fmt.toLowerCase().replace(/^\.+/, '');
  const mappedExt = rawExt === 'ssa' ? 'ass' : rawExt;
  const ext = ALLOWED_EXPORT_EXTS.has(mappedExt) ? mappedExt : 'txt';
  const rawStem = (cached?.fileName || `tranx-${params.mid}`).replace(/\.[^.]+$/, '');
  const baseStem = safePathFileName(rawStem, 'tranx-export');

  if (ext === 'docx') {
    const docxBytes = buildDocxArchiveBytes(baseStem, rows, params.bilingual);
    return {
      blob: new Blob([docxBytes.buffer as ArrayBuffer], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      }),
      filename: `${baseStem}.docx`,
    };
  }

  if (ext === 'ass') {
    const defaultAssHeader = [
      '[Script Info]',
      `Title: ${baseStem}`,
      'ScriptType: v4.00+',
      'WrapStyle: 0',
      'ScaledBorderAndShadow: yes',
      '',
      '[V4+ Styles]',
      'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
      'Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1',
      '',
      '[Events]',
      'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ].join('\n');
    const headerBlock = cached?.headerDoc || defaultAssHeader;
    const events = rows
      .map((r, idx) => {
        const startSec = idx * 3;
        const endSec = startSec + 2;
        const fmtAssTime = (sec: number) => {
          const h = Math.floor(sec / 3600);
          const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0');
          const s = String(sec % 60).padStart(2, '0');
          return `${h}:${m}:${s}.00`;
        };
        const lead =
          r.prefix && /^dialogue\s*:/i.test(r.prefix)
            ? r.prefix
            : `Dialogue: 0,${fmtAssTime(startSec)},${fmtAssTime(endSec)},Default,,0,0,0,,`;
        const body = (params.bilingual && r.src ? `${r.src}\n${r.dst}` : wrapSubtitleBalanced(r.dst)).replace(
          /\r?\n/g,
          '\\N'
        );
        return `${lead}${body}`;
      })
      .join('\n');
    return {
      blob: new Blob([`${headerBlock}\n${events}\n`], { type: 'text/plain;charset=utf-8' }),
      filename: `${baseStem}.ass`,
    };
  }

  if (ext === 'vtt') {
    const cues = rows
      .map((r, idx) => {
        const startSec = idx * 3;
        const header = r.prefix
          ? r.prefix.replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, '$1.$2')
          : `${fmtSubtitleClock(startSec, '.')}000 --> ${fmtSubtitleClock(startSec + 2, '.')}500`;
        return `${header}\n${params.bilingual && r.src ? `${r.src}\n${r.dst}` : wrapSubtitleBalanced(r.dst)}`;
      })
      .join('\n\n');
    return {
      blob: new Blob([`WEBVTT\n\n${cues}\n`], { type: 'text/vtt;charset=utf-8' }),
      filename: `${baseStem}.vtt`,
    };
  }

  if (ext === 'srt') {
    const srt = rows
      .map((r, idx) => {
        const startSec = idx * 3;
        const header =
          r.prefix ||
          `${idx + 1}\n${fmtSubtitleClock(startSec, ',')}000 --> ${fmtSubtitleClock(startSec + 2, ',')}500`;
        return `${header}\n${params.bilingual && r.src ? `${r.src}\n${r.dst}` : wrapSubtitleBalanced(r.dst)}`;
      })
      .join('\n\n');
    return {
      blob: new Blob([srt], { type: 'text/plain;charset=utf-8' }),
      filename: `${baseStem}.srt`,
    };
  }

  if (ext === 'html') {
    const body = rows
      .map((r) =>
        params.bilingual && r.src
          ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:10px 0;border-bottom:1px solid #DEE3E0"><div>${escapeHtml(
            r.src
          )}</div><div>${escapeHtml(r.dst)}</div></div>`
          : `<p>${escapeHtml(r.dst)}</p>`
      )
      .join('\n');
    const isDark = params.theme === 'Gelap';
    const safeTheme = isDark ? 'Gelap' : 'Terang';
    const html = `<!doctype html><html lang="id" data-tranx-v3="${safeTheme}"><head><meta charset="utf-8"><title>${escapeHtml(
      baseStem
    )}</title><style>body{font-family:Charter,Georgia,serif;max-width:860px;margin:28px auto;padding:0 20px;line-height:1.75;background:${isDark ? '#171B1A' : '#FAFBFA'
      };color:${isDark ? '#E7ECEA' : '#141917'}}</style></head><body><h1>${escapeHtml(
        baseStem
      )}</h1>${body}</body></html>`;
    return {
      blob: new Blob([html], { type: 'text/html;charset=utf-8' }),
      filename: `${baseStem}.html`,
    };
  }

  const txt = rows
    .map((r) => (params.bilingual && r.src ? `${r.src}\n${r.dst}` : r.dst))
    .join('\n\n');
  return {
    blob: new Blob([txt], { type: 'text/plain;charset=utf-8' }),
    filename: `${baseStem}.${ext}`,
  };
}

const MAX_REMOTE_IMAGE_BYTES = 15 * 1024 * 1024; // 15 MB
const HAS_SENSITIVE_QUERY_RE =
  /[?&](?:token|sig|signature|hm|auth|auth_token|id_token|refresh_token|jwt|session|sid|cookie|secret|password|passwd|pwd|credential|key|apikey|api_key|access_token|code|state|nonce|x-amz-[^=]+|x-goog-[^=]+|expires)=/i;

function safePathFileName(pathname: string, fallback: string): string {
  const rawSeg = pathname.split('/').pop() || fallback;
  let decoded = rawSeg;
  try {
    decoded = decodeURIComponent(rawSeg);
  } catch {
    decoded = rawSeg;
  }
  return (
    decoded
      .replace(/[\x00-\x1f\x7f\\/:*?"<>|\u202a-\u202e\u2066-\u2069]/g, '_')
      .slice(0, 80) || fallback
  );
}

function detectMimeFromMagicBytes(bytes: Uint8Array): string | null {
  if (bytes.length < 12) return null;
  // Full 8-byte PNG signature
  if (
    bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
    bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a
  ) {
    return 'image/png';
  }
  // JPEG
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg';
  // Full 6-byte GIF87a / GIF89a signature
  if (
    bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x38 &&
    (bytes[4] === 0x37 || bytes[4] === 0x39) && bytes[5] === 0x61
  ) {
    return 'image/gif';
  }
  // WEBP (RIFF....WEBP)
  if (
    bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
    bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50
  ) {
    return 'image/webp';
  }
  return null;
}

async function readBoundedBytes(
  resp: Response,
  maxBytes: number,
  requireImageMagic: boolean
): Promise<Uint8Array> {
  const cLen = Number(resp.headers.get('content-length') || 0);
  if (cLen > maxBytes) {
    throw new Error('Ukuran berkas melebihi batas aman.');
  }
  if (!resp.body) {
    const buf = new Uint8Array(await resp.arrayBuffer());
    if (buf.byteLength > maxBytes) throw new Error('Ukuran berkas melebihi batas aman.');
    if (requireImageMagic && !detectMimeFromMagicBytes(buf)) {
      throw new Error('Respons tautan bukan berkas gambar PNG/JPG/WEBP/GIF yang sah.');
    }
    return buf;
  }
  const reader = resp.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let checkedMagic = !requireImageMagic;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        throw new Error('Ukuran berkas melebihi batas aman.');
      }
      chunks.push(value);
      if (!checkedMagic && total >= 12) {
        const head = new Uint8Array(12);
        let pos = 0;
        for (const c of chunks) {
          const take = Math.min(c.byteLength, 12 - pos);
          head.set(c.subarray(0, take), pos);
          pos += take;
          if (pos >= 12) break;
        }
        if (!detectMimeFromMagicBytes(head)) {
          await reader.cancel();
          throw new Error('Respons tautan bukan berkas gambar PNG/JPG/WEBP/GIF yang sah.');
        }
        checkedMagic = true;
      }
    }
  } finally {
    reader.releaseLock();
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.byteLength;
  }
  return out;
}

function uint8ToBase64(bytes: Uint8Array): string {
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function loadCorsImageViaImgElement(
  cleanUrl: string,
  signal?: AbortSignal
): Promise<{ dataUrl: string; mime: string }> {
  if (typeof document === 'undefined' || typeof Image === 'undefined') {
    throw new Error('no_dom');
  }
  if (/\.svg(?:$|[?#])|[?&]format=svg\b/i.test(cleanUrl)) {
    throw new Error('svg_not_raster');
  }
  return new Promise<{ dataUrl: string; mime: string }>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.referrerPolicy = 'no-referrer';
    let settled = false;
    const cleanup = () => {
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      img.onload = null;
      img.onerror = null;
    };
    const fail = (err: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      img.src = '';
      reject(err);
    };
    const onAbort = () => fail(new DOMException('Aborted', 'AbortError'));
    signal?.addEventListener('abort', onAbort, { once: true });
    const timer = window.setTimeout(() => fail(new Error('timeout')), 12_000);

    img.onload = () => {
      if (settled) return;
      settled = true;
      cleanup();
      const nw = img.naturalWidth || 0;
      const nh = img.naturalHeight || 0;
      if (nw <= 0 || nh <= 0 || nw > 8192 || nh > 65536 || nw * nh > 36_000_000) {
        reject(new Error('Resolusi gambar melampaui batas aman 36 megapiksel.'));
        return;
      }
      // Keep offscreen canvas safely within browser GPU limits while preserving aspect ratio
      let scale = 1;
      if (nw > 12_000) scale = Math.min(scale, 12_000 / nw);
      if (nh > 12_000) scale = Math.min(scale, 12_000 / nh);
      if (nw * nh * scale * scale > 16_777_216) {
        scale = Math.min(scale, Math.sqrt(16_777_216 / (nw * nh)));
      }
      const cw = Math.max(1, Math.round(nw * scale));
      const ch = Math.max(1, Math.round(nh * scale));
      const canvas = document.createElement('canvas');
      canvas.width = cw;
      canvas.height = ch;
      try {
        const ctx = canvas.getContext('2d');
        if (!ctx) throw new Error('canvas_ctx_unavailable');
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, cw, ch);
        ctx.drawImage(img, 0, 0, cw, ch);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
        if (!dataUrl || dataUrl.length < 32) throw new Error('empty_canvas_export');
        resolve({ dataUrl, mime: 'image/jpeg' });
      } catch (err) {
        reject(err instanceof Error ? err : new Error('cors_tainted'));
      } finally {
        canvas.width = 0;
        canvas.height = 0;
        img.src = '';
      }
    };
    img.onerror = () => fail(new Error('img_cors_error'));
    img.src = cleanUrl;
  });
}

/**
 * Anti-SSRF remote image fetcher (validates URL with normalizeWebUrl, uses CSP-clean CORS <img> stage
 * before falling back to allowlisted proxies with 15 MB stream cap & magic-byte validation).
 * Refuses leaking signed URLs/tokens to public third-party proxies.
 */
export async function fetchRemoteImageAsDataUrl(
  rawUrl: string,
  signal?: AbortSignal
): Promise<{ dataUrl: string; mime: string; fileName: string }> {
  if (/^data:image\/(?:png|jpeg|jpg|webp|gif);base64,/i.test(rawUrl.trim())) {
    const trimmed = rawUrl.trim();
    if (trimmed.length > Math.ceil(MAX_REMOTE_IMAGE_BYTES * 1.38)) {
      throw new Error('Ukuran gambar melebihi batas aman 15 MB.');
    }
    const mimeMatch = trimmed.match(/^data:([^;]+);base64,/i);
    return {
      dataUrl: trimmed,
      mime: mimeMatch ? mimeMatch[1].toLowerCase() : 'image/png',
      fileName: 'gambar-komik.png',
    };
  }
  const cleanUrl = normalizeSocialImageUrl(normalizeWebUrl(rawUrl));
  const parsed = new URL(cleanUrl);
  const fileName = safePathFileName(parsed.pathname, 'halaman-komik.png');
  const isSameOrigin = typeof window !== 'undefined' && parsed.origin === window.location.origin;

  // Stage 1: For cross-origin HTTPS images, load via <img crossOrigin="anonymous"> (governed by img-src https:,
  // avoiding connect-src CSP violations on live Hosting and keeping signed URLs strictly off third-party proxies!)
  if (!isSameOrigin && typeof document !== 'undefined') {
    try {
      const viaImg = await loadCorsImageViaImgElement(cleanUrl, signal);
      return { dataUrl: viaImg.dataUrl, mime: viaImg.mime, fileName };
    } catch (err) {
      if ((err as Error)?.name === 'AbortError' && signal?.aborted) throw err;
      if (err instanceof Error && err.message.includes('batas aman')) throw err;
    }
  }

  // Stage 2: Same-origin fetch or allowlisted CORS proxies (never forwarding signed/auth URLs!)
  const candidates: string[] = [];
  if (isSameOrigin || typeof document === 'undefined') {
    candidates.push(cleanUrl);
  }
  if (!HAS_SENSITIVE_QUERY_RE.test(cleanUrl)) {
    candidates.push(
      `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(cleanUrl)}`,
      `https://api.allorigins.win/raw?url=${encodeURIComponent(cleanUrl)}`
    );
  }

  let lastErr = 'Situs gambar membatasi pengambilan langsung (CORS / proteksi hotlink).';
  for (const target of candidates) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const ctrl = new AbortController();
    const onAbort = () => ctrl.abort();
    signal?.addEventListener('abort', onAbort, { once: true });
    const timer = window.setTimeout(() => ctrl.abort(), 14_000);
    try {
      const resp = await fetch(target, {
        method: 'GET',
        mode: 'cors',
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
        signal: ctrl.signal,
      });
      if (!resp.ok) {
        lastErr = `Gagal memuat gambar (HTTP ${resp.status}).`;
        continue;
      }
      const bytes = await readBoundedBytes(resp, MAX_REMOTE_IMAGE_BYTES, true);
      if (bytes.byteLength === 0) {
        lastErr = 'Berkas gambar kosong.';
        continue;
      }
      const detectedMime = detectMimeFromMagicBytes(bytes);
      if (!detectedMime) {
        lastErr = 'Respons tautan bukan berkas gambar PNG/JPG/WEBP/GIF yang sah.';
        continue;
      }
      const b64 = uint8ToBase64(bytes);
      return {
        dataUrl: `data:${detectedMime};base64,${b64}`,
        mime: detectedMime,
        fileName,
      };
    } catch (err) {
      if ((err as Error)?.name === 'AbortError' && signal?.aborted) throw err;
      if (err instanceof Error && err.message.includes('batas aman')) throw err;
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  }
  throw new Error(lastErr);
}

const VALID_BLOCK_KINDS = new Set<VisionBlockKind>([
  'dialogue',
  'thought',
  'shout',
  'narration',
  'sfx',
  'status_window',
  'caption',
  'aside',
  'sign',
]);
const VALID_BLOCK_SHAPES = new Set<VisionBlockShape>(['oval', 'rect', 'jagged', 'cloud', 'unbordered']);
const VALID_BG_TONES = new Set<VisionBgTone>(['light', 'dark', 'artwork', 'colored']);
const VALID_SFX_IMPORTANCE = new Set<NonNullable<VisionBlock['sfxImportance']>>([
  'none',
  'ambient',
  'impact',
  'narrative',
  'major',
  'minor',
  'plot_critical',
]);

interface RichVisionBubble {
  id?: number;
  box_2d: number[];
  text: string;
  kind?: VisionBlockKind;
  shape?: VisionBlockShape;
  bgTone?: VisionBgTone;
  writingDir?: 'vertical' | 'horizontal';
  sfxImportance?: VisionBlock['sfxImportance'];
}

async function detectVisionBubblesOnSource(params: {
  dataUrl: string;
  mime: string;
  b64: string;
  imgEl: HTMLImageElement | HTMLCanvasElement;
  w: number;
  h: number;
  srcLang: SourceLang;
  geminiKey: string | null;
  signal?: AbortSignal;
}): Promise<{ bubbles: RichVisionBubble[]; model: string }> {
  const { geminiKey, imgEl, w, h, srcLang, dataUrl, mime, b64, signal } = params;
  if (geminiKey) {
    try {
      const visionPrompt =
        'Extract ALL visible manga/comic speech bubbles, narration boxes, RPG status windows, and major sound effects (SFX) in natural reading order. ' +
        'Ignore tiny Japanese furigana glosses beside kanji. ' +
        'Return strict JSON: {"bubbles":[{"id":1,"box_2d":[ymin,xmin,ymax,xmax],"text":"...","kind":"dialogue|thought|shout|narration|sfx|status_window|caption|aside|sign","shape":"oval|rect|jagged|cloud|unbordered","bgTone":"light|dark|artwork|colored","writingDir":"vertical|horizontal","sfxImportance":"plot_critical|ambient"}]} ' +
        'with integer coordinates normalized 0..1000.';

      const reqCtrl = new AbortController();
      const onOuter = () => reqCtrl.abort();
      signal?.addEventListener('abort', onOuter, { once: true });
      const reqTimer = window.setTimeout(() => reqCtrl.abort(), 45_000);
      let resp: Response;
      try {
        resp = await fetch(
          'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent',
          {
            method: 'POST',
            signal: reqCtrl.signal,
            headers: {
              'Content-Type': 'application/json',
              'x-goog-api-key': geminiKey,
            },
            body: JSON.stringify({
              systemInstruction: { parts: [{ text: visionPrompt }] },
              contents: [
                {
                  role: 'user',
                  parts: [
                    { inlineData: { mimeType: mime, data: b64 } },
                    { text: 'Detect all comic speech bubbles, captions, status windows, and SFX.' },
                  ],
                },
              ],
              generationConfig: { responseMimeType: 'application/json', temperature: 0.1 },
            }),
          }
        );
      } finally {
        window.clearTimeout(reqTimer);
        signal?.removeEventListener('abort', onOuter);
      }
      if (!resp.ok) {
        throw new Error(`Gemini Vision HTTP ${resp.status}`);
      }
      const raw = await resp.json();
      let rawJsonText = extractGeminiResponseText(raw, '{}');
      const fence = rawJsonText.match(/```(?:json)?\s*([\s\S]*?)```/i);
      if (fence) rawJsonText = fence[1].trim();
      const parsed = JSON.parse(rawJsonText) as { bubbles?: unknown };
      const bubbles: Array<Record<string, unknown>> = Array.isArray(parsed.bubbles) ? parsed.bubbles : [];
      const valid = bubbles
        .filter(
          (b) =>
            typeof b.text === 'string' &&
            Boolean(b.text.trim()) &&
            Array.isArray(b.box_2d) &&
            b.box_2d.length === 4 &&
            (b.box_2d as unknown[]).every((n) => Number.isFinite(Number(n)))
        )
        .map((b, idx): RichVisionBubble => ({
          id: typeof b.id === 'number' ? b.id : idx + 1,
          box_2d: (b.box_2d as number[]).map((n) => Number(n)),
          text: String(b.text).trim(),
          kind: VALID_BLOCK_KINDS.has(b.kind as VisionBlockKind) ? (b.kind as VisionBlockKind) : undefined,
          shape: VALID_BLOCK_SHAPES.has(b.shape as VisionBlockShape) ? (b.shape as VisionBlockShape) : undefined,
          bgTone: VALID_BG_TONES.has(b.bgTone as VisionBgTone) ? (b.bgTone as VisionBgTone) : undefined,
          writingDir: b.writingDir === 'vertical' || b.writingDir === 'horizontal' ? b.writingDir : undefined,
          sfxImportance: VALID_SFX_IMPORTANCE.has(b.sfxImportance as NonNullable<VisionBlock['sfxImportance']>)
            ? (b.sfxImportance as VisionBlock['sfxImportance'])
            : undefined,
        }));
      return { bubbles: valid, model: 'gemini-2.5-flash' };
    } catch (err) {
      if (signal?.aborted || (err as { name?: string })?.name === 'AbortError') throw err;
      // Graceful fallback to local browser OCR / Tesseract WASM when Gemini Vision fails (429/5xx/bad key)
    }
  }

  let validBubbles: RichVisionBubble[] = [];
  let usedModel = 'browser-text-detector';
  const DetectorCtor = (
    window as unknown as {
      TextDetector?: new () => {
        detect: (
          src: HTMLImageElement | HTMLCanvasElement
        ) => Promise<
          Array<{
            rawValue?: string;
            boundingBox?: { x: number; y: number; width: number; height: number };
          }>
        >;
      };
    }
  ).TextDetector;
  if (DetectorCtor) {
    try {
      const detector = new DetectorCtor();
      const detectedBoxes = await detector.detect(imgEl);
      validBubbles = detectedBoxes
        .filter((d) => typeof d.rawValue === 'string' && d.rawValue.trim() && d.boundingBox)
        .map((d, idx) => {
          const bb = d.boundingBox!;
          const ymin = Math.round((bb.y / h) * 1000);
          const xmin = Math.round((bb.x / w) * 1000);
          const ymax = Math.round(((bb.y + bb.height) / h) * 1000);
          const xmax = Math.round(((bb.x + bb.width) / w) * 1000);
          return {
            id: idx + 1,
            box_2d: [ymin, xmin, ymax, xmax],
            text: d.rawValue!.trim(),
          };
        });
    } catch {
      validBubbles = [];
    }
  }

  if (validBubbles.length === 0) {
    usedModel = 'tesseract-wasm-ocr';
    validBubbles = await runTesseractOcrBoxes(dataUrl, w, h, srcLang);
  }
  return { bubbles: validBubbles, model: usedModel };
}

export async function directScanRemoteMangaPage(params: {
  imageUrl: string;
  mode: ModePair;
  titleId?: string;
  layout?: ComicLayoutMode;
  signal?: AbortSignal;
}): Promise<ImageTranslationResult> {
  const cacheKey = `${params.imageUrl}::${params.mode}`;
  const cached = scannedMangaPageCache.get(cacheKey);
  if (cached) return cached;

  const { dataUrl, fileName } = await fetchRemoteImageAsDataUrl(params.imageUrl, params.signal);
  const res = await directTranslateImage({
    cid: `c_comic_${Date.now().toString(36)}`,
    mode: params.mode,
    fileName,
    imageDataUrl: dataUrl,
    titleId: params.titleId,
    layout: params.layout,
    persistMessage: false,
    signal: params.signal,
  });
  const out: ImageTranslationResult = {
    width: res.width,
    height: res.height,
    blocks: res.blocks,
    fullSrc: res.fullSrc,
    fullDst: res.fullDst,
    model: res.model,
    dataUrl: res.dataUrl,
    comicLayout: res.comicLayout,
    readingDir: res.readingDir,
    isSpread: res.isSpread,
  };
  scannedMangaPageCache.set(cacheKey, out);
  return out;
}

export async function directTranslateImage(params: {
  cid: string;
  mode: ModePair;
  fileName: string;
  imageDataUrl: string;
  titleId?: string;
  layout?: ComicLayoutMode;
  persistMessage?: boolean;
  signal?: AbortSignal;
}): Promise<{ cid: string; mid: string; titleId: string } & ImageTranslationResult> {
  const [dataHeader, rawB64 = ''] = params.imageDataUrl.split(',', 2);
  if (rawB64.length > Math.ceil(MAX_REMOTE_IMAGE_BYTES * 1.38)) {
    throw new Error('Ukuran gambar melebihi batas aman 15 MB.');
  }
  const cleanPrefix = rawB64.replace(/\s+/g, '').slice(0, 64);
  const headLen = cleanPrefix.length - (cleanPrefix.length % 4);
  if (headLen < 4) {
    throw new Error('Data gambar tidak sah atau rusak.');
  }
  let headStr = '';
  try {
    headStr = atob(cleanPrefix.slice(0, headLen));
  } catch {
    throw new Error('Data gambar tidak sah atau rusak.');
  }
  const headBytes = new Uint8Array(headStr.length);
  for (let i = 0; i < headStr.length; i += 1) {
    headBytes[i] = headStr.charCodeAt(i) & 0xff;
  }
  const ext = (params.fileName.split('.').pop() || 'png').toLowerCase();
  const magicMime = detectMimeFromMagicBytes(headBytes);
  const magicErr = magicMime ? null : inspectBinaryMagicBytes(headBytes, ext, 'gambar');
  if (magicErr) {
    throw new Error(magicErr);
  }

  const imgDims = await new Promise<{
    w: number;
    h: number;
    mime: string;
    b64: string;
    imgEl: HTMLImageElement;
  }>((resolve, reject) => {
    const mimeMatch = dataHeader.match(/data:([^;]+)/);
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth || 640;
      const h = img.naturalHeight || 480;
      if (w > 8192 || h > MAX_MANGA_STRIP_HEIGHT || w * h > MAX_MANGA_STRIP_PIXELS) {
        reject(new Error('Resolusi gambar melampaui batas aman 36 megapiksel (tinggi maks 65.536 px).'));
        return;
      }
      resolve({
        w,
        h,
        mime: magicMime || (mimeMatch ? mimeMatch[1] : 'image/png'),
        b64: rawB64,
        imgEl: img,
      });
    };
    img.onerror = () => reject(new Error('Berkas gambar tidak dapat dibaca.'));
    img.src = params.imageDataUrl;
  });

  const { src } = parseModePair(params.mode);
  const geminiKey = await getOwnerGeminiKey();
  let rawPixelBoxes: RawOcrBox[] = [];
  let usedModel = 'gemini-2.5-flash';

  try {
    const isConstrained = getDeviceRuntimeProfile().isConstrained;
    // Build lightweight 96px-wide Rec. 709 horizontal row-variance probe for tall webtoon gutter seam snapping
    let rowVarianceFn: ((y: number) => number) | undefined;
    if (imgDims.h > (isConstrained ? 1500 : 2100) && typeof document !== 'undefined') {
      const probeW = Math.min(96, imgDims.w);
      const maxProbeH = isConstrained ? 2048 : 4096;
      const probeScaleY = Math.min(1, maxProbeH / imgDims.h);
      const probeH = Math.max(1, Math.round(imgDims.h * probeScaleY));
      const probeCanvas = document.createElement('canvas');
      try {
        probeCanvas.width = probeW;
        probeCanvas.height = probeH;
        const pCtx = probeCanvas.getContext('2d', { willReadFrequently: true });
        if (pCtx) {
          pCtx.drawImage(imgDims.imgEl, 0, 0, probeW, probeH);
          const pData = pCtx.getImageData(0, 0, probeW, probeH).data;
          const rowVars = new Float32Array(probeH);
          for (let py = 0; py < probeH; py += 1) {
            let sum = 0;
            let sumSq = 0;
            const base = py * probeW * 4;
            for (let px = 0; px < probeW; px += 1) {
              const o = base + px * 4;
              const lum = 0.2126 * pData[o] + 0.7152 * pData[o + 1] + 0.0722 * pData[o + 2];
              sum += lum;
              sumSq += lum * lum;
            }
            const mean = sum / probeW;
            rowVars[py] = Math.max(0, sumSq / probeW - mean * mean);
          }
          rowVarianceFn = (origY: number) => {
            const py = Math.max(0, Math.min(probeH - 1, Math.round(origY * probeScaleY)));
            return rowVars[py];
          };
        }
      } catch {
        rowVarianceFn = undefined;
      } finally {
        probeCanvas.width = 0;
        probeCanvas.height = 0;
      }
    }
    const tiles = planVerticalStripTiles(imgDims.w, imgDims.h, { isConstrained, rowVarianceFn });

    if (tiles.length === 1) {
      const det = await detectVisionBubblesOnSource({
        dataUrl: params.imageDataUrl,
        mime: imgDims.mime,
        b64: imgDims.b64,
        imgEl: imgDims.imgEl,
        w: imgDims.w,
        h: imgDims.h,
        srcLang: src,
        geminiKey,
        signal: params.signal,
      });
      usedModel = det.model;
      rawPixelBoxes = det.bubbles.map((b, idx) => {
        const [ymin, xmin, ymax, xmax] = b.box_2d.map((v) =>
          Number.isFinite(v) ? Math.max(0, Math.min(1000, v)) : 0
        );
        const x = Math.max(0, Math.min(imgDims.w - 1, Math.round((Math.min(xmin, xmax) / 1000) * imgDims.w)));
        const y = Math.max(0, Math.min(imgDims.h - 1, Math.round((Math.min(ymin, ymax) / 1000) * imgDims.h)));
        const bw = Math.max(24, Math.min(imgDims.w - x, Math.round((Math.abs(xmax - xmin) / 1000) * imgDims.w)));
        const bh = Math.max(20, Math.min(imgDims.h - y, Math.round((Math.abs(ymax - ymin) / 1000) * imgDims.h)));
        return {
          id: idx + 1,
          box: [x, y, bw, bh],
          text: b.text.trim(),
          kind: b.kind,
          shape: b.shape,
          bgTone: b.bgTone,
          writingDir: b.writingDir,
          sfxImportance: b.sfxImportance,
        };
      });
    } else {
      // Tall webtoon / manhwa strip: slice into bounded tiles & stitch cross-seam detections (GPU-safe cleanup)
      const tileCanvas = document.createElement('canvas');
      const tCtx = tileCanvas.getContext('2d');
      const stitchedInput: Array<RawOcrBox & { src: string }> = [];
      try {
        for (const tile of tiles) {
          if (params.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
          tileCanvas.width = imgDims.w;
          tileCanvas.height = tile.height;
          if (tCtx) {
            tCtx.clearRect(0, 0, tileCanvas.width, tileCanvas.height);
            tCtx.drawImage(
              imgDims.imgEl,
              0,
              tile.yStart,
              imgDims.w,
              tile.height,
              0,
              0,
              imgDims.w,
              tile.height
            );
          }
          const tileDataUrl = tileCanvas.toDataURL('image/jpeg', 0.9);
          const tileB64 = tileDataUrl.split(',', 2)[1] || '';
          const det = await detectVisionBubblesOnSource({
            dataUrl: tileDataUrl,
            mime: 'image/jpeg',
            b64: tileB64,
            imgEl: tileCanvas,
            w: imgDims.w,
            h: tile.height,
            srcLang: src,
            geminiKey,
            signal: params.signal,
          });
          usedModel = det.model;
          for (const b of det.bubbles) {
            const [ymin, xmin, ymax, xmax] = b.box_2d.map((v) =>
              Number.isFinite(v) ? Math.max(0, Math.min(1000, v)) : 0
            );
            const x = Math.max(0, Math.min(imgDims.w - 1, Math.round((Math.min(xmin, xmax) / 1000) * imgDims.w)));
            const y = Math.max(
              0,
              Math.min(imgDims.h - 1, tile.yStart + Math.round((Math.min(ymin, ymax) / 1000) * tile.height))
            );
            const bw = Math.max(24, Math.min(imgDims.w - x, Math.round((Math.abs(xmax - xmin) / 1000) * imgDims.w)));
            const bh = Math.max(20, Math.min(imgDims.h - y, Math.round((Math.abs(ymax - ymin) / 1000) * tile.height)));
            stitchedInput.push({
              id: stitchedInput.length + 1,
              box: [x, y, bw, bh],
              text: b.text.trim(),
              src: b.text.trim(),
              kind: b.kind,
              shape: b.shape,
              bgTone: b.bgTone,
              writingDir: b.writingDir,
              sfxImportance: b.sfxImportance,
            });
          }
        }
      } finally {
        tileCanvas.width = 0;
        tileCanvas.height = 0;
      }
      rawPixelBoxes = dedupeAndStitchTileBlocks(stitchedInput);
    }
  } finally {
    // Release decoded bitmap memory immediately after OCR completes or fails
    imgDims.imgEl.src = '';
  }

  if (rawPixelBoxes.length === 0 && !geminiKey) {
    throw new Error('Tidak ditemukan teks yang dapat dibaca pada gambar ini.');
  }

  // Cluster line-level OCR fragments into unified speech bubbles (only when using line-based fallback OCR)
  const clustered =
    usedModel === 'gemini-2.5-flash'
      ? rawPixelBoxes
      : clusterOcrBoxes(rawPixelBoxes, src === 'ja' ? 'vertical' : 'horizontal');

  const inferredLayout: ComicLayoutMode =
    params.layout ||
    (imgDims.h / Math.max(1, imgDims.w) >= 2.5
      ? 'webtoon_strip'
      : src === 'ja' || clustered.some((b) => CJK_RE.test(b.text))
        ? 'rtl_manga'
        : 'ltr_comic');

  const orderedBoxes = sortMangaReadingOrder(clustered, inferredLayout, imgDims.w, imgDims.h);
  const preparedInputs = orderedBoxes.map((b) => normalizeComicAllCaps(b.text.trim()));

  const { outputs, detectedSource } = orderedBoxes.length
    ? await translateParagraphsDirect({
      paragraphs: preparedInputs,
      mode: params.mode,
      titleId: params.titleId,
      titleKind: 'komik',
      docFormat: 'image',
      signal: params.signal,
    })
    : { outputs: [], detectedSource: 'ja' as TargetLang };

  const blocks: VisionBlock[] = orderedBoxes.map((b, idx) => ({
    id: idx + 1,
    box: b.box,
    src: b.text.trim(),
    dst: outputs[idx] || b.text.trim(),
    kind: b.kind,
    shape: b.shape,
    bgTone: b.bgTone,
    writingDir: b.writingDir,
    sfxImportance: b.sfxImportance,
  }));

  const tid = params.titleId || 't_gambar';
  const mid = `img_${Date.now().toString(36)}`;
  const isSpread = inferredLayout === 'rtl_manga' && imgDims.w > imgDims.h * 1.15;
  const canonicalDataUrl = `data:${imgDims.mime};base64,${imgDims.b64}`;
  const res: ImageTranslationResult = {
    width: imgDims.w,
    height: imgDims.h,
    blocks,
    fullSrc: blocks.map((b) => b.src).join('\n'),
    fullDst: blocks.map((b) => b.dst).join('\n'),
    model: usedModel,
    dataUrl: canonicalDataUrl,
    comicLayout: inferredLayout,
    readingDir: inferredLayout === 'rtl_manga' || inferredLayout === 'four_koma' ? 'rtl' : inferredLayout === 'webtoon_strip' ? 'vertical' : 'ltr',
    isSpread,
  };

  if (params.persistMessage !== false) {
    await Promise.all([
      upsertConversationMeta(params.cid, {
        title: params.fileName,
        titleId: tid,
        mode: params.mode,
        detectedSource,
        activeTab: 'gambar',
        preview: res.fullDst.slice(0, 180) || params.fileName,
      }),
      saveTurnMessageDirect(params.cid, mid, {
        role: 'assistant',
        kind: 'image',
        mode: params.mode,
        detectedSource,
        titleId: tid,
        fileName: params.fileName,
        text: res.fullDst,
        imageResult: res,
        state: 'done',
        model: usedModel,
      }),
    ]);
  }

  return { cid: params.cid, mid, titleId: tid, ...res };
}
