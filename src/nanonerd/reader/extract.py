from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
import trafilatura

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 nanonerd-reader/0.1"
)

_MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


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


def extract_article(html: str, url: str) -> Extraction | None:
    content_html: str | None = trafilatura.extract(
        html,
        url=url,
        output_format="html",
        include_links=True,
        include_images=False,
        favor_recall=True,
    )
    if not content_html:
        return None

    metadata = trafilatura.extract_metadata(html)
    title: str | None = None
    author: str | None = None
    site_name: str | None = None
    if metadata is not None:
        title = _clean(metadata.title)
        author = _clean(metadata.author)
        site_name = _clean(metadata.sitename)

    return Extraction(
        title=title, author=author, site_name=site_name, content_html=content_html
    )
