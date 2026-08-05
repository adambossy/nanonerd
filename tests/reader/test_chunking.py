from nanonerd.reader.chunking import chunk_html, html_to_text


def para(words, prefix="w"):
    return "<p>" + " ".join(f"{prefix}{i}" for i in range(words)) + "</p>"


def test_chunk_html_groups_small_paragraphs_greedily():
    input_html = para(100, "a") + para(100, "b") + para(100, "c") + para(100, "d")
    output = chunk_html(input_html)
    expected_output = [300, 100]
    assert [c.word_count for c in output] == expected_output


def test_chunk_html_heading_starts_new_chunk():
    input_html = para(160, "a") + "<h2>Section Two</h2>" + para(160, "b")
    output = chunk_html(input_html)
    assert [c.word_count for c in output] == [160, 162]
    assert output[1].html.startswith("<h2")


def test_chunk_html_never_splits_a_paragraph():
    input_html = para(500)
    output = chunk_html(input_html)
    assert [c.word_count for c in output] == [500]


def test_chunk_html_keeps_short_trailing_chunk():
    input_html = para(300, "a") + para(20, "b")
    output = chunk_html(input_html)
    assert [c.word_count for c in output] == [300, 20]


def test_html_to_text_strips_markup():
    output = html_to_text("<p>Hello <em>city</em> planners</p>")
    assert output == "Hello city planners"
