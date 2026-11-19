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
      out.set(name, decoder.decode(rawSlice));
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
      out.set(name, decoder.decode(merged));
    }
  }
  return out;
}

interface ParsedDocUnit {
  prefix?: string; // e.g. SRT index + timestamp lines
  text: string;
}

async function parseDocumentUnitsInBrowser(file: File): Promise<{
  fmt: string;
  units: ParsedDocUnit[];
}> {
  const ext = (file.name.split('.').pop() || 'txt').toLowerCase();

  if (ext === 'docx') {
    const entries = await extractZipTextEntries(
      await file.arrayBuffer(),
      (n) => n === 'word/document.xml'
    );
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
      await file.arrayBuffer(),
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
    throw new Error(
      'Ekstraksi berkas PDF biner memerlukan Cloud Functions aktif (paket Blaze). Untuk saat ini unggah .docx, .epub, .srt, .vtt, .html, .md, atau .txt.'
    );
  }

  const rawText = await file.text();
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
  { fileName: string; fmt: string; units: Array<{ prefix?: string; src: string; dst: string }> }
>();

export async function directTranslateDocumentFile(params: {
  cid: string;
  mid: string;
  mode: ModePair;
  titleId?: string;
  file: File;
  onProgress?: (pct: number) => void;
}): Promise<string> {
  const jobId = `job_${Date.now().toString(36)}`;
  const { fmt, units } = await parseDocumentUnitsInBrowser(params.file);
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

  const ext = params.fmt.toLowerCase() === 'docx' ? 'html' : params.fmt.toLowerCase();
  const baseStem = (cached?.fileName || `tranx-${params.mid}`).replace(/\.[^.]+$/, '');

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
  const geminiKey = await getOwnerGeminiKey();
  if (!geminiKey) {
    throw new Error(
      'Untuk menerjemahkan teks pada gambar secara langsung, simpan kunci API Gemini Anda di Setelan -> Lanjutan.'
    );
  }

  const imgDims = await new Promise<{ w: number; h: number; mime: string; b64: string }>(
    (resolve, reject) => {
      const [header, b64] = params.imageDataUrl.split(',', 2);
      const mimeMatch = header.match(/data:([^;]+)/);
      const img = new Image();
      img.onload = () =>
        resolve({
          w: img.naturalWidth || 640,
          h: img.naturalHeight || 480,
          mime: mimeMatch ? mimeMatch[1] : 'image/png',
          b64: b64 || '',
        });
      img.onerror = () => reject(new Error('Berkas gambar tidak dapat dibaca.'));
      img.src = params.imageDataUrl;
    }
  );

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

  const validBubbles = bubbles.filter(
    (b) => typeof b.text === 'string' && b.text.trim() && Array.isArray(b.box_2d) && b.box_2d.length === 4
  );

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
    model: 'gemini-2.5-flash',
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
    model: 'gemini-2.5-flash',
  });

  return { cid: params.cid, mid, titleId: tid, ...res };
}
