import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { loadArticle, offline } from "../offline";
import { fidelityNotice } from "../reader/fidelity";
import { useReadTracking } from "../reader/useReadTracking";
import { useReadingSession, type SessionTick } from "../reader/useReadingSession";
import type { ArticleDetail } from "../types";

const RESUME_FAB_FADE_DISTANCE = 120; // px of scroll over which the resume fab fades out

type LoadState = "loading" | "ready" | "unavailable" | "invalid";

export default function Reader() {
  const { id } = useParams();
  const location = useLocation();
  const resumed = Boolean((location.state as { resumed?: boolean } | null)?.resumed);
  const [resumeFabOpacity, setResumeFabOpacity] = useState(1);
  const [searchParams] = useSearchParams();
  const targetChunk = searchParams.get("chunk");
  const articleId = Number(id);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [noticeDismissed, setNoticeDismissed] = useState(false);

  // Persist at event time so nothing is lost if the tab closes; sync soon after.
  const onRead = useCallback(
    (chunkIds: number[]) => {
      const read_at = new Date().toISOString();
      void offline.store
        .addMarks(
          chunkIds.map((chunk_id) => ({
            chunk_id,
            article_id: articleId,
            read_at,
            synced: false,
          })),
        )
        .then(() => offline.scheduler.requestSync());
    },
    [articleId],
  );
  const onTick = useCallback((tick: SessionTick) => {
    void offline.store
      .upsertSession({ ...tick, synced_seconds: 0 })
      .then(() => offline.scheduler.requestSync());
  }, []);

  const readIds = useReadTracking(article, onRead);
  useReadingSession(articleId, article !== null, onTick);
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
      setState("invalid");
      return;
    }
    let cancelled = false;
    const load = async () => {
      let detail = await loadArticle(offline.store, articleId);
      if (!detail) {
        // Not cached yet (first open, or a new article): try one sync, then look again.
        await offline.scheduler.syncNow();
        detail = await loadArticle(offline.store, articleId);
      }
      if (cancelled) return;
      if (detail) {
        setArticle(detail);
        setState("ready");
      } else {
        setState("unavailable");
      }
    };
    void load().catch(() => {
      if (!cancelled) setState("unavailable");
    });
    return () => {
      cancelled = true;
    };
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

  if (state === "invalid" || state === "unavailable") {
    return (
      <main className="reader">
        <p>
          {state === "invalid"
            ? "Couldn't load this article."
            : "This article isn't available offline yet. It downloads the next time you're connected."}
        </p>
        <Link to="/library">back</Link>
      </main>
    );
  }

  if (!article) {
    return <main className="reader">loading…</main>;
  }

  const notice = noticeDismissed ? null : fidelityNotice(article);

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
        {notice && (
          <p className="fidelity-notice">
            <span>{notice}</span>
            <button
              className="fidelity-dismiss"
              aria-label="dismiss"
              onClick={() => setNoticeDismissed(true)}
            >
              ×
            </button>
          </p>
        )}
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
