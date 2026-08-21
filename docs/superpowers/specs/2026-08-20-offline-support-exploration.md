# nano::nerd Reader — Offline Support Exploration

**Date:** 2026-08-20
**Status:** Implemented 2026-08-20 (approach B; decisions recorded at the end; plan in `docs/superpowers/plans/2026-08-20-offline-support.md`)

Goal as stated: (1) the article list is available offline, (2) articles on
that list can be read offline, (3) read tracking syncs to the server once
back online — and work out how sync conflicts should be handled.

## TL;DR

- **Offline reading is cheap.** Articles are text-only HTML (trafilatura
  runs with `include_images=False`), ~32 KB each in the local DB. Prefetching
  every `ready` article into IndexedDB is a few hundred KB per dozen
  articles. The app already ships a PWA manifest but has **no service
  worker**, so today nothing works offline — not even the app shell.
- **There are no real sync conflicts in the current data model.** The only
  things the client writes are (a) "chunk X has been read" — a set-once
  flag, and (b) "session S has N active seconds" — a monotonically
  increasing counter. Both merge trivially: union for reads, max for
  seconds. Two devices, offline replay, duplicate delivery, out-of-order
  delivery — none of them produce a conflict that needs a resolution
  policy. The work is making the API *idempotent and replayable*, not
  building a conflict resolver.
- **Four server changes** make replay correct: client-generated session ids
  (UUID upsert instead of server-allocated `id`), client-supplied
  timestamps (`read_at`, `started_at`) so stats land on the right day,
  tolerate unknown chunk ids (already true), and expose `extracted_at` on
  the list so the client can detect re-extracted articles.
- **Recommended shape:** service worker for the app shell only
  (`vite-plugin-pwa`, generateSW) + an IndexedDB local store that is the
  single source of truth for the UI + an outbox drained on load/online/tick.
  Don't cache `/api/*` at the service-worker layer; the app owns the data so
  it can overlay local progress onto server state.
- **Real conflicts appear only with future features** — "mark unread",
  "reset progress", archive/delete, reordering. The upgrade path for those
  is an op-log with per-field last-writer-wins; sketched below, not built.

## What exists today

Grounding facts that shape the design (file refs are to `main` at
`95deec6`):

| Area | Fact | Where |
|---|---|---|
| App shell | Vite/React SPA, `manifest.webmanifest` with `display: standalone`, installed to iPhone home screen. No service worker registered. | `web/index.html`, `web/public/manifest.webmanifest`, `web/src/main.tsx` |
| List | `GET /api/articles` → `ArticleSummary[]` with server-computed `percent_read`. Home polls every 3 s while any article is `pending`. | `src/nanonerd/reader/api.py:79`, `web/src/pages/Home.tsx` |
| Article | `GET /api/articles/{id}` → summary + `chunks[{id, position, html, word_count, read}]`. Content is immutable once `ready`; `retry` deletes and regenerates chunks (new ids). | `api.py:99`, `api.py:141` |
| Read marks | Client marks chunks read locally (IntersectionObserver + dwell), batches ids every 3 s to `POST /articles/{id}/progress {chunk_ids}`; `sendBeacon` on pagehide. Failed batches are requeued **in memory only** — lost on page close. Server: `UPDATE chunks SET read_at=now() WHERE id IN (...) AND read_at IS NULL` — idempotent, ignores unknown ids. | `web/src/reader/useReadTracking.ts`, `api.py:118` |
| Sessions | `POST /articles/{id}/sessions` allocates a server id; then `POST /sessions/{id} {active_seconds}` every 5 s; server keeps `max()`, stamps `last_active_at=now()`. Session creation retried on failure; if it never succeeds, the time is lost. | `web/src/reader/useReadingSession.ts`, `api.py:158`, `api.py:169` |
| Stats | Daily chart buckets by `ReadingSession.started_at` (server-stamped at creation). Totals/`words_read` use only the existence of `read_at`, not its value. | `src/nanonerd/reader/stats.py` |
| Saving | Bookmarklet / extension / iOS Shortcut `POST /api/articles {url}`; the **server** fetches and extracts. | `api.py:63`, `extension/background.js` |
| Scale | Single user, no auth, 8 articles locally, ~32 KB HTML each. | `AGENTS.md` scale assumptions |

## What "offline" has to mean here

The three stated requirements map to five concrete capabilities:

1. **App shell loads offline** — `/`, `/read/:id`, `/stats` must resolve
   without the network. Needs a service worker that precaches the Vite
   build and serves `index.html` for navigations.
2. **List available offline** — last-known summaries persisted locally;
   `percent_read` must reflect local (unsynced) progress, not the server's
   stale number.
3. **Article bodies available offline** — and not only for articles you
   happened to open while online. That means **prefetching** every `ready`
   article's chunks whenever the app is online. (Given ~32 KB/article, there
   is no reason to make this opt-in; a "downloaded" indicator is enough.)
4. **Tracking works offline** — read marks and active seconds are written
   to durable local storage *at the moment they happen* (not at flush
   time), then replayed.
5. **Replay is safe** — the server must accept late, duplicated, and
   reordered writes without corrupting state or stats.

Out of scope (and unchanged): saving new articles offline. The server does
the fetch/extract, so the phone cannot save without connectivity. The
extension, bookmarklet, and Shortcut are untouched by this work.

## Sync conflicts

### Inventory: every piece of state, who writes it, how it merges

| State | Written by | Read by | Merge rule | Conflict possible? |
|---|---|---|---|---|
| Article rows (url, title, status, content, categories, priority) | Server only (pipeline, retry) | Client | Server authoritative; client refetches | No — client never writes |
| Chunk rows (html, position, word_count) | Server only | Client | Same | No |
| `chunk.read_at` | Client (via progress) | Both | **Grow-only set.** Once read, stays read. Union of all devices' marks. Timestamp: earliest wins. | **No** |
| `reading_session.active_seconds` | Client | Stats | **Max register.** Per session, monotone non-decreasing. | **No** |
| `reading_session.started_at`, `last_active_at` | Server today → client after change | Stats | Set once by the device that owns the session | No |
| `percent_read` | Derived | Client | Recomputed from the union locally; server's number is advisory | No — but the client must stop trusting the server's value |
| Stats aggregates | Derived | Client | Network-only page; shows "needs connection" or last-known | No |

In CRDT terms the client writes exactly two things — a G-Set (read chunk
ids) and a max-register per session — which is why there's nothing to
"resolve". Every interleaving of two devices and a flaky network converges
to the same server state: the union of everything anyone read, and the max
of every session's clock.

### Worked scenarios

**A. Phone reads offline, laptop reads the same article online, phone
syncs later.** Laptop marks chunks 1–10 read at 14:00; server stamps them.
Phone (offline since 12:00) read chunks 1–15 at 12:30 and replays at 16:00.
Server: chunks 1–10 already read → no-op (or, with earliest-wins, `read_at`
corrected to 12:30); chunks 11–15 set with `read_at=12:30`. Both devices
refetch → both see 1–15 read. Sessions: two different sessions (one per
device per open), both summed into the article's active time. No conflict.

**B. Replay after a lost response.** Phone sends progress for chunks 3,4;
the request reaches the server but the response times out. Outbox keeps
the entry and resends. Server: `WHERE read_at IS NULL` matches nothing →
no-op, 200. Sessions: upsert with `max()` → no-op. Idempotent by
construction, so the outbox can retry blindly. **This is the property to
protect in every new endpoint.**

**C. Article re-extracted (`retry`) while phone was offline.** Phone's
pending reads reference chunk ids that no longer exist. Server's `IN (...)`
matches nothing → silently dropped (correct: the content changed, old
progress is meaningless). Client: when it refetches and sees a different
`extracted_at` (new field on the summary), it discards the cached body,
drops pending marks for that article, and re-downloads. Today `retry` is
only allowed from `failed`, so a `ready` article's chunks can't change
underneath you — this scenario only matters if re-extraction of ready
articles is added later.

**D. Clock skew.** Phone's clock is 10 min fast; it replays
`read_at=13:40` at server time 13:35. Server clamps:
`read_at = LEAST(client_ts, now())`. Same for `started_at`. Skew in the
other direction (slow clock) just puts the read a few minutes earlier than
truth — harmless for a 30-day daily chart.

**E. Two devices, one never comes back.** Offline marks on a phone that is
wiped before syncing are lost. Nothing to do; this is inherent. Mitigation
is "sync early, sync often": flush on app open, on `online`, and on every
5 s tick while online.

**F. Article deleted on the server (no delete endpoint exists today).**
Outbox replays progress → 404. The outbox must classify 4xx as *terminal*
(drop the entry, prune the local article) and network/5xx as *retryable*
(exponential backoff). Without that distinction a dead entry blocks the
queue forever.

**G. Same chunk read on two devices, both offline, both replay.** Union.
`read_at` = earliest of the two. No conflict.

### Changes that make replay correct

1. **Client-generated session ids.** Replace
   `POST /articles/{id}/sessions` + `POST /sessions/{id}` with a single
   idempotent upsert:
   `PUT /api/sessions/{client_id} {article_id, started_at, active_seconds}`
   where `client_id` is a UUID minted in the browser. Server inserts if
   missing, else `active_seconds = max(existing, payload)`,
   `last_active_at = now()` (or client-supplied). This also deletes the
   "creating / retry on later tick" dance in `useReadingSession.ts`.
   Schema: add `client_id` (uuid, unique) to `reading_sessions`; one
   Alembic migration.
2. **Client-supplied `read_at`.** `ProgressRequest` gains an optional
   per-chunk timestamp, e.g. `{marks: [{chunk_id, read_at}]}` (keep
   `chunk_ids` accepted for the beacon path). Server:
   `read_at = LEAST(COALESCE(read_at, ts), ts)` — earliest wins. Today
   `read_at`'s value is only used for existence, so this is cheap and makes
   the timestamp honest for any future "words read per day" chart.
3. **`extracted_at` on `ArticleSummary`.** Lets the client key its body
   cache on `(id, extracted_at)` and invalidate when content changes.
4. **Keep "unknown ids are ignored"** as an explicit contract (it's already
   the behavior; add a test so it stays that way).

Everything else on the server stays as is. No op-log, no vector clocks.

### Where real conflicts would come from, and the upgrade path

The no-conflict result holds only because every client write is monotone.
Each of these future features breaks that and needs a policy:

| Future feature | Why it conflicts | Cheapest correct policy |
|---|---|---|
| Mark unread / reset progress | `read_at` becomes a toggle, not a flag. Device A resets offline at t1, device B reads chunk at t2. | Per-chunk **LWW register**: store `(read, changed_at)`; replay applies only if `changed_at` is newer. Needs client timestamps (change #2 above already provides them). |
| Archive / delete from the client | Offline progress races a delete. | Tombstone `deleted_at` on `articles`; progress for tombstoned articles → 410, client prunes. |
| Manual priority / reorder | Two devices reorder offline. | LWW per article on `(priority, priority_changed_at)`, or give up and make it server-only (priority is currently reserved for AI reprioritization anyway). |
| Highlights / notes | Text edits. | Append-only notes are fine (G-Set again); *editing* a note needs LWW or real CRDT text — avoid editing. |

If two or more of those land, switch the outbox from "typed queue" to a
general **op-log**: each client write is `{op_id (uuid), kind, article_id,
payload, client_ts}`; server table `ops(op_id unique)` gives idempotency
for free; state is a fold over ops with per-field LWW. The IndexedDB
outbox proposed below is already shaped like that (an ordered list of
typed entries with client timestamps), so the migration is mechanical.
Don't build the op-log now — YAGNI — but don't shape the outbox in a way
that fights it.

## Approaches

### A. Service-worker-only (Workbox runtime caching + BackgroundSync)

`vite-plugin-pwa` with `runtimeCaching`: `NetworkFirst` for
`/api/articles*`, Workbox `BackgroundSyncPlugin` on the progress/session
POSTs.

- **Pros:** ~40 lines of config, no app code changes. Offline reading of
  previously-opened articles works in an afternoon.
- **Cons:** (1) Only articles you already opened are cached — no prefetch
  without extra code. (2) Cached list responses carry stale `percent_read`;
  the UI can't overlay local progress because the data lives in opaque HTTP
  cache entries. (3) Background Sync API is **not supported on iOS Safari /
  home-screen PWAs**; Workbox falls back to replaying when the SW starts,
  which is better than nothing but the queue lives in the SW, not the app,
  so the app can't show "3 unsynced reads". (4) Session creation still
  requires a server round-trip for the id → offline sessions still fail to
  be created → time lost. (5) The in-memory requeue in `useReadTracking`
  still drops marks on page close.
- **Verdict:** a fine 1-hour spike to feel it out, not the destination,
  because the iPhone is the primary reading device.

### B. App-owned local store + outbox, SW for shell only (recommended)

- **Service worker:** `vite-plugin-pwa` in `generateSW` mode, precache the
  build, `navigateFallback: index.html`. Explicitly *exclude* `/api` from
  runtime caching.
- **Local store (IndexedDB, via the 1 KB `idb` wrapper):**
  - `articles` — `ArticleSummary` + `extracted_at`, keyed by id; plus a
    `body` store of `ChunkData[]` keyed by id (kept separate so the list
    loads without deserializing bodies).
  - `read_marks` — `{chunk_id, article_id, read_at, synced: bool}`.
  - `sessions` — `{client_id, article_id, started_at, active_seconds,
    synced_seconds}`.
  - `meta` — `last_list_sync`.
- **Repository layer (`web/src/offline/store.ts`):** `loadList()` returns
  the local list immediately with `percent_read` recomputed from
  `read_marks ∪ server flags`, then kicks a background refresh when online.
  `loadArticle(id)` likewise. This replaces the direct `fetch` calls in
  `Home.tsx` and `Reader.tsx`.
- **Prefetch (`prefetch.ts`):** after each list refresh, download bodies
  for `ready` articles whose `(id, extracted_at)` isn't cached, 3 at a
  time. Show a small "n of m available offline" indicator on Home.
- **Write path:** `useReadTracking` and `useReadingSession` write to the
  store at event time (a mark becomes durable the moment the observer
  fires; seconds are persisted on every 5 s tick). They no longer call the
  network.
- **Outbox (`sync.ts`):** one drain routine: coalesce unsynced marks per
  article into one progress request; send `max(active_seconds)` per dirty
  session as one upsert. Triggered on app start, `online` event,
  `visibilitychange → visible`, and after each tick if online. Exponential
  backoff on failure; 4xx = terminal (drop + prune). Keep `sendBeacon` on
  `pagehide` as a best-effort fast path — duplicates are harmless because
  every endpoint is idempotent.
- **Pros:** works on iOS; UI always shows the truth (local ∪ server);
  testable merge logic with no network; explicit sync status; no data loss
  on page close; shaped like an op-log for later.
- **Cons:** ~400–600 lines of TypeScript touching both hooks and both
  pages; one migration + three API changes on the server; need to bring
  up a TS test runner (`vitest`) if you want the merge logic unit-tested
  (the web package has no tests today).

### C. Sync engine (Replicache / PowerSync / ElectricSQL / Yjs)

Solves a problem this app doesn't have (multi-writer, many tables, real
conflicts). Adds a backend service or SDK, auth wiring, and a mental
model for a single-user reader with two monotone write types. Not worth
it unless the data model grows the conflict-bearing features above — and
even then the op-log in B scales further than you'd expect.

## Proposed design (B), in enough detail to estimate

### Data flow

```
                 ┌───────────── online ─────────────┐
Home/Reader ──▶ store.ts ──▶ IndexedDB ◀── prefetch.ts ◀── GET /api/articles, /articles/{id}
    ▲               │
    │               ▼
    └── percent = f(server flags ∪ read_marks)
                                   sync.ts (drain) ──▶ POST /articles/{id}/progress {marks}
useReadTracking ──▶ read_marks ──┘        └──────────▶ PUT  /sessions/{client_id} {...}
useReadingSession ─▶ sessions  ──┘
```

### Server changes (Python, one migration)

| Change | Files |
|---|---|
| `reading_sessions.client_id` uuid unique nullable (nullable so existing rows survive); `PUT /api/sessions/{client_id}` upsert with `article_id`, `started_at`, `active_seconds`; delete the two old session endpoints (extension doesn't use them) | `models.py`, `schemas.py`, `api.py`, new `migrations/versions/…` |
| `ProgressRequest.marks: list[{chunk_id, read_at}]` (optional; `chunk_ids` still accepted); `read_at = LEAST(...)` with clamp to `now()` | `schemas.py`, `api.py` |
| `ArticleSummary.extracted_at` | `schemas.py`, `api.py` (`_summary`) |
| Tests: replay idempotency, unknown-id tolerance, earliest-wins, clamp, upsert max | `tests/reader/test_api.py`, `test_sessions.py` |

### Client changes (TypeScript)

| Change | Files |
|---|---|
| `vite-plugin-pwa` (generateSW, precache, navigateFallback, no `/api` runtime caching); register SW in `main.tsx`; request `navigator.storage.persist()` | `web/vite.config.ts`, `web/src/main.tsx`, `web/package.json` |
| `web/src/offline/db.ts` (idb schema + open), `store.ts` (read-through repo + percent overlay), `prefetch.ts`, `sync.ts` (outbox drain, backoff, terminal-vs-retryable), `useOnline.ts` | new |
| `Home.tsx`, `Reader.tsx` read from `store.ts`; Home shows offline/sync indicator; Stats shows "needs connection" when offline | edit |
| `useReadTracking.ts`: `markRead` → `store.addMark()`; drop in-memory `pending`/`requeue`; keep beacon as fast path | edit |
| `useReadingSession.ts`: mint `crypto.randomUUID()` at mount; persist `{client_id, article_id, started_at, active_seconds}` every tick; drop create/retry logic | edit |
| `api.ts`: `putSession`, `postMarks`; remove `markProgress` callback shape | edit |
| `types.ts`: `extracted_at`, `ReadMark`, `LocalSession` | edit |

### Gotchas worth knowing up front

- **iOS has no Background Sync / Periodic Sync.** All syncing happens while
  the app is in the foreground. That's fine for a single user who opens the
  app to read, but it means "close the app 2 s after finishing a paragraph
  while offline" syncs on *next* open, not in the background.
- **iOS storage eviction.** Safari deletes script-writable storage for
  sites unused for 7 days — but **home-screen-installed PWAs are exempt**.
  Call `navigator.storage.persist()` anyway; it's free.
- **`navigator.onLine` lies** (captive portals, lie-fi). Use it as a hint
  to *attempt* a drain; treat a failed fetch as the real offline signal and
  back off.
- **Write at event time, not flush time.** The reason marks survive a
  closed tab is that `store.addMark()` runs inside the
  IntersectionObserver callback, not in `pagehide` (where async IDB writes
  may not complete).
- **React StrictMode double-mount** will mint two session UUIDs in dev
  unless the id is created lazily on first persisted tick. Harmless
  (second session has 0 s and is never sent) but worth a comment.
- **Stale chunk ids** after a retry are dropped server-side; the client
  should also prune `read_marks` whose `article_id`'s `extracted_at`
  changed, so the "unsynced" count doesn't show phantom items.
- **Home's 3 s polling while `pending`** should pause when offline.
- **Bookmarklet/Shortcut saves** still require the server; nothing to do,
  but the setup page could say so.

## Phasing and effort

| Phase | Delivers | Rough size |
|---|---|---|
| 0 (optional spike) | Approach A config only — feel offline reading of opened articles | ~1 hr |
| 1 | App shell offline + local store + prefetch; read any `ready` article offline; tracking still online-only (unchanged hooks) | ~1 day |
| 2 | Outbox + server API changes (client session ids, timestamps, `extracted_at`) + migration + tests; hooks rewritten to write-through | ~1 day |
| 3 | Polish: offline/sync indicators, `storage.persist()`, stats offline state, vitest for merge logic | ~½ day |

Phases 1 and 2 are independently shippable; 1 alone already satisfies
"list + read offline", and the existing in-memory requeue keeps working
online.

## Decisions (2026-08-20)

1. **Prefetch everything.** Every `ready` article body is downloaded when
   the app is online; no opt-in.
2. **Drop the old session endpoints.** `POST /articles/{id}/sessions` and
   `POST /sessions/{id}` are removed in favor of the idempotent
   `PUT /sessions/{client_id}` upsert.
3. **Earliest `read_at` wins.** Server stores
   `LEAST(COALESCE(read_at, ts), ts)`, clamped to `now()`.
4. **Sync status UI:** one chip on Home — "offline" / "n unsynced".
5. **vitest now.** The sync layer ships with unit tests; merge/overlay
   logic is table-tested.
6. **Stats page is out of scope for offline.** It stays network-only and
   shows a "needs connection" message when the fetch fails.
7. **Separation of concerns (explicit requirement):** the sync code lives in
   `web/src/offline/` behind small interfaces — a `LocalStore` (IndexedDB
   persistence), a `SyncApi` (HTTP transport), and a pure `Syncer` that
   drains the outbox using those two. Hooks and pages depend only on the
   store/syncer interfaces, never on IndexedDB or `fetch` directly, and the
   syncer never imports React.
