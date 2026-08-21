import { describe, expect, test } from "vitest";
import type { ArticleDetail, ArticleSummary } from "../types";
import { article, body, chunk, detail, mark, session } from "./fixtures";
import { MemoryStore } from "./memoryStore";
import { Syncer } from "./syncer";
import { SyncError, type MarkPayload, type RequestOptions, type SessionPayload, type SyncApi } from "./transport";

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

/** Scriptable SyncApi that records every call. */
class FakeSyncApi implements SyncApi {
  articles: ArticleSummary[] = [];
  details = new Map<number, ArticleDetail>();
  failPostMarks = new Map<number, SyncError>();
  failPutSession = new Map<string, SyncError>();
  failFetchArticles: SyncError | null = null;
  failFetchArticle = new Map<number, SyncError>();
  /** When set, fetchArticle waits on the deferred for that id (for concurrency tests). */
  gate = new Map<number, Deferred<void>>();
  inflightFetches = 0;
  maxInflightFetches = 0;
  calls: Array<{ op: string; args: unknown[] }> = [];

  async fetchArticles(): Promise<ArticleSummary[]> {
    this.calls.push({ op: "fetchArticles", args: [] });
    if (this.failFetchArticles) throw this.failFetchArticles;
    return structuredClone(this.articles);
  }

  async fetchArticle(id: number): Promise<ArticleDetail> {
    this.calls.push({ op: "fetchArticle", args: [id] });
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
    const failure = this.failPostMarks.get(articleId);
    if (failure) throw failure;
  }

  async putSession(payload: SessionPayload, opts?: RequestOptions): Promise<void> {
    this.calls.push({ op: "putSession", args: [payload, opts] });
    const failure = this.failPutSession.get(payload.client_id);
    if (failure) throw failure;
  }

  ops(): string[] {
    return this.calls.map((c) => c.op);
  }
}

const NETWORK = new SyncError("network", null);
const GONE = new SyncError("http", 404);

async function setup(seed: (store: MemoryStore, api: FakeSyncApi) => Promise<void> = async () => {}) {
  const store = new MemoryStore();
  const api = new FakeSyncApi();
  await seed(store, api);
  return { store, api, syncer: new Syncer(store, api, { prefetchConcurrency: 2 }) };
}

describe("Syncer.pushMarks", () => {
  test("groups unsynced marks per article and marks them synced", async () => {
    const { store, api, syncer } = await setup(async (store) => {
      await store.addMarks([
        mark({ chunk_id: 10, article_id: 1, read_at: "a" }),
        mark({ chunk_id: 11, article_id: 1, read_at: "b" }),
        mark({ chunk_id: 20, article_id: 2, read_at: "c" }),
        mark({ chunk_id: 30, article_id: 3, synced: true }),
      ]);
    });

    const pushed = await syncer.pushMarks();
    const output = {
      pushed,
      calls: api.calls.map((c) => [c.args[0], (c.args[1] as MarkPayload[]).map((m) => m.chunk_id)]),
      remaining: (await store.unsyncedMarks()).length,
    };

    expect(output).toEqual({ pushed: 3, calls: [[1, [10, 11]], [2, [20]]], remaining: 0 });
  });

  test("passes keepalive through to the transport", async () => {
    const { api, syncer } = await setup(async (store) => {
      await store.addMarks([mark()]);
    });

    await syncer.pushMarks({ keepalive: true });

    expect(api.calls[0].args[2]).toEqual({ keepalive: true });
  });

  test("drops an article's marks on a terminal (4xx) error and continues", async () => {
    const { store, syncer } = await setup(async (store, api) => {
      await store.addMarks([mark({ chunk_id: 10, article_id: 1 }), mark({ chunk_id: 20, article_id: 2 })]);
      api.failPostMarks.set(1, GONE);
    });

    const pushed = await syncer.pushMarks();
    const output = {
      pushed,
      marks1: await store.marksForArticle(1),
      marks2Synced: (await store.marksForArticle(2)).map((m) => m.synced),
    };

    expect(output).toEqual({ pushed: 1, marks1: [], marks2Synced: [true] });
  });

  test("leaves marks unsynced and rethrows on a retryable error", async () => {
    const { store, syncer } = await setup(async (store, api) => {
      await store.addMarks([mark({ chunk_id: 10, article_id: 1 })]);
      api.failPostMarks.set(1, NETWORK);
    });

    const error = await syncer.pushMarks().catch((e: unknown) => e);
    const output = [error, (await store.unsyncedMarks()).length];

    expect(output).toEqual([NETWORK, 1]);
  });
});

describe("Syncer.pushSessions", () => {
  test("sends each unsynced session and records the acknowledged seconds", async () => {
    const { store, api, syncer } = await setup(async (store) => {
      await store.upsertSession(session({ client_id: "a", article_id: 1, active_seconds: 30, synced_seconds: 10 }));
      await store.upsertSession(session({ client_id: "b", article_id: 2, active_seconds: 5, synced_seconds: 5 }));
    });

    const pushed = await syncer.pushSessions();
    const output = {
      pushed,
      payload: api.calls[0].args[0],
      remaining: await store.unsyncedSessions(),
    };

    expect(output).toEqual({
      pushed: 1,
      payload: { client_id: "a", article_id: 1, started_at: "2026-01-02T00:00:00Z", active_seconds: 30 },
      remaining: [],
    });
  });

  test("drops a session on a terminal error and rethrows on a retryable one", async () => {
    const { store, api, syncer } = await setup(async (store, api) => {
      await store.upsertSession(session({ client_id: "gone", active_seconds: 9 }));
      api.failPutSession.set("gone", GONE);
    });
    await syncer.pushSessions();
    const afterTerminal = await store.unsyncedSessions();

    await store.upsertSession(session({ client_id: "flaky", active_seconds: 4 }));
    api.failPutSession.set("flaky", NETWORK);
    const error = await syncer.pushSessions().catch((e: unknown) => e);
    const output = [afterTerminal, error, (await store.unsyncedSessions()).map((s) => s.client_id)];

    expect(output).toEqual([[], NETWORK, ["flaky"]]);
  });
});

describe("Syncer.refreshArticles", () => {
  test("replaces the local list with the server list", async () => {
    const { store, syncer } = await setup(async (store, api) => {
      await store.replaceArticles([article({ id: 1 }), article({ id: 2 })]);
      api.articles = [article({ id: 2, percent_read: 50 }), article({ id: 3, added_at: "2026-01-02T00:00:00Z" })];
    });

    await syncer.refreshArticles();
    const output = (await store.listArticles()).map((a) => [a.id, a.percent_read]);

    expect(output).toEqual([[3, 0], [2, 50]]);
  });
});

describe("Syncer.prefetchBodies", () => {
  test("fetches bodies only for ready articles that are missing locally", async () => {
    const { store, api, syncer } = await setup(async (store, api) => {
      await store.replaceArticles([
        article({ id: 1 }),
        article({ id: 2 }),
        article({ id: 3, status: "pending" }),
      ]);
      await store.putBody(body({ article_id: 1 }));
      api.details.set(2, detail({ id: 2 }));
    });

    const fetched = await syncer.prefetchBodies();
    const output = [fetched, api.ops(), (await store.getBody(2))?.chunks.length];

    expect(output).toEqual([1, ["fetchArticle"], 2]);
  });

  test("refetches when extracted_at changed and drops that article's stale marks", async () => {
    const { store, syncer } = await setup(async (store, api) => {
      await store.replaceArticles([article({ id: 1, extracted_at: "v2" })]);
      await store.putBody(body({ article_id: 1, extracted_at: "v1" }));
      await store.addMarks([mark({ chunk_id: 10, article_id: 1 })]);
      api.details.set(1, detail({ id: 1, extracted_at: "v2" }));
    });

    await syncer.prefetchBodies();
    const output = [(await store.getBody(1))?.extracted_at, await store.marksForArticle(1)];

    expect(output).toEqual(["v2", []]);
  });

  test("refetches when the server percent is ahead of the local overlay", async () => {
    const { store, syncer } = await setup(async (store, api) => {
      await store.replaceArticles([article({ id: 1, percent_read: 50 })]);
      await store.putBody(body({ article_id: 1, chunks: [chunk({ id: 10 }), chunk({ id: 11 })] }));
      api.details.set(1, detail({ id: 1, chunks: [chunk({ id: 10, read: true }), chunk({ id: 11 })] }));
    });

    await syncer.prefetchBodies();
    const output = (await store.getBody(1))?.chunks.map((c) => c.read);

    expect(output).toEqual([true, false]);
  });

  test("does not refetch when the local overlay already matches the server percent", async () => {
    const { syncer } = await setup(async (store) => {
      await store.replaceArticles([article({ id: 1, percent_read: 50 })]);
      await store.putBody(body({ article_id: 1, chunks: [chunk({ id: 10 }), chunk({ id: 11 })] }));
      await store.addMarks([mark({ chunk_id: 10, article_id: 1 })]);
    });

    const fetched = await syncer.prefetchBodies();

    expect(fetched).toBe(0);
  });

  test("stores extracted_at from the fetched detail", async () => {
    const { store, syncer } = await setup(async (store, api) => {
      await store.replaceArticles([article({ id: 1, extracted_at: "v9" })]);
      api.details.set(1, detail({ id: 1, extracted_at: "v9" }));
    });

    await syncer.prefetchBodies();

    expect((await store.getBody(1))?.extracted_at).toBe("v9");
  });

  test("skips an article that 404s and continues with the rest", async () => {
    const { store, syncer } = await setup(async (store, api) => {
      await store.replaceArticles([article({ id: 1 }), article({ id: 2 })]);
      api.details.set(2, detail({ id: 2 }));
    });

    const fetched = await syncer.prefetchBodies();
    const output = [fetched, await store.getBody(1), (await store.getBody(2))?.article_id];

    expect(output).toEqual([1, undefined, 2]);
  });

  test("rethrows on a retryable error", async () => {
    const { syncer } = await setup(async (store, api) => {
      await store.replaceArticles([article({ id: 1 })]);
      api.failFetchArticle.set(1, NETWORK);
    });

    const output = await syncer.prefetchBodies().catch((e: unknown) => e);

    expect(output).toBe(NETWORK);
  });

  test("limits concurrent fetches to prefetchConcurrency", async () => {
    const { api, syncer } = await setup(async (store, api) => {
      await store.replaceArticles([1, 2, 3, 4, 5].map((id) => article({ id })));
      for (const id of [1, 2, 3, 4, 5]) {
        api.details.set(id, detail({ id }));
        api.gate.set(id, deferred<void>());
      }
    });

    const running = syncer.prefetchBodies();
    for (let i = 0; i < 50 && api.inflightFetches < 2; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
    const duringFirstWave = api.inflightFetches;
    for (const gate of api.gate.values()) gate.resolve();
    const fetched = await running;

    expect([duringFirstWave, api.maxInflightFetches, fetched]).toEqual([2, 2, 5]);
  });
});

describe("Syncer.syncAll", () => {
  test("pushes, then refreshes, then prefetches, and reports counts", async () => {
    const { api, syncer } = await setup(async (store, api) => {
      await store.addMarks([mark({ chunk_id: 10, article_id: 1 })]);
      await store.upsertSession(session({ client_id: "a", active_seconds: 3 }));
      api.articles = [article({ id: 1 })];
      api.details.set(1, detail({ id: 1 }));
    });

    const result = await syncer.syncAll();
    const output = { ops: api.ops(), result };

    expect(output).toEqual({
      ops: ["postMarks", "putSession", "fetchArticles", "fetchArticle"],
      result: { pushedMarks: 1, pushedSessions: 1, refreshed: true, prefetched: 1, error: null },
    });
  });

  test("stops at the first retryable error and reports it", async () => {
    const { api, syncer } = await setup(async (store, api) => {
      await store.addMarks([mark({ chunk_id: 10, article_id: 1 })]);
      api.failPostMarks.set(1, NETWORK);
    });

    const result = await syncer.syncAll();
    const output = { ops: api.ops(), result };

    expect(output).toEqual({
      ops: ["postMarks"],
      result: { pushedMarks: 0, pushedSessions: 0, refreshed: false, prefetched: 0, error: NETWORK },
    });
  });

  test("pushOnly skips refresh and prefetch", async () => {
    const { api, syncer } = await setup(async (store) => {
      await store.addMarks([mark()]);
    });

    await syncer.syncAll({ pushOnly: true, keepalive: true });

    expect([api.ops(), api.calls[0].args[2]]).toEqual([["postMarks"], { keepalive: true }]);
  });
});

describe("Syncer.pendingCount", () => {
  test("counts unsynced marks plus unsynced sessions", async () => {
    const { syncer } = await setup(async (store) => {
      await store.addMarks([mark({ chunk_id: 1 }), mark({ chunk_id: 2 }), mark({ chunk_id: 3, synced: true })]);
      await store.upsertSession(session({ client_id: "a", active_seconds: 2 }));
      await store.upsertSession(session({ client_id: "b", active_seconds: 2, synced_seconds: 2 }));
    });

    expect(await syncer.pendingCount()).toBe(3);
  });
});
