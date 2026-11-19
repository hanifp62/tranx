import {
  Suspense,
  lazy,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { STRINGS, labelForLang } from './i18n/strings';
import type {
  AppSettingsDoc,
  ConversationDoc,
  InboxItem,
  JobDoc,
  ModePair,
  PendingAttachment,
  ResolvedTheme,
  SourceLang,
  TargetLang,
  TitleDoc,
  ToastItem,
  TurnMessage,
  UiLang,
  WorkTab,
} from './types';
import {
  DEFAULT_SETTINGS,
  dismissInboxItemBridge,
  loginWithCustomPairToken,
  loginWithGoogleOwner,
  logoutSession,
  normalizeModePair,
  processDocumentSubmission,
  renameConversationTitle,
  requestStopJob,
  subscribeAuth,
  subscribeConversations,
  subscribeInbox,
  subscribeJobs,
  subscribeMessages,
  subscribeSettings,
  subscribeTitles,
  toggleConversationPin,
  updateAppSettings,
  upsertConversationMeta,
  upsertUserGlossaryEntry,
  type AuthSessionUser,
} from './lib/firebaseBridge';
import {
  deleteConversationRemote,
  downloadExportedTurn,
  humanizeFetchError,
  lookupTurnNames,
  previewLinkRequest,
  redeemPairCodeRequest,
  resumeInterruptedTurn,
  streamChatTurn,
  translateImageRequest,
} from './lib/api';
import {
  buildAutoTranslatedSiteUrl,
  buildModePair,
  detectLanguageLocal,
  isSingleStandaloneUrl,
  parseModePair,
  prefetchNextChapterTranslatedDirect,
  swapModePair,
  toSafeHttpUrl,
  translateChapterTitlesDirect,
  validateUploadedFileMagic,
} from './lib/directEngine';
import { startVoiceDictation, type DictationHandle } from './lib/speech';
import {
  BrandAppTile,
  BrandWordmark,
  IconAlert,
  IconArrowUp,
  IconArrowsSwitch,
  IconBook,
  IconCamera,
  IconCheck,
  IconChevronDown,
  IconColumns,
  IconCopy,
  IconDots,
  IconDownload,
  IconEdit,
  IconFileText,
  IconFolder,
  IconGlobe,
  IconHelp,
  IconInfo,
  IconKeyboard,
  IconLink,
  IconLogout,
  IconMail,
  IconMenu,
  IconMic,
  IconPhoto,
  IconPin,
  IconPinOff,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconSettings,
  IconShare,
  IconSidebarCollapse,
  IconStop,
  IconText,
  IconTrash,
  IconX,
} from './components/Icons';
const ImageResultCard = lazy(() =>
  import('./components/ImageOverlayCanvas').then((m) => ({ default: m.ImageResultCard }))
);
const InfoModal = lazy(() =>
  import('./components/Modals').then((m) => ({ default: m.InfoModal }))
);
const LogoutDialog = lazy(() =>
  import('./components/Modals').then((m) => ({ default: m.LogoutDialog }))
);
const RenameDialog = lazy(() =>
  import('./components/Modals').then((m) => ({ default: m.RenameDialog }))
);
const SettingsModal = lazy(() =>
  import('./components/Modals').then((m) => ({ default: m.SettingsModal }))
);
const ShortcutsModal = lazy(() =>
  import('./components/Modals').then((m) => ({ default: m.ShortcutsModal }))
);
const GlossaryView = lazy(() =>
  import('./components/SubViews').then((m) => ({ default: m.GlossaryView }))
);
const MyFilesView = lazy(() =>
  import('./components/SubViews').then((m) => ({ default: m.MyFilesView }))
);
const SideBySideReaderView = lazy(() =>
  import('./components/SubViews').then((m) => ({ default: m.SideBySideReaderView }))
);
const TranslatedWebViewer = lazy(() =>
  import('./components/SubViews').then((m) => ({ default: m.TranslatedWebViewer }))
);

const SUPPORTED_DOC_EXTS = new Set([
  'epub',
  'pdf',
  'docx',
  'srt',
  'vtt',
  'ass',
  'ssa',
  'html',
  'htm',
  'xhtml',
  'md',
  'txt',
]);
const SUPPORTED_IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'webp']);

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Gagal membaca berkas gambar.'));
    reader.readAsDataURL(file);
  });
}

export function App() {
  const [routePath, setRoutePath] = useState<string>(
    () => window.location.pathname + window.location.search
  );
  const [isMobile, setIsMobile] = useState<boolean>(() => window.innerWidth < 768);
  const [isOnline, setIsOnline] = useState<boolean>(() => navigator.onLine);

  const [authReady, setAuthReady] = useState(false);
  const [user, setUser] = useState<AuthSessionUser | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [pairCodeInput, setPairCodeInput] = useState('');
  const [pairError, setPairError] = useState<string | null>(null);

  const [settings, setSettings] = useState<AppSettingsDoc>(DEFAULT_SETTINGS);
  const [systemDark, setSystemDark] = useState<boolean>(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  );

  const [conversations, setConversations] = useState<ConversationDoc[]>([]);
  const [messages, setMessages] = useState<TurnMessage[]>([]);
  const [streamingTurn, setStreamingTurn] = useState<TurnMessage | null>(null);
  const [titles, setTitles] = useState<TitleDoc[]>([]);
  const [jobs, setJobs] = useState<JobDoc[]>([]);
  const [inboxItems, setInboxItems] = useState<InboxItem[]>([]);

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const [activeMode, setActiveMode] = useState<ModePair>('auto-id');
  const [lastDetectedSource, setLastDetectedSource] = useState<TargetLang | ''>('');
  const [swapFlipped, setSwapFlipped] = useState(false);

  const [activeTab, setActiveTab] = useState<WorkTab>('teks');
  const [composerText, setComposerText] = useState('');
  const [linkUrlInput, setLinkUrlInput] = useState('');
  const [isFetchingLink, setIsFetchingLink] = useState(false);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [isSubmittingAttachment, setIsSubmittingAttachment] = useState(false);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [uploadPct, setUploadPct] = useState<number | null>(null);

  const [isDictating, setIsDictating] = useState(false);
  const [dictationSeconds, setDictationSeconds] = useState(0);
  const [dictationBars, setDictationBars] = useState<number[]>([6, 12, 9, 14, 7]);
  const dictationRef = useRef<DictationHandle | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  /* Floating Glass Menu / Sheet State (strictly <= 1 floating menu open at once -> R-10 dose cap) */
  const [langPickerSide, setLangPickerSide] = useState<'source' | 'target' | null>(null);
  const [langMenuRect, setLangMenuRect] = useState<DOMRect | null>(null);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [moreMenuRect, setMoreMenuRect] = useState<DOMRect | null>(null);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [accountMenuRect, setAccountMenuRect] = useState<DOMRect | null>(null);
  const [historyMenuTarget, setHistoryMenuTarget] = useState<{
    conv: ConversationDoc;
    rect: DOMRect | null;
  } | null>(null);
  const [mobileTurnSheet, setMobileTurnSheet] = useState<TurnMessage | null>(null);

  /* Modals */
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ConversationDoc | null>(null);
  const [infoModalKind, setInfoModalKind] = useState<'help' | 'about' | null>(null);
  const [inlineChaptersNav, setInlineChaptersNav] = useState<{
    nav: import('./types').NovelNavigation;
    mode: ModePair;
    titleId?: string;
  } | null>(null);
  const [inlineChapterQuery, setInlineChapterQuery] = useState('');
  const [inlineTranslatedTitles, setInlineTranslatedTitles] = useState<Record<string, string>>({});

  /* Source bubble expand & inline edit */
  const [expandedBubbles, setExpandedBubbles] = useState<Record<string, boolean>>({});
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null);
  const [editingDraft, setEditingDraft] = useState('');

  /* Reversible Toast */
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const cameraInputRef = useRef<HTMLInputElement | null>(null);
  const docInputRef = useRef<HTMLInputElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  const closeAllPopovers = useCallback(() => {
    setMoreMenuOpen(false);
    setAccountMenuOpen(false);
    setLangPickerSide(null);
    setHistoryMenuTarget(null);
  }, []);

  const navigate = useCallback(
    (nextPath: string) => {
      if (window.location.pathname + window.location.search !== nextPath) {
        window.history.pushState({}, '', nextPath);
      }
      setRoutePath(nextPath);
      setMobileDrawerOpen(false);
      closeAllPopovers();
    },
    [closeAllPopovers]
  );

  const pushToast = useCallback(
    (message: string, undoLabel?: string, onUndo?: () => void) => {
      const id = `tst_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
      setToasts((prev) => [...prev.slice(-2), { id, message, undoLabel, onUndo }]);
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 4500);
    },
    []
  );

  const parsedUrl = useMemo(() => new URL(routePath, window.location.origin), [routePath]);
  const pathname = parsedUrl.pathname;
  const lastNonWebPathRef = useRef<string>('/');
  if (
    pathname !== '/web' &&
    pathname !== '/share' &&
    !pathname.startsWith('/r/') &&
    !pathname.startsWith('/masuk')
  ) {
    lastNonWebPathRef.current = routePath;
  }
  const activeCid = useMemo(() => {
    const match = pathname.match(/^\/c\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }, [pathname]);
  const readerMatch = useMemo(() => {
    const m = pathname.match(/^\/c\/([^/]+)\/m\/([^/]+)\/baca$/);
    return m ? { cid: decodeURIComponent(m[1]), mid: decodeURIComponent(m[2]) } : null;
  }, [pathname]);
  const kamusMatch = useMemo(() => {
    const m = pathname.match(/^\/kamus(?:\/([^/]+))?$/);
    return m ? { titleId: m[1] ? decodeURIComponent(m[1]) : undefined } : null;
  }, [pathname]);

  const resolvedTheme: ResolvedTheme = useMemo(() => {
    if (settings.theme === 'dark') return 'Gelap';
    if (settings.theme === 'light') return 'Terang';
    return systemDark ? 'Gelap' : 'Terang';
  }, [settings.theme, systemDark]);

  useEffect(() => {
    const root = document.documentElement;
    if (resolvedTheme === 'Gelap') {
      root.setAttribute('data-tranx-v3', 'Gelap');
    } else {
      root.removeAttribute('data-tranx-v3');
    }
    root.lang = settings.uiLang;
  }, [resolvedTheme, settings.uiLang]);

  const strings = STRINGS[settings.uiLang];

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    const onPop = () => setRoutePath(window.location.pathname + window.location.search);
    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    const onMq = (e: MediaQueryListEvent) => setSystemDark(e.matches);

    window.addEventListener('resize', onResize);
    window.addEventListener('popstate', onPop);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    mq?.addEventListener?.('change', onMq);

    const vv = window.visualViewport;
    const onVv = () => {
      if (!vv) return;
      const kbOffset = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      document.documentElement.style.setProperty('--dur-kb-offset', `${kbOffset}px`);
    };
    vv?.addEventListener('resize', onVv);

    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('popstate', onPop);
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
      mq?.removeEventListener?.('change', onMq);
      vv?.removeEventListener('resize', onVv);
    };
  }, []);

  useEffect(() => {
    return subscribeAuth((u, err) => {
      setUser(u);
      setAuthError(err);
      setAuthReady(true);
    });
  }, []);

  useEffect(() => {
    if (!user) return;
    let prevDefPair = '';
    const unsubs = [
      subscribeSettings((s) => {
        setSettings(s);
        const nextDefPair = `${s.defaultSource}-${s.defaultTarget}`;
        if (nextDefPair !== prevDefPair) {
          prevDefPair = nextDefPair;
          if (!window.location.pathname.startsWith('/c/')) {
            setActiveMode(buildModePair(s.defaultSource, s.defaultTarget));
          }
        }
      }),
      subscribeConversations(setConversations),
      subscribeTitles(setTitles),
      subscribeJobs(setJobs),
      subscribeInbox(setInboxItems),
    ];
    return () => unsubs.forEach((u) => u());
  }, [user]);

  useEffect(() => {
    if (!user || !activeCid) {
      setMessages([]);
      return;
    }
    return subscribeMessages(activeCid, setMessages);
  }, [user, activeCid]);

  useEffect(() => {
    const qTab = parsedUrl.searchParams.get('tab');
    if (qTab && ['teks', 'gambar', 'dokumen', 'link'].includes(qTab)) {
      setActiveTab(qTab as WorkTab);
    }

    // Preserve deep-link / bookmarklet / share route ONLY when genuinely unauthenticated
    if (!authReady) return;
    if (!user) {
      if (pathname === '/web' || pathname === '/share' || pathname.startsWith('/r/')) {
        window.sessionStorage.setItem('tranx_post_login_path', routePath);
      }
      return;
    }

    const pendingPostLogin = window.sessionStorage.getItem('tranx_post_login_path');
    if (pendingPostLogin) {
      window.sessionStorage.removeItem('tranx_post_login_path');
      if ((pathname === '/' || pathname === '/masuk') && pendingPostLogin !== routePath) {
        navigate(pendingPostLogin);
        return;
      }
    }

    // Instant URL prefix shortcut: /r/https://kakuyomu.jp/... or /r/kakuyomu.jp/...
    if (pathname.startsWith('/r/') && pathname.length > 3) {
      const rawTail = decodeURIComponent(pathname.slice(3)) + parsedUrl.search;
      const safeUrl = toSafeHttpUrl(rawTail);
      if (safeUrl) {
        navigate(
          `/web?url=${encodeURIComponent(safeUrl)}&mode=${encodeURIComponent(activeMode)}&view=reader`
        );
      } else {
        setActiveTab('link');
        setLinkUrlInput(rawTail);
        navigate('/?tab=link');
      }
      return;
    }

    // Mobile PWA Share Target: auto-translate shared URLs in 1 tap (handles Android Chrome sending URL in text!)
    if (pathname === '/share') {
      const rawSharedUrl = (parsedUrl.searchParams.get('url') || '').trim();
      const rawSharedText = (parsedUrl.searchParams.get('text') || '').trim();
      const extractedUrl =
        toSafeHttpUrl(rawSharedUrl) ||
        toSafeHttpUrl((rawSharedText.match(/https?:\/\/[^\s]+/i) || [''])[0]);
      if (extractedUrl) {
        navigate(
          `/web?url=${encodeURIComponent(extractedUrl)}&mode=${encodeURIComponent(activeMode)}&view=reader`
        );
      } else if (rawSharedText) {
        setActiveTab('teks');
        setComposerText(rawSharedText);
        navigate('/');
      } else {
        navigate('/');
      }
    }
  }, [pathname, parsedUrl, routePath, authReady, user, activeMode, navigate]);

  useEffect(() => {
    if (window.launchQueue) {
      window.launchQueue.setConsumer(async (params) => {
        if (!params.files.length) return;
        const files: File[] = [];
        for (const handle of params.files) {
          files.push(await handle.getFile());
        }
        if (files.length) {
          setActiveTab('dokumen');
          handleStageFiles(files, 'dokumen');
          navigate('/');
        }
      });
    }
  }, [navigate]);

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeCid) || null,
    [conversations, activeCid]
  );

  const prevSyncedCidRef = useRef<string>('');
  useEffect(() => {
    if (activeConversation && activeConversation.id !== prevSyncedCidRef.current) {
      prevSyncedCidRef.current = activeConversation.id;
      setActiveMode(activeConversation.mode);
      setActiveTab(activeConversation.activeTab || 'teks');
      if (activeConversation.detectedSource) {
        setLastDetectedSource(activeConversation.detectedSource);
      }
    } else if (!activeCid) {
      prevSyncedCidRef.current = '';
    }
  }, [activeConversation, activeCid]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSidebarCollapsed(false);
        setSearchOpen(true);
        window.setTimeout(() => searchInputRef.current?.focus(), 40);
      } else if (mod && e.key === ',') {
        e.preventDefault();
        if (user) setSettingsOpen(true);
      } else if (mod && e.key === '/') {
        e.preventDefault();
        setShortcutsOpen((v) => !v);
      } else if (mod && e.shiftKey && e.key.toLowerCase() === 'c') {
        const lastAsst = [...messages].reverse().find((m) => m.role === 'assistant');
        if (lastAsst?.text) {
          e.preventDefault();
          navigator.clipboard?.writeText(lastAsst.text);
          pushToast(strings.copiedToast);
        }
      } else if (e.key === 'Escape') {
        setLangPickerSide(null);
        setMoreMenuOpen(false);
        setAccountMenuOpen(false);
        setHistoryMenuTarget(null);
        setMobileTurnSheet(null);
        setMobileDrawerOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [user, messages, pushToast, strings.copiedToast]);

  useEffect(() => {
    if (!isDictating) {
      setDictationSeconds(0);
      return;
    }
    const id = window.setInterval(() => setDictationSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [isDictating]);

  const deferredSearchQuery = useDeferredValue(searchQuery);
  const deferredInlineChapterQuery = useDeferredValue(inlineChapterQuery);

  const { pinnedList, recentList } = useMemo(() => {
    const q = deferredSearchQuery.trim().toLowerCase();
    const filtered = q
      ? conversations.filter(
          (c) =>
            c.title.toLowerCase().includes(q) || c.preview.toLowerCase().includes(q)
        )
      : conversations;
    const pinned = filtered
      .filter((c) => c.pinned)
      .sort((a, b) => (b.pinnedAt || 0) - (a.pinnedAt || 0));
    const recent = filtered
      .filter((c) => !c.pinned)
      .sort((a, b) => b.updatedAt - a.updatedAt);
    return { pinnedList: pinned, recentList: recent };
  }, [conversations, deferredSearchQuery]);

  const { src: currentSrcLang, tgt: currentTgtLang } = useMemo(
    () => parseModePair(activeMode),
    [activeMode]
  );

  const liveDetectedLang: TargetLang | '' = useMemo(() => {
    if (currentSrcLang !== 'auto') return '';
    if (composerText.trim().length >= 3) {
      return detectLanguageLocal(
        composerText,
        currentTgtLang === 'ja' ? 'id' : 'ja'
      );
    }
    return lastDetectedSource;
  }, [currentSrcLang, currentTgtLang, composerText, lastDetectedSource]);

  const displayedMessages = useMemo(() => {
    if (!streamingTurn) return messages;
    const exists = messages.some((m) => m.id === streamingTurn.id);
    return exists ? messages : [...messages, streamingTurn];
  }, [messages, streamingTurn]);

  const modeMessages = useMemo(
    () =>
      displayedMessages.filter((turn) => {
        if (activeTab === 'gambar') return turn.kind === 'image';
        if (activeTab === 'dokumen') return turn.kind === 'document';
        if (activeTab === 'link') {
          return turn.kind === 'link' || Boolean(streamingTurn && turn.id === streamingTurn.id);
        }
        return (
          turn.role === 'user' ||
          !turn.kind ||
          turn.kind === 'text' ||
          turn.kind === 'long'
        );
      }),
    [displayedMessages, activeTab, streamingTurn]
  );

  const applyModeChange = useCallback(
    (nextMode: ModePair) => {
      setActiveMode(nextMode);
      setLangPickerSide(null);
      if (activeConversation) {
        upsertConversationMeta(activeConversation.id, {
          title: activeConversation.title,
          titleId: activeConversation.titleId,
          mode: nextMode,
          activeTab,
          pinned: activeConversation.pinned,
          pinnedAt: activeConversation.pinnedAt,
        });
      }
    },
    [activeConversation, activeTab]
  );

  const handleSelectSourceLang = (src: SourceLang) => {
    const next = buildModePair(src, currentTgtLang, activeMode);
    applyModeChange(next);
  };

  const handleSelectTargetLang = (tgt: TargetLang) => {
    const next = buildModePair(currentSrcLang, tgt, activeMode);
    applyModeChange(next);
  };

  const handleSwapLanguages = () => {
    setSwapFlipped((f) => !f);
    const swapped = swapModePair(activeMode, liveDetectedLang || lastDetectedSource);
    applyModeChange(swapped);
  };

  const handleStageFiles = (fileList: FileList | File[], targetTab: WorkTab) => {
    const arr = Array.from(fileList);
    const kind: 'gambar' | 'dokumen' = targetTab === 'gambar' ? 'gambar' : 'dokumen';
    const next: PendingAttachment[] = arr.map((f, idx) => {
      const ext = (f.name.split('.').pop() || '').toLowerCase();
      const maxBytes = settings.maxUploadMb * 1024 * 1024;
      const attId = `att_${Date.now()}_${idx}_${f.name}`;
      if (f.size > maxBytes) {
        return {
          id: attId,
          file: f,
          name: f.name,
          sizeBytes: f.size,
          ext,
          status: 'error',
          reason: `Ukuran berkas melebihi batas ${settings.maxUploadMb} MB.`,
        };
      }
      const allowed = targetTab === 'gambar' ? SUPPORTED_IMAGE_EXTS : SUPPORTED_DOC_EXTS;
      if (!allowed.has(ext)) {
        return {
          id: attId,
          file: f,
          name: f.name,
          sizeBytes: f.size,
          ext,
          status: 'error',
          reason:
            targetTab === 'gambar'
              ? `Format .${ext || 'berkas'} tidak didukung. Gunakan .png, .jpg, atau .webp.`
              : `Format .${ext || 'berkas'} tidak didukung. Pilih .epub, .pdf, .docx, .srt, .vtt, .ass, .html, .md, atau .txt.`,
        };
      }
      return {
        id: attId,
        file: f,
        name: f.name,
        sizeBytes: f.size,
        ext,
        status: 'ready',
      };
    });
    setAttachments((prev) => [...prev, ...next]);

    for (const item of next) {
      if (item.status === 'ready' && item.file) {
        void validateUploadedFileMagic(item.file, kind).then((magicErr) => {
          if (magicErr) {
            setAttachments((prev) =>
              prev.map((a) =>
                a.id === item.id ? { ...a, status: 'error', reason: magicErr } : a
              )
            );
          }
        });
      }
    }
  };

  const handleChangeUiLang = async (nextLang: UiLang) => {
    const prevLang = settings.uiLang;
    if (prevLang === nextLang) return;
    await updateAppSettings({ uiLang: nextLang });
    setAccountMenuOpen(false);
    pushToast(STRINGS[nextLang].langChangedToast, STRINGS[nextLang].undo, () => {
      updateAppSettings({ uiLang: prevLang });
    });
  };

  const handleTogglePin = async (conv: ConversationDoc) => {
    const nextPinned = !conv.pinned;
    setHistoryMenuTarget(null);
    await toggleConversationPin(conv, nextPinned);
    pushToast(
      nextPinned ? strings.pinnedToast : strings.unpinnedToast,
      strings.undo,
      () => {
        toggleConversationPin(conv, !nextPinned);
      }
    );
  };

  const handleShareConversation = async (conv: ConversationDoc) => {
    setHistoryMenuTarget(null);
    const shareUrl = `${window.location.origin}/c/${conv.id}`;
    const text = `${conv.title}\n${conv.preview}\n${shareUrl}`;
    if (navigator.share) {
      await navigator
        .share({ title: conv.title, text: conv.preview, url: shareUrl })
        .catch(() => {});
    } else {
      await navigator.clipboard?.writeText(text);
      pushToast(strings.copiedToast);
    }
  };

  const handleDeleteConversation = async (conv: ConversationDoc) => {
    if (!user) return;
    setHistoryMenuTarget(null);
    await deleteConversationRemote(user, conv.id);
    if (activeCid === conv.id) navigate('/');
    pushToast(strings.deletedToast);
  };

  const handleSelectWorkTab = useCallback(
    (nextTab: WorkTab) => {
      closeAllPopovers();
      if (isDictating) {
        dictationRef.current?.stop();
        setIsDictating(false);
      }
      setAttachments([]);
      setStreamingTurn(null);
      setActiveTab(nextTab);

      const convTab: WorkTab = activeConversation?.activeTab || 'teks';
      if (activeCid && convTab !== nextTab) {
        setComposerText('');
        setLinkUrlInput('');
        navigate(nextTab === 'teks' ? '/' : `/?tab=${nextTab}`);
        return;
      }
      if (!activeCid) {
        navigate(nextTab === 'teks' ? '/' : `/?tab=${nextTab}`);
      }
    },
    [activeCid, activeConversation, closeAllPopovers, isDictating, navigate]
  );

  useEffect(() => {
    if (activeTab !== 'gambar') return;
    const onGlobalPaste = (e: ClipboardEvent) => {
      const files = e.clipboardData?.files;
      if (files && files.length > 0 && files[0].type.startsWith('image/')) {
        e.preventDefault();
        handleStageFiles([files[0]], 'gambar');
      }
    };
    window.addEventListener('paste', onGlobalPaste);
    return () => window.removeEventListener('paste', onGlobalPaste);
  }, [activeTab]);

  /* Submit Link Preview (L5 / H7): works both from Link tab and standalone URLs in Teks */
  const handleSubmitLink = async (e?: React.FormEvent, explicitUrl?: string) => {
    e?.preventDefault();
    if (!user || isFetchingLink) return;
    const rawUrl = (explicitUrl ?? (linkUrlInput || composerText)).trim();
    if (!rawUrl) return;

    const reuseCid =
      activeCid && (!activeConversation || activeConversation.activeTab === 'link');
    const cid = reuseCid ? activeCid : `c_${Date.now().toString(36)}`;
    const tempId = `lnk_wait_${Date.now().toString(36)}`;
    prevSyncedCidRef.current = cid;
    setActiveTab('link');
    setLinkUrlInput('');
    if (!explicitUrl) setComposerText('');
    setIsFetchingLink(true);
    if (activeCid !== cid) navigate(`/c/${cid}`);

    setStreamingTurn({
      id: tempId,
      role: 'assistant',
      kind: 'text',
      mode: activeMode,
      text: strings.loadingWebPage,
      state: 'running',
      createdAt: Date.now(),
    });

    try {
      await previewLinkRequest({
        user,
        cid,
        url: rawUrl,
        mode: activeMode,
        titleId: reuseCid ? activeConversation?.titleId || undefined : undefined,
      });
      setStreamingTurn(null);
    } catch (err) {
      const msg = humanizeFetchError(
        err,
        'Halaman web tersebut menolak pembacaan otomatis atau sedang tidak terjangkau.'
      );
      setStreamingTurn({
        id: tempId,
        role: 'assistant',
        kind: 'text',
        mode: activeMode,
        srcText: rawUrl,
        text: '',
        state: 'error',
        error: msg,
        createdAt: Date.now(),
      });
      pushToast(msg);
    } finally {
      setIsFetchingLink(false);
    }
  };

  /* Send Text Turn */
  const handleSendText = async (overrideText?: string, inboxId?: string) => {
    if (!user) return;
    const raw = (overrideText ?? composerText).trim();
    if (!raw) return;

    // If the user pasted a single standalone http(s):// URL directly into chat, treat it as a web link!
    if (isSingleStandaloneUrl(raw) && !inboxId) {
      if (!overrideText) setComposerText('');
      await handleSubmitLink(undefined, raw);
      return;
    }

    const reuseCid =
      activeCid && (!activeConversation || (activeConversation.activeTab || 'teks') === 'teks');
    const cid = reuseCid ? activeCid : `c_${Date.now().toString(36)}`;
    const clientMsgId = `m_${Date.now().toString(36)}_u`;
    const asstId = `${clientMsgId}_r`;
    const titleId = reuseCid ? activeConversation?.titleId || undefined : undefined;

    prevSyncedCidRef.current = cid;
    setActiveTab('teks');
    if (!overrideText) setComposerText('');
    if (activeCid !== cid) navigate(`/c/${cid}`);

    const abort = new AbortController();
    streamAbortRef.current = abort;

    setStreamingTurn({
      id: asstId,
      role: 'assistant',
      kind: raw.length > settings.chatMaxChars ? 'long' : 'text',
      mode: activeMode,
      srcText: raw,
      text: '',
      state: 'running',
      createdAt: Date.now(),
    });

    try {
      let finalMid = asstId;
      let finalTid = titleId || '';
      await streamChatTurn({
        user,
        cid,
        clientMsgId,
        mode: activeMode,
        text: raw,
        titleId,
        inboxId,
        signal: abort.signal,
        onEvent: (ev) => {
          if (ev.mid) finalMid = ev.mid;
          if (ev.titleId) finalTid = ev.titleId;
          if (ev.detectedSource) setLastDetectedSource(ev.detectedSource);
          if ((ev.type === 'delta' || ev.type === 'seg') && ev.dst) {
            setStreamingTurn((prev) =>
              prev
                ? {
                    ...prev,
                    id: finalMid,
                    detectedSource: ev.detectedSource || prev.detectedSource,
                    text: prev.text ? `${prev.text}\n${ev.dst}` : ev.dst || '',
                  }
                : null
            );
          } else if (ev.type === 'para') {
            setStreamingTurn((prev) =>
              prev
                ? {
                    ...prev,
                    text: prev.text ? `${prev.text}\n\n${ev.dst || ''}` : ev.dst || '',
                    done: ev.doneParas,
                    total: ev.totalParas,
                  }
                : null
            );
          } else if (ev.type === 'done') {
            setStreamingTurn((prev) =>
              prev
                ? {
                    ...prev,
                    id: finalMid,
                    titleId: finalTid,
                    detectedSource: ev.detectedSource || prev.detectedSource,
                    text: ev.fullDst || prev.text,
                    sentences: ev.sentences,
                    state: 'done',
                    model: ev.model,
                    ms: ev.ms,
                  }
                : null
            );
          } else if (ev.type === 'error') {
            setStreamingTurn((prev) =>
              prev
                ? {
                    ...prev,
                    state: ev.code === 'DAILY_CAP_REACHED' ? 'busy' : 'error',
                    error: ev.message || 'Terjemahan terhenti.',
                  }
                : null
            );
          }
        },
      });

      lookupTurnNames({
        user,
        cid,
        mid: finalMid,
        titleId: finalTid,
        text: raw,
        mode: activeMode,
      }).catch(() => {});
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') {
        setStreamingTurn((prev) => (prev ? { ...prev, state: 'stopped' } : null));
      } else {
        setStreamingTurn((prev) =>
          prev
            ? {
                ...prev,
                state: 'error',
                error: humanizeFetchError(
                  err,
                  'Koneksi jaringan terganggu saat menerjemahkan. Tekan Coba sekarang.'
                ),
              }
            : null
        );
      }
    } finally {
      streamAbortRef.current = null;
      window.setTimeout(() => setStreamingTurn(null), 350);
    }
  };

  const handleSendAttachments = async () => {
    if (!user || isSubmittingAttachment) return;
    const readyItems = attachments.filter((a) => a.status === 'ready' && a.file);
    if (!readyItems.length) return;

    const targetTab: WorkTab = activeTab === 'gambar' ? 'gambar' : 'dokumen';
    const reuseCid =
      activeCid && (!activeConversation || activeConversation.activeTab === targetTab);
    const cid = reuseCid ? activeCid : `c_${Date.now().toString(36)}`;
    prevSyncedCidRef.current = cid;
    if (activeCid !== cid) navigate(`/c/${cid}`);

    setIsSubmittingAttachment(true);
    try {
      for (const item of readyItems) {
        setAttachments((prev) =>
          prev.map((a) => (a.id === item.id ? { ...a, status: 'reading' } : a))
        );
        try {
          if (targetTab === 'gambar' && item.file) {
            const dataUrl = await readFileAsDataUrl(item.file);
            await translateImageRequest({
              user,
              cid,
              mode: activeMode,
              fileName: item.name,
              imageDataUrl: dataUrl,
              titleId: reuseCid ? activeConversation?.titleId || undefined : undefined,
            });
          } else if (item.file) {
            const mid = `doc_${Date.now().toString(36)}`;
            setUploadPct(5);
            await processDocumentSubmission({
              uid: user.uid,
              cid,
              mid,
              mode: activeMode,
              titleId: reuseCid ? activeConversation?.titleId || undefined : undefined,
              file: item.file,
              onProgress: (pct) => setUploadPct(pct),
            });
            setUploadPct(null);
          }
          setAttachments((prev) => prev.filter((a) => a.id !== item.id));
        } catch (err) {
          setUploadPct(null);
          setAttachments((prev) =>
            prev.map((a) =>
              a.id === item.id
                ? {
                    ...a,
                    status: 'error',
                    reason: humanizeFetchError(err, 'Gagal memproses berkas.'),
                  }
                : a
            )
          );
        }
      }
    } finally {
      setIsSubmittingAttachment(false);
    }
  };

  const handleToggleDictation = () => {
    if (!user) return;
    if (isDictating) {
      dictationRef.current?.stop();
      setIsDictating(false);
      return;
    }
    setIsDictating(true);
    dictationRef.current = startVoiceDictation({
      user,
      sourceLang: currentSrcLang,
      detectedLang: liveDetectedLang || lastDetectedSource,
      onInterim: (txt) => setComposerText(txt),
      onLevels: (bars) => setDictationBars(bars),
      onDone: (finalTxt) => {
        setIsDictating(false);
        if (finalTxt) {
          setComposerText((prev) => (prev ? prev : finalTxt));
        }
      },
      onError: (msg) => {
        setIsDictating(false);
        pushToast(msg);
      },
    });
  };

  /* Auth Gate (/masuk & /masuk/kode) */
  if (!authReady) {
    return (
      <div className="auth-screen">
        <div className="auth-card" style={{ alignItems: 'center', textAlign: 'center' }}>
          <BrandAppTile size={48} />
          <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
            Menyiapkan ruang baca tranX...
          </div>
        </div>
      </div>
    );
  }

  if (!user) {
    const isPairRoute = pathname === '/masuk/kode';
    return (
      <main className="auth-screen">
        <div className="auth-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <BrandAppTile size={44} />
            <BrandWordmark />
          </div>

          {authError === 'NOT_OWNER' && (
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
              {strings.notOwnerError}
            </div>
          )}

          {!isPairRoute ? (
            <>
              <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '15px' }}>
                {strings.loginSubtitle}
              </p>
              <button
                type="button"
                className="btn-primary pressable"
                style={{ width: '100%', minHeight: '44px' }}
                onClick={() =>
                  loginWithGoogleOwner().catch((err) =>
                    setPairError(err instanceof Error ? err.message : 'Gagal masuk.')
                  )
                }
              >
                {strings.loginWithGoogle}
              </button>
              <button
                type="button"
                className="btn-secondary pressable"
                style={{ width: '100%', minHeight: '44px' }}
                onClick={() => {
                  setPairError(null);
                  navigate('/masuk/kode');
                }}
              >
                {strings.loginWithPairCode}
              </button>
              {pairError && (
                <div style={{ color: 'var(--danger)', fontSize: '13px' }}>{pairError}</div>
              )}
            </>
          ) : (
            <form
              style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}
              onSubmit={async (e) => {
                e.preventDefault();
                setPairError(null);
                try {
                  const customTok = await redeemPairCodeRequest(pairCodeInput);
                  await loginWithCustomPairToken(customTok);
                  navigate('/');
                } catch (err) {
                  setPairError(
                    err instanceof Error ? err.message : 'Kode pasangan tidak sah.'
                  );
                }
              }}
            >
              <h1 style={{ margin: 0, fontSize: '18px' }}>{strings.pairCodeTitle}</h1>
              <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-muted)' }}>
                {strings.pairCodeHint}
              </p>
              <input
                className="field-input"
                inputMode="numeric"
                maxLength={6}
                placeholder="000000"
                value={pairCodeInput}
                onChange={(e) => setPairCodeInput(e.target.value.replace(/\D/g, ''))}
                aria-label="Kode pasangan 6 angka"
                style={{
                  fontSize: '22px',
                  letterSpacing: '0.25em',
                  textAlign: 'center',
                  fontWeight: 700,
                }}
                required
              />
              {pairError && (
                <div role="alert" style={{ color: 'var(--danger)', fontSize: '13px' }}>
                  {pairError}
                </div>
              )}
              <button
                type="submit"
                className="btn-primary pressable"
                style={{ minHeight: '44px' }}
              >
                {strings.pairSubmit}
              </button>
              <button
                type="button"
                className="btn-secondary pressable"
                style={{ minHeight: '44px' }}
                onClick={() => navigate('/masuk')}
              >
                {strings.backToLogin}
              </button>
            </form>
          )}
        </div>
      </main>
    );
  }

  /* Full-screen Translated Web Viewer (/web?url=...) */
  if (pathname === '/web') {
    const targetUrl = parsedUrl.searchParams.get('url') || '';
    const qMode = normalizeModePair(parsedUrl.searchParams.get('mode'), activeMode);
    const qTid = parsedUrl.searchParams.get('titleId') || undefined;
    const rawView = parsedUrl.searchParams.get('view');
    const qView: 'reader' | 'site' | 'original' =
      rawView === 'site' || rawView === 'original' ? rawView : 'reader';
    return (
      <>
        <Suspense
          fallback={
            <div className="novel-reader-wrap">
              <div className="ebook-skeleton-card">
                <div className="skeleton-line skeleton-meta" />
                <div className="skeleton-line skeleton-title" />
                <div className="skeleton-line" />
              </div>
            </div>
          }
        >
          <TranslatedWebViewer
            user={user}
            url={targetUrl}
            initialMode={qMode}
            initialView={qView}
            titleId={qTid}
            backPath={lastNonWebPathRef.current || '/'}
            strings={strings}
            onNavigate={navigate}
          />
        </Suspense>
        {toasts.length > 0 && (
          <div className="toast-container" role="status" aria-live="polite">
            {toasts.map((t) => (
              <div key={t.id} className="toast-bar">
                <span>{t.message}</span>
              </div>
            ))}
          </div>
        )}
      </>
    );
  }

  const isStageEmpty = !activeCid || modeMessages.length === 0;
  const readyAttachmentCount = attachments.filter((a) => a.status === 'ready').length;
  const canSendNow =
    activeTab === 'teks'
      ? composerText.trim().length > 0
      : activeTab === 'link'
        ? linkUrlInput.trim().length > 0 && !isFetchingLink
        : readyAttachmentCount > 0 && !isSubmittingAttachment;

  const numLocale = settings.uiLang === 'en' ? 'en-US' : 'id-ID';

  const sourcePillLabel =
    currentSrcLang === 'auto'
      ? liveDetectedLang
        ? isMobile
          ? `${strings.langAutoShort} (${liveDetectedLang.toUpperCase()})`
          : `${strings.langAutoShort} · ${labelForLang(liveDetectedLang, strings)}`
        : isMobile
          ? strings.langAutoShort
          : strings.langAuto
      : labelForLang(currentSrcLang, strings);

  const targetPillLabel = labelForLang(currentTgtLang, strings);

  const renderStagedAttachmentList = (modeKind: 'gambar' | 'dokumen') => (
    <div className="attachment-list">
      {attachments.map((att) => (
        <div
          key={att.id}
          className={`attachment-chip ${att.status === 'error' ? 'is-error' : ''}`}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
            {att.status === 'error' ? (
              <IconAlert size={20} style={{ color: 'var(--danger)', flexShrink: 0 }} />
            ) : modeKind === 'gambar' ? (
              <IconPhoto size={20} style={{ color: 'var(--accent)', flexShrink: 0 }} />
            ) : (
              <IconFileText size={20} style={{ color: 'var(--accent)', flexShrink: 0 }} />
            )}
            <div style={{ minWidth: 0 }}>
              <div className="attachment-chip-title">{att.name}</div>
              <div className="attachment-chip-sub">
                {att.status === 'error'
                  ? att.reason
                  : att.status === 'reading'
                    ? modeKind === 'gambar'
                      ? strings.readingImageOcr
                      : uploadPct !== null
                        ? `${strings.processingDoc} (${uploadPct}%)`
                        : strings.processingDoc
                    : `${strings.readyToSend} (${(att.sizeBytes / 1024).toFixed(1)} KB)`}
              </div>
            </div>
          </div>
          <button
            type="button"
            className="icon-square-btn"
            disabled={att.status === 'reading'}
            aria-label={`Hapus lampiran ${att.name}`}
            onClick={() => setAttachments((prev) => prev.filter((x) => x.id !== att.id))}
          >
            <IconX size={18} />
          </button>
        </div>
      ))}
    </div>
  );

  const renderComposerAndModeZone = () => (
    <div className="composer-zone-wrapper">
      <div className="composer-slot">
        {activeTab === 'gambar' ? (
          attachments.length > 0 ? (
            <div className="composer-island">
              {renderStagedAttachmentList('gambar')}
              <div className="composer-footer">
                <div className="composer-meta-left">
                  <button
                    type="button"
                    className="btn-secondary pressable"
                    disabled={isSubmittingAttachment}
                    onClick={() => imageInputRef.current?.click()}
                  >
                    <IconPhoto size={16} />
                    {strings.pickImage}
                  </button>
                </div>
                <div className="composer-controls-right">
                  <button
                    type="button"
                    className="btn-primary pressable"
                    disabled={!canSendNow}
                    onClick={() => handleSendAttachments()}
                  >
                    <IconPhoto size={17} />
                    {isSubmittingAttachment
                      ? strings.readingImageOcr
                      : strings.translateImageBtn}
                  </button>
                </div>
              </div>
            </div>
          ) : isStageEmpty ? (
            <div
              className={`task-drop-card ${isDraggingFile ? 'dragging' : ''}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDraggingFile(true);
              }}
              onDragLeave={() => setIsDraggingFile(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDraggingFile(false);
                if (e.dataTransfer.files.length) {
                  handleStageFiles(e.dataTransfer.files, 'gambar');
                }
              }}
            >
              <IconPhoto size={28} />
              <div style={{ fontWeight: 600, fontSize: '16px' }}>{strings.pickImage}</div>
              <div style={{ fontSize: '14px', color: 'var(--text-muted)', maxWidth: '460px' }}>
                {strings.supportedImageHint}
              </div>
              <div
                style={{
                  display: 'flex',
                  gap: '10px',
                  flexWrap: 'wrap',
                  justifyContent: 'center',
                }}
              >
                <button
                  type="button"
                  className="btn-primary pressable"
                  onClick={() => imageInputRef.current?.click()}
                >
                  <IconPhoto size={18} />
                  {isMobile ? strings.pickFromGallery : strings.pickImage}
                </button>
                {isMobile && (
                  <button
                    type="button"
                    className="btn-secondary pressable"
                    onClick={() => cameraInputRef.current?.click()}
                  >
                    <IconCamera size={18} />
                    {strings.takeCameraPhoto}
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div
              className="composer-island"
              style={{
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
              }}
            >
              <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                {strings.supportedImageHint}
              </span>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="btn-primary pressable"
                  onClick={() => imageInputRef.current?.click()}
                >
                  <IconPhoto size={17} />
                  {strings.translateAnotherImage}
                </button>
                {isMobile && (
                  <button
                    type="button"
                    className="btn-secondary pressable"
                    onClick={() => cameraInputRef.current?.click()}
                  >
                    <IconCamera size={17} />
                    {strings.takeCameraPhoto}
                  </button>
                )}
              </div>
            </div>
          )
        ) : activeTab === 'dokumen' ? (
          attachments.length > 0 ? (
            <div className="composer-island">
              {renderStagedAttachmentList('dokumen')}
              {isSubmittingAttachment && uploadPct !== null && (
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${uploadPct}%` }} />
                </div>
              )}
              <div className="composer-footer">
                <div className="composer-meta-left">
                  <button
                    type="button"
                    className="btn-secondary pressable"
                    disabled={isSubmittingAttachment}
                    onClick={() => docInputRef.current?.click()}
                  >
                    <IconFileText size={16} />
                    {strings.addMoreFiles}
                  </button>
                </div>
                <div className="composer-controls-right">
                  <button
                    type="button"
                    className="btn-primary pressable"
                    disabled={!canSendNow}
                    onClick={() => handleSendAttachments()}
                  >
                    <IconFileText size={17} />
                    {isSubmittingAttachment
                      ? strings.processingDoc
                      : strings.translateDocBtn}
                  </button>
                </div>
              </div>
            </div>
          ) : isStageEmpty ? (
            <div
              className={`task-drop-card ${isDraggingFile ? 'dragging' : ''}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDraggingFile(true);
              }}
              onDragLeave={() => setIsDraggingFile(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDraggingFile(false);
                if (e.dataTransfer.files.length) {
                  handleStageFiles(e.dataTransfer.files, 'dokumen');
                }
              }}
            >
              <IconFileText size={28} />
              <div style={{ fontWeight: 600, fontSize: '16px' }}>{strings.pickDocument}</div>
              <div style={{ fontSize: '14px', color: 'var(--text-muted)', maxWidth: '480px' }}>
                {strings.supportedDocHint}
              </div>
              <button
                type="button"
                className="btn-primary pressable"
                onClick={() => docInputRef.current?.click()}
              >
                <IconFileText size={18} />
                {strings.pickDocument}
              </button>
            </div>
          ) : (
            <div
              className="composer-island"
              style={{
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
              }}
            >
              <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                {strings.supportedDocHint}
              </span>
              <button
                type="button"
                className="btn-primary pressable"
                onClick={() => docInputRef.current?.click()}
              >
                <IconFileText size={17} />
                {strings.translateAnotherDoc}
              </button>
            </div>
          )
        ) : activeTab === 'link' ? (
          <form onSubmit={(e) => handleSubmitLink(e)} className="composer-island">
            <label className="field-label">
              <span>{strings.pasteLinkLabel}</span>
              <input
                type="text"
                inputMode="url"
                className="field-input"
                placeholder={strings.composerLinkPlaceholder}
                value={linkUrlInput}
                onChange={(e) => setLinkUrlInput(e.target.value)}
                required
              />
            </label>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '8px',
                flexWrap: 'wrap',
              }}
            >
              <button
                type="button"
                className="btn-secondary pressable"
                disabled={isFetchingLink}
                onClick={async () => {
                  try {
                    const clip = (await navigator.clipboard.readText()).trim();
                    if (clip) {
                      setLinkUrlInput(clip);
                    } else {
                      pushToast('Papan klip masih kosong.');
                    }
                  } catch {
                    pushToast('Tempel URL dengan Cmd/Ctrl+V.');
                  }
                }}
              >
                <IconCopy size={16} />
                {strings.pasteUrlBtn}
              </button>
              <button
                type="submit"
                className="btn-primary pressable"
                disabled={isFetchingLink || !linkUrlInput.trim()}
              >
                <IconLink size={18} />
                {isFetchingLink ? strings.loadingWebPage : strings.translateLinkBtn}
              </button>
            </div>
          </form>
        ) : (
          <div className="composer-island">
            {isDictating ? (
              <div className="dictation-panel" role="status" aria-live="polite">
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div className="dictation-bars" aria-hidden="true">
                    {dictationBars.map((h, idx) => (
                      <span
                        key={idx}
                        className="dictation-bar"
                        style={{ height: `${h}px` }}
                      />
                    ))}
                  </div>
                  <span style={{ fontSize: '14px', fontWeight: 600 }}>
                    {strings.dictationListening} (
                    {String(Math.floor(dictationSeconds / 60)).padStart(2, '0')}:
                    {String(dictationSeconds % 60).padStart(2, '0')})
                  </span>
                </div>
                <button
                  type="button"
                  className="btn-secondary pressable"
                  onClick={handleToggleDictation}
                >
                  {strings.dictationStop}
                </button>
              </div>
            ) : null}

            <textarea
              className="composer-textarea"
              aria-label={strings.composerPlaceholder}
              placeholder={strings.composerPlaceholder}
              value={composerText}
              onChange={(e) => setComposerText(e.target.value)}
              onPaste={(e) => {
                if (e.clipboardData.files.length > 0) {
                  const f = e.clipboardData.files[0];
                  if (f.type.startsWith('image/')) {
                    e.preventDefault();
                    handleSelectWorkTab('gambar');
                    handleStageFiles([f], 'gambar');
                  }
                }
              }}
              onKeyDown={(e) => {
                if (
                  e.key === 'Enter' &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing &&
                  e.keyCode !== 229
                ) {
                  e.preventDefault();
                  if (composerText.trim()) {
                    handleSendText();
                  }
                }
              }}
            />

            <div className="composer-footer">
              <div className="composer-meta-left">
                {composerText.length > 0 && (
                  <span>
                    {composerText.length.toLocaleString(numLocale)} /{' '}
                    {composerText.length <= settings.chatMaxChars
                      ? `${settings.chatMaxChars.toLocaleString(numLocale)} ${strings.fastLimitUnit}`
                      : `${settings.longMaxChars.toLocaleString(numLocale)} ${strings.longLimitUnit}`}
                  </span>
                )}
              </div>

              <div className="composer-controls-right">
                <button
                  type="button"
                  className={`mic-round-btn pressable ${isDictating ? 'active' : ''}`}
                  aria-label={isDictating ? strings.dictationStop : strings.dictationStart}
                  title={strings.dictationStart}
                  onClick={handleToggleDictation}
                >
                  <IconMic size={19} />
                </button>

                {streamingTurn && streamingTurn.state === 'running' ? (
                  <button
                    type="button"
                    className="send-round-btn stopping pressable"
                    aria-label={strings.stop}
                    title={strings.stop}
                    onClick={() => streamAbortRef.current?.abort()}
                  >
                    <IconStop size={18} />
                  </button>
                ) : (
                  <button
                    type="button"
                    className="send-round-btn pressable"
                    aria-label={strings.send}
                    disabled={!canSendNow}
                    onClick={() => handleSendText()}
                  >
                    <IconArrowUp size={19} />
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* K/Bilah mode: Segmented Liquid Glass Capsule (Teks, Gambar, Dokumen, Link) */}
      <div className="mode-bar-slot">
        <div
          className="mode-tray glass-tray-surface"
          role="tablist"
          aria-label="Moda penerjemahan"
        >
          {(
            [
              ['teks', strings.modeText, IconText],
              ['gambar', strings.modeImage, IconPhoto],
              ['dokumen', strings.modeDocument, IconFileText],
              ['link', strings.modeLink, IconLink],
            ] as const
          ).map(([tabId, label, TabIcon]) => (
            <button
              key={tabId}
              type="button"
              role="tab"
              aria-selected={activeTab === tabId}
              className="mode-seg-btn pressable"
              onClick={() => handleSelectWorkTab(tabId)}
            >
              <TabIcon size={17} />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <div
      className="app-shell"
      onDragOver={(e) => {
        e.preventDefault();
      }}
      onDrop={(e) => {
        if (e.dataTransfer.files.length > 0) {
          e.preventDefault();
          const first = e.dataTransfer.files[0];
          const nextTab: WorkTab = first.type.startsWith('image/') ? 'gambar' : 'dokumen';
          handleSelectWorkTab(nextTab);
          handleStageFiles(e.dataTransfer.files, nextTab);
        }
      }}
    >
      <input
        ref={imageInputRef}
        type="file"
        accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
        hidden
        onChange={(e) => {
          if (e.target.files?.length) handleStageFiles(e.target.files, 'gambar');
          e.target.value = '';
        }}
      />
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          if (e.target.files?.length) handleStageFiles(e.target.files, 'gambar');
          e.target.value = '';
        }}
      />
      <input
        ref={docInputRef}
        type="file"
        accept=".epub,.pdf,.docx,.srt,.vtt,.ass,.ssa,.html,.htm,.md,.txt,.rar,.zip"
        hidden
        onChange={(e) => {
          if (e.target.files?.length) handleStageFiles(e.target.files, 'dokumen');
          e.target.value = '';
        }}
      />

      {isMobile && mobileDrawerOpen && (
        <div
          className="scrim-backdrop"
          style={{ zIndex: 52 }}
          onClick={() => setMobileDrawerOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        aria-label="Navigasi riwayat"
        inert={(isMobile && !mobileDrawerOpen) || (!isMobile && sidebarCollapsed) || undefined}
        className={`sidebar ${
          isMobile
            ? mobileDrawerOpen
              ? ''
              : 'mobile-closed'
            : sidebarCollapsed
              ? 'collapsed'
              : ''
        }`}
      >
        <div className="sidebar-top-row">
          <BrandWordmark />
          <button
            type="button"
            className="icon-square-btn pressable"
            aria-label={isMobile ? 'Tutup laci' : 'Lipat panel samping'}
            onClick={() =>
              isMobile ? setMobileDrawerOpen(false) : setSidebarCollapsed(true)
            }
          >
            {isMobile ? <IconX size={18} /> : <IconSidebarCollapse size={18} />}
          </button>
        </div>

        <div className="sidebar-actions">
          <button
            type="button"
            className="sidebar-nav-btn pressable"
            onClick={() => {
              setAttachments([]);
              setComposerText('');
              setLinkUrlInput('');
              setStreamingTurn(null);
              setActiveTab('teks');
              navigate('/');
            }}
          >
            <span className="new-chat-badge">
              <IconPlus size={15} />
            </span>
            <span>{strings.sidebarNew}</span>
          </button>

          <button
            type="button"
            className="sidebar-nav-btn pressable"
            onClick={() => {
              closeAllPopovers();
              setSearchOpen((v) => !v);
              window.setTimeout(() => searchInputRef.current?.focus(), 30);
            }}
          >
            <IconSearch size={18} />
            <span>{strings.sidebarSearch}</span>
          </button>

          <button
            type="button"
            className="sidebar-nav-btn pressable"
            aria-expanded={moreMenuOpen}
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              setAccountMenuOpen(false);
              setLangPickerSide(null);
              setHistoryMenuTarget(null);
              setMoreMenuRect(rect);
              setMoreMenuOpen((v) => !v);
            }}
          >
            <IconDots size={18} />
            <span>{strings.sidebarMore}</span>
          </button>
        </div>

        {searchOpen && (
          <div className="sidebar-search-box">
            <input
              ref={searchInputRef}
              type="search"
              className="sidebar-search-input"
              placeholder={strings.sidebarSearchPlaceholder}
              aria-label={strings.sidebarSearchPlaceholder}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        )}

        <div className="sidebar-history-scroll">
          {pinnedList.length === 0 && recentList.length === 0 ? (
            <div style={{ padding: '8px 10px', fontSize: '13px', color: 'var(--text-muted)' }}>
              {searchQuery.trim() ? strings.noSearchMatch : strings.emptyHistory}
            </div>
          ) : (
            <>
              {pinnedList.length > 0 && (
                <section aria-label={strings.pinnedSection}>
                  <div className="history-section-label">{strings.pinnedSection}</div>
                  <div className="history-list">
                    {pinnedList.map((conv) => (
                      <div
                        key={conv.id}
                        className={`history-row ${activeCid === conv.id ? 'active' : ''}`}
                      >
                        <button
                          type="button"
                          className="history-row-main"
                          onClick={() => navigate(`/c/${conv.id}`)}
                        >
                          <span className="history-pin-icon" aria-hidden="true">
                            <IconPin size={15} />
                          </span>
                          <span className="history-row-title">{conv.title}</span>
                        </button>
                        <button
                          type="button"
                          className="history-dots-btn"
                          aria-label={`Menu riwayat ${conv.title}`}
                          aria-expanded={historyMenuTarget?.conv.id === conv.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            const rect = e.currentTarget.getBoundingClientRect();
                            setMoreMenuOpen(false);
                            setAccountMenuOpen(false);
                            setLangPickerSide(null);
                            setHistoryMenuTarget((prev) =>
                              prev?.conv.id === conv.id ? null : { conv, rect }
                            );
                          }}
                        >
                          <IconDots size={17} />
                        </button>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {recentList.length > 0 && (
                <section aria-label={strings.recentSection}>
                  <div className="history-section-label">{strings.recentSection}</div>
                  <div className="history-list">
                    {recentList.map((conv) => (
                      <div
                        key={conv.id}
                        className={`history-row ${activeCid === conv.id ? 'active' : ''}`}
                      >
                        <button
                          type="button"
                          className="history-row-main"
                          onClick={() => navigate(`/c/${conv.id}`)}
                        >
                          <span className="history-row-title">{conv.title}</span>
                        </button>
                        <button
                          type="button"
                          className="history-dots-btn"
                          aria-label={`Menu riwayat ${conv.title}`}
                          aria-expanded={historyMenuTarget?.conv.id === conv.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            const rect = e.currentTarget.getBoundingClientRect();
                            setMoreMenuOpen(false);
                            setAccountMenuOpen(false);
                            setLangPickerSide(null);
                            setHistoryMenuTarget((prev) =>
                              prev?.conv.id === conv.id ? null : { conv, rect }
                            );
                          }}
                        >
                          <IconDots size={17} />
                        </button>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>

        <div className="sidebar-account-footer">
          <button
            type="button"
            className="account-row-btn pressable"
            aria-expanded={accountMenuOpen}
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              setMoreMenuOpen(false);
              setLangPickerSide(null);
              setHistoryMenuTarget(null);
              setAccountMenuRect(rect);
              setAccountMenuOpen((v) => !v);
            }}
          >
            <span className="account-avatar">
              {(user.displayName || user.email || 'H').slice(0, 1).toUpperCase()}
            </span>
            <span className="account-meta">
              <div className="account-name">{user.displayName || 'Hanif'}</div>
              <div className="account-email">{user.email}</div>
            </span>
            <IconDots size={17} />
          </button>
        </div>
      </aside>

      {/* Main Reading Stage */}
      <main className="main-stage">
        <header className="stage-header">
          <div className="header-left">
            {(isMobile || sidebarCollapsed) && (
              <button
                type="button"
                className="icon-square-btn pressable"
                aria-label="Menu"
                onClick={() =>
                  isMobile ? setMobileDrawerOpen(true) : setSidebarCollapsed(false)
                }
              >
                <IconMenu size={20} />
              </button>
            )}

            {/* Split Bidirectional & Auto-Detect Language Selector (Sumber <-> Tujuan) */}
            <div className="lang-pair-bar">
              <button
                type="button"
                className="lang-pill-btn pressable"
                aria-label={`${strings.sourceLangTitle}: ${sourcePillLabel}`}
                aria-expanded={langPickerSide === 'source'}
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setMoreMenuOpen(false);
                  setAccountMenuOpen(false);
                  setHistoryMenuTarget(null);
                  setLangMenuRect(rect);
                  setLangPickerSide((p) => (p === 'source' ? null : 'source'));
                }}
              >
                <span>{sourcePillLabel}</span>
                <IconChevronDown size={15} />
              </button>

              <button
                type="button"
                className={`lang-swap-btn pressable ${swapFlipped ? 'flipped' : ''}`}
                aria-label={strings.swapLanguages}
                title={strings.swapLanguages}
                onClick={handleSwapLanguages}
              >
                <IconArrowsSwitch size={16} />
              </button>

              <button
                type="button"
                className="lang-pill-btn pressable"
                aria-label={`${strings.targetLangTitle}: ${targetPillLabel}`}
                aria-expanded={langPickerSide === 'target'}
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setMoreMenuOpen(false);
                  setAccountMenuOpen(false);
                  setHistoryMenuTarget(null);
                  setLangMenuRect(rect);
                  setLangPickerSide((p) => (p === 'target' ? null : 'target'));
                }}
              >
                <span>{targetPillLabel}</span>
                <IconChevronDown size={15} />
              </button>
            </div>
          </div>

          <div className="header-right">
            {isMobile && (
              <button
                type="button"
                className="icon-square-btn pressable"
                aria-label={strings.sidebarNew}
                onClick={() => {
                  setComposerText('');
                  setLinkUrlInput('');
                  setAttachments([]);
                  setStreamingTurn(null);
                  setActiveTab('teks');
                  navigate('/');
                }}
              >
                <IconPlus size={20} />
              </button>
            )}
          </div>
        </header>

        {!isOnline && (
          <div className="offline-banner" role="status">
            {strings.offlineBanner}
          </div>
        )}

        {pathname === '/berkas' ? (
          <Suspense fallback={<div className="subpage-container"><div className="result-card">...</div></div>}>
            <MyFilesView
              user={user}
              jobs={jobs}
              resolvedTheme={resolvedTheme}
              strings={strings}
              onNavigate={navigate}
              onNotify={(m) => pushToast(m)}
            />
          </Suspense>
        ) : kamusMatch ? (
          <Suspense fallback={<div className="subpage-container"><div className="result-card">...</div></div>}>
            <GlossaryView
              user={user}
              titles={titles}
              activeTitleId={kamusMatch.titleId}
              strings={strings}
              onNavigate={navigate}
              onNotify={(m) => pushToast(m)}
            />
          </Suspense>
        ) : readerMatch ? (
          <Suspense fallback={<div className="subpage-container"><div className="result-card">...</div></div>}>
            <SideBySideReaderView
              user={user}
              cid={readerMatch.cid}
              mid={readerMatch.mid}
              messages={messages}
              resolvedTheme={resolvedTheme}
              strings={strings}
              onNavigate={navigate}
            />
          </Suspense>
        ) : isStageEmpty ? (
          <div className="stage-body is-empty">
            <div className="empty-center-stack">
              <h1 className="greeting-heading">{strings.greeting}</h1>

              {inboxItems.map((item) => (
                <div key={item.id} className="result-card" style={{ maxWidth: '720px' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--accent)' }}>
                    {strings.inboxFromShortcut}
                  </div>
                  <div style={{ fontFamily: 'var(--font-jp)', fontSize: '15px' }}>
                    {item.text.slice(0, 180)}
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      className="btn-primary pressable"
                      onClick={() => handleSendText(item.text, item.id)}
                    >
                      {strings.translateNow}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary pressable"
                      onClick={() => dismissInboxItemBridge(user, item.id)}
                    >
                      {strings.dismiss}
                    </button>
                  </div>
                </div>
              ))}

              {activeTab === 'teks' && (
                <button
                  type="button"
                  className="btn-secondary pressable"
                  onClick={async () => {
                    try {
                      const clip = await navigator.clipboard.readText();
                      if (clip.trim()) {
                        setComposerText(clip);
                        handleSendText(clip);
                      } else {
                        pushToast('Papan klip masih kosong.');
                      }
                    } catch {
                      pushToast('Tempel teks secara langsung dengan Cmd/Ctrl+V.');
                    }
                  }}
                >
                  <IconCopy size={16} />
                  {strings.pasteAndTranslate}
                </button>
              )}

              {renderComposerAndModeZone()}
            </div>
          </div>
        ) : (
          <div className="stage-body">
            <div className="stream-column">
              {modeMessages.map((turn) => {
                const { src: turnSrc, tgt: turnTgt } = parseModePair(turn.mode);
                const effectiveTurnSrc = turn.detectedSource || (turnSrc === 'auto' ? 'ja' : turnSrc);

                if (turn.role === 'user') {
                  const isLongSrc = turn.text.length > 280;
                  const isExpanded = Boolean(expandedBubbles[turn.id]);
                  const shownText =
                    isLongSrc && !isExpanded ? `${turn.text.slice(0, 280)}...` : turn.text;

                  return (
                    <div key={turn.id} className="turn-user-wrap">
                      {editingMsgId === turn.id ? (
                        <div className="result-card" style={{ maxWidth: '580px' }}>
                          <textarea
                            className="field-input"
                            style={{ minHeight: '90px' }}
                            value={editingDraft}
                            onChange={(e) => setEditingDraft(e.target.value)}
                          />
                          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <button
                              type="button"
                              className="btn-secondary pressable"
                              onClick={() => setEditingMsgId(null)}
                            >
                              {strings.cancel}
                            </button>
                            <button
                              type="button"
                              className="btn-primary pressable"
                              onClick={() => {
                                const txt = editingDraft.trim();
                                setEditingMsgId(null);
                                if (txt) handleSendText(txt);
                              }}
                            >
                              {strings.retranslate}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div
                            className={`user-bubble ${effectiveTurnSrc === 'ja' ? 'is-jp' : ''}`}
                            lang={effectiveTurnSrc}
                          >
                            {shownText}
                          </div>
                          <div style={{ display: 'flex', gap: '6px' }}>
                            {isLongSrc && (
                              <button
                                type="button"
                                className="action-chip-btn"
                                onClick={() =>
                                  setExpandedBubbles((p) => ({
                                    ...p,
                                    [turn.id]: !isExpanded,
                                  }))
                                }
                              >
                                {isExpanded ? strings.showLess : strings.showAll}
                              </button>
                            )}
                            <button
                              type="button"
                              className="action-chip-btn"
                              onClick={() => {
                                setEditingMsgId(turn.id);
                                setEditingDraft(turn.text);
                              }}
                            >
                              <IconEdit size={15} />
                              {strings.editSource}
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  );
                }

                if (turn.kind === 'image' && turn.imageResult) {
                  return (
                    <div key={turn.id} className="turn-assistant-wrap">
                      <Suspense fallback={<div className="result-card">...</div>}>
                        <ImageResultCard
                          result={turn.imageResult}
                          fileName={turn.fileName}
                          resolvedTheme={resolvedTheme}
                          strings={strings}
                          onCopy={(txt) => {
                            navigator.clipboard?.writeText(txt);
                            pushToast(strings.copiedToast);
                          }}
                        />
                      </Suspense>
                    </div>
                  );
                }

                if (turn.kind === 'link' && turn.linkPreview) {
                  const lp = turn.linkPreview;
                  const nav = lp.novelNav;
                  const fullArticleText = turn.text || lp.excerptDst;
                  return (
                    <div key={turn.id} className="turn-assistant-wrap">
                      <div className="result-card">
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
                          <span>
                            {lp.host} · {lp.paragraphCount} {strings.paragraphsUnit}
                            {lp.lockedNames > 0
                              ? ` · ${lp.lockedNames} ${strings.lockedNamesUnit}`
                              : ''}
                          </span>
                          {nav?.isNovel && (
                            <span className="status-badge done">
                              {nav.isTocPage ? strings.ebookTocBadge : strings.novelDetectedBadge}
                              {nav.chapterLabel ? ` · ${nav.chapterLabel}` : ''}
                            </span>
                          )}
                        </div>
                        <div style={{ fontWeight: 700, fontSize: '20px', lineHeight: '28px' }}>
                          {lp.titleDst}
                        </div>

                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            className="btn-primary pressable"
                            onMouseEnter={() =>
                              prefetchNextChapterTranslatedDirect(
                                nav?.isTocPage && nav.firstUrl ? nav.firstUrl : lp.url,
                                turn.mode,
                                lp.titleId
                              )
                            }
                            onFocus={() =>
                              prefetchNextChapterTranslatedDirect(
                                nav?.isTocPage && nav.firstUrl ? nav.firstUrl : lp.url,
                                turn.mode,
                                lp.titleId
                              )
                            }
                            onClick={() =>
                              navigate(
                                `/web?url=${encodeURIComponent(
                                  nav?.isTocPage && nav.firstUrl ? nav.firstUrl : lp.url
                                )}&mode=${turn.mode}&view=reader&titleId=${encodeURIComponent(lp.titleId)}`
                              )
                            }
                          >
                            <IconBook size={17} />
                            {nav?.isTocPage && nav.firstUrl
                              ? strings.startReadingCh1
                              : strings.openFullTranslatedPage}
                          </button>
                          <button
                            type="button"
                            className="btn-secondary pressable"
                            onClick={() =>
                              navigate(
                                `/web?url=${encodeURIComponent(lp.url)}&mode=${turn.mode}&view=site&titleId=${encodeURIComponent(lp.titleId)}`
                              )
                            }
                          >
                            <IconGlobe size={17} />
                            {strings.openTranslatedSite}
                          </button>
                          <button
                            type="button"
                            className="btn-secondary pressable"
                            onClick={() => {
                              navigator.clipboard?.writeText(
                                `${lp.titleDst}\n\n${fullArticleText}`
                              );
                              pushToast(strings.copiedToast);
                            }}
                          >
                            <IconCopy size={16} />
                            {strings.copyTranslation}
                          </button>
                        </div>

                        <div
                          className={`assistant-prose ${turnTgt === 'ja' ? 'is-jp' : ''}`}
                          style={{
                            fontSize: '17px',
                            lineHeight: '29px',
                            paddingTop: '8px',
                            borderTop: '1px solid var(--border)',
                          }}
                          lang={turnTgt}
                        >
                          {fullArticleText}
                        </div>

                        {nav && (nav.prevUrl || nav.nextUrl || nav.chapters?.length || nav.firstUrl) && (
                          <div className="novel-inline-nav">
                            <button
                              type="button"
                              className="btn-secondary pressable"
                              disabled={!nav.prevUrl || isFetchingLink}
                              onClick={() =>
                                nav.prevUrl && handleSubmitLink(undefined, nav.prevUrl)
                              }
                            >
                              {'\u2190'} {strings.prevChapter}
                            </button>
                            <button
                              type="button"
                              className="btn-secondary pressable"
                              onClick={() => {
                                setInlineChapterQuery('');
                                setInlineChaptersNav({ nav, mode: turn.mode, titleId: lp.titleId });
                                if (nav.chapters && nav.chapters.length > 0) {
                                  translateChapterTitlesDirect({
                                    chapters: nav.chapters,
                                    mode: turn.mode,
                                    titleId: lp.titleId,
                                    tocKey: nav.tocUrl || lp.url,
                                  })
                                    .then((m) =>
                                      setInlineTranslatedTitles((prev) => ({ ...prev, ...m }))
                                    )
                                    .catch(() => {});
                                }
                              }}
                            >
                              <IconBook size={16} />
                              {strings.chapterListBtn}
                              {nav.chapterLabel ? ` (${nav.chapterLabel})` : ''}
                            </button>
                            {nav.nextUrl ? (
                              <button
                                type="button"
                                className="btn-primary pressable"
                                disabled={isFetchingLink}
                                onMouseEnter={() =>
                                  prefetchNextChapterTranslatedDirect(
                                    nav.nextUrl!,
                                    turn.mode,
                                    lp.titleId
                                  )
                                }
                                onFocus={() =>
                                  prefetchNextChapterTranslatedDirect(
                                    nav.nextUrl!,
                                    turn.mode,
                                    lp.titleId
                                  )
                                }
                                onClick={() => handleSubmitLink(undefined, nav.nextUrl!)}
                              >
                                {isFetchingLink
                                  ? strings.loadingNextChapter
                                  : nav.isTocPage
                                    ? strings.startReadingCh1
                                    : strings.nextChapter}{' '}
                                {'\u2192'}
                              </button>
                            ) : nav.firstUrl && nav.firstUrl !== lp.url ? (
                              <button
                                type="button"
                                className="btn-primary pressable"
                                disabled={isFetchingLink}
                                onClick={() => handleSubmitLink(undefined, nav.firstUrl!)}
                              >
                                {strings.readFromChapter1}
                              </button>
                            ) : (
                              <button type="button" className="btn-secondary" disabled>
                                {strings.nextChapter} {'\u2192'}
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                }

                if (turn.kind === 'document') {
                  const pct =
                    turn.total && turn.total > 0
                      ? Math.round(((turn.done || 0) / turn.total) * 100)
                      : turn.state === 'done'
                        ? 100
                        : 15;
                  return (
                    <div key={turn.id} className="turn-assistant-wrap">
                      <div className="result-card">
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '8px',
                          }}
                        >
                          <div style={{ fontWeight: 600 }}>
                            {turn.fileName || 'Dokumen'}
                          </div>
                          <span
                            className={`status-badge ${
                              turn.state === 'done'
                                ? 'done'
                                : turn.state === 'error'
                                  ? 'error'
                                  : turn.state === 'running'
                                    ? 'running'
                                    : 'warning'
                            }`}
                          >
                            {turn.state === 'done'
                              ? 'Selesai'
                              : turn.state === 'running'
                                ? 'Berjalan'
                                : turn.state === 'stopped'
                                  ? 'Berhenti'
                                  : turn.state === 'partial'
                                    ? 'Sebagian'
                                    : 'Galat'}
                          </span>
                        </div>

                        {turn.state === 'running' && (
                          <div className="progress-track">
                            <div className="progress-fill" style={{ width: `${pct}%` }} />
                          </div>
                        )}

                        {turn.error && (
                          <div style={{ fontSize: '13px', color: 'var(--danger)' }}>
                            {turn.error}
                          </div>
                        )}

                        {turn.state === 'done' && turn.text && (
                          <div
                            className={`assistant-prose ${turnTgt === 'ja' ? 'is-jp' : ''}`}
                            style={{ fontSize: '15px', lineHeight: '24px' }}
                            lang={turnTgt}
                          >
                            {turn.text.length > 260 ? `${turn.text.slice(0, 260)}...` : turn.text}
                          </div>
                        )}

                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                          {turn.state === 'running' && turn.jobId && (
                            <button
                              type="button"
                              className="btn-secondary pressable"
                              onClick={() => requestStopJob(turn.jobId!)}
                            >
                              <IconStop size={16} />
                              {strings.stop}
                            </button>
                          )}

                          {(turn.state === 'stopped' || turn.state === 'partial') && (
                            <button
                              type="button"
                              className="btn-primary pressable"
                              onClick={() =>
                                resumeInterruptedTurn({
                                  user,
                                  cid: activeCid,
                                  mid: turn.id,
                                  onEvent: () => {},
                                })
                              }
                            >
                              {strings.resumeTranslation}
                            </button>
                          )}

                          {turn.state === 'done' && (
                            <>
                              <button
                                type="button"
                                className="btn-primary pressable"
                                onClick={() =>
                                  navigate(`/c/${activeCid}/m/${turn.id}/baca`)
                                }
                              >
                                <IconColumns size={16} />
                                {strings.readSideBySide}
                              </button>
                              {(
                                [
                                  'html',
                                  'docx',
                                  'srt',
                                  ...(turn.fmt === 'ass' || turn.fmt === 'ssa'
                                    ? (['ass'] as const)
                                    : []),
                                  ...(turn.fmt === 'vtt' ? (['vtt'] as const) : []),
                                  'txt',
                                  'md',
                                ] as const
                              ).map((fmt) => (
                                <button
                                  key={fmt}
                                  type="button"
                                  className="btn-secondary pressable"
                                  onClick={async () => {
                                    const { blob, filename } = await downloadExportedTurn({
                                      user,
                                      cid: activeCid,
                                      mid: turn.id,
                                      fmt,
                                      theme: resolvedTheme,
                                      fallbackSentences: turn.sentences,
                                      fallbackText: turn.text,
                                    });
                                    const url = URL.createObjectURL(blob);
                                    const a = document.createElement('a');
                                    a.href = url;
                                    a.download = filename;
                                    document.body.appendChild(a);
                                    a.click();
                                    a.remove();
                                    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
                                  }}
                                >
                                  <IconDownload size={16} />.{fmt}
                                </button>
                              ))}
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                }

                return (
                  <div key={turn.id} className="turn-assistant-wrap">
                    {turn.state === 'error' || turn.state === 'busy' ? (
                      <div className="result-card">
                        <span className="status-badge error">
                          {turn.state === 'busy' ? 'Penuh' : 'Galat'}
                        </span>
                        <div style={{ fontSize: '14px' }}>
                          {turn.error || 'Terjemahan belum berhasil diselesaikan.'}
                        </div>

                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                          {turn.srcText && (
                            <button
                              type="button"
                              className="btn-primary pressable"
                              onClick={() =>
                                isSingleStandaloneUrl(turn.srcText!)
                                  ? handleSubmitLink(undefined, turn.srcText!)
                                  : handleSendText(turn.srcText)
                              }
                            >
                              <IconRefresh size={16} />
                              {strings.retryNow}
                            </button>
                          )}
                          {turn.srcText &&
                            isSingleStandaloneUrl(turn.srcText) &&
                            buildAutoTranslatedSiteUrl(turn.srcText, turn.mode) && (
                              <a
                                href={buildAutoTranslatedSiteUrl(turn.srcText, turn.mode)!}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="btn-secondary pressable"
                              >
                                <IconGlobe size={16} />
                                {strings.openAutoTranslatedTab}
                              </a>
                            )}
                        </div>
                      </div>
                    ) : (
                      <>
                        {turnSrc === 'auto' && turn.detectedSource && (
                          <div style={{ fontSize: '12px', color: 'var(--text-subtle)' }}>
                            {strings.detectedPrefix}:{' '}
                            {labelForLang(turn.detectedSource, strings)} {'\u2192'}{' '}
                            {labelForLang(turnTgt, strings)}
                          </div>
                        )}

                        <div
                          className={`assistant-prose ${turnTgt === 'ja' ? 'is-jp' : ''}`}
                          lang={turnTgt}
                          onClick={() => {
                            if (isMobile) setMobileTurnSheet(turn);
                          }}
                        >
                          {turn.text || 'Menerjemahkan...'}
                        </div>

                        {turn.nameChips && turn.nameChips.length > 0 && (
                          <div className="name-chips-row">
                            {turn.nameChips.map((chip) => (
                              <button
                                key={chip.surface}
                                type="button"
                                className={`name-chip pressable ${
                                  chip.confirmed ? 'locked' : ''
                                }`}
                                onClick={async () => {
                                  const tid =
                                    turn.titleId ||
                                    activeConversation?.titleId ||
                                    't_rashomon';
                                  await upsertUserGlossaryEntry(tid, {
                                    surface: chip.surface,
                                    kind: chip.kind,
                                    reading: chip.reading,
                                    romaji: chip.romaji || chip.dst,
                                    render_id: chip.dst,
                                    render_en: chip.dst,
                                    gloss_id: '',
                                    gloss_en: '',
                                    gender: '',
                                    aliases: [],
                                    allow_compound: false,
                                    score: 1.0,
                                  });
                                  pushToast(
                                    `Ejaan ${chip.surface} \u2192 ${chip.dst} dikunci`
                                  );
                                }}
                              >
                                <span style={{ fontFamily: 'var(--font-jp)' }}>
                                  {chip.surface}
                                </span>
                                <span>{'\u2192'}</span>
                                <strong>{chip.dst}</strong>
                                {chip.confirmed && (
                                  <IconCheck size={14} style={{ color: 'var(--accent)' }} />
                                )}
                              </button>
                            ))}
                          </div>
                        )}

                        {turn.state === 'done' && (
                          <div className="turn-action-bar">
                            <button
                              type="button"
                              className="action-chip-btn pressable"
                              onClick={() => {
                                navigator.clipboard?.writeText(turn.text);
                                pushToast(strings.copiedToast);
                              }}
                            >
                              <IconCopy size={15} />
                              {strings.copyTranslation}
                            </button>
                            {turn.srcText && (
                              <button
                                type="button"
                                className="action-chip-btn pressable"
                                onClick={() => handleSendText(turn.srcText)}
                              >
                                <IconRefresh size={15} />
                                {strings.retranslate}
                              </button>
                            )}
                            <button
                              type="button"
                              className="action-chip-btn pressable"
                              onClick={() => {
                                navigator.clipboard?.writeText(turn.text);
                                pushToast(strings.copiedToast);
                              }}
                            >
                              <IconShare size={15} />
                              {strings.shareChat}
                            </button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="composer-dock">
              <div className="composer-dock-inner">{renderComposerAndModeZone()}</div>
            </div>
          </div>
        )}
      </main>

      {/* Root-level Non-Overlapping Popovers with Shared Click-Outside Dismissal Backdrop */}
      {(moreMenuOpen ||
        accountMenuOpen ||
        (!isMobile && Boolean(langPickerSide)) ||
        (!isMobile && Boolean(historyMenuTarget))) && (
        <>
          <div className="popover-dismiss-backdrop" onClick={closeAllPopovers} />

          {moreMenuOpen && (
            <div
              className="context-popover glass-regular-surface"
              style={{
                width: '224px',
                left: `${Math.min(
                  window.innerWidth - 236,
                  Math.max(12, moreMenuRect?.left || 14)
                )}px`,
                top: `${Math.min(
                  window.innerHeight - 170,
                  Math.max(12, (moreMenuRect?.bottom || 152) + 6)
                )}px`,
              }}
              role="menu"
            >
              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => navigate('/berkas')}
              >
                <span className="menu-item-left">
                  <IconFolder size={18} />
                  {strings.myFiles}
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => navigate('/kamus')}
              >
                <span className="menu-item-left">
                  <IconBook size={18} />
                  {strings.glossary}
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => {
                  setMoreMenuOpen(false);
                  setShortcutsOpen(true);
                }}
              >
                <span className="menu-item-left">
                  <IconKeyboard size={18} />
                  {strings.shortcuts}
                </span>
                <span style={{ fontSize: '12px', color: 'var(--text-subtle)' }}>
                  Ctrl+/
                </span>
              </button>
            </div>
          )}

          {accountMenuOpen && (
            <div
              className="context-popover glass-regular-surface"
              style={{
                width: '236px',
                left: `${Math.min(
                  window.innerWidth - 248,
                  Math.max(12, accountMenuRect?.left || 12)
                )}px`,
                bottom: `${Math.max(
                  12,
                  window.innerHeight - (accountMenuRect?.top || window.innerHeight - 64) + 8
                )}px`,
              }}
              role="menu"
            >
              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => {
                  setAccountMenuOpen(false);
                  setSettingsOpen(true);
                }}
              >
                <span className="menu-item-left">
                  <IconSettings size={18} />
                  {strings.settings}
                </span>
                <span style={{ fontSize: '12px', color: 'var(--text-subtle)' }}>Ctrl+,</span>
              </button>

              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => handleChangeUiLang(settings.uiLang === 'id' ? 'en' : 'id')}
              >
                <span className="menu-item-left">
                  <IconGlobe size={18} />
                  {strings.uiLanguage}
                </span>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--accent)' }}>
                  {settings.uiLang === 'id' ? 'ID \u2192 EN' : 'EN \u2192 ID'}
                </span>
              </button>

              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => {
                  setAccountMenuOpen(false);
                  setInfoModalKind('help');
                }}
              >
                <span className="menu-item-left">
                  <IconHelp size={18} />
                  {strings.help}
                </span>
              </button>

              <a
                role="menuitem"
                className="menu-item-btn"
                href="mailto:hanifp633@gmail.com?subject=Masukan%20tranX"
                onClick={() => setAccountMenuOpen(false)}
              >
                <span className="menu-item-left">
                  <IconMail size={18} />
                  {strings.sendFeedback}
                </span>
              </a>

              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => {
                  setAccountMenuOpen(false);
                  setInfoModalKind('about');
                }}
              >
                <span className="menu-item-left">
                  <IconInfo size={18} />
                  {strings.learnMore}
                </span>
              </button>

              <div className="menu-divider" />

              <button
                type="button"
                role="menuitem"
                className="menu-item-btn danger"
                onClick={() => {
                  setAccountMenuOpen(false);
                  setLogoutOpen(true);
                }}
              >
                <span className="menu-item-left">
                  <IconLogout size={18} />
                  {strings.signOut}
                </span>
              </button>
            </div>
          )}

          {!isMobile && langPickerSide === 'source' && (
            <div
              className="context-popover glass-regular-surface"
              style={{
                width: '240px',
                left: `${Math.min(
                  window.innerWidth - 252,
                  Math.max(12, langMenuRect?.left || 276)
                )}px`,
                top: `${Math.min(
                  window.innerHeight - 230,
                  Math.max(12, (langMenuRect?.bottom || 48) + 6)
                )}px`,
              }}
              role="menu"
              aria-label={strings.sourceLangTitle}
            >
              <div
                style={{
                  padding: '4px 10px 6px 10px',
                  fontSize: '12px',
                  color: 'var(--text-subtle)',
                }}
              >
                {strings.sourceAutoHint}
              </div>
              {(
                [
                  ['auto', strings.langAuto],
                  ['id', strings.langId],
                  ['en', strings.langEn],
                  ['ja', strings.langJa],
                ] as const
              ).map(([code, label]) => (
                <button
                  key={code}
                  type="button"
                  role="menuitemradio"
                  aria-checked={currentSrcLang === code}
                  className="menu-item-btn"
                  onClick={() => handleSelectSourceLang(code)}
                >
                  <span>{label}</span>
                  {currentSrcLang === code && (
                    <IconCheck size={17} style={{ color: 'var(--accent)' }} />
                  )}
                </button>
              ))}
            </div>
          )}

          {!isMobile && langPickerSide === 'target' && (
            <div
              className="context-popover glass-regular-surface"
              style={{
                width: '216px',
                left: `${Math.min(
                  window.innerWidth - 228,
                  Math.max(12, langMenuRect?.left || 380)
                )}px`,
                top: `${Math.min(
                  window.innerHeight - 190,
                  Math.max(12, (langMenuRect?.bottom || 48) + 6)
                )}px`,
              }}
              role="menu"
              aria-label={strings.targetLangTitle}
            >
              {(
                [
                  ['id', strings.langId],
                  ['en', strings.langEn],
                  ['ja', strings.langJa],
                ] as const
              ).map(([code, label]) => (
                <button
                  key={code}
                  type="button"
                  role="menuitemradio"
                  aria-checked={currentTgtLang === code}
                  className="menu-item-btn"
                  onClick={() => handleSelectTargetLang(code)}
                >
                  <span>{label}</span>
                  {currentTgtLang === code && (
                    <IconCheck size={17} style={{ color: 'var(--accent)' }} />
                  )}
                </button>
              ))}
            </div>
          )}

          {!isMobile && historyMenuTarget && (
            <div
              className="context-popover glass-regular-surface"
              style={{
                width: '216px',
                left: `${Math.min(
                  window.innerWidth - 228,
                  Math.max(12, historyMenuTarget.rect?.right || 220)
                )}px`,
                top: `${Math.min(
                  window.innerHeight - 210,
                  Math.max(12, historyMenuTarget.rect?.top || 120)
                )}px`,
              }}
              role="menu"
            >
              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => handleTogglePin(historyMenuTarget.conv)}
              >
                <span className="menu-item-left">
                  {historyMenuTarget.conv.pinned ? (
                    <IconPinOff size={18} />
                  ) : (
                    <IconPin size={18} />
                  )}
                  {historyMenuTarget.conv.pinned ? strings.unpinChat : strings.pinChat}
                </span>
              </button>

              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => {
                  const target = historyMenuTarget.conv;
                  setHistoryMenuTarget(null);
                  setRenameTarget(target);
                }}
              >
                <span className="menu-item-left">
                  <IconEdit size={18} />
                  {strings.renameChat}
                </span>
              </button>

              <button
                type="button"
                role="menuitem"
                className="menu-item-btn"
                onClick={() => handleShareConversation(historyMenuTarget.conv)}
              >
                <span className="menu-item-left">
                  <IconShare size={18} />
                  {strings.shareChat}
                </span>
              </button>

              <div className="menu-divider" />

              <button
                type="button"
                role="menuitem"
                className="menu-item-btn danger"
                onClick={() => handleDeleteConversation(historyMenuTarget.conv)}
              >
                <span className="menu-item-left">
                  <IconTrash size={18} />
                  {strings.deleteChat}
                </span>
              </button>
            </div>
          )}
        </>
      )}

      {/* Mobile K/Lembar bawah for History Context Menu */}
      {isMobile && historyMenuTarget && (
        <div
          className="bottom-sheet-backdrop"
          onClick={() => setHistoryMenuTarget(null)}
        >
          <div
            className="bottom-sheet glass-regular-surface"
            role="dialog"
            aria-modal="true"
            aria-label={historyMenuTarget.conv.title}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="sheet-handle-btn"
              aria-label={strings.cancel}
              onClick={() => setHistoryMenuTarget(null)}
            >
              <span className="sheet-handle-pill" />
            </button>
            <div
              style={{
                padding: '2px 12px 10px 12px',
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--text-muted)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {historyMenuTarget.conv.title}
            </div>

            <button
              type="button"
              className="sheet-row-btn"
              onClick={() => handleTogglePin(historyMenuTarget.conv)}
            >
              {historyMenuTarget.conv.pinned ? (
                <IconPinOff size={20} />
              ) : (
                <IconPin size={20} />
              )}
              <span>
                {historyMenuTarget.conv.pinned ? strings.unpinChat : strings.pinToTop}
              </span>
            </button>

            <button
              type="button"
              className="sheet-row-btn"
              onClick={() => {
                const target = historyMenuTarget.conv;
                setHistoryMenuTarget(null);
                setRenameTarget(target);
              }}
            >
              <IconEdit size={20} />
              <span>{strings.renameChat}</span>
            </button>

            <button
              type="button"
              className="sheet-row-btn"
              onClick={() => handleShareConversation(historyMenuTarget.conv)}
            >
              <IconShare size={20} />
              <span>{strings.shareChat}</span>
            </button>

            <div className="menu-divider" />

            <button
              type="button"
              className="sheet-row-btn danger"
              onClick={() => handleDeleteConversation(historyMenuTarget.conv)}
            >
              <IconTrash size={20} />
              <span>{strings.deleteHistoryMobile}</span>
            </button>
          </div>
        </div>
      )}

      {/* Mobile K/Lembar bawah for Source / Target Language Picker (H13) */}
      {isMobile && langPickerSide && (
        <div className="bottom-sheet-backdrop" onClick={() => setLangPickerSide(null)}>
          <div
            className="bottom-sheet glass-regular-surface"
            role="dialog"
            aria-modal="true"
            aria-label={
              langPickerSide === 'source'
                ? strings.sourceLangTitle
                : strings.targetLangTitle
            }
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="sheet-handle-btn"
              aria-label={strings.cancel}
              onClick={() => setLangPickerSide(null)}
            >
              <span className="sheet-handle-pill" />
            </button>
            <div
              style={{
                padding: '0 12px 8px 12px',
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--text-subtle)',
              }}
            >
              {langPickerSide === 'source'
                ? `${strings.sourceLangTitle} · ${strings.sourceAutoHint}`
                : strings.targetLangTitle}
            </div>
            {langPickerSide === 'source'
              ? (
                  [
                    ['auto', strings.langAuto],
                    ['id', strings.langId],
                    ['en', strings.langEn],
                    ['ja', strings.langJa],
                  ] as const
                ).map(([code, label]) => (
                  <button
                    key={code}
                    type="button"
                    className="sheet-row-btn"
                    onClick={() => handleSelectSourceLang(code)}
                  >
                    <span style={{ flex: 1 }}>{label}</span>
                    {currentSrcLang === code && (
                      <IconCheck size={20} style={{ color: 'var(--accent)' }} />
                    )}
                  </button>
                ))
              : (
                  [
                    ['id', strings.langId],
                    ['en', strings.langEn],
                    ['ja', strings.langJa],
                  ] as const
                ).map(([code, label]) => (
                  <button
                    key={code}
                    type="button"
                    className="sheet-row-btn"
                    onClick={() => handleSelectTargetLang(code)}
                  >
                    <span style={{ flex: 1 }}>{label}</span>
                    {currentTgtLang === code && (
                      <IconCheck size={20} style={{ color: 'var(--accent)' }} />
                    )}
                  </button>
                ))}
          </div>
        </div>
      )}

      {/* Mobile K/Lembar bawah for Assistant Turn Actions */}
      {isMobile && mobileTurnSheet && (
        <div
          className="bottom-sheet-backdrop"
          onClick={() => setMobileTurnSheet(null)}
        >
          <div
            className="bottom-sheet glass-regular-surface"
            role="dialog"
            aria-modal="true"
            aria-label="Aksi hasil terjemahan"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="sheet-handle-btn"
              aria-label={strings.cancel}
              onClick={() => setMobileTurnSheet(null)}
            >
              <span className="sheet-handle-pill" />
            </button>
            <button
              type="button"
              className="sheet-row-btn"
              onClick={() => {
                navigator.clipboard?.writeText(mobileTurnSheet.text);
                setMobileTurnSheet(null);
                pushToast(strings.copiedToast);
              }}
            >
              <IconCopy size={20} />
              <span>{strings.copyTranslation}</span>
            </button>
            {mobileTurnSheet.srcText && (
              <button
                type="button"
                className="sheet-row-btn"
                onClick={() => {
                  const src = mobileTurnSheet.srcText!;
                  setMobileTurnSheet(null);
                  handleSendText(src);
                }}
              >
                <IconRefresh size={20} />
                <span>{strings.retranslate}</span>
              </button>
            )}
            <button
              type="button"
              className="sheet-row-btn"
              onClick={() => {
                navigator.clipboard?.writeText(mobileTurnSheet.text);
                setMobileTurnSheet(null);
                pushToast(strings.copiedToast);
              }}
            >
              <IconShare size={20} />
              <span>{strings.shareChat}</span>
            </button>
          </div>
        </div>
      )}

      <Suspense fallback={null}>
        {settingsOpen && (
          <SettingsModal
            user={user}
            settings={settings}
            strings={strings}
            onClose={() => setSettingsOpen(false)}
            onChangeUiLang={handleChangeUiLang}
            onNotify={(m) => pushToast(m)}
          />
        )}

        {shortcutsOpen && (
          <ShortcutsModal strings={strings} onClose={() => setShortcutsOpen(false)} />
        )}

        {logoutOpen && (
          <LogoutDialog
            strings={strings}
            onClose={() => setLogoutOpen(false)}
            onConfirm={async () => {
              setLogoutOpen(false);
              await logoutSession();
              navigate('/masuk');
            }}
          />
        )}

        {renameTarget && (
          <RenameDialog
            initialTitle={renameTarget.title}
            strings={strings}
            onClose={() => setRenameTarget(null)}
            onSave={async (nextTitle) => {
              const target = renameTarget;
              setRenameTarget(null);
              await renameConversationTitle(target.id, nextTitle);
            }}
          />
        )}

        {infoModalKind && (
          <InfoModal
            kind={infoModalKind}
            strings={strings}
            onClose={() => setInfoModalKind(null)}
          />
        )}
      </Suspense>

      {inlineChaptersNav && (
        <div className="scrim-backdrop" onClick={() => setInlineChaptersNav(null)}>
          <div
            className="modal-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="inline-chapters-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 id="inline-chapters-title" className="modal-title">
                {inlineChaptersNav.nav.seriesTitle || strings.chapterListBtn}
                {inlineChaptersNav.nav.chapters?.length
                  ? ` (${inlineChaptersNav.nav.chapters.length})`
                  : ''}
              </h2>
              <button
                type="button"
                className="icon-square-btn"
                aria-label={strings.closeLabel}
                onClick={() => setInlineChaptersNav(null)}
              >
                <IconX size={18} />
              </button>
            </div>
            <div className="modal-body">
              {inlineChaptersNav.nav.chapters && inlineChaptersNav.nav.chapters.length > 6 && (
                <input
                  type="search"
                  className="field-input"
                  placeholder={strings.searchChaptersPlaceholder}
                  value={inlineChapterQuery}
                  onChange={(e) => setInlineChapterQuery(e.target.value)}
                />
              )}
              {inlineChaptersNav.nav.chapters && inlineChaptersNav.nav.chapters.length > 0 ? (
                <div className="chapter-list-grid">
                  {inlineChaptersNav.nav.chapters
                    .filter((ch, idx) => {
                      if (!deferredInlineChapterQuery.trim()) return true;
                      const q = deferredInlineChapterQuery.trim().toLowerCase();
                      const tDst = (inlineTranslatedTitles[ch.url] || ch.titleDst || '').toLowerCase();
                      return (
                        ch.title.toLowerCase().includes(q) ||
                        tDst.includes(q) ||
                        String(idx + 1).includes(q)
                      );
                    })
                    .map((ch, idx) => (
                      <button
                        key={`${ch.url}_${idx}`}
                        type="button"
                        className={`chapter-list-item pressable ${ch.current ? 'is-current' : ''}`}
                        onClick={() => {
                          setInlineChaptersNav(null);
                          handleSubmitLink(undefined, ch.url);
                        }}
                      >
                        <span>{inlineTranslatedTitles[ch.url] || ch.titleDst || ch.title}</span>
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

      {toasts.length > 0 && (
        <div className="toast-container" role="status" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className="toast-bar">
              <span>{t.message}</span>
              {t.undoLabel && t.onUndo && (
                <button
                  type="button"
                  className="toast-undo-btn"
                  onClick={() => {
                    t.onUndo?.();
                    setToasts((prev) => prev.filter((x) => x.id !== t.id));
                  }}
                >
                  {t.undoLabel}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
