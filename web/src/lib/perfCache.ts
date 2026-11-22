/* Unified Persistent L2 Performance Cache (IndexedDB v2.5 with relaxed durability,
 * QuotaExceededError 50% self-healing prune, storage-pressure telemetry, and version-conflict recovery).
 */

const DB_NAME = 'tranx_perf_cache_v1';
const DB_VERSION = 2;

export type PerfStoreName = 'paras' | 'articles' | 'tocs';

interface StoredRecord<T = unknown> {
  k: string;
  v: T;
  t: number;
}

export interface StorageHealthSnapshot {
  usageBytes: number;
  quotaBytes: number;
  usageRatio: number;
  persisted: boolean;
  dbOpen: boolean;
  highPressure: boolean;
}

const STORE_LIMITS: Record<PerfStoreName, number> = {
  paras: 4000,
  articles: 24,
  tocs: 40,
};

let dbPromise: Promise<IDBDatabase | null> | null = null;
let activeDb: IDBDatabase | null = null;
let selfHealAttempted = false;
let persistenceRequested = false;
let lastStorageEstimateMs = 0;
const STORAGE_ESTIMATE_DEBOUNCE_MS = 5 * 60 * 1000;
const pruneScheduled = new Set<PerfStoreName>();

let cachedStorageSnapshot: StorageHealthSnapshot = {
  usageBytes: 0,
  quotaBytes: 0,
  usageRatio: 0,
  persisted: false,
  dbOpen: false,
  highPressure: false,
};

function openTransaction(
  db: IDBDatabase,
  storeName: PerfStoreName,
  mode: IDBTransactionMode
): IDBTransaction {
  if (mode === 'readwrite') {
    try {
      return db.transaction(storeName, 'readwrite', { durability: 'relaxed' });
    } catch {
      return db.transaction(storeName, 'readwrite');
    }
  }
  return db.transaction(storeName, mode);
}

function resetDbHandle(): void {
  if (activeDb) {
    try {
      activeDb.close();
    } catch {
      // ignore close errors
    }
    activeDb = null;
  }
  dbPromise = null;
  cachedStorageSnapshot = { ...cachedStorageSnapshot, dbOpen: false };
}

function maybeRequestStandalonePersistence(): void {
  if (persistenceRequested || typeof window === 'undefined' || typeof navigator === 'undefined') return;
  persistenceRequested = true;
  const isStandalone =
    window.matchMedia?.('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true;
  if (!isStandalone || !navigator.storage?.persist) return;
  void navigator.storage
    .persist()
    .then((granted) => {
      cachedStorageSnapshot = { ...cachedStorageSnapshot, persisted: Boolean(granted) };
    })
    .catch(() => { });
}

export async function refreshStorageHealthSnapshot(force = false): Promise<StorageHealthSnapshot> {
  if (typeof navigator === 'undefined' || !navigator.storage?.estimate) {
    return { ...cachedStorageSnapshot, dbOpen: Boolean(activeDb) };
  }
  const now = Date.now();
  if (!force && lastStorageEstimateMs > 0 && now - lastStorageEstimateMs < STORAGE_ESTIMATE_DEBOUNCE_MS) {
    return { ...cachedStorageSnapshot, dbOpen: Boolean(activeDb) };
  }
  lastStorageEstimateMs = now;
  try {
    const [est, persisted] = await Promise.all([
      navigator.storage.estimate(),
      navigator.storage.persisted ? navigator.storage.persisted().catch(() => false) : Promise.resolve(false),
    ]);
    const usage = Math.max(0, Number(est.usage || 0));
    const quota = Math.max(0, Number(est.quota || 0));
    const ratio = quota > 0 ? usage / quota : 0;
    cachedStorageSnapshot = {
      usageBytes: usage,
      quotaBytes: quota,
      usageRatio: Number(ratio.toFixed(4)),
      persisted: Boolean(persisted),
      dbOpen: Boolean(activeDb),
      highPressure: ratio >= 0.75,
    };
    if (ratio >= 0.75) {
      void emergencyHalfPruneAll();
    }
  } catch {
    // ignore browser estimate restrictions
  }
  return { ...cachedStorageSnapshot };
}

export function getStorageHealthSnapshot(): StorageHealthSnapshot {
  return { ...cachedStorageSnapshot, dbOpen: Boolean(activeDb) };
}

function openPerfDb(): Promise<IDBDatabase | null> {
  if (typeof window === 'undefined' || typeof indexedDB === 'undefined') {
    return Promise.resolve(null);
  }
  if (dbPromise) return dbPromise;
  maybeRequestStandalonePersistence();

  dbPromise = new Promise<IDBDatabase | null>((resolve) => {
    try {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (ev) => {
        const db = req.result;
        const oldVersion = ev.oldVersion || 0;
        (['paras', 'articles', 'tocs'] as PerfStoreName[]).forEach((name) => {
          if (!db.objectStoreNames.contains(name)) {
            const store = db.createObjectStore(name, { keyPath: 'k' });
            store.createIndex('t', 't', { unique: false });
          } else if (oldVersion > 0 && oldVersion < 2) {
            try {
              req.transaction?.objectStore(name).clear();
            } catch {
              // ignore clear errors during schema upgrade
            }
          }
        });
      };
      req.onsuccess = () => {
        const db = req.result;
        activeDb = db;
        cachedStorageSnapshot = { ...cachedStorageSnapshot, dbOpen: true };
        db.onversionchange = () => {
          resetDbHandle();
        };
        db.onclose = () => {
          resetDbHandle();
        };
        resolve(db);
      };
      req.onerror = () => {
        const errName = req.error?.name || '';
        dbPromise = null;
        activeDb = null;
        if (
          !selfHealAttempted &&
          (errName === 'VersionError' || errName === 'InvalidStateError' || errName === 'UnknownError')
        ) {
          selfHealAttempted = true;
          try {
            const delReq = indexedDB.deleteDatabase(DB_NAME);
            delReq.onsuccess = () => resolve(null);
            delReq.onerror = () => resolve(null);
            delReq.onblocked = () => resolve(null);
            return;
          } catch {
            // ignore delete failure
          }
        }
        resolve(null);
      };
      req.onblocked = () => {
        dbPromise = null;
        resolve(null);
      };
    } catch {
      dbPromise = null;
      resolve(null);
    }
  });
  return dbPromise;
}

function schedulePrune(storeName: PerfStoreName): void {
  if (pruneScheduled.has(storeName) || typeof window === 'undefined') return;
  pruneScheduled.add(storeName);
  window.setTimeout(() => {
    pruneScheduled.delete(storeName);
    void pruneStore(storeName, STORE_LIMITS[storeName]);
    void refreshStorageHealthSnapshot();
  }, 4000);
}

async function pruneStore(
  storeName: PerfStoreName,
  target: number | { ratio: number }
): Promise<void> {
  const db = await openPerfDb();
  if (!db) return;
  await new Promise<void>((resolve) => {
    try {
      const tx = openTransaction(db, storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      const countReq = store.count();
      countReq.onsuccess = () => {
        const total = countReq.result;
        const excess =
          typeof target === 'number'
            ? total - target
            : Math.ceil(total * Math.max(0.1, Math.min(0.9, target.ratio)));
        if (excess <= 0) return;
        let removed = 0;
        const idx = store.index('t');
        const curReq = idx.openCursor();
        curReq.onsuccess = () => {
          const cursor = curReq.result;
          if (!cursor || removed >= excess) return;
          cursor.delete();
          removed += 1;
          cursor.continue();
        };
      };
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}

async function emergencyHalfPruneAll(): Promise<void> {
  const targets: PerfStoreName[] = ['articles', 'tocs', 'paras'];
  for (const name of targets) {
    await pruneStore(name, { ratio: 0.5 });
  }
}

export async function clearPerfCacheDb(): Promise<void> {
  resetDbHandle();
  if (typeof window === 'undefined' || typeof indexedDB === 'undefined') return;
  await new Promise<void>((resolve) => {
    try {
      const req = indexedDB.deleteDatabase(DB_NAME);
      req.onsuccess = () => resolve();
      req.onerror = () => resolve();
      req.onblocked = () => resolve();
    } catch {
      resolve();
    }
  });
}

export async function idbGet<T>(
  storeName: PerfStoreName,
  key: string,
  maxAgeMs?: number
): Promise<T | undefined> {
  const db = await openPerfDb();
  if (!db) return undefined;
  return new Promise<T | undefined>((resolve) => {
    try {
      const tx = openTransaction(db, storeName, 'readonly');
      const req = tx.objectStore(storeName).get(key);
      req.onsuccess = () => {
        const rec = req.result as StoredRecord<T> | undefined;
        if (!rec) {
          resolve(undefined);
          return;
        }
        if (maxAgeMs && Date.now() - rec.t > maxAgeMs) {
          resolve(undefined);
          return;
        }
        resolve(rec.v);
      };
      req.onerror = () => resolve(undefined);
      tx.onabort = () => resolve(undefined);
    } catch {
      resetDbHandle();
      resolve(undefined);
    }
  });
}

export async function idbDelete(storeName: PerfStoreName, key: string): Promise<void> {
  const db = await openPerfDb();
  if (!db) return;
  await new Promise<void>((resolve) => {
    try {
      const tx = openTransaction(db, storeName, 'readwrite');
      tx.objectStore(storeName).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}

async function writeRecordsWithQuotaRetry<T>(
  storeName: PerfStoreName,
  items: Array<[string, T]>,
  allowRetry = true
): Promise<void> {
  const db = await openPerfDb();
  if (!db || items.length === 0) return;

  const outcome = await new Promise<'ok' | 'quota' | 'error'>((resolve) => {
    try {
      const now = Date.now();
      const tx = openTransaction(db, storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      for (const [k, v] of items) {
        store.put({ k, v, t: now } satisfies StoredRecord<T>);
      }
      tx.oncomplete = () => resolve('ok');
      tx.onabort = () => {
        const name = tx.error?.name || '';
        resolve(name === 'QuotaExceededError' ? 'quota' : 'error');
      };
      tx.onerror = () => {
        const name = tx.error?.name || '';
        resolve(name === 'QuotaExceededError' ? 'quota' : 'error');
      };
    } catch (err) {
      const name = (err as DOMException)?.name || '';
      if (name === 'InvalidStateError') resetDbHandle();
      resolve(name === 'QuotaExceededError' ? 'quota' : 'error');
    }
  });

  if (outcome === 'ok') {
    schedulePrune(storeName);
    return;
  }
  if (outcome === 'quota' && allowRetry) {
    cachedStorageSnapshot = { ...cachedStorageSnapshot, highPressure: true };
    await emergencyHalfPruneAll();
    await writeRecordsWithQuotaRetry(storeName, items, false);
  }
}

export async function idbPut<T>(
  storeName: PerfStoreName,
  key: string,
  value: T
): Promise<void> {
  await writeRecordsWithQuotaRetry(storeName, [[key, value]]);
}

export async function idbPutMany<T>(
  storeName: PerfStoreName,
  items: Array<[string, T]>
): Promise<void> {
  if (!items.length) return;
  await writeRecordsWithQuotaRetry(storeName, items);
}

export async function idbLoadRecent<T>(
  storeName: PerfStoreName,
  limit: number,
  maxAgeMs?: number
): Promise<Array<[string, T]>> {
  const db = await openPerfDb();
  if (!db) return [];
  return new Promise<Array<[string, T]>>((resolve) => {
    try {
      const out: Array<[string, T]> = [];
      const cutoff = maxAgeMs ? Date.now() - maxAgeMs : 0;
      const tx = openTransaction(db, storeName, 'readonly');
      const idx = tx.objectStore(storeName).index('t');
      const req = idx.openCursor(null, 'prev');
      req.onsuccess = () => {
        const cursor = req.result;
        if (!cursor || out.length >= limit) {
          resolve(out);
          return;
        }
        const rec = cursor.value as StoredRecord<T>;
        if (cutoff && rec.t < cutoff) {
          // Index 't' is traversed descending ('prev'), so all remaining records are strictly older
          resolve(out);
          return;
        }
        out.push([rec.k, rec.v]);
        cursor.continue();
      };
      req.onerror = () => resolve(out);
      tx.onabort = () => resolve(out);
    } catch {
      resolve([]);
    }
  });
}
