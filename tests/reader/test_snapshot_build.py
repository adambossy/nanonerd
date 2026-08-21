from lxml import html as lxml_html

from nanonerd.reader.snapshot.build import BuildLimits, assemble_snapshot
from nanonerd.reader.snapshot.css import Resource

BLOG_HTML = """<!DOCTYPE html>
<html class="light" lang="en"><head><meta charset="utf-8">
<title>Hello World - Blog</title>
<meta property="og:title" content="x"><link rel="icon" href="/favicon.ico">
<link rel="stylesheet" href="https://blog.example/missing.css">
<style>body{font-family:Serif} html{--a:1} .x{color:red}</style>
<style>@font-face{font-family:F;src:url(https://blog.example/f.woff2)}
 p{margin:0}</style>
<script>alert(1)</script></head>
<body class="page" onload="go()">
<header class="site-header"><nav><a href="/">Home</a>
<a href="/about">About us</a></nav></header>
<main>
<article>
<header><h1>Hello World</h1><p class="byline">By Ann</p></header>
<div class="entry-content">
<p>First paragraph with <a href="javascript:alert(1)">link</a> words here.</p>
<div class="wrapper"><p>Second paragraph inside a wrapper div.</p></div>
<figure><img src="/y.png" onerror="alert(1)"><figcaption>A caption</figcaption></figure>
<ul><li>alpha</li><li>beta</li></ul>
<div class="share-buttons"><a href="https://t.co">Tweet this</a></div>
<div>Stray <em>text</em> block</div>
<div><svg viewBox="0 0 1 1"><path d="M0 0"/></svg></div>
<form class="subscribe"><input type="email"><button>Subscribe</button></form>
</div>
<footer class="post-footer">Tags: a, b</footer>
</article>
<aside class="sidebar"><a href="/1">one</a> <a href="/2">two</a>
<a href="/3">three</a></aside>
</main>
<footer class="site-footer">Copyright footer with many words about the site
and links</footer>
<div id="comments"><p>A comment by someone</p></div>
<script>track()</script>
</body></html>"""


def build(html, title="Hello World", resources=None, limits=None):
    return assemble_snapshot(
        html,
        url="https://blog.example/post",
        title=title,
        resources=resources or {},
        limits=limits or BuildLimits(),
    )


def _tagged_blocks(snapshot_html):
    root = lxml_html.document_fromstring(snapshot_html)
    return [
        (el.tag, el.get("data-chunk-index"))
        for el in root.iter()
        if isinstance(el.tag, str) and el.get("data-chunk-index") is not None
    ]


def _css_text(snapshot_html):
    root = lxml_html.document_fromstring(snapshot_html)
    return [(style.get("id"), style.text) for style in root.iter("style")]


def test_assemble_snapshot_tags_real_blocks_in_document_order():
    output = build(BLOG_HTML)

    expected_output = [
        ("h1", "0"),
        ("p", "1"),
        ("p", "2"),
        ("p", "3"),
        ("figure", "4"),
        ("ul", "5"),
        ("div", "6"),
        ("footer", "7"),
    ]
    assert _tagged_blocks(output.html) == expected_output


def test_assemble_snapshot_chunks_mirror_tagged_blocks():
    output = build(BLOG_HTML)

    chunk_summaries = [(c.word_count, c.html[:11]) for c in output.chunks]
    expected_output = [
        (2, "<h1>Hello W"),
        (2, '<p class="b'),
        (6, "<p>First pa"),
        (6, "<p>Second p"),
        (2, "<figure><im"),
        (2, "<ul><li>alp"),
        (3, "<div>Stray "),
        (3, "<footer cla"),
    ]
    assert chunk_summaries == expected_output


def test_assemble_snapshot_removes_chrome_and_junk():
    output = build(BLOG_HTML)

    root = lxml_html.document_fromstring(output.html)
    survivors = {
        selector: len(root.cssselect(selector))
        for selector in (
            "header.site-header",
            "nav",
            "aside.sidebar",
            "footer.site-footer",
            "#comments",
            ".share-buttons",
            "form",
            "button",
            "script",
            "link[rel=icon]",
            "meta[property]",
            "article",
            "footer.post-footer",
            "meta[charset]",
        )
    }
    expected_output = {
        "header.site-header": 0,
        "nav": 0,
        "aside.sidebar": 0,
        "footer.site-footer": 0,
        "#comments": 0,
        ".share-buttons": 0,
        "form": 0,
        "button": 0,
        "script": 0,
        "link[rel=icon]": 0,
        "meta[property]": 0,
        "article": 1,
        "footer.post-footer": 1,
        "meta[charset]": 1,
    }
    assert survivors == expected_output


def test_assemble_snapshot_strips_event_handlers_and_javascript_urls():
    output = build(BLOG_HTML)

    root = lxml_html.document_fromstring(output.html)
    img = root.cssselect("figure img")[0]
    link = root.cssselect("p a")[0]
    observed = (
        img.get("onerror"),
        img.get("src"),
        link.get("href"),
        "onload" in output.html,
    )
    assert observed == (None, "https://blog.example/y.png", None, False)


def test_assemble_snapshot_wraps_body_and_scopes_root_css():
    output = build(BLOG_HTML)

    root = lxml_html.document_fromstring(output.html)
    body = root.find("body")
    assert body is not None
    wrapper = body[0]
    inner = wrapper[0]
    observed = {
        "wrapper": (wrapper.tag, wrapper.get("class"), wrapper.get("lang")),
        "inner": (inner.tag, inner.get("class"), inner[0].tag),
        "styles": _css_text(output.html),
    }
    expected_output = {
        "wrapper": ("div", "sf-html light", "en"),
        "inner": ("div", "sf-body page", "main"),
        "styles": [
            (
                "snapshot-fonts",
                "@font-face{font-family:F;src:url(https://blog.example/f.woff2)}",
            ),
            (None, ".sf-body{font-family:Serif} .sf-html{--a:1} .x{color:red}"),
            (None, "\n p{margin:0}"),
        ],
    }
    assert observed == expected_output


def test_assemble_snapshot_reports_container_and_removals():
    output = build(BLOG_HTML)

    assert (output.container, sorted(output.removed)) == (
        "article",
        [
            "aside.sidebar",
            "div#comments",
            "div.share-buttons",
            "footer.site-footer",
            "form.subscribe",
            "header.site-header",
        ],
    )


def test_assemble_snapshot_inlines_captured_images_and_fonts():
    resources = {
        "https://blog.example/y.png": Resource("image/png", b"PNG"),
        "https://blog.example/f.woff2": Resource("font/woff2", b"WOFF"),
        "https://blog.example/missing.css": Resource("text/css", b"h1{x:y}"),
    }

    output = build(BLOG_HTML, resources=resources)

    root = lxml_html.document_fromstring(output.html)
    observed = (
        root.cssselect("figure img")[0].get("src"),
        _css_text(output.html)[0][1],
        _css_text(output.html)[1][1],
        len(root.cssselect("link[rel=stylesheet]")),
    )
    expected_output = (
        "data:image/png;base64,UE5H",
        "@font-face{font-family:F;src:url(data:font/woff2;base64,V09GRg==)}",
        "h1{x:y}",
        0,
    )
    assert observed == expected_output


def test_assemble_snapshot_skips_large_images_but_keeps_absolute_url():
    resources = {"https://blog.example/y.png": Resource("image/png", b"x" * 100)}

    output = build(
        BLOG_HTML, resources=resources, limits=BuildLimits(max_image_bytes=10)
    )

    root = lxml_html.document_fromstring(output.html)
    assert root.cssselect("figure img")[0].get("src") == "https://blog.example/y.png"


SCROLLY_HTML = """<html><head><style>.step{opacity:1}</style></head><body>
<main>
<section class="hero"><div><h1>Ordinary Abundance</h1>
<p>An intro line.</p></div></section>
<section class="chapter" id="story"><div class="story-column"><div id="steps">
<article class="step"><p class="scene-text">Scene one text goes here.</p>
</article>
<article class="step"><blockquote class="quote">A quote about abundance.</blockquote>
<p class="source">Source A</p></article>
<article class="step"><blockquote class="quote">Another quote here.</blockquote>
<p class="source">Source B</p></article>
</div></div></section>
<section class="ledger"><div class="outro"><p>Outro paragraph one.</p>
<p>Outro paragraph two.</p></div></section>
</main></body></html>"""


def test_assemble_snapshot_unwraps_nested_wrappers_for_scrollytelling_page():
    output = build(SCROLLY_HTML, title="Ordinary Abundance")

    observed = (output.container, [(t, i) for t, i in _tagged_blocks(output.html)])
    expected_output = (
        "main",
        [
            ("h1", "0"),
            ("p", "1"),
            ("p", "2"),
            ("blockquote", "3"),
            ("p", "4"),
            ("blockquote", "5"),
            ("p", "6"),
            ("p", "7"),
            ("p", "8"),
        ],
    )
    assert observed == expected_output


def test_assemble_snapshot_falls_back_to_body_when_no_text():
    output = build("<html><body><div><img src='a.png'></div></body></html>", title="x")

    assert (output.container, len(output.chunks)) == ("body", 1)
