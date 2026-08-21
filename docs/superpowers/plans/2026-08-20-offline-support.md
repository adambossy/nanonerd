# Offline Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The reader PWA works offline — the article list and every ready article body are available without a network, read marks and reading time are recorded locally at event time, and everything replays to the server idempotently when connectivity returns.

**Architecture:** Server: make the two client-write endpoints replayable (client-supplied `read_at` with earliest-wins; client-keyed session upsert) and expose `extracted_at` for cache keys. Web: a self-contained `web/src/offline/` package with three seams — `LocalStore` (persistence; IndexedDB impl + in-memory impl), `SyncApi` (HTTP transport), and a pure `Syncer` that pushes the outbox and pulls/prefetches — plus a `SyncScheduler` that decides *when* to sync. Hooks and pages depend only on those interfaces. A service worker (vite-plugin-pwa) precaches the app shell and nothing else.

**Tech Stack:** FastAPI/SQLAlchemy/Alembic/pytest (server); Vite 6, React 19, TypeScript, `idb`, `vite-plugin-pwa`, `vitest`, `fake-indexeddb` (web).

**Spec:** `docs/superpowers/specs/2026-08-20-offline-support-exploration.md`

## Global Constraints

- Python 3.12 tooling: `uv run ruff check .`, `uv run ruff format .`, `uv run mypy --config-file mypy.ini .`, `uv run deadcode .`, `uv run pytest -q` must all pass before finishing (AGENTS.md).
- Web: `cd web && npm run build` (runs `tsc --noEmit`) and `npm test` (vitest) must pass.
- Test style (AGENTS.md): input → helper setup → single `output = ...` → `expected_output` → one assert. Test names `test_<unit>_<behavior>`.
- Old session endpoints are **removed** (decision 2). Earliest `read_at` wins, clamped to server now (decision 3). Prefetch everything (decision 1). Stats page stays network-only (decision 6).
- `web/src/offline/syncer.ts`, `store.ts`, `memoryStore.ts`, `idbStore.ts`, `transport.ts`, `scheduler.ts`, `reading.ts`, `repository.ts` must not import React or touch `window`/`document` except through injected parameters.
- Single-user app: no auth, no multi-tenant concerns.

---

## File structure

Server (modify): `src/nanonerd/reader/models.py`, `schemas.py`, `api.py`; new `migrations/versions/<rev>_session_client_id.py`; tests `tests/reader/test_api.py`, `test_sessions.py`.

Web (new, `web/src/offline/`):

| File | Responsibility |
|---|---|
| `types.ts` | Stored record types: `StoredArticle`, `StoredBody`, `ReadMark`, `LocalSession`, `SyncStatus` |
| `store.ts` | `LocalStore` interface only |
| `memoryStore.ts` | `MemoryStore implements LocalStore` (tests + fallback) |
| `idbStore.ts` | `IdbStore implements LocalStore` via `idb` |
| `transport.ts` | `SyncApi` interface, `SyncError`, `HttpSyncApi` (fetch) |
| `reading.ts` | Pure functions: `readIdsFor(body, marks)`, `percentFor(article, body, marks)` |
| `repository.ts` | `loadArticleList(store)`, `loadArticle(store, id)` — what pages render |
| `syncer.ts` | `Syncer`: `pushMarks`, `pushSessions`, `refreshArticles`, `prefetchBodies`, `syncAll` |
| `scheduler.ts` | `SyncScheduler`: triggers (start/online/visible/interval/request), backoff, status subscription |
| `index.ts` | Composition root: `offline` singleton `{store, syncer, scheduler}` |
| `useSyncStatus.ts` | React hook adapter over `scheduler.subscribe` |

Web (modify): `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/src/main.tsx`, `web/src/api.ts`, `web/src/types.ts`, `web/src/reader/useReadTracking.ts`, `web/src/reader/useReadingSession.ts`, `web/src/pages/Home.tsx`, `web/src/pages/Reader.tsx`, `web/src/pages/Stats.tsx`, `web/src/styles.css`.

Web tests (new, `web/src/offline/*.test.ts`): `store.contract.test.ts` (run against both stores), `reading.test.ts`, `repository.test.ts`, `syncer.test.ts`, `scheduler.test.ts`, `transport.test.ts`.

---

### Task 1: Server — `extracted_at` on summaries and earliest-wins read marks

**Files:**
- Modify: `src/nanonerd/reader/schemas.py`, `src/nanonerd/reader/api.py:45-60,117-138`
- Test: `tests/reader/test_api.py`

**Interfaces:**
- Produces: `ArticleSummary.extracted_at: datetime | None`; `ProgressRequest { chunk_ids: list[int] = [], marks: list[ReadMark] = [] }` with `ReadMark { chunk_id: int, read_at: datetime }`; server rule `read_at = min(existing, clamp(read_at, now))`.

- [ ] **Step 1: Write failing tests** (append to `tests/reader/test_api.py`)

```python
def _read_at_by_position(factory, article_id):
    with factory() as session:
        article = session.get(Article, article_id)
        return [
            chunk.read_at.replace(tzinfo=UTC) if chunk.read_at else None
            for chunk in article.chunks
        ]


def test_list_articles_includes_extracted_at(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    seed_ready_article(factory)

    output = client.get("/api/articles").json()[0]

    assert "extracted_at" in output


def test_mark_progress_with_marks_uses_client_timestamp(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, chunk_ids = seed_ready_article(factory)
    read_at = "2026-01-02T03:04:05Z"

    client.post(
        f"/api/articles/{article_id}/progress",
        json={"marks": [{"chunk_id": chunk_ids[1], "read_at": read_at}]},
    )

    output = _read_at_by_position(factory, article_id)[1]
    assert output == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_mark_progress_earliest_read_at_wins(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, chunk_ids = seed_ready_article(factory)
    later = {"chunk_id": chunk_ids[1], "read_at": "2026-01-05T00:00:00Z"}
    earlier = {"chunk_id": chunk_ids[1], "read_at": "2026-01-01T00:00:00Z"}

    client.post(f"/api/articles/{article_id}/progress", json={"marks": [later]})
    client.post(f"/api/articles/{article_id}/progress", json={"marks": [earlier]})

    output = _read_at_by_position(factory, article_id)[1]
    assert output == datetime(2026, 1, 1, tzinfo=UTC)


def test_mark_progress_clamps_future_read_at_to_now(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, chunk_ids = seed_ready_article(factory)
    before = datetime.now(UTC)

    client.post(
        f"/api/articles/{article_id}/progress",
        json={"marks": [{"chunk_id": chunk_ids[1], "read_at": "2999-01-01T00:00:00Z"}]},
    )

    output = _read_at_by_position(factory, article_id)[1]
    assert before <= output <= datetime.now(UTC)


def test_mark_progress_ignores_unknown_and_foreign_chunk_ids(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, _chunk_ids = seed_ready_article(factory)

    response = client.post(
        f"/api/articles/{article_id}/progress",
        json={"chunk_ids": [999999], "marks": [{"chunk_id": 999998, "read_at": "2026-01-01T00:00:00Z"}]},
    )

    assert (response.status_code, response.json()["percent_read"]) == (200, 25.0)


def test_mark_progress_replay_is_idempotent(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, chunk_ids = seed_ready_article(factory)
    payload = {"marks": [{"chunk_id": chunk_ids[1], "read_at": "2026-01-01T00:00:00Z"}]}

    first = client.post(f"/api/articles/{article_id}/progress", json=payload).json()
    second = client.post(f"/api/articles/{article_id}/progress", json=payload).json()

    assert (first, second, _read_at_by_position(factory, article_id)[1]) == (
        {"percent_read": 100.0},
        {"percent_read": 100.0},
        datetime(2026, 1, 1, tzinfo=UTC),
    )
```

- [ ] **Step 2: Run** `uv run pytest tests/reader/test_api.py -q` → the new tests FAIL (422 on `marks`, missing `extracted_at`).

- [ ] **Step 3: Implement**

`schemas.py`:
```python
class ArticleSummary(BaseModel):
    ...
    added_at: datetime
    extracted_at: datetime | None


class ReadMark(BaseModel):
    chunk_id: int
    read_at: datetime


class ProgressRequest(BaseModel):
    chunk_ids: list[int] = []
    marks: list[ReadMark] = []
```

`api.py` — `_summary` adds `extracted_at=article.extracted_at`; replace the body of `mark_progress`:
```python
def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _requested_read_times(payload: ProgressRequest, now: datetime) -> dict[int, datetime]:
    times = {chunk_id: now for chunk_id in payload.chunk_ids}
    for mark in payload.marks:
        requested = min(_as_utc(mark.read_at), now)
        existing = times.get(mark.chunk_id)
        times[mark.chunk_id] = requested if existing is None else min(existing, requested)
    return times


def _apply_read_times(session: Session, article_id: int, times: dict[int, datetime]) -> None:
    if not times:
        return
    chunks = session.scalars(
        select(Chunk).where(Chunk.article_id == article_id, Chunk.id.in_(times))
    ).all()
    rows = []
    for chunk in chunks:
        requested = times[chunk.id]
        current = _as_utc(chunk.read_at) if chunk.read_at is not None else None
        if current is None or requested < current:
            rows.append({"id": chunk.id, "read_at": requested})
    if rows:
        session.execute(update(Chunk), rows)
        session.commit()
```
and in the endpoint: `_apply_read_times(session, article_id, _requested_read_times(payload, datetime.now(UTC)))`.

- [ ] **Step 4: Run** `uv run pytest tests/reader -q` → PASS.
- [ ] **Step 5: Commit** `feat(reader): client read timestamps with earliest-wins; expose extracted_at`

---

### Task 2: Server — client-keyed reading session upsert

**Files:**
- Modify: `models.py` (ReadingSession), `schemas.py`, `api.py:157-183`
- Create: `migrations/versions/<rev>_session_client_id.py` (`uv run alembic revision -m "session client id"` then fill in)
- Test: `tests/reader/test_sessions.py` (rewrite)

**Interfaces:**
- Produces: `PUT /api/sessions/{client_id: UUID}` body `SessionUpsert { article_id: int, started_at: datetime, active_seconds: int }` → `SessionState { client_id: str, active_seconds: int }`. Removes `POST /articles/{id}/sessions` and `POST /sessions/{id}`.

- [ ] **Step 1: Rewrite `tests/reader/test_sessions.py`**

```python
from datetime import UTC, datetime

from nanonerd.reader.models import Article, ReadingSession
from tests.reader.webapp import create_test_client

CLIENT_ID = "0b6a9a1e-4d8e-4a8a-9e0e-1c2d3e4f5a6b"


def seed_article(factory, url="https://example.com/a"):
    with factory() as session:
        article = Article(url=url, title="A", status="ready", word_count=100)
        session.add(article)
        session.commit()
        return article.id


def upsert(client, article_id, seconds, started_at="2026-01-02T03:04:05Z"):
    return client.put(
        f"/api/sessions/{CLIENT_ID}",
        json={"article_id": article_id, "started_at": started_at, "active_seconds": seconds},
    )


def _session_rows(factory):
    with factory() as session:
        return [
            (row.client_id, row.article_id, row.active_seconds, row.started_at.replace(tzinfo=UTC))
            for row in session.query(ReadingSession).all()
        ]


def test_upsert_session_creates_row_with_client_fields(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)

    output = upsert(client, article_id, 12).json()

    assert (output, _session_rows(factory)) == (
        {"client_id": CLIENT_ID, "active_seconds": 12},
        [(CLIENT_ID, article_id, 12, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))],
    )


def test_upsert_session_is_monotonic_max(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)

    first = upsert(client, article_id, 40).json()
    second = upsert(client, article_id, 25).json()

    assert (first["active_seconds"], second["active_seconds"], len(_session_rows(factory))) == (40, 40, 1)


def test_upsert_session_clamps_future_started_at(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)
    before = datetime.now(UTC)

    upsert(client, article_id, 1, started_at="2999-01-01T00:00:00Z")

    output = _session_rows(factory)[0][3]
    assert before <= output <= datetime.now(UTC)


def test_upsert_session_missing_article_returns_404(monkeypatch):
    client, _factory, _processed = create_test_client(monkeypatch)
    assert upsert(client, 999, 5).status_code == 404


def test_upsert_session_rejects_non_uuid(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)
    output = client.put(
        "/api/sessions/not-a-uuid",
        json={"article_id": article_id, "started_at": "2026-01-01T00:00:00Z", "active_seconds": 1},
    )
    assert output.status_code == 422


def test_old_session_endpoints_are_gone(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)
    output = (
        client.post(f"/api/articles/{article_id}/sessions").status_code,
        client.post("/api/sessions/1", json={"active_seconds": 1}).status_code,
    )
    assert output == (405, 405) or output == (404, 405) or output == (404, 404)
```
(Keep the last assertion simple: after removal FastAPI returns 405 for `POST /api/sessions/1` because `PUT` exists on a different path pattern? No — the path `/api/sessions/{client_id}` matches, so POST → 405; `/articles/{id}/sessions` → 404. Assert `== (404, 405)`.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**

`models.py`: add to `ReadingSession`
```python
    client_id: Mapped[str | None] = mapped_column(String(36), unique=True, default=None)
```
`schemas.py`: remove `SessionCreated`, `SessionUpdate`; add
```python
class SessionUpsert(BaseModel):
    article_id: int
    started_at: datetime
    active_seconds: int


class SessionState(BaseModel):
    client_id: str
    active_seconds: int
```
`api.py`: delete both old endpoints; add
```python
@router.put("/sessions/{client_id}", response_model=SessionState)
def upsert_reading_session(
    client_id: UUID, payload: SessionUpsert, session: SessionDep
) -> SessionState:
    now = datetime.now(UTC)
    key = str(client_id)
    reading = session.scalar(select(ReadingSession).where(ReadingSession.client_id == key))
    if reading is None:
        if session.get(Article, payload.article_id) is None:
            raise HTTPException(status_code=404, detail="article not found")
        reading = ReadingSession(
            client_id=key,
            article_id=payload.article_id,
            started_at=min(_as_utc(payload.started_at), now),
            last_active_at=now,
            active_seconds=max(0, payload.active_seconds),
        )
        session.add(reading)
    elif payload.active_seconds > reading.active_seconds:
        reading.active_seconds = payload.active_seconds
        reading.last_active_at = now
    session.commit()
    return SessionState(client_id=key, active_seconds=reading.active_seconds)
```
Migration (`upgrade`): `op.add_column('reading_sessions', sa.Column('client_id', sa.String(36), nullable=True))`; `op.create_index('ix_reading_sessions_client_id', 'reading_sessions', ['client_id'], unique=True)`. `downgrade` reverses.

- [ ] **Step 4: Run** `uv run pytest -q` → PASS. Run `uv run alembic upgrade head` against a scratch sqlite (`DATABASE_URL=sqlite:///$CLAUDE_JOB_DIR/tmp/mig.db`) to prove the migration applies.
- [ ] **Step 5: Lint/type/deadcode:** `uv run ruff check . && uv run ruff format . && uv run mypy --config-file mypy.ini . && uv run deadcode .`
- [ ] **Step 6: Commit** `feat(reader): client-keyed idempotent reading session upsert`

---

### Task 3: Web tooling — vitest, idb, fake-indexeddb, vite-plugin-pwa

**Files:** `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/src/main.tsx`

- [ ] **Step 1:** `cd web && npm i idb && npm i -D vitest fake-indexeddb vite-plugin-pwa`
- [ ] **Step 2:** `package.json` scripts: `"test": "vitest run"`, `"test:watch": "vitest"`. `tsconfig.json` `types`: `["vite/client", "vite-plugin-pwa/client"]`.
- [ ] **Step 3:** `vite.config.ts`:
```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: false, // keep public/manifest.webmanifest
      includeAssets: ["icon.svg"],
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [], // API data is owned by src/offline, not the SW
      },
    }),
  ],
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
```
(`test` key needs `/// <reference types="vitest/config" />` at top or `import { defineConfig } from "vitest/config"` — use the latter.)
- [ ] **Step 4:** `main.tsx`: add `import { registerSW } from "virtual:pwa-register"; registerSW({ immediate: true });` and `void navigator.storage?.persist?.();` guarded by `if ("storage" in navigator)`.
- [ ] **Step 5:** Smoke test file `src/offline/smoke.test.ts` with `expect(1).toBe(1)`; `npm test` passes; `npm run build` passes and emits `dist/sw.js`. Delete the smoke test in Task 4.
- [ ] **Step 6: Commit** `chore(web): vitest, idb, vite-plugin-pwa app-shell service worker`

---

### Task 4: `types.ts`, `store.ts`, `MemoryStore`, `IdbStore` + shared contract test

**Files:** `web/src/offline/types.ts`, `store.ts`, `memoryStore.ts`, `idbStore.ts`, `store.contract.test.ts`

**Interfaces (Produces):**
```ts
// types.ts
export interface StoredArticle extends ArticleSummary { extracted_at: string | null }  // ArticleSummary from ../types (gains extracted_at there too)
export interface StoredBody { article_id: number; extracted_at: string | null; chunks: ChunkData[] }
export interface ReadMark { chunk_id: number; article_id: number; read_at: string; synced: boolean }
export interface LocalSession { client_id: string; article_id: number; started_at: string; active_seconds: number; synced_seconds: number }
export interface SyncStatus { online: boolean; syncing: boolean; unsynced: number; lastError: string | null }

// store.ts
export interface LocalStore {
  replaceArticles(articles: StoredArticle[]): Promise<void>; // full list; deletes articles (and their bodies/marks) not present
  listArticles(): Promise<StoredArticle[]>;                 // ordered: priority desc, added_at desc
  getArticle(id: number): Promise<StoredArticle | undefined>;
  putBody(body: StoredBody): Promise<void>;
  getBody(articleId: number): Promise<StoredBody | undefined>;
  listBodyVersions(): Promise<Array<{ article_id: number; extracted_at: string | null }>>;
  deleteBody(articleId: number): Promise<void>;
  addMarks(marks: ReadMark[]): Promise<void>;               // existing chunk_id → keep existing (earliest read wins)
  marksForArticle(articleId: number): Promise<ReadMark[]>;
  unsyncedMarks(): Promise<ReadMark[]>;
  markMarksSynced(chunkIds: number[]): Promise<void>;
  deleteMarksForArticle(articleId: number): Promise<void>;
  upsertSession(session: LocalSession): Promise<void>;      // active_seconds = max, synced_seconds = max
  unsyncedSessions(): Promise<LocalSession[]>;              // active_seconds > synced_seconds
  markSessionSynced(clientId: string, seconds: number): Promise<void>; // synced_seconds = max(existing, seconds)
}
```

- [ ] **Step 1: Contract test** `store.contract.test.ts` exporting `describeStoreContract(name, makeStore: () => Promise<LocalStore>)` with cases: replaceArticles prunes removed article + its body + marks; listArticles ordering; putBody/getBody roundtrip; listBodyVersions; addMarks keeps earliest on duplicate chunk_id; unsyncedMarks / markMarksSynced; deleteMarksForArticle; upsertSession max semantics; unsyncedSessions; markSessionSynced. Each case: input → act → expected → single assert (AGENTS.md style). Two spec files call it: `memoryStore.test.ts` and `idbStore.test.ts` (the latter does `import "fake-indexeddb/auto"` and opens a uniquely named DB per test via `new IdbStore(\`t-${counter++}\`)`).
- [ ] **Step 2: Run** → FAIL (modules missing).
- [ ] **Step 3: Implement `MemoryStore`** with `Map`s; **`IdbStore`** with `idb` `openDB(name, 1, { upgrade })` creating stores `articles` (key `id`), `bodies` (key `article_id`), `marks` (key `chunk_id`, indexes `by_article`, `by_synced`), `sessions` (key `client_id`). Booleans aren't indexable as keys in IDB reliably across engines → store `synced` as `0|1` internally (`by_synced` index) and convert at the boundary.
- [ ] **Step 4: Run** `npm test` → PASS for both stores.
- [ ] **Step 5: Commit** `feat(web): LocalStore interface with IndexedDB and in-memory implementations`

---

### Task 5: `reading.ts` + `repository.ts` (what pages render)

**Files:** `web/src/offline/reading.ts`, `repository.ts`, `reading.test.ts`, `repository.test.ts`; modify `web/src/types.ts` (`ArticleSummary.extracted_at: string | null`)

**Interfaces (Produces):**
```ts
// reading.ts
export function readIdsFor(body: StoredBody | undefined, marks: ReadMark[]): Set<number>;
export function percentFor(article: StoredArticle, body: StoredBody | undefined, marks: ReadMark[]): number;
//  - no body → article.percent_read (server's number)
//  - body → 100 * sum(word_count of chunks read-by-server ∪ marks) / sum(word_count), 0 if total 0, rounded to 1 decimal
// repository.ts
export async function loadArticleList(store: LocalStore): Promise<ArticleSummary[]>;  // percent_read overlaid
export async function loadArticle(store: LocalStore, id: number): Promise<ArticleDetail | undefined>; // undefined if no body cached; chunks[].read = server ∪ marks
```

- [ ] **Step 1: Tests** — `reading.test.ts`: table cases for percentFor (no body; server flags only; marks only; union; zero total). `repository.test.ts` with `MemoryStore`: list overlays percent from marks; article undefined without body; article merges read flags.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(web): local read-state overlay and page repository`

---

### Task 6: `transport.ts` — `SyncApi`, `SyncError`, `HttpSyncApi`

**Files:** `web/src/offline/transport.ts`, `transport.test.ts`; modify `web/src/api.ts` (remove `markProgress`, `beaconProgress`; keep `retryArticle`, `getStats`; `listArticles`/`getArticle` move into `HttpSyncApi` — keep thin re-exports only if still used).

**Interfaces (Produces):**
```ts
export class SyncError extends Error { constructor(public kind: "network" | "http", public status: number | null) ; get retryable(): boolean /* network or status >= 500 */ }
export interface SyncApi {
  fetchArticles(): Promise<ArticleSummary[]>;
  fetchArticle(id: number): Promise<ArticleDetail>;
  postMarks(articleId: number, marks: Array<{ chunk_id: number; read_at: string }>, opts?: { keepalive?: boolean }): Promise<void>;
  putSession(session: { client_id: string; article_id: number; started_at: string; active_seconds: number }, opts?: { keepalive?: boolean }): Promise<void>;
}
export class HttpSyncApi implements SyncApi { constructor(fetchFn: typeof fetch = fetch) }
```

- [ ] **Step 1: Tests** with an injected fake `fetch`: postMarks sends `PUT`/`POST` to the right URL with the right JSON and `keepalive`; non-ok → `SyncError("http", status)`; thrown fetch → `SyncError("network", null)`; `retryable` truth table (network → true, 503 → true, 404 → false).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(web): SyncApi transport with typed retryable errors`

---

### Task 7: `syncer.ts` — push outbox, pull list, prefetch bodies

**Files:** `web/src/offline/syncer.ts`, `syncer.test.ts`

**Interfaces (Produces):**
```ts
export interface SyncOptions { keepalive?: boolean }
export interface SyncResult { pushedMarks: number; pushedSessions: number; refreshed: boolean; prefetched: number; error: SyncError | null }
export class Syncer {
  constructor(store: LocalStore, api: SyncApi, opts?: { prefetchConcurrency?: number })
  pushMarks(opts?: SyncOptions): Promise<number>;      // groups unsynced marks by article; success → markMarksSynced; 4xx → deleteMarksForArticle (terminal); retryable error → rethrow
  pushSessions(opts?: SyncOptions): Promise<number>;   // unsynced sessions → putSession; success → markSessionSynced(active_seconds); 4xx → markSessionSynced (drop); retryable → rethrow
  refreshArticles(): Promise<void>;                    // fetchArticles → replaceArticles
  prefetchBodies(): Promise<number>;                   // fetch bodies that are missing, whose extracted_at differs (also deleteMarksForArticle for those), or whose server percent_read > local percentFor + 0.05; concurrency-limited
  syncAll(opts?: SyncOptions): Promise<SyncResult>;    // pushMarks → pushSessions → refreshArticles → prefetchBodies; stops at first retryable error and reports it
  pendingCount(): Promise<number>;                     // unsyncedMarks.length + unsyncedSessions.length
}
```

- [ ] **Step 1: Tests** (MemoryStore + a `FakeSyncApi` recording calls, scriptable to throw): pushMarks groups per article and marks synced; pushMarks on 404 drops that article's marks and continues with others; pushMarks on network error leaves marks unsynced and throws; pushSessions sends max and marks synced; refreshArticles replaces list; prefetchBodies fetches missing only; refetches when extracted_at changed and drops stale marks; refetches when server percent ahead of local; respects concurrency (count max in-flight via fake that resolves on demand); syncAll order and early stop on network error (no refresh after failed push); syncAll with keepalive passes option through.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(web): Syncer — idempotent outbox push, list pull, body prefetch`

---

### Task 8: `scheduler.ts` — when to sync, backoff, status

**Files:** `web/src/offline/scheduler.ts`, `scheduler.test.ts`

**Interfaces (Produces):**
```ts
export interface SchedulerEnv {
  isOnline(): boolean;                                    // navigator.onLine hint
  addEventListener(type: "online" | "offline" | "visibilitychange" | "pagehide", handler: () => void): () => void; // returns unsubscribe
  isVisible(): boolean;
  setTimeout: (fn: () => void, ms: number) => unknown; clearTimeout: (handle: unknown) => void;
}
export class SyncScheduler {
  constructor(syncer: Syncer, env: SchedulerEnv, opts?: { intervalMs?: number /*5000*/; maxBackoffMs?: number /*60000*/ })
  start(): void; stop(): void;
  requestSync(): void;         // coalesced: at most one sync in flight; another queued if requested during one
  subscribe(cb: (status: SyncStatus) => void): () => void;  // called immediately with current status and after every change
  getStatus(): SyncStatus;
}
```
Behavior: on `start` → sync; `online` event → sync (reset backoff); `visibilitychange` → visible: sync; hidden/`pagehide`: `syncer.syncAll({ keepalive: true })`; interval tick while visible and online → sync if `pendingCount() > 0`; retryable failure → exponential backoff (1s, 2s, …, cap) before the next automatic attempt, `status.online=false`, `lastError` set; success → `online=true`, backoff reset; `unsynced` refreshed from `pendingCount()` after each attempt and on `requestSync()`.

- [ ] **Step 1: Tests** with `vi.useFakeTimers()` and a hand-rolled `FakeEnv` (event map + online flag) and a `FakeSyncer` (scriptable results): start triggers one sync; requestSync during in-flight coalesces into exactly one follow-up; online event triggers sync; hidden triggers keepalive sync; interval skips when pendingCount is 0; backoff doubles and caps; subscribe gets immediate status and updates.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(web): SyncScheduler with coalescing, backoff, and status`

---

### Task 9: Composition root + hooks rewired + pages

**Files:** `web/src/offline/index.ts`, `useSyncStatus.ts`; modify `web/src/reader/useReadTracking.ts`, `useReadingSession.ts`, `web/src/pages/Home.tsx`, `Reader.tsx`, `Stats.tsx`, `web/src/api.ts`, `styles.css`

- [ ] **Step 1: `index.ts`**
```ts
export function createOffline(): { store: LocalStore; syncer: Syncer; scheduler: SyncScheduler }  // IdbStore if indexedDB exists else MemoryStore; HttpSyncApi; browserEnv()
export const offline = createOffline();   // singleton used by hooks/pages
export function browserEnv(): SchedulerEnv  // wraps window/document/navigator
```
- [ ] **Step 2: `useReadTracking(articleId, article, onRead: (chunkIds: number[]) => void): Set<number>`** — drop `pending`, `requeue`, `flush`, beacon, timer; `markRead` calls `onRead([chunkId])`. Initial `alreadyRead` comes from `article.chunks[].read` (repository already merged marks). Keep observer/dwell/at-bottom logic unchanged.
- [ ] **Step 3: `useReadingSession(articleId, ready, onTick: (s: { client_id, article_id, started_at, active_seconds }) => void)`** — mint `client_id = crypto.randomUUID()` and `started_at` lazily on the first tick with `seconds > 0`; call `onTick` each tick when seconds increased; `visibilitychange hidden`/`pagehide` → accumulate + onTick. No fetch.
- [ ] **Step 4: Reader.tsx** — load via `loadArticle(offline.store, id)`; if undefined: `await offline.syncer.syncAll()` then retry once; still undefined → "Not available offline yet." `onRead` → `offline.store.addMarks(...)` then `offline.scheduler.requestSync()`. `onTick` → `offline.store.upsertSession({...s, synced_seconds: 0})` then `requestSync()`.
- [ ] **Step 5: Home.tsx** — `loadArticleList(offline.store)` on mount and on every scheduler status change (subscribe); keep the 3 s pending refresh but call `offline.scheduler.requestSync()` only while `status.online`; render `<SyncChip />` in the nav: `offline` when `!online`, `n unsynced` when `unsynced > 0`, nothing otherwise. `retryArticle` unchanged (network-only action).
- [ ] **Step 6: Stats.tsx** — on fetch failure show `<p className="empty">Stats need a connection.</p>`.
- [ ] **Step 7: `api.ts`** — keep `retryArticle`, `getStats`; delete `markProgress`, `beaconProgress`, `listArticles`, `getArticle` (now in `HttpSyncApi`). `types.ts` `ArticleSummary.extracted_at: string | null`.
- [ ] **Step 8: `styles.css`** — `.sync-chip { font-size: .8rem; color: var(--muted); }` `.sync-chip.offline { color: #b3261e; }`
- [ ] **Step 9:** `npm run build && npm test` PASS. Manual smoke: `uv run uvicorn nanonerd.reader.main:app` + `npm run dev`, open an article, toggle DevTools offline, read, go online, confirm `PUT /api/sessions/...` and `POST .../progress` with `marks` fire and the chip clears.
- [ ] **Step 10: Commit** `feat(web): offline reading with local-first tracking and background sync`

---

### Task 10: Docs + final verification

- [ ] `docs/reader-deploy.md`: note that `alembic upgrade head` adds `reading_sessions.client_id`; README/spec status line → Implemented.
- [ ] Run the full gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy --config-file mypy.ini . && uv run deadcode . && uv run pytest -q && (cd web && npm run build && npm test)`.
- [ ] Commit `docs(reader): offline support shipped`; push branch.
