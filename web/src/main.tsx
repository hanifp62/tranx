import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { bootstrapFirebaseConfig, isLocalE2EMode } from './lib/firebase';
import { initPwaInstallCapture } from './lib/pwaInstall';
import './styles/tokens.css';
import './styles/app.css';
import { App } from './App';

// Capture beforeinstallprompt & appinstalled synchronously before React mounts
initPwaInstallCapture();

if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
  const hadPreviousController = Boolean(navigator.serviceWorker.controller);
  let lastSwCheckAt = 0;

  const checkForSwUpdate = () => {
    const now = Date.now();
    if (now - lastSwCheckAt < 5 * 60 * 1000) return;
    lastSwCheckAt = now;
    navigator.serviceWorker
      .getRegistrations()
      .then((regs) => {
        regs.forEach((reg) => {
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

  if (hadPreviousController) {
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!window.sessionStorage.getItem('tranx_sw_reloaded')) {
        window.sessionStorage.setItem('tranx_sw_reloaded', '1');
        window.location.reload();
      }
    });
  }
}

function mountApp() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>
  );
}

if (isLocalE2EMode()) {
  mountApp();
} else {
  bootstrapFirebaseConfig().finally(mountApp);
}
