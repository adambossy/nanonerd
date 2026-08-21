from nanonerd.reader.models import Article, ArticleSnapshot, Chunk
from tests.reader.webapp import create_test_client


def seed_article(factory, with_snapshot=False):
    with factory() as session:
        article = Article(
            url="https://example.com/a",
            title="Ready Article",
            status="ready",
            word_count=3,
            chunks=[Chunk(position=0, html="<p>a b c</p>", word_count=3)],
        )
        if with_snapshot:
            article.snapshot = ArticleSnapshot(
                html='<html><body><p data-chunk-index="0">a b c</p></body></html>',
            )
            article.snapshot_status = "ready"
            article.snapshot_available = True
            article.snapshot_bytes = 60
        session.add(article)
        session.commit()
        return article.id


def test_get_article_exposes_snapshot_state(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)

    output = client.get(f"/api/articles/{article_id}").json()["snapshot"]

    expected_output = {
        "status": "none",
        "available": False,
        "bytes": 0,
        "captured_at": None,
        "error": None,
    }
    assert output == expected_output


def test_list_articles_exposes_snapshot_state(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    seed_article(factory, with_snapshot=True)

    output = client.get("/api/articles").json()[0]["snapshot"]

    expected_output = {
        "status": "ready",
        "available": True,
        "bytes": 60,
        "captured_at": None,
        "error": None,
    }
    assert output == expected_output


def test_request_snapshot_marks_pending_and_queues_capture(monkeypatch):
    client, factory, processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)

    response = client.post(f"/api/articles/{article_id}/snapshot")

    output = (response.status_code, response.json()["status"], processed)
    assert output == (200, "pending", [("snapshot", article_id)])


def test_request_snapshot_rejects_when_already_pending(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)
    client.post(f"/api/articles/{article_id}/snapshot")

    output = client.post(f"/api/articles/{article_id}/snapshot").status_code

    assert output == 409


def test_get_snapshot_serves_html_with_strict_headers(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory, with_snapshot=True)

    response = client.get(f"/api/articles/{article_id}/snapshot")

    output = (
        response.status_code,
        response.headers["content-type"].split(";")[0],
        response.headers["x-content-type-options"],
        "sandbox" in response.headers["content-security-policy"],
        'data-chunk-index="0"' in response.text,
    )
    assert output == (200, "text/html", "nosniff", True, True)


def test_get_snapshot_404_when_missing(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)

    output = client.get(f"/api/articles/{article_id}/snapshot").status_code

    assert output == 404


def test_retry_article_discards_snapshot(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory, with_snapshot=True)
    with factory() as session:
        article = session.get(Article, article_id)
        article.status = "failed"
        session.commit()

    client.post(f"/api/articles/{article_id}/retry")

    detail = client.get(f"/api/articles/{article_id}").json()["snapshot"]
    snapshot_response = client.get(f"/api/articles/{article_id}/snapshot")
    assert (detail["status"], detail["available"], snapshot_response.status_code) == (
        "none",
        False,
        404,
    )
