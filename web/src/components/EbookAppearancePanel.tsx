import { memo, useMemo, useRef, useState } from 'react';
import type { UiStrings } from '../i18n/strings';
import type { ResolvedTheme } from '../types';
import {
  DEFAULT_EBOOK_PREFS,
  DYSLEXIA_COMFORT_PATCH,
  EBOOK_FONTS,
  EBOOK_THEMES,
  ensureEbookFontLoaded,
  getEbookThemeById,
  resolveEbookThemeSpec,
  type EbookAlign,
  type EbookDayThemeId,
  type EbookMeasure,
  type EbookNightThemeId,
  type EbookPageMode,
  type EbookPrefs,
  type EbookReadingRulerMode,
  type EbookSpreadMode,
  type EbookTapZoneMode,
  type EbookThemeSpec,
} from '../lib/ebookPrefs';
import { useDialogFocusTrap } from '../lib/useDialogFocusTrap';
import { IconCheck, IconEye, IconX } from './Icons';

interface EbookAppearancePanelProps {
  prefs: EbookPrefs;
  appResolvedTheme: ResolvedTheme;
  isMobile: boolean;
  canUseSpread?: boolean;
  hideReaderOnlyControls?: boolean;
  isEnglishUi: boolean;
  strings: UiStrings;
  onUpdate: (patch: Partial<EbookPrefs>) => void;
  onClose: () => void;
}

type FontFilter = 'all' | 'serif' | 'sans' | 'jp';

export const EbookAppearancePanel = memo(function EbookAppearancePanel({
  prefs,
  appResolvedTheme,
  isMobile,
  canUseSpread = false,
  hideReaderOnlyControls = false,
  isEnglishUi,
  strings,
  onUpdate,
  onClose,
}: EbookAppearancePanelProps) {
  const [fontFilter, setFontFilter] = useState<FontFilter>('all');
  const dialogRef = useRef<HTMLDivElement | null>(null);
  useDialogFocusTrap(dialogRef, onClose);

  const activeSpec = useMemo(
    () => resolveEbookThemeSpec(prefs, appResolvedTheme),
    [prefs, appResolvedTheme]
  );
  const daySpec = useMemo(() => getEbookThemeById(prefs.dayTheme), [prefs.dayTheme]);
  const nightSpec = useMemo(() => getEbookThemeById(prefs.nightTheme), [prefs.nightTheme]);

  const filteredFonts = useMemo(() => {
    if (fontFilter === 'all') return EBOOK_FONTS;
    if (fontFilter === 'serif') {
      return EBOOK_FONTS.filter((f) => f.category === 'serif' || f.category === 'slab');
    }
    return EBOOK_FONTS.filter((f) => f.category === fontFilter);
  }, [fontFilter]);

  const handleSelectThemeSwatch = (theme: EbookThemeSpec) => {
    const appIsDark = appResolvedTheme === 'Gelap';
    if (prefs.themeMode === 'adaptive') {
      // Smart Dual-Slot behavior:
      // - Picking a paper matching current App polarity updates that Day/Night slot while staying Adaptive.
      // - Picking the opposite polarity immediately previews & locks it (while also remembering that slot),
      //   so a tap ALWAYS gives instant visible feedback with zero confusion!
      if (!theme.isDark) {
        const dayId = theme.id as EbookDayThemeId;
        if (!appIsDark) {
          onUpdate({ themeMode: 'adaptive', dayTheme: dayId, theme: 'auto' });
        } else {
          onUpdate({
            themeMode: 'locked',
            dayTheme: dayId,
            lockedTheme: dayId,
            theme: dayId,
          });
        }
      } else {
        const nightId = theme.id as EbookNightThemeId;
        if (appIsDark) {
          onUpdate({ themeMode: 'adaptive', nightTheme: nightId, theme: 'auto' });
        } else {
          onUpdate({
            themeMode: 'locked',
            nightTheme: nightId,
            lockedTheme: nightId,
            theme: nightId,
          });
        }
      }
      return;
    }

    // In locked mode: update lockedTheme and keep day/night pair in sync too
    onUpdate({
      themeMode: 'locked',
      lockedTheme: theme.id,
      theme: theme.id,
      ...(theme.isDark
        ? { nightTheme: theme.id as EbookNightThemeId }
        : { dayTheme: theme.id as EbookDayThemeId }),
    });
  };

  const dayName = isEnglishUi ? daySpec.labelEn : daySpec.labelId;
  const nightName = isEnglishUi ? nightSpec.labelEn : nightSpec.labelId;
  const activeName = isEnglishUi ? activeSpec.labelEn : activeSpec.labelId;

  const panelBody = (
    <div className="ebook-appear-body">
      {/* 1. Tier-2 Dual-Slot Reading Themes (Adaptive Day/Night Pairing vs Explicit Lock) */}
      <section className="ebook-appear-section" aria-label={strings.ebookThemeSection}>
        <div className="ebook-appear-section-head">
          <span className="ebook-appear-label">{strings.ebookThemeSection}</span>
        </div>

        <div className="ebook-seg-row is-compact" role="radiogroup" aria-label={strings.ebookThemeSection}>
          <button
            type="button"
            role="radio"
            aria-checked={prefs.themeMode === 'adaptive'}
            data-ebook-thememode-btn="adaptive"
            className={`ebook-seg-btn pressable ${prefs.themeMode === 'adaptive' ? 'active' : ''}`}
            onClick={() => onUpdate({ themeMode: 'adaptive', theme: 'auto' })}
          >
            {strings.ebookThemeModeAdaptive}
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={prefs.themeMode === 'locked'}
            data-ebook-thememode-btn="locked"
            className={`ebook-seg-btn pressable ${prefs.themeMode === 'locked' ? 'active' : ''}`}
            onClick={() =>
              onUpdate({
                themeMode: 'locked',
                lockedTheme: activeSpec.id,
                theme: activeSpec.id,
              })
            }
          >
            {strings.ebookThemeModeLocked}
          </button>
        </div>

        <div className="ebook-theme-status-note" data-ebook-theme-status="true">
          {prefs.themeMode === 'adaptive'
            ? `${strings.ebookActiveSlotHint}: ${isEnglishUi ? 'Day' : 'Siang'} ${dayName} · ${isEnglishUi ? 'Night' : 'Malam'} ${nightName}`
            : `${strings.ebookLockedSlotHint}: ${activeName}`}
        </div>

        <div className="ebook-theme-grid" role="radiogroup" aria-label={strings.ebookThemeSection}>
          {EBOOK_THEMES.map((theme) => {
            const isCurrentActive = activeSpec.id === theme.id;
            const isPairedSlot =
              prefs.themeMode === 'adaptive' &&
              (theme.id === prefs.dayTheme || theme.id === prefs.nightTheme);
            const label = isEnglishUi ? theme.labelEn : theme.labelId;
            return (
              <button
                key={theme.id}
                type="button"
                role="radio"
                aria-checked={isCurrentActive}
                data-ebook-theme-btn={theme.id}
                className={`ebook-theme-swatch pressable ${isCurrentActive ? 'active' : ''}`}
                style={{
                  backgroundColor: theme.bg,
                  color: theme.ink,
                  borderColor: isCurrentActive
                    ? theme.accent
                    : isPairedSlot
                      ? theme.muted
                      : theme.border,
                }}
                onClick={() => handleSelectThemeSwatch(theme)}
              >
                <span className="ebook-theme-aa">Aa</span>
                <span className="ebook-theme-name">{label}</span>
                {isCurrentActive && (
                  <span
                    className="ebook-theme-check"
                    style={{
                      backgroundColor: theme.accent,
                      color: theme.isDark ? '#141416' : '#FFFFFF',
                    }}
                    aria-hidden="true"
                  >
                    <IconCheck size={11} />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </section>

      {/* 2. Page-Turn Motion Mode + Wide-Screen 2-Page Spread (Ebook Reader only) */}
      {!hideReaderOnlyControls && (
        <section className="ebook-appear-section" aria-label={strings.ebookPageModeSection}>
          <div className="ebook-appear-label">{strings.ebookPageModeSection}</div>
          <div className="ebook-seg-row" role="radiogroup" aria-label={strings.ebookPageModeSection}>
            {(
              [
                ['scroll', strings.ebookPageScroll],
                ['slide', strings.ebookPageSlide],
                ['flip', strings.ebookPageFlip],
              ] as ReadonlyArray<readonly [EbookPageMode, string]>
            ).map(([modeId, label]) => (
              <button
                key={modeId}
                type="button"
                role="radio"
                aria-checked={prefs.pageMode === modeId}
                data-ebook-pagemode-btn={modeId}
                className={`ebook-seg-btn pressable ${prefs.pageMode === modeId ? 'active' : ''}`}
                onClick={() => onUpdate({ pageMode: modeId })}
              >
                {label}
              </button>
            ))}
          </div>

          {prefs.pageMode !== 'scroll' && (
            <div className="ebook-theme-status-note">
              {strings.ebookPageGestureHint}
            </div>
          )}

          {canUseSpread && prefs.pageMode !== 'scroll' && (
            <div className="ebook-appear-inline-row">
              <span className="ebook-appear-label">{strings.ebookSpreadLabel}</span>
              <div className="ebook-seg-row is-compact" style={{ minWidth: '176px' }}>
                {(
                  [
                    ['single', strings.ebookSpreadSingle],
                    ['auto', strings.ebookSpreadAuto],
                  ] as ReadonlyArray<readonly [EbookSpreadMode, string]>
                ).map(([spreadId, label]) => (
                  <button
                    key={spreadId}
                    type="button"
                    aria-pressed={prefs.spread === spreadId}
                    data-ebook-spread-btn={spreadId}
                    className={`ebook-seg-btn pressable ${prefs.spread === spreadId ? 'active' : ''}`}
                    onClick={() => onUpdate({ spread: spreadId })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* 3. Typography Sizing, Line Spacing, Measure & Alignment */}
      <section className="ebook-appear-section" aria-label={strings.ebookTextSizeLabel}>
        <div className="ebook-controls-grid">
          <div className="ebook-control-block">
            <span className="ebook-appear-label">{strings.ebookTextSizeLabel}</span>
            <div className="ebook-stepper">
              <button
                type="button"
                className="ebook-step-btn pressable"
                aria-label={`${strings.ebookTextSizeLabel} -`}
                disabled={prefs.fontSize <= 14}
                onClick={() => onUpdate({ fontSize: Math.max(14, prefs.fontSize - 1) })}
              >
                A-
              </button>
              <span className="ebook-step-val">{prefs.fontSize}px</span>
              <button
                type="button"
                className="ebook-step-btn pressable"
                aria-label={`${strings.ebookTextSizeLabel} +`}
                disabled={prefs.fontSize >= 32}
                onClick={() => onUpdate({ fontSize: Math.min(32, prefs.fontSize + 1) })}
              >
                A+
              </button>
            </div>
          </div>

          <div className="ebook-control-block">
            <span className="ebook-appear-label">{strings.ebookLineHeightLabel}</span>
            <div className="ebook-seg-row is-compact">
              {([1.58, 1.75, 1.95] as const).map((lh) => (
                <button
                  key={lh}
                  type="button"
                  aria-pressed={Math.abs(prefs.lineHeight - lh) < 0.08}
                  className={`ebook-seg-btn pressable ${Math.abs(prefs.lineHeight - lh) < 0.08 ? 'active' : ''}`}
                  onClick={() => onUpdate({ lineHeight: lh })}
                >
                  {lh.toFixed(2)}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* WCAG 1.4.12 Text Spacing + Dyslexia/Low-Vision 1-Tap Preset */}
        <div className="ebook-controls-grid" style={{ marginTop: '8px' }}>
          <div className="ebook-control-block">
            <span className="ebook-appear-label">{strings.ebookLetterSpacingLabel}</span>
            <div className="ebook-seg-row is-compact">
              {([0, 0.05, 0.12] as const).map((ls) => (
                <button
                  key={ls}
                  type="button"
                  aria-pressed={Math.abs(prefs.letterSpacing - ls) < 0.015}
                  data-ebook-ls-btn={String(ls)}
                  className={`ebook-seg-btn pressable ${Math.abs(prefs.letterSpacing - ls) < 0.015 ? 'active' : ''}`}
                  onClick={() => onUpdate({ letterSpacing: ls })}
                >
                  {ls === 0 ? '0' : `+${ls}`}
                </button>
              ))}
            </div>
          </div>

          <div className="ebook-control-block">
            <span className="ebook-appear-label">{strings.ebookWordSpacingLabel}</span>
            <div className="ebook-seg-row is-compact">
              {([0, 0.08, 0.16] as const).map((ws) => (
                <button
                  key={ws}
                  type="button"
                  aria-pressed={Math.abs(prefs.wordSpacing - ws) < 0.02}
                  data-ebook-ws-btn={String(ws)}
                  className={`ebook-seg-btn pressable ${Math.abs(prefs.wordSpacing - ws) < 0.02 ? 'active' : ''}`}
                  onClick={() => onUpdate({ wordSpacing: ws })}
                >
                  {ws === 0 ? '0' : `+${ws}`}
                </button>
              ))}
            </div>
          </div>

          <div className="ebook-control-block">
            <span className="ebook-appear-label">{strings.ebookParaSpacingLabel}</span>
            <div className="ebook-seg-row is-compact">
              {([1.05, 1.45, 1.85] as const).map((ps) => (
                <button
                  key={ps}
                  type="button"
                  aria-pressed={Math.abs(prefs.paragraphSpacing - ps) < 0.12}
                  className={`ebook-seg-btn pressable ${Math.abs(prefs.paragraphSpacing - ps) < 0.12 ? 'active' : ''}`}
                  onClick={() => onUpdate({ paragraphSpacing: ps })}
                >
                  {ps.toFixed(1)}x
                </button>
              ))}
            </div>
          </div>
        </div>

        {!hideReaderOnlyControls && (
          <div className="ebook-controls-grid" style={{ marginTop: '8px' }}>
            <div className="ebook-control-block">
              <span className="ebook-appear-label">{strings.ebookReadingRulerLabel}</span>
              <div className="ebook-seg-row is-compact">
                {(
                  [
                    ['off', strings.ebookRulerOff],
                    ['bar', strings.ebookRulerBar],
                    ['shade', strings.ebookRulerShade],
                    ['underline', strings.ebookRulerUnderline],
                  ] as ReadonlyArray<readonly [EbookReadingRulerMode, string]>
                ).map(([rId, label]) => (
                  <button
                    key={rId}
                    type="button"
                    aria-pressed={prefs.readingRuler === rId}
                    data-ebook-ruler-btn={rId}
                    className={`ebook-seg-btn pressable ${prefs.readingRuler === rId ? 'active' : ''}`}
                    onClick={() => onUpdate({ readingRuler: rId })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {prefs.pageMode !== 'scroll' && (
              <div className="ebook-control-block">
                <span className="ebook-appear-label">{strings.ebookTapZoneLabel}</span>
                <div className="ebook-seg-row is-compact">
                  {(
                    [
                      ['edges', strings.ebookTapEdges],
                      ['right-hand', strings.ebookTapRight],
                      ['left-hand', strings.ebookTapLeft],
                    ] as ReadonlyArray<readonly [EbookTapZoneMode, string]>
                  ).map(([tId, label]) => (
                    <button
                      key={tId}
                      type="button"
                      aria-pressed={prefs.tapZone === tId}
                      data-ebook-tapzone-btn={tId}
                      className={`ebook-seg-btn pressable ${prefs.tapZone === tId ? 'active' : ''}`}
                      onClick={() => onUpdate({ tapZone: tId })}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!hideReaderOnlyControls && (
          <div className="ebook-controls-grid" style={{ marginTop: '8px' }}>
            <div className="ebook-control-block">
              <span className="ebook-appear-label">{strings.ebookWidthLabel}</span>
              <div className="ebook-seg-row is-compact">
                {(
                  [
                    ['narrow', strings.ebookWidthNarrow],
                    ['standard', strings.ebookWidthStandard],
                    ['wide', strings.ebookWidthWide],
                  ] as ReadonlyArray<readonly [EbookMeasure, string]>
                ).map(([mId, label]) => (
                  <button
                    key={mId}
                    type="button"
                    aria-pressed={prefs.measure === mId}
                    className={`ebook-seg-btn pressable ${prefs.measure === mId ? 'active' : ''}`}
                    onClick={() => onUpdate({ measure: mId })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="ebook-control-block">
              <span className="ebook-appear-label">{strings.ebookAlignLabel}</span>
              <div className="ebook-seg-row is-compact">
                {(
                  [
                    ['left', strings.ebookAlignLeft],
                    ['justify', strings.ebookAlignJustify],
                  ] as ReadonlyArray<readonly [EbookAlign, string]>
                ).map(([aId, label]) => (
                  <button
                    key={aId}
                    type="button"
                    aria-pressed={prefs.align === aId}
                    className={`ebook-seg-btn pressable ${prefs.align === aId ? 'active' : ''}`}
                    onClick={() => onUpdate({ align: aId })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 4. 14 Curated Author & Publisher Reading Fonts with Category Filter */}
      <section className="ebook-appear-section" aria-label={strings.ebookFontSection}>
        <div className="ebook-appear-section-head">
          <span className="ebook-appear-label">
            {isEnglishUi ? 'Font (14)' : 'Font bacaan (14)'}
          </span>
          <div className="ebook-font-filter-row" role="tablist" aria-label={strings.ebookFontSection}>
            {(
              [
                ['all', strings.ebookFontFilterAll],
                ['serif', strings.ebookFontFilterSerif],
                ['sans', strings.ebookFontFilterSans],
                ['jp', strings.ebookFontFilterJp],
              ] as ReadonlyArray<readonly [FontFilter, string]>
            ).map(([cat, label]) => (
              <button
                key={cat}
                type="button"
                role="tab"
                aria-selected={fontFilter === cat}
                className={`ebook-filter-chip pressable ${fontFilter === cat ? 'active' : ''}`}
                onClick={() => setFontFilter(cat)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="ebook-font-grid" role="radiogroup" aria-label={strings.ebookFontSection}>
          {filteredFonts.map((font) => {
            const active = prefs.fontId === font.id;
            return (
              <button
                key={font.id}
                type="button"
                role="radio"
                aria-checked={active}
                data-ebook-font-btn={font.id}
                className={`ebook-font-card pressable ${active ? 'active' : ''}`}
                onClick={() => {
                  ensureEbookFontLoaded(font.id);
                  onUpdate({ fontId: font.id });
                }}
              >
                <span className="ebook-font-name" style={{ fontFamily: font.stack }}>
                  {font.name}
                </span>
                <span className="ebook-font-note">
                  {isEnglishUi ? font.noteEn : font.noteId}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      {/* 5. Inline Source Peek + Focus / Zen Mode + Reset */}
      {!hideReaderOnlyControls && (
        <button
          type="button"
          className={`ebook-toggle-row pressable ${prefs.inlinePeek ? 'active' : ''}`}
          aria-pressed={prefs.inlinePeek}
          data-ebook-inlinepeek-btn="true"
          onClick={() => onUpdate({ inlinePeek: !prefs.inlinePeek })}
        >
          <IconEye size={16} />
          <span style={{ flex: 1, textAlign: 'left' }}>{strings.ebookInlinePeekLabel}</span>
          {prefs.inlinePeek && <IconCheck size={15} />}
        </button>
      )}

      <div className="ebook-appear-footer">
        <button
          type="button"
          className="btn-secondary pressable"
          data-ebook-dyslexia-preset="true"
          onClick={() => {
            ensureEbookFontLoaded('atkinson');
            onUpdate(DYSLEXIA_COMFORT_PATCH);
          }}
        >
          {strings.ebookDyslexiaPresetBtn}
        </button>
        {!hideReaderOnlyControls && (
          <button
            type="button"
            className={prefs.zenMode ? 'btn-primary pressable' : 'btn-secondary pressable'}
            aria-pressed={prefs.zenMode}
            onClick={() => {
              onUpdate({ zenMode: !prefs.zenMode });
              onClose();
            }}
          >
            {strings.ebookZenModeLabel}
          </button>
        )}
        <button
          type="button"
          className="btn-secondary pressable"
          onClick={() => onUpdate({ ...DEFAULT_EBOOK_PREFS })}
        >
          {strings.ebookResetDefaults}
        </button>
      </div>
    </div>
  );

  if (isMobile) {
    return (
      <div className="bottom-sheet-backdrop" onClick={onClose}>
        <div
          ref={dialogRef}
          className="bottom-sheet glass-regular-surface ebook-appear-sheet"
          role="dialog"
          aria-modal="true"
          aria-label={strings.ebookAppearanceTitle}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            className="sheet-handle-btn"
            aria-label={strings.closeLabel}
            onClick={onClose}
          >
            <span className="sheet-handle-pill" />
          </button>
          <div className="ebook-appear-header">
            <h2 className="modal-title">{strings.ebookAppearanceTitle}</h2>
            <button
              type="button"
              className="icon-square-btn"
              aria-label={strings.closeLabel}
              onClick={onClose}
            >
              <IconX size={18} />
            </button>
          </div>
          {panelBody}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="popover-dismiss-backdrop" onClick={onClose} aria-hidden="true" />
      <div
        ref={dialogRef}
        className="context-popover glass-regular-surface ebook-appear-popover"
        role="dialog"
        aria-modal="true"
        aria-label={strings.ebookAppearanceTitle}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ebook-appear-header">
          <h2 className="modal-title">{strings.ebookAppearanceTitle}</h2>
          <button
            type="button"
            className="icon-square-btn"
            aria-label={strings.closeLabel}
            onClick={onClose}
          >
            <IconX size={18} />
          </button>
        </div>
        {panelBody}
      </div>
    </>
  );
});
