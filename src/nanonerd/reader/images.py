"""Download, shrink and re-host article images so the reader never hotlinks."""

from dataclasses import dataclass
import hashlib
from io import BytesIO
import logging
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from nanonerd.reader.dom import Element, parse_fragment, serialize_children
from nanonerd.reader.errors import FetchError
from nanonerd.reader.fetch import fetch_response
from nanonerd.reader.storage import Storage, StorageError

logger = logging.getLogger(__name__)

MAX_WIDTH = 1200
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 60 * 1024 * 1024
JPEG_QUALITY = 82
# Opaque PNGs above this many pixels are almost always photos or screenshots
# where JPEG is a fraction of the size at phone resolution.
_LARGE_PNG_PIXELS = 1_000_000
_MEDIA_SRC_TAGS = ("video", "audio", "source")


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    data: bytes
    content_type: str
    extension: str


@dataclass(frozen=True, slots=True)
class CachedContent:
    html: str
    cached_count: int


def _is_svg(data: bytes, content_type: str | None) -> bool:
    if content_type and content_type.split(";")[0].strip() == "image/svg+xml":
        return True
    head = data[:512].lstrip().lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head)


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA"):
        return True
    return image.mode == "P" and "transparency" in image.info


def _resize_to_width(image: Image.Image, max_width: int) -> Image.Image:
    if image.width <= max_width:
        return image
    height = max(1, round(image.height * max_width / image.width))
    return image.resize((max_width, height), Image.Resampling.LANCZOS)


def process_image(data: bytes, content_type: str | None) -> ProcessedImage:
    """Normalize to a phone-sized JPEG/PNG with metadata stripped.

    SVGs and animated GIFs pass through untouched.
    """
    if _is_svg(data, content_type):
        return ProcessedImage(data, "image/svg+xml", "svg")
    opened = Image.open(BytesIO(data))
    if opened.format == "GIF" and getattr(opened, "is_animated", False):
        return ProcessedImage(data, "image/gif", "gif")
    source_format = opened.format or ""
    # Bake the EXIF orientation in before the EXIF itself is dropped.
    image: Image.Image = ImageOps.exif_transpose(opened) or opened
    image = _resize_to_width(image, MAX_WIDTH)
    buffer = BytesIO()
    if _has_alpha(image):
        image.convert("RGBA").save(buffer, format="PNG", optimize=True)
        return ProcessedImage(buffer.getvalue(), "image/png", "png")
    keep_png = (
        source_format == "PNG" and image.width * image.height <= _LARGE_PNG_PIXELS
    )
    if keep_png:
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return ProcessedImage(buffer.getvalue(), "image/png", "png")
    image.convert("RGB").save(
        buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True
    )
    return ProcessedImage(buffer.getvalue(), "image/jpeg", "jpg")


def _absolute_http_url(raw: str | None, base_url: str) -> str | None:
    if raw is None or not raw.strip():
        return None
    absolute = urljoin(base_url, raw.strip())
    if urlsplit(absolute).scheme not in ("http", "https"):
        return None
    return absolute


def _download(
    src: str, page_url: str, client: httpx.Client, limit: int
) -> httpx.Response | None:
    try:
        response = fetch_response(
            src,
            client=client,
            headers={"Referer": page_url, "Accept": "image/*,*/*;q=0.8"},
        )
    except FetchError:
        logger.info("image fetch failed: %s", src, exc_info=True)
        return None
    if response.status_code >= 400:
        return None
    if len(response.content) > limit:
        logger.info("image too large (%d bytes): %s", len(response.content), src)
        return None
    return response


def _cache_key(prefix: str, src: str, extension: str) -> str:
    digest = hashlib.sha1(src.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"{prefix}/{digest}.{extension}"


def _cache_one(
    img: Element,
    *,
    page_url: str,
    storage: Storage,
    key_prefix: str,
    client: httpx.Client,
    budget: int,
) -> int:
    """Rewrite one `<img>` to a cached copy; return the bytes stored (0 on skip)."""
    src = _absolute_http_url(img.get("src") or img.get("data-src"), page_url)
    for attr in ("srcset", "sizes", "data-src", "data-srcset"):
        if attr in img.attrib:
            del img.attrib[attr]
    if src is None:
        return 0
    img.set("src", src)
    if budget <= 0:
        return 0
    response = _download(src, page_url, client, min(MAX_IMAGE_BYTES, budget))
    if response is None:
        return 0
    try:
        processed = process_image(
            response.content, response.headers.get("content-type")
        )
    except (UnidentifiedImageError, OSError, ValueError):
        logger.info("image could not be decoded: %s", src, exc_info=True)
        return 0
    try:
        public_url = storage.put(
            _cache_key(key_prefix, src, processed.extension),
            processed.data,
            processed.content_type,
        )
    except StorageError:
        logger.warning("image store failed: %s", src, exc_info=True)
        return 0
    img.set("src", public_url)
    return len(processed.data)


def _absolutize_media(root: Element, page_url: str) -> None:
    for element in root.iter(*_MEDIA_SRC_TAGS):
        for attr in ("src", "poster"):
            absolute = _absolute_http_url(element.get(attr), page_url)
            if absolute is not None:
                element.set(attr, absolute)


def cache_images(
    content_html: str,
    *,
    page_url: str,
    storage: Storage,
    key_prefix: str,
    client: httpx.Client,
) -> CachedContent:
    """Re-host every `<img>` we can; anything that fails keeps its absolute URL."""
    root = parse_fragment(content_html)
    budget = MAX_TOTAL_BYTES
    cached_count = 0
    for img in list(root.iter("img")):
        stored = _cache_one(
            img,
            page_url=page_url,
            storage=storage,
            key_prefix=key_prefix,
            client=client,
            budget=budget,
        )
        if stored:
            cached_count += 1
            budget -= stored
    _absolutize_media(root, page_url)
    return CachedContent(html=serialize_children(root), cached_count=cached_count)
