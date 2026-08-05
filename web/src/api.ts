import type { ArticleDetail, ArticleSummary } from "./types";

async function asJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export function listArticles(): Promise<ArticleSummary[]> {
  return fetch("/api/articles").then((r) => asJson<ArticleSummary[]>(r));
}

export function getArticle(id: number): Promise<ArticleDetail> {
  return fetch(`/api/articles/${id}`).then((r) => asJson<ArticleDetail>(r));
}

export async function retryArticle(id: number): Promise<void> {
  await fetch(`/api/articles/${id}/retry`, { method: "POST" });
}

export function markProgress(
  id: number,
  chunkIds: number[],
  onFail: (ids: number[]) => void,
): void {
  fetch(`/api/articles/${id}/progress`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chunk_ids: chunkIds }),
  }).catch(() => onFail(chunkIds));
}

export function beaconProgress(id: number, chunkIds: number[]): void {
  const blob = new Blob([JSON.stringify({ chunk_ids: chunkIds })], {
    type: "application/json",
  });
  navigator.sendBeacon(`/api/articles/${id}/progress`, blob);
}
