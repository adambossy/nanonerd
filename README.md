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

Production build: `cd web && npm run build`, then the FastAPI app serves
`web/dist` at `/`. Deployment: see `docs/reader-deploy.md`.
