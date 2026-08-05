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


class ChunkOut(BaseModel):
    id: int
    position: int
    html: str
    word_count: int
    read: bool


class ArticleDetail(ArticleSummary):
    chunks: list[ChunkOut]


class ProgressRequest(BaseModel):
    chunk_ids: list[int]


class ProgressResponse(BaseModel):
    percent_read: float
