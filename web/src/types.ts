export type ModePair = 'ja-id' | 'ja-en';
export type UiLang = 'id' | 'en';
export type ThemePref = 'system' | 'light' | 'dark';
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

export interface VisionBlock {
  id: number;
  box: [number, number, number, number]; // [x, y, w, h] in pixels
  src: string;
  dst: string;
}

export interface ImageTranslationResult {
  width: number;
  height: number;
  blocks: VisionBlock[];
  fullSrc: string;
  fullDst: string;
  model: string;
  dataUrl?: string;
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
  status: 'ready' | 'reading' | 'error' | 'unsupported';
  reason?: string;
  previewUrl?: string;
}

export interface AppSettingsDoc {
  llmModels: string[];
  reasoningEffort: 'none' | 'low' | 'medium';
  chatMaxChars: number;
  longMaxChars: number;
  maxUploadMb: number;
  dailyCharCap: number;
  dailyCallCap: number;
  defaultTarget: 'id' | 'en';
  uiLang: UiLang;
  theme: ThemePref;
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
