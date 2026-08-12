from datetime import UTC, datetime
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from nanonerd.reader.categorize import assign_categories
from nanonerd.reader.chunking import chunk_html, html_to_text
from nanonerd.reader.db import SessionLocal
from nanonerd.reader.extract import extract_article, fetch_html
from nanonerd.reader.models import Article, Category, Chunk

logger = logging.getLogger(__name__)


def _get_or_create_category(session: Session, name: str) -> Category:
    existing = session.scalar(
        select(Category).where(func.lower(Category.name) == name.lower())
    )
    if existing is not None:
        return existing
    category = Category(name=name)
    session.add(category)
    session.flush()
    return category


def _apply_categories(session: Session, article: Article) -> None:
    if not article.content_html:
        return
    existing_names = list(session.scalars(select(Category.name)).all())
    names = assign_categories(
        article.title, html_to_text(article.content_html), existing_names
    )
    article.categories = [_get_or_create_category(session, name) for name in names]


def process_article(
    article_id: int, session_factory: sessionmaker[Session] | None = None
) -> None:
    factory = session_factory if session_factory is not None else SessionLocal
    with factory() as session:
        article = session.get(Article, article_id)
        if article is None:
            return
        try:
            html = fetch_html(article.url)
            extraction = extract_article(html, article.url)
            if extraction is None:
                raise ValueError("could not extract readable content")
            chunks = chunk_html(extraction.content_html)
            if not chunks:
                raise ValueError("extracted content produced no chunks")

            article.chunks = [
                Chunk(position=i, html=c.html, word_count=c.word_count)
                for i, c in enumerate(chunks)
            ]
            article.title = extraction.title or article.title or article.url
            article.author = extraction.author
            article.site_name = extraction.site_name
            article.content_html = extraction.content_html
            article.word_count = sum(c.word_count for c in chunks)
            article.status = "ready"
            article.error = None
            article.extracted_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 - background task must not raise
            logger.warning(
                "processing failed for article %s", article_id, exc_info=True
            )
            session.rollback()
            failed = session.get(Article, article_id)
            if failed is not None:
                failed.status = "failed"
                failed.error = str(exc)[:1000]
                session.commit()
            return

        try:
            _apply_categories(session, article)
        except Exception:
            logger.warning(
                "categorization failed for article %s", article_id, exc_info=True
            )
        session.commit()
