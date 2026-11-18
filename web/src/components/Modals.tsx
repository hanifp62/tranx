import { useEffect, useState } from 'react';
import type { AppSettingsDoc, ThemePref, UiLang } from '../types';
import type { UiStrings } from '../i18n/strings';
import {
  downloadFullBackup,
  fetchEngineMeta,
  generateInboxToken,
  generatePairCode,
  getApiBaseUrl,
  revokeAllOwnerSessions,
  runEngineCheck,
  saveEngineVaultKey,
} from '../lib/api';
import { updateAppSettings, type AuthSessionUser } from '../lib/firebase';
import { IconCheck, IconCopy, IconDownload, IconRefresh, IconX } from './Icons';

function useEscapeClose(onClose: () => void) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);
}

export function LogoutDialog({
  strings,
  onClose,
  onConfirm,
}: {
  strings: UiStrings;
  onClose: () => void;
  onConfirm: () => void;
}) {
  useEscapeClose(onClose);
  return (
    <div className="scrim-backdrop" onClick={onClose}>
      <div
        className="modal-dialog"
        style={{ width: 'min(400px, 100%)' }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="logout-dialog-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="logout-dialog-title" className="modal-title">
            {strings.signOutTitle}
          </h2>
          <button
            type="button"
            className="icon-square-btn"
            aria-label={strings.cancel}
            onClick={onClose}
          >
            <IconX size={18} />
          </button>
        </div>
        <div className="modal-body">
          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '14px' }}>
            {strings.signOutBody}
          </p>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn-secondary pressable" onClick={onClose}>
            {strings.cancel}
          </button>
          <button type="button" className="btn-danger pressable" onClick={onConfirm}>
            {strings.signOut}
          </button>
        </div>
      </div>
    </div>
  );
}

export function RenameDialog({
  initialTitle,
  strings,
  onClose,
  onSave,
}: {
  initialTitle: string;
  strings: UiStrings;
  onClose: () => void;
  onSave: (title: string) => void;
}) {
  const [title, setTitle] = useState(initialTitle);
  useEscapeClose(onClose);
  return (
    <div className="scrim-backdrop" onClick={onClose}>
      <form
        className="modal-dialog"
        style={{ width: 'min(420px, 100%)' }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="rename-dialog-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) onSave(title.trim());
        }}
      >
        <div className="modal-header">
          <h2 id="rename-dialog-title" className="modal-title">
            {strings.renameChat}
          </h2>
          <button
            type="button"
            className="icon-square-btn"
            aria-label={strings.cancel}
            onClick={onClose}
          >
            <IconX size={18} />
          </button>
        </div>
        <div className="modal-body">
          <label className="field-label">
            <span>Judul percakapan</span>
            <input
              className="field-input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
              maxLength={160}
              required
            />
          </label>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn-secondary pressable" onClick={onClose}>
            {strings.cancel}
          </button>
          <button type="submit" className="btn-primary pressable">
            {strings.save}
          </button>
        </div>
      </form>
    </div>
  );
}

export function ShortcutsModal({
  strings,
  onClose,
}: {
  strings: UiStrings;
  onClose: () => void;
}) {
  useEscapeClose(onClose);
  const rows = [
    ['Cmd / Ctrl + K', 'Cari riwayat percakapan'],
    ['Cmd / Ctrl + ,', 'Buka Setelan'],
    ['Cmd / Ctrl + /', 'Tampilkan daftar pintasan keyboard'],
    ['Cmd / Ctrl + Shift + C', 'Salin hasil terjemahan terakhir'],
    ['Enter', 'Kirim teks (aman terhadap komposisi IME Jepang)'],
    ['Shift + Enter', 'Baris baru di area ketik'],
    ['Escape', 'Tutup menu, laci, atau dialog aktif'],
  ];
  return (
    <div className="scrim-backdrop" onClick={onClose}>
      <div
        className="modal-dialog"
        style={{ width: 'min(480px, 100%)' }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="shortcuts-title" className="modal-title">
            {strings.shortcuts}
          </h2>
          <button
            type="button"
            className="icon-square-btn"
            aria-label={strings.cancel}
            onClick={onClose}
          >
            <IconX size={18} />
          </button>
        </div>
        <div className="modal-body">
          {rows.map(([keys, desc]) => (
            <div
              key={keys}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '12px',
                paddingBottom: '8px',
                borderBottom: '1px solid var(--border)',
                fontSize: '14px',
              }}
            >
              <span>{desc}</span>
              <code
                style={{
                  padding: '3px 8px',
                  borderRadius: '6px',
                  background: 'var(--bg-sidebar)',
                  border: '1px solid var(--border)',
                  fontSize: '12px',
                  whiteSpace: 'nowrap',
                }}
              >
                {keys}
              </code>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function InfoModal({
  kind,
  strings,
  onClose,
}: {
  kind: 'help' | 'about';
  strings: UiStrings;
  onClose: () => void;
}) {
  useEscapeClose(onClose);
  const title = kind === 'help' ? strings.help : strings.learnMore;
  return (
    <div className="scrim-backdrop" onClick={onClose}>
      <div
        className="modal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="info-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="info-modal-title" className="modal-title">
            {title}
          </h2>
          <button
            type="button"
            className="icon-square-btn"
            aria-label={strings.cancel}
            onClick={onClose}
          >
            <IconX size={18} />
          </button>
        </div>
        <div className="modal-body" style={{ fontSize: '14px', lineHeight: '22px' }}>
          {kind === 'help' ? (
            <>
              <div>
                <strong>Empat moda kerja terpadu:</strong> pilih <em>Teks</em> untuk obrolan dan
                dikte suara langsung, <em>Gambar</em> untuk tangkapan layar atau panel manga,{' '}
                <em>Dokumen</em> untuk berkas hingga 50 MB (.epub, .pdf, .docx, .srt, .vtt, .ass,
                .html, .md, .txt), atau <em>Link</em> untuk membaca artikel web Jepang.
              </div>
              <div>
                <strong>Menyematkan proyek bacaan:</strong> buka tombol tiga titik pada baris
                riwayat untuk menyematkan seri novel ke grup <em>Disematkan</em> di bagian atas
                panel samping.
              </div>
              <div>
                <strong>Mengunci ejaan nama tokoh:</strong> ketuk chip nama tokoh di bawah hasil
                terjemahan atau kelola seluruh entri 14 kolom melalui menu <em>Daftar nama</em>.
              </div>
            </>
          ) : (
            <>
              <div>
                <strong>Mesin inti jptrans 1.1.0:</strong> tranX menjalankan paket mesin{' '}
                <code>translator.py</code> utuh di Cloud Functions Gen-2 Jakarta (
                <code>asia-southeast2</code>) dengan pelindung placeholder entitas, glosarium
                terkunci per judul karya, dan bacaan serif <em>Charter</em>.
              </div>
              <div>
                <strong>Privasi pemilik tunggal:</strong> seluruh aturan akses Cloud Firestore,
                Cloud Storage, dan HTTP memverifikasi akun pemilik tunggal serta tidak menyimpan
                kunci API model di penyimpanan peramban.
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* L8 & H12: Modal Setelan 4 Tab (Umum, Akun, Data, Lanjutan) */
export function SettingsModal({
  user,
  settings,
  strings,
  onClose,
  onChangeUiLang,
  onNotify,
}: {
  user: AuthSessionUser;
  settings: AppSettingsDoc;
  strings: UiStrings;
  onClose: () => void;
  onChangeUiLang: (lang: UiLang) => void;
  onNotify: (msg: string) => void;
}) {
  const [tab, setTab] = useState<'general' | 'account' | 'data' | 'advanced'>('general');
  const [pairInfo, setPairInfo] = useState<{ code: string; expiresAt: string } | null>(null);
  const [inboxToken, setInboxToken] = useState<string | null>(null);
  const [vaultKeyInput, setVaultKeyInput] = useState('');
  const [metaInfo, setMetaInfo] = useState<Record<string, unknown> | null>(null);
  const [engineReport, setEngineReport] = useState<
    Array<{ model: string; ok: boolean; ms: number; sample?: string; error?: string }>
  >([]);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [charCapInput, setCharCapInput] = useState(String(settings.dailyCharCap));
  const [callCapInput, setCallCapInput] = useState(String(settings.dailyCallCap));

  useEscapeClose(onClose);

  useEffect(() => {
    if (tab !== 'advanced') return;
    fetchEngineMeta(user)
      .then((info) => {
        setMetaInfo(info);
        setStatusError(null);
      })
      .catch((err) => {
        setStatusError(
          err instanceof Error
            ? err.message
            : 'Layanan Cloud Functions belum terjangkau saat ini.'
        );
      });
  }, [tab, user]);

  const handleSaveTheme = async (theme: ThemePref) => {
    await updateAppSettings({ theme });
  };

  const handleCreatePairCode = async () => {
    setBusyAction('pair');
    setStatusError(null);
    try {
      const res = await generatePairCode(user);
      setPairInfo(res);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Gagal membuat kode pasangan.');
    } finally {
      setBusyAction(null);
    }
  };

  const handleCreateInboxToken = async () => {
    setBusyAction('inbox');
    setStatusError(null);
    try {
      const res = await generateInboxToken(user);
      setInboxToken(res.token);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Gagal membuat token Pintasan.');
    } finally {
      setBusyAction(null);
    }
  };

  const handleExportBackup = async () => {
    setBusyAction('backup');
    setStatusError(null);
    try {
      const blob = await downloadFullBackup(user);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `tranx-backup-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      onNotify('Cadangan JSON berhasil diunduh');
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Gagal mengekspor cadangan.');
    } finally {
      setBusyAction(null);
    }
  };

  const handleSaveVaultKey = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusyAction('key');
    setStatusError(null);
    try {
      await saveEngineVaultKey(user, vaultKeyInput);
      setVaultKeyInput('');
      const refreshed = await fetchEngineMeta(user);
      setMetaInfo(refreshed);
      onNotify('Kunci API model disimpan di brankas server');
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Gagal menyimpan kunci API.');
    } finally {
      setBusyAction(null);
    }
  };

  const handleRunEngineCheck = async () => {
    setBusyAction('check');
    setStatusError(null);
    try {
      const rows = await runEngineCheck(user);
      setEngineReport(rows);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Pemeriksaan mesin gagal.');
    } finally {
      setBusyAction(null);
    }
  };

  const handleSaveCaps = async (e: React.FormEvent) => {
    e.preventDefault();
    const dailyCharCap = Math.max(10000, Number(charCapInput) || 500000);
    const dailyCallCap = Math.max(20, Number(callCapInput) || 1500);
    await updateAppSettings({ dailyCharCap, dailyCallCap });
    onNotify('Batas pemakaian harian diperbarui');
  };

  const keyStatus = (metaInfo?.keyStatus as { configured?: boolean; source?: string }) || null;
  const usageToday = (metaInfo?.usageToday as { chars?: number; calls?: number }) || null;

  return (
    <div className="scrim-backdrop" onClick={onClose}>
      <div
        className="modal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="settings-modal-title" className="modal-title">
            {strings.settings}
          </h2>
          <button
            type="button"
            className="icon-square-btn"
            aria-label={strings.cancel}
            onClick={onClose}
          >
            <IconX size={18} />
          </button>
        </div>

        <div
          role="tablist"
          style={{
            display: 'flex',
            gap: '6px',
            padding: '10px 20px',
            borderBottom: '1px solid var(--border)',
            overflowX: 'auto',
          }}
        >
          {(
            [
              ['general', strings.settingsGeneral],
              ['account', strings.settingsAccount],
              ['data', strings.settingsData],
              ['advanced', strings.settingsAdvanced],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={tab === id ? 'btn-primary pressable' : 'btn-secondary pressable'}
              onClick={() => {
                setTab(id);
                setStatusError(null);
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="modal-body">
          {statusError && (
            <div
              role="alert"
              style={{
                padding: '10px 12px',
                borderRadius: 'var(--r-control)',
                background: 'var(--danger-soft)',
                color: 'var(--danger)',
                fontSize: '13px',
              }}
            >
              {statusError}
            </div>
          )}

          {tab === 'general' && (
            <>
              <div className="field-label">
                <span>{strings.themeLabel}</span>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {(
                    [
                      ['light', strings.themeLight],
                      ['dark', strings.themeDark],
                      ['system', strings.themeSystem],
                    ] as const
                  ).map(([val, label]) => (
                    <button
                      key={val}
                      type="button"
                      className={
                        settings.theme === val
                          ? 'btn-primary pressable'
                          : 'btn-secondary pressable'
                      }
                      onClick={() => handleSaveTheme(val)}
                    >
                      {settings.theme === val && <IconCheck size={16} />}
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="field-label">
                <span>{strings.uiLanguage}</span>
                <div style={{ display: 'flex', gap: '8px' }}>
                  {(
                    [
                      ['id', 'Indonesia'],
                      ['en', 'English'],
                    ] as const
                  ).map(([code, label]) => (
                    <button
                      key={code}
                      type="button"
                      className={
                        settings.uiLang === code
                          ? 'btn-primary pressable'
                          : 'btn-secondary pressable'
                      }
                      onClick={() => onChangeUiLang(code)}
                    >
                      {settings.uiLang === code && <IconCheck size={16} />}
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="field-label">
                <span>{strings.defaultTargetLabel}</span>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {(
                    [
                      ['id', strings.langJaId],
                      ['en', strings.langJaEn],
                    ] as const
                  ).map(([tgt, label]) => (
                    <button
                      key={tgt}
                      type="button"
                      className={
                        settings.defaultTarget === tgt
                          ? 'btn-primary pressable'
                          : 'btn-secondary pressable'
                      }
                      onClick={() => updateAppSettings({ defaultTarget: tgt })}
                    >
                      {settings.defaultTarget === tgt && <IconCheck size={16} />}
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}

          {tab === 'account' && (
            <>
              <div
                style={{
                  padding: '12px',
                  borderRadius: 'var(--r-card)',
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  fontSize: '14px',
                }}
              >
                <div style={{ fontWeight: 600 }}>{user.displayName || 'Pemilik tranX'}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>{user.email}</div>
              </div>

              <div className="field-label">
                <span>Pasangkan perangkat kedua (kode 6 angka berlaku 120 detik)</span>
                <div>
                  <button
                    type="button"
                    className="btn-primary pressable"
                    disabled={busyAction === 'pair'}
                    onClick={handleCreatePairCode}
                  >
                    Buat kode pasangan
                  </button>
                </div>
                {pairInfo && (
                  <div
                    style={{
                      padding: '12px',
                      borderRadius: 'var(--r-control)',
                      background: 'var(--accent-soft)',
                      fontSize: '20px',
                      fontWeight: 700,
                      letterSpacing: '0.18em',
                    }}
                  >
                    {pairInfo.code}
                  </div>
                )}
              </div>

              <div className="field-label">
                <span>Keamanan sesi lintas perangkat</span>
                <div>
                  <button
                    type="button"
                    className="btn-danger pressable"
                    onClick={async () => {
                      await revokeAllOwnerSessions(user);
                      onNotify('Seluruh token sesi perangkat lain telah dicabut');
                    }}
                  >
                    Putuskan semua perangkat
                  </button>
                </div>
              </div>
            </>
          )}

          {tab === 'data' && (
            <>
              <div className="field-label">
                <span>Cadangan penuh (riwayat, setelan, dan daftar nama 14 kolom)</span>
                <div>
                  <button
                    type="button"
                    className="btn-primary pressable"
                    disabled={busyAction === 'backup'}
                    onClick={handleExportBackup}
                  >
                    <IconDownload size={18} />
                    Unduh cadangan JSON
                  </button>
                </div>
              </div>

              <div className="field-label">
                <span>Token Pintasan iOS / macOS (POST /v1/inbox)</span>
                <p style={{ margin: 0, fontWeight: 400, color: 'var(--text-muted)' }}>
                  Kirim teks Jepang dari menu Bagikan iPhone langsung ke panggung tranX memakai
                  header <code>X-Inbox-Token</code>.
                </p>
                <div>
                  <button
                    type="button"
                    className="btn-secondary pressable"
                    disabled={busyAction === 'inbox'}
                    onClick={handleCreateInboxToken}
                  >
                    Buat token Pintasan baru
                  </button>
                </div>
                {inboxToken && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '8px',
                      padding: '10px 12px',
                      borderRadius: 'var(--r-control)',
                      background: 'var(--bg)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <code style={{ fontSize: '12px', wordBreak: 'break-all' }}>{inboxToken}</code>
                    <button
                      type="button"
                      className="btn-secondary pressable"
                      onClick={() => {
                        navigator.clipboard?.writeText(inboxToken);
                        onNotify('Token Pintasan disalin');
                      }}
                    >
                      <IconCopy size={16} />
                      Salin
                    </button>
                  </div>
                )}
              </div>
            </>
          )}

          {tab === 'advanced' && (
            <>
              <div
                style={{
                  padding: '12px',
                  borderRadius: 'var(--r-card)',
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  fontSize: '13px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                }}
              >
                <div>
                  <strong>Endpoint API:</strong> <code>{getApiBaseUrl() || '(relatif /v1)'}</code>
                </div>
                <div>
                  <strong>Status kunci Gemini server:</strong>{' '}
                  {keyStatus
                    ? keyStatus.configured
                      ? `Aktif (${keyStatus.source})`
                      : 'Belum diatur'
                    : 'Menunggu sambungan mesin'}
                </div>
                {usageToday && (
                  <div>
                    <strong>Pemakaian hari ini (WIB):</strong>{' '}
                    {usageToday.chars?.toLocaleString('id-ID') || 0} karakter /{' '}
                    {usageToday.calls || 0} panggilan
                  </div>
                )}
              </div>

              <form onSubmit={handleSaveVaultKey} className="field-label">
                <span>Simpan kunci API Gemini berbayar di brankas server (0 kunci di peramban)</span>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input
                    type="password"
                    className="field-input"
                    style={{ flex: 1 }}
                    placeholder="Masukkan kunci API Gemini..."
                    value={vaultKeyInput}
                    onChange={(e) => setVaultKeyInput(e.target.value)}
                  />
                  <button
                    type="submit"
                    className="btn-primary pressable"
                    disabled={busyAction === 'key' || !vaultKeyInput.trim()}
                  >
                    {strings.save}
                  </button>
                </div>
              </form>

              <div className="field-label">
                <span>Uji kesehatan rantai model LLM</span>
                <div>
                  <button
                    type="button"
                    className="btn-secondary pressable"
                    disabled={busyAction === 'check'}
                    onClick={handleRunEngineCheck}
                  >
                    <IconRefresh size={16} />
                    Cek mesin sekarang
                  </button>
                </div>
                {engineReport.map((row) => (
                  <div
                    key={row.model}
                    style={{
                      padding: '8px 10px',
                      borderRadius: 'var(--r-control)',
                      background: row.ok ? 'var(--success-soft)' : 'var(--danger-soft)',
                      color: row.ok ? 'var(--success)' : 'var(--danger)',
                      fontSize: '13px',
                      fontWeight: 500,
                    }}
                  >
                    {row.model}: {row.ok ? `Siap (${row.ms} md)` : `Gagal (${row.error})`}
                  </div>
                ))}
              </div>

              <form onSubmit={handleSaveCaps} className="form-grid-2">
                <label className="field-label">
                  <span>Rem karakter harian (WIB)</span>
                  <input
                    type="number"
                    className="field-input"
                    value={charCapInput}
                    onChange={(e) => setCharCapInput(e.target.value)}
                    min={10000}
                  />
                </label>
                <label className="field-label">
                  <span>Rem panggilan harian (WIB)</span>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input
                      type="number"
                      className="field-input"
                      style={{ flex: 1 }}
                      value={callCapInput}
                      onChange={(e) => setCallCapInput(e.target.value)}
                      min={20}
                    />
                    <button type="submit" className="btn-secondary pressable">
                      {strings.save}
                    </button>
                  </div>
                </label>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
