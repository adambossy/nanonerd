from pathlib import Path
import re
import socket

import pytest

from nanonerd.reader.chunking import chunk_html
from nanonerd.reader.extract import (
    NotArticleError,
    _ensure_public_http_url,
    extract_article,
    resolve_base_url,
)
from nanonerd.reader.normalize import parse_document, parse_fragment

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

FIXTURE_HTML = """<!doctype html>
<html>
<head>
  <title>How Cities Breathe</title>
  <meta name="author" content="Jane Doe">
  <meta property="og:site_name" content="Urban Notes">
</head>
<body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<article>
  <h1>How Cities Breathe</h1>
  <p>Street trees change the thermal profile of a neighborhood in measurable
  ways. A mature canopy can lower surface temperatures by several degrees on a
  summer afternoon, and the effect compounds when tree pits are connected into
  continuous soil trenches that let roots share water.</p>
  <p>The same logic applies to pavement. Permeable surfaces slow stormwater,
  feed the water table, and reduce the urban heat island effect that makes
  dense districts so punishing in July. Cities that treat streets as
  ecological infrastructure rather than pure conveyance get both benefits at
  once.</p>
  <p>None of this is exotic engineering. The techniques are decades old and
  well documented in municipal design manuals. What changed recently is the
  political will to reallocate street space, which is always the scarcest
  resource in a built-out city, away from parked cars and toward living
  systems.</p>
  <p>The cities that move first tend to be the ones that measure. When a
  public works department can show that a greened corridor cut ambient
  temperature and flooding complaints in one season, the next corridor is an
  easier sell to a skeptical council and to residents who fear losing
  parking.</p>
</article>
<footer>Copyright 2026</footer>
</body>
</html>"""

PARAGRAPH = (
    "This paragraph carries enough ordinary prose words that the extractor "
    "treats the page as an article rather than a listing of short fragments, "
    "and it repeats the point once more so the count is comfortably high."
)

RICH_HTML = f"""<!doctype html>
<html>
<head>
  <title>Rich Post</title>
  <meta property="og:type" content="article">
  <link rel="canonical" href="https://example.com/posts/slug/">
</head>
<body>
<article>
  <h1>Rich Post</h1>
  <p>{PARAGRAPH}</p>
  <h2 id="first">First Section<a class="anchor" href="#first">#</a></h2>
  <p>Use <strong>bold words</strong> and <em>italic words</em> here. {PARAGRAPH}</p>
  <p>Run <code>glob</code> then <code>grep</code> to search files. {PARAGRAPH}</p>
  <figure><img src="fig.png" alt="A figure"><figcaption>Figure one</figcaption></figure>
  <p>Steps follow in order. {PARAGRAPH}</p>
  <ol><li>First step of the list</li><li>Second step of the list</li></ol>
  <pre><code>line one
line two</code></pre>
  <p>See <a href="../other-post">the other post</a>. {PARAGRAPH}</p>
</article>
<div id="comments" class="comments">
  <h2>Comments</h2>
  <div class="comment"><p>Commenter says thanks for the clear write-up.</p></div>
</div>
</body>
</html>"""

PRODUCT_HTML = """<!doctype html>
<html><head><meta property="og:type" content="product.group"></head>
<body><ul><li>Smock Teak Twill $245</li><li>Trucker Jacket $330</li></ul></body>
</html>"""

CAPTCHA_HTML = """<html lang="en"><head><title>nytimes.com</title></head>
<body><p id="cmsg">Please enable JS and disable any ad blocker</p></body></html>"""


def count(pattern, html):
    return len(re.findall(pattern, html))


def first_match(pattern, html):
    match = re.search(pattern, html)
    assert match is not None, pattern
    return match.group(1)


def extract_content(html, url="https://example.com/posts/slug"):
    output = extract_article(html, url)
    assert output is not None
    return output.content_html


def test_extract_article_returns_content_and_metadata():
    output = extract_article(FIXTURE_HTML, "https://example.com/cities")
    assert output is not None
    summary = {
        "title": output.title,
        "has_thermal_sentence": "thermal profile" in output.content_html,
        "nav_stripped": "About" not in output.content_html,
    }
    expected_output = {
        "title": "How Cities Breathe",
        "has_thermal_sentence": True,
        "nav_stripped": True,
    }
    assert summary == expected_output


def test_extract_article_returns_none_for_empty_page():
    output = extract_article("<html><body></body></html>", "https://x.com/a")
    assert output is None


def test_extract_article_keeps_images_formatting_code_and_ordered_lists():
    content = extract_content(RICH_HTML)

    output = {
        "img": count(r"<img\b", content),
        "strong": count(r"<strong>", content),
        "italic": count(r"<(em|i)>", content),
        "inline_code": count(r"<code>(glob|grep)</code>", content),
        "block_pre": count(r"<pre>line one\nline two</pre>", content),
        "ol": count(r"<ol>", content),
        "title_h1_dropped": "<h1>" not in content,
    }

    expected_output = {
        "img": 1,
        "strong": 1,
        "italic": 1,
        "inline_code": 2,
        "block_pre": 1,
        "ol": 1,
        "title_h1_dropped": True,
    }
    assert output == expected_output


def test_extract_article_absolutizes_urls_against_canonical_page_url():
    content = extract_content(RICH_HTML, url="https://example.com/posts/slug")

    output = {
        "img_src": first_match(r'<img src="([^"]+)"', content),
        "link_href": first_match(r'<a href="([^"]+)">the other post', content),
    }

    expected_output = {
        "img_src": "https://example.com/posts/slug/fig.png",
        "link_href": "https://example.com/posts/other-post",
    }
    assert output == expected_output


def test_extract_article_strips_heading_permalink_anchor():
    content = extract_content(RICH_HTML)
    assert "<h2>First Section</h2>" in content


def test_extract_article_excludes_comment_section():
    content = extract_content(RICH_HTML)
    assert "Commenter says" not in content


def test_extract_article_output_is_sanitized_block_sequence():
    content = extract_content(RICH_HTML)
    root = parse_fragment(content)

    output = {
        "top_level_tags": sorted({str(child.tag) for child in root}),
        "has_tail_text": any((child.tail or "").strip() for child in root),
        "has_class_attrs": 'class="' in content,
    }

    expected_output = {
        "top_level_tags": ["h2", "img", "ol", "p", "pre"],
        "has_tail_text": False,
        "has_class_attrs": False,
    }
    assert output == expected_output


def test_extract_article_rejects_product_pages():
    with pytest.raises(NotArticleError, match="not an article: og:type is product"):
        extract_article(PRODUCT_HTML, "https://shop.example/collections/new")


def test_extract_article_rejects_pages_without_prose():
    with pytest.raises(NotArticleError, match="not an article: longest block has"):
        extract_article(CAPTCHA_HTML, "https://www.nytimes.com/2026/opinion")


@pytest.mark.parametrize(
    ("head", "expected_output"),
    [
        ('<base href="https://cdn.example/base/">', "https://cdn.example/base/"),
        (
            '<link rel="canonical" href="https://example.com/posts/slug/">',
            "https://example.com/posts/slug/",
        ),
        (
            '<meta property="og:url" content="https://example.com/posts/slug/">',
            "https://example.com/posts/slug/",
        ),
        (
            '<link rel="canonical" href="https://other.example/syndicated/">',
            "https://example.com/posts/slug",
        ),
        ("", "https://example.com/posts/slug"),
    ],
)
def test_resolve_base_url_prefers_page_declared_location(
    head: str, expected_output: str
) -> None:
    doc = parse_document(f"<html><head>{head}</head><body><p>x</p></body></html>")
    output = resolve_base_url(doc, "https://example.com/posts/slug")
    assert output == expected_output


def load_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_extract_article_lilog_fixture_recovers_figures_and_inline_code():
    html = load_fixture("lilianweng_harness.html")

    content = extract_content(
        html, url="https://lilianweng.github.io/posts/2026-07-04-harness"
    )
    chunks = chunk_html(content)

    output = {
        "img": count(r"<img\b", content),
        "img_absolute_to_post_dir": count(
            r'<img src="https://lilianweng\.github\.io/posts/2026-07-04-harness/',
            content,
        ),
        "pre": count(r"<pre>", content),
        "inline_bash_code_in_paragraph": "(commonly via <code>bash</code> commands)"
        in content,
        "headings_with_hash": count(r"#</h[1-6]>", content)
        + count(r"<h[1-6]>[^<]*<a[^>]*>#</a>", content),
        "ol": count(r"<ol>", content),
        "sum_chunk_words_over_5000": sum(c.word_count for c in chunks) > 5000,
        "one_word_non_heading_chunks": sum(
            1
            for c in chunks
            if c.word_count <= 1 and not re.match(r"<(img|h[1-6])", c.html)
        ),
    }

    expected_output = {
        "img": 18,
        "img_absolute_to_post_dir": 18,
        "pre": 1,
        "inline_bash_code_in_paragraph": True,
        "headings_with_hash": 0,
        "ol": 7,
        "sum_chunk_words_over_5000": True,
        "one_word_non_heading_chunks": 0,
    }
    assert output == expected_output


def test_extract_article_single_container_fixture_yields_many_chunks():
    html = load_fixture("ordinaryabundance.html")

    content = extract_content(html, url="https://ordinaryabundance.com")
    chunks = chunk_html(content)

    output = {
        "chunk_count_over_40": len(chunks) > 40,
        "max_chunk_words_under_100": max(c.word_count for c in chunks) < 100,
        "total_words_over_1400": sum(c.word_count for c in chunks) > 1400,
    }

    expected_output = {
        "chunk_count_over_40": True,
        "max_chunk_words_under_100": True,
        "total_words_over_1400": True,
    }
    assert output == expected_output


def test_ensure_public_http_url_rejects_file_scheme():
    with pytest.raises(ValueError):
        _ensure_public_http_url("file:///etc/passwd")


def test_ensure_public_http_url_rejects_localhost():
    with pytest.raises(ValueError):
        _ensure_public_http_url("http://localhost:8000/x")


def test_ensure_public_http_url_rejects_loopback_ip():
    with pytest.raises(ValueError):
        _ensure_public_http_url("http://127.0.0.1/x")


def test_ensure_public_http_url_rejects_link_local_metadata_ip():
    with pytest.raises(ValueError):
        _ensure_public_http_url("http://169.254.169.254/latest/meta-data")


def test_ensure_public_http_url_accepts_public_ip(monkeypatch):
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    _ensure_public_http_url("http://example.com/x")
