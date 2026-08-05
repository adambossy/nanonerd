from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from lxml import html as lxml_html

MIN_CHUNK_WORDS = 150
MAX_CHUNK_WORDS = 300
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SAFE_HREF_SCHEMES = {"", "http", "https", "mailto"}


class _Element(Protocol):
    tag: str | object
    attrib: MutableMapping[str, str]

    def text_content(self) -> str: ...
    def get(self, key: str) -> str | None: ...
    def iter(self, tag: str) -> Iterator["_Element"]: ...


@dataclass
class ChunkData:
    html: str
    word_count: int


def html_to_text(content_html: str) -> str:
    root = lxml_html.fragment_fromstring(content_html, create_parent="div")
    return " ".join(root.text_content().split())


def _word_count(element: _Element) -> int:
    return len(element.text_content().split())


def _serialize(elements: list[_Element]) -> str:
    return "".join(
        lxml_html.tostring(element, encoding="unicode") for element in elements
    )


def _sanitize_hrefs(root: _Element) -> None:
    """Strip hrefs with unsafe schemes (e.g. javascript:) from anchor tags."""
    for anchor in root.iter("a"):
        href = anchor.get("href")
        if href is None:
            continue
        scheme = urlsplit(href).scheme.lower()
        if scheme not in _SAFE_HREF_SCHEMES:
            del anchor.attrib["href"]


def chunk_html(content_html: str) -> list[ChunkData]:
    root = lxml_html.fragment_fromstring(content_html, create_parent="div")
    _sanitize_hrefs(root)
    blocks: list[_Element] = [child for child in root if isinstance(child.tag, str)]

    chunks: list[ChunkData] = []
    current: list[_Element] = []
    current_words = 0

    def flush() -> None:
        nonlocal current, current_words
        if current:
            chunks.append(ChunkData(html=_serialize(current), word_count=current_words))
        current = []
        current_words = 0

    for block in blocks:
        words = _word_count(block)
        starts_section = block.tag in _HEADING_TAGS
        would_overflow = (
            current_words >= MIN_CHUNK_WORDS and current_words + words > MAX_CHUNK_WORDS
        )
        if current and (starts_section or would_overflow):
            flush()
        current.append(block)
        current_words += words
    flush()

    return chunks
