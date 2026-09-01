import type { BodyVersion, LocalStore } from "./store";
import type { LocalSession, ReadMark, StoredArticle, StoredBody, StoredImage } from "./types";

export function compareArticles(a: StoredArticle, b: StoredArticle): number {
  if (a.priority !== b.priority) return b.priority - a.priority;
  return b.added_at.localeCompare(a.added_at);
}

/** In-memory LocalStore: the reference implementation, used in tests and as a fallback without IndexedDB. */
export class MemoryStore implements LocalStore {
  private articles = new Map<number, StoredArticle>();
  private bodies = new Map<number, StoredBody>();
  private images = new Map<string, StoredImage>();
  private marks = new Map<number, ReadMark>();
  private sessions = new Map<string, LocalSession>();

  async replaceArticles(articles: StoredArticle[]): Promise<void> {
    const keep = new Set(articles.map((a) => a.id));
    for (const id of [...this.articles.keys()]) {
      if (keep.has(id)) continue;
      this.articles.delete(id);
      this.bodies.delete(id);
      await this.putImagesForArticle(id, []);
      await this.deleteMarksForArticle(id);
      for (const [clientId, s] of this.sessions) {
        if (s.article_id === id) this.sessions.delete(clientId);
      }
    }
    for (const a of articles) this.articles.set(a.id, structuredClone(a));
  }

  async listArticles(): Promise<StoredArticle[]> {
    return [...this.articles.values()].map((a) => structuredClone(a)).sort(compareArticles);
  }

  async getArticle(id: number): Promise<StoredArticle | undefined> {
    const found = this.articles.get(id);
    return found ? structuredClone(found) : undefined;
  }

  async putBody(body: StoredBody): Promise<void> {
    this.bodies.set(body.article_id, structuredClone(body));
  }

  async getBody(articleId: number): Promise<StoredBody | undefined> {
    const found = this.bodies.get(articleId);
    return found ? structuredClone(found) : undefined;
  }

  async listBodyVersions(): Promise<BodyVersion[]> {
    return [...this.bodies.values()].map((b) => ({
      article_id: b.article_id,
      extracted_at: b.extracted_at,
    }));
  }

  async putImagesForArticle(articleId: number, urls: string[]): Promise<void> {
    // Sizes are a property of the url, so collect them before dropping the
    // article's rows: a url that survives the rewrite keeps its measurement.
    const known = new Map([...this.images.values()].map((i) => [i.url, i]));
    for (const [key, image] of this.images) {
      if (image.article_id === articleId) this.images.delete(key);
    }
    for (const url of urls) {
      this.images.set(imageKey(articleId, url), {
        url,
        article_id: articleId,
        width: known.get(url)?.width ?? 0,
        height: known.get(url)?.height ?? 0,
      });
    }
  }

  async imagesForArticle(articleId: number): Promise<StoredImage[]> {
    return [...this.images.values()]
      .filter((i) => i.article_id === articleId)
      .map((i) => ({ ...i }));
  }

  async unmeasuredImages(): Promise<StoredImage[]> {
    return [...this.images.values()].filter((i) => i.width === 0).map((i) => ({ ...i }));
  }

  async setImageSize(url: string, width: number, height: number): Promise<void> {
    for (const image of this.images.values()) {
      if (image.url === url) {
        image.width = width;
        image.height = height;
      }
    }
  }

  async addMarks(marks: ReadMark[]): Promise<void> {
    for (const m of marks) {
      if (!this.marks.has(m.chunk_id)) this.marks.set(m.chunk_id, { ...m });
    }
  }

  async marksForArticle(articleId: number): Promise<ReadMark[]> {
    return [...this.marks.values()]
      .filter((m) => m.article_id === articleId)
      .map((m) => ({ ...m }));
  }

  async unsyncedMarks(): Promise<ReadMark[]> {
    return [...this.marks.values()].filter((m) => !m.synced).map((m) => ({ ...m }));
  }

  async markMarksSynced(chunkIds: number[]): Promise<void> {
    for (const id of chunkIds) {
      const found = this.marks.get(id);
      if (found) found.synced = true;
    }
  }

  async deleteMarksForArticle(articleId: number): Promise<void> {
    for (const [id, m] of this.marks) {
      if (m.article_id === articleId) this.marks.delete(id);
    }
  }

  async upsertSession(session: LocalSession): Promise<void> {
    const existing = this.sessions.get(session.client_id);
    this.sessions.set(session.client_id, mergeSession(existing, session));
  }

  async unsyncedSessions(): Promise<LocalSession[]> {
    return [...this.sessions.values()]
      .filter((s) => s.active_seconds > s.synced_seconds)
      .map((s) => ({ ...s }));
  }

  async markSessionSynced(clientId: string, seconds: number): Promise<void> {
    const found = this.sessions.get(clientId);
    if (found) found.synced_seconds = Math.max(found.synced_seconds, seconds);
  }
}

/** Images are keyed per (article, url): the same url may appear in several articles. */
function imageKey(articleId: number, url: string): string {
  return `${articleId}\u0000${url}`;
}

/** Shared merge rule for sessions: both counters are max registers. */
export function mergeSession(
  existing: LocalSession | undefined,
  incoming: LocalSession,
): LocalSession {
  if (!existing) return { ...incoming };
  return {
    ...existing,
    active_seconds: Math.max(existing.active_seconds, incoming.active_seconds),
    synced_seconds: Math.max(existing.synced_seconds, incoming.synced_seconds),
  };
}
