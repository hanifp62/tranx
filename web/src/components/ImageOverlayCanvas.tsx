import { useEffect, useRef, useState } from 'react';
import type { ImageTranslationResult, ResolvedTheme } from '../types';
import type { UiStrings } from '../i18n/strings';
import { renderMangaOverlayToCanvas } from '../lib/mangaScanner';
import { IconCopy, IconDownload } from './Icons';

interface Props {
  result: ImageTranslationResult;
  fileName?: string;
  resolvedTheme: ResolvedTheme;
  strings: UiStrings;
  onCopy: (text: string) => void;
  defaultViewMode?: 'side' | 'overlay' | 'original';
}

const SAFE_RASTER_DATA_URL_RE = /^data:image\/(?:png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=\s]+$/i;

export function ImageResultCard({
  result,
  fileName,
  resolvedTheme,
  strings,
  onCopy,
  defaultViewMode = 'overlay',
}: Props) {
  const [viewMode, setViewMode] = useState<'side' | 'overlay' | 'original'>(defaultViewMode);
  const [showSfx, setShowSfx] = useState(true);
  const [activeBlockId, setActiveBlockId] = useState<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const safeDataUrl =
    result.dataUrl && SAFE_RASTER_DATA_URL_RE.test(result.dataUrl) ? result.dataUrl : null;
  const hasSfxBlocks = result.blocks.some((b) => b.kind === 'sfx');

  useEffect(() => {
    setActiveBlockId(null);
  }, [result]);

  useEffect(() => {
    if (viewMode === 'original' && !safeDataUrl) {
      setViewMode('overlay');
    }
  }, [viewMode, safeDataUrl]);

  useEffect(() => {
    if (viewMode !== 'overlay') {
      if (canvasRef.current) {
        canvasRef.current.width = 0;
        canvasRef.current.height = 0;
      }
      return;
    }
    if (!canvasRef.current) return;
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

    if (safeDataUrl) {
      if (imgRef.current && imgRef.current.src === safeDataUrl && imgRef.current.complete) {
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
        img.src = safeDataUrl;
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
  }, [viewMode, result, safeDataUrl, resolvedTheme, showSfx]);

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

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
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
    setActiveBlockId((cur) => (hit ? (cur === hit.id ? null : hit.id) : null));
  };

  const handleDownloadOverlay = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const safeStem =
      (fileName || 'gambar')
        .replace(/\.[^.]+$/, '')
        .replace(/[\x00-\x1f\x7f\\/:*?"<>|\u202a-\u202e\u2066-\u2069]/g, '_')
        .slice(0, 64) || 'gambar';
    const downloadName = `tranx-${safeStem}-overlay.png`;
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
    };
    try {
      if (typeof canvas.toBlob === 'function') {
        canvas.toBlob((blob) => {
          if (!blob) {
            try {
              triggerDownload(canvas.toDataURL('image/png'), false);
            } catch {
              // ignore tainted canvas SecurityError
            }
            return;
          }
          const objUrl = URL.createObjectURL(blob);
          triggerDownload(objUrl, true);
        }, 'image/png');
        return;
      }
      triggerDownload(canvas.toDataURL('image/png'), false);
    } catch {
      // ignore tainted canvas SecurityError
    }
  };

  const activeBlock = activeBlockId !== null ? result.blocks.find((b) => b.id === activeBlockId) : null;

  return (
    <div className="result-card" data-image-result-card="true">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', minWidth: 0 }}>
          <span className="status-badge done">{strings.statusDone}</span>
          <span style={{ fontSize: '14px', fontWeight: 600, overflowWrap: 'anywhere' }}>
            {fileName || strings.modeImage}
          </span>
          <span style={{ fontSize: '12px', color: 'var(--text-subtle)' }}>
            · {result.blocks.length} {strings.mangaBubblesUnit}
          </span>
        </div>
        <div
          style={{ display: 'inline-flex', gap: '6px', flexWrap: 'wrap' }}
          role="tablist"
          aria-label={strings.mangaToolbarLabel}
        >
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === 'overlay'}
            className={
              viewMode === 'overlay' ? 'btn-primary pressable' : 'btn-secondary pressable'
            }
            onClick={() => setViewMode('overlay')}
          >
            {strings.imageOverlay}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === 'side'}
            className={viewMode === 'side' ? 'btn-primary pressable' : 'btn-secondary pressable'}
            onClick={() => setViewMode('side')}
          >
            {strings.sideBySide}
          </button>
          {safeDataUrl && (
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'original'}
              className={
                viewMode === 'original' ? 'btn-primary pressable' : 'btn-secondary pressable'
              }
              onClick={() => setViewMode('original')}
            >
              {strings.mangaViewOriginal}
            </button>
          )}
        </div>
      </div>

      {viewMode === 'original' && safeDataUrl ? (
        <div style={{ width: '100%' }}>
          <img
            src={safeDataUrl}
            alt={fileName || 'Gambar asli'}
            style={{
              width: '100%',
              height: 'auto',
              borderRadius: 'var(--r-control)',
              border: '1px solid var(--border)',
              display: 'block',
            }}
          />
        </div>
      ) : viewMode === 'side' ? (
        <div className="form-grid-2" style={{ alignItems: 'start' }}>
          {safeDataUrl ? (
            <img
              src={safeDataUrl}
              alt={fileName || 'Sumber gambar'}
              style={{
                width: '100%',
                borderRadius: 'var(--r-control)',
                border: '1px solid var(--border)',
              }}
            />
          ) : (
            <div
              style={{
                padding: '12px',
                borderRadius: 'var(--r-control)',
                background: 'var(--bubble-user)',
                fontFamily: 'var(--font-jp)',
              }}
            >
              {result.fullSrc}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {result.blocks.map((blk) => (
              <div
                key={blk.id}
                style={{
                  padding: '10px 12px',
                  borderRadius: 'var(--r-control)',
                  border: '1px solid var(--border)',
                  background: 'var(--bg)',
                }}
              >
                <div
                  style={{
                    fontFamily: 'var(--font-jp)',
                    fontSize: '13px',
                    color: 'var(--text-muted)',
                    marginBottom: '4px',
                  }}
                >
                  {blk.src}
                </div>
                <div className="assistant-prose" style={{ fontSize: '16px', lineHeight: '24px' }}>
                  {blk.dst}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}>
          <div style={{ position: 'relative', width: '100%', overflowX: 'auto' }}>
            <canvas
              ref={canvasRef}
              onClick={handleCanvasClick}
              data-manga-overlay-canvas="true"
              aria-label={strings.imageOverlay}
              style={{
                width: '100%',
                height: 'auto',
                aspectRatio: `${Math.max(1, result.width)} / ${Math.max(1, result.height)}`,
                borderRadius: 'var(--r-control)',
                border: '1px solid var(--border)',
                display: 'block',
                cursor: 'pointer',
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
            {result.fullDst && <div className="sr-only">{result.fullDst}</div>}
          </div>
          {activeBlock && (
            <div
              style={{
                padding: '10px 12px',
                borderRadius: 'var(--r-control)',
                border: '1px solid var(--border)',
                background: 'var(--bg-subtle)',
                fontSize: '13px',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px',
              }}
            >
              <span style={{ color: 'var(--text-subtle)', fontFamily: 'var(--font-jp)' }}>
                {activeBlock.src}
              </span>
              <span style={{ fontWeight: 600, color: 'var(--text)' }}>{activeBlock.dst}</span>
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        <button
          type="button"
          className="btn-secondary pressable"
          onClick={() => onCopy(result.fullDst)}
        >
          <IconCopy size={18} />
          {strings.copyText}
        </button>
        {viewMode === 'overlay' && hasSfxBlocks && (
          <button
            type="button"
            className="btn-secondary pressable"
            aria-pressed={showSfx}
            onClick={() => setShowSfx((v) => !v)}
          >
            {strings.mangaSfxToggle}: {showSfx ? 'ON' : 'OFF'}
          </button>
        )}
        {viewMode === 'overlay' && (
          <button
            type="button"
            className="btn-primary pressable"
            onClick={handleDownloadOverlay}
          >
            <IconDownload size={18} />
            {strings.downloadImage}
          </button>
        )}
      </div>
    </div>
  );
}
