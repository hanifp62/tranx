/**
 * Ebook Reader HCI Preferences v2 (2025/2026 Two-Tier Surface Architecture):
 * - Tier 1 (App Shell Chrome): follows OS/App settings.theme (Terang / Gelap / Sistem)
 * - Tier 2 (Ebook Reading Canvas): Dual-Slot Adaptive Pairing (Day Paper + Night Paper)
 *   so choosing Sepia by day NEVER blasts bright light when OS switches to Dark Mode at night,
 *   plus optional explicit Lock mode, dynamic <meta name="theme-color"> & color-scheme sync.
 * - 6 WCAG AA/AAA Verified Reading Themes + 14 Lazy-Loaded Publisher Reading Fonts
 * - Scientific Reading Time Estimator (Brysbaert 2019 / IReST)
 */

import type { CSSProperties } from 'react';
import type { TargetLang } from '../types';

export type EbookDayThemeId = 'paper' | 'sepia' | 'sage' | 'eink';
export type EbookNightThemeId = 'dusk' | 'midnight';
export type EbookThemeId = EbookDayThemeId | EbookNightThemeId;
export type EbookThemeMode = 'adaptive' | 'locked';
export type EbookPageMode = 'scroll' | 'slide' | 'flip';
export type EbookMeasure = 'narrow' | 'standard' | 'wide';
export type EbookAlign = 'left' | 'justify';
export type EbookSpreadMode = 'single' | 'auto';
export type EbookReadingRulerMode = 'off' | 'bar' | 'shade' | 'underline';
export type EbookTapZoneMode = 'edges' | 'right-hand' | 'left-hand';

export interface EbookThemeSpec {
  id: EbookThemeId;
  labelId: string;
  labelEn: string;
  isDark: boolean;
  bg: string;
  surface: string;
  ink: string;
  muted: string;
  accent: string;
  border: string;
  borderStrong: string;
}

export const EBOOK_THEMES: readonly EbookThemeSpec[] = [
  {
    id: 'paper',
    labelId: 'Kertas',
    labelEn: 'Paper',
    isDark: false,
    bg: '#FAF6EE',
    surface: '#F2ECE0',
    ink: '#221F1A',
    muted: '#5C564C',
    accent: '#166658',
    border: '#DDD5C7',
    borderStrong: '#756E61',
  },
  {
    id: 'sepia',
    labelId: 'Sepia',
    labelEn: 'Sepia',
    isDark: false,
    bg: '#F4ECD8',
    surface: '#EAE0C6',
    ink: '#38281B',
    muted: '#614D3A',
    accent: '#8C4214',
    border: '#D4C5A6',
    borderStrong: '#786246',
  },
  {
    id: 'sage',
    labelId: 'Hijau Teduh',
    labelEn: 'Sage',
    isDark: false,
    bg: '#E3EDE2',
    surface: '#D6E3D5',
    ink: '#192920',
    muted: '#3B5245',
    accent: '#145E50',
    border: '#B8CBB7',
    borderStrong: '#4D6957',
  },
  {
    id: 'dusk',
    labelId: 'Senja',
    labelEn: 'Dusk',
    isDark: true,
    bg: '#1E1F22',
    surface: '#27292E',
    ink: '#DDD8CE',
    muted: '#A39F97',
    accent: '#66CBB5',
    border: '#3A3D45',
    borderStrong: '#828694',
  },
  {
    id: 'midnight',
    labelId: 'Malam OLED',
    labelEn: 'Midnight',
    isDark: true,
    bg: '#141416',
    surface: '#1E1F23',
    ink: '#D9D4CA',
    muted: '#9B968D',
    accent: '#DFA95B',
    border: '#303138',
    borderStrong: '#7C7F8D',
  },
  {
    id: 'eink',
    labelId: 'E-Ink',
    labelEn: 'E-Ink',
    isDark: false,
    bg: '#F4F4F2',
    surface: '#EAEAE6',
    ink: '#121212',
    muted: '#4B4B48',
    accent: '#1F1F1D',
    border: '#C7C7C1',
    borderStrong: '#696964',
  },
] as const;

export const EBOOK_DAY_THEMES: readonly EbookThemeSpec[] = EBOOK_THEMES.filter((t) => !t.isDark);
export const EBOOK_NIGHT_THEMES: readonly EbookThemeSpec[] = EBOOK_THEMES.filter((t) => t.isDark);

export interface EbookFontSpec {
  id: string;
  name: string;
  noteId: string;
  noteEn: string;
  category: 'serif' | 'sans' | 'slab' | 'jp';
  stack: string;
  googleSpec?: string;
}

/**
 * 14 curated best reading fonts used by famous authors, literary publishers, and top ebook apps.
 * Unused Google Fonts are NEVER fetched on initial app load; they load lazily when selected.
 */
export const EBOOK_FONTS: readonly EbookFontSpec[] = [
  {
    id: 'charter',
    name: 'Charter',
    noteId: 'Apple Books · Bawaan',
    noteEn: 'Apple Books · Built-in',
    category: 'serif',
    stack: "Charter, 'Bitstream Charter', Georgia, Cambria, serif",
  },
  {
    id: 'literata',
    name: 'Literata',
    noteId: 'Google Play Books · Novel',
    noteEn: 'Google Play Books · Novels',
    category: 'serif',
    stack: "'Literata', Charter, Georgia, serif",
    googleSpec: 'Literata:ital,opsz,wght@0,7..72,400..700;1,7..72,400..600',
  },
  {
    id: 'eb-garamond',
    name: 'EB Garamond',
    noteId: 'Penguin Classics · Sastra',
    noteEn: 'Penguin Classics · Fiction',
    category: 'serif',
    stack: "'EB Garamond', Garamond, 'Palatino Linotype', Georgia, serif",
    googleSpec: 'EB+Garamond:ital,wght@0,400..700;1,400..600',
  },
  {
    id: 'libre-caslon',
    name: 'Libre Caslon Text',
    noteId: 'The New Yorker · Klasik',
    noteEn: 'The New Yorker · Classic',
    category: 'serif',
    stack: "'Libre Caslon Text', 'Big Caslon', Georgia, serif",
    googleSpec: 'Libre+Caslon+Text:ital,wght@0,400;0,700;1,400',
  },
  {
    id: 'libre-baskerville',
    name: 'Libre Baskerville',
    noteId: 'Oxford Press · Tegas',
    noteEn: 'Oxford Press · Crisp',
    category: 'serif',
    stack: "'Libre Baskerville', Baskerville, Georgia, serif",
    googleSpec: 'Libre+Baskerville:ital,wght@0,400;0,700;1,400',
  },
  {
    id: 'crimson-pro',
    name: 'Crimson Pro',
    noteId: 'Sabon · Novel Halus',
    noteEn: 'Sabon · Fine Book',
    category: 'serif',
    stack: "'Crimson Pro', Palatino, Georgia, serif",
    googleSpec: 'Crimson+Pro:ital,wght@0,400..700;1,400..600',
  },
  {
    id: 'source-serif-4',
    name: 'Source Serif 4',
    noteId: 'Adobe · Tajam di HP',
    noteEn: 'Adobe · Sharp on Mobile',
    category: 'serif',
    stack: "'Source Serif 4', Charter, Georgia, serif",
    googleSpec: 'Source+Serif+4:ital,opsz,wght@0,8..60,400..700;1,8..60,400..600',
  },
  {
    id: 'newsreader',
    name: 'Newsreader',
    noteId: 'Bacaan Panjang Editorial',
    noteEn: 'Long-Form Editorial',
    category: 'serif',
    stack: "'Newsreader', Georgia, serif",
    googleSpec: 'Newsreader:ital,opsz,wght@0,6..72,400..700;1,6..72,400..600',
  },
  {
    id: 'lora',
    name: 'Lora',
    noteId: 'Kaligrafis Hangat',
    noteEn: 'Warm Calligraphic',
    category: 'serif',
    stack: "'Lora', Georgia, serif",
    googleSpec: 'Lora:ital,wght@0,400..700;1,400..600',
  },
  {
    id: 'merriweather',
    name: 'Merriweather',
    noteId: 'Tinggi & Nyaman di Layar',
    noteEn: 'High x-Height Screen Serif',
    category: 'serif',
    stack: "'Merriweather', Georgia, Cambria, serif",
    googleSpec: 'Merriweather:ital,wght@0,400;0,700;1,400',
  },
  {
    id: 'bitter',
    name: 'Bitter',
    noteId: 'Slab Serif · Ala Caecilia',
    noteEn: 'Slab Serif · Kindle Style',
    category: 'slab',
    stack: "'Bitter', Cambria, Georgia, serif",
    googleSpec: 'Bitter:ital,wght@0,400..700;1,400..600',
  },
  {
    id: 'inter',
    name: 'Inter',
    noteId: 'Sans Modern · Fokus',
    noteEn: 'Modern Sans · Focus',
    category: 'sans',
    stack: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
  {
    id: 'atkinson',
    name: 'Atkinson Hyperlegible',
    noteId: 'Braille Inst. · Super Jelas',
    noteEn: 'Braille Inst. · High Legibility',
    category: 'sans',
    stack: "'Atkinson Hyperlegible', Verdana, -apple-system, sans-serif",
    googleSpec: 'Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400',
  },
  {
    id: 'shippori-mincho',
    name: 'Shippori Mincho',
    noteId: 'Mincho Sastra Jepang',
    noteEn: 'Japanese Literary Mincho',
    category: 'jp',
    stack: "'Shippori Mincho', 'Hiragino Mincho ProN', 'Yu Mincho', serif",
    googleSpec: 'Shippori+Mincho:wght@400;600;700',
  },
] as const;

export interface EbookPrefs {
  /** 'adaptive' pairs dayTheme (App Light) + nightTheme (App Dark); 'locked' pins lockedTheme across all modes. */
  themeMode: EbookThemeMode;
  dayTheme: EbookDayThemeId;
  nightTheme: EbookNightThemeId;
  lockedTheme: EbookThemeId;
  /** Legacy compatibility mirror ('auto' when adaptive, or lockedTheme id when locked). */
  theme: EbookThemeId | 'auto';
  fontId: string;
  fontSize: number; // 14..32 px (WCAG 2.2 low-vision 200% scaling)
  lineHeight: number; // 1.5..2.05
  letterSpacing: number; // 0..0.14 em (WCAG 1.4.12 / Zorzi 2012)
  wordSpacing: number; // 0..0.20 em (WCAG 1.4.12)
  paragraphSpacing: number; // 0.8..2.2 em (WCAG 1.4.12)
  measure: EbookMeasure;
  align: EbookAlign;
  pageMode: EbookPageMode;
  spread: EbookSpreadMode;
  readingRuler: EbookReadingRulerMode;
  tapZone: EbookTapZoneMode;
  inlinePeek: boolean;
  zenMode: boolean;
}

export const DEFAULT_EBOOK_PREFS: EbookPrefs = {
  themeMode: 'adaptive',
  dayTheme: 'paper',
  nightTheme: 'dusk',
  lockedTheme: 'paper',
  theme: 'auto',
  fontId: 'literata',
  fontSize: 18,
  lineHeight: 1.75,
  letterSpacing: 0,
  wordSpacing: 0,
  paragraphSpacing: 1.05,
  measure: 'standard',
  align: 'left',
  pageMode: 'scroll',
  spread: 'single',
  readingRuler: 'off',
  tapZone: 'edges',
  inlinePeek: false,
  zenMode: false,
};

/** 1-tap empirically grounded Dyslexia / Low-Vision Comfort Preset (Zorzi 2012 / Rello 2013 / CHI '23). */
export const DYSLEXIA_COMFORT_PATCH: Partial<EbookPrefs> = {
  fontId: 'atkinson',
  fontSize: 20,
  lineHeight: 1.85,
  letterSpacing: 0.12,
  wordSpacing: 0.16,
  paragraphSpacing: 1.55,
  align: 'left',
  readingRuler: 'bar',
};

const STORAGE_KEY = 'tranx_ebook_prefs_v1';
const loadedGoogleFontIds = new Set<string>();

function isDayTheme(id: unknown): id is EbookDayThemeId {
  return id === 'paper' || id === 'sepia' || id === 'sage' || id === 'eink';
}

function isNightTheme(id: unknown): id is EbookNightThemeId {
  return id === 'dusk' || id === 'midnight';
}

function isAnyEbookTheme(id: unknown): id is EbookThemeId {
  return isDayTheme(id) || isNightTheme(id);
}

export function normalizeEbookPrefs(raw: Partial<EbookPrefs> | null | undefined): EbookPrefs {
  const p = raw && typeof raw === 'object' ? raw : {};

  let dayTheme: EbookDayThemeId = isDayTheme(p.dayTheme) ? p.dayTheme : DEFAULT_EBOOK_PREFS.dayTheme;
  let nightTheme: EbookNightThemeId = isNightTheme(p.nightTheme)
    ? p.nightTheme
    : DEFAULT_EBOOK_PREFS.nightTheme;
  let themeMode: EbookThemeMode =
    p.themeMode === 'locked' || p.themeMode === 'adaptive' ? p.themeMode : 'adaptive';
  let lockedTheme: EbookThemeId = isAnyEbookTheme(p.lockedTheme)
    ? p.lockedTheme
    : DEFAULT_EBOOK_PREFS.lockedTheme;

  // Seamless migration from v1 single-field `theme` when `themeMode` was not explicitly saved
  if (p.themeMode === undefined && p.theme !== undefined) {
    if (p.theme === 'auto') {
      themeMode = 'adaptive';
    } else if (isAnyEbookTheme(p.theme)) {
      themeMode = 'locked';
      lockedTheme = p.theme;
      if (isDayTheme(p.theme)) dayTheme = p.theme;
      if (isNightTheme(p.theme)) nightTheme = p.theme;
    }
  }

  const validFont = EBOOK_FONTS.some((f) => f.id === p.fontId)
    ? String(p.fontId)
    : DEFAULT_EBOOK_PREFS.fontId;
  const validPageMode: EbookPageMode =
    p.pageMode === 'scroll' || p.pageMode === 'slide' || p.pageMode === 'flip'
      ? p.pageMode
      : 'scroll';
  const validMeasure: EbookMeasure =
    p.measure === 'narrow' || p.measure === 'standard' || p.measure === 'wide'
      ? p.measure
      : 'standard';
  const validAlign: EbookAlign = p.align === 'justify' ? 'justify' : 'left';
  const validSpread: EbookSpreadMode = p.spread === 'auto' ? 'auto' : 'single';
  const validRuler: EbookReadingRulerMode =
    p.readingRuler === 'bar' || p.readingRuler === 'shade' || p.readingRuler === 'underline'
      ? p.readingRuler
      : 'off';
  const validTapZone: EbookTapZoneMode =
    p.tapZone === 'right-hand' || p.tapZone === 'left-hand' ? p.tapZone : 'edges';
  const fontSize = Math.min(32, Math.max(14, Math.round(Number(p.fontSize) || 18)));
  const lineHeight = Math.min(2.05, Math.max(1.5, Number(p.lineHeight) || 1.75));
  const rawLs = Number(p.letterSpacing);
  const letterSpacing = Number.isFinite(rawLs) ? Number(Math.min(0.14, Math.max(0, rawLs)).toFixed(3)) : 0;
  const rawWs = Number(p.wordSpacing);
  const wordSpacing = Number.isFinite(rawWs) ? Number(Math.min(0.2, Math.max(0, rawWs)).toFixed(3)) : 0;
  const rawPs = Number(p.paragraphSpacing);
  const paragraphSpacing = Number.isFinite(rawPs) ? Number(Math.min(2.2, Math.max(0.8, rawPs)).toFixed(2)) : 1.05;

  return {
    themeMode,
    dayTheme,
    nightTheme,
    lockedTheme,
    theme: themeMode === 'adaptive' ? 'auto' : lockedTheme,
    fontId: validFont,
    fontSize,
    lineHeight,
    letterSpacing,
    wordSpacing,
    paragraphSpacing,
    measure: validMeasure,
    align: validAlign,
    pageMode: validPageMode,
    spread: validSpread,
    readingRuler: validRuler,
    tapZone: validTapZone,
    inlinePeek: Boolean(p.inlinePeek),
    zenMode: Boolean(p.zenMode),
  };
}

export function loadEbookPrefs(): EbookPrefs {
  if (typeof window === 'undefined') return { ...DEFAULT_EBOOK_PREFS };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_EBOOK_PREFS };
    return normalizeEbookPrefs(JSON.parse(raw) as Partial<EbookPrefs>);
  } catch {
    return { ...DEFAULT_EBOOK_PREFS };
  }
}

export function saveEbookPrefs(prefs: EbookPrefs): EbookPrefs {
  const normalized = normalizeEbookPrefs(prefs);
  if (typeof window === 'undefined') return normalized;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // ignore quota errors
  }
  return normalized;
}

/**
 * Resolves the active Ebook surface spec from either a full Dual-Slot EbookPrefs object
 * or a legacy theme id ('auto' | EbookThemeId).
 */
export function resolveEbookThemeSpec(
  themeOrPrefs: EbookPrefs | EbookPrefs['theme'],
  appResolvedTheme: 'Terang' | 'Gelap'
): EbookThemeSpec {
  let id: EbookThemeId;
  if (typeof themeOrPrefs === 'string') {
    id = themeOrPrefs === 'auto' ? (appResolvedTheme === 'Gelap' ? 'dusk' : 'paper') : themeOrPrefs;
  } else if (themeOrPrefs.themeMode === 'locked') {
    id = themeOrPrefs.lockedTheme;
  } else {
    id = appResolvedTheme === 'Gelap' ? themeOrPrefs.nightTheme : themeOrPrefs.dayTheme;
  }
  return EBOOK_THEMES.find((t) => t.id === id) || EBOOK_THEMES[0];
}

export function getEbookThemeById(id: EbookThemeId): EbookThemeSpec {
  return EBOOK_THEMES.find((t) => t.id === id) || EBOOK_THEMES[0];
}

export function getEbookFontSpec(fontId: string): EbookFontSpec {
  return EBOOK_FONTS.find((f) => f.id === fontId) || EBOOK_FONTS[0];
}

/**
 * Builds the canonical scoped CSS variable map for Tier-2 Reading Canvas surfaces
 * (used identically by TranslatedWebViewer and SideBySideReaderView).
 */
export function buildEbookSurfaceStyle(
  activeThemeSpec: EbookThemeSpec,
  activeFontSpec: EbookFontSpec,
  prefs: EbookPrefs,
  isMobile: boolean
): CSSProperties {
  // Polarity-aware Dark/OLED halation mitigation (Palmen et al. CHI '23 / Piepenbrock 2014)
  const effectiveFontSize = activeThemeSpec.isDark ? Math.max(16, prefs.fontSize) : prefs.fontSize;
  const darkTrackingBonus = activeThemeSpec.isDark ? 0.012 : 0;
  const effectiveAlign = isMobile ? 'left' : prefs.align;

  return {
    colorScheme: activeThemeSpec.isDark ? 'dark' : 'light',
    '--eb-bg': activeThemeSpec.bg,
    '--eb-surface': activeThemeSpec.surface,
    '--eb-ink': activeThemeSpec.ink,
    '--eb-muted': activeThemeSpec.muted,
    '--eb-accent': activeThemeSpec.accent,
    '--eb-border': activeThemeSpec.border,
    '--eb-border-strong': activeThemeSpec.borderStrong,
    '--eb-gutter': activeThemeSpec.isDark
      ? 'rgba(255, 255, 255, 0.11)'
      : 'rgba(34, 31, 26, 0.10)',
    '--eb-font': activeFontSpec.stack,
    '--eb-size': `${effectiveFontSize}px`,
    '--eb-lh': String(prefs.lineHeight),
    '--eb-ls': `${(prefs.letterSpacing + darkTrackingBonus).toFixed(3)}em`,
    '--eb-ws': `${prefs.wordSpacing.toFixed(3)}em`,
    '--eb-para-gap': `${prefs.paragraphSpacing.toFixed(2)}em`,
    '--eb-hyphens': effectiveAlign === 'justify' ? 'auto' : 'none',
    '--eb-measure': measureToMaxWidth(prefs.measure),
    '--eb-align': effectiveAlign,
    '--bg-sidebar': activeThemeSpec.bg,
    '--surface-hover': activeThemeSpec.isDark
      ? 'rgba(255, 255, 255, 0.08)'
      : 'rgba(20, 25, 23, 0.06)',
    '--surface-pressed': activeThemeSpec.isDark
      ? 'rgba(255, 255, 255, 0.14)'
      : 'rgba(20, 25, 23, 0.10)',
    '--accent-soft': activeThemeSpec.surface,
    '--glass-surface': activeThemeSpec.bg,
    '--glass-border': activeThemeSpec.border,
    '--on-accent': activeThemeSpec.isDark ? '#141416' : '#FFFFFF',
    '--focus-ring': activeThemeSpec.accent,
  } as CSSProperties;
}

/**
 * Dynamically synchronizes the OS / PWA status-bar <meta name="theme-color"> tag
 * so mobile notch/chrome blends cleanly with either the App Shell or active Ebook Paper.
 */
export function syncDocumentThemeColor(hexColor: string): void {
  if (typeof document === 'undefined' || !hexColor) return;
  let dynamicMeta = document.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"][data-tranx-dynamic="1"]'
  );
  if (!dynamicMeta) {
    dynamicMeta = document.createElement('meta');
    dynamicMeta.name = 'theme-color';
    dynamicMeta.setAttribute('data-tranx-dynamic', '1');
    document.head.appendChild(dynamicMeta);
  }
  dynamicMeta.content = hexColor;
  // Also align any static theme-color tags so Safari/Chrome always pick the active surface
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]:not([data-tranx-dynamic])').forEach((m) => {
    m.content = hexColor;
  });
}

/**
 * Lazy-loads a Google Font CSS2 stylesheet strictly on demand (0 cost until requested).
 */
export function ensureEbookFontLoaded(fontId: string): void {
  if (typeof document === 'undefined') return;
  const spec = getEbookFontSpec(fontId);
  if (!spec.googleSpec || loadedGoogleFontIds.has(spec.id)) return;
  const linkId = `tranx-ebook-font-${spec.id}`;
  if (document.getElementById(linkId)) {
    loadedGoogleFontIds.add(spec.id);
    return;
  }
  // Lazy preconnect to fonts.gstatic.com ONLY when a web font is actually requested (0 boot cost)
  if (!document.getElementById('tranx-gstatic-preconnect')) {
    const pre = document.createElement('link');
    pre.id = 'tranx-gstatic-preconnect';
    pre.rel = 'preconnect';
    pre.href = 'https://fonts.gstatic.com';
    pre.crossOrigin = 'anonymous';
    document.head.appendChild(pre);
  }
  const link = document.createElement('link');
  link.id = linkId;
  link.rel = 'stylesheet';
  link.crossOrigin = 'anonymous';
  link.href = `https://fonts.googleapis.com/css2?family=${spec.googleSpec}&display=swap`;
  document.head.appendChild(link);
  loadedGoogleFontIds.add(spec.id);
}

export function pickSyncableEbookPrefs(prefs: EbookPrefs): Record<string, unknown> {
  return {
    themeMode: prefs.themeMode,
    dayTheme: prefs.dayTheme,
    nightTheme: prefs.nightTheme,
    lockedTheme: prefs.lockedTheme,
    theme: prefs.theme,
    fontId: prefs.fontId,
    fontSize: prefs.fontSize,
    lineHeight: prefs.lineHeight,
    letterSpacing: prefs.letterSpacing,
    wordSpacing: prefs.wordSpacing,
    paragraphSpacing: prefs.paragraphSpacing,
    measure: prefs.measure,
    align: prefs.align,
    pageMode: prefs.pageMode,
    spread: prefs.spread,
    readingRuler: prefs.readingRuler,
    tapZone: prefs.tapZone,
    inlinePeek: prefs.inlinePeek,
  };
}

export function getTapZoneBounds(tapZone: EbookTapZoneMode): {
  leftAction: 'prev' | 'next';
  leftMaxX: number;
  rightAction: 'prev' | 'next';
  rightMinX: number;
} {
  if (tapZone === 'right-hand') {
    return { leftAction: 'prev', leftMaxX: 0.22, rightAction: 'next', rightMinX: 0.56 };
  }
  if (tapZone === 'left-hand') {
    return { leftAction: 'next', leftMaxX: 0.44, rightAction: 'prev', rightMinX: 0.78 };
  }
  return { leftAction: 'prev', leftMaxX: 0.28, rightAction: 'next', rightMinX: 0.68 };
}

export function measureToMaxWidth(measure: EbookMeasure): string {
  switch (measure) {
    case 'narrow':
      return '56ch';
    case 'wide':
      return '74ch';
    default:
      return '65ch';
  }
}

/**
 * Estimates remaining reading minutes grounded in Brysbaert (2019) & IReST:
 * ID = 220 WPM, EN = 240 WPM, JA = 500 CPM, Bilingual = 1.45x dwell multiplier.
 */
export function estimateReadingMinutes(
  texts: string[],
  tgtLang: TargetLang,
  bilingual = false
): number {
  const joined = texts.join(' ').trim();
  if (!joined) return 0;
  let mins: number;
  if (tgtLang === 'ja') {
    const chars = joined.replace(/\s+/g, '').length;
    mins = chars / 500;
  } else {
    const words = joined.split(/\s+/).filter(Boolean).length;
    const wpm = tgtLang === 'en' ? 240 : 220;
    mins = words / wpm;
  }
  if (bilingual) mins *= 1.45;
  return Math.max(1, Math.round(mins));
}
