# Deploying the reader (Neon + Fly.io)

Not automated — run these once, from the repo root, using the same Fly
account as transactoid (`fly auth whoami` to check).

## 1. Neon database

1. https://console.neon.tech → New Project (name: `nanonerd-reader`,
   Postgres 16+, region near your Fly region).
2. Copy the connection string (the pooled one is fine), e.g.
   `postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require`.

## 2. Fly app

```bash
fly apps create nanonerd-reader          # name must match fly.toml
fly secrets set -a nanonerd-reader \
  DATABASE_URL='postgresql://…sslmode=require' \
  ANTHROPIC_API_KEY='sk-ant-…'
fly deploy
```

The container runs `alembic upgrade head` on boot, so the schema is created
on first deploy.

### Rendering and memory

Articles are rendered in headless Chromium (Playwright) before extraction, so
the image is built from `mcr.microsoft.com/playwright/python` (≈2 GB) and
`fly.toml` asks for `memory = "1gb"` — the 256 MB default for `shared-cpu-1x`
is not enough to launch Chromium on image-heavy pages. Set
`NANONERD_RENDERER=httpx` to fall back to a plain fetch + trafilatura
(no JavaScript, no Defuddle) on a box without Chromium.

### Cached images (Tigris)

Article images are re-hosted so the reader never hotlinks. Without any
configuration they land on the machine's disk under `./media` and are served
from `/media/...` — fine for local dev, but Fly machines have ephemeral disks,
so for production create a public Tigris bucket:

```bash
fly storage create -a nanonerd-reader --name nanonerd-reader-media --public
```

That injects `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_ENDPOINT_URL_S3` and `BUCKET_NAME` as secrets, which is all the app
needs; objects are then served from `https://<bucket>.fly.storage.tigris.dev`.
Override with `MEDIA_S3_BUCKET`, `MEDIA_S3_ENDPOINT` and
`MEDIA_PUBLIC_BASE_URL` for any other S3-compatible store.

## 3. Wire up the save surfaces

Open `https://nanonerd-reader.fly.dev/setup` and re-grab the bookmarklet and
re-point the iOS Shortcut — both bake in the origin they're loaded from, so
the local ones point at localhost.
