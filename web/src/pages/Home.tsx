import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { archiveArticle, deleteArticle, retryArticle } from "../api";
import { loadArticleList, offline } from "../offline";
import { useSyncStatus } from "../offline/useSyncStatus";
import { fidelityBadge } from "../reader/fidelity";
import SwipeRow from "../SwipeRow";
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

function ArchiveIcon({ size = 15 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="4" rx="1" />
      <path d="M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8" />
      <path d="M10 13h4" />
    </svg>
  );
}

function DeleteIcon({ size = 15 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 7h16" />
      <path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13" />
      <path d="M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  );
}

function Card({
  article,
  onRetry,
  onArchive,
  onDelete,
}: {
  article: ArticleSummary;
  onRetry: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const badge = fidelityBadge(article);
  const actions = (
    <div className="card-actions">
      <button
        type="button"
        className="icon-btn"
        title="archive"
        aria-label="archive article"
        onClick={(event) => {
          event.preventDefault();
          onArchive();
        }}
      >
        <ArchiveIcon />
      </button>
      <button
        type="button"
        className="icon-btn icon-btn-danger"
        title="delete"
        aria-label="delete article"
        onClick={(event) => {
          event.preventDefault();
          if (window.confirm(`Delete "${article.title}"? This can't be undone.`)) {
            onDelete();
          }
        }}
      >
        <DeleteIcon />
      </button>
    </div>
  );
  const body = (
    <>
      {actions}
      <h2>{article.title}</h2>
      <div className="meta">
        {article.site_name && <span>{article.site_name}</span>}
        {badge && (
          <span
            className="fidelity-badge"
            title={article.fidelity_reasons[0] ?? undefined}
          >
            {badge}
          </span>
        )}
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

  const reload = useCallback(
    () =>
      loadArticleList(offline.store)
        .then(setArticles)
        .catch(() => undefined),
    [],
  );

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
        <div className="article-list">
          {articles?.map((article) => {
            // The server list is authoritative for membership, so a syncNow pull
            // drops the archived/deleted article from the local store before the
            // reload that SwipeRow's spring-back waits on.
            const archive = () =>
              archiveArticle(article.id)
                .then(() => offline.scheduler.syncNow())
                .catch(() => undefined)
                .then(() => reload());
            const remove = () =>
              deleteArticle(article.id)
                .then(() => offline.scheduler.syncNow())
                .catch(() => undefined)
                .then(() => reload());
            return (
              <SwipeRow
                key={article.id}
                rightSwipeIcon={<ArchiveIcon size={22} />}
                leftSwipeIcon={<DeleteIcon size={22} />}
                onSwipeRight={archive}
                onSwipeLeft={remove}
              >
                <Card
                  article={article}
                  onRetry={() => {
                    void retryArticle(article.id)
                      .catch(() => undefined)
                      .then(() => offline.scheduler.requestSync());
                  }}
                  onArchive={archive}
                  onDelete={remove}
                />
              </SwipeRow>
            );
          })}
        </div>
      </main>
    </>
  );
}
