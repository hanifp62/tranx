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
  installGuideMacSafariStep1: string;
  installGuideDesktopStep1: string;
  installGuideDesktopStep2: string;
  readerMenuLabel: string;
  shortEbookTab: string;
  shortSiteTab: string;
  shortPrevChapter: string;
  shortNextChapter: string;
  closeLabel: string;
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
    notOwnerError: 'Akses ditolak. Aplikasi pribadi ini terkunci khusus untuk akun pemilik.',
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
    installGuideMacSafariStep1: 'Di Safari macOS, buka menu File lalu pilih "Tambahkan ke Dock" untuk memasang tranX sebagai aplikasi penuh.',
    installGuideDesktopStep1: 'Klik ikon "Pasang tranX" di sisi kanan bilah alamat browser (Chrome / Edge / Brave), atau buka menu titik tiga browser lalu pilih "Pasang aplikasi".',
    installGuideDesktopStep2: 'Konfirmasi "Pasang" agar tranX muncul sebagai aplikasi mandiri di desktop atau layar utama HP Anda.',
    readerMenuLabel: 'Menu pembaca',
    shortEbookTab: 'Ebook',
    shortSiteTab: 'Situs',
    shortPrevChapter: 'Sblm',
    shortNextChapter: 'Lanjut',
    closeLabel: 'Tutup',
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
    notOwnerError: 'Access denied. This personal app is locked to the owner account.',
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
    installGuideMacSafariStep1: 'In macOS Safari, open the File menu and choose "Add to Dock" to install tranX as a standalone app.',
    installGuideDesktopStep1: 'Click the Install icon on the right side of the address bar (Chrome / Edge / Brave), or open the browser menu and select "Install app".',
    installGuideDesktopStep2: 'Confirm "Install" to add tranX as a full standalone app on your desktop or home screen.',
    readerMenuLabel: 'Reader menu',
    shortEbookTab: 'Ebook',
    shortSiteTab: 'Site',
    shortPrevChapter: 'Prev',
    shortNextChapter: 'Next',
    closeLabel: 'Close',
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
