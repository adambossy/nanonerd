import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { requestSnapshot } from "../api";
import { loadArticle, offline } from "../offline";
import { fidelityNotice } from "../reader/fidelity";
import { loadReaderMode, saveReaderMode, type ReaderMode } from "../reader/readerMode";
import { SnapshotView } from "../reader/SnapshotView";
import { useReadTracking, type ChunkRoot } from "../reader/useReadTracking";
import { useReadingSession, type SessionTick } from "../reader/useReadingSession";
import type { ArticleDetail, SnapshotState } from "../types";

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
const RESUME_FAB_FADE_DISTANCE = 120; // px of scroll over which the resume fab fades out
const SNAPSHOT_POLL_MS = 3000;

type LoadState = "loading" | "ready" | "unavailable" | "invalid";

function SnapshotNotice({
  state,
  loadError,
  onCapture,
}: {
  state: SnapshotState;
  loadError: string | null;
  onCapture: () => void;
}) {
  if (loadError) {
    return (
      <p className="snapshot-notice">
        Snapshot failed to load ({loadError}); showing reader view.{" "}
        <button className="retry" onClick={onCapture}>
          capture again
        </button>
      </p>
    );
  }
  if (state.status === "pending") {
    return (
      <p className="snapshot-notice">capturing snapshot… showing reader view.</p>
    );
  }
  return (
    <p className="snapshot-notice">
      {state.status === "failed"
        ? `Snapshot unavailable (${state.error ?? "capture failed"}); `
        : "No snapshot yet; "}
      showing reader view.{" "}
      <button className="retry" onClick={onCapture}>
        capture snapshot
      </button>
    </p>
  );
}

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
  const [mode, setMode] = useState<ReaderMode>(() => loadReaderMode(articleId));
  const [shadowRoot, setShadowRoot] = useState<ShadowRoot | null>(null);
  const [snapshotLoadError, setSnapshotLoadError] = useState<string | null>(null);
  const scrolledForRef = useRef<number | null>(null);

  const snapshot = article?.snapshot ?? null;
  const faithful =
    mode === "faithful" && !!snapshot?.available && snapshotLoadError === null;
  // Read tracking watches whichever DOM holds the chunks; persistence below
  // is the same offline path in both modes.
  const chunkRoot: ChunkRoot = faithful ? shadowRoot : document;

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

  const readIds = useReadTracking(article, chunkRoot, onRead);
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

  // While a capture is running, sync until it settles: a finished capture
  // bumps extracted_at, so the sync refetches the rebuilt chunks.
  useEffect(() => {
    if (snapshot?.status !== "pending") return;
    const timer = setInterval(() => {
      void offline.scheduler
        .syncNow()
        .then(() => loadArticle(offline.store, articleId))
        .then((next) => {
          if (next && next.snapshot.status !== "pending") setArticle(next);
        })
        .catch(() => undefined);
    }, SNAPSHOT_POLL_MS);
    return () => clearInterval(timer);
  }, [articleId, snapshot?.status]);

  // Open at the requested chunk, otherwise at the earliest unread chunk
  // (once per article, once the chunk elements exist in `chunkRoot`).
  useEffect(() => {
    if (!article || !chunkRoot || scrolledForRef.current === articleId) return;
    scrolledForRef.current = articleId;
    if (targetChunk) {
      chunkRoot.querySelector(`[data-chunk-id="${targetChunk}"]`)?.scrollIntoView();
      return;
    }
    const firstUnread = article.chunks.find((c) => !c.read);
    if (firstUnread && firstUnread.position > 0) {
      chunkRoot
        .querySelector(`[data-chunk-id="${firstUnread.id}"]`)
        ?.scrollIntoView();
    }
    if (resumed) {
      requestAnimationFrame(() => {
        resumeBaselineRef.current = window.scrollY;
      });
    }
  }, [article, articleId, chunkRoot, targetChunk, resumed]);

  const percent = useMemo(() => {
    if (!article) return 0;
    const total = article.chunks.reduce((sum, c) => sum + c.word_count, 0);
    if (total === 0) return 0;
    const read = article.chunks
      .filter((c) => readIds.has(c.id))
      .reduce((sum, c) => sum + c.word_count, 0);
    return (100 * read) / total;
  }, [article, readIds]);

  const switchMode = (next: ReaderMode) => {
    setMode(next);
    saveReaderMode(articleId, next);
    setSnapshotLoadError(null);
  };

  const captureSnapshot = () => {
    requestSnapshot(articleId)
      .then((next) => {
        setArticle((prev) => (prev ? { ...prev, snapshot: next } : prev));
        offline.scheduler.requestSync();
      })
      .catch(() => setSnapshotLoadError("could not start capture"));
  };

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

  const notice = noticeDismissed || faithful ? null : fidelityNotice(article);
  const snapshotNotice =
    mode === "faithful" && !faithful ? (
      <SnapshotNotice
        state={article.snapshot}
        loadError={snapshotLoadError}
        onCapture={captureSnapshot}
      />
    ) : null;

  return (
    <>
      <div className="reader-progress">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <main
        className={faithful ? "reader reader--faithful" : "reader"}
        onClick={jumpToFragment}
      >
        <nav className="top-nav" style={{ padding: 0 }}>
          <Link className="brand" to="/library">nano::nerd</Link>
          <span className="mode-toggle" role="group" aria-label="view mode">
            <button
              className={mode === "reader" ? "active" : undefined}
              onClick={() => switchMode("reader")}
            >
              reader
            </button>
            <button
              className={mode === "faithful" ? "active" : undefined}
              onClick={() => switchMode("faithful")}
            >
              faithful
            </button>
          </span>
          <span>{Math.round(percent)}%</span>
        </nav>
        {snapshotNotice}
        {!faithful && (
          <>
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
          </>
        )}
      </main>
      {faithful && (
        <SnapshotView
          articleId={articleId}
          readIds={readIds}
          onMount={setShadowRoot}
          onError={setSnapshotLoadError}
        />
      )}
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
