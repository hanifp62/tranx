/**
 * Manga, Comic, Webtoon, Manhwa, Manhua & Direct-Image Detection, Extraction,
 * Vertical Strip Tiling, Reading-Order Solver, and Background-Sampled Visual Overlay Engine.
 * Grounded in our 300-manga 6-session research corpus (Shonen, Seinen, Shojo/4-Koma,
 * Isekai/LitRPG, Korean Manhwa/Webtoon, Chinese Manhua, Western Comics & Direct Image CDNs).
 */

import type {
  ComicLayoutMode,
  MangaLinkMeta,
  MangaPageItem,
  ResolvedTheme,
  VisionBgTone,
  VisionBlock,
  VisionBlockKind,
  VisionBlockShape,
} from '../types';
import { toSafeHttpUrl } from './langUtils';

const DIRECT_IMAGE_EXT_RE = /\.(?:png|jpe?g|webp|avif|gif|bmp)(?:[?#].*)?$/i;
const DIRECT_IMAGE_QUERY_RE = /[?&](?:format|fm|ext|type)=(?:png|jpe?g|webp|avif|gif)\b/i;

const EXTENSIONLESS_IMAGE_CDN_PATTERNS: readonly RegExp[] = [
  /^https?:\/\/pbs\.twimg\.com\/media\//i,
  /^https?:\/\/(?:i|preview)\.redd\.it\//i,
  /^https?:\/\/i\.imgur\.com\//i,
  /^https?:\/\/uploads\.mangadex\.org\/data(?:-saver)?\//i,
  /^https?:\/\/[a-z0-9-]+\.mangadex\.network\/data(?:-saver)?\//i,
  /^https?:\/\/(?:s?webtoon|image-comic|comic)-phinf\.pstatic\.net\//i,
  /^https?:\/\/[ic]\.pximg\.net\/img-/i,
  /^https?:\/\/cdn\.imgchest\.com\/files\//i,
  /^https?:\/\/files\.catbox\.moe\//i,
  /^https?:\/\/(?:cdn|media)\.discordapp\.(?:com|net)\/attachments\//i,
  /^https?:\/\/lh\d+\.googleusercontent\.com\//i,
];

const COMIC_HOST_OR_PATH_RE =
  /(?:mangadex|webtoons?\.com|mangatown|mangakakalot|manganelo|manganato|asura(?:scans|comic)|reaperscans|flamescans|flamecomics|toonily|bato\.to|dynasty-scans|cubari\.moe|comic\.naver|kakaopage|tapas\.io|xkcd\.com|explosm\.net|smbc-comics|gocomics|pixiv\.net|komiku|komikcast|komikindo|kiryuu|shinigami|westmanga|manhuaplus|manhuaus|mangaplus|\/(?:manga|manhwa|manhua|komik|comic|comics|webtoon|chapter[-_/]?\d|ch[-_/]?\d|episode[-_/]?\d|wp-manga)\b)/i;

const AD_OR_NOISE_IMG_RE =
  /(?:\/(?:ads?|advert|sponsor|banners?|logos?|avatars?|profile|icons?|emojis?|smilies|badges?|pixel|beacon|tracker|analytics|promo|sidebar|widget|footer|header|nav|thumb_small)\/|\/(?:site[-_]?logo|ad[-_]?banner|banner\d+x\d+|loading(?:[-_](?:spinner|icon|gif))?|spinner|loader|placeholder|blank|spacer|watermark|qr[-_]?code|donate|patreon|ko-?fi|paypal|discord|favicon)\b(?:\.[a-z]+|$|[-_](?:small|icon|gif|png|webp|jpg|svg|patreon|banner))|gravatar\.com|doubleclick\.net|googlesyndication|facebook\.com\/tr|google-analytics|googletagmanager|scorecardresearch|quantserve|adnxs\.com|\.svg(?:[?#]|$)|1x1\.(?:gif|png))/i;

const DRM_CANVAS_RULES: ReadonlyArray<{ label: string; hostRe?: RegExp; htmlRe?: RegExp }> = [
  {
    label: 'GigaViewer (Shonen Jump+ / Magazine Pocket)',
    hostRe: /(?:shonenjumpplus\.com|tonarinoyj\.jp|pocket\.shonenmagazine\.com|kuragebunch\.com|comic-days\.com|sunday-webry\.com|viewer\.heros-web\.com)/i,
    htmlRe: /episode-json|gigaviewer|scrambled_image/i,
  },
  {
    label: 'MANGA Plus (DRM Canvas)',
    hostRe: /mangaplus\.shueisha\.co\.jp/i,
    htmlRe: /encryption_key|mangaplus/i,
  },
  {
    label: 'Publus / SpeedBinb / ComicWalker',
    hostRe: /(?:comic-walker\.com|comic\.pixiv\.net|bookwalker\.jp|cmoa\.jp|mechacomic\.jp|ebookjapan\.yahoo\.co\.jp)/i,
    htmlRe: /publus|speedbinb|nfbr|scrambleSeed/i,
  },
  {
    label: 'Kakao / Lezhin / Tappytoon / Toomics (DRM)',
    hostRe: /(?:webtoon\.kakao\.com|lezhin\.com|lezhinus\.com|tappytoon\.com|toomics\.com|ridibooks\.com|manta\.net)/i,
    htmlRe: /drm[-_]?canvas|unscramble|canvas-viewer/i,
  },
];

export function isLikelyDirectImageUrl(rawUrl: string): boolean {
  const clean = (rawUrl || '').trim();
  if (!clean) return false;
  if (/^data:image\/(?:png|jpeg|jpg|webp|gif|avif);base64,/i.test(clean)) return true;
  if (!/^https?:\/\//i.test(clean)) return false;
  try {
    const u = new URL(clean);
    if (DIRECT_IMAGE_EXT_RE.test(u.pathname)) return true;
    if (DIRECT_IMAGE_QUERY_RE.test(u.search)) return true;
    if (EXTENSIONLESS_IMAGE_CDN_PATTERNS.some((re) => re.test(clean))) return true;
    return false;
  } catch {
    return false;
  }
}

export function normalizeSocialImageUrl(rawUrl: string): string {
  const clean = (rawUrl || '').trim();
  try {
    const u = new URL(clean);
    if (u.hostname.toLowerCase() === 'pbs.twimg.com' && u.pathname.startsWith('/media/')) {
      u.searchParams.set('name', 'orig');
      if (!u.searchParams.get('format') && !/\.(?:jpg|jpeg|png|webp)$/i.test(u.pathname)) {
        u.searchParams.set('format', 'jpg');
      }
      return u.toString();
    }
    return clean;
  } catch {
    return clean;
  }
}

export function detectDrmCanvasViewer(html: string, rawUrl: string): { isDrm: boolean; reason?: string } {
  const url = rawUrl || '';
  const sample = (html || '').slice(0, 60_000);
  for (const rule of DRM_CANVAS_RULES) {
    const hostHit = rule.hostRe ? rule.hostRe.test(url) : false;
    const htmlHit = rule.htmlRe ? rule.htmlRe.test(sample) : false;
    if (hostHit && (htmlHit || sample.length < 4000 || /<canvas\b/i.test(sample))) {
      return {
        isDrm: true,
        reason: `${rule.label} menggunakan kanvas terenkripsi/DRM. Tangkap layar atau tempel gambar (Ctrl+V) untuk langsung dipindai di tranX.`,
      };
    }
  }
  return { isDrm: false };
}

const MAX_SCAN_HTML_CHARS = 1_500_000;

function resolveSafeHttpUrl(candidate: string, baseUrl: string): string | null {
  const trimmed = (candidate || '').trim().replace(/^['"]|['"]$/g, '');
  if (!trimmed || trimmed.startsWith('data:') || trimmed.startsWith('blob:') || trimmed.startsWith('javascript:')) {
    return null;
  }
  try {
    const resolved = new URL(trimmed, baseUrl).toString();
    const safe = toSafeHttpUrl(resolved);
    return safe ? normalizeSocialImageUrl(safe) : null;
  } catch {
    return null;
  }
}

function stripTagBlocksLinear(input: string, tagNames: readonly string[]): string {
  let out = input.length > MAX_SCAN_HTML_CHARS ? input.slice(0, MAX_SCAN_HTML_CHARS) : input;
  for (const tag of tagNames) {
    const lower = out.toLowerCase();
    const openNeedle = `<${tag}`;
    const closeNeedle = `</${tag}>`;
    const chunks: string[] = [];
    let cursor = 0;
    while (cursor < out.length) {
      const start = lower.indexOf(openNeedle, cursor);
      if (start === -1) {
        chunks.push(out.slice(cursor));
        break;
      }
      const nextCh = lower[start + openNeedle.length] || '';
      if (nextCh && !/[\s>/]/.test(nextCh)) {
        chunks.push(out.slice(cursor, start + openNeedle.length));
        cursor = start + openNeedle.length;
        continue;
      }
      chunks.push(out.slice(cursor, start));
      const end = lower.indexOf(closeNeedle, start + openNeedle.length);
      if (end === -1) break;
      chunks.push(' ');
      cursor = end + closeNeedle.length;
    }
    out = chunks.join('');
  }
  return out;
}

function extractNextDataLinear(html: string): string | null {
  const capped = html.length > MAX_SCAN_HTML_CHARS ? html.slice(0, MAX_SCAN_HTML_CHARS) : html;
  const idPos = capped.search(/id=["']__NEXT_DATA__["']/i);
  if (idPos === -1) return null;
  const gtPos = capped.indexOf('>', idPos);
  if (gtPos === -1) return null;
  const closePos = capped.toLowerCase().indexOf('</script>', gtPos + 1);
  if (closePos === -1 || closePos - gtPos > 300_000) return null;
  return capped.slice(gtPos + 1, closePos);
}

function pickBestFromSrcset(srcset: string): string {
  const entries = srcset
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [u, desc = '1x'] = part.split(/\s+/);
      const wMatch = desc.match(/^(\d+)w$/i);
      const xMatch = desc.match(/^([\d.]+)x$/i);
      const weight = wMatch ? Number(wMatch[1]) : xMatch ? Number(xMatch[1]) * 1000 : 100;
      return { u, weight };
    })
    .filter((e) => Boolean(e.u));
  if (entries.length === 0) return '';
  entries.sort((a, b) => b.weight - a.weight);
  return entries[0].u;
}

function isLikelyComicImageCandidate(url: string, alt: string, classHint: string, widthAttr: number, heightAttr: number): boolean {
  if (!url || AD_OR_NOISE_IMG_RE.test(url)) return false;
  if (AD_OR_NOISE_IMG_RE.test(classHint) || /\b(?:logo|avatar|icon|banner|ad|sponsor)\b/i.test(alt)) {
    return false;
  }
  // Reject tiny icons/avatars when explicit dimensions are present (keep 0/unspecified lazy images!)
  if (widthAttr > 0 && heightAttr > 0 && widthAttr < 180 && heightAttr < 180) return false;
  if (widthAttr > 0 && heightAttr > 0) {
    const ratio = widthAttr / heightAttr;
    // Reject ultra-wide ad leaderboards (728x90 = 8.08) unless inside comic strip container
    if (ratio > 5.5 && heightAttr < 160 && !/comic|strip|4koma|manga/i.test(classHint)) return false;
  }
  return true;
}

function extractImagesFromScriptPayloads(html: string, baseUrl: string): string[] {
  const found: string[] = [];
  if (!html) return found;
  const unescaped = (html.length > MAX_SCAN_HTML_CHARS ? html.slice(0, MAX_SCAN_HTML_CHARS) : html).replace(
    /\\\//g,
    '/'
  );

  // 1. MangaStream / Themesia: ts_reader.run({... "images":["..."] ...})
  const tsMatch = unescaped.match(/ts_reader\.run\(\s*(\{[\s\S]{10,120000}?\})\s*\)/);
  if (tsMatch) {
    try {
      const obj = JSON.parse(tsMatch[1]);
      const sources = Array.isArray(obj?.sources) ? obj.sources : [];
      for (const s of sources) {
        if (Array.isArray(s?.images)) {
          for (const u of s.images) {
            if (typeof u === 'string') {
              const abs = resolveSafeHttpUrl(u, baseUrl);
              if (abs) found.push(abs);
            }
          }
          if (found.length > 0) return found;
        }
      }
    } catch {
      // ignore malformed inline script JSON
    }
  }

  // 2. Madara / WP-Manga / Generic JS arrays: chapter_preloaded_images / imgHttps / page_images / chapterImages
  const arrayPatterns = [
    /(?:chapter_preloaded_images|imgHttps|page_images|chapterImages|manga_images)\s*[:=]\s*(\[[\s\S]{6,80000}?\])/gi,
    /"(?:images|pages|imageUrls|chapterImages)"\s*:\s*(\[\s*"https?:\/\/[\s\S]{6,80000}?\])/gi,
  ];
  for (const pat of arrayPatterns) {
    let m: RegExpExecArray | null;
    while ((m = pat.exec(unescaped)) !== null) {
      try {
        const arr = JSON.parse(m[1]);
        if (Array.isArray(arr)) {
          for (const item of arr) {
            const raw = typeof item === 'string' ? item : typeof item?.src === 'string' ? item.src : typeof item?.url === 'string' ? item.url : '';
            const abs = resolveSafeHttpUrl(raw, baseUrl);
            if (abs && !AD_OR_NOISE_IMG_RE.test(abs)) found.push(abs);
          }
          if (found.length >= 2) return found;
        }
      } catch {
        const urlHits = m[1].match(/https?:\/\/[^"'\s\\\]]+/g) || [];
        for (const raw of urlHits) {
          const abs = resolveSafeHttpUrl(raw, baseUrl);
          if (abs && !AD_OR_NOISE_IMG_RE.test(abs)) found.push(abs);
        }
        if (found.length >= 2) return found;
      }
    }
  }

  // 3. __NEXT_DATA__ script block (linear O(N) scan immune to ReDoS)
  const nextRaw = extractNextDataLinear(unescaped);
  if (nextRaw) {
    try {
      const nextJson = JSON.parse(nextRaw);
      const stack: unknown[] = [nextJson];
      let visited = 0;
      while (stack.length > 0 && visited < 4000) {
        visited += 1;
        const cur = stack.pop();
        if (Array.isArray(cur)) {
          const strUrls = cur
            .map((item) =>
              typeof item === 'string'
                ? item
                : item && typeof item === 'object'
                  ? String((item as Record<string, unknown>).url || (item as Record<string, unknown>).src || (item as Record<string, unknown>).imageUrl || '')
                  : ''
            )
            .filter((u) => isLikelyDirectImageUrl(u) && !AD_OR_NOISE_IMG_RE.test(u));
          if (strUrls.length >= 3) {
            for (const u of strUrls) {
              const abs = resolveSafeHttpUrl(u, baseUrl);
              if (abs) found.push(abs);
            }
            return found;
          }
          for (const item of cur) {
            if (item && typeof item === 'object') stack.push(item);
          }
        } else if (cur && typeof cur === 'object') {
          for (const val of Object.values(cur as Record<string, unknown>)) {
            if (val && typeof val === 'object') stack.push(val);
          }
        }
      }
    } catch {
      // ignore
    }
  }

  return found;
}

const COMIC_CONTAINER_HINT_RE =
  /(?:reading-content|wp-manga|readerarea|chapter-content|chapter-reader|container-chapter-reader|viewer_lst|_imageList|comic-pages|manga-pages|page-break|comic|xkcd|webtoon|manhwa|manhua|ch-images|img-list)/i;

export function detectComicLayout(
  pages: MangaPageItem[],
  html: string,
  url: string
): ComicLayoutMode {
  if (pages.length === 1) {
    const p = pages[0];
    if (p.width && p.height && p.height / p.width >= 2.6) return 'webtoon_strip';
    if (/(?:4koma|yonkoma|4-koma)/i.test(`${url} ${html.slice(0, 4000)}`)) return 'four_koma';
    if (/(?:webtoon|manhwa|manhua|pstatic\.net|tapas|kakao)/i.test(`${url} ${p.url}`)) return 'webtoon_strip';
    if (/(?:xkcd|explosm|smbc|gocomics|dilbert|garfield|calvin|marvel|dccomics|webcomic)/i.test(url)) {
      return 'ltr_comic';
    }
    return 'single_image';
  }
  const combined = `${url} ${html.slice(0, 8000)} ${pages.slice(0, 5).map((p) => p.url).join(' ')}`;
  if (/(?:webtoon|manhwa|manhua|pstatic\.net|asura|reaperscans|flamecomics|toonily|tapas|kakao|naver)/i.test(combined)) {
    return 'webtoon_strip';
  }
  if (/(?:4koma|yonkoma|4-koma)/i.test(combined)) {
    return 'four_koma';
  }
  if (/(?:xkcd|explosm|smbc|gocomics|marvel|dccomics|imagecomics|readcomiconline|western)/i.test(combined)) {
    return 'ltr_comic';
  }
  return 'rtl_manga';
}

/**
 * Pure parser usable in BOTH Browser DOM and Node/TS tests (works via regex HTML parser fallback
 * when DOMParser is unavailable so our 300-manga automated benchmark runs deterministically in Node!).
 */
export function extractMangaPagesFromHtml(
  html: string,
  baseUrl: string,
  options?: {
    proseParagraphCount?: number;
    proseCharCount?: number;
    jinaLinks?: Array<{ title: string; url: string }>;
  }
): MangaLinkMeta {
  const drm = detectDrmCanvasViewer(html, baseUrl);
  const proseParas = options?.proseParagraphCount ?? 0;
  const proseChars = options?.proseCharCount ?? 0;

  if (isLikelyDirectImageUrl(baseUrl)) {
    const norm = normalizeSocialImageUrl(baseUrl);
    return {
      isComic: true,
      isDirectImage: true,
      layout: 'single_image',
      pageCount: 1,
      pages: [{ index: 0, url: norm, alt: 'Gambar langsung' }],
      drmProtected: false,
    };
  }

  const orderedUrls: Array<{ url: string; alt: string; score: number; w?: number; h?: number }> = [];
  const seen = new Set<string>();
  const addUrl = (raw: string, alt: string, score: number, w?: number, h?: number) => {
    const abs = resolveSafeHttpUrl(raw, baseUrl);
    if (!abs || seen.has(abs) || AD_OR_NOISE_IMG_RE.test(abs)) return;
    seen.add(abs);
    orderedUrls.push({ url: abs, alt, score, w, h });
  };

  // Stage 1: Safe JSON script extractors (ts_reader, chapter_preloaded_images, __NEXT_DATA__)
  const scriptUrls = extractImagesFromScriptPayloads(html, baseUrl);
  for (const u of scriptUrls) {
    addUrl(u, '', 10);
  }

  // Stage 2: Scan <img> tags (with full lazy-load attribute priority chain & O(N) linear tag stripping)
  if (orderedUrls.length < 2 && html) {
    const cleanedHtml = stripTagBlocksLinear(html, ['script', 'style', 'nav', 'footer', 'aside']);

    // Find container hints around img tags
    const imgTagRe = /<img\b([^>]{4,2000})>/gi;
    let m: RegExpExecArray | null;
    while ((m = imgTagRe.exec(cleanedHtml)) !== null) {
      const attrs = m[1];
      const getAttr = (name: string): string => {
        const am = attrs.match(new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s"'>]+))`, 'i'));
        return (am?.[1] || am?.[2] || am?.[3] || '').trim();
      };

      const dataUrl = getAttr('data-url');
      const dataSrc = getAttr('data-src');
      const dataOrig = getAttr('data-original');
      const dataLazy = getAttr('data-lazy-src');
      const dataCf = getAttr('data-cfsrc');
      const dataActual = getAttr('data-actualsrc');
      const dataEcho = getAttr('data-echo');
      const srcsetBest = pickBestFromSrcset(getAttr('data-srcset') || getAttr('srcset'));
      const src = getAttr('src');

      const chosen =
        dataUrl || dataSrc || dataOrig || dataLazy || dataCf || dataActual || dataEcho || srcsetBest || src;
      if (!chosen) continue;

      const alt = getAttr('alt');
      const cls = `${getAttr('class')} ${getAttr('id')}`;
      const w = Number.parseInt(getAttr('width'), 10) || 0;
      const h = Number.parseInt(getAttr('height'), 10) || 0;

      const abs = resolveSafeHttpUrl(chosen, baseUrl);
      if (!abs) continue;
      if (!isLikelyComicImageCandidate(abs, alt, cls, w, h)) continue;

      const surrounding = cleanedHtml.slice(Math.max(0, m.index - 280), m.index);
      let score = 2;
      if (dataUrl || dataSrc || dataOrig || dataLazy) score += 2;
      if (COMIC_CONTAINER_HINT_RE.test(cls) || COMIC_CONTAINER_HINT_RE.test(surrounding)) score += 4;
      if (/wp-manga-chapter-img|_images|chapter|page[-_]?\d|ch[-_]?\d/i.test(`${cls} ${abs}`)) score += 3;
      if (w >= 450 || h >= 450) score += 2;
      if (w >= 600 && h >= 1200) score += 3; // vertical webtoon slice
      addUrl(abs, alt, score, w || undefined, h || undefined);
    }
  }

  // Stage 3: Check Jina links for explicit comic image URLs if HTML had none
  if (orderedUrls.length === 0 && options?.jinaLinks?.length) {
    for (const link of options.jinaLinks) {
      if (isLikelyDirectImageUrl(link.url) && !AD_OR_NOISE_IMG_RE.test(link.url)) {
        addUrl(link.url, link.title || '', 3);
      }
    }
  }

  // Filter out low-confidence thumbnails if we already have high-confidence chapter pages
  const highScore = orderedUrls.filter((x) => x.score >= 5);
  const chosenList = highScore.length >= 2 ? highScore : orderedUrls;

  // Determine whether this page is genuinely a Manga/Comic/Image page (vs a text novel with 1 illustration!)
  const comicSignal = COMIC_HOST_OR_PATH_RE.test(baseUrl) || COMIC_CONTAINER_HINT_RE.test(html.slice(0, 60_000));
  const totalScore = chosenList.reduce((acc, item) => acc + item.score, 0);
  const isHeavyNovelProse = proseParas >= 10 && proseChars >= 1400;

  let isComic = false;
  if (drm.isDrm && proseChars < 800) {
    isComic = true;
  } else if (chosenList.length >= 3 && (!isHeavyNovelProse || comicSignal || totalScore >= 18)) {
    isComic = true;
  } else if (chosenList.length >= 1 && comicSignal && proseChars < 900) {
    isComic = true;
  } else if (chosenList.length === 1 && chosenList[0].score >= 5 && proseChars < 450) {
    isComic = true;
  }

  const pages: MangaPageItem[] = chosenList.slice(0, 120).map((item, idx) => ({
    index: idx,
    url: item.url,
    alt: item.alt || `Halaman ${idx + 1}`,
    width: item.w,
    height: item.h,
  }));

  const layout = detectComicLayout(pages, html, baseUrl);
  return {
    isComic,
    isDirectImage: false,
    layout,
    pageCount: pages.length,
    pages,
    drmProtected: drm.isDrm,
    drmReason: drm.reason,
  };
}

/* 2. Gutter-Aware Tall Vertical Strip Tiling & Cross-Tile IoU Stitching */

export interface StripTileSpec {
  index: number;
  yStart: number;
  yEnd: number;
  height: number;
}

export const MAX_MANGA_STRIP_HEIGHT = 65_536;
export const MAX_MANGA_STRIP_PIXELS = 36_000_000;

export function planVerticalStripTiles(
  _width: number,
  height: number,
  options?: {
    isConstrained?: boolean;
    overlapPx?: number;
    rowVarianceFn?: (y: number) => number;
  }
): StripTileSpec[] {
  const maxTileH = options?.isConstrained ? 1500 : 2100;
  const overlap = options?.overlapPx ?? 140;
  if (height <= maxTileH) {
    return [{ index: 0, yStart: 0, yEnd: height, height }];
  }

  const tiles: StripTileSpec[] = [];
  const snapBackMax = options?.rowVarianceFn ? 120 : 0;
  const minStep = Math.max(200, maxTileH - snapBackMax - overlap);
  const maxTiles = Math.min(128, Math.ceil(height / minStep) + 2);
  let y = 0;
  let idx = 0;
  while (y < height && idx < maxTiles) {
    let targetEnd = Math.min(height, y + maxTileH);
    // Gutter-aware seam snapping: search +/-120px window for lowest horizontal pixel variance
    if (targetEnd < height && options?.rowVarianceFn) {
      let bestY = targetEnd;
      let bestVar = Infinity;
      const lo = Math.max(y + 400, targetEnd - 120);
      const hi = Math.min(height - 1, targetEnd + 80);
      for (let cand = lo; cand <= hi; cand += 4) {
        const v = options.rowVarianceFn(cand);
        if (v < bestVar) {
          bestVar = v;
          bestY = cand;
        }
      }
      targetEnd = bestY;
    }
    tiles.push({ index: idx, yStart: y, yEnd: targetEnd, height: targetEnd - y });
    if (targetEnd >= height) break;
    y = Math.max(y + 200, targetEnd - overlap);
    idx += 1;
  }
  return tiles;
}

export function computeBoxIoU(a: [number, number, number, number], b: [number, number, number, number]): number {
  const ax1 = a[0];
  const ay1 = a[1];
  const ax2 = a[0] + a[2];
  const ay2 = a[1] + a[3];
  const bx1 = b[0];
  const by1 = b[1];
  const bx2 = b[0] + b[2];
  const by2 = b[1] + b[3];

  const ix1 = Math.max(ax1, bx1);
  const iy1 = Math.max(ay1, by1);
  const ix2 = Math.min(ax2, bx2);
  const iy2 = Math.min(ay2, by2);
  const inter = Math.max(0, ix2 - ix1) * Math.max(0, iy2 - iy1);
  if (inter <= 0) return 0;
  const union = a[2] * a[3] + b[2] * b[3] - inter;
  return union > 0 ? inter / union : 0;
}

export function dedupeAndStitchTileBlocks<T extends { box: [number, number, number, number]; src: string }>(
  items: T[]
): T[] {
  const kept: T[] = [];
  for (const cand of items) {
    let merged = false;
    for (let i = 0; i < kept.length; i++) {
      const existing = kept[i];
      const iou = computeBoxIoU(existing.box, cand.box);
      const sameText =
        existing.src.trim().toLowerCase() === cand.src.trim().toLowerCase() ||
        (cand.src.length >= 4 && existing.src.includes(cand.src)) ||
        (existing.src.length >= 4 && cand.src.includes(existing.src));
      if (iou >= 0.35 || (iou >= 0.16 && sameText)) {
        // Keep the fuller text AND true union bounding box across tile overlap seams
        const minX = Math.min(existing.box[0], cand.box[0]);
        const minY = Math.min(existing.box[1], cand.box[1]);
        const maxX = Math.max(existing.box[0] + existing.box[2], cand.box[0] + cand.box[2]);
        const maxY = Math.max(existing.box[1] + existing.box[3], cand.box[1] + cand.box[3]);
        const winner = cand.src.length > existing.src.length ? cand : existing;
        kept[i] = {
          ...winner,
          box: [minX, minY, maxX - minX, maxY - minY],
        };
        merged = true;
        break;
      }
    }
    if (!merged) kept.push(cand);
  }
  return kept;
}

/* 3. OCR Spatial Line-to-Bubble Clustering & Manga Reading-Order Solver */

export interface RawOcrBox {
  id: number;
  box: [number, number, number, number]; // pixel [x, y, w, h]
  text: string;
  kind?: VisionBlockKind;
  shape?: VisionBlockShape;
  bgTone?: VisionBgTone;
  writingDir?: 'vertical' | 'horizontal';
  sfxImportance?: 'none' | 'ambient' | 'impact' | 'narrative' | 'major' | 'minor' | 'plot_critical';
}

export function clusterOcrBoxes(boxes: RawOcrBox[], writingDir: 'vertical' | 'horizontal' = 'horizontal'): RawOcrBox[] {
  if (boxes.length <= 1) return boxes;
  const items = boxes.map((b) => {
    const [, , bw, bh] = b.box;
    const inferredDir: 'vertical' | 'horizontal' =
      b.writingDir || (bh > bw * 1.45 ? 'vertical' : bw > bh * 1.45 ? 'horizontal' : writingDir);
    return { ...b, writingDir: inferredDir, box: [...b.box] as [number, number, number, number] };
  });
  const n = items.length;
  const parent = Array.from({ length: n }, (_, i) => i);
  const find = (i: number): number => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]];
      i = parent[i];
    }
    return i;
  };
  const unite = (i: number, j: number) => {
    const ri = find(i);
    const rj = find(j);
    if (ri !== rj) parent[ri] = rj;
  };

  // Transitive union-find clustering respects per-box orientation so vertical dialogue never fuses with horizontal captions
  for (let i = 0; i < n; i++) {
    const [ax, ay, aw, ah] = items[i].box;
    const dirA = items[i].writingDir || writingDir;
    for (let j = i + 1; j < n; j++) {
      const dirB = items[j].writingDir || writingDir;
      if (dirA !== dirB) continue;
      const [bx, by, bw, bh] = items[j].box;
      let touches = false;
      if (dirA === 'vertical') {
        const xGap = Math.max(0, Math.max(ax - (bx + bw), bx - (ax + aw)));
        const yOverlap = Math.min(ay + ah, by + bh) - Math.max(ay, by);
        touches = xGap <= Math.max(aw, bw) * 0.65 && yOverlap >= Math.min(ah, bh) * 0.4;
      } else {
        const yGap = Math.max(0, Math.max(ay - (by + bh), by - (ay + ah)));
        const xOverlap = Math.min(ax + aw, bx + bw) - Math.max(ax, bx);
        touches = yGap <= Math.max(ah, bh) * 0.55 && xOverlap >= Math.min(aw, bw) * 0.35;
      }
      if (touches) unite(i, j);
    }
  }

  const byRoot = new Map<number, typeof items>();
  for (let i = 0; i < n; i++) {
    const r = find(i);
    const grp = byRoot.get(r);
    if (grp) grp.push(items[i]);
    else byRoot.set(r, [items[i]]);
  }

  return Array.from(byRoot.values()).map((cluster, idx) => {
    if (cluster.length === 1) return { ...cluster[0], id: idx + 1 };
    const clusterDir = cluster[0].writingDir || writingDir;
    const sorted = [...cluster].sort((a, b) =>
      clusterDir === 'vertical'
        ? b.box[0] - a.box[0] || a.box[1] - b.box[1]
        : a.box[1] - b.box[1] || a.box[0] - b.box[0]
    );
    const minX = Math.min(...sorted.map((c) => c.box[0]));
    const minY = Math.min(...sorted.map((c) => c.box[1]));
    const maxX = Math.max(...sorted.map((c) => c.box[0] + c.box[2]));
    const maxY = Math.max(...sorted.map((c) => c.box[1] + c.box[3]));
    const joiner = clusterDir === 'vertical' ? '' : ' ';
    return {
      ...sorted[0],
      id: idx + 1,
      box: [minX, minY, maxX - minX, maxY - minY],
      text: sorted.map((c) => c.text.trim()).join(joiner).trim(),
    };
  });
}

export function sortMangaReadingOrder<
  T extends { box: [number, number, number, number]; kind?: VisionBlockKind }
>(
  blocks: T[],
  layout: ComicLayoutMode,
  imgW: number,
  imgH: number,
  allowSpreadSplit = true
): T[] {
  if (blocks.length <= 1) return blocks;
  const cx = (b: T) => b.box[0] + b.box[2] / 2;
  const cy = (b: T) => b.box[1] + b.box[3] / 2;
  const sfxRank = (b: T) => (b.kind === 'sfx' ? 1 : 0);

  if (layout === 'webtoon_strip') {
    return [...blocks].sort((a, b) => a.box[1] - b.box[1] || sfxRank(a) - sfxRank(b) || a.box[0] - b.box[0]);
  }

  const isSpread = allowSpreadSplit && layout === 'rtl_manga' && imgW > imgH * 1.15;
  if (isSpread) {
    const midX = imgW / 2;
    const rightHalf = blocks.filter((b) => cx(b) >= midX);
    const leftHalf = blocks.filter((b) => cx(b) < midX);
    return [
      ...sortMangaReadingOrder(rightHalf, 'rtl_manga', imgW / 2, imgH, false),
      ...sortMangaReadingOrder(leftHalf, 'rtl_manga', imgW / 2, imgH, false),
    ];
  }

  if (layout === 'four_koma') {
    const midX = imgW / 2;
    const rightCol = blocks.filter((b) => cx(b) >= midX);
    const leftCol = blocks.filter((b) => cx(b) < midX);
    if (rightCol.length > 0 && leftCol.length > 0) {
      return [
        ...rightCol.sort((a, b) => a.box[1] - b.box[1] || b.box[0] - a.box[0]),
        ...leftCol.sort((a, b) => a.box[1] - b.box[1] || b.box[0] - a.box[0]),
      ];
    }
    return [...blocks].sort((a, b) => a.box[1] - b.box[1] || b.box[0] - a.box[0]);
  }

  // Recursive XY-Cut panel-gutter reading order (Ha et al. 1995 / Comic MT panel-tree reading)
  const isRtl = layout === 'rtl_manga';
  const minYGap = Math.max(12, Math.round(imgH * 0.015));
  const minXGap = Math.max(12, Math.round(imgW * 0.018));

  const xyCut = (group: T[], depth: number): T[] => {
    if (group.length <= 1 || depth > 6) return group;

    // 1. Horizontal panel-row gutter cut (top-to-bottom)
    const byY = [...group].sort((a, b) => a.box[1] - b.box[1]);
    let bestYGap = 0;
    let bestYIdx = -1;
    let runMaxY = byY[0].box[1] + byY[0].box[3];
    for (let i = 1; i < byY.length; i += 1) {
      const gap = byY[i].box[1] - runMaxY;
      if (gap > bestYGap) {
        bestYGap = gap;
        bestYIdx = i;
      }
      runMaxY = Math.max(runMaxY, byY[i].box[1] + byY[i].box[3]);
    }
    if (bestYIdx > 0 && bestYGap >= minYGap) {
      return [...xyCut(byY.slice(0, bestYIdx), depth + 1), ...xyCut(byY.slice(bestYIdx), depth + 1)];
    }

    // 2. Vertical panel-column gutter cut (RTL for manga, LTR for western)
    const byX = [...group].sort((a, b) => a.box[0] - b.box[0]);
    let bestXGap = 0;
    let bestXIdx = -1;
    let runMaxX = byX[0].box[0] + byX[0].box[2];
    for (let i = 1; i < byX.length; i += 1) {
      const gap = byX[i].box[0] - runMaxX;
      if (gap > bestXGap) {
        bestXGap = gap;
        bestXIdx = i;
      }
      runMaxX = Math.max(runMaxX, byX[i].box[0] + byX[i].box[2]);
    }
    if (bestXIdx > 0 && bestXGap >= minXGap) {
      const leftPart = xyCut(byX.slice(0, bestXIdx), depth + 1);
      const rightPart = xyCut(byX.slice(bestXIdx), depth + 1);
      return isRtl ? [...rightPart, ...leftPart] : [...leftPart, ...rightPart];
    }

    // 3. Leaf panel fallback: band sort + dialogue-before-SFX tie-breaker
    const bandH = Math.max(70, Math.round(imgH * 0.16));
    return [...group].sort((a, b) => {
      const bandDiff = Math.floor(cy(a) / bandH) - Math.floor(cy(b) / bandH);
      if (bandDiff !== 0) return bandDiff;
      const sfxDiff = sfxRank(a) - sfxRank(b);
      if (sfxDiff !== 0) return sfxDiff;
      return isRtl ? cx(b) - cx(a) : cx(a) - cx(b);
    });
  };

  return xyCut(blocks, 0);
}

/* 4. Western Comic ALL-CAPS Normalizer (preserves acronyms & RPG stats) */

const PRESERVE_ACRONYMS = new Set([
  'I', 'OK', 'TV', 'ID', 'AI', 'UI', 'API', 'FBI', 'CIA', 'NSA', 'USA', 'UK', 'UN', 'EU',
  'NASA', 'CEO', 'CTO', 'VIP', 'DNA', 'RNA', 'RPG', 'HP', 'MP', 'SP', 'XP', 'EXP', 'ATK',
  'DEF', 'AGI', 'INT', 'STR', 'DEX', 'VIT', 'LUK', 'LV', 'LVL', 'MAX', 'MIN', 'KO', 'SFX',
  'SSR', 'SSS', 'SS', 'SR', 'UR', 'NPC', 'BOSS', 'GM', 'DM', 'HUD', 'SOS', 'ATM', 'GPS',
]);

export function normalizeComicAllCaps(text: string): string {
  const clean = (text || '').trim();
  if (!clean) return clean;
  const letters = clean.replace(/[^A-Za-z]/g, '');
  if (letters.length < 4) return clean;
  const upperCount = (letters.match(/[A-Z]/g) || []).length;
  if (upperCount / letters.length < 0.82) return clean;

  // Lowercase words except preserved acronyms, then capitalize sentence starts & pronoun I
  let lower = clean
    .split(/(\s+)/)
    .map((tok) => {
      const stripped = tok.replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, '');
      if (PRESERVE_ACRONYMS.has(stripped)) return tok;
      return tok.toLowerCase();
    })
    .join('');

  lower = lower.replace(
    /(^|[.!?]\s+|(?:^|\s)["'(])([a-z])/g,
    (_m, lead: string, ch: string) => `${lead}${ch.toUpperCase()}`
  );
  lower = lower.replace(/\bi(['’](?:m|ve|ll|d))?\b/g, (_m, suf: string | undefined) => `I${suf || ''}`);
  return lower;
}

/* 5. Studio-Quality Background-Sampled & Chord-Fitted Manga Overlay Renderer */

function relativeLuminance(r: number, g: number, b: number): number {
  const toLin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * toLin(r) + 0.7152 * toLin(g) + 0.0722 * toLin(b);
}

export function contrastRatioRgb(a: [number, number, number], b: [number, number, number]): number {
  const l1 = relativeLuminance(a[0], a[1], a[2]);
  const l2 = relativeLuminance(b[0], b[1], b[2]);
  const hi = Math.max(l1, l2);
  const lo = Math.min(l1, l2);
  return (hi + 0.05) / (lo + 0.05);
}

function sampleBubbleBackground(
  ctx: CanvasRenderingContext2D,
  box: [number, number, number, number],
  canvasW: number,
  canvasH: number,
  hintTone: VisionBgTone | undefined,
  resolvedTheme: ResolvedTheme
): {
  fill: [number, number, number];
  topFill: [number, number, number];
  bottomFill: [number, number, number];
  useGradient: boolean;
  isScreentone: boolean;
  isDark: boolean;
  sampled: boolean;
} {
  const fallback: [number, number, number] =
    hintTone === 'dark' || (hintTone === undefined && resolvedTheme === 'Gelap')
      ? [22, 26, 25]
      : [252, 252, 250];
  try {
    const [bx, by, bw, bh] = box;
    // Sample a clean 4px outer halo ring right outside the tight OCR text box so letter ink never skews median color
    const margin = Math.max(3, Math.min(8, Math.round(Math.min(bw, bh) * 0.14)));
    const sx = Math.max(0, Math.min(canvasW - 1, Math.round(bx - margin)));
    const sy = Math.max(0, Math.min(canvasH - 1, Math.round(by - margin)));
    const ex = Math.min(canvasW, Math.round(bx + bw + margin));
    const ey = Math.min(canvasH, Math.round(by + bh + margin));
    const sw = Math.max(1, ex - sx);
    const sh = Math.max(1, ey - sy);
    const data = ctx.getImageData(sx, sy, sw, sh).data;

    const rs: number[] = [];
    const gs: number[] = [];
    const bs: number[] = [];
    const topR: number[] = [];
    const topG: number[] = [];
    const topB: number[] = [];
    const botR: number[] = [];
    const botG: number[] = [];
    const botB: number[] = [];
    const lums: number[] = [];
    const stepX = Math.max(1, Math.floor(sw / 18));
    const stepY = Math.max(1, Math.floor(sh / 18));

    const pushPixel = (px: number, py: number, zone: 'top' | 'bot' | 'side') => {
      const idx = (py * sw + px) * 4;
      if (idx + 3 < data.length && data[idx + 3] > 200) {
        const r = data[idx];
        const g = data[idx + 1];
        const b = data[idx + 2];
        rs.push(r);
        gs.push(g);
        bs.push(b);
        lums.push(0.2126 * r + 0.7152 * g + 0.0722 * b);
        if (zone === 'top') {
          topR.push(r);
          topG.push(g);
          topB.push(b);
        } else if (zone === 'bot') {
          botR.push(r);
          botG.push(g);
          botB.push(b);
        }
      }
    };

    for (let x = 0; x < sw; x += stepX) {
      pushPixel(x, 0, 'top');
      pushPixel(x, Math.max(0, sh - 1), 'bot');
    }
    for (let y = 1; y < sh - 1; y += stepY) {
      pushPixel(0, y, 'side');
      pushPixel(Math.max(0, sw - 1), y, 'side');
    }

    if (rs.length >= 6) {
      const med = (arr: number[]) => {
        const s = [...arr].sort((a, b) => a - b);
        return s[Math.floor(s.length / 2)];
      };
      const fill: [number, number, number] = [med(rs), med(gs), med(bs)];
      const topFill: [number, number, number] =
        topR.length >= 3 ? [med(topR), med(topG), med(topB)] : fill;
      const bottomFill: [number, number, number] =
        botR.length >= 3 ? [med(botR), med(botG), med(botB)] : fill;
      const gradDist = Math.hypot(
        topFill[0] - bottomFill[0],
        topFill[1] - bottomFill[1],
        topFill[2] - bottomFill[2]
      );
      const meanLum = lums.reduce((a, b) => a + b, 0) / lums.length;
      const lumStdDev = Math.sqrt(
        lums.reduce((acc, l) => acc + (l - meanLum) * (l - meanLum), 0) / lums.length
      );
      const lum = relativeLuminance(fill[0], fill[1], fill[2]);
      return {
        fill,
        topFill,
        bottomFill,
        useGradient: gradDist > 14,
        isScreentone: lumStdDev > 44,
        isDark: lum < 0.32,
        sampled: true,
      };
    }
  } catch {
    // Tainted cross-origin canvas -> clean deterministic fallback
  }
  const isDark = hintTone === 'dark' || (hintTone === undefined && resolvedTheme === 'Gelap');
  return {
    fill: fallback,
    topFill: fallback,
    bottomFill: fallback,
    useGradient: false,
    isScreentone: false,
    isDark,
    sampled: false,
  };
}

function wrapTextToLines(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
  chordWidthFn?: (lineIdx: number, totalEstLines: number) => number
): string[] {
  const words = text.replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  if (words.length === 0) return [];
  const totalEst = Math.max(1, Math.ceil((ctx.measureText(text).width || 1) / Math.max(24, maxWidth * 0.82)));
  const getLimit = (idx: number) =>
    Math.max(28, chordWidthFn ? chordWidthFn(idx, totalEst) : maxWidth);
  const lines: string[] = [];
  let cur = '';
  for (const word of words) {
    const lineLimit = getLimit(lines.length);
    const cand = cur ? `${cur} ${word}` : word;
    if (ctx.measureText(cand).width <= lineLimit) {
      cur = cand;
    } else if (cur) {
      lines.push(cur);
      cur = word;
    } else {
      // Single ultra-long or space-less CJK word: recompute chord width on every new line!
      let slice = '';
      for (const ch of word) {
        const dynLimit = getLimit(lines.length);
        if (ctx.measureText(slice + ch).width > dynLimit && slice) {
          lines.push(slice);
          slice = ch;
        } else {
          slice += ch;
        }
      }
      cur = slice;
    }
  }
  if (cur) lines.push(cur);
  return lines;
}

function fitTextBinarySearch(
  ctx: CanvasRenderingContext2D,
  text: string,
  boxW: number,
  boxH: number,
  isOval: boolean,
  fontFamily: string,
  fontWeight: string
): { fontSize: number; lines: string[]; lineHeight: number } {
  const isWideBanner = boxW > boxH * 2.2;
  const padX = Math.max(6, Math.round(boxW * (isWideBanner ? 0.04 : isOval ? 0.1 : 0.06)));
  const padY = Math.max(4, Math.round(boxH * (isWideBanner ? 0.06 : isOval ? 0.1 : 0.06)));
  const innerW = Math.max(28, boxW - padX * 2);
  const innerH = Math.max(18, boxH - padY * 2);

  let lo = 10;
  let hi = Math.min(38, Math.max(15, Math.round(Math.min(boxW * 0.44, boxH * 0.72))));
  const rx = innerW / 2;

  const makeChordFn = (useOval: boolean) =>
    useOval && !isWideBanner
      ? (lineIdx: number, estLines: number) => {
        const frac = ((lineIdx + 0.5) / Math.max(1, estLines)) * 2 - 1;
        const clamped = Math.max(-0.82, Math.min(0.82, frac));
        const chord = 2 * rx * Math.sqrt(Math.max(0.28, 1 - clamped * clamped));
        return Math.max(innerW * 0.62, Math.min(innerW, chord));
      }
      : undefined;

  // Always initialize `best` with properly wrapped lines at min font size so unwrapped single-line overflow is impossible!
  ctx.font = `${fontWeight} ${lo}px ${fontFamily}`;
  let best = {
    fontSize: lo,
    lines: wrapTextToLines(ctx, text, innerW, makeChordFn(false)),
    lineHeight: Math.round(lo * 1.24),
  };

  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const lh = Math.round(mid * 1.24);
    ctx.font = `${fontWeight} ${mid}px ${fontFamily}`;
    const lines = wrapTextToLines(ctx, text, innerW, makeChordFn(isOval));
    const totalH = lines.length * lh;
    const widest = Math.max(0, ...lines.map((l) => ctx.measureText(l).width));
    if (totalH <= innerH && widest <= innerW * 1.02) {
      best = { fontSize: mid, lines, lineHeight: lh };
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  // Enforce strict vertical line budget with ellipsis only when text exceeds even 9px capacity
  const maxLines = Math.max(1, Math.floor(innerH / best.lineHeight));
  if (best.lines.length > maxLines) {
    const trimmed = best.lines.slice(0, maxLines);
    const last = trimmed[maxLines - 1];
    trimmed[maxLines - 1] = last.length > 3 ? `${last.slice(0, Math.max(1, last.length - 1))}...` : `${last}...`;
    best = { ...best, lines: trimmed };
  }
  return best;
}

const MAX_BROWSER_CANVAS_SIDE = 12_000;
const MAX_BROWSER_CANVAS_AREA = 16_777_216;

export interface RenderOverlayOptions {
  resolvedTheme: ResolvedTheme;
  showSfx?: boolean;
  highlightBlockId?: number | null;
}

export function renderMangaOverlayToCanvas(
  canvas: HTMLCanvasElement,
  imgEl: HTMLImageElement | null,
  blocks: VisionBlock[],
  width: number,
  height: number,
  opts: RenderOverlayOptions
): void {
  const srcW = Math.max(1, Math.round(width || imgEl?.naturalWidth || 640));
  const srcH = Math.max(1, Math.round(height || imgEl?.naturalHeight || 480));
  // Preserve exact aspect ratio while clamping inside browser GPU limits (Safari 16384 / Chrome 32767)
  let scale = 1;
  if (srcW > MAX_BROWSER_CANVAS_SIDE) scale = Math.min(scale, MAX_BROWSER_CANVAS_SIDE / srcW);
  if (srcH > MAX_BROWSER_CANVAS_SIDE) scale = Math.min(scale, MAX_BROWSER_CANVAS_SIDE / srcH);
  if (srcW * srcH * scale * scale > MAX_BROWSER_CANVAS_AREA) {
    scale = Math.min(scale, Math.sqrt(MAX_BROWSER_CANVAS_AREA / (srcW * srcH)));
  }
  const w = Math.max(1, Math.round(srcW * scale));
  const h = Math.max(1, Math.round(srcH * scale));
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return;

  ctx.fillStyle = opts.resolvedTheme === 'Gelap' ? '#171B1A' : '#FAFBFA';
  ctx.fillRect(0, 0, w, h);
  if (imgEl && imgEl.complete && imgEl.naturalWidth > 0) {
    ctx.drawImage(imgEl, 0, 0, w, h);
  }

  const showSfx = opts.showSfx !== false;
  const comicSans = '"Plus Jakarta Sans", "Noto Sans", system-ui, -apple-system, sans-serif';
  const narrativeSerif = 'Charter, Georgia, "Noto Serif", serif';

  for (const blk of blocks) {
    if (!blk.dst?.trim()) continue;
    const kind: VisionBlockKind = blk.kind || 'dialogue';
    if (kind === 'sfx' && !showSfx) continue;

    const scaledBox: [number, number, number, number] = [
      Math.round(blk.box[0] * scale),
      Math.round(blk.box[1] * scale),
      Math.round(blk.box[2] * scale),
      Math.round(blk.box[3] * scale),
    ];
    const [bx, by, bw, bh] = scaledBox;
    if (bw < 8 || bh < 8) continue;

    ctx.save();
    const isHighlighted = opts.highlightBlockId === blk.id;

    // Case 1: SFX or Unbordered Margin Aside -> Halo-stroked text directly over art (zero boxy rectangle!)
    if (kind === 'sfx' || kind === 'aside' || blk.shape === 'unbordered') {
      const sample = sampleBubbleBackground(ctx, scaledBox, w, h, blk.bgTone, opts.resolvedTheme);
      const isDarkBg = sample.isDark;
      const fillText = isDarkBg ? '#FFF8EC' : '#151918';
      const strokeHalo = isDarkBg ? 'rgba(12, 16, 15, 0.92)' : 'rgba(255, 255, 255, 0.94)';
      const weight = kind === 'sfx' ? '800' : '600';
      const fit = fitTextBinarySearch(ctx, blk.dst, bw, bh, false, comicSans, weight);
      ctx.font = `${weight} ${fit.fontSize}px ${comicSans}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.lineJoin = 'round';
      ctx.lineWidth = Math.max(3, Math.round(fit.fontSize * 0.24));
      ctx.strokeStyle = strokeHalo;
      ctx.fillStyle = fillText;
      const startY = by + (bh - fit.lines.length * fit.lineHeight) / 2 + fit.lineHeight / 2;
      fit.lines.forEach((line, li) => {
        const ly = startY + li * fit.lineHeight;
        ctx.strokeText(line, bx + bw / 2, ly);
        ctx.fillText(line, bx + bw / 2, ly);
      });
      ctx.restore();
      continue;
    }

    // Case 2: Isekai / LitRPG RPG Status Window -> Translucent glass overlay preserving game HUD aesthetic
    if (kind === 'status_window') {
      ctx.fillStyle = 'rgba(15, 22, 32, 0.90)';
      ctx.strokeStyle = isHighlighted ? '#5DC3AC' : 'rgba(148, 197, 255, 0.65)';
      ctx.lineWidth = isHighlighted ? 2.5 : 1.5;
      ctx.beginPath();
      if (typeof ctx.roundRect === 'function') ctx.roundRect(bx, by, bw, bh, 8);
      else ctx.rect(bx, by, bw, bh);
      ctx.fill();
      ctx.stroke();

      const fit = fitTextBinarySearch(ctx, blk.dst, bw, bh, false, comicSans, '600');
      ctx.font = `600 ${fit.fontSize}px ${comicSans}`;
      ctx.fillStyle = '#F0F6FC';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      const startY = by + Math.max(6, (bh - fit.lines.length * fit.lineHeight) / 2);
      fit.lines.forEach((line, li) => {
        ctx.fillText(line, bx + 10, startY + li * fit.lineHeight);
      });
      ctx.restore();
      continue;
    }

    // Case 3: Speech / Thought / Shout / Narration Bubbles -> Background-Sampled & Full-Cover Inpainting Pill
    const sample = sampleBubbleBackground(ctx, scaledBox, w, h, blk.bgTone, opts.resolvedTheme);
    const [fr, fg, fb] = sample.fill;
    const isOval =
      blk.shape === 'oval' ||
      blk.shape === 'cloud' ||
      (blk.shape === undefined && kind !== 'narration' && kind !== 'caption' && bw < w * 0.65);
    const isJagged = blk.shape === 'jagged' || kind === 'shout';

    // Outward-padded opaque mask guarantees 100% erasure of original OCR glyphs (zero peeking edges!)
    const coverPadX = Math.max(6, Math.min(18, Math.round(bw * 0.04)));
    const coverPadY = Math.max(5, Math.min(16, Math.round(bh * 0.14)));
    const mx = Math.max(0, bx - coverPadX);
    const my = Math.max(0, by - coverPadY);
    const mw = Math.min(w - mx, bw + coverPadX * 2);
    const mh = Math.min(h - my, bh + coverPadY * 2);

    let fillPaint: string | CanvasGradient = `rgb(${fr}, ${fg}, ${fb})`;
    if (sample.useGradient) {
      const grad = ctx.createLinearGradient(mx, my, mx, my + mh);
      grad.addColorStop(0, `rgb(${sample.topFill[0]}, ${sample.topFill[1]}, ${sample.topFill[2]})`);
      grad.addColorStop(1, `rgb(${sample.bottomFill[0]}, ${sample.bottomFill[1]}, ${sample.bottomFill[2]})`);
      fillPaint = grad;
    }

    ctx.beginPath();
    const radius =
      kind === 'narration' || kind === 'caption'
        ? 4
        : isJagged
          ? Math.min(12, mh * 0.25)
          : isOval
            ? Math.min(mw * 0.16, mh * 0.42, 22)
            : 10;
    if (typeof ctx.roundRect === 'function') {
      ctx.roundRect(mx, my, Math.max(8, mw), Math.max(8, mh), radius);
    } else {
      ctx.rect(mx, my, Math.max(8, mw), Math.max(8, mh));
    }

    // Soft-feathered 2-pass edge blend + screentone guard preserves manga artwork seamlessly
    ctx.save();
    ctx.globalAlpha = sample.isScreentone ? 0.9 : 1.0;
    if (sample.sampled) {
      ctx.shadowColor = `rgba(${fr}, ${fg}, ${fb}, 0.85)`;
      ctx.shadowBlur = Math.max(3, Math.min(8, Math.round(coverPadY * 0.7)));
    }
    ctx.fillStyle = fillPaint;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fill();
    ctx.restore();

    // Subtle highlight ring ONLY when actively tapped/selected (never ugly permanent neon borders!)
    if (isHighlighted) {
      ctx.strokeStyle = sample.isDark ? '#5DC3AC' : '#17695B';
      ctx.lineWidth = 2.5;
      ctx.stroke();
    } else if (!sample.sampled) {
      // Soft neutral hairline when cross-origin taint prevented pixel sampling
      ctx.strokeStyle = sample.isDark ? 'rgba(255,255,255,0.16)' : 'rgba(20,25,23,0.14)';
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Enforce WCAG AA >= 4.8:1 text color against sampled bubble fill
    const darkInk: [number, number, number] = [20, 25, 23];
    const lightInk: [number, number, number] = [243, 246, 245];
    const chosenInk =
      contrastRatioRgb(sample.fill, darkInk) >= contrastRatioRgb(sample.fill, lightInk)
        ? darkInk
        : lightInk;

    const fontWeight = kind === 'shout' ? '700' : kind === 'thought' ? 'italic 500' : '700';
    const fontFamily = kind === 'narration' || kind === 'caption' ? narrativeSerif : comicSans;
    const fit = fitTextBinarySearch(ctx, blk.dst, mw, mh, isOval && !isJagged, fontFamily, fontWeight);

    ctx.font = `${fontWeight} ${fit.fontSize}px ${fontFamily}`;
    ctx.fillStyle = `rgb(${chosenInk[0]}, ${chosenInk[1]}, ${chosenInk[2]})`;
    ctx.textAlign = kind === 'narration' || kind === 'caption' ? 'left' : 'center';
    ctx.textBaseline = 'middle';

    const startY = my + (mh - fit.lines.length * fit.lineHeight) / 2 + fit.lineHeight / 2;
    const textX = kind === 'narration' || kind === 'caption' ? mx + Math.max(8, mw * 0.06) : mx + mw / 2;
    fit.lines.forEach((line, li) => {
      ctx.fillText(line, textX, startY + li * fit.lineHeight);
    });

    ctx.restore();
  }
}
