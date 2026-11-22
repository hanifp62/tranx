import { Component, type ErrorInfo, type ReactNode } from 'react';
import { clearLocalUserCaches } from '../lib/firebase';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  errorCode: string;
  resettingCache: boolean;
  retryKey: number;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
    errorCode: '',
    resettingCache: false,
    retryKey: 0,
  };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    const rawName = (error?.name || 'RenderError').replace(/[^A-Za-z0-9_]/g, '').slice(0, 32);
    return {
      hasError: true,
      errorCode: rawName || 'RenderError',
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Capture PII-free structural metadata only (never log raw user content or stack secrets).
    try {
      const frameCount = (info?.componentStack || '').split('\n').filter(Boolean).length;
      window.sessionStorage?.setItem(
        'tranx_last_boundary_event',
        JSON.stringify({
          code: (error?.name || 'RenderError').slice(0, 32),
          frames: frameCount,
          ts: Date.now(),
        })
      );
    } catch {
      // ignore storage restrictions
    }
  }

  private handleSoftRetry = () => {
    this.setState((prev) => ({
      hasError: false,
      errorCode: '',
      resettingCache: false,
      retryKey: prev.retryKey + 1,
    }));
  };

  private handleResetLocalCache = async () => {
    if (this.state.resettingCache) return;
    this.setState({ resettingCache: true });
    try {
      clearLocalUserCaches();
    } catch {
      // ignore storage wipe errors
    }
    this.setState((prev) => ({
      hasError: false,
      errorCode: '',
      resettingCache: false,
      retryKey: prev.retryKey + 1,
    }));
  };

  private handleGoHome = () => {
    window.location.assign('/');
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return <div key={this.state.retryKey} style={{ display: 'contents' }}>{this.props.children}</div>;
    }
    const isEn = typeof document !== 'undefined' && document.documentElement.lang === 'en';
    return (
      <main
        className="auth-screen"
        data-error-boundary="true"
        style={{ padding: '24px' }}
      >
        <div className="auth-card not-found-card" style={{ maxWidth: '460px' }}>
          <span className="not-found-badge" role="alert" aria-live="assertive">
            {isEn ? 'Recovery' : 'Pemulihan'}
            {this.state.errorCode ? ` · ${this.state.errorCode}` : ''}
          </span>
          <h1 className="not-found-title">
            {isEn ? 'Something interrupted this view' : 'Tampilan sempat terganggu'}
          </h1>
          <p className="not-found-desc">
            {isEn
              ? 'Your Google account, cloud history, and saved settings remain safe. Try resuming, clear the local cache, or return home.'
              : 'Akun Google, riwayat cloud, dan pengaturan Anda tetap aman. Coba muat ulang tampilan, bersihkan cache lokal, atau kembali ke beranda.'}
          </p>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '4px' }}>
            <button
              type="button"
              className="btn-primary pressable"
              data-boundary-retry="true"
              style={{ minHeight: '44px' }}
              onClick={this.handleSoftRetry}
            >
              {isEn ? 'Try again' : 'Coba lagi'}
            </button>
            <button
              type="button"
              className="btn-secondary pressable"
              data-boundary-reset-cache="true"
              style={{ minHeight: '44px' }}
              disabled={this.state.resettingCache}
              onClick={() => void this.handleResetLocalCache()}
            >
              {this.state.resettingCache
                ? isEn
                  ? 'Clearing cache...'
                  : 'Membersihkan cache...'
                : isEn
                  ? 'Reset local cache & retry'
                  : 'Reset cache lokal & coba lagi'}
            </button>
            <button
              type="button"
              className="btn-secondary pressable"
              style={{ minHeight: '44px' }}
              onClick={this.handleGoHome}
            >
              {isEn ? 'Back to Home' : 'Kembali ke Beranda'}
            </button>
          </div>
        </div>
      </main>
    );
  }
}
