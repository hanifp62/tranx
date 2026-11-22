import type { ModePair, SourceLang, TargetLang } from '../types';

/* Lightweight pure language, URL validation, and binary magic-byte helpers.
 * Extracted from directEngine.ts so App.tsx and api.ts stay tiny and lazy-load directEngine on demand.
 */

export const CJK_RE = /[\u3040-\u309f\u30a0-\u30ff\u3400-\u9fff]/;
export const CJK_SPAN_RE = /[\u3000-\u30ff\u3400-\u9fff\uff01-\uff60]+/g;
export const WORD_RE = /[A-Za-zÀ-ÿ']+/g;

const ID_WORDS = new Set([
  'yang', 'dan', 'di', 'ke', 'dari', 'ini', 'itu', 'untuk', 'dengan', 'tidak', 'tak',
  'bisa', 'dapat', 'ada', 'saya', 'aku', 'kamu', 'kau', 'dia', 'ia', 'kami', 'kita',
  'mereka', 'dalam', 'pada', 'adalah', 'ialah', 'sudah', 'telah', 'akan', 'sedang',
  'atau', 'karena', 'sebab', 'seperti', 'juga', 'oleh', 'tentang', 'lebih', 'sangat',
  'hanya', 'saja', 'cuma', 'selamat', 'pagi', 'malam', 'siang', 'sore', 'terima',
  'kasih', 'bagaimana', 'mengapa', 'kenapa', 'kapan', 'dimana', 'apa', 'siapa', 'berapa',
  'tetap', 'bukan', 'belum', 'masih', 'lagi', 'baru', 'lama', 'semua', 'seluruh',
  'setiap', 'ketika', 'saat', 'waktu', 'hari', 'orang', 'rumah', 'jalan', 'cerita',
  'bab', 'halaman', 'buku', 'baca', 'membaca', 'tulis', 'menulis', 'pergi', 'datang',
  'lihat', 'melihat', 'kata', 'berkata', 'bilang', 'sambil', 'lalu', 'kemudian',
  'setelah', 'sebelum', 'sampai', 'hingga', 'sejak', 'selama', 'tanpa', 'antara',
  'tetapi', 'tapi', 'namun', 'jika', 'kalau', 'bila', 'agar', 'supaya', 'buat',
  'mau', 'ingin', 'harus', 'boleh', 'perlu', 'pernah', 'pun', 'jadi', 'menjadi',
  'sesuai', 'berubah', 'kakek', 'nenek', 'anak', 'ibu', 'ayah', 'teman', 'besar',
  'kecil', 'baik', 'buruk', 'cantik', 'indah', 'tenang', 'pelan', 'cepat', 'halo',
  'tolong', 'maaf', 'ya', 'iya', 'tidaklah', 'disini', 'disana', 'sini', 'sana',
]);

const EN_WORDS = new Set([
  'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'i', 'it', 'for', 'not',
  'on', 'with', 'he', 'as', 'you', 'do', 'at', 'this', 'but', 'his', 'by', 'from',
  'they', 'we', 'say', 'her', 'she', 'or', 'an', 'will', 'my', 'one', 'all', 'would',
  'there', 'their', 'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which',
  'go', 'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just', 'him', 'know',
  'take', 'into', 'year', 'your', 'good', 'some', 'could', 'them', 'see', 'other',
  'than', 'then', 'now', 'look', 'only', 'come', 'its', 'over', 'think', 'also',
  'back', 'after', 'use', 'two', 'how', 'our', 'work', 'first', 'well', 'way', 'even',
  'new', 'want', 'because', 'any', 'these', 'give', 'day', 'most', 'us', 'is', 'are',
  'was', 'were', 'been', 'has', 'had', 'does', 'did', 'more', 'very', 'much', 'still',
  'hello', 'morning', 'evening', 'night', 'please', 'thank', 'thanks', 'chapter',
  'episode', 'next', 'previous', 'story', 'page', 'read', 'reading', 'book', 'novel',
  'while', 'under', 'opened', 'stood', 'quietly', 'listening', 'rain', 'letter',
]);

export type ParagraphLangClass =
  | 'ja'
  | 'id'
  | 'en'
  | 'mixed-ja'
  | 'mixed-latin'
  | 'unknown';

export function scoreLatinWords(sample: string): {
  idScore: number;
  enScore: number;
  wordCount: number;
} {
  const words = (sample.slice(0, 4000).match(WORD_RE) || []).map((w) => w.toLowerCase());
  let idScore = 0;
  let enScore = 0;
  let idStopHits = 0;
  let enStopHits = 0;
  for (const w of words) {
    if (ID_WORDS.has(w)) {
      idScore += 1.2;
      idStopHits += 1;
    }
    if (EN_WORDS.has(w)) {
      enScore += 1.2;
      enStopHits += 1;
    }
    if (
      !EN_WORDS.has(w) &&
      w.length >= 6 &&
      (w.endsWith('nya') ||
        w.endsWith('kan') ||
        w.endsWith('lah') ||
        w.endsWith('kah') ||
        w.startsWith('meny') ||
        w.startsWith('meng') ||
        w.startsWith('memb') ||
        w.startsWith('mend') ||
        w.startsWith('berk') ||
        w.startsWith('bert') ||
        w.startsWith('terj') ||
        w.startsWith('terk') ||
        w.startsWith('terl') ||
        w.startsWith('terd'))
    ) {
      idScore += 0.65;
    }
    if (
      !ID_WORDS.has(w) &&
      ((w.length >= 5 &&
        (w.endsWith('tion') || w.endsWith('ment') || w.endsWith('ing') || w.endsWith('ness'))) ||
        /^(don't|can't|won't|isn't|aren't|it's|i'm|you're|we're|they're|didn't|wasn't|couldn't|wouldn't)$/.test(
          w
        ))
    ) {
      enScore += 0.7;
    }
  }
  if (idStopHits === 0 && idScore < 1.5) idScore = 0;
  if (enStopHits === 0 && enScore < 1.5) enScore = 0;
  return { idScore, enScore, wordCount: words.length };
}

export function classifyParagraphLanguage(text: string): ParagraphLangClass {
  const sample = (text || '').trim();
  if (!sample) return 'unknown';

  const hasCjk = CJK_RE.test(sample);
  const { idScore, enScore, wordCount } = scoreLatinWords(sample);

  if (hasCjk) {
    const latinWords = (sample.match(/[A-Za-zÀ-ÿ]{2,}/g) || []).length;
    return latinWords >= 2 ? 'mixed-ja' : 'ja';
  }
  if (wordCount === 0) return 'unknown';

  if (idScore >= 1.2 && enScore === 0 && (wordCount <= 4 || idScore >= 2.0)) return 'id';
  if (enScore >= 1.2 && idScore === 0 && (wordCount <= 4 || enScore >= 2.0)) return 'en';
  if (idScore > 0 && enScore > 0) {
    if (idScore >= 2.4 && idScore >= enScore * 2.2) return 'id';
    if (enScore >= 2.4 && enScore >= idScore * 2.2) return 'en';
    return 'mixed-latin';
  }
  return 'unknown';
}

export function parseModePair(mode: ModePair): { src: SourceLang; tgt: TargetLang } {
  const [rawSrc, rawTgt] = mode.split('-') as [SourceLang, TargetLang];
  const src: SourceLang = ['auto', 'id', 'en', 'ja'].includes(rawSrc) ? rawSrc : 'auto';
  const tgt: TargetLang = ['id', 'en', 'ja'].includes(rawTgt) ? rawTgt : 'id';
  if (src !== 'auto' && src === tgt) {
    return { src: 'auto', tgt };
  }
  return { src, tgt };
}

export function buildModePair(
  nextSrc: SourceLang,
  nextTgt: TargetLang,
  prevMode: ModePair = 'auto-id'
): ModePair {
  const prev = parseModePair(prevMode);
  let src = nextSrc;
  let tgt = nextTgt;
  if (src !== 'auto' && src === tgt) {
    if (nextTgt !== prev.tgt && prev.src !== 'auto' && prev.src !== nextTgt) {
      src = prev.tgt;
    } else if (nextSrc !== prev.src && prev.tgt !== nextSrc) {
      tgt = prev.src === 'auto' ? (nextSrc === 'ja' ? 'id' : 'ja') : prev.src;
    } else {
      tgt = src === 'ja' ? 'id' : 'ja';
    }
  }
  return `${src}-${tgt}` as ModePair;
}

export function swapModePair(
  current: ModePair,
  detectedSource?: TargetLang | ''
): ModePair {
  const { src, tgt } = parseModePair(current);
  const concreteSrc: TargetLang =
    src === 'auto'
      ? detectedSource && detectedSource !== tgt
        ? detectedSource
        : tgt === 'ja'
          ? 'id'
          : 'ja'
      : src;
  const nextSrc: SourceLang = tgt;
  const nextTgt: TargetLang = concreteSrc === tgt ? (tgt === 'ja' ? 'id' : 'ja') : concreteSrc;
  return `${nextSrc}-${nextTgt}` as ModePair;
}

export function detectLanguageLocal(text: string, fallback: TargetLang = 'ja'): TargetLang {
  const sample = (text || '').trim();
  if (!sample) return fallback;
  if (CJK_RE.test(sample)) return 'ja';

  const { idScore, enScore, wordCount } = scoreLatinWords(sample);
  if (wordCount === 0) return fallback;
  if (idScore > enScore) return 'id';
  if (enScore > idScore) return 'en';
  return fallback;
}

export function isSingleStandaloneUrl(raw: string): boolean {
  const trimmed = raw.trim();
  if (!trimmed || /\s/.test(trimmed)) return false;
  return /^https?:\/\/[^\s]+$/i.test(trimmed);
}

export function normalizeWebUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed || trimmed.length > 2048) {
    throw new Error('Masukkan alamat tautan halaman web yang sah (maks. 2.048 karakter).');
  }
  const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(trimmed) ? trimmed : `https://${trimmed}`;
  let parsed: URL;
  try {
    parsed = new URL(withScheme);
  } catch {
    throw new Error('Format alamat URL tidak sah.');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('Hanya tautan http:// dan https:// yang diizinkan.');
  }
  if (parsed.username || parsed.password) {
    throw new Error('Kredensial di dalam URL tidak diizinkan.');
  }
  if (parsed.port && parsed.port !== '80' && parsed.port !== '443') {
    throw new Error('Hanya port standar 80 dan 443 yang diizinkan.');
  }
  const rawHost = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  const host = rawHost.replace(/\.+$/, '');
  const isIpv6 = host.includes(':');
  const isPrivateIpv4 =
    /^0\./.test(host) ||
    host === '0.0.0.0' ||
    /^127\./.test(host) ||
    /^10\./.test(host) ||
    /^192\.168\./.test(host) ||
    /^192\.0\.(?:0|2)\./.test(host) ||
    /^198\.(?:1[89]|51\.100)\./.test(host) ||
    /^203\.0\.113\./.test(host) ||
    /^169\.254\./.test(host) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(host) ||
    /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(host) ||
    /^2(?:2[4-9]|3\d)\./.test(host) ||
    /^2(?:4\d|5[0-5])\./.test(host);

  const expandIpv6Hextets = (ip: string): number[] | null => {
    const parts = ip.split('::');
    if (parts.length > 2) return null;
    const left = parts[0] ? parts[0].split(':') : [];
    const right = parts[1] ? parts[1].split(':') : [];
    const missing = 8 - (left.length + right.length);
    if (parts.length === 1 ? left.length !== 8 : missing < 1) return null;
    const full = [...left, ...Array<string>(Math.max(0, missing)).fill('0'), ...right];
    const nums = full.map((h) => (/^[0-9a-f]{1,4}$/i.test(h) ? parseInt(h, 16) : NaN));
    return nums.some(Number.isNaN) ? null : nums;
  };

  const isNonGlobalIpv6 = (ip: string): boolean => {
    const h = expandIpv6Hextets(ip);
    if (!h) return true; // Fail closed on malformed IPv6 literal
    const [h0, h1] = h;
    // Allow ONLY global unicast 2000::/3 excluding IETF/Teredo (2001::/23), docs (2001:db8::/32), benchmarking (2001:2::/48), and 6to4 (2002::/16)
    if ((h0 & 0xe000) !== 0x2000) return true;
    if (h0 === 0x2001 && h1 <= 0x01ff) return true;
    if (h0 === 0x2001 && h1 === 0x0db8) return true;
    if (h0 === 0x2002) return true;
    return false;
  };

  const isPrivateIpv6 = isIpv6 && isNonGlobalIpv6(host);
  if (
    !host ||
    host === 'localhost' ||
    host.endsWith('.localhost') ||
    host === 'metadata' ||
    host === 'metadata.google.internal' ||
    host.endsWith('.local') ||
    host.endsWith('.internal') ||
    isPrivateIpv4 ||
    isPrivateIpv6
  ) {
    const err = new Error('Alamat jaringan internal atau privat ditolak demi keamanan.') as Error & {
      status?: number;
      code?: string;
    };
    err.status = 403;
    err.code = 'BLOCKED_URL';
    throw err;
  }
  return parsed.toString();
}

export function toSafeHttpUrl(raw: string): string | null {
  try {
    return normalizeWebUrl(raw);
  } catch {
    return null;
  }
}

export function deriveSeriesTitleId(rawUrl: string): string {
  try {
    const u = new URL(rawUrl);
    const host = u.hostname.toLowerCase();
    const path = u.pathname;
    const kakuyomu = path.match(/^\/works\/(\d+)/);
    if (host.includes('kakuyomu.jp') && kakuyomu) {
      return `t_novel_kakuyomu_${kakuyomu[1]}`;
    }
    const syosetu = path.match(/^\/(n[a-z0-9]+)/i);
    if (host.includes('syosetu.com') && syosetu) {
      return `t_novel_syosetu_${syosetu[1].toLowerCase()}`;
    }
    const hameln = path.match(/^\/novel\/(\d+)/);
    if (host.includes('syosetu.org') && hameln) {
      return `t_novel_hameln_${hameln[1]}`;
    }
    const alpha = path.match(/^\/novel\/(\d+\/\d+)/);
    if (host.includes('alphapolis.co.jp') && alpha) {
      return `t_novel_alpha_${alpha[1].replace(/\//g, '_')}`;
    }
    const aozora = path.match(/^\/cards\/(\d+)/);
    if (host.includes('aozora.gr.jp') && aozora) {
      return `t_novel_aozora_${aozora[1]}`;
    }
    const royal = path.match(/^\/fiction\/(\d+)/);
    if (host.includes('royalroad.com') && royal) {
      return `t_novel_rr_${royal[1]}`;
    }
    const scribble = path.match(/^\/(?:read|series)\/(\d+)/);
    if (host.includes('scribblehub.com') && scribble) {
      return `t_novel_sh_${scribble[1]}`;
    }
    const ao3 = path.match(/^\/works\/(\d+)/);
    if (host.includes('archiveofourown.org') && ao3) {
      return `t_novel_ao3_${ao3[1]}`;
    }
    const ffnet = path.match(/^\/s\/(\d+)/);
    if (host.includes('fanfiction.net') && ffnet) {
      return `t_novel_ff_${ffnet[1]}`;
    }
    const genericNovel = path.match(/^\/(?:b|book|novel|series|story|light-novel)\/([^/]+)/i);
    if (genericNovel) {
      const slug = genericNovel[1].replace(/[^a-z0-9]/gi, '_').slice(0, 28);
      return `t_novel_${host.replace(/^www\./, '').split('.')[0].slice(0, 12)}_${slug}`;
    }
    return `t_web_${host.replace(/[^a-z0-9]/gi, '_').slice(0, 24)}`;
  } catch {
    return 't_web_page';
  }
}

export function inspectBinaryMagicBytes(
  bytes: Uint8Array,
  ext: string,
  kind: 'gambar' | 'dokumen'
): string | null {
  if (bytes.byteLength === 0) {
    return 'Berkas kosong dan tidak dapat diproses.';
  }
  const cleanExt = ext.toLowerCase();

  if (kind === 'gambar') {
    const isPng =
      bytes.byteLength >= 8 &&
      bytes[0] === 0x89 &&
      bytes[1] === 0x50 &&
      bytes[2] === 0x4e &&
      bytes[3] === 0x47 &&
      bytes[4] === 0x0d &&
      bytes[5] === 0x0a &&
      bytes[6] === 0x1a &&
      bytes[7] === 0x0a;
    const isJpeg =
      bytes.byteLength >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
    const isWebp =
      bytes.byteLength >= 12 &&
      bytes[0] === 0x52 &&
      bytes[1] === 0x49 &&
      bytes[2] === 0x46 &&
      bytes[3] === 0x46 &&
      bytes[8] === 0x57 &&
      bytes[9] === 0x45 &&
      bytes[10] === 0x42 &&
      bytes[11] === 0x50;
    if (!isPng && !isJpeg && !isWebp) {
      return 'Isi biner berkas bukan gambar PNG, JPG, atau WEBP yang sah.';
    }
    return null;
  }

  if (cleanExt === 'pdf') {
    const head = new TextDecoder('latin1').decode(
      bytes.subarray(0, Math.min(bytes.byteLength, 1024))
    );
    if (!head.includes('%PDF-')) {
      return 'Isi biner berkas bukan dokumen PDF yang sah.';
    }
    return null;
  }

  if (cleanExt === 'docx' || cleanExt === 'epub') {
    const isZip =
      bytes.byteLength >= 4 &&
      bytes[0] === 0x50 &&
      bytes[1] === 0x4b &&
      (bytes[2] === 0x03 || bytes[2] === 0x05);
    if (!isZip) {
      return `Berkas .${cleanExt} rusak atau bukan arsip dokumen yang sah.`;
    }
    return null;
  }

  const hasUtf16Bom =
    bytes.byteLength >= 2 &&
    ((bytes[0] === 0xfe && bytes[1] === 0xff) || (bytes[0] === 0xff && bytes[1] === 0xfe));
  if (!hasUtf16Bom) {
    const sampleLen = Math.min(bytes.byteLength, 512);
    for (let i = 0; i < sampleLen; i += 1) {
      if (bytes[i] === 0x00) {
        return `Isi biner berkas tidak sesuai dengan format teks .${cleanExt}.`;
      }
    }
  }
  return null;
}

export async function validateUploadedFileMagic(
  file: File,
  kind: 'gambar' | 'dokumen'
): Promise<string | null> {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  const sliceBuf = await file.slice(0, 1024).arrayBuffer();
  return inspectBinaryMagicBytes(new Uint8Array(sliceBuf), ext, kind);
}
