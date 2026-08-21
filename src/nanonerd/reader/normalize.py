"""Post-extraction cleanup of article HTML.

Trafilatura's HTML output is structurally noisy for a reader: inline ``<code>``
comes back as ``<pre>`` (sometimes hoisted out of its paragraph with the rest of
the sentence left dangling as tail text), wrapper ``<div>`` containers hide the
real blocks, heading permalink anchors leak as ``#``, and relative URLs survive.
This module fixes the DOM and sanitizes the result with an allowlist so every
top-level element is a self-contained block suitable for chunking.
"""

from collections.abc import Iterator
from typing import Protocol, cast
from urllib.parse import urljoin

from lxml import html as lxml_html
import nh3


class HtmlNode(Protocol):
    """The slice of lxml.html.HtmlElement this module relies on."""

    tag: str | object
    text: str | None
    tail: str | None

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def iter(self, *tags: str) -> Iterator["HtmlNode"]: ...
    def find(self, path: str) -> "HtmlNode | None": ...
    def getparent(self) -> "HtmlNode | None": ...
    def getprevious(self) -> "HtmlNode | None": ...
    def remove(self, child: "HtmlNode") -> None: ...
    def append(self, child: "HtmlNode") -> None: ...
    def replace(self, old: "HtmlNode", new: "HtmlNode") -> None: ...
    def drop_tag(self) -> None: ...
    def drop_tree(self) -> None: ...
    def text_content(self) -> str: ...
    def __iter__(self) -> Iterator["HtmlNode"]: ...
    def __len__(self) -> int: ...
    def __getitem__(self, index: int) -> "HtmlNode": ...


ALLOWED_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "br",
        "hr",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "strong",
        "em",
        "b",
        "i",
        "sup",
        "sub",
        "a",
        "img",
        "figure",
        "figcaption",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)
_ALLOWED_ATTRIBUTES = {"a": {"href"}, "img": {"src", "alt", "width", "height"}}
_URL_SCHEMES = {"http", "https", "mailto"}

# Elements that stand on their own as a reading chunk. Anything else found at
# the top level is inline content and gets grouped into a paragraph.
BLOCK_TAGS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "dl",
        "blockquote",
        "pre",
        "table",
        "figure",
        "img",
        "hr",
    }
)
_CONTAINER_TAGS = frozenset(
    {"div", "section", "article", "main", "header", "footer", "aside", "details"}
)
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_ANCHOR_MARKERS = frozenset({"#", "¶", "§", "🔗", "🔗︎", "#️⃣", "permalink", "anchor"})
_ANCHOR_MARKER_CHARS = "#¶§🔗︎️⃣ \t\n"
_SENTENCE_END_CHARS = '.!?:;"”’)]'
_URL_ATTRIBUTES = (("a", "href"), ("img", "src"))


def sanitize_html(html: str) -> str:
    """Allowlist-sanitize a fragment (tags, attributes, URL schemes)."""
    return nh3.clean(
        html,
        tags=set(ALLOWED_TAGS),
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_URL_SCHEMES,
        link_rel=None,
    )


def parse_fragment(content_html: str) -> HtmlNode:
    return cast(
        HtmlNode, lxml_html.fragment_fromstring(content_html, create_parent="div")
    )


def parse_document(html: str) -> HtmlNode:
    return cast(HtmlNode, lxml_html.document_fromstring(html))


def to_html(node: HtmlNode) -> str:
    return str(lxml_html.tostring(node, encoding="unicode"))


def serialize_children(root: HtmlNode) -> str:
    parts = [root.text or ""]
    parts.extend(to_html(child) for child in root)
    return "".join(parts)


def normalize_content(content_html: str, *, base_url: str) -> str:
    """Return sanitized HTML whose top-level elements are all reading blocks."""
    root = parse_fragment(content_html)
    unwrap_containers(root)
    _unwrap_nested_pre(root)
    _inline_pre_to_code(root)
    _strip_heading_anchors(root)
    absolutize_urls(root, base_url)
    wrap_inline_runs(root)
    return sanitize_html(serialize_children(root))


def drop_duplicate_title(content_html: str, title: str | None) -> str:
    """Remove a leading <h1> that repeats the article title the reader shows."""
    if not title:
        return content_html
    root = parse_fragment(content_html)
    first = root[0] if len(root) else None
    if first is None or first.tag != "h1":
        return content_html
    if (
        " ".join(first.text_content().split()).lower()
        != " ".join(title.split()).lower()
    ):
        return content_html
    root.remove(first)
    return serialize_children(root)


def unwrap_containers(root: HtmlNode) -> None:
    """Hoist children of wrapper containers (div, section, ...) up to root."""
    while True:
        containers = [child for child in root if child.tag in _CONTAINER_TAGS]
        if not containers:
            return
        for container in containers:
            container.drop_tag()


def _detach_children_with_tails(root: HtmlNode) -> list[str | HtmlNode]:
    """Pull root's content out as an ordered list of text runs and elements."""
    nodes: list[str | HtmlNode] = []
    if root.text:
        nodes.append(root.text)
        root.text = None
    for child in list(root):
        tail = child.tail
        child.tail = None
        root.remove(child)
        if isinstance(child.tag, str):
            nodes.append(child)
        if tail:
            nodes.append(tail)
    return nodes


def _append_inline(target: HtmlNode, node: str | HtmlNode) -> None:
    if isinstance(node, str):
        if len(target) == 0:
            target.text = (target.text or "") + node
        else:
            last = target[-1]
            last.tail = (last.tail or "") + node
        return
    target.append(node)


def _ends_mid_sentence(paragraph: HtmlNode) -> bool:
    text = paragraph.text_content().rstrip()
    return bool(text) and text[-1] not in _SENTENCE_END_CHARS


def _run_has_content(run: list[str | HtmlNode]) -> bool:
    for node in run:
        if isinstance(node, str):
            if node.strip():
                return True
        elif node.tag == "img" or node.text_content().strip():
            return True
    return False


def _trim_run(run: list[str | HtmlNode]) -> list[str | HtmlNode]:
    """Drop leading/trailing whitespace-only text so paragraphs start clean."""
    trimmed = list(run)
    while trimmed and isinstance(trimmed[0], str) and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and isinstance(trimmed[-1], str) and not trimmed[-1].strip():
        trimmed.pop()
    if trimmed and isinstance(trimmed[0], str):
        trimmed[0] = trimmed[0].lstrip()
    if trimmed and isinstance(trimmed[-1], str):
        trimmed[-1] = trimmed[-1].rstrip()
    return trimmed


def _new_element(tag: str) -> HtmlNode:
    return cast(HtmlNode, lxml_html.Element(tag))


def _flush_run(root: HtmlNode, run: list[str | HtmlNode]) -> None:
    if not _run_has_content(run):
        return
    run = _trim_run(run)
    previous = root[-1] if len(root) else None
    if previous is not None and previous.tag == "p" and _ends_mid_sentence(previous):
        # The run is the rest of a sentence trafilatura split off: rejoin it.
        if not previous.text_content().endswith(" "):
            _append_inline(previous, " ")
        for node in run:
            _append_inline(previous, node)
        return
    paragraph = _new_element("p")
    for node in run:
        _append_inline(paragraph, node)
    root.append(paragraph)


def wrap_inline_runs(root: HtmlNode) -> None:
    """Group top-level inline content (text, links, code, ...) into <p> blocks."""
    nodes = _detach_children_with_tails(root)
    run: list[str | HtmlNode] = []
    for node in nodes:
        if isinstance(node, str) or node.tag not in BLOCK_TAGS:
            run.append(node)
            continue
        _flush_run(root, run)
        run = []
        root.append(node)
    _flush_run(root, run)


def _unwrap_nested_pre(root: HtmlNode) -> None:
    for outer in list(root.iter("pre")):
        parent = outer.getparent()
        if parent is None:
            continue
        inner_pres = [child for child in outer if child.tag == "pre"]
        only_child_is_pre = (
            len(outer) == 1
            and len(inner_pres) == 1
            and not (outer.text or "").strip()
            and not (inner_pres[0].tail or "").strip()
        )
        if only_child_is_pre:
            inner = inner_pres[0]
            inner.tail = outer.tail
            parent.replace(outer, inner)
    for outer in list(root.iter("pre")):
        for inner in list(outer.iter("pre")):
            if inner is not outer and inner.getparent() is not None:
                inner.drop_tag()


def _is_single_line(element: HtmlNode) -> bool:
    return "\n" not in element.text_content().strip()


def _looks_inline_at_root(pre: HtmlNode) -> bool:
    if (pre.tail or "").strip():
        return True
    previous = pre.getprevious()
    return previous is not None and previous.tag == "p" and _ends_mid_sentence(previous)


def _inline_pre_to_code(root: HtmlNode) -> None:
    """Undo trafilatura mapping inline <code> to <pre>."""
    for pre in list(root.iter("pre")):
        if not _is_single_line(pre):
            continue
        at_root = pre.getparent() is root
        if not at_root or _looks_inline_at_root(pre):
            pre.tag = "code"


def _strip_anchor_text(heading: HtmlNode) -> None:
    last = heading[-1] if len(heading) else None
    if last is not None:
        if last.tail and last.tail.strip(" \t\n") in _ANCHOR_MARKERS:
            last.tail = None
        return
    if heading.text:
        heading.text = heading.text.rstrip(_ANCHOR_MARKER_CHARS)


def _strip_heading_anchors(root: HtmlNode) -> None:
    for heading in root.iter(*_HEADING_TAGS):
        # Heading links are permalinks to themselves: drop marker-only ones
        # entirely and keep just the text of the rest.
        for anchor in list(heading.iter("a")):
            label = anchor.text_content().strip().lower()
            if label in _ANCHOR_MARKERS or not label:
                anchor.drop_tree()
            else:
                anchor.drop_tag()
        _strip_anchor_text(heading)
        if heading.text:
            heading.text = heading.text.rstrip()


def absolutize_urls(
    root: HtmlNode,
    base_url: str,
    attributes: tuple[tuple[str, str], ...] = _URL_ATTRIBUTES,
) -> None:
    for tag, attribute in attributes:
        for element in root.iter(tag):
            value = element.get(attribute)
            if value:
                element.set(attribute, urljoin(base_url, value.strip()))
