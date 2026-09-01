// @vitest-environment jsdom
import { afterEach, describe, expect, test, vi } from "vitest";
import { scrollToAndHold } from "./anchorScroll";

/**
 * A stand-in for the article: `top` is where the anchor currently sits in the
 * viewport, and `grow` simulates an image loading above it, which pushes the
 * anchor down exactly as a real reflow would.
 */
function fakeArticle(startTop = 0) {
  let top = startTop;
  let scrollY = 0;
  const target = {
    scrollIntoView: () => {
      top = 0;
    },
    getBoundingClientRect: () => ({ top }) as unknown as DOMRect,
  } as unknown as Element;

  Object.defineProperty(window, "scrollY", { configurable: true, get: () => scrollY });
  window.scrollBy = ((_x: number, by: number) => {
    scrollY += by;
    top -= by;
  }) as typeof window.scrollBy;

  return {
    target,
    grow: (pixels: number) => {
      top += pixels;
    },
    top: () => top,
    scrollY: () => scrollY,
  };
}

/** Drive the rAF loop `count` times. */
function frames(count: number): void {
  for (let i = 0; i < count; i++) vi.advanceTimersByTime(16);
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("scrollToAndHold", () => {
  test("keeps the anchor in place when images load above it", () => {
    vi.useFakeTimers();
    const article = fakeArticle(900);

    scrollToAndHold(article.target);
    article.grow(300); // an image above the anchor finishes loading
    frames(2);

    expect([article.top(), article.scrollY()]).toEqual([0, 300]);
  });

  test("corrects repeatedly while the page keeps growing", () => {
    vi.useFakeTimers();
    const article = fakeArticle(900);

    scrollToAndHold(article.target);
    for (let i = 0; i < 4; i++) {
      article.grow(120);
      frames(1);
    }

    expect([article.top(), article.scrollY()]).toEqual([0, 480]);
  });

  test("reports each correction so the caller can rebase on it", () => {
    vi.useFakeTimers();
    const article = fakeArticle();
    const adjustments: number[] = [];

    scrollToAndHold(article.target, { onAdjust: (y) => adjustments.push(y) });
    article.grow(200);
    frames(2);
    article.grow(50);
    frames(2);

    expect(adjustments).toEqual([200, 250]);
  });

  test("hands control back the moment the reader scrolls", () => {
    vi.useFakeTimers();
    const article = fakeArticle();

    scrollToAndHold(article.target);
    window.dispatchEvent(new Event("touchstart"));
    article.grow(300);
    frames(3);

    expect([article.top(), article.scrollY()]).toEqual([300, 0]);
  });

  test("releases once the layout has been quiet", () => {
    vi.useFakeTimers();
    const article = fakeArticle();

    scrollToAndHold(article.target, { quietMs: 100 });
    frames(20); // 320ms of nothing happening
    article.grow(300);
    frames(3);

    expect([article.top(), article.scrollY()]).toEqual([300, 0]);
  });

  test("release() stops correcting", () => {
    vi.useFakeTimers();
    const article = fakeArticle();

    const release = scrollToAndHold(article.target);
    release();
    release(); // idempotent
    article.grow(300);
    frames(3);

    expect(article.top()).toBe(300);
  });

  test("suspends smooth scrolling for the hold and restores it on release", () => {
    vi.useFakeTimers();
    const article = fakeArticle();
    const root = document.documentElement;
    root.style.scrollBehavior = "smooth";

    const release = scrollToAndHold(article.target);
    const duringHold = root.style.scrollBehavior;
    release();

    expect([duringHold, root.style.scrollBehavior]).toEqual(["auto", "smooth"]);
  });

  test("does not fight a document that cannot scroll any further", () => {
    vi.useFakeTimers();
    const article = fakeArticle();
    const adjustments: number[] = [];
    window.scrollBy = (() => undefined) as typeof window.scrollBy; // at the end of the document

    scrollToAndHold(article.target, { onAdjust: (y) => adjustments.push(y), quietMs: 100 });
    article.grow(300);
    frames(20);

    expect(adjustments).toEqual([]);
  });
});
