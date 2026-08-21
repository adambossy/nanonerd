import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { archiveArticle, deleteArticle, listArticles, retryArticle } from "../api";
import SwipeRow from "../SwipeRow";
import type { ArticleSummary } from "../types";

function readingMinutes(wordCount: number): number {
  return Math.max(1, Math.round(wordCount / 230));
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

  const refresh = useCallback(
    () =>
      listArticles()
        .then(setArticles)
        .catch(() => undefined),
    [],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!articles?.some((a) => a.status === "pending")) return;
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [articles, refresh]);

  return (
    <>
      <nav className="top-nav">
        <Link className="brand" to="/">nano::nerd</Link>
        <span className="nav-links">
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
            const archive = () =>
              archiveArticle(article.id)
                .catch(() => undefined)
                .then(() => refresh());
            const remove = () =>
              deleteArticle(article.id)
                .catch(() => undefined)
                .then(() => refresh());
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
                      .then(() => refresh());
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
