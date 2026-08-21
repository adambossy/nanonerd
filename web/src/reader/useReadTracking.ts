import { useEffect, useState } from "react";
import type { ArticleDetail } from "../types";

const WORDS_PER_SECOND_CAP = 30; // faster than ~1800 wpm doesn't count as reading

/**
 * Decides when a chunk counts as read (scrolled past + dwell time + tab
 * visible) and reports newly read chunk ids through `onRead`. Persistence
 * and syncing are the caller's concern; this hook never touches the network.
 */
export function useReadTracking(
  article: ArticleDetail | null,
  onRead: (chunkIds: number[]) => void,
): Set<number> {
  const [readIds, setReadIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!article) return;

    const alreadyRead = new Set(
      article.chunks.filter((c) => c.read).map((c) => c.id),
    );
    setReadIds(new Set(alreadyRead));
    const wordCounts = new Map(article.chunks.map((c) => [c.id, c.word_count]));
    const firstVisibleAt = new Map<number, number>();

    const markRead = (chunkId: number) => {
      if (alreadyRead.has(chunkId)) return;
      alreadyRead.add(chunkId);
      setReadIds((prev) => new Set(prev).add(chunkId));
      onRead([chunkId]);
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
    // Dwell can elapse without any further scroll; re-check periodically.
    const timer = setInterval(tryMarkAtBottom, 3000);

    return () => {
      observer.disconnect();
      clearInterval(timer);
      window.removeEventListener("scroll", tryMarkAtBottom);
    };
  }, [article, onRead]);

  return readIds;
}
