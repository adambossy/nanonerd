"""Locate archived copies of a URL (archive.ph first, then the Wayback Machine).

Both services are public goods; every request carries an identifying
User-Agent, retries are bounded, and submissions are only made when no
snapshot exists yet.
"""

from collections.abc import Callable
import logging
import re
import time
from urllib.parse import quote

import httpx

from nanonerd.reader.fetch import ARCHIVE_USER_AGENT

logger = logging.getLogger(__name__)

ARCHIVE_PH_BASE = "https://archive.ph"
WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_NEWEST_URL = "https://web.archive.org/web/2/"

_TIMEOUT = httpx.Timeout(30.0)
_LOOKUP_ATTEMPTS = 2
_SUBMIT_POLL_DELAYS = (5.0, 10.0, 20.0)
_MEMENTO_LINE = re.compile(r"<(?P<url>[^>]+)>;\s*rel=\"(?P<rel>[^\"]*memento[^\"]*)\"")
_HEADERS = {"User-Agent": ARCHIVE_USER_AGENT}

SleepFn = Callable[[float], None]


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    # Both archives are slow and occasionally drop connections; one retry
    # catches most transient failures without hammering them.
    for attempt in range(_LOOKUP_ATTEMPTS):
        try:
            return client.get(
                url, headers=_HEADERS, follow_redirects=False, timeout=_TIMEOUT
            )
        except httpx.HTTPError:
            logger.info(
                "archive lookup request failed (attempt %d): %s", attempt + 1, url
            )
    return None


def _latest_memento(timemap: str) -> str | None:
    latest: str | None = None
    for match in _MEMENTO_LINE.finditer(timemap):
        if "memento" in match.group("rel").split():
            latest = match.group("url")
    if latest is None:
        return None
    if latest.startswith("http://"):
        latest = "https://" + latest[len("http://") :]
    return latest


def _archive_ph_timemap(url: str, client: httpx.Client) -> str | None:
    response = _get(client, f"{ARCHIVE_PH_BASE}/timemap/{url}")
    if response is None or response.status_code != 200:
        return None
    return _latest_memento(response.text)


def find_archive_ph_snapshot(
    url: str,
    *,
    client: httpx.Client,
    submit: bool = True,
    sleep_fn: SleepFn | None = None,
) -> str | None:
    """Newest archive.ph memento for `url`, submitting it if none exists yet."""
    if sleep_fn is None:
        sleep_fn = time.sleep
    snapshot = _archive_ph_timemap(url, client)
    if snapshot is not None or not submit:
        return snapshot
    submitted = _get(client, f"{ARCHIVE_PH_BASE}/submit/?url={quote(url, safe='')}")
    if submitted is None or submitted.status_code >= 400:
        return None
    for delay in _SUBMIT_POLL_DELAYS:
        sleep_fn(delay)
        snapshot = _archive_ph_timemap(url, client)
        if snapshot is not None:
            return snapshot
    return None


def _latest_ok_capture(cdx_json: object, url: str) -> str | None:
    # CDX JSON is a header row followed by data rows: [["timestamp"], ["2026..."]].
    if not isinstance(cdx_json, list) or len(cdx_json) < 2:
        return None
    last = cdx_json[-1]
    if not isinstance(last, list) or not last or not isinstance(last[0], str):
        return None
    return f"https://web.archive.org/web/{last[0]}/{url}"


def find_wayback_snapshot(url: str, *, client: httpx.Client) -> str | None:
    """Newest Wayback capture that was stored with HTTP 200."""
    response = _get(
        client,
        f"{WAYBACK_CDX_URL}?url={quote(url, safe='')}&output=json"
        "&fl=timestamp&filter=statuscode:200&limit=-1",
    )
    if response is not None and response.status_code == 200:
        try:
            snapshot = _latest_ok_capture(response.json(), url)
        except ValueError:
            snapshot = None
        if snapshot is not None:
            return snapshot
    # The redirect target is the newest capture regardless of status; it is a
    # last resort when the CDX index is unavailable.
    redirect = _get(client, f"{WAYBACK_NEWEST_URL}{url}")
    if redirect is None or redirect.status_code not in (301, 302, 307, 308):
        return None
    location = redirect.headers.get("location")
    if not location:
        return None
    return str(httpx.URL(WAYBACK_NEWEST_URL).join(location))
