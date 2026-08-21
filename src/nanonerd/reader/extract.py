from dataclasses import dataclass
from urllib.parse import urlsplit

from lxml import etree
import trafilatura
from trafilatura.htmlprocessing import convert_to_html
from trafilatura.settings import Document

from nanonerd.reader.chunking import chunk_html
from nanonerd.reader.errors import FetchError
from nanonerd.reader.fetch import ensure_public_http_url, fetch_html
from nanonerd.reader.normalize import (
    HtmlNode,
    absolutize_urls,
    drop_duplicate_title,
    normalize_content,
    parse_document,
)
from nanonerd.reader.render import RenderedPage

# Kept under their historical names: the judge CLI, reprocess and tests
# import the fetch helpers from here.
_ensure_public_http_url = ensure_public_http_url

# A page with no block of at least this many words is a listing, a captcha
# wall or a product grid, not prose worth reading.
MIN_PROSE_BLOCK_WORDS = 20
_NON_ARTICLE_OG_TYPES = ("product",)
_PAGE_URL_SOURCES = (
    (".//link[@rel='canonical']", "href"),
    (".//meta[@property='og:url']", "content"),
)
_RAW_URL_ATTRIBUTES = (
    ("a", "href"),
    ("img", "src"),
    ("img", "data-src"),
    ("source", "src"),
    ("source", "data-src"),
)


class NotArticleError(ValueError):
    """The page fetched fine but is not a readable article.

    `status_code`/`body` carry what was served so the fidelity judge can
    still see the page; they are optional because the trafilatura path
    raises before any HTTP context is known.
    """

    def __init__(
        self, message: str, *, status_code: int | None = None, body: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class Extraction:
    title: str | None
    author: str | None
    site_name: str | None
    content_html: str


def _clean(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_document(html: str) -> HtmlNode | None:
    try:
        return parse_document(html)
    except (etree.ParserError, ValueError):
        return None


def _attribute_of(doc: HtmlNode, path: str, attribute: str) -> str | None:
    element = doc.find(path)
    if element is None:
        return None
    return _clean(element.get(attribute))


def _same_host(candidate: str, url: str) -> bool:
    return urlsplit(candidate).hostname == urlsplit(url).hostname


def resolve_base_url(doc: HtmlNode, url: str) -> str:
    """Pick the URL relative links should resolve against.

    The stored URL is normalized (trailing slash dropped), so a page served at
    ``/posts/x/`` with ``<img src="fig.png">`` would otherwise resolve to
    ``/posts/fig.png``. Prefer the page's own idea of its location.
    """
    base_href = _attribute_of(doc, ".//base", "href")
    if base_href:
        return base_href
    for path, attribute in _PAGE_URL_SOURCES:
        candidate = _attribute_of(doc, path, attribute)
        if candidate and _same_host(candidate, url):
            return candidate
    return url


def _reject_non_article_page(doc: HtmlNode) -> None:
    og_type = (
        _attribute_of(doc, ".//meta[@property='og:type']", "content") or ""
    ).lower()
    if og_type.startswith(_NON_ARTICLE_OG_TYPES):
        raise NotArticleError(f"not an article: og:type is {og_type}")


def _reject_non_prose_content(content_html: str) -> None:
    chunks = chunk_html(content_html)
    longest = max((chunk.word_count for chunk in chunks), default=0)
    if longest < MIN_PROSE_BLOCK_WORDS:
        raise NotArticleError(
            f"not an article: longest block has {longest} words "
            f"(need {MIN_PROSE_BLOCK_WORDS})"
        )


def _body_to_html(body: etree._Element) -> str:
    # convert_to_html drops the rend attribute that distinguishes <ol> from
    # <ul>, so remember ordered lists before converting and restore them.
    ordered = [element for element in body.iter("list") if element.get("rend") == "ol"]
    html_tree = convert_to_html(body)
    for element in ordered:
        element.tag = "ol"
    html_body = html_tree.find("body")
    if html_body is None:
        return ""
    serialized = etree.tostring(html_body, method="html", encoding="unicode")
    return serialized if isinstance(serialized, str) else serialized.decode()


def _bare_extract(doc: HtmlNode, base_url: str) -> Document | None:
    result = trafilatura.bare_extraction(
        doc,
        url=base_url,
        with_metadata=True,
        include_links=True,
        include_images=True,
        include_formatting=True,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )
    if not isinstance(result, Document) or result.body is None:
        return None
    return result


def extract_article(html: str, url: str) -> Extraction | None:
    """Corpus-style extraction with trafilatura (no browser needed)."""
    doc = _parse_document(html)
    if doc is None:
        return None
    _reject_non_article_page(doc)
    base_url = resolve_base_url(doc, url)
    # trafilatura resolves relative links against the host only, so make them
    # absolute against the real page location before it sees them.
    absolutize_urls(doc, base_url, attributes=_RAW_URL_ATTRIBUTES)

    document = _bare_extract(doc, base_url)
    if document is None:
        return None
    title = _clean(document.title)
    content_html = normalize_content(_body_to_html(document.body), base_url=base_url)
    content_html = drop_duplicate_title(content_html, title)
    if not content_html:
        return None
    _reject_non_prose_content(content_html)

    return Extraction(
        title=title,
        author=_clean(document.author),
        site_name=_clean(document.sitename),
        content_html=content_html,
    )


def extract_rendered(rendered: RenderedPage) -> Extraction | None:
    """Prefer the in-page Defuddle result; fall back to trafilatura on the DOM.

    The same not-an-article gate applies to both paths: product pages are
    rejected from the rendered DOM's metadata and listings from the lack of
    any prose block in the extracted content.
    """
    source = rendered.dom_html or rendered.html
    readable = rendered.readable
    if readable is None or not readable.content_html.strip():
        if not source.strip():
            return None
        return extract_article(source, rendered.final_url or rendered.url)
    doc = _parse_document(source)
    if doc is not None:
        _reject_non_article_page(doc)
    _reject_non_prose_content(readable.content_html)
    return Extraction(
        title=readable.title,
        author=readable.author,
        site_name=readable.site,
        content_html=readable.content_html,
    )


__all__ = [
    "Extraction",
    "FetchError",
    "NotArticleError",
    "extract_article",
    "extract_rendered",
    "fetch_html",
    "resolve_base_url",
]
