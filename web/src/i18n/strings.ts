import type { SourceLang, TargetLang, UiLang } from '../types';

export interface UiStrings {
  greeting: string;
  pasteAndTranslate: string;
  composerPlaceholder: string;
  composerImagePlaceholder: string;
  composerDocPlaceholder: string;
  composerLinkPlaceholder: string;
  modeText: string;
  modeImage: string;
  modeDocument: string;
  modeLink: string;
  langAuto: string;
  langAutoShort: string;
  langId: string;
  langEn: string;
  langJa: string;
  swapLanguages: string;
  sourceLangTitle: string;
  targetLangTitle: string;
  detectedPrefix: string;
  langJaId: string;
  langJaEn: string;
  langMenuTitle: string;
  sourceAutoHint: string;
  sidebarNew: string;
  sidebarSearch: string;
  sidebarSearchPlaceholder: string;
  sidebarMore: string;
  myFiles: string;
  glossary: string;
  shortcuts: string;
  pinnedSection: string;
  recentSection: string;
  emptyHistory: string;
  noSearchMatch: string;
  pinChat: string;
  pinToTop: string;
  unpinChat: string;
  renameChat: string;
  shareChat: string;
  deleteChat: string;
  deleteHistoryMobile: string;
  settings: string;
  uiLanguage: string;
  help: string;
  sendFeedback: string;
  learnMore: string;
  signOut: string;
  signOutTitle: string;
  signOutBody: string;
  cancel: string;
  save: string;
  undo: string;
  copiedToast: string;
  pinnedToast: string;
  unpinnedToast: string;
  langChangedToast: string;
  deletedToast: string;
  dictationListening: string;
  dictationStop: string;
  dictationStart: string;
  send: string;
  stop: string;
  showAll: string;
  showLess: string;
  editSource: string;
  copyTranslation: string;
  retranslate: string;
  selectText: string;
  sideBySide: string;
  imageOverlay: string;
  takeCameraPhoto: string;
  pickFromGallery: string;
  pickImage: string;
  downloadImage: string;
  copyText: string;
  pickDocument: string;
  dropFilesHere: string;
  supportedDocHint: string;
  supportedImageHint: string;
  pasteLinkLabel: string;
  translateLinkBtn: string;
  openFullTranslatedPage: string;
  openOriginalSite: string;
  downloadResult: string;
  readSideBySide: string;
  resumeTranslation: string;
  retryNow: string;
  pickAnotherFile: string;
  lockName: string;
  lockedBadge: string;
  loginSubtitle: string;
  loginWithGoogle: string;
  loginWithPairCode: string;
  pairCodeTitle: string;
  pairCodeHint: string;
  pairSubmit: string;
  backToLogin: string;
  notOwnerError: string;
  offlineBanner: string;
  settingsGeneral: string;
  settingsAccount: string;
  settingsData: string;
  settingsAdvanced: string;
  themeLabel: string;
  themeSystem: string;
  themeLight: string;
  themeDark: string;
  defaultSourceLabel: string;
  defaultTargetLabel: string;
  inboxFromShortcut: string;
  translateNow: string;
  dismiss: string;
  translateImageBtn: string;
  translateDocBtn: string;
  translateAnotherImage: string;
  translateAnotherDoc: string;
  translateAnotherLink: string;
  addMoreFiles: string;
  pasteUrlBtn: string;
  backBtn: string;
  translatedViewTab: string;
  originalViewTab: string;
  loadingWebPage: string;
  cannotTranslateWeb: string;
  readingImageOcr: string;
  processingDoc: string;
  readyToSend: string;
  fastLimitUnit: string;
  longLimitUnit: string;
  paragraphsUnit: string;
  lockedNamesUnit: string;
  openTranslatedSite: string;
  openAutoTranslatedTab: string;
  readerModeTab: string;
  translatedSiteTab: string;
  bilingualToggle: string;
  novelDetectedBadge: string;
  ebookTocBadge: string;
  startReadingCh1: string;
  continueNextChapter: string;
  lastChapterReached: string;
  readFromChapter1: string;
  searchChaptersPlaceholder: string;
  translatingChapters: string;
  prevChapter: string;
  nextChapter: string;
  chapterListBtn: string;
  loadingNextChapter: string;
  noChaptersFound: string;
  openTocSite: string;
  currentChapterBadge: string;
  resumeReadingChapter: string;
  streamingProgressLabel: string;
  installAppMenu: string;
  installBannerTitle: string;
  installBannerDesc: string;
  installNowBtn: string;
  installLaterBtn: string;
  installSuccessToast: string;
  installGuideTitle: string;
  installGuideIosStep1: string;
  installGuideIosStep2: string;
  installGuideAndroidStep1: string;
  installGuideAndroidStep2: string;
  installGuideMacSafariStep1: string;
  installGuideDesktopStep1: string;
  installGuideDesktopStep2: string;
  readerMenuLabel: string;
  shortEbookTab: string;
  shortSiteTab: string;
  shortPrevChapter: string;
  shortNextChapter: string;
  closeLabel: string;
  // 404 Guard
  notFoundTitle: string;
  notFoundDesc: string;
  backToHomeBtn: string;
  // Translation Tone / Style
  translationToneLabel: string;
  toneAuto: string;
  toneNovel: string;
  toneCasual: string;
  toneFormal: string;
  // Ebook Appearance, Themes, Fonts & Page-Turn HCI
  ebookAppearanceBtn: string;
  ebookAppearanceTitle: string;
  ebookThemeSection: string;
  ebookPageModeSection: string;
  ebookPageScroll: string;
  ebookPageSlide: string;
  ebookPageFlip: string;
  ebookFontSection: string;
  ebookTextSizeLabel: string;
  ebookLineHeightLabel: string;
  ebookWidthLabel: string;
  ebookWidthNarrow: string;
  ebookWidthStandard: string;
  ebookWidthWide: string;
  ebookAlignLabel: string;
  ebookAlignLeft: string;
  ebookAlignJustify: string;
  ebookZenModeLabel: string;
  ebookExitZenBtn: string;
  ebookPageCounter: string;
  ebookMinUnit: string;
  ebookPrevPage: string;
  ebookNextPage: string;
  ebookThemeAuto: string;
  ebookResetDefaults: string;
  // Ebook v2 Dual-Slot Theme, Progressive Disclosure, Spread, Inline Peek, Bookmark, TTS & Shelf
  ebookThemeModeAdaptive: string;
  ebookThemeModeLocked: string;
  ebookDaySlotLabel: string;
  ebookNightSlotLabel: string;
  ebookActiveSlotHint: string;
  ebookLockedSlotHint: string;
  ebookSpreadLabel: string;
  ebookSpreadSingle: string;
  ebookSpreadAuto: string;
  ebookFontFilterAll: string;
  ebookFontFilterSerif: string;
  ebookFontFilterSans: string;
  ebookFontFilterJp: string;
  ebookToolsMenuBtn: string;
  ebookToolsMenuTitle: string;
  ebookInlinePeekLabel: string;
  ebookInlinePeekHint: string;
  ebookBookmarkAdd: string;
  ebookBookmarkSaved: string;
  ebookBookmarksTab: string;
  ebookChaptersTab: string;
  ebookNoBookmarks: string;
  ebookListenBtn: string;
  ebookListenStop: string;
  ebookListenPause: string;
  ebookListenResume: string;
  ebookListenUnsupported: string;
  ebookScrubberLabel: string;
  ebookHudHintToast: string;
  ebookContinueShelfTitle: string;
  ebookContinueShelfOpen: string;
  ebookRemoveShelfItem: string;
  settingsAppThemeHint: string;
  settingsEbookThemeLabel: string;
  settingsEbookThemeHint: string;
  // Ebook v3: Hierarchy Groups, Auto-Gulir, Tactile Page-Turn & Podcast Narration Studio
  ebookToolsGroupHandsFree: string;
  ebookToolsGroupReading: string;
  ebookToolsGroupSource: string;
  ebookPageGestureHint: string;
  ebookAutoScrollBtn: string;
  ebookAutoScrollActive: string;
  ebookAutoScrollPaused: string;
  ebookAutoScrollStop: string;
  ebookAutoScrollSpeedDown: string;
  ebookAutoScrollSpeedUp: string;
  ebookAutoScrollSwitchedToast: string;
  ebookAutoScrollPausedTouchToast: string;
  ebookAutoScrollEndToast: string;
  ebookPodcastBtn: string;
  ebookPodcastStudioBtn: string;
  ebookPodcastStyleLabel: string;
  ebookPodcastStyleSantai: string;
  ebookPodcastStyleNarasi: string;
  ebookPodcastStyleCepat: string;
  ebookPodcastVoiceLabel: string;
  ebookPodcastVoiceAuto: string;
  ebookPodcastSleepLabel: string;
  ebookPodcastSleepOff: string;
  ebookPodcastSleep15: string;
  ebookPodcastSleep30: string;
  ebookPodcastSleepChapter: string;
  ebookPodcastSleepDoneToast: string;
  ebookPodcastPrevPara: string;
  ebookPodcastNextPara: string;
  ebookPodcastFollowBtn: string;
  ebookPodcastKindNarration: string;
  ebookPodcastKindDialogue: string;
  ebookPodcastKindThought: string;
  ebookPodcastKindIntro: string;
  ebookPodcastKindQuestion: string;
  ebookPodcastKindCode: string;
  ebookPodcastKindTable: string;
  ebookPodcastKindList: string;
  ebookPodcastKindVerse: string;
  ebookPodcastFormatLabel: string;
  ebookPodcastFormatAuto: string;
  ebookPodcastFormatFiction: string;
  ebookPodcastFormatScript: string;
  ebookPodcastFormatNews: string;
  ebookPodcastFormatAcademic: string;
  ebookPodcastFormatTech: string;
  ebookPodcastFormatList: string;
  ebookPodcastFormatPoetry: string;
  ebookPodcastFormatLetter: string;
  // Manga / Comic / Direct-Image Link Scanner & Visual Overlay
  statusDone: string;
  mangaDetectedBadge: string;
  mangaDirectImageBadge: string;
  mangaPageUnit: string;
  mangaScannedLabel: string;
  mangaToolbarLabel: string;
  mangaViewOverlay: string;
  mangaViewOriginal: string;
  mangaViewList: string;
  mangaSfxToggle: string;
  mangaScanAllBtn: string;
  mangaScanningProgress: string;
  mangaListenDialogue: string;
  mangaDrmTitle: string;
  mangaCorsFallbackTitle: string;
  mangaCorsFallbackDesc: string;
  mangaUploadRescueBtn: string;
  mangaUploadRescueResult: string;
  mangaPageLabel: string;
  mangaBubblesUnit: string;
  mangaScanPageBtn: string;
  mangaRescanPageBtn: string;
  mangaNotScannedYet: string;
  openMangaReaderBtn: string;
  // v2.5 WCAG 1.4.12 Spacing, Reading Ruler, Handedness, Jump-Back & Podcast Studio Telemetry
  ebookDyslexiaPresetBtn: string;
  ebookSpacingSection: string;
  ebookLetterSpacingLabel: string;
  ebookWordSpacingLabel: string;
  ebookParaSpacingLabel: string;
  ebookReadingRulerLabel: string;
  ebookRulerOff: string;
  ebookRulerBar: string;
  ebookRulerShade: string;
  ebookRulerUnderline: string;
  ebookTapZoneLabel: string;
  ebookTapEdges: string;
  ebookTapRight: string;
  ebookTapLeft: string;
  ebookJumpBackBtn: string;
  ebookPodcastCastLabel: string;
  ebookPodcastCastSingle: string;
  ebookPodcastCastPersona: string;
  ebookPodcastCastMulti: string;
  ebookPodcastPreviewVoiceBtn: string;
  ebookPodcastLocalFallbackPill: string;
}

export const STRINGS: Record<UiLang, UiStrings> = {
  id: {
    greeting: 'Mau baca apa hari ini?',
    pasteAndTranslate: 'Tempel dan terjemahkan',
    composerPlaceholder: 'Ketik atau tempel teks, atau mulai bicara...',
    composerImagePlaceholder: 'Tambahkan catatan konteks tokoh bila perlu...',
    composerDocPlaceholder: 'Tambahkan petunjuk judul karya bila perlu...',
    composerLinkPlaceholder: 'Tempel tautan artikel atau halaman web (https://...)',
    modeText: 'Teks',
    modeImage: 'Gambar',
    modeDocument: 'Dokumen',
    modeLink: 'Link',
    langAuto: 'Deteksi bahasa',
    langAutoShort: 'Deteksi',
    langId: 'Indonesia',
    langEn: 'Inggris',
    langJa: 'Jepang',
    swapLanguages: 'Tukar bahasa',
    sourceLangTitle: 'Bahasa sumber',
    targetLangTitle: 'Bahasa tujuan',
    detectedPrefix: 'Terdeteksi',
    langJaId: 'Jepang \u2192 Indonesia',
    langJaEn: 'Jepang \u2192 Inggris',
    langMenuTitle: 'Pasangan bahasa',
    sourceAutoHint: 'Mendeteksi otomatis Indonesia, Inggris, atau Jepang.',
    sidebarNew: 'Baru',
    sidebarSearch: 'Cari',
    sidebarSearchPlaceholder: 'Cari judul atau isi bacaan...',
    sidebarMore: 'Lainnya',
    myFiles: 'Berkas saya',
    glossary: 'Daftar nama',
    shortcuts: 'Pintasan keyboard',
    pinnedSection: 'Disematkan',
    recentSection: 'Terbaru',
    emptyHistory: 'Belum ada riwayat bacaan. Kirim teks, gambar, dokumen, atau tautan untuk memulai.',
    noSearchMatch: 'Tidak ada percakapan yang cocok dengan kata kunci tersebut.',
    pinChat: 'Sematkan',
    pinToTop: 'Sematkan ke atas',
    unpinChat: 'Lepas sematan',
    renameChat: 'Ganti nama',
    shareChat: 'Bagikan',
    deleteChat: 'Hapus',
    deleteHistoryMobile: 'Hapus riwayat',
    settings: 'Setelan',
    uiLanguage: 'Bahasa tampilan',
    help: 'Bantuan',
    sendFeedback: 'Kirim masukan',
    learnMore: 'Pelajari lebih lanjut',
    signOut: 'Keluar',
    signOutTitle: 'Keluar dari tranX?',
    signOutBody: 'Riwayat percakapan dan daftar nama tetap tersimpan aman di akun Anda.',
    cancel: 'Batal',
    save: 'Simpan',
    undo: 'Urungkan',
    copiedToast: 'Terjemahan disalin',
    pinnedToast: 'Percakapan disematkan ke atas',
    unpinnedToast: 'Sematan dilepas',
    langChangedToast: 'Bahasa tampilan diubah ke Indonesia',
    deletedToast: 'Percakapan dihapus',
    dictationListening: 'Mendengarkan suara...',
    dictationStop: 'Selesai bicara',
    dictationStart: 'Dikte suara',
    send: 'Kirim',
    stop: 'Hentikan',
    showAll: 'Tampilkan semua',
    showLess: 'Ringkas sumber',
    editSource: 'Sunting sumber',
    copyTranslation: 'Salin',
    retranslate: 'Terjemahkan ulang',
    selectText: 'Pilih teks',
    sideBySide: 'Berdampingan',
    imageOverlay: 'Hamparan gambar',
    takeCameraPhoto: 'Ambil foto kamera',
    pickFromGallery: 'Galeri',
    pickImage: 'Pilih gambar',
    downloadImage: 'Unduh gambar',
    copyText: 'Salin teks',
    pickDocument: 'Pilih berkas',
    dropFilesHere: 'Lepaskan berkas di sini untuk diterjemahkan',
    supportedDocHint: 'Mendukung .epub, .pdf, .docx, .srt, .vtt, .ass, .html, .md, .txt hingga 50 MB.',
    supportedImageHint: 'Tarik tangkapan layar, halaman manga, atau foto teks (.png, .jpg, .webp).',
    pasteLinkLabel: 'Alamat halaman web',
    translateLinkBtn: 'Terjemahkan halaman',
    openFullTranslatedPage: 'Buka halaman terjemahan penuh',
    openOriginalSite: 'Buka situs asli',
    downloadResult: 'Unduh',
    readSideBySide: 'Baca berdampingan',
    resumeTranslation: 'Lanjutkan',
    retryNow: 'Coba sekarang',
    pickAnotherFile: 'Pilih berkas lain',
    lockName: 'Kunci ejaan nama',
    lockedBadge: 'Terkunci',
    loginSubtitle: 'Ruang baca lintas perangkat untuk teks, gambar, dokumen, dan tautan dalam bahasa Indonesia, Inggris, serta Jepang.',
    loginWithGoogle: 'Masuk dengan Google',
    loginWithPairCode: 'Masuk dengan kode pasangan 6 angka',
    pairCodeTitle: 'Pasangkan perangkat',
    pairCodeHint: 'Buka Setelan \u2192 Akun di perangkat utama Anda, lalu masukkan 6 angka kode pasangan.',
    pairSubmit: 'Masuk dengan kode',
    backToLogin: 'Kembali ke halaman masuk',
    notOwnerError: 'Akun Google Anda belum terverifikasi atau dibatasi pada instance ini. Silakan masuk dengan akun Google terverifikasi.',
    offlineBanner: 'Koneksi terputus. Anda tetap dapat membaca riwayat dan daftar nama tersimpan.',
    settingsGeneral: 'Umum',
    settingsAccount: 'Akun',
    settingsData: 'Data',
    settingsAdvanced: 'Lanjutan',
    themeLabel: 'Tema tampilan',
    themeSystem: 'Ikuti sistem',
    themeLight: 'Terang',
    themeDark: 'Gelap',
    defaultSourceLabel: 'Bahasa sumber bawaan',
    defaultTargetLabel: 'Bahasa tujuan bawaan',
    inboxFromShortcut: 'Kiriman baru dari Pintasan',
    translateNow: 'Terjemahkan sekarang',
    dismiss: 'Abaikan',
    translateImageBtn: 'Terjemahkan gambar',
    translateDocBtn: 'Terjemahkan dokumen',
    translateAnotherImage: 'Terjemahkan gambar lain',
    translateAnotherDoc: 'Terjemahkan dokumen lain',
    translateAnotherLink: 'Terjemahkan tautan lain',
    addMoreFiles: 'Tambah berkas',
    pasteUrlBtn: 'Tempel URL',
    backBtn: 'Kembali',
    translatedViewTab: 'Terjemahan',
    originalViewTab: 'Situs asli',
    loadingWebPage: 'Memuat dan menerjemahkan halaman web...',
    cannotTranslateWeb: 'Tidak dapat diterjemahkan langsung',
    readingImageOcr: 'Mendeteksi teks pada gambar dan menerjemahkan...',
    processingDoc: 'Membaca dan menerjemahkan dokumen...',
    readyToSend: 'Siap diterjemahkan',
    fastLimitUnit: 'cepat',
    longLimitUnit: 'naskah panjang',
    paragraphsUnit: 'paragraf',
    lockedNamesUnit: 'nama terkunci',
    openTranslatedSite: 'Buka situs terjemahan',
    openAutoTranslatedTab: 'Buka web terjemahan otomatis',
    readerModeTab: 'Mode Ebook',
    translatedSiteTab: 'Situs Terjemahan',
    bilingualToggle: 'Berdampingan',
    novelDetectedBadge: 'Ebook terdeteksi',
    ebookTocBadge: 'Daftar isi Ebook',
    startReadingCh1: 'Mulai baca Bab 1',
    continueNextChapter: 'Lanjut ke bab berikutnya',
    lastChapterReached: 'Anda berada di bab terakhir yang tersedia',
    readFromChapter1: 'Baca dari Bab 1',
    searchChaptersPlaceholder: 'Cari nomor atau judul bab...',
    translatingChapters: 'Menerjemahkan daftar bab...',
    prevChapter: 'Bab sebelumnya',
    nextChapter: 'Bab berikutnya',
    chapterListBtn: 'Daftar bab',
    loadingNextChapter: 'Memuat bab berikutnya...',
    noChaptersFound: 'Daftar bab belum tersedia pada halaman ini. Gunakan tombol Bab sebelumnya / Bab berikutnya.',
    openTocSite: 'Buka halaman daftar isi (terjemahan)',
    currentChapterBadge: 'Aktif',
    resumeReadingChapter: 'Lanjutkan baca',
    streamingProgressLabel: 'Menerjemahkan',
    installAppMenu: 'Pasang aplikasi',
    installBannerTitle: 'Pasang aplikasi tranX',
    installBannerDesc: 'Buka sebagai aplikasi penuh di layar utama, lebih cepat, dan siap dipakai di desktop maupun HP.',
    installNowBtn: 'Pasang sekarang',
    installLaterBtn: 'Nanti',
    installSuccessToast: 'tranX berhasil dipasang sebagai aplikasi!',
    installGuideTitle: 'Cara memasang aplikasi tranX',
    installGuideIosStep1: 'Ketuk tombol Bagikan (ikon kotak dengan panah ke atas) di bilah bawah Safari.',
    installGuideIosStep2: 'Pilih "Tambah ke Layar Utama", lalu ketuk "Tambah".',
    installGuideAndroidStep1: 'Ketuk menu titik tiga (⋮) di pojok kanan atas Chrome Android.',
    installGuideAndroidStep2: 'Pilih "Instal aplikasi" lalu ketuk "Instal". (Jika Chrome menampilkan "Buka tranX", aplikasi masih terpasang di laci aplikasi HP Anda; jika baru saja di-uninstall, menu titik tiga ini langsung memasang ulang tanpa menunggu jeda Chrome.)',
    installGuideMacSafariStep1: 'Di Safari macOS, buka menu File lalu pilih "Tambahkan ke Dock" untuk memasang tranX sebagai aplikasi penuh.',
    installGuideDesktopStep1: 'Klik ikon "Pasang tranX" di sisi kanan bilah alamat browser (Chrome / Edge / Brave), atau buka menu titik tiga browser lalu pilih "Pasang aplikasi".',
    installGuideDesktopStep2: 'Konfirmasi "Pasang" agar tranX muncul sebagai aplikasi mandiri di desktop atau layar utama HP Anda.',
    readerMenuLabel: 'Menu pembaca',
    shortEbookTab: 'Ebook',
    shortSiteTab: 'Situs',
    shortPrevChapter: 'Sblm',
    shortNextChapter: 'Lanjut',
    closeLabel: 'Tutup',
    notFoundTitle: 'Halaman tidak ditemukan',
    notFoundDesc:
      'Alamat atau jalur tautan yang Anda buka tidak valid atau tidak tersedia di tranX. Silakan kembali ke beranda untuk melanjutkan.',
    backToHomeBtn: 'Kembali ke Beranda',
    translationToneLabel: 'Gaya bahasa terjemahan',
    toneAuto: 'Otomatis (Kontekstual)',
    toneNovel: 'Novel Alami',
    toneCasual: 'Santai & Dialog',
    toneFormal: 'Formal & Baku',
    ebookAppearanceBtn: 'Tampilan',
    ebookAppearanceTitle: 'Tampilan Ebook',
    ebookThemeSection: 'Tema kertas & warna nyaman mata',
    ebookPageModeSection: 'Gaya pindah halaman',
    ebookPageScroll: 'Gulir',
    ebookPageSlide: 'Geser',
    ebookPageFlip: 'Balik Buku',
    ebookFontSection: 'Font bacaan (14 pilihan penerbit)',
    ebookTextSizeLabel: 'Ukuran huruf',
    ebookLineHeightLabel: 'Jarak baris',
    ebookWidthLabel: 'Lebar halaman',
    ebookWidthNarrow: 'Sempit',
    ebookWidthStandard: 'Standar',
    ebookWidthWide: 'Lebar',
    ebookAlignLabel: 'Perataan',
    ebookAlignLeft: 'Rata kiri',
    ebookAlignJustify: 'Rata kanan-kiri',
    ebookZenModeLabel: 'Mode Fokus (Zen)',
    ebookExitZenBtn: 'Keluar Fokus',
    ebookPageCounter: 'Hal',
    ebookMinUnit: 'mnt',
    ebookPrevPage: 'Halaman sebelumnya',
    ebookNextPage: 'Halaman berikutnya',
    ebookThemeAuto: 'Otomatis Siang/Malam',
    ebookResetDefaults: 'Atur ulang bawaan',
    ebookThemeModeAdaptive: 'Otomatis Siang/Malam',
    ebookThemeModeLocked: 'Kunci 1 Kertas',
    ebookDaySlotLabel: 'Kertas Siang (Saat App Terang)',
    ebookNightSlotLabel: 'Kertas Malam (Saat App Gelap)',
    ebookActiveSlotHint: 'Mengikuti tema sistem & aplikasi',
    ebookLockedSlotHint: 'Terkunci di semua kondisi pencahayaan',
    ebookSpreadLabel: 'Tata letak layar lebar',
    ebookSpreadSingle: '1 Halaman',
    ebookSpreadAuto: '2 Halaman',
    ebookFontFilterAll: 'Semua',
    ebookFontFilterSerif: 'Serif',
    ebookFontFilterSans: 'Sans',
    ebookFontFilterJp: 'Jepang',
    ebookToolsMenuBtn: 'Alat baca',
    ebookToolsMenuTitle: 'Alat & Navigasi Ebook',
    ebookInlinePeekLabel: 'Intip teks asli (ketuk paragraf)',
    ebookInlinePeekHint: 'Ketuk paragraf untuk melihat kalimat asli di bawahnya',
    ebookBookmarkAdd: 'Simpan markah',
    ebookBookmarkSaved: 'Tersimpan di markah',
    ebookBookmarksTab: 'Markah',
    ebookChaptersTab: 'Daftar bab',
    ebookNoBookmarks: 'Belum ada markah tersimpan untuk bacaan ini. Tekan tombol Markah saat membaca untuk menyimpan posisi penting.',
    ebookListenBtn: 'Dengarkan bab',
    ebookListenStop: 'Berhenti',
    ebookListenPause: 'Jeda',
    ebookListenResume: 'Lanjut',
    ebookListenUnsupported: 'Browser perangkat ini belum mendukung pembacaan suara otomatis.',
    ebookScrubberLabel: 'Lompat halaman bab',
    ebookHudHintToast: 'Ketuk tengah layar untuk menampilkan bilah kontrol kembali',
    ebookContinueShelfTitle: 'Lanjutkan membaca',
    ebookContinueShelfOpen: 'Lanjutkan',
    ebookRemoveShelfItem: 'Hapus dari rak lanjutkan membaca',
    settingsAppThemeHint: 'Mengatur warna ruang kerja, panel samping, dan dialog aplikasi.',
    settingsEbookThemeLabel: 'Kertas baca Ebook',
    settingsEbookThemeHint: 'Otomatis memasangkan kertas siang & kertas malam mengikuti tema aplikasi tanpa saling menimpa.',
    ebookToolsGroupHandsFree: 'Audio & Gulir Otomatis',
    ebookToolsGroupReading: 'Bantuan Baca & Navigasi',
    ebookToolsGroupSource: 'Sumber Halaman',
    ebookPageGestureHint: 'Ketuk tepi kiri/kanan atau usap layar seperti membalik halaman buku.',
    ebookAutoScrollBtn: 'Auto-Gulir (Baca Otomatis)',
    ebookAutoScrollActive: 'Auto-Gulir berjalan',
    ebookAutoScrollPaused: 'Auto-Gulir dijeda',
    ebookAutoScrollStop: 'Hentikan Auto-Gulir',
    ebookAutoScrollSpeedDown: 'Perlambat gulir',
    ebookAutoScrollSpeedUp: 'Percepat gulir',
    ebookAutoScrollSwitchedToast: 'Auto-Gulir aktif di mode Gulir. Ketuk layar kapan saja untuk jeda.',
    ebookAutoScrollPausedTouchToast: 'Auto-Gulir dijeda saat layar disentuh.',
    ebookAutoScrollEndToast: 'Akhir bab tercapai.',
    ebookPodcastBtn: 'Dengarkan bab (Podcast)',
    ebookPodcastStudioBtn: 'Gaya & Suara',
    ebookPodcastStyleLabel: 'Gaya narasi',
    ebookPodcastStyleSantai: 'Podcast Santai',
    ebookPodcastStyleNarasi: 'Narasi Buku',
    ebookPodcastStyleCepat: 'Fokus Cepat',
    ebookPodcastVoiceLabel: 'Suara narator',
    ebookPodcastVoiceAuto: 'Otomatis (Terbaik di perangkat)',
    ebookPodcastSleepLabel: 'Timer tidur',
    ebookPodcastSleepOff: 'Mati',
    ebookPodcastSleep15: '15 mnt',
    ebookPodcastSleep30: '30 mnt',
    ebookPodcastSleepChapter: 'Akhir bab',
    ebookPodcastSleepDoneToast: 'Timer tidur selesai. Audio dijeda dengan tenang.',
    ebookPodcastPrevPara: 'Paragraf sebelumnya',
    ebookPodcastNextPara: 'Paragraf berikutnya',
    ebookPodcastFollowBtn: 'Ikuti suara',
    ebookPodcastKindNarration: 'Narasi',
    ebookPodcastKindDialogue: 'Dialog',
    ebookPodcastKindThought: 'Monolog',
    ebookPodcastKindIntro: 'Pembuka',
    ebookPodcastKindQuestion: 'Pertanyaan',
    ebookPodcastKindCode: 'Kode',
    ebookPodcastKindTable: 'Tabel',
    ebookPodcastKindList: 'Daftar',
    ebookPodcastKindVerse: 'Bait',
    ebookPodcastFormatLabel: 'Format bacaan',
    ebookPodcastFormatAuto: 'Otomatis',
    ebookPodcastFormatFiction: 'Novel / Cerita',
    ebookPodcastFormatScript: 'Naskah Dialog',
    ebookPodcastFormatNews: 'Berita / Editorial',
    ebookPodcastFormatAcademic: 'Akademik / Riset',
    ebookPodcastFormatTech: 'Teknis / Kode',
    ebookPodcastFormatList: 'Daftar / Langkah',
    ebookPodcastFormatPoetry: 'Puisi / Bait',
    ebookPodcastFormatLetter: 'Surat / Kutipan',
    statusDone: 'Selesai',
    mangaDetectedBadge: 'Komik / Manga terdeteksi',
    mangaDirectImageBadge: 'Gambar komik langsung',
    mangaPageUnit: 'halaman',
    mangaScannedLabel: 'dipindai',
    mangaToolbarLabel: 'Kontrol pembaca komik',
    mangaViewOverlay: 'Terjemahan Visual',
    mangaViewOriginal: 'Asli',
    mangaViewList: 'Daftar Dialog',
    mangaSfxToggle: 'SFX',
    mangaScanAllBtn: 'Pindai Semua',
    mangaScanningProgress: 'Memindai',
    mangaListenDialogue: 'Dengarkan Dialog',
    mangaDrmTitle: 'Halaman menggunakan proteksi kanvas DRM',
    mangaCorsFallbackTitle: 'Sebagian gambar dibatasi situs asal',
    mangaCorsFallbackDesc:
      'Situs penerbit membatasi pengambilan piksel langsung. Anda tetap bisa menempel tangkapan layar (Ctrl+V) atau memilih berkas gambar di bawah untuk langsung dipindai.',
    mangaUploadRescueBtn: 'Pilih / Tempel Gambar',
    mangaUploadRescueResult: 'Hasil pindai gambar tempelan',
    mangaPageLabel: 'Halaman',
    mangaBubblesUnit: 'balon teks',
    mangaScanPageBtn: 'Pindai Halaman',
    mangaRescanPageBtn: 'Pindai Ulang',
    mangaNotScannedYet: 'Halaman ini belum dipindai. Ketuk Pindai Halaman untuk membaca dan menerjemahkan dialognya.',
    openMangaReaderBtn: 'Buka Pembaca Komik Visual',
    ebookDyslexiaPresetBtn: 'Preset Fokus Disleksia',
    ebookSpacingSection: 'Spasi huruf, kata & paragraf (WCAG)',
    ebookLetterSpacingLabel: 'Spasi huruf',
    ebookWordSpacingLabel: 'Spasi kata',
    ebookParaSpacingLabel: 'Jarak paragraf',
    ebookReadingRulerLabel: 'Penggaris fokus baca',
    ebookRulerOff: 'Mati',
    ebookRulerBar: 'Pita',
    ebookRulerShade: 'Redup',
    ebookRulerUnderline: 'Garis',
    ebookTapZoneLabel: 'Zona ketuk balik halaman',
    ebookTapEdges: 'Tepi',
    ebookTapRight: 'Tangan kanan',
    ebookTapLeft: 'Tangan kiri',
    ebookJumpBackBtn: 'Kembali ke posisi sebelumnya',
    ebookPodcastCastLabel: 'Gaya pemeran dialog',
    ebookPodcastCastSingle: 'Tunggal',
    ebookPodcastCastPersona: 'Persona',
    ebookPodcastCastMulti: 'Multi-Suara',
    ebookPodcastPreviewVoiceBtn: 'Coba suara',
    ebookPodcastLocalFallbackPill: 'Mode Lokal',
  },
  en: {
    greeting: 'What would you like to read today?',
    pasteAndTranslate: 'Paste and translate',
    composerPlaceholder: 'Type or paste text, or start speaking...',
    composerImagePlaceholder: 'Add character context notes if needed...',
    composerDocPlaceholder: 'Add series or work title hint if needed...',
    composerLinkPlaceholder: 'Paste an article or web page URL (https://...)',
    modeText: 'Text',
    modeImage: 'Image',
    modeDocument: 'Document',
    modeLink: 'Link',
    langAuto: 'Detect language',
    langAutoShort: 'Detect',
    langId: 'Indonesian',
    langEn: 'English',
    langJa: 'Japanese',
    swapLanguages: 'Swap languages',
    sourceLangTitle: 'Source language',
    targetLangTitle: 'Target language',
    detectedPrefix: 'Detected',
    langJaId: 'Japanese \u2192 Indonesian',
    langJaEn: 'Japanese \u2192 English',
    langMenuTitle: 'Language pair',
    sourceAutoHint: 'Automatically detects Indonesian, English, or Japanese.',
    sidebarNew: 'New',
    sidebarSearch: 'Search',
    sidebarSearchPlaceholder: 'Search titles or reading history...',
    sidebarMore: 'More',
    myFiles: 'My files',
    glossary: 'Name glossary',
    shortcuts: 'Keyboard shortcuts',
    pinnedSection: 'Pinned',
    recentSection: 'Recent',
    emptyHistory: 'No reading history yet. Send text, an image, a document, or a link to start.',
    noSearchMatch: 'No conversations match that search query.',
    pinChat: 'Pin',
    pinToTop: 'Pin to top',
    unpinChat: 'Unpin',
    renameChat: 'Rename',
    shareChat: 'Share',
    deleteChat: 'Delete',
    deleteHistoryMobile: 'Delete history',
    settings: 'Settings',
    uiLanguage: 'Display language',
    help: 'Help',
    sendFeedback: 'Send feedback',
    learnMore: 'Learn more',
    signOut: 'Sign out',
    signOutTitle: 'Sign out of tranX?',
    signOutBody: 'Your conversation history and locked character names stay safely synced.',
    cancel: 'Cancel',
    save: 'Save',
    undo: 'Undo',
    copiedToast: 'Translation copied',
    pinnedToast: 'Conversation pinned to top',
    unpinnedToast: 'Conversation unpinned',
    langChangedToast: 'Display language changed to English',
    deletedToast: 'Conversation deleted',
    dictationListening: 'Listening...',
    dictationStop: 'Finish speaking',
    dictationStart: 'Voice dictation',
    send: 'Send',
    stop: 'Stop',
    showAll: 'Show full source',
    showLess: 'Collapse source',
    editSource: 'Edit source',
    copyTranslation: 'Copy',
    retranslate: 'Retranslate',
    selectText: 'Select text',
    sideBySide: 'Side by side',
    imageOverlay: 'Image overlay',
    takeCameraPhoto: 'Take camera photo',
    pickFromGallery: 'Gallery',
    pickImage: 'Choose image',
    downloadImage: 'Download image',
    copyText: 'Copy text',
    pickDocument: 'Choose file',
    dropFilesHere: 'Drop file here to translate',
    supportedDocHint: 'Supports .epub, .pdf, .docx, .srt, .vtt, .ass, .html, .md, .txt up to 50 MB.',
    supportedImageHint: 'Drop a screenshot, manga page, or photo with text (.png, .jpg, .webp).',
    pasteLinkLabel: 'Web page URL',
    translateLinkBtn: 'Translate page',
    openFullTranslatedPage: 'Open full translated page',
    openOriginalSite: 'Open original site',
    downloadResult: 'Download',
    readSideBySide: 'Read side by side',
    resumeTranslation: 'Resume',
    retryNow: 'Retry now',
    pickAnotherFile: 'Choose another file',
    lockName: 'Lock name spelling',
    lockedBadge: 'Locked',
    loginSubtitle: 'Cross-device reading workspace for Indonesian, English, and Japanese text, images, documents, and links.',
    loginWithGoogle: 'Sign in with Google',
    loginWithPairCode: 'Sign in with 6-digit pair code',
    pairCodeTitle: 'Pair this device',
    pairCodeHint: 'Open Settings \u2192 Account on your primary device and enter the 6-digit code.',
    pairSubmit: 'Sign in with code',
    backToLogin: 'Back to sign in',
    notOwnerError: 'Your Google account is unverified or restricted on this deployment. Please sign in with a verified Google account.',
    offlineBanner: 'You are offline. Saved history and character glossaries remain available.',
    settingsGeneral: 'General',
    settingsAccount: 'Account',
    settingsData: 'Data',
    settingsAdvanced: 'Advanced',
    themeLabel: 'Appearance',
    themeSystem: 'Match system',
    themeLight: 'Light',
    themeDark: 'Dark',
    defaultSourceLabel: 'Default source language',
    defaultTargetLabel: 'Default target language',
    inboxFromShortcut: 'New capture from Shortcuts',
    translateNow: 'Translate now',
    dismiss: 'Dismiss',
    translateImageBtn: 'Translate image',
    translateDocBtn: 'Translate document',
    translateAnotherImage: 'Translate another image',
    translateAnotherDoc: 'Translate another document',
    translateAnotherLink: 'Translate another link',
    addMoreFiles: 'Add file',
    pasteUrlBtn: 'Paste URL',
    backBtn: 'Back',
    translatedViewTab: 'Translated',
    originalViewTab: 'Original site',
    loadingWebPage: 'Loading and translating web page...',
    cannotTranslateWeb: 'Cannot translate directly',
    readingImageOcr: 'Detecting text in image and translating...',
    processingDoc: 'Reading and translating document...',
    readyToSend: 'Ready to translate',
    fastLimitUnit: 'fast',
    longLimitUnit: 'long text',
    paragraphsUnit: 'paragraphs',
    lockedNamesUnit: 'locked names',
    openTranslatedSite: 'Open translated site',
    openAutoTranslatedTab: 'Open auto-translated site',
    readerModeTab: 'Ebook Reader',
    translatedSiteTab: 'Translated Site',
    bilingualToggle: 'Side by side',
    novelDetectedBadge: 'Ebook detected',
    ebookTocBadge: 'Ebook Table of Contents',
    startReadingCh1: 'Start reading Chapter 1',
    continueNextChapter: 'Continue to next chapter',
    lastChapterReached: 'You have reached the latest available chapter',
    readFromChapter1: 'Read from Chapter 1',
    searchChaptersPlaceholder: 'Search chapter number or title...',
    translatingChapters: 'Translating chapter list...',
    prevChapter: 'Previous chapter',
    nextChapter: 'Next chapter',
    chapterListBtn: 'Chapters',
    loadingNextChapter: 'Loading next chapter...',
    noChaptersFound: 'Chapter list was not embedded on this page. Use Previous / Next chapter controls.',
    openTocSite: 'Open translated table of contents',
    currentChapterBadge: 'Current',
    resumeReadingChapter: 'Resume reading',
    streamingProgressLabel: 'Translating',
    installAppMenu: 'Install app',
    installBannerTitle: 'Install the tranX app',
    installBannerDesc: 'Launch as a full standalone app from your home screen or desktop for faster reading.',
    installNowBtn: 'Install now',
    installLaterBtn: 'Later',
    installSuccessToast: 'tranX has been installed as an app!',
    installGuideTitle: 'How to install tranX',
    installGuideIosStep1: 'Tap the Share button (square with upward arrow) in Safari.',
    installGuideIosStep2: 'Select "Add to Home Screen", then tap "Add".',
    installGuideAndroidStep1: 'Tap the three-dot menu (⋮) in the top-right corner of Android Chrome.',
    installGuideAndroidStep2: 'Choose "Install app", then tap "Install". (If Chrome shows "Open tranX", the app is still in your Android app drawer; right after uninstalling, this menu reinstalls immediately without Chrome cooldown.)',
    installGuideMacSafariStep1: 'In macOS Safari, open the File menu and choose "Add to Dock" to install tranX as a standalone app.',
    installGuideDesktopStep1: 'Click the Install icon on the right side of the address bar (Chrome / Edge / Brave), or open the browser menu and select "Install app".',
    installGuideDesktopStep2: 'Confirm "Install" to add tranX as a full standalone app on your desktop or home screen.',
    readerMenuLabel: 'Reader menu',
    shortEbookTab: 'Ebook',
    shortSiteTab: 'Site',
    shortPrevChapter: 'Prev',
    shortNextChapter: 'Next',
    closeLabel: 'Close',
    notFoundTitle: 'Page not found',
    notFoundDesc:
      'The URL or path you opened is invalid or not available in tranX. Return to the home workspace to continue reading and translating.',
    backToHomeBtn: 'Back to Home',
    translationToneLabel: 'Translation style',
    toneAuto: 'Auto (Context-aware)',
    toneNovel: 'Natural Novel',
    toneCasual: 'Casual & Dialogue',
    toneFormal: 'Formal & Standard',
    ebookAppearanceBtn: 'Appearance',
    ebookAppearanceTitle: 'Ebook Appearance',
    ebookThemeSection: 'Paper & eye-comfort themes',
    ebookPageModeSection: 'Page-turn animation',
    ebookPageScroll: 'Scroll',
    ebookPageSlide: 'Slide',
    ebookPageFlip: 'Book Flip',
    ebookFontSection: 'Reading font (14 curated faces)',
    ebookTextSizeLabel: 'Font size',
    ebookLineHeightLabel: 'Line height',
    ebookWidthLabel: 'Page width',
    ebookWidthNarrow: 'Narrow',
    ebookWidthStandard: 'Standard',
    ebookWidthWide: 'Wide',
    ebookAlignLabel: 'Alignment',
    ebookAlignLeft: 'Left',
    ebookAlignJustify: 'Justify',
    ebookZenModeLabel: 'Focus Mode (Zen)',
    ebookExitZenBtn: 'Exit Focus',
    ebookPageCounter: 'Page',
    ebookMinUnit: 'min',
    ebookPrevPage: 'Previous page',
    ebookNextPage: 'Next page',
    ebookThemeAuto: 'Auto Day/Night',
    ebookResetDefaults: 'Reset defaults',
    ebookThemeModeAdaptive: 'Auto Day/Night',
    ebookThemeModeLocked: 'Lock 1 Paper',
    ebookDaySlotLabel: 'Day Paper (When App is Light)',
    ebookNightSlotLabel: 'Night Paper (When App is Dark)',
    ebookActiveSlotHint: 'Follows system & app theme automatically',
    ebookLockedSlotHint: 'Locked across all lighting modes',
    ebookSpreadLabel: 'Wide-screen layout',
    ebookSpreadSingle: '1 Page',
    ebookSpreadAuto: '2 Pages',
    ebookFontFilterAll: 'All',
    ebookFontFilterSerif: 'Serif',
    ebookFontFilterSans: 'Sans',
    ebookFontFilterJp: 'Japanese',
    ebookToolsMenuBtn: 'Reader tools',
    ebookToolsMenuTitle: 'Ebook Tools & Options',
    ebookInlinePeekLabel: 'Inline source peek (tap paragraph)',
    ebookInlinePeekHint: 'Tap any paragraph to reveal the original sentence beneath it',
    ebookBookmarkAdd: 'Save bookmark',
    ebookBookmarkSaved: 'Bookmarked',
    ebookBookmarksTab: 'Bookmarks',
    ebookChaptersTab: 'Chapters',
    ebookNoBookmarks: 'No bookmarks saved for this book yet. Tap Bookmark while reading to save a spot.',
    ebookListenBtn: 'Listen to chapter',
    ebookListenStop: 'Stop',
    ebookListenPause: 'Pause',
    ebookListenResume: 'Resume',
    ebookListenUnsupported: 'Your browser does not support built-in speech synthesis.',
    ebookScrubberLabel: 'Jump to page in chapter',
    ebookHudHintToast: 'Tap the center of the page anytime to show reader controls',
    ebookContinueShelfTitle: 'Continue reading',
    ebookContinueShelfOpen: 'Continue',
    ebookRemoveShelfItem: 'Remove from Continue reading',
    settingsAppThemeHint: 'Controls workspace, sidebar, and dialog colors.',
    settingsEbookThemeLabel: 'Ebook reading paper',
    settingsEbookThemeHint: 'Automatically pairs your Day paper and Night paper with app theme without clashing.',
    ebookToolsGroupHandsFree: 'Audio & Auto-Scroll',
    ebookToolsGroupReading: 'Reading Aids & Navigation',
    ebookToolsGroupSource: 'Page Source',
    ebookPageGestureHint: 'Tap left/right edges or swipe horizontally like turning a real book page.',
    ebookAutoScrollBtn: 'Auto-Scroll (Hands-Free)',
    ebookAutoScrollActive: 'Auto-Scroll running',
    ebookAutoScrollPaused: 'Auto-Scroll paused',
    ebookAutoScrollStop: 'Stop Auto-Scroll',
    ebookAutoScrollSpeedDown: 'Slow down scroll',
    ebookAutoScrollSpeedUp: 'Speed up scroll',
    ebookAutoScrollSwitchedToast: 'Auto-Scroll started in Scroll mode. Tap anywhere to pause.',
    ebookAutoScrollPausedTouchToast: 'Auto-Scroll paused on touch.',
    ebookAutoScrollEndToast: 'Reached end of chapter.',
    ebookPodcastBtn: 'Listen to chapter (Podcast)',
    ebookPodcastStudioBtn: 'Style & Voice',
    ebookPodcastStyleLabel: 'Narration style',
    ebookPodcastStyleSantai: 'Warm Podcast',
    ebookPodcastStyleNarasi: 'Audiobook',
    ebookPodcastStyleCepat: 'Crisp Focus',
    ebookPodcastVoiceLabel: 'Narrator voice',
    ebookPodcastVoiceAuto: 'Automatic (Best on device)',
    ebookPodcastSleepLabel: 'Sleep timer',
    ebookPodcastSleepOff: 'Off',
    ebookPodcastSleep15: '15 min',
    ebookPodcastSleep30: '30 min',
    ebookPodcastSleepChapter: 'End of chapter',
    ebookPodcastSleepDoneToast: 'Sleep timer ended. Audio paused gently.',
    ebookPodcastPrevPara: 'Previous paragraph',
    ebookPodcastNextPara: 'Next paragraph',
    ebookPodcastFollowBtn: 'Follow audio',
    ebookPodcastKindNarration: 'Narration',
    ebookPodcastKindDialogue: 'Dialogue',
    ebookPodcastKindThought: 'Thought',
    ebookPodcastKindIntro: 'Intro',
    ebookPodcastKindQuestion: 'Question',
    ebookPodcastKindCode: 'Code',
    ebookPodcastKindTable: 'Table',
    ebookPodcastKindList: 'List',
    ebookPodcastKindVerse: 'Verse',
    ebookPodcastFormatLabel: 'Reading format',
    ebookPodcastFormatAuto: 'Auto',
    ebookPodcastFormatFiction: 'Novel / Story',
    ebookPodcastFormatScript: 'Script Dialogue',
    ebookPodcastFormatNews: 'News / Editorial',
    ebookPodcastFormatAcademic: 'Academic / Paper',
    ebookPodcastFormatTech: 'Technical / Code',
    ebookPodcastFormatList: 'List / Steps',
    ebookPodcastFormatPoetry: 'Poetry / Verse',
    ebookPodcastFormatLetter: 'Letter / Quote',
    statusDone: 'Done',
    mangaDetectedBadge: 'Comic / Manga detected',
    mangaDirectImageBadge: 'Direct comic image',
    mangaPageUnit: 'pages',
    mangaScannedLabel: 'scanned',
    mangaToolbarLabel: 'Comic reader controls',
    mangaViewOverlay: 'Visual overlay',
    mangaViewOriginal: 'Original',
    mangaViewList: 'Dialogue list',
    mangaSfxToggle: 'SFX',
    mangaScanAllBtn: 'Scan All',
    mangaScanningProgress: 'Scanning',
    mangaListenDialogue: 'Listen to Dialogue',
    mangaDrmTitle: 'Publisher uses encrypted DRM canvas',
    mangaCorsFallbackTitle: 'Some images are restricted by origin host',
    mangaCorsFallbackDesc:
      'The source publisher restricts direct pixel fetches. Paste a screenshot (Ctrl+V) or upload an image below to scan and overlay immediately.',
    mangaUploadRescueBtn: 'Choose / Paste Image',
    mangaUploadRescueResult: 'Scanned pasted image',
    mangaPageLabel: 'Page',
    mangaBubblesUnit: 'bubbles',
    mangaScanPageBtn: 'Scan Page',
    mangaRescanPageBtn: 'Rescan',
    mangaNotScannedYet: 'This page has not been scanned yet. Tap Scan Page to extract and translate dialogue.',
    openMangaReaderBtn: 'Open Visual Comic Reader',
    ebookDyslexiaPresetBtn: 'Dyslexia / Low-Vision Preset',
    ebookSpacingSection: 'Letter, word & paragraph spacing (WCAG)',
    ebookLetterSpacingLabel: 'Letter spacing',
    ebookWordSpacingLabel: 'Word spacing',
    ebookParaSpacingLabel: 'Paragraph gap',
    ebookReadingRulerLabel: 'Digital reading ruler',
    ebookRulerOff: 'Off',
    ebookRulerBar: 'Band',
    ebookRulerShade: 'Shade',
    ebookRulerUnderline: 'Line',
    ebookTapZoneLabel: 'Page-turn tap handedness',
    ebookTapEdges: 'Edges',
    ebookTapRight: 'Right hand',
    ebookTapLeft: 'Left hand',
    ebookJumpBackBtn: 'Return to previous spot',
    ebookPodcastCastLabel: 'Dialogue cast mode',
    ebookPodcastCastSingle: 'Single',
    ebookPodcastCastPersona: 'Persona',
    ebookPodcastCastMulti: 'Multi-Voice',
    ebookPodcastPreviewVoiceBtn: 'Preview voice',
    ebookPodcastLocalFallbackPill: 'Local Mode',
  },
};

export function labelForLang(lang: SourceLang | TargetLang, s: UiStrings): string {
  switch (lang) {
    case 'auto':
      return s.langAuto;
    case 'id':
      return s.langId;
    case 'en':
      return s.langEn;
    case 'ja':
      return s.langJa;
  }
}
