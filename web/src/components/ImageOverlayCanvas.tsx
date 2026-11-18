import { useEffect, useRef, useState } from 'react';
import type { ImageTranslationResult, ResolvedTheme } from '../types';
import type { UiStrings } from '../i18n/strings';
import { IconCopy, IconDownload } from './Icons';

interface Props {
  result: ImageTranslationResult;
  fileName?: string;
  resolvedTheme: ResolvedTheme;
  strings: UiStrings;
  onCopy: (text: string) => void;
}

export function ImageResultCard({
  result,
  fileName,
  resolvedTheme,
  strings,
  onCopy,
}: Props) {
  const [viewMode, setViewMode] = useState<'side' | 'overlay'>('side');
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (viewMode !== 'overlay' || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const w = Math.max(320, result.width || 640);
    const h = Math.max(240, result.height || 480);
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const drawBubbles = () => {
      for (const blk of result.blocks) {
        const [bx, by, bw, bh] = blk.box;
        ctx.save();
        ctx.fillStyle = resolvedTheme === 'Gelap' ? '#1F2423F2' : '#FFFFFFF2';
        ctx.strokeStyle = resolvedTheme === 'Gelap' ? '#5DC3AC' : '#17695B';
        ctx.lineWidth = 2;
        ctx.beginPath();
        if (typeof ctx.roundRect === 'function') {
          ctx.roundRect(bx, by, bw, bh, 10);
        } else {
          ctx.rect(bx, by, bw, bh);
        }
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = resolvedTheme === 'Gelap' ? '#E7ECEA' : '#141917';
        const fontSize = Math.max(13, Math.min(20, Math.floor(bh / 3.5)));
        ctx.font = `${fontSize}px Charter, Georgia, serif`;
        ctx.textBaseline = 'top';

        const words = blk.dst.split(/\s+/);
        let line = '';
        let yCursor = by + 8;
        const maxTextW = Math.max(40, bw - 16);
        for (const word of words) {
          const candidate = line ? `${line} ${word}` : word;
          if (ctx.measureText(candidate).width > maxTextW && line) {
            ctx.fillText(line, bx + 8, yCursor);
            line = word;
            yCursor += fontSize + 5;
            if (yCursor > by + bh - fontSize) break;
          } else {
            line = candidate;
          }
        }
        if (line && yCursor <= by + bh - 4) {
          ctx.fillText(line, bx + 8, yCursor);
        }
        ctx.restore();
      }
    };

    ctx.fillStyle = resolvedTheme === 'Gelap' ? '#171B1A' : '#FAFBFA';
    ctx.fillRect(0, 0, w, h);

    if (result.dataUrl) {
      const img = new Image();
      img.onload = () => {
        ctx.drawImage(img, 0, 0, w, h);
        drawBubbles();
      };
      img.onerror = () => drawBubbles();
      img.src = result.dataUrl;
    } else {
      drawBubbles();
    }
  }, [viewMode, result, resolvedTheme]);

  const handleDownloadOverlay = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const url = canvas.toDataURL('image/png');
    const a = document.createElement('a');
    a.href = url;
    a.download = `tranx-${(fileName || 'gambar').replace(/\.[^.]+$/, '')}-overlay.png`;
    a.click();
  };

  return (
    <div className="result-card">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="status-badge done">Selesai</span>
          <span style={{ fontSize: '14px', fontWeight: 600 }}>
            {fileName || 'Gambar Jepang'}
          </span>
        </div>
        <div style={{ display: 'inline-flex', gap: '6px' }} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === 'side'}
            className={viewMode === 'side' ? 'btn-primary pressable' : 'btn-secondary pressable'}
            onClick={() => setViewMode('side')}
          >
            {strings.sideBySide}
          </button>
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
        </div>
      </div>

      {viewMode === 'side' ? (
        <div className="form-grid-2" style={{ alignItems: 'start' }}>
          {result.dataUrl ? (
            <img
              src={result.dataUrl}
              alt={fileName || 'Sumber gambar Jepang'}
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
                    fontSize: '14px',
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
        <div style={{ width: '100%', overflowX: 'auto' }}>
          <canvas
            ref={canvasRef}
            style={{
              width: '100%',
              height: 'auto',
              borderRadius: 'var(--r-control)',
              border: '1px solid var(--border)',
              display: 'block',
            }}
          />
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <button
          type="button"
          className="btn-secondary pressable"
          onClick={() => onCopy(result.fullDst)}
        >
          <IconCopy size={18} />
          {strings.copyText}
        </button>
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
