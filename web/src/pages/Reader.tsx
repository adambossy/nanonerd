import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getArticle, requestSnapshot } from "../api";
import { SnapshotView } from "../reader/SnapshotView";
import { loadReaderMode, saveReaderMode, type ReaderMode } from "../reader/readerMode";
import { useReadTracking, type ChunkRoot } from "../reader/useReadTracking";
import { useReadingSession } from "../reader/useReadingSession";
import type { ArticleDetail, SnapshotState } from "../types";

const SNAPSHOT_POLL_MS = 3000;

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
  const articleId = Number(id);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [mode, setMode] = useState<ReaderMode>(() => loadReaderMode(articleId));
  const [shadowRoot, setShadowRoot] = useState<ShadowRoot | null>(null);
  const [snapshotLoadError, setSnapshotLoadError] = useState<string | null>(null);
  const scrolledForRef = useRef<number | null>(null);

  const snapshot = article?.snapshot ?? null;
  const faithful =
    mode === "faithful" && !!snapshot?.available && snapshotLoadError === null;
  const chunkRoot: ChunkRoot = faithful ? shadowRoot : document;
  const readIds = useReadTracking(articleId, article, chunkRoot);
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

  // While a capture is running, poll until it settles (chunks may change).
  useEffect(() => {
    if (snapshot?.status !== "pending") return;
    const timer = setInterval(() => {
      getArticle(articleId)
        .then((next) => {
          if (next.snapshot.status !== "pending") setArticle(next);
        })
        .catch(() => undefined);
    }, SNAPSHOT_POLL_MS);
    return () => clearInterval(timer);
  }, [articleId, snapshot?.status]);

  // Open at the earliest unread chunk (once per article, once blocks exist).
  useEffect(() => {
    if (!article || !chunkRoot || scrolledForRef.current === articleId) return;
    const firstUnread = article.chunks.find((c) => !c.read);
    if (!firstUnread) return;
    scrolledForRef.current = articleId;
    if (firstUnread.position === 0) return;
    chunkRoot
      .querySelector(`[data-chunk-id="${firstUnread.id}"]`)
      ?.scrollIntoView();
  }, [article, articleId, chunkRoot]);

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
      .then((state) =>
        setArticle((prev) => (prev ? { ...prev, snapshot: state } : prev)),
      )
      .catch(() => setSnapshotLoadError("could not start capture"));
  };

  const handleSnapshotMount = useCallback((root: ShadowRoot | null) => {
    setShadowRoot(root);
  }, []);
  const handleSnapshotError = useCallback((message: string) => {
    setSnapshotLoadError(message);
  }, []);

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

  const notice =
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
      <main className={faithful ? "reader reader--faithful" : "reader"}>
        <nav className="top-nav" style={{ padding: 0 }}>
          <Link className="brand" to="/">nano::nerd</Link>
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
        {notice}
        {!faithful && (
          <>
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
          </>
        )}
      </main>
      {faithful && (
        <SnapshotView
          articleId={articleId}
          readIds={readIds}
          onMount={handleSnapshotMount}
          onError={handleSnapshotError}
        />
      )}
    </>
  );
}
