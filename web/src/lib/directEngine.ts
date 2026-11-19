import type {
  GlossaryEntry,
  ImageTranslationResult,
  LinkPreviewPayload,
  ModePair,
  NameChipItem,
  SentencePair,
  SourceLang,
  TargetLang,
  VisionBlock,
} from '../types';
import {
  getOwnerGeminiKey,
  loadGlossaryEntriesOnce,
  saveDirectJobRecord,
  saveTurnMessageDirect,
  upsertConversationMeta,
} from './firebase';

const CJK_RE = /[\u3040-\u309f\u30a0-\u30ff\u3400-\u9fff]/;
const WORD_RE = /[A-Za-zÀ-ÿ']+/g;

const ID_WORDS = new Set([
  'yang', 'dan', 'di', 'ke', 'dari', 'ini', 'itu', 'untuk', 'dengan', 'tidak',
  'bisa', 'ada', 'saya', 'aku', 'kamu', 'kami', 'mereka', 'dalam', 'pada',
  'adalah', 'sudah', 'akan', 'atau', 'karena', 'seperti', 'juga', 'oleh',
  'tentang', 'lebih', 'sangat', 'hanya', 'telah', 'dapat', 'selamat', 'pagi',
  'malam', 'siang', 'terima', 'kasih', 'bagaimana', 'mengapa', 'kapan', 'dimana',
]);

const EN_WORDS = new Set([
  'the', 'and', 'to', 'of', 'in', 'is', 'it', 'you', 'that', 'for', 'with',
  'on', 'are', 'this', 'have', 'from', 'not', 'but', 'what', 'all', 'were',
  'when', 'we', 'your', 'can', 'their', 'would', 'there', 'been', 'has',
  'more', 'who', 'will', 'about', 'into', 'than', 'hello', 'good', 'morning',
]);

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

  const words = (sample.slice(0, 4000).match(WORD_RE) || []).map((w) => w.toLowerCase());
  if (words.length === 0) return fallback;

  let idScore = 0;
  let enScore = 0;
  for (const w of words) {
    if (ID_WORDS.has(w)) idScore += 1;
    if (EN_WORDS.has(w)) enScore += 1;
    if (
      w.length >= 5 &&
      (w.endsWith('nya') ||
        w.endsWith('kan') ||
        w.startsWith('meny') ||
        w.startsWith('meng') ||
        w.startsWith('ber'))
    ) {
      idScore += 0.6;
    }
  }
  if (idScore > enScore) return 'id';
  if (enScore > idScore) return 'en';
  return fallback === 'id' ? 'en' : 'id';
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
    out = out.replace(new RegExp(`\\[\\[\\s*E\\s*${num}\\s*\\]\\]`, 'gi'), val);
  }
  return out;
}

async function translateViaGoogleGtx(
  text: string,
  src: SourceLang,
  tgt: TargetLang,
  signal?: AbortSignal
): Promise<{ translated: string; detected: TargetLang }> {
  const clean = text.trim();
  if (!clean) return { translated: '', detected: src === 'auto' ? 'ja' : src };

  // Split long inputs safely into <= 1350-char chunks along paragraph/sentence boundaries
  const chunks: string[] = [];
  let cursor = '';
  for (const part of clean.split(/(\n+)/)) {
    if ((cursor + part).length > 1350 && cursor) {
      chunks.push(cursor);
      cursor = part;
    } else {
      cursor += part;
    }
  }
  if (cursor) chunks.push(cursor);

  const translatedChunks: string[] = [];
  let detected: TargetLang =
    src === 'auto'
      ? detectLanguageLocal(clean, tgt === 'ja' ? 'id' : 'ja')
      : src;

  for (const chunk of chunks) {
    if (!chunk.trim()) {
      translatedChunks.push(chunk);
      continue;
    }
    const qs = new URLSearchParams({
      client: 'gtx',
      sl: src,
      tl: tgt,
      dt: 't',
      q: chunk,
    });
    const resp = await fetch(
      `https://translate.googleapis.com/translate_a/single?${qs.toString()}`,
      { method: 'GET', signal }
    );
    if (!resp.ok) {
      throw new Error(`Layanan terjemahan mengembalikan status ${resp.status}.`);
    }
    const data = await resp.json();
    const pieces: string[] = Array.isArray(data?.[0])
      ? data[0]
          .map((seg: unknown) => (Array.isArray(seg) && typeof seg[0] === 'string' ? seg[0] : ''))
          .filter(Boolean)
      : [];
    const serverSrc = String(data?.[2] || '').toLowerCase();
    if (serverSrc === 'ja' || serverSrc === 'id' || serverSrc === 'en') {
      detected = serverSrc;
    }
    translatedChunks.push(pieces.join(''));
  }

  return { translated: translatedChunks.join(''), detected };
}

async function translateViaGeminiDirect(
  paragraphs: string[],
  src: TargetLang,
  tgt: TargetLang,
  geminiKey: string,
  signal?: AbortSignal
): Promise<string[]> {
  const langNames: Record<TargetLang, string> = {
    ja: 'Japanese',
    id: 'Indonesian',
    en: 'English',
  };
  const items = paragraphs.map((text, idx) => ({ id: idx + 1, text }));
  const sysPrompt =
    `You translate from ${langNames[src]} to ${langNames[tgt]} naturally, accurately, and faithfully without summarizing. ` +
    `Keep placeholders like [[E1]] verbatim. Preserve line breaks. ` +
    `Return strict JSON: {"translations":[{"id":1,"text":"..."}]}`;

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
  return paragraphs.map((orig, idx) => map.get(idx + 1) || orig);
}

export async function translateParagraphsDirect(params: {
  paragraphs: string[];
  mode: ModePair;
  titleId?: string;
  signal?: AbortSignal;
}): Promise<{
  outputs: string[];
  detectedSource: TargetLang;
  model: string;
  matchedChips: NameChipItem[];
}> {
  const { src, tgt } = parseModePair(params.mode);
  const combinedSample = params.paragraphs.slice(0, 5).join('\n');
  let detectedSource: TargetLang =
    src === 'auto'
      ? detectLanguageLocal(combinedSample, tgt === 'ja' ? 'id' : 'ja')
      : src;

  if (detectedSource === tgt && src !== 'auto') {
    return {
      outputs: [...params.paragraphs],
      detectedSource,
      model: 'direct',
      matchedChips: [],
    };
  }

  const glossary = await loadGlossaryEntriesOnce(params.titleId);
  const pairs = buildGlossaryPairs(glossary, detectedSource, tgt);
  const maskedList = params.paragraphs.map((p) => maskWithGlossary(p, pairs));

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
        dst: tgt === 'ja' ? entry.surface : tgt === 'en' ? entry.render_en || entry.romaji : entry.render_id || entry.romaji,
        kind: entry.kind,
        confirmed: true,
        source: entry.source,
      });
    }
  }

  const geminiKey = await getOwnerGeminiKey();
  if (geminiKey && detectedSource !== tgt) {
    try {
      const rawOut = await translateViaGeminiDirect(
        maskedList.map((m) => m.masked),
        detectedSource,
        tgt,
        geminiKey,
        params.signal
      );
      return {
        outputs: rawOut.map((r, i) => unmaskWithGlossary(r, maskedList[i].map)),
        detectedSource,
        model: 'gemini-2.5-flash-lite',
        matchedChips,
      };
    } catch {
      // Fall through to Google GTX if Gemini key quota or network fails
    }
  }

  const outputs: string[] = [];
  for (let i = 0; i < maskedList.length; i += 1) {
    const item = maskedList[i];
    const res = await translateViaGoogleGtx(item.masked, src, tgt, params.signal);
    if (i === 0) detectedSource = res.detected;
    outputs.push(unmaskWithGlossary(res.translated, item.map));
  }

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
  titleSrc: string;
  srcParas: string[];
  detectedSource: TargetLang;
}

const webArticleCache = new Map<string, CachedWebEntry>();

function cleanReaderMarkdownToParagraphs(md: string): string[] {
  const lines = md.split(/\r?\n/);
  const paras: string[] = [];
  let buf: string[] = [];

  const flush = () => {
    if (!buf.length) return;
    const joined = buf.join(' ').replace(/\s+/g, ' ').trim();
    buf = [];
    if (joined.length >= 2) paras.push(joined);
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flush();
      continue;
    }
    // Skip Jina metadata header lines and bare image markdown lines
    if (/^(Title|URL Source|Published Time|Markdown Content):/i.test(line)) continue;
    if (/^!\[[^\]]*\]\([^)]+\)$/.test(line)) continue;

    // Strip markdown links [label](url) -> label while keeping clean headings
    const cleaned = line
      .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .trim();
    if (!cleaned) continue;

    if (/^#{1,6}\s+/.test(cleaned)) {
      flush();
      paras.push(cleaned);
    } else {
      buf.push(cleaned);
    }
  }
  flush();
  return paras.slice(0, 140);
}

async function fetchWebArticleDirect(rawUrl: string): Promise<CachedWebEntry> {
  const cleanUrl = normalizeWebUrl(rawUrl);
  const cached = webArticleCache.get(cleanUrl);
  if (cached) return cached;

  const host = new URL(cleanUrl).hostname;
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 22000);

  try {
    const resp = await fetch(`https://r.jina.ai/${cleanUrl}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: ctrl.signal,
    });
    if (!resp.ok) {
      throw new Error(
        `Halaman ${host} menolak pembacaan otomatis (HTTP ${resp.status}). Gunakan tombol Buka situs asli.`
      );
    }
    const ctype = resp.headers.get('content-type') || '';
    let titleSrc = host;
    let contentText = '';
    let finalUrl = cleanUrl;

    if (ctype.includes('application/json')) {
      const json = await resp.json();
      const d = json?.data || {};
      titleSrc = String(d.title || host).trim() || host;
      contentText = String(d.content || d.description || '').trim();
      if (typeof d.url === 'string' && d.url.startsWith('http')) {
        finalUrl = d.url;
      }
    } else {
      const rawTxt = await resp.text();
      const titleMatch = rawTxt.match(/^Title:\s*(.+)$/m);
      if (titleMatch) titleSrc = titleMatch[1].trim();
      contentText = rawTxt;
    }

    const srcParas = cleanReaderMarkdownToParagraphs(contentText);
    if (srcParas.length === 0) {
      throw new Error(
        `Tidak ditemukan paragraf teks yang dapat dibaca pada ${host}. Halaman mungkin memerlukan login.`
      );
    }
    const detectedSource = detectLanguageLocal(
      `${titleSrc}\n${srcParas.slice(0, 6).join('\n')}`,
      'ja'
    );
    const entry: CachedWebEntry = {
      url: finalUrl,
      host,
      titleSrc,
      srcParas,
      detectedSource,
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

export async function directPreviewLink(params: {
  cid: string;
  url: string;
  mode: ModePair;
  titleId?: string;
}): Promise<LinkPreviewPayload> {
  const article = await fetchWebArticleDirect(params.url);
  const tid = params.titleId || `t_web_${article.host.replace(/[^a-z0-9]/gi, '_').slice(0, 24)}`;
  const mid = `lnk_${Date.now().toString(36)}`;

  const sampleInputs = [article.titleSrc, ...article.srcParas.slice(0, 3)];
  const { outputs, detectedSource, matchedChips } = await translateParagraphsDirect({
    paragraphs: sampleInputs,
    mode: params.mode,
    titleId: tid,
  });

  const titleDst = outputs[0]?.replace(/^#{1,6}\s+/, '') || article.titleSrc;
  const excerptSrc = article.srcParas
    .slice(0, 2)
    .map((s) => s.replace(/^#{1,6}\s+/, ''))
    .join(' ')
    .slice(0, 260);
  const excerptDst = outputs
    .slice(1)
    .map((s) => s.replace(/^#{1,6}\s+/, ''))
    .join(' ')
    .slice(0, 280);

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
    paragraphCount: article.srcParas.length,
    lockedNames: matchedChips.length,
    readerSupported: true,
  };

  await upsertConversationMeta(params.cid, {
    title: titleDst,
    titleId: tid,
    mode: params.mode,
    detectedSource,
    activeTab: 'link',
    preview: excerptDst || titleDst,
  });
  await saveTurnMessageDirect(params.cid, mid, {
    role: 'assistant',
    kind: 'link',
    mode: params.mode,
    detectedSource,
    titleId: tid,
    text: excerptDst,
    linkPreview: preview,
    state: 'done',
  });

  return preview;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export async function directFetchTranslatedWebHtml(params: {
  url: string;
  mode: ModePair;
  titleId?: string;
  view: 'translated' | 'original';
}): Promise<string> {
  const article = await fetchWebArticleDirect(params.url);
  const { tgt } = parseModePair(params.mode);
  const isJpBody = params.view === 'original' ? article.detectedSource === 'ja' : tgt === 'ja';
  const fontStack = isJpBody
    ? '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif'
    : 'Charter, Georgia, Cambria, serif';

  let headingText = article.titleSrc;
  let bodyParas = article.srcParas;

  if (params.view === 'translated') {
    const batch = [article.titleSrc, ...article.srcParas.slice(0, 60)];
    const { outputs } = await translateParagraphsDirect({
      paragraphs: batch,
      mode: params.mode,
      titleId: params.titleId,
    });
    headingText = outputs[0] || article.titleSrc;
    bodyParas = outputs.slice(1);
  }

  const renderedParas = bodyParas
    .map((p) => {
      if (/^#{1,3}\s+/.test(p)) {
        return `<h2>${escapeHtml(p.replace(/^#{1,6}\s+/, ''))}</h2>`;
      }
      if (/^#{4,6}\s+/.test(p)) {
        return `<h3>${escapeHtml(p.replace(/^#{1,6}\s+/, ''))}</h3>`;
      }
      return `<p>${escapeHtml(p)}</p>`;
    })
    .join('\n');

  return `<!doctype html>
<html lang="${tgt}">
<head>
<meta charset="utf-8">
<title>${escapeHtml(headingText)}</title>
<style>
  :root { color-scheme: light dark; }
  body {
    margin: 0;
    padding: 28px 20px 72px;
    background: #FAFBFA;
    color: #141917;
    font-family: ${fontStack};
    font-size: 18px;
    line-height: 1.75;
  }
  @media (prefers-color-scheme: dark) {
    body { background: #171B1A; color: #E7ECEA; }
    header { border-bottom-color: #2B3230 !important; }
    .meta { color: #A5AEAA !important; }
  }
  article { max-width: 700px; margin: 0 auto; }
  header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #DEE3E0; }
  h1 { font-size: 26px; line-height: 1.3; margin: 0 0 8px 0; }
  h2 { font-size: 21px; line-height: 1.4; margin: 28px 0 10px 0; }
  h3 { font-size: 18px; line-height: 1.45; margin: 22px 0 8px 0; }
  p { margin: 0 0 16px 0; }
  .meta { font-family: Inter, -apple-system, sans-serif; font-size: 13px; color: #4F5855; }
</style>
</head>
<body>
  <article>
    <header>
      <div class="meta">${escapeHtml(article.host)}</div>
      <h1>${escapeHtml(headingText.replace(/^#{1,6}\s+/, ''))}</h1>
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

async function extractPdfUnitsViaGemini(
  buffer: ArrayBuffer,
  geminiKey: string
): Promise<ParsedDocUnit[]> {
  if (buffer.byteLength > 18 * 1024 * 1024) {
    throw new Error('PDF pindaian untuk ekstraksi multimodal dibatasi maksimal 18 MB.');
  }
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  const b64 = btoa(binary);
  const resp = await fetch(
    'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-goog-api-key': geminiKey },
      body: JSON.stringify({
        contents: [
          {
            role: 'user',
            parts: [
              { inlineData: { mimeType: 'application/pdf', data: b64 } },
              {
                text: 'Extract all readable paragraphs from this PDF in reading order. Return strict JSON: {"paragraphs":["..."]}',
              },
            ],
          },
        ],
        generationConfig: { responseMimeType: 'application/json', temperature: 0.1 },
      }),
    }
  );
  if (!resp.ok) {
    throw new Error(`Ekstraksi PDF Gemini mengembalikan status HTTP ${resp.status}.`);
  }
  const data = await resp.json();
  const parsed = JSON.parse(data?.candidates?.[0]?.content?.parts?.[0]?.text || '{}');
  const paras: unknown[] = Array.isArray(parsed.paragraphs) ? parsed.paragraphs : [];
  return paras
    .map((p) => String(p || '').trim())
    .filter(Boolean)
    .map((text) => ({ text }));
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

async function parseDocumentUnitsInBrowser(file: File): Promise<{
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
    const nativeUnits = await extractPdfUnitsNative(fullBuf);
    if (nativeUnits.length > 0) {
      return { fmt: 'pdf', units: nativeUnits };
    }
    const geminiKey = await getOwnerGeminiKey();
    if (geminiKey) {
      const ocrUnits = await extractPdfUnitsViaGemini(fullBuf, geminiKey);
      if (ocrUnits.length > 0) {
        return { fmt: 'pdf', units: ocrUnits };
      }
    }
    throw new Error(
      'PDF ini berisi hasil pindaian gambar tanpa lapisan teks. Simpan kunci API Gemini di Setelan -> Lanjutan untuk mengekstrak teks pindaian secara otomatis.'
    );
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
  const { fmt, headerDoc, units } = await parseDocumentUnitsInBrowser(params.file);
  if (units.length === 0) {
    throw new Error('Berkas tidak memiliki teks yang dapat diterjemahkan.');
  }

  const cappedUnits = units.slice(0, 200);
  await upsertConversationMeta(params.cid, {
    title: params.file.name,
    titleId: params.titleId || '',
    mode: params.mode,
    activeTab: 'dokumen',
    preview: params.file.name,
  });

  await saveDirectJobRecord({
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
  });

  await saveTurnMessageDirect(params.cid, params.mid, {
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
  });

  const translatedRows: Array<{ prefix?: string; src: string; dst: string }> = [];
  const batchSize = 10;
  let detected: TargetLang = 'ja';

  for (let i = 0; i < cappedUnits.length; i += batchSize) {
    const slice = cappedUnits.slice(i, i + batchSize);
    const { outputs, detectedSource } = await translateParagraphsDirect({
      paragraphs: slice.map((u) => u.text),
      mode: params.mode,
      titleId: params.titleId,
    });
    if (i === 0) detected = detectedSource;
    slice.forEach((u, idx) => {
      translatedRows.push({
        prefix: u.prefix,
        src: u.text,
        dst: outputs[idx] || u.text,
      });
    });
    const pct = Math.round((translatedRows.length / cappedUnits.length) * 100);
    params.onProgress?.(pct);
  }

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

  await saveDirectJobRecord({
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
  });

  await saveTurnMessageDirect(params.cid, params.mid, {
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
  });

  await upsertConversationMeta(params.cid, {
    title: params.file.name,
    titleId: params.titleId || '',
    mode: params.mode,
    detectedSource: detected,
    activeTab: 'dokumen',
    preview: fullDst.slice(0, 180),
  });

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
    if (!DetectorCtor) {
      throw new Error(
        'Untuk menerjemahkan teks pada gambar secara langsung, simpan kunci API Gemini Anda di Setelan -> Lanjutan.'
      );
    }
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
      throw new Error(
        'Untuk menerjemahkan teks pada gambar secara langsung, simpan kunci API Gemini Anda di Setelan -> Lanjutan.'
      );
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

  await upsertConversationMeta(params.cid, {
    title: params.fileName,
    titleId: tid,
    mode: params.mode,
    detectedSource,
    activeTab: 'gambar',
    preview: res.fullDst.slice(0, 180) || params.fileName,
  });
  await saveTurnMessageDirect(params.cid, mid, {
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
  });

  return { cid: params.cid, mid, titleId: tid, ...res };
}
