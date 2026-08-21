import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nanonerd.reader import pipeline
from nanonerd.reader.acquire import AcquiredArticle
from nanonerd.reader.errors import ExtractionError
from nanonerd.reader.models import Article, Base, Category

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
            "source_kind": article.source_kind,
            "source_url": article.source_url,
        }


def acquired(
    title: str | None = "Nice Title",
    author: str | None = "Ann",
    site_name: str | None = "Site",
    source_kind: str = "live",
) -> AcquiredArticle:
    return AcquiredArticle(
        title=title,
        author=author,
        site_name=site_name,
        content_html=CONTENT_HTML,
        source_kind=source_kind,
        source_url="https://example.com/a",
        images_cached=0,
    )


def patch_acquire(monkeypatch: pytest.MonkeyPatch, result: AcquiredArticle) -> None:
    monkeypatch.setattr(pipeline, "acquire_article", lambda url, *, article_id: result)


def test_process_article_success(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    patch_acquire(monkeypatch, acquired(source_kind="wayback"))
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
        "source_kind": "wayback",
        "source_url": "https://example.com/a",
    }
    assert output == expected_output


def test_process_article_acquire_failure_marks_failed(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)

    def boom(url, *, article_id):
        raise ExtractionError("connection refused")

    monkeypatch.setattr(pipeline, "acquire_article", boom)

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    assert output["status"] == "failed"
    assert "connection refused" in output["error"]


def test_process_article_categorization_failure_is_nonfatal(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    patch_acquire(monkeypatch, acquired(title="T", author=None, site_name=None))

    def no_api(title, text, existing):
        raise RuntimeError("no api key")

    monkeypatch.setattr(pipeline, "assign_categories", no_api)

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    assert (output["status"], output["categories"]) == ("ready", [])


def test_process_article_reuses_categories_case_insensitive(monkeypatch):
    factory = create_session_factory()

    # Seed existing category
    with factory() as session:
        session.add(Category(name="Transit"))
        session.commit()

    article_id = create_pending_article(factory)
    patch_acquire(monkeypatch, acquired(title="Title", author=None, site_name=None))
    # Return lowercase "transit" to test case-insensitive matching, plus new "Parks"
    monkeypatch.setattr(
        pipeline,
        "assign_categories",
        lambda title, text, existing: ["transit", "Parks"],
    )

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    # Should reuse existing "Transit" category, not create a duplicate "transit"
    assert output["categories"] == ["Parks", "Transit"]

    # Verify no duplicate category was created
    with factory() as session:
        category_count = session.query(Category).count()
    assert category_count == 2
