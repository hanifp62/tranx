import type { ModePair } from '../types';

/* Rich Reading Shelf ("Continue Reading"), Paragraph Resume & Bookmark Store
 * Extracted into a zero-TTS pure storage module so entry chunks never pull podcastNarrator.ts.
 */

const SHELF_STORAGE_KEY = 'tranx_ebook_shelf_v2';
const PARA_POS_STORAGE_KEY = 'tranx_ebook_para_pos_v1';
const BOOKMARK_STORAGE_KEY = 'tranx_ebook_bookmarks_v1';
const SHELF_MAX = 30;
const PARA_POS_MAX = 120;
const BOOKMARK_MAX = 150;

export interface RichReadingShelfItem {
  seriesKey: string;
  url: string;
  host: string;
  seriesTitle: string;
  titleDst: string;
  chapterLabel?: string;
  mode: ModePair;
  titleId?: string;
  paraIdx: number;
  totalParas: number;
  progressPct: number;
  updatedAt: number;
}

export interface EbookBookmarkItem {
  id: string;
  seriesKey: string;
  url: string;
  chapterLabel?: string;
  titleDst: string;
  paraIdx: number;
  excerpt: string;
  createdAt: number;
}

function safeReadJson<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(fallback)) {
      return (Array.isArray(parsed) ? parsed : fallback) as T;
    }
    if (fallback !== null && typeof fallback === 'object') {
      return (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
        ? parsed
        : fallback) as T;
    }
    return (parsed as T) ?? fallback;
  } catch {
    return fallback;
  }
}

function safeWriteJson(key: string, data: unknown): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, JSON.stringify(data));
  } catch {
    // ignore private-mode or quota limits
  }
}

export function saveRichReadingEntry(
  entry: Omit<RichReadingShelfItem, 'progressPct' | 'updatedAt'> & { updatedAt?: number }
): void {
  if (!entry.seriesKey || !entry.url) return;
  const total = Math.max(1, entry.totalParas || 1);
  const clampedPara = Math.max(0, Math.min(total - 1, entry.paraIdx || 0));
  const progressPct = Math.max(1, Math.min(100, Math.round(((clampedPara + 1) / total) * 100)));

  const store = safeReadJson<Record<string, RichReadingShelfItem>>(SHELF_STORAGE_KEY, {});
  store[entry.seriesKey] = {
    seriesKey: entry.seriesKey,
    url: entry.url,
    host: entry.host,
    seriesTitle: (entry.seriesTitle || entry.titleDst || entry.host).slice(0, 140),
    titleDst: (entry.titleDst || entry.seriesTitle || entry.host).slice(0, 140),
    ...(entry.chapterLabel ? { chapterLabel: entry.chapterLabel.slice(0, 40) } : {}),
    mode: entry.mode,
    ...(entry.titleId ? { titleId: entry.titleId } : {}),
    paraIdx: clampedPara,
    totalParas: total,
    progressPct,
    updatedAt: entry.updatedAt || Date.now(),
  };

  const keys = Object.keys(store);
  if (keys.length > SHELF_MAX) {
    keys
      .sort((a, b) => (store[a]?.updatedAt || 0) - (store[b]?.updatedAt || 0))
      .slice(0, keys.length - SHELF_MAX)
      .forEach((k) => {
        delete store[k];
      });
  }
  safeWriteJson(SHELF_STORAGE_KEY, store);

  // Also save exact per-chapter paragraph position
  saveChapterParaPos(entry.url, clampedPara);
}

export function listRecentReadings(limit = 6): RichReadingShelfItem[] {
  const store = safeReadJson<Record<string, RichReadingShelfItem>>(SHELF_STORAGE_KEY, {});
  return Object.values(store)
    .filter((item) => item && item.url && item.seriesKey)
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, limit);
}

export function removeRecentReading(seriesKey: string): void {
  if (!seriesKey) return;
  const store = safeReadJson<Record<string, RichReadingShelfItem>>(SHELF_STORAGE_KEY, {});
  if (store[seriesKey]) {
    delete store[seriesKey];
    safeWriteJson(SHELF_STORAGE_KEY, store);
  }
}

export function saveChapterParaPos(url: string, paraIdx: number): void {
  if (!url) return;
  const store = safeReadJson<Record<string, { p: number; t: number }>>(PARA_POS_STORAGE_KEY, {});
  store[url] = { p: Math.max(0, Math.floor(paraIdx)), t: Date.now() };
  const keys = Object.keys(store);
  if (keys.length > PARA_POS_MAX) {
    keys
      .sort((a, b) => (store[a]?.t || 0) - (store[b]?.t || 0))
      .slice(0, keys.length - PARA_POS_MAX)
      .forEach((k) => {
        delete store[k];
      });
  }
  safeWriteJson(PARA_POS_STORAGE_KEY, store);
}

export function getChapterParaPos(url: string): number {
  if (!url) return 0;
  const store = safeReadJson<Record<string, { p: number; t: number }>>(PARA_POS_STORAGE_KEY, {});
  const rec = store[url];
  return rec && typeof rec.p === 'number' && rec.p >= 0 ? rec.p : 0;
}

export function listBookmarks(seriesKey?: string): EbookBookmarkItem[] {
  const list = safeReadJson<EbookBookmarkItem[]>(BOOKMARK_STORAGE_KEY, []);
  if (!Array.isArray(list)) return [];
  const filtered = seriesKey ? list.filter((b) => b.seriesKey === seriesKey) : list;
  return filtered.sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
}

export function isParagraphBookmarked(url: string, paraIdx: number): boolean {
  const list = safeReadJson<EbookBookmarkItem[]>(BOOKMARK_STORAGE_KEY, []);
  return Array.isArray(list) && list.some((b) => b.url === url && b.paraIdx === paraIdx);
}

export function toggleBookmark(
  candidate: Omit<EbookBookmarkItem, 'id' | 'createdAt'>
): { added: boolean; items: EbookBookmarkItem[] } {
  const list = safeReadJson<EbookBookmarkItem[]>(BOOKMARK_STORAGE_KEY, []);
  const safeList = Array.isArray(list) ? list : [];
  const existingIdx = safeList.findIndex(
    (b) => b.url === candidate.url && b.paraIdx === candidate.paraIdx
  );
  if (existingIdx >= 0) {
    safeList.splice(existingIdx, 1);
    safeWriteJson(BOOKMARK_STORAGE_KEY, safeList);
    return {
      added: false,
      items: safeList.filter((b) => b.seriesKey === candidate.seriesKey),
    };
  }
  const item: EbookBookmarkItem = {
    ...candidate,
    id: `bm_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
    excerpt: candidate.excerpt.trim().slice(0, 130),
    createdAt: Date.now(),
  };
  const next = [item, ...safeList].slice(0, BOOKMARK_MAX);
  safeWriteJson(BOOKMARK_STORAGE_KEY, next);
  return {
    added: true,
    items: next.filter((b) => b.seriesKey === candidate.seriesKey),
  };
}

export function removeBookmark(id: string, seriesKey?: string): EbookBookmarkItem[] {
  const list = safeReadJson<EbookBookmarkItem[]>(BOOKMARK_STORAGE_KEY, []);
  const next = (Array.isArray(list) ? list : []).filter((b) => b.id !== id);
  safeWriteJson(BOOKMARK_STORAGE_KEY, next);
  return seriesKey ? next.filter((b) => b.seriesKey === seriesKey) : next;
}
