"""Turn a URL into reading-grade article HTML.

Render, extract, fall back to archives when walled, cache images, sanitize.
"""

from collections.abc import Callable
from dataclasses import dataclass
import logging

import httpx

from nanonerd.reader.archive import find_archive_ph_snapshot, find_wayback_snapshot
from nanonerd.reader.chunking import html_to_text
from nanonerd.reader.errors import ExtractionError, FetchError, RenderError
from nanonerd.reader.extract import Extraction, extract_rendered
from nanonerd.reader.images import cache_images
from nanonerd.reader.render import RenderedPage, Renderer, RenderMode, renderer_from_env
from nanonerd.reader.sanitize import sanitize_html
from nanonerd.reader.storage import Storage, storage_from_env

logger = logging.getLogger(__name__)

SOURCE_LIVE = "live"
SOURCE_ARCHIVE_PH = "archive_ph"
SOURCE_WAYBACK = "wayback"

_BLOCKED_STATUSES = {401, 403, 429, 503}
_BLOCK_MARKERS = (
    "captcha-delivery.com",
    "datadome",
    "enable javascript and disable any ad blocker",
    "please enable js and disable any ad blocker",
    "just a moment...",
    "checking your browser",
    "attention required! | cloudflare",
    "verify you are human",
    "are you a robot",
    "please complete the security check",
    "one more step",
    "access denied",
    "not authorized",
)
# Below this many words on a large page, the extractor most likely saw a
# wall rather than the article.
MIN_WORDS = 150
LARGE_BODY_BYTES = 50_000
_MARKER_SCAN_BYTES = 200_000

SnapshotFinder = Callable[..., str | None]


@dataclass(frozen=True, slots=True)
class AcquiredArticle:
    title: str | None
    author: str | None
    site_name: str | None
    content_html: str
    source_kind: str
    source_url: str
    images_cached: int


@dataclass(frozen=True, slots=True)
class _Sourced:
    extraction: Extraction
    source_kind: str
    source_url: str


def _extraction_words(extraction: Extraction | None) -> int:
    if extraction is None:
        return 0
    return len(html_to_text(extraction.content_html).split())


def blocked_reason(rendered: RenderedPage, extraction: Extraction | None) -> str | None:
    """Why this render looks like a bot wall or paywall rather than the article."""
    if rendered.status in _BLOCKED_STATUSES:
        return f"http {rendered.status}"
    haystack = (rendered.dom_html or rendered.html)[:_MARKER_SCAN_BYTES].lower()
    for marker in _BLOCK_MARKERS:
        if marker in haystack:
            return f"marker {marker!r}"
    if extraction is None:
        return "no extractable content"
    words = _extraction_words(extraction)
    source_size = max(len(rendered.html), len(rendered.dom_html))
    if words < MIN_WORDS and source_size > LARGE_BODY_BYTES:
        return f"thin extraction ({words} words from {source_size} bytes)"
    return None


def _is_thin_only(reason: str) -> bool:
    return reason.startswith("thin extraction")


def _render(
    renderer: Renderer, url: str, mode: RenderMode
) -> tuple[RenderedPage | None, Extraction | None, str | None]:
    try:
        rendered = renderer.render(url, mode=mode)
    except (RenderError, FetchError) as exc:
        logger.info("render of %s failed: %s", url, exc)
        return None, None, f"render failed: {exc}"
    extraction = extract_rendered(rendered)
    return rendered, extraction, blocked_reason(rendered, extraction)


_ARCHIVE_FINDERS: tuple[tuple[str, SnapshotFinder], ...] = (
    (SOURCE_ARCHIVE_PH, find_archive_ph_snapshot),
    (SOURCE_WAYBACK, find_wayback_snapshot),
)


def _from_archives(
    url: str, *, renderer: Renderer, client: httpx.Client
) -> _Sourced | None:
    for kind, finder in _ARCHIVE_FINDERS:
        snapshot = finder(url, client=client)
        if snapshot is None:
            logger.info("no %s snapshot for %s", kind, url)
            continue
        _rendered, extraction, reason = _render(renderer, snapshot, RenderMode.ARCHIVE)
        if reason is None and extraction is not None:
            return _Sourced(
                extraction=extraction, source_kind=kind, source_url=snapshot
            )
        logger.info("%s snapshot %s unusable: %s", kind, snapshot, reason)
    return None


def _extract_with_fallback(
    url: str, *, renderer: Renderer, client: httpx.Client
) -> _Sourced:
    live, extraction, reason = _render(renderer, url, RenderMode.LIVE)
    if reason is None and extraction is not None and live is not None:
        return _Sourced(
            extraction=extraction, source_kind=SOURCE_LIVE, source_url=live.final_url
        )
    logger.info("live render of %s looks blocked (%s); trying archives", url, reason)
    archived = _from_archives(url, renderer=renderer, client=client)
    if archived is not None:
        return archived
    # A genuinely short article on a heavy page trips the thin-extraction
    # heuristic; with no archive to compare against, the live copy is best.
    if extraction is not None and reason is not None and _is_thin_only(reason) and live:
        return _Sourced(
            extraction=extraction, source_kind=SOURCE_LIVE, source_url=live.final_url
        )
    raise ExtractionError(
        f"could not extract readable content ({reason}); no usable archive copy"
    )


def acquire_article(
    url: str,
    *,
    article_id: int,
    renderer: Renderer | None = None,
    storage: Storage | None = None,
    client: httpx.Client | None = None,
) -> AcquiredArticle:
    """Fetch, extract, re-host images and sanitize; raises `ReaderError` on failure."""
    if renderer is None:
        renderer = renderer_from_env()
    if storage is None:
        storage = storage_from_env()
    if client is None:
        with httpx.Client() as owned_client:
            return acquire_article(
                url,
                article_id=article_id,
                renderer=renderer,
                storage=storage,
                client=owned_client,
            )
    sourced = _extract_with_fallback(url, renderer=renderer, client=client)
    cached = cache_images(
        sourced.extraction.content_html,
        page_url=sourced.source_url,
        storage=storage,
        key_prefix=f"articles/{article_id}",
        client=client,
    )
    extraction = sourced.extraction
    return AcquiredArticle(
        title=extraction.title,
        author=extraction.author,
        site_name=extraction.site_name,
        content_html=sanitize_html(cached.html),
        source_kind=sourced.source_kind,
        source_url=sourced.source_url,
        images_cached=cached.cached_count,
    )
