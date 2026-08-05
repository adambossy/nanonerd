# nano::nerd Reader — Design

**Date:** 2026-08-04
**Status:** Approved (prototype scope)

A read-later app: save articles from any browser via bookmarklet or iOS share
sheet, store a static text snapshot in Postgres, and read them in a clean
chunked reader that tracks how much of each article you have actually read.

## Decisions made during brainstorming

- **Stack:** FastAPI (Python) JSON API + separate Vite/React/TypeScript PWA.
- **Mobile:** iPhone — share-sheet saving via an iOS Shortcut (Web Share
  Target is not supported on iOS). PWA manifest still ships so the reader
  installs to the home screen.
- **Categories:** open taxonomy. Claude assigns 3–5 free-form categories per
  article, prompted with existing category names so the taxonomy converges.
- **Auth:** none. Single-user prototype; endpoints are open.
- **Deployment:** local-first. Dockerfile, `fly.toml`, and Neon setup
  instructions are included but not executed. Prod targets: Neon Postgres +
  Fly.io (same Fly account as transactoid).

## Architecture

Two components in this repo, one deployable unit:

- **`server/`** — FastAPI (Python 3.12, matching repo tooling: uv, ruff,
  mypy, pytest). Serves the JSON API and, in production, the built React app
  as static files. SQLAlchemy + Alembic against Postgres (Neon in prod;
  local Postgres or a Neon dev branch locally). Article extraction with
  **trafilatura**. Categorization via the Claude API (`claude-haiku-4-5`).
- **`web/`** — Vite + React + TypeScript PWA. Reader UI, home list, PWA
  manifest. Dev mode proxies `/api` to the FastAPI server.

### Save flow

Bookmarklet/Shortcut hits `POST /api/articles` with `{url, title?}`. The
endpoint dedupes on normalized URL and returns in <100ms: a row is inserted
with status `pending`, then a FastAPI `BackgroundTasks` job fetches the page,
extracts content, chunks it, and calls Claude for categories. The bookmarklet
shows a small in-page toast (saved / already saved) without leaving the page.

## Data model

```
articles:  id, url (unique, normalized), title, author, site_name, status
           (pending|ready|failed), content_html (static snapshot), word_count,
           priority (int, default 0 — reserved for future AI reprioritization),
           added_at, extracted_at
chunks:    id, article_id, position, html, word_count, read_at (nullable)
categories:         id, name (unique)
article_categories: article_id, category_id
```

Percent complete = sum of read chunks' word counts / total word count.
Computed in the list query, not stored.

URL normalization for dedupe: lowercase scheme/host, strip fragment, strip
common tracking params (`utm_*`, `fbclid`, `gclid`), strip trailing slash.

## Chunking

Extracted HTML is split on block elements, and every block element
(paragraph, heading, blockquote, ...) becomes its own chunk — one chunk per
paragraph, matching the intuitive reading unit. (Originally chunks were
greedily grouped to ~150–300 words; changed by user decision on 2026-08-05.)
Each chunk renders as `<section data-chunk-id>` in the reader.

## Read tracking

An `IntersectionObserver` watches each chunk. A chunk is marked read when all
three hold:

1. Its bottom edge has passed the viewport's reading zone (the user scrolled
   fully through it).
2. Time since the chunk first became visible ≥ a minimum dwell time derived
   from word count (word_count / 30 words per second — reading faster than
   ~1800 wpm doesn't count).
3. The tab is visible (Page Visibility API).

Fast-swiping past a chunk fails condition 2 and does not mark it. Marks are
batched to `POST /api/articles/:id/progress`, with `navigator.sendBeacon` on
page hide so closing the tab doesn't lose progress. Opening an article scrolls
to the first unread chunk.

## Reader UI

Typography-first: single column ~65ch, generous line height, serif body,
light/dark. Thin margin-rail marker per read chunk; progress bar at top. No
read/unread visual noise in the text itself.

## Home page

Articles sorted by priority, then added date: title, site, category chips,
percent-complete bar, word count / estimated reading time. Tap → reader at
first unread chunk. Pending articles show a "processing…" state; the list
polls until they're ready.

## Save surfaces

- **Bookmarklet** (Chrome + Arc): `javascript:` one-liner that POSTs
  `location.href` + `document.title` and shows an in-page toast. Served from
  a `/setup` page with the API base URL baked in, drag-to-bookmarks-bar.
- **iOS Shortcut** ("Save to nano::nerd"): accepts a URL from the share
  sheet, POSTs it to the API. Exact setup instructions generated on the
  `/setup` page (~6 steps in the Shortcuts app).

## Error handling

- Extraction failure → article status `failed`, error visible in the list,
  retry button re-runs the pipeline.
- Categorization failure → non-fatal: article still readable, categories
  empty, retryable.
- Duplicate save → 200 with `duplicate: true` so save surfaces can say
  "already saved."

## Testing

Pytest for the API following AGENTS.md conventions (input / act / expected /
single assert): URL normalization and dedupe, chunking rules, progress math.
Extraction (network) and Claude calls are mocked. The frontend prototype is
verified by driving it in the browser, not unit-tested.

## Out of scope

- AI reprioritization (the `priority` field exists; nothing writes it yet).
- Auth.
- Actual Neon/Fly provisioning and deployment.
- Native mobile app (PWA is the path there if the prototype works).
