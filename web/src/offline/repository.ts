import type { ArticleDetail, ArticleSummary } from "../types";
import { withImageSizes } from "./images";
import { percentFor, readIdsFor } from "./reading";
import type { LocalStore } from "./store";

/**
 * What the pages render. Reads only from the LocalStore and overlays this
 * device's unsynced progress, so the UI never shows state older than what
 * the user has actually done.
 */

export async function loadArticleList(store: LocalStore): Promise<ArticleSummary[]> {
  const articles = await store.listArticles();
  const overlaid = await Promise.all(
    articles.map(async (article) => {
      const [body, marks] = await Promise.all([
        store.getBody(article.id),
        store.marksForArticle(article.id),
      ]);
      return { ...article, percent_read: percentFor(article, body, marks) };
    }),
  );
  return overlaid;
}

/** Undefined when the article or its body is not cached locally. */
export async function loadArticle(
  store: LocalStore,
  id: number,
): Promise<ArticleDetail | undefined> {
  const [article, body, marks, images] = await Promise.all([
    store.getArticle(id),
    store.getBody(id),
    store.marksForArticle(id),
    store.imagesForArticle(id),
  ]);
  if (!article || !body) return undefined;
  const readIds = readIdsFor(body, marks);
  const sizes = new Map(images.filter((i) => i.width > 0).map((i) => [i.url, i]));
  return {
    ...article,
    percent_read: percentFor(article, body, marks),
    chunks: body.chunks.map((c) => ({
      ...c,
      html: withImageSizes(c.html, sizes),
      read: readIds.has(c.id),
    })),
  };
}
