import { describe, expect, test } from "vitest";
import { HttpSyncApi, SyncError } from "./transport";

interface Call {
  url: string;
  method: string | undefined;
  body: unknown;
  keepalive: boolean | undefined;
}

function fakeFetch(respond: (call: Call) => Response | Error) {
  const calls: Call[] = [];
  const fetchFn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call: Call = {
      url: String(input),
      method: init?.method,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      keepalive: init?.keepalive,
    };
    calls.push(call);
    const result = respond(call);
    if (result instanceof Error) throw result;
    return result;
  }) as typeof fetch;
  return { calls, fetchFn };
}

const ok = (payload: unknown = {}) =>
  new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
const status = (code: number) => new Response("", { status: code, statusText: "nope" });

describe("HttpSyncApi", () => {
  test("fetchArticles GETs the list", async () => {
    const { calls, fetchFn } = fakeFetch(() => ok([{ id: 1 }]));

    const output = await new HttpSyncApi(fetchFn).fetchArticles();

    expect([output, calls[0].url, calls[0].method]).toEqual([[{ id: 1 }], "/api/articles", undefined]);
  });

  test("fetchArticle GETs one article", async () => {
    const { calls, fetchFn } = fakeFetch(() => ok({ id: 7 }));

    const output = await new HttpSyncApi(fetchFn).fetchArticle(7);

    expect([output, calls[0].url]).toEqual([{ id: 7 }, "/api/articles/7"]);
  });

  test("postMarks POSTs marks JSON with keepalive", async () => {
    const { calls, fetchFn } = fakeFetch(() => ok({ percent_read: 1 }));
    const marks = [{ chunk_id: 10, read_at: "2026-01-01T00:00:00Z" }];

    await new HttpSyncApi(fetchFn).postMarks(3, marks, { keepalive: true });

    expect(calls[0]).toEqual({
      url: "/api/articles/3/progress",
      method: "POST",
      body: { marks },
      keepalive: true,
    });
  });

  test("putSession PUTs the session keyed by client_id", async () => {
    const { calls, fetchFn } = fakeFetch(() => ok({ client_id: "c", active_seconds: 5 }));
    const session = { client_id: "c", article_id: 3, started_at: "2026-01-01T00:00:00Z", active_seconds: 5 };

    await new HttpSyncApi(fetchFn).putSession(session);

    expect(calls[0]).toEqual({
      url: "/api/sessions/c",
      method: "PUT",
      body: { article_id: 3, started_at: "2026-01-01T00:00:00Z", active_seconds: 5 },
      keepalive: undefined,
    });
  });

  test("non-ok response throws an http SyncError with the status", async () => {
    const { fetchFn } = fakeFetch(() => status(404));

    const output = await new HttpSyncApi(fetchFn).postMarks(1, []).catch((e: unknown) => e);

    expect(output).toBeInstanceOf(SyncError);
    expect([(output as SyncError).kind, (output as SyncError).status]).toEqual(["http", 404]);
  });

  test("a thrown fetch becomes a network SyncError", async () => {
    const { fetchFn } = fakeFetch(() => new TypeError("Failed to fetch"));

    const output = await new HttpSyncApi(fetchFn).fetchArticles().catch((e: unknown) => e);

    expect([(output as SyncError).kind, (output as SyncError).status]).toEqual(["network", null]);
  });
});

describe("SyncError.retryable", () => {
  test.each([
    ["network", null, true],
    ["http", 503, true],
    ["http", 500, true],
    ["http", 404, false],
    ["http", 422, false],
    ["http", 409, false],
  ] as const)("%s %s → %s", (kind, status, expected) => {
    expect(new SyncError(kind, status).retryable).toBe(expected);
  });
});
