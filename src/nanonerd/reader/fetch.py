import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from nanonerd.reader.errors import FetchError

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
# Identifies us honestly to archive services, which ask for it.
ARCHIVE_USER_AGENT = "nanonerd-reader/0.1 (+https://github.com/adambossy/nanonerd)"

_MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


def ensure_public_http_url(url: str) -> None:
    """Reject URLs that could be used to reach non-public network resources."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise FetchError("URL has no hostname")

    try:
        addrinfo = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise FetchError(f"could not resolve host {host!r}: {exc}") from exc

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
            raise FetchError(f"URL host {host!r} resolves to a non-public address")


def fetch_response(
    url: str,
    *,
    client: httpx.Client | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET a public URL, following redirects while re-checking each hop."""
    get = client.get if client is not None else httpx.get
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    current = url
    for _ in range(_MAX_REDIRECTS):
        ensure_public_http_url(current)
        try:
            response = get(
                current,
                headers=request_headers,
                follow_redirects=False,
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            raise FetchError(f"request to {current} failed: {exc}") from exc
        location = response.headers.get("location")
        if response.status_code in _REDIRECT_STATUS_CODES and location:
            current = str(httpx.URL(current).join(location))
            continue
        return response
    raise FetchError("too many redirects")


def fetch_html(url: str) -> str:
    """GET a page's HTML; a refused fetch raises with the status and body attached."""
    response = fetch_response(url)
    if response.status_code >= 400:
        raise FetchError(
            f"HTTP {response.status_code} fetching {url}",
            status_code=response.status_code,
            body=response.text,
        )
    return response.text
