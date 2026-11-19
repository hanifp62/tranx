export interface BeforeInstallPromptEvent extends Event {
  readonly platforms?: string[];
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
  prompt(): Promise<void>;
}

export interface PwaInstallState {
  canNativePrompt: boolean;
  isInstalled: boolean;
  isIosSafari: boolean;
  isMacSafari: boolean;
}

const INSTALLED_DEVICE_KEY = 'tranx_pwa_installed_device_v1';

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

function readInstalledDeviceFlag(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(INSTALLED_DEVICE_KEY) === '1';
  } catch {
    return false;
  }
}

function writeInstalledDeviceFlag(installed: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    if (installed) {
      window.localStorage.setItem(INSTALLED_DEVICE_KEY, '1');
    } else {
      window.localStorage.removeItem(INSTALLED_DEVICE_KEY);
    }
  } catch {
    // ignore storage errors
  }
}

function detectPlatform(): { isIosSafari: boolean; isMacSafari: boolean } {
  if (typeof navigator === 'undefined') return { isIosSafari: false, isMacSafari: false };
  const ua = navigator.userAgent || '';
  const isIos =
    /iPad|iPhone|iPod/i.test(ua) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isWebKitSafari = /Safari/i.test(ua) && !/Chrome|CriOS|FxiOS|Edg|OPR|Android/i.test(ua);
  const isMac = /Macintosh|Mac OS X/i.test(ua) && !isIos;
  return {
    isIosSafari: isIos && isWebKitSafari,
    isMacSafari: isMac && isWebKitSafari,
  };
}

export function getPwaInstallState(): PwaInstallState {
  const { isIosSafari, isMacSafari } = detectPlatform();
  const isStandalone = detectStandaloneInstalled();
  return {
    canNativePrompt: deferredPrompt !== null,
    isInstalled: installedFlag || isStandalone || readInstalledDeviceFlag(),
    isIosSafari,
    isMacSafari,
  };
}

function emit(): void {
  const snapshot = getPwaInstallState();
  listeners.forEach((fn) => fn(snapshot));
}

export function initPwaInstallCapture(): void {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;
  installedFlag = detectStandaloneInstalled() || readInstalledDeviceFlag();
  if (detectStandaloneInstalled()) {
    writeInstalledDeviceFlag(true);
  }

  // Native OS check on Chromium browsers (works even when opened in a regular tab!)
  const navWithRelated = navigator as Navigator & {
    getInstalledRelatedApps?: () => Promise<Array<{ platform?: string; url?: string }>>;
  };
  if (typeof navWithRelated.getInstalledRelatedApps === 'function') {
    navWithRelated
      .getInstalledRelatedApps()
      .then((apps) => {
        if (Array.isArray(apps) && apps.length > 0) {
          installedFlag = true;
          writeInstalledDeviceFlag(true);
          deferredPrompt = null;
          emit();
        }
      })
      .catch(() => {});
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
