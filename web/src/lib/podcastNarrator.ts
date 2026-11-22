/**
 * Intelligent Semantic & Format-Aware Audio Narration Engine (v2) for tranX.
 * Grounded in prosodic phonology (ToBI), discourse pragmatics, and 100+ broadcast/audiobook studies:
 * - 8-Format Document Classifier + Per-Block Role Classifier (novel, script, news, academic,
 *   technical docs, lists/steps, poetry/verse, letters/quotes + headings, code, tables, blockquotes).
 * - Inline Span Decomposition: splits quoted dialogue, attenuated speech tags (with retroactive
 *   emotion propagation onto the preceding quote), compressed parentheticals, and speaker labels.
 * - Linguistically accurate ToBI intonation: Polar Yes/No (L* H-H% rising) vs WH-questions
 *   (H*...L-L% falling), paragraph-initial pitch reset, F0 declination, Pre-Boundary Final
 *   Lengthening, per-segment volumeMult, and bounded AR(1) organic micro-variance.
 * - Format-aware Text Normalization (code summaries, camelCase/snake_case, domain-only URLs,
 *   Markdown table linearization, citations, ISO dates, times, ID ordinals, compact Rp, decimals,
 *   numeric ranges, SI units, validated Roman numerals, ID/EN/JA abbreviations).
 * - Phrase-integrity breath chunking (hard anti-split after prepositions/determiners & before JA
 *   particles), Voice-Engine Adaptive Calibration (Azure/Apple/Google/Compact), Virtual Pause,
 *   GC-safe utterance pool, watchdog recovery, MediaSession bridge, and Sleep Timer fade-out.
 */

import type { TargetLang } from '../types';

export type TtsPlaybackState = 'idle' | 'playing' | 'paused';
export type TtsRate = 0.85 | 1 | 1.15 | 1.25 | 1.5;
export type PodcastStyleId = 'podcast_santai' | 'narasi_buku' | 'fokus_cepat';
export type PodcastSleepPreset = 'off' | '15' | '30' | 'chapter';
export type PodcastCastMode = 'single' | 'persona' | 'multi_voice';

export type DocumentFormatId =
  | 'fiction_novel'
  | 'script_dialogue'
  | 'news_editorial'
  | 'academic_paper'
  | 'technical_docs'
  | 'list_instructions'
  | 'poetry_verse'
  | 'letter_quote';

export type BlockRole =
  | 'heading'
  | 'code_block'
  | 'table_block'
  | 'blockquote'
  | 'list_item'
  | 'verse_line'
  | 'script_line'
  | 'letter_salutation'
  | 'letter_signoff'
  | 'scene_break'
  | 'body';

export type SpeechSegmentKind =
  | 'chapter_intro'
  | 'narration'
  | 'dialogue'
  | 'dialogue_alt'
  | 'inner_thought'
  | 'question'
  | 'polar_question'
  | 'wh_question'
  | 'exclamation'
  | 'action_burst'
  | 'reflective'
  | 'system_notice'
  | 'speech_tag'
  | 'parenthetical'
  | 'heading'
  | 'list_item'
  | 'code_summary'
  | 'table_row'
  | 'verse_line'
  | 'blockquote'
  | 'letter_salutation'
  | 'letter_signoff'
  | 'scene_break'
  | 'chapter_outro';

export interface SpeechSegment {
  id: string;
  paraIdx: number; // -1 for spoken chapter title intro
  text: string;
  kind: SpeechSegmentKind;
  rateMult: number;
  pitchDelta: number;
  volumeMult: number;
  pauseBeforeMs: number;
  pauseAfterMs: number;
  estimatedMs: number;
  blockRole: BlockRole;
  docFormat: DocumentFormatId;
  speakerName?: string;
  speakerSlot?: number;
}

export interface PodcastSegmentMeta {
  speakerName?: string;
  engineFamily: VoiceEngineFamily;
  isFallbackLocal?: boolean;
  sleepRemainingMs?: number;
}

export type VoiceQualityTier = 'veryHigh' | 'high' | 'normal' | 'low';
export type VoiceEngineFamily = 'edge_azure' | 'apple_neural' | 'google_cloud' | 'compact_local';

export interface RankedVoiceOption {
  voice: SpeechSynthesisVoice;
  uri: string;
  label: string;
  score: number;
  tier: VoiceQualityTier;
  isNeural: boolean;
  isOnline: boolean;
  engineFamily: VoiceEngineFamily;
}

export const PODCAST_RATES: readonly TtsRate[] = [0.85, 1, 1.15, 1.25, 1.5] as const;

export const DOCUMENT_FORMAT_IDS: readonly DocumentFormatId[] = [
  'fiction_novel',
  'script_dialogue',
  'news_editorial',
  'academic_paper',
  'technical_docs',
  'list_instructions',
  'poetry_verse',
  'letter_quote',
] as const;

export const DOCUMENT_FORMAT_CONFIG: Record<
  DocumentFormatId,
  {
    rateMult: number;
    pauseScale: number;
    pitchScale: number;
    paraBreakMs: number;
  }
> = {
  fiction_novel: { rateMult: 1.0, pauseScale: 1.0, pitchScale: 1.0, paraBreakMs: 620 },
  script_dialogue: { rateMult: 1.02, pauseScale: 0.9, pitchScale: 1.08, paraBreakMs: 360 },
  news_editorial: { rateMult: 1.03, pauseScale: 0.88, pitchScale: 0.72, paraBreakMs: 520 },
  academic_paper: { rateMult: 0.93, pauseScale: 1.12, pitchScale: 0.62, paraBreakMs: 680 },
  technical_docs: { rateMult: 0.92, pauseScale: 1.14, pitchScale: 0.58, paraBreakMs: 640 },
  list_instructions: { rateMult: 0.96, pauseScale: 1.08, pitchScale: 0.78, paraBreakMs: 480 },
  poetry_verse: { rateMult: 0.86, pauseScale: 1.24, pitchScale: 0.88, paraBreakMs: 780 },
  letter_quote: { rateMult: 0.92, pauseScale: 1.14, pitchScale: 0.92, paraBreakMs: 660 },
};

export const PODCAST_STYLE_CONFIG: Record<
  PodcastStyleId,
  {
    baseRate: Record<TargetLang, number>;
    pauseScale: number;
    pitchScale: number;
  }
> = {
  podcast_santai: {
    baseRate: { id: 0.89, en: 0.9, ja: 0.87 },
    pauseScale: 1.14,
    pitchScale: 1.0,
  },
  narasi_buku: {
    baseRate: { id: 0.95, en: 0.96, ja: 0.93 },
    pauseScale: 1.0,
    pitchScale: 1.0,
  },
  fokus_cepat: {
    baseRate: { id: 1.16, en: 1.18, ja: 1.14 },
    pauseScale: 0.74,
    pitchScale: 0.65,
  },
};

export function isTtsSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    typeof window.SpeechSynthesisUtterance !== 'undefined'
  );
}

export function langToBcp47(lang: TargetLang): string {
  if (lang === 'en') return 'en-US';
  if (lang === 'ja') return 'ja-JP';
  return 'id-ID';
}

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/* 1. Cross-Browser Neural Voice Ranking & Engine Calibration */

const PREFERRED_REGION: Record<TargetLang, RegExp> = {
  id: /^id[-_]id$/i,
  en: /^en[-_](us|gb|au)$/i,
  ja: /^ja[-_]jp$/i,
};

const NOVELTY_BLACKLIST =
  /\b(albert|bad news|bahh|bells|boing|bubbles|cellos|fred|good news|jester|junior|kathy|organ|ralph|superstar|trinoids|whisper|wobble|zarvox|espeak|festival|eloquence)\b/i;

const FLAGSHIP_VOICE_RULES: Record<TargetLang, Array<{ re: RegExp; bonus: number }>> = {
  id: [
    { re: /microsoft\s+gadis\s+online\s*\(natural\)/i, bonus: 145 },
    { re: /microsoft\s+ardi\s+online\s*\(natural\)/i, bonus: 140 },
    { re: /damayanti.*(premium|enhanced)/i, bonus: 122 },
    { re: /\bsiri\b/i, bonus: 116 },
    { re: /id[-_]id[-_]x[-_].*[-_]network/i, bonus: 98 },
    { re: /google\s+bahasa\s+indonesia/i, bonus: 88 },
    { re: /\bdamayanti\b/i, bonus: 74 },
  ],
  en: [
    {
      re: /microsoft\s+(ava|andrew|aria|jenny|guy|emma|brian|sonia|ryan|steffan)\s+online\s*\(natural\)/i,
      bonus: 145,
    },
    { re: /microsoft\s+.*online\s*\(natural\)/i, bonus: 132 },
    { re: /\b(zoe|ava|allison|samantha|daniel|karen|serena|moira|tessa)\b.*premium/i, bonus: 126 },
    { re: /\bsiri\b/i, bonus: 120 },
    {
      re: /\b(zoe|ava|allison|samantha|daniel|karen|serena|moira|tessa|evan|nathan)\b.*enhanced/i,
      bonus: 114,
    },
    { re: /en[-_](us|gb)[-_]x[-_].*[-_]network/i, bonus: 98 },
    { re: /google\s+(us|uk)\s+english/i, bonus: 86 },
    { re: /\b(samantha|daniel|karen|moira|tessa|alex)\b/i, bonus: 76 },
  ],
  ja: [
    { re: /microsoft\s+nanami\s+online\s*\(natural\)/i, bonus: 145 },
    { re: /microsoft\s+keita\s+online\s*\(natural\)/i, bonus: 140 },
    { re: /\b(kyoko|otoya|hattori|o-ren)\b.*premium/i, bonus: 126 },
    { re: /\bsiri\b/i, bonus: 120 },
    { re: /\b(kyoko|otoya|hattori|o-ren)\b.*enhanced/i, bonus: 114 },
    { re: /ja[-_]jp[-_]x[-_].*[-_]network/i, bonus: 98 },
    { re: /google\s+日本語/i, bonus: 88 },
    { re: /\b(kyoko|otoya)\b/i, bonus: 76 },
  ],
};

export function detectVoiceEngineProfile(voice: SpeechSynthesisVoice | null): {
  family: VoiceEngineFamily;
  pitchGain: number;
  rateScale: number;
  minPitch: number;
  maxPitch: number;
} {
  if (!voice) {
    return { family: 'compact_local', pitchGain: 0.85, rateScale: 1.0, minPitch: 0.93, maxPitch: 1.07 };
  }
  const idStr = `${voice.name} ${voice.voiceURI}`;
  if (/online\s*\(natural\)/i.test(idStr)) {
    return { family: 'edge_azure', pitchGain: 0.88, rateScale: 1.0, minPitch: 0.94, maxPitch: 1.06 };
  }
  if (/com\.apple\.voice\.(premium|enhanced)|\bsiri\b|\((premium|enhanced)\)/i.test(idStr)) {
    return { family: 'apple_neural', pitchGain: 0.94, rateScale: 0.99, minPitch: 0.93, maxPitch: 1.07 };
  }
  if (/^google\s|-network$/i.test(idStr)) {
    return { family: 'google_cloud', pitchGain: 1.0, rateScale: 1.0, minPitch: 0.92, maxPitch: 1.08 };
  }
  return { family: 'compact_local', pitchGain: 0.72, rateScale: 0.97, minPitch: 0.95, maxPitch: 1.05 };
}

function cleanVoiceDisplayName(name: string): string {
  return name
    .replace(/^Microsoft\s+/i, '')
    .replace(/\s+Online\s*\(Natural\)\s*-\s*.+$/i, ' (Alami)')
    .replace(/\s*\(Enhanced\)/i, ' (Halus)')
    .replace(/\s*\(Premium\)/i, ' (Premium)')
    .trim();
}

export function rankVoicesForLang(
  voices: SpeechSynthesisVoice[],
  lang: TargetLang,
  isOnline = typeof navigator === 'undefined' ? true : navigator.onLine
): RankedVoiceOption[] {
  const out: RankedVoiceOption[] = [];
  for (const voice of voices) {
    const normLang = (voice.lang || '').replace('_', '-').toLowerCase();
    if (!normLang.startsWith(lang)) continue;

    const idStr = `${voice.name} ${voice.voiceURI}`;
    let score = PREFERRED_REGION[lang].test(normLang) ? 20 : 8;
    if (NOVELTY_BLACKLIST.test(idStr)) score -= 220;

    let matchedFlagship = false;
    for (const rule of FLAGSHIP_VOICE_RULES[lang]) {
      if (rule.re.test(idStr)) {
        score += rule.bonus;
        matchedFlagship = true;
        break;
      }
    }

    const isEdgeNatural = /online\s*\(natural\)/i.test(idStr);
    const isApplePremium = /com\.apple\.voice\.premium|\(premium\)/i.test(idStr);
    const isAppleEnhanced = /com\.apple\.voice\.enhanced|\(enhanced\)/i.test(idStr);
    const isAppleCompact = /com\.apple\.voice\.compact|compact/i.test(idStr);
    const isAndroidNetwork = /-network$/i.test(voice.voiceURI || '');
    const isGoogleCloud = /^google\s/i.test(voice.name || '');

    if (!matchedFlagship) {
      if (isEdgeNatural) score += 130;
      else if (isApplePremium) score += 118;
      else if (isAppleEnhanced) score += 108;
      else if (/natural|neural|wavenet|studio/i.test(idStr)) score += 96;
      else if (isAndroidNetwork) score += 90;
      else if (isGoogleCloud) score += 80;
      else if (isAppleCompact) score += 46;
      else score += 52;
    }

    const requiresNetwork =
      !voice.localService || isEdgeNatural || isGoogleCloud || isAndroidNetwork;
    if (!isOnline && requiresNetwork) {
      score -= 170;
    }
    if (voice.default) score += 4;

    const tier: VoiceQualityTier =
      score >= 130 ? 'veryHigh' : score >= 95 ? 'high' : score >= 60 ? 'normal' : 'low';
    const isNeural =
      isEdgeNatural ||
      isApplePremium ||
      isAppleEnhanced ||
      isAndroidNetwork ||
      /natural|neural|siri/i.test(idStr);
    const engineFamily = detectVoiceEngineProfile(voice).family;

    out.push({
      voice,
      uri: voice.voiceURI || voice.name,
      label: cleanVoiceDisplayName(voice.name),
      score,
      tier,
      isNeural,
      isOnline: requiresNetwork,
      engineFamily,
    });
  }

  return out
    .filter((v) => v.score > -50)
    .sort((a, b) => b.score - a.score || a.label.localeCompare(b.label));
}

export function loadSpeechVoices(timeoutMs = 1200): Promise<SpeechSynthesisVoice[]> {
  if (!isTtsSupported()) return Promise.resolve([]);
  const synth = window.speechSynthesis;
  const initial = synth.getVoices();
  if (initial.length > 0) return Promise.resolve(initial);

  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      synth.removeEventListener?.('voiceschanged', onChanged);
      window.clearInterval(pollId);
      window.clearTimeout(timerId);
      resolve(synth.getVoices());
    };
    const onChanged = () => {
      if (synth.getVoices().length > 0) finish();
    };
    synth.addEventListener?.('voiceschanged', onChanged);
    const pollId = window.setInterval(() => {
      if (synth.getVoices().length > 0) finish();
    }, 150);
    const timerId = window.setTimeout(finish, timeoutMs);
  });
}

export function unlockSpeechSynthesisOnGesture(): void {
  if (!isTtsSupported()) return;
  try {
    // Safe empty priming utterance (rate=1, volume=0) avoiding Android/Safari rate=10 corruption (#169, #170)
    const prime = new window.SpeechSynthesisUtterance('');
    prime.volume = 0;
    prime.rate = 1;
    window.speechSynthesis.speak(prime);
  } catch {
    // ignore restricted environments
  }
}

/* 2. Document Format & Per-Block Structural Classifier */

const SCENE_BREAK_RE =
  /^\s*([*\-=_~#\u2022\u00B7\u25C6\u25C7\u25A0\u25A1\u2605\u2606\u2726\u2727]\s*){3,}\s*$/;
const CODE_BLOCK_RE = /^\s*```([A-Za-z0-9_+#.-]*)\s*\n?([\s\S]*?)```\s*$/;
const TABLE_LINE_RE = /^\s*\|.+\|\s*$/;
const TABLE_SEP_RE = /^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*$/;
const HEADING_MD_RE = /^#{1,6}\s+/;
const LIST_ITEM_RE = /^\s*(?:[-*\u2022+]|\d+[.)]|[a-zA-Z][.)]|(?:Langkah|Step)\s+\d+[:.)]?)\s+/i;
const SCRIPT_LINE_RE = /^([A-Z\u3040-\u30ff\u4e00-\u9fff][A-Za-z0-9_\s\u3040-\u30ff\u4e00-\u9fff-]{0,22})[:\uFF1A]\s+(.+)$/;
const LETTER_SALUTATION_RE =
  /^(?:Kepada\s+Yth\.?|Yth\.?|Dengan\s+hormat|Dear\s+[A-Z]|To\s+whom\s+it\s+may\s+concern|拝啓|謹啓)/;
const LETTER_SIGNOFF_RE =
  /^(?:Hormat\s+(?:kami|saya)|Salam\s+hangat|Sincerely|Best\s+regards|Warm\s+regards|Yours\s+truly|敬具|草々)/i;
const NEWS_DATELINE_RE = /^[A-Z]{3,16}(?:,\s*[A-Z]{2,12})?\s*[-,]\s/m;
const NEWS_ATTRIBUTION_RE =
  /\b(?:dilaporkan|menurut\s+sumber|juru\s+bicara|press\s+release|spokesperson|according\s+to\s+officials|Reuters|AFP)\b|報道によると/i;
const ACADEMIC_DOC_RE =
  /(?:\b(?:Abstract|Methodology|Hypothesis|Conclusion|References|et\s+al\.|p\s*<\s*0\.\d+|Abstrak|Metodologi|Hipotesis|Kesimpulan|Daftar\s+Pustaka)\b|\([A-Z][a-z]+(?:\s+et\s+al\.)?,\s*\d{4}\)|要旨|参考文献)/;
const TECH_DOC_RE =
  /(?:```|`[^`\n]{2,60}`|\b(?:HTTP|JSON|API|SDK|CLI|REST|GraphQL|npm|git|docker|kubectl|endpoint|payload|boolean|async|await)\b)/;

export function classifyDocumentFormat(paragraphs: string[], lang: TargetLang): DocumentFormatId {
  const sample = paragraphs.map((p) => (p || '').trim()).filter(Boolean).slice(0, 40);
  if (sample.length === 0) return 'fiction_novel';
  const joined = sample.join('\n');
  const total = sample.length;

  const codeCount = sample.filter((p) => CODE_BLOCK_RE.test(p) || p.includes('```')).length;
  const techHits = (joined.match(new RegExp(TECH_DOC_RE.source, 'g')) || []).length;
  if (codeCount >= 1 || techHits >= 4) return 'technical_docs';

  const academicHits = (joined.match(new RegExp(ACADEMIC_DOC_RE.source, 'g')) || []).length;
  if (academicHits >= 2) return 'academic_paper';

  const scriptCount = sample.filter((p) => SCRIPT_LINE_RE.test(p) && !/^https?:/i.test(p)).length;
  if (scriptCount >= 2 && scriptCount / total >= 0.35) return 'script_dialogue';

  const listCount = sample.filter((p) => LIST_ITEM_RE.test(p)).length;
  if (listCount >= 3 && listCount / total >= 0.45) return 'list_instructions';

  const quoteLines = sample.filter((p) => /^[""\u201C\u300C\u300E]/.test(p)).length;
  const hasSalutation = sample.slice(0, 3).some((p) => p.length <= 72 && LETTER_SALUTATION_RE.test(p));
  const hasSignoff = sample.slice(-4).some((p) => p.length <= 60 && LETTER_SIGNOFF_RE.test(p));
  const blockquoteCount = sample.filter((p) => p.startsWith('>')).length;
  if (hasSalutation || (hasSignoff && quoteLines <= 2) || (blockquoteCount >= 2 && blockquoteCount / total >= 0.4)) {
    return 'letter_quote';
  }

  const newsDatelineHits = sample.filter((p) => NEWS_DATELINE_RE.test(p)).length;
  const newsAttrHits = (joined.match(new RegExp(NEWS_ATTRIBUTION_RE.source, 'gi')) || []).length;
  if (newsDatelineHits + newsAttrHits >= 2 && quoteLines / total < 0.25) return 'news_editorial';

  // Poetry/verse detector: multiple short lines, low terminal sentence punctuation ratio, no narrative quotes
  const lines = joined.split('\n').map((l) => l.trim()).filter(Boolean);
  if (lines.length >= 4 && quoteLines === 0) {
    const avgLen = lines.reduce((a, b) => a + b.length, 0) / lines.length;
    const shortRatio = lines.filter((l) => l.length <= (lang === 'ja' ? 24 : 52)).length / lines.length;
    const terminalRatio =
      lines.filter((l) => /[.!?\u3002\uFF01\uFF1F]$/.test(l)).length / lines.length;
    if (avgLen <= (lang === 'ja' ? 22 : 46) && shortRatio >= 0.78 && terminalRatio <= 0.55) {
      return 'poetry_verse';
    }
  }

  return 'fiction_novel';
}

export function classifyBlockRole(raw: string, pIdx: number, docFormat: DocumentFormatId): BlockRole {
  const t = raw.trim();
  if (!t) return 'body';
  if (SCENE_BREAK_RE.test(t)) return 'scene_break';
  if (CODE_BLOCK_RE.test(t) || t.startsWith('```')) return 'code_block';
  if (t.split('\n').filter((l) => TABLE_LINE_RE.test(l)).length >= 2) return 'table_block';
  if (
    HEADING_MD_RE.test(t) ||
    (pIdx === 0 &&
      t.length <= 85 &&
      /^(bab|chapter|prolog|epilog|bagian|jilid|第.{1,6}[章話])/i.test(t))
  ) {
    return 'heading';
  }
  if (t.startsWith('>')) return 'blockquote';
  if (LIST_ITEM_RE.test(t)) return 'list_item';
  if (LETTER_SALUTATION_RE.test(t)) return 'letter_salutation';
  if (LETTER_SIGNOFF_RE.test(t)) return 'letter_signoff';
  if (docFormat === 'script_dialogue' && SCRIPT_LINE_RE.test(t) && !/^https?:/i.test(t)) {
    return 'script_line';
  }
  if (docFormat === 'poetry_verse') return 'verse_line';
  return 'body';
}

/* 3. Format-Aware Non-Destructive Speech Text Normalizer (ID / EN / JA) */

function romanToArabicStrict(roman: string): number {
  const upper = roman.toUpperCase();
  if (!/^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$/.test(upper)) return 0;
  const map: Record<string, number> = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };
  let total = 0;
  for (let i = 0; i < upper.length; i++) {
    const curr = map[upper[i]] || 0;
    const next = map[upper[i + 1]] || 0;
    total += curr < next ? -curr : curr;
  }
  return total;
}

const ID_MONTHS = [
  '',
  'Januari',
  'Februari',
  'Maret',
  'April',
  'Mei',
  'Juni',
  'Juli',
  'Agustus',
  'September',
  'Oktober',
  'November',
  'Desember',
];
const EN_MONTHS = [
  '',
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

const ID_ORDINALS: Record<number, string> = {
  1: 'pertama',
  2: 'kedua',
  3: 'ketiga',
  4: 'keempat',
  5: 'kelima',
  6: 'keenam',
  7: 'ketujuh',
  8: 'kedelapan',
  9: 'kesembilan',
  10: 'kesepuluh',
};

function expandIdentifierForSpeech(raw: string): string {
  return raw
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_/\\.-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function summarizeCodeBlockForSpeech(raw: string, lang: TargetLang): string {
  const m = raw.trim().match(/^```([A-Za-z0-9_+#.-]*)\s*\n?([\s\S]*?)```$/);
  const codeLang = (m?.[1] || '').trim();
  const body = (m?.[2] || raw.replace(/```/g, '')).trim();
  const lineCount = Math.max(1, body ? body.split('\n').length : 1);
  const langLabel = codeLang
    ? codeLang
      .replace(/^ts$/i, 'TypeScript')
      .replace(/^js$/i, 'JavaScript')
      .replace(/^py$/i, 'Python')
      .replace(/^sh$/i, 'Shell')
    : '';
  if (lang === 'en') {
    return langLabel
      ? `${langLabel} code snippet, ${lineCount} ${lineCount === 1 ? 'line' : 'lines'}.`
      : `Code snippet, ${lineCount} ${lineCount === 1 ? 'line' : 'lines'}.`;
  }
  if (lang === 'ja') {
    return langLabel ? `${langLabel}のコード、${lineCount}行。` : `コードブロック、${lineCount}行。`;
  }
  return langLabel
    ? `Cuplikan kode ${langLabel}, ${lineCount} baris.`
    : `Cuplikan kode, ${lineCount} baris.`;
}

export function linearizeMarkdownTableForSpeech(raw: string, lang: TargetLang): string[] {
  const lines = raw
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => TABLE_LINE_RE.test(l) && !TABLE_SEP_RE.test(l));
  if (lines.length === 0) return [];
  const parseCells = (line: string) =>
    line
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((c) => preprocessForSpeech(c.trim(), lang));

  const headers = parseCells(lines[0]);
  if (lines.length === 1) return [headers.filter(Boolean).join(', ')];

  const rows: string[] = [];
  for (let r = 1; r < Math.min(lines.length, 16); r++) {
    const cells = parseCells(lines[r]);
    if (!cells.some(Boolean)) continue;
    const pairs: string[] = [];
    cells.forEach((cell, idx) => {
      if (!cell) return;
      pairs.push(headers[idx] ? `${headers[idx]}, ${cell}` : cell);
    });
    if (pairs.length === 0) continue;
    const prefix = lang === 'en' ? `Row ${r}: ` : lang === 'ja' ? `${r}行目、` : `Baris ${r}: `;
    rows.push(`${prefix}${pairs.join('; ')}.`);
  }
  return rows;
}

export function preprocessForSpeech(raw: string, lang: TargetLang): string {
  if (!raw) return '';
  let s = raw.normalize('NFKC');

  // Summarize embedded fenced code blocks instead of silently vanishing them
  s = s.replace(/```[A-Za-z0-9_+#.-]*\s*\n?[\s\S]*?```/g, (m) => ` ${summarizeCodeBlockForSpeech(m, lang)} `);

  // Strip ONLY real HTML tags (preserving math inequalities like "x < 5 and y > 10"!) & invisible chars
  s = s.replace(/<\/?[A-Za-z][A-Za-z0-9-]*(?:\s[^>]*)?>/g, ' ').replace(/[\u200B-\u200D\uFEFF]/g, '');

  // Japanese literary furigana/ruby -> keep kana reading
  if (lang === 'ja') {
    s = s.replace(/[|\uFF5C]([^\u300A\n]+)\u300A([^\u300B\n]+)\u300B/g, '$2');
    s = s.replace(/([\u4E00-\u9FFF\u3005]+)\u300A([^\u300B\n]+)\u300B/g, '$2');
    s = s.replace(/\uFF08[\u6CE8\u203B][^\uFF09]{0,20}\uFF09/g, '');
  }

  // Expand inline code identifiers cleanly (camelCase & snake_case)
  s = s.replace(/`([^`\n]+)`/g, (_m, inner: string) => expandIdentifierForSpeech(inner));

  // Markdown images & links + URLs BEFORE italic underscore stripping so URL underscores stay intact
  s = s
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, (_m, alt: string) => (alt.trim() ? alt.trim() : ''))
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/https?:\/\/([a-zA-Z0-9.-]+)(?:\/[^\s),;]*)?/gi, (full, host: string) => {
      const trailMatch = full.match(/[.,;:!?]+$/);
      const trail = trailMatch ? trailMatch[0] : '';
      const cleanHost = host.replace(/^www\./i, '');
      if (lang === 'en') return `link ${cleanHost}${trail}`;
      if (lang === 'ja') return `${cleanHost}のリンク${trail}`;
      return `tautan ${cleanHost}${trail}`;
    })
    .replace(/(\*\*|__|~~)(.*?)\1/g, '$2')
    .replace(/(^|\s)([*_])([^\s*_][^*_\n]*?)\2(?=\s|$|[.,!?;:])/g, '$1$3')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^>\s*/gm, '');

  // Academic & numeric citations
  s = s
    .replace(/\(\s*[A-Z][a-z]+(?:\s+(?:et\s+al\.|&\s*[A-Z][a-z]+))?,\s*\d{4}[a-z]?(?:;\s*[^)]{1,60})?\)/g, '')
    .replace(/\[\^?[\d,\s-]{1,12}\]/g, '')
    .replace(/[*†‡※]{2,}/g, ' ');

  // Honorific hyphen smoothing in ID & EN light novel prose
  if (lang !== 'ja') {
    s = s.replace(
      /\b([A-Za-z'][A-Za-z']*)-(san|sama|kun|chan|sensei|senpai|kouhai|dono|tan|shi|tachi)\b/gi,
      '$1 $2'
    );
  }

  // Convert literary dashes (using Unicode escapes so zero raw U+2014 enters source) into breath commas
  s = s
    .replace(/[\u2015\u2500\u2501\u2014\u2013]{2,}/g, ', ')
    .replace(/\s*[\u2014\u2013]\s*/g, ', ')
    .replace(/--+/g, ', ')
    .replace(/\.{3,}|\u2026+|\u22EF+/g, lang === 'ja' ? '\u3001' : '... ')
    .replace(/([!?\uFF01\uFF1F]){2,}/g, (m) => (m.includes('?') || m.includes('\uFF1F') ? '?' : '!'));

  // Kestrel precedence (Ebden & Sproat 2015): SemVer -> Phones -> Scientific/Fractions -> Dates -> Ranges -> Units -> Abbrevs
  // 1. SemVer & Version tokens (v2.5.0 -> versi 2 titik 5 titik 0)
  s = s.replace(/\bv(\d+)\.(\d+)(?:\.(\d+))?\b/gi, (_m, maj: string, min: string, pat: string | undefined) => {
    if (lang === 'en') {
      return pat !== undefined ? `version ${maj} point ${min} point ${pat}` : `version ${maj} point ${min}`;
    }
    if (lang === 'ja') {
      return pat !== undefined ? `バージョン ${maj} てん ${min} てん ${pat}` : `バージョン ${maj} てん ${min}`;
    }
    return pat !== undefined ? `versi ${maj} titik ${min} titik ${pat}` : `versi ${maj} titik ${min}`;
  });

  // 2. Telephone numbers & hyphenated phone codes BEFORE range regex so "021-555-0199" & "+62 812-3456-7890" never become ranges!
  s = s.replace(
    /(?:\+\d{1,3}[\s-]?\d{2,4}-|\(\d{2,4}\)\s*|\b0\d{1,3}-)\d{3,4}-\d{3,5}\b/g,
    (rawPhone) => {
      const cleaned = rawPhone.replace(/^\+/, lang === 'en' ? 'plus ' : lang === 'ja' ? 'プラス ' : 'plus ');
      return cleaned
        .replace(/[()]/g, ' ')
        .replace(/-/g, ', ')
        .replace(/\d/g, (d) => `${d} `)
        .replace(/\s+/g, ' ')
        .trim();
    }
  );

  // 3. Scientific notation, powers & common fractions (Raman 1994 / Sorge 2014)
  s = s
    .replace(/(\d+(?:[.,]\d+)?)\s*[x×]\s*10\^(-?\d+)/gi, (_m, mant: string, exp: string) => {
      if (lang === 'en') return `${mant.replace(',', '.')} times ten to the power of ${exp}`;
      if (lang === 'ja') return `${mant} かける 10 の ${exp} 乗`;
      return `${mant.replace('.', ' koma ')} kali 10 pangkat ${exp}`;
    })
    .replace(/(\d+(?:[.,]\d+)?)e([+-]?\d+)\b/gi, (_m, mant: string, exp: string) => {
      if (lang === 'en') return `${mant.replace(',', '.')} times ten to the power of ${exp}`;
      if (lang === 'ja') return `${mant} かける 10 の ${exp} 乗`;
      return `${mant.replace('.', ' koma ')} kali 10 pangkat ${exp}`;
    })
    .replace(/(\d+)\s*m\u00B2\b/gi, lang === 'en' ? '$1 square meters' : lang === 'ja' ? '$1平方メートル' : '$1 meter persegi')
    .replace(/(\d+)\s*km\u00B2\b/gi, lang === 'en' ? '$1 square kilometers' : lang === 'ja' ? '$1平方キロメートル' : '$1 kilometer persegi')
    .replace(/(\d+)\s*m\u00B3\b/gi, lang === 'en' ? '$1 cubic meters' : lang === 'ja' ? '$1立方メートル' : '$1 meter kubik')
    .replace(/\u00BD/g, lang === 'en' ? 'one half' : lang === 'ja' ? '2分の1' : 'setengah')
    .replace(/\u00BC/g, lang === 'en' ? 'one quarter' : lang === 'ja' ? '4分の1' : 'seperempat')
    .replace(/\u00BE/g, lang === 'en' ? 'three quarters' : lang === 'ja' ? '4分の3' : 'tiga perempat')
    .replace(/(?<![\d/.])\b([1-9])\/([2-9]|10|12)\b(?![\d/.])/g, (_m, num: string, den: string) => {
      if (lang === 'ja') return `${den}分の${num}`;
      if (lang === 'en') {
        if (num === '1' && den === '2') return 'one half';
        if (num === '1' && den === '4') return 'one quarter';
        if (num === '3' && den === '4') return 'three quarters';
        return `${num} over ${den}`;
      }
      if (num === '1' && den === '2') return 'setengah';
      if (num === '1' && den === '4') return 'seperempat';
      return `${num} per ${den}`;
    });

  // ISO & DMY dates: 2026-11-22 / 22-11-2026 -> spoken calendar date (BEFORE numeric range!)
  s = s.replace(/\b(19\d{2}|20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b/g, (_m, y, mo, d) => {
    const mIdx = Number(mo);
    const day = Number(d);
    if (lang === 'en') return `${EN_MONTHS[mIdx]} ${day}, ${y}`;
    if (lang === 'ja') return `${y}年${mIdx}月${day}日`;
    return `${day} ${ID_MONTHS[mIdx]} ${y}`;
  });
  s = s.replace(/\b(0?[1-9]|[12]\d|3[01])-(0?[1-9]|1[0-2])-(19\d{2}|20\d{2})\b/g, (_m, d, mo, y) => {
    const mIdx = Number(mo);
    const day = Number(d);
    if (lang === 'en') return `${EN_MONTHS[mIdx]} ${day}, ${y}`;
    if (lang === 'ja') return `${y}年${mIdx}月${day}日`;
    return `${day} ${ID_MONTHS[mIdx]} ${y}`;
  });

  // 24h Clock times (skip HH:MM:SS timestamps and ratios!)
  if (lang === 'id') {
    s = s.replace(/(?<!:)\b([01]?\d|2[0-3]):([0-5]\d)\b(?!:\d)/g, (_m, hh, mm) =>
      mm === '00' ? `pukul ${Number(hh)}` : `pukul ${Number(hh)} lewat ${Number(mm)}`
    );
  }

  // Contextual Roman numerals (chapter/act/event/century/regnal) with strict validator (#196)
  s = s.replace(
    /\b(Bab|Bagian|Jilid|Pasal|Abad|Perang\s+Dunia|Fase|Tahap|Chapter|Part|Act|Book|Volume|Vol\.?|World\s+War|Phase|Century|Henry|Louis|Charles|Elizabeth|Edward|George|Philip|Richard)\s+([IVXLCDM]{1,7})\b/gi,
    (_m, prefix: string, rom: string) => {
      const n = romanToArabicStrict(rom);
      if (n <= 0 || n > 300) return `${prefix} ${rom}`;
      if (lang === 'en' && /^(?:Henry|Louis|Charles|Elizabeth|Edward|George|Philip|Richard)$/i.test(prefix)) {
        const ordMap: Record<number, string> = { 1: 'the first', 2: 'the second', 3: 'the third', 4: 'the fourth', 5: 'the fifth', 6: 'the sixth', 7: 'the seventh', 8: 'the eighth' };
        return `${prefix} ${ordMap[n] || n}`;
      }
      return `${prefix} ${n}`;
    }
  );

  // Currencies, ordinals, decimals, numeric ranges, SI units & abbreviations
  if (lang === 'id') {
    s = s
      .replace(/\bRp\.?\s*(\d+(?:[.,]\d+)?)\s*(?:rb|ribu)\b/gi, (_m, n: string) => `${n.replace(/[.,]/, ' koma ')} ribu rupiah`)
      .replace(/\bRp\.?\s*(\d+(?:[.,]\d+)?)\s*(?:jt|juta)\b/gi, (_m, n: string) => `${n.replace(/[.,]/, ' koma ')} juta rupiah`)
      .replace(/\bRp\.?\s*(\d+(?:[.,]\d+)?)\s*(?:M|miliar)\b/g, (_m, n: string) => `${n.replace(/[.,]/, ' koma ')} miliar rupiah`)
      .replace(/\bRp\.?\s*(\d+(?:\.\d{3})*)(?:,(\d+))?(?!(?:[.,]\d|\d))/gi, (_m, intPart: string, decPart: string | undefined) => {
        const cleanInt = intPart.replace(/\./g, '');
        return decPart ? `${cleanInt} koma ${decPart} rupiah` : `${cleanInt} rupiah`;
      })
      .replace(/\u00A5\s*(\d+(?:,\d{3})*)(?:\.(\d+))?/g, (_m, i: string, d: string | undefined) =>
        d ? `${i.replace(/,/g, '')} koma ${d} yen` : `${i.replace(/,/g, '')} yen`
      )
      .replace(/\$\s*(\d+(?:,\d{3})*)(?:\.(\d+))?/g, (_m, i: string, d: string | undefined) =>
        d ? `${i.replace(/,/g, '')} koma ${d} dolar` : `${i.replace(/,/g, '')} dolar`
      )
      .replace(/\u20AC\s*(\d+(?:[.,]\d{3})*)(?:[.,](\d{1,2}))?/g, (_m, i: string, d: string | undefined) =>
        d ? `${i.replace(/[.,]/g, '')} koma ${d} euro` : `${i.replace(/[.,]/g, '')} euro`
      )
      .replace(/\bke-(\d{1,3})\b/gi, (_m, d: string) => ID_ORDINALS[Number(d)] || `ke ${d}`)
      .replace(/(\d+)-(\d+)/g, '$1 sampai $2')
      .replace(/(\d+),(?!\d{3}(?:\D|$))(\d+)/g, '$1 koma $2')
      .replace(/(\d+)\s*%/g, '$1 persen')
      .replace(/(\d+)\s*°C\b/g, '$1 derajat Celsius')
      .replace(/(\d+)\s*°F\b/g, '$1 derajat Fahrenheit')
      .replace(/(\d+)\s*km\b/gi, '$1 kilometer')
      .replace(/(\d+)\s*cm\b/gi, '$1 sentimeter')
      .replace(/(\d+)\s*mm\b/gi, '$1 milimeter')
      .replace(/(\d+)\s*kg\b/gi, '$1 kilogram')
      .replace(/(\d+)\s*mg\b/gi, '$1 miligram')
      .replace(/(\d+)\s*mL\b/gi, '$1 mililiter')
      .replace(/(\d+)\s*ms\b/g, '$1 milidetik')
      .replace(/(\d+)\s*GB\b/g, '$1 gigabita')
      .replace(/(\d+)\s*MB\b/g, '$1 megabita')
      .replace(/\bYth\.\s*/gi, 'Yang terhormat ')
      .replace(/\ba\.n\.\s*/gi, 'atas nama ')
      .replace(/\bu\.p\.\s*/gi, 'untuk perhatian ')
      .replace(/\bdr\.\s*/g, 'dokter ')
      .replace(/\bDr\.\s*/g, 'Doktor ')
      .replace(/\bProf\.\s*/gi, 'Profesor ')
      .replace(/\bTn\.\s*/g, 'Tuan ')
      .replace(/\bNy\.\s*/g, 'Nyonya ')
      .replace(/\bNn\.\s*/g, 'Nona ')
      .replace(/\bSdr\.\s*/g, 'Saudara ')
      .replace(/\bJl\.\s*/g, 'Jalan ')
      .replace(/\bKec\.\s*/g, 'Kecamatan ')
      .replace(/\bdgn\.\s*/gi, 'dengan ')
      .replace(/\byg\.\s*/gi, 'yang ')
      .replace(/\butk\.\s*/gi, 'untuk ')
      .replace(/\bWIB\b/g, 'waktu Indonesia barat')
      .replace(/\bWITA\b/g, 'waktu Indonesia tengah')
      .replace(/\bWIT\b/g, 'waktu Indonesia timur')
      .replace(/\bdll\./gi, 'dan lain-lain')
      .replace(/\bdsb\./gi, 'dan sebagainya')
      .replace(/\bdst\./gi, 'dan seterusnya')
      .replace(/\bdkk\./gi, 'dan kawan-kawan')
      .replace(/\b(?:hlm|hal)\.\s*(\d+)/gi, 'halaman $1')
      .replace(/\btgl\.\s*/gi, 'tanggal ')
      .replace(/\bNo\.\s*(\d+)/gi, 'nomor $1')
      .replace(/\bs\/d\b/gi, 'sampai dengan');
  } else if (lang === 'en') {
    s = s
      .replace(/\u00A5\s*(\d+(?:,\d{3})*)(?:\.(\d+))?/g, (_m, i: string, d: string | undefined) =>
        d ? `${i.replace(/,/g, '')} point ${d} yen` : `${i.replace(/,/g, '')} yen`
      )
      .replace(/\$\s*(\d+(?:,\d{3})*)(?:\.(\d{1,2}))?/g, (_m, i: string, c: string | undefined) => {
        const cleanI = i.replace(/,/g, '');
        if (!c) return `${cleanI} dollars`;
        const cents = Number(c.padEnd(2, '0'));
        return cents > 0 ? `${cleanI} dollars and ${cents} cents` : `${cleanI} dollars`;
      })
      .replace(/\u20AC\s*(\d+(?:,\d{3})*)(?:\.(\d{1,2}))?/g, (_m, i: string, c: string | undefined) =>
        c ? `${i.replace(/,/g, '')} point ${c} euros` : `${i.replace(/,/g, '')} euros`
      )
      .replace(/(\d+)-(\d+)/g, '$1 to $2')
      .replace(/(\d+)\s*%/g, '$1 percent')
      .replace(/(\d+)\s*°C\b/g, '$1 degrees Celsius')
      .replace(/(\d+)\s*°F\b/g, '$1 degrees Fahrenheit')
      .replace(/(\d+)\s*km\b/gi, '$1 kilometers')
      .replace(/(\d+)\s*kg\b/gi, '$1 kilograms')
      .replace(/(\d+)\s*ms\b/g, '$1 milliseconds')
      .replace(/\bSt\.\s+(?=[A-Z][a-z]+)/g, 'Saint ')
      .replace(/\b([A-Z][a-z]+)\s+St\.(?=\s|$|[.,!?;:])/g, '$1 Street')
      .replace(/\bPh\.?D\./g, 'P H D')
      .replace(/\bInc\./g, 'Incorporated')
      .replace(/\ba\.m\./gi, 'A M')
      .replace(/\bp\.m\./gi, 'P M')
      .replace(/\bMr\.\s*/g, 'Mister ')
      .replace(/\bMrs\.\s*/g, 'Missus ')
      .replace(/\bMs\.\s*/g, 'Miz ')
      .replace(/\bDr\.\s*/g, 'Doctor ')
      .replace(/\bProf\.\s*/g, 'Professor ')
      .replace(/\bapprox\.\s*/gi, 'approximately ')
      .replace(/\bfig\.\s*(\d+)/gi, 'figure $1')
      .replace(/\bdept\.\s*/gi, 'department ')
      .replace(/\be\.g\./gi, 'for example')
      .replace(/\bi\.e\./gi, 'that is')
      .replace(/\betc\./gi, 'et cetera')
      .replace(/\bvs\.\s*/gi, 'versus ');
  } else if (lang === 'ja') {
    // Vance (2008) Japanese morphophonemic counter disambiguation & semiotic normalization (#191, #193)
    const jaCounterMap: Array<[RegExp, string]> = [
      [/\b1人/g, 'ひとり'],
      [/\b2人/g, 'ふたり'],
      [/\b1本/g, 'いっぽん'],
      [/\b3本/g, 'さんぼん'],
      [/\b6本/g, 'ろっぽん'],
      [/\b1匹/g, 'いっぴき'],
      [/\b3匹/g, 'さんびき'],
      [/\b4日/g, 'よっか'],
      [/\b8日/g, 'ようか'],
      [/\b20日/g, 'はつか'],
      [/\b20歳/g, 'はたち'],
    ];
    for (const [pat, kana] of jaCounterMap) {
      s = s.replace(pat, kana);
    }
    s = s
      .replace(/(\d+)-(\d+)/g, '$1から$2')
      .replace(/(\d+)\s*%/g, '$1パーセント')
      .replace(/(\d+)\s*°C/g, '$1度')
      .replace(/(\d+)\s*km\b/gi, '$1キロメートル')
      .replace(/(\d+)\s*kg\b/gi, '$1キログラム')
      .replace(/〒/g, '郵便番号 ')
      .replace(/㈱/g, '株式会社')
      .replace(/№\s*(\d+)/g, 'ナンバー$1');
  }

  // Strip literal corner/lenticular brackets so TTS never speaks "left lenticular bracket"
  s = s.replace(/[\u3010\u3011\u300A\u300B\u300C\u300D\u300E\u300F]/g, ' ');

  return s.replace(/\s+/g, ' ').trim();
}

/* 4. Semantic Inline Span Decomposition + ToBI Intonation & Breath-Group Engine */

const CHUNK_LIMITS: Record<TargetLang, { minChars: number; targetChars: number; maxChars: number; maxWords: number }> = {
  id: { minChars: 28, targetChars: 130, maxChars: 165, maxWords: 22 },
  en: { minChars: 28, targetChars: 130, maxChars: 165, maxWords: 22 },
  ja: { minChars: 12, targetChars: 38, maxChars: 52, maxWords: 99 },
};

const CLAUSE_PIVOT_RE: Record<TargetLang, RegExp> = {
  id: /\s+(tetapi|namun|melainkan|sedangkan|sementara|karena|sebab|sehingga|meskipun|walaupun|ketika|saat|lalu|kemudian|dan)\s+/i,
  en: /\s+(and|but|however|because|while|although|though|when|where|which|since|yet|so)\s+/i,
  ja: /(\u3001|が|けれど|けど|ので|から|のに|ながら|そして|しかし|だが)/,
};

// Hard phrase-integrity anti-split guard: never end left chunk on dangling preposition/determiner
const DANGLING_LEFT_WORD: Record<TargetLang, RegExp> = {
  id: /\b(?:di|ke|dari|pada|untuk|yang|dengan|oleh|sebagai|terhadap|tentang|dalam|para|sang|si)$/i,
  en: /\b(?:the|a|an|of|in|to|for|with|by|at|from|into|onto|my|your|his|her|their|our)$/i,
  ja: /[のはがをにでへと]$/,
};

const ID_WHISPER_CUE =
  /\b(?:bisik(?:nya|ku|mu)?|berbisik|batin(?:nya|ku|mu)?|membatin|gumam(?:nya|ku|mu)?|bergumam|dalam hati|suara pelan|berkata pelan|ucapnya pelan|lirih)\b/i;
const EN_WHISPER_CUE = /\b(whispered|murmured|thought to|inwardly|quietly|softly|muttered)\b/i;
const JA_WHISPER_CUE = /(呟いた|ささやいた|思った|心の中で|小声で)/;

const ID_SHOUT_CUE =
  /\b(?:teriak(?:nya|ku|mu)?|berteriak|bentak(?:nya|ku|mu)?|membentak|seru(?:nya|ku|mu)?|berseru|pekik(?:nya|ku|mu)?|memekik|hardik(?:nya|ku|mu)?)\b/i;
const EN_SHOUT_CUE = /\b(shouted|yelled|screamed|snapped|barked|roared|exclaimed)\b/i;
const JA_SHOUT_CUE = /(叫んだ|怒鳴った|喚いた|声を荒らげ)/;

const ID_SPEECH_TAG_START =
  /^(?:kata|ujar|jawab|sahut|balas|tanya|gumam|bisik|seru|teriak|bentak|pekik|celetuk|lanjut|potong|ucap|tutur|tegas|sambung|timpal|desah|keluh)(?:nya|ku|mu)?\b/i;
const EN_SPEECH_TAG_START =
  /^(?:he|she|they|i|[A-Z][a-z]+)?\s*(?:said|asked|replied|whispered|murmured|muttered|shouted|yelled|snapped|added|continued|answered|sighed)\b/i;
const JA_SPEECH_TAG_START = /^(?:と|って)(?:彼|彼女|私|僕|俺)?[^。！？]{0,20}(?:言った|呟いた|尋ねた|答えた|叫んだ|ささやいた|笑った)/;

const ID_CASUAL_POLAR_RE =
  /^(?:apakah\b|apa\s+(?:kamu|kau|kalian|dia|ia|mereka|kita|kami|ini|itu|sudah|belum|bisa|benar|boleh|mau|yakin)\b)/i;
const WH_QUESTION_RE: Record<TargetLang, RegExp> = {
  id: /\b(?:siapa|apa(?!kah|-apa)|di mana|ke mana|dari mana|kapan|mengapa|kenapa|bagaimana|gimana|berapa|mana)\b/i,
  en: /^(?:(?:and|but|so|well|then|wait|[A-Z][a-z]+),?\s+)?(?:who|whom|whose|what|where|when|why|how|which)\b/i,
  ja: /(?:誰|だれ|何|なに|なん|どこ|いつ|なぜ|どうして|どう|どれ|いくら|いくつ)/,
};

const REFLECTIVE_CUE: Record<TargetLang, RegExp> = {
  id: /\b(mungkin|barangkali|rupanya|ternyata|dalam diam|entah mengapa|perlahan|hening|sunyi)\b/i,
  en: /\b(perhaps|maybe|quietly|slowly|wondered|realized|somehow|silence|softly)\b/i,
  ja: /(たぶん|おそらく|静かに|ゆっくり|ふと|なぜか|気がした)/,
};

function countWords(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function estimateSegmentMs(text: string, lang: TargetLang): number {
  if (!text) return 0;
  if (lang === 'ja') return Math.max(850, Math.round((text.length / 5.8) * 1000));
  const words = countWords(text);
  const wpm = lang === 'id' ? 140 : 152;
  return Math.max(850, Math.round((words / wpm) * 60_000));
}

export function classifyQuestionContour(sentence: string, lang: TargetLang): 'polar_question' | 'wh_question' {
  const clean = sentence.replace(/^["\u201C\u300C\u300E\s]+/, '').trim();
  if (lang === 'id' && ID_CASUAL_POLAR_RE.test(clean)) return 'polar_question';
  if (WH_QUESTION_RE[lang].test(clean)) return 'wh_question';
  return 'polar_question';
}

export interface InlineProsodySpan {
  type: 'quote' | 'speech_tag' | 'parenthetical' | 'narration';
  text: string;
  emotionHint?: 'whisper' | 'shout' | 'normal';
  speakerName?: string;
}

const SPEAKER_NAME_STOPWORDS = new Set([
  'Dia', 'Ia', 'Aku', 'Saya', 'Kamu', 'Kau', 'Mereka', 'Kami', 'Kita',
  'He', 'She', 'They', 'We', 'It', 'The', 'This', 'That', 'Then', 'And', 'But',
]);

function extractSpeakerFromTag(tagText: string, lang: TargetLang): string | undefined {
  const s = tagText.trim();
  if (!s) return undefined;
  if (lang === 'id') {
    const m = s.match(/(?:kata|ujar|jawab|sahut|balas|tanya|gumam|bisik|seru|teriak|bentak|ucap|lanjut)\s+([A-Z][a-zA-Z'-]{1,20})\b/);
    if (m && !SPEAKER_NAME_STOPWORDS.has(m[1])) return m[1];
    const m2 = s.match(/\b([A-Z][a-zA-Z'-]{1,20})\s+(?:berkata|berbisik|berteriak|bertanya|menjawab|bergumam|berseru|membentak)\b/);
    if (m2 && !SPEAKER_NAME_STOPWORDS.has(m2[1])) return m2[1];
  } else if (lang === 'en') {
    const m = s.match(/\b([A-Z][a-zA-Z'-]{1,20})\s+(?:said|asked|replied|whispered|murmured|muttered|shouted|yelled|snapped|added|answered)\b/);
    if (m && !SPEAKER_NAME_STOPWORDS.has(m[1])) return m[1];
    const m2 = s.match(/\b(?:said|asked|replied|whispered|shouted)\s+([A-Z][a-zA-Z'-]{1,20})\b/);
    if (m2 && !SPEAKER_NAME_STOPWORDS.has(m2[1])) return m2[1];
  } else {
    const m = s.match(/(?:と|って)([ァ-ヶー]{2,10}|[\u4e00-\u9fff]{1,4})(?:は|が|も)?(?:言った|呟いた|尋ねた|答えた|叫んだ|ささやいた|笑った)/);
    if (m) return m[1];
    const m2 = s.match(/([ァ-ヶー]{2,10}|[\u4e00-\u9fff]{1,4})(?:は|が)(?:静かに|小さく)?(?:言った|呟いた|尋ねた|答えた|叫んだ|ささやいた)/);
    if (m2) return m2[1];
  }
  return undefined;
}

export function decomposeInlineSpans(rawPara: string, lang: TargetLang): InlineProsodySpan[] {
  // Strip academic parenthetical citations BEFORE span tokenization so zero ghost empty parentheticals occur (#187)
  const t = rawPara
    .replace(/\(\s*[A-Z][a-z]+(?:\s+(?:et\s+al\.|&\s*[A-Z][a-z]+))?,\s*\d{4}[a-z]?(?:;\s*[^)]{1,60})?\)/g, '')
    .trim();
  if (!t) return [];

  // Tokenize quotes ("...", “...”, 「...」, 『...』), parentheticals ((...), （...）), and paired dash appositives (-- ... --)
  const TOKEN_RE =
    /("[^"\n]{1,500}"|\u201C[^\u201D\n]{1,500}\u201D|\u300C[^\u300D\n]{1,500}\u300D|\u300E[^\u300F\n]{1,500}\u300F|\([^()\n]{2,160}\)|\uFF08[^\uFF09\n]{2,100}\uFF09|--\s*[^-\n]{3,110}\s*--)/g;

  const spans: InlineProsodySpan[] = [];
  let cursor = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(t)) !== null) {
    if (m.index > cursor) {
      const between = t.slice(cursor, m.index).trim();
      if (between) spans.push({ type: 'narration', text: between });
    }
    const tok = m[0];
    if (tok.startsWith('(') || tok.startsWith('\uFF08')) {
      spans.push({ type: 'parenthetical', text: tok.slice(1, -1).trim() });
    } else if (tok.startsWith('--') && tok.endsWith('--')) {
      spans.push({ type: 'parenthetical', text: tok.slice(2, -2).trim() });
    } else {
      spans.push({ type: 'quote', text: tok, emotionHint: 'normal' });
    }
    cursor = m.index + tok.length;
  }
  if (cursor < t.length) {
    const tail = t.slice(cursor).trim();
    if (tail) spans.push({ type: 'narration', text: tail });
  }

  // Identify post-quote speech tags & propagate both emotion AND speaker attribution bidirectionally (#151, #153, #156)
  const isWhisper = (s: string) =>
    lang === 'id' ? ID_WHISPER_CUE.test(s) : lang === 'en' ? EN_WHISPER_CUE.test(s) : JA_WHISPER_CUE.test(s);
  const isShout = (s: string) =>
    lang === 'id' ? ID_SHOUT_CUE.test(s) : lang === 'en' ? EN_SHOUT_CUE.test(s) : JA_SHOUT_CUE.test(s);
  const isTag = (raw: string) => {
    const s = raw.replace(/^[,;:\s]+/, '');
    return (
      s.length > 0 &&
      s.length <= 75 &&
      (lang === 'id'
        ? ID_SPEECH_TAG_START.test(s) || ID_WHISPER_CUE.test(s) || ID_SHOUT_CUE.test(s)
        : lang === 'en'
          ? EN_SPEECH_TAG_START.test(s) || EN_WHISPER_CUE.test(s) || EN_SHOUT_CUE.test(s)
          : JA_SPEECH_TAG_START.test(s) || JA_WHISPER_CUE.test(s) || JA_SHOUT_CUE.test(s))
    );
  };

  for (let i = 1; i < spans.length; i++) {
    if (spans[i - 1].type === 'quote' && spans[i].type === 'narration' && isTag(spans[i].text)) {
      spans[i].type = 'speech_tag';
      const attrSpeaker = extractSpeakerFromTag(spans[i].text, lang);
      if (attrSpeaker) spans[i - 1].speakerName = attrSpeaker;
      if (isWhisper(spans[i].text)) {
        spans[i - 1].emotionHint = 'whisper';
      } else if (isShout(spans[i].text)) {
        spans[i - 1].emotionHint = 'shout';
      }
    } else if (spans[i].type === 'quote' && spans[i - 1].type === 'narration') {
      const preSpeaker = extractSpeakerFromTag(spans[i - 1].text, lang);
      if (preSpeaker) spans[i].speakerName = preSpeaker;
      if (isWhisper(spans[i - 1].text)) spans[i].emotionHint = 'whisper';
      else if (isShout(spans[i - 1].text)) spans[i].emotionHint = 'shout';
    }
  }
  return spans.filter((s) => s.text.length > 0);
}

function bisectToBreathGroups(sentence: string, lang: TargetLang, rateScale = 1.0): string[] {
  const baseLim = CHUNK_LIMITS[lang];
  // Rate-adaptive <11s anti-stall cap: tighten chunk length when speaking slowly (< 1.0x) (#168)
  const slowFactor = rateScale < 1.0 ? Math.max(0.62, rateScale) : 1.0;
  const lim = {
    minChars: Math.max(10, Math.round(baseLim.minChars * slowFactor)),
    targetChars: Math.max(24, Math.round(baseLim.targetChars * slowFactor)),
    maxChars: Math.max(32, Math.round(baseLim.maxChars * slowFactor)),
    maxWords: Math.max(10, Math.round(baseLim.maxWords * slowFactor)),
  };
  const exceeds = (s: string) =>
    s.length > lim.maxChars || (lang !== 'ja' && countWords(s) > lim.maxWords);

  if (!exceeds(sentence)) return [sentence];

  const clauseParts =
    lang === 'ja'
      ? sentence
        .split(/(?<=[\u3001\uFF0C\uFF1B\uFF1A])/)
        .map((p) => p.trim())
        .filter(Boolean)
      : sentence
        .split(/(?<=[,;:])\s+/)
        .map((p) => p.trim())
        .filter(Boolean);

  const merged: string[] = [];
  for (const part of clauseParts) {
    const prev = merged[merged.length - 1];
    const joiner = lang === 'ja' ? '' : ' ';
    if (
      prev &&
      prev.length + part.length + 1 <= lim.targetChars &&
      (lang === 'ja' || countWords(prev) + countWords(part) <= lim.maxWords - 2)
    ) {
      merged[merged.length - 1] = `${prev}${joiner}${part}`;
    } else {
      merged.push(part);
    }
  }

  const out: string[] = [];
  const splitBalanced = (seg: string) => {
    if (!exceeds(seg)) {
      out.push(seg);
      return;
    }
    const mid = Math.floor(seg.length / 2);
    const pivotRe = new RegExp(CLAUSE_PIVOT_RE[lang].source, lang === 'ja' ? 'g' : 'gi');
    let bestIdx = -1;
    let bestDist = Infinity;

    for (const m of seg.matchAll(pivotRe)) {
      const idx = (m.index ?? 0) + (lang === 'ja' ? m[0].length : 0);
      if (idx >= lim.minChars && seg.length - idx >= lim.minChars) {
        const leftCand = seg.slice(0, idx).trim();
        if (DANGLING_LEFT_WORD[lang].test(leftCand)) continue;
        const dist = Math.abs(idx - mid);
        if (dist < bestDist) {
          bestDist = dist;
          bestIdx = idx;
        }
      }
    }

    if (bestIdx === -1) {
      if (lang === 'ja') {
        bestIdx = mid;
        // Shift off Japanese particle boundary so particles stay attached to their host noun
        if (bestIdx + 1 < seg.length && /[はがをにでへと]/.test(seg[bestIdx])) {
          bestIdx += 1;
        }
      } else {
        const candidates: number[] = [];
        for (let i = lim.minChars; i < seg.length - lim.minChars; i++) {
          if (seg[i] === ' ') {
            const leftCand = seg.slice(0, i).trim();
            if (!DANGLING_LEFT_WORD[lang].test(leftCand)) candidates.push(i);
          }
        }
        if (candidates.length > 0) {
          bestIdx = candidates.reduce((a, b) => (Math.abs(a - mid) <= Math.abs(b - mid) ? a : b));
        } else {
          const leftSpace = seg.lastIndexOf(' ', mid);
          const rightSpace = seg.indexOf(' ', mid);
          bestIdx =
            leftSpace > lim.minChars && (rightSpace === -1 || mid - leftSpace <= rightSpace - mid)
              ? leftSpace
              : rightSpace > 0
                ? rightSpace
                : mid;
        }
      }
    }

    const left = seg.slice(0, bestIdx).trim();
    const right = seg.slice(bestIdx).trim();
    if (!left || !right) {
      out.push(seg);
      return;
    }
    splitBalanced(left);
    splitBalanced(right);
  };

  for (const seg of merged) splitBalanced(seg);
  return out;
}

function splitIntoSentences(clean: string, lang: TargetLang): string[] {
  if (!clean) return [];
  if (typeof Intl !== 'undefined' && 'Segmenter' in Intl) {
    try {
      const segmenter = new Intl.Segmenter(langToBcp47(lang), { granularity: 'sentence' });
      const parts: string[] = [];
      for (const item of segmenter.segment(clean)) {
        const t = item.segment.trim();
        if (t) parts.push(t);
      }
      if (parts.length > 0) return parts;
    } catch {
      // fallback regex below
    }
  }
  const matches = clean.match(/[^.!?\u3002\uFF01\uFF1F]+[.!?\u3002\uFF01\uFF1F]*["\u201D\u300D\u300F]*/g);
  return (matches || [clean]).map((s) => s.trim()).filter(Boolean);
}

function classifyRawParagraphKind(
  raw: string,
  lang: TargetLang,
  dialogueTurnCounter: number
): { isDialogue: boolean; isInner: boolean; isSystem: boolean; altSpeaker: boolean } {
  const t = raw.trim();
  const isSystem = /^[\u3010\[\u300A]/.test(t) && /[\u3011\]\u300B]$/.test(t);
  const isInner =
    (/^[\u300E(\uFF08]/.test(t) && /[\u300F)\uFF09]$/.test(t)) ||
    (lang === 'id' ? ID_WHISPER_CUE.test(t) : lang === 'en' ? EN_WHISPER_CUE.test(t) : JA_WHISPER_CUE.test(t));
  const isDialogue =
    !isSystem &&
    (/^[""\u201C\u300C]/.test(t) || /["\u201C\u300C][^"\u201D\u300D]{3,}["\u201D\u300D]/.test(t));
  return {
    isDialogue,
    isInner,
    isSystem,
    altSpeaker: isDialogue && dialogueTurnCounter % 2 === 1,
  };
}

const SUSPENSE_PIVOT_RE: Record<TargetLang, RegExp> = {
  id: /^(?:tiba-tiba|mendadak|ternyata|namun\s+seketika|saat\s+itu\s+juga|tak\s+disangka)\b/i,
  en: /^(?:suddenly|all\s+of\s+a\s+sudden|and\s+then|at\s+that\s+moment|unexpectedly)\b/i,
  ja: /^(?:突然|その瞬間|なんと|次の瞬間|まさか)/,
};

const SPEAKER_PERSONA_PALETTE: ReadonlyArray<{ pitch: number; rate: number }> = [
  { pitch: 0.032, rate: 1.02 },
  { pitch: -0.032, rate: 0.98 },
  { pitch: 0.018, rate: 1.03 },
  { pitch: -0.018, rate: 0.97 },
];

export function buildPodcastScript(
  paragraphs: string[],
  lang: TargetLang,
  options: {
    chapterTitle?: string;
    startParaIdx?: number;
    formatOverride?: 'auto' | DocumentFormatId;
    rateScale?: number;
  } = {}
): SpeechSegment[] {
  const segments: SpeechSegment[] = [];
  const startIdx = Math.max(0, options.startParaIdx || 0);
  const rateScale = options.rateScale ?? 1.0;
  const docFormat: DocumentFormatId =
    options.formatOverride && options.formatOverride !== 'auto'
      ? options.formatOverride
      : classifyDocumentFormat(paragraphs, lang);
  const fmtCfg = DOCUMENT_FORMAT_CONFIG[docFormat];

  // Opening title ritual when starting from the beginning
  if (startIdx === 0 && options.chapterTitle) {
    const cleanTitle = preprocessForSpeech(options.chapterTitle, lang);
    if (cleanTitle) {
      segments.push({
        id: 'intro-title',
        paraIdx: -1,
        text: cleanTitle,
        kind: 'chapter_intro',
        rateMult: 0.91,
        pitchDelta: -0.04,
        volumeMult: 1.0,
        pauseBeforeMs: 360,
        pauseAfterMs: 1050,
        estimatedMs: estimateSegmentMs(cleanTitle, lang),
        blockRole: 'heading',
        docFormat,
      });
    }
  }

  let dialogueStreak = 0;
  let shortBurstStreak = 0;
  let prevWasDialogue = false;
  const speakerRegistry = new Map<string, { slot: number; pitch: number; rate: number }>();
  const recentSpeakers: string[] = [];
  const registerSpeaker = (name: string) => {
    const key = name.trim();
    if (!speakerRegistry.has(key)) {
      const slot = speakerRegistry.size % SPEAKER_PERSONA_PALETTE.length;
      const p = SPEAKER_PERSONA_PALETTE[slot];
      speakerRegistry.set(key, { slot, pitch: p.pitch, rate: p.rate });
    }
    if (recentSpeakers[recentSpeakers.length - 1] !== key) {
      recentSpeakers.push(key);
      if (recentSpeakers.length > 4) recentSpeakers.shift();
    }
    return speakerRegistry.get(key)!;
  };

  const nonEmptyLastIdx = (() => {
    for (let i = paragraphs.length - 1; i >= 0; i--) {
      if (paragraphs[i]?.trim() && !SCENE_BREAK_RE.test(paragraphs[i].trim())) return i;
    }
    return -1;
  })();

  for (let pIdx = startIdx; pIdx < paragraphs.length; pIdx++) {
    const raw = (paragraphs[pIdx] || '').trim();
    if (!raw) continue;

    const blockRole = classifyBlockRole(raw, pIdx, docFormat);
    const nextNonEmptyRaw = paragraphs.slice(pIdx + 1).find((x) => (x || '').trim())?.trim() || '';
    const nextBlockRole = nextNonEmptyRaw ? classifyBlockRole(nextNonEmptyRaw, pIdx + 1, docFormat) : 'body';
    const isFinalListItem = blockRole === 'list_item' && nextBlockRole !== 'list_item';

    // 1. Two-tier macro scene break silence (1350ms subtle * * * vs 2100ms major === / ###) (#171, #181)
    if (blockRole === 'scene_break') {
      const isMajorDivider = /[=#■◆]{3,}/.test(raw);
      const breakMs = isMajorDivider ? 2100 : 1350;
      segments.push({
        id: `p${pIdx}-scene`,
        paraIdx: pIdx,
        text: '',
        kind: 'scene_break',
        rateMult: 1,
        pitchDelta: 0,
        volumeMult: 1,
        pauseBeforeMs: 0,
        pauseAfterMs: breakMs,
        estimatedMs: breakMs,
        blockRole,
        docFormat,
      });
      dialogueStreak = 0;
      shortBurstStreak = 0;
      prevWasDialogue = false;
      recentSpeakers.length = 0;
      continue;
    }

    // 2. Fenced code block -> concise spoken summary
    if (blockRole === 'code_block') {
      const summary = summarizeCodeBlockForSpeech(raw, lang);
      segments.push({
        id: `p${pIdx}-code`,
        paraIdx: pIdx,
        text: summary,
        kind: 'code_summary',
        rateMult: 0.94,
        pitchDelta: -0.03,
        volumeMult: 0.94,
        pauseBeforeMs: 280,
        pauseAfterMs: 640,
        estimatedMs: estimateSegmentMs(summary, lang),
        blockRole,
        docFormat,
      });
      prevWasDialogue = false;
      continue;
    }

    // 3. Markdown table -> linearized row-by-row speech
    if (blockRole === 'table_block') {
      const tableRows = linearizeMarkdownTableForSpeech(raw, lang);
      tableRows.forEach((rowText, rIdx) => {
        segments.push({
          id: `p${pIdx}-tbl-${rIdx}`,
          paraIdx: pIdx,
          text: rowText,
          kind: 'table_row',
          rateMult: 0.94,
          pitchDelta: rIdx === 0 ? 0.01 : -0.01,
          volumeMult: 0.98,
          pauseBeforeMs: rIdx === 0 ? 260 : 120,
          pauseAfterMs: rIdx === tableRows.length - 1 ? 650 : 380,
          estimatedMs: estimateSegmentMs(rowText, lang),
          blockRole,
          docFormat,
        });
      });
      prevWasDialogue = false;
      continue;
    }

    // 4. Script dialogue line ("SPEAKER: utterance")
    if (blockRole === 'script_line') {
      const sm = raw.match(SCRIPT_LINE_RE);
      if (sm) {
        const speaker = sm[1].trim();
        const body = preprocessForSpeech(sm[2], lang);
        const persona = registerSpeaker(speaker);
        segments.push({
          id: `p${pIdx}-spkr`,
          paraIdx: pIdx,
          text: speaker,
          kind: 'speech_tag',
          rateMult: 1.0,
          pitchDelta: -0.03,
          volumeMult: 0.9,
          pauseBeforeMs: 140,
          pauseAfterMs: 160,
          estimatedMs: estimateSegmentMs(speaker, lang),
          blockRole,
          docFormat,
          speakerName: speaker,
          speakerSlot: persona.slot,
        });
        if (body) {
          const isQ = /[?\uFF1F]$/.test(body);
          const qKind = isQ ? classifyQuestionContour(body, lang) : null;
          segments.push({
            id: `p${pIdx}-line`,
            paraIdx: pIdx,
            text: body,
            kind: qKind || (persona.pitch < 0 ? 'dialogue_alt' : 'dialogue'),
            rateMult: Number((persona.rate * fmtCfg.rateMult).toFixed(3)),
            pitchDelta:
              qKind === 'polar_question'
                ? 0.05
                : qKind === 'wh_question'
                  ? persona.pitch - 0.012
                  : persona.pitch,
            volumeMult: 1.0,
            pauseBeforeMs: 0,
            pauseAfterMs: 360,
            estimatedMs: estimateSegmentMs(body, lang),
            blockRole,
            docFormat,
            speakerName: speaker,
            speakerSlot: persona.slot,
          });
        }
        prevWasDialogue = true;
        continue;
      }
    }

    // 5. Poetry/Verse stanza (preserves enjambed vs end-stopped line breaks)
    if (blockRole === 'verse_line') {
      const verseLines = raw
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean);
      verseLines.forEach((vLine, vIdx) => {
        const cleanV = preprocessForSpeech(vLine, lang);
        if (!cleanV) return;
        const isLastLine = vIdx === verseLines.length - 1;
        const isEndStopped = /[.!?;:\u3002\uFF01\uFF1F]$/.test(cleanV);
        segments.push({
          id: `p${pIdx}-v${vIdx}`,
          paraIdx: pIdx,
          text: cleanV,
          kind: 'verse_line',
          rateMult: isLastLine ? 0.84 : 0.88,
          pitchDelta: isEndStopped ? -0.02 : 0.015,
          volumeMult: 0.96,
          pauseBeforeMs: vIdx === 0 ? 220 : 0,
          pauseAfterMs: isLastLine ? 820 : isEndStopped ? 500 : 280,
          estimatedMs: estimateSegmentMs(cleanV, lang),
          blockRole,
          docFormat,
        });
      });
      prevWasDialogue = false;
      continue;
    }

    const paraFlags = classifyRawParagraphKind(raw, lang, dialogueStreak);
    if (paraFlags.isDialogue) {
      dialogueStreak += 1;
    } else {
      dialogueStreak = 0;
    }

    const isLastParagraph = pIdx === nonEmptyLastIdx;
    const cleanedRawForSpans =
      blockRole === 'list_item' ? raw.replace(/^\s*(?:[-*\u2022+])\s+/, '') : raw;
    const inlineSpans = decomposeInlineSpans(cleanedRawForSpans, lang);
    const useSpanSplit =
      (blockRole === 'body' || blockRole === 'blockquote' || blockRole === 'list_item') &&
      inlineSpans.length > 1 &&
      inlineSpans.some((sp) => sp.type === 'quote' || sp.type === 'speech_tag' || sp.type === 'parenthetical');

    const singleSpeaker = extractSpeakerFromTag(cleanedRawForSpans, lang);
    const unitEntries: Array<{
      rawText: string;
      spanType: InlineProsodySpan['type'];
      emotionHint?: 'whisper' | 'shout' | 'normal';
      speakerName?: string;
    }> = useSpanSplit
        ? inlineSpans.map((sp) => ({
          rawText: sp.text,
          spanType: sp.type,
          emotionHint: sp.emotionHint,
          speakerName: sp.speakerName,
        }))
        : [
          {
            rawText: cleanedRawForSpans,
            spanType: paraFlags.isDialogue ? 'quote' : 'narration',
            emotionHint: 'normal',
            speakerName: paraFlags.isDialogue ? singleSpeaker : undefined,
          },
        ];

    let sentOrderInPara = 0;

    unitEntries.forEach((unit, uIdx) => {
      const clean = preprocessForSpeech(unit.rawText, lang);
      if (!clean) return;
      const sentences = splitIntoSentences(clean, lang);
      const isLastUnitInPara = uIdx === unitEntries.length - 1;

      // Two-pass speaker sieve: explicit tag speaker > alternating prior cast speaker > parity fallback
      let resolvedSpeakerName = unit.speakerName;
      let resolvedPersona: { slot: number; pitch: number; rate: number } | null = null;
      if (unit.spanType === 'quote') {
        if (resolvedSpeakerName) {
          resolvedPersona = registerSpeaker(resolvedSpeakerName);
        } else if (prevWasDialogue && recentSpeakers.length >= 2) {
          resolvedSpeakerName = recentSpeakers[recentSpeakers.length - 2];
          resolvedPersona = registerSpeaker(resolvedSpeakerName);
        }
      }

      sentences.forEach((sentence, sIdx) => {
        const isFirstSentInPara = uIdx === 0 && sIdx === 0;
        const isLastSentInPara = isLastUnitInPara && sIdx === sentences.length - 1;
        const isChapterOutro =
          isLastParagraph && isLastSentInPara && paragraphs.length >= 3 && docFormat === 'fiction_novel';

        const words = countWords(sentence);
        const isShort = lang === 'ja' ? sentence.length <= 26 : words <= 10;
        shortBurstStreak =
          isShort && blockRole === 'body' && docFormat === 'fiction_novel' ? shortBurstStreak + 1 : 0;

        const isQuestion = /[?\uFF1F]["\u201D\u300D\u300F]?$/.test(sentence);
        const isExclamation = /[!\uFF01]["\u201D\u300D\u300F]?$/.test(sentence);
        const hasEllipsis = /\.{3}|,\s*$/.test(sentence);
        const isSuspensePivot = SUSPENSE_PIVOT_RE[lang].test(sentence);
        const isReflective =
          unit.spanType !== 'quote' &&
          (REFLECTIVE_CUE[lang].test(sentence) ||
            (lang === 'ja' ? sentence.length >= 62 : words >= 24));

        const declination =
          blockRole === 'body' && unit.spanType === 'narration'
            ? sentOrderInPara === 0
              ? 0.016
              : -Math.min(0.032, sentOrderInPara * 0.008)
            : 0;
        sentOrderInPara += 1;

        let kind: SpeechSegmentKind = 'narration';
        let rateMult = 1.0 * fmtCfg.rateMult;
        let pitchDelta = declination;
        let volumeMult = 1.0;

        if (blockRole === 'heading') {
          kind = pIdx === 0 ? 'chapter_intro' : 'heading';
          rateMult = 0.91;
          pitchDelta = -0.035;
        } else if (blockRole === 'letter_salutation') {
          kind = 'letter_salutation';
          rateMult = 0.91;
          pitchDelta = 0.01;
        } else if (blockRole === 'letter_signoff') {
          kind = 'letter_signoff';
          rateMult = 0.89;
          pitchDelta = -0.035;
          volumeMult = 0.95;
        } else if (blockRole === 'blockquote') {
          kind = 'blockquote';
          rateMult = 0.92;
          pitchDelta = -0.025;
          volumeMult = 0.94;
        } else if (blockRole === 'list_item') {
          // Selting (2007) list enumeration cadence: continuation lift on non-final items, falling closure on final item
          kind = 'list_item';
          rateMult = (isFinalListItem ? 0.93 : 0.97) * fmtCfg.rateMult;
          pitchDelta = isFinalListItem ? -0.028 : 0.018;
        } else if (unit.spanType === 'speech_tag') {
          kind = 'speech_tag';
          rateMult = 1.04 * fmtCfg.rateMult;
          pitchDelta = -0.025;
          volumeMult = 0.9;
        } else if (unit.spanType === 'parenthetical') {
          // Dehe (2014) prosodic compression for parenthetical asides
          kind = 'parenthetical';
          rateMult = 1.09 * fmtCfg.rateMult;
          pitchDelta = -0.042;
          volumeMult = 0.87;
        } else if (isChapterOutro) {
          kind = 'chapter_outro';
          rateMult = 0.92;
          pitchDelta = -0.04;
        } else if (paraFlags.isSystem) {
          kind = 'system_notice';
          rateMult = 0.97;
          pitchDelta = -0.02;
        } else if (
          (paraFlags.isInner && unit.spanType !== 'quote') ||
          unit.emotionHint === 'whisper'
        ) {
          kind = 'inner_thought';
          rateMult = 0.92;
          pitchDelta = -0.045;
          volumeMult = 0.86;
        } else if (isQuestion) {
          const qContour = classifyQuestionContour(sentence, lang);
          kind = qContour;
          if (qContour === 'polar_question') {
            rateMult = 0.98 * fmtCfg.rateMult;
            pitchDelta = 0.055;
          } else {
            rateMult = 0.99 * fmtCfg.rateMult;
            pitchDelta = resolvedPersona ? resolvedPersona.pitch - 0.012 : -0.012;
          }
        } else if (isExclamation || unit.emotionHint === 'shout') {
          kind = 'exclamation';
          rateMult = 1.05 * fmtCfg.rateMult;
          pitchDelta = 0.055;
        } else if (unit.spanType === 'quote') {
          const useAlt = resolvedPersona ? resolvedPersona.pitch < 0 : paraFlags.altSpeaker;
          kind = useAlt ? 'dialogue_alt' : 'dialogue';
          rateMult = (resolvedPersona ? resolvedPersona.rate : 1.02) * fmtCfg.rateMult;
          pitchDelta = resolvedPersona ? resolvedPersona.pitch : paraFlags.altSpeaker ? -0.03 : 0.03;
        } else if (shortBurstStreak >= 2) {
          kind = 'action_burst';
          rateMult = 1.06;
          pitchDelta = 0.02;
        } else if (isReflective) {
          kind = 'reflective';
          rateMult = 0.94 * fmtCfg.rateMult;
          pitchDelta = -0.03;
          volumeMult = 0.95;
        }

        if (isSuspensePivot && unit.spanType === 'narration') {
          rateMult *= 0.94;
        }

        const subChunks = bisectToBreathGroups(sentence, lang, rateScale);
        subChunks.forEach((chunkText, cIdx) => {
          const isFirstChunk = cIdx === 0;
          const isLastChunk = cIdx === subChunks.length - 1;

          const finalLengthening = isLastChunk && subChunks.length > 1 ? 0.965 : 1.0;
          const contLift = !isLastChunk && /[,;\u3001]$/.test(chunkText) ? 0.012 : 0;

          let pauseBeforeMs = 0;
          if (isFirstSentInPara && isFirstChunk) {
            if (blockRole === 'heading') pauseBeforeMs = 280;
            else if (blockRole === 'blockquote') pauseBeforeMs = 240;
            else if (unit.spanType === 'quote' && !prevWasDialogue) pauseBeforeMs = 190;
            else if (unit.spanType !== 'quote' && prevWasDialogue) pauseBeforeMs = 160;
            else if (kind === 'inner_thought') pauseBeforeMs = 180;
          } else if (unit.spanType === 'parenthetical' && isFirstChunk) {
            pauseBeforeMs = 110;
          }
          if (isFirstChunk && isSuspensePivot) {
            pauseBeforeMs = Math.max(pauseBeforeMs, 320);
          }

          let pauseAfterMs = 130;
          if (isLastChunk) {
            if (blockRole === 'heading') pauseAfterMs = 950;
            else if (blockRole === 'list_item') pauseAfterMs = isFinalListItem ? 680 : 360;
            else if (blockRole === 'letter_salutation') pauseAfterMs = 620;
            else if (blockRole === 'letter_signoff') pauseAfterMs = 850;
            else if (isChapterOutro) pauseAfterMs = 1500;
            else if (unit.spanType === 'speech_tag' && !isLastUnitInPara) pauseAfterMs = 190;
            else if (unit.spanType === 'parenthetical') pauseAfterMs = 170;
            else if (isLastSentInPara) {
              pauseAfterMs = unit.spanType === 'quote' ? 310 : fmtCfg.paraBreakMs;
              if (hasEllipsis) pauseAfterMs += 180;
            } else if (hasEllipsis) {
              pauseAfterMs = 520;
            } else if (isQuestion) {
              pauseAfterMs = 370;
            } else if (isExclamation) {
              pauseAfterMs = kind === 'action_burst' ? 230 : 320;
            } else if (kind === 'action_burst') {
              pauseAfterMs = 200;
            } else {
              pauseAfterMs = 320;
            }
          }

          const spokenText = chunkText.replace(/^\.{3}\s*/, '').trim();
          if (chunkText.startsWith('...')) {
            pauseBeforeMs += 170;
          }
          if (!spokenText) return;

          segments.push({
            id: `p${pIdx}-u${uIdx}-s${sIdx}-c${cIdx}`,
            paraIdx: pIdx,
            text: spokenText,
            kind,
            rateMult: Number((rateMult * finalLengthening).toFixed(3)),
            pitchDelta: Number((pitchDelta + contLift).toFixed(3)),
            volumeMult,
            pauseBeforeMs,
            pauseAfterMs,
            estimatedMs: estimateSegmentMs(spokenText, lang),
            blockRole,
            docFormat,
            ...(resolvedSpeakerName ? { speakerName: resolvedSpeakerName } : {}),
            ...(resolvedPersona ? { speakerSlot: resolvedPersona.slot } : {}),
          });
        });
      });
    });

    prevWasDialogue = paraFlags.isDialogue;
  }

  return segments;
}

/* 5. MediaSession Bridge + Silent WAV Keep-Alive (Lock Screen & Earbuds) */

const SILENT_WAV_DATA_URI =
  'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';

class PodcastMediaBridge {
  private audio: HTMLAudioElement | null = null;

  private ensureAudio(): HTMLAudioElement | null {
    if (typeof document === 'undefined') return null;
    if (!this.audio) {
      const el = document.createElement('audio');
      el.src = SILENT_WAV_DATA_URI;
      el.loop = true;
      el.preload = 'auto';
      el.setAttribute('aria-hidden', 'true');
      this.audio = el;
    }
    return this.audio;
  }

  activate(
    meta: { title: string; chapter: string },
    handlers: {
      onPlay: () => void;
      onPause: () => void;
      onStop: () => void;
      onPrev: () => void;
      onNext: () => void;
    }
  ): void {
    this.ensureAudio()?.play().catch(() => { });
    if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: meta.chapter || meta.title,
        artist: meta.title || 'tranX Podcast Reader',
        album: 'tranX Ebook',
      });
      navigator.mediaSession.playbackState = 'playing';
      const bind = (action: MediaSessionAction, fn: MediaSessionActionHandler) => {
        try {
          navigator.mediaSession.setActionHandler(action, fn);
        } catch {
          // ignore unsupported action on browser
        }
      };
      bind('play', handlers.onPlay);
      bind('pause', handlers.onPause);
      bind('stop', handlers.onStop);
      bind('previoustrack', handlers.onPrev);
      bind('nexttrack', handlers.onNext);
      bind('seekbackward', handlers.onPrev);
      bind('seekforward', handlers.onNext);
    } catch {
      // ignore restricted environments
    }
  }

  setState(state: MediaSessionPlaybackState): void {
    if (state === 'playing') {
      this.audio?.play().catch(() => { });
    } else {
      this.audio?.pause();
    }
    if (typeof navigator !== 'undefined' && 'mediaSession' in navigator) {
      try {
        navigator.mediaSession.playbackState = state;
      } catch {
        // ignore
      }
    }
  }

  dispose(): void {
    this.setState('none');
    if (this.audio) {
      this.audio.pause();
      try {
        this.audio.removeAttribute('src');
        this.audio.load();
      } catch {
        // ignore uninitialized media reset
      }
      this.audio = null;
    }
    if (typeof navigator !== 'undefined' && 'mediaSession' in navigator) {
      try {
        navigator.mediaSession.metadata = null;
      } catch {
        // ignore
      }
      (
        ['play', 'pause', 'stop', 'previoustrack', 'nexttrack', 'seekbackward', 'seekforward'] as MediaSessionAction[]
      ).forEach((action) => {
        try {
          navigator.mediaSession.setActionHandler(action, null);
        } catch {
          // ignore
        }
      });
    }
  }
}

/* 6. Resilient Podcast Narrator Controller (AR(1) Variance + Engine Calibration + Virtual Pause) */

export const SLEEP_FADE_WINDOW_MS = 45_000;

/** Stevens (1957) & ISO 226:2023 convex power-law sleep fade envelope with gentle rate relaxation. */
export function computeSleepFadeEnvelope(remMs: number): {
  expired: boolean;
  volume: number;
  rateMult: number;
  inFadeWindow: boolean;
} {
  if (remMs <= 0) {
    return { expired: true, volume: 0, rateMult: 0.88, inFadeWindow: true };
  }
  if (remMs >= SLEEP_FADE_WINDOW_MS) {
    return { expired: false, volume: 1, rateMult: 1, inFadeWindow: false };
  }
  const progress = clamp(remMs / SLEEP_FADE_WINDOW_MS, 0, 1);
  const volume = clamp(Math.pow(progress, 1.55), 0.08, 1);
  const rateMult = clamp(0.88 + 0.12 * progress, 0.88, 1);
  return { expired: false, volume, rateMult, inFadeWindow: true };
}

export interface PodcastStartOptions {
  texts: string[];
  startIndex: number;
  lang: TargetLang;
  rate: TtsRate;
  style: PodcastStyleId;
  voiceUri?: string;
  chapterTitle?: string;
  seriesTitle?: string;
  sleepPreset?: PodcastSleepPreset;
  formatOverride?: 'auto' | DocumentFormatId;
  castMode?: PodcastCastMode;
}

export interface PodcastNarratorController {
  start: (opts: PodcastStartOptions) => void;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  setRate: (rate: TtsRate) => void;
  setStyle: (style: PodcastStyleId) => void;
  setVoiceUri: (uri: string) => void;
  setSleepPreset: (preset: PodcastSleepPreset) => void;
  setFormatOverride: (fmt: 'auto' | DocumentFormatId) => void;
  setCastMode: (mode: PodcastCastMode) => void;
  previewVoice: (uri?: string, langOverride?: TargetLang) => void;
  skipParagraph: (delta: -1 | 1) => void;
  jumpToParagraph: (paraIdx: number) => void;
}

function hashTextUnit(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 2001) / 1000 - 1; // [-1, 1]
}

export function createPodcastNarratorController(callbacks: {
  onSegmentStart: (
    paraIdx: number,
    kind: SpeechSegmentKind,
    docFormat?: DocumentFormatId,
    meta?: PodcastSegmentMeta
  ) => void;
  onStateChange: (state: TtsPlaybackState) => void;
  onChapterComplete?: () => void;
  onSleepTriggered?: () => void;
}): PodcastNarratorController {
  let script: SpeechSegment[] = [];
  let rawTexts: string[] = [];
  let cursor = 0;
  let activeLang: TargetLang = 'id';
  let activeRate: TtsRate = 1;
  let activeStyle: PodcastStyleId = 'podcast_santai';
  let activeFormatOverride: 'auto' | DocumentFormatId = 'auto';
  let activeCastMode: PodcastCastMode = 'persona';
  let preferredVoiceUri = '';
  let forceLocalFallback = false;
  let cachedVoices: SpeechSynthesisVoice[] = [];
  let state: TtsPlaybackState = 'idle';
  let sessionId = 0;
  let pauseTimerId: number | null = null;
  let watchdogTimerId: number | null = null;
  let launchWatchdogId: number | null = null;
  let settleTimerId: number | null = null;
  const activeUtterancePool = new Set<SpeechSynthesisUtterance>();
  let sleepPreset: PodcastSleepPreset = 'off';
  let sleepEndsAtMs = 0;
  let activeChapterTitle = '';
  let activeSeriesTitle = '';
  let arPitchState = 0;
  let arPauseState = 0;
  let listenersBound = false;
  const mediaBridge = new PodcastMediaBridge();

  const onVoicesChanged = () => {
    if (isTtsSupported()) {
      cachedVoices = window.speechSynthesis.getVoices();
    }
  };
  const onVisibilityChange = () => {
    if (
      typeof document !== 'undefined' &&
      document.visibilityState === 'visible' &&
      state === 'playing' &&
      isTtsSupported() &&
      !window.speechSynthesis.speaking &&
      !window.speechSynthesis.pending &&
      pauseTimerId === null &&
      settleTimerId === null
    ) {
      // Mobile OS suspended Web Speech in background -> cleanly re-anchor at current cursor (#166)
      const sid = sessionId;
      speakAtCursor(sid);
    }
  };

  const bindLifecycleListeners = () => {
    if (listenersBound) return;
    listenersBound = true;
    if (isTtsSupported()) {
      window.speechSynthesis.addEventListener?.('voiceschanged', onVoicesChanged);
    }
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibilityChange);
    }
  };

  const unbindLifecycleListeners = () => {
    if (!listenersBound) return;
    listenersBound = false;
    if (isTtsSupported()) {
      window.speechSynthesis.removeEventListener?.('voiceschanged', onVoicesChanged);
    }
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange);
    }
  };

  const clearTimers = () => {
    if (pauseTimerId !== null) {
      window.clearTimeout(pauseTimerId);
      pauseTimerId = null;
    }
    if (watchdogTimerId !== null) {
      window.clearTimeout(watchdogTimerId);
      watchdogTimerId = null;
    }
    if (launchWatchdogId !== null) {
      window.clearTimeout(launchWatchdogId);
      launchWatchdogId = null;
    }
    if (settleTimerId !== null) {
      window.clearTimeout(settleTimerId);
      settleTimerId = null;
    }
  };

  let sleepPausedRemainingMs = 0;
  let previewTimerId: number | null = null;

  const clearPreviewTimer = () => {
    if (previewTimerId !== null) {
      window.clearTimeout(previewTimerId);
      previewTimerId = null;
    }
  };

  const clearUtterancePool = () => {
    for (const u of activeUtterancePool) {
      u.onstart = null;
      u.onboundary = null;
      u.onend = null;
      u.onerror = null;
    }
    activeUtterancePool.clear();
  };

  const resolveActiveVoice = (speakerSlot?: number): SpeechSynthesisVoice | null => {
    const pool = cachedVoices.length > 0 ? cachedVoices : isTtsSupported() ? window.speechSynthesis.getVoices() : [];
    const ranked = rankVoicesForLang(pool, activeLang, !forceLocalFallback);
    if (forceLocalFallback) {
      const localPick = ranked.find((v) => v.voice.localService) || ranked[0];
      return localPick?.voice || null;
    }
    if (
      activeCastMode === 'multi_voice' &&
      typeof speakerSlot === 'number' &&
      speakerSlot > 0 &&
      ranked.length >= 2
    ) {
      const highTier = ranked.filter((v) => v.tier === 'veryHigh' || v.tier === 'high');
      const castPool = highTier.length >= 2 ? highTier : ranked.slice(0, 3);
      return castPool[speakerSlot % castPool.length]?.voice || ranked[0]?.voice || null;
    }
    if (preferredVoiceUri) {
      const explicit = ranked.find((v) => v.uri === preferredVoiceUri);
      if (explicit) return explicit.voice;
    }
    return ranked[0]?.voice || null;
  };

  const computeSleepStatus = () => {
    if (sleepPreset === 'off' || sleepPreset === 'chapter' || sleepEndsAtMs <= 0) {
      return { expired: false, volume: 1, rateMult: 1, inFadeWindow: false, remainingMs: 0 };
    }
    const rem = sleepEndsAtMs - Date.now();
    const env = computeSleepFadeEnvelope(rem);
    return { ...env, remainingMs: Math.max(0, rem) };
  };

  const setState = (next: TtsPlaybackState) => {
    state = next;
    callbacks.onStateChange(next);
    if (next === 'playing') {
      bindLifecycleListeners();
      mediaBridge.setState('playing');
    } else if (next === 'paused') {
      mediaBridge.setState('paused');
    } else {
      unbindLifecycleListeners();
      mediaBridge.dispose();
    }
  };

  // Post-cancel 50ms settle guard preventing Safari/WebKit dropped utterances on live mutations (#169)
  const scheduleRestartAfterCancel = (sid: number) => {
    clearTimers();
    clearPreviewTimer();
    clearUtterancePool();
    if (isTtsSupported()) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // ignore
      }
    }
    settleTimerId = window.setTimeout(() => {
      settleTimerId = null;
      if (sid === sessionId && state === 'playing') {
        speakAtCursor(sid);
      }
    }, 50);
  };

  const speakAtCursor = (sid: number, isLocalRetry = false) => {
    if (!isTtsSupported() || sid !== sessionId || state !== 'playing') return;
    clearTimers();

    if (cursor >= script.length) {
      clearUtterancePool();
      setState('idle');
      if (sleepPreset === 'chapter') {
        callbacks.onSleepTriggered?.();
      } else {
        callbacks.onChapterComplete?.();
      }
      return;
    }

    const sleepCheck = computeSleepStatus();
    if (sleepCheck.expired) {
      clearUtterancePool();
      setState('paused');
      callbacks.onSleepTriggered?.();
      return;
    }

    const seg = script[cursor];
    const styleCfg = PODCAST_STYLE_CONFIG[activeStyle];
    const fmtCfg = DOCUMENT_FORMAT_CONFIG[seg.docFormat];
    const chosenVoice = resolveActiveVoice(seg.speakerSlot);
    const engineCal = detectVoiceEngineProfile(chosenVoice);

    const noisePitch = hashTextUnit(`p:${seg.id}:${seg.text.slice(0, 24)}`);
    const noisePause = hashTextUnit(`t:${seg.id}:${seg.text.slice(0, 24)}`);
    arPitchState = clamp(0.55 * arPitchState + 0.45 * noisePitch * 0.009, -0.009, 0.009);
    arPauseState = clamp(0.55 * arPauseState + 0.45 * noisePause * 0.045, -0.045, 0.045);

    const isAndroid = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent || '');
    const segRateMult = activeCastMode === 'single' && seg.speakerName ? 1.0 : seg.rateMult;
    const segPitchDelta = activeCastMode === 'single' && seg.speakerName ? 0 : seg.pitchDelta;

    const effectiveRate = clamp(
      styleCfg.baseRate[activeLang] * activeRate * segRateMult * engineCal.rateScale * sleepCheck.rateMult,
      isAndroid ? 0.72 : 0.68,
      isAndroid ? 1.65 : 1.75
    );
    const effectivePitch = clamp(
      1.0 + segPitchDelta * styleCfg.pitchScale * fmtCfg.pitchScale * engineCal.pitchGain + arPitchState,
      engineCal.minPitch,
      engineCal.maxPitch
    );
    const pauseJitter = 1.0 + arPauseState;
    const isMacroBoundary =
      seg.kind === 'scene_break' ||
      seg.kind === 'heading' ||
      seg.kind === 'chapter_intro' ||
      seg.kind === 'chapter_outro';
    // Dual-exponent rate scaling: macro structural pauses preserve breathing room at 1.5x (#176)
    const ratePauseFactor = Math.pow(1 / effectiveRate, isMacroBoundary ? 0.45 : 0.78);
    const scalePause = (ms: number) =>
      ms <= 0
        ? 0
        : Math.round(clamp(ms * styleCfg.pauseScale * fmtCfg.pauseScale * ratePauseFactor * pauseJitter, 70, 2600));

    const meta: PodcastSegmentMeta = {
      speakerName: seg.speakerName,
      engineFamily: engineCal.family,
      isFallbackLocal: forceLocalFallback,
      sleepRemainingMs: sleepCheck.remainingMs,
    };

    if (seg.kind === 'scene_break' || !seg.text) {
      if (seg.paraIdx >= 0) callbacks.onSegmentStart(seg.paraIdx, seg.kind, seg.docFormat, meta);
      pauseTimerId = window.setTimeout(() => {
        if (sid !== sessionId || state !== 'playing') return;
        cursor += 1;
        speakAtCursor(sid);
      }, scalePause(seg.pauseAfterMs));
      return;
    }

    const launchUtterance = () => {
      if (sid !== sessionId || state !== 'playing') return;
      callbacks.onSegmentStart(seg.paraIdx, seg.kind, seg.docFormat, meta);

      const utter = new window.SpeechSynthesisUtterance(seg.text);
      if (chosenVoice) {
        try {
          utter.voice = chosenVoice;
        } catch {
          // Non-native or restricted voice objects fall back cleanly to utter.lang
        }
      }
      utter.lang = chosenVoice?.lang || langToBcp47(activeLang);
      utter.rate = effectiveRate;
      utter.pitch = effectivePitch;
      utter.volume = clamp(sleepCheck.volume * seg.volumeMult, 0.08, 1.0);
      activeUtterancePool.add(utter);

      let settled = false;
      const armEndWatchdog = () => {
        if (watchdogTimerId !== null) window.clearTimeout(watchdogTimerId);
        const watchdogMs = Math.max(6500, Math.round((seg.estimatedMs / effectiveRate) * 2.2 + 4000));
        watchdogTimerId = window.setTimeout(() => {
          if (settled || sid !== sessionId || state !== 'playing') return;
          utter.onend = null;
          utter.onerror = null;
          try {
            window.speechSynthesis.cancel();
          } catch {
            // ignore
          }
          advanceAfterEnd();
        }, watchdogMs);
      };

      const retryOnLocalFallback = (): boolean => {
        if (isLocalRetry || forceLocalFallback || chosenVoice?.localService) return false;
        forceLocalFallback = true;
        settled = true;
        utter.onend = null;
        utter.onerror = null;
        clearTimers();
        activeUtterancePool.delete(utter);
        try {
          window.speechSynthesis.cancel();
        } catch {
          // ignore
        }
        settleTimerId = window.setTimeout(() => {
          settleTimerId = null;
          if (sid === sessionId && state === 'playing') {
            speakAtCursor(sid, true);
          }
        }, 60);
        return true;
      };

      const advanceAfterEnd = () => {
        if (settled || sid !== sessionId || state !== 'playing') return;
        settled = true;
        utter.onend = null;
        utter.onerror = null;
        utter.onstart = null;
        utter.onboundary = null;
        clearTimers();
        activeUtterancePool.delete(utter);
        cursor += 1;
        const postDelay = scalePause(seg.pauseAfterMs);
        if (postDelay > 0 && cursor < script.length) {
          pauseTimerId = window.setTimeout(() => speakAtCursor(sid), postDelay);
        } else {
          speakAtCursor(sid);
        }
      };

      utter.onstart = () => {
        if (launchWatchdogId !== null) {
          window.clearTimeout(launchWatchdogId);
          launchWatchdogId = null;
        }
        armEndWatchdog();
      };
      utter.onboundary = () => {
        if (!settled && sid === sessionId && state === 'playing') {
          armEndWatchdog();
        }
      };
      utter.onend = advanceAfterEnd;
      utter.onerror = (ev) => {
        activeUtterancePool.delete(utter);
        if (settled || sid !== sessionId) return;
        const errCode = (ev as SpeechSynthesisErrorEvent)?.error;
        if (errCode === 'interrupted' || errCode === 'canceled') return;
        if ((errCode === 'network' || errCode === 'synthesis-failed' || errCode === 'audio-busy') && retryOnLocalFallback()) {
          return;
        }
        settled = true;
        utter.onend = null;
        utter.onerror = null;
        clearTimers();
        setState('idle');
      };

      // 2.8s launch watchdog for hung cloud voices -> falls back to local voice cleanly (#168)
      if (!forceLocalFallback && chosenVoice && !chosenVoice.localService) {
        launchWatchdogId = window.setTimeout(() => {
          launchWatchdogId = null;
          if (!settled && sid === sessionId && state === 'playing' && !window.speechSynthesis.speaking) {
            retryOnLocalFallback();
          }
        }, 2800);
      }
      armEndWatchdog();
      window.speechSynthesis.speak(utter);
    };

    const preDelay = scalePause(seg.pauseBeforeMs);
    if (preDelay > 0) {
      pauseTimerId = window.setTimeout(launchUtterance, preDelay);
    } else {
      launchUtterance();
    }
  };

  const applySleepPreset = (preset: PodcastSleepPreset) => {
    sleepPreset = preset;
    const durationMs = preset === '15' ? 15 * 60_000 : preset === '30' ? 30 * 60_000 : 0;
    if (durationMs > 0) {
      if (state === 'paused') {
        sleepEndsAtMs = 0;
        sleepPausedRemainingMs = durationMs;
      } else {
        sleepPausedRemainingMs = 0;
        sleepEndsAtMs = Date.now() + durationMs;
      }
    } else {
      sleepPausedRemainingMs = 0;
      sleepEndsAtMs = 0;
    }
  };

  const controller: PodcastNarratorController = {
    start(opts) {
      if (!isTtsSupported()) {
        setState('idle');
        return;
      }
      sessionId += 1;
      const sid = sessionId;
      clearTimers();
      clearUtterancePool();
      arPitchState = 0;
      arPauseState = 0;
      forceLocalFallback = false;
      window.speechSynthesis.cancel();
      unlockSpeechSynthesisOnGesture();

      rawTexts = opts.texts;
      activeLang = opts.lang;
      activeRate = opts.rate;
      activeStyle = opts.style;
      activeFormatOverride = opts.formatOverride || 'auto';
      if (opts.castMode) activeCastMode = opts.castMode;
      if (opts.voiceUri !== undefined) preferredVoiceUri = opts.voiceUri;
      activeChapterTitle = opts.chapterTitle || '';
      activeSeriesTitle = opts.seriesTitle || '';

      const effRateScale = PODCAST_STYLE_CONFIG[activeStyle].baseRate[activeLang] * activeRate;
      script = buildPodcastScript(opts.texts, opts.lang, {
        chapterTitle: opts.startIndex === 0 ? opts.chapterTitle : undefined,
        startParaIdx: opts.startIndex,
        formatOverride: activeFormatOverride,
        rateScale: effRateScale,
      });
      cursor = 0;

      if (script.length === 0) {
        setState('idle');
        return;
      }

      mediaBridge.activate(
        { title: activeSeriesTitle || 'tranX Ebook', chapter: activeChapterTitle },
        {
          onPlay: () => controller.resume(),
          onPause: () => controller.pause(),
          onStop: () => controller.stop(),
          onPrev: () => controller.skipParagraph(-1),
          onNext: () => controller.skipParagraph(1),
        }
      );
      setState('playing');
      if (opts.sleepPreset) applySleepPreset(opts.sleepPreset);

      const immediateVoices = window.speechSynthesis.getVoices();
      if (immediateVoices.length > 0) {
        cachedVoices = immediateVoices;
        speakAtCursor(sid);
      } else {
        loadSpeechVoices(900).then((loaded) => {
          if (sid !== sessionId || state !== 'playing') return;
          cachedVoices = loaded;
          speakAtCursor(sid);
        });
      }
    },

    pause() {
      if (state !== 'playing') return;
      sessionId += 1;
      clearTimers();
      clearUtterancePool();
      if (sleepEndsAtMs > 0) {
        sleepPausedRemainingMs = Math.max(0, sleepEndsAtMs - Date.now());
        sleepEndsAtMs = 0;
      }
      if (isTtsSupported()) {
        window.speechSynthesis.cancel();
      }
      setState('paused');
    },

    resume() {
      if (state !== 'paused' || script.length === 0 || !isTtsSupported()) return;
      sessionId += 1;
      const sid = sessionId;
      clearTimers();
      unlockSpeechSynthesisOnGesture();
      if (sleepPreset === '15' || sleepPreset === '30') {
        if (sleepPausedRemainingMs > 0) {
          sleepEndsAtMs = Date.now() + sleepPausedRemainingMs;
          sleepPausedRemainingMs = 0;
        } else if (sleepEndsAtMs > 0 && sleepEndsAtMs <= Date.now()) {
          applySleepPreset(sleepPreset);
        }
      }
      setState('playing');
      speakAtCursor(sid);
    },

    stop() {
      sessionId += 1;
      clearTimers();
      clearPreviewTimer();
      clearUtterancePool();
      sleepPausedRemainingMs = 0;
      sleepEndsAtMs = 0;
      script = [];
      rawTexts = [];
      cursor = 0;
      forceLocalFallback = false;
      if (isTtsSupported()) {
        window.speechSynthesis.cancel();
      }
      setState('idle');
    },

    setRate(rate) {
      activeRate = rate;
      if (state === 'playing' && isTtsSupported()) {
        sessionId += 1;
        scheduleRestartAfterCancel(sessionId);
      }
    },

    setStyle(style) {
      activeStyle = style;
      if (state === 'playing' && isTtsSupported()) {
        sessionId += 1;
        scheduleRestartAfterCancel(sessionId);
      }
    },

    setVoiceUri(uri) {
      preferredVoiceUri = uri;
      forceLocalFallback = false;
      if (state === 'playing' && isTtsSupported()) {
        sessionId += 1;
        scheduleRestartAfterCancel(sessionId);
      }
    },

    setCastMode(mode) {
      activeCastMode = mode;
      if (state === 'playing' && isTtsSupported()) {
        sessionId += 1;
        scheduleRestartAfterCancel(sessionId);
      }
    },

    previewVoice(uri, langOverride) {
      if (!isTtsSupported()) return;
      const lang = langOverride || activeLang;
      const sample =
        lang === 'en'
          ? 'This is a calm preview of your chosen reading voice.'
          : lang === 'ja'
            ? 'こんにちは、選択した音声のプレビューです。'
            : 'Halo, ini contoh suara narator untuk menemani bacaan Anda.';
      const pool = cachedVoices.length > 0 ? cachedVoices : window.speechSynthesis.getVoices();
      const ranked = rankVoicesForLang(pool, lang);
      const chosen = (uri ? ranked.find((v) => v.uri === uri)?.voice : null) || ranked[0]?.voice || null;
      try {
        clearPreviewTimer();
        window.speechSynthesis.cancel();
        previewTimerId = window.setTimeout(() => {
          previewTimerId = null;
          try {
            const u = new window.SpeechSynthesisUtterance(sample);
            if (chosen) u.voice = chosen;
            u.lang = chosen?.lang || langToBcp47(lang);
            u.rate = PODCAST_STYLE_CONFIG[activeStyle].baseRate[lang];
            window.speechSynthesis.speak(u);
          } catch {
            // ignore restricted environments
          }
        }, 50);
      } catch {
        // ignore restricted environments
      }
    },

    setSleepPreset(preset) {
      applySleepPreset(preset);
    },

    setFormatOverride(fmt) {
      activeFormatOverride = fmt;
      if (rawTexts.length > 0 && (state === 'playing' || state === 'paused')) {
        const currentPara = Math.max(0, script[Math.min(cursor, Math.max(0, script.length - 1))]?.paraIdx ?? 0);
        const effRateScale = PODCAST_STYLE_CONFIG[activeStyle].baseRate[activeLang] * activeRate;
        script = buildPodcastScript(rawTexts, activeLang, {
          startParaIdx: currentPara,
          formatOverride: activeFormatOverride,
          rateScale: effRateScale,
        });
        cursor = 0;
        if (state === 'playing' && isTtsSupported()) {
          sessionId += 1;
          scheduleRestartAfterCancel(sessionId);
        }
      }
    },

    skipParagraph(delta) {
      if (script.length === 0 || rawTexts.length === 0) return;
      const currentPara = Math.max(0, script[Math.min(cursor, script.length - 1)]?.paraIdx ?? 0);
      let targetPara = clamp(currentPara + delta, 0, rawTexts.length - 1);
      while (
        targetPara > 0 &&
        targetPara < rawTexts.length - 1 &&
        !(rawTexts[targetPara] || '').trim()
      ) {
        targetPara += delta;
      }
      controller.jumpToParagraph(targetPara);
    },

    jumpToParagraph(paraIdx) {
      if (rawTexts.length === 0) return;
      const clampedPara = clamp(paraIdx, 0, rawTexts.length - 1);
      const firstBodySeg = script.find((seg) => seg.paraIdx >= 0);
      const needsRebuild = !firstBodySeg || clampedPara < firstBodySeg.paraIdx;
      const existingIdx = needsRebuild
        ? -1
        : script.findIndex((seg) => seg.paraIdx >= clampedPara);
      if (existingIdx >= 0) {
        cursor = existingIdx;
      } else {
        const effRateScale = PODCAST_STYLE_CONFIG[activeStyle].baseRate[activeLang] * activeRate;
        script = buildPodcastScript(rawTexts, activeLang, {
          startParaIdx: clampedPara,
          formatOverride: activeFormatOverride,
          rateScale: effRateScale,
        });
        cursor = 0;
      }
      if (state === 'playing' && isTtsSupported()) {
        sessionId += 1;
        scheduleRestartAfterCancel(sessionId);
      } else if (state === 'paused' && script[cursor]) {
        callbacks.onSegmentStart(
          Math.max(0, script[cursor].paraIdx),
          script[cursor].kind,
          script[cursor].docFormat,
          {
            speakerName: script[cursor].speakerName,
            engineFamily: detectVoiceEngineProfile(resolveActiveVoice(script[cursor].speakerSlot)).family,
            isFallbackLocal: forceLocalFallback,
            sleepRemainingMs: computeSleepStatus().remainingMs,
          }
        );
      }
    },
  };

  return controller;
}
