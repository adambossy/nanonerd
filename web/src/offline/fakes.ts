import type { ArticleDetail, ArticleSummary } from "../types";
import type { SchedulerEnv, SchedulerEvent } from "./scheduler";
import { SyncError, type MarkPayload, type RequestOptions, type SessionPayload, type SyncApi } from "./transport";

// Test doubles shared by the offline test suites. Not shipped (only imported by *.test.ts).

export interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

export function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

/** Scriptable SyncApi that records every call and can be told to fail per endpoint. */
export class FakeSyncApi implements SyncApi {
  articles: ArticleSummary[] = [];
  details = new Map<number, ArticleDetail>();
  failPostMarks = new Map<number, SyncError>();
  failPutSession = new Map<string, SyncError>();
  failFetchArticles: SyncError | null = null;
  failFetchArticle = new Map<number, SyncError>();
  /** When true, every call fails with a network error (simulates being offline). */
  offline = false;
  /** When set, fetchArticle waits on the deferred for that id (for concurrency tests). */
  gate = new Map<number, Deferred<void>>();
  inflightFetches = 0;
  maxInflightFetches = 0;
  calls: Array<{ op: string; args: unknown[] }> = [];
  /** What the "server" has accepted: marks by article, sessions by client id. */
  acceptedMarks = new Map<number, MarkPayload[]>();
  acceptedSessions = new Map<string, SessionPayload>();

  async fetchArticles(): Promise<ArticleSummary[]> {
    this.calls.push({ op: "fetchArticles", args: [] });
    this.throwIfOffline();
    if (this.failFetchArticles) throw this.failFetchArticles;
    return structuredClone(this.articles);
  }

  async fetchArticle(id: number): Promise<ArticleDetail> {
    this.calls.push({ op: "fetchArticle", args: [id] });
    this.throwIfOffline();
    this.inflightFetches += 1;
    this.maxInflightFetches = Math.max(this.maxInflightFetches, this.inflightFetches);
    try {
      await this.gate.get(id)?.promise;
      const failure = this.failFetchArticle.get(id);
      if (failure) throw failure;
      const found = this.details.get(id);
      if (!found) throw new SyncError("http", 404);
      return structuredClone(found);
    } finally {
      this.inflightFetches -= 1;
    }
  }

  async postMarks(articleId: number, marks: MarkPayload[], opts?: RequestOptions): Promise<void> {
    this.calls.push({ op: "postMarks", args: [articleId, marks, opts] });
    this.throwIfOffline();
    const failure = this.failPostMarks.get(articleId);
    if (failure) throw failure;
    this.acceptedMarks.set(articleId, [...(this.acceptedMarks.get(articleId) ?? []), ...marks]);
  }

  async putSession(payload: SessionPayload, opts?: RequestOptions): Promise<void> {
    this.calls.push({ op: "putSession", args: [payload, opts] });
    this.throwIfOffline();
    const failure = this.failPutSession.get(payload.client_id);
    if (failure) throw failure;
    const existing = this.acceptedSessions.get(payload.client_id);
    this.acceptedSessions.set(payload.client_id, {
      ...payload,
      active_seconds: Math.max(existing?.active_seconds ?? 0, payload.active_seconds),
    });
  }

  ops(): string[] {
    return this.calls.map((c) => c.op);
  }

  private throwIfOffline(): void {
    if (this.offline) throw new SyncError("network", null);
  }
}

/** SchedulerEnv backed by plain flags and an in-memory event map; uses global timers so fake timers apply. */
export class FakeEnv implements SchedulerEnv {
  online = true;
  visible = true;
  private handlers = new Map<SchedulerEvent, Set<() => void>>();

  isOnline(): boolean {
    return this.online;
  }
  isVisible(): boolean {
    return this.visible;
  }
  on(event: SchedulerEvent, handler: () => void): () => void {
    const set = this.handlers.get(event) ?? new Set();
    set.add(handler);
    this.handlers.set(event, set);
    return () => set.delete(handler);
  }
  emit(event: SchedulerEvent): void {
    for (const handler of this.handlers.get(event) ?? []) handler();
  }
  setTimeout(fn: () => void, ms: number): unknown {
    return globalThis.setTimeout(fn, ms);
  }
  clearTimeout(handle: unknown): void {
    globalThis.clearTimeout(handle as ReturnType<typeof globalThis.setTimeout>);
  }
}
