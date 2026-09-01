import type { StoredImage } from "./types";

/**
 * Image bookkeeping over chunk HTML.
 *
 * Chunk HTML arrives already sanitized by the server (`nh3`), which escapes
 * `>` inside attribute values, so an `<img …>` tag never contains a raw `>`
 * and matching a tag with a regex is exact here. That keeps this module pure
 * and DOM-free, which matters because it runs inside the repository on every
 * article load.
 */

const IMG_TAG = /<img\b[^>]*>/gi;
const SRC = /\bsrc\s*=\s*"([^"]*)"/i;
const HAS_SIZE = /\b(?:width|height)\s*=/i;

/** Every distinct `src` referenced by these chunks, in document order. */
export function imageUrlsIn(chunks: { html: string }[]): string[] {
  const urls: string[] = [];
  const seen = new Set<string>();
  for (const chunk of chunks) {
    for (const tag of chunk.html.match(IMG_TAG) ?? []) {
      const url = SRC.exec(tag)?.[1];
      if (!url || seen.has(url)) continue;
      seen.add(url);
      urls.push(url);
    }
  }
  return urls;
}

/**
 * Stamp each image's measured natural size onto its tag so the browser
 * reserves the right box on the very first paint. Without it an image is zero
 * pixels tall until its bytes arrive and every late arrival shoves the rest of
 * the article down. Tags that already carry a dimension are left alone — the
 * source page's own numbers win.
 */
export function withImageSizes(html: string, sizes: Map<string, StoredImage>): string {
  if (sizes.size === 0) return html;
  return html.replace(IMG_TAG, (tag) => {
    if (HAS_SIZE.test(tag)) return tag;
    const size = sizes.get(SRC.exec(tag)?.[1] ?? "");
    if (!size) return tag;
    return `${tag.replace(/\s*\/?>$/, "")} width="${size.width}" height="${size.height}">`;
  });
}
