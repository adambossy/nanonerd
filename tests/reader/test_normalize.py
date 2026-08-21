import pytest

from nanonerd.reader.normalize import (
    drop_duplicate_title,
    normalize_content,
    sanitize_html,
)

BASE_URL = "https://example.com/posts/slug/"


def words(count, prefix="w"):
    return " ".join(f"{prefix}{i}" for i in range(count))


def test_sanitize_html_strips_disallowed_tags_and_attributes():
    input_html = (
        '<p class="x" onclick="evil()">Hi <b>b</b> <span>s</span>'
        "<script>alert(1)</script><style>p{}</style>"
        '<iframe src="https://x"></iframe></p>'
    )

    output = sanitize_html(input_html)

    expected_output = "<p>Hi <b>b</b> s</p>"
    assert output == expected_output


@pytest.mark.parametrize(
    ("input_html", "expected_output"),
    [
        ('<p><a href="javascript:alert(1)">x</a></p>', "<p><a>x</a></p>"),
        (
            '<p><a href="https://ok.example/a" target="_blank">y</a></p>',
            '<p><a href="https://ok.example/a">y</a></p>',
        ),
        (
            '<p><img src="https://x/y.png" alt="a" width="10" onload="z"></p>',
            '<p><img src="https://x/y.png" alt="a" width="10"></p>',
        ),
    ],
)
def test_sanitize_html_keeps_only_safe_urls_and_attributes(
    input_html: str, expected_output: str
) -> None:
    output = sanitize_html(input_html)
    assert output == expected_output


def test_normalize_content_absolutizes_relative_image_and_link_urls():
    input_html = (
        '<p>See <a href="../other">other</a> and <a href="#fn1">note</a>.</p>'
        '<img src="openai-agent-loop.png" alt="loop">'
    )

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = (
        '<p>See <a href="https://example.com/posts/other">other</a> and '
        '<a href="https://example.com/posts/slug/#fn1">note</a>.</p>'
        '<img src="https://example.com/posts/slug/openai-agent-loop.png" alt="loop">'
    )
    assert output == expected_output


def test_normalize_content_converts_inline_pre_inside_paragraph_to_code():
    input_html = "<p>Run <pre>glob</pre> then <pre>grep</pre> to search.</p>"

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = "<p>Run <code>glob</code> then <code>grep</code> to search.</p>"
    assert output == expected_output


def test_normalize_content_keeps_multiline_pre_as_block():
    input_html = "<p>Example:</p><pre>line one\nline two</pre>"

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = "<p>Example:</p><pre>line one\nline two</pre>"
    assert output == expected_output


def test_normalize_content_merges_hoisted_inline_code_back_into_paragraph():
    # trafilatura splits "<p>..via <code>bash</code> commands..</p>" into a
    # truncated <p>, a root-level <pre>, and tail text.
    input_html = (
        "<p>Learning the file system (commonly via</p>"
        "<pre>bash</pre> commands) is a foundation skill."
    )

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = (
        "<p>Learning the file system (commonly via <code>bash</code> "
        "commands) is a foundation skill.</p>"
    )
    assert output == expected_output


def test_normalize_content_wraps_heading_tail_text_in_paragraph():
    input_html = "<h2>Title</h2>Prose that followed the heading as tail text."

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = (
        "<h2>Title</h2><p>Prose that followed the heading as tail text.</p>"
    )
    assert output == expected_output


def test_normalize_content_starts_new_paragraph_after_heading_then_inline_pre():
    input_html = (
        "<h3>TokenVerifier</h3><pre>TokenVerifier</pre> provides pure validation."
    )

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = (
        "<h3>TokenVerifier</h3><p><code>TokenVerifier</code> provides pure "
        "validation.</p>"
    )
    assert output == expected_output


def test_normalize_content_keeps_single_token_pre_after_colon_as_block():
    input_html = "<p>Install with:</p><pre>uv sync</pre><p>Done.</p>"

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = "<p>Install with:</p><pre>uv sync</pre><p>Done.</p>"
    assert output == expected_output


def test_normalize_content_unwraps_nested_pre():
    input_html = "<pre>\n  <pre>NOTE_ON_60_80\nNOTE_OFF_60\n</pre>\n</pre><p>After.</p>"

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = "<pre>NOTE_ON_60_80\nNOTE_OFF_60\n</pre><p>After.</p>"
    assert output == expected_output


@pytest.mark.parametrize(
    "input_html",
    [
        '<h2>Harness Design Patterns<a href="https://x#harness">#</a></h2>',
        "<h2>Harness Design Patterns#</h2>",
        '<h2>Harness Design Patterns <a href="#h">¶</a></h2>',
        '<h2><a href="#h">Harness Design Patterns</a></h2>',
    ],
)
def test_normalize_content_strips_heading_anchor_markers(input_html: str) -> None:
    output = normalize_content(input_html, base_url=BASE_URL)
    expected_output = "<h2>Harness Design Patterns</h2>"
    assert output == expected_output


def test_normalize_content_unwraps_single_wrapper_container():
    input_html = (
        '<div id="steps"><div><h2>One</h2><p>'
        + words(30, "a")
        + "</p><p>"
        + words(30, "b")
        + "</p></div></div>"
    )

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = (
        "<h2>One</h2><p>" + words(30, "a") + "</p><p>" + words(30, "b") + "</p>"
    )
    assert output == expected_output


def test_normalize_content_wraps_loose_text_inside_container_into_paragraph():
    input_html = "<div>Intro text.<p>Real paragraph.</p>Outro text.</div>"

    output = normalize_content(input_html, base_url=BASE_URL)

    expected_output = "<p>Intro text.</p><p>Real paragraph.</p><p>Outro text.</p>"
    assert output == expected_output


@pytest.mark.parametrize(
    ("input_html", "title", "expected_output"),
    [
        ("<h1>Rich  Post</h1><p>Body.</p>", "rich post", "<p>Body.</p>"),
        ("<h1>Section</h1><p>Body.</p>", "Rich Post", "<h1>Section</h1><p>Body.</p>"),
        ("<p>Body.</p><h1>Rich</h1>", "Rich", "<p>Body.</p><h1>Rich</h1>"),
        ("<h1>Rich Post</h1>", None, "<h1>Rich Post</h1>"),
    ],
)
def test_drop_duplicate_title_removes_only_leading_h1_matching_title(
    input_html: str, title: str | None, expected_output: str
) -> None:
    output = drop_duplicate_title(input_html, title)
    assert output == expected_output


def test_normalize_content_preserves_ordered_lists_tables_and_figures():
    input_html = (
        "<ol><li>one</li><li>two</li></ol>"
        "<table><tbody><tr><th>h</th><td>d</td></tr></tbody></table>"
        '<figure><img src="https://x/y.png"><figcaption>cap</figcaption></figure>'
    )

    output = normalize_content(input_html, base_url=BASE_URL)

    assert output == input_html
