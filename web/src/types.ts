export type FidelityStatus = "ok" | "degraded" | "not_article" | "blocked";

export interface SnapshotState {
  status: "none" | "pending" | "ready" | "failed";
  available: boolean;
  bytes: number;
  captured_at: string | null;
  error: string | null;
}

export interface ArticleSummary {
  id: number;
  title: string;
  url: string;
  site_name: string | null;
  author: string | null;
  status: "pending" | "ready" | "failed";
  error: string | null;
  word_count: number;
  priority: number;
  percent_read: number;
  categories: string[];
  added_at: string;
  source_kind: "live" | "archive_ph" | "wayback" | null;
  source_url: string | null;
  extracted_at: string | null;
  fidelity_status: FidelityStatus | null;
  fidelity_score: number | null;
  fidelity_reasons: string[];
  // Travels with the summary so the offline list refresh sees capture progress.
  snapshot: SnapshotState;
}

export interface ChunkData {
  id: number;
  position: number;
  html: string;
  word_count: number;
  read: boolean;
}

export interface ArticleDetail extends ArticleSummary {
  chunks: ChunkData[];
}

export interface ResumeTarget {
  article_id: number;
  title: string;
}

export interface HistoryEntry {
  chunk_id: number;
  article_id: number;
  article_title: string;
  position: number;
  word_count: number;
  read_at: string;
  snippet: string;
}

export interface StatsTotals {
  active_seconds: number;
  articles_saved: number;
  articles_finished: number;
  words_read: number;
}

export interface TopicStats {
  name: string;
  saved: number;
  read_through: number;
  active_seconds: number;
}

export interface DailyStats {
  date: string;
  active_seconds: number;
}

export interface TopArticle {
  id: number;
  title: string;
  active_seconds: number;
  percent_read: number;
}

export interface StatsResponse {
  totals: StatsTotals;
  topics: TopicStats[];
  daily: DailyStats[];
  top_articles: TopArticle[];
}
