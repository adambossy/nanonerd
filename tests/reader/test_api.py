from datetime import UTC, datetime

from nanonerd.reader.models import Article, Category, Chunk
from tests.reader.webapp import create_test_client


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


def test_archive_article_hides_it_from_list(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, _chunk_ids = seed_ready_article(factory)

    response = client.post(f"/api/articles/{article_id}/archive")

    assert response.status_code == 204
    assert client.get("/api/articles").json() == []
    assert client.get(f"/api/articles/{article_id}").status_code == 200


def test_delete_article_removes_it(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id, _chunk_ids = seed_ready_article(factory)

    response = client.delete(f"/api/articles/{article_id}")

    assert response.status_code == 204
    assert client.get("/api/articles").json() == []
    assert client.get(f"/api/articles/{article_id}").status_code == 404
