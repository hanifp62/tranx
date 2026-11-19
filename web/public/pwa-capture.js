/* Ultra-early synchronous PWA install event capture (runs in <head> before React ES modules load).
 * Single canonical prompt holder shared with pwaInstall.ts so beforeinstallprompt is never lost or desynced.
 */
(function () {
  var store = (window.__tranxEarlyPwa = window.__tranxEarlyPwa || {
    deferredPrompt: null,
    appInstalled: false,
    capturedAt: 0,
    promptCount: 0,
  });
  window.addEventListener('beforeinstallprompt', function (ev) {
    ev.preventDefault();
    store.deferredPrompt = ev;
    store.appInstalled = false;
    store.capturedAt = Date.now();
    store.promptCount = (store.promptCount || 0) + 1;
    try {
      window.dispatchEvent(new CustomEvent('tranx:pwa-prompt-ready'));
    } catch (_e) {
      // ignore
    }
  });
  window.addEventListener('appinstalled', function () {
    store.deferredPrompt = null;
    store.appInstalled = true;
    try {
      window.dispatchEvent(new CustomEvent('tranx:pwa-installed'));
    } catch (_e) {
      // ignore
    }
  });
})();
