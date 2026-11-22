import { memo, useCallback, useEffect, useRef, useState } from 'react';
import type {
  ComicLayoutMode,
  ImageTranslationResult,
  MangaLinkMeta,
  ModePair,
  NovelNavigation,
  ResolvedTheme,
  TargetLang,
  VisionBlockKind,
} from '../types';
import type { UiStrings } from '../i18n/strings';
import { parseModePair, toSafeHttpUrl } from '../lib/langUtils';
import { directScanRemoteMangaPage, directTranslateImage } from '../lib/directEngine';
import { renderMangaOverlayToCanvas } from '../lib/mangaScanner';
import type { PodcastNarratorController, TtsPlaybackState } from '../lib/podcastNarrator';
import {
  IconCopy,
  IconDownload,
  IconEye,
  IconHeadphones,
  IconPause,
  IconPhoto,
  IconPlay,
} from './Icons';

interface Props {
  comicMeta: MangaLinkMeta;
  titleDst: string;
  host: string;
  mode: ModePair;
  titleId?: string;
  resolvedTheme: ResolvedTheme;
  strings: UiStrings;
  initialFirstResult?: ImageTranslationResult;
  novelNav?: NovelNavigation;
  onOpenChapterUrl?: (url: string) => void;
  onCopyToast?: (msg: string) => void;
}

const LAYOUT_LABELS_ID: Record<ComicLayoutMode, string> = {
  rtl_manga: 'Manga (Kanan ke Kiri)',
  webtoon_strip: 'Webtoon / Manhwa',
  four_koma: '4-Koma',
  ltr_comic: 'Komik (Kiri ke Kanan)',
  single_image: 'Gambar Komik',
};

const LAYOUT_LABELS_EN: Record<ComicLayoutMode, string> = {
  rtl_manga: 'Manga (RTL)',
  webtoon_strip: 'Webtoon / Manhwa',
  four_koma: '4-Koma',
  ltr_comic: 'Comic (LTR)',
  single_image: 'Single Image',
};

const KIND_LABELS: Record<VisionBlockKind, { id: string; en: string }> = {
  dialogue: { id: 'Dialog', en: 'Dialogue' },
  thought: { id: 'Batin', en: 'Thought' },
  shout: { id: 'Teriakan', en: 'Shout' },
  narration: { id: 'Narasi', en: 'Narration' },
  sfx: { id: 'SFX', en: 'SFX' },
  status_window: { id: 'Status RPG', en: 'RPG Status' },
  caption: { id: 'Keterangan', en: 'Caption' },
  sign: { id: 'Papan', en: 'Sign' },
  aside: { id: 'Catatan', en: 'Aside' },
};

const SAFE_RASTER_DATA_URL_RE = /^data:image\/(?:png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=\s]+$/i;
const ALLOWED_RESCUE_MIMES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
const MAX_RESCUE_FILE_BYTES = 15 * 1024 * 1024;

const canUseSpeechTts =
  typeof window !== 'undefined' &&
  'speechSynthesis' in window &&
  typeof window.SpeechSynthesisUtterance !== 'undefined';

const MangaOverlayPageCanvas = memo(function MangaOverlayPageCanvas({
  result,
  resolvedTheme,
  showSfx,
  pageIndex,
  onDownloadReady,
}: {
  result: ImageTranslationResult;
  resolvedTheme: ResolvedTheme;
  showSfx: boolean;
  pageIndex: number;
  onDownloadReady?: (pageIndex: number, fn: () => void) => void;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const onDownloadReadyRef = useRef(onDownloadReady);
  onDownloadReadyRef.current = onDownloadReady;
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isNearViewport, setIsNearViewport] = useState(pageIndex <= 2);

  useEffect(() => {
    setSelectedId(null);
  }, [result]);

  // Offscreen canvas dehydration prevents iOS Safari GPU OOM crashes on 50-120 page manga chapters while preserving 0 CLS
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setIsNearViewport(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry) {
          setIsNearViewport(entry.isIntersecting);
        }
      },
      { rootMargin: '600px 0px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (!isNearViewport) {
      if (imgRef.current) {
        imgRef.current.src = '';
        imgRef.current = null;
      }
      canvas.width = 0;
      canvas.height = 0;
      return;
    }
    let cancelled = false;
    let activeImg: HTMLImageElement | null = null;
    const draw = (img: HTMLImageElement | null) => {
      if (cancelled || !canvasRef.current) return;
      renderMangaOverlayToCanvas(canvasRef.current, img, result.blocks, result.width, result.height, {
        resolvedTheme,
        showSfx,
        highlightBlockId: null,
      });
    };
    const safeUrl =
      result.dataUrl && SAFE_RASTER_DATA_URL_RE.test(result.dataUrl) ? result.dataUrl : null;
    if (safeUrl) {
      if (imgRef.current && imgRef.current.src === safeUrl && imgRef.current.complete) {
        draw(imgRef.current);
      } else {
        const img = new Image();
        activeImg = img;
        img.onload = () => {
          if (cancelled) return;
          imgRef.current = img;
          draw(img);
        };
        img.onerror = () => {
          if (!cancelled) draw(null);
        };
        img.src = safeUrl;
      }
    } else {
      draw(null);
    }
    return () => {
      cancelled = true;
      if (activeImg) {
        activeImg.onload = null;
        activeImg.onerror = null;
      }
    };
  }, [result, resolvedTheme, showSfx, isNearViewport]);

  // Release decoded GPU canvas backing store & image reference on unmount
  useEffect(() => {
    return () => {
      if (imgRef.current) {
        imgRef.current.src = '';
        imgRef.current = null;
      }
      if (canvasRef.current) {
        canvasRef.current.width = 0;
        canvasRef.current.height = 0;
      }
    };
  }, []);

  useEffect(() => {
    if (!onDownloadReadyRef.current) return;
    onDownloadReadyRef.current(pageIndex, () => {
      const exportFromCanvas = (canvas: HTMLCanvasElement, disposeAfter: boolean) => {
        const downloadName = `tranx-komik-hal-${pageIndex + 1}.png`;
        const triggerDownload = (href: string, revokeAfter: boolean) => {
          const a = document.createElement('a');
          a.href = href;
          a.download = downloadName;
          document.body.appendChild(a);
          a.click();
          a.remove();
          if (revokeAfter) {
            window.setTimeout(() => URL.revokeObjectURL(href), 10_000);
          }
          if (disposeAfter) {
            canvas.width = 0;
            canvas.height = 0;
          }
        };
        try {
          if (typeof canvas.toBlob === 'function') {
            canvas.toBlob((blob) => {
              if (!blob) {
                if (disposeAfter) {
                  canvas.width = 0;
                  canvas.height = 0;
                }
                return;
              }
              triggerDownload(URL.createObjectURL(blob), true);
            }, 'image/png');
            return;
          }
          triggerDownload(canvas.toDataURL('image/png'), false);
        } catch {
          if (disposeAfter) {
            canvas.width = 0;
            canvas.height = 0;
          }
        }
      };

      const canvas = canvasRef.current;
      if (canvas && canvas.width > 0 && canvas.height > 0) {
        exportFromCanvas(canvas, false);
        return;
      }
      // Dehydrated offscreen page: rehydrate background image onto temporary canvas before PNG export
      const safeUrl =
        result.dataUrl && SAFE_RASTER_DATA_URL_RE.test(result.dataUrl) ? result.dataUrl : null;
      const offscreen = document.createElement('canvas');
      const renderAndExport = (img: HTMLImageElement | null) => {
        renderMangaOverlayToCanvas(offscreen, img, result.blocks, result.width, result.height, {
          resolvedTheme,
          showSfx,
          highlightBlockId: null,
        });
        exportFromCanvas(offscreen, true);
      };
      if (imgRef.current && imgRef.current.complete && imgRef.current.naturalWidth > 0) {
        renderAndExport(imgRef.current);
      } else if (safeUrl) {
        const tmpImg = new Image();
        tmpImg.onload = () => {
          renderAndExport(tmpImg);
          tmpImg.src = '';
        };
        tmpImg.onerror = () => renderAndExport(null);
        tmpImg.src = safeUrl;
      } else {
        renderAndExport(null);
      }
    });
  }, [pageIndex, result, resolvedTheme, showSfx]);

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = result.width / Math.max(1, rect.width);
    const scaleY = result.height / Math.max(1, rect.height);
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;
    const hit = result.blocks.find((blk) => {
      const [bx, by, bw, bh] = blk.box;
      return x >= bx && x <= bx + bw && y >= by && y <= by + bh;
    });
    setSelectedId((cur) => (hit ? (cur === hit.id ? null : hit.id) : null));
  };

  const activeBlock = selectedId !== null ? result.blocks.find((b) => b.id === selectedId) : null;
  const aspectRatio = `${Math.max(1, result.width)} / ${Math.max(1, result.height)}`;

  return (
    <div ref={wrapRef} style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}>
      <div style={{ position: 'relative', width: '100%' }}>
        <canvas
          ref={canvasRef}
          onClick={handleClick}
          data-manga-overlay-canvas="true"
          data-manga-page-idx={pageIndex}
          aria-label={`Hasil terjemahan visual halaman ${pageIndex + 1}`}
          style={{
            width: '100%',
            height: 'auto',
            aspectRatio,
            borderRadius: 'var(--r-control)',
            border: '1px solid var(--border)',
            display: 'block',
            cursor: 'pointer',
            background: 'var(--bg-subtle)',
          }}
        />
        {activeBlock && (
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: `${(activeBlock.box[0] / Math.max(1, result.width)) * 100}%`,
              top: `${(activeBlock.box[1] / Math.max(1, result.height)) * 100}%`,
              width: `${(activeBlock.box[2] / Math.max(1, result.width)) * 100}%`,
              height: `${(activeBlock.box[3] / Math.max(1, result.height)) * 100}%`,
              border: '2px solid var(--accent)',
              borderRadius: '6px',
              boxShadow: '0 0 0 2px color-mix(in srgb, var(--accent) 26%, transparent)',
              pointerEvents: 'none',
              boxSizing: 'border-box',
            }}
          />
        )}
      </div>
      {activeBlock && (
        <div
          style={{
            padding: '10px 12px',
            borderRadius: 'var(--r-control)',
            border: '1px solid var(--border)',
            background: 'var(--bg-subtle)',
            fontSize: '13px',
          }}
        >
          <div style={{ color: 'var(--text-subtle)', fontFamily: 'var(--font-jp)', marginBottom: '2px' }}>
            {activeBlock.src}
          </div>
          <div style={{ fontWeight: 600, color: 'var(--text)' }}>{activeBlock.dst}</div>
        </div>
      )}
    </div>
  );
});

export function MangaLinkReader({
  comicMeta,
  titleDst,
  host,
  mode,
  titleId,
  resolvedTheme,
  strings,
  initialFirstResult,
  novelNav,
  onOpenChapterUrl,
  onCopyToast,
}: Props) {
  const [viewMode, setViewMode] = useState<'overlay' | 'original' | 'list'>('overlay');
  const [showSfx, setShowSfx] = useState(true);
  const [pageResults, setPageResults] = useState<Record<number, ImageTranslationResult>>(() => {
    const init: Record<number, ImageTranslationResult> = {};
    if (initialFirstResult) init[0] = initialFirstResult;
    return init;
  });
  const [scanningIdx, setScanningIdx] = useState<Record<number, boolean>>({});
  const [pageErrors, setPageErrors] = useState<Record<number, string>>({});
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null);
  const [ttsState, setTtsState] = useState<TtsPlaybackState>('idle');
  const [rescueResult, setRescueResult] = useState<ImageTranslationResult | null>(null);
  const [rescueLoading, setRescueLoading] = useState(false);

  const batchAbortRef = useRef<AbortController | null>(null);
  const unmountAbortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const downloadFnsRef = useRef<Record<number, () => void>>({});
  const ttsCtrlRef = useRef<PodcastNarratorController | null>(null);
  const rescueInputRef = useRef<HTMLInputElement | null>(null);
  const rescueInFlightRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    const ctrl = new AbortController();
    unmountAbortRef.current = ctrl;
    const fnsMap = downloadFnsRef.current;
    return () => {
      mountedRef.current = false;
      ctrl.abort();
      batchAbortRef.current?.abort();
      ttsCtrlRef.current?.stop();
      Object.keys(fnsMap).forEach((k) => delete fnsMap[Number(k)]);
    };
  }, []);

  const { tgt } = parseModePair(mode);
  const isEnUi = strings.mangaViewOverlay === 'Visual overlay';
  const layoutLabel = isEnUi
    ? LAYOUT_LABELS_EN[comicMeta.layout]
    : LAYOUT_LABELS_ID[comicMeta.layout];

  const scanPage = useCallback(
    async (pageIdx: number, signal?: AbortSignal) => {
      const page = comicMeta.pages[pageIdx];
      if (!page) return;
      setScanningIdx((prev) => ({ ...prev, [pageIdx]: true }));
      setPageErrors((prev) => {
        const next = { ...prev };
        delete next[pageIdx];
        return next;
      });
      try {
        const res = await directScanRemoteMangaPage({
          imageUrl: page.url,
          mode,
          titleId,
          layout: comicMeta.layout,
          signal: signal || unmountAbortRef.current?.signal,
        });
        if (!mountedRef.current) return;
        setPageResults((prev) => ({ ...prev, [pageIdx]: res }));
      } catch (err) {
        if (!mountedRef.current || (err as Error)?.name === 'AbortError') return;
        const msg =
          err instanceof Error
            ? err.message
            : 'Halaman ini menolak pengambilan gambar otomatis. Gunakan unggah/tempel gambar di atas.';
        setPageErrors((prev) => ({ ...prev, [pageIdx]: msg }));
      } finally {
        if (mountedRef.current) {
          setScanningIdx((prev) => ({ ...prev, [pageIdx]: false }));
        }
      }
    },
    [comicMeta.pages, comicMeta.layout, mode, titleId]
  );

  // Auto-scan Page 1 on first mount if not already provided and not DRM-blocked
  const autoStartedRef = useRef(false);
  useEffect(() => {
    if (autoStartedRef.current) return;
    if (!comicMeta.drmProtected && comicMeta.pages.length > 0 && !pageResults[0]) {
      autoStartedRef.current = true;
      void scanPage(0);
    }
  }, [comicMeta.drmProtected, comicMeta.pages.length, pageResults, scanPage]);

  const handleScanAll = async () => {
    if (batchProgress) {
      batchAbortRef.current?.abort();
      batchAbortRef.current = null;
      setBatchProgress(null);
      return;
    }
    const pendingIndices = comicMeta.pages
      .map((p) => p.index)
      .filter((idx) => !pageResults[idx]);
    if (pendingIndices.length === 0) return;

    const ctrl = new AbortController();
    batchAbortRef.current = ctrl;
    setBatchProgress({ done: 0, total: pendingIndices.length });
    let done = 0;
    try {
      for (const idx of pendingIndices) {
        if (ctrl.signal.aborted || !mountedRef.current) break;
        await scanPage(idx, ctrl.signal);
        done += 1;
        if (mountedRef.current && batchAbortRef.current === ctrl) {
          setBatchProgress({ done, total: pendingIndices.length });
        }
      }
    } finally {
      if (batchAbortRef.current === ctrl) {
        batchAbortRef.current = null;
        if (mountedRef.current) setBatchProgress(null);
      }
    }
  };

  const handleRescueImageFile = useCallback(
    async (file: File) => {
      if (rescueInFlightRef.current) return;
      if (!ALLOWED_RESCUE_MIMES.has(file.type.toLowerCase())) {
        onCopyToast?.('Format gambar belum didukung. Gunakan PNG, JPG, WEBP, atau GIF.');
        return;
      }
      if (file.size <= 0 || file.size > MAX_RESCUE_FILE_BYTES) {
        onCopyToast?.('Ukuran gambar melebihi batas aman 15 MB.');
        return;
      }
      rescueInFlightRef.current = true;
      setRescueLoading(true);
      try {
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ''));
          reader.onerror = () => reject(new Error('Gagal membaca berkas gambar.'));
          reader.readAsDataURL(file);
        });
        const res = await directTranslateImage({
          cid: `c_comic_${Date.now().toString(36)}`,
          mode,
          fileName: file.name || 'tangkapan-komik.png',
          imageDataUrl: dataUrl,
          titleId,
          persistMessage: false,
          signal: unmountAbortRef.current?.signal,
        });
        if (!mountedRef.current) return;
        setRescueResult(res);
      } catch (err) {
        if (!mountedRef.current || (err as Error)?.name === 'AbortError') return;
        onCopyToast?.(err instanceof Error ? err.message : 'Gagal memindai gambar tempelan.');
      } finally {
        rescueInFlightRef.current = false;
        if (mountedRef.current) {
          setRescueLoading(false);
        }
      }
    },
    [mode, titleId, onCopyToast]
  );

  // Instant Ctrl+V clipboard image paste rescue for DRM/CORS pages
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of Array.from(items)) {
        if (ALLOWED_RESCUE_MIMES.has(item.type.toLowerCase())) {
          const f = item.getAsFile();
          if (f) {
            void handleRescueImageFile(f);
            break;
          }
        }
      }
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [handleRescueImageFile]);

  const allDialogueLines = [
    ...comicMeta.pages.flatMap((p) => {
      const r = pageResults[p.index];
      if (!r) return [];
      return r.blocks
        .filter((b) => showSfx || b.kind !== 'sfx')
        .map((b) => b.dst)
        .filter(Boolean);
    }),
    ...(rescueResult ? rescueResult.blocks.map((b) => b.dst).filter(Boolean) : []),
  ];

  const ttsLoadingRef = useRef(false);
  const handleDownloadReady = useCallback((idx: number, fn: () => void) => {
    downloadFnsRef.current[idx] = fn;
  }, []);

  const handleTogglePodcast = async () => {
    if (!canUseSpeechTts || allDialogueLines.length === 0 || ttsLoadingRef.current) return;
    if (ttsState === 'playing') {
      ttsCtrlRef.current?.pause();
      return;
    }
    if (ttsState === 'paused') {
      ttsCtrlRef.current?.resume();
      return;
    }
    // Synchronously unlock iOS Safari SpeechSynthesis inside the click gesture before dynamic import
    try {
      const unlockUtter = new window.SpeechSynthesisUtterance('');
      unlockUtter.volume = 0;
      window.speechSynthesis.speak(unlockUtter);
    } catch {
      // ignore unlock errors
    }
    if (!ttsCtrlRef.current) {
      ttsLoadingRef.current = true;
      try {
        const { createPodcastNarratorController } = await import('../lib/podcastNarrator');
        if (!mountedRef.current) return;
        ttsCtrlRef.current = createPodcastNarratorController({
          onSegmentStart: () => { },
          onStateChange: (st) => {
            if (mountedRef.current) setTtsState(st);
          },
        });
      } finally {
        ttsLoadingRef.current = false;
      }
    }
    ttsCtrlRef.current.start({
      texts: allDialogueLines,
      startIndex: 0,
      lang: tgt as TargetLang,
      rate: 1,
      style: 'podcast_santai',
      chapterTitle: titleDst,
      seriesTitle: host,
      formatOverride: 'script_dialogue',
    });
  };

  const scannedCount = Object.keys(pageResults).length;

  return (
    <section className="manga-reader-shell" data-manga-reader="true" aria-label={titleDst}>
      <header className="manga-reader-head">
        <div className="manga-reader-badges">
          <span className="status-badge done">
            {comicMeta.isDirectImage
              ? strings.mangaDirectImageBadge
              : `${strings.mangaDetectedBadge} · ${comicMeta.pageCount} ${strings.mangaPageUnit}`}
          </span>
          <span className="manga-layout-pill">{layoutLabel}</span>
          {scannedCount > 0 && (
            <span style={{ fontSize: '12px', color: 'var(--text-subtle)' }}>
              · {scannedCount}/{comicMeta.pageCount} {strings.mangaScannedLabel}
            </span>
          )}
        </div>
        <h1 className="novel-reader-title" style={{ marginTop: '6px' }}>
          {titleDst}
        </h1>

        <div className="manga-toolbar" role="toolbar" aria-label={strings.mangaToolbarLabel}>
          <div className="manga-view-tabs" role="tablist" aria-label={strings.mangaToolbarLabel}>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'overlay'}
              data-manga-view-tab="overlay"
              className={viewMode === 'overlay' ? 'btn-primary pressable' : 'btn-secondary pressable'}
              onClick={() => setViewMode('overlay')}
            >
              {strings.mangaViewOverlay}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'original'}
              data-manga-view-tab="original"
              className={viewMode === 'original' ? 'btn-primary pressable' : 'btn-secondary pressable'}
              onClick={() => setViewMode('original')}
            >
              {strings.mangaViewOriginal}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'list'}
              data-manga-view-tab="list"
              className={viewMode === 'list' ? 'btn-primary pressable' : 'btn-secondary pressable'}
              onClick={() => setViewMode('list')}
            >
              {strings.mangaViewList}
            </button>
          </div>

          <div className="manga-toolbar-actions">
            <button
              type="button"
              className="btn-secondary pressable"
              aria-pressed={showSfx}
              onClick={() => setShowSfx((v) => !v)}
            >
              {strings.mangaSfxToggle}: {showSfx ? 'ON' : 'OFF'}
            </button>

            {comicMeta.pageCount > 1 && !comicMeta.drmProtected && (
              <button
                type="button"
                className="btn-primary pressable"
                data-manga-scan-all="true"
                onClick={handleScanAll}
              >
                <IconEye size={16} />
                {batchProgress
                  ? `${strings.mangaScanningProgress} (${batchProgress.done}/${batchProgress.total})`
                  : strings.mangaScanAllBtn}
              </button>
            )}

            {allDialogueLines.length > 0 && canUseSpeechTts && (
              <button
                type="button"
                className="btn-secondary pressable"
                aria-pressed={ttsState === 'playing'}
                onClick={() => void handleTogglePodcast()}
              >
                {ttsState === 'playing' ? <IconPause size={16} /> : ttsState === 'paused' ? <IconPlay size={16} /> : <IconHeadphones size={16} />}
                {ttsState === 'playing' ? strings.ebookListenPause : strings.mangaListenDialogue}
              </button>
            )}
          </div>
        </div>
      </header>

      {(comicMeta.drmProtected || Object.keys(pageErrors).length > 0) && (
        <div className="manga-rescue-banner" role="status">
          <div style={{ fontWeight: 600, marginBottom: '4px' }}>
            {comicMeta.drmProtected ? strings.mangaDrmTitle : strings.mangaCorsFallbackTitle}
          </div>
          <p style={{ margin: '0 0 10px', fontSize: '13px', color: 'var(--text-muted)' }}>
            {comicMeta.drmReason || strings.mangaCorsFallbackDesc}
          </p>
          <input
            ref={rescueInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleRescueImageFile(f);
              e.target.value = '';
            }}
          />
          <button
            type="button"
            className="btn-primary pressable"
            disabled={rescueLoading}
            onClick={() => rescueInputRef.current?.click()}
          >
            <IconPhoto size={16} />
            {rescueLoading ? strings.readingImageOcr : strings.mangaUploadRescueBtn}
          </button>
        </div>
      )}

      {rescueResult && (
        <div className="manga-page-card">
          <div className="manga-page-card-head">
            <span className="status-badge done">{strings.mangaUploadRescueResult}</span>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {viewMode === 'overlay' && (
                <button
                  type="button"
                  className="btn-secondary pressable"
                  onClick={() => downloadFnsRef.current[999]?.()}
                >
                  <IconDownload size={15} />
                  {strings.downloadImage}
                </button>
              )}
              <button
                type="button"
                className="btn-secondary pressable"
                onClick={() => {
                  navigator.clipboard
                    ?.writeText(rescueResult.fullDst)
                    .then(() => onCopyToast?.(strings.copiedToast))
                    .catch(() => { });
                }}
              >
                <IconCopy size={16} />
                {strings.copyText}
              </button>
            </div>
          </div>
          {viewMode === 'list' ? (
            <div className="manga-dialogue-list">
              {rescueResult.blocks
                .filter((b) => showSfx || b.kind !== 'sfx')
                .map((blk, bIdx) => {
                  const kindMeta = KIND_LABELS[blk.kind || 'dialogue'];
                  return (
                    <div key={blk.id} className="manga-dialogue-row">
                      <div className="manga-dialogue-meta">
                        <span>#{bIdx + 1}</span>
                        <span>{isEnUi ? kindMeta.en : kindMeta.id}</span>
                      </div>
                      <div className="manga-dialogue-src">{blk.src}</div>
                      <div className="manga-dialogue-dst">{blk.dst}</div>
                    </div>
                  );
                })}
            </div>
          ) : viewMode === 'original' &&
            rescueResult.dataUrl &&
            SAFE_RASTER_DATA_URL_RE.test(rescueResult.dataUrl) ? (
            <div className="manga-raw-img-wrap">
              <img
                src={rescueResult.dataUrl}
                alt={strings.mangaUploadRescueResult}
                style={{
                  width: '100%',
                  height: 'auto',
                  borderRadius: 'var(--r-control)',
                  border: '1px solid var(--border)',
                  display: 'block',
                }}
              />
            </div>
          ) : (
            <MangaOverlayPageCanvas
              result={rescueResult}
              resolvedTheme={resolvedTheme}
              showSfx={showSfx}
              pageIndex={999}
              onDownloadReady={handleDownloadReady}
            />
          )}
        </div>
      )}

      <div
        className={`manga-pages-stack ${comicMeta.layout === 'webtoon_strip' ? 'is-webtoon' : ''}`}
      >
        {comicMeta.pages.map((page) => {
          const result = pageResults[page.index];
          const isScanning = Boolean(scanningIdx[page.index]);
          const errText = pageErrors[page.index];

          return (
            <article
              key={`${page.url}_${page.index}`}
              className="manga-page-card"
              data-manga-page-card={page.index}
            >
              <div className="manga-page-card-head">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, fontSize: '13px' }}>
                    {strings.mangaPageLabel} {page.index + 1} / {comicMeta.pageCount}
                  </span>
                  {result && (
                    <span className="status-badge done">
                      {result.blocks.length} {strings.mangaBubblesUnit}
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    className={result ? 'btn-secondary pressable' : 'btn-primary pressable'}
                    disabled={isScanning}
                    data-manga-scan-page={page.index}
                    onClick={() => void scanPage(page.index)}
                  >
                    <IconEye size={15} />
                    {isScanning
                      ? strings.readingImageOcr
                      : result
                        ? strings.mangaRescanPageBtn
                        : strings.mangaScanPageBtn}
                  </button>
                  {result && viewMode === 'overlay' && (
                    <button
                      type="button"
                      className="btn-secondary pressable"
                      onClick={() => downloadFnsRef.current[page.index]?.()}
                    >
                      <IconDownload size={15} />
                      {strings.downloadImage}
                    </button>
                  )}
                  {result && (
                    <button
                      type="button"
                      className="btn-secondary pressable"
                      onClick={() => {
                        navigator.clipboard
                          ?.writeText(result.fullDst)
                          .then(() => onCopyToast?.(strings.copiedToast))
                          .catch(() => { });
                      }}
                    >
                      <IconCopy size={15} />
                      {strings.copyText}
                    </button>
                  )}
                </div>
              </div>

              {errText && (
                <div className="manga-page-error" role="alert">
                  {errText}
                </div>
              )}

              {viewMode === 'list' ? (
                result ? (
                  <div className="manga-dialogue-list">
                    {result.blocks
                      .filter((b) => showSfx || b.kind !== 'sfx')
                      .map((blk, bIdx) => {
                        const kindMeta = KIND_LABELS[blk.kind || 'dialogue'];
                        return (
                          <div key={blk.id} className="manga-dialogue-row">
                            <div className="manga-dialogue-meta">
                              <span>#{bIdx + 1}</span>
                              <span>{isEnUi ? kindMeta.en : kindMeta.id}</span>
                            </div>
                            <div className="manga-dialogue-src">{blk.src}</div>
                            <div className="manga-dialogue-dst">{blk.dst}</div>
                          </div>
                        );
                      })}
                  </div>
                ) : (
                  <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '4px 0' }}>
                    {strings.mangaNotScannedYet}
                  </p>
                )
              ) : viewMode === 'overlay' && result ? (
                <MangaOverlayPageCanvas
                  result={result}
                  resolvedTheme={resolvedTheme}
                  showSfx={showSfx}
                  pageIndex={page.index}
                  onDownloadReady={handleDownloadReady}
                />
              ) : (
                <div className="manga-raw-img-wrap">
                  {toSafeHttpUrl(page.url) ? (
                    <img
                      src={toSafeHttpUrl(page.url)!}
                      alt={page.alt || `${strings.mangaPageLabel} ${page.index + 1}`}
                      referrerPolicy="no-referrer"
                      loading={page.index <= 1 ? 'eager' : 'lazy'}
                      style={{
                        width: '100%',
                        height: 'auto',
                        borderRadius: 'var(--r-control)',
                        border: '1px solid var(--border)',
                        display: 'block',
                      }}
                    />
                  ) : null}
                </div>
              )}
            </article>
          );
        })}
      </div>

      {novelNav && (novelNav.prevUrl || novelNav.nextUrl) && onOpenChapterUrl && (
        <nav className="novel-chapter-nav" style={{ marginTop: '20px' }} aria-label={strings.chapterListBtn}>
          {novelNav.prevUrl ? (
            <button
              type="button"
              className="btn-secondary pressable"
              onClick={() => onOpenChapterUrl(novelNav.prevUrl!)}
            >
              {'\u2190'} {strings.prevChapter}
            </button>
          ) : (
            <span />
          )}
          {novelNav.nextUrl ? (
            <button
              type="button"
              className="btn-primary pressable"
              onClick={() => onOpenChapterUrl(novelNav.nextUrl!)}
            >
              {strings.nextChapter} {'\u2192'}
            </button>
          ) : null}
        </nav>
      )}
    </section>
  );
}
