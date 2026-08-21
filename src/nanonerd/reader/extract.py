from dataclasses import dataclass

import trafilatura

from nanonerd.reader.render import RenderedPage


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


def extract_article(html: str, url: str) -> Extraction | None:
    """Corpus-style extraction with trafilatura (no browser needed)."""
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


def extract_rendered(rendered: RenderedPage) -> Extraction | None:
    """Prefer the in-page Defuddle result; fall back to trafilatura on the DOM."""
    readable = rendered.readable
    if readable is not None and readable.content_html.strip():
        return Extraction(
            title=readable.title,
            author=readable.author,
            site_name=readable.site,
            content_html=readable.content_html,
        )
    source = rendered.dom_html or rendered.html
    if not source.strip():
        return None
    return extract_article(source, rendered.final_url or rendered.url)
