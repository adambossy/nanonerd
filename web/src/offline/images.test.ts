import { describe, expect, test } from "vitest";
import { imageUrlsIn, withImageSizes } from "./images";
import type { StoredImage } from "./types";

function sizes(...images: Array<[string, number, number]>): Map<string, StoredImage> {
  return new Map(
    images.map(([url, width, height]) => [url, { url, article_id: 1, width, height }]),
  );
}

describe("imageUrlsIn", () => {
  test("collects each src once, in document order", () => {
    const input = [
      { html: '<p>a</p><img src="/media/a.jpg" alt="a">' },
      { html: '<figure><img src="/media/b.png"><img src="/media/a.jpg"></figure>' },
    ];

    const output = imageUrlsIn(input);

    expect(output).toEqual(["/media/a.jpg", "/media/b.png"]);
  });

  test("ignores tags with no src and chunks with no images", () => {
    const input = [{ html: "<p>text only</p>" }, { html: "<img alt=\"broken\">" }];

    expect(imageUrlsIn(input)).toEqual([]);
  });

  test("is not confused by a > inside an escaped attribute value", () => {
    const input = [{ html: '<img src="/media/a.jpg" alt="a &gt; b"><img src="/media/b.jpg">' }];

    expect(imageUrlsIn(input)).toEqual(["/media/a.jpg", "/media/b.jpg"]);
  });
});

describe("withImageSizes", () => {
  test("stamps the measured natural size onto a bare img", () => {
    const input = '<p>x</p><img src="/media/a.jpg" alt="a" loading="lazy">';

    const output = withImageSizes(input, sizes(["/media/a.jpg", 1200, 800]));

    expect(output).toBe(
      '<p>x</p><img src="/media/a.jpg" alt="a" loading="lazy" width="1200" height="800">',
    );
  });

  test("leaves a tag that already declares a dimension alone", () => {
    const input = '<img src="/media/a.jpg" width="640">';

    expect(withImageSizes(input, sizes(["/media/a.jpg", 1200, 800]))).toBe(input);
  });

  test("leaves images with no measurement alone", () => {
    const input = '<img src="/media/a.jpg"><img src="/media/b.jpg">';

    const output = withImageSizes(input, sizes(["/media/b.jpg", 300, 300]));

    expect(output).toBe('<img src="/media/a.jpg"><img src="/media/b.jpg" width="300" height="300">');
  });

  test("handles a self-closing tag without doubling the slash", () => {
    const input = '<img src="/media/a.jpg" />';

    const output = withImageSizes(input, sizes(["/media/a.jpg", 10, 20]));

    expect(output).toBe('<img src="/media/a.jpg" width="10" height="20">');
  });

  test("returns the html untouched when nothing has been measured", () => {
    const input = '<img src="/media/a.jpg">';

    expect(withImageSizes(input, new Map())).toBe(input);
  });
});
