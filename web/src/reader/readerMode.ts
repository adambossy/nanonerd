export type ReaderMode = "reader" | "faithful";

const KEY_PREFIX = "nanonerd:reader-mode:";

export function loadReaderMode(articleId: number): ReaderMode {
  try {
    return localStorage.getItem(KEY_PREFIX + articleId) === "faithful"
      ? "faithful"
      : "reader";
  } catch {
    return "reader";
  }
}

export function saveReaderMode(articleId: number, mode: ReaderMode): void {
  try {
    localStorage.setItem(KEY_PREFIX + articleId, mode);
  } catch {
    // storage unavailable (private mode, quota) – the toggle still works for
    // this page view.
  }
}
