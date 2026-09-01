import "fake-indexeddb/auto";
import { openDB } from "idb";
import { expect, test } from "vitest";
import { article, body, mark } from "./fixtures";
import { IdbStore } from "./idbStore";
import { describeStoreContract } from "./storeContract";

let counter = 0;

describeStoreContract("IdbStore", async () => new IdbStore(`test-${counter++}`));

/** The v1 schema, exactly as it shipped before the images store existed. */
async function createV1Database(name: string): Promise<void> {
  const db = await openDB(name, 1, {
    upgrade(db) {
      db.createObjectStore("articles", { keyPath: "id" });
      db.createObjectStore("bodies", { keyPath: "article_id" });
      const marks = db.createObjectStore("marks", { keyPath: "chunk_id" });
      marks.createIndex("by_article", "article_id");
      marks.createIndex("by_synced", "synced");
      const sessions = db.createObjectStore("sessions", { keyPath: "client_id" });
      sessions.createIndex("by_article", "article_id");
    },
  });
  const tx = db.transaction(["articles", "bodies", "marks"], "readwrite");
  await tx.objectStore("articles").put(article({ id: 1 }));
  await tx.objectStore("bodies").put(body({ article_id: 1 }));
  await tx.objectStore("marks").put({ ...mark({ chunk_id: 10, article_id: 1 }), synced: 0 });
  await tx.done;
  db.close();
}

test("upgrading from v1 keeps existing data and adds the images store", async () => {
  const name = `upgrade-${counter++}`;
  await createV1Database(name);

  const store = new IdbStore(name);
  await store.putImagesForArticle(1, ["/media/a.jpg"]);
  const output = {
    articles: (await store.listArticles()).map((a) => a.id),
    chunks: (await store.getBody(1))?.chunks.length,
    marks: (await store.marksForArticle(1)).map((m) => m.chunk_id),
    images: (await store.imagesForArticle(1)).map((i) => i.url),
  };

  expect(output).toEqual({ articles: [1], chunks: 2, marks: [10], images: ["/media/a.jpg"] });
});
