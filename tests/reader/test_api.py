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


def seed_degraded_article(factory):
    with factory() as session:
        article = Article(
            url="https://example.com/degraded",
            title="Degraded Article",
            status="ready",
            word_count=100,
            chunks=[Chunk(position=0, html="<p>a</p>", word_count=100)],
            fidelity_status="degraded",
            fidelity_score=0.37,
            fidelity_reasons='["18 figures and their captions are missing"]',
        )
        session.add(article)
        session.commit()
        return article.id


def test_list_articles_exposes_fidelity_annotations(monkeypatch):
    # input
    client, factory, _processed = create_test_client(monkeypatch)
    seed_degraded_article(factory)

    # act
    entry = client.get("/api/articles").json()[0]

    # expected
    expected_output = {
        "fidelity_status": "degraded",
        "fidelity_score": 0.37,
        "fidelity_reasons": ["18 figures and their captions are missing"],
    }

    # assert
    assert {key: entry[key] for key in expected_output} == expected_output


def test_get_article_detail_defaults_fidelity_to_empty(monkeypatch):
    # input
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, _chunk_ids = seed_ready_article(factory)

    # act
    output = client.get(f"/api/articles/{article_id}").json()

    # expected
    expected_output: dict[str, object] = {
        "fidelity_status": None,
        "fidelity_score": None,
        "fidelity_reasons": [],
    }

    # assert
    assert {key: output[key] for key in expected_output} == expected_output


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
        json={
            "chunk_ids": [999999],
            "marks": [{"chunk_id": 999998, "read_at": "2026-01-01T00:00:00Z"}],
        },
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
