"""In-page article extraction with the vendored Defuddle browser bundle."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, Page

from nanonerd.reader.errors import ExtractionError

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"

# Normalizes markup Defuddle does not recognise on its own, and strips the
# chrome that archive services wrap around a snapshot, so the extractor sees
# the article the way its author published it.
PREPASS_JS = """() => {
  const calloutSelector =
    'div.callout[data-callout-type], div[role="note"][aria-label]';
  for (const el of document.querySelectorAll(calloutSelector)) {
    const type = (
      el.getAttribute('data-callout-type') ||
      el.getAttribute('aria-label') ||
      'note'
    ).toLowerCase();
    const aside = document.createElement('aside');
    aside.className = 'callout-' + type;
    const content = document.createElement('div');
    content.className = 'callout-content';
    el.querySelectorAll('[data-component-part="callout-icon"], svg')
      .forEach((icon) => icon.remove());
    while (el.firstChild) content.appendChild(el.firstChild);
    aside.appendChild(content);
    el.replaceWith(aside);
  }
  const archiveChrome =
    '#wm-ipp-base, #wm-ipp-print, #donato, #HEADER, #hashtags';
  document.querySelectorAll(archiveChrome).forEach((el) => el.remove());
}"""

PARSE_JS = """(url) => {
  const result = new Defuddle(document, {
    url, debug: false, useAsync: false
  }).parse();
  return {
    content: result.content || '',
    title: result.title || '',
    author: result.author || '',
    site: result.site || '',
    wordCount: result.wordCount || 0,
  };
}"""


@dataclass(frozen=True, slots=True)
class ReadableContent:
    title: str | None
    author: str | None
    site: str | None
    word_count: int
    content_html: str


@cache
def defuddle_source() -> str:
    return (_VENDOR_DIR / "defuddle.js").read_text(encoding="utf-8")


def _clean(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _to_readable(raw: object) -> ReadableContent:
    if not isinstance(raw, dict):
        raise ExtractionError(f"unexpected Defuddle result: {type(raw).__name__}")
    word_count = raw.get("wordCount")
    content = raw.get("content")
    return ReadableContent(
        title=_clean(raw.get("title")),
        author=_clean(raw.get("author")),
        site=_clean(raw.get("site")),
        word_count=int(word_count) if isinstance(word_count, int | float) else 0,
        content_html=content if isinstance(content, str) else "",
    )


def extract_readable(page: Page, url: str) -> ReadableContent:
    """Run the pre-pass and Defuddle inside a rendered page."""
    try:
        page.evaluate(PREPASS_JS)
        page.evaluate(defuddle_source())
        raw = page.evaluate(PARSE_JS, url)
    except PlaywrightError as exc:
        raise ExtractionError(f"Defuddle failed in page: {exc}") from exc
    return _to_readable(raw)
