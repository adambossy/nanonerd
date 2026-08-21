from datetime import UTC, datetime

from sqlalchemy import select

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
        json={
            "article_id": article_id,
            "started_at": started_at,
            "active_seconds": seconds,
        },
    )


def _session_rows(factory):
    with factory() as session:
        return [
            (
                row.client_id,
                row.article_id,
                row.active_seconds,
                row.started_at.replace(tzinfo=UTC),
            )
            for row in session.scalars(select(ReadingSession)).all()
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

    output = (
        first["active_seconds"],
        second["active_seconds"],
        len(_session_rows(factory)),
    )
    assert output == (40, 40, 1)


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
        json={
            "article_id": article_id,
            "started_at": "2026-01-01T00:00:00Z",
            "active_seconds": 1,
        },
    )

    assert output.status_code == 422


def test_old_session_endpoints_are_gone(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)

    output = (
        client.post(f"/api/articles/{article_id}/sessions").status_code,
        client.post("/api/sessions/1", json={"active_seconds": 1}).status_code,
    )

    assert output == (404, 405)
