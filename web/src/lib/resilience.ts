/* Adaptive Resilience, Bounded Memory LRU, Token Bucket Rate-Limiting,
 * Circuit Breakers, and Device/Network Hardware Profiling for Web & Installed PWA.
 * Engineered to keep 5-10 concurrent users fast, balanced, thermal-safe, and 429/403-free.
 */

export interface DeviceRuntimeProfile {
  cores: number;
  deviceMemoryGb: number;
  effectiveType: string;
  saveData: boolean;
  online: boolean;
  isConstrained: boolean;
  gtxConcurrency: number;
  geminiConcurrency: number;
  jinaConcurrency: number;
  allowBackgroundPrefetch: boolean;
  ramCacheScale: number;
}

interface NetworkInformationLike {
  effectiveType?: string;
  saveData?: boolean;
}

export function getDeviceRuntimeProfile(): DeviceRuntimeProfile {
  if (typeof navigator === 'undefined') {
    return {
      cores: 4,
      deviceMemoryGb: 4,
      effectiveType: '4g',
      saveData: false,
      online: true,
      isConstrained: false,
      gtxConcurrency: 4,
      geminiConcurrency: 3,
      jinaConcurrency: 2,
      allowBackgroundPrefetch: true,
      ramCacheScale: 1,
    };
  }

  const nav = navigator as Navigator & {
    deviceMemory?: number;
    connection?: NetworkInformationLike;
    mozConnection?: NetworkInformationLike;
    webkitConnection?: NetworkInformationLike;
  };
  const conn = nav.connection || nav.mozConnection || nav.webkitConnection;
  const cores = Math.max(1, Number(nav.hardwareConcurrency || 4));
  const deviceMemoryGb = Number(nav.deviceMemory || 4);
  const effectiveType = String(conn?.effectiveType || '4g').toLowerCase();
  const saveData = Boolean(conn?.saveData);
  const online = typeof nav.onLine === 'boolean' ? nav.onLine : true;

  const isSlowNet = effectiveType === 'slow-2g' || effectiveType === '2g' || effectiveType === '3g';
  const isLowRam = deviceMemoryGb > 0 && deviceMemoryGb <= 2;
  const isConstrained = saveData || isSlowNet || isLowRam || cores <= 2;
  const isHidden =
    typeof document !== 'undefined' && document.visibilityState === 'hidden';

  return {
    cores,
    deviceMemoryGb,
    effectiveType,
    saveData,
    online,
    isConstrained,
    gtxConcurrency: isConstrained ? 2 : cores >= 6 && deviceMemoryGb >= 4 ? 4 : 3,
    geminiConcurrency: isConstrained ? 2 : 3,
    jinaConcurrency: isConstrained ? 1 : 2,
    allowBackgroundPrefetch: online && !isHidden && !saveData && !isSlowNet && !isLowRam,
    ramCacheScale: isLowRam ? 0.5 : 1,
  };
}

/** O(1) Bounded LRU Cache preventing unbounded RAM growth and OS PWA OOM eviction. */
export class BoundedLruCache<K, V> {
  private readonly store = new Map<K, V>();
  private maxEntries: number;

  constructor(maxEntries: number) {
    this.maxEntries = Math.max(4, maxEntries);
  }

  get size(): number {
    return this.store.size;
  }

  has(key: K): boolean {
    return this.store.has(key);
  }

  get(key: K): V | undefined {
    const val = this.store.get(key);
    if (val !== undefined) {
      this.store.delete(key);
      this.store.set(key, val);
    }
    return val;
  }

  set(key: K, value: V): void {
    this.store.delete(key);
    this.store.set(key, value);
    this.evictOverflow();
  }

  delete(key: K): boolean {
    return this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
  }

  entries(): IterableIterator<[K, V]> {
    return this.store.entries();
  }

  /** Trim oldest entries down to target fraction of current size (e.g. 0.5 when mobile PWA goes to background). */
  trimToRatio(ratio: number): void {
    if (this.store.size === 0) return;
    const clamped = Math.max(0, Math.min(1, ratio));
    const target = Math.floor(this.store.size * clamped);
    while (this.store.size > target) {
      const oldest = this.store.keys().next().value;
      if (oldest === undefined) break;
      this.store.delete(oldest);
    }
  }

  private evictOverflow(): void {
    while (this.store.size > this.maxEntries) {
      const oldest = this.store.keys().next().value;
      if (oldest === undefined) break;
      this.store.delete(oldest);
    }
  }
}

/** Parse Retry-After (seconds or HTTP-date) or compute capped exponential backoff with full jitter. */
export function computeBackoffDelayMs(
  attempt: number,
  retryAfterHeader?: string | null,
  baseMs = 450,
  maxDelayMs = 10_000
): number {
  if (retryAfterHeader) {
    const trimmed = retryAfterHeader.trim();
    const secs = Number(trimmed);
    if (Number.isFinite(secs) && secs >= 0) {
      return Math.min(Math.max(200, secs * 1000), maxDelayMs);
    }
    const parsedDate = Date.parse(trimmed);
    if (Number.isFinite(parsedDate)) {
      return Math.min(Math.max(200, parsedDate - Date.now()), maxDelayMs);
    }
  }
  const cap = Math.min(baseMs * 2 ** Math.max(0, attempt), maxDelayMs);
  return Math.max(150, Math.floor(cap * (0.45 + Math.random() * 0.55)));
}

function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  if (signal?.aborted) {
    return Promise.reject(new DOMException('Aborted', 'AbortError'));
  }
  return new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      globalThis.clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/**
 * Proactive Adaptive Token Bucket (safe for 5-10 concurrent users sharing NAT/upstreams).
 * Paces outbound bursts, slows down automatically on 429/503, and smoothly recovers on success.
 */
export class AdaptiveTokenBucket {
  private tokens: number;
  private lastRefillMs: number;
  private queue: Promise<void> = Promise.resolve();
  private currentRate: number;
  private cooldownUntilMs = 0;

  constructor(
    private readonly maxTokens: number,
    private readonly baseRatePerSec: number,
    private readonly minRatePerSec: number
  ) {
    this.tokens = maxTokens;
    this.currentRate = baseRatePerSec;
    this.lastRefillMs = Date.now();
  }

  get effectiveRate(): number {
    return this.currentRate;
  }

  async acquire(signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    const waitTurn = this.queue.then(() => this.acquireOnce(signal));
    this.queue = waitTurn.catch(() => undefined);
    if (!signal) return waitTurn;
    return new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        reject(new DOMException('Aborted', 'AbortError'));
      };
      if (signal.aborted) {
        onAbort();
        return;
      }
      signal.addEventListener('abort', onAbort, { once: true });
      waitTurn.then(
        () => {
          signal.removeEventListener('abort', onAbort);
          resolve();
        },
        (err) => {
          signal.removeEventListener('abort', onAbort);
          reject(err);
        }
      );
    });
  }

  onThrottle(retryAfterMs?: number): void {
    this.currentRate = Math.max(this.minRatePerSec, this.currentRate * 0.55);
    this.tokens = Math.min(this.tokens, 0.5);
    const pause = Math.min(12_000, Math.max(600, retryAfterMs || 1200));
    this.cooldownUntilMs = Math.max(this.cooldownUntilMs, Date.now() + pause);
  }

  onSuccess(): void {
    if (this.currentRate < this.baseRatePerSec) {
      this.currentRate = Math.min(this.baseRatePerSec, this.currentRate * 1.12 + 0.08);
    }
  }

  private async acquireOnce(signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    const now = Date.now();
    if (this.cooldownUntilMs > now) {
      await abortableSleep(this.cooldownUntilMs - now, signal);
    }
    this.refill();
    if (this.tokens < 1) {
      const waitMs = Math.ceil(((1 - this.tokens) / this.currentRate) * 1000);
      await abortableSleep(waitMs, signal);
      this.refill();
    }
    this.tokens = Math.max(0, this.tokens - 1);
  }

  private refill(): void {
    const now = Date.now();
    const elapsedSec = Math.max(0, (now - this.lastRefillMs) / 1000);
    this.tokens = Math.min(this.maxTokens, this.tokens + elapsedSec * this.currentRate);
    this.lastRefillMs = now;
  }
}

/**
 * Lightweight Circuit Breaker per upstream endpoint with explicit closed/open/half-open telemetry.
 * Prevents cascading latency spikes when an upstream CDN/proxy/API returns 403/429/5xx.
 */
export type CircuitBreakerState = 'closed' | 'open' | 'half-open';

export interface CircuitBreakerTelemetry {
  name: string;
  state: CircuitBreakerState;
  failures: number;
  openTransitions: number;
  cooldownRemainingMs: number;
}

const breakerRegistry = new Map<string, EndpointCircuitBreaker>();

export class EndpointCircuitBreaker {
  private failures = 0;
  private openUntilMs = 0;
  private halfOpenProbe = false;
  private halfOpenProbeUntilMs = 0;
  private openTransitions = 0;
  readonly name: string;

  constructor(
    private readonly failureThreshold = 2,
    private readonly cooldownMs = 30_000,
    name?: string
  ) {
    this.name = name || `endpoint_${breakerRegistry.size + 1}`;
    breakerRegistry.set(this.name, this);
  }

  dispose(): void {
    if (breakerRegistry.get(this.name) === this) {
      breakerRegistry.delete(this.name);
    }
  }

  getState(): CircuitBreakerState {
    if (this.openUntilMs === 0) {
      if (this.halfOpenProbe && Date.now() < this.halfOpenProbeUntilMs) {
        return 'half-open';
      }
      return 'closed';
    }
    if (Date.now() >= this.openUntilMs) {
      return 'half-open';
    }
    return 'open';
  }

  isOpen(): boolean {
    const now = Date.now();
    // Gate concurrent callers while a single half-open probe is still in flight (prevents stampede)
    if (this.halfOpenProbe) {
      if (now < this.halfOpenProbeUntilMs) return true;
      this.halfOpenProbe = false;
    }
    if (this.openUntilMs === 0) return false;
    if (now >= this.openUntilMs) {
      // Half-open: admit exactly ONE probe caller (15s safety ceiling in case probe is aborted)
      this.openUntilMs = 0;
      this.halfOpenProbe = true;
      this.halfOpenProbeUntilMs = now + 15_000;
      this.failures = Math.max(0, this.failureThreshold - 1);
      return false;
    }
    return true;
  }

  recordSuccess(): void {
    this.failures = 0;
    this.openUntilMs = 0;
    this.halfOpenProbe = false;
    this.halfOpenProbeUntilMs = 0;
  }

  recordFailure(customCooldownMs?: number): void {
    this.failures += 1;
    this.halfOpenProbe = false;
    this.halfOpenProbeUntilMs = 0;
    if (this.failures >= this.failureThreshold) {
      this.openTransitions += 1;
      this.openUntilMs = Date.now() + Math.max(2000, customCooldownMs || this.cooldownMs);
    }
  }

  reset(): void {
    this.failures = 0;
    this.openUntilMs = 0;
    this.halfOpenProbe = false;
    this.halfOpenProbeUntilMs = 0;
  }

  getTelemetry(): CircuitBreakerTelemetry {
    const state = this.getState();
    return {
      name: this.name,
      state,
      failures: this.failures,
      openTransitions: this.openTransitions,
      cooldownRemainingMs: state === 'open' ? Math.max(0, this.openUntilMs - Date.now()) : 0,
    };
  }
}

export interface RuntimeHealthSnapshot {
  online: boolean;
  isConstrained: boolean;
  allowBackgroundPrefetch: boolean;
  openBreakerCount: number;
  breakers: CircuitBreakerTelemetry[];
  checkedAt: number;
}

export function getRuntimeHealthSnapshot(): RuntimeHealthSnapshot {
  const profile = getDeviceRuntimeProfile();
  const breakers = Array.from(breakerRegistry.values()).map((b) => b.getTelemetry());
  const openBreakerCount = breakers.filter((b) => b.state === 'open').length;
  return {
    online: profile.online,
    isConstrained: profile.isConstrained,
    allowBackgroundPrefetch: profile.allowBackgroundPrefetch && openBreakerCount === 0,
    openBreakerCount,
    breakers,
    checkedAt: Date.now(),
  };
}

export function shouldShedBackgroundLoad(storageRatio = 0): boolean {
  const snap = getRuntimeHealthSnapshot();
  return !snap.allowBackgroundPrefetch || snap.openBreakerCount > 0 || storageRatio >= 0.85;
}

/**
 * Cooperative main-thread yield keeping INP responsive during heavy batch parsing/naturalization.
 * Uses Chrome 129+ `scheduler.yield()` with a universal `setTimeout(0)` fallback.
 */
export async function yieldToMain(): Promise<void> {
  if (typeof globalThis === 'undefined') return;
  const sched = (globalThis as { scheduler?: { yield?: () => Promise<void> } }).scheduler;
  if (typeof sched?.yield === 'function') {
    try {
      await sched.yield();
      return;
    } catch {
      // fall through to macrotask yield
    }
  }
  await new Promise<void>((resolve) => {
    setTimeout(resolve, 0);
  });
}
