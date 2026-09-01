/**
 * Pulls an article image into the offline cache and reports its natural size.
 *
 * Both happen in one step, by loading the url into a detached `<img>`: the
 * request goes through the service worker like any other image request, so the
 * `article-images` runtime cache (see vite.config.ts) keeps the bytes, and the
 * element hands us the dimensions the reader needs to reserve the image's box.
 *
 * An `<img>` load is also the only way to reach the media host at all — it
 * answers cross-origin without CORS headers, so `fetch()` could never read the
 * response and `Cache.add()` would reject it.
 */

export interface ImageSize {
  width: number;
  height: number;
}

export interface ImageWarmer {
  /** Resolves with the natural size, or null when the image could not be loaded. */
  warm(url: string): Promise<ImageSize | null>;
}

/** Used where there is no DOM (unit tests, and the MemoryStore fallback path). */
export const noImageWarmer: ImageWarmer = {
  async warm(): Promise<ImageSize | null> {
    return null;
  },
};

export function domImageWarmer(timeoutMs = 30_000): ImageWarmer {
  return {
    warm(url: string): Promise<ImageSize | null> {
      return new Promise((resolve) => {
        const image = new Image();
        let settled = false;
        const finish = (size: ImageSize | null) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          image.onload = null;
          image.onerror = null;
          resolve(size);
        };
        const timer = setTimeout(() => {
          // Abandon the request so a stalled connection cannot pin the element.
          image.src = "";
          finish(null);
        }, timeoutMs);
        image.onload = () =>
          // SVGs without an intrinsic size report 0; there is nothing to reserve,
          // so treat them as unmeasurable rather than stamping a zero box.
          finish(
            image.naturalWidth > 0 && image.naturalHeight > 0
              ? { width: image.naturalWidth, height: image.naturalHeight }
              : null,
          );
        image.onerror = () => finish(null);
        image.decoding = "async";
        image.src = url;
      });
    },
  };
}

/** The warmer for the current environment. */
export function imageWarmer(): ImageWarmer {
  return typeof Image === "undefined" ? noImageWarmer : domImageWarmer();
}
