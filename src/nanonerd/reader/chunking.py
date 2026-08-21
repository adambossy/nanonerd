from dataclasses import dataclass

from nanonerd.reader.normalize import (
    HtmlNode,
    flatten_blocks,
    parse_fragment,
    sanitize_html,
    to_html,
)


@dataclass
class ChunkData:
    html: str
    word_count: int


def html_to_text(content_html: str) -> str:
    root = parse_fragment(content_html)
    return " ".join(root.text_content().split())


def _word_count(html: str) -> int:
    return len(html_to_text(html).split())


def _has_image(block: HtmlNode) -> bool:
    return block.tag == "img" or block.find(".//img") is not None


def chunk_html(content_html: str) -> list[ChunkData]:
    """One chunk per block element (paragraph, heading, blockquote, ...).

    Wrapper containers are unwrapped and loose inline content is grouped into
    paragraphs first, so every chunk is a real block and the sum of chunk word
    counts equals the article's word count.
    """
    root = parse_fragment(content_html)
    flatten_blocks(root)
    chunks: list[ChunkData] = []
    for block in root:
        html = sanitize_html(to_html(block))
        word_count = _word_count(html)
        if word_count == 0 and not _has_image(block):
            continue
        chunks.append(ChunkData(html=html, word_count=word_count))
    return chunks
