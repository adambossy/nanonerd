"""Render a URL in headless Chromium at a phone viewport and return the post-JS
DOM plus the CSS/font/image responses the page loaded (for inlining)."""

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any, cast

from playwright.sync_api import Error as PlaywrightError, Response, sync_playwright

from nanonerd.reader.snapshot.css import Resource

_JS_DIR = Path(__file__).resolve().parent
_PREPARE_JS = (_JS_DIR / "prepare_page.js").read_text(encoding="utf-8")
_SERIALIZE_JS = (_JS_DIR / "serialize_page.js").read_text(encoding="utf-8")

DEVICE_NAME = "iPhone 13"
# The device descriptor asks for 3x; 2x keeps srcset choices (and bytes) sane.
DEVICE_SCALE_FACTOR = 2
_RESOURCE_TYPES = frozenset({"stylesheet", "font", "image"})
_RESOURCE_CONTENT_PREFIXES = ("text/css", "font/", "image/", "application/font")

# Chromium is memory-hungry; never render two pages at once on a small box.
_capture_lock = threading.Lock()


class SnapshotCaptureError(RuntimeError):
    """Raised when the page could not be rendered or serialized."""


@dataclass(frozen=True, slots=True)
class CaptureLimits:
    navigation_timeout_s: float = 30.0
    idle_timeout_s: float = 8.0
    scroll_time_s: float = 6.0
    max_resource_bytes: int = 1_500_000
    max_total_resource_bytes: int = 16_000_000


@dataclass(frozen=True, slots=True)
class CapturedPage:
    url: str
    html: str
    resources: dict[str, Resource] = field(default_factory=dict)


def _wants_body(response: Response) -> bool:
    if not response.ok:
        return False
    if response.request.resource_type in _RESOURCE_TYPES:
        return True
    content_type = (response.headers.get("content-type") or "").lower()
    return content_type.startswith(_RESOURCE_CONTENT_PREFIXES)


def _harvest(responses: list[Response], limits: CaptureLimits) -> dict[str, Resource]:
    resources: dict[str, Resource] = {}
    total = 0
    for response in responses:
        if response.url in resources or not _wants_body(response):
            continue
        try:
            body = response.body()
        except PlaywrightError:
            continue
        if len(body) > limits.max_resource_bytes:
            continue
        if total + len(body) > limits.max_total_resource_bytes:
            break
        total += len(body)
        content_type = (response.headers.get("content-type") or "").split(";")[0]
        resources[response.url] = Resource(content_type=content_type.strip(), body=body)
    return resources


def _settle(page: Any, limits: CaptureLimits) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=limits.idle_timeout_s * 1000)
    except PlaywrightError:
        pass  # bounded wait; busy pages (analytics, polling) never go idle


def _render(page: Any, url: str, limits: CaptureLimits) -> CapturedPage:
    responses: list[Response] = []
    page.on("response", lambda response: responses.append(response))
    page.goto(url, wait_until="load", timeout=limits.navigation_timeout_s * 1000)
    _settle(page, limits)
    page.evaluate(_PREPARE_JS, int(limits.scroll_time_s * 1000))
    _settle(page, limits)
    result = cast(dict[str, str], page.evaluate(_SERIALIZE_JS))
    resources = _harvest(responses, limits)
    return CapturedPage(url=result["url"], html=result["html"], resources=resources)


def capture_page(url: str, *, limits: CaptureLimits | None = None) -> CapturedPage:
    """Render ``url`` at a phone viewport and serialize the resulting DOM."""
    limits = limits or CaptureLimits()
    with _capture_lock:
        try:
            with sync_playwright() as playwright:
                device = dict(playwright.devices[DEVICE_NAME])
                device["device_scale_factor"] = DEVICE_SCALE_FACTOR
                device.pop("default_browser_type", None)
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(**device)
                    page = context.new_page()
                    return _render(page, url, limits)
                finally:
                    browser.close()
        except PlaywrightError as exc:
            raise SnapshotCaptureError(f"could not capture {url}: {exc}") from exc
