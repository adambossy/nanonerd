from dataclasses import dataclass

import httpx
import trafilatura

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 nanonerd-reader/0.1"
)


@dataclass
class Extraction:
    title: str | None
    author: str | None
    site_name: str | None
    content_html: str


def fetch_html(url: str) -> str:
    response = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=20.0,
    )
    response.raise_for_status()
    return response.text


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
