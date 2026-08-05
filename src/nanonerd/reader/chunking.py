from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from lxml import html as lxml_html

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
    """One chunk per block element (paragraph, heading, blockquote, ...)."""
    root = lxml_html.fragment_fromstring(content_html, create_parent="div")
    _sanitize_hrefs(root)
    blocks: list[_Element] = [child for child in root if isinstance(child.tag, str)]
    return [
        ChunkData(html=_serialize([block]), word_count=_word_count(block))
        for block in blocks
    ]
