import type { ReadMark, StoredArticle, StoredBody } from "./types";

/**
 * Pure read-state math: what the reader and list should display given the
 * last server snapshot (body chunks' `read` flags) and this device's marks.
 */

/** Chunk ids that count as read: server flags ∪ local marks (restricted to the body's chunks when a body is given). */
export function readIdsFor(body: StoredBody | undefined, marks: ReadMark[]): Set<number> {
  const ids = new Set<number>();
  if (!body) {
    for (const m of marks) ids.add(m.chunk_id);
    return ids;
  }
  const known = new Set(body.chunks.map((c) => c.id));
  for (const c of body.chunks) if (c.read) ids.add(c.id);
  for (const m of marks) if (known.has(m.chunk_id)) ids.add(m.chunk_id);
  return ids;
}

/** Percent read with local marks overlaid; falls back to the server's number when no body is cached. */
export function percentFor(
  article: StoredArticle,
  body: StoredBody | undefined,
  marks: ReadMark[],
): number {
  if (!body) return article.percent_read;
  const total = body.chunks.reduce((sum, c) => sum + c.word_count, 0);
  if (total <= 0) return 0;
  const readIds = readIdsFor(body, marks);
  const read = body.chunks
    .filter((c) => readIds.has(c.id))
    .reduce((sum, c) => sum + c.word_count, 0);
  return Math.round((1000 * read) / total) / 10;
}
