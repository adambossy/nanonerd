from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from nanonerd.reader.db import get_session
from nanonerd.reader.models import Article, Chunk, ReadingSession
from nanonerd.reader.schemas import (
    DailyStats,
    StatsResponse,
    StatsTotals,
    TopArticle,
    TopicStats,
)

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]

FINISHED_PERCENT = 95.0
DAILY_WINDOW_DAYS = 30
TOP_ARTICLES_LIMIT = 10
UNCATEGORIZED = "(uncategorized)"


def _percent(read_words: int, total_words: int) -> float:
    if total_words <= 0:
        return 0.0
    return round(100 * read_words / total_words, 1)


@router.get("/stats", response_model=StatsResponse)
def get_stats(session: SessionDep) -> StatsResponse:
    articles = session.scalars(
        select(Article).options(selectinload(Article.categories))
    ).all()
    read_words: dict[int, int] = {
        article_id: int(total)
        for article_id, total in session.execute(
            select(Chunk.article_id, func.sum(Chunk.word_count))
            .where(Chunk.read_at.is_not(None))
            .group_by(Chunk.article_id)
        ).all()
    }
    active_by_article: dict[int, int] = {
        article_id: int(total)
        for article_id, total in session.execute(
            select(
                ReadingSession.article_id, func.sum(ReadingSession.active_seconds)
            ).group_by(ReadingSession.article_id)
        ).all()
    }
    percents = {
        article.id: _percent(read_words.get(article.id, 0), article.word_count)
        for article in articles
    }

    totals = StatsTotals(
        active_seconds=sum(active_by_article.values()),
        articles_saved=len(articles),
        articles_finished=sum(
            1 for article in articles if percents[article.id] >= FINISHED_PERCENT
        ),
        words_read=sum(read_words.values()),
    )

    topic_saved: dict[str, int] = {}
    topic_percent_sum: dict[str, float] = {}
    topic_seconds: dict[str, int] = {}
    for article in articles:
        names = [category.name for category in article.categories] or [UNCATEGORIZED]
        for name in names:
            topic_saved[name] = topic_saved.get(name, 0) + 1
            topic_percent_sum[name] = (
                topic_percent_sum.get(name, 0.0) + percents[article.id]
            )
            topic_seconds[name] = topic_seconds.get(name, 0) + active_by_article.get(
                article.id, 0
            )
    topics = sorted(
        (
            TopicStats(
                name=name,
                saved=saved,
                read_through=round(topic_percent_sum[name] / saved, 1),
                active_seconds=topic_seconds[name],
            )
            for name, saved in topic_saved.items()
        ),
        key=lambda topic: (-topic.active_seconds, -topic.saved, topic.name),
    )

    window_start = datetime.now(UTC) - timedelta(days=DAILY_WINDOW_DAYS - 1)
    day_zero = window_start.date()
    per_day: dict[str, int] = {}
    for reading in session.scalars(
        select(ReadingSession).where(ReadingSession.started_at >= window_start)
    ).all():
        key = reading.started_at.date().isoformat()
        per_day[key] = per_day.get(key, 0) + reading.active_seconds
    daily = [
        DailyStats(
            date=(day_zero + timedelta(days=offset)).isoformat(),
            active_seconds=per_day.get(
                (day_zero + timedelta(days=offset)).isoformat(), 0
            ),
        )
        for offset in range(DAILY_WINDOW_DAYS)
    ]

    articles_by_id = {article.id: article for article in articles}
    top_articles = [
        TopArticle(
            id=article_id,
            title=articles_by_id[article_id].title,
            active_seconds=seconds,
            percent_read=percents[article_id],
        )
        for article_id, seconds in sorted(
            active_by_article.items(), key=lambda item: -item[1]
        )[:TOP_ARTICLES_LIMIT]
        if seconds > 0 and article_id in articles_by_id
    ]

    return StatsResponse(
        totals=totals, topics=topics, daily=daily, top_articles=top_articles
    )
