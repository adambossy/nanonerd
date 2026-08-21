import type { HistoryEntry, ResumeTarget, StatsResponse } from "./types";

// Network-only actions. Reading and progress tracking go through src/offline.

async function asJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export async function retryArticle(id: number): Promise<void> {
  const response = await fetch(`/api/articles/${id}/retry`, { method: "POST" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
}

export function getStats(): Promise<StatsResponse> {
  return fetch("/api/stats").then((r) => asJson<StatsResponse>(r));
}

export function getResume(): Promise<ResumeTarget | null> {
  return fetch("/api/resume").then((r) => asJson<ResumeTarget | null>(r));
}

export function getHistory(): Promise<HistoryEntry[]> {
  return fetch("/api/history").then((r) => asJson<HistoryEntry[]>(r));
}
