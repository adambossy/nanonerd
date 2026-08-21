"""Small lxml helpers shared by the HTML post-processing steps.

Elements are typed as `lxml.etree._Element` (what lxml-stubs knows about);
lxml.html's parser produces `HtmlElement` subclasses at runtime, which is fine
since only the etree API is used here.
"""

from typing import cast

from lxml import etree, html as lxml_html
from lxml.etree import _Element

Element = _Element

# Comments, processing instructions and entities: present in the tree, but
# they carry no article content.
NON_ELEMENT_TYPES = (etree._Comment, etree._ProcessingInstruction, etree._Entity)


def parse_fragment(content_html: str) -> Element:
    """Parse an HTML fragment into a wrapper `<div>` root."""
    if not content_html.strip():
        return etree.Element("div")
    return cast(
        Element, lxml_html.fragment_fromstring(content_html, create_parent="div")
    )


def new_element(tag: str) -> Element:
    return etree.Element(tag)


def text_of(element: Element) -> str:
    """All text inside the element (not its tail)."""
    return "".join(str(part) for part in element.itertext())


def word_count_of(element: Element) -> int:
    """Words inside the element, counting each text node separately.

    Adjacent blocks (`<li>a</li><li>b</li>`) have no whitespace between their
    text nodes, so joining first would fuse words across element boundaries.
    """
    return sum(len(str(part).split()) for part in element.itertext())


def is_real_element(node: Element) -> bool:
    return not isinstance(node, NON_ELEMENT_TYPES)


def serialize_children(root: Element) -> str:
    """Serialize everything inside `root` (text, children and their tails)."""
    parts = [root.text or ""]
    parts.extend(
        etree.tostring(child, encoding="unicode", method="html", with_tail=True)
        for child in root
    )
    return "".join(parts)


def serialize_element(element: Element) -> str:
    return etree.tostring(element, encoding="unicode", method="html", with_tail=False)
