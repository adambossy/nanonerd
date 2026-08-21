import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { retryArticle } from "../api";
import { loadArticleList, offline } from "../offline";
import { useSyncStatus } from "../offline/useSyncStatus";
import type { ArticleSummary } from "../types";

function readingMinutes(wordCount: number): number {
  return Math.max(1, Math.round(wordCount / 230));
}

function SyncChip() {
  const status = useSyncStatus();
  if (!status.online) {
    return (
      <span className="sync-chip offline" title={status.lastError ?? undefined}>
        offline{status.unsynced > 0 ? ` · ${status.unsynced} unsynced` : ""}
      </span>
    );
  }
  if (status.unsynced > 0) {
    return <span className="sync-chip">{status.unsynced} unsynced</span>;
  }
  return null;
}

function Card({ article, onRetry }: { article: ArticleSummary; onRetry: () => void }) {
  const body = (
    <>
      <h2>{article.title}</h2>
      <div className="meta">
        {article.site_name && <span>{article.site_name}</span>}
        {article.status === "ready" && (
          <span>
            {article.word_count.toLocaleString()} words ·{" "}
            {readingMinutes(article.word_count)} min ·{" "}
            {Math.round(article.percent_read)}% read
          </span>
        )}
        {article.status === "pending" && <span>processing…</span>}
      </div>
      {article.categories.length > 0 && (
        <div className="chips">
          {article.categories.map((name) => (
            <span key={name} className="chip">{name}</span>
          ))}
        </div>
      )}
      {article.status === "failed" && (
        <>
          <p className="error-text">failed: {article.error ?? "unknown error"}</p>
          <button
            className="retry"
            onClick={(event) => {
              event.preventDefault();
              onRetry();
            }}
          >
            retry
          </button>
        </>
      )}
      {article.status === "ready" && (
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${article.percent_read}%` }}
          />
        </div>
      )}
    </>
  );
  if (article.status === "ready") {
    return (
      <Link className="card" to={`/read/${article.id}`}>
        {body}
      </Link>
    );
  }
  return <div className="card">{body}</div>;
}

export default function Home() {
  const [articles, setArticles] = useState<ArticleSummary[] | null>(null);
  const status = useSyncStatus();

  const reload = useCallback(() => {
    loadArticleList(offline.store)
      .then(setArticles)
      .catch(() => undefined);
  }, []);

  // Local state first; re-read whenever a sync finishes or status changes.
  useEffect(() => {
    reload();
  }, [reload, status]);

  // Pending articles are being processed server-side; keep pulling while online.
  useEffect(() => {
    if (!status.online || !articles?.some((a) => a.status === "pending")) return;
    const timer = setInterval(() => offline.scheduler.requestSync(), 3000);
    return () => clearInterval(timer);
  }, [articles, status.online]);

  return (
    <>
      <nav className="top-nav">
        <Link className="brand" to="/library">nano::nerd</Link>
        <span className="nav-links">
          <SyncChip />
          <Link to="/history">history</Link>
          <Link to="/stats">stats</Link>
          <Link to="/setup">setup</Link>
        </span>
      </nav>
      <main className="home">
        {articles?.length === 0 && (
          <p className="empty">
            Nothing saved yet. Grab the bookmarklet on the setup page.
          </p>
        )}
        {articles?.map((article) => (
          <Card
            key={article.id}
            article={article}
            onRetry={() => {
              void retryArticle(article.id)
                .catch(() => undefined)
                .then(() => offline.scheduler.requestSync());
            }}
          />
        ))}
      </main>
    </>
  );
}
