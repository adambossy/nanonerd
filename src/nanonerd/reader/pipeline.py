from datetime import UTC, datetime
import json
import logging

from anthropic import Anthropic
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from nanonerd.reader.categorize import assign_categories
from nanonerd.reader.chunking import ChunkData, chunk_html, html_to_text
from nanonerd.reader.db import SessionLocal
from nanonerd.reader.extract import FetchError, extract_article, fetch_html
from nanonerd.reader.fidelity import Verdict, judge_extraction
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


def fidelity_client() -> Anthropic | None:
    """A client for the judge's escalation path, or None when unavailable."""
    try:
        return Anthropic()
    except Exception:  # noqa: BLE001 - judging must work without an API key
        logger.debug("no Anthropic client available for fidelity judging")
        return None


def apply_verdict(article: Article, verdict: Verdict) -> None:
    article.fidelity_status = verdict.status
    article.fidelity_score = verdict.score
    article.fidelity_reasons = json.dumps(verdict.reasons)
    article.fidelity_checked_at = datetime.now(UTC)


def record_fidelity(
    article: Article,
    *,
    http_status: int | None,
    source_html: str | None,
    extracted_html: str | None,
    chunks: list[ChunkData] | None,
) -> None:
    """Annotate `article` with an extraction-fidelity verdict.

    This never changes `status`; a bad verdict on a "ready" article is a
    warning for the reader, not a processing failure.
    """
    try:
        verdict = judge_extraction(
            url=article.url,
            http_status=http_status,
            source_html=source_html,
            extracted_html=extracted_html,
            chunks=(
                [(chunk.html, chunk.word_count) for chunk in chunks]
                if chunks is not None
                else None
            ),
            title=article.title,
            client=fidelity_client(),
        )
    except Exception:  # noqa: BLE001 - the judge is an annotation, not a gate
        logger.warning("fidelity judging failed for %s", article.url, exc_info=True)
        return
    apply_verdict(article, verdict)


def process_article(
    article_id: int, session_factory: sessionmaker[Session] | None = None
) -> None:
    factory = session_factory if session_factory is not None else SessionLocal
    with factory() as session:
        article = session.get(Article, article_id)
        if article is None:
            return
        source_html: str | None = None
        http_status: int | None = None
        try:
            source_html = fetch_html(article.url)
            http_status = 200
            extraction = extract_article(source_html, article.url)
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
            if isinstance(exc, FetchError):
                http_status = exc.status_code
                source_html = exc.body
            session.rollback()
            failed = session.get(Article, article_id)
            if failed is not None:
                failed.status = "failed"
                failed.error = str(exc)[:1000]
                record_fidelity(
                    failed,
                    http_status=http_status,
                    source_html=source_html,
                    extracted_html=None,
                    chunks=None,
                )
                session.commit()
            return

        record_fidelity(
            article,
            http_status=http_status,
            source_html=source_html,
            extracted_html=extraction.content_html,
            chunks=chunks,
        )
        try:
            _apply_categories(session, article)
        except Exception:
            logger.warning(
                "categorization failed for article %s", article_id, exc_info=True
            )
        session.commit()
