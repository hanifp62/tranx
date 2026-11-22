export type SourceLang = 'auto' | 'id' | 'en' | 'ja';
export type TargetLang = 'id' | 'en' | 'ja';
export type ModePair =
  | 'auto-id'
  | 'auto-en'
  | 'auto-ja'
  | 'ja-id'
  | 'ja-en'
  | 'id-ja'
  | 'id-en'
  | 'en-id'
  | 'en-ja';
export type UiLang = 'id' | 'en';
export type ThemePref = 'system' | 'light' | 'dark';
export type TranslationTonePref = 'auto' | 'novel' | 'casual' | 'formal';
export type ResolvedTheme = 'Terang' | 'Gelap';
export type WorkTab = 'teks' | 'gambar' | 'dokumen' | 'link';
export type EntityKind = 'PERSON' | 'PLACE' | 'ORG' | 'TERM' | 'CULTURE';
export type TitleKind = 'novel' | 'komik' | 'dokumen' | 'subtitle' | 'web' | 'lepas';

export interface GlossaryEntry {
  surface: string;
  kind: EntityKind;
  reading: string;
  romaji: string;
  render_id: string;
  render_en: string;
  gloss_id: string;
  gloss_en: string;
  gender: 'm' | 'f' | '';
  aliases: string[];
  allow_compound: boolean;
  confirmed: boolean;
  source: 'user' | 'engine' | 'heuristic' | 'builtin' | string;
  score: number;
}

export interface TitleStyle {
  honorific_style: 'keep' | 'localize' | 'drop';
  name_order: 'jp' | 'western';
  romanization: 'macron' | 'kana' | 'plain';
}

export interface TitleDoc {
  id: string;
  name: string;
  kind: TitleKind;
  style: TitleStyle;
  description?: string;
  notes?: string;
  mergedInto?: string;
  updatedAt?: string;
}

export interface ConversationDoc {
  id: string;
  title: string;
  titleId: string;
  mode: ModePair;
  detectedSource?: TargetLang | '';
  activeTab: WorkTab;
  pinned: boolean;
  pinnedAt: number | null;
  preview: string;
  createdAt: number;
  updatedAt: number;
}

export interface SentencePair {
  i: number;
  src: string;
  dst: string;
}

export interface NameChipItem {
  surface: string;
  reading: string;
  romaji: string;
  dst: string;
  kind: EntityKind;
  confirmed: boolean;
  source: string;
}

export type VisionBlockKind =
  | 'dialogue'
  | 'shout'
  | 'thought'
  | 'narration'
  | 'sfx'
  | 'aside'
  | 'sign'
  | 'caption'
  | 'status_window';

export type VisionBlockShape = 'oval' | 'jagged' | 'rect' | 'cloud' | 'unbordered';
export type VisionBgTone = 'light' | 'dark' | 'artwork' | 'colored';
export type ComicLayoutMode =
  | 'rtl_manga'
  | 'webtoon_strip'
  | 'four_koma'
  | 'ltr_comic'
  | 'single_image';

export interface VisionBlock {
  id: number;
  box: [number, number, number, number]; // [x, y, w, h] in pixels
  src: string;
  dst: string;
  kind?: VisionBlockKind;
  shape?: VisionBlockShape;
  bgTone?: VisionBgTone;
  writingDir?: 'vertical' | 'horizontal';
  furiganaNote?: string;
  sfxImportance?: 'none' | 'ambient' | 'impact' | 'narrative' | 'major' | 'minor' | 'plot_critical';
  rows?: Array<[string, string]>;
}

export interface ImageTranslationResult {
  width: number;
  height: number;
  blocks: VisionBlock[];
  fullSrc: string;
  fullDst: string;
  model: string;
  dataUrl?: string;
  readingDir?: 'rtl' | 'ltr' | 'vertical';
  comicLayout?: ComicLayoutMode;
  isSpread?: boolean;
}

export interface MangaPageItem {
  index: number;
  url: string;
  alt?: string;
  width?: number;
  height?: number;
  possibleCredit?: boolean;
}

export interface MangaLinkMeta {
  isComic: boolean;
  isDirectImage: boolean;
  layout: ComicLayoutMode;
  pageCount: number;
  pages: MangaPageItem[];
  drmProtected?: boolean;
  drmReason?: string;
  sourceHint?: string;
}

export interface NovelChapterLink {
  title: string;
  titleDst?: string;
  url: string;
  current?: boolean;
}

export interface NovelNavigation {
  isNovel: boolean;
  isTocPage?: boolean;
  seriesTitle?: string;
  chapterLabel?: string;
  totalChapters?: number;
  currentIndex?: number;
  firstUrl?: string | null;
  prevUrl?: string | null;
  nextUrl?: string | null;
  tocUrl?: string | null;
  chapters?: NovelChapterLink[];
}

export interface LinkPreviewPayload {
  mid: string;
  cid: string;
  titleId: string;
  url: string;
  host: string;
  isAozora: boolean;
  titleSrc: string;
  titleDst: string;
  excerptSrc: string;
  excerptDst: string;
  paragraphCount: number;
  lockedNames: number;
  readerSupported: boolean;
  novelNav?: NovelNavigation;
  comicMeta?: MangaLinkMeta;
  firstImageResult?: ImageTranslationResult;
}

export interface WebReaderBundle {
  url: string;
  host: string;
  titleId: string;
  detectedSource: TargetLang;
  titleSrc: string;
  titleDst: string;
  sentences: SentencePair[];
  novelNav: NovelNavigation;
  siteHtml?: string;
  comicMeta?: MangaLinkMeta;
  firstImageResult?: ImageTranslationResult;
}

export type TurnState =
  | 'running'
  | 'done'
  | 'partial'
  | 'stopped'
  | 'busy'
  | 'error';

export interface TurnMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: 'text' | 'long' | 'image' | 'document' | 'link';
  mode: ModePair;
  detectedSource?: TargetLang;
  titleId?: string;
  text: string;
  srcText?: string;
  sentences?: SentencePair[];
  nameChips?: NameChipItem[];
  fileName?: string;
  fmt?: string;
  jobId?: string;
  storageOutputPath?: string | null;
  done?: number;
  total?: number;
  imageResult?: ImageTranslationResult;
  linkPreview?: LinkPreviewPayload;
  state: TurnState;
  model?: string;
  ms?: number;
  error?: string;
  createdAt: number;
}

export interface PendingAttachment {
  id: string;
  file?: File;
  name: string;
  sizeBytes: number;
  ext: string;
  status: 'checking' | 'ready' | 'reading' | 'error' | 'unsupported';
  reason?: string;
  previewUrl?: string;
}

export interface EbookPrefsSync {
  themeMode?: 'adaptive' | 'locked';
  dayTheme?: 'paper' | 'sepia' | 'sage' | 'eink';
  nightTheme?: 'dusk' | 'midnight';
  lockedTheme?: 'paper' | 'sepia' | 'sage' | 'dusk' | 'midnight' | 'eink';
  fontId?: string;
  fontSize?: number;
  lineHeight?: number;
  letterSpacing?: number;
  wordSpacing?: number;
  paragraphSpacing?: number;
  measure?: 'narrow' | 'standard' | 'wide';
  align?: 'left' | 'justify';
  pageMode?: 'scroll' | 'slide' | 'flip';
  spread?: 'single' | 'auto';
  inlinePeek?: boolean;
  readingRuler?: 'off' | 'bar' | 'shade' | 'underline';
  tapZone?: 'edges' | 'right-hand' | 'left-hand';
}

export interface AppSettingsDoc {
  llmModels: string[];
  reasoningEffort: 'none' | 'low' | 'medium';
  chatMaxChars: number;
  longMaxChars: number;
  maxUploadMb: number;
  dailyCharCap: number;
  dailyCallCap: number;
  defaultSource: SourceLang;
  defaultTarget: TargetLang;
  uiLang: UiLang;
  theme: ThemePref;
  translationTone?: TranslationTonePref;
  ebookPrefs?: EbookPrefsSync;
}

export interface JobDoc {
  id: string;
  cid: string;
  mid: string;
  titleId?: string;
  fileName: string;
  fileSize: number;
  fmt?: string;
  state: 'uploading' | 'queued' | 'running' | 'done' | 'partial' | 'stopped' | 'error';
  doneParas?: number;
  totalParas?: number;
  storagePath?: string;
  storageOutputPath?: string | null;
  message?: string;
  updatedAt: number;
}

export interface InboxItem {
  id: string;
  text: string;
  url?: string | null;
  title?: string | null;
  createdAt: number;
}

export interface ToastItem {
  id: string;
  message: string;
  undoLabel?: string;
  onUndo?: () => void;
}
