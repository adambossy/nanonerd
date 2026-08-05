import { useEffect, useRef, useState } from "react";
import { beaconProgress, markProgress } from "../api";
import type { ArticleDetail } from "../types";

const WORDS_PER_SECOND_CAP = 30; // faster than ~1800 wpm doesn't count as reading
const FLUSH_INTERVAL_MS = 3000;

export function useReadTracking(
  articleId: number,
  article: ArticleDetail | null,
): Set<number> {
  const [readIds, setReadIds] = useState<Set<number>>(new Set());
  const pendingRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!article) return;

    const alreadyRead = new Set(
      article.chunks.filter((c) => c.read).map((c) => c.id),
    );
    setReadIds(new Set(alreadyRead));
    const wordCounts = new Map(article.chunks.map((c) => [c.id, c.word_count]));
    const firstVisibleAt = new Map<number, number>();
    const pending = pendingRef.current;
    pending.clear();

    const markRead = (chunkId: number) => {
      if (alreadyRead.has(chunkId)) return;
      alreadyRead.add(chunkId);
      pending.add(chunkId);
      setReadIds((prev) => new Set(prev).add(chunkId));
    };

    const dwellSatisfied = (chunkId: number) => {
      const firstSeen = firstVisibleAt.get(chunkId);
      const minDwellMs =
        ((wordCounts.get(chunkId) ?? 0) / WORDS_PER_SECOND_CAP) * 1000;
      return (
        firstSeen !== undefined && performance.now() - firstSeen >= minDwellMs
      );
    };

    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        const chunkId = Number((entry.target as HTMLElement).dataset.chunkId);
        if (Number.isNaN(chunkId)) continue;
        if (entry.isIntersecting) {
          // Condition 3: only start the dwell clock while the tab is visible.
          if (
            document.visibilityState === "visible" &&
            !firstVisibleAt.has(chunkId)
          ) {
            firstVisibleAt.set(chunkId, performance.now());
          }
        } else if (entry.boundingClientRect.bottom <= 0) {
          // Condition 1: chunk has fully scrolled past the top of the viewport.
          if (dwellSatisfied(chunkId)) {
            markRead(chunkId);
          }
        }
      }
    });
    document
      .querySelectorAll("[data-chunk-id]")
      .forEach((el) => observer.observe(el));

    // The final chunk of an article can never scroll past the viewport top
    // (its bottom stays in view at max scroll), so it can never satisfy the
    // exit-past-top rule above. When the user has scrolled to the very
    // bottom of the document, mark any visible chunk read once its dwell
    // time has elapsed.
    const tryMarkAtBottom = () => {
      const atBottom =
        window.innerHeight + window.scrollY >=
        document.documentElement.scrollHeight - 4;
      if (!atBottom) return;
      document.querySelectorAll("[data-chunk-id]").forEach((el) => {
        const chunkId = Number((el as HTMLElement).dataset.chunkId);
        if (Number.isNaN(chunkId)) return;
        if (el.getBoundingClientRect().top >= window.innerHeight) return;
        if (dwellSatisfied(chunkId)) {
          markRead(chunkId);
        }
      });
    };
    window.addEventListener("scroll", tryMarkAtBottom, { passive: true });

    const requeue = (ids: number[]) => {
      ids.forEach((id) => pending.add(id));
    };
    const flush = () => {
      tryMarkAtBottom();
      if (pending.size === 0) return;
      const ids = [...pending];
      pending.clear();
      markProgress(articleId, ids, requeue);
    };
    const flushWithBeacon = () => {
      if (pending.size === 0) return;
      const ids = [...pending];
      pending.clear();
      beaconProgress(articleId, ids);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushWithBeacon();
    };

    const timer = setInterval(flush, FLUSH_INTERVAL_MS);
    window.addEventListener("pagehide", flushWithBeacon);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      observer.disconnect();
      clearInterval(timer);
      window.removeEventListener("scroll", tryMarkAtBottom);
      window.removeEventListener("pagehide", flushWithBeacon);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      flush();
    };
  }, [article, articleId]);

  return readIds;
}
