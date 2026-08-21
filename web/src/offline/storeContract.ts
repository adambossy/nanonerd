import { beforeEach, describe, expect, test } from "vitest";
import { article, body, mark, session } from "./fixtures";
import type { LocalStore } from "./store";

/**
 * Behavioral contract every LocalStore implementation must satisfy.
 * Each implementation's spec file calls this with a factory for a fresh store.
 */
export function describeStoreContract(
  name: string,
  makeStore: () => Promise<LocalStore>,
): void {
  describe(`${name} LocalStore contract`, () => {
    let store: LocalStore;
    beforeEach(async () => {
      store = await makeStore();
    });

    test("replaceArticles then listArticles orders by priority desc, added_at desc", async () => {
      const input = [
        article({ id: 1, priority: 0, added_at: "2026-01-01T00:00:00Z" }),
        article({ id: 2, priority: 5, added_at: "2026-01-01T00:00:00Z" }),
        article({ id: 3, priority: 0, added_at: "2026-01-03T00:00:00Z" }),
      ];

      await store.replaceArticles(input);
      const output = (await store.listArticles()).map((a) => a.id);

      expect(output).toEqual([2, 3, 1]);
    });

    test("replaceArticles prunes removed articles with their bodies, marks, and sessions", async () => {
      await store.replaceArticles([article({ id: 1 }), article({ id: 2 })]);
      await store.putBody(body({ article_id: 1 }));
      await store.putBody(body({ article_id: 2, chunks: [] }));
      await store.addMarks([mark({ chunk_id: 10, article_id: 1 }), mark({ chunk_id: 20, article_id: 2 })]);
      await store.upsertSession(session({ client_id: "s1", article_id: 1, active_seconds: 5 }));
      await store.upsertSession(session({ client_id: "s2", article_id: 2, active_seconds: 5 }));

      await store.replaceArticles([article({ id: 2 })]);
      const output = {
        articles: (await store.listArticles()).map((a) => a.id),
        body1: await store.getBody(1),
        body2: (await store.getBody(2))?.article_id,
        marks1: await store.marksForArticle(1),
        marks2: (await store.marksForArticle(2)).map((m) => m.chunk_id),
        sessions: (await store.unsyncedSessions()).map((s) => s.client_id),
      };

      expect(output).toEqual({
        articles: [2],
        body1: undefined,
        body2: 2,
        marks1: [],
        marks2: [20],
        sessions: ["s2"],
      });
    });

    test("replaceArticles overwrites existing article fields", async () => {
      await store.replaceArticles([article({ id: 1, percent_read: 10 })]);

      await store.replaceArticles([article({ id: 1, percent_read: 40 })]);
      const output = (await store.getArticle(1))?.percent_read;

      expect(output).toBe(40);
    });

    test("getArticle returns undefined for unknown id", async () => {
      expect(await store.getArticle(99)).toBeUndefined();
    });

    test("putBody and getBody round-trip", async () => {
      const input = body({ article_id: 7 });

      await store.putBody(input);
      const output = await store.getBody(7);

      expect(output).toEqual(input);
    });

    test("listBodyVersions reports article_id and extracted_at for each body", async () => {
      await store.putBody(body({ article_id: 1, extracted_at: "a" }));
      await store.putBody(body({ article_id: 2, extracted_at: null }));

      const output = (await store.listBodyVersions()).sort((x, y) => x.article_id - y.article_id);

      expect(output).toEqual([
        { article_id: 1, extracted_at: "a" },
        { article_id: 2, extracted_at: null },
      ]);
    });

    test("addMarks keeps the existing record for an already-marked chunk", async () => {
      await store.addMarks([mark({ chunk_id: 10, read_at: "2026-01-01T00:00:00Z", synced: true })]);

      await store.addMarks([mark({ chunk_id: 10, read_at: "2026-01-05T00:00:00Z", synced: false })]);
      const output = await store.marksForArticle(1);

      expect(output).toEqual([mark({ chunk_id: 10, read_at: "2026-01-01T00:00:00Z", synced: true })]);
    });

    test("marksForArticle returns only that article's marks", async () => {
      await store.addMarks([
        mark({ chunk_id: 10, article_id: 1 }),
        mark({ chunk_id: 11, article_id: 1 }),
        mark({ chunk_id: 20, article_id: 2 }),
      ]);

      const output = (await store.marksForArticle(1)).map((m) => m.chunk_id).sort();

      expect(output).toEqual([10, 11]);
    });

    test("unsyncedMarks and markMarksSynced", async () => {
      await store.addMarks([
        mark({ chunk_id: 10, synced: false }),
        mark({ chunk_id: 11, synced: false }),
        mark({ chunk_id: 12, synced: true }),
      ]);

      await store.markMarksSynced([10]);
      const output = (await store.unsyncedMarks()).map((m) => m.chunk_id);

      expect(output).toEqual([11]);
    });

    test("deleteMarksForArticle removes synced and unsynced marks for that article only", async () => {
      await store.addMarks([
        mark({ chunk_id: 10, article_id: 1, synced: true }),
        mark({ chunk_id: 11, article_id: 1, synced: false }),
        mark({ chunk_id: 20, article_id: 2 }),
      ]);

      await store.deleteMarksForArticle(1);
      const output = [await store.marksForArticle(1), (await store.marksForArticle(2)).length];

      expect(output).toEqual([[], 1]);
    });

    test("upsertSession takes the max of active and synced seconds", async () => {
      await store.upsertSession(session({ active_seconds: 30, synced_seconds: 20 }));

      await store.upsertSession(session({ active_seconds: 25, synced_seconds: 0 }));
      const output = await store.unsyncedSessions();

      expect(output).toEqual([session({ active_seconds: 30, synced_seconds: 20 })]);
    });

    test("unsyncedSessions excludes fully synced sessions", async () => {
      await store.upsertSession(session({ client_id: "a", active_seconds: 10, synced_seconds: 10 }));
      await store.upsertSession(session({ client_id: "b", active_seconds: 11, synced_seconds: 10 }));

      const output = (await store.unsyncedSessions()).map((s) => s.client_id);

      expect(output).toEqual(["b"]);
    });

    test("markSessionSynced raises synced_seconds monotonically and ignores unknown ids", async () => {
      await store.upsertSession(session({ client_id: "a", active_seconds: 50, synced_seconds: 0 }));

      await store.markSessionSynced("a", 40);
      await store.markSessionSynced("a", 30);
      await store.markSessionSynced("missing", 99);
      const output = await store.unsyncedSessions();

      expect(output).toEqual([session({ client_id: "a", active_seconds: 50, synced_seconds: 40 })]);
    });
  });
}
