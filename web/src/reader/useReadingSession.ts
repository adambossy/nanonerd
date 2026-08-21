import { useEffect } from "react";

const IDLE_MS = 30_000; // no interaction for this long -> clock stops
const TICK_MS = 5_000; // accumulate + report cadence

export interface SessionTick {
  client_id: string;
  article_id: number;
  started_at: string;
  active_seconds: number;
}

/**
 * Measures active reading time for one open of an article and reports it
 * through `onTick` whenever the whole-second count grows. The session id is
 * minted on this device so the report is idempotent wherever it lands;
 * persistence and syncing are the caller's concern.
 */
export function useReadingSession(
  articleId: number,
  ready: boolean,
  onTick: (tick: SessionTick) => void,
): void {
  useEffect(() => {
    if (!ready || !Number.isFinite(articleId)) return;

    // Minted lazily so a session that never accrues time is never reported
    // (and StrictMode's double mount can't leave a stray zero-second row).
    let identity: { client_id: string; started_at: string } | null = null;
    let activeMs = 0;
    let reportedSeconds = 0;
    let lastInteraction = performance.now();
    let lastTick = performance.now();

    const interact = () => {
      lastInteraction = performance.now();
    };

    const accumulate = () => {
      const now = performance.now();
      const active =
        document.visibilityState === "visible" &&
        now - lastInteraction <= IDLE_MS;
      if (active) activeMs += now - lastTick;
      lastTick = now;
    };

    const report = () => {
      const seconds = Math.floor(activeMs / 1000);
      if (seconds <= reportedSeconds) return;
      if (identity === null) {
        identity = {
          client_id: crypto.randomUUID(),
          started_at: new Date().toISOString(),
        };
      }
      reportedSeconds = seconds;
      onTick({ ...identity, article_id: articleId, active_seconds: seconds });
    };

    const onVisibilityChange = () => {
      accumulate();
      if (document.visibilityState === "hidden") report();
    };
    const onPageHide = () => {
      accumulate();
      report();
    };

    const timer = setInterval(() => {
      accumulate();
      report();
    }, TICK_MS);
    window.addEventListener("scroll", interact, { passive: true });
    window.addEventListener("mousemove", interact, { passive: true });
    window.addEventListener("keydown", interact, { passive: true });
    window.addEventListener("touchstart", interact, { passive: true });
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      clearInterval(timer);
      window.removeEventListener("scroll", interact);
      window.removeEventListener("mousemove", interact);
      window.removeEventListener("keydown", interact);
      window.removeEventListener("touchstart", interact);
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      accumulate();
      report();
    };
  }, [articleId, ready, onTick]);
}
