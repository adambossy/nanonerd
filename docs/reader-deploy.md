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

### Faithful-mode snapshots (Chromium)

The image installs headless Chromium (`playwright install --with-deps
chromium`, ~400MB). Snapshot capture runs one page at a time inside the
uvicorn process; on a 256MB machine Chromium will be OOM-killed. Before
using the feature in production, bump the machine:

```bash
fly scale memory 1024 -a nanonerd-reader   # or uncomment memory = "1gb" in fly.toml
```

Snapshots are stored in Postgres (`article_snapshots`, ≤8MB each) — no
object storage to configure.

## 3. Wire up the save surfaces

Open `https://nanonerd-reader.fly.dev/setup` and re-grab the bookmarklet and
re-point the iOS Shortcut — both bake in the origin they're loaded from, so
the local ones point at localhost.
