"""CSS rewriting helpers for self-contained, shadow-DOM-scoped snapshots."""

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import mimetypes
import re
from urllib.parse import urljoin

HTML_WRAPPER_CLASS = "sf-html"
BODY_WRAPPER_CLASS = "sf-body"

_ROOT_SELECTOR_RE = re.compile(r":root\b")
_HTML_BODY_SELECTOR_RE = re.compile(r"(?<![-\w.#\[:=\"'])(html|body)(?![-\w])")
_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.DOTALL)
_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*(['\"]?)([^'\")]+)\1\s*\)|(['\"])([^'\"]+)\3)\s*([^;]*);",
)
_MAX_IMPORT_DEPTH = 3
_SKIP_URL_PREFIXES = ("data:", "blob:", "#", "about:")


@dataclass(frozen=True, slots=True)
class Resource:
    content_type: str
    body: bytes


def _rewrite_prelude(prelude: str) -> str:
    prelude = _ROOT_SELECTOR_RE.sub("." + HTML_WRAPPER_CLASS, prelude)
    return _HTML_BODY_SELECTOR_RE.sub(
        lambda m: "."
        + (HTML_WRAPPER_CLASS if m.group(1) == "html" else BODY_WRAPPER_CLASS),
        prelude,
    )


def scope_root_selectors(css: str) -> str:
    """Rewrite ``html``/``body``/``:root`` selectors to wrapper classes so the
    stylesheet keeps working when the body content is hosted in a shadow root
    (which has no html/body element of its own)."""
    segments = css.split("{")
    if len(segments) == 1:
        return css
    parts: list[str] = []
    last_idx = len(segments) - 1
    for idx, segment in enumerate(segments):
        if idx == last_idx:
            parts.append(segment)
            continue
        # Text after the last '}' of this segment is the prelude of the rule
        # opened by the next '{'; everything before it is declarations.
        cut = segment.rfind("}") + 1
        parts.append(segment[:cut] + _rewrite_prelude(segment[cut:]))
    return "{".join(parts)


def _find_block_end(css: str, open_idx: int) -> int | None:
    depth = 0
    for idx in range(open_idx, len(css)):
        char = css[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return idx + 1
    return None


def split_font_faces(css: str) -> tuple[str, str]:
    """Return ``(font_face_css, remaining_css)``.

    Chromium ignores ``@font-face`` declared inside a shadow root, so the
    reader hoists those rules into the document head."""
    faces: list[str] = []
    rest: list[str] = []
    pos = 0
    while True:
        idx = css.find("@font-face", pos)
        if idx == -1:
            rest.append(css[pos:])
            break
        open_idx = css.find("{", idx)
        end = _find_block_end(css, open_idx) if open_idx != -1 else None
        if end is None:
            rest.append(css[pos:])
            break
        rest.append(css[pos:idx])
        faces.append(css[idx:end])
        pos = end
    return "\n".join(faces), "".join(rest)


def _mime_for(url: str, resource: Resource) -> str:
    declared = resource.content_type.split(";")[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared
    guessed, _ = mimetypes.guess_type(url)
    return guessed or "application/octet-stream"


def _css_url_token(url: str) -> str:
    if any(char in url for char in " ()'\""):
        return 'url("' + url.replace('"', "%22") + '")'
    return f"url({url})"


def _inline_imports(
    css: str,
    *,
    base_url: str,
    resources: Mapping[str, Resource],
    max_inline_bytes: int,
    depth: int,
) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(2) or match.group(4) or ""
        media = match.group(5).strip()
        absolute = urljoin(base_url, raw.strip())
        resource = resources.get(absolute)
        if resource is None or depth >= _MAX_IMPORT_DEPTH:
            suffix = f" {media}" if media else ""
            return f"@import {_css_url_token(absolute)}{suffix};"
        imported = _resolve(
            resource.body.decode("utf-8", errors="replace"),
            base_url=absolute,
            resources=resources,
            max_inline_bytes=max_inline_bytes,
            depth=depth + 1,
        )
        return f"@media {media}{{{imported}}}" if media else imported

    return _IMPORT_RE.sub(replace, css)


def _inline_urls(
    css: str, *, base_url: str, resources: Mapping[str, Resource], max_inline_bytes: int
) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(2).strip()
        if not raw or raw.startswith(_SKIP_URL_PREFIXES):
            return match.group(0)
        absolute = urljoin(base_url, raw)
        resource = resources.get(absolute)
        if resource is None or len(resource.body) > max_inline_bytes:
            return _css_url_token(absolute)
        encoded = base64.b64encode(resource.body).decode("ascii")
        return f"url(data:{_mime_for(absolute, resource)};base64,{encoded})"

    return _URL_RE.sub(replace, css)


def _resolve(
    css: str,
    *,
    base_url: str,
    resources: Mapping[str, Resource],
    max_inline_bytes: int,
    depth: int,
) -> str:
    with_imports = _inline_imports(
        css,
        base_url=base_url,
        resources=resources,
        max_inline_bytes=max_inline_bytes,
        depth=depth,
    )
    return _inline_urls(
        with_imports,
        base_url=base_url,
        resources=resources,
        max_inline_bytes=max_inline_bytes,
    )


def resolve_css_urls(
    css: str,
    *,
    base_url: str,
    resources: Mapping[str, Resource],
    max_inline_bytes: int,
) -> str:
    """Absolutize every ``url()`` against ``base_url`` and inline the ones we
    captured (fonts, images, imported sheets) as data URIs when small enough."""
    return _resolve(
        css,
        base_url=base_url,
        resources=resources,
        max_inline_bytes=max_inline_bytes,
        depth=0,
    )


def to_data_uri(url: str, resource: Resource) -> str:
    encoded = base64.b64encode(resource.body).decode("ascii")
    return f"data:{_mime_for(url, resource)};base64,{encoded}"
