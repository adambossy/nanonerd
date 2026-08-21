import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { FakeEnv } from "./fakes";
import { SyncScheduler, type SyncRunner } from "./scheduler";
import type { SyncOptions, SyncResult } from "./syncer";
import { SyncError } from "./transport";
import type { SyncStatus } from "./types";

const OK: SyncResult = { pushedMarks: 0, pushedSessions: 0, refreshed: true, prefetched: 0, error: null };
const OFFLINE: SyncResult = { ...OK, refreshed: false, error: new SyncError("network", null) };

class FakeSyncer implements SyncRunner {
  calls: SyncOptions[] = [];
  results: SyncResult[] = [];
  pending = 0;
  /** When set, syncAll waits for this promise before resolving (for coalescing tests). */
  gate: Promise<void> | null = null;

  async syncAll(opts: SyncOptions = {}): Promise<SyncResult> {
    this.calls.push(opts);
    if (this.gate) await this.gate;
    return this.results.shift() ?? OK;
  }
  async pendingCount(): Promise<number> {
    return this.pending;
  }
}

async function flush(): Promise<void> {
  // Let queued promise callbacks (store reads, status updates) settle.
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

function setup(opts = {}) {
  const env = new FakeEnv();
  const syncer = new FakeSyncer();
  const scheduler = new SyncScheduler(syncer, env, { intervalMs: 5_000, initialBackoffMs: 1_000, maxBackoffMs: 8_000, ...opts });
  const statuses: SyncStatus[] = [];
  scheduler.subscribe((s) => statuses.push(s));
  return { env, syncer, scheduler, statuses };
}

describe("SyncScheduler", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test("start triggers exactly one full sync", async () => {
    const { syncer, scheduler } = setup();

    scheduler.start();
    await flush();

    expect(syncer.calls).toEqual([{}]);
  });

  test("subscribe delivers the current status immediately", () => {
    const { statuses } = setup();
    expect(statuses).toEqual([{ online: true, syncing: false, unsynced: 0, lastError: null }]);
  });

  test("requestSync during an in-flight sync coalesces into one follow-up", async () => {
    const { syncer, scheduler } = setup();
    let release!: () => void;
    syncer.gate = new Promise<void>((r) => (release = r));
    scheduler.start();
    await flush();

    scheduler.requestSync();
    scheduler.requestSync();
    scheduler.requestSync();
    syncer.gate = null;
    release();
    await flush();

    expect(syncer.calls.length).toBe(2);
  });

  test("successful sync reports online with the pending count", async () => {
    const { syncer, scheduler, statuses } = setup();
    syncer.pending = 2;

    scheduler.start();
    await flush();

    expect(statuses.at(-1)).toEqual({ online: true, syncing: false, unsynced: 2, lastError: null });
  });

  test("retryable failure marks offline, records the error, and retries with doubling backoff", async () => {
    const { syncer, scheduler, statuses } = setup();
    syncer.results = [OFFLINE, OFFLINE, OFFLINE, OK];
    scheduler.start();
    await flush();
    const afterFirst = statuses.at(-1);

    await vi.advanceTimersByTimeAsync(999);
    const callsBeforeFirstRetry = syncer.calls.length;
    await vi.advanceTimersByTimeAsync(1);
    await flush();
    const callsAfterFirstRetry = syncer.calls.length;
    await vi.advanceTimersByTimeAsync(2_000);
    await flush();
    const callsAfterSecondRetry = syncer.calls.length;
    await vi.advanceTimersByTimeAsync(4_000);
    await flush();

    expect({
      afterFirst,
      callsBeforeFirstRetry,
      callsAfterFirstRetry,
      callsAfterSecondRetry,
      finalCalls: syncer.calls.length,
      finalOnline: statuses.at(-1)?.online,
    }).toEqual({
      afterFirst: { online: false, syncing: false, unsynced: 0, lastError: "network error" },
      callsBeforeFirstRetry: 1,
      callsAfterFirstRetry: 2,
      callsAfterSecondRetry: 3,
      finalCalls: 4,
      finalOnline: true,
    });
  });

  test("backoff is capped at maxBackoffMs", async () => {
    const { syncer, scheduler } = setup({ initialBackoffMs: 1_000, maxBackoffMs: 2_000 });
    syncer.results = [OFFLINE, OFFLINE, OFFLINE, OFFLINE];
    scheduler.start();
    await flush();
    await vi.advanceTimersByTimeAsync(1_000); // retry 1 (after 1s)
    await flush();
    await vi.advanceTimersByTimeAsync(2_000); // retry 2 (after 2s)
    await flush();

    await vi.advanceTimersByTimeAsync(2_000); // retry 3 (capped at 2s, not 4s)
    await flush();

    expect(syncer.calls.length).toBe(4);
  });

  test("requestSync while backing off only refreshes the pending count", async () => {
    const { syncer, scheduler, statuses } = setup();
    syncer.results = [OFFLINE];
    scheduler.start();
    await flush();
    syncer.pending = 3;

    scheduler.requestSync();
    await flush();

    expect([syncer.calls.length, statuses.at(-1)?.unsynced]).toEqual([1, 3]);
  });

  test("online event cancels backoff and syncs immediately", async () => {
    const { env, syncer, scheduler, statuses } = setup();
    syncer.results = [OFFLINE, OK];
    scheduler.start();
    await flush();

    env.emit("online");
    await flush();
    await vi.advanceTimersByTimeAsync(10_000);
    await flush();

    expect([syncer.calls.length, statuses.at(-1)?.online]).toEqual([2, true]);
  });

  test("visible event requests a sync", async () => {
    const { env, syncer, scheduler } = setup();
    scheduler.start();
    await flush();

    env.emit("visible");
    await flush();

    expect(syncer.calls.length).toBe(2);
  });

  test("hidden event runs a push-only keepalive sync", async () => {
    const { env, syncer, scheduler } = setup();
    scheduler.start();
    await flush();

    env.emit("hidden");
    await flush();

    expect(syncer.calls.at(-1)).toEqual({ pushOnly: true, keepalive: true });
  });

  test("interval tick syncs only when something is pending and the tab is visible", async () => {
    const { env, syncer, scheduler } = setup();
    scheduler.start();
    await flush();

    await vi.advanceTimersByTimeAsync(5_000);
    await flush();
    const afterIdleTick = syncer.calls.length;
    syncer.pending = 1;
    env.visible = false;
    await vi.advanceTimersByTimeAsync(5_000);
    await flush();
    const afterHiddenTick = syncer.calls.length;
    env.visible = true;
    await vi.advanceTimersByTimeAsync(5_000);
    await flush();

    expect([afterIdleTick, afterHiddenTick, syncer.calls.length]).toEqual([1, 1, 2]);
  });

  test("stop unsubscribes from events and timers", async () => {
    const { env, syncer, scheduler } = setup();
    scheduler.start();
    await flush();

    scheduler.stop();
    env.emit("online");
    env.emit("visible");
    syncer.pending = 5;
    await vi.advanceTimersByTimeAsync(60_000);
    await flush();

    expect(syncer.calls.length).toBe(1);
  });

  test("a non-SyncError thrown by the syncer is surfaced as lastError without going offline", async () => {
    const broken: SyncRunner = {
      syncAll: async () => {
        throw new Error("bug");
      },
      pendingCount: async () => 0,
    };
    const statuses: SyncStatus[] = [];
    const scheduler = new SyncScheduler(broken, new FakeEnv());
    scheduler.subscribe((st) => statuses.push(st));

    scheduler.start();
    await flush();

    expect(statuses.at(-1)).toMatchObject({ online: true, syncing: false, lastError: "Error: bug" });
  });

  test("syncNow resolves with the run's result", async () => {
    const { syncer, scheduler } = setup();
    syncer.results = [{ ...OK, prefetched: 4 }];

    const output = await scheduler.syncNow();

    expect([output.prefetched, syncer.calls]).toEqual([4, [{}]]);
  });

  test("syncNow during an in-flight sync waits for the coalesced follow-up run", async () => {
    const { syncer, scheduler } = setup();
    let release!: () => void;
    syncer.gate = new Promise<void>((r) => (release = r));
    syncer.results = [{ ...OK, prefetched: 1 }, { ...OK, prefetched: 2 }];
    scheduler.start();
    await flush();

    const waiting = scheduler.syncNow();
    syncer.gate = null;
    release();
    const output = await waiting;

    expect([output.prefetched, syncer.calls.length]).toEqual([2, 2]);
  });

  test("syncNow during backoff runs immediately instead of waiting for the retry", async () => {
    const { syncer, scheduler } = setup();
    syncer.results = [OFFLINE, OK];
    scheduler.start();
    await flush();

    const output = await scheduler.syncNow();
    await vi.advanceTimersByTimeAsync(10_000);
    await flush();

    expect([output.error, syncer.calls.length]).toEqual([null, 2]);
  });

  test("a queued full sync is not downgraded by a concurrent push-only flush", async () => {
    const { env, syncer, scheduler } = setup();
    let release!: () => void;
    syncer.gate = new Promise<void>((r) => (release = r));
    scheduler.start();
    await flush();

    scheduler.requestSync();
    env.emit("hidden");
    syncer.gate = null;
    release();
    await flush();

    expect(syncer.calls).toEqual([{}, { pushOnly: false, keepalive: true }]);
  });
});
