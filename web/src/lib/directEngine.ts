import type {
  GlossaryEntry,
  ImageTranslationResult,
  LinkPreviewPayload,
  ModePair,
  NameChipItem,
  NovelChapterLink,
  NovelNavigation,
  SentencePair,
  SourceLang,
  TargetLang,
  VisionBlock,
  WebReaderBundle,
} from '../types';
import {
  getOwnerGeminiKey,
  loadGlossaryEntriesOnce,
  saveDirectJobRecord,
  saveTurnMessageDirect,
  upsertConversationMeta,
} from './firebase';

const CJK_RE = /[\u3040-\u309f\u30a0-\u30ff\u3400-\u9fff]/;
const CJK_SPAN_RE = /[\u3000-\u30ff\u3400-\u9fff\uff01-\uff60]+/g;
const WORD_RE = /[A-Za-zÀ-ÿ']+/g;

const ID_WORDS = new Set([
  'yang', 'dan', 'di', 'ke', 'dari', 'ini', 'itu', 'untuk', 'dengan', 'tidak', 'tak',
  'bisa', 'dapat', 'ada', 'saya', 'aku', 'kamu', 'kau', 'dia', 'ia', 'kami', 'kita',
  'mereka', 'dalam', 'pada', 'adalah', 'ialah', 'sudah', 'telah', 'akan', 'sedang',
  'atau', 'karena', 'sebab', 'seperti', 'juga', 'oleh', 'tentang', 'lebih', 'sangat',
  'hanya', 'saja', 'cuma', 'selamat', 'pagi', 'malam', 'siang', 'sore', 'terima',
  'kasih', 'bagaimana', 'mengapa', 'kenapa', 'kapan', 'dimana', 'apa', 'siapa', 'berapa',
  'tetap', 'bukan', 'belum', 'masih', 'lagi', 'baru', 'lama', 'semua', 'seluruh',
  'setiap', 'ketika', 'saat', 'waktu', 'hari', 'orang', 'rumah', 'jalan', 'cerita',
  'bab', 'halaman', 'buku', 'baca', 'membaca', 'tulis', 'menulis', 'pergi', 'datang',
  'lihat', 'melihat', 'kata', 'berkata', 'bilang', 'sambil', 'lalu', 'kemudian',
  'setelah', 'sebelum', 'sampai', 'hingga', 'sejak', 'selama', 'tanpa', 'antara',
  'tetapi', 'tapi', 'namun', 'jika', 'kalau', 'bila', 'agar', 'supaya', 'buat',
  'mau', 'ingin', 'harus', 'boleh', 'perlu', 'pernah', 'pun', 'jadi', 'menjadi',
  'sesuai', 'berubah', 'kakek', 'nenek', 'anak', 'ibu', 'ayah', 'teman', 'besar',
  'kecil', 'baik', 'buruk', 'cantik', 'indah', 'tenang', 'pelan', 'cepat', 'halo',
  'tolong', 'maaf', 'ya', 'iya', 'tidaklah', 'disini', 'disana', 'sini', 'sana',
]);

const EN_WORDS = new Set([
  'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'i', 'it', 'for', 'not',
  'on', 'with', 'he', 'as', 'you', 'do', 'at', 'this', 'but', 'his', 'by', 'from',
  'they', 'we', 'say', 'her', 'she', 'or', 'an', 'will', 'my', 'one', 'all', 'would',
  'there', 'their', 'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which',
  'go', 'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just', 'him', 'know',
  'take', 'into', 'year', 'your', 'good', 'some', 'could', 'them', 'see', 'other',
  'than', 'then', 'now', 'look', 'only', 'come', 'its', 'over', 'think', 'also',
  'back', 'after', 'use', 'two', 'how', 'our', 'work', 'first', 'well', 'way', 'even',
  'new', 'want', 'because', 'any', 'these', 'give', 'day', 'most', 'us', 'is', 'are',
  'was', 'were', 'been', 'has', 'had', 'does', 'did', 'more', 'very', 'much', 'still',
  'hello', 'morning', 'evening', 'night', 'please', 'thank', 'thanks', 'chapter',
  'episode', 'next', 'previous', 'story', 'page', 'read', 'reading', 'book', 'novel',
  'while', 'under', 'opened', 'stood', 'quietly', 'listening', 'rain', 'letter',
]);

export type ParagraphLangClass =
  | 'ja'
  | 'id'
  | 'en'
  | 'mixed-ja'
  | 'mixed-latin'
  | 'unknown';

function scoreLatinWords(sample: string): { idScore: number; enScore: number; wordCount: number } {
  const words = (sample.slice(0, 4000).match(WORD_RE) || []).map((w) => w.toLowerCase());
  let idScore = 0;
  let enScore = 0;
  for (const w of words) {
    if (ID_WORDS.has(w)) idScore += 1.2;
    if (EN_WORDS.has(w)) enScore += 1.2;
    if (
      w.length >= 5 &&
      (w.endsWith('nya') ||
        w.endsWith('kan') ||
        w.endsWith('lah') ||
        w.endsWith('kah') ||
        w.startsWith('meny') ||
        w.startsWith('meng') ||
        w.startsWith('memb') ||
        w.startsWith('mend') ||
        w.startsWith('ber') ||
        w.startsWith('ter'))
    ) {
      idScore += 0.7;
    }
    if (
      (w.length >= 5 && (w.endsWith('tion') || w.endsWith('ment') || w.endsWith('ing') || w.endsWith('ness'))) ||
      /^(don't|can't|won't|isn't|aren't|it's|i'm|you're|we're|they're|didn't|wasn't|couldn't|wouldn't)$/.test(w)
    ) {
      enScore += 0.7;
    }
  }
  return { idScore, enScore, wordCount: words.length };
}

export function classifyParagraphLanguage(text: string): ParagraphLangClass {
  const sample = (text || '').trim();
  if (!sample) return 'unknown';

  const hasCjk = CJK_RE.test(sample);
  const { idScore, enScore, wordCount } = scoreLatinWords(sample);

  if (hasCjk) {
    // Only treat as mixed-ja if there are real multi-char Latin words alongside CJK
    const latinWords = (sample.match(/[A-Za-zÀ-ÿ]{2,}/g) || []).length;
    return latinWords >= 2 ? 'mixed-ja' : 'ja';
  }
  if (wordCount === 0) return 'unknown';

  if (idScore > 0 && enScore === 0) return 'id';
  if (enScore > 0 && idScore === 0) return 'en';
  if (idScore > 0 && enScore > 0) {
    if (idScore >= enScore * 1.8) return 'id';
    if (enScore >= idScore * 1.8) return 'en';
    return 'mixed-latin';
  }
  return 'unknown';
}

export function parseModePair(mode: ModePair): { src: SourceLang; tgt: TargetLang } {
  const [rawSrc, rawTgt] = mode.split('-') as [SourceLang, TargetLang];
  const src: SourceLang = ['auto', 'id', 'en', 'ja'].includes(rawSrc) ? rawSrc : 'auto';
  const tgt: TargetLang = ['id', 'en', 'ja'].includes(rawTgt) ? rawTgt : 'id';
  if (src !== 'auto' && src === tgt) {
    return { src: 'auto', tgt };
  }
  return { src, tgt };
}

export function buildModePair(
  nextSrc: SourceLang,
  nextTgt: TargetLang,
  prevMode: ModePair = 'auto-id'
): ModePair {
  const prev = parseModePair(prevMode);
  let src = nextSrc;
  let tgt = nextTgt;
  if (src !== 'auto' && src === tgt) {
    // Flip whichever side wasn't just changed, mirroring Google Translate
    if (nextTgt !== prev.tgt && prev.src !== 'auto' && prev.src !== nextTgt) {
      src = prev.tgt;
    } else if (nextSrc !== prev.src && prev.tgt !== nextSrc) {
      tgt = prev.src === 'auto' ? (nextSrc === 'ja' ? 'id' : 'ja') : prev.src;
    } else {
      tgt = src === 'ja' ? 'id' : 'ja';
    }
  }
  return `${src}-${tgt}` as ModePair;
}

export function swapModePair(
  current: ModePair,
  detectedSource?: TargetLang | ''
): ModePair {
  const { src, tgt } = parseModePair(current);
  const concreteSrc: TargetLang =
    src === 'auto'
      ? detectedSource && detectedSource !== tgt
        ? detectedSource
        : tgt === 'ja'
          ? 'id'
          : 'ja'
      : src;
  const nextSrc: SourceLang = tgt;
  const nextTgt: TargetLang = concreteSrc === tgt ? (tgt === 'ja' ? 'id' : 'ja') : concreteSrc;
  return `${nextSrc}-${nextTgt}` as ModePair;
}

export function detectLanguageLocal(text: string, fallback: TargetLang = 'ja'): TargetLang {
  const sample = (text || '').trim();
  if (!sample) return fallback;
  if (CJK_RE.test(sample)) return 'ja';

  const { idScore, enScore, wordCount } = scoreLatinWords(sample);
  if (wordCount === 0) return fallback;
  if (idScore > enScore) return 'id';
  if (enScore > idScore) return 'en';
  return fallback;
}

export function isSingleStandaloneUrl(raw: string): boolean {
  const trimmed = raw.trim();
  if (!trimmed || /\s/.test(trimmed)) return false;
  return /^https?:\/\/[^\s]+$/i.test(trimmed);
}

export function normalizeWebUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed || trimmed.length > 2048) {
    throw new Error('Masukkan alamat tautan halaman web yang sah (maks. 2.048 karakter).');
  }
  const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(trimmed)
    ? trimmed
    : `https://${trimmed}`;
  let parsed: URL;
  try {
    parsed = new URL(withScheme);
  } catch {
    throw new Error('Format alamat URL tidak sah.');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('Hanya tautan http:// dan https:// yang diizinkan.');
  }
  if (parsed.username || parsed.password) {
    throw new Error('Kredensial di dalam URL tidak diizinkan.');
  }
  if (parsed.port && parsed.port !== '80' && parsed.port !== '443') {
    throw new Error('Hanya port standar 80 dan 443 yang diizinkan.');
  }
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (
    !host ||
    host === 'localhost' ||
    host === 'metadata.google.internal' ||
    host.endsWith('.local') ||
    host.endsWith('.internal') ||
    /^0\./.test(host) ||
    /^127\./.test(host) ||
    /^10\./.test(host) ||
    /^192\.168\./.test(host) ||
    /^169\.254\./.test(host) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(host) ||
    /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(host) ||
    host === '::1' ||
    host === '::' ||
    host.startsWith('fc') ||
    host.startsWith('fd') ||
    host.startsWith('fe80:') ||
    host.startsWith('::ffff:')
  ) {
    const err = new Error('Alamat jaringan internal atau privat ditolak demi keamanan.') as Error & {
      status?: number;
      code?: string;
    };
    err.status = 403;
    err.code = 'BLOCKED_URL';
    throw err;
  }
  return parsed.toString();
}

export function toSafeHttpUrl(raw: string): string | null {
  try {
    return normalizeWebUrl(raw);
  } catch {
    return null;
  }
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
    if (masked.includes(srcTerm)) {
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

/** Cleans machine-translation punctuation & spacing artifacts for crisp literary readability. */
export function polishTranslatedProse(text: string, tgt: TargetLang): string {
  if (!text) return text;
  if (tgt === 'ja') {
    return text.replace(/[ \t]{2,}/g, ' ').trim();
  }
  return text
    .replace(/\u3000+/g, ' ')
    .replace(/``\s*/g, '"')
    .replace(/\s*''/g, '"')
    .replace(/“\s+/g, '"')
    .replace(/\s+”/g, '"')
    .replace(/"\s+([^"\n]+?)\s+"/g, '"$1"')
    .replace(/\s+([,.;:?!])/g, '$1')
    .replace(/([.!?])(?=[^\s"”’)\].!?0-9])/g, '$1 ')
    .replace(/\.{4,}/g, '...')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
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

const PARA_CACHE_STORAGE_KEY = 'tranx_para_cache_v2';
const MAX_PARA_CACHE_MEM = 900;
const MAX_PARA_CACHE_LS = 450;
const paraTranslationCache = new Map<string, string>();
let paraCacheHydrated = false;
let paraCacheFlushTimer: number | null = null;

function hydrateParaCacheOnce(): void {
  if (paraCacheHydrated || typeof window === 'undefined') return;
  paraCacheHydrated = true;
  try {
    const raw = window.localStorage.getItem(PARA_CACHE_STORAGE_KEY);
    if (!raw) return;
    const entries = JSON.parse(raw);
    if (Array.isArray(entries)) {
      for (const pair of entries) {
        if (Array.isArray(pair) && typeof pair[0] === 'string' && typeof pair[1] === 'string') {
          paraTranslationCache.set(pair[0], pair[1]);
        }
      }
    }
  } catch {
    // Ignore storage read issues
  }
}

function scheduleParaCacheFlush(): void {
  if (typeof window === 'undefined' || paraCacheFlushTimer !== null) return;
  paraCacheFlushTimer = window.setTimeout(() => {
    paraCacheFlushTimer = null;
    try {
      const recent = Array.from(paraTranslationCache.entries()).slice(-MAX_PARA_CACHE_LS);
      window.localStorage.setItem(PARA_CACHE_STORAGE_KEY, JSON.stringify(recent));
    } catch {
      // Ignore storage quota errors
    }
  }, 1500);
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
  if (paraTranslationCache.size > MAX_PARA_CACHE_MEM) {
    const oldestKey = paraTranslationCache.keys().next().value;
    if (oldestKey !== undefined) paraTranslationCache.delete(oldestKey);
  }
  scheduleParaCacheFlush();
}

function hasTranslatableLetters(text: string): boolean {
  return /[\p{L}\p{N}\u3040-\u30ff\u3400-\u9fff]/u.test(text);
}

function cleanCjkSpacing(raw: string): string {
  return raw.replace(
    /([\u3000-\u30ff\u3400-\u9fff\uff00-\uffef])\s+(?=[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef])/g,
    '$1'
  );
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

  try {
    const resp = await fetch(
      `https://translate.googleapis.com/translate_a/single?${queryMeta.toString()}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: bodyForm.toString(),
        signal,
      }
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
      return { translated: pieces.join(''), detected };
    }
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError') throw err;
  }

  // Fallback 1: GET for short payloads or alternate Google endpoint
  if (clean.length <= 450) {
    try {
      const qs = new URLSearchParams({
        client: 'gtx',
        sl: src,
        tl: tgt,
        dt: 't',
        q: clean,
      });
      const respGet = await fetch(
        `https://translate.googleapis.com/translate_a/single?${qs.toString()}`,
        { method: 'GET', signal }
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
      if ((err as { name?: string })?.name === 'AbortError') throw err;
    }
  }

  // Fallback 2: MyMemory public translation API for short chunks
  if (clean.length <= 480) {
    try {
      const effSrc = src === 'auto' ? detectLanguageLocal(clean, tgt === 'ja' ? 'id' : 'ja') : src;
      const mmQs = new URLSearchParams({
        q: clean,
        langpair: `${effSrc}|${tgt}`,
      });
      const mmResp = await fetch(
        `https://api.mymemory.translated.net/get?${mmQs.toString()}`,
        { signal }
      );
      if (mmResp.ok) {
        const mmData = await mmResp.json();
        const mmText = String(mmData?.responseData?.translatedText || '').trim();
        if (mmText) return { translated: mmText, detected: effSrc };
      }
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') throw err;
    }
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

  // Pack optimal request batches (<= 18 items, <= 1,750 chars each)
  const batches: Array<Array<{ text: string; slots: number[] }>> = [];
  let cursor = 0;
  while (cursor < work.length) {
    const batch: Array<{ text: string; slots: number[] }> = [];
    let charCount = 0;
    while (
      cursor < work.length &&
      batch.length < 18 &&
      charCount + work[cursor].text.length <= 1750
    ) {
      batch.push(work[cursor]);
      charCount += work[cursor].text.length + 12;
      cursor += 1;
    }
    if (batch.length === 0) {
      batch.push(work[cursor]);
      cursor += 1;
    }
    batches.push(batch);
  }

  // Execute up to 3 batches concurrently for ~3.5x faster chapter & document translation!
  await runConcurrentPool(batches, 3, async (batch) => {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

    if (batch.length === 1 && batch[0].text.length > 1750) {
      const parts = batch[0].text.split(/(?<=[。！？.!?\n])/);
      const subChunks: string[] = [];
      let acc = '';
      for (const part of parts) {
        if ((acc + part).length > 1300 && acc) {
          subChunks.push(acc);
          acc = part;
        } else {
          acc += part;
        }
      }
      if (acc) subChunks.push(acc);
      const translatedSubs = new Array<string>(subChunks.length).fill('');
      await runConcurrentPool(subChunks, 2, async (sc, scIdx) => {
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
        assignSlots(batch[0].slots, res.translated || batch[0].text);
      } catch (err) {
        if ((err as { name?: string })?.name === 'AbortError') throw err;
        if (work.length === 1) throw err;
        assignSlots(batch[0].slots, batch[0].text);
      }
      return;
    }

    const joined = batch.map((b, k) => `[[#${k}]] ${b.text}`).join('\n');
    try {
      const res = await requestGtxSingleChunk(joined, src, tgt, signal);
      if (res.detected) detected = res.detected;
      const splitParts = res.translated.split(/\[\[\s*#\s*(\d+)\s*\]\]/);
      const batchOut = new Array<string>(batch.length).fill('');
      for (let p = 1; p + 1 < splitParts.length; p += 2) {
        const slot = Number(splitParts[p]);
        if (batch[slot]) {
          batchOut[slot] = splitParts[p + 1].trim();
        }
      }
      for (let bIdx = 0; bIdx < batch.length; bIdx += 1) {
        if (batchOut[bIdx]) {
          assignSlots(batch[bIdx].slots, batchOut[bIdx]);
        } else {
          const singleRes = await requestGtxSingleChunk(batch[bIdx].text, src, tgt, signal).catch(
            () => ({ translated: batch[bIdx].text })
          );
          assignSlots(batch[bIdx].slots, singleRes.translated || batch[bIdx].text);
        }
      }
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') throw err;
      for (const b of batch) {
        const singleRes = await requestGtxSingleChunk(b.text, src, tgt, signal).catch(() => ({
          translated: b.text,
        }));
        assignSlots(b.slots, singleRes.translated || b.text);
      }
    }
  });

  return { outputs, detected };
}

async function translateViaGeminiDirect(
  paragraphs: string[],
  src: SourceLang,
  tgt: TargetLang,
  geminiKey: string,
  signal?: AbortSignal,
  onChunkDone?: (startOffset: number, chunkOutputs: string[]) => void
): Promise<string[]> {
  const langNames: Record<TargetLang, string> = {
    ja: 'Japanese',
    id: 'Indonesian',
    en: 'English',
  };
  const srcLabel = src === 'auto' ? 'any detected source language' : langNames[src];
  const sysPrompt =
    `You are a literary and technical translator producing fluent, natural, accurate ${langNames[tgt]} without summarizing. ` +
    `Translate from ${srcLabel} into idiomatic ${langNames[tgt]} with natural dialogue rhythm and consistent pronouns. ` +
    `Ensure 100% of every output item is written in ${langNames[tgt]}. ` +
    `Keep any text that is already in ${langNames[tgt]} intact in ${langNames[tgt]} and NEVER translate it into another language. ` +
    `Keep placeholders like [[E1]] verbatim in their natural grammatical position. Preserve line breaks. ` +
    `Return strict JSON: {"translations":[{"id":1,"text":"..."}]}`;

  const chunkSize = 40;
  const chunks: Array<{ start: number; slice: string[] }> = [];
  for (let i = 0; i < paragraphs.length; i += chunkSize) {
    chunks.push({ start: i, slice: paragraphs.slice(i, i + chunkSize) });
  }

  const allOut = new Array<string>(paragraphs.length);
  await runConcurrentPool(chunks, 2, async ({ start, slice }) => {
    const items = slice.map((text, idx) => ({ id: idx + 1, text }));
    const resp = await fetch(
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
              parts: [{ text: `Input:\n${JSON.stringify(items)}` }],
            },
          ],
          generationConfig: {
            responseMimeType: 'application/json',
            temperature: 0.2,
          },
        }),
        signal,
      }
    );
    if (!resp.ok) {
      throw new Error(`Gemini HTTP ${resp.status}`);
    }
    const raw = await resp.json();
    const textPart = raw?.candidates?.[0]?.content?.parts?.[0]?.text || '{}';
    const parsed = JSON.parse(textPart);
    const map = new Map<number, string>();
    for (const row of parsed.translations || []) {
      map.set(Number(row.id), String(row.text || ''));
    }
    const chunkOut = slice.map((orig, idx) => map.get(idx + 1) || orig);
    chunkOut.forEach((txt, idx) => {
      allOut[start + idx] = txt;
    });
    onChunkDone?.(start, chunkOut);
  });
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
    const r = await requestGtxSingleChunk(line, latinSrc, 'ja', signal).catch(() => ({
      translated: line,
    }));
    return r.translated || line;
  }

  // Replace every Japanese/CJK span inside the line with its target translation first
  const spans: string[] = [];
  const tokenLine = line.replace(CJK_SPAN_RE, (match) => {
    if (!hasTranslatableLetters(match)) return match;
    const idx = spans.length;
    spans.push(match);
    return `[[C${idx}]]`;
  });

  let merged = tokenLine;
  if (spans.length > 0) {
    const { outputs } = await translateBatchViaGoogleGtx(spans, 'ja', tgt, signal);
    outputs.forEach((tr, idx) => {
      merged = merged.split(`[[C${idx}]]`).join(tr || spans[idx]);
    });
  }

  // If the remaining Latin part is in a non-target language (e.g. English when tgt=id), translate it too
  const restClass = classifyParagraphLanguage(merged);
  if (
    (tgt === 'id' && (restClass === 'en' || restClass === 'mixed-latin')) ||
    (tgt === 'en' && (restClass === 'id' || restClass === 'mixed-latin'))
  ) {
    const secondSrc: SourceLang = restClass === 'en' ? 'en' : restClass === 'id' ? 'id' : 'auto';
    const r2 = await requestGtxSingleChunk(merged, secondSrc, tgt, signal).catch(() => ({
      translated: merged,
    }));
    return r2.translated || merged;
  }
  return merged;
}

export async function translateParagraphsDirect(params: {
  paragraphs: string[];
  mode: ModePair;
  titleId?: string;
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
  // Compact signature of active glossary + engine so cache invalidates automatically on glossary/key change
  const glossarySig = `${geminiKey ? 'g' : 'x'}${combinedGlossaryPairs.length}:${combinedGlossaryPairs
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
    if (cached !== undefined) {
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

  const maskedEntries = toTranslateIdx.map((origIdx) => ({
    origIdx,
    cls: paraClasses[origIdx],
    cacheKey: makeParaCacheKey(src, tgt, glossarySig, params.paragraphs[origIdx].trim()),
    ...maskWithGlossary(params.paragraphs[origIdx], combinedGlossaryPairs),
  }));

  if (geminiKey) {
    try {
      await translateViaGeminiDirect(
        maskedEntries.map((m) => m.masked),
        src,
        tgt,
        geminiKey,
        params.signal,
        (startOffset, chunkOut) => {
          chunkOut.forEach((txt, offset) => {
            const m = maskedEntries[startOffset + offset];
            if (!m) return;
            const finalTxt = polishTranslatedProse(unmaskWithGlossary(txt || m.masked, m.map), tgt);
            setCachedParaTranslation(m.cacheKey, finalTxt);
            markDone(m.origIdx, finalTxt, offset === chunkOut.length - 1);
          });
        }
      );
      params.onProgress?.(outputs.slice(), totalCount, totalCount);
      return {
        outputs,
        detectedSource,
        model: 'gemini-2.5-flash-lite',
        matchedChips,
      };
    } catch {
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
          const finalTxt = polishTranslatedProse(
            unmaskWithGlossary(translatedRaw || item.masked, item.map),
            tgt
          );
          setCachedParaTranslation(item.cacheKey, finalTxt);
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
          const finalTxt = polishTranslatedProse(
            unmaskWithGlossary(batchedRes.outputs[k] || item.masked, item.map),
            tgt
          );
          setCachedParaTranslation(item.cacheKey, finalTxt);
          markDone(item.origIdx, finalTxt);
        }
      });
    })
  );

  if (mixedJaItems.length > 0) {
    await runConcurrentPool(mixedJaItems, 3, async (item) => {
      const tr = await translateMixedCjkLineToTarget(item.masked, tgt, params.signal);
      const finalTxt = polishTranslatedProse(unmaskWithGlossary(tr, item.map), tgt);
      setCachedParaTranslation(item.cacheKey, finalTxt);
      markDone(item.origIdx, finalTxt);
      if (tgt !== 'ja') detectedSource = 'ja';
    });
  }

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
  rawHtml?: string;
  rawMarkdown?: string;
}

const webArticleCache = new Map<string, CachedWebEntry>();
const inFlightArticleFetches = new Map<string, Promise<CachedWebEntry>>();
const translatedWebCache = new Map<string, { heading: string; paras: string[] }>();
const inFlightPreTranslations = new Set<string>();
const translatedSiteHtmlCache = new Map<string, string>();
const seriesTocCache = new Map<
  string,
  { seriesTitle?: string; tocUrl: string; chapters: NovelChapterLink[] }
>();
const translatedChapterTitlesCache = new Map<string, Record<string, string>>();

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
  const head = `${title}\n${content.slice(0, 800)}\n${html.slice(0, 2200)}`;
  const hasChallengeMarker =
    /just a moment\.\.\.|attention required!\s*\|\s*cloudflare|checking your browser|enable javascript and cookies to continue|cf-browser-verification|cf-challenge|challenge-platform|verify you are human|please complete the security check|ddos-guard|access denied\s*\|\s*cloudflare/i.test(
      head
    );
  if (!hasChallengeMarker) return false;
  // Only flag if body text is small (real articles discussing Cloudflare are long!)
  if (content.length > 2500) return false;
  if (html.length > 25000 && !/just a moment\.\.\.|attention required/i.test(title)) return false;
  return true;
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

export function deriveSeriesTitleId(rawUrl: string): string {
  try {
    const u = new URL(rawUrl);
    const host = u.hostname.toLowerCase();
    const path = u.pathname;
    const kakuyomu = path.match(/^\/works\/(\d+)/);
    if (host.includes('kakuyomu.jp') && kakuyomu) {
      return `t_novel_kakuyomu_${kakuyomu[1]}`;
    }
    const syosetu = path.match(/^\/(n[a-z0-9]+)/i);
    if (host.includes('syosetu.com') && syosetu) {
      return `t_novel_syosetu_${syosetu[1].toLowerCase()}`;
    }
    const hameln = path.match(/^\/novel\/(\d+)/);
    if (host.includes('syosetu.org') && hameln) {
      return `t_novel_hameln_${hameln[1]}`;
    }
    const alpha = path.match(/^\/novel\/(\d+\/\d+)/);
    if (host.includes('alphapolis.co.jp') && alpha) {
      return `t_novel_alpha_${alpha[1].replace(/\//g, '_')}`;
    }
    const aozora = path.match(/^\/cards\/(\d+)/);
    if (host.includes('aozora.gr.jp') && aozora) {
      return `t_novel_aozora_${aozora[1]}`;
    }
    const royal = path.match(/^\/fiction\/(\d+)/);
    if (host.includes('royalroad.com') && royal) {
      return `t_novel_rr_${royal[1]}`;
    }
    const scribble = path.match(/^\/(?:read|series)\/(\d+)/);
    if (host.includes('scribblehub.com') && scribble) {
      return `t_novel_sh_${scribble[1]}`;
    }
    const ao3 = path.match(/^\/works\/(\d+)/);
    if (host.includes('archiveofourown.org') && ao3) {
      return `t_novel_ao3_${ao3[1]}`;
    }
    const ffnet = path.match(/^\/s\/(\d+)/);
    if (host.includes('fanfiction.net') && ffnet) {
      return `t_novel_ff_${ffnet[1]}`;
    }
    const genericNovel = path.match(/^\/(?:b|book|novel|series|story|light-novel)\/([^/]+)/i);
    if (genericNovel) {
      const slug = genericNovel[1].replace(/[^a-z0-9]/gi, '_').slice(0, 28);
      return `t_novel_${host.replace(/^www\./, '').split('.')[0].slice(0, 12)}_${slug}`;
    }
    return `t_web_${host.replace(/[^a-z0-9]/gi, '_').slice(0, 24)}`;
  } catch {
    return 't_web_page';
  }
}

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
      chapters: chapters.slice(0, 500),
    });
  } catch {
    return null;
  }
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
      chapters: chapters.slice(0, 500),
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
      return parsed.slice(0, 500);
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

  const capped = chapters.slice(0, 500);
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
  const resp = await fetch(`https://r.jina.ai/${cleanUrl}`, {
    method: 'GET',
    headers,
    signal: options.signal,
  });
  if (!resp.ok) return null;
  const ctype = resp.headers.get('content-type') || '';
  if (ctype.includes('application/json')) {
    const json = await resp.json();
    const d = json?.data || {};
    const title = decodeHtmlEntities(String(d.title || '').trim());
    const finalUrl =
      typeof d.finalUrl === 'string' && d.finalUrl.startsWith('http')
        ? d.finalUrl
        : typeof d.url === 'string' && d.url.startsWith('http')
          ? d.url
          : cleanUrl;
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
      if (typeof v === 'string' && v.startsWith('http')) {
        links.push({ title: decodeHtmlEntities(k), url: v });
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
      isSuspiciousTrackerPayload(cleanUrl, first.title, first.finalUrl, first.html, first.content)
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
    return await fetchViaJinaInternal(cleanUrl, {
      format: 'markdown',
      noCache: Boolean(options?.noCache),
      signal: options?.signal,
    });
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
      if (paras.length >= 220) break;
    }
    if (paras.length >= 220) break;
  }

  if (paras.length >= 2) return paras;

  // Fallback for <br>-separated prose inside a single container (e.g. Aozora Bunko .main_text, Hameln #honbun, Blogger)
  const brLines = extractNodeLinesPreservingBreaks(root)
    .filter((s, idx) => s.length >= 1 && !(idx === 0 && normTitle && s.toLowerCase() === normTitle))
    .slice(0, 220);
  return brLines.length >= paras.length ? brLines : paras;
}

async function fetchSeriesTocDirect(
  tocUrl: string,
  currentUrl: string
): Promise<NovelNavigation | null> {
  const safeToc = toSafeHttpUrl(tocUrl);
  if (!safeToc) return null;
  const cacheKey = canonicalUrlKey(safeToc);
  const mem = seriesTocCache.get(cacheKey);
  if (mem && mem.chapters.length >= 2) {
    return applyChapterListToCurrentUrl(mem, currentUrl);
  }
  if (typeof window !== 'undefined') {
    try {
      const saved = window.sessionStorage.getItem(`tranx_toc_v2::${cacheKey}`);
      if (saved) {
        const parsed = JSON.parse(saved) as {
          seriesTitle?: string;
          tocUrl: string;
          chapters: NovelChapterLink[];
        };
        if (Array.isArray(parsed.chapters) && parsed.chapters.length >= 2) {
          seriesTocCache.set(cacheKey, parsed);
          return applyChapterListToCurrentUrl(parsed, currentUrl);
        }
      }
    } catch {
      // ignore storage errors
    }
  }

  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 14000);
  try {
    let bestNav: NovelNavigation | null = null;
    let fallbackTitle = '';

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
      }
      if ((!bestNav || (bestNav.chapters?.length || 0) < 2) && (jinaRes.content || jinaRes.links.length > 0)) {
        const mdNav = extractNovelNavigationFromMarkdown(jinaRes.content, safeToc, jinaRes.links);
        if ((mdNav.chapters?.length || 0) > (bestNav?.chapters?.length || 0)) {
          bestNav = mdNav;
        }
      }
    }

    // Secondary: Jina Rendered Markdown + Links Summary when HTML TOC was empty/challenged/mojibake
    if (!bestNav || (bestNav.chapters?.length || 0) < 2) {
      const mdRes = await fetchViaJinaRenderedMarkdown(safeToc, {
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
    }

    // Tertiary fallback: CORS HTML proxies if Jina didn't find >= 2 chapters
    if (!bestNav || (bestNav.chapters?.length || 0) < 2) {
      const raw = await fetchRawHtmlViaCorsProxy(safeToc, ctrl.signal).catch(() => null);
      if (raw && !isChallengeOrBlockedPayload('', raw, '')) {
        const doc = new DOMParser().parseFromString(raw, 'text/html');
        const proxyNav = extractNovelNavigationFromHtml(doc, raw, safeToc);
        if ((proxyNav.chapters?.length || 0) > (bestNav?.chapters?.length || 0)) {
          bestNav = proxyNav;
        }
      }
    }

    const bestChapters = bestNav?.chapters || [];
    if (bestChapters.length < 2) return null;

    const seriesTitle = bestNav?.seriesTitle || fallbackTitle || undefined;
    const tocRecord = {
      ...(seriesTitle ? { seriesTitle } : {}),
      tocUrl: safeToc,
      chapters: bestChapters,
    };
    seriesTocCache.set(cacheKey, tocRecord);
    if (typeof window !== 'undefined') {
      try {
        window.sessionStorage.setItem(`tranx_toc_v2::${cacheKey}`, JSON.stringify(tocRecord));
      } catch {
        // ignore quota
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
}): Promise<Record<string, string>> {
  const { chapters, mode, titleId, tocKey } = params;
  if (!chapters.length) return {};
  const cacheKey = `${tocKey}::${mode}`;
  const cached = translatedChapterTitlesCache.get(cacheKey);
  if (cached && Object.keys(cached).length >= Math.min(chapters.length, 60)) {
    return cached;
  }
  const map: Record<string, string> = { ...(cached || {}) };
  // Prioritize window around current chapter (or first 80 chapters) so TOC translates fast
  const curIdx = chapters.findIndex((c) => c.current);
  const start = curIdx >= 0 ? Math.max(0, curIdx - 30) : 0;
  const slice = chapters.slice(start, start + 80).filter((c) => !map[c.url] && c.title.trim());
  if (slice.length > 0) {
    try {
      const { outputs } = await translateParagraphsDirect({
        paragraphs: slice.map((c) => c.title),
        mode,
        titleId,
      });
      slice.forEach((ch, idx) => {
        if (outputs[idx]) map[ch.url] = outputs[idx];
      });
      translatedChapterTitlesCache.set(cacheKey, map);
    } catch {
      // Keep original titles gracefully if network hiccups
    }
  }
  return map;
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
  const buf = await resp.arrayBuffer();
  if (buf.byteLength > 5 * 1024 * 1024) return '';
  const bytes = new Uint8Array(buf);
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
  const proxies = [
    `https://api.allorigins.win/raw?url=${encodeURIComponent(cleanUrl)}`,
    `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(cleanUrl)}`,
  ];
  // Race proxies in parallel so one dead proxy never blocks another
  const attempts = proxies.map(async (endpoint) => {
    const resp = await fetch(endpoint, { method: 'GET', signal });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const html = await decodeHtmlResponseWithCharset(resp);
    if (!html || !/<(html|body|article|div|p)\b/i.test(html)) {
      throw new Error('Non-HTML payload');
    }
    if (isChallengeOrBlockedPayload('', html, '')) {
      throw new Error('Blocked challenge payload');
    }
    return html;
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
  return paras.slice(0, 200);
}

async function fetchWebArticleDirect(
  rawUrl: string,
  options?: { needRawHtml?: boolean }
): Promise<CachedWebEntry> {
  const cleanUrl = normalizeWebUrl(rawUrl);
  const cached = webArticleCache.get(cleanUrl);
  if (cached && (!options?.needRawHtml || cached.rawHtml)) {
    return cached;
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
  options?: { needRawHtml?: boolean }
): Promise<CachedWebEntry> {
  const host = new URL(cleanUrl).hostname;
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 24000);

  try {
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
      const mdRes = await fetchViaJinaRenderedMarkdown(cleanUrl, { signal: ctrl.signal });
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

    // Secondary Fallback: Parallel charset-aware CORS HTML proxies when still empty or raw HTML needed for view=site
    if (!rawHtml && (srcParas.length === 0 || (options?.needRawHtml && srcParas.length < 2))) {
      const htmlCtrl = new AbortController();
      const htmlTimer = window.setTimeout(() => htmlCtrl.abort(), 7000);
      try {
        const fetched = await fetchRawHtmlViaCorsProxy(cleanUrl, htmlCtrl.signal);
        if (fetched && !hasMojibake(fetched.slice(0, 2000))) {
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
      }
    }

    if (srcParas.length === 0) {
      if (hitAntiBotChallenge) {
        throw new Error(
          `Situs ${host} memasang verifikasi keamanan / anti-bot (Cloudflare) sehingga konten tidak dapat diambil otomatis. Buka situs asli atau salin teks halaman langsung ke tab Teks.`
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
    // If current page itself IS a TOC page with chapters, store it in seriesTocCache for instant chapter navigation
    if (mergedNav.chapters && mergedNav.chapters.length >= 2 && mergedNav.tocUrl) {
      const tocKey = canonicalUrlKey(mergedNav.tocUrl);
      if (!seriesTocCache.has(tocKey)) {
        seriesTocCache.set(tocKey, {
          ...(mergedNav.seriesTitle ? { seriesTitle: mergedNav.seriesTitle } : {}),
          tocUrl: mergedNav.tocUrl,
          chapters: mergedNav.chapters,
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
      rawHtml: rawHtml || undefined,
      rawMarkdown: rawMarkdown || undefined,
    };
    webArticleCache.set(cleanUrl, entry);
    webArticleCache.set(finalUrl, entry);
    return entry;
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError') {
      throw new Error(`Waktu tunggu habis saat mengambil halaman ${host}. Coba lagi.`);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

export function prefetchWebArticleDirect(rawUrl?: string | null): void {
  if (!rawUrl) return;
  const safe = toSafeHttpUrl(rawUrl);
  if (!safe || webArticleCache.has(safe)) return;
  fetchWebArticleDirect(safe).catch(() => {});
}

/**
 * Fetches and pre-translates the upcoming chapter in idle background time so
 * clicking "Next chapter" opens instantaneously from memory + L2 cache.
 */
export function prefetchNextChapterTranslatedDirect(
  rawUrl?: string | null,
  mode: ModePair = 'auto-id',
  titleId?: string
): void {
  if (!rawUrl) return;
  const safe = toSafeHttpUrl(rawUrl);
  if (!safe) return;
  const cacheKey = `${safe}::${mode}`;
  if (translatedWebCache.has(cacheKey) || inFlightPreTranslations.has(cacheKey)) return;

  inFlightPreTranslations.add(cacheKey);
  const runTask = () => {
    (async () => {
      try {
        const article = await fetchWebArticleDirect(safe);
        const articleCacheKey = `${article.url}::${mode}`;
        if (translatedWebCache.has(articleCacheKey)) return;
        const tid = titleId || article.titleId;
        const cappedSrc = article.srcParas.slice(0, 180);
        const batch = [article.titleSrc, ...cappedSrc];
        const { outputs } = await translateParagraphsDirect({
          paragraphs: batch,
          mode,
          titleId: tid,
        });
        const heading = outputs[0]?.replace(/^#{1,6}\s+/, '') || article.titleSrc;
        const paras = outputs.slice(1).map((s) => s.replace(/^#{1,6}\s+/, ''));
        translatedWebCache.set(articleCacheKey, { heading, paras });
        translatedWebCache.set(cacheKey, { heading, paras });
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
      idleCb(runTask, { timeout: 1400 });
    } else {
      window.setTimeout(runTask, 300);
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
    .replace(/"/g, '&quot;');
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
}): Promise<string> {
  const { article, mode, translatedHeading, translatedParas } = params;
  const cacheKey = `${article.url}::${mode}::site`;
  const cachedHtml = translatedSiteHtmlCache.get(cacheKey);
  if (cachedHtml) return cachedHtml;

  const { tgt } = parseModePair(mode);
  const nav = article.novelNav;
  const navButtonsHtml =
    nav.prevUrl || nav.nextUrl || nav.tocUrl
      ? `<div style="position:sticky;bottom:0;z-index:9999;background:#141917;color:#FAFBFA;padding:12px 16px;display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;border-top:1px solid #2B3230;font-family:Inter,-apple-system,sans-serif;font-size:14px;">
          ${
            nav.prevUrl
              ? `<a href="${escapeHtml(buildTranxWebHref(nav.prevUrl, mode, 'site', params.titleId))}" target="_top" rel="noopener noreferrer" style="color:#E7ECEA;text-decoration:none;padding:8px 14px;border:1px solid #3C4743;border-radius:10px;font-weight:600;">&#8592; Bab sebelumnya</a>`
              : ''
          }
          ${
            nav.tocUrl
              ? `<a href="${escapeHtml(buildTranxWebHref(nav.tocUrl, mode, 'site', params.titleId))}" target="_top" rel="noopener noreferrer" style="color:#E7ECEA;text-decoration:none;padding:8px 14px;border:1px solid #3C4743;border-radius:10px;font-weight:600;">Daftar bab</a>`
              : ''
          }
          ${
            nav.nextUrl
              ? `<a href="${escapeHtml(buildTranxWebHref(nav.nextUrl, mode, 'site', params.titleId))}" target="_top" rel="noopener noreferrer" style="background:#17695B;color:#FFFFFF;text-decoration:none;padding:8px 16px;border-radius:10px;font-weight:600;">Bab berikutnya &#8594;</a>`
              : ''
          }
        </div>`
      : '';

  if (article.rawHtml) {
    const doc = new DOMParser().parseFromString(article.rawHtml, 'text/html');

    // Remove all executable/embedded/redirect tags strictly (zero JS in translated site iframe)
    doc
      .querySelectorAll(
        'script, noscript, iframe, frame, frameset, object, embed, applet, base, meta[http-equiv="refresh"], meta[http-equiv="Content-Security-Policy"]'
      )
      .forEach((el) => el.remove());

    // Sanitize attributes and rewrite every safe <a href> into tranX auto-translating /web links
    const allElements = Array.from(doc.querySelectorAll('*'));
    for (const el of allElements) {
      for (const attr of Array.from(el.attributes)) {
        const name = attr.name.toLowerCase();
        if (name.startsWith('on') || name === 'srcdoc') {
          el.removeAttribute(attr.name);
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
            cleanedVal.startsWith('data:text/html') ||
            cleanedVal.startsWith('data:image/svg')
          ) {
            el.removeAttribute(attr.name);
          }
        }
      }

      if (el.tagName === 'A') {
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
        const rawHref = el.getAttribute('href') || '';
        const safeAbs = resolveSafeSiblingUrl(rawHref, article.url);
        if (safeAbs) {
          el.setAttribute('href', safeAbs);
        } else {
          el.removeAttribute('href');
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
        if (rawSrc && !rawSrc.startsWith('data:')) {
          const safeAbs = resolveSafeSiblingUrl(rawSrc, article.url);
          if (safeAbs) el.setAttribute('src', safeAbs);
        }
        const rawPoster = el.getAttribute('poster') || '';
        if (rawPoster) {
          const safePoster = resolveSafeSiblingUrl(rawPoster, article.url);
          if (safePoster) el.setAttribute('poster', safePoster);
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

    // Inject lightweight responsive safety CSS so translated site fits cleanly on Desktop & Mobile
    const head = doc.head || doc.createElement('head');
    if (!doc.head && doc.documentElement) {
      doc.documentElement.insertBefore(head, doc.body);
    }
    const safeStyle = doc.createElement('style');
    safeStyle.textContent =
      'html,body{overflow-x:hidden !important;max-width:100vw !important;} img,video{max-width:100% !important;height:auto !important;}';
    head.appendChild(safeStyle);

    // Collect visible text nodes prioritizing main article content FIRST (up to 750 nodes) so long Wikipedia/news/novel pages never stop halfway
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
    const MAX_SITE_NODES = 750;
    const textNodes: Text[] = [];
    const seenTextNodes = new Set<Text>();
    const collectFromSubtree = (rootEl: Node | null) => {
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
            (!parent || !skipParentTags.has(parent.tagName))
          ) {
            seenTextNodes.add(tn);
            textNodes.push(tn);
          }
        }
        node = walker.nextNode();
      }
    };

    const mainRegion = doc.querySelector(MAIN_CONTENT_SELECTORS);
    if (mainRegion) collectFromSubtree(mainRegion);
    collectFromSubtree(doc.body || doc.documentElement);

    // Guard against blank JS-only SPA shells (<div id="root"></div>): fall back to clean semantic translated view!
    if (textNodes.length >= 2 || translatedParas.length < 2) {
      if (textNodes.length > 0) {
        const { outputs } = await translateParagraphsDirect({
          paragraphs: textNodes.map((n) => (n.nodeValue || '').trim()),
          mode,
          titleId: params.titleId || article.titleId,
        });
        textNodes.forEach((tn, idx) => {
          if (outputs[idx]) {
            tn.nodeValue = outputs[idx];
          }
        });
      }

      if (doc.title) {
        doc.title = translatedHeading;
      }
      if (navButtonsHtml && doc.body) {
        const navWrap = doc.createElement('div');
        navWrap.innerHTML = navButtonsHtml;
        doc.body.appendChild(navWrap);
      }

      const serialized = `<!doctype html>\n${doc.documentElement.outerHTML}`;
      translatedSiteHtmlCache.set(cacheKey, serialized);
      return serialized;
    }
  }

  // Clean semantic fallback when CORS HTML proxy was blocked: still rewrites chapter links into /web!
  const isJpBody = tgt === 'ja';
  const fontStack = isJpBody
    ? '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif'
    : 'Charter, Georgia, Cambria, serif';
  const renderedParas = translatedParas
    .map((p) =>
      /^#{1,3}\s+/.test(p)
        ? `<h2>${escapeHtml(p.replace(/^#{1,6}\s+/, ''))}</h2>`
        : `<p>${escapeHtml(p)}</p>`
    )
    .join('\n');

  const chaptersHtml =
    nav.chapters && nav.chapters.length > 0
      ? `<section style="margin-top:32px;padding-top:20px;border-top:1px solid #DEE3E0;">
          <h2 style="font-family:Inter,-apple-system,sans-serif;font-size:16px;">Daftar Bab</h2>
          <ul style="list-style:none;padding:0;margin:12px 0;display:flex;flex-direction:column;gap:8px;font-family:Inter,-apple-system,sans-serif;font-size:14px;">
            ${nav.chapters
              .slice(0, 40)
              .map(
                (ch) =>
                  `<li><a href="${escapeHtml(buildTranxWebHref(ch.url, mode, 'site', params.titleId))}" target="_top" rel="noopener noreferrer" style="color:#17695B;font-weight:${ch.current ? '700' : '500'};text-decoration:none;">${escapeHtml(ch.title)}</a></li>`
              )
              .join('')}
          </ul>
        </section>`
      : '';

  const fallbackHtml = `<!doctype html>
<html lang="${tgt}">
<head>
<meta charset="utf-8">
<title>${escapeHtml(translatedHeading)}</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; padding: 28px 20px 0; background: #FAFBFA; color: #141917; font-family: ${fontStack}; font-size: 18px; line-height: 1.78; }
  @media (prefers-color-scheme: dark) { body { background: #171B1A; color: #E7ECEA; } header { border-bottom-color: #2B3230 !important; } .meta { color: #A5AEAA !important; } }
  article { max-width: 700px; margin: 0 auto 40px; }
  header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #DEE3E0; }
  h1 { font-size: 26px; line-height: 1.3; margin: 0 0 8px 0; }
  p { margin: 0 0 16px 0; }
  .meta { font-family: Inter, -apple-system, sans-serif; font-size: 13px; color: #4F5855; }
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
  onProgress?: (partialBundle: WebReaderBundle, doneCount: number, totalCount: number) => void;
}): Promise<WebReaderBundle> {
  const article = await fetchWebArticleDirect(params.url, {
    needRawHtml: params.view === 'site',
  });
  const tid = params.titleId || article.titleId;
  const cappedSrc = article.srcParas.slice(0, 180);

  let titleDst = article.titleSrc;
  let translatedParas = cappedSrc;

  if (params.view !== 'original') {
    const cacheKey1 = `${article.url}::${params.mode}`;
    const cacheKey2 = `${normalizeWebUrl(params.url)}::${params.mode}`;
    const preTranslated = translatedWebCache.get(cacheKey1) || translatedWebCache.get(cacheKey2);
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
      translatedWebCache.set(cacheKey1, { heading: titleDst, paras: translatedParas });
      translatedWebCache.set(cacheKey2, { heading: titleDst, paras: translatedParas });
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
    prefetchNextChapterTranslatedDirect(article.novelNav.nextUrl, params.mode, tid);
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

    if (name.includes('..') || name.startsWith('/') || !predicate(name)) continue;
    if (localHeaderOffset + 30 > bytes.length) continue;
    if (totalUncompressed + uncompSize > MAX_UNCOMPRESSED_BYTES) {
      throw new Error('Ukuran isi dokumen melebihi batas aman 50 MB.');
    }

    const lNameLen = view.getUint16(localHeaderOffset + 26, true);
    const lExtraLen = view.getUint16(localHeaderOffset + 28, true);
    const dataStart = localHeaderOffset + 30 + lNameLen + lExtraLen;
    const rawSlice = bytes.subarray(dataStart, dataStart + compSize);

    if (method === 0) {
      totalUncompressed += rawSlice.byteLength;
      if (totalUncompressed > MAX_UNCOMPRESSED_BYTES) {
        throw new Error('Ukuran isi dokumen melebihi batas aman 50 MB.');
      }
      const decodedEntry = decoder.decode(rawSlice);
      if (/<!ENTITY/i.test(decodedEntry.slice(0, 8192))) {
        throw new Error('Entitas XML eksternal (XXE) ditolak demi keamanan.');
      }
      out.set(name, decodedEntry);
    } else if (method === 8 && typeof DecompressionStream !== 'undefined') {
      const ds = new DecompressionStream('deflate-raw');
      const writer = ds.writable.getWriter();
      writer.write(rawSlice);
      writer.close();
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
            await reader.cancel();
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
      if (/<!ENTITY/i.test(decodedEntry.slice(0, 8192))) {
        throw new Error('Entitas XML eksternal (XXE) ditolak demi keamanan.');
      }
      out.set(name, decodedEntry);
    }
  }
  return out;
}

export function inspectBinaryMagicBytes(
  bytes: Uint8Array,
  ext: string,
  kind: 'gambar' | 'dokumen'
): string | null {
  if (bytes.byteLength === 0) {
    return 'Berkas kosong dan tidak dapat diproses.';
  }
  const cleanExt = ext.toLowerCase();

  if (kind === 'gambar') {
    const isPng =
      bytes.byteLength >= 8 &&
      bytes[0] === 0x89 &&
      bytes[1] === 0x50 &&
      bytes[2] === 0x4e &&
      bytes[3] === 0x47 &&
      bytes[4] === 0x0d &&
      bytes[5] === 0x0a &&
      bytes[6] === 0x1a &&
      bytes[7] === 0x0a;
    const isJpeg =
      bytes.byteLength >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
    const isWebp =
      bytes.byteLength >= 12 &&
      bytes[0] === 0x52 &&
      bytes[1] === 0x49 &&
      bytes[2] === 0x46 &&
      bytes[3] === 0x46 &&
      bytes[8] === 0x57 &&
      bytes[9] === 0x45 &&
      bytes[10] === 0x42 &&
      bytes[11] === 0x50;
    if (!isPng && !isJpeg && !isWebp) {
      return 'Isi biner berkas bukan gambar PNG, JPG, atau WEBP yang sah.';
    }
    return null;
  }

  if (cleanExt === 'pdf') {
    const head = new TextDecoder('latin1').decode(bytes.subarray(0, Math.min(bytes.byteLength, 1024)));
    if (!head.includes('%PDF-')) {
      return 'Isi biner berkas bukan dokumen PDF yang sah.';
    }
    return null;
  }

  if (cleanExt === 'docx' || cleanExt === 'epub') {
    const isZip =
      bytes.byteLength >= 4 &&
      bytes[0] === 0x50 &&
      bytes[1] === 0x4b &&
      (bytes[2] === 0x03 || bytes[2] === 0x05);
    if (!isZip) {
      return `Berkas .${cleanExt} rusak atau bukan arsip dokumen yang sah.`;
    }
    return null;
  }

  const hasUtf16Bom =
    bytes.byteLength >= 2 &&
    ((bytes[0] === 0xfe && bytes[1] === 0xff) || (bytes[0] === 0xff && bytes[1] === 0xfe));
  if (!hasUtf16Bom) {
    const sampleLen = Math.min(bytes.byteLength, 512);
    for (let i = 0; i < sampleLen; i += 1) {
      if (bytes[i] === 0x00) {
        return `Isi biner berkas tidak sesuai dengan format teks .${cleanExt}.`;
      }
    }
  }
  return null;
}

export async function validateUploadedFileMagic(
  file: File,
  kind: 'gambar' | 'dokumen'
): Promise<string | null> {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  const sliceBuf = await file.slice(0, 1024).arrayBuffer();
  return inspectBinaryMagicBytes(new Uint8Array(sliceBuf), ext, kind);
}

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
      writer.write(raw).catch(() => {});
      writer.close().catch(() => {});
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
  const bfcharRe = /beginbfchar([\s\S]*?)endbfchar/g;
  let m: RegExpExecArray | null;
  while ((m = bfcharRe.exec(streamText)) !== null) {
    const pairRe = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g;
    let pm: RegExpExecArray | null;
    while ((pm = pairRe.exec(m[1])) !== null) {
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
  while ((m = bfrangeRe.exec(streamText)) !== null) {
    const rangeRe = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g;
    let rm: RegExpExecArray | null;
    while ((rm = rangeRe.exec(m[1])) !== null) {
      const start = parseInt(rm[1], 16);
      const end = Math.min(parseInt(rm[2], 16), start + 512);
      let codePoint = parseInt(rm[3], 16);
      const width = rm[1].length;
      for (let cur = start; cur <= end; cur += 1, codePoint += 1) {
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
          else idx += 1;
        }
        if (block[idx] === ']') idx += 1;
        pendingStr = arrText;
        continue;
      }

      const tokMatch = block.slice(idx).match(/^([^\s()<>[\]/%]+)/);
      if (!tokMatch) {
        idx += 1;
        continue;
      }
      const tok = tokMatch[1];
      idx += tok.length;

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
const TESSERACT_IDLE_TTL_MS = 120_000;

async function getWarmTesseractSlot(langs: string[]): Promise<WarmTesseractSlot> {
  const key = langs.join('+');
  const existing = warmTesseractWorkers.get(key);
  if (existing) {
    if (existing.idleTimer !== null && typeof window !== 'undefined') {
      window.clearTimeout(existing.idleTimer);
      existing.idleTimer = null;
    }
    return existing;
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
      logger: () => {},
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
  if (slot.idleTimer !== null) window.clearTimeout(slot.idleTimer);
  slot.idleTimer = window.setTimeout(() => {
    if (warmTesseractWorkers.get(key) !== slot) return;
    warmTesseractWorkers.delete(key);
    slot.workerPromise
      .then((w) => w.terminate())
      .catch(() => {});
  }, TESSERACT_IDLE_TTL_MS);
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
    try {
      const worker = await slot.workerPromise;
      const { data } = await worker.recognize(
        imageSource,
        {},
        { text: true, blocks: true }
      );
      const out: Array<{ id: number; box_2d: number[]; text: string }> = [];
      const blocks = Array.isArray(data?.blocks) ? data.blocks : [];

      for (const blk of blocks) {
        const paras = Array.isArray(blk.paragraphs) ? blk.paragraphs : [];
        for (const para of paras) {
          const cleaned = cleanCjkSpacing((para.text || '').replace(/\s+/g, ' ').trim());
          if (!cleaned || !hasTranslatableLetters(cleaned)) continue;
          const bb = para.bbox || blk.bbox;
          if (bb) {
            const ymin = Math.max(0, Math.min(1000, Math.round((bb.y0 / imgH) * 1000)));
            const xmin = Math.max(0, Math.min(1000, Math.round((bb.x0 / imgW) * 1000)));
            const ymax = Math.max(0, Math.min(1000, Math.round((bb.y1 / imgH) * 1000)));
            const xmax = Math.max(0, Math.min(1000, Math.round((bb.x1 / imgW) * 1000)));
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
          .catch(() => {});
      }
      throw err;
    }
  };

  const resultPromise = slot.queue.then(runRecognize, runRecognize);
  slot.queue = resultPromise.catch(() => {});
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
    data: new Uint8Array(buffer.slice(0)),
    cMapUrl: `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/standard_fonts/`,
  });
  const pdf = await loadingTask.promise;

  if (pdf.numPages > 500) {
    throw new Error(`PDF memiliki ${pdf.numPages} halaman (batas maksimum 500 halaman).`);
  }

  const units: ParsedDocUnit[] = [];
  const maxPages = Math.min(pdf.numPages, 120);

  for (let p = 1; p <= maxPages; p += 1) {
    const page = await pdf.getPage(p);
    const textContent = await page.getTextContent();
    const lines: string[] = [];
    let curLine = '';
    let prevY: number | null = null;

    for (const rawItem of textContent.items) {
      if (!('str' in rawItem)) continue;
      const str = rawItem.str || '';
      const tx = Array.isArray(rawItem.transform) ? Number(rawItem.transform[5]) : null;
      if (prevY !== null && tx !== null && Math.abs(tx - prevY) > 4) {
        if (curLine.trim()) lines.push(cleanCjkSpacing(curLine.trim()));
        curLine = str;
      } else {
        curLine += curLine && !curLine.endsWith(' ') && !CJK_RE.test(str) ? ` ${str}` : str;
      }
      if (tx !== null) prevY = tx;
      if (rawItem.hasEOL && curLine.trim()) {
        lines.push(cleanCjkSpacing(curLine.trim()));
        curLine = '';
        prevY = null;
      }
    }
    if (curLine.trim()) lines.push(cleanCjkSpacing(curLine.trim()));

    let paraBuf: string[] = [];
    for (const ln of lines) {
      if (!ln) continue;
      paraBuf.push(ln);
      if (/[.!?。！？」』]$/.test(ln) || paraBuf.join(' ').length >= 260) {
        const sep = CJK_RE.test(ln) ? '' : ' ';
        units.push({ text: cleanCjkSpacing(paraBuf.join(sep).trim()) });
        paraBuf = [];
      }
    }
    if (paraBuf.length > 0) {
      const joined = paraBuf.join(' ');
      units.push({ text: cleanCjkSpacing(joined.trim()) });
    }
  }

  if (units.length > 0) {
    await loadingTask.destroy().catch(() => {});
    return units;
  }

  // Scanned image-only PDF: render pages to canvas and OCR via Tesseract
  const { src } = parseModePair(mode);
  const ocrPages = Math.min(pdf.numPages, 6);
  for (let p = 1; p <= ocrPages; p += 1) {
    const page = await pdf.getPage(p);
    const viewport = page.getViewport({ scale: 1.7 });
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.floor(viewport.width));
    canvas.height = Math.max(1, Math.floor(viewport.height));
    const ctx = canvas.getContext('2d');
    if (!ctx) continue;
    await page.render({ canvasContext: ctx, canvas, viewport }).promise;
    const boxes = await runTesseractOcrBoxes(canvas, canvas.width, canvas.height, src);
    for (const b of boxes) {
      if (b.text.trim()) units.push({ text: b.text.trim() });
    }
  }

  await loadingTask.destroy().catch(() => {});
  return units;
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
    const entries = await extractZipTextEntries(
      fullBuf,
      (n) => /\.(xhtml|html|htm)$/i.test(n) && !n.toLowerCase().includes('nav')
    );
    const units: ParsedDocUnit[] = [];
    const sortedNames = Array.from(entries.keys()).sort();
    for (const name of sortedNames) {
      const doc = new DOMParser().parseFromString(entries.get(name) || '', 'text/html');
      const blocks = Array.from(doc.querySelectorAll('h1, h2, h3, p'));
      for (const b of blocks) {
        const txt = (b.textContent || '').trim();
        if (txt) units.push({ text: txt });
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

const directExportCache = new Map<
  string,
  {
    fileName: string;
    fmt: string;
    headerDoc?: string;
    units: Array<{ prefix?: string; src: string; dst: string }>;
  }
>();

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
    cached?.units ||
    (params.fallbackSentences || []).map((s) => ({ src: s.src, dst: s.dst })) ||
    [{ src: '', dst: params.fallbackText || '' }];

  const ext = params.fmt.toLowerCase() === 'ssa' ? 'ass' : params.fmt.toLowerCase();
  const baseStem = (cached?.fileName || `tranx-${params.mid}`).replace(/\.[^.]+$/, '');

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
        const body = (params.bilingual && r.src ? `${r.src}\n${r.dst}` : r.dst).replace(
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
        const header = r.prefix
          ? r.prefix.replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, '$1.$2')
          : `00:00:${String((idx * 3) % 60).padStart(2, '0')}.000 --> 00:00:${String(
              ((idx * 3) % 60) + 2
            ).padStart(2, '0')}.500`;
        return `${header}\n${params.bilingual && r.src ? `${r.src}\n${r.dst}` : r.dst}`;
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
        const header =
          r.prefix ||
          `${idx + 1}\n00:00:${String((idx * 3) % 60).padStart(2, '0')},000 --> 00:00:${String(
            ((idx * 3) % 60) + 2
          ).padStart(2, '0')},500`;
        return `${header}\n${params.bilingual && r.src ? `${r.src}\n${r.dst}` : r.dst}`;
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
    const html = `<!doctype html><html lang="id" data-tranx-v3="${
      params.theme || 'Terang'
    }"><head><meta charset="utf-8"><title>${escapeHtml(
      baseStem
    )}</title><style>body{font-family:Charter,Georgia,serif;max-width:860px;margin:28px auto;padding:0 20px;line-height:1.75;background:${
      isDark ? '#171B1A' : '#FAFBFA'
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

export async function directTranslateImage(params: {
  cid: string;
  mode: ModePair;
  fileName: string;
  imageDataUrl: string;
  titleId?: string;
}): Promise<{ cid: string; mid: string; titleId: string } & ImageTranslationResult> {
  const [dataHeader, rawB64 = ''] = params.imageDataUrl.split(',', 2);
  let binaryStr = '';
  try {
    binaryStr = atob(rawB64);
  } catch {
    throw new Error('Data gambar tidak sah atau rusak.');
  }
  const rawBytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i += 1) {
    rawBytes[i] = binaryStr.charCodeAt(i) & 0xff;
  }
  const ext = (params.fileName.split('.').pop() || 'png').toLowerCase();
  const magicErr = inspectBinaryMagicBytes(rawBytes, ext, 'gambar');
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
      if (w > 8192 || h > 8192 || w * h > 25_000_000) {
        reject(new Error('Resolusi gambar melampaui batas aman 8192x8192 piksel (25 MP).'));
        return;
      }
      resolve({
        w,
        h,
        mime: mimeMatch ? mimeMatch[1] : 'image/png',
        b64: rawB64,
        imgEl: img,
      });
    };
    img.onerror = () => reject(new Error('Berkas gambar tidak dapat dibaca.'));
    img.src = params.imageDataUrl;
  });

  const geminiKey = await getOwnerGeminiKey();
  let validBubbles: Array<{ id?: number; box_2d: number[]; text: string }> = [];
  let usedModel = 'gemini-2.5-flash';

  if (geminiKey) {
    const visionPrompt =
      'Extract all visible text blocks or speech bubbles in reading order. ' +
      'Return strict JSON: {"bubbles":[{"id":1,"box_2d":[ymin,xmin,ymax,xmax],"text":"..."}]} ' +
      'with integer coordinates normalized 0..1000.';

    const resp = await fetch(
      'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent',
      {
        method: 'POST',
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
                { inlineData: { mimeType: imgDims.mime, data: imgDims.b64 } },
                { text: 'Detect all visible text regions.' },
              ],
            },
          ],
          generationConfig: { responseMimeType: 'application/json', temperature: 0.1 },
        }),
      }
    );
    if (!resp.ok) {
      throw new Error(`Gemini Vision mengembalikan status HTTP ${resp.status}.`);
    }
    const raw = await resp.json();
    const parsed = JSON.parse(raw?.candidates?.[0]?.content?.parts?.[0]?.text || '{}');
    const bubbles: Array<{ id?: number; box_2d?: number[]; text?: string }> = Array.isArray(
      parsed.bubbles
    )
      ? parsed.bubbles
      : [];
    validBubbles = bubbles
      .filter(
        (b): b is { id?: number; box_2d: number[]; text: string } =>
          typeof b.text === 'string' &&
          Boolean(b.text.trim()) &&
          Array.isArray(b.box_2d) &&
          b.box_2d.length === 4
      )
      .map((b) => ({ id: b.id, box_2d: b.box_2d, text: b.text.trim() }));
  } else {
    const DetectorCtor = (
      window as unknown as {
        TextDetector?: new () => {
          detect: (
            src: HTMLImageElement
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
        const detectedBoxes = await detector.detect(imgDims.imgEl);
        usedModel = 'browser-text-detector';
        validBubbles = detectedBoxes
          .filter((d) => typeof d.rawValue === 'string' && d.rawValue.trim() && d.boundingBox)
          .map((d, idx) => {
            const bb = d.boundingBox!;
            const ymin = Math.round((bb.y / imgDims.h) * 1000);
            const xmin = Math.round((bb.x / imgDims.w) * 1000);
            const ymax = Math.round(((bb.y + bb.height) / imgDims.h) * 1000);
            const xmax = Math.round(((bb.x + bb.width) / imgDims.w) * 1000);
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
      const { src } = parseModePair(params.mode);
      usedModel = 'tesseract-wasm-ocr';
      validBubbles = await runTesseractOcrBoxes(
        params.imageDataUrl,
        imgDims.w,
        imgDims.h,
        src
      );
    }

    if (validBubbles.length === 0) {
      throw new Error('Tidak ditemukan teks yang dapat dibaca pada gambar ini.');
    }
  }

  const { outputs, detectedSource } = validBubbles.length
    ? await translateParagraphsDirect({
        paragraphs: validBubbles.map((b) => b.text!.trim()),
        mode: params.mode,
        titleId: params.titleId,
      })
    : { outputs: [], detectedSource: 'ja' as TargetLang };

  const blocks: VisionBlock[] = validBubbles.map((b, idx) => {
    const [ymin, xmin, ymax, xmax] = b.box_2d!;
    const x = Math.max(0, Math.round((Math.min(xmin, xmax) / 1000) * imgDims.w));
    const y = Math.max(0, Math.round((Math.min(ymin, ymax) / 1000) * imgDims.h));
    const w = Math.max(24, Math.round((Math.abs(xmax - xmin) / 1000) * imgDims.w));
    const h = Math.max(20, Math.round((Math.abs(ymax - ymin) / 1000) * imgDims.h));
    return {
      id: idx + 1,
      box: [x, y, w, h],
      src: b.text!.trim(),
      dst: outputs[idx] || b.text!.trim(),
    };
  });

  const tid = params.titleId || 't_gambar';
  const mid = `img_${Date.now().toString(36)}`;
  const res: ImageTranslationResult = {
    width: imgDims.w,
    height: imgDims.h,
    blocks,
    fullSrc: blocks.map((b) => b.src).join('\n'),
    fullDst: blocks.map((b) => b.dst).join('\n'),
    model: usedModel,
    dataUrl: params.imageDataUrl,
  };

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

  return { cid: params.cid, mid, titleId: tid, ...res };
}
