import type { TranslationTonePref } from '../types';

export const TONE_PREF_STORAGE_KEY = 'tranx_translation_tone_v1';

export function readTranslationTonePref(): TranslationTonePref {
  if (typeof window === 'undefined') return 'auto';
  try {
    const raw = window.localStorage.getItem(TONE_PREF_STORAGE_KEY);
    if (raw === 'auto' || raw === 'novel' || raw === 'casual' || raw === 'formal') {
      return raw;
    }
  } catch {
    // ignore storage read restrictions
  }
  return 'auto';
}

export function saveTranslationTonePref(tone: TranslationTonePref): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(TONE_PREF_STORAGE_KEY, tone);
  } catch {
    // ignore storage write restrictions
  }
}
