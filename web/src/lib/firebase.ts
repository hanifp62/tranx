import { initializeApp, type FirebaseApp } from 'firebase/app';
import {
  GoogleAuthProvider,
  getAuth,
  getRedirectResult,
  onAuthStateChanged,
  signInWithCustomToken,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type Auth,
  type User,
} from 'firebase/auth';
import type { DocumentData, Firestore, UpdateData } from 'firebase/firestore';
import type { FirebaseStorage } from 'firebase/storage';
import type {
  AppSettingsDoc,
  ConversationDoc,
  GlossaryEntry,
  InboxItem,
  JobDoc,
  ModePair,
  SentencePair,
  SourceLang,
  TargetLang,
  TitleDoc,
  TitleKind,
  TitleStyle,
  TurnMessage,
  WorkTab,
} from '../types';

const DEMO_E2E_EMAIL = 'reader@example.com';

const ALLOWED_EMAIL_SET: ReadonlySet<string> | null = (() => {
  const raw = String(import.meta.env?.VITE_ALLOWED_EMAILS || '').trim();
  if (!raw) return null;
  const items = raw
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  return items.length > 0 ? new Set(items) : null;
})();

export const VALID_MODES: ReadonlySet<string> = new Set<ModePair>([
  'auto-id',
  'auto-en',
  'auto-ja',
  'ja-id',
  'ja-en',
  'id-ja',
  'id-en',
  'en-id',
  'en-ja',
]);

export function normalizeModePair(raw: unknown, fallback: ModePair = 'auto-id'): ModePair {
  const s = String(raw || '').trim().toLowerCase();
  return VALID_MODES.has(s) ? (s as ModePair) : fallback;
}

export const DEFAULT_SETTINGS: AppSettingsDoc = {
  llmModels: ['gemini-2.5-flash-lite', 'gemini-2.5-flash'],
  reasoningEffort: 'none',
  chatMaxChars: 5000,
  longMaxChars: 60000,
  maxUploadMb: 50,
  dailyCharCap: 500000,
  dailyCallCap: 1500,
  defaultSource: 'auto',
  defaultTarget: 'id',
  uiLang: 'id',
  theme: 'light',
  translationTone: 'auto',
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

const SHARED_DEVICE_USER_CACHE_KEYS = [
  'tranx_para_cache_v3',
  'tranx_ebook_shelf_v2',
  'tranx_ebook_para_pos_v1',
  'tranx_ebook_bookmarks_v1',
  'tranx_reading_progress_v1',
  'tranx_series_discourse_v1',
  'tranx_ebook_prefs_v1',
  'tranx_translation_tone_v1',
];

const localCacheResetHooks = new Set<() => void>();

export function registerLocalCacheResetHook(hook: () => void): () => void {
  localCacheResetHooks.add(hook);
  return () => {
    localCacheResetHooks.delete(hook);
  };
}

export function clearLocalUserCaches(): void {
  for (const hook of localCacheResetHooks) {
    try {
      hook();
    } catch {
      // ignore individual cache reset hook failures
    }
  }
  if (typeof window === 'undefined') return;
  for (const key of SHARED_DEVICE_USER_CACHE_KEYS) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // ignore storage restrictions
    }
  }
  try {
    const dynamicKeys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const k = window.localStorage.key(i);
      if (k && (k.startsWith('tranx_toc_v3::') || k.startsWith('tranx_ebook_'))) {
        dynamicKeys.push(k);
      }
    }
    for (const k of dynamicKeys) {
      window.localStorage.removeItem(k);
    }
  } catch {
    // ignore storage iteration restrictions
  }
  try {
    window.sessionStorage.removeItem('tranx_post_login_path');
  } catch {
    // ignore sessionStorage restrictions
  }
  try {
    void import('./perfCache')
      .then((m) => m.clearPerfCacheDb())
      .catch(() => {
        try {
          window.indexedDB?.deleteDatabase('tranx_perf_cache_v1');
        } catch {
          // ignore IndexedDB restrictions
        }
      });
  } catch {
    // ignore IndexedDB restrictions
  }
}

export function isLocalE2EMode(): boolean {
  if (typeof window === 'undefined') return false;
  const host = window.location.hostname;
  if (host !== 'localhost' && host !== '127.0.0.1') return false;
  return (
    window.__TRANX_E2E__ === true ||
    new URLSearchParams(window.location.search).get('e2e') === '1' ||
    window.sessionStorage.getItem('tranx_e2e') === '1'
  );
}

export interface RuntimeFirebaseConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  storageBucket: string;
  messagingSenderId: string;
  appId: string;
}

const FB_INIT_SESSION_KEY = 'tranx_fb_init_v1';
let runtimeFirebaseConfig: Partial<RuntimeFirebaseConfig> | null = (() => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(FB_INIT_SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RuntimeFirebaseConfig>;
    return parsed && typeof parsed.apiKey === 'string' && parsed.apiKey.trim() ? parsed : null;
  } catch {
    return null;
  }
})();
let firebaseBootstrapPromise: Promise<void> | null = null;

/**
 * Loads Firebase Hosting's official same-origin runtime config (/__/firebase/init.json)
 * before Firebase initializes, avoiding baking VITE_FIREBASE_API_KEY into static JS bundles.
 * Memoizes in sessionStorage so warm reloads pay 0ms network RTT.
 */
export function bootstrapFirebaseConfig(): Promise<void> {
  if (typeof window === 'undefined' || isLocalE2EMode()) {
    return Promise.resolve();
  }
  if (import.meta.env.VITE_FIREBASE_API_KEY || runtimeFirebaseConfig?.apiKey) {
    return Promise.resolve();
  }
  if (firebaseBootstrapPromise) return firebaseBootstrapPromise;
  firebaseBootstrapPromise = (async () => {
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 4000);
    try {
      const resp = await fetch('/__/firebase/init.json', {
        method: 'GET',
        cache: 'default',
        credentials: 'same-origin',
        signal: ctrl.signal,
      });
      if (!resp.ok) return;
      const data = (await resp.json()) as Partial<RuntimeFirebaseConfig>;
      if (data && typeof data.apiKey === 'string' && data.apiKey.trim()) {
        runtimeFirebaseConfig = {
          apiKey: data.apiKey.trim(),
          authDomain: String(data.authDomain || '').trim(),
          projectId: String(data.projectId || '').trim(),
          storageBucket: String(data.storageBucket || '').trim(),
          messagingSenderId: String(data.messagingSenderId || '').trim(),
          appId: String(data.appId || '').trim(),
        };
        try {
          window.sessionStorage.setItem(FB_INIT_SESSION_KEY, JSON.stringify(runtimeFirebaseConfig));
        } catch {
          // ignore sessionStorage restrictions
        }
      }
    } catch {
      // Reset memoized promise on transient failure so subsequent retries can succeed
      firebaseBootstrapPromise = null;
    } finally {
      window.clearTimeout(timer);
    }
  })();
  return firebaseBootstrapPromise;
}

type FirestoreModule = typeof import('firebase/firestore');

let fbApp: FirebaseApp | null = null;
let fbAuth: Auth | null = null;
let fbDb: Firestore | null = null;
let fbStorage: FirebaseStorage | null = null;
let firestoreModPromise: Promise<FirestoreModule> | null = null;
let activeAuthUid: string | null = null;
let redirectResultChecked = false;
let googleSignInInFlight: Promise<void> | null = null;

function getActiveUid(): string | null {
  return fbAuth?.currentUser?.uid || activeAuthUid;
}

function requireActiveUid(): string {
  const uid = getActiveUid();
  if (!uid) {
    throw new Error('Sesi masuk tidak aktif. Silakan masuk dengan akun Google Anda.');
  }
  return uid;
}

function loadFirestoreMod(): Promise<FirestoreModule> {
  if (!firestoreModPromise) {
    firestoreModPromise = import('firebase/firestore');
  }
  return firestoreModPromise;
}

function userDoc(fs: FirestoreModule, db: Firestore, pathSegment: string, ...segments: string[]) {
  return fs.doc(db, 'users', requireActiveUid(), pathSegment, ...segments);
}

function userCollection(
  fs: FirestoreModule,
  db: Firestore,
  pathSegment: string,
  ...segments: string[]
) {
  return fs.collection(db, 'users', requireActiveUid(), pathSegment, ...segments);
}

export function ensureFirebaseAuth(): {
  app: FirebaseApp;
  auth: Auth;
} {
  if (!fbApp) {
    const rt = runtimeFirebaseConfig;
    fbApp = initializeApp({
      apiKey: rt?.apiKey || import.meta.env.VITE_FIREBASE_API_KEY || 'demo-key',
      authDomain: rt?.authDomain || import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || 'localhost',
      projectId: rt?.projectId || import.meta.env.VITE_FIREBASE_PROJECT_ID || 'tranx-hanif-id',
      storageBucket:
        rt?.storageBucket ||
        import.meta.env.VITE_FIREBASE_STORAGE_BUCKET ||
        'tranx-hanif-id.firebasestorage.app',
      messagingSenderId:
        rt?.messagingSenderId || import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || '0',
      appId: rt?.appId || import.meta.env.VITE_FIREBASE_APP_ID || '1:0:web:0',
    });
    fbAuth = getAuth(fbApp);
  }
  return { app: fbApp!, auth: fbAuth! };
}

async function ensureFirestore(): Promise<{
  app: FirebaseApp;
  auth: Auth;
  db: Firestore;
  fs: FirestoreModule;
}> {
  const { app, auth } = ensureFirebaseAuth();
  const fs = await loadFirestoreMod();
  if (!fbDb) {
    fbDb = fs.initializeFirestore(app, {
      localCache: fs.persistentLocalCache({
        tabManager: fs.persistentMultipleTabManager(),
        cacheSizeBytes: 40 * 1024 * 1024, // 40 MiB ceiling preventing mobile PWA IndexedDB bloat
      }),
    });
  }
  return { app, auth, db: fbDb, fs };
}

async function ensureFirebaseStorage(): Promise<{
  storage: FirebaseStorage;
  mod: typeof import('firebase/storage');
}> {
  const { app } = ensureFirebaseAuth();
  const mod = await import('firebase/storage');
  if (!fbStorage) {
    fbStorage = mod.getStorage(app);
  }
  return { storage: fbStorage, mod };
}

function toMillis(val: unknown): number {
  if (
    val &&
    typeof val === 'object' &&
    typeof (val as { toMillis?: unknown }).toMillis === 'function'
  ) {
    return (val as { toMillis: () => number }).toMillis();
  }
  if (typeof val === 'number') return val;
  if (typeof val === 'string') {
    const parsed = Date.parse(val);
    return Number.isNaN(parsed) ? Date.now() : parsed;
  }
  return Date.now();
}

function isPlainObject(val: unknown): val is Record<string, unknown> {
  if (!val || typeof val !== 'object') return false;
  const proto = Object.getPrototypeOf(val);
  return proto === Object.prototype || proto === null;
}

/** Recursively removes undefined fields from plain objects/arrays before Firestore writes (preserving FieldValue/Timestamp). */
export function stripUndefinedDeep<T>(value: T): T {
  if (value === null || value === undefined || typeof value !== 'object') {
    return value;
  }
  if (Array.isArray(value)) {
    return value
      .filter((item) => item !== undefined)
      .map((item) => stripUndefinedDeep(item)) as unknown as T;
  }
  if (!isPlainObject(value)) {
    return value;
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value)) {
    if (v !== undefined) {
      out[k] = stripUndefinedDeep(v);
    }
  }
  return out as T;
}

export function glossaryKeyForSurface(surface: string): string {
  const clean = surface.normalize('NFKC').trim();
  let hash = 2166136261;
  for (let i = 0; i < clean.length; i += 1) {
    hash ^= clean.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const hex = (hash >>> 0).toString(16).padStart(8, '0');
  const safePrefix = clean
    .replace(/[^A-Za-z0-9_\u3040-\u30ff\u3400-\u9fff-]/g, '')
    .slice(0, 40);
  return safePrefix ? `${safePrefix}_${hex}` : `e_${hex}`;
}

class LocalE2EStore {
  user: AuthSessionUser | null = {
    uid: 'demo-user-1',
    email: DEMO_E2E_EMAIL,
    displayName: 'Demo Reader',
    getIdToken: async () => 'valid-owner-token',
  };
  settings: AppSettingsDoc = { ...DEFAULT_SETTINGS };
  geminiKey = '';
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
      detectedSource: 'ja',
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
      mode: 'auto-id',
      detectedSource: 'ja',
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
      detectedSource: 'ja',
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
      detectedSource: 'ja',
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
  let cancelled = false;
  let unsubscribeInner: (() => void) | null = null;

  const attachListener = () => {
    if (cancelled) return;
    const { auth } = ensureFirebaseAuth();
    if (!redirectResultChecked) {
      redirectResultChecked = true;
      void getRedirectResult(auth).catch(() => {
        // Redirect errors surface cleanly through auth state / retry UI without stalling boot
      });
    }
    let authSeq = 0;
    unsubscribeInner = onAuthStateChanged(auth, async (fbUser: User | null) => {
      const seq = ++authSeq;
      if (!fbUser) {
        const hadPrevUser = Boolean(activeAuthUid);
        activeAuthUid = null;
        geminiKeyCache = null;
        glossaryEntriesCache.clear();
        if (hadPrevUser) {
          clearLocalUserCaches();
        }
        onChange(null, null);
        return;
      }
      if (fbUser.isAnonymous) {
        activeAuthUid = null;
        await signOut(auth).catch(() => { });
        if (seq === authSeq) onChange(null, 'ACCOUNT_RESTRICTED');
        return;
      }
      let claims: Record<string, unknown> = {};
      try {
        const tokenRes = await fbUser.getIdTokenResult();
        claims = tokenRes.claims;
      } catch {
        // Offline token refresh fallback: continue with verified Google email if present
      }
      if (seq !== authSeq) return;
      const isPaired = claims.paired === true || claims.owner === true;
      const isVerifiedEmail = fbUser.emailVerified === true;
      if (!isPaired && !isVerifiedEmail) {
        activeAuthUid = null;
        await signOut(auth).catch(() => { });
        if (seq === authSeq) onChange(null, 'ACCOUNT_RESTRICTED');
        return;
      }
      if (
        ALLOWED_EMAIL_SET &&
        !isPaired &&
        (!fbUser.email || !ALLOWED_EMAIL_SET.has(fbUser.email.toLowerCase()))
      ) {
        activeAuthUid = null;
        await signOut(auth).catch(() => { });
        if (seq === authSeq) onChange(null, 'ACCOUNT_RESTRICTED');
        return;
      }
      if (activeAuthUid && activeAuthUid !== fbUser.uid) {
        geminiKeyCache = null;
        glossaryEntriesCache.clear();
        clearLocalUserCaches();
      }
      activeAuthUid = fbUser.uid;
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
  };

  void bootstrapFirebaseConfig().finally(attachListener);
  return () => {
    cancelled = true;
    unsubscribeInner?.();
  };
}

export async function loginWithGoogle(): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.user = {
      uid: 'demo-user-1',
      email: DEMO_E2E_EMAIL,
      displayName: 'Demo Reader',
      getIdToken: async () => 'valid-owner-token',
    };
    store.emit();
    return;
  }
  if (googleSignInInFlight) {
    return googleSignInInFlight;
  }
  const { auth } = ensureFirebaseAuth();
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: 'select_account' });
  googleSignInInFlight = (async () => {
    try {
      await signInWithPopup(auth, provider);
    } catch (err: unknown) {
      const code = (err as { code?: string })?.code || '';
      if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') {
        return;
      }
      if (
        code === 'auth/popup-blocked' ||
        code === 'auth/operation-not-supported-in-this-environment'
      ) {
        await signInWithRedirect(auth, provider);
        return;
      }
      throw err;
    } finally {
      googleSignInInFlight = null;
    }
  })();
  return googleSignInInFlight;
}

export async function loginWithCustomPairToken(customToken: string): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.user = {
      uid: 'demo-user-1',
      email: DEMO_E2E_EMAIL,
      displayName: 'Paired Device',
      getIdToken: async () => 'valid-paired-token',
    };
    store.emit();
    return;
  }
  const { auth } = ensureFirebaseAuth();
  await signInWithCustomToken(auth, customToken);
}

export async function logoutSession(): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.user = null;
    store.emit();
    return;
  }
  await bootstrapFirebaseConfig();
  const { auth } = ensureFirebaseAuth();
  activeAuthUid = null;
  geminiKeyCache = null;
  glossaryEntriesCache.clear();
  clearLocalUserCaches();
  await signOut(auth);
  // Shared-device privacy: terminate and purge Firestore IndexedDB persistence cache cleanly if initialized
  if (fbDb) {
    try {
      const oldDb = fbDb;
      fbDb = null;
      const fs = await loadFirestoreMod();
      await fs.terminate(oldDb);
      await fs.clearIndexedDbPersistence(oldDb);
    } catch {
      // Multi-tab contention can defer persistence clear safely
    }
  }
}

export function subscribeSettings(onData: (settings: AppSettingsDoc) => void): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => onData({ ...store.settings }));
  }
  if (!getActiveUid()) {
    onData({ ...DEFAULT_SETTINGS });
    return () => { };
  }
  let cancelled = false;
  let unsubInner: (() => void) | null = null;
  void ensureFirestore()
    .then(({ db, fs }) => {
      if (cancelled || !getActiveUid()) return;
      unsubInner = fs.onSnapshot(
        userDoc(fs, db, 'settings', 'app'),
        (snap) => {
          if (!snap.exists()) {
            onData({ ...DEFAULT_SETTINGS });
            return;
          }
          const d = snap.data();
          const src = ['auto', 'ja', 'id', 'en'].includes(d.defaultSource)
            ? (d.defaultSource as SourceLang)
            : DEFAULT_SETTINGS.defaultSource;
          const tgt = ['id', 'en', 'ja'].includes(d.defaultTarget)
            ? (d.defaultTarget as TargetLang)
            : DEFAULT_SETTINGS.defaultTarget;
          onData({
            llmModels: Array.isArray(d.llmModels) ? d.llmModels : DEFAULT_SETTINGS.llmModels,
            reasoningEffort: d.reasoningEffort || DEFAULT_SETTINGS.reasoningEffort,
            chatMaxChars: Number(d.chatMaxChars || DEFAULT_SETTINGS.chatMaxChars),
            longMaxChars: Number(d.longMaxChars || DEFAULT_SETTINGS.longMaxChars),
            maxUploadMb: Number(d.maxUploadMb || DEFAULT_SETTINGS.maxUploadMb),
            dailyCharCap: Number(d.dailyCharCap || DEFAULT_SETTINGS.dailyCharCap),
            dailyCallCap: Number(d.dailyCallCap || DEFAULT_SETTINGS.dailyCallCap),
            defaultSource: src,
            defaultTarget: tgt,
            uiLang: d.uiLang === 'en' ? 'en' : 'id',
            theme: d.theme === 'dark' || d.theme === 'system' ? d.theme : 'light',
            translationTone:
              d.translationTone === 'novel' ||
                d.translationTone === 'casual' ||
                d.translationTone === 'formal'
                ? d.translationTone
                : 'auto',
            ...(d.ebookPrefs && typeof d.ebookPrefs === 'object' ? { ebookPrefs: d.ebookPrefs } : {}),
          });
        },
        () => onData({ ...DEFAULT_SETTINGS })
      );
    })
    .catch(() => {
      if (!cancelled) onData({ ...DEFAULT_SETTINGS });
    });
  return () => {
    cancelled = true;
    unsubInner?.();
  };
}

export async function updateAppSettings(patch: Partial<AppSettingsDoc>): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.settings = { ...store.settings, ...patch };
    store.emit();
    return;
  }
  const { db, fs } = await ensureFirestore();
  await fs.setDoc(
    userDoc(fs, db, 'settings', 'app'),
    { ...patch, updatedAt: fs.serverTimestamp() },
    { merge: true }
  );
}

let geminiKeyCache: { value: string; checkedAt: number } | null = null;
let geminiKeyInFlight: Promise<string> | null = null;
const GEMINI_KEY_CACHE_TTL_MS = 5 * 60 * 1000;

export async function getOwnerGeminiKey(): Promise<string> {
  if (isLocalE2EMode()) {
    return getE2EStore().geminiKey;
  }
  if (!getActiveUid()) return '';
  if (geminiKeyCache && Date.now() - geminiKeyCache.checkedAt < GEMINI_KEY_CACHE_TTL_MS) {
    return geminiKeyCache.value;
  }
  if (geminiKeyInFlight) return geminiKeyInFlight;
  geminiKeyInFlight = (async () => {
    try {
      const { db, fs } = await ensureFirestore();
      const snap = await fs.getDoc(userDoc(fs, db, 'settings', 'secrets'));
      const val = snap.exists() ? String(snap.data().geminiApiKey || '').trim() : '';
      geminiKeyCache = { value: val, checkedAt: Date.now() };
      return val;
    } catch {
      return geminiKeyCache?.value || '';
    } finally {
      geminiKeyInFlight = null;
    }
  })();
  return geminiKeyInFlight;
}

export async function setOwnerGeminiKey(apiKey: string): Promise<void> {
  const clean = apiKey.trim();
  if (isLocalE2EMode()) {
    getE2EStore().geminiKey = clean;
    return;
  }
  const { db, fs } = await ensureFirestore();
  const ref = userDoc(fs, db, 'settings', 'secrets');
  geminiKeyCache = { value: clean.slice(0, 512), checkedAt: Date.now() };
  if (!clean) {
    await fs.deleteDoc(ref).catch(() => { });
    return;
  }
  await fs.setDoc(ref, {
    geminiApiKey: clean.slice(0, 512),
    updatedAt: fs.serverTimestamp(),
  });
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
  if (!getActiveUid()) {
    onData([]);
    return () => { };
  }
  let cancelled = false;
  let unsubInner: (() => void) | null = null;
  void ensureFirestore()
    .then(({ db, fs }) => {
      if (cancelled || !getActiveUid()) return;
      const q = fs.query(userCollection(fs, db, 'conversations'), fs.orderBy('updatedAt', 'desc'));
      unsubInner = fs.onSnapshot(
        q,
        (snap) => {
          const items: ConversationDoc[] = snap.docs.map((d) => {
            const raw = d.data();
            return {
              id: d.id,
              title: String(raw.title || 'Percakapan baru'),
              titleId: String(raw.titleId || ''),
              mode: normalizeModePair(raw.mode, 'auto-id'),
              detectedSource: ['ja', 'id', 'en'].includes(raw.detectedSource)
                ? (raw.detectedSource as TargetLang)
                : '',
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
    })
    .catch(() => {
      if (!cancelled) onData([]);
    });
  return () => {
    cancelled = true;
    unsubInner?.();
  };
}

export async function upsertConversationMeta(
  cid: string,
  data: {
    title: string;
    titleId?: string;
    mode: ModePair;
    detectedSource?: TargetLang | '';
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
      detectedSource: data.detectedSource ?? cur?.detectedSource ?? '',
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
  const { db, fs } = await ensureFirestore();
  const ref = userDoc(fs, db, 'conversations', cid);
  const snap = await fs.getDoc(ref);
  if (!snap.exists()) {
    await fs.setDoc(ref, {
      title: data.title.slice(0, 500),
      titleId: data.titleId || '',
      mode: data.mode,
      detectedSource: data.detectedSource || '',
      activeTab: data.activeTab,
      pinned: data.pinned ?? false,
      pinnedAt: data.pinnedAt ? fs.Timestamp.fromMillis(data.pinnedAt) : null,
      preview: (data.preview || '').slice(0, 2000),
      createdAt: fs.serverTimestamp(),
      updatedAt: fs.serverTimestamp(),
    });
  } else {
    const patch: Record<string, unknown> = {
      mode: data.mode,
      activeTab: data.activeTab,
      updatedAt: fs.serverTimestamp(),
    };
    if (data.title) patch.title = data.title.slice(0, 500);
    if (data.titleId !== undefined) patch.titleId = data.titleId;
    if (data.detectedSource !== undefined) patch.detectedSource = data.detectedSource;
    if (data.pinned !== undefined) patch.pinned = data.pinned;
    if (data.pinnedAt !== undefined) {
      patch.pinnedAt = data.pinnedAt ? fs.Timestamp.fromMillis(data.pinnedAt) : null;
    }
    if (data.preview !== undefined) patch.preview = data.preview.slice(0, 2000);
    await fs.updateDoc(ref, patch as UpdateData<DocumentData>);
  }
}

export async function saveTurnMessageDirect(
  cid: string,
  mid: string,
  turn: Omit<TurnMessage, 'id' | 'createdAt'>
): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const bucket = store.messages.get(cid) ?? new Map<string, TurnMessage>();
    const prev = bucket.get(mid);
    bucket.set(mid, {
      ...prev,
      ...turn,
      id: mid,
      createdAt: prev?.createdAt ?? Date.now(),
    });
    store.messages.set(cid, bucket);
    store.emit();
    return;
  }
  const { db, fs } = await ensureFirestore();
  const ref = userDoc(fs, db, 'conversations', cid, 'messages', mid);
  const snap = await fs.getDoc(ref);
  const cleanPayload: Record<string, unknown> = {
    role: turn.role,
    kind: turn.kind,
    mode: turn.mode,
    text: (turn.text || '').slice(0, 240000),
    state: turn.state,
    updatedAt: fs.serverTimestamp(),
  };
  if (turn.detectedSource) cleanPayload.detectedSource = turn.detectedSource;
  if (turn.titleId) cleanPayload.titleId = turn.titleId;
  if (turn.srcText !== undefined) cleanPayload.srcText = turn.srcText.slice(0, 240000);
  if (turn.sentences) cleanPayload.sentences = turn.sentences.slice(0, 500);
  if (turn.nameChips) cleanPayload.nameChips = turn.nameChips.slice(0, 50);
  if (turn.fileName) cleanPayload.fileName = turn.fileName.slice(0, 500);
  if (turn.fmt) cleanPayload.fmt = turn.fmt;
  if (turn.jobId) cleanPayload.jobId = turn.jobId;
  if (turn.done !== undefined) cleanPayload.done = turn.done;
  if (turn.total !== undefined) cleanPayload.total = turn.total;
  if (turn.imageResult) {
    // Store blocks & text without multi-MB base64 dataUrl if large (stays well under Firestore 1 MiB cap)
    const { dataUrl, blocks, ...restImg } = turn.imageResult;
    const boundedBlocks = Array.isArray(blocks) ? blocks.slice(0, 250) : [];
    cleanPayload.imageResult =
      dataUrl && dataUrl.length < 400000
        ? { ...restImg, blocks: boundedBlocks, dataUrl }
        : { ...restImg, blocks: boundedBlocks };
  }
  if (turn.linkPreview) {
    const lp = { ...turn.linkPreview };
    if (lp.novelNav && Array.isArray(lp.novelNav.chapters) && lp.novelNav.chapters.length > 80) {
      const idx = lp.novelNav.chapters.findIndex((c) => c.current);
      const start = idx >= 0 ? Math.max(0, Math.min(idx - 25, lp.novelNav.chapters.length - 80)) : 0;
      lp.novelNav = {
        ...lp.novelNav,
        chapters: lp.novelNav.chapters.slice(start, start + 80),
      };
    }
    if (lp.firstImageResult) {
      const { dataUrl, blocks, ...restFirstImg } = lp.firstImageResult;
      const boundedBlocks = Array.isArray(blocks) ? blocks.slice(0, 250) : [];
      lp.firstImageResult =
        dataUrl && dataUrl.length < 400000
          ? { ...restFirstImg, blocks: boundedBlocks, dataUrl }
          : { ...restFirstImg, blocks: boundedBlocks };
    }
    if (lp.comicMeta && Array.isArray(lp.comicMeta.pages) && lp.comicMeta.pages.length > 120) {
      lp.comicMeta = {
        ...lp.comicMeta,
        pages: lp.comicMeta.pages.slice(0, 120),
      };
    }
    cleanPayload.linkPreview = stripUndefinedDeep(lp);
  }
  if (turn.model) cleanPayload.model = turn.model;
  if (turn.ms !== undefined) cleanPayload.ms = turn.ms;
  if (turn.error) cleanPayload.error = turn.error.slice(0, 1000);

  const firestoreSafePayload = stripUndefinedDeep(cleanPayload);

  if (!snap.exists()) {
    firestoreSafePayload.createdAt = fs.serverTimestamp();
    await fs.setDoc(ref, firestoreSafePayload);
  } else {
    await fs.updateDoc(ref, firestoreSafePayload as UpdateData<DocumentData>);
  }
}

export async function deleteConversationDirect(cid: string): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.conversations.delete(cid);
    store.messages.delete(cid);
    store.emit();
    return;
  }
  const { db, fs } = await ensureFirestore();
  const msgCol = userCollection(fs, db, 'conversations', cid, 'messages');
  const msgs = await fs.getDocs(msgCol);
  for (const m of msgs.docs) {
    const paras = await fs.getDocs(userCollection(fs, db, 'conversations', cid, 'messages', m.id, 'paras'));
    for (const p of paras.docs) {
      await fs.deleteDoc(p.ref).catch(() => { });
    }
    await fs.deleteDoc(m.ref).catch(() => { });
  }
  await fs.deleteDoc(userDoc(fs, db, 'conversations', cid));
}

export async function toggleConversationPin(
  conv: ConversationDoc,
  pinned: boolean
): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const cur = store.conversations.get(conv.id);
    if (cur) {
      store.conversations.set(conv.id, {
        ...cur,
        pinned,
        pinnedAt: pinned ? Date.now() : null,
        updatedAt: Date.now(),
      });
      store.emit();
    }
    return;
  }
  const { db, fs } = await ensureFirestore();
  await fs.updateDoc(userDoc(fs, db, 'conversations', conv.id), {
    pinned,
    pinnedAt: pinned ? fs.serverTimestamp() : null,
    updatedAt: fs.serverTimestamp(),
  });
}

export async function renameConversationTitle(cid: string, title: string): Promise<void> {
  const clean = title.trim().slice(0, 500);
  if (!clean) return;
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const cur = store.conversations.get(cid);
    if (cur) {
      store.conversations.set(cid, {
        ...cur,
        title: clean,
        updatedAt: Date.now(),
      });
      store.emit();
    }
    return;
  }
  const { db, fs } = await ensureFirestore();
  await fs.updateDoc(userDoc(fs, db, 'conversations', cid), {
    title: clean,
    updatedAt: fs.serverTimestamp(),
  });
}

export function subscribeMessages(
  cid: string,
  onData: (items: TurnMessage[]) => void
): () => void {
  if (!cid) {
    onData([]);
    return () => { };
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
  if (!getActiveUid()) {
    onData([]);
    return () => { };
  }
  let cancelled = false;
  let unsubInner: (() => void) | null = null;
  void ensureFirestore()
    .then(({ db, fs }) => {
      if (cancelled || !getActiveUid()) return;
      const q = fs.query(
        userCollection(fs, db, 'conversations', cid, 'messages'),
        fs.orderBy('createdAt', 'asc')
      );
      unsubInner = fs.onSnapshot(
        q,
        (snap) => {
          const items: TurnMessage[] = snap.docs.map((d) => {
            const raw = d.data();
            return {
              id: d.id,
              role: raw.role === 'user' ? 'user' : 'assistant',
              kind: raw.kind || 'text',
              mode: normalizeModePair(raw.mode, 'auto-id'),
              detectedSource: ['ja', 'id', 'en'].includes(raw.detectedSource)
                ? (raw.detectedSource as TargetLang)
                : undefined,
              titleId: raw.titleId,
              text: String(raw.text || ''),
              srcText: raw.srcText,
              sentences: raw.sentences,
              nameChips: raw.nameChips,
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
    })
    .catch(() => {
      if (!cancelled) onData([]);
    });
  return () => {
    cancelled = true;
    unsubInner?.();
  };
}

export function subscribeTitles(onData: (titles: TitleDoc[]) => void): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => {
      onData(Array.from(store.titles.values()).filter((t) => !t.mergedInto));
    });
  }
  if (!getActiveUid()) {
    onData([]);
    return () => { };
  }
  let cancelled = false;
  let unsubInner: (() => void) | null = null;
  void ensureFirestore()
    .then(({ db, fs }) => {
      if (cancelled || !getActiveUid()) return;
      unsubInner = fs.onSnapshot(
        userCollection(fs, db, 'titles'),
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
    })
    .catch(() => {
      if (!cancelled) onData([]);
    });
  return () => {
    cancelled = true;
    unsubInner?.();
  };
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
  const { db, fs } = await ensureFirestore();
  const ref = userDoc(fs, db, 'titles', titleId);
  const snap = await fs.getDoc(ref);
  await fs.setDoc(
    ref,
    {
      name: payload.name.trim().slice(0, 300),
      kind: payload.kind,
      style: payload.style,
      notes: (payload.notes || '').slice(0, 5000),
      ...(snap.exists() ? {} : { createdAt: fs.serverTimestamp() }),
      updatedAt: fs.serverTimestamp(),
    },
    { merge: true }
  );
}

function mapGlossaryDoc(r: Record<string, unknown>): GlossaryEntry {
  return {
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
  };
}

const glossaryEntriesCache = new Map<string, { entries: GlossaryEntry[]; checkedAt: number }>();
const glossaryEntriesInFlight = new Map<string, Promise<GlossaryEntry[]>>();
const GLOSSARY_CACHE_TTL_MS = 3 * 60 * 1000;

export async function loadGlossaryEntriesOnce(titleId?: string): Promise<GlossaryEntry[]> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const bySurface = new Map<string, GlossaryEntry>();
    if (titleId) {
      const primary = store.glossaries.get(titleId);
      if (primary) {
        for (const entry of primary.values()) {
          if (entry.surface) bySurface.set(entry.surface, entry);
        }
      }
    }
    for (const [tid, gmap] of store.glossaries.entries()) {
      if (tid === titleId) continue;
      for (const entry of gmap.values()) {
        if (entry.surface && entry.confirmed && !bySurface.has(entry.surface)) {
          bySurface.set(entry.surface, entry);
        }
      }
    }
    return Array.from(bySurface.values());
  }

  const cacheKey = titleId || '__default__';
  const hit = glossaryEntriesCache.get(cacheKey);
  if (hit && Date.now() - hit.checkedAt < GLOSSARY_CACHE_TTL_MS) {
    return hit.entries;
  }
  const inflight = glossaryEntriesInFlight.get(cacheKey);
  if (inflight) return inflight;

  const task = (async (): Promise<GlossaryEntry[]> => {
    try {
      if (!getActiveUid()) return [];
      const { db, fs } = await ensureFirestore();
      const bySurface = new Map<string, GlossaryEntry>();

      let effectiveTitleId: string | undefined = titleId;
      if (effectiveTitleId) {
        const seen = new Set<string>();
        while (effectiveTitleId && !seen.has(effectiveTitleId) && seen.size < 5) {
          seen.add(effectiveTitleId);
          const tSnap = await fs.getDoc(userDoc(fs, db, 'titles', effectiveTitleId));
          const tData = tSnap.exists() ? (tSnap.data() as { mergedInto?: unknown }) : null;
          const mergedInto: string = tData?.mergedInto ? String(tData.mergedInto).trim() : '';
          if (mergedInto) {
            effectiveTitleId = mergedInto;
          } else {
            break;
          }
        }
      }

      // Parallelize title glossary + default glossary in a single round-trip
      const [primarySnap, defSnap] = await Promise.all([
        effectiveTitleId
          ? fs.getDocs(userCollection(fs, db, 'titles', effectiveTitleId, 'glossary'))
          : Promise.resolve(null),
        effectiveTitleId !== 't_default'
          ? fs.getDocs(userCollection(fs, db, 'titles', 't_default', 'glossary'))
          : Promise.resolve(null),
      ]);

      if (primarySnap) {
        for (const d of primarySnap.docs) {
          const entry = mapGlossaryDoc(d.data());
          if (entry.surface) bySurface.set(entry.surface, entry);
        }
      }
      if (defSnap) {
        for (const d of defSnap.docs) {
          const entry = mapGlossaryDoc(d.data());
          if (entry.surface && entry.confirmed && !bySurface.has(entry.surface)) {
            bySurface.set(entry.surface, entry);
          }
        }
      }
      const list = Array.from(bySurface.values());
      glossaryEntriesCache.set(cacheKey, { entries: list, checkedAt: Date.now() });
      return list;
    } catch {
      return hit?.entries || [];
    } finally {
      glossaryEntriesInFlight.delete(cacheKey);
    }
  })();

  glossaryEntriesInFlight.set(cacheKey, task);
  return task;
}

export function subscribeGlossary(
  titleId: string,
  onData: (entries: Array<{ key: string; entry: GlossaryEntry }>) => void
): () => void {
  if (!titleId) {
    onData([]);
    return () => { };
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
  if (!getActiveUid()) {
    onData([]);
    return () => { };
  }
  let cancelled = false;
  let unsubInner: (() => void) | null = null;
  void ensureFirestore()
    .then(({ db, fs }) => {
      if (cancelled || !getActiveUid()) return;
      unsubInner = fs.onSnapshot(
        userCollection(fs, db, 'titles', titleId, 'glossary'),
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
    })
    .catch(() => {
      if (!cancelled) onData([]);
    });
  return () => {
    cancelled = true;
    unsubInner?.();
  };
}

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
  const { db, fs } = await ensureFirestore();
  const titleRef = userDoc(fs, db, 'titles', titleId);
  const titleSnap = await fs.getDoc(titleRef);
  if (!titleSnap.exists()) {
    await fs.setDoc(titleRef, {
      name: 'Percakapan',
      kind: 'lepas',
      style: { ...DEFAULT_STYLE },
      createdAt: fs.serverTimestamp(),
      updatedAt: fs.serverTimestamp(),
    });
  }
  await fs.setDoc(userDoc(fs, db, 'titles', titleId, 'glossary', key), {
    ...fullEntry,
    updatedAt: fs.serverTimestamp(),
  });
  glossaryEntriesCache.clear();
}

export async function removeGlossaryEntry(titleId: string, key: string): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.glossaries.get(titleId)?.delete(key);
    store.emit();
    return;
  }
  const { db, fs } = await ensureFirestore();
  await fs.deleteDoc(userDoc(fs, db, 'titles', titleId, 'glossary', key));
  glossaryEntriesCache.clear();
}

export function subscribeJobs(onData: (jobs: JobDoc[]) => void): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => {
      onData(Array.from(store.jobs.values()).sort((a, b) => b.updatedAt - a.updatedAt));
    });
  }
  if (!getActiveUid()) {
    onData([]);
    return () => { };
  }
  let cancelled = false;
  let unsubInner: (() => void) | null = null;
  void ensureFirestore()
    .then(({ db, fs }) => {
      if (cancelled || !getActiveUid()) return;
      unsubInner = fs.onSnapshot(
        userCollection(fs, db, 'jobs'),
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
    })
    .catch(() => {
      if (!cancelled) onData([]);
    });
  return () => {
    cancelled = true;
    unsubInner?.();
  };
}

export async function saveDirectJobRecord(job: JobDoc): Promise<void> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.jobs.set(job.id, job);
    store.emit();
    return;
  }
  const { db, fs } = await ensureFirestore();
  const ref = userDoc(fs, db, 'jobs', job.id);
  const snap = await fs.getDoc(ref);
  if (!snap.exists()) {
    await fs.setDoc(ref, {
      state: job.state === 'done' || job.state === 'running' ? job.state : 'running',
      fileSize: Math.max(1, job.fileSize),
      fileName: job.fileName.slice(0, 500),
      fmt: (job.fmt || '').slice(0, 32),
      cid: job.cid,
      mid: job.mid,
      titleId: job.titleId || '',
      doneParas: job.doneParas ?? 0,
      totalParas: job.totalParas ?? 0,
      updatedAt: fs.serverTimestamp(),
    });
  } else {
    await fs.updateDoc(ref, {
      state: job.state === 'uploading' ? 'running' : job.state,
      doneParas: job.doneParas ?? 0,
      totalParas: job.totalParas ?? 0,
      ...(job.message ? { message: job.message.slice(0, 1000) } : {}),
      updatedAt: fs.serverTimestamp(),
    });
  }
}

export function subscribeInbox(onData: (items: InboxItem[]) => void): () => void {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    return store.subscribe(() => onData(Array.from(store.inbox.values())));
  }
  if (!getActiveUid()) {
    onData([]);
    return () => { };
  }
  let cancelled = false;
  let unsubInner: (() => void) | null = null;
  void ensureFirestore()
    .then(({ db, fs }) => {
      if (cancelled || !getActiveUid()) return;
      unsubInner = fs.onSnapshot(
        userCollection(fs, db, 'inbox'),
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
    })
    .catch(() => {
      if (!cancelled) onData([]);
    });
  return () => {
    cancelled = true;
    unsubInner?.();
  };
}

export async function deleteInboxItemDirect(inboxId: string): Promise<void> {
  if (!inboxId) return;
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    store.inbox.delete(inboxId);
    store.emit();
    return;
  }
  if (!getActiveUid()) return;
  const { db, fs } = await ensureFirestore();
  await fs.deleteDoc(userDoc(fs, db, 'inbox', inboxId));
}

function sanitizeStorageLeafName(rawName: string): string {
  const leaf = rawName.split(/[\\/]/).pop() || 'document.txt';
  const dotIdx = leaf.lastIndexOf('.');
  const rawStem = dotIdx > 0 ? leaf.slice(0, dotIdx) : leaf;
  const rawExt = dotIdx > 0 ? leaf.slice(dotIdx + 1).toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 12) : '';
  const safeStem = rawStem.replace(/[^A-Za-z0-9_-]/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '').slice(0, 120) || 'file';
  return rawExt ? `${safeStem}.${rawExt}` : safeStem;
}

export async function uploadDocumentToCloudStorage(params: {
  uid: string;
  cid: string;
  mid: string;
  mode: ModePair;
  titleId?: string;
  file: File;
  onProgress?: (pct: number) => void;
}): Promise<string> {
  const jobId = `job_${Date.now().toString(36)}`;
  const safeLeaf = sanitizeStorageLeafName(params.file.name);
  const storagePath = `uploads/${params.uid}/${jobId}/${safeLeaf}`;
  const [{ db, fs }, { storage, mod }] = await Promise.all([
    ensureFirestore(),
    ensureFirebaseStorage(),
  ]);
  const jobRef = fs.doc(db, 'users', params.uid, 'jobs', jobId);

  await fs.setDoc(jobRef, {
    state: 'uploading',
    fileSize: Math.max(1, params.file.size),
    fileName: params.file.name.slice(0, 500),
    storagePath,
    mimeType: (params.file.type || 'application/octet-stream').slice(0, 200),
    cid: params.cid,
    mid: params.mid,
    mode: params.mode,
    titleId: params.titleId || '',
    updatedAt: fs.serverTimestamp(),
  });

  await new Promise<void>((resolve, reject) => {
    const task = mod.uploadBytesResumable(mod.ref(storage, storagePath), params.file, {
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

  // Transition uploading -> queued atomically so fast Storage triggers that already reached running/done are never overwritten
  await fs.runTransaction(db, async (txn) => {
    const cur = await txn.get(jobRef);
    if (cur.exists() && cur.data()?.state === 'uploading') {
      txn.update(jobRef, {
        state: 'queued',
        updatedAt: fs.serverTimestamp(),
      });
    }
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
  const { db, fs } = await ensureFirestore();
  await fs.updateDoc(userDoc(fs, db, 'jobs', jobId), {
    state: 'stopped',
    updatedAt: fs.serverTimestamp(),
  });
}

export async function resolveStorageOutputUrl(storageOutputPath: string): Promise<string> {
  if (isLocalE2EMode()) {
    const blob = new Blob(['1\n00:00:01,000 --> 00:00:03,000\nChihaya tersenyum kecil.\n'], {
      type: 'text/plain;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    return url;
  }
  const { storage, mod } = await ensureFirebaseStorage();
  return mod.getDownloadURL(mod.ref(storage, storageOutputPath));
}

export async function loadTurnMessageOnce(
  cid: string,
  mid: string
): Promise<{ sentences?: SentencePair[]; text?: string; fileName?: string } | null> {
  if (!cid || !mid) return null;
  if (isLocalE2EMode()) {
    const msg = getE2EStore().messages.get(cid)?.get(mid);
    if (!msg) return null;
    return { sentences: msg.sentences, text: msg.text, fileName: msg.fileName };
  }
  try {
    if (!getActiveUid()) return null;
    const { db, fs } = await ensureFirestore();
    const snap = await fs.getDoc(userDoc(fs, db, 'conversations', cid, 'messages', mid));
    if (!snap.exists()) return null;
    const r = snap.data();
    const sentences = Array.isArray(r.sentences)
      ? (r.sentences as SentencePair[])
      : undefined;
    return {
      sentences,
      text: typeof r.text === 'string' ? r.text : undefined,
      fileName: typeof r.fileName === 'string' ? r.fileName : undefined,
    };
  } catch {
    return null;
  }
}

export async function mergeTitleGlossariesDirect(
  fromTitleId: string,
  toTitleId: string
): Promise<{ merged: number; conflicts: string[] }> {
  if (!fromTitleId || !toTitleId || fromTitleId === toTitleId) {
    return { merged: 0, conflicts: [] };
  }
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const src = store.glossaries.get(fromTitleId);
    const dst = store.glossaries.get(toTitleId) ?? new Map();
    let merged = 0;
    const conflicts: string[] = [];
    if (src) {
      for (const [k, v] of src.entries()) {
        if (!dst.has(k)) {
          dst.set(k, v);
          merged += 1;
        } else {
          conflicts.push(v.surface);
        }
      }
    }
    store.glossaries.set(toTitleId, dst);
    const fromDoc = store.titles.get(fromTitleId);
    if (fromDoc) fromDoc.mergedInto = toTitleId;
    for (const conv of store.conversations.values()) {
      if (conv.titleId === fromTitleId) {
        conv.titleId = toTitleId;
      }
    }
    store.emit();
    return { merged, conflicts };
  }
  const { db, fs } = await ensureFirestore();
  const [srcSnap, dstSnap, convsSnap] = await Promise.all([
    fs.getDocs(userCollection(fs, db, 'titles', fromTitleId, 'glossary')),
    fs.getDocs(userCollection(fs, db, 'titles', toTitleId, 'glossary')),
    fs.getDocs(fs.query(userCollection(fs, db, 'conversations'), fs.where('titleId', '==', fromTitleId))),
  ]);
  const existingKeys = new Set(dstSnap.docs.map((d) => d.id));
  let merged = 0;
  const conflicts: string[] = [];
  for (const d of srcSnap.docs) {
    const raw = d.data();
    if (existingKeys.has(d.id)) {
      conflicts.push(String(raw.surface || d.id));
      continue;
    }
    const entry = mapGlossaryDoc(raw);
    await fs.setDoc(userDoc(fs, db, 'titles', toTitleId, 'glossary', d.id), {
      ...entry,
      confirmed: true,
      source: 'user',
      updatedAt: fs.serverTimestamp(),
    });
    merged += 1;
  }
  const fromRef = userDoc(fs, db, 'titles', fromTitleId);
  const fromDocSnap = await fs.getDoc(fromRef);
  if (fromDocSnap.exists()) {
    await fs.updateDoc(fromRef, {
      mergedInto: toTitleId.slice(0, 200),
      updatedAt: fs.serverTimestamp(),
    });
  }
  for (let start = 0; start < convsSnap.docs.length; start += 400) {
    const batch = fs.writeBatch(db);
    for (const c of convsSnap.docs.slice(start, start + 400)) {
      batch.update(c.ref, {
        titleId: toTitleId.slice(0, 200),
        updatedAt: fs.serverTimestamp(),
      });
    }
    await batch.commit();
  }
  glossaryEntriesCache.clear();
  return { merged, conflicts };
}

export async function exportFullBackupDirect(): Promise<Record<string, unknown>> {
  if (isLocalE2EMode()) {
    const store = getE2EStore();
    const conversations: Record<string, unknown> = {};
    for (const [cid, conv] of store.conversations.entries()) {
      const msgs = Array.from(store.messages.get(cid)?.values() || []);
      conversations[cid] = { ...conv, messages: msgs };
    }
    const titles: Record<string, unknown> = {};
    for (const [tid, tdoc] of store.titles.entries()) {
      const gloss = Object.fromEntries(store.glossaries.get(tid)?.entries() || []);
      titles[tid] = { ...tdoc, glossary: gloss };
    }
    return {
      version: '2.2',
      exportedAt: new Date().toISOString(),
      settings: store.settings,
      conversations,
      titles,
      jobs: Object.fromEntries(store.jobs.entries()),
    };
  }
  const { db, fs } = await ensureFirestore();
  const [settingsSnap, convsSnap, titlesSnap, jobsSnap] = await Promise.all([
    fs.getDoc(userDoc(fs, db, 'settings', 'app')),
    fs.getDocs(userCollection(fs, db, 'conversations')),
    fs.getDocs(userCollection(fs, db, 'titles')),
    fs.getDocs(userCollection(fs, db, 'jobs')),
  ]);
  const conversations: Record<string, unknown> = {};
  for (const c of convsSnap.docs) {
    const msgsSnap = await fs.getDocs(userCollection(fs, db, 'conversations', c.id, 'messages'));
    conversations[c.id] = {
      ...c.data(),
      messages: msgsSnap.docs.map((m) => ({ id: m.id, ...m.data() })),
    };
  }
  const titles: Record<string, unknown> = {};
  for (const t of titlesSnap.docs) {
    const gSnap = await fs.getDocs(userCollection(fs, db, 'titles', t.id, 'glossary'));
    const glossary: Record<string, unknown> = {};
    for (const g of gSnap.docs) glossary[g.id] = g.data();
    titles[t.id] = { ...t.data(), glossary };
  }
  const jobs: Record<string, unknown> = {};
  for (const j of jobsSnap.docs) jobs[j.id] = j.data();

  return {
    version: '2.2',
    exportedAt: new Date().toISOString(),
    settings: settingsSnap.exists() ? settingsSnap.data() : DEFAULT_SETTINGS,
    conversations,
    titles,
    jobs,
  };
}
