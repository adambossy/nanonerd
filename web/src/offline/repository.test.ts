import { describe, expect, test } from "vitest";
import { article, body, chunk, mark } from "./fixtures";
import { MemoryStore } from "./memoryStore";
import { loadArticle, loadArticleList } from "./repository";

async function storeWith(opts: {
  articles?: ReturnType<typeof article>[];
  bodies?: ReturnType<typeof body>[];
  marks?: ReturnType<typeof mark>[];
  images?: Array<[number, string, number, number]>;
}): Promise<MemoryStore> {
  const store = new MemoryStore();
  await store.replaceArticles(opts.articles ?? []);
  for (const b of opts.bodies ?? []) await store.putBody(b);
  await store.addMarks(opts.marks ?? []);
  const byArticle = new Map<number, string[]>();
  for (const [articleId, url] of opts.images ?? []) {
    byArticle.set(articleId, [...(byArticle.get(articleId) ?? []), url]);
  }
  for (const [articleId, urls] of byArticle) await store.putImagesForArticle(articleId, urls);
  for (const [, url, width, height] of opts.images ?? []) {
    if (width > 0) await store.setImageSize(url, width, height);
  }
  return store;
}

describe("loadArticleList", () => {
  test("overlays local marks onto percent_read when a body is cached", async () => {
    const store = await storeWith({
      articles: [article({ id: 1, percent_read: 0 })],
      bodies: [body({ article_id: 1, chunks: [chunk({ id: 10, word_count: 50 }), chunk({ id: 11, word_count: 50 })] })],
      marks: [mark({ chunk_id: 10, article_id: 1 })],
    });

    const output = (await loadArticleList(store)).map((a) => a.percent_read);

    expect(output).toEqual([50]);
  });

  test("keeps the server percent when no body is cached", async () => {
    const store = await storeWith({ articles: [article({ id: 1, percent_read: 12.5 })] });

    const output = (await loadArticleList(store)).map((a) => a.percent_read);

    expect(output).toEqual([12.5]);
  });

  test("preserves store ordering", async () => {
    const store = await storeWith({
      articles: [article({ id: 1, priority: 0 }), article({ id: 2, priority: 9 })],
    });

    const output = (await loadArticleList(store)).map((a) => a.id);

    expect(output).toEqual([2, 1]);
  });
});

describe("loadArticle", () => {
  test("returns undefined when the body is not cached", async () => {
    const store = await storeWith({ articles: [article({ id: 1 })] });
    expect(await loadArticle(store, 1)).toBeUndefined();
  });

  test("returns undefined when the article summary is unknown", async () => {
    const store = await storeWith({ bodies: [body({ article_id: 1 })] });
    expect(await loadArticle(store, 1)).toBeUndefined();
  });

  test("merges server read flags with local marks into chunks and percent", async () => {
    const store = await storeWith({
      articles: [article({ id: 1, percent_read: 0 })],
      bodies: [
        body({
          article_id: 1,
          chunks: [
            chunk({ id: 10, position: 0, word_count: 50, read: true }),
            chunk({ id: 11, position: 1, word_count: 25 }),
            chunk({ id: 12, position: 2, word_count: 25 }),
          ],
        }),
      ],
      marks: [mark({ chunk_id: 11, article_id: 1 })],
    });

    const detail = await loadArticle(store, 1);
    const output = {
      read: detail?.chunks.map((c) => c.read),
      percent: detail?.percent_read,
      id: detail?.id,
    };

    expect(output).toEqual({ read: [true, true, false], percent: 75, id: 1 });
  });

  test("stamps measured image sizes into the chunk html", async () => {
    const store = await storeWith({
      articles: [article({ id: 1 })],
      bodies: [
        body({
          article_id: 1,
          chunks: [chunk({ id: 10, html: '<img src="/media/a.jpg"><img src="/media/b.jpg">' })],
        }),
      ],
      images: [
        [1, "/media/a.jpg", 1200, 800],
        [1, "/media/b.jpg", 0, 0],
      ],
    });

    const detail = await loadArticle(store, 1);

    expect(detail?.chunks[0].html).toBe(
      '<img src="/media/a.jpg" width="1200" height="800"><img src="/media/b.jpg">',
    );
  });

  test("does not borrow another article's image sizes", async () => {
    const store = await storeWith({
      articles: [article({ id: 1 }), article({ id: 2 })],
      bodies: [
        body({ article_id: 1, chunks: [chunk({ id: 10, html: '<img src="/media/a.jpg">' })] }),
      ],
      images: [[2, "/media/a.jpg", 1200, 800]],
    });

    const detail = await loadArticle(store, 1);

    expect(detail?.chunks[0].html).toBe('<img src="/media/a.jpg">');
  });
});
