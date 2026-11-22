import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { initPwaInstallCapture } from './lib/pwaInstall';
import './styles/tokens.css';
import './styles/app.css';
import { App } from './App';
import { ErrorBoundary } from './components/ErrorBoundary';

// Capture beforeinstallprompt & appinstalled synchronously before React mounts
initPwaInstallCapture();

if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
  let lastSwCheckAt = 0;

  const emitSwUpdateReady = (reg: ServiceWorkerRegistration) => {
    const waiting = reg.waiting;
    if (!waiting || !navigator.serviceWorker.controller) return;
    window.dispatchEvent(
      new CustomEvent('tranx:sw-update-ready', {
        detail: {
          applyUpdate: () => {
            waiting.postMessage({ type: 'SKIP_WAITING' });
          },
        },
      })
    );
  };

  const watchRegistration = (reg: ServiceWorkerRegistration) => {
    if (reg.waiting && navigator.serviceWorker.controller) {
      emitSwUpdateReady(reg);
    }
    reg.addEventListener('updatefound', () => {
      const installing = reg.installing;
      if (!installing) return;
      installing.addEventListener('statechange', () => {
        if (installing.state === 'installed' && navigator.serviceWorker.controller) {
          emitSwUpdateReady(reg);
        }
      });
    });
  };

  const checkForSwUpdate = () => {
    const now = Date.now();
    if (now - lastSwCheckAt < 5 * 60 * 1000) return;
    lastSwCheckAt = now;
    navigator.serviceWorker
      .getRegistrations()
      .then((regs) => {
        regs.forEach((reg) => {
          watchRegistration(reg);
          reg.update().catch(() => {});
        });
      })
      .catch(() => {});
  };

  checkForSwUpdate();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      checkForSwUpdate();
    }
  });

  // Reload ONLY after the user explicitly accepted an update via the non-blocking banner
  let userRequestedReload = false;
  window.addEventListener('tranx:sw-apply-requested', () => {
    userRequestedReload = true;
  });
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (userRequestedReload) {
      userRequestedReload = false;
      window.location.reload();
    }
  });
}

// Mount React immediately for sub-second cold LCP (Firebase init resolves asynchronously in subscribeAuth)
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
);
