from nanonerd.reader.chunking import chunk_html, html_to_text


def para(words, prefix="w"):
    return "<p>" + " ".join(f"{prefix}{i}" for i in range(words)) + "</p>"


def test_chunk_html_one_chunk_per_paragraph():
    input_html = para(100, "a") + para(100, "b") + para(100, "c") + para(20, "d")
    output = chunk_html(input_html)
    expected_output = [100, 100, 100, 20]
    assert [c.word_count for c in output] == expected_output


def test_chunk_html_heading_is_its_own_chunk():
    input_html = para(160, "a") + "<h2>Section Two</h2>" + para(160, "b")
    output = chunk_html(input_html)
    assert [c.word_count for c in output] == [160, 2, 160]
    assert output[1].html.startswith("<h2")


def test_chunk_html_long_paragraph_stays_whole():
    input_html = para(500)
    output = chunk_html(input_html)
    assert [c.word_count for c in output] == [500]


def test_html_to_text_strips_markup():
    output = html_to_text("<p>Hello <em>city</em> planners</p>")
    assert output == "Hello city planners"


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
