import { memo } from 'react';
import type { UiStrings } from '../i18n/strings';
import { BrandAppTile, BrandWordmark } from './Icons';

interface NotFoundViewProps {
  badPath: string;
  strings: UiStrings;
  onGoHome: () => void;
}

export const NotFoundView = memo(function NotFoundView({
  badPath,
  strings,
  onGoHome,
}: NotFoundViewProps) {
  return (
    <main className="auth-screen" role="main" aria-labelledby="tranx-404-title">
      <div className="auth-card not-found-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <BrandAppTile size={40} />
            <BrandWordmark />
          </div>
          <span className="not-found-badge" aria-label="HTTP 404">
            404
          </span>
        </div>

        <h1 id="tranx-404-title" className="not-found-title">
          {strings.notFoundTitle}
        </h1>

        <p className="not-found-desc">{strings.notFoundDesc}</p>

        <code className="not-found-path" aria-label="Requested path">
          {badPath.slice(0, 120)}
        </code>

        <button
          type="button"
          className="btn-primary pressable"
          style={{ width: '100%', minHeight: '44px' }}
          onClick={onGoHome}
        >
          {strings.backToHomeBtn}
        </button>
      </div>
    </main>
  );
});
