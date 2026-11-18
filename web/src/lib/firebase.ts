import { initializeApp, type FirebaseApp } from 'firebase/app';
import {
  GoogleAuthProvider,
  getAuth,
  onAuthStateChanged,
  signInWithCustomToken,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type Auth,
  type User,
} from 'firebase/auth';
import {
  Timestamp,
  collection,
  deleteDoc,
  doc,
  initializeFirestore,
  onSnapshot,
  orderBy,
  persistentLocalCache,
  persistentMultipleTabManager,
  query,
  serverTimestamp,
  setDoc,
  updateDoc,
  type Firestore,
} from 'firebase/firestore';
import {
  getDownloadURL,
  getStorage,
  ref as storageRef,
  uploadBytesResumable,
  type FirebaseStorage,
} from 'firebase/storage';
import type {
  AppSettingsDoc,
  ConversationDoc,
  GlossaryEntry,
  InboxItem,
  JobDoc,
  ModePair,
  TitleDoc,
  TitleKind,
  TitleStyle,
  TurnMessage,
  WorkTab,
} from '../types';

export const OWNER_EMAIL = import.meta.env.VITE_OWNER_EMAIL || 'hanifp633@gmail.com';

export const DEFAULT_SETTINGS: AppSettingsDoc = {
  llmModels: ['gemini-2.5-flash-lite', 'gemini-2.5-flash'],
  reasoningEffort: 'none',
  chatMaxChars: 5000,
  longMaxChars: 60000,
  maxUploadMb: 50,
  dailyCharCap: 500000,
  dailyCallCap: 1500,
  defaultTarget: 'id',
  uiLang: 'id',
  theme: 'light',
};

export const DEFAULT_STYLE: TitleStyle = {
  honorific_style: 'keep',
  name_order: 'jp',
  romanization: 'macron',
};

export interface AuthSessionUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  getIdToken: () => Promise<string>;
}

export function isLocalE2EMode(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.__TRANX_E2E__ === true) return true;
  const host = window.location.hostname;
  if (host !== 'localhost' && host !== '127.0.0.1') return false;
  return new URLSearchParams(window.location.search).get('e2e') === '1' ||
    window.sessionStorage.getItem('tranx_e2e') === '1';
}

let fbApp: FirebaseApp | null = null;
let fbAuth: Auth | null = null;
let fbDb: Firestore | null = null;
let fbStorage: FirebaseStorage | null = null;

function ensureFirebase(): {
  app: FirebaseApp;
  auth: Auth;
  db: Firestore;
  storage: FirebaseStorage;
} {
  if (!fbApp) {
    fbApp = initializeApp({
      apiKey: import.meta.env.VITE_FIREBASE_API_KEY || 'demo-key',
      authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || 'localhost',
      projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || 'tranx-hanif-id',
      storageBucket:
        import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || 'tranx-hanif-id.firebasestorage.app',
      messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || '0',
      appId: import.meta.env.VITE_FIREBASE_APP_ID || '1:0:web:0',
    });
    fbAuth = getAuth(fbApp);
    fbDb = initializeFirestore(fbApp, {
      localCache: persistentLocalCache({
        tabManager: persistentMultipleTabManager(),
      }),
    });
    fbStorage = getStorage(fbApp);
  }
  return { app: fbApp!, auth: fbAuth!, db: fbDb!, storage: fbStorage! };
}

function toMillis(val: unknown): number {
  if (val instanceof Timestamp) return val.toMillis();
  if (typeof val === 'number') return val;
  if (typeof val === 'string') {
    const parsed = Date.parse(val);
    return Number.isNaN(parsed) ? Date.now() : parsed;
  }
  return Date.now();
}

export function glossaryKeyForSurface(surface: string): string {
  const clean = surface.normalize('NFKC').trim();
  let hash = 2166136261;
  for (let i = 0; i < clean.length; i += 1) {
    hash ^= clean.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const hex = (hash >>> 0).toString(16).padStart(8, '0');
  const safePrefix = clean.replace(/[^A-Za-z0-9_\u3040-\u30ff\u3400-\u9fff-]/g, '').slice(0, 40);
  return safePrefix ? `${safePrefix}_${hex}` : `e_${hex}`;
}

/* Deterministic local E2E state container used ONLY on localhost?e2e=1 */
class LocalE2EStore {
  user: AuthSessionUser | null = {
    uid: 'owner-1',
    email: OWNER_EMAIL,
    displayName: 'Hanif Priyambodo',
    getIdToken: async () => 'valid-owner-token',
  };
  settings: AppSettingsDoc = { ...DEFAULT_SETTINGS };
  conversations = new Map<string, ConversationDoc>();
  messages = new Map<string, Map<string, TurnMessage>>();
  titles = new Map<string, TitleDoc>();
  glossaries = new Map<string, Map<string, GlossaryEntry>>();
  jobs = new Map<string, JobDoc>();
  inbox = new Map<string, InboxItem>();
  listeners = new Set<() => void>();

  constructor() {
    this.titles.set('t_rashomon', {
      id: 't_rashomon',
      name: 'Rashomon',
      kind: 'novel',
      style: { ...DEFAULT_STYLE },
    });
    const gMap = new Map<string, GlossaryEntry>();
    gMap.set(glossaryKeyForSurface('千早'), {
      surface: '千早',
      kind: 'PERSON',
      reading: 'ちはや',
      romaji: 'Chihaya',
      render_id: 'Chihaya',
      render_en: 'Chihaya',
      gloss_id: '',
      gloss_en: '',
      gender: 'f',
      aliases: [],
      allow_compound: false,
      confirmed: true,
      source: 'user',
      score: 1.0,
    });
    this.glossaries.set('t_rashomon', gMap);

    const now = Date.now();
    this.conversations.set('c_pinned_demo', {
      id: 'c_pinned_demo',
      title: 'Bab 1: Hujan di Gerbang Rashomon',
      titleId: 't_rashomon',
      mode: 'ja-id',
      activeTab: 'teks',
      pinned: true,
      pinnedAt: now - 10000,
      preview: 'Chihaya tersenyum kecil di bawah atap tua.',
      createdAt: now - 60000,
      updatedAt: now - 10000,
    });
    this.conversations.set('c_recent_demo', {
      id: 'c_recent_demo',
      title: 'Catatan Dialog Stasiun Kyoto',
      titleId: 't_rashomon',
      mode: 'ja-id',
      activeTab: 'teks',
      pinned: false,
      pinnedAt: null,
      preview: 'Saya turun di stasiun berikutnya.',
      createdAt: now - 120000,
      updatedAt: now - 50000,
    });

    const turnMap = new Map<string, TurnMessage>();
    turnMap.set('m_1_u', {
      id: 'm_1_u',
      role: 'user',
      kind: 'text',
      mode: 'ja-id',
      titleId: 't_rashomon',
      text: '「千早は小さく笑った。」',
      state: 'done',
      createdAt: now - 59000,
    });
    turnMap.set('m_1_r', {
      id: 'm_1_r',
      role: 'assistant',
      kind: 'text',
      mode: 'ja-id',
      titleId: 't_rashomon',
      srcText: '「千早は小さく笑った。」',
      text: '“Chihaya tersenyum kecil.”',
      sentences: [{ i: 0, src: '「千早は小さく笑った。」', dst: '“Chihaya tersenyum kecil.”' }],
      nameChips: [
        {
          surface: '千早',
          reading: 'ちはや',
          romaji: 'Chihaya',
          dst: 'Chihaya',
          kind: 'PERSON',
          confirmed: true,
          source: 'user',
        },
      ],
      state: 'done',
      model: 'gemini-2.5-flash-lite',
      ms: 420,
      createdAt: now - 58000,
    });
    this.messages.set('c_pinned_demo', turnMap);
  }

  emit() {
    for (const cb of this.listeners) cb();
  }

  subscribe(cb: () => void): () => void {
    this.listeners.add(cb);
    cb();
    return () => {
      this.listeners.delete(cb);
    };
  }
}

let e2eStore: LocalE2EStore | null = null;
export function getE2EStore(): LocalE2EStore {
  if (!e2eStore) e2eStore = new LocalE2EStore();
  return e2eStore;
}

export function subscribeAuth(
  onChange: (user: AuthSessionUser | null, authError: string | null) => void
): () => void {
  if (isLocalE2EMode()) {
    if (typeof window !== 'undefined') {
      window.sessionStorage.setItem('tranx_e2e', '1');
    }
    const store = getE2EStore();
    return store.subscribe(() => onChange(store.user, null));
  }
  const { auth } = ensureFirebase();
  return onAuthStateChanged(auth, async (fbUser: User | null) => {
    if (!fbUser) {
      onChange(null, null);
      return;
    }
    const tokenRes = await fbUser.getIdTokenResult();
    const isPaired = tokenRes.claims.owner === true;
    const isVerifiedOwner =
      fbUser.email?.toLowerCase() === OWNER_EMAIL.toLowerCase() && fbUser.emailVerified;
    if (!isPaired && !isVerifiedOwner) {
      await signOut(auth);
      onChange(null, 'NOT_OWNER');
      return;
    }
    onChange(
      {
        uid: fbUser.uid,
        email: fbUser.email,
        displayName: fbUser.displayName,
        getIdToken: () => fbUser.getIdToken(),
      },
      null
    );
  });
}

export async function loginWithGoogleOwner(): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.user = {
      uid: 'owner-1',
      email: OWNER_EMAIL,
      displayName: 'Hanif Priyambodo',
      getIdToken: async () => 'valid-owner-token',
    };
    store.emit();
    return;
  }
  const { auth } = ensureFirebase();
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ login_hint: OWNER_EMAIL, prompt: 'select_account' });
  try {
    await signInWithPopup(auth, provider);
  } catch (err: unknown) {
    const code = (err as { code?: string })?.code || '';
    if (code === 'auth/popup-blocked') {
      await signInWithRedirect(auth, provider);
      return;
    }
    throw err;
  }
}

export async function loginWithCustomPairToken(customToken: string): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.user = {
      uid: 'owner-1',
      email: OWNER_EMAIL,
      displayName: 'Perangkat Terpasang',
      getIdToken: async () => 'valid-paired-token',
    };
    store.emit();
    return;
  }
  const { auth } = ensureFirebase();
  await signInWithCustomToken(auth, customToken);
}

export async function logoutSession(): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.user = null;
    store.emit();
    return;
  }
  const { auth } = ensureFirebase();
  await signOut(auth);
}

export function subscribeSettings(onData: (settings: AppSettingsDoc) => void): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => onData({ ...store.settings }));
  }
  const { db } = ensureFirebase();
  return onSnapshot(
    doc(db, 'settings', 'app'),
    (snap) => {
      if (!snap.exists()) {
        onData({ ...DEFAULT_SETTINGS });
        return;
      }
      const d = snap.data();
      onData({
        llmModels: Array.isArray(d.llmModels) ? d.llmModels : DEFAULT_SETTINGS.llmModels,
        reasoningEffort: d.reasoningEffort || DEFAULT_SETTINGS.reasoningEffort,
        chatMaxChars: Number(d.chatMaxChars || DEFAULT_SETTINGS.chatMaxChars),
        longMaxChars: Number(d.longMaxChars || DEFAULT_SETTINGS.longMaxChars),
        maxUploadMb: Number(d.maxUploadMb || DEFAULT_SETTINGS.maxUploadMb),
        dailyCharCap: Number(d.dailyCharCap || DEFAULT_SETTINGS.dailyCharCap),
        dailyCallCap: Number(d.dailyCallCap || DEFAULT_SETTINGS.dailyCallCap),
        defaultTarget: d.defaultTarget === 'en' ? 'en' : 'id',
        uiLang: d.uiLang === 'en' ? 'en' : 'id',
        theme: d.theme === 'dark' || d.theme === 'system' ? d.theme : 'light',
      });
    },
    () => onData({ ...DEFAULT_SETTINGS })
  );
}

export async function updateAppSettings(patch: Partial<AppSettingsDoc>): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.settings = { ...store.settings, ...patch };
    store.emit();
    return;
  }
  const { db } = ensureFirebase();
  await setDoc(
    doc(db, 'settings', 'app'),
    { ...patch, updatedAt: serverTimestamp() },
    { merge: true }
  );
}

export function subscribeConversations(
  onData: (items: ConversationDoc[]) => void
): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => {
      const list = Array.from(store.conversations.values()).sort(
        (a, b) => b.updatedAt - a.updatedAt
      );
      onData(list);
    });
  }
  const { db } = ensureFirebase();
  const q = query(collection(db, 'conversations'), orderBy('updatedAt', 'desc'));
  return onSnapshot(
    q,
    (snap) => {
      const items: ConversationDoc[] = snap.docs.map((d) => {
        const raw = d.data();
        return {
          id: d.id,
          title: String(raw.title || 'Percakapan baru'),
          titleId: String(raw.titleId || ''),
          mode: raw.mode === 'ja-en' ? 'ja-en' : 'ja-id',
          activeTab: (['teks', 'gambar', 'dokumen', 'link'].includes(raw.activeTab)
            ? raw.activeTab
            : 'teks') as WorkTab,
          pinned: Boolean(raw.pinned),
          pinnedAt: raw.pinnedAt ? toMillis(raw.pinnedAt) : null,
          preview: String(raw.preview || ''),
          createdAt: toMillis(raw.createdAt),
          updatedAt: toMillis(raw.updatedAt),
        };
      });
      onData(items);
    },
    () => onData([])
  );
}

export async function upsertConversationMeta(
  cid: string,
  data: {
    title: string;
    titleId?: string;
    mode: ModePair;
    activeTab: WorkTab;
    pinned?: boolean;
    pinnedAt?: number | null;
    preview?: string;
  }
): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const cur = store.conversations.get(cid);
    const now = Date.now();
    store.conversations.set(cid, {
      id: cid,
      title: data.title,
      titleId: data.titleId ?? cur?.titleId ?? '',
      mode: data.mode,
      activeTab: data.activeTab,
      pinned: data.pinned ?? cur?.pinned ?? false,
      pinnedAt: data.pinnedAt !== undefined ? data.pinnedAt : cur?.pinnedAt ?? null,
      preview: data.preview ?? cur?.preview ?? '',
      createdAt: cur?.createdAt ?? now,
      updatedAt: now,
    });
    store.emit();
    return;
  }
  const { db } = ensureFirebase();
  await setDoc(
    doc(db, 'conversations', cid),
    {
      title: data.title.slice(0, 500),
      titleId: data.titleId || '',
      mode: data.mode,
      activeTab: data.activeTab,
      pinned: data.pinned ?? false,
      pinnedAt: data.pinnedAt ? Timestamp.fromMillis(data.pinnedAt) : null,
      preview: (data.preview || '').slice(0, 2000),
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    },
    { merge: true }
  );
}

export async function toggleConversationPin(
  conv: ConversationDoc,
  pinned: boolean
): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const cur = store.conversations.get(conv.id);
    if (cur) {
      cur.pinned = pinned;
      cur.pinnedAt = pinned ? Date.now() : null;
      cur.updatedAt = Date.now();
      store.emit();
    }
    return;
  }
  const { db } = ensureFirebase();
  await updateDoc(doc(db, 'conversations', conv.id), {
    pinned,
    pinnedAt: pinned ? serverTimestamp() : null,
    updatedAt: serverTimestamp(),
  });
}

export async function renameConversationTitle(cid: string, title: string): Promise<void> {
  const clean = title.trim().slice(0, 500);
  if (!clean) return;
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const cur = store.conversations.get(cid);
    if (cur) {
      cur.title = clean;
      cur.updatedAt = Date.now();
      store.emit();
    }
    return;
  }
  const { db } = ensureFirebase();
  await updateDoc(doc(db, 'conversations', cid), {
    title: clean,
    updatedAt: serverTimestamp(),
  });
}

export function subscribeMessages(
  cid: string,
  onData: (items: TurnMessage[]) => void
): () => void {
  if (!cid) {
    onData([]);
    return () => {};
  }
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => {
      const bucket = store.messages.get(cid);
      const list = bucket
        ? Array.from(bucket.values()).sort((a, b) => a.createdAt - b.createdAt)
        : [];
      onData(list);
    });
  }
  const { db } = ensureFirebase();
  const q = query(
    collection(db, 'conversations', cid, 'messages'),
    orderBy('createdAt', 'asc')
  );
  return onSnapshot(
    q,
    (snap) => {
      const items: TurnMessage[] = snap.docs.map((d) => {
        const raw = d.data();
        return {
          id: d.id,
          role: raw.role === 'user' ? 'user' : 'assistant',
          kind: raw.kind || 'text',
          mode: raw.mode === 'ja-en' ? 'ja-en' : 'ja-id',
          titleId: raw.titleId,
          text: String(raw.text || ''),
          srcText: raw.srcText,
          sentences: raw.sentences,
          fileName: raw.fileName,
          fmt: raw.fmt,
          jobId: raw.jobId,
          storageOutputPath: raw.storageOutputPath,
          done: raw.done,
          total: raw.total,
          imageResult: raw.imageResult,
          linkPreview: raw.linkPreview,
          state: raw.state || 'done',
          model: raw.model,
          ms: raw.ms,
          error: raw.error,
          createdAt: toMillis(raw.createdAt),
        };
      });
      onData(items);
    },
    () => onData([])
  );
}

export function subscribeTitles(onData: (titles: TitleDoc[]) => void): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => {
      onData(Array.from(store.titles.values()).filter((t) => !t.mergedInto));
    });
  }
  const { db } = ensureFirebase();
  return onSnapshot(
    collection(db, 'titles'),
    (snap) => {
      const out: TitleDoc[] = [];
      for (const d of snap.docs) {
        const raw = d.data();
        if (raw.mergedInto) continue;
        out.push({
          id: d.id,
          name: String(raw.name || d.id),
          kind: (raw.kind || 'lepas') as TitleKind,
          style: {
            honorific_style: raw.style?.honorific_style || 'keep',
            name_order: raw.style?.name_order || 'jp',
            romanization: raw.style?.romanization || 'macron',
          },
          description: raw.description,
          notes: raw.notes,
        });
      }
      onData(out);
    },
    () => onData([])
  );
}

export async function saveTitleDoc(
  titleId: string,
  payload: { name: string; kind: TitleKind; style: TitleStyle; notes?: string }
): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.titles.set(titleId, { id: titleId, ...payload });
    store.emit();
    return;
  }
  const { db } = ensureFirebase();
  await setDoc(
    doc(db, 'titles', titleId),
    {
      name: payload.name.trim().slice(0, 300),
      kind: payload.kind,
      style: payload.style,
      notes: (payload.notes || '').slice(0, 5000),
      updatedAt: serverTimestamp(),
    },
    { merge: true }
  );
}

export function subscribeGlossary(
  titleId: string,
  onData: (entries: Array<{ key: string; entry: GlossaryEntry }>) => void
): () => void {
  if (!titleId) {
    onData([]);
    return () => {};
  }
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => {
      const g = store.glossaries.get(titleId);
      if (!g) {
        onData([]);
        return;
      }
      onData(Array.from(g.entries()).map(([key, entry]) => ({ key, entry })));
    });
  }
  const { db } = ensureFirebase();
  return onSnapshot(
    collection(db, 'titles', titleId, 'glossary'),
    (snap) => {
      const rows = snap.docs.map((d) => {
        const r = d.data();
        return {
          key: d.id,
          entry: {
            surface: String(r.surface || ''),
            kind: (r.kind || 'PERSON') as GlossaryEntry['kind'],
            reading: String(r.reading || ''),
            romaji: String(r.romaji || ''),
            render_id: String(r.render_id || ''),
            render_en: String(r.render_en || ''),
            gloss_id: String(r.gloss_id || ''),
            gloss_en: String(r.gloss_en || ''),
            gender: (r.gender === 'm' || r.gender === 'f' ? r.gender : '') as GlossaryEntry['gender'],
            aliases: Array.isArray(r.aliases) ? r.aliases.map(String) : [],
            allow_compound: Boolean(r.allow_compound),
            confirmed: Boolean(r.confirmed ?? true),
            source: String(r.source || 'user'),
            score: Number(r.score ?? 1.0),
          },
        };
      });
      onData(rows);
    },
    () => onData([])
  );
}

/* Saves exact 14 GlossaryEntry fields + updatedAt matching firestore.rules isValidGlossaryEntry */
export async function upsertUserGlossaryEntry(
  titleId: string,
  entry: Omit<GlossaryEntry, 'confirmed' | 'source'>
): Promise<void> {
  const key = glossaryKeyForSurface(entry.surface);
  const fullEntry: GlossaryEntry = {
    surface: entry.surface.trim(),
    kind: entry.kind,
    reading: entry.reading.trim(),
    romaji: entry.romaji.trim(),
    render_id: entry.render_id.trim(),
    render_en: entry.render_en.trim(),
    gloss_id: entry.gloss_id.trim(),
    gloss_en: entry.gloss_en.trim(),
    gender: entry.gender,
    aliases: entry.aliases.map((a) => a.trim()).filter(Boolean),
    allow_compound: Boolean(entry.allow_compound),
    confirmed: true,
    source: 'user',
    score: Math.min(1, Math.max(0, Number(entry.score ?? 1.0))),
  };
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    if (!store.titles.has(titleId)) {
      store.titles.set(titleId, {
        id: titleId,
        name: 'Percakapan',
        kind: 'lepas',
        style: { ...DEFAULT_STYLE },
      });
    }
    const bucket = store.glossaries.get(titleId) ?? new Map<string, GlossaryEntry>();
    bucket.set(key, fullEntry);
    store.glossaries.set(titleId, bucket);
    store.emit();
    return;
  }
  const { db } = ensureFirebase();
  await setDoc(doc(db, 'titles', titleId, 'glossary', key), {
    ...fullEntry,
    updatedAt: serverTimestamp(),
  });
}

export async function removeGlossaryEntry(titleId: string, key: string): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.glossaries.get(titleId)?.delete(key);
    store.emit();
    return;
  }
  const { db } = ensureFirebase();
  await deleteDoc(doc(db, 'titles', titleId, 'glossary', key));
}

export function subscribeJobs(onData: (jobs: JobDoc[]) => void): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => {
      onData(
        Array.from(store.jobs.values()).sort((a, b) => b.updatedAt - a.updatedAt)
      );
    });
  }
  const { db } = ensureFirebase();
  return onSnapshot(
    collection(db, 'jobs'),
    (snap) => {
      const list: JobDoc[] = snap.docs
        .map((d) => {
          const r = d.data();
          return {
            id: d.id,
            cid: String(r.cid || ''),
            mid: String(r.mid || ''),
            titleId: r.titleId,
            fileName: String(r.fileName || 'berkas'),
            fileSize: Number(r.fileSize || 0),
            fmt: r.fmt,
            state: (r.state || 'uploading') as JobDoc['state'],
            doneParas: r.doneParas,
            totalParas: r.totalParas,
            storagePath: r.storagePath,
            storageOutputPath: r.storageOutputPath,
            message: r.message,
            updatedAt: toMillis(r.updatedAt),
          };
        })
        .sort((a, b) => b.updatedAt - a.updatedAt);
      onData(list);
    },
    () => onData([])
  );
}

export function subscribeInbox(onData: (items: InboxItem[]) => void): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => onData(Array.from(store.inbox.values())));
  }
  const { db } = ensureFirebase();
  return onSnapshot(
    collection(db, 'inbox'),
    (snap) => {
      onData(
        snap.docs.map((d) => {
          const r = d.data();
          return {
            id: d.id,
            text: String(r.text || ''),
            url: r.url || null,
            title: r.title || null,
            createdAt: toMillis(r.createdAt),
          };
        })
      );
    },
    () => onData([])
  );
}

export async function uploadDocumentForJob(params: {
  uid: string;
  cid: string;
  mid: string;
  mode: ModePair;
  titleId?: string;
  file: File;
  onProgress?: (pct: number) => void;
}): Promise<string> {
  const jobId = `job_${Date.now().toString(36)}`;
  const storagePath = `uploads/${params.uid}/${jobId}/${params.file.name}`;

  if (isLocalE2EMode()) {
    const store = getE2EStore();
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
      storagePath,
      storageOutputPath: `outputs/${params.uid}/${jobId}/${params.file.name}`,
      updatedAt: now,
    });
    const bucket = store.messages.get(params.cid) ?? new Map<string, TurnMessage>();
    bucket.set(params.mid, {
      id: params.mid,
      role: 'assistant',
      kind: 'document',
      mode: params.mode,
      titleId: params.titleId || 't_rashomon',
      fileName: params.file.name,
      fmt: params.file.name.split('.').pop()?.toLowerCase() || 'txt',
      jobId,
      done: 3,
      total: 3,
      text: `Terjemahan dokumen ${params.file.name} selesai.`,
      state: 'done',
      createdAt: now,
    });
    store.messages.set(params.cid, bucket);
    await upsertConversationMeta(params.cid, {
      title: params.file.name,
      titleId: params.titleId || 't_rashomon',
      mode: params.mode,
      activeTab: 'dokumen',
      preview: params.file.name,
    });
    params.onProgress?.(100);
    store.emit();
    return jobId;
  }

  const { db, storage } = ensureFirebase();
  await setDoc(doc(db, 'jobs', jobId), {
    state: 'uploading',
    fileSize: params.file.size,
    fileName: params.file.name.slice(0, 500),
    storagePath,
    mimeType: (params.file.type || 'application/octet-stream').slice(0, 200),
    cid: params.cid,
    mid: params.mid,
    mode: params.mode,
    titleId: params.titleId || '',
    updatedAt: serverTimestamp(),
  });

  await new Promise<void>((resolve, reject) => {
    const task = uploadBytesResumable(storageRef(storage, storagePath), params.file, {
      contentType: params.file.type || 'application/octet-stream',
    });
    task.on(
      'state_changed',
      (snap) => {
        if (snap.totalBytes > 0) {
          params.onProgress?.(Math.round((snap.bytesTransferred / snap.totalBytes) * 100));
        }
      },
      (err) => reject(err),
      () => resolve()
    );
  });

  await updateDoc(doc(db, 'jobs', jobId), {
    state: 'queued',
    updatedAt: serverTimestamp(),
  });

  return jobId;
}

export async function requestStopJob(jobId: string): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const job = store.jobs.get(jobId);
    if (job) {
      job.state = 'stopped';
      store.emit();
    }
    return;
  }
  const { db } = ensureFirebase();
  await updateDoc(doc(db, 'jobs', jobId), {
    state: 'stopped',
    updatedAt: serverTimestamp(),
  });
}

export async function resolveStorageOutputUrl(storageOutputPath: string): Promise<string> {
  if (isLocalE2EMode()) {
    const blob = new Blob(['1\n00:00:01,000 --> 00:00:03,000\nChihaya tersenyum kecil.\n'], {
      type: 'text/plain;charset=utf-8',
    });
    return URL.createObjectURL(blob);
  }
  const { storage } = ensureFirebase();
  return getDownloadURL(storageRef(storage, storageOutputPath));
}
