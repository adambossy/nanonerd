import type { ArticleSummary, FidelityStatus } from "../types";

const BADGE_LABELS: Record<Exclude<FidelityStatus, "ok">, string> = {
  degraded: "incomplete",
  not_article: "not an article",
  blocked: "blocked",
};

/** Short label for the list view — "ok" extractions get no badge at all. */
export function fidelityBadge(article: ArticleSummary): string | null {
  const status = article.fidelity_status;
  if (status === null || status === "ok") return null;
  return BADGE_LABELS[status];
}

/** One-line notice for the reader, shown only when content is likely missing. */
export function fidelityNotice(article: ArticleSummary): string | null {
  if (article.fidelity_status !== "degraded") return null;
  const reason = article.fidelity_reasons[0];
  return reason
    ? `extraction may be incomplete — ${reason}`
    : "extraction may be incomplete";
}
