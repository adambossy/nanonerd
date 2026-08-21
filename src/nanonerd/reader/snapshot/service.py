"""Background job: capture a faithful snapshot for an article and rebuild its
chunks from the snapshot's tagged blocks (chunks stay the single source of
truth for reading progress)."""

from collections.abc import Callable
from datetime import UTC, datetime
import logging

from sqlalchemy.orm import Session, sessionmaker

from nanonerd.reader.chunking import ChunkData, html_to_text
from nanonerd.reader.db import SessionLocal
from nanonerd.reader.extract import _ensure_public_http_url
from nanonerd.reader.models import Article, ArticleSnapshot, Chunk
from nanonerd.reader.snapshot.build import (
    BuildLimits,
    SnapshotBuild,
    assemble_snapshot,
    attach_chunk_ids,
)
from nanonerd.reader.snapshot.capture import CapturedPage, capture_page
from nanonerd.reader.snapshot.declutter import normalize_text

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_BYTES = 8_000_000
# Second attempt keeps fonts/CSS but stops inlining images (they stay https:).
_BUILD_ATTEMPTS = (BuildLimits(), BuildLimits(max_image_bytes=0))

CaptureFn = Callable[[str], CapturedPage]


class SnapshotTooLargeError(ValueError):
    pass


def _build_within_budget(captured: CapturedPage, title: str | None) -> SnapshotBuild:
    build: SnapshotBuild | None = None
    for limits in _BUILD_ATTEMPTS:
        build = assemble_snapshot(
            captured.html,
            url=captured.url,
            title=title,
            resources=captured.resources,
            limits=limits,
        )
        if len(build.html.encode("utf-8")) <= MAX_SNAPSHOT_BYTES:
            return build
    assert build is not None  # noqa: S101 - loop always runs at least once
    raise SnapshotTooLargeError(
        f"snapshot too large ({len(build.html.encode('utf-8'))} bytes > "
        f"{MAX_SNAPSHOT_BYTES})"
    )


def _chunk_key(html: str) -> str:
    return normalize_text(html_to_text(html)).lower()


def _replace_chunks(article: Article, chunks: list[ChunkData]) -> None:
    """Swap in snapshot-derived chunks, carrying read state over to any new
    chunk whose text matches an already-read chunk."""
    read_keys = {
        _chunk_key(old.html) for old in article.chunks if old.read_at is not None
    }
    now = datetime.now(UTC)
    article.chunks = [
        Chunk(
            position=index,
            html=chunk.html,
            word_count=chunk.word_count,
            read_at=now
            if chunk.word_count and _chunk_key(chunk.html) in read_keys
            else None,
        )
        for index, chunk in enumerate(chunks)
    ]
    article.word_count = sum(chunk.word_count for chunk in chunks)


def _store(session: Session, article: Article, build: SnapshotBuild) -> None:
    _replace_chunks(article, build.chunks)
    session.flush()  # assigns chunk ids
    html = attach_chunk_ids(build.html, [chunk.id for chunk in article.chunks])
    if article.snapshot is None:
        article.snapshot = ArticleSnapshot(html=html)
    else:
        article.snapshot.html = html
    article.snapshot_status = "ready"
    article.snapshot_available = True
    article.snapshot_bytes = len(html.encode("utf-8"))
    article.snapshot_captured_at = datetime.now(UTC)
    article.snapshot_error = None


def _mark_failed(
    session_factory: sessionmaker[Session], article_id: int, reason: str
) -> None:
    with session_factory() as session:
        article = session.get(Article, article_id)
        if article is None:
            return
        article.snapshot_status = "failed"
        article.snapshot_error = reason[:1000]
        session.commit()


def capture_snapshot(
    article_id: int,
    session_factory: sessionmaker[Session] | None = None,
    capture: CaptureFn = capture_page,
) -> None:
    """Render, declutter, tag and store the snapshot; never raises."""
    factory = session_factory if session_factory is not None else SessionLocal
    with factory() as session:
        article = session.get(Article, article_id)
        if article is None:
            return
        url, title = article.url, article.title
        try:
            _ensure_public_http_url(url)
            captured = capture(url)
            build = _build_within_budget(captured, title)
            if not build.chunks:
                raise ValueError("snapshot produced no readable blocks")
            _store(session, article, build)
            session.commit()
        except Exception as exc:  # noqa: BLE001 - background task must not raise
            logger.warning("snapshot failed for article %s", article_id, exc_info=True)
            session.rollback()
            _mark_failed(factory, article_id, str(exc))
