import httpx
import pytest

from nanonerd.reader.acquire import acquire_article, blocked_reason
from nanonerd.reader.defuddle import ReadableContent
from nanonerd.reader.errors import ExtractionError, FetchError, RenderError
from nanonerd.reader.extract import Extraction, NotArticleError
from nanonerd.reader.render import RenderedPage, RenderMode

URL = "https://news.example/story"
ARCHIVE_PH_URL = "https://archive.ph/abc/https://news.example/story"
WAYBACK_URL = "https://web.archive.org/web/2026/https://news.example/story"
LONG_TEXT = " ".join(f"word{i}" for i in range(400))
ARTICLE_HTML = f"<h2>Story</h2><p>{LONG_TEXT}</p>"


def readable(content_html=ARTICLE_HTML, title="Story"):
    return ReadableContent(
        title=title,
        author="Ann",
        site="News",
        word_count=400,
        content_html=content_html,
    )


def rendered(url=URL, *, status=200, readable_content=None, dom_html=None, html=""):
    return RenderedPage(
        url=url,
        final_url=url,
        status=status,
        html=html,
        dom_html=dom_html
        if dom_html is not None
        else f"<html><body>{ARTICLE_HTML}</body></html>",
        readable=readable_content,
    )


class FakeRenderer:
    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def render(self, url, *, mode=RenderMode.LIVE):
        self.calls.append((url, mode))
        page = self._pages.get(url)
        if page is None:
            raise RenderError(f"no page for {url}")
        return page


class NullStorage:
    def put(self, key, data, content_type):
        return f"https://cdn.example/{key}"


def create_client(archive_ph=None, wayback=None):
    """Archive lookups answer from canned data; the submit endpoint always 404s
    so no polling (and no sleeping) happens in tests."""

    def handler(request):
        url = str(request.url)
        if url.startswith("https://archive.ph/timemap/") and archive_ph:
            return httpx.Response(
                200, text=f'<http://{archive_ph[8:]}>; rel="last memento"\n'
            )
        if url.startswith("https://web.archive.org/cdx/") and wayback:
            return httpx.Response(200, json=[["timestamp"], ["2026"]])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def extraction(content_html=ARTICLE_HTML):
    return Extraction(
        title="Story", author=None, site_name=None, content_html=content_html
    )


@pytest.mark.parametrize(
    ("page", "extracted", "expected"),
    [
        (rendered(status=403, readable_content=readable()), extraction(), "http 403"),
        (rendered(status=429), extraction(), "http 429"),
        (
            rendered(
                dom_html="<body>Please enable JS and disable any ad blocker</body>"
            ),
            extraction("<p>Please enable JS</p>"),
            "marker 'please enable js and disable any ad blocker'",
        ),
        (
            rendered(dom_html='<iframe src="https://geo.captcha-delivery.com/x">'),
            None,
            "marker 'captcha-delivery.com'",
        ),
        (rendered(dom_html="<html></html>"), None, "no extractable content"),
        (
            rendered(dom_html="<html>" + "x" * 60_000 + "</html>"),
            extraction("<p>only a few words here</p>"),
            "thin extraction (5 words from 60013 bytes)",
        ),
        (rendered(), extraction(), None),
        (rendered(dom_html="<html>short page</html>"), extraction("<p>tiny</p>"), None),
    ],
)
def test_blocked_reason(
    page: RenderedPage, extracted: Extraction | None, expected: str | None
) -> None:
    assert blocked_reason(page, extracted) == expected


def test_acquire_article_uses_live_render_when_clean():
    renderer = FakeRenderer({URL: rendered(readable_content=readable())})

    output = acquire_article(
        URL,
        article_id=1,
        renderer=renderer,
        storage=NullStorage(),
        client=create_client(),
    )

    summary = {
        "title": output.title,
        "author": output.author,
        "site_name": output.site_name,
        "source_kind": output.source_kind,
        "source_url": output.source_url,
        "starts_with": output.content_html[:30],
        "calls": renderer.calls,
    }
    expected_output = {
        "title": "Story",
        "author": "Ann",
        "site_name": "News",
        "source_kind": "live",
        "source_url": URL,
        "starts_with": "<h2>Story</h2><p>word0 word1 w",
        "calls": [(URL, RenderMode.LIVE)],
    }
    assert summary == expected_output


def test_acquire_article_falls_back_to_archive_ph_when_blocked():
    renderer = FakeRenderer(
        {
            URL: rendered(status=403, dom_html="<html>captcha-delivery.com</html>"),
            ARCHIVE_PH_URL: rendered(ARCHIVE_PH_URL, readable_content=readable()),
        }
    )

    output = acquire_article(
        URL,
        article_id=1,
        renderer=renderer,
        storage=NullStorage(),
        client=create_client(archive_ph=ARCHIVE_PH_URL),
    )

    summary = (output.source_kind, output.source_url, renderer.calls)
    expected_output = (
        "archive_ph",
        ARCHIVE_PH_URL,
        [(URL, RenderMode.LIVE), (ARCHIVE_PH_URL, RenderMode.ARCHIVE)],
    )
    assert summary == expected_output


def test_acquire_article_skips_captcha_walled_archive_and_uses_wayback():
    renderer = FakeRenderer(
        {
            URL: rendered(status=403),
            ARCHIVE_PH_URL: rendered(
                ARCHIVE_PH_URL, status=429, dom_html="<h2>One more step</h2>"
            ),
            WAYBACK_URL: rendered(WAYBACK_URL, readable_content=readable()),
        }
    )

    output = acquire_article(
        URL,
        article_id=1,
        renderer=renderer,
        storage=NullStorage(),
        client=create_client(archive_ph=ARCHIVE_PH_URL, wayback=WAYBACK_URL),
    )

    assert (output.source_kind, output.source_url) == ("wayback", WAYBACK_URL)


def test_acquire_article_accepts_thin_live_copy_when_no_archive_exists():
    # One real paragraph (clears the prose gate) but far under the 150-word
    # thin-extraction threshold on a 60 KB page.
    short_prose = "<p>" + " ".join(f"short{i}" for i in range(40)) + "</p>"
    thin = ReadableContent(
        title="Short",
        author=None,
        site=None,
        word_count=40,
        content_html=short_prose,
    )
    renderer = FakeRenderer(
        {URL: rendered(readable_content=thin, dom_html="<html>" + "x" * 60_000)}
    )

    output = acquire_article(
        URL,
        article_id=1,
        renderer=renderer,
        storage=NullStorage(),
        client=create_client(),
    )

    assert (output.source_kind, output.content_html) == ("live", short_prose)


def test_acquire_article_raises_fetch_error_with_wall_when_blocked_everywhere():
    wall_html = "<html>captcha-delivery.com</html>"
    renderer = FakeRenderer({URL: rendered(status=403, dom_html=wall_html)})

    with pytest.raises(FetchError, match="http 403") as raised:
        acquire_article(
            URL,
            article_id=1,
            renderer=renderer,
            storage=NullStorage(),
            client=create_client(),
        )
    assert (raised.value.status_code, raised.value.body) == (403, wall_html)


def test_acquire_article_rejects_product_pages_from_rendered_dom():
    product_dom = (
        "<html><head><meta property='og:type' content='product.group'></head>"
        f"<body>{ARTICLE_HTML}</body></html>"
    )
    renderer = FakeRenderer(
        {URL: rendered(readable_content=readable(), dom_html=product_dom)}
    )

    with pytest.raises(NotArticleError, match="og:type is product.group") as raised:
        acquire_article(
            URL,
            article_id=1,
            renderer=renderer,
            storage=NullStorage(),
            client=create_client(),
        )
    assert (raised.value.status_code, raised.value.body) == (200, product_dom)


def test_acquire_article_rejects_listings_without_prose():
    listing = "".join(f"<p>Product {i} $99</p>" for i in range(40))
    renderer = FakeRenderer({URL: rendered(readable_content=readable(listing))})

    with pytest.raises(NotArticleError, match="longest block has 3 words"):
        acquire_article(
            URL,
            article_id=1,
            renderer=renderer,
            storage=NullStorage(),
            client=create_client(),
        )


def test_acquire_article_exposes_rendered_dom_and_status_for_the_judge():
    renderer = FakeRenderer({URL: rendered(readable_content=readable())})

    output = acquire_article(
        URL,
        article_id=1,
        renderer=renderer,
        storage=NullStorage(),
        client=create_client(),
    )

    assert (output.http_status, output.source_html) == (
        200,
        f"<html><body>{ARTICLE_HTML}</body></html>",
    )


def test_acquire_article_raises_when_live_render_fails_and_no_archive():
    renderer = FakeRenderer({})

    with pytest.raises(ExtractionError, match="render failed"):
        acquire_article(
            URL,
            article_id=1,
            renderer=renderer,
            storage=NullStorage(),
            client=create_client(),
        )


def test_acquire_article_sanitizes_and_prefixes_ids():
    content = (
        '<div><p>Ref<sup id="fnref:1"><a href="#fn:1">1</a></sup> '
        + LONG_TEXT
        + '</p><script>x()</script><div id="footnotes"><ol><li id="fn:1">note</li>'
        "</ol></div></div>"
    )
    renderer = FakeRenderer({URL: rendered(readable_content=readable(content))})

    output = acquire_article(
        URL,
        article_id=1,
        renderer=renderer,
        storage=NullStorage(),
        client=create_client(),
    )

    summary = {
        "has_script": "<script" in output.content_html,
        "has_prefixed_ref": 'id="nn-fnref:1"' in output.content_html,
        "has_prefixed_link": 'href="#nn-fn:1"' in output.content_html,
        "footnote_li": '<li id="nn-fn:1">note</li>' in output.content_html,
    }
    expected_output = {
        "has_script": False,
        "has_prefixed_ref": True,
        "has_prefixed_link": True,
        "footnote_li": True,
    }
    assert summary == expected_output
