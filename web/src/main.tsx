import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/tokens.css';
import './styles/app.css';
import { App } from './App';

if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
  const hadPreviousController = Boolean(navigator.serviceWorker.controller);

  navigator.serviceWorker
    .getRegistrations()
    .then((regs) => {
      regs.forEach((reg) => {
        reg.update().catch(() => {});
      });
    })
    .catch(() => {});

  if (hadPreviousController) {
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!window.sessionStorage.getItem('tranx_sw_reloaded')) {
        window.sessionStorage.setItem('tranx_sw_reloaded', '1');
        window.location.reload();
      }
    });
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
