import {
  getE2EStore,
  isLocalE2EMode,
  upsertConversationMeta,
  type AuthSessionUser,
} from './firebase';
import type {
  ImageTranslationResult,
  LinkPreviewPayload,
  ModePair,
  NameChipItem,
  SentencePair,
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
  type: 'meta' | 'delta' | 'para' | 'done' | 'error';
  cid?: string;
  mid?: string;
  titleId?: string;
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
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const tid = params.titleId || 't_rashomon';
    const asstMid = `${params.clientMsgId}_r`;
    const isEn = params.mode === 'ja-en';
    const dst = isEn
      ? 'Chihaya smiled quietly beneath the eaves.'
      : 'Chihaya tersenyum tenang di bawah atap.';
    const now = Date.now();
    const bucket = store.messages.get(params.cid) ?? new Map();
    bucket.set(params.clientMsgId, {
      id: params.clientMsgId,
      role: 'user',
      kind: 'text',
      mode: params.mode,
      titleId: tid,
      text: params.text,
      state: 'done',
      createdAt: now,
    });
    params.onEvent({ type: 'meta', cid: params.cid, mid: asstMid, titleId: tid });
    params.onEvent({ type: 'delta', i: 0, src: params.text, dst });
    params.onEvent({
      type: 'done',
      cid: params.cid,
      mid: asstMid,
      titleId: tid,
      fullDst: dst,
      sentences: [{ i: 0, src: params.text, dst }],
      model: 'gemini-2.5-flash-lite',
      ms: 210,
    });
    bucket.set(asstMid, {
      id: asstMid,
      role: 'assistant',
      kind: 'text',
      mode: params.mode,
      titleId: tid,
      srcText: params.text,
      text: dst,
      sentences: [{ i: 0, src: params.text, dst }],
      nameChips: params.text.includes('千早')
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
      state: 'done',
      model: 'gemini-2.5-flash-lite',
      ms: 210,
      createdAt: now + 1,
    });
    store.messages.set(params.cid, bucket);
    await upsertConversationMeta(params.cid, {
      title: params.text.split('\n')[0].slice(0, 80) || 'Percakapan',
      titleId: tid,
      mode: params.mode,
      activeTab: 'teks',
      preview: dst,
    });
    if (params.inboxId) store.inbox.delete(params.inboxId);
    store.emit();
    return;
  }

  const endpoint =
    params.text.length > 5000 ? `${getApiBaseUrl()}/v1/translate` : `${getApiBaseUrl()}/v1/chat`;
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
  if (!resp.ok) throw await parseErrorResponse(resp);
  await consumeNdjson(resp, params.onEvent);
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
}

export async function translateImageRequest(params: {
  user: AuthSessionUser;
  cid: string;
  mode: ModePair;
  fileName: string;
  imageDataUrl: string;
  titleId?: string;
}): Promise<{ cid: string; mid: string; titleId: string } & ImageTranslationResult> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const mid = `img_${Date.now().toString(36)}`;
    const res: ImageTranslationResult = {
      width: 640,
      height: 480,
      blocks: [
        {
          id: 1,
          box: [60, 50, 280, 96],
          src: '「千早は小さく笑った。」',
          dst: params.mode === 'ja-en' ? 'Chihaya smiled quietly.' : 'Chihaya tersenyum kecil.',
        },
      ],
      fullSrc: '「千早は小さく笑った。」',
      fullDst: params.mode === 'ja-en' ? 'Chihaya smiled quietly.' : 'Chihaya tersenyum kecil.',
      model: 'gemini-2.5-flash',
      dataUrl: params.imageDataUrl,
    };
    const bucket = store.messages.get(params.cid) ?? new Map();
    bucket.set(mid, {
      id: mid,
      role: 'assistant',
      kind: 'image',
      mode: params.mode,
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
      activeTab: 'gambar',
      preview: res.fullDst,
    });
    store.emit();
    return { cid: params.cid, mid, titleId: 't_rashomon', ...res };
  }
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
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.json();
}

export async function previewLinkRequest(params: {
  user: AuthSessionUser;
  cid: string;
  url: string;
  mode: ModePair;
  titleId?: string;
}): Promise<LinkPreviewPayload> {
  if (isLocalE2EMode()) {
    if (params.url.includes('127.0.0.1') || params.url.includes('169.254.169.254')) {
      throw new ApiClientError(403, 'BLOCKED_URL', 'Alamat jaringan internal ditolak.');
    }
    const store = getE2EStore();
    const mid = `lnk_${Date.now().toString(36)}`;
    const host = new URL(params.url).hostname;
    const preview: LinkPreviewPayload = {
      mid,
      cid: params.cid,
      titleId: 't_rashomon',
      url: params.url,
      host,
      isAozora: host.includes('aozora'),
      titleSrc: '第一章 雨の羅生門',
      titleDst: params.mode === 'ja-en' ? 'Chapter 1: Rain at Rashomon' : 'Bab 1: Hujan di Rashomon',
      excerptSrc: '千早は小さく笑った。',
      excerptDst:
        params.mode === 'ja-en'
          ? 'Chihaya smiled quietly under the gate.'
          : 'Chihaya tersenyum kecil di bawah gerbang.',
      paragraphCount: 12,
      lockedNames: 1,
      readerSupported: true,
    };
    const bucket = store.messages.get(params.cid) ?? new Map();
    bucket.set(mid, {
      id: mid,
      role: 'assistant',
      kind: 'link',
      mode: params.mode,
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
      activeTab: 'link',
      preview: preview.excerptDst,
    });
    store.emit();
    return preview;
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/links:preview`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(await authHeaders(params.user)),
    },
    body: JSON.stringify(params),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.json();
}

export async function fetchTranslatedWebHtml(params: {
  user: AuthSessionUser;
  url: string;
  mode: ModePair;
  titleId?: string;
  view: 'translated' | 'original';
}): Promise<string> {
  if (isLocalE2EMode()) {
    const bodyText =
      params.view === 'original'
        ? '<h1>第一章 雨の羅生門</h1><p>千早は小さく笑った。</p>'
        : params.mode === 'ja-en'
          ? '<h1>Chapter 1: Rain at Rashomon</h1><p>Chihaya smiled quietly.</p>'
          : '<h1>Bab 1: Hujan di Rashomon</h1><p>Chihaya tersenyum kecil.</p>';
    return `<!doctype html><html lang="id"><head><meta charset="utf-8"><style>body{font-family:Charter,Georgia,serif;max-width:680px;margin:32px auto;padding:0 20px;line-height:1.75;color:#141917;background:#FAFBFA}</style></head><body>${bodyText}</body></html>`;
  }
  const qs = new URLSearchParams({
    url: params.url,
    mode: params.mode,
    view: params.view,
    ...(params.titleId ? { titleId: params.titleId } : {}),
  });
  const resp = await fetch(`${getApiBaseUrl()}/v1/web?${qs.toString()}`, {
    headers: await authHeaders(params.user),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.text();
}

export async function transcribeShortClip(params: {
  user: AuthSessionUser;
  blob: Blob;
  lang?: string;
}): Promise<string> {
  if (isLocalE2EMode()) {
    return '千早は小さく笑った。';
  }
  const fd = new FormData();
  fd.append('audio', params.blob, 'dictation.webm');
  fd.append('lang', params.lang || 'ja-JP');
  const resp = await fetch(`${getApiBaseUrl()}/v1/speech:transcribe`, {
    method: 'POST',
    headers: await authHeaders(params.user),
    body: fd,
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  const data = await resp.json();
  return String(data.text || '');
}

export async function downloadExportedTurn(params: {
  user: AuthSessionUser;
  cid: string;
  mid: string;
  fmt: string;
  bilingual?: boolean;
  theme?: string;
}): Promise<{ blob: Blob; filename: string }> {
  if (isLocalE2EMode()) {
    const content =
      params.fmt === 'html'
        ? `<!doctype html><html lang="id" data-tranx-v3="${params.theme || 'Terang'}"><body><p><ruby>千早<rt>ちはや</rt></ruby>: Chihaya tersenyum kecil.</p></body></html>`
        : 'Chihaya tersenyum kecil.\n';
    return {
      blob: new Blob([content], {
        type: params.fmt === 'html' ? 'text/html;charset=utf-8' : 'text/plain;charset=utf-8',
      }),
      filename: `tranx-${params.mid}.${params.fmt}`,
    };
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
  if (!resp.ok) throw await parseErrorResponse(resp);
  const blob = await resp.blob();
  return { blob, filename: `tranx-${params.mid}.${params.fmt}` };
}

export async function resumeInterruptedTurn(params: {
  user: AuthSessionUser;
  cid: string;
  mid: string;
  onEvent: (ev: StreamEvent) => void;
}): Promise<void> {
  if (isLocalE2EMode()) {
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
  const resp = await fetch(`${getApiBaseUrl()}/v1/meta`, {
    headers: await authHeaders(user),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.json();
}

export async function saveEngineVaultKey(
  user: AuthSessionUser,
  apiKey: string
): Promise<{ configured: boolean; source: string }> {
  if (isLocalE2EMode()) {
    return { configured: Boolean(apiKey.trim()), source: apiKey.trim() ? 'vault' : 'missing' };
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/engine:key`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(await authHeaders(user)),
    },
    body: JSON.stringify({ apiKey }),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.json();
}

export async function runEngineCheck(
  user: AuthSessionUser
): Promise<Array<{ model: string; ok: boolean; ms: number; sample?: string; error?: string }>> {
  if (isLocalE2EMode()) {
    return [
      { model: 'gemini-2.5-flash-lite', ok: true, ms: 340, sample: 'Selamat pagi. Chihaya tersenyum kecil.' },
      { model: 'gemini-2.5-flash', ok: true, ms: 580, sample: 'Selamat pagi. Chihaya tersenyum kecil.' },
    ];
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/engine:check`, {
    method: 'POST',
    headers: await authHeaders(user),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  const data = await resp.json();
  return data.models || [];
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
      throw new ApiClientError(400, 'INVALID_FORMAT', 'Kode pasangan harus terdiri atas 6 angka.');
    }
    return 'e2e-custom-token';
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
  if (isLocalE2EMode()) return;
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
  await fetch(`${getApiBaseUrl()}/v1/inbox/${encodeURIComponent(inboxId)}`, {
    method: 'DELETE',
    headers: await authHeaders(user),
  });
}

export async function mergeTitleGlossaries(
  user: AuthSessionUser,
  fromTitleId: string,
  toTitleId: string
): Promise<{ merged: number; conflicts: string[] }> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const src = store.glossaries.get(fromTitleId);
    const dst = store.glossaries.get(toTitleId) ?? new Map();
    let merged = 0;
    if (src) {
      for (const [k, v] of src.entries()) {
        if (!dst.has(k)) {
          dst.set(k, v);
          merged += 1;
        }
      }
    }
    store.glossaries.set(toTitleId, dst);
    const fromDoc = store.titles.get(fromTitleId);
    if (fromDoc) fromDoc.mergedInto = toTitleId;
    store.emit();
    return { merged, conflicts: [] };
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/titles:merge`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(await authHeaders(user)),
    },
    body: JSON.stringify({ fromTitleId, toTitleId }),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.json();
}

export async function downloadFullBackup(user: AuthSessionUser): Promise<Blob> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const payload = JSON.stringify(
      {
        version: '2.1',
        exportedAt: new Date().toISOString(),
        settings: store.settings,
        conversations: Array.from(store.conversations.values()),
      },
      null,
      2
    );
    return new Blob([payload], { type: 'application/json' });
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/backup`, {
    headers: await authHeaders(user),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
  return resp.blob();
}

export async function deleteConversationRemote(
  user: AuthSessionUser,
  cid: string
): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.conversations.delete(cid);
    store.messages.delete(cid);
    store.emit();
    return;
  }
  const resp = await fetch(`${getApiBaseUrl()}/v1/conversations/${encodeURIComponent(cid)}`, {
    method: 'DELETE',
    headers: await authHeaders(user),
  });
  if (!resp.ok) throw await parseErrorResponse(resp);
}
