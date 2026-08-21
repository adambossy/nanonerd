import { openDB, type DBSchema, type IDBPDatabase } from "idb";
import { compareArticles, mergeSession } from "./memoryStore";
import type { BodyVersion, LocalStore } from "./store";
import type { LocalSession, ReadMark, StoredArticle, StoredBody } from "./types";

// Booleans are not valid IndexedDB index keys, so `synced` is stored as 0 | 1.
interface MarkRow extends Omit<ReadMark, "synced"> {
  synced: 0 | 1;
}

interface ReaderDB extends DBSchema {
  articles: { key: number; value: StoredArticle };
  bodies: { key: number; value: StoredBody };
  marks: {
    key: number;
    value: MarkRow;
    indexes: { by_article: number; by_synced: 0 | 1 };
  };
  sessions: { key: string; value: LocalSession };
}

const DB_VERSION = 1;

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
      upgrade(db) {
        db.createObjectStore("articles", { keyPath: "id" });
        db.createObjectStore("bodies", { keyPath: "article_id" });
        const marks = db.createObjectStore("marks", { keyPath: "chunk_id" });
        marks.createIndex("by_article", "article_id");
        marks.createIndex("by_synced", "synced");
        db.createObjectStore("sessions", { keyPath: "client_id" });
      },
    });
  }

  async replaceArticles(articles: StoredArticle[]): Promise<void> {
    const db = await this.db;
    const tx = db.transaction(["articles", "bodies", "marks"], "readwrite");
    const keep = new Set(articles.map((a) => a.id));
    for (const id of await tx.objectStore("articles").getAllKeys()) {
      if (keep.has(id)) continue;
      await tx.objectStore("articles").delete(id);
      await tx.objectStore("bodies").delete(id);
      for (const key of await tx.objectStore("marks").index("by_article").getAllKeys(id)) {
        await tx.objectStore("marks").delete(key);
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

  async deleteBody(articleId: number): Promise<void> {
    await (await this.db).delete("bodies", articleId);
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
