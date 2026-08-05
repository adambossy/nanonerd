from dataclasses import dataclass
from typing import Protocol

from lxml import html as lxml_html

MIN_CHUNK_WORDS = 150
MAX_CHUNK_WORDS = 300
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _Element(Protocol):
    tag: str | object

    def text_content(self) -> str: ...


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


def chunk_html(content_html: str) -> list[ChunkData]:
    root = lxml_html.fragment_fromstring(content_html, create_parent="div")
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
