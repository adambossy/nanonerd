import type { ArticleSummary, ChunkData } from "../types";

/** Article summary as last seen from the server. `percent_read` is the server's number. */
export type StoredArticle = ArticleSummary;

/** Cached article body, keyed by article and versioned by `extracted_at`. */
export interface StoredBody {
  article_id: number;
  extracted_at: string | null;
  chunks: ChunkData[];
}

/** A chunk the user read on this device. Grow-only; earliest read_at wins. */
export interface ReadMark {
  chunk_id: number;
  article_id: number;
  read_at: string; // ISO-8601
  synced: boolean;
}

/** A reading session owned by this device; active_seconds only grows. */
export interface LocalSession {
  client_id: string; // UUID minted on the device
  article_id: number;
  started_at: string; // ISO-8601
  active_seconds: number;
  synced_seconds: number; // highest active_seconds the server has acknowledged
}

export interface SyncStatus {
  online: boolean;
  syncing: boolean;
  unsynced: number;
  lastError: string | null;
}
