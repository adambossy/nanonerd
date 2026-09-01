import type { LocalSession, ReadMark, StoredArticle, StoredBody, StoredImage } from "./types";

export interface BodyVersion {
  article_id: number;
  extracted_at: string | null;
}

/**
 * Device-local persistence for the reader. This is the only seam through
 * which the app touches stored data; `IdbStore` backs it in the browser and
 * `MemoryStore` in tests. All methods are safe to call concurrently.
 */
export interface LocalStore {
  /** Replace the whole list. Articles absent from `articles` are removed along with their bodies, images, marks, and sessions. */
  replaceArticles(articles: StoredArticle[]): Promise<void>;
  /** Ordered like the server list: priority desc, then added_at desc. */
  listArticles(): Promise<StoredArticle[]>;
  getArticle(id: number): Promise<StoredArticle | undefined>;

  putBody(body: StoredBody): Promise<void>;
  getBody(articleId: number): Promise<StoredBody | undefined>;
  listBodyVersions(): Promise<BodyVersion[]>;

  /** Insert marks; a chunk already marked keeps its existing (earlier) record. */
  addMarks(marks: ReadMark[]): Promise<void>;
  marksForArticle(articleId: number): Promise<ReadMark[]>;
  unsyncedMarks(): Promise<ReadMark[]>;
  markMarksSynced(chunkIds: number[]): Promise<void>;
  deleteMarksForArticle(articleId: number): Promise<void>;

  /** Replace one article's image list; a url whose size is already known keeps it. */
  putImagesForArticle(articleId: number, urls: string[]): Promise<void>;
  imagesForArticle(articleId: number): Promise<StoredImage[]>;
  /** Images still waiting to be loaded and measured, across every article. */
  unmeasuredImages(): Promise<StoredImage[]>;
  /** Record a natural size against every row sharing this url. */
  setImageSize(url: string, width: number, height: number): Promise<void>;

  /** Insert or update; active_seconds and synced_seconds each take the max of old and new. */
  upsertSession(session: LocalSession): Promise<void>;
  /** Sessions whose active_seconds exceeds synced_seconds. */
  unsyncedSessions(): Promise<LocalSession[]>;
  /** synced_seconds = max(existing, seconds). No-op for unknown ids. */
  markSessionSynced(clientId: string, seconds: number): Promise<void>;
}
