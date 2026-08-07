from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from nanonerd.reader import pipeline
from nanonerd.reader.db import get_session
from nanonerd.reader.models import Article, Chunk, ReadingSession
from nanonerd.reader.schemas import (
    ArticleDetail,
    ArticleSummary,
    ChunkOut,
    ProgressRequest,
    ProgressResponse,
    SaveRequest,
    SaveResponse,
    SessionCreated,
    SessionState,
    SessionUpdate,
)
from nanonerd.reader.urlnorm import normalize_url

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]


def _percent(read_words: int, total_words: int) -> float:
    if total_words <= 0:
        return 0.0
    return round(100 * read_words / total_words, 1)


def _read_words(session: Session, article_id: int) -> int:
    value = session.scalar(
        select(func.coalesce(func.sum(Chunk.word_count), 0)).where(
            Chunk.article_id == article_id, Chunk.read_at.is_not(None)
        )
    )
    return int(value or 0)


def _summary(article: Article, read_words: int) -> ArticleSummary:
    return ArticleSummary(
        id=article.id,
        title=article.title,
        url=article.url,
        site_name=article.site_name,
        author=article.author,
        status=article.status,
        error=article.error,
        word_count=article.word_count,
        priority=article.priority,
        percent_read=_percent(read_words, article.word_count),
        categories=[category.name for category in article.categories],
        added_at=article.added_at,
    )


@router.post("/articles", response_model=SaveResponse)
def save_article(
    payload: SaveRequest, background: BackgroundTasks, session: SessionDep
) -> SaveResponse:
    url = normalize_url(payload.url)
    existing = session.scalar(select(Article).where(Article.url == url))
    if existing is not None:
        return SaveResponse(id=existing.id, duplicate=True, status=existing.status)

    article = Article(url=url, title=payload.title or url, status="pending")
    session.add(article)
    session.commit()
    background.add_task(pipeline.process_article, article.id)
    return SaveResponse(id=article.id, duplicate=False, status="pending")


@router.get("/articles", response_model=list[ArticleSummary])
def list_articles(session: SessionDep) -> list[ArticleSummary]:
    articles = session.scalars(
        select(Article)
        .options(selectinload(Article.categories))
        .order_by(Article.priority.desc(), Article.added_at.desc())
    ).all()
    read_by_article: dict[int, int] = {
        article_id: int(total)
        for article_id, total in session.execute(
            select(Chunk.article_id, func.sum(Chunk.word_count))
            .where(Chunk.read_at.is_not(None))
            .group_by(Chunk.article_id)
        ).all()
    }
    return [
        _summary(article, read_by_article.get(article.id, 0)) for article in articles
    ]


@router.get("/articles/{article_id}", response_model=ArticleDetail)
def get_article(article_id: int, session: SessionDep) -> ArticleDetail:
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    summary = _summary(article, _read_words(session, article_id))
    chunks = [
        ChunkOut(
            id=chunk.id,
            position=chunk.position,
            html=chunk.html,
            word_count=chunk.word_count,
            read=chunk.read_at is not None,
        )
        for chunk in article.chunks
    ]
    return ArticleDetail(**summary.model_dump(), chunks=chunks)


@router.post("/articles/{article_id}/progress", response_model=ProgressResponse)
def mark_progress(
    article_id: int, payload: ProgressRequest, session: SessionDep
) -> ProgressResponse:
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    if payload.chunk_ids:
        session.execute(
            update(Chunk)
            .where(
                Chunk.article_id == article_id,
                Chunk.id.in_(payload.chunk_ids),
                Chunk.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        session.commit()
    return ProgressResponse(
        percent_read=_percent(_read_words(session, article_id), article.word_count)
    )


@router.post("/articles/{article_id}/retry", response_model=SaveResponse)
def retry_article(
    article_id: int, background: BackgroundTasks, session: SessionDep
) -> SaveResponse:
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    if article.status != "failed":
        raise HTTPException(status_code=409, detail="article is not in failed state")
    session.execute(delete(Chunk).where(Chunk.article_id == article_id))
    article.status = "pending"
    article.error = None
    session.commit()
    background.add_task(pipeline.process_article, article.id)
    return SaveResponse(id=article.id, duplicate=False, status="pending")


@router.post("/articles/{article_id}/sessions", response_model=SessionCreated)
def create_reading_session(article_id: int, session: SessionDep) -> SessionCreated:
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    reading = ReadingSession(article_id=article_id)
    session.add(reading)
    session.commit()
    return SessionCreated(id=reading.id)


@router.post("/sessions/{session_id}", response_model=SessionState)
def update_reading_session(
    session_id: int, payload: SessionUpdate, session: SessionDep
) -> SessionState:
    reading = session.get(ReadingSession, session_id)
    if reading is None:
        raise HTTPException(status_code=404, detail="session not found")
    if payload.active_seconds > reading.active_seconds:
        reading.active_seconds = payload.active_seconds
        reading.last_active_at = datetime.now(UTC)
        session.commit()
    return SessionState(id=reading.id, active_seconds=reading.active_seconds)
