import {
  Suspense,
  lazy,
  memo,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useDialogFocusTrap } from '../lib/useDialogFocusTrap';
import type {
  EntityKind,
  GlossaryEntry,
  JobDoc,
  ModePair,
  ResolvedTheme,
  SentencePair,
  TitleDoc,
  TitleKind,
  TitleStyle,
  TurnMessage,
  WebReaderBundle,
} from '../types';
import type { UiStrings } from '../i18n/strings';
import {
  buildEbookSurfaceStyle,
  ensureEbookFontLoaded,
  estimateReadingMinutes,
  getEbookFontSpec,
  getTapZoneBounds,
  loadEbookPrefs,
  pickSyncableEbookPrefs,
  resolveEbookThemeSpec,
  saveEbookPrefs,
  syncDocumentThemeColor,
  type EbookPrefs,
} from '../lib/ebookPrefs';
import {
  AUTO_SCROLL_SPEEDS,
  createEbookAutoScrollController,
  createPodcastNarratorController,
  findPageIndexForParagraph,
  isTtsSupported,
  loadSpeechVoices,
  paginateEbookParagraphs,
  PODCAST_RATES,
  rankVoicesForLang,
  scrollActiveParagraphIntoComfortZone,
  type AutoScrollSpeedPreset,
  type AutoScrollState,
  type BookPageSlice,
  type EbookAutoScrollController,
  type PodcastCastMode,
  type PodcastNarratorController,
  type PodcastSleepPreset,
  type PodcastStyleId,
  type RankedVoiceOption,
  type SpeechSegmentKind,
  type TtsPlaybackState,
  type TtsRate,
} from '../lib/ebookService';
import {
  getChapterParaPos,
  listBookmarks,
  removeBookmark,
  saveChapterParaPos,
  saveRichReadingEntry,
  toggleBookmark,
  type EbookBookmarkItem,
} from '../lib/ebookStorage';
import {
  classifyDocumentFormat,
  type DocumentFormatId,
} from '../lib/podcastNarrator';

const EbookAppearancePanel = lazy(() =>
  import('./EbookAppearancePanel').then((m) => ({ default: m.EbookAppearancePanel }))
);
const MangaLinkReader = lazy(() =>
  import('./MangaLinkReader').then((m) => ({ default: m.MangaLinkReader }))
);
import {
  downloadExportedTurn,
  fetchWebReaderBundle,
  mergeTitleGlossaries,
} from '../lib/api';
import {
  buildAutoTranslatedSiteUrl,
  getReadingProgress,
  parseModePair,
  prefetchNextChapterTranslatedDirect,
  toSafeHttpUrl,
  translateChapterTitlesDirect,
} from '../lib/directEngine';
import {
  DEFAULT_STYLE,
  removeGlossaryEntry,
  resolveStorageOutputUrl,
  saveTitleDoc,
  subscribeGlossary,
  updateAppSettings,
  upsertUserGlossaryEntry,
  type AuthSessionUser,
} from '../lib/firebase';
import {
  IconAutoScroll,
  IconBook,
  IconBookmark,
  IconCheck,
  IconColumns,
  IconDots,
  IconDownload,
  IconEye,
  IconGlobe,
  IconHeadphones,
  IconLink,
  IconMenu,
  IconPause,
  IconPlay,
  IconPlus,
  IconSkipBack,
  IconSkipForward,
  IconSliders,
  IconTrash,
  IconX,
} from './Icons';

/* /berkas: Berkas Saya */
export function MyFilesView({
  user,
  jobs,
  resolvedTheme,
  strings,
  onNavigate,
  onNotify,
}: {
  user: AuthSessionUser;
  jobs: JobDoc[];
  resolvedTheme: ResolvedTheme;
  strings: UiStrings;
  onNavigate: (path: string) => void;
  onNotify: (msg: string) => void;
}) {
  const handleDownloadFormat = async (job: JobDoc, fmt: string) => {
    try {
      if (fmt === 'storage' && job.storageOutputPath) {
        const url = await resolveStorageOutputUrl(job.storageOutputPath);
        window.open(url, '_blank', 'noopener,noreferrer');
        return;
      }
      const { blob, filename } = await downloadExportedTurn({
        user,
        cid: job.cid,
        mid: job.mid,
        fmt,
        theme: resolvedTheme,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Gagal mengunduh berkas.');
    }
  };

  return (
    <div className="subpage-container">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: '22px', lineHeight: '28px' }}>{strings.myFiles}</h1>
          <p style={{ margin: '4px 0 0 0', fontSize: '14px', color: 'var(--text-muted)' }}>
            Dokumen yang telah diunggah dan diterjemahkan beserta pilihan ekspor ulang tanpa
            panggilan model tambahan.
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary pressable"
          onClick={() => onNavigate('/')}
        >
          Kembali ke ruang baca
        </button>
      </div>

      {jobs.length === 0 ? (
        <div className="result-card">
          <div style={{ fontWeight: 600 }}>Belum ada berkas terjemahan</div>
          <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
            Buka moda Dokumen di panggung utama lalu pilih berkas .epub, .pdf, .docx, .srt, .vtt,
            .ass, .html, .md, atau .txt hingga 50 MB.
          </div>
          <div>
            <button
              type="button"
              className="btn-primary pressable"
              onClick={() => onNavigate('/?tab=dokumen')}
            >
              Terjemahkan dokumen pertama
            </button>
          </div>
        </div>
      ) : (
        jobs.map((job) => (
          <div key={job.id} className="result-card files-row">
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '10px',
                flexWrap: 'wrap',
              }}
            >
              <div>
                <div style={{ fontWeight: 600, fontSize: '15px' }}>{job.fileName}</div>
                <div style={{ fontSize: '12px', color: 'var(--text-subtle)' }}>
                  {(job.fileSize / 1024).toFixed(1)} KB ·{' '}
                  {job.doneParas !== undefined && job.totalParas !== undefined
                    ? `${job.doneParas}/${job.totalParas} paragraf`
                    : job.state}
                </div>
              </div>
              <span
                className={`status-badge ${job.state === 'done'
                  ? 'done'
                  : job.state === 'error'
                    ? 'error'
                    : job.state === 'running' || job.state === 'uploading'
                      ? 'running'
                      : 'warning'
                  }`}
              >
                {job.state === 'done'
                  ? 'Selesai'
                  : job.state === 'running'
                    ? 'Berjalan'
                    : job.state === 'error'
                      ? 'Galat'
                      : job.state}
              </span>
            </div>

            {job.cid && job.mid && (
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="btn-primary pressable"
                  onClick={() => onNavigate(`/c/${job.cid}/m/${job.mid}/baca`)}
                >
                  <IconColumns size={16} />
                  {strings.readSideBySide}
                </button>
                {(
                  [
                    'html',
                    'docx',
                    'srt',
                    ...(job.fmt === 'ass' || job.fmt === 'ssa' ? (['ass'] as const) : []),
                    ...(job.fmt === 'vtt' ? (['vtt'] as const) : []),
                    'txt',
                    'md',
                  ] as const
                ).map((fmt) => (
                  <button
                    key={fmt}
                    type="button"
                    className="btn-secondary pressable"
                    onClick={() => handleDownloadFormat(job, fmt)}
                  >
                    <IconDownload size={16} />.{fmt}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

/* /kamus & /kamus/:titleId: Daftar Nama (14-field GlossaryEntry + Gaya + Merge) */
export function GlossaryView({
  user,
  titles,
  activeTitleId,
  strings,
  onNavigate,
  onNotify,
}: {
  user: AuthSessionUser;
  titles: TitleDoc[];
  activeTitleId?: string;
  strings: UiStrings;
  onNavigate: (path: string) => void;
  onNotify: (msg: string) => void;
}) {
  const selectedId = activeTitleId || titles[0]?.id || 't_default';
  const selectedTitle: TitleDoc = titles.find((t) => t.id === selectedId) || {
    id: selectedId,
    name: selectedId === 't_default' ? 'Kamus Utama' : 'Kamus Bacaan',
    kind: 'lepas',
    style: { ...DEFAULT_STYLE },
  };
  const [entries, setEntries] = useState<Array<{ key: string; entry: GlossaryEntry }>>([]);
  const [newTitleName, setNewTitleName] = useState('');
  const [newTitleKind, setNewTitleKind] = useState<TitleKind>('novel');
  const [mergeTargetId, setMergeTargetId] = useState('');

  const [surface, setSurface] = useState('');
  const [kind, setKind] = useState<EntityKind>('PERSON');
  const [reading, setReading] = useState('');
  const [romaji, setRomaji] = useState('');
  const [renderId, setRenderId] = useState('');
  const [renderEn, setRenderEn] = useState('');
  const [glossId, setGlossId] = useState('');
  const [glossEn, setGlossEn] = useState('');
  const [gender, setGender] = useState<'m' | 'f' | ''>('');
  const [aliasesText, setAliasesText] = useState('');
  const [allowCompound, setAllowCompound] = useState(false);

  useEffect(() => {
    if (!selectedId) {
      setEntries([]);
      return;
    }
    return subscribeGlossary(selectedId, setEntries);
  }, [selectedId]);

  const handleCreateTitle = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitleName.trim()) return;
    const tid = `t_${Date.now().toString(36)}`;
    await saveTitleDoc(tid, {
      name: newTitleName.trim(),
      kind: newTitleKind,
      style: { ...DEFAULT_STYLE },
    });
    setNewTitleName('');
    onNavigate(`/kamus/${tid}`);
    onNotify('Judul karya baru ditambahkan');
  };

  const handleAddGlossaryEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId || !surface.trim()) return;
    await upsertUserGlossaryEntry(selectedId, {
      surface: surface.trim(),
      kind,
      reading: reading.trim(),
      romaji: romaji.trim(),
      render_id: renderId.trim() || romaji.trim(),
      render_en: renderEn.trim() || romaji.trim(),
      gloss_id: glossId.trim(),
      gloss_en: glossEn.trim(),
      gender,
      aliases: aliasesText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      allow_compound: allowCompound,
      score: 1.0,
    });
    setSurface('');
    setReading('');
    setRomaji('');
    setRenderId('');
    setRenderEn('');
    setGlossId('');
    setGlossEn('');
    setGender('');
    setAliasesText('');
    setAllowCompound(false);
    onNotify('Entri nama berhasil dikunci');
  };

  const handleStyleChange = async (patch: Partial<TitleStyle>) => {
    if (!selectedTitle) return;
    await saveTitleDoc(selectedTitle.id, {
      name: selectedTitle.name,
      kind: selectedTitle.kind,
      style: { ...selectedTitle.style, ...patch },
      notes: selectedTitle.notes,
    });
    onNotify('Gaya penulisan nama disimpan');
  };

  const handleMerge = async () => {
    if (!selectedId || !mergeTargetId || selectedId === mergeTargetId) return;
    try {
      const res = await mergeTitleGlossaries(user, selectedId, mergeTargetId);
      onNavigate(`/kamus/${mergeTargetId}`);
      onNotify(`${res.merged} entri digabungkan ke judul tujuan`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Gagal menggabungkan daftar nama.');
    }
  };

  return (
    <div className="subpage-container">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: '22px', lineHeight: '28px' }}>{strings.glossary}</h1>
          <p style={{ margin: '4px 0 0 0', fontSize: '14px', color: 'var(--text-muted)' }}>
            Kunci ejaan tokoh, tempat, istilah, dan gaya sapaan Jepang per judul karya.
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary pressable"
          onClick={() => onNavigate('/')}
        >
          Kembali ke ruang baca
        </button>
      </div>

      <form onSubmit={handleCreateTitle} className="result-card">
        <div style={{ fontWeight: 600, fontSize: '15px' }}>Tambah judul karya atau seri</div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <input
            className="field-input"
            style={{ flex: '1 1 220px' }}
            aria-label="Judul karya atau seri baru"
            placeholder="Contoh: Rashomon atau Bab Manga..."
            value={newTitleName}
            onChange={(e) => setNewTitleName(e.target.value)}
            required
          />
          <select
            className="field-select"
            value={newTitleKind}
            onChange={(e) => setNewTitleKind(e.target.value as TitleKind)}
            aria-label="Jenis karya"
          >
            <option value="novel">Novel</option>
            <option value="komik">Komik / Manga</option>
            <option value="dokumen">Dokumen</option>
            <option value="subtitle">Takarir (.srt/.ass)</option>
            <option value="web">Situs Web</option>
            <option value="lepas">Percakapan Lepas</option>
          </select>
          <button type="submit" className="btn-primary pressable">
            <IconPlus size={16} />
            Buat judul
          </button>
        </div>
      </form>

      {titles.length > 0 && (
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {titles.map((t) => (
            <button
              key={t.id}
              type="button"
              className={
                t.id === selectedId ? 'btn-primary pressable' : 'btn-secondary pressable'
              }
              onClick={() => onNavigate(`/kamus/${t.id}`)}
            >
              <IconBook size={16} />
              {t.name}
            </button>
          ))}
        </div>
      )}

      {selectedTitle && (
        <>
          <div className="result-card">
            <div style={{ fontWeight: 600, fontSize: '15px' }}>
              Gaya sapaan & urutan nama: {selectedTitle.name}
            </div>
            <div className="form-grid-2">
              <label className="field-label">
                <span>Akhiran sapaan (-san, -kun, -sama)</span>
                <select
                  className="field-select"
                  value={selectedTitle.style.honorific_style}
                  onChange={(e) =>
                    handleStyleChange({
                      honorific_style: e.target.value as TitleStyle['honorific_style'],
                    })
                  }
                >
                  <option value="keep">Pertahankan (-san, -kun)</option>
                  <option value="localize">Lokalkan (Tuan, Kak, Pak)</option>
                  <option value="drop">Tanggalkan sapaan</option>
                </select>
              </label>

              <label className="field-label">
                <span>Romanisasi vokal panjang</span>
                <select
                  className="field-select"
                  value={selectedTitle.style.romanization}
                  onChange={(e) =>
                    handleStyleChange({
                      romanization: e.target.value as TitleStyle['romanization'],
                    })
                  }
                >
                  <option value="macron">Makron (Tōkyō)</option>
                  <option value="plain">Polos (Tokyo)</option>
                  <option value="kana">Ejaan kana (Toukyou)</option>
                </select>
              </label>
            </div>

            {titles.length > 1 && (
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                <select
                  className="field-select"
                  value={mergeTargetId}
                  onChange={(e) => setMergeTargetId(e.target.value)}
                  aria-label="Pilih judul tujuan penggabungan"
                >
                  <option value="">Gabungkan kamus ini ke judul lain...</option>
                  {titles
                    .filter((t) => t.id !== selectedId)
                    .map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                </select>
                <button
                  type="button"
                  className="btn-secondary pressable"
                  disabled={!mergeTargetId}
                  onClick={handleMerge}
                >
                  Gabungkan judul
                </button>
              </div>
            )}
          </div>

          <form onSubmit={handleAddGlossaryEntry} className="result-card">
            <div style={{ fontWeight: 600, fontSize: '15px' }}>
              Kunci entri baru pada {selectedTitle.name}
            </div>
            <div className="form-grid-2">
              <label className="field-label">
                <span>Kanji / Kana sumber (surface)</span>
                <input
                  className="field-input"
                  style={{ fontFamily: 'var(--font-jp)' }}
                  placeholder="Contoh: 鴉羽"
                  value={surface}
                  onChange={(e) => setSurface(e.target.value)}
                  required
                />
              </label>
              <label className="field-label">
                <span>Kategori entitas</span>
                <select
                  className="field-select"
                  value={kind}
                  onChange={(e) => setKind(e.target.value as EntityKind)}
                >
                  <option value="PERSON">Tokoh (PERSON)</option>
                  <option value="PLACE">Tempat (PLACE)</option>
                  <option value="ORG">Organisasi (ORG)</option>
                  <option value="TERM">Istilah khusus (TERM)</option>
                  <option value="CULTURE">Budaya (CULTURE)</option>
                </select>
              </label>
              <label className="field-label">
                <span>Bacaan kana (reading)</span>
                <input
                  className="field-input"
                  style={{ fontFamily: 'var(--font-jp)' }}
                  placeholder="Contoh: からすば"
                  value={reading}
                  onChange={(e) => setReading(e.target.value)}
                />
              </label>
              <label className="field-label">
                <span>Ejaan Romaji</span>
                <input
                  className="field-input"
                  placeholder="Contoh: Karasuba"
                  value={romaji}
                  onChange={(e) => setRomaji(e.target.value)}
                />
              </label>
              <label className="field-label">
                <span>Tampilan bahasa Indonesia (render_id)</span>
                <input
                  className="field-input"
                  placeholder="Contoh: Karasuba"
                  value={renderId}
                  onChange={(e) => setRenderId(e.target.value)}
                />
              </label>
              <label className="field-label">
                <span>Tampilan bahasa Inggris (render_en)</span>
                <input
                  className="field-input"
                  placeholder="Contoh: Karasuba"
                  value={renderEn}
                  onChange={(e) => setRenderEn(e.target.value)}
                />
              </label>
              <label className="field-label">
                <span>Gender tokoh</span>
                <select
                  className="field-select"
                  value={gender}
                  onChange={(e) => setGender(e.target.value as 'm' | 'f' | '')}
                >
                  <option value="">Tidak ditentukan</option>
                  <option value="f">Perempuan (f)</option>
                  <option value="m">Laki-laki (m)</option>
                </select>
              </label>
              <label className="field-label">
                <span>Alias (pisahkan dengan koma)</span>
                <input
                  className="field-input"
                  placeholder="Contoh: カラスバ"
                  value={aliasesText}
                  onChange={(e) => setAliasesText(e.target.value)}
                />
              </label>
              <label className="field-label">
                <span>Catatan makna Indonesia (gloss_id)</span>
                <input
                  className="field-input"
                  placeholder="Keterangan opsional..."
                  value={glossId}
                  onChange={(e) => setGlossId(e.target.value)}
                />
              </label>
              <label className="field-label">
                <span>Catatan makna Inggris (gloss_en)</span>
                <input
                  className="field-input"
                  placeholder="Optional gloss..."
                  value={glossEn}
                  onChange={(e) => setGlossEn(e.target.value)}
                />
              </label>
            </div>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
              <input
                type="checkbox"
                checked={allowCompound}
                onChange={(e) => setAllowCompound(e.target.checked)}
              />
              Izinkan pencocokan di dalam kata majemuk (allow_compound)
            </label>
            <div>
              <button type="submit" className="btn-primary pressable">
                {strings.lockName}
              </button>
            </div>
          </form>

          <div className="result-card">
            <div style={{ fontWeight: 600, fontSize: '15px' }}>
              Daftar entri terkunci ({entries.length})
            </div>
            {entries.length === 0 ? (
              <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                Belum ada entri nama terkunci pada judul ini. Tambahkan di formulir atas atau ketuk
                chip nama langsung dari hasil terjemahan.
              </div>
            ) : (
              entries.map(({ key, entry }) => (
                <div
                  key={key}
                  className="glossary-row"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px',
                    padding: '10px 0',
                    borderTop: '1px solid var(--border)',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontFamily: 'var(--font-jp)', fontWeight: 600 }}>
                        {entry.surface}
                      </span>
                      {entry.reading && (
                        <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                          ({entry.reading})
                        </span>
                      )}
                      <span className="status-badge done">{entry.kind}</span>
                    </div>
                    <div style={{ fontSize: '14px', marginTop: '2px' }}>
                      ID: <strong>{entry.render_id || entry.romaji}</strong> · EN:{' '}
                      <strong>{entry.render_en || entry.romaji}</strong>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="btn-danger pressable"
                    aria-label={`Hapus ${entry.surface}`}
                    onClick={() => removeGlossaryEntry(selectedId, key)}
                  >
                    <IconTrash size={16} />
                  </button>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* /web?url=...: Unified Ebook Reader v2 (Dual-Slot Themes, Paragraph-Anchored Spread, Calm HUD, Scrubber, Bookmarks, Inline Peek, TTS) */
export function TranslatedWebViewer({
  user,
  url,
  initialMode,
  initialView = 'reader',
  initialPos,
  titleId,
  backPath = '/',
  resolvedTheme,
  strings,
  onNavigate,
}: {
  user: AuthSessionUser;
  url: string;
  initialMode: ModePair;
  initialView?: 'reader' | 'site' | 'original';
  initialPos?: string;
  titleId?: string;
  backPath?: string;
  resolvedTheme?: ResolvedTheme;
  strings: UiStrings;
  onNavigate: (path: string) => void;
}) {
  const [mode, setMode] = useState<ModePair>(initialMode);
  const [view, setView] = useState<'reader' | 'site' | 'original'>(initialView);
  const [bilingual, setBilingual] = useState(false);
  const [isMobile, setIsMobile] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.innerWidth < 768 : false
  );
  const [viewportW, setViewportW] = useState<number>(() =>
    typeof window !== 'undefined' ? window.innerWidth : 1280
  );
  const [viewportH, setViewportH] = useState<number>(() =>
    typeof window !== 'undefined' ? window.innerHeight : 800
  );
  const [ebookPrefs, setEbookPrefs] = useState<EbookPrefs>(() => loadEbookPrefs());
  const ebookPrefsRef = useRef<EbookPrefs>(ebookPrefs);
  ebookPrefsRef.current = ebookPrefs;
  const stringsRef = useRef<UiStrings>(strings);
  stringsRef.current = strings;
  const isPaginatedModeRef = useRef(false);
  const lastAutoScrollTouchPauseRef = useRef<number>(0);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const [hudHidden, setHudHidden] = useState(false);
  const [pageIndex, setPageIndex] = useState(0);
  const [anchorParaIdx, setAnchorParaIdx] = useState(0);
  const anchorParaRef = useRef(0);
  const pendingPositionRef = useRef<string | null>(initialPos || null);
  const [turnAnim, setTurnAnim] = useState<{ dir: 'next' | 'prev'; seq: number } | null>(null);
  const [tapCue, setTapCue] = useState<{ side: 'left' | 'right'; seq: number } | null>(null);
  const bookLeafRef = useRef<HTMLDivElement | null>(null);
  const bookDragRef = useRef<{
    startX: number;
    startY: number;
    t: number;
    locked: 'none' | 'h' | 'v';
    lastDx: number;
    stageW: number;
  } | null>(null);
  const dragSuppressClickRef = useRef<number>(0);
  const reducedMotionRef = useRef<boolean>(
    typeof window !== 'undefined'
      ? (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
      : false
  );
  const touchMoveRafRef = useRef<number>(0);
  const lastViewportRef = useRef<{ w: number; h: number }>({
    w: typeof window !== 'undefined' ? window.innerWidth : 1280,
    h: typeof window !== 'undefined' ? window.innerHeight : 800,
  });
  const [peekedParas, setPeekedParas] = useState<Record<number, boolean>>({});
  const [chapterModalTab, setChapterModalTab] = useState<'chapters' | 'bookmarks'>('chapters');
  const [bookmarks, setBookmarks] = useState<EbookBookmarkItem[]>([]);
  const [inlineToast, setInlineToast] = useState<string | null>(null);
  // Podcast-Grade Audio Narration State (100-Literature Prosody Engine)
  const [ttsState, setTtsState] = useState<TtsPlaybackState>('idle');
  const [ttsParaIdx, setTtsParaIdx] = useState<number | null>(null);
  const [ttsKind, setTtsKind] = useState<SpeechSegmentKind>('narration');
  const [ttsRate, setTtsRate] = useState<TtsRate>(1);
  const [podcastStyle, setPodcastStyle] = useState<PodcastStyleId>('podcast_santai');
  const [podcastFormatOverride, setPodcastFormatOverride] = useState<'auto' | DocumentFormatId>('auto');
  const [podcastVoiceUri, setPodcastVoiceUri] = useState<string>('');
  const [podcastCastMode, setPodcastCastMode] = useState<PodcastCastMode>('persona');
  const [activeSpeakerName, setActiveSpeakerName] = useState<string | null>(null);
  const [podcastLocalFallback, setPodcastLocalFallback] = useState(false);
  const [sleepCountdownSeed, setSleepCountdownSeed] = useState<{ sec: number; seq: number }>({
    sec: 0,
    seq: 0,
  });
  const [rankedVoices, setRankedVoices] = useState<RankedVoiceOption[]>([]);
  const [sleepPreset, setSleepPreset] = useState<PodcastSleepPreset>('off');
  const [podcastStudioOpen, setPodcastStudioOpen] = useState(false);
  const [podcastUserDetached, setPodcastUserDetached] = useState(false);
  const [focusedParaIdx, setFocusedParaIdx] = useState<number | null>(null);
  const [jumpBackParaIdx, setJumpBackParaIdx] = useState<number | null>(null);
  const lastScrollEventTsRef = useRef<number>(0);
  const podcastUserDetachedRef = useRef(false);
  podcastUserDetachedRef.current = podcastUserDetached;
  const programmaticScrollUntilRef = useRef<number>(0);
  const ttsCtrlRef = useRef<PodcastNarratorController | null>(null);
  // Hands-Free Auto-Scroll State (Single Scroll-Owner with Podcast)
  const [autoScrollState, setAutoScrollState] = useState<AutoScrollState>('idle');
  const [autoScrollSpeed, setAutoScrollSpeed] = useState<AutoScrollSpeedPreset>(1);
  const autoScrollCtrlRef = useRef<EbookAutoScrollController | null>(null);
  const prefsSyncTimerRef = useRef<number | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const autoScrollDelayTimerRef = useRef<number | null>(null);
  const leafSnapTimerRef = useRef<number | null>(null);

  const [readerMenuOpen, setReaderMenuOpen] = useState(false);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const readerMenuDialogRef = useRef<HTMLDivElement | null>(null);
  const chaptersDialogRef = useRef<HTMLDivElement | null>(null);
  useDialogFocusTrap(readerMenuDialogRef, () => setReaderMenuOpen(false), readerMenuOpen);
  useDialogFocusTrap(chaptersDialogRef, () => setChaptersOpen(false), chaptersOpen);
  const [chapterQuery, setChapterQuery] = useState('');
  const deferredChapterQuery = useDeferredValue(chapterQuery);
  const [translatedTitlesByKey, setTranslatedTitlesByKey] = useState<
    Record<string, Record<string, string>>
  >({});
  const [chapterTranslateProgress, setChapterTranslateProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [bundle, setBundle] = useState<WebReaderBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [streamProgress, setStreamProgress] = useState<{ done: number; total: number } | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const progressBarRef = useRef<HTMLDivElement | null>(null);
  const autoTranslatedSiteUrl = buildAutoTranslatedSiteUrl(url, mode);
  const safeExternalUrl = toSafeHttpUrl(url);
  const appTheme: ResolvedTheme = resolvedTheme || 'Terang';

  const flashReaderToast = useCallback((msg: string) => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    setInlineToast(msg);
    toastTimerRef.current = window.setTimeout(() => {
      toastTimerRef.current = null;
      setInlineToast((cur) => (cur === msg ? null : cur));
    }, 2400);
  }, []);

  const updateEbookPrefs = useCallback((patch: Partial<EbookPrefs>) => {
    const next = saveEbookPrefs({ ...ebookPrefsRef.current, ...patch });
    ebookPrefsRef.current = next;
    setEbookPrefs(next);
    if (prefsSyncTimerRef.current !== null) window.clearTimeout(prefsSyncTimerRef.current);
    prefsSyncTimerRef.current = window.setTimeout(() => {
      prefsSyncTimerRef.current = null;
      void updateAppSettings({
        ebookPrefs: pickSyncableEbookPrefs(next),
      }).catch(() => { });
    }, 450);
  }, []);

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const onMq = (e: MediaQueryListEvent) => {
      reducedMotionRef.current = e.matches;
    };
    mq?.addEventListener?.('change', onMq);
    return () => {
      mq?.removeEventListener?.('change', onMq);
      if (prefsSyncTimerRef.current !== null) window.clearTimeout(prefsSyncTimerRef.current);
      if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
      if (autoScrollDelayTimerRef.current !== null) window.clearTimeout(autoScrollDelayTimerRef.current);
      if (leafSnapTimerRef.current !== null) window.clearTimeout(leafSnapTimerRef.current);
      if (touchMoveRafRef.current) window.cancelAnimationFrame(touchMoveRafRef.current);
      ttsCtrlRef.current?.stop();
      autoScrollCtrlRef.current?.stop();
    };
  }, []);

  useEffect(() => {
    ensureEbookFontLoaded(ebookPrefs.fontId);
  }, [ebookPrefs.fontId]);

  useEffect(() => {
    setView(initialView);
  }, [initialView, url]);

  useEffect(() => {
    setMode(initialMode);
  }, [initialMode]);

  useEffect(() => {
    pendingPositionRef.current = initialPos || null;
  }, [initialPos, url]);

  useEffect(() => {
    let rafId = 0;
    const onResize = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = 0;
        const nextW = window.innerWidth;
        const nextH = window.innerHeight;
        const prev = lastViewportRef.current;
        const widthChanged = nextW !== prev.w;
        const heightDelta = Math.abs(nextH - prev.h);
        // Ignore <90px vertical-only mobile address-bar collapse/expand jitter
        if (!widthChanged && heightDelta < 90) return;
        lastViewportRef.current = { w: nextW, h: nextH };
        setIsMobile(nextW < 768);
        setViewportW(nextW);
        setViewportH(nextH);
      });
    };
    window.addEventListener('resize', onResize, { passive: true });
    return () => {
      if (rafId) window.cancelAnimationFrame(rafId);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  useEffect(() => {
    if (!readerMenuOpen && !chaptersOpen && !(isMobile && appearanceOpen)) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setReaderMenuOpen(false);
        setChaptersOpen(false);
        setAppearanceOpen(false);
        setToolsMenuOpen(false);
      }
    };
    window.addEventListener('keydown', onEsc);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener('keydown', onEsc);
    };
  }, [readerMenuOpen, chaptersOpen, appearanceOpen, isMobile]);

  // Only re-fetch when OS theme changes if currently rendering external site iframe HTML
  const siteFetchTheme = view === 'site' ? resolvedTheme : undefined;

  useEffect(() => {
    let active = true;
    const ctrl = new AbortController();
    restoredForUrlRef.current = '';
    if (autoScrollDelayTimerRef.current !== null) {
      window.clearTimeout(autoScrollDelayTimerRef.current);
      autoScrollDelayTimerRef.current = null;
    }
    if (leafSnapTimerRef.current !== null) {
      window.clearTimeout(leafSnapTimerRef.current);
      leafSnapTimerRef.current = null;
    }
    ttsCtrlRef.current?.stop();
    autoScrollCtrlRef.current?.stop();
    setTtsState('idle');
    setTtsParaIdx(null);
    setPodcastStudioOpen(false);
    setPodcastUserDetached(false);
    setAutoScrollState('idle');
    setTapCue(null);
    setLoading(true);
    setStreamProgress(null);
    setErrorMsg(null);
    setReaderMenuOpen(false);
    setChaptersOpen(false);
    setAppearanceOpen(false);
    setToolsMenuOpen(false);
    setHudHidden(false);
    setPeekedParas({});
    setPageIndex(0);
    setAnchorParaIdx(0);
    anchorParaRef.current = 0;
    setJumpBackParaIdx(null);
    setFocusedParaIdx(null);
    setTurnAnim(null);
    setChapterQuery('');
    window.scrollTo({ top: 0 });
    fetchWebReaderBundle({
      user,
      url,
      mode,
      titleId,
      view,
      theme: siteFetchTheme,
      signal: ctrl.signal,
      onProgress: (partial, doneCount, totalCount) => {
        if (!active || ctrl.signal.aborted) return;
        setBundle(partial);
        setLoading(false);
        setStreamProgress(doneCount < totalCount ? { done: doneCount, total: totalCount } : null);
      },
    })
      .then((res) => {
        if (active && !ctrl.signal.aborted) {
          setBundle(res);
          setLoading(false);
          setStreamProgress(null);
        }
      })
      .catch((err) => {
        if (active && !ctrl.signal.aborted && (err as { name?: string })?.name !== 'AbortError') {
          setErrorMsg(
            err instanceof Error ? err.message : 'Halaman web tidak dapat dimuat.'
          );
          setLoading(false);
          setStreamProgress(null);
        }
      });
    return () => {
      active = false;
      ctrl.abort();
    };
  }, [user, url, mode, titleId, view, siteFetchTheme]);

  const effectiveTitleId = titleId || bundle?.titleId;
  const nav = bundle?.novelNav;
  const seriesKey = nav?.tocUrl || effectiveTitleId || bundle?.url || url;
  const { tgt } = parseModePair(mode);
  const isJpOut = view === 'original' ? bundle?.detectedSource === 'ja' : tgt === 'ja';
  const isEnglishUi = strings.backBtn === 'Back';
  const activeThemeSpec = useMemo(
    () => resolveEbookThemeSpec(ebookPrefs, appTheme),
    [ebookPrefs, appTheme]
  );
  const activeFontSpec = useMemo(
    () => getEbookFontSpec(ebookPrefs.fontId),
    [ebookPrefs.fontId]
  );
  const ebookSurfaceStyle = useMemo(
    () => buildEbookSurfaceStyle(activeThemeSpec, activeFontSpec, ebookPrefs, isMobile),
    [activeThemeSpec, activeFontSpec, ebookPrefs, isMobile]
  );

  // Sync dynamic <meta name="theme-color"> so OS/PWA status bar seamlessly blends with Ebook paper
  useEffect(() => {
    const activeBg =
      view === 'site'
        ? appTheme === 'Gelap'
          ? '#171B1A'
          : '#FAFBFA'
        : activeThemeSpec.bg;
    syncDocumentThemeColor(activeBg);
    return () => {
      syncDocumentThemeColor(appTheme === 'Gelap' ? '#171B1A' : '#FAFBFA');
    };
  }, [view, activeThemeSpec.bg, appTheme]);

  // Refresh bookmarks whenever active series changes
  useEffect(() => {
    setBookmarks(listBookmarks(seriesKey));
  }, [seriesKey]);

  const isPaginatedMode =
    view !== 'site' &&
    !nav?.isTocPage &&
    (ebookPrefs.pageMode === 'slide' || ebookPrefs.pageMode === 'flip');
  isPaginatedModeRef.current = isPaginatedMode;
  const canUseSpread = !isMobile && !bilingual && viewportW >= 1120;

  // Enforce scroll-mode invariant: stop Auto-Gulir immediately if user switches to paginated Slide/Flip
  useEffect(() => {
    if (ebookPrefs.pageMode !== 'scroll') {
      if (autoScrollDelayTimerRef.current !== null) {
        window.clearTimeout(autoScrollDelayTimerRef.current);
        autoScrollDelayTimerRef.current = null;
      }
      autoScrollCtrlRef.current?.stop();
    }
  }, [ebookPrefs.pageMode]);

  const bookPages = useMemo<BookPageSlice[]>(() => {
    const list = bundle?.sentences || [];
    if (!isPaginatedMode || list.length === 0) return [];
    return paginateEbookParagraphs(list, {
      viewportWidth: viewportW,
      viewportHeight: viewportH,
      isMobile,
      fontSize: ebookPrefs.fontSize,
      lineHeight: ebookPrefs.lineHeight,
      measure: ebookPrefs.measure,
      bilingual,
      isOriginal: view === 'original',
      wantSpread: ebookPrefs.spread === 'auto',
    });
  }, [
    bundle?.sentences,
    isPaginatedMode,
    viewportW,
    viewportH,
    isMobile,
    ebookPrefs.fontSize,
    ebookPrefs.lineHeight,
    ebookPrefs.measure,
    ebookPrefs.spread,
    bilingual,
    view,
  ]);

  // Restore exact chapter position (?pos=end, ?pos=pN, or saved paragraph) once streaming has enough paragraphs
  const restoredForUrlRef = useRef<string>('');
  useEffect(() => {
    const list = bundle?.sentences || [];
    if (!bundle || loading || list.length === 0 || nav?.isTocPage) return;
    const restoreSig = `${bundle.url}|${mode}|${view}`;
    if (restoredForUrlRef.current === restoreSig) return;

    const hint = pendingPositionRef.current;
    if (streamProgress) {
      if (hint === 'end') return;
      const wanted = hint && /^p\d+$/.test(hint) ? Number(hint.slice(1)) || 0 : getChapterParaPos(bundle.url);
      if (wanted >= list.length) return;
    }

    restoredForUrlRef.current = restoreSig;
    pendingPositionRef.current = null;
    let targetPara = 0;
    if (hint === 'end') {
      targetPara = list.length - 1;
    } else if (hint && /^p\d+$/.test(hint)) {
      targetPara = Math.min(list.length - 1, Math.max(0, Number(hint.slice(1)) || 0));
    } else {
      targetPara = Math.min(list.length - 1, getChapterParaPos(bundle.url));
    }

    anchorParaRef.current = targetPara;
    setAnchorParaIdx(targetPara);
    if (bookPages.length > 0) {
      setPageIndex(findPageIndexForParagraph(bookPages, targetPara));
    } else if (targetPara > 0) {
      window.requestAnimationFrame(() => {
        const el = document.querySelector<HTMLElement>(`[data-para-idx="${targetPara}"]`);
        el?.scrollIntoView({ block: 'start', behavior: 'auto' });
      });
    }
  }, [bundle, loading, streamProgress, mode, view, nav?.isTocPage, bookPages]);

  // Reflow-safe paragraph anchoring: when font size / spread / viewport changes, stay on the SAME paragraph!
  useEffect(() => {
    if (!isPaginatedMode || bookPages.length === 0) return;
    const anchoredPage = findPageIndexForParagraph(bookPages, anchorParaRef.current);
    setPageIndex((prev) => (prev === anchoredPage ? prev : anchoredPage));
  }, [isPaginatedMode, bookPages]);

  const safePageIndex =
    bookPages.length > 0 ? Math.min(pageIndex, bookPages.length - 1) : 0;
  const currentSlice = bookPages[safePageIndex] || null;

  // Persist rich reading shelf entry & exact paragraph progress cleanly
  useEffect(() => {
    if (!bundle || loading || nav?.isTocPage || bundle.sentences.length === 0) return;
    const activePara = isPaginatedMode && currentSlice ? currentSlice.startParaIdx : anchorParaIdx;
    const timer = window.setTimeout(() => {
      saveRichReadingEntry({
        seriesKey,
        url: bundle.url,
        host: bundle.host,
        seriesTitle: nav?.seriesTitle || bundle.titleDst || bundle.titleSrc || bundle.host,
        titleDst: bundle.titleDst || bundle.titleSrc || bundle.host,
        chapterLabel: nav?.chapterLabel,
        mode,
        titleId: effectiveTitleId,
        paraIdx: activePara,
        totalParas: bundle.sentences.length,
      });
    }, 320);
    return () => window.clearTimeout(timer);
  }, [
    bundle,
    loading,
    nav?.isTocPage,
    nav?.seriesTitle,
    nav?.chapterLabel,
    isPaginatedMode,
    currentSlice,
    anchorParaIdx,
    seriesKey,
    mode,
    effectiveTitleId,
  ]);

  // Passive GPU-composited scroll progress bar (0 scroll-frame React re-renders & 0 sync localStorage inside rAF!)
  useEffect(() => {
    if (view !== 'reader' || loading || errorMsg || isPaginatedMode) return;
    let rafId = 0;
    let saveTimer: number | null = null;
    let lastSavedScrollPara = -1;

    const flushScrollPosition = () => {
      if (saveTimer !== null) {
        window.clearTimeout(saveTimer);
        saveTimer = null;
      }
      const curPara = anchorParaRef.current;
      if (bundle?.url && curPara !== lastSavedScrollPara) {
        lastSavedScrollPara = curPara;
        saveChapterParaPos(bundle.url, curPara);
        setAnchorParaIdx((prev) => (Math.abs(prev - curPara) >= 2 ? curPara : prev));
      }
    };

    const scheduleIdleFlush = () => {
      if (saveTimer !== null) window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(flushScrollPosition, 900);
    };

    const updateBar = () => {
      rafId = 0;
      const el = progressBarRef.current;
      const docEl = document.documentElement;
      const maxScroll = Math.max(1, docEl.scrollHeight - window.innerHeight);
      const ratio = Math.max(0, Math.min(1, window.scrollY / maxScroll));
      if (el) {
        el.style.transform = `scaleX(${ratio.toFixed(4)})`;
      }
      const total = bundle?.sentences.length || 0;
      if (total > 1) {
        const estPara = Math.min(total - 1, Math.floor(ratio * total));
        anchorParaRef.current = estPara;
        if (Math.abs(estPara - lastSavedScrollPara) >= 2) {
          scheduleIdleFlush();
        }
      }
    };
    const onScroll = () => {
      lastScrollEventTsRef.current = Date.now();
      if (!rafId) rafId = window.requestAnimationFrame(updateBar);
    };
    const onPageHide = () => flushScrollPosition();
    const onVis = () => {
      if (document.visibilityState === 'hidden') flushScrollPosition();
    };
    updateBar();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    window.addEventListener('pagehide', onPageHide);
    document.addEventListener('visibilitychange', onVis);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      window.removeEventListener('pagehide', onPageHide);
      document.removeEventListener('visibilitychange', onVis);
      if (rafId) window.cancelAnimationFrame(rafId);
      flushScrollPosition();
    };
  }, [view, loading, errorMsg, isPaginatedMode, bundle?.sentences.length, bundle?.url]);

  // Sync top hairline progress bar cleanly for paginated mode too
  useEffect(() => {
    if (!isPaginatedMode || bookPages.length === 0 || !progressBarRef.current) return;
    const ratio = (safePageIndex + 1) / bookPages.length;
    progressBarRef.current.style.transform = `scaleX(${ratio.toFixed(4)})`;
  }, [isPaginatedMode, safePageIndex, bookPages.length]);

  const readingMins = useMemo(() => {
    const list = bundle?.sentences || [];
    if (list.length === 0) return 0;
    const remainingPairs =
      isPaginatedMode && bookPages.length > 0
        ? bookPages.slice(safePageIndex).flatMap((p) => p.pairs)
        : list;
    const texts = remainingPairs.map((p) => (view === 'original' ? p.src : p.dst));
    return estimateReadingMinutes(
      texts,
      view === 'original' ? bundle?.detectedSource || 'ja' : tgt,
      bilingual && view === 'reader'
    );
  }, [
    bundle?.sentences,
    bundle?.detectedSource,
    isPaginatedMode,
    bookPages,
    safePageIndex,
    view,
    tgt,
    bilingual,
  ]);

  const progressPct = useMemo(() => {
    const total = bundle?.sentences.length || 0;
    if (total === 0) return 0;
    if (isPaginatedMode && bookPages.length > 0) {
      return Math.round(((safePageIndex + 1) / bookPages.length) * 100);
    }
    return Math.min(100, Math.max(1, Math.round(((anchorParaIdx + 1) / total) * 100)));
  }, [bundle?.sentences.length, isPaginatedMode, bookPages.length, safePageIndex, anchorParaIdx]);

  const chapterModeKey = `${nav?.tocUrl || url}::${mode}`;
  const translatedTitles = translatedTitlesByKey[chapterModeKey] || {};
  const translatingChapters = Boolean(
    chapterTranslateProgress && chapterTranslateProgress.done < chapterTranslateProgress.total
  );

  // Auto-translate 100% of ALL chapter titles + seriesTitle strictly matching the active target mode.
  const isOriginalView = view === 'original';
  const chapterListCount = nav?.chapters?.length || 0;
  const chapterListRef = useRef(nav?.chapters);
  chapterListRef.current = nav?.chapters;
  const chapterBatchSig = `${chapterModeKey}::${chapterListCount}::${nav?.seriesTitle || ''}`;

  useEffect(() => {
    const isMockOnlyE2E =
      typeof window !== 'undefined' &&
      (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') &&
      (new URLSearchParams(window.location.search).get('e2e') === '1' ||
        window.sessionStorage.getItem('tranx_e2e') === '1') &&
      new URLSearchParams(window.location.search).get('direct') !== '1' &&
      window.sessionStorage.getItem('tranx_e2e_direct') !== '1';
    const currentChapters = chapterListRef.current;
    if (!currentChapters || currentChapters.length === 0 || isOriginalView || isMockOnlyE2E) {
      setChapterTranslateProgress(null);
      return;
    }
    let active = true;
    const ctrl = new AbortController();
    const total = currentChapters.length;
    setChapterTranslateProgress({ done: 0, total });
    translateChapterTitlesDirect({
      chapters: currentChapters,
      mode,
      titleId: effectiveTitleId,
      tocKey: nav?.tocUrl || url,
      seriesTitle: nav?.seriesTitle,
      signal: ctrl.signal,
      onProgress: (partialMap, doneCount, totalCount) => {
        if (!active) return;
        setTranslatedTitlesByKey((prev) => ({
          ...prev,
          [chapterModeKey]: partialMap,
        }));
        setChapterTranslateProgress(
          doneCount < totalCount ? { done: doneCount, total: totalCount } : null
        );
      },
    })
      .then((map) => {
        if (active) {
          setTranslatedTitlesByKey((prev) => ({
            ...prev,
            [chapterModeKey]: map,
          }));
          setChapterTranslateProgress(null);
        }
      })
      .catch(() => {
        if (active) setChapterTranslateProgress(null);
      });
    return () => {
      active = false;
      ctrl.abort();
    };
  }, [chapterBatchSig, mode, effectiveTitleId, isOriginalView, chapterModeKey]);

  const rawDisplaySeriesTitle =
    view === 'original'
      ? nav?.seriesTitle || ''
      : translatedTitles.__seriesTitle__ || nav?.seriesTitle || '';
  const displaySeriesTitle =
    /^(?:error:|kesalahan:|403\s+(?:error|kesalahan|forbidden)|the request could not be satisfied|permintaan (?:itu )?tidak dapat dipenuhi)/i.test(
      rawDisplaySeriesTitle.trim()
    )
      ? ''
      : rawDisplaySeriesTitle;

  const openChapterUrl = useCallback(
    (
      targetUrl: string,
      targetView: 'reader' | 'site' | 'original' = view,
      posHint?: string
    ) => {
      setChaptersOpen(false);
      setReaderMenuOpen(false);
      setAppearanceOpen(false);
      setToolsMenuOpen(false);
      setView(targetView);
      const qs = new URLSearchParams({
        url: targetUrl,
        mode,
        view: targetView,
        ...(effectiveTitleId ? { titleId: effectiveTitleId } : {}),
        ...(posHint ? { pos: posHint } : {}),
      });
      onNavigate(`/web?${qs.toString()}`);
    },
    [view, mode, effectiveTitleId, onNavigate]
  );

  const jumpToPage = useCallback(
    (nextPageIdx: number, dir?: 'next' | 'prev') => {
      if (bookPages.length === 0) return;
      const clamped = Math.max(0, Math.min(bookPages.length - 1, nextPageIdx));
      const slice = bookPages[clamped];
      if (slice) {
        anchorParaRef.current = slice.startParaIdx;
        setAnchorParaIdx(slice.startParaIdx);
      }
      setPageIndex(clamped);
      if (dir) {
        setTurnAnim((prev) => ({ dir, seq: (prev?.seq || 0) + 1 }));
        setTapCue((prev) => ({
          side: dir === 'next' ? 'right' : 'left',
          seq: (prev?.seq || 0) + 1,
        }));
        try {
          if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
            navigator.vibrate(8);
          }
        } catch {
          // ignore on unsupported browsers
        }
      }
      window.scrollTo({ top: 0, behavior: 'auto' });
    },
    [bookPages]
  );

  const jumpToParagraph = useCallback(
    (paraIdx: number) => {
      const total = bundle?.sentences.length || 0;
      if (total === 0) return;
      const clamped = Math.max(0, Math.min(total - 1, paraIdx));
      anchorParaRef.current = clamped;
      setAnchorParaIdx(clamped);
      if (isPaginatedMode && bookPages.length > 0) {
        const targetPage = findPageIndexForParagraph(bookPages, clamped);
        setPageIndex(targetPage);
        window.scrollTo({ top: 0, behavior: 'auto' });
      } else {
        window.requestAnimationFrame(() => {
          const el = document.querySelector<HTMLElement>(`[data-para-idx="${clamped}"]`);
          el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        });
      }
    },
    [bundle?.sentences.length, isPaginatedMode, bookPages]
  );

  const turnBookPage = useCallback(
    (dir: 'next' | 'prev') => {
      if (!isPaginatedMode || bookPages.length === 0) return;
      if (dir === 'next') {
        if (safePageIndex < bookPages.length - 1) {
          jumpToPage(safePageIndex + 1, 'next');
        } else if (nav?.nextUrl && !loading) {
          openChapterUrl(nav.nextUrl);
        }
      } else {
        if (safePageIndex > 0) {
          jumpToPage(safePageIndex - 1, 'prev');
        } else if (nav?.prevUrl && !loading) {
          // Land cleanly on the LAST page of the previous chapter like a physical book!
          openChapterUrl(nav.prevUrl, view === 'original' ? 'original' : 'reader', 'end');
        }
      }
    },
    [
      isPaginatedMode,
      bookPages.length,
      safePageIndex,
      nav?.nextUrl,
      nav?.prevUrl,
      loading,
      jumpToPage,
      openChapterUrl,
      view,
    ]
  );

  const activeAnchorForBookmark = isPaginatedMode && currentSlice ? currentSlice.startParaIdx : anchorParaIdx;
  const isCurrentBookmarked = useMemo(
    () => bookmarks.some((b) => b.url === (bundle?.url || url) && b.paraIdx === activeAnchorForBookmark),
    [bookmarks, bundle?.url, url, activeAnchorForBookmark]
  );

  const handleToggleCurrentBookmark = useCallback(() => {
    if (!bundle || bundle.sentences.length === 0) return;
    const pair = bundle.sentences[activeAnchorForBookmark] || bundle.sentences[0];
    const excerpt = (view === 'original' ? pair.src : pair.dst) || bundle.titleDst;
    const res = toggleBookmark({
      seriesKey,
      url: bundle.url,
      chapterLabel: nav?.chapterLabel,
      titleDst: bundle.titleDst || bundle.titleSrc || bundle.host,
      paraIdx: activeAnchorForBookmark,
      excerpt,
    });
    setBookmarks(res.items);
    flashReaderToast(res.added ? strings.ebookBookmarkSaved : strings.ebookBookmarkAdd);
  }, [
    bundle,
    activeAnchorForBookmark,
    view,
    seriesKey,
    nav?.chapterLabel,
    flashReaderToast,
    strings.ebookBookmarkSaved,
    strings.ebookBookmarkAdd,
  ]);

  const activeSpeakLang = view === 'original' ? bundle?.detectedSource || 'ja' : tgt;

  // Refresh ranked neural voices cleanly whenever playback language changes or voices load asynchronously
  useEffect(() => {
    if (!isTtsSupported()) return;
    let active = true;
    const refresh = (pool?: SpeechSynthesisVoice[]) => {
      if (!active) return;
      const voices = pool || window.speechSynthesis.getVoices();
      const ranked = rankVoicesForLang(voices, activeSpeakLang);
      setRankedVoices(ranked);
      setPodcastVoiceUri((cur) => (cur && !ranked.some((v) => v.uri === cur) ? '' : cur));
    };
    loadSpeechVoices(1000).then((loaded) => refresh(loaded));
    const onVoices = () => refresh();
    window.speechSynthesis.addEventListener?.('voiceschanged', onVoices);
    return () => {
      active = false;
      window.speechSynthesis.removeEventListener?.('voiceschanged', onVoices);
    };
  }, [activeSpeakLang]);

  // Podcast-Grade Audio Narration Wiring (Single Scroll-Owner: suspends Auto-Scroll cleanly)
  const handleToggleTts = useCallback(() => {
    if (!bundle || bundle.sentences.length === 0) return;
    if (!isTtsSupported()) {
      flashReaderToast(strings.ebookListenUnsupported);
      return;
    }
    if (ttsState === 'playing') {
      ttsCtrlRef.current?.pause();
      return;
    }
    if (ttsState === 'paused') {
      autoScrollCtrlRef.current?.stop();
      ttsCtrlRef.current?.resume();
      return;
    }
    // Enforce Single Scroll-Owner Invariant: stop Auto-Gulir before starting Podcast
    autoScrollCtrlRef.current?.stop();
    setPodcastUserDetached(false);

    if (!ttsCtrlRef.current) {
      ttsCtrlRef.current = createPodcastNarratorController({
        onSegmentStart: (idx, kind, _fmt, meta) => {
          setTtsKind(kind);
          setActiveSpeakerName(meta?.speakerName || null);
          setPodcastLocalFallback(Boolean(meta?.isFallbackLocal));
          const remainingSec =
            meta?.sleepRemainingMs && meta.sleepRemainingMs > 0
              ? Math.ceil(meta.sleepRemainingMs / 1000)
              : 0;
          setSleepCountdownSeed((prev) => ({ sec: remainingSec, seq: prev.seq + 1 }));
          if (idx < 0) {
            setTtsParaIdx(null);
            return;
          }
          setTtsParaIdx(idx);
          anchorParaRef.current = idx;
          setAnchorParaIdx(idx);
          if (!podcastUserDetachedRef.current && !isPaginatedModeRef.current) {
            programmaticScrollUntilRef.current = Date.now() + 650;
            scrollActiveParagraphIntoComfortZone(idx);
          }
        },
        onStateChange: (nextState) => {
          setTtsState(nextState);
          if (nextState === 'idle') {
            setTtsParaIdx(null);
            setActiveSpeakerName(null);
            setPodcastLocalFallback(false);
            setSleepCountdownSeed((prev) => ({ sec: 0, seq: prev.seq + 1 }));
            setPodcastStudioOpen(false);
            setPodcastUserDetached(false);
          }
        },
        onSleepTriggered: () => {
          setSleepCountdownSeed((prev) => ({ sec: 0, seq: prev.seq + 1 }));
          flashReaderToast(stringsRef.current.ebookPodcastSleepDoneToast);
        },
      });
    }
    const texts = bundle.sentences.map((p) => (view === 'original' ? p.src : p.dst));
    ttsCtrlRef.current.start({
      texts,
      startIndex: activeAnchorForBookmark,
      lang: activeSpeakLang,
      rate: ttsRate,
      style: podcastStyle,
      voiceUri: podcastVoiceUri,
      chapterTitle: view === 'original' ? bundle.titleSrc : bundle.titleDst || bundle.titleSrc,
      seriesTitle: displaySeriesTitle || bundle.host,
      sleepPreset,
      formatOverride: podcastFormatOverride,
      castMode: podcastCastMode,
    });
  }, [
    bundle,
    ttsState,
    view,
    activeSpeakLang,
    activeAnchorForBookmark,
    ttsRate,
    podcastStyle,
    podcastVoiceUri,
    podcastCastMode,
    displaySeriesTitle,
    sleepPreset,
    podcastFormatOverride,
    flashReaderToast,
    strings.ebookListenUnsupported,
    strings.ebookPodcastSleepDoneToast,
  ]);

  // Keep paginated page synced ONLY when spoken Podcast paragraph advances (never fights manual turns)
  useEffect(() => {
    if (ttsParaIdx === null || ttsParaIdx < 0 || !isPaginatedMode || bookPages.length === 0) return;
    const targetPage = findPageIndexForParagraph(bookPages, ttsParaIdx);
    setPageIndex((prev) => (prev === targetPage ? prev : targetPage));
  }, [ttsParaIdx, isPaginatedMode, bookPages]);

  // Detect manual user scroll during Podcast mode so we NEVER fight the reader (Voice Dream pattern)
  useEffect(() => {
    if (ttsState !== 'playing' || isPaginatedMode) return;
    const onUserScrollIntent = (e: Event) => {
      if (Date.now() < programmaticScrollUntilRef.current) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest('[data-ebook-podcast-bar], [data-ebook-podcast-studio]')) return;
      setPodcastUserDetached(true);
    };
    window.addEventListener('wheel', onUserScrollIntent, { passive: true });
    window.addEventListener('touchmove', onUserScrollIntent, { passive: true });
    return () => {
      window.removeEventListener('wheel', onUserScrollIntent);
      window.removeEventListener('touchmove', onUserScrollIntent);
    };
  }, [ttsState, isPaginatedMode]);

  const handleCycleTtsRate = useCallback(() => {
    const next = PODCAST_RATES[(PODCAST_RATES.indexOf(ttsRate) + 1) % PODCAST_RATES.length];
    setTtsRate(next);
    ttsCtrlRef.current?.setRate(next);
  }, [ttsRate]);

  const handleChangePodcastStyle = useCallback((nextStyle: PodcastStyleId) => {
    setPodcastStyle(nextStyle);
    ttsCtrlRef.current?.setStyle(nextStyle);
  }, []);

  const handleChangePodcastCastMode = useCallback((nextCast: PodcastCastMode) => {
    setPodcastCastMode(nextCast);
    ttsCtrlRef.current?.setCastMode(nextCast);
  }, []);

  const handleChangePodcastVoice = useCallback((uri: string) => {
    setPodcastVoiceUri(uri);
    ttsCtrlRef.current?.setVoiceUri(uri);
  }, []);

  const handleChangeSleepPreset = useCallback((preset: PodcastSleepPreset) => {
    setSleepPreset(preset);
    const nextSec = preset === '15' ? 15 * 60 : preset === '30' ? 30 * 60 : 0;
    setSleepCountdownSeed((prev) => ({ sec: nextSec, seq: prev.seq + 1 }));
    ttsCtrlRef.current?.setSleepPreset(preset);
  }, []);

  const handleChangePodcastFormat = useCallback((fmt: 'auto' | DocumentFormatId) => {
    setPodcastFormatOverride(fmt);
    ttsCtrlRef.current?.setFormatOverride(fmt);
  }, []);

  const detectedPodcastFormat = useMemo<DocumentFormatId>(() => {
    if (!bundle || bundle.sentences.length === 0) return 'fiction_novel';
    const texts = bundle.sentences.map((p) => (view === 'original' ? p.src : p.dst));
    return classifyDocumentFormat(texts, activeSpeakLang);
  }, [bundle, view, activeSpeakLang]);

  const podcastFormatLabel = useCallback(
    (fmt: DocumentFormatId): string => {
      switch (fmt) {
        case 'script_dialogue':
          return strings.ebookPodcastFormatScript;
        case 'news_editorial':
          return strings.ebookPodcastFormatNews;
        case 'academic_paper':
          return strings.ebookPodcastFormatAcademic;
        case 'technical_docs':
          return strings.ebookPodcastFormatTech;
        case 'list_instructions':
          return strings.ebookPodcastFormatList;
        case 'poetry_verse':
          return strings.ebookPodcastFormatPoetry;
        case 'letter_quote':
          return strings.ebookPodcastFormatLetter;
        default:
          return strings.ebookPodcastFormatFiction;
      }
    },
    [strings]
  );

  // Hands-Free Auto-Gulir Controller (Single Scroll-Owner: pauses Podcast & switches cleanly to Scroll mode)
  const handleToggleAutoScroll = useCallback(() => {
    if (!bundle || bundle.sentences.length === 0 || view === 'site') return;
    if (autoScrollState === 'running') {
      autoScrollCtrlRef.current?.pause('manual');
      return;
    }
    if (autoScrollState === 'paused') {
      ttsCtrlRef.current?.stop();
      autoScrollCtrlRef.current?.resume();
      return;
    }
    ttsCtrlRef.current?.stop();
    if (!autoScrollCtrlRef.current) {
      autoScrollCtrlRef.current = createEbookAutoScrollController({
        onStateChange: (next, reason) => {
          setAutoScrollState(next);
          if (next === 'paused' && reason === 'interaction') {
            flashReaderToast(stringsRef.current.ebookAutoScrollPausedTouchToast);
          } else if (next === 'paused' && reason === 'end') {
            flashReaderToast(stringsRef.current.ebookAutoScrollEndToast);
          }
        },
      });
    }
    if (ebookPrefs.pageMode !== 'scroll') {
      updateEbookPrefs({ pageMode: 'scroll' });
      flashReaderToast(strings.ebookAutoScrollSwitchedToast);
      if (autoScrollDelayTimerRef.current !== null) {
        window.clearTimeout(autoScrollDelayTimerRef.current);
      }
      autoScrollDelayTimerRef.current = window.setTimeout(() => {
        autoScrollDelayTimerRef.current = null;
        autoScrollCtrlRef.current?.start(autoScrollSpeed);
      }, 120);
    } else {
      autoScrollCtrlRef.current.start(autoScrollSpeed);
    }
  }, [
    bundle,
    view,
    autoScrollState,
    ebookPrefs.pageMode,
    updateEbookPrefs,
    autoScrollSpeed,
    flashReaderToast,
    strings.ebookAutoScrollPausedTouchToast,
    strings.ebookAutoScrollEndToast,
    strings.ebookAutoScrollSwitchedToast,
  ]);

  const handleStepAutoScrollSpeed = useCallback(
    (delta: -1 | 1) => {
      const idx = AUTO_SCROLL_SPEEDS.indexOf(autoScrollSpeed);
      const nextIdx = Math.max(0, Math.min(AUTO_SCROLL_SPEEDS.length - 1, idx + delta));
      const nextSpeed = AUTO_SCROLL_SPEEDS[nextIdx];
      setAutoScrollSpeed(nextSpeed);
      autoScrollCtrlRef.current?.setSpeed(nextSpeed);
    },
    [autoScrollSpeed]
  );

  // Auto-pause Auto-Gulir smoothly when user touches screen or uses scroll wheel (WCAG 2.2.2)
  useEffect(() => {
    if (autoScrollState !== 'running') return;
    const onInteract = (e: Event) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest('[data-ebook-autoscroll-bar]')) return;
      lastAutoScrollTouchPauseRef.current = Date.now();
      autoScrollCtrlRef.current?.pause('interaction');
    };
    window.addEventListener('wheel', onInteract, { passive: true });
    window.addEventListener('touchstart', onInteract, { passive: true });
    return () => {
      window.removeEventListener('wheel', onInteract);
      window.removeEventListener('touchstart', onInteract);
    };
  }, [autoScrollState]);

  const readerKeyHandlerRef = useRef<(e: KeyboardEvent) => void>(() => {});
  readerKeyHandlerRef.current = (e: KeyboardEvent) => {
    if (
      e.target instanceof HTMLInputElement ||
      e.target instanceof HTMLTextAreaElement ||
      e.target instanceof HTMLSelectElement
    ) {
      return;
    }
    if (e.key === 'Escape') {
      if (podcastStudioOpen) {
        setPodcastStudioOpen(false);
        return;
      }
      if (autoScrollState !== 'idle') {
        autoScrollCtrlRef.current?.stop();
        return;
      }
      if (toolsMenuOpen) {
        setToolsMenuOpen(false);
        return;
      }
      if (hudHidden) {
        setHudHidden(false);
        return;
      }
      if (ebookPrefs.zenMode) {
        updateEbookPrefs({ zenMode: false });
        return;
      }
    }
    if (autoScrollState !== 'idle' && !appearanceOpen && !chaptersOpen && !toolsMenuOpen && !readerMenuOpen) {
      if (e.key === ' ') {
        e.preventDefault();
        handleToggleAutoScroll();
        return;
      }
      if (e.key === 'ArrowDown' || e.key === ']') {
        e.preventDefault();
        handleStepAutoScrollSpeed(1);
        return;
      }
      if (e.key === 'ArrowUp' || e.key === '[') {
        e.preventDefault();
        handleStepAutoScrollSpeed(-1);
        return;
      }
    }
    if (!appearanceOpen && !chaptersOpen && !toolsMenuOpen && !readerMenuOpen) {
      if ((e.key === 'b' || e.key === 'B') && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        handleToggleCurrentBookmark();
        return;
      }
      if ((e.key === 'f' || e.key === 'F') && !e.metaKey && !e.ctrlKey && view !== 'site') {
        e.preventDefault();
        updateEbookPrefs({ zenMode: !ebookPrefs.zenMode });
        return;
      }
    }
    if (isPaginatedMode && bookPages.length > 0) {
      if (e.key === 'ArrowRight' || (e.key === ' ' && !e.shiftKey)) {
        e.preventDefault();
        turnBookPage('next');
      } else if (e.key === 'ArrowLeft' || (e.key === ' ' && e.shiftKey)) {
        e.preventDefault();
        turnBookPage('prev');
      }
      return;
    }
    if (!nav?.isNovel) return;
    if (e.key === 'ArrowRight' && nav.nextUrl && !loading) {
      openChapterUrl(nav.nextUrl);
    } else if (e.key === 'ArrowLeft' && nav.prevUrl && !loading) {
      openChapterUrl(nav.prevUrl, view, 'end');
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => readerKeyHandlerRef.current(e);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const nextChapterObj = useMemo(
    () =>
      nav?.chapters && nav.nextUrl
        ? nav.chapters.find((c) => c.url === nav.nextUrl)
        : undefined,
    [nav?.chapters, nav?.nextUrl]
  );
  const nextChapterDisplayTitle = nextChapterObj
    ? translatedTitles[nextChapterObj.url] || nextChapterObj.titleDst || nextChapterObj.title
    : '';
  const savedProgress = useMemo(
    () => getReadingProgress(nav?.tocUrl || effectiveTitleId),
    [nav?.tocUrl, effectiveTitleId, bundle?.url]
  );
  const canResumeProgress = Boolean(
    nav?.isTocPage && savedProgress && savedProgress.url && savedProgress.url !== bundle?.url
  );
  const canRestartFromCh1 = Boolean(
    nav?.isNovel && !nav.nextUrl && !nav.isTocPage && nav.firstUrl && nav.firstUrl !== bundle?.url
  );
  const filteredChapters = useMemo(() => {
    const list = (nav?.chapters || []).map((ch, idx) => ({ ch, origIndex: idx + 1 }));
    const q = deferredChapterQuery.trim().toLowerCase();
    if (!q) return list;
    return list.filter(({ ch, origIndex }) => {
      const tDst = (translatedTitles[ch.url] || ch.titleDst || '').toLowerCase();
      return (
        ch.title.toLowerCase().includes(q) ||
        tDst.includes(q) ||
        String(origIndex).includes(q)
      );
    });
  }, [nav?.chapters, deferredChapterQuery, translatedTitles]);

  const chromeHidden = (ebookPrefs.zenMode || hudHidden) && view !== 'site';

  const renderReadingParagraph = (pair: SentencePair, idxInDoc: number) => {
    const isTtsSpeaking = ttsParaIdx === idxInDoc;
    const activeRulerIdx = ttsParaIdx !== null ? ttsParaIdx : focusedParaIdx;
    const isRulerFocused = ebookPrefs.readingRuler !== 'off' && activeRulerIdx === idxInDoc;
    const isRulerDimmed =
      ebookPrefs.readingRuler === 'shade' && activeRulerIdx !== null && activeRulerIdx !== idxInDoc;
    const isPeekOpen = ebookPrefs.inlinePeek && view === 'reader' && !bilingual && Boolean(peekedParas[pair.i]);
    if (bilingual && view === 'reader') {
      return (
        <div
          key={pair.i}
          data-para-idx={idxInDoc}
          className={`bilingual-pair-card ${isTtsSpeaking ? 'is-tts-active' : ''} ${isRulerFocused ? `is-ruler-${ebookPrefs.readingRuler}` : ''} ${isRulerDimmed ? 'is-ruler-dimmed' : ''}`}
          onMouseEnter={ebookPrefs.readingRuler !== 'off' ? () => setFocusedParaIdx(idxInDoc) : undefined}
        >
          <div
            className="bilingual-pair-src"
            style={{
              fontFamily:
                bundle?.detectedSource === 'ja' ? 'var(--font-jp)' : 'var(--font-ui)',
            }}
          >
            {pair.src}
          </div>
          <p className="novel-reader-para">{pair.dst}</p>
        </div>
      );
    }

    const isPeekable = ebookPrefs.inlinePeek && view === 'reader';
    return (
      <div
        key={pair.i}
        data-para-idx={idxInDoc}
        role={isPeekable ? 'button' : undefined}
        tabIndex={isPeekable ? 0 : undefined}
        aria-expanded={isPeekable ? isPeekOpen : undefined}
        className={`ebook-para-block ${isPeekable ? 'is-peekable' : ''} ${isTtsSpeaking ? 'is-tts-active' : ''} ${isRulerFocused ? `is-ruler-${ebookPrefs.readingRuler}` : ''} ${isRulerDimmed ? 'is-ruler-dimmed' : ''}`}
        onMouseEnter={ebookPrefs.readingRuler !== 'off' ? () => setFocusedParaIdx(idxInDoc) : undefined}
        onKeyDown={
          isPeekable
            ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  e.stopPropagation();
                  setPeekedParas((prev) => ({ ...prev, [pair.i]: !prev[pair.i] }));
                }
              }
            : undefined
        }
        onClick={(e) => {
          if (ebookPrefs.readingRuler !== 'off') setFocusedParaIdx(idxInDoc);
          if (!isPeekable) return;
          if (window.getSelection()?.toString().trim()) return;
          if (autoScrollState !== 'idle') return;
          if (isPaginatedMode) {
            const stage = e.currentTarget.closest<HTMLElement>('[data-ebook-book-stage]');
            if (stage) {
              const rect = stage.getBoundingClientRect();
              const relX = (e.clientX - rect.left) / Math.max(1, rect.width);
              const bounds = getTapZoneBounds(ebookPrefs.tapZone);
              if (relX <= bounds.leftMaxX || relX >= bounds.rightMinX) return;
            }
          }
          e.stopPropagation();
          setPeekedParas((prev) => ({ ...prev, [pair.i]: !prev[pair.i] }));
        }}
      >
        <p className="novel-reader-para">
          {view === 'original' ? pair.src : pair.dst}
        </p>
        {isPeekOpen && pair.src && (
          <div
            className="ebook-inline-peek-src"
            data-ebook-peek-src="true"
            style={{
              fontFamily:
                bundle?.detectedSource === 'ja' ? 'var(--font-jp)' : 'var(--font-ui)',
            }}
          >
            {pair.src}
          </div>
        )}
      </div>
    );
  };

  return (
    <div
      className={view === 'site' ? '' : 'ebook-reader-surface'}
      data-ebook-theme={activeThemeSpec.id}
      data-ebook-thememode={ebookPrefs.themeMode}
      data-ebook-pagemode={ebookPrefs.pageMode}
      data-ebook-font={activeFontSpec.id}
      data-ebook-spread={currentSlice?.isSpread ? 'two' : 'one'}
      data-ebook-hud={chromeHidden ? 'hidden' : 'visible'}
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100dvh',
        ...(view === 'site' ? {} : ebookSurfaceStyle),
      }}
    >
      {chromeHidden && (
        <button
          type="button"
          className="ebook-zen-exit-btn pressable"
          onClick={() => {
            setHudHidden(false);
            if (ebookPrefs.zenMode) updateEbookPrefs({ zenMode: false });
          }}
        >
          {strings.ebookExitZenBtn}
        </button>
      )}

      {inlineToast && (
        <div className="ebook-reader-toast" role="status" aria-live="polite">
          {inlineToast}
        </div>
      )}

      {!chromeHidden && (
        <header
          className={`web-viewer-topbar ${isMobile ? 'is-mobile' : ''}`}
          inert={isMobile && (appearanceOpen || readerMenuOpen) ? true : undefined}
        >
          {isMobile ? (
            <div className="reader-mobile-bar">
              <button
                type="button"
                className="icon-square-btn pressable"
                aria-label={strings.backBtn}
                onClick={() => onNavigate(backPath)}
              >
                <span aria-hidden="true" style={{ fontSize: '18px', fontWeight: 600 }}>
                  {'\u2190'}
                </span>
              </button>

              <div className="reader-mobile-seg" role="tablist" aria-label={strings.readerModeTab}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={view === 'reader'}
                  className={`reader-mobile-seg-btn pressable ${view === 'reader' ? 'active' : ''}`}
                  onClick={() => setView('reader')}
                >
                  <IconBook size={15} />
                  <span>{strings.shortEbookTab}</span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={view === 'site'}
                  className={`reader-mobile-seg-btn pressable ${view === 'site' ? 'active' : ''}`}
                  onClick={() => setView('site')}
                >
                  <IconGlobe size={15} />
                  <span>{strings.shortSiteTab}</span>
                </button>
              </div>

              {view !== 'site' && (
                <button
                  type="button"
                  className={`ebook-aa-btn pressable ${appearanceOpen ? 'active' : ''}`}
                  aria-label={strings.ebookAppearanceTitle}
                  aria-expanded={appearanceOpen}
                  onClick={() => {
                    setReaderMenuOpen(false);
                    setChaptersOpen(false);
                    setToolsMenuOpen(false);
                    setAppearanceOpen((v) => !v);
                  }}
                >
                  Aa
                </button>
              )}

              <button
                type="button"
                className="icon-square-btn pressable"
                aria-label={strings.readerMenuLabel}
                aria-expanded={readerMenuOpen}
                onClick={() => {
                  setAppearanceOpen(false);
                  setToolsMenuOpen(false);
                  setReaderMenuOpen((v) => !v);
                }}
              >
                <IconMenu size={20} />
              </button>
            </div>
          ) : (
            <div className="reader-desktop-bar">
              <div className="reader-desktop-left">
                <button
                  type="button"
                  className="btn-secondary pressable reader-back-btn"
                  onClick={() => onNavigate(backPath)}
                >
                  <span aria-hidden="true">{'\u2190'}</span>
                  <span>{strings.backBtn}</span>
                </button>

                <span className="reader-toolbar-divider" aria-hidden="true" />

                <div className="reader-desktop-seg" role="group" aria-label={strings.readerModeTab}>
                  <button
                    type="button"
                    aria-pressed={view === 'reader'}
                    className={`reader-desktop-seg-btn pressable ${view === 'reader' ? 'active' : ''}`}
                    onClick={() => setView('reader')}
                  >
                    <IconBook size={15} />
                    <span>{strings.readerModeTab}</span>
                  </button>
                  <button
                    type="button"
                    aria-pressed={view === 'site'}
                    className={`reader-desktop-seg-btn pressable ${view === 'site' ? 'active' : ''}`}
                    onClick={() => setView('site')}
                  >
                    <IconGlobe size={15} />
                    <span>{strings.translatedSiteTab}</span>
                  </button>
                  <button
                    type="button"
                    aria-pressed={view === 'original'}
                    className={`reader-desktop-seg-btn pressable ${view === 'original' ? 'active' : ''}`}
                    onClick={() => setView('original')}
                  >
                    <span>{strings.originalViewTab}</span>
                  </button>
                </div>
              </div>

              {/* Calm Progressive Disclosure Right Zone: Core reading & language controls visible, secondary grouped in Alat Baca */}
              <div className="reader-desktop-right">
                {view === 'reader' && !nav?.isTocPage && (
                  <button
                    type="button"
                    className={`reader-bilingual-btn pressable ${bilingual ? 'active' : ''}`}
                    aria-pressed={bilingual}
                    onClick={() => setBilingual((v) => !v)}
                  >
                    <IconColumns size={15} />
                    <span>{strings.bilingualToggle}</span>
                  </button>
                )}

                {view !== 'site' && (
                  <button
                    type="button"
                    className={`ebook-aa-btn pressable ${appearanceOpen ? 'active' : ''}`}
                    aria-label={strings.ebookAppearanceTitle}
                    aria-expanded={appearanceOpen}
                    onClick={() => {
                      setChaptersOpen(false);
                      setToolsMenuOpen(false);
                      setAppearanceOpen((v) => !v);
                    }}
                  >
                    <span>Aa</span>
                    <span style={{ fontFamily: 'var(--font-ui)', fontSize: '13px', fontWeight: 600 }}>
                      {strings.ebookAppearanceBtn}
                    </span>
                  </button>
                )}

                <select
                  className="field-select reader-lang-select"
                  value={mode}
                  onChange={(e) => setMode(e.target.value as ModePair)}
                  aria-label={strings.langMenuTitle}
                >
                  <option value="auto-id">{strings.langAuto} {'\u2192'} {strings.langId}</option>
                  <option value="auto-en">{strings.langAuto} {'\u2192'} {strings.langEn}</option>
                  <option value="auto-ja">{strings.langAuto} {'\u2192'} {strings.langJa}</option>
                  <option value="ja-id">{strings.langJa} {'\u2192'} {strings.langId}</option>
                  <option value="ja-en">{strings.langJa} {'\u2192'} {strings.langEn}</option>
                  <option value="id-ja">{strings.langId} {'\u2192'} {strings.langJa}</option>
                  <option value="id-en">{strings.langId} {'\u2192'} {strings.langEn}</option>
                  <option value="en-id">{strings.langEn} {'\u2192'} {strings.langId}</option>
                  <option value="en-ja">{strings.langEn} {'\u2192'} {strings.langJa}</option>
                </select>

                {view !== 'site' && !nav?.isTocPage && bundle && (
                  <button
                    type="button"
                    className={`icon-square-btn pressable ${isCurrentBookmarked ? 'ebook-bookmark-active' : ''}`}
                    aria-label={isCurrentBookmarked ? strings.ebookBookmarkSaved : strings.ebookBookmarkAdd}
                    aria-pressed={isCurrentBookmarked}
                    title={isCurrentBookmarked ? strings.ebookBookmarkSaved : strings.ebookBookmarkAdd}
                    onClick={handleToggleCurrentBookmark}
                  >
                    <IconBookmark size={18} filled={isCurrentBookmarked} />
                  </button>
                )}

                <button
                  type="button"
                  className={`btn-secondary pressable reader-utility-btn ${toolsMenuOpen ? 'active' : ''}`}
                  aria-label={strings.ebookToolsMenuBtn}
                  aria-expanded={toolsMenuOpen}
                  onClick={() => {
                    setAppearanceOpen(false);
                    setChaptersOpen(false);
                    setToolsMenuOpen((v) => !v);
                  }}
                >
                  <IconDots size={16} />
                  <span>{strings.ebookToolsMenuBtn}</span>
                </button>
              </div>
            </div>
          )}
          {view === 'reader' && !loading && !errorMsg && (
            <div className="ebook-reading-progress-track" aria-hidden="true">
              <div ref={progressBarRef} className="ebook-reading-progress-fill" />
            </div>
          )}
          {streamProgress && streamProgress.total > 0 && (
            <div
              className="ebook-stream-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={streamProgress.total}
              aria-valuenow={streamProgress.done}
              aria-label={`${strings.streamingProgressLabel} ${streamProgress.done}/${streamProgress.total}`}
            >
              <div
                className="ebook-stream-bar-fill"
                style={{
                  transform: `scaleX(${Math.max(
                    0.06,
                    Math.min(1, streamProgress.done / streamProgress.total)
                  )})`,
                }}
              />
            </div>
          )}
        </header>
      )}

      {/* Desktop Progressive Disclosure Popover: Alat & Navigasi Ebook */}
      {!isMobile && toolsMenuOpen && (
        <>
          <div
            className="popover-dismiss-backdrop"
            onClick={() => setToolsMenuOpen(false)}
            aria-hidden="true"
          />
          <div
            className="context-popover glass-regular-surface ebook-tools-popover"
            role="dialog"
            aria-modal="false"
            aria-label={strings.ebookToolsMenuTitle}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="ebook-appear-header">
              <h2 className="modal-title">{strings.ebookToolsMenuTitle}</h2>
              <button
                type="button"
                className="icon-square-btn"
                aria-label={strings.closeLabel}
                onClick={() => setToolsMenuOpen(false)}
              >
                <IconX size={18} />
              </button>
            </div>

            <div className="ebook-tools-body">
              {view !== 'site' && !nav?.isTocPage && (
                <>
                  <div className="ebook-tools-group-label">{strings.ebookToolsGroupHandsFree}</div>
                  <button
                    type="button"
                    className="menu-item-btn"
                    data-ebook-podcast-trigger="true"
                    onClick={() => {
                      setToolsMenuOpen(false);
                      handleToggleTts();
                    }}
                  >
                    <span className="menu-item-left">
                      <IconHeadphones size={17} />
                      <span>
                        {ttsState === 'playing'
                          ? strings.ebookListenPause
                          : ttsState === 'paused'
                            ? strings.ebookListenResume
                            : strings.ebookPodcastBtn}
                      </span>
                    </span>
                    {ttsState !== 'idle' && <IconCheck size={16} />}
                  </button>

                  <button
                    type="button"
                    className="menu-item-btn"
                    data-ebook-autoscroll-trigger="true"
                    onClick={() => {
                      setToolsMenuOpen(false);
                      handleToggleAutoScroll();
                    }}
                  >
                    <span className="menu-item-left">
                      <IconAutoScroll size={17} />
                      <span>
                        {autoScrollState === 'running'
                          ? strings.ebookAutoScrollActive
                          : autoScrollState === 'paused'
                            ? strings.ebookAutoScrollPaused
                            : strings.ebookAutoScrollBtn}
                      </span>
                    </span>
                    {autoScrollState !== 'idle' && <IconCheck size={16} />}
                  </button>
                  <div className="menu-divider" />
                </>
              )}

              {view !== 'site' && (
                <>
                  <div className="ebook-tools-group-label">{strings.ebookToolsGroupReading}</div>
                  {view === 'reader' && !nav?.isTocPage && (
                    <button
                      type="button"
                      className="menu-item-btn"
                      aria-pressed={ebookPrefs.inlinePeek}
                      onClick={() => {
                        updateEbookPrefs({ inlinePeek: !ebookPrefs.inlinePeek });
                        setToolsMenuOpen(false);
                      }}
                    >
                      <span className="menu-item-left">
                        <IconEye size={17} />
                        <span>{strings.ebookInlinePeekLabel}</span>
                      </span>
                      {ebookPrefs.inlinePeek && <IconCheck size={16} />}
                    </button>
                  )}

                  <button
                    type="button"
                    className="menu-item-btn"
                    onClick={() => {
                      setToolsMenuOpen(false);
                      setChapterModalTab('bookmarks');
                      setChaptersOpen(true);
                    }}
                  >
                    <span className="menu-item-left">
                      <IconBookmark size={17} filled={bookmarks.length > 0} />
                      <span>
                        {strings.ebookBookmarksTab} ({bookmarks.length})
                      </span>
                    </span>
                  </button>

                  {effectiveTitleId && (
                    <button
                      type="button"
                      className="menu-item-btn"
                      onClick={() => {
                        setToolsMenuOpen(false);
                        onNavigate(`/kamus/${effectiveTitleId}`);
                      }}
                    >
                      <span className="menu-item-left">
                        <IconBook size={17} />
                        <span>{strings.glossary}</span>
                      </span>
                    </button>
                  )}
                </>
              )}

              {safeExternalUrl && (
                <>
                  {view !== 'site' && <div className="menu-divider" />}
                  <div className="ebook-tools-group-label">{strings.ebookToolsGroupSource}</div>
                  <button
                    type="button"
                    className="menu-item-btn"
                    onClick={() => {
                      setToolsMenuOpen(false);
                      openChapterUrl(safeExternalUrl, 'site');
                    }}
                  >
                    <span className="menu-item-left">
                      <IconGlobe size={17} />
                      <span>{strings.openAutoTranslatedTab}</span>
                    </span>
                  </button>
                  <a
                    href={safeExternalUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="menu-item-btn"
                    onClick={() => setToolsMenuOpen(false)}
                  >
                    <span className="menu-item-left">
                      <IconLink size={17} />
                      <span>{strings.openOriginalSite}</span>
                    </span>
                  </a>
                </>
              )}
            </div>
          </div>
        </>
      )}

      <main
        style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, maxWidth: '100%' }}
        inert={isMobile && (appearanceOpen || readerMenuOpen) ? true : undefined}
      >
        {loading ? (
          <div className="novel-reader-wrap" role="status" aria-live="polite">
            <div className="ebook-skeleton-card">
              <div className="skeleton-line skeleton-meta" />
              <div className="skeleton-line skeleton-title" />
              <div className="skeleton-line skeleton-title-short" />
              <div className="skeleton-divider" />
              <div className="skeleton-line" />
              <div className="skeleton-line" />
              <div className="skeleton-line skeleton-short" />
              <div className="skeleton-line" />
              <div className="skeleton-line skeleton-medium" />
              <div style={{ fontSize: '13px', color: 'var(--text-subtle)', marginTop: '6px' }}>
                {strings.loadingWebPage}
              </div>
            </div>
          </div>
        ) : errorMsg ? (
          <div className="subpage-container">
            <div className="result-card">
              <span className="status-badge error">{strings.cannotTranslateWeb}</span>
              <div>{errorMsg}</div>
              {safeExternalUrl && (
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {view !== 'site' ? (
                    <button
                      type="button"
                      className="btn-primary pressable"
                      onClick={() => openChapterUrl(safeExternalUrl, 'site')}
                    >
                      <IconGlobe size={16} />
                      {strings.openAutoTranslatedTab}
                    </button>
                  ) : autoTranslatedSiteUrl ? (
                    <a
                      href={autoTranslatedSiteUrl}
                      rel="noopener noreferrer"
                      className="btn-primary pressable"
                    >
                      <IconGlobe size={16} />
                      {strings.openAutoTranslatedTab}
                    </a>
                  ) : null}
                  <a
                    href={safeExternalUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-secondary pressable"
                  >
                    <IconLink size={16} />
                    {strings.openOriginalSite}
                  </a>
                </div>
              )}
            </div>
          </div>
        ) : view === 'site' && bundle?.siteHtml ? (
          <iframe
            key={`${bundle.url}::${mode}::${resolvedTheme || 'auto'}::site`}
            title="Pembaca Halaman Terjemahan"
            sandbox="allow-top-navigation-by-user-activation"
            srcDoc={bundle.siteHtml}
            style={{
              flex: 1,
              width: '100%',
              minHeight: 'calc(100dvh - 124px)',
              border: 'none',
              background: 'var(--bg)',
            }}
          />
        ) : bundle?.comicMeta?.isComic ? (
          <Suspense fallback={<div className="result-card">{strings.loadingWebPage}</div>}>
            <MangaLinkReader
              comicMeta={bundle.comicMeta}
              titleDst={view === 'original' ? bundle.titleSrc : bundle.titleDst || bundle.titleSrc}
              host={bundle.host}
              mode={mode}
              titleId={effectiveTitleId}
              resolvedTheme={appTheme}
              strings={strings}
              initialFirstResult={bundle.firstImageResult}
              novelNav={bundle.novelNav}
              onOpenChapterUrl={(u) => openChapterUrl(u, 'reader')}
              onCopyToast={flashReaderToast}
            />
          </Suspense>
        ) : bundle ? (
          <article
            className={`novel-reader-wrap ${bilingual && view === 'reader' && !nav?.isTocPage ? 'is-bilingual' : ''
              } ${currentSlice?.isSpread ? 'is-spread' : ''} ${ttsState !== 'idle' || autoScrollState !== 'idle' ? 'has-floating-dock' : ''
              }`}
          >
            <div className="novel-reader-header">
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  flexWrap: 'wrap',
                  fontSize: '12px',
                  color: 'var(--text-subtle)',
                }}
              >
                <span>{bundle.host}</span>
                {nav?.isNovel && (
                  <span className="status-badge done">
                    {nav.isTocPage ? strings.ebookTocBadge : strings.novelDetectedBadge}
                    {nav.chapterLabel ? ` · ${nav.chapterLabel}` : ''}
                  </span>
                )}
                {displaySeriesTitle && <span>{displaySeriesTitle}</span>}
                {readingMins > 0 && !nav?.isTocPage && (
                  <span>
                    · ~{readingMins} {strings.ebookMinUnit}
                  </span>
                )}
                {ebookPrefs.inlinePeek && view === 'reader' && !bilingual && !nav?.isTocPage && (
                  <span className="ebook-peek-badge">{strings.ebookInlinePeekHint}</span>
                )}
              </div>
              <h1 className="novel-reader-title">
                {view === 'original' ? bundle.titleSrc : bundle.titleDst}
              </h1>
            </div>

            {nav?.isTocPage && nav.chapters && nav.chapters.length > 0 && view !== 'original' ? (
              <div className="ebook-toc-hero">
                <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                  {canResumeProgress && savedProgress && (
                    <button
                      type="button"
                      className="btn-primary pressable"
                      onMouseEnter={() =>
                        prefetchNextChapterTranslatedDirect(savedProgress.url, mode, effectiveTitleId)
                      }
                      onFocus={() =>
                        prefetchNextChapterTranslatedDirect(savedProgress.url, mode, effectiveTitleId)
                      }
                      onClick={() => openChapterUrl(savedProgress.url, 'reader')}
                    >
                      <IconBook size={16} />
                      {strings.resumeReadingChapter}
                      {savedProgress.chapterLabel ? ` (${savedProgress.chapterLabel})` : ''} {'\u2192'}
                    </button>
                  )}
                  {nav.firstUrl && (
                    <button
                      type="button"
                      className={canResumeProgress ? 'btn-secondary pressable' : 'btn-primary pressable'}
                      onMouseEnter={() =>
                        prefetchNextChapterTranslatedDirect(nav.firstUrl!, mode, effectiveTitleId)
                      }
                      onFocus={() =>
                        prefetchNextChapterTranslatedDirect(nav.firstUrl!, mode, effectiveTitleId)
                      }
                      onClick={() => openChapterUrl(nav.firstUrl!, 'reader')}
                    >
                      <IconBook size={16} />
                      {strings.startReadingCh1} {'\u2192'}
                    </button>
                  )}
                  <input
                    type="search"
                    className="field-input"
                    style={{ flex: '1 1 220px', minHeight: '42px' }}
                    aria-label={strings.searchChaptersPlaceholder}
                    placeholder={strings.searchChaptersPlaceholder}
                    value={chapterQuery}
                    onChange={(e) => setChapterQuery(e.target.value)}
                  />
                </div>
                {translatingChapters && chapterTranslateProgress && (
                  <div style={{ fontSize: '12px', color: 'var(--text-subtle)' }}>
                    {strings.translatingChapters} ({chapterTranslateProgress.done}/
                    {chapterTranslateProgress.total})
                  </div>
                )}
                <div className="chapter-list-grid">
                  {filteredChapters.map(({ ch, origIndex }) => (
                    <button
                      key={`${ch.url}_${origIndex}`}
                      type="button"
                      className="chapter-list-item pressable"
                      onClick={() => openChapterUrl(ch.url, 'reader')}
                    >
                      <span>{translatedTitles[ch.url] || ch.titleDst || ch.title}</span>
                      <span style={{ fontSize: '12px', color: 'var(--text-subtle)', flexShrink: 0 }}>
                        #{origIndex}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {isPaginatedMode && currentSlice ? (
                  <div
                    className={`ebook-book-stage ${currentSlice.isSpread ? 'is-spread' : ''} ${ebookPrefs.pageMode === 'flip' ? 'is-flip' : 'is-slide'
                      }`}
                    data-ebook-book-stage="true"
                    onTouchStart={(e) => {
                      if (leafSnapTimerRef.current !== null) {
                        window.clearTimeout(leafSnapTimerRef.current);
                        leafSnapTimerRef.current = null;
                      }
                      const t = e.touches[0];
                      // 24px OS edge-swipe guard: never conflict with iOS/Android back swipe!
                      if (
                        t &&
                        t.clientX > 24 &&
                        t.clientX < (typeof window !== 'undefined' ? window.innerWidth - 24 : 9999)
                      ) {
                        const rect = e.currentTarget.getBoundingClientRect();
                        bookDragRef.current = {
                          startX: t.clientX,
                          startY: t.clientY,
                          t: Date.now(),
                          locked: 'none',
                          lastDx: 0,
                          stageW: Math.max(240, rect.width),
                        };
                      } else {
                        bookDragRef.current = null;
                      }
                    }}
                    onTouchMove={(e) => {
                      const drag = bookDragRef.current;
                      const t = e.touches[0];
                      if (!drag || !t) return;
                      const dx = t.clientX - drag.startX;
                      const dy = t.clientY - drag.startY;
                      if (drag.locked === 'none') {
                        if (Math.abs(dx) < 12 && Math.abs(dy) < 12) return;
                        drag.locked = Math.abs(dx) > Math.abs(dy) * 1.25 ? 'h' : 'v';
                      }
                      if (drag.locked !== 'h') return;
                      drag.lastDx = dx;
                      if (reducedMotionRef.current) return;
                      if (touchMoveRafRef.current) return;
                      const pageMode = ebookPrefs.pageMode;
                      const blockedPrev = dx > 0 && safePageIndex === 0 && !nav?.prevUrl;
                      const blockedNext = dx < 0 && safePageIndex >= bookPages.length - 1 && !nav?.nextUrl;
                      touchMoveRafRef.current = window.requestAnimationFrame(() => {
                        touchMoveRafRef.current = 0;
                        const leaf = bookLeafRef.current;
                        const curDrag = bookDragRef.current;
                        if (!leaf || !curDrag || curDrag.locked !== 'h') return;
                        const curDx = curDrag.lastDx;
                        const effDx = blockedPrev || blockedNext ? curDx * 0.28 : curDx;
                        const ratio = Math.max(-1, Math.min(1, effDx / curDrag.stageW));
                        leaf.style.transition = 'none';
                        if (pageMode === 'flip') {
                          const deg = Math.max(-42, Math.min(42, -ratio * 42));
                          leaf.style.transformOrigin = effDx < 0 ? 'left center' : 'right center';
                          leaf.style.transform = `translate3d(${(effDx * 0.24).toFixed(1)}px, 0, 0) rotateY(${deg.toFixed(1)}deg)`;
                          leaf.style.opacity = String(Math.max(0.76, 1 - Math.abs(ratio) * 0.22));
                        } else {
                          leaf.style.transform = `translate3d(${effDx.toFixed(1)}px, 0, 0)`;
                          leaf.style.opacity = String(Math.max(0.84, 1 - Math.abs(ratio) * 0.14));
                        }
                      });
                    }}
                    onTouchEnd={(e) => {
                      if (touchMoveRafRef.current) {
                        window.cancelAnimationFrame(touchMoveRafRef.current);
                        touchMoveRafRef.current = 0;
                      }
                      const drag = bookDragRef.current;
                      bookDragRef.current = null;
                      const t = e.changedTouches[0];
                      const leaf = bookLeafRef.current;
                      if (!drag || !t) return;
                      if (window.getSelection()?.toString().trim()) {
                        if (leaf) {
                          leaf.style.transition = '';
                          leaf.style.transform = '';
                          leaf.style.opacity = '';
                        }
                        return;
                      }
                      const dx = t.clientX - drag.startX;
                      const dy = Math.abs(t.clientY - drag.startY);
                      const dt = Math.max(1, Date.now() - drag.t);
                      const velocity = Math.abs(dx) / dt;
                      const horizontalIntent = drag.locked === 'h' || (Math.abs(dx) > 18 && Math.abs(dx) > dy * 1.25);

                      if (!horizontalIntent) {
                        if (leaf) {
                          leaf.style.transition = '';
                          leaf.style.transform = '';
                          leaf.style.opacity = '';
                        }
                        return;
                      }

                      dragSuppressClickRef.current = Date.now() + 260;
                      const shouldTurn = (Math.abs(dx) >= 28 && velocity >= 0.26) || Math.abs(dx) >= 56;
                      if (shouldTurn) {
                        if (leaf) {
                          leaf.style.transition = '';
                          leaf.style.transform = '';
                          leaf.style.opacity = '';
                        }
                        turnBookPage(dx < 0 ? 'next' : 'prev');
                      } else if (leaf) {
                        // Critically-damped spring back when released before threshold
                        leaf.style.transition =
                          'transform 220ms cubic-bezier(0.22, 1, 0.36, 1), opacity 180ms ease';
                        leaf.style.transform = 'translate3d(0, 0, 0)';
                        leaf.style.opacity = '1';
                        if (leafSnapTimerRef.current !== null) {
                          window.clearTimeout(leafSnapTimerRef.current);
                        }
                        leafSnapTimerRef.current = window.setTimeout(() => {
                          leafSnapTimerRef.current = null;
                          if (leaf) {
                            leaf.style.transition = '';
                            leaf.style.transform = '';
                            leaf.style.opacity = '';
                          }
                        }, 240);
                      }
                    }}
                    onTouchCancel={() => {
                      if (leafSnapTimerRef.current !== null) {
                        window.clearTimeout(leafSnapTimerRef.current);
                        leafSnapTimerRef.current = null;
                      }
                      bookDragRef.current = null;
                      const leaf = bookLeafRef.current;
                      if (leaf) {
                        leaf.style.transition = '';
                        leaf.style.transform = '';
                        leaf.style.opacity = '';
                      }
                    }}
                    onClick={(e) => {
                      if (Date.now() < dragSuppressClickRef.current) return;
                      if (Date.now() - lastScrollEventTsRef.current < 180) return;
                      if (window.getSelection()?.toString().trim()) return;
                      const targetEl = e.target as HTMLElement | null;
                      if (targetEl?.closest('button, a, input, select')) return;
                      const rect = e.currentTarget.getBoundingClientRect();
                      const relX = (e.clientX - rect.left) / Math.max(1, rect.width);
                      // Handedness-aware tap zones (MobileHCI / Hoober thumb-arc ergonomics)
                      const bounds = getTapZoneBounds(ebookPrefs.tapZone);
                      if (relX <= bounds.leftMaxX) turnBookPage(bounds.leftAction);
                      else if (relX >= bounds.rightMinX) turnBookPage(bounds.rightAction);
                      else setHudHidden((prev) => !prev);
                    }}
                  >
                    {/* Restrained directional edge-fold feedback overlay on tap/swipe turn */}
                    {tapCue && (
                      <div
                        key={tapCue.seq}
                        className={`ebook-tap-cue is-${tapCue.side}`}
                        data-ebook-tap-cue={tapCue.side}
                        aria-hidden="true"
                      />
                    )}
                    {/* Subtle non-intrusive desktop margin hints for tap-to-turn discoverability */}
                    {!isMobile && (
                      <>
                        <span className="ebook-edge-hint is-left" aria-hidden="true">
                          {'\u2039'}
                        </span>
                        <span className="ebook-edge-hint is-right" aria-hidden="true">
                          {'\u203A'}
                        </span>
                      </>
                    )}
                    <div
                      ref={bookLeafRef}
                      key={`${safePageIndex}-${turnAnim?.seq || 0}`}
                      className={`ebook-book-leaf novel-reader-body assistant-prose ${isJpOut ? 'is-jp' : ''} ${currentSlice.isSpread ? 'is-spread' : ''
                        } ${turnAnim
                          ? ebookPrefs.pageMode === 'flip'
                            ? turnAnim.dir === 'next'
                              ? 'anim-flip-next'
                              : 'anim-flip-prev'
                            : turnAnim.dir === 'next'
                              ? 'anim-slide-next'
                              : 'anim-slide-prev'
                          : ''
                        }`}
                      lang={view === 'original' ? bundle.detectedSource : tgt}
                    >
                      {currentSlice.isSpread ? (
                        <div className="ebook-spread-grid" data-ebook-spread-grid="true">
                          <div className="ebook-spread-col">
                            {(currentSlice.leftPairs || []).map((pair, localIdx) =>
                              renderReadingParagraph(pair, currentSlice.startParaIdx + localIdx)
                            )}
                          </div>
                          <div className="ebook-spread-col">
                            {(currentSlice.rightPairs || []).map((pair, localIdx) =>
                              renderReadingParagraph(
                                pair,
                                currentSlice.startParaIdx +
                                (currentSlice.leftPairs?.length || 0) +
                                localIdx
                              )
                            )}
                          </div>
                        </div>
                      ) : (
                        currentSlice.pairs.map((pair, localIdx) =>
                          renderReadingParagraph(pair, currentSlice.startParaIdx + localIdx)
                        )
                      )}
                    </div>

                    <div className="ebook-page-bar">
                      <button
                        type="button"
                        className="btn-secondary pressable"
                        aria-label={strings.ebookPrevPage}
                        disabled={safePageIndex === 0 && !nav?.prevUrl}
                        onClick={() => turnBookPage('prev')}
                      >
                        {'\u2190'}
                      </button>

                      <div className="ebook-scrubber-center">
                        <span className="ebook-page-indicator" data-ebook-page-indicator="true">
                          {strings.ebookPageCounter} {safePageIndex + 1} / {bookPages.length}
                          {` · ${progressPct}%`}
                          {readingMins > 0 ? ` · ~${readingMins} ${strings.ebookMinUnit}` : ''}
                        </span>
                        {bookPages.length > 1 && (
                          <input
                            type="range"
                            className="ebook-page-scrubber"
                            aria-label={strings.ebookScrubberLabel}
                            min={1}
                            max={bookPages.length}
                            value={safePageIndex + 1}
                            onChange={(e) => {
                              const nextIdx = Number(e.target.value) - 1;
                              if (Math.abs(nextIdx - safePageIndex) >= 2 && currentSlice) {
                                setJumpBackParaIdx(currentSlice.startParaIdx);
                              }
                              jumpToPage(nextIdx, nextIdx > safePageIndex ? 'next' : 'prev');
                            }}
                          />
                        )}
                      </div>

                      <button
                        type="button"
                        className="btn-primary pressable"
                        aria-label={strings.ebookNextPage}
                        disabled={safePageIndex >= bookPages.length - 1 && !nav?.nextUrl}
                        onClick={() => turnBookPage('next')}
                      >
                        {'\u2192'}
                      </button>
                    </div>
                    {jumpBackParaIdx !== null && (
                      <div style={{ display: 'flex', justifyContent: 'center', marginTop: '8px' }}>
                        <button
                          type="button"
                          className="btn-secondary pressable"
                          data-ebook-jump-back="true"
                          onClick={() => {
                            const targetPage = findPageIndexForParagraph(bookPages, jumpBackParaIdx);
                            setJumpBackParaIdx(null);
                            jumpToPage(targetPage, targetPage > safePageIndex ? 'next' : 'prev');
                          }}
                        >
                          {'\u21A9'} {strings.ebookJumpBackBtn}
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <div
                    className={`novel-reader-body assistant-prose ${isJpOut ? 'is-jp' : ''}`}
                    lang={view === 'original' ? bundle.detectedSource : tgt}
                    onClick={(e) => {
                      if (window.getSelection()?.toString().trim()) return;
                      const targetEl = e.target as HTMLElement | null;
                      if (targetEl?.closest('button, a, input, select')) return;
                      if (autoScrollState !== 'idle') {
                        // Guard against mobile touchstart->click self-resume race
                        if (Date.now() - lastAutoScrollTouchPauseRef.current < 450) return;
                        handleToggleAutoScroll();
                        return;
                      }
                      if (!isMobile || ebookPrefs.inlinePeek) return;
                      setHudHidden((prev) => !prev);
                    }}
                  >
                    {bundle.sentences.map((pair, idx) => renderReadingParagraph(pair, idx))}
                  </div>
                )}

                {streamProgress && (
                  <div className="ebook-stream-footer">
                    <div className="skeleton-line skeleton-medium" />
                    <div style={{ fontSize: '13px', color: 'var(--text-subtle)' }}>
                      {strings.streamingProgressLabel} ({streamProgress.done}/{streamProgress.total})...
                    </div>
                  </div>
                )}

                {nav?.isNovel && !streamProgress && (
                  <div className="ebook-next-card">
                    {nav.nextUrl ? (
                      <>
                        <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                          {strings.continueNextChapter}
                        </div>
                        {nextChapterDisplayTitle && (
                          <div style={{ fontWeight: 600, fontSize: '16px' }}>
                            {nextChapterDisplayTitle}
                          </div>
                        )}
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            className="btn-primary pressable"
                            onMouseEnter={() =>
                              prefetchNextChapterTranslatedDirect(nav.nextUrl!, mode, effectiveTitleId)
                            }
                            onFocus={() =>
                              prefetchNextChapterTranslatedDirect(nav.nextUrl!, mode, effectiveTitleId)
                            }
                            onClick={() => openChapterUrl(nav.nextUrl!)}
                          >
                            {strings.nextChapter} {'\u2192'}
                          </button>
                          {nav.chapters && nav.chapters.length > 0 && (
                            <button
                              type="button"
                              className="btn-secondary pressable"
                              onClick={() => {
                                setChapterModalTab('chapters');
                                setChaptersOpen(true);
                              }}
                            >
                              <IconBook size={16} />
                              {strings.chapterListBtn} ({nav.chapters.length})
                            </button>
                          )}
                        </div>
                      </>
                    ) : (
                      <>
                        <div style={{ fontWeight: 600, fontSize: '15px' }}>
                          {strings.lastChapterReached}
                          {nav.chapterLabel ? ` (${nav.chapterLabel})` : ''}
                        </div>
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                          {canRestartFromCh1 && nav.firstUrl && (
                            <button
                              type="button"
                              className="btn-primary pressable"
                              onClick={() => openChapterUrl(nav.firstUrl!)}
                            >
                              <IconBook size={16} />
                              {strings.readFromChapter1}
                            </button>
                          )}
                          {nav.prevUrl && (
                            <button
                              type="button"
                              className="btn-secondary pressable"
                              onClick={() => openChapterUrl(nav.prevUrl!)}
                            >
                              {'\u2190'} {strings.prevChapter}
                            </button>
                          )}
                          {(nav.chapters?.length || nav.tocUrl) && (
                            <button
                              type="button"
                              className="btn-secondary pressable"
                              onClick={() => {
                                setChapterModalTab('chapters');
                                setChaptersOpen(true);
                              }}
                            >
                              <IconBook size={16} />
                              {strings.chapterListBtn}
                              {nav.chapters?.length ? ` (${nav.chapters.length})` : ''}
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </article>
        ) : null}
      </main>

      {/* Floating Podcast Narration Studio Pill & Expandable Style/Voice/Sleep Drawer */}
      {ttsState !== 'idle' && (
        <aside
          className="ebook-floating-dock-wrap"
          role="region"
          aria-label={strings.ebookPodcastBtn}
          data-ebook-podcast-bar="true"
        >
          {podcastStudioOpen && (
            <div
              className="ebook-podcast-studio glass-regular-surface"
              data-ebook-podcast-studio="true"
              role="dialog"
              aria-modal="false"
              aria-label={strings.ebookPodcastStudioBtn}
            >
              <div className="ebook-studio-head">
                <div className="ebook-studio-meta">
                  <span className="ebook-studio-badge">
                    {ttsKind === 'dialogue' || ttsKind === 'dialogue_alt' || ttsKind === 'speech_tag'
                      ? strings.ebookPodcastKindDialogue
                      : ttsKind === 'inner_thought' || ttsKind === 'parenthetical'
                        ? strings.ebookPodcastKindThought
                        : ttsKind === 'polar_question' || ttsKind === 'wh_question' || ttsKind === 'question'
                          ? strings.ebookPodcastKindQuestion
                          : ttsKind === 'code_summary'
                            ? strings.ebookPodcastKindCode
                            : ttsKind === 'table_row'
                              ? strings.ebookPodcastKindTable
                              : ttsKind === 'list_item'
                                ? strings.ebookPodcastKindList
                                : ttsKind === 'verse_line'
                                  ? strings.ebookPodcastKindVerse
                                  : ttsKind === 'chapter_intro' || ttsKind === 'heading'
                                    ? strings.ebookPodcastKindIntro
                                    : strings.ebookPodcastKindNarration}
                  </span>
                  <span
                    className="ebook-studio-badge"
                    data-ebook-podcast-format-badge={
                      podcastFormatOverride === 'auto' ? detectedPodcastFormat : podcastFormatOverride
                    }
                  >
                    {podcastFormatLabel(
                      podcastFormatOverride === 'auto' ? detectedPodcastFormat : podcastFormatOverride
                    )}
                  </span>
                  {activeSpeakerName && (
                    <span className="ebook-studio-badge" data-ebook-podcast-speaker={activeSpeakerName}>
                      {activeSpeakerName}
                    </span>
                  )}
                  {podcastLocalFallback && (
                    <span className="ebook-studio-badge" data-ebook-podcast-local-fallback="true">
                      {strings.ebookPodcastLocalFallbackPill}
                    </span>
                  )}
                  {bundle && ttsParaIdx !== null && (
                    <span className="ebook-studio-pos">
                      {ttsParaIdx + 1} / {bundle.sentences.length}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  className="icon-square-btn"
                  aria-label={strings.closeLabel}
                  onClick={() => setPodcastStudioOpen(false)}
                >
                  <IconX size={16} />
                </button>
              </div>

              <div className="ebook-studio-section">
                <span className="ebook-appear-label">{strings.ebookPodcastStyleLabel}</span>
                <div className="ebook-seg-row" role="radiogroup" aria-label={strings.ebookPodcastStyleLabel}>
                  {(
                    [
                      ['podcast_santai', strings.ebookPodcastStyleSantai],
                      ['narasi_buku', strings.ebookPodcastStyleNarasi],
                      ['fokus_cepat', strings.ebookPodcastStyleCepat],
                    ] as ReadonlyArray<readonly [PodcastStyleId, string]>
                  ).map(([styleId, label]) => (
                    <button
                      key={styleId}
                      type="button"
                      role="radio"
                      aria-checked={podcastStyle === styleId}
                      data-ebook-podcast-style={styleId}
                      className={`ebook-seg-btn pressable ${podcastStyle === styleId ? 'active' : ''}`}
                      onClick={() => handleChangePodcastStyle(styleId)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="ebook-studio-section">
                <label className="ebook-appear-label" htmlFor="ebook-podcast-format-select">
                  {strings.ebookPodcastFormatLabel}
                </label>
                <select
                  id="ebook-podcast-format-select"
                  data-ebook-podcast-format-select="true"
                  className="field-select"
                  style={{ width: '100%', minHeight: '44px', fontSize: isMobile ? '16px' : '14px' }}
                  value={podcastFormatOverride}
                  onChange={(e) => handleChangePodcastFormat(e.target.value as 'auto' | DocumentFormatId)}
                >
                  <option value="auto">
                    {strings.ebookPodcastFormatAuto} ({podcastFormatLabel(detectedPodcastFormat)})
                  </option>
                  <option value="fiction_novel">{strings.ebookPodcastFormatFiction}</option>
                  <option value="script_dialogue">{strings.ebookPodcastFormatScript}</option>
                  <option value="news_editorial">{strings.ebookPodcastFormatNews}</option>
                  <option value="academic_paper">{strings.ebookPodcastFormatAcademic}</option>
                  <option value="technical_docs">{strings.ebookPodcastFormatTech}</option>
                  <option value="list_instructions">{strings.ebookPodcastFormatList}</option>
                  <option value="poetry_verse">{strings.ebookPodcastFormatPoetry}</option>
                  <option value="letter_quote">{strings.ebookPodcastFormatLetter}</option>
                </select>
              </div>

              {((podcastFormatOverride === 'auto' ? detectedPodcastFormat : podcastFormatOverride) === 'fiction_novel' ||
                (podcastFormatOverride === 'auto' ? detectedPodcastFormat : podcastFormatOverride) === 'script_dialogue') && (
                  <div className="ebook-studio-section">
                    <span className="ebook-appear-label">{strings.ebookPodcastCastLabel}</span>
                    <div className="ebook-seg-row is-compact" role="radiogroup" aria-label={strings.ebookPodcastCastLabel}>
                      {(
                        [
                          ['single', strings.ebookPodcastCastSingle],
                          ['persona', strings.ebookPodcastCastPersona],
                          ['multi_voice', strings.ebookPodcastCastMulti],
                        ] as ReadonlyArray<readonly [PodcastCastMode, string]>
                      ).map(([castId, label]) => (
                        <button
                          key={castId}
                          type="button"
                          role="radio"
                          aria-checked={podcastCastMode === castId}
                          data-ebook-podcast-cast={castId}
                          className={`ebook-seg-btn pressable ${podcastCastMode === castId ? 'active' : ''}`}
                          onClick={() => handleChangePodcastCastMode(castId)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

              {rankedVoices.length > 0 && (
                <div className="ebook-studio-section">
                  <label className="ebook-appear-label" htmlFor="ebook-podcast-voice-select">
                    {strings.ebookPodcastVoiceLabel}
                  </label>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                    <select
                      id="ebook-podcast-voice-select"
                      className="field-select"
                      style={{ flex: 1, minHeight: '44px', fontSize: isMobile ? '16px' : '14px' }}
                      value={podcastVoiceUri}
                      onChange={(e) => handleChangePodcastVoice(e.target.value)}
                    >
                      <option value="">{strings.ebookPodcastVoiceAuto}</option>
                      {rankedVoices.map((v) => (
                        <option key={v.uri} value={v.uri}>
                          {v.label}
                          {v.isNeural ? ' · Alami' : ''}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="icon-square-btn pressable"
                      data-ebook-voice-preview="true"
                      style={{ minWidth: '44px', minHeight: '44px' }}
                      aria-label={strings.ebookPodcastPreviewVoiceBtn}
                      title={strings.ebookPodcastPreviewVoiceBtn}
                      onClick={() => ttsCtrlRef.current?.previewVoice(podcastVoiceUri, activeSpeakLang)}
                    >
                      <IconPlay size={16} />
                    </button>
                  </div>
                </div>
              )}

              <div className="ebook-studio-section">
                <span className="ebook-appear-label">
                  {strings.ebookPodcastSleepLabel}
                  <SleepCountdownBadge
                    active={ttsState === 'playing' && (sleepPreset === '15' || sleepPreset === '30')}
                    seedSec={sleepCountdownSeed.sec}
                    seedSeq={sleepCountdownSeed.seq}
                  />
                </span>
                <div className="ebook-sleep-row" role="radiogroup" aria-label={strings.ebookPodcastSleepLabel}>
                  {(
                    [
                      ['off', strings.ebookPodcastSleepOff],
                      ['15', strings.ebookPodcastSleep15],
                      ['30', strings.ebookPodcastSleep30],
                      ['chapter', strings.ebookPodcastSleepChapter],
                    ] as ReadonlyArray<readonly [PodcastSleepPreset, string]>
                  ).map(([presetId, label]) => (
                    <button
                      key={presetId}
                      type="button"
                      role="radio"
                      aria-checked={sleepPreset === presetId}
                      data-ebook-sleep-btn={presetId}
                      className={`ebook-filter-chip pressable ${sleepPreset === presetId ? 'active' : ''}`}
                      onClick={() => handleChangeSleepPreset(presetId)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="ebook-tts-bar glass-regular-surface">
            <span
              className={`ebook-eq-bars ${ttsState === 'playing' ? 'is-playing' : ''}`}
              aria-hidden="true"
            >
              <span />
              <span />
              <span />
            </span>

            <button
              type="button"
              className="icon-square-btn pressable ebook-dock-icon-btn"
              aria-label={strings.ebookPodcastPrevPara}
              onClick={() => ttsCtrlRef.current?.skipParagraph(-1)}
            >
              <IconSkipBack size={16} />
            </button>

            <button
              type="button"
              className="btn-primary pressable ebook-dock-play-btn"
              aria-label={ttsState === 'playing' ? strings.ebookListenPause : strings.ebookListenResume}
              aria-pressed={ttsState === 'playing'}
              onClick={handleToggleTts}
            >
              {ttsState === 'playing' ? <IconPause size={16} /> : <IconPlay size={16} />}
            </button>

            <button
              type="button"
              className="icon-square-btn pressable ebook-dock-icon-btn"
              aria-label={strings.ebookPodcastNextPara}
              onClick={() => ttsCtrlRef.current?.skipParagraph(1)}
            >
              <IconSkipForward size={16} />
            </button>

            <button
              type="button"
              className="btn-secondary pressable ebook-dock-chip-btn"
              aria-label={`Kecepatan ${ttsRate}x`}
              onClick={handleCycleTtsRate}
            >
              {ttsRate}x
            </button>

            {podcastUserDetached && !isPaginatedMode && ttsParaIdx !== null && (
              <button
                type="button"
                className="btn-secondary pressable ebook-dock-chip-btn"
                onClick={() => {
                  setPodcastUserDetached(false);
                  programmaticScrollUntilRef.current = Date.now() + 650;
                  scrollActiveParagraphIntoComfortZone(ttsParaIdx);
                }}
              >
                {strings.ebookPodcastFollowBtn}
              </button>
            )}

            <button
              type="button"
              className={`icon-square-btn pressable ebook-dock-icon-btn ${podcastStudioOpen ? 'ebook-bookmark-active' : ''}`}
              aria-label={strings.ebookPodcastStudioBtn}
              aria-expanded={podcastStudioOpen}
              data-ebook-podcast-studio-btn="true"
              onClick={() => setPodcastStudioOpen((v) => !v)}
            >
              <IconSliders size={16} />
            </button>

            <button
              type="button"
              className="icon-square-btn pressable ebook-dock-icon-btn"
              aria-label={strings.ebookListenStop}
              onClick={() => ttsCtrlRef.current?.stop()}
            >
              <IconX size={16} />
            </button>
          </div>
        </aside>
      )}

      {/* Mutually-Exclusive Floating Auto-Gulir Pill (visible ONLY when Auto-Scroll active & Podcast idle) */}
      {ttsState === 'idle' && autoScrollState !== 'idle' && (
        <aside
          className="ebook-floating-dock-wrap"
          role="region"
          aria-label={strings.ebookAutoScrollBtn}
          data-ebook-autoscroll-bar="true"
        >
          <div className="ebook-tts-bar glass-regular-surface">
            <IconAutoScroll size={17} />

            <button
              type="button"
              className="btn-primary pressable ebook-dock-play-btn"
              aria-label={
                autoScrollState === 'running' ? strings.ebookListenPause : strings.ebookListenResume
              }
              aria-pressed={autoScrollState === 'running'}
              onClick={handleToggleAutoScroll}
            >
              {autoScrollState === 'running' ? <IconPause size={16} /> : <IconPlay size={16} />}
            </button>

            <button
              type="button"
              className="btn-secondary pressable ebook-dock-chip-btn"
              aria-label={strings.ebookAutoScrollSpeedDown}
              disabled={autoScrollSpeed <= AUTO_SCROLL_SPEEDS[0]}
              onClick={() => handleStepAutoScrollSpeed(-1)}
            >
              -
            </button>

            <span className="ebook-autoscroll-speed" data-ebook-autoscroll-speed="true">
              {autoScrollSpeed.toFixed(1)}x
            </span>

            <button
              type="button"
              className="btn-secondary pressable ebook-dock-chip-btn"
              aria-label={strings.ebookAutoScrollSpeedUp}
              disabled={autoScrollSpeed >= AUTO_SCROLL_SPEEDS[AUTO_SCROLL_SPEEDS.length - 1]}
              onClick={() => handleStepAutoScrollSpeed(1)}
            >
              +
            </button>

            <button
              type="button"
              className="icon-square-btn pressable ebook-dock-icon-btn"
              aria-label={strings.ebookAutoScrollStop}
              onClick={() => autoScrollCtrlRef.current?.stop()}
            >
              <IconX size={16} />
            </button>
          </div>
        </aside>
      )}

      {!chromeHidden &&
        !loading &&
        !errorMsg &&
        nav &&
        (nav.prevUrl || nav.nextUrl || nav.chapters?.length || nav.tocUrl) && (
          <nav
            className="novel-chapter-dock"
            aria-label={strings.chapterListBtn}
            inert={isMobile && (appearanceOpen || readerMenuOpen) ? true : undefined}
          >
            <div className={`novel-chapter-dock-inner ${isMobile ? 'is-mobile' : ''}`}>
              <button
                type="button"
                className="btn-secondary pressable"
                aria-label={strings.prevChapter}
                disabled={!nav.prevUrl}
                onClick={() => nav.prevUrl && openChapterUrl(nav.prevUrl)}
              >
                {'\u2190'} {isMobile ? strings.shortPrevChapter : strings.prevChapter}
              </button>

              <button
                type="button"
                className="btn-secondary pressable"
                aria-label={`${strings.chapterListBtn}${nav.chapterLabel ? ` (${nav.chapterLabel})` : ''}`}
                onClick={() => {
                  setChapterModalTab('chapters');
                  setChaptersOpen(true);
                }}
              >
                <IconBook size={16} />
                <span className="chapter-dock-center-label">
                  {isMobile
                    ? nav.chapterLabel || strings.chapterListBtn
                    : `${strings.chapterListBtn}${nav.chapterLabel ? ` (${nav.chapterLabel})` : ''}`}
                </span>
              </button>

              {nav.nextUrl ? (
                <button
                  type="button"
                  className="btn-primary pressable"
                  aria-label={nav.isTocPage ? strings.startReadingCh1 : strings.nextChapter}
                  onMouseEnter={() =>
                    prefetchNextChapterTranslatedDirect(
                      nav.nextUrl!,
                      mode,
                      effectiveTitleId,
                      view === 'site' ? 'site' : 'reader',
                      resolvedTheme
                    )
                  }
                  onFocus={() =>
                    prefetchNextChapterTranslatedDirect(
                      nav.nextUrl!,
                      mode,
                      effectiveTitleId,
                      view === 'site' ? 'site' : 'reader',
                      resolvedTheme
                    )
                  }
                  onClick={() => openChapterUrl(nav.nextUrl!)}
                >
                  {isMobile
                    ? nav.isTocPage
                      ? 'Bab 1'
                      : strings.shortNextChapter
                    : nav.isTocPage
                      ? strings.startReadingCh1
                      : strings.nextChapter}{' '}
                  {'\u2192'}
                </button>
              ) : canRestartFromCh1 && nav.firstUrl ? (
                <button
                  type="button"
                  className="btn-primary pressable"
                  aria-label={strings.readFromChapter1}
                  onClick={() => openChapterUrl(nav.firstUrl!)}
                >
                  {isMobile ? 'Bab 1' : strings.readFromChapter1}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-secondary"
                  aria-label={strings.nextChapter}
                  disabled
                >
                  {isMobile ? strings.shortNextChapter : strings.nextChapter} {'\u2192'}
                </button>
              )}
            </div>
          </nav>
        )}

      {isMobile && readerMenuOpen && (
        <div className="bottom-sheet-backdrop" onClick={() => setReaderMenuOpen(false)}>
          <div
            ref={readerMenuDialogRef}
            className="bottom-sheet glass-regular-surface"
            role="dialog"
            aria-modal="true"
            aria-label={strings.readerMenuLabel}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="sheet-handle-btn"
              aria-label={strings.closeLabel}
              onClick={() => setReaderMenuOpen(false)}
            >
              <span className="sheet-handle-pill" />
            </button>
            <div className="reader-sheet-section">
              <div className="reader-sheet-label">{strings.langMenuTitle}</div>
              <select
                className="field-select"
                style={{ width: '100%', minHeight: '44px', fontSize: '16px' }}
                value={mode}
                onChange={(e) => {
                  setMode(e.target.value as ModePair);
                  setReaderMenuOpen(false);
                }}
                aria-label={strings.langMenuTitle}
              >
                <option value="auto-id">{strings.langAuto} {'\u2192'} {strings.langId}</option>
                <option value="auto-en">{strings.langAuto} {'\u2192'} {strings.langEn}</option>
                <option value="auto-ja">{strings.langAuto} {'\u2192'} {strings.langJa}</option>
                <option value="ja-id">{strings.langJa} {'\u2192'} {strings.langId}</option>
                <option value="ja-en">{strings.langJa} {'\u2192'} {strings.langEn}</option>
                <option value="id-ja">{strings.langId} {'\u2192'} {strings.langJa}</option>
                <option value="id-en">{strings.langId} {'\u2192'} {strings.langEn}</option>
                <option value="en-id">{strings.langEn} {'\u2192'} {strings.langId}</option>
                <option value="en-ja">{strings.langEn} {'\u2192'} {strings.langJa}</option>
              </select>
            </div>
            <div className="menu-divider" />
            <button
              type="button"
              className="sheet-row-btn"
              onClick={() => {
                setView('reader');
                setReaderMenuOpen(false);
              }}
            >
              <IconBook size={20} />
              <span style={{ flex: 1 }}>{strings.readerModeTab}</span>
              {view === 'reader' && <IconCheck size={18} style={{ color: 'var(--accent)' }} />}
            </button>
            <button
              type="button"
              className="sheet-row-btn"
              onClick={() => {
                setView('site');
                setReaderMenuOpen(false);
              }}
            >
              <IconGlobe size={20} />
              <span style={{ flex: 1 }}>{strings.translatedSiteTab}</span>
              {view === 'site' && <IconCheck size={18} style={{ color: 'var(--accent)' }} />}
            </button>
            <button
              type="button"
              className="sheet-row-btn"
              onClick={() => {
                setView('original');
                setReaderMenuOpen(false);
              }}
            >
              <IconLink size={20} />
              <span style={{ flex: 1 }}>{strings.originalViewTab}</span>
              {view === 'original' && <IconCheck size={18} style={{ color: 'var(--accent)' }} />}
            </button>
            {view === 'reader' && !nav?.isTocPage && (
              <>
                <button
                  type="button"
                  className="sheet-row-btn"
                  aria-pressed={bilingual}
                  onClick={() => {
                    setBilingual((v) => !v);
                    setReaderMenuOpen(false);
                  }}
                >
                  <IconColumns size={20} />
                  <span style={{ flex: 1 }}>{strings.bilingualToggle}</span>
                  {bilingual && <IconCheck size={18} style={{ color: 'var(--accent)' }} />}
                </button>
                <button
                  type="button"
                  className="sheet-row-btn"
                  aria-pressed={ebookPrefs.inlinePeek}
                  onClick={() => {
                    updateEbookPrefs({ inlinePeek: !ebookPrefs.inlinePeek });
                    setReaderMenuOpen(false);
                  }}
                >
                  <IconEye size={20} />
                  <span style={{ flex: 1 }}>{strings.ebookInlinePeekLabel}</span>
                  {ebookPrefs.inlinePeek && <IconCheck size={18} style={{ color: 'var(--accent)' }} />}
                </button>
              </>
            )}
            {view !== 'site' && (
              <>
                <button
                  type="button"
                  className="sheet-row-btn"
                  onClick={() => {
                    setReaderMenuOpen(false);
                    setAppearanceOpen(true);
                  }}
                >
                  <span style={{ width: '20px', textAlign: 'center', fontFamily: 'var(--font-result)', fontWeight: 700 }}>
                    Aa
                  </span>
                  <span style={{ flex: 1 }}>{strings.ebookAppearanceTitle}</span>
                </button>
                {!nav?.isTocPage && (
                  <>
                    <div className="menu-divider" />
                    <div className="ebook-tools-group-label" style={{ padding: '4px 12px 2px 12px' }}>
                      {strings.ebookToolsGroupHandsFree}
                    </div>
                    <button
                      type="button"
                      className="sheet-row-btn"
                      data-ebook-podcast-trigger="true"
                      onClick={() => {
                        setReaderMenuOpen(false);
                        handleToggleTts();
                      }}
                    >
                      <IconHeadphones size={20} />
                      <span style={{ flex: 1 }}>
                        {ttsState === 'playing'
                          ? strings.ebookListenPause
                          : ttsState === 'paused'
                            ? strings.ebookListenResume
                            : strings.ebookPodcastBtn}
                      </span>
                      {ttsState !== 'idle' && <IconCheck size={18} style={{ color: 'var(--accent)' }} />}
                    </button>
                    <button
                      type="button"
                      className="sheet-row-btn"
                      data-ebook-autoscroll-trigger="true"
                      onClick={() => {
                        setReaderMenuOpen(false);
                        handleToggleAutoScroll();
                      }}
                    >
                      <IconAutoScroll size={20} />
                      <span style={{ flex: 1 }}>
                        {autoScrollState === 'running'
                          ? strings.ebookAutoScrollActive
                          : autoScrollState === 'paused'
                            ? strings.ebookAutoScrollPaused
                            : strings.ebookAutoScrollBtn}
                      </span>
                      {autoScrollState !== 'idle' && (
                        <IconCheck size={18} style={{ color: 'var(--accent)' }} />
                      )}
                    </button>
                    <div className="menu-divider" />
                    <div className="ebook-tools-group-label" style={{ padding: '4px 12px 2px 12px' }}>
                      {strings.ebookToolsGroupReading}
                    </div>
                    <button
                      type="button"
                      className="sheet-row-btn"
                      onClick={() => {
                        setReaderMenuOpen(false);
                        handleToggleCurrentBookmark();
                      }}
                    >
                      <IconBookmark size={20} filled={isCurrentBookmarked} />
                      <span style={{ flex: 1 }}>
                        {isCurrentBookmarked ? strings.ebookBookmarkSaved : strings.ebookBookmarkAdd}
                      </span>
                    </button>
                  </>
                )}
              </>
            )}
            <div className="menu-divider" />
            {nav && (nav.chapters?.length || nav.tocUrl || bookmarks.length > 0) && (
              <button
                type="button"
                className="sheet-row-btn"
                onClick={() => {
                  setReaderMenuOpen(false);
                  setChapterModalTab('chapters');
                  setChaptersOpen(true);
                }}
              >
                <IconBook size={20} />
                <span style={{ flex: 1 }}>
                  {strings.chapterListBtn}
                  {nav.chapterLabel ? ` (${nav.chapterLabel})` : ''}
                </span>
              </button>
            )}
            {effectiveTitleId && (
              <button
                type="button"
                className="sheet-row-btn"
                onClick={() => {
                  setReaderMenuOpen(false);
                  onNavigate(`/kamus/${effectiveTitleId}`);
                }}
              >
                <IconBook size={20} />
                <span style={{ flex: 1 }}>{strings.glossary}</span>
              </button>
            )}
          </div>
        </div>
      )}

      {appearanceOpen && view !== 'site' && (
        <Suspense fallback={null}>
          <EbookAppearancePanel
            prefs={ebookPrefs}
            appResolvedTheme={appTheme}
            isMobile={isMobile}
            canUseSpread={canUseSpread}
            isEnglishUi={isEnglishUi}
            strings={strings}
            onUpdate={updateEbookPrefs}
            onClose={() => setAppearanceOpen(false)}
          />
        </Suspense>
      )}

      {chaptersOpen && (
        <div className="scrim-backdrop" onClick={() => setChaptersOpen(false)}>
          <div
            ref={chaptersDialogRef}
            className={`modal-dialog ${(nav?.chapters?.length || 0) > 10 ? 'is-chapter-modal' : ''}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="chapter-list-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 id="chapter-list-title" className="modal-title">
                {displaySeriesTitle || strings.chapterListBtn}
                {nav?.chapters?.length ? ` (${nav.chapters.length})` : ''}
              </h2>
              <button
                type="button"
                className="icon-square-btn"
                aria-label={strings.closeLabel}
                onClick={() => setChaptersOpen(false)}
              >
                <IconX size={18} />
              </button>
            </div>

            <div className="ebook-modal-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={chapterModalTab === 'chapters'}
                className={chapterModalTab === 'chapters' ? 'btn-primary pressable' : 'btn-secondary pressable'}
                onClick={() => setChapterModalTab('chapters')}
              >
                {strings.ebookChaptersTab}
                {nav?.chapters?.length ? ` (${nav.chapters.length})` : ''}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={chapterModalTab === 'bookmarks'}
                className={chapterModalTab === 'bookmarks' ? 'btn-primary pressable' : 'btn-secondary pressable'}
                onClick={() => setChapterModalTab('bookmarks')}
              >
                {strings.ebookBookmarksTab} ({bookmarks.length})
              </button>
            </div>

            <div className="modal-body">
              {chapterModalTab === 'bookmarks' ? (
                bookmarks.length === 0 ? (
                  <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                    {strings.ebookNoBookmarks}
                  </div>
                ) : (
                  <div className="ebook-bookmark-list">
                    {bookmarks.map((bm) => (
                      <div key={bm.id} className="ebook-bookmark-row">
                        <button
                          type="button"
                          className="ebook-bookmark-jump pressable"
                          onClick={() => {
                            setChaptersOpen(false);
                            if (bm.url === (bundle?.url || url)) {
                              jumpToParagraph(bm.paraIdx);
                            } else {
                              openChapterUrl(bm.url, 'reader', `p${bm.paraIdx}`);
                            }
                          }}
                        >
                          <div className="ebook-bookmark-meta">
                            <span>{bm.chapterLabel || bm.titleDst}</span>
                            <span>· #{bm.paraIdx + 1}</span>
                          </div>
                          <div className="ebook-bookmark-excerpt">{bm.excerpt}</div>
                        </button>
                        <button
                          type="button"
                          className="icon-square-btn pressable"
                          aria-label={strings.deleteChat}
                          onClick={() => setBookmarks(removeBookmark(bm.id, seriesKey))}
                        >
                          <IconTrash size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <>
                  {nav?.chapters && nav.chapters.length > 6 && (
                    <input
                      type="search"
                      className="field-input"
                      aria-label={strings.searchChaptersPlaceholder}
                      placeholder={strings.searchChaptersPlaceholder}
                      value={chapterQuery}
                      onChange={(e) => setChapterQuery(e.target.value)}
                    />
                  )}
                  {translatingChapters && chapterTranslateProgress && (
                    <div style={{ fontSize: '12px', color: 'var(--text-subtle)' }}>
                      {strings.translatingChapters} ({chapterTranslateProgress.done}/
                      {chapterTranslateProgress.total})
                    </div>
                  )}
                  {nav?.tocUrl && (
                    <div>
                      <button
                        type="button"
                        className="btn-secondary pressable"
                        onClick={() => openChapterUrl(nav.tocUrl!, 'reader')}
                      >
                        <IconGlobe size={16} />
                        {strings.openTocSite}
                      </button>
                    </div>
                  )}
                  {filteredChapters.length > 0 ? (
                    <div className="chapter-list-grid">
                      {filteredChapters.map(({ ch, origIndex }) => (
                        <button
                          key={`${ch.url}_${origIndex}`}
                          type="button"
                          className={`chapter-list-item pressable ${ch.current ? 'is-current' : ''}`}
                          onClick={() => openChapterUrl(ch.url)}
                        >
                          <span>
                            {view === 'original'
                              ? ch.title
                              : translatedTitles[ch.url] || ch.titleDst || ch.title}
                          </span>
                          {ch.current && (
                            <span className="status-badge done">{strings.currentChapterBadge}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                      {strings.noChaptersFound}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const SleepCountdownBadge = memo(function SleepCountdownBadge({
  active,
  seedSec,
  seedSeq,
}: {
  active: boolean;
  seedSec: number;
  seedSeq: number;
}) {
  const [sec, setSec] = useState(seedSec);

  useEffect(() => {
    setSec(seedSec);
  }, [seedSec, seedSeq]);

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => {
      setSec((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => window.clearInterval(id);
  }, [active, seedSeq]);

  if (sec <= 0) return null;
  return (
    <span style={{ marginLeft: '6px', fontVariantNumeric: 'tabular-nums' }} data-ebook-sleep-countdown="true">
      ({String(Math.floor(sec / 60)).padStart(2, '0')}:{String(sec % 60).padStart(2, '0')})
    </span>
  );
});

/* /c/:cid/m/:mid/baca: Unified Side-by-Side Document Reader sharing Dual-Slot Theme, Podcast Narration & Auto-Gulir */
export function SideBySideReaderView({
  user,
  cid,
  mid,
  messages,
  resolvedTheme,
  strings,
  onNavigate,
}: {
  user: AuthSessionUser;
  cid: string;
  mid: string;
  messages: TurnMessage[];
  resolvedTheme: ResolvedTheme;
  strings: UiStrings;
  onNavigate: (path: string) => void;
}) {
  const [htmlPreview, setHtmlPreview] = useState<string>('');
  const [ebookPrefs, setEbookPrefs] = useState<EbookPrefs>(() => loadEbookPrefs());
  const sidePrefsRef = useRef<EbookPrefs>(ebookPrefs);
  sidePrefsRef.current = ebookPrefs;
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [inlineToast, setInlineToast] = useState<string | null>(null);
  const [ttsState, setTtsState] = useState<TtsPlaybackState>('idle');
  const [ttsParaIdx, setTtsParaIdx] = useState<number | null>(null);
  const [ttsRate, setTtsRate] = useState<TtsRate>(1);
  const [autoScrollState, setAutoScrollState] = useState<AutoScrollState>('idle');
  const [autoScrollSpeed, setAutoScrollSpeed] = useState<AutoScrollSpeedPreset>(1);
  const [isMobile, setIsMobile] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.innerWidth < 768 : false
  );
  const prefsSyncTimerRef = useRef<number | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const ttsCtrlRef = useRef<PodcastNarratorController | null>(null);
  const autoScrollCtrlRef = useRef<EbookAutoScrollController | null>(null);
  const stringsRef = useRef(strings);
  stringsRef.current = strings;

  const turn = messages.find((m) => m.id === mid);
  const isEnglishUi = strings.backBtn === 'Back';
  const activeThemeSpec = useMemo(
    () => resolveEbookThemeSpec(ebookPrefs, resolvedTheme),
    [ebookPrefs, resolvedTheme]
  );
  const activeFontSpec = useMemo(
    () => getEbookFontSpec(ebookPrefs.fontId),
    [ebookPrefs.fontId]
  );
  const speakLang = useMemo(() => {
    const parsed = parseModePair(turn?.mode || 'auto-id');
    return parsed.tgt;
  }, [turn?.mode]);

  const flashSideToast = useCallback((msg: string) => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    setInlineToast(msg);
    toastTimerRef.current = window.setTimeout(() => {
      toastTimerRef.current = null;
      setInlineToast((cur) => (cur === msg ? null : cur));
    }, 2400);
  }, []);

  const updateEbookPrefs = useCallback((patch: Partial<EbookPrefs>) => {
    const next = saveEbookPrefs({ ...sidePrefsRef.current, ...patch });
    sidePrefsRef.current = next;
    setEbookPrefs(next);
    if (prefsSyncTimerRef.current !== null) window.clearTimeout(prefsSyncTimerRef.current);
    prefsSyncTimerRef.current = window.setTimeout(() => {
      prefsSyncTimerRef.current = null;
      void updateAppSettings({
        ebookPrefs: pickSyncableEbookPrefs(next),
      }).catch(() => { });
    }, 450);
  }, []);

  useEffect(() => {
    if (!isMobile || !appearanceOpen) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [isMobile, appearanceOpen]);

  useEffect(() => {
    ttsCtrlRef.current?.stop();
    autoScrollCtrlRef.current?.stop();
    setTtsState('idle');
    setTtsParaIdx(null);
    setAutoScrollState('idle');
  }, [cid, mid]);

  useEffect(() => {
    return () => {
      if (prefsSyncTimerRef.current !== null) window.clearTimeout(prefsSyncTimerRef.current);
      if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
      ttsCtrlRef.current?.stop();
      autoScrollCtrlRef.current?.stop();
    };
  }, []);

  useEffect(() => {
    ensureEbookFontLoaded(ebookPrefs.fontId);
  }, [ebookPrefs.fontId]);

  useEffect(() => {
    syncDocumentThemeColor(activeThemeSpec.bg);
    return () => {
      syncDocumentThemeColor(resolvedTheme === 'Gelap' ? '#171B1A' : '#FAFBFA');
    };
  }, [activeThemeSpec.bg, resolvedTheme]);

  useEffect(() => {
    let rafId = 0;
    const onResize = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = 0;
        setIsMobile(window.innerWidth < 768);
      });
    };
    window.addEventListener('resize', onResize, { passive: true });
    return () => {
      if (rafId) window.cancelAnimationFrame(rafId);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  useEffect(() => {
    if (autoScrollState !== 'running') return;
    const onInteract = (e: Event) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest('[data-ebook-autoscroll-bar]')) return;
      autoScrollCtrlRef.current?.pause('interaction');
    };
    window.addEventListener('wheel', onInteract, { passive: true });
    window.addEventListener('touchstart', onInteract, { passive: true });
    return () => {
      window.removeEventListener('wheel', onInteract);
      window.removeEventListener('touchstart', onInteract);
    };
  }, [autoScrollState]);

  useEffect(() => {
    if (turn?.sentences && turn.sentences.length > 0) {
      setHtmlPreview('');
      return;
    }
    let active = true;
    downloadExportedTurn({
      user,
      cid,
      mid,
      fmt: 'html',
      bilingual: true,
      theme: resolvedTheme,
      fallbackSentences: turn?.sentences,
      fallbackText: turn?.text,
    })
      .then(({ blob }) => blob.text())
      .then((txt) => {
        if (active) setHtmlPreview(txt);
      })
      .catch(() => { });
    return () => {
      active = false;
    };
  }, [user, cid, mid, resolvedTheme, turn?.sentences, turn?.text]);

  const handleToggleSidePodcast = useCallback(() => {
    const list = turn?.sentences || [];
    if (list.length === 0) return;
    if (!isTtsSupported()) {
      flashSideToast(strings.ebookListenUnsupported);
      return;
    }
    if (ttsState === 'playing') {
      ttsCtrlRef.current?.pause();
      return;
    }
    if (ttsState === 'paused') {
      autoScrollCtrlRef.current?.stop();
      ttsCtrlRef.current?.resume();
      return;
    }
    autoScrollCtrlRef.current?.stop();
    if (!ttsCtrlRef.current) {
      ttsCtrlRef.current = createPodcastNarratorController({
        onSegmentStart: (idx) => {
          setTtsParaIdx(idx);
          scrollActiveParagraphIntoComfortZone(idx);
        },
        onStateChange: (nextState) => {
          setTtsState(nextState);
          if (nextState === 'idle') setTtsParaIdx(null);
        },
      });
    }
    ttsCtrlRef.current.start({
      texts: list.map((p) => p.dst),
      startIndex: 0,
      lang: speakLang,
      rate: ttsRate,
      style: 'podcast_santai',
      chapterTitle: turn?.fileName || strings.readSideBySide,
      seriesTitle: 'tranX',
    });
  }, [
    turn?.sentences,
    turn?.fileName,
    ttsState,
    speakLang,
    ttsRate,
    flashSideToast,
    strings.ebookListenUnsupported,
    strings.readSideBySide,
  ]);

  const handleToggleSideAutoScroll = useCallback(() => {
    if (!turn?.sentences || turn.sentences.length === 0) return;
    if (autoScrollState === 'running') {
      autoScrollCtrlRef.current?.pause('manual');
      return;
    }
    if (autoScrollState === 'paused') {
      ttsCtrlRef.current?.stop();
      autoScrollCtrlRef.current?.resume();
      return;
    }
    ttsCtrlRef.current?.stop();
    if (!autoScrollCtrlRef.current) {
      autoScrollCtrlRef.current = createEbookAutoScrollController({
        onStateChange: (next, reason) => {
          setAutoScrollState(next);
          if (next === 'paused' && reason === 'interaction') {
            flashSideToast(stringsRef.current.ebookAutoScrollPausedTouchToast);
          } else if (next === 'paused' && reason === 'end') {
            flashSideToast(stringsRef.current.ebookAutoScrollEndToast);
          }
        },
      });
    }
    autoScrollCtrlRef.current.start(autoScrollSpeed);
  }, [
    turn?.sentences,
    autoScrollState,
    autoScrollSpeed,
    flashSideToast,
    strings.ebookAutoScrollPausedTouchToast,
    strings.ebookAutoScrollEndToast,
  ]);

  const handleStepSideAutoScroll = useCallback(
    (delta: -1 | 1) => {
      const idx = AUTO_SCROLL_SPEEDS.indexOf(autoScrollSpeed);
      const nextIdx = Math.max(0, Math.min(AUTO_SCROLL_SPEEDS.length - 1, idx + delta));
      const nextSpeed = AUTO_SCROLL_SPEEDS[nextIdx];
      setAutoScrollSpeed(nextSpeed);
      autoScrollCtrlRef.current?.setSpeed(nextSpeed);
    },
    [autoScrollSpeed]
  );

  const handleCycleSideRate = useCallback(() => {
    const next = PODCAST_RATES[(PODCAST_RATES.indexOf(ttsRate) + 1) % PODCAST_RATES.length];
    setTtsRate(next);
    ttsCtrlRef.current?.setRate(next);
  }, [ttsRate]);

  const surfaceStyle = useMemo(
    () => buildEbookSurfaceStyle(activeThemeSpec, activeFontSpec, ebookPrefs, isMobile),
    [activeThemeSpec, activeFontSpec, ebookPrefs, isMobile]
  );

  const hasSentences = Boolean(turn?.sentences && turn.sentences.length > 0);

  return (
    <div
      className="ebook-reader-surface"
      data-ebook-theme={activeThemeSpec.id}
      data-ebook-thememode={ebookPrefs.themeMode}
      style={{ flex: 1, minHeight: 'calc(100dvh - 56px)', ...surfaceStyle }}
    >
      {inlineToast && (
        <div className="ebook-reader-toast" role="status" aria-live="polite">
          {inlineToast}
        </div>
      )}

      <div
        className="subpage-container"
        inert={isMobile && appearanceOpen ? true : undefined}
        style={{ paddingBottom: ttsState !== 'idle' || autoScrollState !== 'idle' ? '132px' : undefined }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            flexWrap: 'wrap',
          }}
        >
          <h1 style={{ margin: 0, fontSize: '20px' }}>
            {turn?.fileName || strings.readSideBySide}
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {hasSentences && (
              <>
                <button
                  type="button"
                  className={`btn-secondary pressable ${ttsState !== 'idle' ? 'ebook-bookmark-active' : ''}`}
                  aria-label={strings.ebookPodcastBtn}
                  aria-pressed={ttsState !== 'idle'}
                  onClick={handleToggleSidePodcast}
                >
                  <IconHeadphones size={16} />
                  {!isMobile && <span>{strings.ebookPodcastBtn}</span>}
                </button>
                <button
                  type="button"
                  className={`btn-secondary pressable ${autoScrollState !== 'idle' ? 'ebook-bookmark-active' : ''}`}
                  aria-label={strings.ebookAutoScrollBtn}
                  aria-pressed={autoScrollState !== 'idle'}
                  onClick={handleToggleSideAutoScroll}
                >
                  <IconAutoScroll size={16} />
                  {!isMobile && <span>{strings.ebookAutoScrollBtn}</span>}
                </button>
              </>
            )}
            <button
              type="button"
              className={`ebook-aa-btn pressable ${appearanceOpen ? 'active' : ''}`}
              aria-label={strings.ebookAppearanceTitle}
              aria-expanded={appearanceOpen}
              onClick={() => setAppearanceOpen((v) => !v)}
            >
              <span>Aa</span>
              {!isMobile && (
                <span style={{ fontFamily: 'var(--font-ui)', fontSize: '13px', fontWeight: 600 }}>
                  {strings.ebookAppearanceBtn}
                </span>
              )}
            </button>
            <button
              type="button"
              className="btn-secondary pressable"
              onClick={() => onNavigate(`/c/${cid}`)}
            >
              {isEnglishUi ? 'Back to conversation' : 'Kembali ke percakapan'}
            </button>
          </div>
        </div>

        {hasSentences && turn?.sentences ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {turn.sentences.map((pair, idx) => (
              <div
                key={pair.i}
                data-para-idx={idx}
                className={`result-card form-grid-2 files-row ${ttsParaIdx === idx ? 'is-tts-active' : ''}`}
              >
                <div
                  style={{
                    fontFamily: /[\u3040-\u30ff\u3400-\u9fff]/.test(pair.src)
                      ? 'var(--font-jp)'
                      : 'var(--font-ui)',
                    fontSize: `max(15px, calc(${ebookPrefs.fontSize}px * 0.92))`,
                    lineHeight: String(ebookPrefs.lineHeight),
                    letterSpacing: 'var(--eb-ls, 0em)',
                  }}
                >
                  {pair.src}
                </div>
                <div
                  className="assistant-prose"
                  style={{
                    fontFamily: activeFontSpec.stack,
                    fontSize: `${ebookPrefs.fontSize}px`,
                    lineHeight: String(ebookPrefs.lineHeight),
                    letterSpacing: 'var(--eb-ls, 0em)',
                    wordSpacing: 'var(--eb-ws, 0em)',
                  }}
                >
                  {pair.dst}
                </div>
              </div>
            ))}
          </div>
        ) : htmlPreview ? (
          <iframe
            title="Baca Berdampingan"
            sandbox=""
            srcDoc={htmlPreview}
            style={{
              width: '100%',
              minHeight: '72dvh',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-card)',
              background: 'var(--surface)',
            }}
          />
        ) : (
          <div className="result-card">Menyiapkan tampilan baca berdampingan...</div>
        )}
      </div>

      {ttsState !== 'idle' && (
        <aside
          className="ebook-floating-dock-wrap"
          role="region"
          aria-label={strings.ebookPodcastBtn}
          data-ebook-podcast-bar="true"
        >
          <div className="ebook-tts-bar glass-regular-surface">
            <span
              className={`ebook-eq-bars ${ttsState === 'playing' ? 'is-playing' : ''}`}
              aria-hidden="true"
            >
              <span />
              <span />
              <span />
            </span>
            <button
              type="button"
              className="icon-square-btn pressable ebook-dock-icon-btn"
              aria-label={strings.ebookPodcastPrevPara}
              onClick={() => ttsCtrlRef.current?.skipParagraph(-1)}
            >
              <IconSkipBack size={16} />
            </button>
            <button
              type="button"
              className="btn-primary pressable ebook-dock-play-btn"
              aria-label={ttsState === 'playing' ? strings.ebookListenPause : strings.ebookListenResume}
              aria-pressed={ttsState === 'playing'}
              onClick={handleToggleSidePodcast}
            >
              {ttsState === 'playing' ? <IconPause size={16} /> : <IconPlay size={16} />}
            </button>
            <button
              type="button"
              className="icon-square-btn pressable ebook-dock-icon-btn"
              aria-label={strings.ebookPodcastNextPara}
              onClick={() => ttsCtrlRef.current?.skipParagraph(1)}
            >
              <IconSkipForward size={16} />
            </button>
            <button
              type="button"
              className="btn-secondary pressable ebook-dock-chip-btn"
              aria-label={`Kecepatan ${ttsRate}x`}
              onClick={handleCycleSideRate}
            >
              {ttsRate}x
            </button>
            <button
              type="button"
              className="icon-square-btn pressable ebook-dock-icon-btn"
              aria-label={strings.ebookListenStop}
              onClick={() => ttsCtrlRef.current?.stop()}
            >
              <IconX size={16} />
            </button>
          </div>
        </aside>
      )}

      {ttsState === 'idle' && autoScrollState !== 'idle' && (
        <aside
          className="ebook-floating-dock-wrap"
          role="region"
          aria-label={strings.ebookAutoScrollBtn}
          data-ebook-autoscroll-bar="true"
        >
          <div className="ebook-tts-bar glass-regular-surface">
            <IconAutoScroll size={17} />
            <button
              type="button"
              className="btn-primary pressable ebook-dock-play-btn"
              aria-label={autoScrollState === 'running' ? strings.ebookListenPause : strings.ebookListenResume}
              aria-pressed={autoScrollState === 'running'}
              onClick={handleToggleSideAutoScroll}
            >
              {autoScrollState === 'running' ? <IconPause size={16} /> : <IconPlay size={16} />}
            </button>
            <button
              type="button"
              className="btn-secondary pressable ebook-dock-chip-btn"
              aria-label={strings.ebookAutoScrollSpeedDown}
              disabled={autoScrollSpeed <= AUTO_SCROLL_SPEEDS[0]}
              onClick={() => handleStepSideAutoScroll(-1)}
            >
              -
            </button>
            <span className="ebook-autoscroll-speed">{autoScrollSpeed.toFixed(1)}x</span>
            <button
              type="button"
              className="btn-secondary pressable ebook-dock-chip-btn"
              aria-label={strings.ebookAutoScrollSpeedUp}
              disabled={autoScrollSpeed >= AUTO_SCROLL_SPEEDS[AUTO_SCROLL_SPEEDS.length - 1]}
              onClick={() => handleStepSideAutoScroll(1)}
            >
              +
            </button>
            <button
              type="button"
              className="icon-square-btn pressable ebook-dock-icon-btn"
              aria-label={strings.ebookAutoScrollStop}
              onClick={() => autoScrollCtrlRef.current?.stop()}
            >
              <IconX size={16} />
            </button>
          </div>
        </aside>
      )}

      {appearanceOpen && (
        <Suspense fallback={null}>
          <EbookAppearancePanel
            prefs={ebookPrefs}
            appResolvedTheme={resolvedTheme}
            isMobile={isMobile}
            hideReaderOnlyControls
            isEnglishUi={isEnglishUi}
            strings={strings}
            onUpdate={updateEbookPrefs}
            onClose={() => setAppearanceOpen(false)}
          />
        </Suspense>
      )}
    </div>
  );
}
