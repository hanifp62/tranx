import {
  deleteConversationDirect,
  exportFullBackupDirect,
  getE2EStore,
  getOwnerGeminiKey,
  isLocalE2EMode,
  loadTurnMessageOnce,
  mergeTitleGlossariesDirect,
  saveTurnMessageDirect,
  setOwnerGeminiKey,
  uploadDocumentToCloudStorage,
  upsertConversationMeta,
  type AuthSessionUser,
} from './firebase';
import {
  buildDirectExportBlob,
  classifyParagraphLanguage,
  deriveSeriesTitleId,
  detectLanguageLocal,
  directFetchTranslatedWebHtml,
  directFetchWebReaderBundle,
  directPreviewLink,
  directTranslateDocumentFile,
  directTranslateImage,
  normalizeWebUrl,
  parseModePair,
  translateParagraphsDirect,
} from './directEngine';
import type {
  ImageTranslationResult,
  LinkPreviewPayload,
  ModePair,
  NameChipItem,
  SentencePair,
  TargetLang,
  WebReaderBundle,
} from '../types';

export function getApiBaseUrl(): string {
  const custom =
    typeof window !== 'undefined'
      ? window.localStorage.getItem('tranx_api_base') || ''
      : '';
  if (custom.trim()) return custom.trim().replace(/\/+$/, '');
  const envUrl = (import.meta.env.VITE_API_BASE_URL || '').trim();
  if (envUrl) return envUrl.replace(/\/+$/, '');
  return '';
}

async function authHeaders(user: AuthSessionUser | null): Promise<Record<string, string>> {
  if (!user) return {};
  const token = await user.getIdToken();
  return { Authorization: `Bearer ${token}` };
}

export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function humanizeFetchError(err: unknown, fallbackMsg: string): string {
  if (err instanceof ApiClientError) return err.message;
  if (err instanceof Error) {
    if (/failed to fetch|networkerror|load failed/i.test(err.message)) {
      return fallbackMsg;
    }
    return err.message;
  }
  return fallbackMsg;
}

if (
  typeof window !== 'undefined' &&
  new URLSearchParams(window.location.search).get('direct') === '1'
) {
  window.sessionStorage.setItem('tranx_e2e_direct', '1');
}

function isDirectE2ETest(): boolean {
  if (typeof window === 'undefined') return false;
  if (new URLSearchParams(window.location.search).get('direct') === '1') {
    window.sessionStorage.setItem('tranx_e2e_direct', '1');
    return true;
  }
  return window.sessionStorage.getItem('tranx_e2e_direct') === '1';
}

/* Fast cached probe so Spark deployments don't wait on unprovisioned Cloud Functions */
let cloudReachableState: { ok: boolean; checkedAt: number } | null = null;

async function isCloudBackendAvailable(): Promise<boolean> {
  if (isLocalE2EMode() && !isDirectE2ETest()) return false;
  const base = getApiBaseUrl();
  if (cloudReachableState && Date.now() - cloudReachableState.checkedAt < 120000) {
    return cloudReachableState.ok;
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 2200);
  try {
    const r = await fetch(`${base}/v1/healthz`, { method: 'GET', signal: ctrl.signal });
    const ctype = (r.headers.get('content-type') || '').toLowerCase();
    const ok = r.status === 204 || (r.ok && !ctype.includes('text/html'));
    cloudReachableState = { ok, checkedAt: Date.now() };
    return ok;
  } catch {
    cloudReachableState = { ok: false, checkedAt: Date.now() };
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

async function parseErrorResponse(resp: Response): Promise<ApiClientError> {
  try {
    const data = await resp.json();
    const code = data?.error?.code || `HTTP_${resp.status}`;
    const msg = data?.error?.message || resp.statusText || 'Permintaan gagal diproses.';
    return new ApiClientError(resp.status, code, msg);
  } catch {
    return new ApiClientError(
      resp.status,
      `HTTP_${resp.status}`,
      resp.statusText || 'Layanan terjemahan belum terjangkau.'
    );
  }
}

export interface StreamEvent {
  type: 'meta' | 'delta' | 'seg' | 'para' | 'done' | 'error';
  cid?: string;
  mid?: string;
  titleId?: string;
  detectedSource?: TargetLang;
  i?: number;
  src?: string;
  dst?: string;
  fullDst?: string;
  sentences?: SentencePair[];
  model?: string;
  ms?: number;
  doneParas?: number;
  totalParas?: number;
  state?: string;
  code?: string;
  message?: string;
}

async function consumeNdjson(
  resp: Response,
  onEvent: (ev: StreamEvent) => void
): Promise<void> {
  if (!resp.body) throw new ApiClientError(500, 'EMPTY_STREAM', 'Aliran respons kosong.');
  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx = buffer.indexOf('\n');
    while (idx >= 0) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (line) {
        onEvent(JSON.parse(line) as StreamEvent);
      }
      idx = buffer.indexOf('\n');
    }
  }
  const tail = buffer.trim();
  if (tail) onEvent(JSON.parse(tail) as StreamEvent);
}

export async function streamChatTurn(params: {
  user: AuthSessionUser;
  cid: string;
  clientMsgId: string;
  mode: ModePair;
  text: string;
  titleId?: string;
  inboxId?: string;
  signal?: AbortSignal;
  onEvent: (ev: StreamEvent) => void;
}): Promise<void> {
  if (isLocalE2EMode() && !isDirectE2ETest()) {
    const store = getE2EStore();
    const tid = params.titleId || 't_rashomon';
    const asstMid = `${params.clientMsgId}_r`;
    const { src, tgt } = parseModePair(params.mode);
    const detected: TargetLang =
      src === 'auto'
        ? detectLanguageLocal(params.text, tgt === 'ja' ? 'id' : 'ja')
        : src;
    const paraCls = classifyParagraphLanguage(params.text);
    const dst =
      paraCls === tgt
        ? params.text
        : tgt === 'ja'
          ? '千早は軒下で静かに微笑んだ。'
          : tgt === 'en'
            ? 'Chihaya smiled quietly beneath the eaves.'
            : 'Chihaya tersenyum tenang di bawah atap.';
    const now = Date.now();
    const bucket = store.messages.get(params.cid) ?? new Map();
    bucket.set(params.clientMsgId, {
      id: params.clientMsgId,
      role: 'user',
      kind: 'text',
      mode: params.mode,
      detectedSource: detected,
      titleId: tid,
      text: params.text,
      state: 'done',
      createdAt: now,
    });
    params.onEvent({
      type: 'meta',
      cid: params.cid,
      mid: asstMid,
      titleId: tid,
      detectedSource: detected,
    });
    params.onEvent({ type: 'delta', i: 0, src: params.text, dst });
    params.onEvent({
      type: 'done',
      cid: params.cid,
      mid: asstMid,
      titleId: tid,
      detectedSource: detected,
      fullDst: dst,
      sentences: [{ i: 0, src: params.text, dst }],
      model: 'gemini-2.5-flash-lite',
      ms: 190,
    });
    bucket.set(asstMid, {
      id: asstMid,
      role: 'assistant',
      kind: 'text',
      mode: params.mode,
      detectedSource: detected,
      titleId: tid,
      srcText: params.text,
      text: dst,
      sentences: [{ i: 0, src: params.text, dst }],
      nameChips:
        params.text.includes('千早') || params.text.includes('Chihaya')
          ? [
              {
                surface: '千早',
                reading: 'ちはや',
                romaji: 'Chihaya',
                dst: tgt === 'ja' ? '千早' : 'Chihaya',
                kind: 'PERSON',
                confirmed: true,
                source: 'user',
              },
            ]
          : [],
      state: 'done',
      model: 'gemini-2.5-flash-lite',
      ms: 190,
      createdAt: now + 1,
    });
    store.messages.set(params.cid, bucket);
    await upsertConversationMeta(params.cid, {
      title: params.text.split('\n')[0].slice(0, 80) || 'Percakapan',
      titleId: tid,
      mode: params.mode,
      detectedSource: detected,
      activeTab: 'teks',
      preview: dst,
    });
    if (params.inboxId) store.inbox.delete(params.inboxId);
    store.emit();
    return;
  }

  if (await isCloudBackendAvailable()) {
    try {
      const endpoint =
        params.text.length > 5000
          ? `${getApiBaseUrl()}/v1/translate`
          : `${getApiBaseUrl()}/v1/chat`;
      const body =
        params.text.length > 5000
          ? {
              cid: params.cid,
              clientMsgId: params.clientMsgId,
              mode: params.mode,
              titleId: params.titleId,
              source: { text: params.text },
            }
          : {
              cid: params.cid,
              clientMsgId: params.clientMsgId,
              mode: params.mode,
              titleId: params.titleId,
              inboxId: params.inboxId,
              text: params.text,
            };

      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(await authHeaders(params.user)),
        },
        body: JSON.stringify(body),
        signal: params.signal,
      });
      if (resp.ok) {
        await consumeNdjson(resp, params.onEvent);
        return;
      }
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') throw err;
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    }
  }

  /* Direct Browser Translation + Real Cloud Firestore Sync */
  const t0 = performance.now();
  const tid = params.titleId || `t_${params.cid}`;
  const asstMid = `${params.clientMsgId}_r`;
  const paras = params.text
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);

  const firstLine = (paras[0] || params.text).split('\n')[0].slice(0, 80) || 'Percakapan';
  await upsertConversationMeta(params.cid, {
    title: firstLine,
    titleId: tid,
    mode: params.mode,
    activeTab: 'teks',
    preview: firstLine,
  });
  await saveTurnMessageDirect(params.cid, params.clientMsgId, {
    role: 'user',
    kind: 'text',
    mode: params.mode,
    titleId: tid,
    text: params.text,
    state: 'done',
  });

  const { outputs, detectedSource, model, matchedChips } = await translateParagraphsDirect({
    paragraphs: paras.length ? paras : [params.text],
    mode: params.mode,
    titleId: tid,
    signal: params.signal,
  });

  const fullDst = outputs.join('\n\n');
  const sentences: SentencePair[] = outputs.map((dst, i) => ({
    i,
    src: paras[i] || params.text,
    dst,
  }));
  const elapsed = Math.round(performance.now() - t0);

  params.onEvent({
    type: 'meta',
    cid: params.cid,
    mid: asstMid,
    titleId: tid,
    detectedSource,
  });
  params.onEvent({
    type: 'done',
    cid: params.cid,
    mid: asstMid,
    titleId: tid,
    detectedSource,
    fullDst,
    sentences,
    model,
    ms: elapsed,
  });

  await saveTurnMessageDirect(params.cid, asstMid, {
    role: 'assistant',
    kind: params.text.length > 5000 ? 'long' : 'text',
    mode: params.mode,
    detectedSource,
    titleId: tid,
    srcText: params.text,
    text: fullDst,
    sentences,
    nameChips: matchedChips,
    state: 'done',
    model,
    ms: elapsed,
  });
  await upsertConversationMeta(params.cid, {
    title: firstLine,
    titleId: tid,
    mode: params.mode,
    detectedSource,
    activeTab: 'teks',
    preview: fullDst.slice(0, 180) || firstLine,
  });
}

export async function lookupTurnNames(params: {
  user: AuthSessionUser;
  cid: string;
  mid: string;
  titleId?: string;
  text?: string;
  mode: ModePair;
}): Promise<{ titleId: string; entries: NameChipItem[] }> {
  if (isLocalE2EMode()) {
    return {
      titleId: params.titleId || 't_rashomon',
      entries: (params.text || '').includes('千早')
        ? [
            {
              surface: '千早',
              reading: 'ちはや',
              romaji: 'Chihaya',
              dst: 'Chihaya',
              kind: 'PERSON',
              confirmed: true,
              source: 'user',
            },
          ]
        : [],
    };
  }
  if (!(await isCloudBackendAvailable())) {
    return { titleId: params.titleId || '', entries: [] };
  }
  try {
    const resp = await fetch(`${getApiBaseUrl()}/v1/names:lookup`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(await authHeaders(params.user)),
      },
      body: JSON.stringify(params),
    });
    if (!resp.ok) return { titleId: params.titleId || '', entries: [] };
    return resp.json();
  } catch {
    return { titleId: params.titleId || '', entries: [] };
  }
}

export async function translateImageRequest(params: {
  user: AuthSessionUser;
  cid: string;
  mode: ModePair;
  fileName: string;
  imageDataUrl: string;
  titleId?: string;
}): Promise<{ cid: string; mid: string; titleId: string } & ImageTranslationResult> {
  if (isLocalE2EMode() && !isDirectE2ETest()) {
    const store = getE2EStore();
    const mid = `img_${Date.now().toString(36)}`;
    const { tgt } = parseModePair(params.mode);
    const dstText =
      tgt === 'ja'
        ? '千早は静かに微笑んだ。'
        : tgt === 'en'
          ? 'Chihaya smiled quietly.'
          : 'Chihaya tersenyum kecil.';
    const res: ImageTranslationResult = {
      width: 640,
      height: 480,
      blocks: [
        {
          id: 1,
          box: [60, 50, 280, 96],
          src: '「千早は小さく笑った。」',
          dst: dstText,
        },
      ],
      fullSrc: '「千早は小さく笑った。」',
      fullDst: dstText,
      model: 'gemini-2.5-flash',
      dataUrl: params.imageDataUrl,
    };
    const bucket = store.messages.get(params.cid) ?? new Map();
    bucket.set(mid, {
      id: mid,
      role: 'assistant',
      kind: 'image',
      mode: params.mode,
      detectedSource: 'ja',
      titleId: 't_rashomon',
      fileName: params.fileName,
      text: res.fullDst,
      imageResult: res,
      state: 'done',
      createdAt: Date.now(),
    });
    store.messages.set(params.cid, bucket);
    await upsertConversationMeta(params.cid, {
      title: params.fileName,
      titleId: 't_rashomon',
      mode: params.mode,
      detectedSource: 'ja',
      activeTab: 'gambar',
      preview: res.fullDst,
    });
    store.emit();
    return { cid: params.cid, mid, titleId: 't_rashomon', ...res };
  }

  if (await isCloudBackendAvailable()) {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/v1/image:translate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(await authHeaders(params.user)),
        },
        body: JSON.stringify({
          cid: params.cid,
          mode: params.mode,
          fileName: params.fileName,
          imageB64: params.imageDataUrl,
          titleId: params.titleId,
        }),
      });
      if (resp.ok) return resp.json();
    } catch {
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    }
  }

  return directTranslateImage({
    cid: params.cid,
    mode: params.mode,
    fileName: params.fileName,
    imageDataUrl: params.imageDataUrl,
    titleId: params.titleId,
  });
}

export async function processDocumentSubmission(params: {
  uid: string;
  cid: string;
  mid: string;
  mode: ModePair;
  titleId?: string;
  file: File;
  onProgress?: (pct: number) => void;
}): Promise<string> {
  if (isLocalE2EMode() && !isDirectE2ETest()) {
    const store = getE2EStore();
    const jobId = `job_${Date.now().toString(36)}`;
    const now = Date.now();
    store.jobs.set(jobId, {
      id: jobId,
      cid: params.cid,
      mid: params.mid,
      titleId: params.titleId,
      fileName: params.file.name,
      fileSize: params.file.size,
      fmt: params.file.name.split('.').pop()?.toLowerCase() || 'txt',
      state: 'done',
      doneParas: 3,
      totalParas: 3,
      updatedAt: now,
    });
    const bucket = store.messages.get(params.cid) ?? new Map();
    bucket.set(params.mid, {
      id: params.mid,
      role: 'assistant',
      kind: 'document',
      mode: params.mode,
      detectedSource: 'ja',
      titleId: params.titleId || 't_rashomon',
      fileName: params.file.name,
      fmt: params.file.name.split('.').pop()?.toLowerCase() || 'txt',
      jobId,
      done: 3,
      total: 3,
      text: `Terjemahan dokumen ${params.file.name} selesai.`,
      sentences: [{ i: 0, src: '千早は走った。', dst: 'Chihaya berlari.' }],
      state: 'done',
      createdAt: now,
    });
    store.messages.set(params.cid, bucket);
    await upsertConversationMeta(params.cid, {
      title: params.file.name,
      titleId: params.titleId || 't_rashomon',
      mode: params.mode,
      detectedSource: 'ja',
      activeTab: 'dokumen',
      preview: params.file.name,
    });
    params.onProgress?.(100);
    store.emit();
    return jobId;
  }

  if (await isCloudBackendAvailable()) {
    try {
      return await uploadDocumentToCloudStorage(params);
    } catch {
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    }
  }

  return directTranslateDocumentFile({
    cid: params.cid,
    mid: params.mid,
    mode: params.mode,
    titleId: params.titleId,
    file: params.file,
    onProgress: params.onProgress,
  });
}

export async function previewLinkRequest(params: {
  user: AuthSessionUser;
  cid: string;
  url: string;
  mode: ModePair;
  titleId?: string;
}): Promise<LinkPreviewPayload> {
  const cleanUrl = normalizeWebUrl(params.url);

  if (isLocalE2EMode() && !isDirectE2ETest()) {
    const store = getE2EStore();
    const mid = `lnk_${Date.now().toString(36)}`;
    const host = new URL(cleanUrl).hostname;
    const { tgt } = parseModePair(params.mode);
    const isEp2 = cleanUrl.includes('/2') || cleanUrl.includes('episodes/2');
    const mockChapters = [
      {
        title: tgt === 'en' ? 'Chapter 1: Rain at Rashomon' : 'Bab 1: Hujan di Rashomon',
        url: 'https://www.aozora.gr.jp/cards/1.html',
        current: !isEp2,
      },
      {
        title: tgt === 'en' ? 'Chapter 2: Lanterns of Kyoto' : 'Bab 2: Lentera di Kyoto',
        url: 'https://www.aozora.gr.jp/cards/2.html',
        current: isEp2,
      },
    ];
    const preview: LinkPreviewPayload = {
      mid,
      cid: params.cid,
      titleId: deriveSeriesTitleId(cleanUrl) || 't_rashomon',
      url: cleanUrl,
      host,
      isAozora: host.includes('aozora'),
      titleSrc: isEp2 ? '第二章 京都の提灯' : '第一章 雨の羅生門',
      titleDst: isEp2
        ? tgt === 'ja'
          ? '第二章 京都の提灯'
          : tgt === 'en'
            ? 'Chapter 2: Lanterns of Kyoto'
            : 'Bab 2: Lentera di Kyoto'
        : tgt === 'ja'
          ? '第一章 雨の羅生門'
          : tgt === 'en'
            ? 'Chapter 1: Rain at Rashomon'
            : 'Bab 1: Hujan di Rashomon',
      excerptSrc: isEp2 ? '提灯の明かりが雨に揺れた。' : '千早は小さく笑った。',
      excerptDst: isEp2
        ? tgt === 'ja'
          ? '提灯の明かりが雨に揺れた。'
          : tgt === 'en'
            ? 'Lantern light swayed softly in the rain.'
            : 'Cahaya lentera bergoyang pelan di tengah hujan.'
        : tgt === 'ja'
          ? '千早は門の下で静かに微笑んだ。'
          : tgt === 'en'
            ? 'Chihaya smiled quietly under the gate.'
            : 'Chihaya tersenyum kecil di bawah gerbang.',
      paragraphCount: 12,
      lockedNames: 1,
      readerSupported: true,
      novelNav: {
        isNovel: true,
        seriesTitle: 'Rashomon',
        chapterLabel: isEp2 ? '2 / 2' : '1 / 2',
        prevUrl: isEp2 ? 'https://www.aozora.gr.jp/cards/1.html' : null,
        nextUrl: isEp2 ? null : 'https://www.aozora.gr.jp/cards/2.html',
        tocUrl: 'https://www.aozora.gr.jp/cards/1.html',
        chapters: mockChapters,
      },
    };
    const bucket = store.messages.get(params.cid) ?? new Map();
    bucket.set(mid, {
      id: mid,
      role: 'assistant',
      kind: 'link',
      mode: params.mode,
      detectedSource: 'ja',
      titleId: 't_rashomon',
      text: preview.excerptDst,
      linkPreview: preview,
      state: 'done',
      createdAt: Date.now(),
    });
    store.messages.set(params.cid, bucket);
    await upsertConversationMeta(params.cid, {
      title: preview.titleDst,
      titleId: 't_rashomon',
      mode: params.mode,
      detectedSource: 'ja',
      activeTab: 'link',
      preview: preview.excerptDst,
    });
    store.emit();
    return preview;
  }

  if (await isCloudBackendAvailable()) {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/v1/links:preview`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(await authHeaders(params.user)),
        },
        body: JSON.stringify({ ...params, url: cleanUrl }),
      });
      if (resp.ok) return resp.json();
      if (resp.status === 403 || resp.status === 422) {
        throw await parseErrorResponse(resp);
      }
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    } catch (err) {
      if (err instanceof ApiClientError) throw err;
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    }
  }

  try {
    return await directPreviewLink({
      cid: params.cid,
      url: cleanUrl,
      mode: params.mode,
      titleId: params.titleId,
    });
  } catch (err) {
    throw new Error(
      humanizeFetchError(
        err,
        'Halaman web ini menolak akses pembaca otomatis atau sedang tidak terjangkau. Gunakan tautan langsung atau salin isi artikelnya.'
      )
    );
  }
}

export async function fetchWebReaderBundle(params: {
  user: AuthSessionUser;
  url: string;
  mode: ModePair;
  titleId?: string;
  view: 'reader' | 'site' | 'original';
}): Promise<WebReaderBundle> {
  const cleanUrl = normalizeWebUrl(params.url);

  if (isLocalE2EMode() && !isDirectE2ETest()) {
    const { tgt } = parseModePair(params.mode);
    const host = new URL(cleanUrl).hostname;
    const isEp2 = cleanUrl.includes('/2') || cleanUrl.includes('episodes/2');
    const titleSrc = isEp2 ? '第二章 京都の提灯' : '第一章 雨の羅生門';
    const titleDst = isEp2
      ? tgt === 'ja'
        ? '第二章 京都の提灯'
        : tgt === 'en'
          ? 'Chapter 2: Lanterns of Kyoto'
          : 'Bab 2: Lentera di Kyoto'
      : tgt === 'ja'
        ? '第一章 雨の羅生門'
        : tgt === 'en'
          ? 'Chapter 1: Rain at Rashomon'
          : 'Bab 1: Hujan di Rashomon';
    const sentences: SentencePair[] = isEp2
      ? [
          {
            i: 0,
            src: '提灯の明かりが雨に揺れた。',
            dst:
              tgt === 'ja'
                ? '提灯の明かりが雨に揺れた。'
                : tgt === 'en'
                  ? 'Lantern light swayed softly in the rain.'
                  : 'Cahaya lentera bergoyang pelan di tengah hujan.',
          },
        ]
      : [
          {
            i: 0,
            src: '千早は小さく笑った。',
            dst:
              tgt === 'ja'
                ? '千早は静かに微笑んだ。'
                : tgt === 'en'
                  ? 'Chihaya smiled quietly.'
                  : 'Chihaya tersenyum kecil.',
          },
        ];
    const nextUrl = isEp2 ? null : 'https://www.aozora.gr.jp/cards/2.html';
    const prevUrl = isEp2 ? 'https://www.aozora.gr.jp/cards/1.html' : null;
    const origin = window.location.origin;
    const nextHref = nextUrl
      ? `${origin}/web?url=${encodeURIComponent(nextUrl)}&mode=${params.mode}&view=site`
      : '';
    const siteHtml =
      params.view === 'site'
        ? `<!doctype html><html lang="${tgt}"><head><meta charset="utf-8"><style>body{font-family:Charter,Georgia,serif;max-width:680px;margin:32px auto;padding:0 20px;line-height:1.75;color:#141917;background:#FAFBFA}</style></head><body><h1>${titleDst}</h1><p>${sentences[0].dst}</p>${
            nextHref
              ? `<p><a href="${nextHref}" target="_top" rel="noopener noreferrer">Bab berikutnya</a></p>`
              : ''
          }</body></html>`
        : undefined;
    return {
      url: cleanUrl,
      host,
      titleId: params.titleId || deriveSeriesTitleId(cleanUrl),
      detectedSource: 'ja',
      titleSrc,
      titleDst,
      sentences,
      novelNav: {
        isNovel: true,
        seriesTitle: 'Rashomon',
        chapterLabel: isEp2 ? '2 / 2' : '1 / 2',
        prevUrl,
        nextUrl,
        tocUrl: 'https://www.aozora.gr.jp/cards/1.html',
        chapters: [
          {
            title: tgt === 'en' ? 'Chapter 1: Rain at Rashomon' : 'Bab 1: Hujan di Rashomon',
            url: 'https://www.aozora.gr.jp/cards/1.html',
            current: !isEp2,
          },
          {
            title: tgt === 'en' ? 'Chapter 2: Lanterns of Kyoto' : 'Bab 2: Lentera di Kyoto',
            url: 'https://www.aozora.gr.jp/cards/2.html',
            current: isEp2,
          },
        ],
      },
      siteHtml,
    };
  }

  return directFetchWebReaderBundle({
    url: cleanUrl,
    mode: params.mode,
    titleId: params.titleId,
    view: params.view,
  });
}

export async function fetchTranslatedWebHtml(params: {
  user: AuthSessionUser;
  url: string;
  mode: ModePair;
  titleId?: string;
  view: 'translated' | 'original' | 'site' | 'reader';
}): Promise<string> {
  const cleanUrl = normalizeWebUrl(params.url);

  if (isLocalE2EMode() && !isDirectE2ETest()) {
    const { tgt } = parseModePair(params.mode);
    const bodyText =
      params.view === 'original'
        ? '<h1>第一章 雨の羅生門</h1><p>千早は小さく笑った。</p>'
        : tgt === 'ja'
          ? '<h1>第一章 雨の羅生門</h1><p>千早は静かに微笑んだ。</p>'
          : tgt === 'en'
            ? '<h1>Chapter 1: Rain at Rashomon</h1><p>Chihaya smiled quietly.</p>'
            : '<h1>Bab 1: Hujan di Rashomon</h1><p>Chihaya tersenyum kecil.</p>';
    return `<!doctype html><html lang="${tgt}"><head><meta charset="utf-8"><style>body{font-family:Charter,Georgia,serif;max-width:680px;margin:32px auto;padding:0 20px;line-height:1.75;color:#141917;background:#FAFBFA}</style></head><body>${bodyText}</body></html>`;
  }

  if (await isCloudBackendAvailable()) {
    try {
      const qs = new URLSearchParams({
        url: cleanUrl,
        mode: params.mode,
        view: params.view === 'original' ? 'original' : 'translated',
        ...(params.titleId ? { titleId: params.titleId } : {}),
      });
      const resp = await fetch(`${getApiBaseUrl()}/v1/web?${qs.toString()}`, {
        headers: await authHeaders(params.user),
      });
      if (resp.ok) return resp.text();
    } catch {
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    }
  }

  return directFetchTranslatedWebHtml({
    url: cleanUrl,
    mode: params.mode,
    titleId: params.titleId,
    view: params.view,
  });
}

export async function transcribeShortClip(params: {
  user: AuthSessionUser;
  blob: Blob;
  lang?: string;
}): Promise<string> {
  if (isLocalE2EMode()) {
    if ((params.lang || '').startsWith('id')) return 'Selamat pagi, apa kabar hari ini?';
    if ((params.lang || '').startsWith('en')) return 'Good morning, nice to meet you.';
    return '千早は小さく笑った。';
  }

  if (await isCloudBackendAvailable()) {
    try {
      const fd = new FormData();
      fd.append('audio', params.blob, 'dictation.webm');
      fd.append('lang', params.lang || 'ja-JP');
      const resp = await fetch(`${getApiBaseUrl()}/v1/speech:transcribe`, {
        method: 'POST',
        headers: await authHeaders(params.user),
        body: fd,
      });
      if (resp.ok) {
        const data = await resp.json();
        return String(data.text || '');
      }
    } catch {
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    }
  }

  const geminiKey = await getOwnerGeminiKey();
  if (!geminiKey) {
    throw new Error(
      'Peramban ini tidak menyediakan Web Speech API bawaan. Simpan kunci Gemini di Setelan -> Lanjutan untuk transkripsi suara.'
    );
  }
  const b64 = await new Promise<string>((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || '').split(',', 2)[1] || '');
    r.onerror = () => reject(new Error('Gagal membaca klip audio.'));
    r.readAsDataURL(params.blob);
  });
  const resp = await fetch(
    'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-goog-api-key': geminiKey },
      body: JSON.stringify({
        contents: [
          {
            role: 'user',
            parts: [
              { inlineData: { mimeType: params.blob.type || 'audio/webm', data: b64 } },
              {
                text: `Transcribe the spoken speech (${params.lang || 'ja-JP'}) verbatim as plain text only.`,
              },
            ],
          },
        ],
      }),
    }
  );
  if (!resp.ok) throw new Error(`Gemini Audio HTTP ${resp.status}`);
  const data = await resp.json();
  return String(data?.candidates?.[0]?.content?.parts?.[0]?.text || '').trim();
}

export async function downloadExportedTurn(params: {
  user: AuthSessionUser;
  cid: string;
  mid: string;
  fmt: string;
  bilingual?: boolean;
  theme?: string;
  fallbackSentences?: SentencePair[];
  fallbackText?: string;
}): Promise<{ blob: Blob; filename: string }> {
  if (isLocalE2EMode() || !(await isCloudBackendAvailable())) {
    let fallbackSentences = params.fallbackSentences;
    let fallbackText = params.fallbackText;
    if (!fallbackSentences && !fallbackText) {
      const stored = await loadTurnMessageOnce(params.cid, params.mid);
      if (stored) {
        fallbackSentences = stored.sentences;
        fallbackText = stored.text;
      }
    }
    return buildDirectExportBlob({
      cid: params.cid,
      mid: params.mid,
      fmt: params.fmt,
      fallbackSentences,
      fallbackText,
      bilingual: params.bilingual,
      theme: params.theme,
    });
  }
  const qs = new URLSearchParams({
    cid: params.cid,
    fmt: params.fmt,
    ...(params.bilingual ? { bilingual: '1' } : {}),
    ...(params.theme ? { theme: params.theme } : {}),
  });
  const resp = await fetch(
    `${getApiBaseUrl()}/v1/messages/${encodeURIComponent(params.mid)}/export?${qs.toString()}`,
    { headers: await authHeaders(params.user) }
  );
  if (!resp.ok) {
    return buildDirectExportBlob({
      cid: params.cid,
      mid: params.mid,
      fmt: params.fmt,
      fallbackSentences: params.fallbackSentences,
      fallbackText: params.fallbackText,
      bilingual: params.bilingual,
      theme: params.theme,
    });
  }
  const blob = await resp.blob();
  return { blob, filename: `tranx-${params.mid}.${params.fmt}` };
}

export async function resumeInterruptedTurn(params: {
  user: AuthSessionUser;
  cid: string;
  mid: string;
  onEvent: (ev: StreamEvent) => void;
}): Promise<void> {
  if (isLocalE2EMode() || !(await isCloudBackendAvailable())) {
    params.onEvent({ type: 'done', state: 'done', doneParas: 3, totalParas: 3 });
    return;
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/translate:resume`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(await authHeaders(params.user)),
    },
    body: JSON.stringify({ cid: params.cid, mid: params.mid }),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  await consumeNdjson(resp, params.onEvent);
}

export async function fetchEngineMeta(user: AuthSessionUser): Promise<Record<string, unknown>> {
  if (isLocalE2EMode()) {
    return {
      keyStatus: { configured: true, source: 'vault' },
      usageToday: { chars: 1240, calls: 4 },
      jptrans: { version: '1.1.0', manifest: 'verified' },
    };
  }
  if (await isCloudBackendAvailable()) {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/v1/meta`, {
        headers: await authHeaders(user),
      });
      if (resp.ok) return resp.json();
    } catch {
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    }
  }
  const directKey = await getOwnerGeminiKey();
  return {
    keyStatus: {
      configured: Boolean(directKey),
      source: directKey ? 'firestore-vault' : 'tranx-direct-gtx',
    },
    usageToday: { chars: 0, calls: 0 },
    jptrans: { version: '1.1.0', manifest: 'direct-mode' },
  };
}

export async function saveEngineVaultKey(
  user: AuthSessionUser,
  apiKey: string
): Promise<{ configured: boolean; source: string }> {
  await setOwnerGeminiKey(apiKey);
  if (!isLocalE2EMode() && (await isCloudBackendAvailable())) {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/v1/engine:key`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(await authHeaders(user)),
        },
        body: JSON.stringify({ apiKey }),
      });
      if (resp.ok) return resp.json();
    } catch {
      // Stored safely in owner-only Firestore settings/secrets
    }
  }
  return {
    configured: Boolean(apiKey.trim()),
    source: apiKey.trim() ? 'firestore-vault' : 'missing',
  };
}

export async function runEngineCheck(
  user: AuthSessionUser
): Promise<Array<{ model: string; ok: boolean; ms: number; sample?: string; error?: string }>> {
  if (isLocalE2EMode()) {
    return [
      {
        model: 'gemini-2.5-flash-lite',
        ok: true,
        ms: 320,
        sample: 'Selamat pagi. Chihaya tersenyum kecil.',
      },
      {
        model: 'gemini-2.5-flash',
        ok: true,
        ms: 540,
        sample: 'Selamat pagi. Chihaya tersenyum kecil.',
      },
    ];
  }
  if (await isCloudBackendAvailable()) {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/v1/engine:check`, {
        method: 'POST',
        headers: await authHeaders(user),
      });
      if (resp.ok) {
        const data = await resp.json();
        return data.models || [];
      }
    } catch {
      cloudReachableState = { ok: false, checkedAt: Date.now() };
    }
  }

  const t0 = performance.now();
  try {
    const { outputs, model } = await translateParagraphsDirect({
      paragraphs: ['おはようございます。'],
      mode: 'ja-id',
    });
    return [
      {
        model,
        ok: true,
        ms: Math.round(performance.now() - t0),
        sample: outputs[0] || 'Selamat pagi.',
      },
    ];
  } catch (err) {
    return [
      {
        model: 'tranx-direct',
        ok: false,
        ms: Math.round(performance.now() - t0),
        error: humanizeFetchError(err, 'Mesin langsung tidak dapat dijangkau.'),
      },
    ];
  }
}

export async function generatePairCode(
  user: AuthSessionUser
): Promise<{ code: string; expiresAt: string }> {
  if (isLocalE2EMode()) {
    return {
      code: '482915',
      expiresAt: new Date(Date.now() + 120000).toISOString(),
    };
  }
  if (!(await isCloudBackendAvailable())) {
    throw new ApiClientError(
      503,
      'CLOUD_FN_REQUIRED',
      'Kode pasangan 6 angka memerlukan Cloud Functions aktif. Gunakan tombol Masuk dengan Google di perangkat kedua Anda.'
    );
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/auth:pairCode`, {
    method: 'POST',
    headers: await authHeaders(user),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.json();
}

export async function redeemPairCodeRequest(code: string): Promise<string> {
  if (isLocalE2EMode()) {
    if (code.trim().length !== 6) {
      throw new ApiClientError(
        400,
        'INVALID_FORMAT',
        'Kode pasangan harus terdiri atas 6 angka.'
      );
    }
    return 'e2e-custom-token';
  }
  if (!(await isCloudBackendAvailable())) {
    throw new ApiClientError(
      503,
      'CLOUD_FN_REQUIRED',
      'Layanan kode pasangan belum aktif. Silakan masuk langsung menggunakan akun Google pemilik.'
    );
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/auth:pair`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  const data = await resp.json();
  return String(data.customToken || '');
}

export async function revokeAllOwnerSessions(user: AuthSessionUser): Promise<void> {
  if (isLocalE2EMode() || !(await isCloudBackendAvailable())) return;
  const resp = await fetch(`${getApiBaseUrl()}/v1/auth:revoke`, {
    method: 'POST',
    headers: await authHeaders(user),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
}

export async function generateInboxToken(
  user: AuthSessionUser
): Promise<{ id: string; token: string }> {
  if (isLocalE2EMode()) {
    return { id: 'inb_demo', token: 'txi_e2e_shortcut_token_demo' };
  }
  if (!(await isCloudBackendAvailable())) {
    throw new ApiClientError(
      503,
      'CLOUD_FN_REQUIRED',
      'Webhook Pintasan memerlukan Cloud Functions aktif. Anda tetap dapat memakai Bagikan -> tranX langsung di PWA.'
    );
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/inbox:token`, {
    method: 'POST',
    headers: await authHeaders(user),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.json();
}

export async function dismissInboxItem(user: AuthSessionUser, inboxId: string): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.inbox.delete(inboxId);
    store.emit();
    return;
  }
  if (await isCloudBackendAvailable()) {
    await fetch(`${getApiBaseUrl()}/v1/inbox/${encodeURIComponent(inboxId)}`, {
      method: 'DELETE',
      headers: await authHeaders(user),
    }).catch(() => {});
  }
}

export async function mergeTitleGlossaries(
  user: AuthSessionUser,
  fromTitleId: string,
  toTitleId: string
): Promise<{ merged: number; conflicts: string[] }> {
  if (isLocalE2EMode() || !(await isCloudBackendAvailable())) {
    return mergeTitleGlossariesDirect(fromTitleId, toTitleId);
  }
  try {
    const resp = await fetch(`${getApiBaseUrl()}/v1/titles:merge`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(await authHeaders(user)),
      },
      body: JSON.stringify({ fromTitleId, toTitleId }),
    });
    if (resp.ok) return resp.json();
  } catch {
    cloudReachableState = { ok: false, checkedAt: Date.now() };
  }
  return mergeTitleGlossariesDirect(fromTitleId, toTitleId);
}

export async function downloadFullBackup(
  user: AuthSessionUser,
  fallbackData?: Record<string, unknown>
): Promise<Blob> {
  if (isLocalE2EMode() || !(await isCloudBackendAvailable())) {
    const directSnapshot = fallbackData || (await exportFullBackupDirect());
    const payload = JSON.stringify(directSnapshot, null, 2);
    return new Blob([payload], { type: 'application/json' });
  }
  try {
    const resp = await fetch(`${getApiBaseUrl()}/v1/backup`, {
      headers: await authHeaders(user),
    });
    if (resp.ok) return resp.blob();
  } catch {
    cloudReachableState = { ok: false, checkedAt: Date.now() };
  }
  const directSnapshot = fallbackData || (await exportFullBackupDirect());
  return new Blob([JSON.stringify(directSnapshot, null, 2)], { type: 'application/json' });
}

export async function deleteConversationRemote(
  user: AuthSessionUser,
  cid: string
): Promise<void> {
  if (isLocalE2EMode() || !(await isCloudBackendAvailable())) {
    await deleteConversationDirect(cid);
    return;
  }
  try {
    const resp = await fetch(`${getApiBaseUrl()}/v1/conversations/${encodeURIComponent(cid)}`, {
      method: 'DELETE',
      headers: await authHeaders(user),
    });
    if (!resp.ok) await deleteConversationDirect(cid);
  } catch {
    await deleteConversationDirect(cid);
  }
}
