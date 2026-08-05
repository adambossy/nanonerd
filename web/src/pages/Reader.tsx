import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getArticle } from "../api";
import { useReadTracking } from "../reader/useReadTracking";
import type { ArticleDetail } from "../types";

export default function Reader() {
  const { id } = useParams();
  const articleId = Number(id);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const readIds = useReadTracking(articleId, article);

  useEffect(() => {
    getArticle(articleId)
      .then(setArticle)
      .catch(() => undefined);
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

  if (!article) {
    return <main className="reader">loading…</main>;
  }

  return (
    <>
      <div className="reader-progress">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <main className="reader">
        <nav className="top-nav" style={{ padding: 0 }}>
          <Link className="brand" to="/">nano::nerd</Link>
          <span>{Math.round(percent)}%</span>
        </nav>
        <h1 className="article-title">{article.title}</h1>
        <p className="byline">
          {article.site_name && `${article.site_name} · `}
          <a href={article.url}>original</a>
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
