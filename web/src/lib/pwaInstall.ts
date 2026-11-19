export interface BeforeInstallPromptEvent extends Event {
  readonly platforms?: string[];
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
  prompt(): Promise<void>;
}

export interface PwaInstallState {
  canNativePrompt: boolean;
  isInstalled: boolean;
  shouldShowInstallButton: boolean;
  isIosSafari: boolean;
  isMacSafari: boolean;
  isAndroid: boolean;
}

interface EarlyPwaStore {
  deferredPrompt: BeforeInstallPromptEvent | null;
  appInstalled: boolean;
}

const LEGACY_INSTALLED_KEY = 'tranx_pwa_installed_device_v1';
const INSTALLED_DEVICE_KEY = 'tranx_pwa_installed_v2';
const RELATED_APP_ORIGINS = new Set([
  'https://tranx-hanif-id.web.app',
  'https://tranx-hanif-id.firebaseapp.com',
]);
const POST_INSTALL_GRACE_MS = 20_000;
const FALLBACK_STORAGE_TTL_MS = 24 * 60 * 60 * 1000;

let deferredPrompt: BeforeInstallPromptEvent | null = null;
let installedFlag = false;
let initialized = false;
const listeners = new Set<(state: PwaInstallState) => void>();

function detectStandaloneInstalled(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia?.('(display-mode: standalone)').matches) return true;
  if (window.matchMedia?.('(display-mode: window-controls-overlay)').matches) return true;
  if ((window.navigator as Navigator & { standalone?: boolean }).standalone === true) return true;
  if (typeof document !== 'undefined' && document.referrer.startsWith('android-app://')) return true;
  return false;
}

function readInstalledRecord(): { installedAt: number } | null {
  if (typeof window === 'undefined') return null;
  try {
    if (window.localStorage.getItem(LEGACY_INSTALLED_KEY) !== null) {
      window.localStorage.removeItem(LEGACY_INSTALLED_KEY);
    }
    const raw = window.localStorage.getItem(INSTALLED_DEVICE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { installedAt?: number };
    if (typeof parsed?.installedAt === 'number' && Number.isFinite(parsed.installedAt)) {
      if (Date.now() - parsed.installedAt > FALLBACK_STORAGE_TTL_MS && !detectStandaloneInstalled()) {
        window.localStorage.removeItem(INSTALLED_DEVICE_KEY);
        return null;
      }
      return { installedAt: parsed.installedAt };
    }
  } catch {
    // ignore storage errors
  }
  return null;
}

function readInstalledDeviceFlag(): boolean {
  return readInstalledRecord() !== null;
}

function writeInstalledDeviceFlag(installed: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(LEGACY_INSTALLED_KEY);
    if (installed) {
      window.localStorage.setItem(
        INSTALLED_DEVICE_KEY,
        JSON.stringify({ installedAt: Date.now() })
      );
    } else {
      window.localStorage.removeItem(INSTALLED_DEVICE_KEY);
    }
  } catch {
    // ignore storage errors
  }
}

function detectPlatform(): {
  isIosSafari: boolean;
  isMacSafari: boolean;
  isAndroid: boolean;
  isChromiumDesktop: boolean;
} {
  if (typeof navigator === 'undefined') {
    return { isIosSafari: false, isMacSafari: false, isAndroid: false, isChromiumDesktop: false };
  }
  const ua = navigator.userAgent || '';
  const isAndroid = /Android/i.test(ua);
  const isIos =
    /iPad|iPhone|iPod/i.test(ua) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isWebKitSafari = /Safari/i.test(ua) && !/Chrome|CriOS|FxiOS|Edg|OPR|Android/i.test(ua);
  const isMac = /Macintosh|Mac OS X/i.test(ua) && !isIos;
  const isChromium = /Chrome|Chromium|Edg\/|OPR\//i.test(ua) && !/Firefox|FxiOS/i.test(ua);
  const isChromiumDesktop = isChromium && !isAndroid && !isIos;
  return {
    isIosSafari: isIos && isWebKitSafari,
    isMacSafari: isMac && isWebKitSafari,
    isAndroid,
    isChromiumDesktop,
  };
}

export function getPwaInstallState(): PwaInstallState {
  const { isIosSafari, isMacSafari, isAndroid, isChromiumDesktop } = detectPlatform();
  const isStandalone = detectStandaloneInstalled();
  const canNativePrompt = deferredPrompt !== null;
  const isInstalled = installedFlag || isStandalone || readInstalledDeviceFlag();

  // On Desktop Chrome/Edge/Brave, Chrome fires beforeinstallprompt when uninstalled and suppresses it
  // when already installed ("Open in app" in address bar). Showing Install only when canNativePrompt is true
  // guarantees 1-click direct native installation and hides the button automatically when already installed!
  // On Android & Safari/Firefox, show when !isInstalled (1-click when prompt ready, platform guide otherwise).
  const shouldShowInstallButton =
    !isInstalled && (canNativePrompt || !isChromiumDesktop);

  return {
    canNativePrompt,
    isInstalled,
    shouldShowInstallButton,
    isIosSafari,
    isMacSafari,
    isAndroid,
  };
}

function emit(): void {
  const snapshot = getPwaInstallState();
  listeners.forEach((fn) => fn(snapshot));
}

export function refreshInstalledRelatedApps(): void {
  if (typeof window === 'undefined') return;
  if (detectStandaloneInstalled()) {
    installedFlag = true;
    writeInstalledDeviceFlag(true);
    deferredPrompt = null;
    emit();
    return;
  }

  const navWithRelated = navigator as Navigator & {
    getInstalledRelatedApps?: () => Promise<Array<{ platform?: string; url?: string }>>;
  };
  if (typeof navWithRelated.getInstalledRelatedApps !== 'function') return;

  const { isAndroid } = detectPlatform();
  const isMockRelated = Boolean(
    (window as unknown as { __tranxMockRelatedApps?: boolean }).__tranxMockRelatedApps
  );
  // getInstalledRelatedApps() for webapp platform is authoritative on Android Chrome WebAPKs
  // (Desktop Chrome can return [] even while the desktop PWA is installed and showing "Open in app").
  const canClearFromEmpty =
    isMockRelated || (isAndroid && RELATED_APP_ORIGINS.has(window.location.origin));

  navWithRelated
    .getInstalledRelatedApps()
    .then((apps) => {
      if (!Array.isArray(apps)) return;
      if (apps.length > 0) {
        installedFlag = true;
        writeInstalledDeviceFlag(true);
        deferredPrompt = null;
        emit();
        return;
      }
      if (canClearFromEmpty && !detectStandaloneInstalled()) {
        const rec = readInstalledRecord();
        const withinGrace = Boolean(rec && Date.now() - rec.installedAt < POST_INSTALL_GRACE_MS);
        if (!withinGrace && (installedFlag || rec !== null)) {
          installedFlag = false;
          writeInstalledDeviceFlag(false);
          emit();
        }
      }
    })
    .catch(() => {});
}

export function initPwaInstallCapture(): void {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;

  // Adopt any beforeinstallprompt / appinstalled captured synchronously by /pwa-capture.js in <head>
  const early = (window as unknown as { __tranxEarlyPwa?: EarlyPwaStore }).__tranxEarlyPwa;
  if (early?.deferredPrompt) {
    deferredPrompt = early.deferredPrompt;
    early.deferredPrompt = null;
    installedFlag = false;
    writeInstalledDeviceFlag(false);
  } else if (early?.appInstalled) {
    installedFlag = true;
    writeInstalledDeviceFlag(true);
  } else {
    installedFlag = detectStandaloneInstalled() || readInstalledDeviceFlag();
    if (detectStandaloneInstalled()) {
      writeInstalledDeviceFlag(true);
    }
  }

  refreshInstalledRelatedApps();

  window.addEventListener('focus', () => refreshInstalledRelatedApps());
  window.addEventListener('pageshow', () => refreshInstalledRelatedApps());
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        refreshInstalledRelatedApps();
      }
    });
  }

  // Browser fires beforeinstallprompt ONLY when the app is NOT currently installed on this device
  window.addEventListener('beforeinstallprompt', (ev: Event) => {
    ev.preventDefault();
    deferredPrompt = ev as BeforeInstallPromptEvent;
    installedFlag = false;
    writeInstalledDeviceFlag(false);
    emit();
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    installedFlag = true;
    writeInstalledDeviceFlag(true);
    emit();
  });

  const mq = window.matchMedia?.('(display-mode: standalone)');
  mq?.addEventListener?.('change', (e) => {
    if (e.matches) {
      installedFlag = true;
      writeInstalledDeviceFlag(true);
      deferredPrompt = null;
      emit();
    } else {
      refreshInstalledRelatedApps();
    }
  });
}

export function subscribePwaInstallState(fn: (state: PwaInstallState) => void): () => void {
  initPwaInstallCapture();
  listeners.add(fn);
  fn(getPwaInstallState());
  return () => {
    listeners.delete(fn);
  };
}

export async function triggerNativePwaInstall(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
  if (!deferredPrompt) return 'unavailable';
  const promptEvent = deferredPrompt;
  deferredPrompt = null;
  emit();
  try {
    await promptEvent.prompt();
    const choice = await promptEvent.userChoice;
    if (choice?.outcome === 'accepted') {
      installedFlag = true;
      writeInstalledDeviceFlag(true);
      emit();
      return 'accepted';
    }
    return 'dismissed';
  } catch {
    return 'unavailable';
  }
}
