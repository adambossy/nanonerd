from nanonerd.reader.models import Article
from tests.reader.webapp import create_test_client


def seed_article(factory, url="https://example.com/a"):
    with factory() as session:
        article = Article(url=url, title="A", status="ready", word_count=100)
        session.add(article)
        session.commit()
        return article.id


def test_create_session_returns_id(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)

    output = client.post(f"/api/articles/{article_id}/sessions")

    assert (output.status_code, output.json()["id"] > 0) == (200, True)


def test_create_session_missing_article_returns_404(monkeypatch):
    client, _factory, _processed = create_test_client(monkeypatch)
    assert client.post("/api/articles/999/sessions").status_code == 404


def test_update_session_is_monotonic(monkeypatch):
    client, factory, _processed = create_test_client(monkeypatch)
    article_id = seed_article(factory)
    session_id = client.post(f"/api/articles/{article_id}/sessions").json()["id"]

    first = client.post(
        f"/api/sessions/{session_id}", json={"active_seconds": 40}
    ).json()
    second = client.post(
        f"/api/sessions/{session_id}", json={"active_seconds": 25}
    ).json()

    assert (first["active_seconds"], second["active_seconds"]) == (40, 40)


def test_update_session_missing_returns_404(monkeypatch):
    client, _factory, _processed = create_test_client(monkeypatch)
    output = client.post("/api/sessions/999", json={"active_seconds": 5})
    assert output.status_code == 404
