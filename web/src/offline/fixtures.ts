import type { ArticleDetail, ChunkData } from "../types";
import type { LocalSession, ReadMark, StoredArticle, StoredBody } from "./types";

// Test fixtures shared by the offline test suites. Not shipped (only imported by *.test.ts).

export function article(overrides: Partial<StoredArticle> = {}): StoredArticle {
  return {
    id: 1,
    title: "Article",
    url: "https://example.com/1",
    site_name: "Example",
    author: null,
    status: "ready",
    error: null,
    word_count: 100,
    priority: 0,
    percent_read: 0,
    categories: [],
    added_at: "2026-01-01T00:00:00Z",
    extracted_at: "2026-01-01T00:01:00Z",
    fidelity_status: null,
    fidelity_score: null,
    fidelity_reasons: [],
    ...overrides,
  };
}

export function chunk(overrides: Partial<ChunkData> = {}): ChunkData {
  return {
    id: 10,
    position: 0,
    html: "<p>x</p>",
    word_count: 50,
    read: false,
    ...overrides,
  };
}

export function body(overrides: Partial<StoredBody> = {}): StoredBody {
  return {
    article_id: 1,
    extracted_at: "2026-01-01T00:01:00Z",
    chunks: [chunk({ id: 10, position: 0 }), chunk({ id: 11, position: 1 })],
    ...overrides,
  };
}

export function detail(overrides: Partial<ArticleDetail> = {}): ArticleDetail {
  const base = article(overrides);
  return { ...base, chunks: body({ article_id: base.id }).chunks, ...overrides };
}

export function mark(overrides: Partial<ReadMark> = {}): ReadMark {
  return {
    chunk_id: 10,
    article_id: 1,
    read_at: "2026-01-02T00:00:00Z",
    synced: false,
    ...overrides,
  };
}

export function session(overrides: Partial<LocalSession> = {}): LocalSession {
  return {
    client_id: "00000000-0000-4000-8000-000000000001",
    article_id: 1,
    started_at: "2026-01-02T00:00:00Z",
    active_seconds: 0,
    synced_seconds: 0,
    ...overrides,
  };
}
