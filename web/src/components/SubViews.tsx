import { useEffect, useState } from 'react';
import type {
  EntityKind,
  GlossaryEntry,
  JobDoc,
  ModePair,
  ResolvedTheme,
  TitleDoc,
  TitleKind,
  TitleStyle,
  TurnMessage,
  WebReaderBundle,
} from '../types';
import type { UiStrings } from '../i18n/strings';
import {
  downloadExportedTurn,
  fetchWebReaderBundle,
  mergeTitleGlossaries,
} from '../lib/api';
import { parseModePair, toSafeHttpUrl } from '../lib/directEngine';
import {
  DEFAULT_STYLE,
  removeGlossaryEntry,
  resolveStorageOutputUrl,
  saveTitleDoc,
  subscribeGlossary,
  upsertUserGlossaryEntry,
  type AuthSessionUser,
} from '../lib/firebase';
import {
  IconBook,
  IconColumns,
  IconDownload,
  IconGlobe,
  IconLink,
  IconPlus,
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
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
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
          <div key={job.id} className="result-card">
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
                className={`status-badge ${
                  job.state === 'done'
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

/* /web?url=...: Extension-less Auto-Translating Web Browser & Novel Reader */
export function TranslatedWebViewer({
  user,
  url,
  initialMode,
  initialView = 'reader',
  titleId,
  backPath = '/',
  strings,
  onNavigate,
  onOpenWebTools,
}: {
  user: AuthSessionUser;
  url: string;
  initialMode: ModePair;
  initialView?: 'reader' | 'site' | 'original';
  titleId?: string;
  backPath?: string;
  strings: UiStrings;
  onNavigate: (path: string) => void;
  onOpenWebTools?: () => void;
}) {
  const [mode, setMode] = useState<ModePair>(initialMode);
  const [view, setView] = useState<'reader' | 'site' | 'original'>(initialView);
  const [bilingual, setBilingual] = useState(false);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [bundle, setBundle] = useState<WebReaderBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const safeExternalUrl = toSafeHttpUrl(url);

  useEffect(() => {
    setView(initialView);
  }, [initialView, url]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setErrorMsg(null);
    setChaptersOpen(false);
    fetchWebReaderBundle({ user, url, mode, titleId, view })
      .then((res) => {
        if (active) {
          setBundle(res);
          setLoading(false);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
      })
      .catch((err) => {
        if (active) {
          setErrorMsg(
            err instanceof Error ? err.message : 'Halaman web tidak dapat dimuat.'
          );
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [user, url, mode, titleId, view]);

  const effectiveTitleId = titleId || bundle?.titleId;
  const nav = bundle?.novelNav;
  const { tgt } = parseModePair(mode);
  const isJpOut = view === 'original' ? bundle?.detectedSource === 'ja' : tgt === 'ja';

  const openChapterUrl = (targetUrl: string, targetView: 'reader' | 'site' = view === 'site' ? 'site' : 'reader') => {
    setChaptersOpen(false);
    const qs = new URLSearchParams({
      url: targetUrl,
      mode,
      view: targetView,
      ...(effectiveTitleId ? { titleId: effectiveTitleId } : {}),
    });
    onNavigate(`/web?${qs.toString()}`);
  };

  useEffect(() => {
    if (!nav?.isNovel) return;
    const onKey = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return;
      }
      if (e.key === 'ArrowRight' && nav.nextUrl && !loading) {
        openChapterUrl(nav.nextUrl);
      } else if (e.key === 'ArrowLeft' && nav.prevUrl && !loading) {
        openChapterUrl(nav.prevUrl);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [nav, loading, mode, view, effectiveTitleId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100dvh' }}>
      <header className="web-viewer-topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn-secondary pressable"
            onClick={() => onNavigate(backPath)}
          >
            {strings.backBtn}
          </button>
          <div style={{ display: 'inline-flex', gap: '4px', flexWrap: 'wrap' }}>
            <button
              type="button"
              className={view === 'reader' ? 'btn-primary pressable' : 'btn-secondary pressable'}
              onClick={() => setView('reader')}
            >
              {strings.readerModeTab}
            </button>
            <button
              type="button"
              className={view === 'site' ? 'btn-primary pressable' : 'btn-secondary pressable'}
              onClick={() => setView('site')}
            >
              <IconGlobe size={15} />
              {strings.translatedSiteTab}
            </button>
            <button
              type="button"
              className={view === 'original' ? 'btn-primary pressable' : 'btn-secondary pressable'}
              onClick={() => setView('original')}
            >
              {strings.originalViewTab}
            </button>
          </div>
          {view === 'reader' && (
            <button
              type="button"
              className={bilingual ? 'btn-primary pressable' : 'btn-secondary pressable'}
              aria-pressed={bilingual}
              onClick={() => setBilingual((v) => !v)}
            >
              <IconColumns size={15} />
              {strings.bilingualToggle}
            </button>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <select
            className="field-select"
            style={{ minHeight: '36px', padding: '4px 10px', fontSize: '13px' }}
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
          {onOpenWebTools && (
            <button
              type="button"
              className="btn-secondary pressable"
              onClick={onOpenWebTools}
            >
              {strings.webToolsBtn}
            </button>
          )}
          {effectiveTitleId && (
            <button
              type="button"
              className="btn-secondary pressable"
              onClick={() => onNavigate(`/kamus/${effectiveTitleId}`)}
            >
              {strings.glossary}
            </button>
          )}
          {safeExternalUrl && (
            <a
              href={safeExternalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="action-chip-btn"
              title={strings.openOriginalUntranslated}
            >
              <IconLink size={15} />
              {strings.openOriginalUntranslated}
            </a>
          )}
        </div>
      </header>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {loading ? (
          <div className="subpage-container">
            <div className="result-card">{strings.loadingWebPage}</div>
          </div>
        ) : errorMsg ? (
          <div className="subpage-container">
            <div className="result-card">
              <span className="status-badge error">{strings.cannotTranslateWeb}</span>
              <div>{errorMsg}</div>
              {safeExternalUrl && (
                <div>
                  <a
                    href={safeExternalUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-primary pressable"
                  >
                    {strings.openOriginalUntranslated}
                  </a>
                </div>
              )}
            </div>
          </div>
        ) : view === 'site' && bundle?.siteHtml ? (
          <iframe
            title="Pembaca Halaman Terjemahan"
            sandbox="allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation"
            srcDoc={bundle.siteHtml}
            style={{
              flex: 1,
              width: '100%',
              minHeight: 'calc(100dvh - 124px)',
              border: 'none',
              background: 'var(--bg)',
            }}
          />
        ) : bundle ? (
          <article className="novel-reader-wrap">
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
                    {strings.novelDetectedBadge}
                    {nav.chapterLabel ? ` · ${nav.chapterLabel}` : ''}
                  </span>
                )}
                {nav?.seriesTitle && <span>{nav.seriesTitle}</span>}
              </div>
              <h1 className="novel-reader-title">
                {view === 'original' ? bundle.titleSrc : bundle.titleDst}
              </h1>
            </div>

            <div
              className={`novel-reader-body assistant-prose ${isJpOut ? 'is-jp' : ''}`}
              lang={view === 'original' ? bundle.detectedSource : tgt}
            >
              {bundle.sentences.map((pair) =>
                bilingual && view === 'reader' ? (
                  <div key={pair.i} className="bilingual-pair-card">
                    <div
                      className="bilingual-pair-src"
                      style={{
                        fontFamily:
                          bundle.detectedSource === 'ja' ? 'var(--font-jp)' : 'var(--font-ui)',
                      }}
                    >
                      {pair.src}
                    </div>
                    <p className="novel-reader-para">{pair.dst}</p>
                  </div>
                ) : (
                  <p key={pair.i} className="novel-reader-para">
                    {view === 'original' ? pair.src : pair.dst}
                  </p>
                )
              )}
            </div>
          </article>
        ) : null}
      </div>

      {!loading && !errorMsg && nav && (nav.prevUrl || nav.nextUrl || nav.chapters?.length || nav.tocUrl) && (
        <nav className="novel-chapter-dock" aria-label={strings.chapterListBtn}>
          <div className="novel-chapter-dock-inner">
            <button
              type="button"
              className="btn-secondary pressable"
              disabled={!nav.prevUrl}
              onClick={() => nav.prevUrl && openChapterUrl(nav.prevUrl)}
            >
              {'\u2190'} {strings.prevChapter}
            </button>

            <button
              type="button"
              className="btn-secondary pressable"
              onClick={() => setChaptersOpen(true)}
            >
              <IconBook size={16} />
              {strings.chapterListBtn}
              {nav.chapterLabel ? ` (${nav.chapterLabel})` : ''}
            </button>

            <button
              type="button"
              className="btn-primary pressable"
              disabled={!nav.nextUrl}
              onClick={() => nav.nextUrl && openChapterUrl(nav.nextUrl)}
            >
              {strings.nextChapter} {'\u2192'}
            </button>
          </div>
        </nav>
      )}

      {chaptersOpen && nav && (
        <div className="scrim-backdrop" onClick={() => setChaptersOpen(false)}>
          <div
            className="modal-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="chapter-list-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 id="chapter-list-title" className="modal-title">
                {nav.seriesTitle || strings.chapterListBtn}
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
            <div className="modal-body">
              {nav.tocUrl && (
                <div>
                  <button
                    type="button"
                    className="btn-secondary pressable"
                    onClick={() => openChapterUrl(nav.tocUrl!, 'site')}
                  >
                    <IconGlobe size={16} />
                    {strings.openTocSite}
                  </button>
                </div>
              )}
              {nav.chapters && nav.chapters.length > 0 ? (
                <div className="chapter-list-grid">
                  {nav.chapters.map((ch, idx) => (
                    <button
                      key={`${ch.url}_${idx}`}
                      type="button"
                      className={`chapter-list-item pressable ${ch.current ? 'is-current' : ''}`}
                      onClick={() => openChapterUrl(ch.url)}
                    >
                      <span>{ch.title}</span>
                      {ch.current && <span className="status-badge done">Aktif</span>}
                    </button>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                  {strings.noChaptersFound}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* /c/:cid/m/:mid/baca: Side-by-Side Reader with Furigana (<ruby>) */
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
  const turn = messages.find((m) => m.id === mid);

  useEffect(() => {
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
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [user, cid, mid, resolvedTheme]);

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
        <h1 style={{ margin: 0, fontSize: '20px' }}>
          {turn?.fileName || strings.readSideBySide}
        </h1>
        <button
          type="button"
          className="btn-secondary pressable"
          onClick={() => onNavigate(`/c/${cid}`)}
        >
          Kembali ke percakapan
        </button>
      </div>

      {turn?.sentences && turn.sentences.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {turn.sentences.map((pair) => (
            <div key={pair.i} className="result-card form-grid-2">
              <div style={{ fontFamily: 'var(--font-jp)', fontSize: '16px', lineHeight: '28px' }}>
                {pair.src}
              </div>
              <div className="assistant-prose" style={{ fontSize: '17px', lineHeight: '28px' }}>
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
  );
}
