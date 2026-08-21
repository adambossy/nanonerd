import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { FakeEnv, FakeSyncApi } from "./fakes";
import { article, chunk, detail } from "./fixtures";
import { MemoryStore } from "./memoryStore";
import { loadArticle, loadArticleList } from "./repository";
import { SyncScheduler } from "./scheduler";
import { Syncer } from "./syncer";
import type { SyncStatus } from "./types";

/**
 * Cross-layer test: real MemoryStore + Syncer + SyncScheduler, fake transport
 * and browser env. Exercises the actual composition the app runs, minus
 * IndexedDB and the DOM (each of which has its own contract/adapter tests).
 */

async function flush(): Promise<void> {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

/** Wait until the scheduler reports it is no longer syncing (bounded). */
async function settle(statuses: SyncStatus[]): Promise<void> {
  for (let i = 0; i < 2_000 && statuses.at(-1)?.syncing; i++) await Promise.resolve();
  await flush();
}

function setup() {
  const store = new MemoryStore();
  const api = new FakeSyncApi();
  const env = new FakeEnv();
  const syncer = new Syncer(store, api);
  const scheduler = new SyncScheduler(syncer, env, { intervalMs: 5_000, initialBackoffMs: 1_000 });
  const statuses: SyncStatus[] = [];
  scheduler.subscribe((s) => statuses.push(s));
  api.articles = [article({ id: 1, percent_read: 0, word_count: 100 })];
  api.details.set(
    1,
    detail({
      id: 1,
      chunks: [chunk({ id: 10, position: 0, word_count: 50 }), chunk({ id: 11, position: 1, word_count: 50 })],
    }),
  );
  return { store, api, env, scheduler, statuses };
}

describe("offline layer end to end", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test("start online: list and body are cached, article is readable from the store", async () => {
    const { store, scheduler } = setup();

    scheduler.start();
    await flush();
    const output = {
      list: (await loadArticleList(store)).map((a) => [a.id, a.percent_read]),
      chunks: (await loadArticle(store, 1))?.chunks.map((c) => c.read),
    };

    expect(output).toEqual({ list: [[1, 0]], chunks: [false, false] });
  });

  test("read offline, then come online: marks and session replay once and the UI overlay is right throughout", async () => {
    const { store, api, env, scheduler, statuses } = setup();
    scheduler.start();
    await settle(statuses);

    // Go offline and read half the article; the page persists at event time and asks for a sync.
    api.offline = true;
    await store.addMarks([{ chunk_id: 10, article_id: 1, read_at: "2026-01-02T00:00:00Z", synced: false }]);
    await store.upsertSession({
      client_id: "s1",
      article_id: 1,
      started_at: "2026-01-02T00:00:00Z",
      active_seconds: 7,
      synced_seconds: 0,
    });
    scheduler.requestSync();
    await settle(statuses);
    const whileOffline = {
      status: statuses.at(-1),
      percent: (await loadArticleList(store))[0].percent_read,
      serverMarks: api.acceptedMarks.get(1) ?? [],
    };

    // Back online: the browser fires "online"; one scheduler-driven sync replays everything.
    api.offline = false;
    api.articles = [article({ id: 1, percent_read: 50, word_count: 100 })];
    env.emit("online");
    await settle(statuses);
    const afterOnline = {
      status: statuses.at(-1),
      serverMarks: api.acceptedMarks.get(1)?.map((m) => m.chunk_id),
      serverSession: api.acceptedSessions.get("s1")?.active_seconds,
      percent: (await loadArticleList(store))[0].percent_read,
    };

    // Nothing left to push: further ticks are quiet.
    const callsBefore = api.calls.length;
    await vi.advanceTimersByTimeAsync(15_000);
    await flush();

    expect({ whileOffline, afterOnline, extraCalls: api.calls.length - callsBefore }).toEqual({
      whileOffline: {
        status: { online: false, syncing: false, unsynced: 2, lastError: "network error" },
        percent: 50,
        serverMarks: [],
      },
      afterOnline: {
        status: { online: true, syncing: false, unsynced: 0, lastError: null },
        serverMarks: [10],
        serverSession: 7,
        percent: 50,
      },
      extraCalls: 0,
    });
  });

  test("syncNow makes a newly saved article readable without waiting for the next tick", async () => {
    const { store, api, scheduler } = setup();
    scheduler.start();
    await flush();
    api.articles.push(article({ id: 2, added_at: "2026-02-01T00:00:00Z" }));
    api.details.set(2, detail({ id: 2 }));

    const before = await loadArticle(store, 2);
    await scheduler.syncNow();
    const after = await loadArticle(store, 2);

    expect([before, after?.id]).toEqual([undefined, 2]);
  });

  test("server re-extraction invalidates the cached body and drops stale local marks", async () => {
    const { store, api, scheduler } = setup();
    scheduler.start();
    await flush();
    await store.addMarks([{ chunk_id: 10, article_id: 1, read_at: "2026-01-02T00:00:00Z", synced: true }]);
    api.articles = [article({ id: 1, extracted_at: "v2" })];
    api.details.set(1, detail({ id: 1, extracted_at: "v2", chunks: [chunk({ id: 99, position: 0 })] }));

    await scheduler.syncNow();
    const output = {
      chunkIds: (await loadArticle(store, 1))?.chunks.map((c) => c.id),
      marks: await store.marksForArticle(1),
    };

    expect(output).toEqual({ chunkIds: [99], marks: [] });
  });
});
