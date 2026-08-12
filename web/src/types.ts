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
