from nanonerd.reader.chunking import MEDIA_WORDS, chunk_html, html_to_text


def para(words, prefix="w"):
    return "<p>" + " ".join(f"{prefix}{i}" for i in range(words)) + "</p>"


def words_of(chunks):
    return [c.word_count for c in chunks]


def tag_of(html):
    return html[1 : html.index(">")].split(" ")[0]


def test_chunk_html_one_chunk_per_paragraph():
    input_html = para(100, "a") + para(100, "b") + para(100, "c") + para(20, "d")
    output = chunk_html(input_html)
    expected_output = [100, 100, 100, 20]
    assert words_of(output) == expected_output


def test_chunk_html_heading_is_its_own_chunk():
    input_html = para(160, "a") + "<h2>Section Two</h2>" + para(160, "b")
    output = chunk_html(input_html)
    assert words_of(output) == [160, 2, 160]
    assert output[1].html.startswith("<h2")


def test_chunk_html_long_paragraph_stays_whole():
    input_html = para(500)
    output = chunk_html(input_html)
    assert words_of(output) == [500]


def test_html_to_text_strips_markup():
    output = html_to_text("<p>Hello <em>city</em> planners</p>")
    assert output == "Hello city planners"


def test_chunk_html_counts_tail_text_after_block_elements():
    # trafilatura can leave prose as tail text after <h2>/<pre>; it must still
    # be counted (and rendered) rather than vanish from the progress math.
    input_html = "<h2>Title</h2>" + " ".join(f"t{i}" for i in range(100))

    output = chunk_html(input_html)

    expected_output = [("h2", 1), ("p", 100)]
    assert [(tag_of(c.html), c.word_count) for c in output] == expected_output


def test_chunk_html_unwraps_single_wrapper_container():
    input_html = (
        '<div id="steps"><div>'
        + para(40, "a")
        + para(40, "b")
        + para(40, "c")
        + "</div></div>"
    )

    output = chunk_html(input_html)

    expected_output = [40, 40, 40]
    assert [c.word_count for c in output] == expected_output


def test_chunk_html_drops_empty_blocks_but_keeps_images():
    input_html = (
        para(30, "a") + "<p></p><p> </p><img src='https://x/y.png'>" + para(30, "b")
    )

    output = chunk_html(input_html)

    # Media chunks carry a fixed dwell word-equivalent rather than zero.
    expected_output = [30, MEDIA_WORDS, 30]
    assert [c.word_count for c in output] == expected_output


def test_chunk_html_strips_javascript_hrefs():
    input_html = (
        "<p>"
        + " ".join(f"w{i}" for i in range(150))
        + ' <a href="javascript:alert(1)">x</a>'
        + ' <a href="https://ok.example/a">y</a></p>'
    )
    output = chunk_html(input_html)
    html = "".join(c.html for c in output)
    assert "https://ok.example/a" in html
    assert "javascript:" not in html


def test_chunk_html_unwraps_nested_containers():
    input_html = (
        "<main><article><div>"
        + para(10, "a")
        + "<section>"
        + para(12, "b")
        + "</section></div></article></main>"
    )
    output = chunk_html(input_html)
    assert words_of(output) == [10, 12]
    assert all(c.html.startswith("<p") for c in output)


def test_chunk_html_groups_stray_inline_content_into_paragraph():
    input_html = (
        "<div>Leading <em>inline</em> text" + para(5, "a") + "trailing words</div>"
    )
    output = chunk_html(input_html)
    expected_output = [
        ("<p>Leading <em>inline</em> text</p>", 3),
        (para(5, "a"), 5),
        ("<p>trailing words</p>", 2),
    ]
    assert [(c.html, c.word_count) for c in output] == expected_output


def test_chunk_html_word_count_includes_tail_text():
    input_html = "<p>one <a href='https://x.example'>two</a> three four</p>"
    output = chunk_html(input_html)
    assert words_of(output) == [4]


def test_chunk_html_keeps_figure_pre_table_atomic():
    input_html = (
        "<figure><img src='https://x.example/a.png'><figcaption>Cap one</figcaption>"
        "</figure><pre><code>a = 1\nb = 2</code></pre>"
        "<table><tr><td>c1</td><td>c2</td></tr><tr><td>c3</td></tr></table>"
    )
    output = chunk_html(input_html)
    assert [c.html.split(">")[0] + ">" for c in output] == [
        "<figure>",
        "<pre>",
        "<table>",
    ]


def test_chunk_html_media_chunks_get_dwell_floor():
    input_html = (
        "<figure><img src='https://x.example/a.png'></figure>"
        "<video controls><source src='https://x.example/v.mp4'></video>"
        "<figure><img src='https://x.example/b.png'><figcaption>"
        + " ".join(f"cap{i}" for i in range(30))
        + "</figcaption></figure>"
    )
    output = chunk_html(input_html)
    assert words_of(output) == [MEDIA_WORDS, MEDIA_WORDS, 30]


def test_chunk_html_drops_empty_blocks():
    input_html = "<p></p><hr><p>   </p>" + para(3) + "<div><span></span></div>"
    output = chunk_html(input_html)
    assert words_of(output) == [3]


def test_chunk_html_splits_footnote_list_per_item():
    input_html = (
        para(4) + "<ol><li id='nn-fn:1'>first note <a href='#nn-fnref:1'>↩</a></li>"
        "<li id='nn-fn:2'>second note</li></ol>"
    )
    output = chunk_html(input_html)
    assert [c.html.split(">")[0] for c in output[1:]] == [
        '<ol start="1"',
        '<ol start="2"',
    ]
    assert words_of(output) == [4, 3, 2]


def test_chunk_html_keeps_short_list_whole():
    input_html = '<ol start="3"><li>alpha</li><li>beta</li></ol>'
    output = chunk_html(input_html)
    assert [(c.html, c.word_count) for c in output] == [(input_html, 2)]


def test_chunk_html_splits_long_list_per_item():
    item = "<li>" + " ".join(f"w{i}" for i in range(70)) + "</li>"
    input_html = f"<ul>{item}{item}{item}</ul>"
    output = chunk_html(input_html)
    assert [(c.html.startswith("<ul><li>"), c.word_count) for c in output] == [
        (True, 70),
        (True, 70),
        (True, 70),
    ]


def test_chunk_html_blockquote_is_atomic():
    input_html = "<blockquote data-callout='tip'>" + para(5, "a") + para(6, "b")
    input_html += "</blockquote>"
    output = chunk_html(input_html)
    assert words_of(output) == [11]
