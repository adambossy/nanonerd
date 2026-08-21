"""Page renderers: fetch a URL and hand back the document as the reader saw it.

`PlaywrightRenderer` drives headless Chromium at a phone viewport and runs the
in-page Defuddle extraction while the DOM is alive. `HttpxRenderer` is the
light-weight fallback (no browser, no in-page extraction) for tests, dev
boxes without Chromium, and `NANONERD_RENDERER=httpx`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import logging
import os
from typing import Literal, Protocol
from urllib.parse import urlsplit

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    Response,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from nanonerd.reader.defuddle import ReadableContent, extract_readable
from nanonerd.reader.errors import ExtractionError, FetchError, RenderError
from nanonerd.reader.fetch import ensure_public_http_url, fetch_response

logger = logging.getLogger(__name__)

_DEVICE_NAME = "iPhone 13"
_GOTO_TIMEOUT_MS = 30_000
_SETTLE_TIMEOUT_MS = 5_000
_POST_SETTLE_MS = 300
_CONTENT_ATTEMPTS = 3
# Resource types that never contribute to article content; skipping them
# makes renders faster and more deterministic.
_BLOCKED_RESOURCE_TYPES = {"font", "media", "websocket", "manifest", "ping"}
_BLOCKED_HOST_FRAGMENTS = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "googlesyndication.com",
    "adservice.google",
    "facebook.net",
    "connect.facebook.com",
    "hotjar.com",
    "segment.io",
    "segment.com",
    "sentry.io",
    "mixpanel.com",
    "amplitude.com",
    "fullstory.com",
    "intercom.io",
    "chartbeat.com",
    "scorecardresearch.com",
    "quantserve.com",
    "outbrain.com",
    "taboola.com",
    "criteo.com",
)


class RenderMode(Enum):
    LIVE = "live"
    # Archive snapshots load slowly and their scripts are often broken, so we
    # wait for the DOM rather than for the full load event.
    ARCHIVE = "archive"


@dataclass(frozen=True, slots=True)
class RenderedPage:
    url: str
    final_url: str
    status: int | None
    html: str
    dom_html: str
    readable: ReadableContent | None


class Renderer(Protocol):
    def render(
        self, url: str, *, mode: RenderMode = RenderMode.LIVE
    ) -> RenderedPage: ...


def _is_blocked_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(fragment in host for fragment in _BLOCKED_HOST_FRAGMENTS)


UrlGuard = Callable[[str], None]


def should_block_request(resource_type: str, url: str, mode: RenderMode) -> bool:
    """Trackers, fonts and media never help extraction; archived scripts hurt it.

    Archive snapshots are server-rendered copies whose JavaScript is stale and
    often redirect-loops (bot walls replaying themselves), so in ARCHIVE mode
    scripts are dropped too and the DOM is read as stored.
    """
    if resource_type in _BLOCKED_RESOURCE_TYPES or _is_blocked_host(url):
        return True
    return mode is RenderMode.ARCHIVE and resource_type == "script"


def _route_request(route: Route, url_guard: UrlGuard, mode: RenderMode) -> None:
    request = route.request
    if should_block_request(request.resource_type, request.url, mode):
        route.abort()
        return
    if request.is_navigation_request() and request.frame.parent_frame is None:
        try:
            url_guard(request.url)
        except FetchError:
            route.abort()
            return
    route.continue_()


def _dom_html(page: Page) -> str:
    # A page mid-navigation refuses to serialize; give it a moment and retry.
    for _ in range(_CONTENT_ATTEMPTS - 1):
        try:
            return page.content()
        except PlaywrightError:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=_SETTLE_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                pass
    return page.content()


@dataclass(frozen=True, slots=True)
class _Navigation:
    status: int | None
    html: str


def _navigate(page: Page, url: str, mode: RenderMode) -> _Navigation:
    """Navigate and settle; a slow page is still worth extracting from."""
    wait_until: Literal["load", "domcontentloaded"] = (
        "load" if mode is RenderMode.LIVE else "domcontentloaded"
    )
    navigation = _Navigation(status=None, html="")
    try:
        response = page.goto(url, wait_until=wait_until, timeout=_GOTO_TIMEOUT_MS)
        if response is not None:
            navigation = _Navigation(status=response.status, html=_body_text(response))
    except PlaywrightTimeoutError:
        logger.info("render of %s hit the %s timeout; using partial DOM", url, mode)
    try:
        page.wait_for_load_state("networkidle", timeout=_SETTLE_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(_POST_SETTLE_MS)
    return navigation


def _body_text(response: Response) -> str:
    # The served body only feeds size heuristics; the rendered DOM is the
    # primary artefact, so a body that is no longer available is not an error.
    try:
        return response.text()
    except PlaywrightError:
        return ""


class PlaywrightRenderer:
    def __init__(
        self,
        *,
        device_name: str = _DEVICE_NAME,
        url_guard: UrlGuard | None = None,
    ) -> None:
        self._device_name = device_name
        # Injected so tests can render file:// fixtures; production keeps the
        # public-network guard.
        self._url_guard = url_guard if url_guard is not None else ensure_public_http_url

    def render(self, url: str, *, mode: RenderMode = RenderMode.LIVE) -> RenderedPage:
        self._url_guard(url)
        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch()
                except PlaywrightError as exc:
                    raise RenderError(
                        "could not launch Chromium; run `playwright install "
                        "chromium` or set NANONERD_RENDERER=httpx"
                    ) from exc
                context = browser.new_context(
                    **playwright.devices[self._device_name],
                    bypass_csp=True,
                    locale="en-US",
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                try:
                    page = context.new_page()
                    page.route(
                        "**/*",
                        lambda route: _route_request(route, self._url_guard, mode),
                    )
                    navigation = _navigate(page, url, mode)
                    dom_html = _dom_html(page)
                    # Relative image/link URLs must resolve against the URL
                    # the page actually landed on (redirects, trailing slash).
                    readable = _try_extract(page, page.url)
                    return RenderedPage(
                        url=url,
                        final_url=page.url,
                        status=navigation.status,
                        html=navigation.html,
                        dom_html=dom_html,
                        readable=readable,
                    )
                finally:
                    context.close()
                    browser.close()
        except PlaywrightError as exc:
            raise RenderError(f"render of {url} failed: {exc}") from exc


def _try_extract(page: Page, url: str) -> ReadableContent | None:
    try:
        return extract_readable(page, url)
    except ExtractionError:
        logger.warning("in-page extraction failed for %s", url, exc_info=True)
        return None


class HttpxRenderer:
    """Plain HTTP fetch; no JavaScript, no in-page extraction."""

    def render(self, url: str, *, mode: RenderMode = RenderMode.LIVE) -> RenderedPage:
        response = fetch_response(url)
        return RenderedPage(
            url=url,
            final_url=str(response.url),
            status=response.status_code,
            html=response.text,
            dom_html=response.text,
            readable=None,
        )


def renderer_from_env() -> Renderer:
    choice = os.environ.get("NANONERD_RENDERER", "playwright").strip().lower()
    if choice == "httpx":
        return HttpxRenderer()
    if choice == "playwright":
        return PlaywrightRenderer()
    raise RenderError(f"unknown NANONERD_RENDERER value: {choice!r}")


__all__ = [
    "HttpxRenderer",
    "PlaywrightRenderer",
    "RenderMode",
    "RenderedPage",
    "Renderer",
    "renderer_from_env",
]
