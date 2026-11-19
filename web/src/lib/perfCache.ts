/* Unified Persistent L2 Performance Cache (IndexedDB with silent fallback)
 * Gives Web and Installed Standalone PWA identical near-instant repeat loads,
 * chapter list persistence across app restarts, and non-blocking cache writes.
 */

const DB_NAME = 'tranx_perf_cache_v1';
const DB_VERSION = 1;

export type PerfStoreName = 'paras' | 'articles' | 'tocs';

interface StoredRecord<T = unknown> {
  k: string;
  v: T;
  t: number;
}

const STORE_LIMITS: Record<PerfStoreName, number> = {
  paras: 4000,
  articles: 24,
  tocs: 40,
};

let dbPromise: Promise<IDBDatabase | null> | null = null;
const pruneScheduled = new Set<PerfStoreName>();

function openPerfDb(): Promise<IDBDatabase | null> {
  if (typeof window === 'undefined' || typeof indexedDB === 'undefined') {
    return Promise.resolve(null);
  }
  if (dbPromise) return dbPromise;
  dbPromise = new Promise<IDBDatabase | null>((resolve) => {
    try {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        (['paras', 'articles', 'tocs'] as PerfStoreName[]).forEach((name) => {
          if (!db.objectStoreNames.contains(name)) {
            const store = db.createObjectStore(name, { keyPath: 'k' });
            store.createIndex('t', 't', { unique: false });
          }
        });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
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
  }, 4000);
}

async function pruneStore(storeName: PerfStoreName, maxEntries: number): Promise<void> {
  const db = await openPerfDb();
  if (!db) return;
  try {
    const tx = db.transaction(storeName, 'readwrite');
    const store = tx.objectStore(storeName);
    const countReq = store.count();
    countReq.onsuccess = () => {
      const excess = countReq.result - maxEntries;
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
  } catch {
    // Ignore background prune failures
  }
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
      const tx = db.transaction(storeName, 'readonly');
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
    } catch {
      resolve(undefined);
    }
  });
}

export async function idbPut<T>(
  storeName: PerfStoreName,
  key: string,
  value: T
): Promise<void> {
  const db = await openPerfDb();
  if (!db) return;
  try {
    const tx = db.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).put({ k: key, v: value, t: Date.now() } satisfies StoredRecord<T>);
    schedulePrune(storeName);
  } catch {
    // Ignore quota or private-mode failures
  }
}

export async function idbPutMany<T>(
  storeName: PerfStoreName,
  items: Array<[string, T]>
): Promise<void> {
  if (!items.length) return;
  const db = await openPerfDb();
  if (!db) return;
  try {
    const now = Date.now();
    const tx = db.transaction(storeName, 'readwrite');
    const store = tx.objectStore(storeName);
    for (const [k, v] of items) {
      store.put({ k, v, t: now } satisfies StoredRecord<T>);
    }
    schedulePrune(storeName);
  } catch {
    // Ignore quota or private-mode failures
  }
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
      const tx = db.transaction(storeName, 'readonly');
      const idx = tx.objectStore(storeName).index('t');
      const req = idx.openCursor(null, 'prev');
      req.onsuccess = () => {
        const cursor = req.result;
        if (!cursor || out.length >= limit) {
          resolve(out);
          return;
        }
        const rec = cursor.value as StoredRecord<T>;
        if (!cutoff || rec.t >= cutoff) {
          out.push([rec.k, rec.v]);
        }
        cursor.continue();
      };
      req.onerror = () => resolve(out);
    } catch {
      resolve([]);
    }
  });
}
