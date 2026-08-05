from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nanonerd.reader import pipeline
from nanonerd.reader.extract import Extraction
from nanonerd.reader.models import Article, Base

CONTENT_HTML = (
    "<p>" + " ".join(f"alpha{i}" for i in range(180)) + "</p>"
    "<p>" + " ".join(f"beta{i}" for i in range(180)) + "</p>"
)


def create_session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_pending_article(factory, url="https://example.com/a"):
    with factory() as session:
        article = Article(url=url, title=url, status="pending")
        session.add(article)
        session.commit()
        return article.id


def fetch_article(factory, article_id):
    with factory() as session:
        article = session.scalars(select(Article).where(Article.id == article_id)).one()
        return {
            "status": article.status,
            "title": article.title,
            "error": article.error,
            "word_count": article.word_count,
            "chunk_words": [c.word_count for c in article.chunks],
            "categories": sorted(c.name for c in article.categories),
        }


def test_process_article_success(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    monkeypatch.setattr(pipeline, "fetch_html", lambda url: "<html>raw</html>")
    monkeypatch.setattr(
        pipeline,
        "extract_article",
        lambda html, url: Extraction(
            title="Nice Title",
            author="Ann",
            site_name="Site",
            content_html=CONTENT_HTML,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "assign_categories",
        lambda title, text, existing: ["Transit", "Parks"],
    )

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    expected_output = {
        "status": "ready",
        "title": "Nice Title",
        "error": None,
        "word_count": 360,
        "chunk_words": [180, 180],
        "categories": ["Parks", "Transit"],
    }
    assert output == expected_output


def test_process_article_fetch_failure_marks_failed(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)

    def boom(url):
        raise ValueError("connection refused")

    monkeypatch.setattr(pipeline, "fetch_html", boom)

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    assert output["status"] == "failed"
    assert "connection refused" in output["error"]


def test_process_article_categorization_failure_is_nonfatal(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    monkeypatch.setattr(pipeline, "fetch_html", lambda url: "<html>raw</html>")
    monkeypatch.setattr(
        pipeline,
        "extract_article",
        lambda html, url: Extraction(
            title="T", author=None, site_name=None, content_html=CONTENT_HTML
        ),
    )

    def no_api(title, text, existing):
        raise RuntimeError("no api key")

    monkeypatch.setattr(pipeline, "assign_categories", no_api)

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    assert (output["status"], output["categories"]) == ("ready", [])
