/**
 * Unified Ebook Domain Service Layer for tranX:
 * 1. Paragraph-Anchored Pagination & Two-Page Book Spread Engine (reflow-safe across font/resize)
 * 2. Rich Reading Shelf ("Continue Reading") + Exact Per-Chapter Paragraph Resume
 * 3. Per-Series Bookmark Store
 * 4. Web Speech Read-Aloud TTS Controller (graceful fallback, 0 external dependencies)
 */

import type { SentencePair } from '../types';
import type { EbookMeasure } from './ebookPrefs';

export interface BookPageSlice {
  pageNumber: number;
  pairs: SentencePair[];
  leftPairs?: SentencePair[];
  rightPairs?: SentencePair[];
  isSpread: boolean;
  startParaIdx: number;
  endParaIdx: number;
}

export interface PaginationOptions {
  viewportWidth: number;
  viewportHeight: number;
  isMobile: boolean;
  fontSize: number;
  lineHeight: number;
  measure: EbookMeasure;
  bilingual: boolean;
  isOriginal: boolean;
  wantSpread: boolean;
}

/**
 * Paginates sentences into single pages or wide-desktop two-page spreads (when >= 1120px & non-bilingual)
 * with explicit startParaIdx / endParaIdx metadata so reading position survives any reflow.
 */
export function paginateEbookParagraphs(
  sentences: SentencePair[],
  opts: PaginationOptions
): BookPageSlice[] {
  if (!sentences || sentences.length === 0) return [];

  const canSpread =
    opts.wantSpread && !opts.isMobile && !opts.bilingual && opts.viewportWidth >= 1120;
  const usableH = Math.max(220, opts.viewportHeight - (opts.isMobile ? 410 : 272));
  const linePx = opts.fontSize * opts.lineHeight;
  const fontScale = 18 / Math.max(14, opts.fontSize);
  const charsPerLine = opts.isMobile
    ? Math.max(24, Math.round(330 / (opts.fontSize * 0.54)))
    : Math.max(
        28,
        Math.round(
          (canSpread
            ? 48
            : opts.measure === 'narrow'
              ? 54
              : opts.measure === 'wide'
                ? 70
                : 62) * fontScale
        )
      );
  const maxLinesPerColumn = Math.max(
    6,
    Math.floor((usableH / linePx) * (opts.bilingual && !opts.isOriginal ? 0.82 : 0.88))
  );

  const singleCols: Array<{ pairs: SentencePair[]; startIdx: number; endIdx: number }> = [];
  let current: SentencePair[] = [];
  let startIdx = 0;
  let usedLines = 0;

  for (let idx = 0; idx < sentences.length; idx++) {
    const pair = sentences[idx];
    const txt = opts.isOriginal ? pair.src : pair.dst;
    let estLines = Math.max(1.45, Math.ceil((txt.length || 1) / charsPerLine) + 0.72);
    if (opts.bilingual && !opts.isOriginal && pair.src) {
      estLines += Math.max(1.2, Math.ceil(pair.src.length / Math.max(22, charsPerLine * 0.9)) + 0.9);
    }
    if (current.length > 0 && usedLines + estLines > maxLinesPerColumn) {
      singleCols.push({ pairs: current, startIdx, endIdx: idx - 1 });
      current = [pair];
      startIdx = idx;
      usedLines = estLines;
    } else {
      current.push(pair);
      usedLines += estLines;
    }
  }
  if (current.length > 0) {
    singleCols.push({ pairs: current, startIdx, endIdx: sentences.length - 1 });
  }

  if (!canSpread || singleCols.length <= 1) {
    return singleCols.map((col, i) => ({
      pageNumber: i + 1,
      pairs: col.pairs,
      isSpread: false,
      startParaIdx: col.startIdx,
      endParaIdx: col.endIdx,
    }));
  }

  const spreads: BookPageSlice[] = [];
  for (let i = 0; i < singleCols.length; i += 2) {
    const left = singleCols[i];
    const right = singleCols[i + 1];
    spreads.push({
      pageNumber: spreads.length + 1,
      pairs: right ? [...left.pairs, ...right.pairs] : left.pairs,
      leftPairs: left.pairs,
      rightPairs: right ? right.pairs : [],
      isSpread: true,
      startParaIdx: left.startIdx,
      endParaIdx: right ? right.endIdx : left.endIdx,
    });
  }
  return spreads;
}

/**
 * Finds the exact page containing `anchorParaIdx` after font size, viewport, or spread reflow.
 */
export function findPageIndexForParagraph(pages: BookPageSlice[], anchorParaIdx: number): number {
  if (!pages.length || anchorParaIdx <= 0) return 0;
  for (let i = 0; i < pages.length; i++) {
    if (anchorParaIdx >= pages[i].startParaIdx && anchorParaIdx <= pages[i].endParaIdx) {
      return i;
    }
  }
  return pages.length - 1;
}

export {
  getChapterParaPos,
  isParagraphBookmarked,
  listBookmarks,
  listRecentReadings,
  removeBookmark,
  removeRecentReading,
  saveChapterParaPos,
  saveRichReadingEntry,
  toggleBookmark,
  type EbookBookmarkItem,
  type RichReadingShelfItem,
} from './ebookStorage';

/* Re-exported Podcast-Grade Audio Narration Engine (100-Literature Prosody) */

export {
  buildPodcastScript,
  computeSleepFadeEnvelope,
  createPodcastNarratorController,
  isTtsSupported,
  loadSpeechVoices,
  PODCAST_RATES,
  PODCAST_STYLE_CONFIG,
  preprocessForSpeech,
  rankVoicesForLang,
  unlockSpeechSynthesisOnGesture,
  type PodcastCastMode,
  type PodcastNarratorController,
  type PodcastSegmentMeta,
  type PodcastSleepPreset,
  type PodcastStartOptions,
  type PodcastStyleId,
  type RankedVoiceOption,
  type SpeechSegment,
  type SpeechSegmentKind,
  type TtsPlaybackState,
  type TtsRate,
} from './podcastNarrator';

/* Upper-Third Eye-Voice Lead Follow-Scroll (Conklin et al. 2020 + WCAG 2.2) */

export function scrollActiveParagraphIntoComfortZone(paraIdx: number): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  const el = document.querySelector<HTMLElement>(`[data-para-idx="${paraIdx}"]`);
  if (!el) return;
  const prefersReduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const rect = el.getBoundingClientRect();
  const vh = window.innerHeight || document.documentElement.clientHeight || 800;
  const comfortTop = vh * 0.2;
  const comfortBottom = vh * 0.64;
  if (rect.top >= comfortTop && rect.bottom <= comfortBottom) return;
  const desiredTop = vh * 0.32;
  window.scrollBy({
    top: rect.top - desiredTop,
    behavior: prefersReduced ? 'auto' : 'smooth',
  });
}

/* Hands-Free Smooth Sub-Pixel Auto-Scroll Engine (rAF + Reduced Motion Guard) */

export type AutoScrollState = 'idle' | 'running' | 'paused';
export type AutoScrollSpeedPreset = 0.5 | 1 | 1.5 | 2 | 2.5;

export const AUTO_SCROLL_SPEEDS: readonly AutoScrollSpeedPreset[] = [0.5, 1, 1.5, 2, 2.5] as const;

const SPEED_TO_PX_PER_SEC: Record<AutoScrollSpeedPreset, number> = {
  0.5: 18,
  1: 32,
  1.5: 48,
  2: 68,
  2.5: 94,
};

export interface EbookAutoScrollController {
  start: (speed: AutoScrollSpeedPreset) => void;
  pause: (reason?: 'manual' | 'interaction' | 'hidden') => void;
  resume: () => void;
  stop: () => void;
  setSpeed: (speed: AutoScrollSpeedPreset) => void;
}

export function createEbookAutoScrollController(callbacks: {
  onStateChange: (state: AutoScrollState, reason?: 'manual' | 'interaction' | 'hidden' | 'end') => void;
  onReachEnd?: () => void;
}): EbookAutoScrollController {
  let state: AutoScrollState = 'idle';
  let activeSpeed: AutoScrollSpeedPreset = 1;
  let rafId = 0;
  let reducedTimerId: number | null = null;
  let lastTs = 0;
  let startedTs = 0;
  let subPixelAcc = 0;
  let visBound = false;

  const onVisibilityChange = () => {
    if (document.hidden && state === 'running') {
      stopLoops();
      state = 'paused';
      callbacks.onStateChange('paused', 'hidden');
    }
  };

  const stopLoops = () => {
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = 0;
    }
    if (reducedTimerId !== null) {
      window.clearInterval(reducedTimerId);
      reducedTimerId = null;
    }
    if (visBound && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      visBound = false;
    }
    lastTs = 0;
    subPixelAcc = 0;
  };

  const atBottom = (): boolean => {
    const doc = document.documentElement;
    return window.scrollY + window.innerHeight >= doc.scrollHeight - 4;
  };

  const runLoop = () => {
    stopLoops();
    if (state !== 'running' || typeof window === 'undefined') return;
    if (atBottom()) {
      state = 'paused';
      callbacks.onStateChange('paused', 'end');
      callbacks.onReachEnd?.();
      return;
    }
    if (!visBound && typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibilityChange);
      visBound = true;
    }

    const prefersReduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced) {
      // Discrete gentle step advance for motion-sensitive readers (WCAG 2.3.3)
      const intervalMs = Math.round(3200 / activeSpeed);
      reducedTimerId = window.setInterval(() => {
        if (state !== 'running' || document.hidden) return;
        if (atBottom()) {
          stopLoops();
          state = 'paused';
          callbacks.onStateChange('paused', 'end');
          callbacks.onReachEnd?.();
          return;
        }
        window.scrollBy({ top: Math.round(window.innerHeight * 0.28), behavior: 'auto' });
      }, intervalMs);
      return;
    }

    startedTs = performance.now();
    lastTs = startedTs;
    const step = (ts: number) => {
      if (state !== 'running') return;
      if (document.hidden) {
        stopLoops();
        state = 'paused';
        callbacks.onStateChange('paused', 'hidden');
        return;
      }
      const dtMs = Math.min(50, Math.max(0, ts - lastTs));
      lastTs = ts;
      // Smooth 320ms acceleration ramp so eyes never get jolted on start/resume
      const ramp = Math.min(1, (ts - startedTs) / 320);
      const easeRamp = ramp * (2 - ramp);
      const pxPerSec = SPEED_TO_PX_PER_SEC[activeSpeed] || 32;
      subPixelAcc += (pxPerSec * easeRamp * dtMs) / 1000;
      const wholePx = Math.floor(subPixelAcc);
      if (wholePx >= 1) {
        subPixelAcc -= wholePx;
        window.scrollBy(0, wholePx);
        if (atBottom()) {
          stopLoops();
          state = 'paused';
          callbacks.onStateChange('paused', 'end');
          callbacks.onReachEnd?.();
          return;
        }
      }
      rafId = window.requestAnimationFrame(step);
    };
    rafId = window.requestAnimationFrame(step);
  };

  return {
    start(speed) {
      activeSpeed = speed;
      state = 'running';
      callbacks.onStateChange('running', 'manual');
      runLoop();
    },
    pause(reason = 'manual') {
      if (state !== 'running') return;
      stopLoops();
      state = 'paused';
      callbacks.onStateChange('paused', reason);
    },
    resume() {
      if (state !== 'paused') return;
      state = 'running';
      callbacks.onStateChange('running', 'manual');
      runLoop();
    },
    stop() {
      stopLoops();
      if (state !== 'idle') {
        state = 'idle';
        callbacks.onStateChange('idle', 'manual');
      }
    },
    setSpeed(speed) {
      activeSpeed = speed;
      if (state === 'running') {
        // Restart reduced-motion timer smoothly if active; continuous rAF reads activeSpeed live
        if (reducedTimerId !== null) runLoop();
      }
    },
  };
}
