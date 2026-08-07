---
name: reading-digest
description: Analyze nano::nerd reading behavior and produce 3-5 recommendations on what to dig into next. Use when the user asks for a reading digest, what to read next, or what their reading stats say about them.
---

# Reading Digest

Turn the reader's stats into a short, honest digest of how the user actually
reads, ending with 3-5 concrete recommendations. You are describing their
behavior to them — be direct, specific, and numeric; never moralize.

## 1. Get the data

Prefer the running app:

```bash
curl -s http://localhost:8000/api/stats
```

If that fails (server not running), compute the same aggregates directly
from the database (run from the repo root; respects DATABASE_URL, defaults
to the local sqlite file):

```bash
uv run python - <<'EOF'
import json
from sqlalchemy import func, select
from nanonerd.reader.db import SessionLocal
from nanonerd.reader.models import Article, Chunk, ReadingSession

with SessionLocal() as s:
    articles = s.scalars(select(Article)).all()
    read_words = dict(
        s.execute(
            select(Chunk.article_id, func.sum(Chunk.word_count))
            .where(Chunk.read_at.is_not(None))
            .group_by(Chunk.article_id)
        ).all()
    )
    secs = dict(
        s.execute(
            select(ReadingSession.article_id, func.sum(ReadingSession.active_seconds))
            .group_by(ReadingSession.article_id)
        ).all()
    )
    rows = []
    for a in articles:
        pct = round(100 * read_words.get(a.id, 0) / a.word_count, 1) if a.word_count else 0.0
        rows.append({
            "id": a.id, "title": a.title, "status": a.status,
            "categories": [c.name for c in a.categories] or ["(uncategorized)"],
            "word_count": a.word_count, "percent_read": pct,
            "active_seconds": int(secs.get(a.id, 0)),
            "added_at": a.added_at.isoformat(),
        })
    print(json.dumps(rows, indent=2))
EOF
```

Also fetch the article list (`curl -s http://localhost:8000/api/articles`)
when the server is up — per-article percent_read plus categories is the
raw material for recommendations.

## 2. Analyze

Look for, with numbers attached:

- **Gravitation** — topics with the most active time and highest
  read-through. What does the user actually finish?
- **Neglect** — topics saved repeatedly but barely read (low read-through,
  ~zero time). Frame each as an open question, never a verdict: "you've
  saved N of these and read none — should this surface more, or do you
  actually not care?"
- **Momentum** — articles substantially started (say 40-90% read): cheap
  wins to finish.
- **Staleness** — old unread saves (compare added_at to today).

Ignore days-with-zero-reading noise; small personal datasets are spiky.

## 3. Output

A digest of at most ~150 words (what the numbers say about how they read),
then **3 to 5 numbered recommendations on what to dig into next**. Each
recommendation names a specific article or topic and cites its evidence,
e.g.:

1. Finish "<title>" — you're 72% through and it's in your top topic.
2. Security: saved 5, read 0. Read one this week, or consciously drop the
   bucket — either answer beats letting it rot.
3. You finish everything under 1,500 words — queue up two short saves.

If there are no reading sessions yet, say so and recommend starting with
the most recently saved articles instead of inventing patterns.
