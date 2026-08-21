import type { SyncOptions, SyncResult } from "./syncer";
import type { SyncStatus } from "./types";

/**
 * Decides *when* to sync. Owns no data: it drives a Syncer in response to
 * app start, connectivity, visibility, a periodic tick, and explicit
 * requests, with exponential backoff after retryable failures. The browser
 * is reached only through the injected SchedulerEnv, so this is unit-testable
 * with fake timers and no DOM.
 *
 * Single-flight: at most one sync runs at a time; requests that arrive while
 * one is running coalesce into a single follow-up run.
 */

export type SchedulerEvent = "online" | "visible" | "hidden";

export interface SchedulerEnv {
  isOnline(): boolean;
  isVisible(): boolean;
  /** Subscribe to a browser signal; returns an unsubscribe function. */
  on(event: SchedulerEvent, handler: () => void): () => void;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

/** The slice of Syncer the scheduler needs (structural, so tests can fake it). */
export interface SyncRunner {
  syncAll(opts?: SyncOptions): Promise<SyncResult>;
  pendingCount(): Promise<number>;
}

export interface SchedulerOptions {
  /** Periodic tick while visible; syncs only if something is pending. */
  intervalMs?: number;
  /** First retry delay after a retryable failure; doubles up to maxBackoffMs. */
  initialBackoffMs?: number;
  maxBackoffMs?: number;
}

type Listener = (status: SyncStatus) => void;

interface QueuedRun {
  opts: SyncOptions;
  promise: Promise<SyncResult>;
  resolve: (result: SyncResult) => void;
}

const EMPTY_RESULT: SyncResult = {
  pushedMarks: 0,
  pushedSessions: 0,
  refreshed: false,
  prefetched: 0,
  error: null,
};

export class SyncScheduler {
  private readonly intervalMs: number;
  private readonly initialBackoffMs: number;
  private readonly maxBackoffMs: number;

  private status: SyncStatus = { online: true, syncing: false, unsynced: 0, lastError: null };
  private listeners = new Set<Listener>();
  private unsubscribers: Array<() => void> = [];
  private started = false;
  private current: Promise<SyncResult> | null = null;
  private next: QueuedRun | null = null;
  private backoffMs = 0;
  private retryHandle: unknown = null;
  private tickHandle: unknown = null;

  constructor(
    private readonly syncer: SyncRunner,
    private readonly env: SchedulerEnv,
    opts: SchedulerOptions = {},
  ) {
    this.intervalMs = opts.intervalMs ?? 5_000;
    this.initialBackoffMs = opts.initialBackoffMs ?? 1_000;
    this.maxBackoffMs = opts.maxBackoffMs ?? 60_000;
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    this.unsubscribers = [
      this.env.on("online", () => this.onOnline()),
      this.env.on("visible", () => this.requestSync()),
      this.env.on("hidden", () => this.flushForUnload()),
    ];
    this.scheduleTick();
    this.requestSync();
  }

  stop(): void {
    if (!this.started) return;
    this.started = false;
    for (const unsubscribe of this.unsubscribers) unsubscribe();
    this.unsubscribers = [];
    this.clearRetry();
    if (this.tickHandle !== null) this.env.clearTimeout(this.tickHandle);
    this.tickHandle = null;
  }

  /**
   * Ask for a full sync soon (fire-and-forget). While backing off after a
   * failure, only the pending count is refreshed; the backoff timer owns the
   * retry so user activity can't extend the backoff.
   */
  requestSync(): void {
    if (this.retryHandle !== null) {
      void this.refreshPending();
      return;
    }
    void this.enqueue({});
  }

  /**
   * Run a full sync now and resolve with its result, even while backing off.
   * For callers that must know the outcome (e.g. "is this article available?").
   */
  syncNow(): Promise<SyncResult> {
    this.clearRetry();
    return this.enqueue({});
  }

  /** Push-only, keepalive sync for pagehide / hidden: requests may outlive the page. */
  flushForUnload(): void {
    void this.enqueue({ pushOnly: true, keepalive: true });
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.status);
    return () => {
      this.listeners.delete(listener);
    };
  }

  getStatus(): SyncStatus {
    return this.status;
  }

  /** Single-flight entry point: runs now, or coalesces into the one queued follow-up. */
  private enqueue(opts: SyncOptions): Promise<SyncResult> {
    if (this.current) {
      if (this.next) {
        this.next.opts = mergeOptions(this.next.opts, opts);
      } else {
        let resolve!: (result: SyncResult) => void;
        const promise = new Promise<SyncResult>((r) => (resolve = r));
        this.next = { opts, promise, resolve };
      }
      return this.next.promise;
    }
    const run = this.execute(opts);
    this.current = run;
    const onDone = (result: SyncResult) => {
      this.current = null;
      const queued = this.next;
      this.next = null;
      if (!queued) return;
      // A failed run scheduled a retry; hand waiters that outcome instead of hammering.
      if (this.retryHandle !== null) queued.resolve(result);
      else void this.enqueue(queued.opts).then(queued.resolve);
    };
    void run.then(onDone);
    return run;
  }

  /** One sync attempt. Never rejects; failures are folded into status and the result. */
  private async execute(opts: SyncOptions): Promise<SyncResult> {
    this.setStatus({ syncing: true });
    let result: SyncResult;
    let unexpected: string | null = null;
    try {
      result = await this.syncer.syncAll(opts);
    } catch (error) {
      // Non-SyncError: a bug, not a connectivity problem. Surface it and keep running.
      result = EMPTY_RESULT;
      unexpected = String(error);
    }
    const unsynced = await this.safePendingCount();
    if (result.error) {
      this.scheduleRetry();
      this.setStatus({ online: false, syncing: false, unsynced, lastError: result.error.message });
    } else {
      this.backoffMs = 0;
      this.setStatus({ online: true, syncing: false, unsynced, lastError: unexpected });
    }
    return result;
  }

  private onOnline(): void {
    this.backoffMs = 0;
    this.clearRetry();
    this.requestSync();
  }

  private scheduleRetry(): void {
    this.clearRetry();
    this.backoffMs =
      this.backoffMs === 0
        ? this.initialBackoffMs
        : Math.min(this.backoffMs * 2, this.maxBackoffMs);
    this.retryHandle = this.env.setTimeout(() => {
      this.retryHandle = null;
      void this.enqueue({});
    }, this.backoffMs);
  }

  private clearRetry(): void {
    if (this.retryHandle !== null) this.env.clearTimeout(this.retryHandle);
    this.retryHandle = null;
  }

  private scheduleTick(): void {
    if (!this.started) return;
    this.tickHandle = this.env.setTimeout(() => {
      void this.tick().finally(() => this.scheduleTick());
    }, this.intervalMs);
  }

  private async tick(): Promise<void> {
    if (!this.env.isVisible() || this.retryHandle !== null || this.current) return;
    if ((await this.safePendingCount()) > 0) this.requestSync();
  }

  private async refreshPending(): Promise<void> {
    this.setStatus({ unsynced: await this.safePendingCount() });
  }

  private async safePendingCount(): Promise<number> {
    try {
      return await this.syncer.pendingCount();
    } catch {
      return this.status.unsynced;
    }
  }

  private setStatus(patch: Partial<SyncStatus>): void {
    this.status = { ...this.status, ...patch };
    for (const listener of this.listeners) listener(this.status);
  }
}

/** A queued run serves every waiter: full sync beats push-only; keepalive if anyone asked. */
function mergeOptions(a: SyncOptions, b: SyncOptions): SyncOptions {
  return {
    pushOnly: Boolean(a.pushOnly && b.pushOnly),
    keepalive: Boolean(a.keepalive || b.keepalive),
  };
}
