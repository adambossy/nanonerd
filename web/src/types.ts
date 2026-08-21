export type FidelityStatus = "ok" | "degraded" | "not_article" | "blocked";

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
  extracted_at: string | null;
  fidelity_status: FidelityStatus | null;
  fidelity_score: number | null;
  fidelity_reasons: string[];
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
