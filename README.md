# nanonerd

A collection of personal tools. Current tool: **reader** — a read-later app
with chunked reading-progress tracking and AI-assigned categories.

## Reader: local development

Backend (terminal 1):

```bash
uv sync
uv run uvicorn nanonerd.reader.main:app --reload --port 8000
```

Frontend (terminal 2):

```bash
cd web
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend.

Environment variables (all optional locally):

- `DATABASE_URL` — Postgres/Neon URL; defaults to `sqlite:///./reader.db`
- `ANTHROPIC_API_KEY` — enables AI categorization (articles still save/read without it)

### Stats and digest

The app tracks active reading time (tab visible + recent interaction) per
article. `/stats` shows totals, time by topic, saved-vs-read per topic, a
30-day sparkline, and top articles. For an interpreted digest with
recommendations on what to read next, run the `/reading-digest` skill in a
Claude Code session in this repo.

### Faithful mode (per-article snapshot)

The reader's `faithful` toggle shows an article looking like its source page
(fonts, colors, figures, rendered math) with our progress bar and gutter
marks overlaid. It needs a snapshot: `POST /api/articles/{id}/snapshot`
(or the "capture snapshot" link in the reader) renders the page with
headless Chromium at a phone viewport, inlines CSS/fonts/images, strips
scripts and chrome, tags the article's blocks and **rebuilds the article's
chunks from those blocks** (read state carries over by text match). The
snapshot is served from `GET /api/articles/{id}/snapshot` and mounted in a
shadow root. Local setup: `uv run playwright install chromium`.

Production build: `cd web && npm run build`, then the FastAPI app serves
`web/dist` at `/`. Deployment: see `docs/reader-deploy.md`.
