"""Assemble a captured page into a decluttered, self-contained, chunk-tagged
snapshot document."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from urllib.parse import urljoin

from lxml import etree, html as lxml_html
from lxml.etree import _Element

from nanonerd.reader.chunking import ChunkData
from nanonerd.reader.snapshot import declutter
from nanonerd.reader.snapshot.css import (
    BODY_WRAPPER_CLASS,
    HTML_WRAPPER_CLASS,
    Resource,
    resolve_css_urls,
    scope_root_selectors,
    split_font_faces,
    to_data_uri,
)

CHUNK_INDEX_ATTR = "data-chunk-index"
CHUNK_ID_ATTR = "data-chunk-id"
FONT_STYLE_ID = "snapshot-fonts"
STYLE_BASE_ATTR = "data-sf-base"
UNRESOLVED_LINK_ATTR = "data-sf-unresolved"

_STYLE_URL_RE = re.compile(r"url\(", re.IGNORECASE)
_CHUNK_INDEX_RE = re.compile(rf'{CHUNK_INDEX_ATTR}="(\d+)"')


@dataclass(frozen=True, slots=True)
class BuildLimits:
    max_image_bytes: int = 400_000
    max_css_resource_bytes: int = 1_000_000


@dataclass(frozen=True, slots=True)
class SnapshotBuild:
    html: str
    chunks: list[ChunkData]
    container: str
    removed: list[str] = field(default_factory=list)


def _ensure_charset(head: _Element) -> None:
    if head.find("meta[@charset]") is not None:
        return
    meta = etree.Element("meta")
    meta.set("charset", "utf-8")
    head.insert(0, meta)


def _resolve_stylesheet_links(
    root: _Element, resources: Mapping[str, Resource], url: str
) -> None:
    for link in list(root.iter("link")):
        rel = (link.get("rel") or "").lower().split()
        if "stylesheet" not in rel:
            continue
        href = link.get(UNRESOLVED_LINK_ATTR) or link.get("href")
        if not href:
            continue
        absolute = urljoin(url, href)
        resource = resources.get(absolute)
        if resource is None:
            continue
        style = etree.Element("style")
        style.text = resource.body.decode("utf-8", errors="replace")
        style.set(STYLE_BASE_ATTR, absolute)
        media = link.get("media")
        if media:
            style.set("media", media)
        style.tail = link.tail
        parent = link.getparent()
        if parent is not None:
            parent.replace(link, style)


def _inline_styles(
    root: _Element, resources: Mapping[str, Resource], url: str, limits: BuildLimits
) -> None:
    for style in root.iter("style"):
        base = style.get(STYLE_BASE_ATTR) or url
        if STYLE_BASE_ATTR in style.attrib:
            del style.attrib[STYLE_BASE_ATTR]
        style.text = resolve_css_urls(
            style.text or "",
            base_url=base,
            resources=resources,
            max_inline_bytes=limits.max_css_resource_bytes,
        )
    for element in declutter.iter_elements(root):
        inline = element.get("style")
        if inline and _STYLE_URL_RE.search(inline):
            element.set(
                "style",
                resolve_css_urls(
                    inline,
                    base_url=url,
                    resources=resources,
                    max_inline_bytes=limits.max_image_bytes,
                ),
            )


def _inline_images(
    root: _Element, resources: Mapping[str, Resource], url: str, limits: BuildLimits
) -> None:
    for img in root.iter("img"):
        src = img.get("src")
        if not src or src.startswith(("data:", "blob:")):
            continue
        absolute = urljoin(url, src)
        resource = resources.get(absolute)
        if resource is not None and len(resource.body) <= limits.max_image_bytes:
            img.set("src", to_data_uri(absolute, resource))
        else:
            img.set("src", absolute)


def _scope_styles(root: _Element, head: _Element) -> None:
    faces: list[str] = []
    for style in list(root.iter("style")):
        scoped = scope_root_selectors(style.text or "")
        font_faces, rest = split_font_faces(scoped)
        if font_faces:
            faces.append(font_faces)
        style.text = rest
        if not rest.strip():
            parent = style.getparent()
            if parent is not None:
                parent.remove(style)
    if faces:
        font_style = etree.Element("style")
        font_style.set("id", FONT_STYLE_ID)
        font_style.text = "\n".join(faces)
        head.insert(0, font_style)


def _copy_attributes(source: _Element, target: _Element, wrapper_class: str) -> None:
    for name, value in source.attrib.items():
        if name == "class":
            continue
        target.set(name, value)
    classes = [wrapper_class, *(source.get("class") or "").split()]
    target.set("class", " ".join(classes))


def _wrap_body(root: _Element, body: _Element) -> None:
    """``<body>children</body>`` -> ``<body><div.sf-html><div.sf-body>children``
    so the rewritten html/body selectors keep matching inside a shadow root."""
    outer = etree.Element("div")
    inner = etree.Element("div")
    _copy_attributes(root, outer, HTML_WRAPPER_CLASS)
    _copy_attributes(body, inner, BODY_WRAPPER_CLASS)
    inner.text = body.text
    body.text = None
    for child in list(body):
        inner.append(child)
    outer.append(inner)
    body.append(outer)
    for name in list(body.attrib):
        del body.attrib[name]


def _chunk_for(block: _Element) -> ChunkData:
    return ChunkData(
        html=etree.tostring(block, encoding="unicode", method="html"),
        word_count=declutter.text_words(block),
    )


def assemble_snapshot(
    html: str,
    *,
    url: str,
    title: str | None,
    resources: Mapping[str, Resource],
    limits: BuildLimits,
) -> SnapshotBuild:
    root = lxml_html.document_fromstring(html)
    head = root.find("head")
    if head is None:
        head = etree.Element("head")
        root.insert(0, head)
    body = root.find("body")
    if body is None:
        body = etree.Element("body")
        root.append(body)

    declutter.sanitize(root)
    declutter.prune_head(head)
    _ensure_charset(head)
    _resolve_stylesheet_links(root, resources, url)

    container = declutter.locate_container(body, title)
    container_label = declutter.describe(container)
    removed = declutter.remove_chrome(container, body, title)

    blocks = declutter.collect_blocks(container)
    _inline_images(root, resources, url, limits)
    chunks = [_chunk_for(block) for block in blocks]
    for index, block in enumerate(blocks):
        block.set(CHUNK_INDEX_ATTR, str(index))

    _inline_styles(root, resources, url, limits)
    _scope_styles(root, head)
    _wrap_body(root, body)

    document = etree.tostring(
        root, encoding="unicode", doctype="<!DOCTYPE html>", method="html"
    )
    return SnapshotBuild(
        html=document, chunks=chunks, container=container_label, removed=removed
    )


def attach_chunk_ids(snapshot_html: str, chunk_ids: list[int]) -> str:
    """Add ``data-chunk-id`` next to each ``data-chunk-index`` marker."""

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if index >= len(chunk_ids):
            return match.group(0)
        return f'{match.group(0)} {CHUNK_ID_ATTR}="{chunk_ids[index]}"'

    return _CHUNK_INDEX_RE.sub(replace, snapshot_html)
