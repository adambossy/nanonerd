import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nanonerd.reader import pipeline
from nanonerd.reader.acquire import AcquiredArticle
from nanonerd.reader.errors import ExtractionError
from nanonerd.reader.extract import FetchError, NotArticleError
from nanonerd.reader.models import Article, Base, Category

CONTENT_HTML = (
    "<p>" + " ".join(f"alpha{i}" for i in range(180)) + "</p>"
    "<p>" + " ".join(f"beta{i}" for i in range(180)) + "</p>"
)
SOURCE_HTML = "<html><body><article>" + CONTENT_HTML + "</article></body></html>"


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


def fetch_fidelity(factory, article_id):
    with factory() as session:
        article = session.scalars(select(Article).where(Article.id == article_id)).one()
        return {
            "status": article.status,
            "fidelity_status": article.fidelity_status,
            "reasons": json.loads(article.fidelity_reasons or "[]"),
            "checked": article.fidelity_checked_at is not None,
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
        http_status=200,
        source_html=SOURCE_HTML,
    )


def patch_acquire(monkeypatch: pytest.MonkeyPatch, result: AcquiredArticle) -> None:
    monkeypatch.setattr(pipeline, "acquire_article", lambda url, *, article_id: result)


def patch_acquire_failure(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def boom(url, *, article_id):
        raise exc

    monkeypatch.setattr(pipeline, "acquire_article", boom)


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


def test_process_article_records_fidelity_verdict(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    patch_acquire(monkeypatch, acquired(author=None, site_name=None))
    monkeypatch.setattr(pipeline, "assign_categories", lambda title, text, existing: [])

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_fidelity(factory, article_id)
    expected_output = {
        "status": "ready",
        "fidelity_status": "ok",
        "reasons": [],
        "checked": True,
    }
    assert output == expected_output


def test_process_article_acquire_failure_marks_failed(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    patch_acquire_failure(monkeypatch, ExtractionError("connection refused"))

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    assert output["status"] == "failed"
    assert "connection refused" in output["error"]


def test_process_article_records_blocked_fidelity_on_bot_wall(monkeypatch):
    bot_wall_html = (
        "<html><body><p>Please enable JS and disable any ad blocker</p>"
        "<script>var dd={'host':'geo.captcha-delivery.com'}</script></body></html>"
    )
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    patch_acquire_failure(
        monkeypatch, FetchError("HTTP 403", status_code=403, body=bot_wall_html)
    )

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_fidelity(factory, article_id)
    expected_output = {
        "status": "failed",
        "fidelity_status": "blocked",
        "reasons": ["fetch returned HTTP 403 — the page was not served"],
        "checked": True,
    }
    assert output == expected_output


def test_process_article_not_an_article_marks_failed_with_reason(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    patch_acquire_failure(
        monkeypatch, NotArticleError("not an article: og:type is product.group")
    )

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    expected_output = {
        "status": "failed",
        "error": "not an article: og:type is product.group",
        "chunk_words": [],
    }
    assert {key: output[key] for key in expected_output} == expected_output


def test_process_article_not_an_article_records_not_article_fidelity(monkeypatch):
    source_html = (
        "<html><head><meta property='og:type' content='product.group'></head>"
        "<body><div class='grid'>"
        + "".join(f"<a href='/p/{i}'>Product {i} $99</a>" for i in range(60))
        + "</div></body></html>"
    )
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    patch_acquire_failure(
        monkeypatch,
        NotArticleError(
            "not an article: og:type is product.group",
            status_code=200,
            body=source_html,
        ),
    )

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_fidelity(factory, article_id)
    expected_output = {
        "status": "failed",
        "fidelity_status": "not_article",
        "reasons": ["page is not an article (og:type=product.group)"],
        "checked": True,
    }
    assert output == expected_output


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
