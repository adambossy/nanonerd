"""Split article HTML into an ordered list of block-level chunks.

Each chunk is something the reader can mark read on its own: a paragraph, a
heading, or an atomic block (figure, code, table, math, media, quote, list).
Container elements are unwrapped recursively; stray inline content between
blocks is gathered into synthetic paragraphs so no text is lost.
"""

from collections.abc import Iterator
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from nanonerd.reader.dom import (
    Element,
    is_real_element,
    new_element,
    parse_fragment,
    serialize_element,
    text_of,
    word_count_of,
)

_SAFE_HREF_SCHEMES = {"", "http", "https", "mailto"}

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
ATOMIC_TAGS = {
    "figure",
    "pre",
    "table",
    "math",
    "video",
    "audio",
    "img",
    "blockquote",
    "ul",
    "ol",
    "dl",
}
BLOCK_TAGS = HEADING_TAGS | ATOMIC_TAGS | {"p", "hr"}
CONTAINER_TAGS = {
    "div",
    "section",
    "article",
    "main",
    "aside",
    "header",
    "footer",
    "nav",
    "details",
    "body",
    "html",
}
MEDIA_TAGS = {"figure", "img", "video", "audio", "math"}
# Dwell-time word-equivalent for chunks whose value is not in their text.
MEDIA_WORDS = 20
_FOOTNOTE_ID = re.compile(r"^(nn-)?fn[:\-_]?\d", re.IGNORECASE)


@dataclass
class ChunkData:
    html: str
    word_count: int


def html_to_text(content_html: str) -> str:
    return " ".join(text_of(parse_fragment(content_html)).split())


def _word_count(element: Element) -> int:
    """Words in the element's own text, its descendants, and descendants' tails."""
    return word_count_of(element)


def _sanitize_hrefs(root: Element) -> None:
    """Strip hrefs with unsafe schemes (e.g. javascript:) from anchor tags."""
    for anchor in root.iter("a"):
        href = anchor.get("href")
        if href is None:
            continue
        scheme = urlsplit(href).scheme.lower()
        if scheme not in _SAFE_HREF_SCHEMES:
            del anchor.attrib["href"]


def _has_words(text: str | None) -> bool:
    return bool(text and text.strip())


class _InlineRun:
    """Accumulates inline nodes between blocks into one synthetic paragraph."""

    def __init__(self) -> None:
        self._paragraph = new_element("p")
        self._dirty = False

    def add_text(self, text: str | None) -> None:
        if not text:
            return
        children = list(self._paragraph)
        if children:
            children[-1].tail = (children[-1].tail or "") + text
        else:
            self._paragraph.text = (self._paragraph.text or "") + text
        self._dirty = self._dirty or _has_words(text)

    def add_element(self, element: Element) -> None:
        self._paragraph.append(element)
        self._dirty = self._dirty or _word_count(element) > 0

    def flush(self) -> Iterator[Element]:
        if self._dirty:
            yield self._paragraph
        self._paragraph = new_element("p")
        self._dirty = False


def _is_footnote_list(element: Element) -> bool:
    if element.tag not in ("ol", "ul"):
        return False
    items = [child for child in element if child.tag == "li"]
    if not items:
        return False
    return all(
        _FOOTNOTE_ID.match(item.get("id") or "")
        or "footnote" in (item.get("class") or "")
        for item in items
    )


def _split_footnotes(footnote_list: Element) -> Iterator[Element]:
    """One chunk per footnote, each wrapped in an `<ol start>` to keep numbering."""
    start = int(footnote_list.get("start") or 1)
    for offset, item in enumerate(list(footnote_list)):
        if item.tag != "li":
            continue
        wrapper = new_element(footnote_list.tag)
        for attr, value in footnote_list.attrib.items():
            if attr != "start":
                wrapper.set(attr, value)
        if footnote_list.tag == "ol":
            wrapper.set("start", str(start + offset))
        item.tail = None
        wrapper.append(item)
        yield wrapper


def _collect_blocks(container: Element) -> Iterator[Element]:
    run = _InlineRun()
    run.add_text(container.text)
    for child in list(container):
        tail = child.tail
        child.tail = None
        if not is_real_element(child):
            run.add_text(tail)
            continue
        tag = child.tag.lower()
        if tag in CONTAINER_TAGS:
            yield from run.flush()
            yield from _collect_blocks(child)
        elif tag in BLOCK_TAGS:
            yield from run.flush()
            if _is_footnote_list(child):
                yield from _split_footnotes(child)
            else:
                yield child
        else:
            run.add_element(child)
        run.add_text(tail)
    yield from run.flush()


def _is_media(block: Element) -> bool:
    if block.tag in MEDIA_TAGS:
        return True
    return any(True for _ in block.iter(*MEDIA_TAGS))


def _to_chunk(block: Element) -> ChunkData | None:
    words = _word_count(block)
    if _is_media(block):
        words = max(words, MEDIA_WORDS)
    if words == 0:
        return None
    return ChunkData(html=serialize_element(block), word_count=words)


def chunk_html(content_html: str) -> list[ChunkData]:
    """One chunk per block element; containers are unwrapped, media kept whole."""
    root = parse_fragment(content_html)
    _sanitize_hrefs(root)
    chunks: list[ChunkData] = []
    for block in _collect_blocks(root):
        chunk = _to_chunk(block)
        if chunk is not None:
            chunks.append(chunk)
    return chunks
