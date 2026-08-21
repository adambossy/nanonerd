from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from lxml import etree
import trafilatura
from trafilatura.htmlprocessing import convert_to_html
from trafilatura.settings import Document

from nanonerd.reader.chunking import chunk_html
from nanonerd.reader.normalize import (
    HtmlNode,
    absolutize_urls,
    drop_duplicate_title,
    normalize_content,
    parse_document,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 nanonerd-reader/0.1"
)

_MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}

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
    """The page fetched fine but is not a readable article."""


@dataclass
class Extraction:
    title: str | None
    author: str | None
    site_name: str | None
    content_html: str


def _ensure_public_http_url(url: str) -> None:
    """Reject URLs that could be used to reach non-public network resources."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname")

    try:
        addrinfo = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(f"could not resolve host {host!r}: {exc}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        addr = str(sockaddr[0])
        ip = ipaddress.ip_address(addr)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"URL host {host!r} resolves to a non-public address")


def fetch_html(url: str) -> str:
    current = url
    for _ in range(_MAX_REDIRECTS):
        _ensure_public_http_url(current)
        response = httpx.get(
            current,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
            timeout=20.0,
        )
        location = response.headers.get("location")
        if response.status_code in _REDIRECT_STATUS_CODES and location:
            current = str(httpx.URL(current).join(location))
            continue
        response.raise_for_status()
        return response.text
    raise ValueError("too many redirects")


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
