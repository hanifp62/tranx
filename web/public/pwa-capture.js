/* Ultra-early synchronous PWA install event capture (runs in <head> before React ES modules load).
 * Prevents losing Chrome's beforeinstallprompt when SW/manifest resolves faster than the main bundle.
 */
(function () {
  var store = (window.__tranxEarlyPwa = window.__tranxEarlyPwa || {
    deferredPrompt: null,
    appInstalled: false,
  });
  window.addEventListener('beforeinstallprompt', function (ev) {
    ev.preventDefault();
    store.deferredPrompt = ev;
    store.appInstalled = false;
  });
  window.addEventListener('appinstalled', function () {
    store.deferredPrompt = null;
    store.appInstalled = true;
  });
})();
