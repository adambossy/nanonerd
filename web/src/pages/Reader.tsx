import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { getArticle } from "../api";
import { useReadTracking } from "../reader/useReadTracking";
import { useReadingSession } from "../reader/useReadingSession";
import type { ArticleDetail } from "../types";

const RESUME_FAB_FADE_DISTANCE = 120; // px of scroll over which the resume fab fades out

export default function Reader() {
  const { id } = useParams();
  const location = useLocation();
  const resumed = Boolean((location.state as { resumed?: boolean } | null)?.resumed);
  const [resumeFabOpacity, setResumeFabOpacity] = useState(1);
  const [searchParams] = useSearchParams();
  const targetChunk = searchParams.get("chunk");
  const articleId = Number(id);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const readIds = useReadTracking(articleId, article);
  useReadingSession(articleId, article !== null);
  const resumeBaselineRef = useRef<number | null>(null);

  useEffect(() => {
    if (!resumed) return;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const baseline = resumeBaselineRef.current ?? window.scrollY;
        const scrolled = window.scrollY - baseline;
        setResumeFabOpacity(
          Math.min(1, Math.max(0, 1 - scrolled / RESUME_FAB_FADE_DISTANCE)),
        );
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [resumed]);

  useEffect(() => {
    if (!Number.isFinite(articleId)) {
      setFailed(true);
      return;
    }
    getArticle(articleId)
      .then(setArticle)
      .catch(() => setFailed(true));
  }, [articleId]);

  // Open at the requested chunk, otherwise at the earliest unread chunk.
  useEffect(() => {
    if (!article) return;
    if (targetChunk) {
      document.querySelector(`[data-chunk-id="${targetChunk}"]`)?.scrollIntoView();
      return;
    }
    const firstUnread = article.chunks.find((c) => !c.read);
    if (firstUnread && firstUnread.position > 0) {
      document
        .querySelector(`[data-chunk-id="${firstUnread.id}"]`)
        ?.scrollIntoView();
    }
    if (resumed) {
      requestAnimationFrame(() => {
        resumeBaselineRef.current = window.scrollY;
      });
    }
  }, [article, targetChunk, resumed]);

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
        <Link to="/library">back</Link>
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
      <main className="reader">
        <nav className="top-nav" style={{ padding: 0 }}>
          <Link className="brand" to="/library">nano::nerd</Link>
          <span>{Math.round(percent)}%</span>
        </nav>
        <h1 className="article-title">{article.title}</h1>
        <p className="byline">
          {[article.site_name, article.author]
            .filter(Boolean)
            .map((part) => `${part} · `)
            .join("")}
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
      {resumed && (
        <Link
          className="resume-fab"
          to="/library"
          style={{
            opacity: resumeFabOpacity,
            pointerEvents: resumeFabOpacity < 0.05 ? "none" : "auto",
          }}
        >
          article list
        </Link>
      )}
    </>
  );
}
