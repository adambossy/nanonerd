"""Reduce extracted HTML to the reading-grade subset the reader knows how to style."""

import nh3

from nanonerd.reader.dom import (
    Element,
    is_real_element,
    new_element,
    parse_fragment,
    serialize_children,
    text_of,
)

# Element ids are kept so footnote links work, but namespaced so they cannot
# collide with the reader app's own DOM.
ID_PREFIX = "nn-"

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_TEXT_TAGS = {"p", "br", "hr", "ul", "ol", "li", "dl", "dt", "dd", "blockquote"}
_INLINE_TAGS = {"strong", "em", "b", "i", "u", "s", "sup", "sub", "a", "code", "pre"}
_MEDIA_TAGS = {"img", "figure", "figcaption", "video", "audio", "source"}
_TABLE_TAGS = {"table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption"}
# MathML Core element set plus the annotation pair Defuddle emits.
_MATHML_TAGS = {
    "math",
    "semantics",
    "annotation",
    "annotation-xml",
    "mrow",
    "mi",
    "mn",
    "mo",
    "mtext",
    "mspace",
    "ms",
    "mfrac",
    "msqrt",
    "mroot",
    "mstyle",
    "merror",
    "mpadded",
    "mphantom",
    "msub",
    "msup",
    "msubsup",
    "munder",
    "mover",
    "munderover",
    "mmultiscripts",
    "mprescripts",
    "mtable",
    "mtr",
    "mtd",
    "maction",
}

ALLOWED_TAGS = (
    _HEADINGS | _TEXT_TAGS | _INLINE_TAGS | _MEDIA_TAGS | _TABLE_TAGS | _MATHML_TAGS
)
# Removed together with their content; everything else not allowed is unwrapped.
CLEAN_CONTENT_TAGS = {
    "script",
    "style",
    "noscript",
    "iframe",
    "object",
    "embed",
    "template",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "svg",
    "canvas",
}

_MATH_LAYOUT_ATTRS = {"width", "height", "depth", "lspace", "voffset"}
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"id"},
    "a": {"href", "title", "class"},
    "img": {"src", "alt", "width", "height", "loading"},
    "ol": {"start", "reversed", "type"},
    "li": {"value", "class"},
    "blockquote": {"data-callout", "cite", "class"},
    "pre": {"class", "data-lang", "data-language"},
    "code": {"class", "data-lang", "data-language"},
    "td": {"colspan", "rowspan", "scope"},
    "th": {"colspan", "rowspan", "scope"},
    "video": {"src", "controls", "poster", "width", "height", "preload", "playsinline"},
    "audio": {"src", "controls", "preload"},
    "source": {"src", "type"},
    "math": {"display", "data-latex", "xmlns", "alttext"},
    "annotation": {"encoding"},
    "annotation-xml": {"encoding"},
    "mo": {
        "stretchy",
        "fence",
        "separator",
        "largeop",
        "movablelimits",
        "lspace",
        "rspace",
        "form",
        "symmetric",
        "accent",
    },
    "mi": {"mathvariant"},
    "mstyle": {"displaystyle", "scriptlevel", "mathvariant"},
    "mfrac": {"linethickness"},
    "mspace": _MATH_LAYOUT_ATTRS,
    "mpadded": _MATH_LAYOUT_ATTRS,
    "mtd": {"columnspan", "rowspan"},
    "mtable": {"columnalign", "rowalign", "columnlines", "rowlines", "frame"},
    "mover": {"accent"},
    "munder": {"accentunder"},
    "munderover": {"accent", "accentunder"},
}
URL_SCHEMES = {"http", "https", "mailto"}


def _namespace_ids(tag: str, attribute: str, value: str) -> str | None:
    if attribute == "id":
        return ID_PREFIX + value
    if attribute == "href" and value.startswith("#"):
        return "#" + ID_PREFIX + value[1:]
    return value


def _paragraph(text: str, *, strong: bool = False) -> Element:
    paragraph = new_element("p")
    if strong:
        emphasis = new_element("strong")
        emphasis.text = text
        paragraph.append(emphasis)
    else:
        paragraph.text = text
    return paragraph


def _callout_title(callout: Element) -> str:
    for selector in (
        ".//*[@class='callout-title-inner']",
        ".//*[@class='callout-title']",
    ):
        title = callout.find(selector)
        if title is not None:
            return " ".join(text_of(title).split())
    return ""


def _replace(old: Element, new: Element) -> None:
    parent = old.getparent()
    if parent is None:
        return
    new.tail = old.tail
    parent.replace(old, new)


def _callout_to_blockquote(callout: Element) -> None:
    """Defuddle's `div.callout` becomes `blockquote[data-callout]` with a bold title."""
    quote = new_element("blockquote")
    quote.set("data-callout", (callout.get("data-callout") or "note").lower())
    title_text = _callout_title(callout)
    content = callout.find(".//*[@class='callout-content']")
    if content is None:
        content = callout
        for title in callout.findall(".//*[@class='callout-title']"):
            parent = title.getparent()
            if parent is not None:
                parent.remove(title)
    if title_text:
        quote.append(_paragraph(title_text, strong=True))
    if content.text and content.text.strip():
        quote.append(_paragraph(content.text))
    for child in list(content):
        quote.append(child)
    _replace(callout, quote)


def _latex_fallback(math: Element) -> None:
    """Show the LaTeX source when Defuddle could not build MathML."""
    code = new_element("code")
    code.text = math.get("data-latex") or math.get("alttext") or ""
    replacement = code
    if (math.get("display") or "").lower() == "block":
        replacement = new_element("pre")
        replacement.append(code)
    replacement.set("class", "latex")
    _replace(math, replacement)


def _normalize(root: Element) -> None:
    for callout in list(root.iter("div")):
        if callout.get("data-callout") is not None:
            _callout_to_blockquote(callout)
    for math in list(root.iter("math")):
        has_children = any(is_real_element(child) for child in math)
        if not has_children and not (math.text or "").strip():
            _latex_fallback(math)


def sanitize_html(content_html: str) -> str:
    root = parse_fragment(content_html)
    _normalize(root)
    return nh3.clean(
        serialize_children(root),
        tags=ALLOWED_TAGS,
        clean_content_tags=CLEAN_CONTENT_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_namespace_ids,
        url_schemes=URL_SCHEMES,
        set_tag_attribute_values={"img": {"loading": "lazy"}},
        link_rel=None,
    )
