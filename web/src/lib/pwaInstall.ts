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
  isDismissed: boolean;
}

const DISMISS_KEY = 'tranx_pwa_install_dismissed_at';
const DISMISS_TTL_MS = 7 * 24 * 60 * 60 * 1000;

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

function readDismissed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const raw = window.localStorage.getItem(DISMISS_KEY);
    if (!raw) return false;
    const ts = Number(raw);
    return Number.isFinite(ts) && Date.now() - ts < DISMISS_TTL_MS;
  } catch {
    return false;
  }
}

export function getPwaInstallState(): PwaInstallState {
  const { isIosSafari, isMacSafari } = detectPlatform();
  return {
    canNativePrompt: deferredPrompt !== null,
    isInstalled: installedFlag || detectStandaloneInstalled(),
    isIosSafari,
    isMacSafari,
    isDismissed: readDismissed(),
  };
}

function emit(): void {
  const snapshot = getPwaInstallState();
  listeners.forEach((fn) => fn(snapshot));
}

export function initPwaInstallCapture(): void {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;
  installedFlag = detectStandaloneInstalled();

  window.addEventListener('beforeinstallprompt', (ev: Event) => {
    ev.preventDefault();
    deferredPrompt = ev as BeforeInstallPromptEvent;
    emit();
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    installedFlag = true;
    try {
      window.localStorage.removeItem(DISMISS_KEY);
    } catch {
      // ignore
    }
    emit();
  });

  const mq = window.matchMedia?.('(display-mode: standalone)');
  mq?.addEventListener?.('change', (e) => {
    if (e.matches) {
      installedFlag = true;
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

export function dismissPwaInstallBanner(): void {
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      // ignore
    }
  }
  emit();
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
      emit();
      return 'accepted';
    }
    return 'dismissed';
  } catch {
    return 'unavailable';
  }
}
