import type { HistoryEntry, ResumeTarget, SnapshotState, StatsResponse } from "./types";

// Network-only actions. Reading and progress tracking go through src/offline.

async function asJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export async function retryArticle(id: number): Promise<void> {
  const response = await fetch(`/api/articles/${id}/retry`, { method: "POST" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
}

export async function archiveArticle(id: number): Promise<void> {
  const response = await fetch(`/api/articles/${id}/archive`, { method: "POST" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
}

export async function deleteArticle(id: number): Promise<void> {
  const response = await fetch(`/api/articles/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
}

// Faithful-mode snapshots are online-only: the HTML is multi-MB and never
// cached locally, and capture is an explicit server-side action.
export async function getSnapshotHtml(id: number): Promise<string> {
  const response = await fetch(`/api/articles/${id}/snapshot`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.text();
}

export async function requestSnapshot(id: number): Promise<SnapshotState> {
  const response = await fetch(`/api/articles/${id}/snapshot`, { method: "POST" });
  return asJson<SnapshotState>(response);
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
