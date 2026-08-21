"""Renderer tests. The Playwright cases run only when Chromium is installed."""

from io import BytesIO
from pathlib import Path
import re
import socket

import httpx
from PIL import Image
from playwright.sync_api import Error as PlaywrightError, sync_playwright
import pytest

from nanonerd.reader import render as render_module
from nanonerd.reader.acquire import acquire_article
from nanonerd.reader.chunking import chunk_html
from nanonerd.reader.errors import RenderError
from nanonerd.reader.render import (
    HttpxRenderer,
    PlaywrightRenderer,
    RenderMode,
    renderer_from_env,
)
from nanonerd.reader.storage import LocalStorage

FIXTURE = Path(__file__).parent / "fixtures" / "article.html"


def chromium_available() -> bool:
    try:
        with sync_playwright() as playwright:
            playwright.chromium.launch().close()
        return True
    except PlaywrightError:
        return False


needs_chromium = pytest.mark.skipif(
    not chromium_available(), reason="Playwright Chromium is not installed"
)


def allow_any_url(url: str) -> None:
    return None


def count(tag: str, html: str) -> int:
    return len(re.findall(rf"<{tag}[\s>]", html))


def png_bytes(width=800, height=500):
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def public_dns(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def create_image_client():
    def handler(request):
        if str(request.url) == "https://img.example/loop.png":
            return httpx.Response(
                200, headers={"content-type": "image/png"}, content=png_bytes()
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_httpx_renderer_returns_body_without_readable(monkeypatch):
    def fake_fetch(url, *, client=None, headers=None):
        return httpx.Response(
            200,
            text="<html><body><p>hi</p></body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(render_module, "fetch_response", fake_fetch)
    output = HttpxRenderer().render("https://site.example/a")
    summary = (output.status, output.html, output.dom_html, output.readable)
    expected_output = (
        200,
        "<html><body><p>hi</p></body></html>",
        "<html><body><p>hi</p></body></html>",
        None,
    )
    assert summary == expected_output


def test_renderer_from_env_selects_httpx(monkeypatch):
    monkeypatch.setenv("NANONERD_RENDERER", "httpx")
    assert isinstance(renderer_from_env(), HttpxRenderer)


def test_renderer_from_env_defaults_to_playwright(monkeypatch):
    monkeypatch.delenv("NANONERD_RENDERER", raising=False)
    assert isinstance(renderer_from_env(), PlaywrightRenderer)


def test_renderer_from_env_rejects_unknown(monkeypatch):
    monkeypatch.setenv("NANONERD_RENDERER", "lynx")
    with pytest.raises(RenderError):
        renderer_from_env()


@needs_chromium
def test_playwright_renderer_extracts_readable_content_from_fixture() -> None:
    renderer = PlaywrightRenderer(url_guard=allow_any_url)
    output = renderer.render(FIXTURE.as_uri(), mode=RenderMode.LIVE)
    readable = output.readable
    assert readable is not None
    content = readable.content_html
    summary = {
        "title": readable.title,
        "author": readable.author,
        "site": readable.site,
        "nav_removed": "About" not in content,
        "sidebar_removed": "Other post" not in content,
        "figures": count("figure", content),
        "pre": count("pre", content),
        "math": count("math", content),
        "callouts": content.count("data-callout="),
        "video": count("video", content),
        "audio": count("audio", content),
        "tables": count("table", content),
        "footnote_refs": content.count('href="#fn:'),
        "footnote_backrefs": content.count('href="#fnref:'),
    }
    expected_output = {
        "title": "Harnesses, Briefly",
        "author": "Jane Doe",
        "site": "Fixture Log",
        "nav_removed": True,
        "sidebar_removed": True,
        "figures": 2,
        "pre": 1,
        "math": 2,
        "callouts": 1,
        "video": 1,
        "audio": 1,
        "tables": 1,
        "footnote_refs": 2,
        "footnote_backrefs": 2,
    }
    assert summary == expected_output


@needs_chromium
def test_acquire_article_end_to_end_from_fixture(
    tmp_path: Path, public_dns: None
) -> None:
    storage = LocalStorage(tmp_path / "media", base_url="/media")
    output = acquire_article(
        FIXTURE.as_uri(),
        article_id=42,
        renderer=PlaywrightRenderer(url_guard=allow_any_url),
        storage=storage,
        client=create_image_client(),
    )
    chunks = chunk_html(output.content_html)
    html = output.content_html
    cached_files = sorted(
        p.name for p in (tmp_path / "media" / "articles" / "42").iterdir()
    )
    summary = {
        "source_kind": output.source_kind,
        "images_cached": output.images_cached,
        "cached_files": len(cached_files),
        "img_src_rewritten": f'src="/media/articles/42/{cached_files[0]}"' in html,
        "srcset_dropped": "srcset" not in html,
        "callout_blockquote": '<blockquote data-callout="tip">' in html,
        "code_language": 'class="language-python"' in html,
        "ol_start_kept": '<ol start="3">' in html,
        "ids_prefixed": 'id="nn-fn:1"' in html and 'href="#nn-fnref:1"' in html,
        "mathml_kept": count("math", html) == 2 and "<munder>" in html,
        "chunk_tags": [c.html.split(">")[0].split(" ")[0] for c in chunks],
        "min_words": min(c.word_count for c in chunks),
    }
    expected_output = {
        "source_kind": "live",
        "images_cached": 1,
        "cached_files": 1,
        "img_src_rewritten": True,
        "srcset_dropped": True,
        "callout_blockquote": True,
        "code_language": True,
        "ol_start_kept": True,
        "ids_prefixed": True,
        "mathml_kept": True,
        "chunk_tags": [
            "<p",
            "<figure",
            "<h2",
            "<p",
            "<pre",
            "<blockquote",
            "<h2",
            "<p",
            "<math",
            "<h2",
            "<table",
            "<ol",
            "<h2",
            "<figure",
            "<p",
            "<p",
            "<ol",
            "<ol",
        ],
        "min_words": 1,
    }
    assert summary == expected_output
