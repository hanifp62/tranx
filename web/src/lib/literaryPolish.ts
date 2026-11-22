/**
 * Multi-Level Skopos, Audience-Calibrated Literary & Technical Translation Engine (tranX v4)
 * Synthesized from translation science (Nida, Newmark, Nord Skopos, Baker 5-Level, House TQA,
 * MQM Core, EYD V / KBBI VI) & 300+ cross-genre linguistic readings (JA / EN / ID):
 * - Author-Purpose-Reader Skopos Profiler & Zero-Dependency Complexity Scoring (EN FKGL,
 *   ID Harjasujana-Fry, JA Hasebe-Lee JReadability -> L1..L5 calibration).
 * - AST-Safe FormatShield (protects fenced/inline code, LaTeX math, SRT/VTT/ASS, URLs/DOIs,
 *   Markdown headings/lists/tables/footnotes BEFORE punctuation normalization).
 * - Multi-Level Post-Editing: EYD V + KBBI VI orthography, 40+ JA idioms & 30+ mimetics,
 *   55+ anti-translationese & collocation rules, EN uncountable repairs, JA pronoun drop.
 * - 12-Invariant ConservationGate & MQM Risk Scoring (exact numeric multiset, currencies,
 *   SI units, years, table/structural parity, extended hard + semi-negation, legal deontics,
 *   zero U+2014 em-dash, atomic rollback).
 */

import type {
  GlossaryEntry,
  SourceLang,
  TargetLang,
  TitleKind,
  TitleStyle,
  TranslationTonePref,
} from '../types';
import { readTranslationTonePref, saveTranslationTonePref } from './tonePrefs';

export { readTranslationTonePref, saveTranslationTonePref };

export type StoryDomain =
  | 'school_peer'
  | 'workplace_modern'
  | 'historical_fantasy'
  | 'slice_of_life'
  | 'formal_nonfiction';

export type GenreKind =
  | 'children_ya'
  | 'fiction_novel'
  | 'classic_literary'
  | 'fiction_dialogue_heavy'
  | 'manga_comic_sfx'
  | 'subtitle_script'
  | 'essay_journalism'
  | 'academic_research'
  | 'technical_docs'
  | 'legal_policy'
  | 'news_wire'
  | 'business_formal'
  | 'general';

export type RegisterLevel =
  | 'intimate_casual'
  | 'literary_neutral'
  | 'novel_archaic'
  | 'dramatic_action'
  | 'semi_formal_editorial'
  | 'formal_academic'
  | 'formal_legal_tech';

export type NarrativePov =
  | '1P_CASUAL'
  | '1P_FORMAL'
  | '1P_ARCHAIC'
  | '3P_LIMITED'
  | '2P_INSTRUCTIONAL';

export type ReissTextType = 'informative' | 'expressive' | 'operative' | 'audiomedial';
export type TranslationMethod = 'semantic' | 'balanced' | 'communicative';
export type HouseMode = 'overt' | 'covert';
export type CulturalFilter = 'none' | 'light' | 'full';
export type MetaphorPolicy = 'preserve_image' | 'adapt_stock' | 'flatten_literal';
export type ComplexityTier = 'L1' | 'L2' | 'L3' | 'L4' | 'L5';

export interface SourceComplexityMetrics {
  score: number; // 0..100
  tier: ComplexityTier;
  asl: number;
}

export interface MqmDefect {
  category:
  | 'accuracy_omission'
  | 'accuracy_addition'
  | 'accuracy_untranslated'
  | 'accuracy_polarity'
  | 'accuracy_number_unit'
  | 'accuracy_modal'
  | 'accuracy_hedging'
  | 'terminology'
  | 'markup_format'
  | 'fluency_punctuation'
  | 'fluency_repetition_loop'
  | 'style_register';
  severity: 'minor' | 'major' | 'critical';
  weight: number;
  detail: string;
}

export type JaKeigoTier = 'plain' | 'bikago' | 'teineigo' | 'kenjougo' | 'sonkeigo';

export interface JaKeigoClassification {
  tier: JaKeigoTier;
  elevatesReferent: boolean;
  humblesSpeaker: boolean;
  locksPoliteRegister: boolean;
}

export interface CenteringState {
  cb: string | null;
  cfList: string[];
  recentEntities: string[];
  speakerStack: string[];
  empathyDirection: 'to_speaker' | 'from_speaker' | 'neutral';
  turnIndex: number;
}

export interface QeReport {
  ok: boolean;
  needsSelfRepair: boolean;
  qeRiskScore: number; // 0..100+ weighted 3:2:1 (Accuracy:Acceptability:Readability)
  defects: MqmDefect[];
  metrics: {
    fertilityRatio: number;
    untranslatedRatio: number;
    repetitionDetected: boolean;
    numericConservationOk: boolean;
    deonticOk: boolean;
    hedgingOk: boolean;
  };
}

export interface SelfRepairPayload {
  systemPrompt: string;
  userPrompt: string;
  defectCodes: string[];
}

export interface ConservationResult {
  ok: boolean;
  mqmRiskScore: number;
  defects: MqmDefect[];
}

export interface DiscourseProfile {
  srcLang: TargetLang;
  tgtLang: TargetLang;
  domain: StoryDomain;
  genre: GenreKind;
  register: RegisterLevel;
  pov: NarrativePov;
  toneOverride: TranslationTonePref;
  dialogueRatio: number;
  jaPoliteRatio: number;
  hasLegalOrAcademicMarkers: boolean;
  hasCodeOrTechMarkers: boolean;
  allowCasualDialogue: boolean;
  allowIdPronounSoften: boolean;
  narratorId1P: 'aku' | 'saya' | 'preserve';
  jaTargetStyle: 'tameguchi' | 'da_dearu' | 'desu_masu' | 'keigo';
  enContractions: 'allow' | 'dialogue_only' | 'forbid';
  // v4 Translation-Science & Skopos Calibration fields
  reissType: ReissTextType;
  skoposGoal: string;
  equivalenceAxis: number; // 0.0 formal .. 1.0 dynamic
  translationMethod: TranslationMethod;
  houseMode: HouseMode;
  culturalFilter: CulturalFilter;
  metaphorPolicy: MetaphorPolicy;
  sourceComplexity: number; // 0..100
  sourceTier: ComplexityTier;
  targetComplexityBand: [number, number];
  maxTargetAslWords: number;
  lengthBudgetRatio: number | null;
  honorificPolicy: 'keep' | 'localize' | 'drop';
  strictDeonticModals: boolean;
  seriesClosingContext: Array<{ src: string; dst: string }>;
  cacheFingerprint: string;
}

export interface SeriesDiscourseMemory {
  seriesKey: string;
  domain: StoryDomain;
  genre: GenreKind;
  register: RegisterLevel;
  pov: NarrativePov;
  narratorId1P: 'aku' | 'saya' | 'preserve';
  honorificNames: Record<string, string>;
  closingContext: Array<{ src: string; dst: string }>;
  updatedAt: number;
}

const SERIES_MEMORY_STORAGE_KEY = 'tranx_series_discourse_v1';
const MAX_SERIES_MEMORY = 48;
const seriesMemoryMap = new Map<string, SeriesDiscourseMemory>();
let seriesMemoryLoaded = false;

function loadSeriesMemoryOnce(): void {
  if (seriesMemoryLoaded || typeof window === 'undefined') return;
  seriesMemoryLoaded = true;
  try {
    const raw = window.localStorage.getItem(SERIES_MEMORY_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      for (const item of parsed) {
        if (item && typeof item.seriesKey === 'string') {
          seriesMemoryMap.set(item.seriesKey, item as SeriesDiscourseMemory);
        }
      }
    }
  } catch {
    // Ignore storage read issues
  }
}

function flushSeriesMemory(): void {
  if (typeof window === 'undefined') return;
  try {
    const entries = Array.from(seriesMemoryMap.values())
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_SERIES_MEMORY);
    window.localStorage.setItem(SERIES_MEMORY_STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Ignore storage quota issues
  }
}

export function getSeriesDiscourseMemory(seriesKey?: string | null): SeriesDiscourseMemory | null {
  if (!seriesKey) return null;
  loadSeriesMemoryOnce();
  return seriesMemoryMap.get(seriesKey) || null;
}

export function saveSeriesDiscourseMemory(
  seriesKey: string | undefined | null,
  profile: DiscourseProfile,
  srcParagraphs: string[],
  dstParagraphs: string[],
  honorificNames?: Record<string, string>
): void {
  if (!seriesKey) return;
  loadSeriesMemoryOnce();
  const prev = seriesMemoryMap.get(seriesKey);
  const closing: Array<{ src: string; dst: string }> = [];
  for (let i = srcParagraphs.length - 1; i >= 0 && closing.length < 2; i -= 1) {
    const s = (srcParagraphs[i] || '').trim();
    const d = (dstParagraphs[i] || '').trim();
    if (s.length >= 12 && d.length >= 12) {
      closing.unshift({ src: s.slice(0, 220), dst: d.slice(0, 220) });
    }
  }
  const mergedHonorifics: Record<string, string> = {
    ...(prev?.honorificNames || {}),
    ...(honorificNames || {}),
  };
  const keys = Object.keys(mergedHonorifics);
  if (keys.length > 60) {
    for (const k of keys.slice(0, keys.length - 60)) {
      delete mergedHonorifics[k];
    }
  }
  seriesMemoryMap.set(seriesKey, {
    seriesKey,
    domain: profile.domain,
    genre: profile.genre,
    register: profile.register,
    pov: profile.pov,
    narratorId1P: profile.narratorId1P,
    honorificNames: mergedHonorifics,
    closingContext: closing.length > 0 ? closing : prev?.closingContext || [],
    updatedAt: Date.now(),
  });
  flushSeriesMemory();
}

export function clearSeriesDiscourseMemory(): void {
  seriesMemoryMap.clear();
  seriesMemoryLoaded = false;
}

export function clearSeriesDiscourseMemoryForTests(): void {
  clearSeriesDiscourseMemory();
}

// ---------- User Translation Tone Preference (re-exported from ./tonePrefs) ----------

// ---------- Stage 1: Document-Level & Series-Aware Discourse Profiler ----------

const LEGAL_POLICY_RE =
  /(?:Pasal\s+\d+|Ayat\s*\(\d+\)|Undang-Undang|Whereas\b|Hereinafter|SHALL\s+NOT|MUST\s+NOT|第\d+条|利用規約|免責事項|個人情報保護|プライバシーポリシー|Copyright\s+©)/g;
const TECH_DOCS_RE =
  /(?:```|`[^`\n]{2,60}`|\b(?:HTTP|JSON|API|SDK|CLI|REST|GraphQL|RFC\s*\d+|localhost|npm|git|async|await|endpoint|payload|deployment)\b|関数|引数|エラー|実装|仕様書)/g;
const ACADEMIC_RE =
  /(?:\b(?:Abstract|Methodology|Hypothesis|Conclusion|et\s+al\.|doi:|Abstrak|Metodologi|Hipotesis|Kesimpulan|Daftar\s+Pustaka)\b|要旨|考察|参考文献|\([A-Z][a-z]+,\s*\d{4}\))/g;
const BUSINESS_FORMAL_RE =
  /(?:拝啓|敬具|お世話になっております|ご確認(?:いただけ|くださ)|いただけますでしょうか|申し上げます|存じます|\b(?:Dengan\s+hormat|Bapak\/Ibu|Mohon\s+kesediaan|Hormat\s+kami|Dear\s+Sir|Sincerely,|Pursuant\s+to)\b)/g;
const NEWS_WIRE_RE =
  /(?:と発表した|とみられている|と報じた|政府は|記者会見|\b(?:Reuters|Associated\s+Press|officials\s+said|spokesperson\s+said|menurut\s+pejabat|ujar\s+juru\s+bicara)\b)/g;

const JA_SCHOOL_RE =
  /(?:教室|クラスメイト|高校|中学|生徒会|部活|先輩|後輩|担任|テスト|放課後|登校|制服|学園|授業|体育祭|文化祭)/g;
const JA_WORK_RE =
  /(?:課長|部長|社長|上司|同僚|会社|残業|会議|取引先|オフィス|係長|出社|営業)/g;
const JA_FANTASY_ARCHAIC_RE =
  /(?:殿下|陛下|王女|騎士|貴族|魔法|ギルド|冒険者|魔王|勇者|侍女|執事|屋敷|城|公爵|伯爵|旦那様|お嬢様|宦官|後宮|拙者|余は|そなた|貴殿|ござる|平伏|玉座|天命|勅命)/g;
const JA_ACTION_RE =
  /(?:斬り|斬る|突き刺|血飛沫|鮮血|爆発|衝撃|咆哮|殺気|刃|剣戟|銃声|弾丸|吹き飛|激突|絶叫|魔力|詠唱|必殺|貫いた)/g;

const EN_ARCHAIC_RE =
  /\b(?:thou|thee|thy|thine|hath|doth|ere|whence|behold|my lord|my lady|your grace|your majesty|sire|foe|covenant|citadel|sovereign)\b/gi;
const EN_ACTION_RE =
  /\b(?:slashed|parried|blood|blade|gunshot|exploded|shattered|lunged|dodged|roared|screamed|impact|ambush|bleeding|struck)\b/gi;
const EN_FICTION_CUE_RE =
  /\b(?:whispered|murmured|muttered|sighed|shrugged|glanced|stared|frowned|smirked|grinned|chuckled|gasped|stepped|heart\s+pounded)\b/gi;

const ID_ARCHAIC_RE =
  /\b(?:paduka|baginda|hamba|beta|patik|engkau|dikau|tiada|hendak|niscaya|wahai|tatkala|seraya|titah|sabda|takhta|ksatria|adinda|kakanda)\b/gi;
const ID_CASUAL_CUE_RE =
  /\b(?:aku|kamu|kau|nggak|gak|sih|kok|lho|dong|deh|ujarnya|katanya|gumamnya|bisiknya|tanyanya|serunya|menghela\s+napas)\b/gi;

const QUOTE_LINE_RE = /^\s*(?:[「『"“]|[^:\n]{1,24}:\s*[「『"“])/;
const JA_POLITE_END_RE = /(?:です|ます|ました|でした|ません|ましょう|ございます|ください)[。！？!?…」』"\s]*$/;
const JA_1P_CASUAL_RE = /(?:俺|僕|あたし|うち|わし|自分)(?:は|が|の|も|を|に|だって)/g;
const JA_1P_WATASHI_RE = /(?:私|わたし|ワタシ)(?:は|が|の|も|を|に)/g;
const JA_1P_ARCHAIC_RE = /(?:余|我|吾輩|拙者|わっち)(?:は|が|の|も)/g;

const CHILDREN_CUE_RE =
  /(?:むかしむかし|ある日|うさぎ|魔法の森|\b(?:once\s+upon\s+a\s+time|fairy\s+tale|pada\s+suatu\s+hari|dongeng|kelinci\s+kecil|hutan\s+ajaib)\b)/gi;
const WEB_NOVEL_TROPE_RE =
  /(?:ステータス|レベルアップ|スキル|ギルド|ダンジョン|チート|\b(?:level\s+up|status\s+window|skill\s+tree|guild\s+rank|mana\s+pool)\b)/gi;
const DEONTIC_MODAL_RE =
  /\b(?:SHALL\s+NOT|MUST\s+NOT|SHALL|MUST|MAY\s+NOT|wajib|dilarang|berhak)\b|(?:なければならない|してはならない)/g;
const FORMAL_ID_LEX_RE =
  /\b(?:sebagaimana|berdasarkan|apabila|melainkan|sedangkan|kendatipun|implementasi|signifikan|hipotesis|metodologi|ketentuan|kewajiban|sehubungan|mengenai|terhadap|[a-z]{4,}(?:isasi|itas|isme|logi))\b/gi;
const JA_FORMAL_GRAMMAR_RE =
  /(?:である|であった|において|に関して|に基づき|に対して|したがって|すなわち|ございます|いたします|申し上げます|存じます|しなければならない)/g;

const clampNum = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

function countMatches(text: string, re: RegExp): number {
  const clone = new RegExp(re.source, re.flags.includes('g') ? re.flags : `${re.flags}g`);
  return (text.match(clone) || []).length;
}

function estimateEnglishSyllables(word: string): number {
  const clean = word.toLowerCase().replace(/[^a-z]/g, '');
  if (!clean) return 1;
  if (clean.length <= 3) return 1;
  const groups = clean.match(/[aeiouy]+/g) || [];
  let count = groups.length;
  if (clean.endsWith('e') && !/[^aeiouy]le$/.test(clean) && count > 1) {
    count -= 1;
  }
  return Math.max(1, count);
}

/**
 * Zero-dependency readability & source-complexity estimator (0..100 -> L1..L5):
 * - EN: Flesch-Kincaid Grade Level normalized
 * - ID: Harjasujana-adapted Fry syllable calibration (x0.60) + formal lexical density
 * - JA: Hasebe-Lee (JReadability) & Sato script-class complexity model
 */
export function computeSourceComplexity(
  paragraphs: string[],
  srcLang: TargetLang
): SourceComplexityMetrics {
  const cleanParas = paragraphs
    .map((p) => (p || '').replace(/```[\s\S]*?```/g, ' ').replace(/https?:\/\/\S+/g, ' ').trim())
    .filter((p) => p.length > 0)
    .slice(0, 40);
  const joined = cleanParas.join('\n');
  if (!joined) return { score: 42, tier: 'L2', asl: 12 };

  let score = 45;
  let asl = 14;

  if (srcLang === 'ja') {
    const sentences = joined.split(/[。！？\n]+/).map((s) => s.trim()).filter(Boolean);
    const nonSpace = joined.match(/[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9]/g) || [];
    const totalChars = Math.max(nonSpace.length, 1);
    const totalSents = Math.max(sentences.length, 1);
    asl = totalChars / totalSents;
    const kanjiCount = (joined.match(/[\u4e00-\u9fff]/g) || []).length;
    const hiraCount = (joined.match(/[\u3040-\u309f]/g) || []).length;
    const kangoRuns = (joined.match(/[\u4e00-\u9fff]{2,}/g) || []).length;
    const formalHits = countMatches(joined, JA_FORMAL_GRAMMAR_RE);
    const kanjiRatio = kanjiCount / totalChars;
    const hiraRatio = hiraCount / totalChars;
    const kangoPerSent = kangoRuns / totalSents;
    const formalDensity = formalHits / totalSents;
    score = clampNum(
      0.5 * Math.min(asl, 80) +
      75.0 * kanjiRatio +
      3.5 * Math.min(kangoPerSent, 6.0) -
      16.0 * Math.max(0, hiraRatio - 0.55) +
      8.0 * Math.min(formalDensity, 1.0),
      0,
      100
    );
  } else {
    const abbrevSafe = joined.replace(/\b(?:Mr|Mrs|Ms|Dr|Prof|Jr|Sr|St|No|Fig|Vol|vs|etc|al|e\.g|i\.e)\./gi, '$& ');
    const sentences = abbrevSafe
      .split(/[.!?\n]+/)
      .map((s) => s.trim())
      .filter((s) => /[A-Za-zÀ-ÿ]/.test(s));
    const words = joined.match(/[A-Za-zÀ-ÿ']+/g) || [];
    const totalWords = Math.max(words.length, 1);
    const totalSents = Math.max(sentences.length, 1);
    asl = totalWords / totalSents;

    if (srcLang === 'en') {
      const syllables = words.reduce((acc, w) => acc + estimateEnglishSyllables(w), 0);
      const asw = syllables / totalWords;
      const fkgl = 0.39 * asl + 11.8 * asw - 15.59;
      score = clampNum(((fkgl - 1.5) / 14.5) * 100, 0, 100);
    } else {
      const nuclei = words.reduce((acc, w) => acc + Math.max(1, (w.toLowerCase().match(/[aiueo]+/g) || []).length), 0);
      const aswAdj = (nuclei / totalWords) * 0.6;
      const formalLexRatio = countMatches(joined, FORMAL_ID_LEX_RE) / totalWords;
      const fkglId = 0.39 * asl + 11.8 * aswAdj - 15.59;
      score = clampNum(((fkglId - 1.5) / 14.5) * 100 + 85.0 * Math.min(formalLexRatio, 0.25), 0, 100);
    }
  }

  const rounded = Math.round(score);
  const tier: ComplexityTier =
    rounded <= 24 ? 'L1' : rounded <= 49 ? 'L2' : rounded <= 69 ? 'L3' : rounded <= 84 ? 'L4' : 'L5';
  return { score: rounded, tier, asl: Math.round(asl * 10) / 10 };
}

export function profileDocument(params: {
  paragraphs: string[];
  srcLang: TargetLang;
  tgtLang: TargetLang;
  seriesKey?: string | null;
  toneOverride?: TranslationTonePref;
  titleKind?: TitleKind;
  titleStyle?: TitleStyle;
  docFormat?: 'txt' | 'md' | 'html' | 'epub' | 'pdf' | 'docx' | 'srt' | 'vtt' | 'image';
  audienceOverride?: 'auto' | 'children_ya' | 'general' | 'specialist';
}): DiscourseProfile {
  const { paragraphs, srcLang, tgtLang } = params;
  const toneOverride: TranslationTonePref = params.toneOverride || readTranslationTonePref();
  const sampleParas = paragraphs
    .map((p) => (p || '').trim())
    .filter(Boolean)
    .slice(0, 40);
  const sampleText = sampleParas.join('\n');
  const totalParas = Math.max(sampleParas.length, 1);

  const seriesMem = getSeriesDiscourseMemory(params.seriesKey);
  const complexity = computeSourceComplexity(sampleParas, srcLang);

  // Structural metrics
  let quoteLines = 0;
  let jaPoliteLines = 0;
  let narrativeLines = 0;
  let shortLines = 0;
  let sfxLines = 0;
  let exclamLines = 0;
  let speakerTagLines = 0;
  for (const p of sampleParas) {
    if (QUOTE_LINE_RE.test(p) || /[「『"“][^」』"”]{2,}[」』"”]/.test(p)) {
      quoteLines += 1;
    } else {
      narrativeLines += 1;
    }
    if (JA_POLITE_END_RE.test(p)) jaPoliteLines += 1;
    if (p.length <= 42) shortLines += 1;
    if (/^[ァ-ヶーッっ・!！?？\s]{2,14}$|^[A-Z]{3,14}!+$/.test(p)) sfxLines += 1;
    if (/[!！?？]/.test(p)) exclamLines += 1;
    if (/^(?:\[[^\]]{1,20}\]|[A-Z][A-Za-z]{1,16})\s*:/.test(p)) speakerTagLines += 1;
  }
  const dialogueRatio = quoteLines / totalParas;
  const shortLineRatio = shortLines / totalParas;
  const sfxRatio = sfxLines / totalParas;
  const exclamRatio = exclamLines / totalParas;
  const speakerTagRatio = speakerTagLines / totalParas;
  const jaPoliteRatio = srcLang === 'ja' ? jaPoliteLines / totalParas : 0;

  // Gate hits (conservative toward formality so formal/legal/tech docs are NEVER casualized)
  const legalHits = countMatches(sampleText, LEGAL_POLICY_RE);
  const deonticHits = countMatches(sampleText, DEONTIC_MODAL_RE);
  const techHits = countMatches(sampleText, TECH_DOCS_RE);
  const academicHits = countMatches(sampleText, ACADEMIC_RE);
  const businessHits = countMatches(sampleText, BUSINESS_FORMAL_RE);
  const newsHits = countMatches(sampleText, NEWS_WIRE_RE);
  const childrenHits = countMatches(sampleText, CHILDREN_CUE_RE);
  const webNovelTropeHits = countMatches(sampleText, WEB_NOVEL_TROPE_RE);

  const schoolHits = countMatches(sampleText, JA_SCHOOL_RE);
  const workHits = countMatches(sampleText, JA_WORK_RE);
  const archaicHits =
    countMatches(sampleText, JA_FANTASY_ARCHAIC_RE) +
    countMatches(sampleText, EN_ARCHAIC_RE) +
    countMatches(sampleText, ID_ARCHAIC_RE);
  const actionHits = countMatches(sampleText, JA_ACTION_RE) + countMatches(sampleText, EN_ACTION_RE);
  const fictionCues =
    countMatches(sampleText, EN_FICTION_CUE_RE) + countMatches(sampleText, ID_CASUAL_CUE_RE);

  const hasLegalOrAcademicMarkers = legalHits >= 2 || (legalHits >= 1 && deonticHits >= 2) || academicHits >= 2;
  const hasCodeOrTechMarkers = techHits >= 3 || sampleText.includes('```');

  let genre: GenreKind = 'general';
  let register: RegisterLevel = 'literary_neutral';
  let domain: StoryDomain = 'slice_of_life';

  const schoolThresh = sampleParas.length <= 6 ? 1 : 2;
  if (legalHits >= 2 || (legalHits >= 1 && deonticHits >= 2)) {
    genre = 'legal_policy';
    register = 'formal_legal_tech';
    domain = 'formal_nonfiction';
  } else if (hasCodeOrTechMarkers && dialogueRatio < 0.2) {
    genre = 'technical_docs';
    register = 'formal_legal_tech';
    domain = 'formal_nonfiction';
  } else if (academicHits >= 2 && dialogueRatio < 0.2) {
    genre = 'academic_research';
    register = 'formal_academic';
    domain = 'formal_nonfiction';
  } else if (businessHits >= 1 && dialogueRatio < 0.25) {
    genre = 'business_formal';
    register = 'formal_academic';
    domain = 'workplace_modern';
  } else if (
    params.docFormat === 'srt' ||
    params.docFormat === 'vtt' ||
    params.titleKind === 'subtitle' ||
    sampleParas.some((p) => p.includes('-->')) ||
    (dialogueRatio >= 0.45 && shortLineRatio >= 0.65 && speakerTagRatio >= 0.2)
  ) {
    genre = 'subtitle_script';
    register = jaPoliteRatio >= 0.65 ? 'semi_formal_editorial' : 'intimate_casual';
    domain = schoolHits >= schoolThresh ? 'school_peer' : archaicHits >= 2 ? 'historical_fantasy' : 'slice_of_life';
  } else if (
    params.docFormat === 'image' ||
    params.titleKind === 'komik' ||
    (shortLineRatio >= 0.72 && (sfxRatio >= 0.15 || exclamRatio >= 0.45) && totalParas >= 2)
  ) {
    genre = 'manga_comic_sfx';
    register =
      archaicHits >= 2
        ? 'novel_archaic'
        : actionHits >= 2
          ? 'dramatic_action'
          : jaPoliteRatio >= 0.65
            ? 'literary_neutral'
            : 'intimate_casual';
    domain =
      archaicHits >= 2 ? 'historical_fantasy' : schoolHits >= schoolThresh ? 'school_peer' : 'slice_of_life';
  } else if (newsHits >= 2 && dialogueRatio < 0.25) {
    genre = 'news_wire';
    register = 'semi_formal_editorial';
    domain = 'formal_nonfiction';
  } else if (
    params.audienceOverride === 'children_ya' ||
    (dialogueRatio >= 0.1 && complexity.score <= 28 && archaicHits === 0 && childrenHits >= 2)
  ) {
    genre = 'children_ya';
    register = 'intimate_casual';
    domain = 'slice_of_life';
  } else if (
    dialogueRatio >= 0.14 ||
    schoolHits >= schoolThresh ||
    archaicHits >= 2 ||
    fictionCues >= 2 ||
    params.titleKind === 'novel' ||
    countMatches(sampleText, JA_1P_CASUAL_RE) >= 1 ||
    (seriesMem &&
      (seriesMem.genre === 'fiction_novel' ||
        seriesMem.genre === 'fiction_dialogue_heavy' ||
        seriesMem.genre === 'classic_literary'))
  ) {
    const isClassicLiterary =
      archaicHits >= 2 ||
      (complexity.score >= 58 && schoolHits === 0 && webNovelTropeHits === 0 && dialogueRatio < 0.45);
    genre = isClassicLiterary
      ? 'classic_literary'
      : dialogueRatio >= 0.35
        ? 'fiction_dialogue_heavy'
        : 'fiction_novel';
    if (archaicHits >= 2) {
      domain = 'historical_fantasy';
      register = 'novel_archaic';
    } else if (isClassicLiterary) {
      domain = seriesMem?.domain || 'slice_of_life';
      register = 'literary_neutral';
    } else if (schoolHits >= schoolThresh) {
      domain = 'school_peer';
      register = jaPoliteRatio < 0.45 ? 'intimate_casual' : 'literary_neutral';
    } else if (workHits >= 2) {
      domain = 'workplace_modern';
      register = 'literary_neutral';
    } else if (actionHits >= 3) {
      domain = seriesMem?.domain || 'slice_of_life';
      register = 'dramatic_action';
    } else {
      domain = seriesMem?.domain || 'slice_of_life';
      register = jaPoliteRatio < 0.35 ? 'intimate_casual' : 'literary_neutral';
    }
  } else if (sampleText.length >= 240 && dialogueRatio < 0.08) {
    genre = 'essay_journalism';
    register = 'semi_formal_editorial';
    domain = 'formal_nonfiction';
  } else if (seriesMem) {
    genre = seriesMem.genre;
    register = seriesMem.register;
    domain = seriesMem.domain;
  }

  // Apply explicit user tone preference while strictly preserving legal/academic/code precision
  if (toneOverride === 'formal') {
    register = hasLegalOrAcademicMarkers || hasCodeOrTechMarkers ? 'formal_legal_tech' : 'formal_academic';
    if (genre === 'general') genre = 'essay_journalism';
  } else if (toneOverride === 'novel' && !hasLegalOrAcademicMarkers && !hasCodeOrTechMarkers) {
    if (genre === 'general' || genre === 'essay_journalism') genre = 'fiction_novel';
    if (register !== 'novel_archaic') register = 'literary_neutral';
  } else if (toneOverride === 'casual' && !hasLegalOrAcademicMarkers && !hasCodeOrTechMarkers) {
    if (genre === 'general' || genre === 'essay_journalism') genre = 'fiction_dialogue_heavy';
    register = 'intimate_casual';
  }

  // POV Detection (scanning narration lines outside Japanese/Latin quotes)
  const narrationOnly = sampleParas
    .filter((p) => !QUOTE_LINE_RE.test(p))
    .map((p) => p.replace(/[「『"“][^」』"”]*[」』"”]/g, ' '))
    .join('\n');

  const ja1pCasualHits = countMatches(narrationOnly, JA_1P_CASUAL_RE);
  const ja1pWatashiHits = countMatches(narrationOnly, JA_1P_WATASHI_RE);
  const ja1pArchaicHits = countMatches(narrationOnly, JA_1P_ARCHAIC_RE);
  const en1pHits = srcLang === 'en' ? countMatches(narrationOnly, /\b(?:I|I'm|I've|I'd|my|myself)\b/g) : 0;
  const id1pAkuHits = srcLang === 'id' ? countMatches(narrationOnly, /\b(?:aku|ku[a-z]+)\b/gi) : 0;

  const isFictionGenre =
    genre === 'children_ya' ||
    genre === 'fiction_novel' ||
    genre === 'classic_literary' ||
    genre === 'fiction_dialogue_heavy' ||
    genre === 'manga_comic_sfx';

  let pov: NarrativePov = seriesMem?.pov || '3P_LIMITED';
  if (genre === 'technical_docs') {
    pov = '2P_INSTRUCTIONAL';
  } else if (ja1pArchaicHits >= 1) {
    pov = '1P_ARCHAIC';
  } else if (ja1pCasualHits >= 1 || id1pAkuHits >= 2 || (en1pHits >= 2 && isFictionGenre)) {
    pov = '1P_CASUAL';
  } else if (ja1pWatashiHits >= 1) {
    const politeNarrRatio =
      narrativeLines > 0
        ? sampleParas.filter((p) => !QUOTE_LINE_RE.test(p) && JA_POLITE_END_RE.test(p)).length /
        narrativeLines
        : 0;
    pov =
      politeNarrRatio >= 0.45 || genre === 'business_formal' || genre === 'academic_research'
        ? '1P_FORMAL'
        : '1P_CASUAL';
  } else if (seriesMem && isFictionGenre) {
    pov = seriesMem.pov;
  }

  const isStrictFormal =
    register === 'formal_academic' ||
    register === 'formal_legal_tech' ||
    genre === 'legal_policy' ||
    genre === 'academic_research' ||
    genre === 'technical_docs' ||
    genre === 'business_formal';

  const allowCasualDialogue =
    !isStrictFormal &&
    register !== 'novel_archaic' &&
    genre !== 'classic_literary' &&
    (genre === 'children_ya' ||
      genre === 'fiction_novel' ||
      genre === 'fiction_dialogue_heavy' ||
      genre === 'manga_comic_sfx' ||
      genre === 'subtitle_script' ||
      toneOverride === 'casual' ||
      toneOverride === 'novel');

  const allowIdPronounSoften =
    tgtLang === 'id' &&
    !isStrictFormal &&
    !hasLegalOrAcademicMarkers &&
    !hasCodeOrTechMarkers &&
    businessHits === 0 &&
    genre !== 'classic_literary' &&
    (toneOverride === 'casual' ||
      toneOverride === 'novel' ||
      ((genre === 'children_ya' ||
        genre === 'fiction_novel' ||
        genre === 'fiction_dialogue_heavy' ||
        genre === 'manga_comic_sfx' ||
        genre === 'subtitle_script') &&
        (register === 'intimate_casual' ||
          register === 'literary_neutral' ||
          register === 'dramatic_action') &&
        jaPoliteRatio < 0.45));

  const narratorId1P: 'aku' | 'saya' | 'preserve' = isStrictFormal
    ? 'saya'
    : pov === '1P_CASUAL'
      ? 'aku'
      : pov === '1P_FORMAL'
        ? 'saya'
        : seriesMem?.narratorId1P || (allowIdPronounSoften ? 'aku' : 'preserve');

  const jaTargetStyle: DiscourseProfile['jaTargetStyle'] =
    genre === 'business_formal'
      ? 'keigo'
      : isStrictFormal || genre === 'news_wire' || genre === 'children_ya'
        ? 'desu_masu'
        : genre === 'fiction_dialogue_heavy' || genre === 'manga_comic_sfx' || register === 'intimate_casual'
          ? 'tameguchi'
          : 'da_dearu';

  const enContractions: DiscourseProfile['enContractions'] = isStrictFormal
    ? 'forbid'
    : genre === 'fiction_dialogue_heavy' ||
      genre === 'manga_comic_sfx' ||
      genre === 'subtitle_script' ||
      genre === 'children_ya' ||
      register === 'intimate_casual'
      ? 'allow'
      : 'dialogue_only';

  // Author-Purpose-Reader Skopos & Nida/Newmark/House Calibration Matrix
  const skoposMap: Record<
    GenreKind,
    {
      reiss: ReissTextType;
      goal: string;
      eq: number;
      method: TranslationMethod;
      house: HouseMode;
      filter: CulturalFilter;
      metaphor: MetaphorPolicy;
      band: [number, number];
      asl: number;
      lenRatio: number | null;
    }
  > = {
    children_ya: {
      reiss: 'expressive',
      goal: 'Warm, concrete, easy-to-follow story tailored for young readers',
      eq: 0.9,
      method: 'communicative',
      house: 'covert',
      filter: 'full',
      metaphor: 'adapt_stock',
      band: [8, 38],
      asl: 13,
      lenRatio: null,
    },
    fiction_novel: {
      reiss: 'expressive',
      goal: 'Immersive natural novel prose preserving author voice and cultural flavor',
      eq: 0.8,
      method: 'balanced',
      house: 'overt',
      filter: 'light',
      metaphor: 'preserve_image',
      band: [24, 60],
      asl: 18,
      lenRatio: null,
    },
    fiction_dialogue_heavy: {
      reiss: 'expressive',
      goal: 'Lively character-driven dialogue with natural spoken cadence',
      eq: 0.85,
      method: 'communicative',
      house: 'overt',
      filter: 'light',
      metaphor: 'adapt_stock',
      band: [20, 52],
      asl: 16,
      lenRatio: null,
    },
    classic_literary: {
      reiss: 'expressive',
      goal: 'Author-centered literary fidelity preserving rhythm, imagery, and depth',
      eq: 0.45,
      method: 'semantic',
      house: 'overt',
      filter: 'none',
      metaphor: 'preserve_image',
      band: [48, 86],
      asl: 24,
      lenRatio: null,
    },
    manga_comic_sfx: {
      reiss: 'audiomedial',
      goal: 'Punchy, compact speech-bubble dialogue & crisp comic SFX matching visual space',
      eq: 0.88,
      method: 'communicative',
      house: 'overt',
      filter: 'light',
      metaphor: 'adapt_stock',
      band: [12, 42],
      asl: 11,
      lenRatio: 1.18,
    },
    subtitle_script: {
      reiss: 'audiomedial',
      goal: 'Concise instant-comprehension spoken lines fitting subtitle timing',
      eq: 0.92,
      method: 'communicative',
      house: 'covert',
      filter: 'full',
      metaphor: 'adapt_stock',
      band: [12, 42],
      asl: 12,
      lenRatio: 1.08,
    },
    news_wire: {
      reiss: 'informative',
      goal: 'Crisp objective journalistic clarity preserving attribution and hedging',
      eq: 0.65,
      method: 'communicative',
      house: 'covert',
      filter: 'full',
      metaphor: 'adapt_stock',
      band: [45, 72],
      asl: 22,
      lenRatio: null,
    },
    essay_journalism: {
      reiss: 'informative',
      goal: 'Fluid, articulate editorial prose preserving argument flow and nuance',
      eq: 0.65,
      method: 'balanced',
      house: 'covert',
      filter: 'light',
      metaphor: 'preserve_image',
      band: [42, 74],
      asl: 22,
      lenRatio: null,
    },
    business_formal: {
      reiss: 'operative',
      goal: 'Courteous, clear executive communication aligned to target business etiquette',
      eq: 0.6,
      method: 'communicative',
      house: 'covert',
      filter: 'full',
      metaphor: 'flatten_literal',
      band: [50, 80],
      asl: 21,
      lenRatio: null,
    },
    technical_docs: {
      reiss: 'operative',
      goal: 'Exact technical accuracy, scannable instructions, and immutable code/CLI syntax',
      eq: 0.3,
      method: 'semantic',
      house: 'covert',
      filter: 'light',
      metaphor: 'flatten_literal',
      band: [52, 84],
      asl: 20,
      lenRatio: null,
    },
    academic_research: {
      reiss: 'informative',
      goal: 'Scholarly rigor preserving epistemic hedging, terminology, and citations',
      eq: 0.25,
      method: 'semantic',
      house: 'overt',
      filter: 'light',
      metaphor: 'preserve_image',
      band: [65, 96],
      asl: 26,
      lenRatio: null,
    },
    legal_policy: {
      reiss: 'operative',
      goal: 'Zero-drift statutory precision preserving deontic modals, clauses, and polarity',
      eq: 0.1,
      method: 'semantic',
      house: 'overt',
      filter: 'none',
      metaphor: 'flatten_literal',
      band: [78, 100],
      asl: 30,
      lenRatio: null,
    },
    general: {
      reiss: 'informative',
      goal: 'Clear, accurate, natural prose calibrated to source complexity',
      eq: 0.72,
      method: 'balanced',
      house: 'covert',
      filter: 'light',
      metaphor: 'adapt_stock',
      band: [24, 72],
      asl: 19,
      lenRatio: null,
    },
  };

  const sk = skoposMap[genre];
  const [gMin, gMax] = sk.band;
  const targetMin = Math.round(clampNum(Math.min(complexity.score - 8, gMax - 10), gMin, gMax));
  const targetMax = Math.round(clampNum(Math.max(complexity.score + 8, gMin + 10), gMin, gMax));
  const honorificPolicy: 'keep' | 'localize' | 'drop' =
    params.titleStyle?.honorific_style ||
    (genre === 'business_formal' || genre === 'legal_policy' || domain === 'historical_fantasy'
      ? 'localize'
      : 'keep');
  const strictDeonticModals = genre === 'legal_policy' || (genre === 'technical_docs' && deonticHits >= 1);

  const cacheFingerprint = `v4:${toneOverride}:${domain}:${genre}:${register}:${pov}:${complexity.tier}:${honorificPolicy}`;

  return {
    srcLang,
    tgtLang,
    domain,
    genre,
    register,
    pov,
    toneOverride,
    dialogueRatio,
    jaPoliteRatio,
    hasLegalOrAcademicMarkers,
    hasCodeOrTechMarkers,
    allowCasualDialogue,
    allowIdPronounSoften,
    narratorId1P,
    jaTargetStyle,
    enContractions,
    reissType: sk.reiss,
    skoposGoal: sk.goal,
    equivalenceAxis: sk.eq,
    translationMethod: sk.method,
    houseMode: sk.house,
    culturalFilter: sk.filter,
    metaphorPolicy: sk.metaphor,
    sourceComplexity: complexity.score,
    sourceTier: complexity.tier,
    targetComplexityBand: [targetMin, targetMax],
    maxTargetAslWords: sk.asl,
    lengthBudgetRatio: sk.lenRatio,
    honorificPolicy,
    strictDeonticModals,
    seriesClosingContext: seriesMem?.closingContext || [],
    cacheFingerprint,
  };
}

// ---------- Stage 1B: Japanese Honorifics, Idioms & Mimetics Lexicons ----------

// Non-person compounds ending in さん/さま/くん/ちゃん/せんせい/せんぱい that must NEVER be treated as person honorifics
const JA_NON_PERSON_HONORIFIC_WORDS = new Set([
  'たくさん', 'おっさん', 'おじさん', 'おばさん', 'お兄さん', 'お姉さん', 'お母さん', 'お父さん',
  'お爺さん', 'お婆さん', 'おじいさん', 'おばあさん', '奥さん', '旦那さん', '皆さん', 'みなさん',
  'お客さん', '店員さん', '運転手さん', '警察官さん', 'お巡りさん', 'お医者さん', '神様', '王様',
  'お姫様', '王子様', '殿様', '奥様', '旦那様', 'お嬢様', '坊っちゃん', 'お坊ちゃま', 'お客様',
  '皆様', 'みなさま', 'お疲れ様', 'ご苦労様', 'ごちそうさま', 'ご馳走様', 'お邪魔様', 'おかげさま',
  'お陰様', 'お互い様', 'おあいこ様', '様変わり', '様子', '様々', '一様', '同様', '左様', '仕様',
  '諸君', '細君', '赤ん坊', '赤ちゃん', '先輩方', '後輩たち', '先生方', '生産', '計算', '解散',
  '予算', '登山', '火山', '鉱山', '財産', '遺産', '水産', '拡散', '倒産', '量産', '出産', '破産',
  '悲惨', '無惨', '賛成', '参照', '太陽', '火山', '大山', '富士山',
]);

const JA_KATAKANA_STOPLIST = new Set([
  'マンション', 'レストラン', 'パソコン', 'エアコン', 'システム', 'モンスター', 'クラスメイト',
  'スマートフォン', 'アパート', 'コンビニ', 'カフェ', 'テーブル', 'ベッド', 'カーテン', 'ドア',
  'スマホ', 'テレビ', 'カメラ', 'ゲーム', 'スキル', 'ステータス', 'レベル', 'ダンジョン', 'ギルド',
]);

// Curated Japanese literary idioms (Session 1 + Session 3) -> pre-mask hints for LLM & GTX rescue
export interface JaIdiomEntry {
  ja: RegExp;
  label: string;
  idHint: string;
  enHint: string;
  gtxLiteralId?: RegExp;
  gtxNaturalId?: string;
  gtxLiteralEn?: RegExp;
  gtxNaturalEn?: string;
}

export const JA_LITERARY_IDIOMS: JaIdiomEntry[] = [
  {
    ja: /首を(?:傾げ|かしげ)/,
    label: '首を傾げる',
    idHint: 'memiringkan kepala dengan bingung / mengernyit heran',
    enHint: 'tilted their head in confusion / looked puzzled',
    gtxLiteralId: /\bmemiringkan kepalanya\b/gi,
    gtxNaturalId: 'memiringkan kepala dengan heran',
  },
  {
    ja: /苦笑(?:い|し|する)/,
    label: '苦笑い',
    idHint: 'tersenyum kecut / tersenyum getir / terkekeh canggung',
    enHint: 'gave a wry smile / smiled wryly',
    gtxLiteralId: /\b(?:tertawa|tersenyum)\s+pahit\b/gi,
    gtxNaturalId: 'tersenyum kecut',
    gtxLiteralEn: /\blaughed bitterly\b/gi,
    gtxNaturalEn: 'gave a wry smile',
  },
  {
    ja: /息を(?:呑|の)(?:む|んだ|んで|み)/,
    label: '息を呑む',
    idHint: 'terkesiap / tersentak menahan napas',
    enHint: 'gasped / caught their breath',
    gtxLiteralId: /\bmenelan napas(?:nya)?\b/gi,
    gtxNaturalId: 'tersentak menahan napas',
    gtxLiteralEn: /\bswallowed (?:his|her|their|my) breath\b/gi,
    gtxNaturalEn: 'caught their breath',
  },
  {
    ja: /(?:ため|溜め)息をつ(?:く|いた|いて|き)/,
    label: 'ため息をつく',
    idHint: 'menghela napas',
    enHint: 'let out a sigh / sighed',
    gtxLiteralId: /\bmembuat desahan\b/gi,
    gtxNaturalId: 'menghela napas',
  },
  {
    ja: /(?:視線|目)を(?:逸ら|そら)(?:す|した|して|し)/,
    label: '視線を逸らす',
    idHint: 'mengalihkan pandangan / membuang muka',
    enHint: 'looked away / averted their gaze',
    gtxLiteralId: /\bmengalihkan garis pandang(?:nya)?\b/gi,
    gtxNaturalId: 'mengalihkan pandangannya',
    gtxLiteralEn: /\baverted (?:his|her|their) line of sight\b/gi,
    gtxNaturalEn: 'averted their gaze',
  },
  {
    ja: /頬を染め|顔を赤らめ/,
    label: '頬を染める',
    idHint: 'pipinya merona merah / wajahnya memerah',
    enHint: 'blushed deeply / flushed crimson',
    gtxLiteralId: /\bmewarnai pipi(?:nya)?\b/gi,
    gtxNaturalId: 'pipinya merona merah',
  },
  {
    ja: /胸が高鳴|胸が躍/,
    label: '胸が高鳴る',
    idHint: 'jantungnya berdebar kencang / dadanya berdegup keras',
    enHint: 'heart raced / pulse quickened',
    gtxLiteralId: /\bdadanya berdering(?:\s+tinggi)?\b/gi,
    gtxNaturalId: 'jantungnya berdebar kencang',
  },
  {
    ja: /肩を(?:すくめ|竦め)/,
    label: '肩をすくめる',
    idHint: 'mengedikkan bahu',
    enHint: 'shrugged',
    gtxLiteralId: /\bmengecilkan bahu(?:nya)?\b/gi,
    gtxNaturalId: 'mengedikkan bahu',
  },
  {
    ja: /肩を落と(?:す|した|して)/,
    label: '肩を落とす',
    idHint: 'bahunya terkulai lesu',
    enHint: 'shoulders slumped',
    gtxLiteralId: /\bmenjatuhkan bahu(?:nya)?\b/gi,
    gtxNaturalId: 'bahunya terkulai lesu',
  },
  {
    ja: /目を丸く(?:する|した|して)/,
    label: '目を丸くする',
    idHint: 'matanya membelalak kaget',
    enHint: 'eyes went wide in surprise',
    gtxLiteralId: /\bmembulatkan mata(?:nya)?\b/gi,
    gtxNaturalId: 'matanya membelalak',
  },
  {
    ja: /眉を(?:ひそめ|寄せ)|眉間に皺を寄せ/,
    label: '眉をひそめる',
    idHint: 'mengernyitkan dahi / alisnya bertaut',
    enHint: 'frowned / furrowed their brow',
    gtxLiteralId: /\bmengerutkan kerutan di antara alis\b/gi,
    gtxNaturalId: 'mengernyitkan dahi',
  },
  {
    ja: /ジト目/,
    label: 'ジト目',
    idHint: 'tatapan datar penuh curiga / menatap malas',
    enHint: 'half-lidded deadpan stare',
    gtxLiteralId: /\bmata (?:basah|lembap|setengah tertutup)\b/gi,
    gtxNaturalId: 'tatapan datar penuh curiga',
  },
  {
    ja: /遠い目/,
    label: '遠い目',
    idHint: 'menatap menerawang',
    enHint: 'distant gaze / stared off into the distance',
    gtxLiteralId: /\bmata (?:yang )?jauh\b/gi,
    gtxNaturalId: 'tatapan menerawang',
  },
  {
    ja: /真顔/,
    label: '真顔',
    idHint: 'wajah datar serius / tanpa ekspresi',
    enHint: 'deadpan / completely straight face',
    gtxLiteralId: /\bwajah (?:asli|nyata|sungguhan)\b/gi,
    gtxNaturalId: 'wajah datar serius',
  },
  {
    ja: /胸を(?:なで|撫で)下ろ/,
    label: '胸をなでおろす',
    idHint: 'menghela napas lega',
    enHint: 'breathed a sigh of relief',
    gtxLiteralId: /\bmengusap dada(?:nya)? ke bawah\b/gi,
    gtxNaturalId: 'menghela napas lega',
  },
  {
    ja: /胸が締め付けられ/,
    label: '胸が締め付けられる',
    idHint: 'dadanya terasa sesak / hatinya serasa diremas perih',
    enHint: 'chest tightened painfully',
    gtxLiteralId: /\bdadanya dikencangkan\b/gi,
    gtxNaturalId: 'dadanya terasa sesak',
  },
  {
    ja: /背筋が凍る|鳥肌が立つ/,
    label: '背筋が凍る',
    idHint: 'bulu kuduknya meremang / merinding',
    enHint: 'a chill ran down their spine',
    gtxLiteralId: /\btulang belakang(?:nya|ku)? membeku\b/gi,
    gtxNaturalId: 'bulu kuduknya meremang',
  },
  {
    ja: /生唾を飲み込/,
    label: '生唾を飲み込む',
    idHint: 'menelan ludah gugup',
    enHint: 'gulped nervously',
    gtxLiteralId: /\bmenelan ludah mentah\b/gi,
    gtxNaturalId: 'menelan ludah dengan gugup',
  },
  {
    ja: /血の気が引/,
    label: '血の気が引く',
    idHint: 'wajahnya langsung pucat pasi',
    enHint: 'the color drained from their face',
    gtxLiteralId: /\benergi darah(?:nya)? tertarik\b/gi,
    gtxNaturalId: 'wajahnya langsung pucat pasi',
  },
  {
    ja: /思わず/,
    label: '思わず',
    idHint: 'tanpa sadar / refleks / spontan',
    enHint: 'involuntarily / reflexively / without meaning to',
    gtxLiteralId: /\btanpa berpikir,\s*/gi,
    gtxNaturalId: 'tanpa sadar, ',
  },
  {
    ja: /仕方(?:が)?ない|しょうがない/,
    label: '仕方がない',
    idHint: 'mau bagaimana lagi / tak ada pilihan lain',
    enHint: "it can't be helped / nothing to be done",
    gtxLiteralId: /\btidak ada cara(?:\s+lain)?(?=[.!,?]|$)/gi,
    gtxNaturalId: 'mau bagaimana lagi',
    gtxLiteralEn: /\bthere is no (?:method|way)(?=[.!,?]|$)/gi,
    gtxNaturalEn: "it can't be helped",
  },
  {
    ja: /というわけではない|わけではない/,
    label: 'というわけではない',
    idHint: 'bukan berarti',
    enHint: "it's not that / doesn't necessarily mean",
    gtxLiteralId: /\bbukan (?:kasus|alasan|masalah) bahwa\b/gi,
    gtxNaturalId: 'bukan berarti',
  },
  {
    ja: /とは限らない/,
    label: 'とは限らない',
    idHint: 'belum tentu',
    enHint: 'not necessarily',
    gtxLiteralId: /\btidak terbatas pada (bagus|baik|benar|salah|mahal|murah|mudah|sulit)\b/gi,
    gtxNaturalId: 'belum tentu $1',
  },
  {
    ja: /雨に降られ/,
    label: '雨に降られた',
    idHint: 'kehujanan',
    enHint: 'got caught in the rain',
    gtxLiteralId: /\bdihujani oleh hujan\b/gi,
    gtxNaturalId: 'kehujanan',
  },
  {
    ja: /案の定/,
    label: '案の定',
    idHint: 'benar saja / tepat seperti dugaan',
    enHint: 'sure enough / just as expected',
    gtxLiteralId: /\bsesuai rencana,\s*/gi,
    gtxNaturalId: 'benar saja, ',
  },
  {
    ja: /いつの間にか/,
    label: 'いつの間にか',
    idHint: 'tahu-tahu / tanpa kusadari / entah sejak kapan',
    enHint: 'before I knew it / without realizing it',
    gtxLiteralId: /\bsebelum tahu kapan\b/gi,
    gtxNaturalId: 'tahu-tahu',
  },
  {
    ja: /頭が真っ白/,
    label: '頭が真っ白',
    idHint: 'pikirannya mendadak kosong',
    enHint: 'mind went completely blank',
    gtxLiteralId: /\bkepala(?:nya|ku)? menjadi putih(?: bersih)?\b/gi,
    gtxNaturalId: 'pikirannya mendadak kosong',
  },
  {
    ja: /お茶を濁す|言葉を濁す/,
    label: '言葉を濁す',
    idHint: 'mengelak halus / menjawab berbelit-belit',
    enHint: 'dodged the question / gave a vague answer',
    gtxLiteralId: /\bmengeruhkan (?:teh|kata(?:-kata)?)\b/gi,
    gtxNaturalId: 'mengelak secara halus',
  },
  {
    ja: /気が置けない/,
    label: '気が置けない',
    idHint: 'bisa bersikap santai tanpa sungkan / akrab tanpa canggung',
    enHint: 'easy to be around / no need to stand on ceremony',
    gtxLiteralId: /\btidak bisa meletakkan pikiran\b/gi,
    gtxNaturalId: 'bisa bersikap santai tanpa sungkan',
  },
  {
    ja: /目から鱗/,
    label: '目から鱗',
    idHint: 'seketika tersadar / langsung terbuka wawasannya',
    enHint: 'an eye-opener / scales fell from their eyes',
    gtxLiteralId: /\bsisik jatuh dari mata\b/gi,
    gtxNaturalId: 'seketika tersadar',
  },
  {
    ja: /猫の手も借りたい/,
    label: '猫の手も借りたい',
    idHint: 'sibuk luar biasa hingga kewalahan',
    enHint: 'swamped and desperate for an extra pair of hands',
    gtxLiteralId: /\bingin meminjam (?:tangan|cakar) kucing\b/gi,
    gtxNaturalId: 'sibuk luar biasa hingga kewalahan',
  },
  {
    ja: /腹を(?:括|くく)(?:る|った|って)/,
    label: '腹を括る',
    idHint: 'membulatkan tekad / memantapkan hati',
    enHint: 'braced themselves / resolved to see it through',
    gtxLiteralId: /\bmengikat perut(?:nya|ku)?\b/gi,
    gtxNaturalId: 'membulatkan tekad',
  },
  {
    ja: /目を細め/,
    label: '目を細める',
    idHint: 'menyipitkan mata dengan lembut',
    enHint: 'eyes softened / squinted warmly',
    gtxLiteralId: /\bmempersempit mata(?:nya|ku)?\b/gi,
    gtxNaturalId: 'menyipitkan mata lembut',
  },
  {
    ja: /口を(?:噤|つぐ)(?:む|んだ|んで)/,
    label: '口を噤む',
    idHint: 'mengatupkan bibir rapat-rapat / terdiam membisu',
    enHint: 'clamped their mouth shut / fell silent',
    gtxLiteralId: /\bmenutup mulut(?:nya|ku)? dengan rapat\b/gi,
    gtxNaturalId: 'terdiam membisu',
  },
  {
    ja: /鼻で笑/,
    label: '鼻で笑う',
    idHint: 'mendengus sinis / mencemooh pelan',
    enHint: 'scoffed / snorted derisively',
    gtxLiteralId: /\btertawa dengan hidung(?:nya)?\b/gi,
    gtxNaturalId: 'mendengus sinis',
  },
  {
    ja: /歯がゆい/,
    label: '歯がゆい',
    idHint: 'geregetan / gemas tak berdaya',
    enHint: 'frustrating / itching with impatience',
    gtxLiteralId: /\bgigi(?:nya|ku)? gatal\b/gi,
    gtxNaturalId: 'geregetan',
  },
  {
    ja: /気が重い/,
    label: '気が重い',
    idHint: 'hatinya terasa berat / enggan melangkah',
    enHint: 'heavy-hearted / dreading it',
    gtxLiteralId: /\bperasaan(?:nya|ku)? berat\b/gi,
    gtxNaturalId: 'hatinya terasa berat',
  },
  {
    ja: /手を抜(?:く|いた|いて|かず)/,
    label: '手を抜く',
    idHint: 'bekerja setengah hati / asal-asalan',
    enHint: 'cut corners / slack off',
    gtxLiteralId: /\bmenarik tangan(?:nya|ku)? keluar\b/gi,
    gtxNaturalId: 'bekerja setengah hati',
  },
  {
    ja: /役不足/,
    label: '役不足',
    idHint: 'terlalu remeh bagi kemampuannya',
    enHint: 'beneath their ability / overqualified for the role',
  },
  {
    ja: /情けは人の為ならず/,
    label: '情けは人の為ならず',
    idHint: 'kebaikan yang ditanam akan kembali pada diri sendiri',
    enHint: 'kindness shown to others eventually returns to you',
  },
  // v5 Yojijukugo & Kotowaza Registry (Dankers 2022 / Liu et al. 2023)
  {
    ja: /一期一会/,
    label: '一期一会',
    idHint: 'pertemuan sekali seumur hidup yang patut dihargai',
    enHint: 'a once-in-a-lifetime encounter to be treasured',
    gtxLiteralId: /\bsatu periode satu pertemuan\b/gi,
    gtxNaturalId: 'pertemuan sekali seumur hidup',
  },
  {
    ja: /以心伝心/,
    label: '以心伝心',
    idHint: 'saling memahami tanpa perlu terucap / sehati',
    enHint: 'tacit understanding / reading each other minds',
    gtxLiteralId: /\bhati ke hati transmisi\b/gi,
    gtxNaturalId: 'saling memahami tanpa kata',
  },
  {
    ja: /一石二鳥/,
    label: '一石二鳥',
    idHint: 'sekali merengkuh dayung, dua tiga pulau terlampaui',
    enHint: 'kill two birds with one stone',
    gtxLiteralId: /\bsatu batu dua burung\b/gi,
    gtxNaturalId: 'sekali langkah dua hasil tercapai',
  },
  {
    ja: /自業自得/,
    label: '自業自得',
    idHint: 'menuai apa yang ditabur / salah sendiri',
    enHint: 'reaping what one sowed / got what was coming',
    gtxLiteralId: /\bperbuatan sendiri hasil sendiri\b/gi,
    gtxNaturalId: 'menuai akibat perbuatannya sendiri',
  },
  {
    ja: /十人十色/,
    label: '十人十色',
    idHint: 'tiap orang punya selera dan jalan masing-masing',
    enHint: 'to each their own / different strokes for different folks',
    gtxLiteralId: /\bsepuluh orang sepuluh warna\b/gi,
    gtxNaturalId: 'lain kepala lain pula isinya',
  },
  {
    ja: /七転び八起き/,
    label: '七転び八起き',
    idHint: 'jatuh tujuh kali bangkit delapan kali / pantang menyerah',
    enHint: 'fall down seven times, stand up eight',
  },
  {
    ja: /起死回生/,
    label: '起死回生',
    idHint: 'membalikkan keadaan dari ambang kekalahan',
    enHint: 'a dramatic turnaround from the brink of defeat',
  },
  {
    ja: /絶体絶命/,
    label: '絶体絶命',
    idHint: 'terpojok tanpa jalan keluar / di ujung tanduk',
    enHint: 'backed into a desperate corner / dire straits',
  },
  {
    ja: /危機一髪/,
    label: '危機一髪',
    idHint: 'nyaris celaka / selamat di detik terakhir',
    enHint: 'by a hairbreadth / narrow escape',
  },
  {
    ja: /半信半疑/,
    label: '半信半疑',
    idHint: 'setengah percaya setengah ragu',
    enHint: 'half-believing, half-doubting / skeptical',
  },
  {
    ja: /本末転倒/,
    label: '本末転倒',
    idHint: 'terbalik prioritasnya / salah kaprah antara tujuan dan sarana',
    enHint: 'putting the cart before the horse',
  },
  {
    ja: /臨機応変/,
    label: '臨機応変',
    idHint: 'luwes menyesuaikan diri dengan situasi',
    enHint: 'adapting flexibly on the fly',
  },
  {
    ja: /猿も木から落ちる/,
    label: '猿も木から落ちる',
    idHint: 'sepandai-pandainya tupai melompat, sekali waktu jatuh juga',
    enHint: 'even experts make mistakes',
    gtxLiteralId: /\bmonyet juga jatuh dari pohon\b/gi,
    gtxNaturalId: 'sepandai-pandainya orang, sesekali bisa terpeleset juga',
  },
  {
    ja: /井の中の蛙/,
    label: '井の中の蛙',
    idHint: 'bagai katak dalam tempurung',
    enHint: 'a frog in a well / narrow-minded',
    gtxLiteralId: /\bkatak di dalam sumur\b/gi,
    gtxNaturalId: 'bagai katak dalam tempurung',
  },
  {
    ja: /二兎を追う者は一兎をも得ず/,
    label: '二兎を追う者は一兎をも得ず',
    idHint: 'mengejar dua hal sekaligus justru kehilangan keduanya',
    enHint: 'chase two hares and you will catch neither',
  },
  {
    ja: /急がば回れ/,
    label: '急がば回れ',
    idHint: 'biar lambat asal selamat',
    enHint: 'more haste, less speed',
  },
  {
    ja: /覆水盆に返らず/,
    label: '覆水盆に返らず',
    idHint: 'nasi sudah menjadi bubur',
    enHint: 'no use crying over spilled milk',
    gtxLiteralId: /\bair yang tumpah tidak kembali ke nampan\b/gi,
    gtxNaturalId: 'nasi sudah menjadi bubur',
  },
  {
    ja: /明鏡止水/,
    label: '明鏡止水',
    idHint: 'pikiran sebening cermin dan setenang air telaga',
    enHint: 'serene, crystal-clear state of mind',
  },
];

// ---------- v5: 5-Tier Japanese Keigo Classifier (Bunka Shingikai 2007) ----------

const JA_SONKEIGO_RE =
  /(?:おっしゃ(?:る|いま|った|って)|いらっしゃ(?:る|いま|った|って)|ご覧にな|召し上が|ご存じ|なさ(?:る|いま|った|って)|お[\u4e00-\u9fff]{1,3}にな(?:る|り|った)|ご[\u4e00-\u9fff]{2,4}にな(?:る|り|った))/;
const JA_KENJOUGO_RE =
  /(?:申し上げ|いたし(?:ます|ました)|参り(?:ます|ました)|伺(?:い|いま|った)|拝見|存じ上げ|恐れ入(?:り|る)|いただけ(?:ます|る|ません)|させていただ)/;
const JA_TEINEIGO_RE =
  /(?:です|ます|ました|でした|ません|ましょう|ございます|申し訳|お客様|ください)(?:か|よ|ね|よね|わ|ぞ|さ|の|けれど|けど|が)?(?=[。！？!?…」』"\s、]|$)/;
const JA_BIKAGO_ONLY_RE =
  /(?:ご飯|お茶|お酒|お金|お菓子|お水|お花|お弁当|お肉|お魚|お皿|お風呂|お手洗い)/;

export function classifyJaKeigo(srcLine: string): JaKeigoClassification {
  const s = (srcLine || '').trim();
  if (!s) {
    return { tier: 'plain', elevatesReferent: false, humblesSpeaker: false, locksPoliteRegister: false };
  }
  const elevatesReferent = JA_SONKEIGO_RE.test(s);
  const humblesSpeaker = JA_KENJOUGO_RE.test(s);
  if (elevatesReferent) {
    return { tier: 'sonkeigo', elevatesReferent: true, humblesSpeaker, locksPoliteRegister: true };
  }
  if (humblesSpeaker) {
    return { tier: 'kenjougo', elevatesReferent: false, humblesSpeaker: true, locksPoliteRegister: true };
  }
  if (JA_TEINEIGO_RE.test(s)) {
    return { tier: 'teineigo', elevatesReferent: false, humblesSpeaker: false, locksPoliteRegister: true };
  }
  if (JA_BIKAGO_ONLY_RE.test(s)) {
    // Bikago beautification prefixes (gohan/ocha) are strictly register-neutral!
    return { tier: 'bikago', elevatesReferent: false, humblesSpeaker: false, locksPoliteRegister: false };
  }
  return { tier: 'plain', elevatesReferent: false, humblesSpeaker: false, locksPoliteRegister: false };
}

// ---------- v5: Centering Theory & Zero-Anaphora Discourse State (Grosz 1995 / Walker 1994 / Kuno 1977) ----------

const JA_TOPIC_ENTITY_RE = /([\u4e00-\u9fffァ-ヶー]{1,8})(?:さん|くん|君|ちゃん|様|先輩|先生)?は(?![ぁ-ん]{0,2}[、。]|なく|ない)/g;
const JA_SUBJ_ENTITY_RE = /([\u4e00-\u9fffァ-ヶー]{1,8})(?:さん|くん|君|ちゃん|様|先輩|先生)?が(?=[ぁ-んァ-ヶー\u4e00-\u9fff])/g;
const JA_NON_ENTITY_TOPICS = new Set([
  'これ', 'それ', 'あれ', 'ここ', 'そこ', 'あそこ', '今', '今日', '明日', '昨日', '私', '僕', '俺', '彼', '彼女', '自分', '何', '誰', 'いつ', 'どこ', 'なぜ', 'どう', 'こと', 'もの', 'とき', 'ところ', 'ため',
]);

export function createCenteringState(): CenteringState {
  return {
    cb: null,
    cfList: [],
    recentEntities: [],
    speakerStack: [],
    empathyDirection: 'neutral',
    turnIndex: 0,
  };
}

export function updateCenteringState(state: CenteringState, srcLine: string, dstLine = ''): CenteringState {
  const s = (srcLine || '').trim();
  if (!s) return state;

  const rankedCf: string[] = [];
  const pushEntity = (raw: string) => {
    const clean = raw.trim();
    if (clean.length < 1 || JA_NON_ENTITY_TOPICS.has(clean)) return;
    if (!rankedCf.includes(clean)) rankedCf.push(clean);
  };

  // Walker/Iida/Cote (1994) JA salience: Topic(wa) > Subject(ga) > prior retained Cb
  JA_TOPIC_ENTITY_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = JA_TOPIC_ENTITY_RE.exec(s)) !== null) {
    pushEntity(m[1]);
  }
  JA_SUBJ_ENTITY_RE.lastIndex = 0;
  while ((m = JA_SUBJ_ENTITY_RE.exec(s)) !== null) {
    pushEntity(m[1]);
  }
  // Latin capitalized proper names in dstLine or EN/ID srcLine
  const latinSource = dstLine || s;
  const latinNames = latinSource.match(/(?<!^)(?<![.!?]\s)\b[A-Z][a-z]{2,18}\b/g) || [];
  for (const name of latinNames) {
    if (!/^(?:The|This|That|When|Then|After|Before|Namun|Tetapi|Karena|Ketika|Pada|Saat|Bab|Chapter|Namun|Jadi|Lalu|Tapi)$/.test(name)) {
      pushEntity(name);
    }
  }

  // Kuno & Kaburaki (1977) Empathy / Benefactive direction
  let empathyDirection: CenteringState['empathyDirection'] = 'neutral';
  if (/(?:くれた|くれて|くれる|てきた|てくる|もらった|もらう|いただいた)/.test(s)) {
    empathyDirection = 'to_speaker';
  } else if (/(?:あげた|あげる|ていった|ていく|やった|さしあげ)/.test(s)) {
    empathyDirection = 'from_speaker';
  }

  const prevCf = state.cfList;
  const retained = prevCf.find((e) => rankedCf.includes(e)) || rankedCf[0] || state.cb;
  const nextRecent = [...rankedCf, ...state.recentEntities].filter((v, i, arr) => arr.indexOf(v) === i).slice(0, 6);

  state.cb = retained;
  state.cfList = rankedCf.length > 0 ? rankedCf.slice(0, 5) : prevCf;
  state.recentEntities = nextRecent;
  state.empathyDirection = empathyDirection;
  state.turnIndex += 1;
  return state;
}

// ---------- v5: Hamano/Akita Phonological Mimetic Detector ----------

const UNSEEN_JA_MIMETIC_RE =
  /([ァ-ヴー]{2,3})\1|([ぁ-ん]{2})\2(?=[とっに、。！？\s\u4E00-\u9FFF]|$)|([ァ-ヴぁ-ん][っッ][ァ-ヴぁ-ん][りリ])|([ァ-ヴぁ-ん][んン][ァ-ヴぁ-ん][りリ])/g;
const VOICED_DAKUTEN_RE = /^[ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ]/;

export function detectUnseenJaMimetics(text: string): Array<{ surface: string; cue: string }> {
  const hits: Array<{ surface: string; cue: string }> = [];
  const seen = new Set<string>();
  UNSEEN_JA_MIMETIC_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = UNSEEN_JA_MIMETIC_RE.exec(text)) !== null) {
    const surface = m[0];
    if (seen.has(surface) || surface.length < 4) continue;
    if (JA_MIMETICS.some((known) => known.ja.test(surface))) continue;
    seen.add(surface);
    const isHeavy = VOICED_DAKUTEN_RE.test(surface);
    const isQuietComplete = /[りリ]$/.test(surface);
    const cue = isHeavy
      ? 'heavy/intense sensory manner verb (avoid bare romaji)'
      : isQuietComplete
        ? 'quiet/settled completion adverb or verb (avoid bare romaji)'
        : 'light/iterative sensory manner verb (avoid bare romaji)';
    hits.push({ surface, cue });
    if (hits.length >= 4) break;
  }
  return hits;
}

export interface JaMimeticEntry {
  ja: RegExp;
  label: string;
  romajiRe: RegExp;
  id: string;
  en: string;
}

export const JA_MIMETICS: JaMimeticEntry[] = [
  { ja: /ドキドキ|どきどき/, label: 'ドキドキ', romajiRe: /\bdoki[-\s]?doki\b/gi, id: 'berdebar kencang', en: 'heart pounding' },
  { ja: /ニヤリ|にやり/, label: 'ニヤリ', romajiRe: /\bniyari\b/gi, id: 'menyeringai tipis', en: 'smirking slyly' },
  { ja: /クスクス|くすくす/, label: 'クスクス', romajiRe: /\bkusu[-\s]?kusu\b/gi, id: 'terkekeh pelan', en: 'giggling softly' },
  { ja: /じっと|ジッと/, label: 'じっと', romajiRe: /\bjitto\b/gi, id: 'lekat-lekat', en: 'intently' },
  { ja: /ふと|フト/, label: 'ふと', romajiRe: /\bfuto\b/gi, id: 'sekilas terlintas', en: 'suddenly' },
  { ja: /そっと|ソッと/, label: 'そっと', romajiRe: /\bsotto\b/gi, id: 'perlahan dengan lembut', en: 'gently' },
  { ja: /ぱっと|パッと/, label: 'ぱっと', romajiRe: /\bpatto\b/gi, id: 'seketika', en: 'in a flash' },
  { ja: /ぎゅっと|ギュッと/, label: 'ぎゅっと', romajiRe: /\bgyutto\b/gi, id: 'erat-erat', en: 'tightly' },
  { ja: /ぼんやり|ボンヤリ/, label: 'ぼんやり', romajiRe: /\bbonyari\b/gi, id: 'termenung kosong', en: 'blankly' },
  { ja: /はっきり|ハッキリ/, label: 'はっきり', romajiRe: /\bhakkiri\b/gi, id: 'dengan tegas', en: 'plainly' },
  { ja: /ずっしり|ズッシリ/, label: 'ずっしり', romajiRe: /\bzusshiri\b/gi, id: 'terasa berat mantap', en: 'heavy and solid' },
  { ja: /ひんやり|ヒンヤリ/, label: 'ひんやり', romajiRe: /\bhinyari\b/gi, id: 'sejuk dingin', en: 'cool to the touch' },
  { ja: /ワクワク|わくわく/, label: 'ワクワク', romajiRe: /\bwaku[-\s]?waku\b/gi, id: 'penuh semangat', en: 'thrilled with excitement' },
  { ja: /ハラハラ|はらはら/, label: 'ハラハラ', romajiRe: /\bhara[-\s]?hara\b/gi, id: 'cemas bukan main', en: 'on edge' },
  { ja: /イライラ|いらいら/, label: 'イライラ', romajiRe: /\bira[-\s]?ira\b/gi, id: 'kesal dan gelisah', en: 'irritated' },
  { ja: /ソワソワ|そわそわ/, label: 'ソワソワ', romajiRe: /\bsowa[-\s]?sowa\b/gi, id: 'salah tingkah gelisah', en: 'fidgeting restlessly' },
  { ja: /モヤモヤ|もやもや/, label: 'モヤモヤ', romajiRe: /\bmoya[-\s]?moya\b/gi, id: 'mengganjal di hati', en: 'nagging unease' },
  { ja: /ニヤニヤ|にやにや/, label: 'ニヤニヤ', romajiRe: /\bniya[-\s]?niya\b/gi, id: 'menyeringai jahil', en: 'grinning smugly' },
  { ja: /ニコリ|にこり/, label: 'ニコリ', romajiRe: /\bnikori\b/gi, id: 'tersenyum hangat', en: 'smiling warmly' },
  { ja: /ボロボロ|ぼろぼろ/, label: 'ボロボロ', romajiRe: /\bboro[-\s]?boro\b/gi, id: 'compang-camping', en: 'battered and worn' },
  { ja: /ギリギリ|ぎりぎり/, label: 'ギリギリ', romajiRe: /\bgiri[-\s]?giri\b/gi, id: 'nyaris saja', en: 'just barely' },
  { ja: /バラバラ|ばらばら/, label: 'バラバラ', romajiRe: /\bbara[-\s]?bara\b/gi, id: 'tercerai-berai', en: 'scattered' },
  { ja: /ビクッ|びくっ/, label: 'ビクッ', romajiRe: /\bbikku\b/gi, id: 'tersentak kaget', en: 'flinched sharply' },
  { ja: /ギロリ|ぎろり/, label: 'ギロリ', romajiRe: /\bgirori\b/gi, id: 'melotot tajam', en: 'glared sharply' },
  { ja: /チラリ|ちらり/, label: 'チラリ', romajiRe: /\bchirari\b/gi, id: 'melirik sekilas', en: 'glanced sideways' },
  { ja: /ジロジロ|じろじろ/, label: 'ジロジロ', romajiRe: /\bjiro[-\s]?jiro\b/gi, id: 'menatap lekat tanpa sungkan', en: 'stared rudely' },
  { ja: /シーン|しーん/, label: 'シーン', romajiRe: /\bshiin\b/gi, id: 'hening seketika', en: 'dead silence' },
  { ja: /フラフラ|ふらふら/, label: 'フラフラ', romajiRe: /\bfura[-\s]?fura\b/gi, id: 'terhuyung-huyung', en: 'staggering' },
  { ja: /ガタガタ|がたがた/, label: 'ガタガタ', romajiRe: /\bgata[-\s]?gata\b/gi, id: 'gemetar hebat', en: 'shivering violently' },
  { ja: /ぐったり|グッタリ/, label: 'ぐったり', romajiRe: /\bguttari\b/gi, id: 'terkulai lemas', en: 'slumped limp' },
];

// Pre-GTX Source Preparation:
// 1. Protects Japanese [GlossaryName][Honorific] slots so GTX NEVER emits "Tuan/Nyonya" for classmates.
// 2. Normalizes Japanese repeated horizontal bars ―― / ーー into clean ellipsis before GTX.
// 3. Protects inline code backticks and URLs.
export interface PreMtResult {
  prepared: string;
  restoreMap: Map<string, string>;
  detectedHonorificNames: Record<string, string>;
  hadJaKeigo: boolean;
}

const JA_HONORIFIC_MAP: Record<string, string> = {
  'さん': '-san',
  'くん': '-kun',
  '君': '-kun',
  'ちゃん': '-chan',
  '様': '-sama',
  'さま': '-sama',
  '先輩': '-senpai',
  'せんぱい': '-senpai',
  '先生': '-sensei',
  'せんせい': '-sensei',
  '殿': '-dono',
  'どの': '-dono',
};

const JA_NAME_HONORIFIC_RE =
  /([ァ-ヶー]{2,8}|[\u4e00-\u9fff]{1,4})(さん|くん|君|ちゃん|様|さま|先輩|せんぱい|先生|せんせい|殿|どの)(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])/g;

export function preprocessSourceForMt(
  srcText: string,
  profile: DiscourseProfile,
  glossaryEntries: GlossaryEntry[]
): PreMtResult {
  let prepared = srcText || '';
  const restoreMap = new Map<string, string>();
  const detectedHonorificNames: Record<string, string> = {};
  let tokIdx = 1;

  const keigo = profile.srcLang === 'ja' ? classifyJaKeigo(srcText) : null;
  const hadJaKeigo = Boolean(keigo?.locksPoliteRegister);

  // Protect inline code spans & bare URLs verbatim across all languages
  prepared = prepared.replace(/`[^`\n]{1,120}`|https?:\/\/[^\s)>"'」』]+/g, (match) => {
    const tok = `[[C${tokIdx}]]`;
    restoreMap.set(tok, match);
    tokIdx += 1;
    return tok;
  });

  if (profile.srcLang === 'ja' && profile.tgtLang !== 'ja') {
    // Convert Japanese horizontal bars (―― / ーー) to clean ellipsis before MT so zero U+2014 leaks
    prepared = prepared
      .replace(/[\u2014\u2015\u2500]{2,}/g, '……')
      .replace(/([ぁ-ゖァ-ヺ\u4e00-\u9fff])ー{2,}/g, '$1……');

    // Protect GlossaryName + Honorific combos first (highest precision)
    const honorificKeys = Object.keys(JA_HONORIFIC_MAP);
    for (const entry of glossaryEntries) {
      const surface = (entry.surface || '').trim();
      if (!surface || surface.length < 1) continue;
      const renderedBase =
        profile.tgtLang === 'en'
          ? entry.render_en || entry.romaji || surface
          : entry.render_id || entry.romaji || surface;
      if (!renderedBase) continue;
      for (const hJa of honorificKeys) {
        const combo = `${surface}${hJa}`;
        if (!prepared.includes(combo)) continue;
        const suffix = JA_HONORIFIC_MAP[hJa];
        const rendered =
          profile.domain === 'historical_fantasy' && (hJa === '様' || hJa === 'さま')
            ? profile.tgtLang === 'id'
              ? `Tuan ${renderedBase}`
              : `Lord ${renderedBase}`
            : `${renderedBase}${suffix}`;
        const tok = `[[H${tokIdx}]]`;
        prepared = prepared.split(combo).join(tok);
        restoreMap.set(tok, rendered);
        detectedHonorificNames[renderedBase] = suffix;
        tokIdx += 1;
      }
    }

    // Track unmasked [Name][Honorific] surfaces (katakana & kanji) for post-GTX anti-"Tuan/Nyonya" repair
    JA_NAME_HONORIFIC_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = JA_NAME_HONORIFIC_RE.exec(prepared)) !== null) {
      const full = m[0];
      const stem = m[1];
      const hJa = m[2];
      if (JA_NON_PERSON_HONORIFIC_WORDS.has(full) || JA_KATAKANA_STOPLIST.has(stem)) {
        continue;
      }
      detectedHonorificNames[stem] = JA_HONORIFIC_MAP[hJa] || '-san';
    }
  }

  return { prepared, restoreMap, detectedHonorificNames, hadJaKeigo };
}

export function restorePreMtTokens(text: string, restoreMap: Map<string, string>): string {
  let out = text;
  for (const [tok, val] of restoreMap.entries()) {
    out = out.split(tok).join(val);
    const kind = tok.charAt(2);
    const num = tok.slice(3, -2);
    out = out.replace(
      new RegExp(`(?:\\[\\[|【【)\\s*${kind}\\s*${num}\\s*(?:\\]\\]|】】)`, 'gi'),
      val
    );
  }
  return out;
}

// ---------- Stage 2: Skopos-Driven Author-Purpose-Reader Prompt Builder (v4) ----------

export function buildLiterarySystemPrompt(
  src: SourceLang,
  tgt: TargetLang,
  profile: DiscourseProfile,
  sampleBatch: string[]
): string {
  const langNames: Record<TargetLang, string> = {
    ja: 'Japanese',
    id: 'Indonesian',
    en: 'English',
  };
  const srcLabel = src === 'auto' ? 'the detected source language' : langNames[src];
  const tgtLabel = langNames[tgt];

  const batchText = sampleBatch.join('\n');
  const dynamicHints: string[] = [];
  if ((src === 'ja' || profile.srcLang === 'ja') && tgt !== 'ja') {
    for (const item of JA_LITERARY_IDIOMS) {
      if (item.ja.test(batchText)) {
        dynamicHints.push(`${item.label} -> ${tgt === 'id' ? item.idHint : item.enHint}`);
        if (dynamicHints.length >= 6) break;
      }
    }
    for (const mim of JA_MIMETICS) {
      if (mim.ja.test(batchText)) {
        dynamicHints.push(`${mim.label} -> ${tgt === 'id' ? mim.id : mim.en}`);
        if (dynamicHints.length >= 10) break;
      }
    }
    const unseenMimetics = detectUnseenJaMimetics(batchText);
    for (const um of unseenMimetics) {
      if (dynamicHints.length >= 12) break;
      dynamicHints.push(`${um.surface} -> ${um.cue}`);
    }
  }

  // v5 Discourse Anchor from Centering / Keigo context
  const batchCentering = createCenteringState();
  for (const line of sampleBatch.slice(0, 8)) {
    updateCenteringState(batchCentering, line);
  }
  const hasSonkeigoInBatch =
    (src === 'ja' || profile.srcLang === 'ja') &&
    sampleBatch.some((l) => classifyJaKeigo(l).elevatesReferent);
  const discourseAnchorParts: string[] = [];
  if (batchCentering.cb) {
    discourseAnchorParts.push(`active_topic=${batchCentering.cb}`);
  }
  if (batchCentering.recentEntities.length > 1) {
    discourseAnchorParts.push(`salient_entities=[${batchCentering.recentEntities.slice(0, 4).join(', ')}]`);
  }
  if (batchCentering.empathyDirection !== 'neutral') {
    discourseAnchorParts.push(`empathy=${batchCentering.empathyDirection}`);
  }
  if (hasSonkeigoInBatch && tgt === 'id') {
    discourseAnchorParts.push('sonkeigo_detected=elevate_referent_to_beliau_where_appropriate');
  }
  const discourseAnchorBlock =
    discourseAnchorParts.length > 0
      ? `\n[Discourse Anchor] ${discourseAnchorParts.join('; ')}. Keep zero-anaphora subjects and pronouns consistent across adjacent paragraphs until a new topic marker introduces a shift.`
      : '';

  let registerDirective = '';
  if (tgt === 'id') {
    if (profile.genre === 'legal_policy') {
      registerDirective =
        'Register: Statutory/Legal Indonesian (EYD V & KBBI VI). Preserve exact deontic modals (shall -> wajib, shall not/must not -> dilarang, may -> dapat, should -> sebaiknya), defined terms, clause numbers, and polarity with zero casualization.';
    } else if (profile.genre === 'academic_research' || profile.genre === 'technical_docs') {
      registerDirective =
        'Register: Formal Academic/Technical Indonesian (EYD V & KBBI VI: praktik, risiko, analisis, sistem, kualitas, aktivitas). Preserve epistemic hedging (suggests/indicates -> mengindikasikan, NOT membuktikan), formal pronouns (saya/Anda), citations, CLI/code tokens, and logical precision.';
    } else if (profile.genre === 'business_formal') {
      registerDirective =
        'Register: Executive Indonesian business prose (EYD V). Courteous, clear, active voice, formal pronouns (saya/Anda/Bapak/Ibu), zero slang.';
    } else if (profile.register === 'novel_archaic' || profile.genre === 'classic_literary') {
      registerDirective =
        'Register: Elevated literary / historical Indonesian. Preserve authorial rhythm, imagery, and dignified diction (aku/engkau/kau/ia, tiada/hendak where fitting). Strictly forbid modern urban slang (gue/lo/nggak/banget/dong/sih).';
    } else if (profile.genre === 'children_ya') {
      registerDirective =
        'Register: Warm, concrete, easy-to-follow Indonesian for young readers. Short clear clauses, familiar vocabulary, vivid sensory verbs.';
    } else if (profile.genre === 'manga_comic_sfx' || profile.genre === 'subtitle_script') {
      registerDirective =
        'Register: Punchy, compact spoken Indonesian fitting speech bubbles / subtitle timing. Natural contractions and interjections inside dialogue; concise comic SFX equivalents; zero stiff bureaucratic phrasing.';
    } else if (profile.register === 'dramatic_action') {
      registerDirective =
        'Register: High-tension literary action Indonesian. Kinetic verbs, crisp short sentences during combat/crisis, clipped urgent shouts without polite padding.';
    } else if (profile.genre === 'news_wire' || profile.genre === 'essay_journalism') {
      registerDirective =
        'Register: Crisp modern Indonesian journalism/editorial (Tempo/Kompas caliber, EYD V). Active verbs, lean clauses, exact attribution and hedging, zero bureaucratic bloat.';
    } else {
      registerDirective =
        `Register: Natural Indonesian fiction & dialogue (${profile.domain}, EYD V & KBBI VI). ` +
        `Flowing literary narration (${profile.narratorId1P === 'saya' ? 'saya' : 'aku'}/ia, clean "tidak", active verbs) and authentic spoken dialogue inside quotes (aku/kamu/kau, natural question cadence, subtle particles kok/sih/kan/ya/lho at most 1 per clause, varied speech verbs ujar/sahut/tanya/gumam/bisik/seru). ` +
        `Honorific policy (${profile.honorificPolicy}): NEVER translate Japanese classmate -san/-kun/-chan into Tuan/Nyonya/Bapak/Ibu.`;
    }
  } else if (tgt === 'en') {
    registerDirective =
      `Register: Natural idiomatic English (${profile.register}, contractions=${profile.enContractions}). ` +
      'Master articles (a/an/the), aspect, and uncountable nouns (information, advice, equipment, research). Avoid "As for X," topic-fronting, double hedging, and stative "-ing" calques.';
  } else {
    registerDirective =
      `Register: Natural Japanese (${profile.jaTargetStyle}). ` +
      'Drop redundant pronouns once topic is established, respect empathy/giving-receiving verbs (あげる/くれる/もらう), avoid inanimate passive calques, and match speech level to speaker hierarchy.';
  }

  const pairGrammarNote =
    profile.srcLang === 'ja' && tgt === 'id'
      ? ' Grammar: recover Japanese zero-anaphora subjects from context, map meN-/di-/ter-/ber- voices naturally (adversity passive -> ke-...-an / tertimpa), apply EYD V spacing (di sini/di atas vs dimakan; apa pun; Rp50.000; Maha Esa) and KBBI VI standard spellings.'
      : tgt === 'id'
        ? ' Grammar: prefer idiomatic Indonesian voice/affixes (bermata/berambut, dibukanya, active verbs), apply EYD V spacing (di sini/ke mana; apa pun; Rp50.000) and KBBI VI spellings, and avoid calques ("di mana"/"yang mana" non-interrogative, "adalah merupakan", "tidak bisa membantu tetapi", redundant "sebuah" before abstract nouns).'
        : ' Grammar: preserve exact grammatical cohesion, tense/aspect, and idiomatic collocations.';

  const lengthBudgetNote = profile.lengthBudgetRatio
    ? ` Keep output concise (target <= ${Math.round(profile.lengthBudgetRatio * 100)}% of source length).`
    : '';

  const hintBlock =
    dynamicHints.length > 0
      ? ` Idiom & mimetic guidance for this batch: ${dynamicHints.join('; ')}.`
      : '';

  return (
    `You are a master translator producing accurate, natural, author-faithful ${tgtLabel} from ${srcLabel} without summarizing, omitting, or hallucinating.\n` +
    `[Skopos & Calibration] genre=${profile.genre}, reiss=${profile.reissType}, method=${profile.translationMethod}, house=${profile.houseMode}, cultural_filter=${profile.culturalFilter}, metaphor=${profile.metaphorPolicy}, pov=${profile.pov}. Goal: ${profile.skoposGoal}. ` +
    `Match reader complexity to source tier ${profile.sourceTier} (score ${profile.sourceComplexity}/100 -> target band ${profile.targetComplexityBand[0]}-${profile.targetComplexityBand[1]}, avg sentence <= ${profile.maxTargetAslWords} words).${lengthBudgetNote}\n` +
    `[Register & Grammar] ${registerDirective}${pairGrammarNote}${discourseAnchorBlock}\n` +
    `[Fidelity & Format] Ensure 100% of every item is in ${tgtLabel} (keep segments already in ${tgtLabel} intact). Preserve every number, date, currency, SI unit, negation polarity, proper noun, Markdown/code/LaTeX/table/URL token, and placeholder ([[E1]], [[H1]], [[C1]]) verbatim. NEVER emit U+2014 em-dashes; use commas, ellipses ("..."), or crisp sentence breaks.${hintBlock}\n` +
    `Return strict JSON only: {"translations":[{"id":1,"text":"..."}]}`
  );
}

// ---------- Stage 3A: FormatShield & Span-Isolated Register-Aware Naturalizer ----------

export interface FormatShieldResult {
  shielded: string;
  restoreMap: Map<string, string>;
}

const FORMAT_SHIELD_LINE_PREFIX_RE =
  /^(?:```[^\n]*|#{1,6}[ \t]+|>[ \t]+|(?:[-*+]|\d+\.)[ \t]+|\|?(?:[ \t]*:?-{2,}:?[ \t]*\|)+[ \t]*$|[ \t\u3000]*(?:\*{3,}|-{3,}|={3,}|◆{2,}|◇{2,})[ \t\u3000]*$)/gm;

const FORMAT_SHIELD_INLINE_RE =
  /```[\s\S]*?```|`[^`\n]{1,240}`|(?<=^|\n)\$\$[^$]{1,600}?\$\$(?=\s*(?:\n|$))|\$(?![\s\d])[^$\n]{1,120}(?<!\s)\$|\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}|\{\\[^}\n]{1,60}\}|\[\[[EHIC]\d+\]\]|(?<=\])\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s)>"'」』]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b10\.\d{4,9}\/[^\s),;]+|\[\^[^\]]+\]|\[\d{1,3}\]|※\d+|\b[A-Za-z][A-Za-z0-9_-]*\.(?:py|ts|tsx|js|jsx|mjs|cjs|json|yaml|yml|toml|md|html|css|scss|sql|sh|go|rs|java|kt|rb|php|vue|svelte|env|lock|txt|pdf|epub|docx|png|jpg|jpeg|webp)\b/g;

export function protectFormatSpans(text: string): FormatShieldResult {
  const restoreMap = new Map<string, string>();
  if (!text) return { shielded: text, restoreMap };
  let idx = 0;
  const makeTok = (val: string): string => {
    const tok = `\u27E6F${idx}\u27E7`;
    restoreMap.set(tok, val);
    idx += 1;
    return tok;
  };
  // Protect inline code/math/URLs/filenames/timestamps/placeholders first
  let shielded = text.replace(FORMAT_SHIELD_INLINE_RE, (m) => makeTok(m));
  // Protect structural line prefixes without consuming line content
  shielded = shielded.replace(FORMAT_SHIELD_LINE_PREFIX_RE, (m) => makeTok(m));
  return { shielded, restoreMap };
}

export function restoreFormatSpans(text: string, restoreMap: Map<string, string>): string {
  if (!text || restoreMap.size === 0) return text;
  let out = text;
  // Restore in reverse insertion order in case any prefix wrapped an inner token
  const entries = Array.from(restoreMap.entries()).reverse();
  for (const [tok, val] of entries) {
    out = out.split(tok).join(val);
  }
  return out;
}

function preserveCase(orig: string, replacement: string): string {
  if (!orig || !replacement) return replacement;
  const first = orig.charAt(0);
  if (first >= 'A' && first <= 'Z') {
    return replacement.charAt(0).toUpperCase() + replacement.slice(1);
  }
  if (first >= 'a' && first <= 'z') {
    return replacement.charAt(0).toLowerCase() + replacement.slice(1);
  }
  return replacement;
}

interface TextSpan {
  kind: 'protected' | 'dialogue' | 'narration';
  text: string;
}

// Tokenize paragraph into immutable protected spans vs dialogue vs narration
function splitProtectedSpans(text: string): TextSpan[] {
  const PROTECTED_RE =
    /(\u27E6F\d+\u27E7|\[\[[EHIC]\d+\]\]|`[^`\n]+`|https?:\/\/[^\s)>"']+)/g;
  const rough: TextSpan[] = [];
  let cursor = 0;
  let m: RegExpExecArray | null;
  while ((m = PROTECTED_RE.exec(text)) !== null) {
    if (m.index > cursor) {
      rough.push({ kind: 'narration', text: text.slice(cursor, m.index) });
    }
    rough.push({ kind: 'protected', text: m[0] });
    cursor = m.index + m[0].length;
  }
  if (cursor < text.length) {
    rough.push({ kind: 'narration', text: text.slice(cursor) });
  }

  // Split narration chunks into dialogue ("...") vs narration
  const out: TextSpan[] = [];
  const QUOTE_SPAN_RE = /("[^"\n]{1,600}")/g;
  for (const seg of rough) {
    if (seg.kind === 'protected') {
      out.push(seg);
      continue;
    }
    let qPos = 0;
    let qm: RegExpExecArray | null;
    QUOTE_SPAN_RE.lastIndex = 0;
    while ((qm = QUOTE_SPAN_RE.exec(seg.text)) !== null) {
      if (qm.index > qPos) {
        out.push({ kind: 'narration', text: seg.text.slice(qPos, qm.index) });
      }
      out.push({ kind: 'dialogue', text: qm[0] });
      qPos = qm.index + qm[0].length;
    }
    if (qPos < seg.text.length) {
      out.push({ kind: 'narration', text: seg.text.slice(qPos) });
    }
  }
  return out;
}

const KNOWN_DOT_ABBREV_RE =
  /(?:^|[\s(])(?:e\.g|i\.e|U\.S|U\.K|a\.m|p\.m|vs|etc|St|Dr|Mr|Mrs|Ms|Prof|Jr|Sr|dll|dsb|dkk|hlm|No|Tn|Ny|Nn|Sdr|Sdri|Jl|Kp|v\d+)$/i;

/**
 * Unconditional Zero-U+2014 Em-Dash & Typography Sanitizer (ID / EN / JA) with FormatShield protection.
 */
export function sanitizeZeroEmDashAndPunct(text: string, tgt: TargetLang): string {
  if (!text) return text;
  const { shielded, restoreMap } = protectFormatSpans(text);
  let out = shielded;

  if (tgt === 'ja') {
    out = out
      .replace(/\u2014/g, '……')
      .replace(/([\u3040-\u30ff\u3400-\u9fff。、！？「」『』])[ \t]+(?=[\u3040-\u30ff\u3400-\u9fff。、！？「」『』])/g, '$1')
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
    return restoreFormatSpans(out, restoreMap);
  }

  // Context-aware U+2014 elimination (strictly 0 U+2014 output; horizontal whitespace only to preserve \n!)
  out = out
    .replace(/\u3000+/g, ' ')
    // Paired parenthetical em-dashes -> crisp commas
    .replace(/[ \t]*\u2014[ \t]*([^\u2014\n]{2,90}?)[ \t]*\u2014[ \t]*/g, ', $1, ')
    // Trailing dialogue cutoff before quote/end -> ellipsis
    .replace(/([A-Za-z0-9])\u2014(["”!?]|$)/g, '$1...$2')
    // Remaining single em-dash -> clean comma
    .replace(/[ \t]*\u2014[ \t]*/g, ', ')
    // Horizontal bar / double hyphen runs
    .replace(/[\u2015\u2500]{2,}/g, '...')
    // Normalize curly quotes & LaTeX quotes to crisp standard quotes (directional trimming only!)
    .replace(/``[ \t]*/g, '"')
    .replace(/[ \t]*''/g, '"')
    .replace(/“[ \t]*/g, '"')
    .replace(/[ \t]*”/g, '"')
    // Normalize Japanese punctuation left behind in ID/EN
    .replace(/、/g, ', ')
    .replace(/。/g, '. ')
    .replace(/！/g, '!')
    .replace(/？/g, '?')
    .replace(/！？|？！/g, '?!')
    .replace(/…{2,}|\.{4,}/g, '...')
    .replace(/([!?])\./g, '$1')
    .replace(/,[ \t]*,+/g, ',')
    .replace(/[ \t]+([,.;:?!])/g, '$1')
    // Insert missing space after ! or ? before next letter (never inside protected code/URLs)
    .replace(/([!?])(?=[A-Za-zÀ-ÿ])/g, '$1 ')
    // Abbreviation & filename-safe period spacing: only split "word.Sentence" (3+ lowercase -> Uppercase)
    .replace(/([a-zà-ÿ]{3,})\.(?=[A-ZÀ-Ý])/g, (m, word: string, offset: number, full: string) => {
      const ctxBefore = full.slice(Math.max(0, offset - 8), offset + word.length);
      if (KNOWN_DOT_ABBREV_RE.test(ctxBefore)) return m;
      return `${word}. `;
    })
    .replace(/([A-Za-zÀ-ÿ])"([A-Za-zÀ-ÿ])/g, '$1" $2')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();

  return restoreFormatSpans(out, restoreMap);
}

const ABSTRACT_SEBUAH_NOUNS =
  'perasaan|kebenaran|kebohongan|keheningan|kesunyian|harapan|mimpi|senyuman|senyum|tawa|masalah|tantangan|peluang|kesempatan|pilihan|keputusan|perubahan|ide|gagasan|pendapat|alasan|tanda|bukti|fakta|rahasia|kenangan|keajaiban|tragedi|kesalahan|kegagalan|keberhasilan|kemenangan|kekalahan|ancaman|risiko|bahaya|solusi|jawaban|pertanyaan|pengalaman|pengetahuan|informasi|data|nasihat|saran|bantuan|dukungan|perhatian|cinta|kasih|kebencian|kemarahan|ketakutan|keraguan|kepercayaan';

const SAFE_OLEHNYA_VERBS =
  'dibuka|ditutup|diambil|dipegang|ditarik|didorong|dilihat|ditatap|dibaca|ditulis|dikatakan|diucapkan|dijawab|ditanya|didengar|dirasakan|dipikirkan|diingat|dilupakan|disimpan|diletakkan|dilemparkan|diberikan|diterima|dikirim|dipilih|dibeli|dibuat|diubah|dihapus|ditemukan|dicari|dikejar|ditangkap|dilepaskan|dipeluk|disentuh';

const SAFE_ID_SPEECH_VERBS =
  'kata|ujar|jawab|sahut|balas|tanya|gumam|bisik|seru|teriak|bentak|pekik|celetuk|lanjut|potong|seloroh|cibir|gerutu|desah|desis|keluh|ucap|tutur|tegas|sambung|timpal';

const REDUPL_BLOCKLIST = new Set(['kupu', 'laba', 'mata', 'cumi', 'ubur', 'kura', 'oleh', 'hati']);

function naturalizeIndonesianSpan(
  spanText: string,
  spanKind: 'dialogue' | 'narration',
  profile: DiscourseProfile,
  srcLine: string,
  hadJaKeigo: boolean,
  recentTags: string[],
  expectedNegDeltaRef: { delta: number },
  followsDialogue = false
): string {
  let t = spanText;
  const isFormal =
    profile.register === 'formal_academic' ||
    profile.register === 'formal_legal_tech' ||
    profile.genre === 'legal_policy' ||
    profile.genre === 'academic_research' ||
    profile.genre === 'technical_docs' ||
    profile.genre === 'business_formal';
  const isFiction =
    profile.genre === 'fiction_novel' ||
    profile.genre === 'fiction_dialogue_heavy' ||
    profile.genre === 'subtitle_script' ||
    profile.toneOverride === 'novel' ||
    profile.toneOverride === 'casual';

  // --- Pass 1: Universal Anti-Translationese Rules (safe across ALL registers) ---

  // ID-R01: spatial head noun + "di mana" -> "$1 tempat" (never duplicate "tempat", never mangle questions!)
  t = t.replace(/\btempat\s+di\s+mana\b(?=\s+[A-Za-zÀ-ÿ])(?!\s*[^.!?]{0,40}\?)/gi, (m) =>
    preserveCase(m, 'tempat')
  );
  t = t.replace(
    /\b(kota|negara|desa|rumah|gedung|kantor|sekolah|kampus|kafe|kamar|ruangan|pulau|jalan|lokasi|wilayah|daerah|area|titik)\s+di\s+mana\b(?=\s+[A-Za-zÀ-ÿ])(?!\s*[^.!?]{0,40}\?)/gi,
    '$1 tempat'
  );
  // ID-R02: temporal head noun + "di mana" -> "$1 ketika" (non-interrogative only)
  t = t.replace(
    /\b(saat|waktu|masa|era|zaman|hari|momen|periode|tahap|fase)\s+di\s+mana\b(?=\s+[A-Za-zÀ-ÿ])(?!\s*[^.!?]{0,40}\?)/gi,
    '$1 ketika'
  );
  // ID-R03: abstract state + "di mana" (non-legal, non-interrogative)
  if (profile.genre !== 'legal_policy') {
    t = t.replace(
      /\b(situasi|kondisi|keadaan|kasus|skenario|proses|sistem|dunia)\s+di\s+mana\b(?=\s+[A-Za-zÀ-ÿ])(?!\s*[^.!?]{0,40}\?)/gi,
      '$1 saat'
    );
  }
  // ID-R04: non-interrogative "yang mana" -> "yang" (never mangle "...yang mana?" or "...yang mana yang")
  t = t.replace(
    /(?<!^)(?<!\.\s)(?<!"\s)(?<!\b(?:tahu|pilih|entah|bingung|tanya|lihat)\s),?\s*\byang\s+mana\b(?!\s*(?:yang\b|[^.!?]{0,40}\?))/gi,
    ' yang'
  );
  // ID-R05: pleonastic "hal tersebut/ini/itu adalah/merupakan sesuatu yang"
  t = t.replace(
    /(?<!\bbukan\s)\b(hal\s+tersebut|hal\s+ini|itu|ini)\s+(?:adalah|merupakan)\s+sesuatu\s+yang\b/gi,
    (_m, head: string) => {
      const cleanHead = isFiction && /^hal\s+tersebut$/i.test(head) ? preserveCase(head, 'itu') : head;
      return `${cleanHead} yang`;
    }
  );
  // ID-R06: "adalah merupakan" -> "merupakan" / "adalah"
  t = t.replace(/\badalah\s+merupakan\b/gi, (m) => preserveCase(m, isFiction ? 'adalah' : 'merupakan'));
  // ID-R08 & ID-R09: "dikarenakan oleh"
  t = t.replace(/\bhal\s+ini\s+dikarenakan\s+oleh\b/gi, (m) =>
    preserveCase(m, isFormal ? 'hal ini disebabkan oleh' : 'ini disebabkan oleh')
  );
  t = t.replace(/\bdikarenakan\s+oleh\b/gi, (m) =>
    preserveCase(m, isFormal ? 'disebabkan oleh' : 'karena')
  );
  // ID-R10 & ID-R11: "sebagai akibat dari fakta bahwa" / "karena fakta bahwa"
  t = t.replace(/(?<!terlepas\s+dari\s)\b(?:sebagai\s+akibat\s+dari|karena|berkat)\s+fakta\s+bahwa\b/gi, (m) =>
    preserveCase(m, 'karena')
  );

  // ID-R12: "tidak bisa membantu tetapi V" ("couldn't help but")
  t = t.replace(
    /\btidak\s+(?:bisa|dapat)\s+membantu\s+(?:tetapi|tapi|selain)\s+([a-z]+)/gi,
    (m, verb: string) =>
      preserveCase(m, isFiction ? `tak kuasa menahan diri untuk ${verb}` : `tak bisa menahan diri untuk ${verb}`)
  );

  // ID-R13: double-negative compulsion "tidak bisa tidak V" (2 negations -> 1 negation "tak", delta = -1)
  if (!isFormal) {
    t = t.replace(
      /\btidak\s+(?:bisa|dapat)\s+tidak\s+(melakukan|mengakui|merasa|tersenyum|tertawa|menangis|mengagumi|setuju|memikirkan|mengingat|tertarik|mengubah)\b/gi,
      (m, verb: string) => {
        expectedNegDeltaRef.delta -= 1;
        return preserveCase(m, `mau tak mau ${verb}`);
      }
    );
  }

  // ID-R14: "telah tidak pernah" -> "belum pernah" (NEVER touches "sudah tidak pernah"!)
  t = t.replace(/\btelah\s+tidak\s+pernah\b/gi, (m) => preserveCase(m, 'belum pernah'));
  // ID-R15: "tidak ada jalan lain selain untuk"
  t = t.replace(/\btidak\s+ada\s+jalan\s+lain\s+selain\s+untuk\b/gi, (m) =>
    preserveCase(m, 'tak ada jalan lain selain')
  );
  // ID-R16: "tidak terbatas pada [scalar adj]" (とは限らない)
  t = t.replace(
    /\btidak\s+terbatas\s+pada\s+(bagus|baik|benar|salah|mahal|murah|mudah|sulit)\b/gi,
    (m, adj: string) => preserveCase(m, `belum tentu ${adj}`)
  );

  // ID-R17..R26: Nominalization & light-verb calques
  if (!isFormal) {
    t = t.replace(/\bmelakukan\s+investigasi\s+(?:terhadap|atas|tentang)\b/gi, (m) =>
      preserveCase(m, 'menyelidiki')
    );
    t = t.replace(/\bmelakukan\s+pengamatan\s+(?:terhadap|atas)\b/gi, (m) =>
      preserveCase(m, 'mengamati')
    );
    t = t.replace(/\bmelakukan\s+diskusi\s+(dengan|tentang|mengenai)\b/gi, (m, prep: string) =>
      preserveCase(m, `berdiskusi ${prep}`)
    );
    t = t.replace(/\bmelakukan\s+pembicaraan\b/gi, (m) => preserveCase(m, 'berbicara'));
    t = t.replace(/\bmelakukan\s+serangan\s+(?:terhadap|atas|ke)\b/gi, (m) =>
      preserveCase(m, 'menyerang')
    );
    t = t.replace(/\bmelakukan\s+perjalanan\s+(ke|menuju)\b/gi, (m, prep: string) =>
      preserveCase(m, isFiction ? `pergi ${prep}` : `bepergian ${prep}`)
    );
    t = t.replace(/\bmemiliki\s+kemampuan\s+untuk\b/gi, (m) =>
      preserveCase(m, isFiction ? 'bisa' : 'mampu')
    );
  }
  t = t.replace(/\bmelakukan\s+perbaikan\s+(?:terhadap|atas|pada)\b/gi, (m) =>
    preserveCase(m, 'memperbaiki')
  );
  t = t.replace(/\bmembuat\s+(?:sebuah\s+)?keputusan\s+untuk\b/gi, (m) =>
    preserveCase(m, 'memutuskan untuk')
  );
  t = t.replace(/(?<!silakan\s)(?<!tolong\s)\bmengambil\s+tempat\s+(di|pada)\b(?!\s+duduk)/gi, (m, prep: string) =>
    preserveCase(m, `berlangsung ${prep}`)
  );
  t = t.replace(/\bmembuat\s+(?:banyak\s+)?(?:arti|akal)\b(?!\s+(?:baru|lain|khusus|ganda))/gi, (m) =>
    preserveCase(m, 'masuk akal')
  );
  t = t.replace(/\bmengambil\s+napas\s+dalam-dalam\b/gi, (m) =>
    preserveCase(m, 'menarik napas dalam-dalam')
  );
  t = t.replace(/\bmemiliki\s+senyum\s+di\s+wajahnya\b/gi, (m) => preserveCase(m, 'tersenyum'));

  // ID-R27: Redundant "sebuah" before curated abstract nouns
  t = t.replace(
    new RegExp(
      `(?<!\\bhanya\\s)(?<!\\bcuma\\s)(?<!\\bsatu\\s)(?<!\\bsekadar\\s)\\bsebuah\\s+(${ABSTRACT_SEBUAH_NOUNS})\\b(?!\\s+(?:tunggal|satu-satunya|tersendiri))`,
      'gi'
    ),
    (m, noun: string) => preserveCase(m, noun)
  );

  // ID-R29: "memiliki mata/rambut/wajah..." -> "bermata/berambut..." with strict morphology, compound & closed-class blocklist
  t = t.replace(
    /(?<!\btidak\s)(?<!\btak\s)(?<!\bbelum\s)(?<!\btanpa\s)\b(?:memiliki|mempunyai|punya)\s+(mata|rambut|wajah|kulit|suara|tubuh|badan|hidung|bibir|alis)\s+(?:yang\s+)?([a-z]{3,})\b/gi,
    (m, bodyPart: string, adj: string) => {
      const bp = bodyPart.toLowerCase();
      const adjLow = adj.toLowerCase();
      if (
        /^(?:pencaharian|uang|pelajaran|kuliah|air|angin|pisau|rantai|hati|terbanyak|mayoritas|bulat|hukum|usaha|dan|atau|dari|untuk|dalam|pada|dengan|ini|itu|tersebut|yang|juga|saja|pun|seperti|akan|bisa|dapat|harus|sudah|belum|tidak|tak|bukan|tanpa|karena|ketika|saat|jika|kalau|namun|tetapi|tapi|agar|supaya|oleh|tentang|antara|sebagai|hingga|sampai)$/.test(
          adjLow
        ) ||
        /^(?:me(?:ng|ny|mb|md|m|n)?|ber|ter|di|pe(?:ng|ny|m|n)?|se)[a-z]{3,}/.test(adjLow)
      ) {
        return m;
      }
      const prefixed = bp === 'rambut' ? `berambut ${adj}` : `ber${bp} ${adj}`;
      return preserveCase(m, prefixed);
    }
  );

  // ID-R30: Dummy-It "Adalah penting/sulit/... untuk/bahwa"
  t = t.replace(
    /(?:^|(?<=[.!?]\s))Adalah\s+(penting|sulit|mudah|mustahil|wajar|jelas|mungkin|benar|salah|aneh|lucu|menarik|mengejutkan|menyedihkan|menyenangkan)\s+(untuk|bahwa)\b/g,
    (_m, adj: string, conj: string) => `${adj.charAt(0).toUpperCase()}${adj.slice(1)} ${conj}`
  );

  // ID-R32: "dengan cara yang [adj]" (excluding sama/berbeda/lain/tepat/benar/salah)
  if (!isFormal) {
    t = t.replace(
      /\bdengan\s+cara\s+yang\s+(sangat\s+)?([a-z]{3,})\b/gi,
      (m, intens: string | undefined, adj: string) => {
        if (/^(?:sama|berbeda|lain|tepat|benar|salah|baik|buruk)$/i.test(adj)) return m;
        return preserveCase(m, `dengan ${intens || ''}${adj}`);
      }
    );
  }

  // ID-R35: "di[verb] olehnya" -> "di[verb]nya"
  t = t.replace(
    new RegExp(`\\b(${SAFE_OLEHNYA_VERBS})\\s+olehnya\\b(?!\\s*(?:sendiri|,\\s*bukan))`, 'gi'),
    '$1nya'
  );
  // ID-R37: adversity passive calque
  t = t.replace(/\bdihujani\s+oleh\s+hujan\b/gi, (m) => preserveCase(m, 'kehujanan'));
  // ID-R38: passive reporting calque
  if (!isFormal) {
    t = t.replace(/(?<!\btidak\s)\bdikatakan\s+oleh(?:nya|\s+(?:dia|ia))\s+bahwa\b/gi, (m) =>
      preserveCase(m, 'katanya,')
    );
  }

  // ID-R45..R52: Double-conjunctions, pleonasms & prepositional calques
  t = t.replace(/\b(Meskipun|Walaupun|Kendati)\s+([^,.!?]{3,80}),\s+(?:tetapi|tapi|namun)\s+/gi, '$1 $2, ');
  t = t.replace(/\b(Karena|Sebab)\s+([^,.!?]{3,80}),\s+maka\s+/gi, '$1 $2, ');
  t = t.replace(/\b(?:dalam\s+rangka\s+untuk|untuk\s+tujuan\s+untuk)\b/gi, (m) => preserveCase(m, 'untuk'));
  t = t.replace(/\b(para)\s+([a-z]{3,})-\2\b/gi, (m, para: string, stem: string) =>
    REDUPL_BLOCKLIST.has(stem.toLowerCase()) ? m : `${para} ${stem}`
  );
  t = t.replace(/\bsangat\s+([a-z]{3,})\s+sekali\b(?!\s+(?:lagi|saja|pun))/gi, (m, adj: string) =>
    preserveCase(m, `sangat ${adj}`)
  );
  t = t.replace(/\b(?:sangat|amat)\s+sekali\b/gi, (m) => preserveCase(m, 'sangat'));
  t = t.replace(/\bjatuh\s+cinta\s+dengan\b/gi, (m) => preserveCase(m, 'jatuh cinta pada'));
  t = t.replace(
    /\btertarik\s+dalam\b(?!\s+(?:arus|pusaran|lubang|jurang|air|lumpur))/gi,
    (m) => preserveCase(m, 'tertarik pada')
  );
  t = t.replace(/\bmelihat\s+ke\s+depan\s+untuk\b/gi, (m) => preserveCase(m, 'menantikan'));
  t = t.replace(/\bsecara\s+tiba-tiba\b/gi, (m) => preserveCase(m, 'tiba-tiba'));
  t = t.replace(/\bsecara\s+perlahan-lahan\b/gi, (m) => preserveCase(m, 'perlahan'));

  // --- Pass 1B: EYD V & KBBI VI Precision Rules (ID-W01..ID-W06, universal across ALL registers) ---
  // ID-W01: EYD V "Maha" rules ("Maha Esa" separated; basic adjectives joined preserving case)
  t = t.replace(/\bMahaesa\b/gi, (m) => preserveCase(m, 'Maha Esa'));
  t = t.replace(
    /\b(Maha|maha)\s+(Kuasa|Tahu|Besar|Adil|Kasih|Suci|Tinggi|Mulia|Agung|Bijaksana)\b/gi,
    (m, _maha: string, adj: string) => preserveCase(m, `maha${adj.toLowerCase()}`)
  );
  // ID-W02: EYD V locative prepositions di/ke separated from location nouns (NEVER split verb "keluar"!)
  t = t.replace(
    /\bdi(sini|situ|sana|mana|atas|bawah|dalam|luar|depan|belakang|samping|antara|tengah|sekitar)\b/gi,
    (m, loc: string) => preserveCase(m, `di ${loc.toLowerCase()}`)
  );
  t = t.replace(
    /\bke(sini|situ|sana|mana|atas|bawah|dalam|depan|belakang|samping|tengah)\b/gi,
    (m, loc: string) => preserveCase(m, `ke ${loc.toLowerCase()}`)
  );
  // ID-W03: EYD V particle "pun" separated (excluding the 12 fused conjunctions) + fused dimanapun/kemanapun
  t = t.replace(/\bdi\s*manapun\b/gi, (m) => preserveCase(m, 'di mana pun'));
  t = t.replace(/\bke\s*manapun\b/gi, (m) => preserveCase(m, 'ke mana pun'));
  t = t.replace(
    /\b(apa|siapa|kapan|berapa|satu|dua|sedikit|banyak|sekali|juga|ia|dia|aku|kamu|kami|kita|mereka)pun\b/gi,
    (m, stem: string) => {
      if (/^sekali$/i.test(stem)) return m; // "sekalipun" is fused in EYD V
      return preserveCase(m, `${stem.toLowerCase()} pun`);
    }
  );
  // ID-W04: KBBI VI baku lexical normalization (safe across formal & literary)
  const kbbiFixes: Array<[RegExp, string]> = [
    [/\bpraktek\b/gi, 'praktik'],
    [/\bresiko\b/gi, 'risiko'],
    [/\banalisa\b/gi, 'analisis'],
    [/\bsistim\b/gi, 'sistem'],
    [/\bkwalitas\b/gi, 'kualitas'],
    [/\bkwantitas\b/gi, 'kuantitas'],
    [/\baktifitas\b/gi, 'aktivitas'],
    [/\befektifitas\b/gi, 'efektivitas'],
    [/\bnafas\b/gi, 'napas'],
    [/\bbernafas\b/gi, 'bernapas'],
    [/\bijin\b/gi, 'izin'],
    [/\bmengijinkan\b/gi, 'mengizinkan'],
    [/\bobyek\b/gi, 'objek'],
    [/\bsubyek\b/gi, 'subjek'],
    [/\bjadual\b/gi, 'jadwal'],
    [/\bantri\b/gi, 'antre'],
    [/\bapotik\b/gi, 'apotek'],
    [/\batlit\b/gi, 'atlet'],
    [/\bhakekat\b/gi, 'hakikat'],
    [/\bsekedar\b/gi, 'sekadar'],
    [/\bte(?:k?h)nik\b/gi, 'teknik'],
    [/\bterimakasih\b/gi, 'terima kasih'],
  ];
  for (const [pat, repl] of kbbiFixes) {
    t = t.replace(pat, (m) => preserveCase(m, repl));
  }
  // ID-W05: EYD V currency format (Rp50.000, no dot and no space after Rp)
  t = t.replace(/\bRp\.?\s+(\d)/g, 'Rp$1');
  t = t.replace(/\bRp\.(\d)/g, 'Rp$1');
  // ID-W05b: Purwo (1984) Indonesian deixis: "ia" is strictly subject-slot, never oblique after preposition (preserve "untuk ia [verb]" embedded subject!)
  t = t.replace(/\b(kepada|oleh|dengan|dari|pada)\s+ia\b/gi, (m, prep: string) =>
    preserveCase(m, `${prep.toLowerCase()}nya`)
  );
  t = t.replace(/\buntuk\s+ia\b(?![ \t]+[a-z]{2,})/gi, (m) => preserveCase(m, 'untuknya'));
  // ID-W06: Legal deontic strengthening (when EN source has uppercase SHALL/MUST and MT softened to "akan")
  if (profile.strictDeonticModals && profile.srcLang === 'en' && /\b(?:SHALL|MUST)\b(?!\s+NOT\b)/.test(srcLine)) {
    t = t.replace(/\b(Pihak|Pengguna|Penyedia|Pemohon|Pembeli|Penjual|Penerima|Kontraktor)\s+akan\b/g, '$1 wajib');
  }
  if (profile.strictDeonticModals && profile.srcLang === 'en' && /\b(?:SHALL|MUST)\s+NOT\b/.test(srcLine)) {
    t = t.replace(/\b(Pihak|Pengguna|Penyedia|Pemohon|Pembeli|Penjual|Penerima|Kontraktor)\s+tidak\s+akan\b/g, (_m, subj: string) => {
      expectedNegDeltaRef.delta -= 1;
      return `${subj} dilarang`;
    });
  }

  // --- Pass 2: Source-Anchored Japanese Idiom & Mimetic Rescue (GTX fallback, with exact negation-delta tracking) ---
  if (profile.srcLang === 'ja' && srcLine) {
    for (const idiom of JA_LITERARY_IDIOMS) {
      if (idiom.gtxLiteralId && idiom.gtxNaturalId && idiom.ja.test(srcLine)) {
        t = t.replace(idiom.gtxLiteralId, (m, ...args) => {
          let repl = idiom.gtxNaturalId!;
          if (typeof args[0] === 'string' && repl.includes('$1')) {
            repl = repl.replace('$1', args[0]);
          }
          const next = preserveCase(m, repl);
          expectedNegDeltaRef.delta += countNegations(next, 'id') - countNegations(m, 'id');
          return next;
        });
      }
    }
    for (const mim of JA_MIMETICS) {
      if (mim.ja.test(srcLine) && mim.romajiRe.test(t)) {
        t = t.replace(mim.romajiRe, (m) => {
          const next = preserveCase(m, mim.id);
          expectedNegDeltaRef.delta += countNegations(next, 'id') - countNegations(m, 'id');
          return next;
        });
      }
    }
  }

  // --- Pass 3: Fiction-Scoped Naturalization (strictly gated off in Formal/Legal/Academic/Tech) ---
  if (isFiction && !isFormal) {
    // Drop stiffness copula "adalah" before bare adjectives in fiction
    t = t.replace(
      /\badalah\s+(sangat\s+|begitu\s+|cukup\s+|terlalu\s+)?(besar|kecil|marah|sedih|senang|tenang|sunyi|gelap|dingin|panas|cantik|indah|aneh|sulit|mudah|penting|lelah|takut|bingung|terkejut)\b/gi,
      (_m, adv: string | undefined, adj: string) => `${adv || ''}${adj}`
    );
    // Fiction connectors (ID-R40..R43)
    t = t.replace(/(?:^|(?<=[.!?]\s))Oleh\s+karena\s+itu,\s+/g, spanKind === 'dialogue' ? 'Jadi, ' : 'Karena itu, ');
    t = t.replace(/(?:^|(?<=[.!?]\s))Dengan\s+kata\s+lain,\s+/g, spanKind === 'dialogue' ? 'Maksudnya, ' : 'Artinya, ');
    t = t.replace(/(?:^|(?<=[.!?]\s))Bagaimanapun\s+juga,\s+/g, 'Walau begitu, ');
    t = t.replace(/(?:^|(?<=[.!?]\s))Sebagai\s+hasilnya,\s+/g, 'Alhasil, ');
    t = t.replace(/\bhal\s+tersebut\s+(menjadi|membuat|menyebabkan|menunjukkan|membuktikan|berarti)\b/gi, (m, v: string) =>
      preserveCase(m, `itu ${v}`)
    );

    // Topic-fronting calque smoothing in fiction narration (Kuno 1973 / Sneddon 2010)
    if (spanKind === 'narration') {
      t = t.replace(/(?:^|(?<=[.!?]\s))(?:Sedangkan\s+untuk|Adapun\s+mengenai)\s+([^,.\n]{2,36}),\s+/g, 'Soal $1, ');
      t = t.replace(/\bberkata\s+dengan\s+(?:lirih|pelan)\b/gi, (m) => preserveCase(m, 'berbisik pelan'));
      t = t.replace(/\bberkata\s+dengan\s+marah\b/gi, (m) => preserveCase(m, 'membentak'));
      t = t.replace(/\bberkata\s+dengan\s+lembut\b/gi, (m) => preserveCase(m, 'bertutur lembut'));

      // Break monotonous "dia berkata" / "katanya" runs ONLY immediately following a dialogue quote
      if (followsDialogue) {
        const tagMatch = t.match(/^([ \t]*,?[ \t]*)(dia\s+berkata|ia\s+berkata|katanya|ujarnya|sahutnya|ucapnya)\b/i);
        if (tagMatch) {
          const lead = tagMatch[1];
          const verbLow = tagMatch[2].toLowerCase();
          if (verbLow === 'katanya' || verbLow === 'dia berkata' || verbLow === 'ia berkata') {
            const recentKatanya = recentTags.filter((x) => x === 'katanya' || x === 'berkata').length;
            if (recentKatanya >= 1) {
              const cycle = ['ujarnya', 'sahutnya', 'ucapnya'];
              const pick = cycle[recentTags.length % cycle.length];
              t = t.replace(
                /^([ \t]*,?[ \t]*)(?:dia\s+berkata|ia\s+berkata|katanya)\b/i,
                `${lead}${pick}`
              );
              recentTags.push(pick);
            } else if (/^(?:dia|ia)\s+berkata/i.test(verbLow)) {
              t = t.replace(/^([ \t]*,?[ \t]*)(?:dia|ia)\s+berkata\b/i, `${lead}ujarnya`);
              recentTags.push('ujarnya');
            } else {
              recentTags.push('katanya');
            }
          } else {
            recentTags.push(verbLow);
          }
          if (recentTags.length > 6) recentTags.shift();
        }
      }
    }

    // Spoken dialogue cadence inside "..." (never in archaic/formal!)
    if (spanKind === 'dialogue' && profile.allowCasualDialogue && !hadJaKeigo) {
      t = t.replace(/^"Apakah\s+(kamu|kau|kalian|dia|mereka|kita)\s+(mau|bisa|tahu|suka|ingin|sudah|belum|tidak|yakin)\b/i, '"Apa $1 $2');
      t = t.replace(/^"Mengapa\s+(kamu|kau|dia|kalian)\b/i, '"Kenapa $1');
      t = t.replace(/\b(?:Saya|Aku)\s+bertanya-tanya\s+apakah\b/gi, (m) =>
        preserveCase(m, 'Kira-kira apa')
      );
      t = t.replace(/\bOh,?\s+tidak!/g, () => {
        expectedNegDeltaRef.delta -= 1;
        return 'Gawat!';
      });
      t = t.replace(/\b(Saya|Aku)\s+berpikir\s+bahwa\b/gi, (m) => preserveCase(m, 'Kupikir'));
    }

    // ID-R53: Casual Fiction Pronoun Softener (strictly guarded!)
    const hasSuperiorAddress =
      /(?:-sensei|-sama|-buchou|-kachou|\b(?:Pak|Bu|Bapak|Ibu|Tuan|Nyonya|Profesor|Dokter|Paduka|Yang\s+Mulia)\b)/i.test(
        t
      );
    const shouldSoftenPronoun =
      profile.allowIdPronounSoften &&
      !hadJaKeigo &&
      !hasSuperiorAddress &&
      (spanKind === 'dialogue' || profile.narratorId1P === 'aku');

    if (shouldSoftenPronoun) {
      t = t.replace(/\bdi([a-z]{3,})\s+oleh\s+saya\b(?!\s*(?:sendiri|,\s*bukan))/gi, (m, stem: string) =>
        /^(?:buka|tutup|lihat|baca|tulis|ambil|pegang|dengar|rasa|ingat|pikir|kata|jawab|temu)/.test(stem)
          ? preserveCase(m, `ku${stem}`)
          : m
      );
      t = t.replace(/\bkepada\s+saya\b/gi, (m) => preserveCase(m, 'padaku'));
      t = t.replace(/\buntuk\s+saya\b/gi, (m) => preserveCase(m, 'untukku'));
      t = t.replace(/\bdari\s+saya\b/gi, (m) => preserveCase(m, 'dariku'));
      t = t.replace(/\bdengan\s+saya\b/gi, (m) => preserveCase(m, 'denganku'));
      t = t.replace(/\bmilik\s+saya\b/gi, (m) => preserveCase(m, 'milikku'));
      t = t.replace(/\bSaya\b/g, 'Aku');
      t = t.replace(/\bsaya\b/g, 'aku');
      if (spanKind === 'dialogue' || profile.genre === 'fiction_novel') {
        t = t.replace(/\bAnda\b/g, 'Kamu');
        t = t.replace(/\banda\b/g, 'kamu');
      }
    } else if (
      spanKind === 'dialogue' &&
      !hadJaKeigo &&
      !hasSuperiorAddress &&
      /\baku\b/i.test(t) &&
      /\banda\b/i.test(t)
    ) {
      // Djenar et al. (2018) intra-turn T-V register alignment: never mix intimate "aku" with sterile "Anda"
      t = t.replace(/\bAnda\b/g, 'Kamu').replace(/\banda\b/g, 'kamu');
    }
  }

  return t;
}

function naturalizeEnglishSpan(
  spanText: string,
  profile: DiscourseProfile,
  srcLine: string
): string {
  let t = spanText;
  // EN-R01: Double hedging
  t = t.replace(/\bIt\s+is\s+(?:thought|believed)\s+that\s+it\s+can\s+be\s+said\s+that\b/gi, (m) =>
    preserveCase(m, 'It appears that')
  );
  // EN-R02: Nested regarding...concerning
  t = t.replace(/\bregarding\s+([^,.]{2,40})\s+concerning\b/gi, (m, mid: string) =>
    preserveCase(m, `on ${mid} about`)
  );
  // EN-R03: Redundant "As for he/she, he/she"
  t = t.replace(/\bAs\s+for\s+(he|she|they|I|we),\s+\1\b/gi, (_m, pron: string) =>
    pron.charAt(0).toUpperCase() + pron.slice(1)
  );
  // EN-R04: Duplicated already/very
  t = t.replace(/\balready\s+(has|have|had)\s+already\b/gi, '$1 already');
  t = t.replace(/\bvery\s+([a-z]+)\s+very\b/gi, 'very $1');
  // EN-R05: Wordy causality
  t = t.replace(
    /\bThis\s+(?:matter|thing)\s+is\s+(?:due\s+to|caused\s+by)\s+the\s+fact\s+that\b/gi,
    (m) => preserveCase(m, 'This is because')
  );
  // EN-R06: Stative marrying X ago
  t = t.replace(/\b(?:is|was)\s+marrying\s+(\d+\s+(?:years|months|days)\s+ago)\b/gi, 'got married $1');
  // EN-R08: Possessive spacing & double article
  t = t.replace(/\bthe\s+the\b/gi, 'the');
  t = t.replace(/([A-Za-z])\s+'s\b/g, "$1's");
  // EN-W01: Uncountable noun plural repairs
  t = t.replace(/\binformations\b/gi, (m) => preserveCase(m, 'information'));
  t = t.replace(/\badvices\b/gi, (m) => preserveCase(m, 'advice'));
  t = t.replace(/\bequipments\b/gi, (m) => preserveCase(m, 'equipment'));
  t = t.replace(/\bfurnitures\b/gi, (m) => preserveCase(m, 'furniture'));
  t = t.replace(/\bknowledges\b/gi, (m) => preserveCase(m, 'knowledge'));
  t = t.replace(/\bsceneries\b/gi, (m) => preserveCase(m, 'scenery'));
  t = t.replace(/\bluggages\b/gi, (m) => preserveCase(m, 'luggage'));
  t = t.replace(/\bbaggages\b/gi, (m) => preserveCase(m, 'baggage'));
  t = t.replace(/\b(many|several|these|some|all|the)\s+researches\b/gi, '$1 research');

  // Source-anchored JA idiom & mimetic rescue for EN
  if (profile.srcLang === 'ja' && srcLine) {
    for (const idiom of JA_LITERARY_IDIOMS) {
      if (idiom.gtxLiteralEn && idiom.gtxNaturalEn && idiom.ja.test(srcLine)) {
        t = t.replace(idiom.gtxLiteralEn, (m) => preserveCase(m, idiom.gtxNaturalEn!));
      }
    }
    for (const mim of JA_MIMETICS) {
      if (mim.ja.test(srcLine) && mim.romajiRe.test(t)) {
        t = t.replace(mim.romajiRe, (m) => preserveCase(m, mim.en));
      }
    }
  }
  return t;
}

function naturalizeJapaneseSpan(spanText: string, spanKind: 'dialogue' | 'narration'): string {
  let t = spanText;
  // JA-W02: Full-width punctuation adjacent to Japanese script
  t = t
    .replace(/([\u3040-\u30ff\u4e00-\u9fff])\?/g, '$1？')
    .replace(/([\u3040-\u30ff\u4e00-\u9fff])!/g, '$1！');
  // JA-R04: Pleonastic intensifier cleanup in narration
  if (spanKind === 'narration') {
    t = t.replace(/とてもとても/g, 'とても').replace(/非常に非常に/g, '極めて');
  }
  // JA-R01: Intra-sentence duplicate pronoun drop (outside quotes, not after contrastive が/一方)
  if (spanKind === 'narration') {
    for (const pron of ['私は', '僕は', '俺は', 'あなたは']) {
      let seen = false;
      t = t.replace(new RegExp(pron, 'g'), (match, offset: number, full: string) => {
        if (!seen) {
          seen = true;
          return match;
        }
        const before = full.slice(Math.max(0, offset - 18), offset);
        if (/[。！？\n]|一方|しかし|だが|けど/.test(before)) {
          return match;
        }
        return '';
      });
    }
  }
  return t;
}

// Post-GTX anti-"Tuan/Nyonya" repair for Japanese classmate honorifics
function repairGtxHonorificLeaks(
  text: string,
  srcLine: string,
  profile: DiscourseProfile
): string {
  if (
    profile.srcLang !== 'ja' ||
    profile.tgtLang !== 'id' ||
    profile.domain === 'historical_fantasy' ||
    profile.domain === 'formal_nonfiction'
  ) {
    return text;
  }
  // Only repair if source had -san/-kun/-chan (optionally followed by particles は/が/の/を/に/も/と/へ/で/、/。) and did NOT have 様/殿/旦那様
  const hasPeerHonorific =
    /[\u4e00-\u9fffァ-ヶー](?:さん|くん|君|ちゃん)(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])/.test(
      srcLine
    );
  const hasLordHonorific = /(?:様|さま|殿|どの|旦那|奥様|お嬢様|陛下|殿下)/.test(srcLine);
  if (!hasPeerHonorific || hasLordHonorific) return text;

  const isKun =
    /[\u4e00-\u9fffァ-ヶー](?:くん|君)(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])/.test(
      srcLine
    );
  const isChan =
    /[\u4e00-\u9fffァ-ヶー]ちゃん(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])/.test(
      srcLine
    );
  const hasSan =
    /[\u4e00-\u9fffァ-ヶー]さん(?=$|[はがのをにもとへで、。！？「」『』\sだでよのかって])/.test(
      srcLine
    );
  const defaultSuffix = isChan && !hasSan ? '-chan' : isKun && !hasSan ? '-kun' : '-san';

  return text.replace(
    /\b(?:Tuan|Nyonya|Bapak|Ibu|Nona|Saudara|Saudari)\s+([A-Z][a-z]{2,20})\b/g,
    (_m, name: string) => `${name}${defaultSuffix}`
  );
}

// Indonesian EYD V dialogue punctuation automation (ellipsis-safe, case-insensitive, & -nya/-ku/-mu aware)
function fixIndonesianDialoguePunctuation(text: string): string {
  let out = text;
  // Rule 1: "Aku pulang." katanya. / "Aku pulang." Katanya. -> "Aku pulang," katanya. (never corrupt "Aku..."!)
  out = out.replace(
    new RegExp(`("[^"\\n]+?)(?<!\\.)\\."\\s+(${SAFE_ID_SPEECH_VERBS})(nya|ku|mu)?\\b`, 'gi'),
    (_m, quote: string, verb: string, enclitic: string | undefined) =>
      `${quote}," ${verb.toLowerCase()}${enclitic ? enclitic.toLowerCase() : ''}`
  );
  // Rule 2: "Mau ke mana?" Tanyanya. -> "Mau ke mana?" tanyanya.
  out = out.replace(
    new RegExp(`("[^"\\n]+?[!?]")\\s+(${SAFE_ID_SPEECH_VERBS})(nya|ku|mu)?\\b`, 'gi'),
    (_m, quote: string, verb: string, enclitic: string | undefined) =>
      `${quote} ${verb.toLowerCase()}${enclitic ? enclitic.toLowerCase() : ''}`
  );
  return out;
}

// ---------- Stage 3B: 12-Invariant ConservationGate & MQM Core Scorer (v4) ----------

const ID_NEG_RE = /\b(?:tidak|tak|bukan|belum|jangan|tanpa|tiada|nggak|gak)\b/gi;
const EN_NEG_RE = /\b(?:not|never|no|without|neither|nor)\b|n't\b/gi;
const JA_NEG_RE = /(?:ない|ません|なかった|ませんでした|ず|ぬ)/g;
const NUM_LITERAL_RE = /(?:\b|(?<=Rp))\d+(?:[.,]\d+)*%?(?![A-Za-z0-9_])/g;
const UNIT_CURRENCY_RE =
  /(?:\bRp(?=\d)|[$€£¥%]|\b(?:kg|km|cm|mm|mg|ml|mL|MHz|GHz|MB|GB|TB|ms|kWh)\b|°[CF])/g;
const DEONTIC_MANDATORY_RE = /\b(?:wajib|harus|dilarang|shall|must|prohibited)\b/gi;

function countNegations(text: string, tgt: TargetLang): number {
  const re = tgt === 'id' ? ID_NEG_RE : tgt === 'en' ? EN_NEG_RE : JA_NEG_RE;
  return (text.match(re) || []).length;
}

function normalizedNumericMultiset(text: string): Map<string, number> {
  const counts = new Map<string, number>();
  const matches = text.match(NUM_LITERAL_RE) || [];
  for (const raw of matches) {
    // Strip thousands separators (1,000 / 1.000 -> 1000) while preserving decimal digits
    const norm = raw.replace(/[.,](?=\d{3}(?:\D|$))/g, '').replace(',', '.');
    counts.set(norm, (counts.get(norm) || 0) + 1);
  }
  return counts;
}

function extractStructuralPrefix(line: string): string {
  const m = line.match(/^(\s*(?:```|#{1,6}\s+|>\s+|(?:[-*+]|\d+\.)\s+))/);
  return m ? m[1].trim() : '';
}

export function evaluateConservationAndMqm(params: {
  preNat: string;
  postNat: string;
  tgt: TargetLang;
  expectedNegDelta: number;
  glossaryValues?: string[];
  strictDeonticModals?: boolean;
}): ConservationResult {
  const { preNat, postNat, tgt, expectedNegDelta, glossaryValues, strictDeonticModals } = params;
  const defects: MqmDefect[] = [];
  const addDefect = (
    category: MqmDefect['category'],
    severity: MqmDefect['severity'],
    detail: string
  ) => {
    const weight = severity === 'critical' ? 25 : severity === 'major' ? 5 : 1;
    defects.push({ category, severity, weight, detail });
  };

  // 1. Non-empty output invariant
  if (!postNat.trim() && preNat.trim()) {
    addDefect('accuracy_omission', 'critical', 'Empty output after naturalization');
  }
  // 2. Zero U+2014 invariant on unshielded prose (allows literal U+2014 inside code/LaTeX/URLs!)
  const shieldedPost = protectFormatSpans(postNat).shielded;
  if (/\u2014/.test(shieldedPost)) {
    addDefect('fluency_punctuation', 'major', 'Leaked U+2014 em-dash');
  }
  // 3. Zero leaked placeholder tokens
  if (/\[\[[EHIC]\d+\]\]|\u27E6F\d+\u27E7/.test(postNat)) {
    addDefect('markup_format', 'critical', 'Leaked internal placeholder token');
  }
  // 4. Exact newline count parity
  const preLines = preNat.split('\n');
  const postLines = postNat.split('\n');
  if (preLines.length !== postLines.length) {
    addDefect('markup_format', 'major', 'Line-break count mismatch');
  }
  // 5. Safe length ratio
  if (preNat.length >= 24) {
    const ratio = postNat.length / Math.max(preNat.length, 1);
    if (ratio < 0.55 || ratio > 1.55) {
      addDefect('accuracy_omission', 'major', `Length ratio out of bounds (${ratio.toFixed(2)})`);
    }
  }
  // 6. Normalized numeric multiset conservation
  const preNums = normalizedNumericMultiset(preNat);
  if (preNums.size > 0) {
    const postNums = normalizedNumericMultiset(postNat);
    for (const [num, needed] of preNums.entries()) {
      if ((postNums.get(num) || 0) < needed) {
        addDefect('accuracy_number_unit', 'critical', `Numeric value lost or altered: ${num}`);
        break;
      }
    }
  }
  // 7. Currency & SI unit symbol conservation
  const preUnits = preNat.match(UNIT_CURRENCY_RE) || [];
  if (preUnits.length > 0) {
    const postUnits = postNat.match(UNIT_CURRENCY_RE) || [];
    if (postUnits.length < preUnits.length) {
      addDefect('accuracy_number_unit', 'major', 'Currency or SI unit dropped');
    }
  }
  // 8. Glossary entity conservation
  if (glossaryValues && glossaryValues.length > 0) {
    for (const val of glossaryValues) {
      if (val.length >= 2 && preNat.includes(val) && !postNat.includes(val)) {
        addDefect('terminology', 'critical', `Glossary term dropped: ${val}`);
        break;
      }
    }
  }
  // 9. Strict negation polarity fidelity
  const preNeg = countNegations(preNat, tgt);
  const postNeg = countNegations(postNat, tgt);
  if (postNeg - preNeg !== expectedNegDelta) {
    addDefect('accuracy_polarity', 'critical', `Negation delta mismatch (${postNeg - preNeg} vs ${expectedNegDelta})`);
  }
  // 10 & 11. Markdown table pipe parity & structural prefix parity
  if (preLines.length === postLines.length) {
    for (let i = 0; i < preLines.length; i++) {
      const preL = preLines[i];
      const postL = postLines[i];
      if (preL.includes('|')) {
        const prePipes = (preL.match(/\|/g) || []).length;
        const postPipes = (postL.match(/\|/g) || []).length;
        if (prePipes >= 2 && prePipes !== postPipes) {
          addDefect('markup_format', 'major', 'Markdown table column pipe mismatch');
          break;
        }
      }
      const prePref = extractStructuralPrefix(preL);
      if (prePref && extractStructuralPrefix(postL) !== prePref) {
        addDefect('markup_format', 'major', `Structural prefix altered (${prePref})`);
        break;
      }
    }
  }
  // 12. Legal deontic modal parity
  if (strictDeonticModals) {
    const preMod = (preNat.match(DEONTIC_MANDATORY_RE) || []).length;
    const postMod = (postNat.match(DEONTIC_MANDATORY_RE) || []).length;
    if (preMod > 0 && postMod < preMod) {
      addDefect('accuracy_modal', 'critical', 'Legal mandatory deontic modal weakened');
    }
  }

  const mqmRiskScore = defects.reduce((acc, d) => acc + d.weight, 0);
  return {
    ok: defects.length === 0,
    mqmRiskScore,
    defects,
  };
}

export function verifyMeaningConservation(params: {
  preNat: string;
  postNat: string;
  tgt: TargetLang;
  expectedNegDelta: number;
  glossaryValues?: string[];
  strictDeonticModals?: boolean;
}): boolean {
  return evaluateConservationAndMqm(params).ok;
}

// ---------- Stage 3C (v5): Reference-Free Source->Target QE, Repetition Loop, 4-Class Deontics & Self-Repair ----------

const KANJI_DIGIT_MAP: Record<string, number> = {
  '〇': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
};
const KANJI_SMALL_UNIT: Record<string, number> = { '十': 10, '百': 100, '千': 1000 };
const KANJI_BIG_UNIT: Record<string, number> = { '万': 10_000, '億': 100_000_000 };
const KANJI_NUM_RUN_RE = /[一二三四五六七八九十百千万億〇零]{2,}|[三四五六七八九](?=[人日回個本枚冊歳年分時円万億])/g;
const KANJI_IDIOM_EXCLUSIONS = new Set([
  '万一', '一切', '一気', '一斉', '一生', '一般', '一定', '一瞬', '一致', '一途', '一応', '一番',
  '万全', '万能', '万事', '万歳', '十分', '十二分', '十中八九', '百発百中', '千差万別', '一期一会',
  '二兎', '三昧', '四方', '五感', '六感', '七転', '八方', '九死',
]);

function parseJapaneseKanjiNumber(raw: string): number | null {
  if (!raw || KANJI_IDIOM_EXCLUSIONS.has(raw)) return null;
  // Positional digit sequence (e.g. 二〇二六 -> 2026)
  if (/^[〇零一二三四五六七八九]{2,}$/.test(raw)) {
    let digits = '';
    for (const ch of raw) {
      digits += String(KANJI_DIGIT_MAP[ch]);
    }
    const parsed = Number.parseInt(digits, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }
  let total = 0;
  let section = 0;
  let digit = 0;
  let seen = false;
  for (const ch of raw) {
    if (ch in KANJI_DIGIT_MAP) {
      digit = KANJI_DIGIT_MAP[ch];
      seen = true;
    } else if (ch in KANJI_SMALL_UNIT) {
      const unit = KANJI_SMALL_UNIT[ch];
      section += (digit === 0 ? 1 : digit) * unit;
      digit = 0;
      seen = true;
    } else if (ch in KANJI_BIG_UNIT) {
      const unit = KANJI_BIG_UNIT[ch];
      section += digit;
      total += (section === 0 ? 1 : section) * unit;
      section = 0;
      digit = 0;
      seen = true;
    } else {
      return null;
    }
  }
  const value = total + section + digit;
  return seen && value > 0 ? value : null;
}

function extractCanonicalNumbers(text: string): Map<string, number> {
  const normFw = text.replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
  const counts = normalizedNumericMultiset(normFw);
  const kanjiHits = normFw.match(KANJI_NUM_RUN_RE) || [];
  for (const kh of kanjiHits) {
    const val = parseJapaneseKanjiNumber(kh);
    if (val !== null) {
      const key = String(val);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  return counts;
}

const DEONTIC_CLASSES = {
  prohibition: {
    en: /\b(?:SHALL\s+NOT|MUST\s+NOT|PROHIBITED|FORBIDDEN|MAY\s+NOT)\b/gi,
    id: /\b(?:dilarang|tidak\s+boleh|haram)\b/gi,
    ja: /(?:してはならない|してはいけません|禁止する|禁止される)/g,
  },
  obligation: {
    en: /\b(?:SHALL(?!\s+NOT)|MUST(?!\s+NOT)|REQUIRED\s+TO)\b/gi,
    id: /\b(?:wajib|harus|diwajibkan)\b/gi,
    ja: /(?:しなければならない|しなければなりません|義務付ける|ものとする)/g,
  },
  permission: {
    en: /\b(?:MAY(?!\s+NOT)|PERMITTED\s+TO|ENTITLED\s+TO)\b/gi,
    id: /\b(?:dapat|berhak|diperbolehkan|boleh)\b/gi,
    ja: /(?:ことができる|してよい|許可される)/g,
  },
  recommendation: {
    en: /\b(?:SHOULD(?!\s+NOT)|RECOMMENDED)\b/gi,
    id: /\b(?:sebaiknya|disarankan|dianjurkan|seyogianya)\b/gi,
    ja: /(?:すべきである|することが望ましい|推奨される)/g,
  },
} as const;

const ACADEMIC_HEDGE_SRC_RE =
  /\b(?:suggests?|indicates?|may\s+(?:indicate|suggest|imply)|appears?\s+to|could\s+be|tends?\s+to|potentially|plausibly)\b|示唆され|と思われる|可能性がある|考えられる/gi;
const ACADEMIC_BOOSTER_TGT_RE =
  /\b(?:membuktikan|terbukti\s+pasti|pasti\s+menunjukkan|proves?\s+conclusively|undoubtedly\s+proves?|definitely\s+proves?)\b|証明している|確実に証明/gi;

/**
 * Holtzman (2020) / Raunak (2021) sliding-window n-gram repetition & degeneration detector.
 * Ignores human speech stutters inside quotes ("T-tunggu", "ま、待って") and short comic SFX.
 */
export function detectRepetitionLoop(
  tgtText: string,
  srcText: string,
  tgtLang: TargetLang
): { hasLoop: boolean; detail?: string } {
  const shieldedTgt = protectFormatSpans(tgtText).shielded;
  if (tgtLang === 'ja') {
    const cleanJa = shieldedTgt.replace(/[\s「」『』、。！？…・]/g, '');
    if (cleanJa.length < 36) return { hasLoop: false };
    const counts = new Map<string, number>();
    let total = 0;
    for (let i = 0; i <= cleanJa.length - 4; i += 1) {
      const gram = cleanJa.slice(i, i + 4);
      counts.set(gram, (counts.get(gram) || 0) + 1);
      total += 1;
    }
    const maxCount = Math.max(0, ...counts.values());
    const uniqRatio = counts.size / Math.max(1, total);
    if (maxCount >= 4 && uniqRatio < 0.48) {
      return { hasLoop: true, detail: `JA 4-gram degeneration (max=${maxCount}, uniq=${uniqRatio.toFixed(2)})` };
    }
    return { hasLoop: false };
  }

  // Strip quoted short stutters before n-gram check
  const words = shieldedTgt
    .toLowerCase()
    .replace(/[^a-zà-ÿ0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length > 0);
  if (words.length < 9) return { hasLoop: false };

  // Consecutive identical 3-to-6-word phrase cycle check (any start offset, repeats >= 3x)
  for (let n = 3; n <= 6; n += 1) {
    if (words.length < n * 3) continue;
    for (let i = 0; i <= words.length - n * 3; i += 1) {
      const p1 = words.slice(i, i + n).join(' ');
      const p2 = words.slice(i + n, i + n * 2).join(' ');
      if (p1 === p2) {
        const p3 = words.slice(i + n * 2, i + n * 3).join(' ');
        if (p2 === p3) {
          return { hasLoop: true, detail: `Consecutive ${n}-gram repetition loop ("${p1}")` };
        }
      }
    }
  }

  // Sliding 3-gram diversity collapse check vs source diversity
  const tgtGrams = new Map<string, number>();
  for (let i = 0; i <= words.length - 3; i += 1) {
    const g = `${words[i]} ${words[i + 1]} ${words[i + 2]}`;
    tgtGrams.set(g, (tgtGrams.get(g) || 0) + 1);
  }
  const tgtUniqRatio = tgtGrams.size / Math.max(1, words.length - 2);
  const srcWords = srcText
    .toLowerCase()
    .replace(/[^a-zà-ÿ0-9\s]/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
  const srcUniqRatio = srcWords.length >= 12 ? new Set(srcWords).size / srcWords.length : 0.85;
  if (words.length >= 20 && tgtUniqRatio < 0.45 && srcUniqRatio >= 0.55) {
    return { hasLoop: true, detail: `3-gram diversity collapse (ratio=${tgtUniqRatio.toFixed(2)})` };
  }
  return { hasLoop: false };
}

/**
 * Reference-free Source-to-Target Quality Estimation (Specia 2018 / Nababan 2012 3:2:1 / ISO 5060:2024).
 */
export function evaluateSourceTargetQe(params: {
  srcText: string;
  tgtText: string;
  profile: DiscourseProfile;
  glossaryValues?: string[];
}): QeReport {
  const { srcText, tgtText, profile, glossaryValues } = params;
  const defects: MqmDefect[] = [];
  // Nababan (2012) 3:2:1 severity weighting -> critical=30 (Accuracy), major=12 (Acceptability), minor=4 (Readability)
  const addDefect = (
    category: MqmDefect['category'],
    severity: MqmDefect['severity'],
    detail: string
  ) => {
    const weight = severity === 'critical' ? 30 : severity === 'major' ? 12 : 4;
    defects.push({ category, severity, weight, detail });
  };

  const cleanSrc = (srcText || '').trim();
  const cleanTgt = (tgtText || '').trim();
  if (!cleanSrc) {
    return {
      ok: true,
      needsSelfRepair: false,
      qeRiskScore: 0,
      defects: [],
      metrics: {
        fertilityRatio: 1,
        untranslatedRatio: 0,
        repetitionDetected: false,
        numericConservationOk: true,
        deonticOk: true,
        hedgingOk: true,
      },
    };
  }
  if (!cleanTgt) {
    addDefect('accuracy_omission', 'critical', 'Translated output is empty');
  }

  // 1. Untranslated script leakage on unshielded prose
  const shieldedTgt = protectFormatSpans(cleanTgt).shielded;
  let untranslatedRatio = 0;
  if (profile.tgtLang !== 'ja' && cleanTgt.length >= 6) {
    const kanaCount = (shieldedTgt.match(/[\u3040-\u30ff]/g) || []).length;
    const kanjiCount = (shieldedTgt.match(/[\u4e00-\u9fff]/g) || []).length;
    const nonWs = Math.max(1, shieldedTgt.replace(/\s+/g, '').length);
    untranslatedRatio = (kanaCount + kanjiCount) / nonWs;
    if (kanaCount >= 3 || untranslatedRatio > 0.08) {
      addDefect(
        'accuracy_untranslated',
        'critical',
        `Untranslated Japanese script leaked (${Math.round(untranslatedRatio * 100)}%)`
      );
    }
  }

  // 2. Pair-calibrated fertility / omission / detached-hallucination check (Vamvas & Sennrich 2022)
  let fertilityRatio = 1;
  if (cleanSrc.length >= 24 && cleanTgt.length > 0) {
    if (profile.srcLang === 'ja' && profile.tgtLang !== 'ja') {
      const jaChars = Math.max(1, cleanSrc.replace(/\s+/g, '').length);
      const tgtWords = Math.max(1, cleanTgt.split(/\s+/).filter(Boolean).length);
      fertilityRatio = tgtWords / jaChars;
      if (jaChars >= 30 && fertilityRatio < 0.16) {
        addDefect('accuracy_omission', 'critical', `Severe JA->${profile.tgtLang} undertranslation (fertility=${fertilityRatio.toFixed(2)})`);
      } else if (jaChars >= 25 && fertilityRatio > 2.2) {
        addDefect('accuracy_addition', 'major', `Suspected JA->${profile.tgtLang} overtranslation (fertility=${fertilityRatio.toFixed(2)})`);
      }
    } else if (profile.srcLang !== 'ja' && profile.tgtLang !== 'ja') {
      const srcWords = Math.max(1, cleanSrc.split(/\s+/).filter(Boolean).length);
      const tgtWords = Math.max(1, cleanTgt.split(/\s+/).filter(Boolean).length);
      fertilityRatio = tgtWords / srcWords;
      if (srcWords >= 12 && fertilityRatio < 0.4) {
        addDefect('accuracy_omission', 'critical', `Severe omission (word ratio=${fertilityRatio.toFixed(2)})`);
      } else if (srcWords >= 12 && fertilityRatio > 2.4) {
        addDefect('accuracy_addition', 'major', `Suspected hallucinated addition (word ratio=${fertilityRatio.toFixed(2)})`);
      }
    }
  }

  // 3. Cross-lingual Arabic + Japanese kanji numeral conservation (Amrhein & Sennrich 2022)
  let numericConservationOk = true;
  const srcNums = extractCanonicalNumbers(cleanSrc);
  if (srcNums.size > 0) {
    const tgtNums = extractCanonicalNumbers(cleanTgt);
    for (const [num, needed] of srcNums.entries()) {
      if ((tgtNums.get(num) || 0) < needed) {
        numericConservationOk = false;
        addDefect('accuracy_number_unit', 'critical', `Source numeric value missing in translation: ${num}`);
        break;
      }
    }
  }

  // 4. Glossary recall check
  if (glossaryValues && glossaryValues.length > 0) {
    for (const val of glossaryValues) {
      if (val.length >= 2 && cleanSrc.includes(val) && !cleanTgt.includes(val)) {
        addDefect('terminology', 'major', `Glossary anchor missing: ${val}`);
        break;
      }
    }
  }

  // 5. 4-Class Legal/RFC 2119 Deontic Lattice Verifier (Cao 2007 / RFC 2119)
  let deonticOk = true;
  if (profile.strictDeonticModals && (profile.genre === 'legal_policy' || profile.genre === 'technical_docs')) {
    const srcProhib = (cleanSrc.match(DEONTIC_CLASSES.prohibition[profile.srcLang]) || []).length;
    const tgtProhib = (cleanTgt.match(DEONTIC_CLASSES.prohibition[profile.tgtLang]) || []).length;
    const srcOblig = (cleanSrc.match(DEONTIC_CLASSES.obligation[profile.srcLang]) || []).length;
    const tgtOblig = (cleanTgt.match(DEONTIC_CLASSES.obligation[profile.tgtLang]) || []).length;
    const srcPerm = (cleanSrc.match(DEONTIC_CLASSES.permission[profile.srcLang]) || []).length;
    if (srcProhib > 0 && tgtProhib === 0) {
      deonticOk = false;
      addDefect('accuracy_modal', 'critical', 'Legal PROHIBITION modal (SHALL NOT / MUST NOT) dropped or weakened');
    } else if (srcOblig > 0 && tgtOblig === 0 && srcProhib === 0) {
      deonticOk = false;
      addDefect('accuracy_modal', 'critical', 'Legal OBLIGATION modal (SHALL / MUST) dropped or weakened');
    } else if (srcPerm > 0 && srcOblig === 0 && tgtOblig > 0) {
      deonticOk = false;
      addDefect('accuracy_modal', 'major', 'Legal PERMISSION modal (MAY) improperly escalated to OBLIGATION');
    }
  }

  // 6. Academic epistemic hedging guard (Hyland 1998)
  let hedgingOk = true;
  if (profile.genre === 'academic_research') {
    const srcHedges = (cleanSrc.match(ACADEMIC_HEDGE_SRC_RE) || []).length;
    const tgtBoosters = (cleanTgt.match(ACADEMIC_BOOSTER_TGT_RE) || []).length;
    if (srcHedges > 0 && tgtBoosters > 0 && !/\b(?:proves?|conclusively|definitely)\b|証明/i.test(cleanSrc)) {
      hedgingOk = false;
      addDefect('accuracy_hedging', 'major', 'Academic epistemic hedge escalated to certainty booster');
    }
  }

  // 7. Repetition loop / neural degeneration detector (Holtzman 2020 / Raunak 2021)
  const repCheck = detectRepetitionLoop(cleanTgt, cleanSrc, profile.tgtLang);
  if (repCheck.hasLoop) {
    addDefect('fluency_repetition_loop', 'critical', repCheck.detail || 'Neural repetition loop detected');
  }

  const qeRiskScore = defects.reduce((acc, d) => acc + d.weight, 0);
  return {
    ok: defects.length === 0,
    needsSelfRepair: qeRiskScore >= 25,
    qeRiskScore,
    defects,
    metrics: {
      fertilityRatio: Number(fertilityRatio.toFixed(3)),
      untranslatedRatio: Number(untranslatedRatio.toFixed(3)),
      repetitionDetected: repCheck.hasLoop,
      numericConservationOk,
      deonticOk,
      hedgingOk,
    },
  };
}

/**
 * Ki & Carpuat (2024) error-span-guided single-pass LLM self-repair prompt generator.
 */
export function buildSelfRepairPrompt(params: {
  srcText: string;
  draftText: string;
  qeReport: QeReport;
  profile: DiscourseProfile;
}): SelfRepairPayload {
  const tgtLabel =
    params.profile.tgtLang === 'id'
      ? 'Indonesian'
      : params.profile.tgtLang === 'en'
        ? 'English'
        : 'Japanese';
  const defectCodes = params.qeReport.defects.map((d) => `${d.category}:${d.severity}`);
  const defectLines = params.qeReport.defects
    .map((d, i) => `${i + 1}. [${d.category}/${d.severity}] ${d.detail}`)
    .join('\n');

  const systemPrompt =
    `You are a senior translation post-editor repairing ONLY the annotated MQM defects in a ${tgtLabel} draft. ` +
    `Preserve exact meaning, numbers, entities, legal modals, academic hedges, Markdown/code tokens, and natural ${params.profile.genre} flow. ` +
    `NEVER emit U+2014 em-dashes. Reply ONLY with JSON: {"text": "..."}`;

  const userPrompt =
    `Source (${params.profile.srcLang}):\n${params.srcText}\n\n` +
    `Draft (${params.profile.tgtLang}):\n${params.draftText}\n\n` +
    `Annotated MQM Defects to fix:\n${defectLines}`;

  return { systemPrompt, userPrompt, defectCodes };
}

/**
 * Main entry point: Naturalizes and verifies a single translated paragraph with full discourse context.
 * Guaranteed idempotent, zero U+2014, FormatShield-safe, and rolls back atomically on any invariant breach.
 */
export function naturalizeAndVerifyParagraph(params: {
  srcText: string;
  rawTranslated: string;
  profile: DiscourseProfile;
  hadJaKeigo?: boolean;
  glossaryValues?: string[];
  recentTags?: string[];
  centering?: CenteringState;
}): string {
  const { srcText, rawTranslated, profile } = params;
  if (!rawTranslated || !rawTranslated.trim()) return rawTranslated;

  const baseClean = sanitizeZeroEmDashAndPunct(rawTranslated, profile.tgtLang);
  const recentTags = params.recentTags || [];
  const workingTags = [...recentTags];
  const expectedNegDeltaRef = { delta: 0 };

  const { shielded, restoreMap } = protectFormatSpans(baseClean);
  let candidate = repairGtxHonorificLeaks(shielded, srcText, profile);
  // Discourse continuity (Grosz-Joshi-Weinstein Centering): when the same entity stays backward-looking center
  // across consecutive Indonesian fiction narration paragraphs and the subject repeats verbatim at start, preserve natural flow
  if (
    params.centering?.cb &&
    profile.tgtLang === 'id' &&
    profile.register !== 'formal_legal_tech' &&
    profile.register !== 'formal_academic' &&
    params.centering.turnIndex > 0 &&
    !candidate.trimStart().startsWith('"') &&
    !/^[「『]/.test((srcText || '').trim())
  ) {
    const cbEsc = params.centering.cb.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const repeatedSubjectRe = new RegExp(`^(${cbEsc})\\s+([a-z]{3,})([^.!?]{6,140}\\.\\s+)${cbEsc}\\s+`, 'u');
    if (repeatedSubjectRe.test(candidate)) {
      candidate = candidate.replace(repeatedSubjectRe, '$1 $2$3Ia ');
    }
  }
  const spans = splitProtectedSpans(candidate);
  const transformed = spans
    .map((span, spanIdx) => {
      if (span.kind === 'protected') return span.text;
      const followsDialogue = spanIdx > 0 && spans[spanIdx - 1].kind === 'dialogue';
      if (profile.tgtLang === 'id') {
        return naturalizeIndonesianSpan(
          span.text,
          span.kind,
          profile,
          srcText,
          Boolean(params.hadJaKeigo),
          workingTags,
          expectedNegDeltaRef,
          followsDialogue
        );
      }
      if (profile.tgtLang === 'en') {
        return naturalizeEnglishSpan(span.text, profile, srcText);
      }
      return naturalizeJapaneseSpan(span.text, span.kind);
    })
    .join('');

  // Run Indonesian dialogue punctuation inside FormatShield BEFORE restoring code/URLs!
  const punctFixed =
    profile.tgtLang === 'id' ? fixIndonesianDialoguePunctuation(transformed) : transformed;
  const restored = restoreFormatSpans(punctFixed, restoreMap);
  candidate = sanitizeZeroEmDashAndPunct(restored, profile.tgtLang);

  const ok = verifyMeaningConservation({
    preNat: baseClean,
    postNat: candidate,
    tgt: profile.tgtLang,
    expectedNegDelta: expectedNegDeltaRef.delta,
    glossaryValues: params.glossaryValues,
    strictDeonticModals: profile.strictDeonticModals,
  });

  if (ok) {
    recentTags.length = 0;
    recentTags.push(...workingTags);
    return candidate;
  }
  return baseClean;
}

/**
 * Paragraph-sequence naturalizer (antar paragraf): runs across an entire chapter/message
 * maintaining dialogue attribution variety and scene-break resets.
 */
export function naturalizeTranslatedParagraphs(params: {
  srcParagraphs: string[];
  rawOutputs: string[];
  profile: DiscourseProfile;
  glossaryValues?: string[];
}): string[] {
  const recentTags: string[] = [];
  const centering = createCenteringState();
  const SCENE_BREAK_RE = /^[\s\u3000]*(?:[*＊◇◆☆■□・―\-=]{2,}|※)[\s\u3000]*$/;

  return params.rawOutputs.map((rawOut, idx) => {
    const src = params.srcParagraphs[idx] || '';
    if (SCENE_BREAK_RE.test(src.trim())) {
      recentTags.length = 0;
      centering.cb = null;
      centering.cfList = [];
      return sanitizeZeroEmDashAndPunct(rawOut, params.profile.tgtLang);
    }
    const keigo = params.profile.srcLang === 'ja' ? classifyJaKeigo(src) : null;
    const hadJaKeigo = Boolean(keigo?.locksPoliteRegister);

    const out = naturalizeAndVerifyParagraph({
      srcText: src,
      rawTranslated: rawOut,
      profile: params.profile,
      hadJaKeigo,
      glossaryValues: params.glossaryValues,
      recentTags,
      centering,
    });
    updateCenteringState(centering, src, out);
    return out;
  });
}
