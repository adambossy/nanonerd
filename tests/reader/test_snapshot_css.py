from nanonerd.reader.snapshot.css import (
    Resource,
    resolve_css_urls,
    scope_root_selectors,
    split_font_faces,
)


def test_scope_root_selectors_rewrites_html_body_and_root():
    input_css = (
        "html{font-size:16px}\n"
        "body{margin:0}\n"
        ":root{--x:1}\n"
        "html.dark body > .a, body.b .c{color:red}\n"
        "@media (min-width:1px){body{padding:0}}\n"
        ".body-copy{font:body}\n"
        "tbody tr{x:y}\n"
    )

    output = scope_root_selectors(input_css)

    expected_output = (
        ".sf-html{font-size:16px}\n"
        ".sf-body{margin:0}\n"
        ".sf-html{--x:1}\n"
        ".sf-html.dark .sf-body > .a, .sf-body.b .c{color:red}\n"
        "@media (min-width:1px){.sf-body{padding:0}}\n"
        ".body-copy{font:body}\n"
        "tbody tr{x:y}\n"
    )
    assert output == expected_output


def test_split_font_faces_extracts_blocks_including_nested():
    input_css = (
        "p{color:red}"
        "@font-face{font-family:A;src:url(a.woff2)}"
        "@media screen{@font-face{font-family:B;src:url(b.woff2)}h1{x:y}}"
    )

    output = split_font_faces(input_css)

    expected_output = (
        "@font-face{font-family:A;src:url(a.woff2)}\n"
        "@font-face{font-family:B;src:url(b.woff2)}",
        "p{color:red}@media screen{h1{x:y}}",
    )
    assert output == expected_output


def test_resolve_css_urls_rebases_and_inlines_known_resources():
    input_css = (
        "@import url('more.css');"
        'a{background:url("img/a.png")} '
        "b{background:url(https://cdn.example.com/big.png)} "
        "@font-face{src:url(fonts/f.woff2) format('woff2')}"
    )
    resources = {
        "https://example.com/css/more.css": Resource("text/css", b"i{z:1}"),
        "https://example.com/css/img/a.png": Resource("image/png", b"PNG"),
        "https://example.com/css/fonts/f.woff2": Resource("font/woff2", b"WOFF"),
    }

    output = resolve_css_urls(
        input_css,
        base_url="https://example.com/css/site.css",
        resources=resources,
        max_inline_bytes=1000,
    )

    expected_output = (
        "i{z:1}"
        "a{background:url(data:image/png;base64,UE5H)} "
        "b{background:url(https://cdn.example.com/big.png)} "
        "@font-face{src:url(data:font/woff2;base64,V09GRg==) format('woff2')}"
    )
    assert output == expected_output


def test_resolve_css_urls_leaves_oversized_resources_as_absolute_urls():
    input_css = "a{background:url(a.png)}"
    resources = {"https://example.com/a.png": Resource("image/png", b"x" * 50)}

    output = resolve_css_urls(
        input_css,
        base_url="https://example.com/",
        resources=resources,
        max_inline_bytes=10,
    )

    assert output == "a{background:url(https://example.com/a.png)}"
