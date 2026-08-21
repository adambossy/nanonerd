from datetime import UTC, datetime, timedelta

from nanonerd.reader.models import Article, Category, Chunk, ReadingSession
from tests.reader.webapp import create_test_client

EPOCH = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def seed_ready_article(factory):
    with factory() as session:
        article = Article(
            url="https://example.com/a",
            title="Ready Article",
            site_name="Example",
            status="ready",
            word_count=400,
            categories=[Category(name="Transit")],
            chunks=[
                Chunk(
                    position=0,
                    html="<p>a</p>",
                    word_count=100,
                    read_at=datetime.now(UTC),
                ),
                Chunk(position=1, html="<p>b</p>", word_count=300),
            ],
        )
        session.add(article)
        session.commit()
        return article.id, [c.id for c in article.chunks]


def seed_article(factory, url, chunks, *, title="A", word_count=100, status="ready"):
    with factory() as session:
        article = Article(
            url=url,
            title=title,
            status=status,
            word_count=word_count,
            chunks=chunks,
        )
        session.add(article)
        session.commit()
        return article.id


def seed_reading_session(factory, article_id, last_active_at):
    with factory() as session:
        session.add(
            ReadingSession(
                article_id=article_id,
                started_at=last_active_at,
                last_active_at=last_active_at,
            )
        )
        session.commit()


def test_save_article_creates_pending_and_queues_pipeline(monkeypatch):
    client, _factory, processed = create_test_client(monkeypatch)

    response = client.post(
        "/api/articles",
        json={"url": "https://example.com/a?utm_source=x", "title": "T"},
    )

    output = response.json()
    assert (output["duplicate"], output["status"]) == (False, "pending")
    assert processed == [output["id"]]


def test_save_article_dedupes_on_normalized_url(monkeypatch):
    client, _factory, _processed = create_test_client(monkeypatch)
    first = client.post(
        "/api/articles", json={"url": "https://example.com/a?utm_source=x"}
    ).json()

    output = client.post("/api/articles", json={"url": "https://example.com/a"}).json()

    assert (output["id"], output["duplicate"]) == (first["id"], True)


def test_list_articles_reports_percent_read(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    seed_ready_article(factory)

    output = client.get("/api/articles").json()

    assert len(output) == 1
    entry = output[0]
    assert (entry["percent_read"], entry["categories"]) == (25.0, ["Transit"])


def test_get_article_detail_includes_chunks(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, _chunk_ids = seed_ready_article(factory)

    output = client.get(f"/api/articles/{article_id}").json()

    assert [c["read"] for c in output["chunks"]] == [True, False]
    assert output["percent_read"] == 25.0


def test_get_article_missing_returns_404(monkeypatch):
    client, _factory, _processed = create_test_client(monkeypatch)
    response = client.get("/api/articles/999")
    assert response.status_code == 404


def test_mark_progress_sets_read_and_returns_percent(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, chunk_ids = seed_ready_article(factory)

    output = client.post(
        f"/api/articles/{article_id}/progress", json={"chunk_ids": [chunk_ids[1]]}
    ).json()

    assert output["percent_read"] == 100.0


def test_resume_returns_null_when_nothing_qualifies(monkeypatch):
    client, _factory, _processed = create_test_client(monkeypatch)

    response = client.get("/api/resume")

    assert (response.status_code, response.json()) == (200, None)


def test_resume_prefers_most_recent_reading_session(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    recent_chunks = seed_article(
        factory,
        "https://example.com/recent-chunks",
        [Chunk(position=0, html="<p>a</p>", word_count=40, read_at=EPOCH)],
    )
    recent_session = seed_article(
        factory,
        "https://example.com/recent-session",
        [
            Chunk(
                position=0,
                html="<p>b</p>",
                word_count=40,
                read_at=EPOCH - timedelta(hours=2),
            )
        ],
        title="Recent Session",
    )
    seed_reading_session(factory, recent_chunks, EPOCH - timedelta(hours=1))
    seed_reading_session(factory, recent_session, EPOCH + timedelta(hours=1))

    output = client.get("/api/resume").json()

    assert output == {"article_id": recent_session, "title": "Recent Session"}


def test_resume_falls_back_to_chunk_read_at_without_sessions(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    seed_article(
        factory,
        "https://example.com/older",
        [
            Chunk(
                position=0,
                html="<p>a</p>",
                word_count=40,
                read_at=EPOCH - timedelta(hours=3),
            )
        ],
    )
    newest = seed_article(
        factory,
        "https://example.com/newest",
        [Chunk(position=0, html="<p>b</p>", word_count=40, read_at=EPOCH)],
        title="Newest",
    )

    output = client.get("/api/resume").json()

    assert output == {"article_id": newest, "title": "Newest"}


def test_resume_skips_fully_read_articles(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    finished = seed_article(
        factory,
        "https://example.com/finished",
        [Chunk(position=0, html="<p>a</p>", word_count=100, read_at=EPOCH)],
    )
    unfinished = seed_article(
        factory,
        "https://example.com/unfinished",
        [Chunk(position=0, html="<p>b</p>", word_count=40, read_at=EPOCH)],
        title="Unfinished",
    )
    seed_reading_session(factory, finished, EPOCH + timedelta(hours=1))
    seed_reading_session(factory, unfinished, EPOCH)

    output = client.get("/api/resume").json()

    assert output == {"article_id": unfinished, "title": "Unfinished"}


def test_history_lists_read_chunks_newest_first(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    first = seed_article(
        factory,
        "https://example.com/first",
        [
            Chunk(
                position=0,
                html="<p>alpha <b>one</b></p>",
                word_count=10,
                read_at=EPOCH - timedelta(minutes=5),
            ),
            Chunk(position=1, html="<p>unread</p>", word_count=10),
        ],
        title="First",
    )
    second = seed_article(
        factory,
        "https://example.com/second",
        [Chunk(position=0, html="<p>beta</p>", word_count=20, read_at=EPOCH)],
        title="Second",
    )

    output = [
        (e["article_id"], e["article_title"], e["position"], e["snippet"])
        for e in client.get("/api/history").json()
    ]

    assert output == [
        (second, "Second", 0, "beta"),
        (first, "First", 0, "alpha one"),
    ]


def test_history_truncates_long_snippets(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    seed_article(
        factory,
        "https://example.com/long",
        [
            Chunk(
                position=0, html=f"<p>{'word ' * 60}</p>", word_count=60, read_at=EPOCH
            )
        ],
    )

    output = client.get("/api/history").json()

    assert output[0]["snippet"] == ("word " * 28).rstrip() + "…"


def test_retry_failed_article_requeues(monkeypatch):
    client, factory, processed = create_test_client(monkeypatch)
    with factory() as session:
        article = Article(
            url="https://example.com/broken", title="B", status="failed", error="boom"
        )
        session.add(article)
        session.commit()
        article_id = article.id

    output = client.post(f"/api/articles/{article_id}/retry").json()

    assert (output["status"], processed) == ("pending", [article_id])
