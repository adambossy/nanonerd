/**
 * Jump to a chunk and hold it in place while the article settles.
 *
 * Resuming an article scrolls to the chunk the reader stopped at, but the page
 * is not finished growing at that moment: any image above the anchor that has
 * not been measured yet occupies no height until its bytes arrive, and each one
 * that lands shoves the anchor further down the page. Chrome's scroll anchoring
 * would absorb that; iOS Safari implements none, which is where this is read.
 *
 * So after the jump we watch the anchor and undo any drift, until the layout
 * goes quiet or the reader takes over by scrolling themselves.
 */

/** Input that means the reader is now driving; corrections stop immediately. */
const HANDOFF_EVENTS = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

export interface HoldOptions {
  /** Called with the new scroll position each time drift is corrected. */
  onAdjust?: (scrollY: number) => void;
  /** Release once this long passes with no correction. */
  quietMs?: number;
  /** Release no later than this, however busy the page stays. */
  maxMs?: number;
}

/**
 * Scroll `target` to the top of the viewport and keep it there. Returns a
 * function that releases the hold; it is safe to call more than once.
 */
export function scrollToAndHold(
  target: Element,
  { onAdjust, quietMs = 1_500, maxMs = 10_000 }: HoldOptions = {},
): () => void {
  // `scroll-behavior: smooth` is set globally for in-article links, but a
  // resume must not animate: the page would still be travelling while images
  // land. Suspend it for the hold rather than passing `behavior: "instant"`,
  // which throws on Safari before 15.4.
  const root = document.documentElement;
  const previousBehavior = root.style.scrollBehavior;
  root.style.scrollBehavior = "auto";
  target.scrollIntoView({ block: "start" });

  const anchorTop = target.getBoundingClientRect().top;
  const deadline = now() + maxMs;
  let quietUntil = now() + quietMs;
  let frame = 0;
  let released = false;

  const release = () => {
    if (released) return;
    released = true;
    root.style.scrollBehavior = previousBehavior;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    for (const event of HANDOFF_EVENTS) window.removeEventListener(event, release);
  };

  const step = () => {
    frame = 0;
    const time = now();
    if (time > deadline || time > quietUntil) return release();
    const drift = target.getBoundingClientRect().top - anchorTop;
    if (Math.abs(drift) >= 1) {
      const before = window.scrollY;
      window.scrollBy(0, drift);
      // A correction the document was too short to make is not progress, and
      // must not keep the hold alive; the next frame retries as it grows.
      if (window.scrollY !== before) {
        quietUntil = time + quietMs;
        onAdjust?.(window.scrollY);
      }
    }
    frame = requestAnimationFrame(step);
  };

  for (const event of HANDOFF_EVENTS) {
    window.addEventListener(event, release, { passive: true });
  }
  frame = requestAnimationFrame(step);
  return release;
}

function now(): number {
  return typeof performance === "undefined" ? Date.now() : performance.now();
}
