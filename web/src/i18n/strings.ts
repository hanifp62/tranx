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
  openOriginalUntranslated: string;
  readerModeTab: string;
  translatedSiteTab: string;
  bilingualToggle: string;
  novelDetectedBadge: string;
  prevChapter: string;
  nextChapter: string;
  chapterListBtn: string;
  loadingNextChapter: string;
  webToolsBtn: string;
  webToolsTitle: string;
  webToolsSubtitle: string;
  bookmarkletTitle: string;
  bookmarkletHint: string;
  copyBookmarklet: string;
  bookmarkletCopied: string;
  mobileShareTitle: string;
  mobileShareHint: string;
  urlPrefixTitle: string;
  urlPrefixHint: string;
  iosShortcutTitle: string;
  iosShortcutHint: string;
  copyTemplate: string;
  noChaptersFound: string;
  openTocSite: string;
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
    openOriginalUntranslated: 'Tab asli (tanpa terjemahan)',
    readerModeTab: 'Mode Baca',
    translatedSiteTab: 'Situs Terjemahan',
    bilingualToggle: 'Berdampingan',
    novelDetectedBadge: 'Novel terdeteksi',
    prevChapter: 'Bab sebelumnya',
    nextChapter: 'Bab berikutnya',
    chapterListBtn: 'Daftar bab',
    loadingNextChapter: 'Memuat bab berikutnya...',
    webToolsBtn: 'Alat Web & HP',
    webToolsTitle: 'Alat Terjemahan Otomatis (Desktop & HP)',
    webToolsSubtitle: 'Terjemahkan situs web dan bab novel otomatis di desktop maupun HP tanpa memasang ekstensi.',
    bookmarkletTitle: '1. Bookmarklet 1-Ketuk (Safari iOS, Chrome HP & Desktop)',
    bookmarkletHint: 'Di desktop, tarik tombol di bawah ke bilah bookmark. Di HP (iPhone/Android), salin skrip lalu tempel pada kolom URL bookmark browser Anda; ketuk bookmark tersebut saat membuka situs novel.',
    copyBookmarklet: 'Salin skrip bookmarklet',
    bookmarkletCopied: 'Skrip bookmarklet disalin',
    mobileShareTitle: '2. Bagikan Langsung dari Browser HP (PWA Share Target)',
    mobileShareHint: 'Pasang tranX ke Layar Utama (Add to Home Screen). Saat membaca novel di Chrome HP, ketuk Bagikan lalu pilih tranX untuk langsung membuka terjemahan otomatis.',
    urlPrefixTitle: '3. Awalan URL Cepat (/r/)',
    urlPrefixHint: 'Tambahkan awalan berikut di depan alamat situs apa pun pada bilah alamat browser:',
    iosShortcutTitle: '4. Templat iOS Shortcuts (Safari iPhone/iPad)',
    iosShortcutHint: 'Buat Pintasan Safari dengan aksi Buka URL menggunakan templat ini agar tersedia di menu Share iOS:',
    copyTemplate: 'Salin templat',
    noChaptersFound: 'Daftar bab belum tersedia pada halaman ini. Gunakan tombol Bab sebelumnya / Bab berikutnya.',
    openTocSite: 'Buka halaman daftar isi (terjemahan)',
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
    openOriginalUntranslated: 'Original tab (untranslated)',
    readerModeTab: 'Reader',
    translatedSiteTab: 'Translated Site',
    bilingualToggle: 'Side by side',
    novelDetectedBadge: 'Novel detected',
    prevChapter: 'Previous chapter',
    nextChapter: 'Next chapter',
    chapterListBtn: 'Chapters',
    loadingNextChapter: 'Loading next chapter...',
    webToolsBtn: 'Web & Mobile tools',
    webToolsTitle: 'Auto-Translate Tools (Desktop & Mobile)',
    webToolsSubtitle: 'Auto-translate web pages and novel chapters on desktop and phone browsers without browser extensions.',
    bookmarkletTitle: '1. One-Tap Bookmarklet (iOS Safari, Mobile Chrome & Desktop)',
    bookmarkletHint: 'On desktop, drag the button below to your bookmarks bar. On mobile, copy the script and save it as a bookmark URL; open any novel page and tap this bookmark to translate immediately.',
    copyBookmarklet: 'Copy bookmarklet script',
    bookmarkletCopied: 'Bookmarklet script copied',
    mobileShareTitle: '2. Share Directly from Phone Browser (PWA Share Target)',
    mobileShareHint: 'Install tranX to your Home Screen. While reading a novel in mobile Chrome, tap Share and choose tranX to open the translated chapter automatically.',
    urlPrefixTitle: '3. Instant URL Prefix (/r/)',
    urlPrefixHint: 'Prepend this prefix before any webpage address in your browser bar:',
    iosShortcutTitle: '4. iOS Shortcuts Template (iPhone / iPad Safari)',
    iosShortcutHint: 'Create an Apple Shortcut with Open URLs using this template to launch auto-translation from the iOS Share Sheet:',
    copyTemplate: 'Copy template',
    noChaptersFound: 'Chapter list was not embedded on this page. Use Previous / Next chapter controls.',
    openTocSite: 'Open translated table of contents',
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
