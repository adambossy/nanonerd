import type { SyncOptions, SyncResult } from "./syncer";
import type { SyncStatus } from "./types";

/**
 * Decides *when* to sync. Owns no data: it drives a Syncer in response to
 * app start, connectivity, visibility, a periodic tick, and explicit
 * requests, with exponential backoff after retryable failures. The browser
 * is reached only through the injected SchedulerEnv, so this is unit-testable
 * with fake timers and no DOM.
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

export class SyncScheduler {
  private readonly intervalMs: number;
  private readonly initialBackoffMs: number;
  private readonly maxBackoffMs: number;

  private status: SyncStatus = { online: true, syncing: false, unsynced: 0, lastError: null };
  private listeners = new Set<Listener>();
  private unsubscribers: Array<() => void> = [];
  private started = false;
  private inFlight = false;
  private queued = false;
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
   * Ask for a full sync soon. Coalesces: at most one sync runs at a time and
   * at most one more is queued behind it. While backing off after a failure,
   * only the pending count is refreshed; the backoff timer owns the retry.
   */
  requestSync(): void {
    if (this.retryHandle !== null) {
      void this.refreshPending();
      return;
    }
    if (this.inFlight) {
      this.queued = true;
      return;
    }
    void this.run({});
  }

  /** Push-only, keepalive sync for pagehide / hidden: requests may outlive the page. */
  flushForUnload(): void {
    void this.run({ pushOnly: true, keepalive: true });
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

  private async run(opts: SyncOptions): Promise<void> {
    if (this.inFlight) {
      this.queued = true;
      return;
    }
    this.inFlight = true;
    this.setStatus({ syncing: true });
    let result: SyncResult;
    let unexpected: string | null = null;
    try {
      result = await this.syncer.syncAll(opts);
    } catch (error) {
      // Non-SyncError: a bug, not a connectivity problem. Surface it and keep running.
      result = { pushedMarks: 0, pushedSessions: 0, refreshed: false, prefetched: 0, error: null };
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
    this.inFlight = false;
    if (this.queued) {
      this.queued = false;
      if (this.retryHandle === null) void this.run({});
    }
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
      void this.run({});
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
    if (!this.env.isVisible() || this.retryHandle !== null || this.inFlight) return;
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
