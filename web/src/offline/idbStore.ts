import { openDB, type DBSchema, type IDBPDatabase } from "idb";
import { compareArticles, mergeSession } from "./memoryStore";
import type { BodyVersion, LocalStore } from "./store";
import type { LocalSession, ReadMark, StoredArticle, StoredBody, StoredImage } from "./types";

// Booleans are not valid IndexedDB index keys, so `synced` is stored as 0 | 1.
interface MarkRow extends Omit<ReadMark, "synced"> {
  synced: 0 | 1;
}

interface ReaderDB extends DBSchema {
  articles: { key: number; value: StoredArticle };
  bodies: { key: number; value: StoredBody };
  images: {
    key: [number, string];
    value: StoredImage;
    indexes: { by_article: number; by_url: string; by_width: number };
  };
  marks: {
    key: number;
    value: MarkRow;
    indexes: { by_article: number; by_synced: 0 | 1 };
  };
  sessions: { key: string; value: LocalSession; indexes: { by_article: number } };
}

const DB_VERSION = 2;

function toRow(mark: ReadMark): MarkRow {
  return { ...mark, synced: mark.synced ? 1 : 0 };
}

function fromRow(row: MarkRow): ReadMark {
  return { ...row, synced: row.synced === 1 };
}

/** IndexedDB-backed LocalStore. One database per `name`; the app uses a single fixed name. */
export class IdbStore implements LocalStore {
  private readonly db: Promise<IDBPDatabase<ReaderDB>>;

  constructor(name = "nanonerd-reader") {
    this.db = openDB<ReaderDB>(name, DB_VERSION, {
      upgrade(db, oldVersion) {
        if (oldVersion < 1) {
          db.createObjectStore("articles", { keyPath: "id" });
          db.createObjectStore("bodies", { keyPath: "article_id" });
          const marks = db.createObjectStore("marks", { keyPath: "chunk_id" });
          marks.createIndex("by_article", "article_id");
          marks.createIndex("by_synced", "synced");
          const sessions = db.createObjectStore("sessions", { keyPath: "client_id" });
          sessions.createIndex("by_article", "article_id");
        }
        if (oldVersion < 2) {
          // Bodies cached before this store existed are reconciled by the
          // Syncer on the next sync, so there is nothing to backfill here.
          const images = db.createObjectStore("images", {
            keyPath: ["article_id", "url"],
          });
          images.createIndex("by_article", "article_id");
          images.createIndex("by_url", "url");
          images.createIndex("by_width", "width");
        }
      },
    });
  }

  async replaceArticles(articles: StoredArticle[]): Promise<void> {
    const db = await this.db;
    const tx = db.transaction(
      ["articles", "bodies", "images", "marks", "sessions"],
      "readwrite",
    );
    const keep = new Set(articles.map((a) => a.id));
    for (const id of await tx.objectStore("articles").getAllKeys()) {
      if (keep.has(id)) continue;
      await tx.objectStore("articles").delete(id);
      await tx.objectStore("bodies").delete(id);
      for (const key of await tx.objectStore("images").index("by_article").getAllKeys(id)) {
        await tx.objectStore("images").delete(key);
      }
      for (const key of await tx.objectStore("marks").index("by_article").getAllKeys(id)) {
        await tx.objectStore("marks").delete(key);
      }
      for (const key of await tx.objectStore("sessions").index("by_article").getAllKeys(id)) {
        await tx.objectStore("sessions").delete(key);
      }
    }
    for (const a of articles) await tx.objectStore("articles").put(a);
    await tx.done;
  }

  async listArticles(): Promise<StoredArticle[]> {
    return (await (await this.db).getAll("articles")).sort(compareArticles);
  }

  async getArticle(id: number): Promise<StoredArticle | undefined> {
    return (await this.db).get("articles", id);
  }

  async putBody(body: StoredBody): Promise<void> {
    await (await this.db).put("bodies", body);
  }

  async getBody(articleId: number): Promise<StoredBody | undefined> {
    return (await this.db).get("bodies", articleId);
  }

  async listBodyVersions(): Promise<BodyVersion[]> {
    const bodies = await (await this.db).getAll("bodies");
    return bodies.map((b) => ({ article_id: b.article_id, extracted_at: b.extracted_at }));
  }

  async putImagesForArticle(articleId: number, urls: string[]): Promise<void> {
    const tx = (await this.db).transaction("images", "readwrite");
    const sizes = new Map<string, StoredImage>();
    for (const url of urls) {
      const known = await tx.store.index("by_url").get(url);
      if (known) sizes.set(url, known);
    }
    for (const key of await tx.store.index("by_article").getAllKeys(articleId)) {
      await tx.store.delete(key);
    }
    for (const url of urls) {
      const known = sizes.get(url);
      await tx.store.put({
        url,
        article_id: articleId,
        width: known?.width ?? 0,
        height: known?.height ?? 0,
      });
    }
    await tx.done;
  }

  async imagesForArticle(articleId: number): Promise<StoredImage[]> {
    return (await this.db).getAllFromIndex("images", "by_article", articleId);
  }

  async unmeasuredImages(): Promise<StoredImage[]> {
    return (await this.db).getAllFromIndex("images", "by_width", 0);
  }

  async setImageSize(url: string, width: number, height: number): Promise<void> {
    const tx = (await this.db).transaction("images", "readwrite");
    for (const row of await tx.store.index("by_url").getAll(url)) {
      await tx.store.put({ ...row, width, height });
    }
    await tx.done;
  }

  async addMarks(marks: ReadMark[]): Promise<void> {
    const tx = (await this.db).transaction("marks", "readwrite");
    for (const m of marks) {
      if ((await tx.store.getKey(m.chunk_id)) === undefined) await tx.store.add(toRow(m));
    }
    await tx.done;
  }

  async marksForArticle(articleId: number): Promise<ReadMark[]> {
    const rows = await (await this.db).getAllFromIndex("marks", "by_article", articleId);
    return rows.map(fromRow);
  }

  async unsyncedMarks(): Promise<ReadMark[]> {
    const rows = await (await this.db).getAllFromIndex("marks", "by_synced", 0);
    return rows.map(fromRow);
  }

  async markMarksSynced(chunkIds: number[]): Promise<void> {
    const tx = (await this.db).transaction("marks", "readwrite");
    for (const id of chunkIds) {
      const row = await tx.store.get(id);
      if (row) await tx.store.put({ ...row, synced: 1 });
    }
    await tx.done;
  }

  async deleteMarksForArticle(articleId: number): Promise<void> {
    const tx = (await this.db).transaction("marks", "readwrite");
    for (const key of await tx.store.index("by_article").getAllKeys(articleId)) {
      await tx.store.delete(key);
    }
    await tx.done;
  }

  async upsertSession(session: LocalSession): Promise<void> {
    const tx = (await this.db).transaction("sessions", "readwrite");
    const existing = await tx.store.get(session.client_id);
    await tx.store.put(mergeSession(existing, session));
    await tx.done;
  }

  async unsyncedSessions(): Promise<LocalSession[]> {
    const all = await (await this.db).getAll("sessions");
    return all.filter((s) => s.active_seconds > s.synced_seconds);
  }

  async markSessionSynced(clientId: string, seconds: number): Promise<void> {
    const tx = (await this.db).transaction("sessions", "readwrite");
    const existing = await tx.store.get(clientId);
    if (existing) {
      await tx.store.put({
        ...existing,
        synced_seconds: Math.max(existing.synced_seconds, seconds),
      });
    }
    await tx.done;
  }
}
