import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nanonerd.reader import pipeline
from nanonerd.reader.extract import Extraction, FetchError, NotArticleError
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


def test_process_article_records_fidelity_verdict(monkeypatch):
    # input
    source_html = "<html><body><article>" + CONTENT_HTML + "</article></body></html>"

    # helper setup
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    monkeypatch.setattr(pipeline, "fetch_html", lambda url: source_html)
    monkeypatch.setattr(
        pipeline,
        "extract_article",
        lambda html, url: Extraction(
            title="Nice Title", author=None, site_name=None, content_html=CONTENT_HTML
        ),
    )
    monkeypatch.setattr(pipeline, "assign_categories", lambda title, text, existing: [])

    # act
    pipeline.process_article(article_id, session_factory=factory)
    output = fetch_fidelity(factory, article_id)

    # expected
    expected_output = {
        "status": "ready",
        "fidelity_status": "ok",
        "reasons": [],
        "checked": True,
    }

    # assert
    assert output == expected_output


def test_process_article_records_blocked_fidelity_on_bot_wall(monkeypatch):
    # input
    bot_wall_html = (
        "<html><body><p>Please enable JS and disable any ad blocker</p>"
        "<script>var dd={'host':'geo.captcha-delivery.com'}</script></body></html>"
    )

    # helper setup
    factory = create_session_factory()
    article_id = create_pending_article(factory)

    def blocked(url):
        raise FetchError("HTTP 403", status_code=403, body=bot_wall_html)

    monkeypatch.setattr(pipeline, "fetch_html", blocked)

    # act
    pipeline.process_article(article_id, session_factory=factory)
    output = fetch_fidelity(factory, article_id)

    # expected
    expected_output = {
        "status": "failed",
        "fidelity_status": "blocked",
        "reasons": ["fetch returned HTTP 403 — the page was not served"],
        "checked": True,
    }

    # assert
    assert output == expected_output


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


def test_process_article_not_an_article_marks_failed_with_reason(monkeypatch):
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    monkeypatch.setattr(pipeline, "fetch_html", lambda url: "<html>raw</html>")

    def reject(html, url):
        raise NotArticleError("not an article: og:type is product.group")

    monkeypatch.setattr(pipeline, "extract_article", reject)

    pipeline.process_article(article_id, session_factory=factory)

    output = fetch_article(factory, article_id)
    expected_output = {
        "status": "failed",
        "error": "not an article: og:type is product.group",
        "chunk_words": [],
    }
    assert {key: output[key] for key in expected_output} == expected_output


def test_process_article_not_an_article_records_not_article_fidelity(monkeypatch):
    # input
    source_html = (
        "<html><head><meta property='og:type' content='product.group'></head>"
        "<body><div class='grid'>"
        + "".join(f"<a href='/p/{i}'>Product {i} $99</a>" for i in range(60))
        + "</div></body></html>"
    )

    # helper setup
    factory = create_session_factory()
    article_id = create_pending_article(factory)
    monkeypatch.setattr(pipeline, "fetch_html", lambda url: source_html)

    def reject(html, url):
        raise NotArticleError("not an article: og:type is product.group")

    monkeypatch.setattr(pipeline, "extract_article", reject)

    # act
    pipeline.process_article(article_id, session_factory=factory)
    output = fetch_fidelity(factory, article_id)

    # expected
    expected_output = {
        "status": "failed",
        "fidelity_status": "not_article",
        "reasons": ["page is not an article (og:type=product.group)"],
        "checked": True,
    }

    # assert
    assert output == expected_output


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


def test_process_article_reuses_categories_case_insensitive(monkeypatch):
    factory = create_session_factory()

    # Seed existing category
    with factory() as session:
        session.add(Category(name="Transit"))
        session.commit()

    article_id = create_pending_article(factory)
    monkeypatch.setattr(pipeline, "fetch_html", lambda url: "<html>raw</html>")
    monkeypatch.setattr(
        pipeline,
        "extract_article",
        lambda html, url: Extraction(
            title="Title", author=None, site_name=None, content_html=CONTENT_HTML
        ),
    )
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
