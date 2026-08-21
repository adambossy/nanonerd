from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, defer, selectinload

from nanonerd.reader import pipeline
from nanonerd.reader.db import get_session
from nanonerd.reader.models import Article, ArticleSnapshot, Chunk, ReadingSession
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
    SnapshotState,
)
from nanonerd.reader.snapshot import service as snapshot_service
from nanonerd.reader.urlnorm import normalize_url

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]

# The snapshot is fetched by the same-origin reader and injected into a shadow
# root; these headers only matter if someone opens the URL directly.
SNAPSHOT_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; img-src data: https:; style-src 'unsafe-inline'; "
        "font-src data: https:; media-src data: https:; sandbox"
    ),
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=0, must-revalidate",
}


def _snapshot_state(article: Article) -> SnapshotState:
    return SnapshotState(
        status=article.snapshot_status,
        available=article.snapshot_available,
        bytes=article.snapshot_bytes,
        captured_at=article.snapshot_captured_at,
        error=article.snapshot_error,
    )


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
    read_words = (
        select(func.coalesce(func.sum(Chunk.word_count), 0))
        .where(Chunk.article_id == Article.id, Chunk.read_at.is_not(None))
        .scalar_subquery()
    )
    rows = session.execute(
        select(Article, read_words)
        .options(defer(Article.content_html), selectinload(Article.categories))
        .order_by(Article.priority.desc(), Article.added_at.desc())
    ).all()
    return [_summary(article, int(read_total)) for article, read_total in rows]


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
    return ArticleDetail(
        **summary.model_dump(), chunks=chunks, snapshot=_snapshot_state(article)
    )


@router.post("/articles/{article_id}/snapshot", response_model=SnapshotState)
def request_snapshot(
    article_id: int, background: BackgroundTasks, session: SessionDep
) -> SnapshotState:
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    if article.snapshot_status == "pending":
        raise HTTPException(status_code=409, detail="snapshot capture in progress")
    article.snapshot_status = "pending"
    article.snapshot_error = None
    session.commit()
    background.add_task(snapshot_service.capture_snapshot, article.id)
    return _snapshot_state(article)


@router.get("/articles/{article_id}/snapshot", response_class=HTMLResponse)
def get_snapshot(article_id: int, session: SessionDep) -> HTMLResponse:
    snapshot = session.get(ArticleSnapshot, article_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no snapshot for this article")
    return HTMLResponse(content=snapshot.html, headers=SNAPSHOT_HEADERS)


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
    # Snapshot markers point at chunk ids; a re-extraction invalidates them.
    session.execute(
        delete(ArticleSnapshot).where(ArticleSnapshot.article_id == article_id)
    )
    article.snapshot_status = "none"
    article.snapshot_available = False
    article.snapshot_bytes = 0
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
