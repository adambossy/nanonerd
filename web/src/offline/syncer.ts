import { imageUrlsIn } from "./images";
import { noImageWarmer, type ImageWarmer } from "./imageWarmer";
import { percentFor } from "./reading";
import type { LocalStore } from "./store";
import { SyncError, type RequestOptions, type SyncApi } from "./transport";
import type { LocalSession, ReadMark, StoredArticle } from "./types";

/**
 * Moves state between the LocalStore and the server. Pure orchestration:
 * no timers, no DOM, no knowledge of *when* to run (see SyncScheduler).
 *
 * Every push is idempotent on the server, so a retry after a lost response
 * is harmless. Retryable errors (network, 5xx) abort the current step and
 * are surfaced; terminal errors (4xx) drop the offending local entry.
 */

export interface SyncOptions {
  /** Let requests outlive the page (pagehide / hidden tab). */
  keepalive?: boolean;
  /** Only push the outbox; skip pulling the list and prefetching bodies. */
  pushOnly?: boolean;
}

export interface SyncResult {
  pushedMarks: number;
  pushedSessions: number;
  refreshed: boolean;
  prefetched: number;
  warmedImages: number;
  error: SyncError | null;
}

export interface SyncerOptions {
  prefetchConcurrency?: number;
  /** Loads article images into the offline cache; omitted where there is no DOM. */
  images?: ImageWarmer;
  /** Cap on images loaded per sync, so one image-heavy article cannot stall the rest. */
  warmBatch?: number;
}

// Server percent is rounded to one decimal; anything beyond that is real divergence.
const PERCENT_EPSILON = 0.05;

export class Syncer {
  private readonly prefetchConcurrency: number;
  private readonly images: ImageWarmer;
  private readonly warmBatch: number;
  /** Articles whose cached body has already been matched against the image store this session. */
  private readonly imagesRegistered = new Set<number>();

  constructor(
    private readonly store: LocalStore,
    private readonly api: SyncApi,
    opts: SyncerOptions = {},
  ) {
    this.prefetchConcurrency = opts.prefetchConcurrency ?? 3;
    this.images = opts.images ?? noImageWarmer;
    this.warmBatch = opts.warmBatch ?? 24;
  }

  /** Send every unsynced mark, one request per article. Returns the number of marks acknowledged. */
  async pushMarks(opts: SyncOptions = {}): Promise<number> {
    const byArticle = groupByArticle(await this.store.unsyncedMarks());
    const request = requestOptions(opts);
    let pushed = 0;
    for (const [articleId, marks] of byArticle) {
      const payload = marks.map((m) => ({ chunk_id: m.chunk_id, read_at: m.read_at }));
      const outcome = await this.attempt(() => this.api.postMarks(articleId, payload, request));
      if (outcome === "ok") {
        await this.store.markMarksSynced(marks.map((m) => m.chunk_id));
        pushed += marks.length;
      } else {
        // The article is gone or the request is malformed; these marks can never apply.
        await this.store.deleteMarksForArticle(articleId);
      }
    }
    return pushed;
  }

  /** Upsert every session whose clock moved since the last acknowledgement. */
  async pushSessions(opts: SyncOptions = {}): Promise<number> {
    const request = requestOptions(opts);
    let pushed = 0;
    for (const s of await this.store.unsyncedSessions()) {
      const outcome = await this.attempt(() => this.api.putSession(toPayload(s), request));
      // Terminal errors also mark the session synced so it stops blocking the outbox.
      await this.store.markSessionSynced(s.client_id, s.active_seconds);
      if (outcome === "ok") pushed += 1;
    }
    return pushed;
  }

  /** Pull the server's list; it is authoritative for membership and metadata. */
  async refreshArticles(): Promise<void> {
    await this.store.replaceArticles(await this.api.fetchArticles());
  }

  /** Download bodies that are missing, re-extracted, or behind the server's read state. */
  async prefetchBodies(): Promise<number> {
    let fetched = 0;
    await this.inParallel(await this.bodiesNeedingFetch(), async (article) => {
      if (await this.fetchBody(article)) fetched += 1;
    });
    return fetched;
  }

  /**
   * Load article images into the offline cache and remember their natural
   * sizes. Runs only after a successful pull, so a dead connection never
   * spends attempts, and each image is loaded once: after that the service
   * worker answers from cache and the reader stops depending on the network
   * to keep an image on screen.
   */
  async warmImages(): Promise<number> {
    await this.registerImagesForCachedBodies();
    const pending = await this.store.unmeasuredImages();
    const urls = [...new Set(pending.map((i) => i.url))].slice(0, this.warmBatch);
    let warmed = 0;
    await this.inParallel(urls, async (url) => {
      const size = await this.images.warm(url);
      if (!size) return;
      await this.store.setImageSize(url, size.width, size.height);
      warmed += 1;
    });
    return warmed;
  }

  /** Push, then pull, then prefetch bodies and their images. Stops at the first retryable error and reports it. */
  async syncAll(opts: SyncOptions = {}): Promise<SyncResult> {
    const result: SyncResult = {
      pushedMarks: 0,
      pushedSessions: 0,
      refreshed: false,
      prefetched: 0,
      warmedImages: 0,
      error: null,
    };
    try {
      result.pushedMarks = await this.pushMarks(opts);
      result.pushedSessions = await this.pushSessions(opts);
      if (opts.pushOnly) return result;
      await this.refreshArticles();
      result.refreshed = true;
      result.prefetched = await this.prefetchBodies();
      result.warmedImages = await this.warmImages();
    } catch (error) {
      if (!(error instanceof SyncError)) throw error;
      result.error = error;
    }
    return result;
  }

  async pendingCount(): Promise<number> {
    const [marks, sessions] = await Promise.all([
      this.store.unsyncedMarks(),
      this.store.unsyncedSessions(),
    ]);
    return marks.length + sessions.length;
  }

  private async bodiesNeedingFetch(): Promise<StoredArticle[]> {
    const [articles, versions] = await Promise.all([
      this.store.listArticles(),
      this.store.listBodyVersions(),
    ]);
    const versionById = new Map(versions.map((v) => [v.article_id, v.extracted_at]));
    const needed: StoredArticle[] = [];
    for (const article of articles) {
      if (article.status !== "ready") continue;
      if (!versionById.has(article.id)) {
        needed.push(article);
      } else if (versionById.get(article.id) !== article.extracted_at) {
        // Content was re-extracted: chunk ids changed, so local marks are meaningless.
        await this.store.deleteMarksForArticle(article.id);
        needed.push(article);
      } else if (await this.serverIsAhead(article)) {
        needed.push(article);
      }
    }
    return needed;
  }

  /**
   * Give bodies that were cached before this device tracked images their image
   * rows. Each article is inspected at most once per page load: a body already
   * has rows, or is read once to create them.
   */
  private async registerImagesForCachedBodies(): Promise<void> {
    for (const article of await this.store.listArticles()) {
      if (this.imagesRegistered.has(article.id)) continue;
      this.imagesRegistered.add(article.id);
      if ((await this.store.imagesForArticle(article.id)).length > 0) continue;
      const body = await this.store.getBody(article.id);
      if (body) await this.store.putImagesForArticle(article.id, imageUrlsIn(body.chunks));
    }
  }

  private async serverIsAhead(article: StoredArticle): Promise<boolean> {
    const [body, marks] = await Promise.all([
      this.store.getBody(article.id),
      this.store.marksForArticle(article.id),
    ]);
    return article.percent_read > percentFor(article, body, marks) + PERCENT_EPSILON;
  }

  /** Returns true when a body was stored; false when the article is terminally unavailable. */
  private async fetchBody(article: StoredArticle): Promise<boolean> {
    let detail;
    try {
      detail = await this.api.fetchArticle(article.id);
    } catch (error) {
      if (error instanceof SyncError && !error.retryable) return false;
      throw error;
    }
    await this.store.putBody({
      article_id: article.id,
      extracted_at: detail.extracted_at,
      chunks: detail.chunks,
    });
    await this.store.putImagesForArticle(article.id, imageUrlsIn(detail.chunks));
    this.imagesRegistered.add(article.id);
    return true;
  }

  /** Run `work` over `items` with at most `prefetchConcurrency` in flight. */
  private async inParallel<T>(
    items: T[],
    work: (item: T) => Promise<void>,
  ): Promise<void> {
    const queue = [...items];
    const worker = async (): Promise<void> => {
      for (let next = queue.shift(); next !== undefined; next = queue.shift()) {
        await work(next);
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(this.prefetchConcurrency, queue.length) }, worker),
    );
  }

  /** Run a push; "ok" on success, "terminal" on a non-retryable SyncError; rethrows otherwise. */
  private async attempt(run: () => Promise<void>): Promise<"ok" | "terminal"> {
    try {
      await run();
      return "ok";
    } catch (error) {
      if (error instanceof SyncError && !error.retryable) return "terminal";
      throw error;
    }
  }
}

function requestOptions(opts: SyncOptions): RequestOptions {
  return opts.keepalive ? { keepalive: true } : {};
}

function groupByArticle(marks: ReadMark[]): Map<number, ReadMark[]> {
  const grouped = new Map<number, ReadMark[]>();
  for (const m of marks) {
    const list = grouped.get(m.article_id);
    if (list) list.push(m);
    else grouped.set(m.article_id, [m]);
  }
  return grouped;
}

function toPayload(s: LocalSession) {
  return {
    client_id: s.client_id,
    article_id: s.article_id,
    started_at: s.started_at,
    active_seconds: s.active_seconds,
  };
}
