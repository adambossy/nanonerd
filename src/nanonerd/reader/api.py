from datetime import UTC, datetime
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, defer, selectinload

from nanonerd.reader import pipeline
from nanonerd.reader.chunking import html_to_text
from nanonerd.reader.db import get_session
from nanonerd.reader.models import Article, Chunk, ReadingSession
from nanonerd.reader.schemas import (
    ArticleDetail,
    ArticleSummary,
    ChunkOut,
    HistoryEntry,
    ProgressRequest,
    ProgressResponse,
    ResumeTarget,
    SaveRequest,
    SaveResponse,
    SessionState,
    SessionUpsert,
)
from nanonerd.reader.urlnorm import normalize_url

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]

SNIPPET_CHARS = 140


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


def _fidelity_reasons(article: Article) -> list[str]:
    if not article.fidelity_reasons:
        return []
    try:
        parsed = json.loads(article.fidelity_reasons)
    except ValueError:
        return []
    return [str(reason) for reason in parsed] if isinstance(parsed, list) else []


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
        extracted_at=article.extracted_at,
        fidelity_status=article.fidelity_status,
        fidelity_score=article.fidelity_score,
        fidelity_reasons=_fidelity_reasons(article),
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _requested_read_times(
    payload: ProgressRequest, now: datetime
) -> dict[int, datetime]:
    """Earliest requested read time per chunk, never later than now."""
    times = dict.fromkeys(payload.chunk_ids, now)
    for mark in payload.marks:
        requested = min(_as_utc(mark.read_at), now)
        existing = times.get(mark.chunk_id)
        times[mark.chunk_id] = (
            requested if existing is None else min(existing, requested)
        )
    return times


def _apply_read_times(
    session: Session, article_id: int, times: dict[int, datetime]
) -> None:
    """Set read_at to the earliest known time; unknown/foreign ids are ignored."""
    if not times:
        return
    chunks = session.scalars(
        select(Chunk).where(Chunk.article_id == article_id, Chunk.id.in_(times))
    ).all()
    rows = []
    for chunk in chunks:
        requested = times[chunk.id]
        current = _as_utc(chunk.read_at) if chunk.read_at is not None else None
        if current is None or requested < current:
            rows.append({"id": chunk.id, "read_at": requested})
    if rows:
        session.execute(update(Chunk), rows)
        session.commit()


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
    return ArticleDetail(**summary.model_dump(), chunks=chunks)


@router.post("/articles/{article_id}/progress", response_model=ProgressResponse)
def mark_progress(
    article_id: int, payload: ProgressRequest, session: SessionDep
) -> ProgressResponse:
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    _apply_read_times(
        session, article_id, _requested_read_times(payload, datetime.now(UTC))
    )
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
    article.fidelity_status = None
    article.fidelity_score = None
    article.fidelity_reasons = None
    article.fidelity_checked_at = None
    session.commit()
    background.add_task(pipeline.process_article, article.id)
    return SaveResponse(id=article.id, duplicate=False, status="pending")


def _first_resumable(session: Session, article_ids: list[int]) -> Article | None:
    for article_id in article_ids:
        article = session.get(Article, article_id)
        if article is None or article.status != "ready":
            continue
        if _read_words(session, article_id) < article.word_count:
            return article
    return None


def _snippet(html: str) -> str:
    text = html_to_text(html)
    if len(text) <= SNIPPET_CHARS:
        return text
    return text[:SNIPPET_CHARS].rstrip() + "…"


@router.get("/resume", response_model=ResumeTarget | None)
def get_resume(session: SessionDep) -> ResumeTarget | None:
    by_session = session.execute(
        select(ReadingSession.article_id)
        .group_by(ReadingSession.article_id)
        .order_by(func.max(ReadingSession.last_active_at).desc())
    ).scalars()
    article = _first_resumable(session, list(by_session))
    if article is None:
        by_chunk = session.execute(
            select(Chunk.article_id)
            .where(Chunk.read_at.is_not(None))
            .group_by(Chunk.article_id)
            .order_by(func.max(Chunk.read_at).desc())
        ).scalars()
        article = _first_resumable(session, list(by_chunk))
    if article is None:
        return None
    return ResumeTarget(article_id=article.id, title=article.title)


@router.get("/history", response_model=list[HistoryEntry])
def get_history(session: SessionDep, limit: int = 200) -> list[HistoryEntry]:
    rows = session.execute(
        select(Chunk, Article.title)
        .join(Article, Article.id == Chunk.article_id)
        .where(Chunk.read_at.is_not(None))
        # Chunks marked in the same batch share a read_at; position breaks the tie.
        .order_by(Chunk.read_at.desc(), Chunk.position.desc())
        .limit(limit)
    ).all()
    return [
        HistoryEntry(
            chunk_id=chunk.id,
            article_id=chunk.article_id,
            article_title=title,
            position=chunk.position,
            word_count=chunk.word_count,
            read_at=chunk.read_at,
            snippet=_snippet(chunk.html),
        )
        for chunk, title in rows
        if chunk.read_at is not None
    ]


@router.put("/sessions/{client_id}", response_model=SessionState)
def upsert_reading_session(
    client_id: UUID, payload: SessionUpsert, session: SessionDep
) -> SessionState:
    now = datetime.now(UTC)
    key = str(client_id)
    reading = session.scalar(
        select(ReadingSession).where(ReadingSession.client_id == key)
    )
    if reading is None:
        if session.get(Article, payload.article_id) is None:
            raise HTTPException(status_code=404, detail="article not found")
        reading = ReadingSession(
            client_id=key,
            article_id=payload.article_id,
            started_at=min(_as_utc(payload.started_at), now),
            last_active_at=now,
            active_seconds=max(0, payload.active_seconds),
        )
        session.add(reading)
    elif payload.active_seconds > reading.active_seconds:
        reading.active_seconds = payload.active_seconds
        reading.last_active_at = now
    session.commit()
    return SessionState(client_id=key, active_seconds=reading.active_seconds)
