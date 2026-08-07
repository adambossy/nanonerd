import { useEffect } from "react";

const IDLE_MS = 30_000; // no interaction for this long -> clock stops
const TICK_MS = 5_000; // accumulate + sync cadence

export function useReadingSession(articleId: number, ready: boolean): void {
  useEffect(() => {
    if (!ready || !Number.isFinite(articleId)) return;

    let sessionId: number | null = null;
    let activeMs = 0;
    let syncedSeconds = 0;
    let lastInteraction = performance.now();
    let lastTick = performance.now();
    let cancelled = false;

    fetch(`/api/articles/${articleId}/sessions`, { method: "POST" })
      .then((r) => (r.ok ? (r.json() as Promise<{ id: number }>) : null))
      .then((data) => {
        if (!cancelled && data) sessionId = data.id;
      })
      .catch(() => undefined);

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

    const body = () =>
      JSON.stringify({ active_seconds: Math.floor(activeMs / 1000) });

    const sync = () => {
      const seconds = Math.floor(activeMs / 1000);
      if (sessionId === null || seconds <= syncedSeconds) return;
      syncedSeconds = seconds;
      fetch(`/api/sessions/${sessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body(),
      }).catch(() => {
        syncedSeconds = 0; // retry on a later tick
      });
    };

    const beaconSync = () => {
      accumulate();
      const seconds = Math.floor(activeMs / 1000);
      if (sessionId === null || seconds <= syncedSeconds) return;
      syncedSeconds = seconds;
      navigator.sendBeacon(
        `/api/sessions/${sessionId}`,
        new Blob([body()], { type: "application/json" }),
      );
    };

    const onVisibilityChange = () => {
      accumulate();
      if (document.visibilityState === "hidden") beaconSync();
    };

    const timer = setInterval(() => {
      accumulate();
      sync();
    }, TICK_MS);
    window.addEventListener("scroll", interact, { passive: true });
    window.addEventListener("mousemove", interact, { passive: true });
    window.addEventListener("keydown", interact, { passive: true });
    window.addEventListener("touchstart", interact, { passive: true });
    window.addEventListener("pagehide", beaconSync);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      cancelled = true;
      clearInterval(timer);
      window.removeEventListener("scroll", interact);
      window.removeEventListener("mousemove", interact);
      window.removeEventListener("keydown", interact);
      window.removeEventListener("touchstart", interact);
      window.removeEventListener("pagehide", beaconSync);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      beaconSync();
    };
  }, [articleId, ready]);
}
