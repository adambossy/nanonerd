from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nanonerd.reader.models import Article, ArticleSnapshot, Base, Chunk
from nanonerd.reader.snapshot import service
from nanonerd.reader.snapshot.capture import CapturedPage, SnapshotCaptureError

PAGE_HTML = """<html><head><style>body{color:red}</style></head><body>
<main><article><h1>My Post</h1>
<p>First paragraph text here.</p>
<p>Second paragraph text here.</p>
</article></main></body></html>"""


def create_session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_article(factory, *, read_first=False):
    with factory() as session:
        article = Article(
            url="https://example.com/post",
            title="My Post",
            status="ready",
            snapshot_status="pending",
            word_count=8,
            chunks=[
                Chunk(
                    position=0,
                    html="<p>First paragraph text here.</p>",
                    word_count=4,
                    read_at=datetime.now(UTC) if read_first else None,
                ),
                Chunk(position=1, html="<p>Trafilatura-only block.</p>", word_count=4),
            ],
        )
        session.add(article)
        session.commit()
        return article.id


def fake_capture(url):
    return CapturedPage(url=url, html=PAGE_HTML, resources={})


def failing_capture(url):
    raise SnapshotCaptureError("boom")


def fetch_state(factory, article_id):
    with factory() as session:
        article = session.get(Article, article_id)
        snapshot = session.get(ArticleSnapshot, article_id)
        return {
            "status": article.snapshot_status,
            "available": article.snapshot_available,
            "error": article.snapshot_error,
            "word_count": article.word_count,
            "chunks": [
                (c.position, c.word_count, c.read_at is not None)
                for c in article.chunks
            ],
            "snapshot_bytes": article.snapshot_bytes,
            "ids_in_html": None
            if snapshot is None
            else [f'data-chunk-id="{c.id}"' in snapshot.html for c in article.chunks],
        }


def test_capture_snapshot_replaces_chunks_and_stores_tagged_html():
    factory = create_session_factory()
    article_id = create_article(factory)

    service.capture_snapshot(article_id, session_factory=factory, capture=fake_capture)

    output = fetch_state(factory, article_id)
    assert output["snapshot_bytes"] > 0
    output.pop("snapshot_bytes")
    expected_output = {
        "status": "ready",
        "available": True,
        "error": None,
        "word_count": 10,
        "chunks": [(0, 2, False), (1, 4, False), (2, 4, False)],
        "ids_in_html": [True, True, True],
    }
    assert output == expected_output


def test_capture_snapshot_carries_read_state_by_text_match():
    factory = create_session_factory()
    article_id = create_article(factory, read_first=True)

    service.capture_snapshot(article_id, session_factory=factory, capture=fake_capture)

    output = fetch_state(factory, article_id)["chunks"]
    assert output == [(0, 2, False), (1, 4, True), (2, 4, False)]


def test_capture_snapshot_records_failure_reason():
    factory = create_session_factory()
    article_id = create_article(factory)

    service.capture_snapshot(
        article_id, session_factory=factory, capture=failing_capture
    )

    output = fetch_state(factory, article_id)
    expected_output = {
        "status": "failed",
        "available": False,
        "error": "boom",
        "word_count": 8,
        "chunks": [(0, 4, False), (1, 4, False)],
        "snapshot_bytes": 0,
        "ids_in_html": None,
    }
    assert output == expected_output


def test_capture_snapshot_rejects_oversized_result(monkeypatch):
    factory = create_session_factory()
    article_id = create_article(factory)
    monkeypatch.setattr(service, "MAX_SNAPSHOT_BYTES", 10)

    service.capture_snapshot(article_id, session_factory=factory, capture=fake_capture)

    output = fetch_state(factory, article_id)
    assert (output["status"], output["error"].startswith("snapshot too large")) == (
        "failed",
        True,
    )


def test_capture_snapshot_refuses_private_urls():
    factory = create_session_factory()
    with factory() as session:
        article = Article(url="http://127.0.0.1:9/x", title="t", status="ready")
        session.add(article)
        session.commit()
        article_id = article.id

    service.capture_snapshot(article_id, session_factory=factory, capture=fake_capture)

    output = fetch_state(factory, article_id)
    assert (output["status"], "non-public" in output["error"]) == ("failed", True)
