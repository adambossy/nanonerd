from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nanonerd.reader import pipeline
from nanonerd.reader.extract import Extraction, NotArticleError
from nanonerd.reader.models import Article, Base, Chunk
from nanonerd.reader.reprocess import reprocess_articles

NEW_CONTENT = "<p>" + " ".join(f"fresh{i}" for i in range(120)) + "</p>"


def create_session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_ready_article(factory, url):
    with factory() as session:
        article = Article(
            url=url,
            title="Old title",
            status="ready",
            word_count=3,
            chunks=[Chunk(position=0, html="<p>old stale</p>", word_count=3)],
        )
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
            "chunk_words": [c.word_count for c in article.chunks],
        }


def test_reprocess_articles_replaces_chunks_with_fresh_extraction(monkeypatch):
    factory = create_session_factory()
    article_id = create_ready_article(factory, "https://example.com/a")
    monkeypatch.setattr(pipeline, "fetch_html", lambda url: "<html>raw</html>")
    monkeypatch.setattr(
        pipeline,
        "extract_article",
        lambda html, url: Extraction(
            title="New title", author=None, site_name=None, content_html=NEW_CONTENT
        ),
    )
    monkeypatch.setattr(pipeline, "assign_categories", lambda *args: [])

    results = reprocess_articles([article_id], session_factory=factory)

    output = {
        "results": [(r.article_id, r.status, r.error) for r in results],
        "article": fetch_article(factory, article_id),
    }
    expected_output = {
        "results": [(article_id, "ready", None)],
        "article": {
            "status": "ready",
            "title": "New title",
            "error": None,
            "chunk_words": [120],
        },
    }
    assert output == expected_output


def test_reprocess_articles_reports_failures_and_missing_ids(monkeypatch):
    factory = create_session_factory()
    article_id = create_ready_article(factory, "https://example.com/b")
    monkeypatch.setattr(pipeline, "fetch_html", lambda url: "<html>raw</html>")

    def reject(html, url):
        raise NotArticleError("not an article: og:type is product")

    monkeypatch.setattr(pipeline, "extract_article", reject)

    results = reprocess_articles([article_id, 999], session_factory=factory)

    output = [(r.article_id, r.status, r.error) for r in results]
    expected_output = [
        (article_id, "failed", "not an article: og:type is product"),
        (999, "missing", None),
    ]
    assert output == expected_output
