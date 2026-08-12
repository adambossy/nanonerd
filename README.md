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

Production build: `cd web && npm run build`, then the FastAPI app serves
`web/dist` at `/`. Deployment: see `docs/reader-deploy.md`.
