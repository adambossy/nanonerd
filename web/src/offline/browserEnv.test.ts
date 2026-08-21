// @vitest-environment jsdom
import { afterEach, describe, expect, test, vi } from "vitest";
import { browserEnv } from "./index";

// index.ts starts the real scheduler as a side effect; in jsdom there is no
// IndexedDB, so it falls back to MemoryStore and its fetches fail harmlessly.

function setVisibility(state: "visible" | "hidden"): void {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("browserEnv", () => {
  afterEach(() => {
    setVisibility("visible");
  });

  test("isOnline and isVisible read navigator and document", () => {
    const env = browserEnv();
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });

    const output = [env.isOnline(), env.isVisible()];

    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => true });
    expect(output).toEqual([false, true]);
  });

  test("online maps to the window online event and unsubscribes cleanly", () => {
    const env = browserEnv();
    const handler = vi.fn();

    const off = env.on("online", handler);
    window.dispatchEvent(new Event("online"));
    off();
    window.dispatchEvent(new Event("online"));

    expect(handler).toHaveBeenCalledTimes(1);
  });

  test("visible fires only when visibility changes to visible", () => {
    const env = browserEnv();
    const handler = vi.fn();

    env.on("visible", handler);
    setVisibility("hidden");
    setVisibility("visible");

    expect(handler).toHaveBeenCalledTimes(1);
  });

  test("hidden fires on visibilitychange→hidden and on pagehide, and unsubscribes both", () => {
    const env = browserEnv();
    const handler = vi.fn();

    const off = env.on("hidden", handler);
    setVisibility("hidden");
    setVisibility("visible");
    window.dispatchEvent(new Event("pagehide"));
    const before = handler.mock.calls.length;
    off();
    setVisibility("hidden");
    window.dispatchEvent(new Event("pagehide"));

    expect([before, handler.mock.calls.length]).toEqual([2, 2]);
  });

  test("setTimeout/clearTimeout delegate to the window timers", () => {
    vi.useFakeTimers();
    const env = browserEnv();
    const fired = vi.fn();

    const handle = env.setTimeout(fired, 100);
    env.clearTimeout(handle);
    vi.advanceTimersByTime(200);
    env.setTimeout(fired, 100);
    vi.advanceTimersByTime(200);
    vi.useRealTimers();

    expect(fired).toHaveBeenCalledTimes(1);
  });
});
