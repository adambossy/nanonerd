import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHistory } from "../api";
import type { HistoryEntry } from "../types";

function formatReadAt(readAt: string): string {
  return new Date(readAt).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function History() {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getHistory()
      .then(setEntries)
      .catch(() => setFailed(true));
  }, []);

  return (
    <>
      <nav className="top-nav">
        <Link className="brand" to="/library">nano::nerd</Link>
        <Link to="/library">library</Link>
      </nav>
      <main className="history">
        {failed && <p className="empty">Couldn't load history.</p>}
        {!failed && !entries && <p className="empty">loading…</p>}
        {entries?.length === 0 && <p className="empty">Nothing read yet.</p>}
        {entries?.map((entry) => (
          <Link
            key={entry.chunk_id}
            className="history-row"
            to={`/read/${entry.article_id}?chunk=${entry.chunk_id}`}
          >
            <div className="history-meta">
              <span className="history-article">{entry.article_title}</span>
              <span className="history-time">{formatReadAt(entry.read_at)}</span>
            </div>
            <p className="history-snippet">{entry.snippet}</p>
          </Link>
        ))}
      </main>
    </>
  );
}
