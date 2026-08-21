import { useEffect, useMemo, useState } from "react";
import type { MouseEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { getArticle } from "../api";
import { useReadTracking } from "../reader/useReadTracking";
import { useReadingSession } from "../reader/useReadingSession";
import type { ArticleDetail } from "../types";

const SOURCE_LABELS: Record<string, string> = {
  archive_ph: "archive.ph copy",
  wayback: "Wayback Machine copy",
};

// Footnote refs and backlinks are plain `#nn-…` anchors inside chunk HTML;
// scroll to them smoothly instead of letting the router see a navigation.
function jumpToFragment(event: MouseEvent<HTMLElement>) {
  const anchor = (event.target as HTMLElement).closest("a[href^='#']");
  if (!(anchor instanceof HTMLAnchorElement)) return;
  const id = decodeURIComponent(anchor.getAttribute("href")!.slice(1));
  const target = document.getElementById(id);
  if (!target) return;
  event.preventDefault();
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function Reader() {
  const { id } = useParams();
  const articleId = Number(id);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const readIds = useReadTracking(articleId, article);
  useReadingSession(articleId, article !== null);

  useEffect(() => {
    if (!Number.isFinite(articleId)) {
      setFailed(true);
      return;
    }
    getArticle(articleId)
      .then(setArticle)
      .catch(() => setFailed(true));
  }, [articleId]);

  // Open at the earliest unread chunk.
  useEffect(() => {
    if (!article) return;
    const firstUnread = article.chunks.find((c) => !c.read);
    if (firstUnread && firstUnread.position > 0) {
      document
        .querySelector(`[data-chunk-id="${firstUnread.id}"]`)
        ?.scrollIntoView();
    }
  }, [article]);

  const percent = useMemo(() => {
    if (!article) return 0;
    const total = article.chunks.reduce((sum, c) => sum + c.word_count, 0);
    if (total === 0) return 0;
    const read = article.chunks
      .filter((c) => readIds.has(c.id))
      .reduce((sum, c) => sum + c.word_count, 0);
    return (100 * read) / total;
  }, [article, readIds]);

  if (failed) {
    return (
      <main className="reader">
        <p>Couldn't load this article.</p>
        <Link to="/">back</Link>
      </main>
    );
  }

  if (!article) {
    return <main className="reader">loading…</main>;
  }

  return (
    <>
      <div className="reader-progress">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <main className="reader" onClick={jumpToFragment}>
        <nav className="top-nav" style={{ padding: 0 }}>
          <Link className="brand" to="/">nano::nerd</Link>
          <span>{Math.round(percent)}%</span>
        </nav>
        <h1 className="article-title">{article.title}</h1>
        <p className="byline">
          {[article.site_name, article.author]
            .filter(Boolean)
            .map((part) => `${part} · `)
            .join("")}
          <a href={article.url}>original</a>
          {article.source_kind && SOURCE_LABELS[article.source_kind] && (
            <>
              {" · "}
              <a href={article.source_url ?? article.url} className="source-note">
                {SOURCE_LABELS[article.source_kind]}
              </a>
            </>
          )}
        </p>
        {article.chunks.map((chunk) => (
          <section
            key={chunk.id}
            data-chunk-id={chunk.id}
            className={readIds.has(chunk.id) ? "read" : undefined}
            dangerouslySetInnerHTML={{ __html: chunk.html }}
          />
        ))}
      </main>
    </>
  );
}
