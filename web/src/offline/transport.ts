import type { ArticleDetail, ArticleSummary } from "../types";

/**
 * HTTP transport for sync. The only module in src/offline that knows URLs.
 * Every write is idempotent on the server, so callers may retry freely.
 */

export class SyncError extends Error {
  constructor(
    public readonly kind: "network" | "http",
    public readonly status: number | null,
  ) {
    super(kind === "network" ? "network error" : `http ${status}`);
    this.name = "SyncError";
  }

  /** Network failures and 5xx are worth retrying; 4xx means the write will never apply. */
  get retryable(): boolean {
    return this.kind === "network" || (this.status !== null && this.status >= 500);
  }
}

export interface RequestOptions {
  /** Lets the request outlive the page (pagehide / hidden tab). */
  keepalive?: boolean;
}

export interface MarkPayload {
  chunk_id: number;
  read_at: string;
}

export interface SessionPayload {
  client_id: string;
  article_id: number;
  started_at: string;
  active_seconds: number;
}

export interface SyncApi {
  fetchArticles(): Promise<ArticleSummary[]>;
  fetchArticle(id: number): Promise<ArticleDetail>;
  postMarks(articleId: number, marks: MarkPayload[], opts?: RequestOptions): Promise<void>;
  putSession(session: SessionPayload, opts?: RequestOptions): Promise<void>;
}

export class HttpSyncApi implements SyncApi {
  constructor(private readonly fetchFn: typeof fetch = (...args) => fetch(...args)) {}

  fetchArticles(): Promise<ArticleSummary[]> {
    return this.json<ArticleSummary[]>("/api/articles");
  }

  fetchArticle(id: number): Promise<ArticleDetail> {
    return this.json<ArticleDetail>(`/api/articles/${id}`);
  }

  async postMarks(articleId: number, marks: MarkPayload[], opts: RequestOptions = {}): Promise<void> {
    await this.send(`/api/articles/${articleId}/progress`, "POST", { marks }, opts);
  }

  async putSession(session: SessionPayload, opts: RequestOptions = {}): Promise<void> {
    const { client_id, ...body } = session;
    await this.send(`/api/sessions/${client_id}`, "PUT", body, opts);
  }

  private async json<T>(url: string): Promise<T> {
    const response = await this.request(url, {});
    return (await response.json()) as T;
  }

  private async send(
    url: string,
    method: "POST" | "PUT",
    body: unknown,
    opts: RequestOptions,
  ): Promise<void> {
    await this.request(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: opts.keepalive,
    });
  }

  private async request(url: string, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchFn(url, init);
    } catch {
      throw new SyncError("network", null);
    }
    if (!response.ok) throw new SyncError("http", response.status);
    return response;
  }
}
