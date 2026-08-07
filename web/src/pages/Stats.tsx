import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getStats } from "../api";
import type { StatsResponse } from "../types";

function formatDuration(totalSeconds: number): string {
  const totalMinutes = Math.round(totalSeconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m`;
  return `${totalSeconds}s`;
}

function TopicBars({ topics }: { topics: StatsResponse["topics"] }) {
  const shown = topics.filter((t) => t.active_seconds > 0).slice(0, 8);
  if (shown.length === 0) {
    return <p className="empty">No reading time recorded yet.</p>;
  }
  const max = Math.max(...shown.map((t) => t.active_seconds));
  return (
    <div className="bars">
      {shown.map((t) => (
        <div key={t.name} className="bar-row">
          <span className="bar-label">{t.name}</span>
          <svg viewBox="0 0 100 8" preserveAspectRatio="none" className="bar-svg">
            <rect
              x="0"
              y="1"
              width={(100 * t.active_seconds) / max}
              height="6"
              rx="2"
              className="bar-fill"
            />
          </svg>
          <span className="bar-value">{formatDuration(t.active_seconds)}</span>
        </div>
      ))}
    </div>
  );
}

function DailySparkline({ daily }: { daily: StatsResponse["daily"] }) {
  const max = Math.max(1, ...daily.map((d) => d.active_seconds));
  const points = daily
    .map(
      (d, i) =>
        `${(100 * i) / (daily.length - 1)},${30 - (28 * d.active_seconds) / max}`,
    )
    .join(" ");
  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" className="sparkline">
      <polyline points={points} fill="none" strokeWidth="1.5" className="spark-line" />
    </svg>
  );
}

export default function Stats() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch(() => setFailed(true));
  }, []);

  return (
    <>
      <nav className="top-nav">
        <Link className="brand" to="/">nano::nerd</Link>
        <Link to="/">home</Link>
      </nav>
      <main className="stats">
        {failed && <p className="empty">Couldn't load stats.</p>}
        {!failed && !stats && <p className="empty">loading…</p>}
        {stats && (
          <>
            <div className="tiles">
              <div className="tile">
                <strong>{formatDuration(stats.totals.active_seconds)}</strong>
                <span>reading time</span>
              </div>
              <div className="tile">
                <strong>{stats.totals.articles_saved}</strong>
                <span>saved</span>
              </div>
              <div className="tile">
                <strong>{stats.totals.articles_finished}</strong>
                <span>finished</span>
              </div>
              <div className="tile">
                <strong>{stats.totals.words_read.toLocaleString()}</strong>
                <span>words read</span>
              </div>
            </div>

            <h2>Time by topic</h2>
            <TopicBars topics={stats.topics} />
            <p className="hint">Articles can count in several topics.</p>

            <h2>Saved vs. read</h2>
            <table className="topic-table">
              <thead>
                <tr>
                  <th>topic</th>
                  <th>saved</th>
                  <th>read-through</th>
                  <th>time</th>
                </tr>
              </thead>
              <tbody>
                {stats.topics.map((t) => (
                  <tr key={t.name}>
                    <td>{t.name}</td>
                    <td>{t.saved}</td>
                    <td>{t.read_through}%</td>
                    <td>{formatDuration(t.active_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h2>Last 30 days</h2>
            <DailySparkline daily={stats.daily} />

            {stats.top_articles.length > 0 && (
              <>
                <h2>Most time spent</h2>
                <ol className="top-articles">
                  {stats.top_articles.map((a) => (
                    <li key={a.id}>
                      <Link to={`/read/${a.id}`}>{a.title}</Link>{" "}
                      <span className="meta-inline">
                        {formatDuration(a.active_seconds)} ·{" "}
                        {Math.round(a.percent_read)}%
                      </span>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}
