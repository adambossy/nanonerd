from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


article_categories = Table(
    "article_categories",
    Base.metadata,
    Column(
        "article_id",
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str | None] = mapped_column(Text, default=None)
    site_name: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    content_html: Mapped[str | None] = mapped_column(Text, default=None)
    word_count: Mapped[int] = mapped_column(default=0)
    priority: Mapped[int] = mapped_column(default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Faithful-snapshot state: none | pending | ready | failed
    snapshot_status: Mapped[str] = mapped_column(String(16), default="none")
    snapshot_available: Mapped[bool] = mapped_column(default=False)
    snapshot_bytes: Mapped[int] = mapped_column(default=0)
    snapshot_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    snapshot_error: Mapped[str | None] = mapped_column(Text, default=None)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="Chunk.position",
    )
    categories: Mapped[list["Category"]] = relationship(secondary=article_categories)
    snapshot: Mapped["ArticleSnapshot | None"] = relationship(
        back_populates="article", cascade="all, delete-orphan", uselist=False
    )


class ArticleSnapshot(Base):
    """Self-contained, chunk-tagged HTML copy of the source page.

    Kept in its own table so article listings never load the (multi-MB)
    payload; single-user scale makes a blob store unnecessary for now."""

    __tablename__ = "article_snapshots"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    html: Mapped[str] = mapped_column(Text)

    article: Mapped[Article] = relationship(back_populates="snapshot")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column()
    html: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(default=0)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    article: Mapped[Article] = relationship(back_populates="chunks")


class ReadingSession(Base):
    __tablename__ = "reading_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    active_seconds: Mapped[int] = mapped_column(default=0)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
