from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from nanonerd.reader.models import Article, Base, Category, Chunk


def create_test_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine


def test_article_roundtrip_with_chunks_and_categories():
    engine = create_test_engine()
    input_article = Article(
        url="https://example.com/a",
        title="A Title",
        status="ready",
        word_count=300,
        chunks=[
            Chunk(position=0, html="<p>one</p>", word_count=100),
            Chunk(
                position=1, html="<p>two</p>", word_count=200, read_at=datetime.now(UTC)
            ),
        ],
        categories=[Category(name="Transit")],
    )

    with Session(engine) as session:
        session.add(input_article)
        session.commit()

    with Session(engine) as session:
        output = session.scalars(select(Article)).one()
        output_summary = {
            "url": output.url,
            "status": output.status,
            "priority": output.priority,
            "chunk_positions": [c.position for c in output.chunks],
            "read_flags": [c.read_at is not None for c in output.chunks],
            "categories": [c.name for c in output.categories],
        }

    expected_output = {
        "url": "https://example.com/a",
        "status": "ready",
        "priority": 0,
        "chunk_positions": [0, 1],
        "read_flags": [False, True],
        "categories": ["Transit"],
    }
    assert output_summary == expected_output
