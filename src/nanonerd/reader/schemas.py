from datetime import datetime

from pydantic import BaseModel


class SaveRequest(BaseModel):
    url: str
    title: str | None = None


class SaveResponse(BaseModel):
    id: int
    duplicate: bool
    status: str


class ArticleSummary(BaseModel):
    id: int
    title: str
    url: str
    site_name: str | None
    author: str | None
    status: str
    error: str | None
    word_count: int
    priority: int
    percent_read: float
    categories: list[str]
    added_at: datetime
    extracted_at: datetime | None


class ChunkOut(BaseModel):
    id: int
    position: int
    html: str
    word_count: int
    read: bool


class ArticleDetail(ArticleSummary):
    chunks: list[ChunkOut]


class ReadMark(BaseModel):
    chunk_id: int
    read_at: datetime


class ProgressRequest(BaseModel):
    chunk_ids: list[int] = []
    marks: list[ReadMark] = []


class ProgressResponse(BaseModel):
    percent_read: float


class SessionUpsert(BaseModel):
    article_id: int
    started_at: datetime
    active_seconds: int


class SessionState(BaseModel):
    client_id: str
    active_seconds: int


class ResumeTarget(BaseModel):
    article_id: int
    title: str


class HistoryEntry(BaseModel):
    chunk_id: int
    article_id: int
    article_title: str
    position: int
    word_count: int
    read_at: datetime
    snippet: str


class StatsTotals(BaseModel):
    active_seconds: int
    articles_saved: int
    articles_finished: int
    words_read: int


class TopicStats(BaseModel):
    name: str
    saved: int
    read_through: float
    active_seconds: int


class DailyStats(BaseModel):
    date: str
    active_seconds: int


class TopArticle(BaseModel):
    id: int
    title: str
    active_seconds: int
    percent_read: float


class StatsResponse(BaseModel):
    totals: StatsTotals
    topics: list[TopicStats]
    daily: list[DailyStats]
    top_articles: list[TopArticle]
