"""DOM-level declutter + block tagging for captured snapshots (lxml).

Everything here mutates an ``lxml.html`` tree in place. The public pieces:

- :func:`sanitize` strips anything executable.
- :func:`locate_container` finds the article container.
- :func:`remove_chrome` drops navigation/sidebars/footers/junk around and
  inside the container.
- :func:`collect_blocks` returns the real block elements (unwrapping single
  wrappers recursively) that become chunks.
"""

from collections.abc import Iterator
import re

from lxml.etree import _Element

CONTAINER_TAGS = frozenset(
    {"div", "section", "article", "main", "body", "header", "footer", "td"}
)
BLOCK_LEAF_TAGS = frozenset(
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
        "figure",
        "pre",
        "table",
        "img",
        "picture",
        "video",
        "audio",
        "math",
        "mjx-container",
        "details",
        "address",
        "aside",
        "canvas",
    }
)
INLINE_TAGS = frozenset(
    {
        "a",
        "span",
        "em",
        "strong",
        "b",
        "i",
        "u",
        "s",
        "small",
        "sup",
        "sub",
        "mark",
        "time",
        "abbr",
        "cite",
        "q",
        "kbd",
        "code",
        "br",
        "img",
        "svg",
        "picture",
        "label",
        "wbr",
        "var",
        "samp",
        "dfn",
        "del",
        "ins",
        "bdi",
        "bdo",
        "font",
    }
)
MEDIA_TAGS = frozenset(
    {"img", "picture", "video", "audio", "canvas", "math", "mjx-container"}
)
SKIP_TAGS = frozenset(
    {"style", "script", "link", "meta", "template", "br", "hr", "noscript"}
)

EXECUTABLE_TAGS = frozenset(
    {
        "script",
        "noscript",
        "iframe",
        "frame",
        "frameset",
        "object",
        "embed",
        "applet",
        "template",
        "base",
        "input",
        "select",
        "textarea",
        "button",
    }
)
URL_ATTRS = ("href", "src", "action", "formaction", "xlink:href", "data", "poster")
_UNSAFE_SCHEME_RE = re.compile(
    r"^\s*(javascript|vbscript|data:text/html)", re.IGNORECASE
)


JUNK_TAGS = frozenset({"div", "section", "aside", "form", "footer", "nav", "ul", "ol"})
JUNK_TOKENS = frozenset(
    {
        "share",
        "sharing",
        "social",
        "subscribe",
        "subscription",
        "newsletter",
        "signup",
        "comments",
        "commentlist",
        "related",
        "recommended",
        "promo",
        "sidebar",
        "advert",
        "advertisement",
        "ads",
        "adslot",
        "cookie",
        "popup",
        "modal",
        "banner",
        "breadcrumb",
        "breadcrumbs",
        "paywall",
    }
)
_TOKEN_SPLIT_RE = re.compile(r"[_\-]+")
# Tailwind-style arbitrary/variant classes (lg:sticky, [&.x]:y, w-[calc()])
# carry no semantic meaning; only plain class names are keyword-matched.
_PLAIN_CLASS_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
# Screen-reader-only helpers: invisible, but would otherwise become chunks.
SR_ONLY_CLASSES = frozenset(
    {"sr-only", "visually-hidden", "visuallyhidden", "screen-reader-text", "skip-link"}
)
HEAD_META_KEEP = frozenset({"charset", "viewport"})

MAX_BLOCK_WORDS = 350
MAX_UNWRAP_DEPTH = 12
DESCEND_RATIO = 0.7


def iter_elements(root: _Element) -> Iterator[_Element]:
    for element in root.iter():
        if isinstance(element.tag, str):
            yield element


def element_children(element: _Element) -> list[_Element]:
    return [child for child in element if isinstance(child.tag, str)]


def describe(element: _Element) -> str:
    tag = str(element.tag)
    element_id = element.get("id")
    if element_id:
        return f"{tag}#{element_id}"
    classes = (element.get("class") or "").split()
    if classes:
        return f"{tag}.{classes[0]}"
    return tag


def _drop(element: _Element) -> None:
    parent = element.getparent()
    if parent is None:
        return
    # Keep the tail text with the previous sibling / parent so prose that
    # follows the removed node is not lost.
    tail = element.tail
    if tail:
        previous = element.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(element)


def normalize_text(text: str) -> str:
    return " ".join(text.split())


_BLOCKISH_TAGS = (
    BLOCK_LEAF_TAGS
    | CONTAINER_TAGS
    | frozenset(
        {
            "li",
            "tr",
            "td",
            "th",
            "dt",
            "dd",
            "br",
            "hr",
            "figcaption",
            "summary",
            "caption",
        }
    )
)


_NON_TEXT_TAGS = frozenset({"style", "script", "noscript", "template", "svg", "head"})


def _text_parts(element: _Element, parts: list[str], *, with_tail: bool) -> None:
    if element.tag in _NON_TEXT_TAGS:
        if with_tail and element.tail:
            parts.append(element.tail)
        return
    blockish = element.tag in _BLOCKISH_TAGS
    if blockish:
        parts.append(" ")
    if element.text:
        parts.append(element.text)
    for child in element:
        if isinstance(child.tag, str):
            _text_parts(child, parts, with_tail=True)
        elif child.tail:
            parts.append(child.tail)
    if blockish:
        parts.append(" ")
    if with_tail and element.tail:
        parts.append(element.tail)


def visible_text(element: _Element) -> str:
    """Text content ignoring style/script/svg subtrees and the element's tail."""
    parts: list[str] = []
    _text_parts(element, parts, with_tail=False)
    return "".join(parts)


def text_words(element: _Element) -> int:
    """Words in the element's text plus its tail, treating block boundaries
    (li, td, p, br, ...) as word separators."""
    parts: list[str] = []
    _text_parts(element, parts, with_tail=True)
    return len("".join(parts).split())


def sanitize(root: _Element) -> None:
    """Remove scripts/frames/forms controls, inline handlers and script URLs."""
    for element in list(iter_elements(root)):
        if element.tag in EXECUTABLE_TAGS:
            _drop(element)
    for element in iter_elements(root):
        for name in list(element.attrib):
            lowered = str(name).lower()
            if lowered.startswith("on"):
                del element.attrib[name]
            elif lowered in URL_ATTRS and _UNSAFE_SCHEME_RE.match(
                str(element.attrib[name])
            ):
                del element.attrib[name]


def prune_head(head: _Element | None) -> None:
    """Keep only charset/viewport metas, title, styles and stylesheet links."""
    if head is None:
        return
    for element in element_children(head):
        tag = element.tag
        if tag == "meta":
            keep = "charset" in element.attrib or (
                (element.get("name") or "").lower() in HEAD_META_KEEP
            )
            if not keep:
                head.remove(element)
        elif tag == "link":
            rel = (element.get("rel") or "").lower().split()
            if "stylesheet" not in rel:
                head.remove(element)
        elif tag not in ("title", "style"):
            head.remove(element)


def _link_text_len(element: _Element) -> int:
    return sum(len(normalize_text(visible_text(a))) for a in element.iter("a"))


def text_score(element: _Element) -> int:
    return max(0, len(normalize_text(visible_text(element))) - _link_text_len(element))


def _heading_matches(heading_text: str, title: str) -> bool:
    if not heading_text or not title:
        return False
    if heading_text == title:
        return True
    shorter, longer = sorted((heading_text, title), key=len)
    return len(shorter) >= 10 and shorter in longer


def _fold(text: str) -> str:
    return normalize_text(re.sub(r"[^\w\s]", " ", text.lower()))


def find_title_heading(body: _Element, title: str | None) -> _Element | None:
    if not title:
        return None
    folded_title = _fold(title)
    for tag in ("h1", "h2"):
        for heading in body.iter(tag):
            if _heading_matches(_fold(visible_text(heading)), folded_title):
                return heading
    return None


def _contains(ancestor: _Element, node: _Element) -> bool:
    current: _Element | None = node
    while current is not None:
        if current is ancestor:
            return True
        current = current.getparent()
    return False


def _is_chrome_child(child: _Element, title_heading: _Element | None) -> bool:
    tag = child.tag
    if tag in ("nav", "aside"):
        return True
    if tag in ("header", "footer"):
        if title_heading is not None:
            return not _contains(child, title_heading)
        return child.find(".//h1") is None
    return tag in JUNK_TAGS and bool(_tokens(child) & JUNK_TOKENS)


def locate_container(body: _Element, title: str | None) -> _Element:
    """Descend from body into the child holding most of the non-link,
    non-chrome text, but never past the heading carrying the article title."""
    title_heading = find_title_heading(body, title)
    node = body
    while True:
        children = element_children(node)
        chrome = [child for child in children if _is_chrome_child(child, title_heading)]
        content_score = text_score(node) - sum(text_score(child) for child in chrome)
        if content_score <= 0:
            return node
        candidates = [
            child
            for child in children
            if child.tag in CONTAINER_TAGS and child not in chrome
        ]
        if not candidates:
            return node
        best = max(candidates, key=text_score)
        if text_score(best) < DESCEND_RATIO * content_score:
            return node
        if _descent_drops_title(node, best, chrome, title_heading):
            return node
        node = best


def _descent_drops_title(
    node: _Element,
    best: _Element,
    chrome: list[_Element],
    title_heading: _Element | None,
) -> bool:
    """Refuse to descend past the article's title block: the matched title
    heading when we know it, otherwise any non-chrome sibling holding an h1."""
    if title_heading is not None:
        return _contains(node, title_heading) and not _contains(best, title_heading)
    return any(
        child is not best and child not in chrome and child.find(".//h1") is not None
        for child in element_children(node)
    )


def _is_sprite_svg(element: _Element) -> bool:
    return element.tag == "svg" and any(
        child.tag in ("symbol", "defs") for child in element_children(element)
    )


def _remove_outside(container: _Element, body: _Element) -> None:
    if container is body:
        return
    child = container
    parent = container.getparent()
    while parent is not None:
        for sibling in element_children(parent):
            if (
                sibling is child
                or sibling.tag in ("style", "link")
                or _is_sprite_svg(sibling)
            ):
                continue
            parent.remove(sibling)
        if parent is body:
            break
        child = parent
        parent = parent.getparent()


def _tokens(element: _Element) -> set[str]:
    names = [element.get("id") or "", *(element.get("class") or "").split()]
    tokens: set[str] = set()
    for name in names:
        if _PLAIN_CLASS_RE.match(name):
            tokens.update(
                token for token in _TOKEN_SPLIT_RE.split(name.lower()) if token
            )
    return tokens


def _inside(element: _Element, tags: frozenset[str]) -> bool:
    parent = element.getparent()
    while parent is not None:
        if parent.tag in tags:
            return True
        parent = parent.getparent()
    return False


_CODE_TAGS = frozenset({"pre", "code"})
_ARTICLE_TAGS = frozenset({"article"})


def _is_junk(element: _Element, title_heading: _Element | None) -> bool:
    tag = element.tag
    if tag in ("form", "nav"):
        return True
    if element.get("role") in ("dialog", "navigation", "complementary", "banner"):
        return True
    if tag in ("header", "footer"):
        holds_title = title_heading is not None and _contains(element, title_heading)
        if not holds_title and not _inside(element, _ARTICLE_TAGS):
            return True
    if tag in JUNK_TAGS and not _inside(element, _CODE_TAGS):
        return bool(_tokens(element) & JUNK_TOKENS)
    return False


def _is_screen_reader_only(element: _Element) -> bool:
    classes = set((element.get("class") or "").lower().split())
    return bool(classes & SR_ONLY_CLASSES)


def _remove_inside(container: _Element, title: str | None) -> None:
    title_heading = find_title_heading(container, title)
    for element in list(iter_elements(container)):
        if element is container or not _contains(container, element):
            continue
        if element.get("hidden") is not None or _is_screen_reader_only(element):
            _drop(element)
        elif _is_junk(element, title_heading):
            _drop(element)


def remove_chrome(container: _Element, body: _Element, title: str | None) -> None:
    """Drop everything outside the container (except styles) and obvious junk
    inside it."""
    _remove_outside(container, body)
    _remove_inside(container, title)


def _has_direct_text(element: _Element) -> bool:
    if element.text and element.text.strip():
        return True
    return any(child.tail and child.tail.strip() for child in element)


def _all_children_inline(element: _Element) -> bool:
    children = element_children(element)
    return bool(children) and all(child.tag in INLINE_TAGS for child in children)


def _has_media(element: _Element) -> bool:
    return element.tag in MEDIA_TAGS or any(
        child.tag in MEDIA_TAGS for child in iter_elements(element)
    )


def _is_meaningful(element: _Element) -> bool:
    return text_words(element) > 0 or _has_media(element)


def _is_block_leaf(element: _Element) -> bool:
    return element.tag in BLOCK_LEAF_TAGS


def _should_unwrap(element: _Element, depth: int) -> bool:
    if element.tag not in CONTAINER_TAGS:
        return False
    if depth >= MAX_UNWRAP_DEPTH:
        return False
    if _all_children_inline(element):
        return False
    if not element_children(element):
        return False
    if _has_direct_text(element):
        # Big text-bearing containers still get split if they hold blocks.
        return text_words(element) > MAX_BLOCK_WORDS
    return True


def collect_blocks(container: _Element) -> list[_Element]:
    """Block-level elements that become chunks, in document order."""
    blocks: list[_Element] = []
    _collect(container, 0, blocks)
    return blocks


def _collect(container: _Element, depth: int, blocks: list[_Element]) -> None:
    for child in element_children(container):
        if child.tag in SKIP_TAGS:
            continue
        if _is_block_leaf(child):
            if _is_meaningful(child):
                blocks.append(child)
        elif _should_unwrap(child, depth):
            _collect(child, depth + 1, blocks)
        elif _is_meaningful(child):
            blocks.append(child)
