from nanonerd.reader.sanitize import sanitize_html


def test_sanitize_html_prefixes_ids_and_fragment_links():
    input_html = '<p>Ref<sup id="fnref:1"><a href="#fn:1">1</a></sup></p>'
    output = sanitize_html(input_html)
    expected_output = '<p>Ref<sup id="nn-fnref:1"><a href="#nn-fn:1">1</a></sup></p>'
    assert output == expected_output


def test_sanitize_html_strips_scripts_and_unsafe_hrefs():
    input_html = (
        '<p>Hi <a href="javascript:alert(1)">x</a> <a href="https://ok.example">y</a>'
        '</p><script>alert(1)</script><p onclick="evil()">z</p>'
    )
    output = sanitize_html(input_html)
    expected_output = '<p>Hi <a>x</a> <a href="https://ok.example">y</a></p><p>z</p>'
    assert output == expected_output


def test_sanitize_html_unwraps_unknown_containers():
    input_html = "<main><div><span>text</span><p>para</p></div></main>"
    output = sanitize_html(input_html)
    assert output == "text<p>para</p>"


def test_sanitize_html_keeps_mathml_with_latex():
    input_html = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML" display="block" '
        'data-latex="x=1" onclick="x()"><mi>x</mi><mo>=</mo><mn>1</mn></math>'
    )
    output = sanitize_html(input_html)
    expected_output = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML" display="block" '
        'data-latex="x=1"><mi>x</mi><mo>=</mo><mn>1</mn></math>'
    )
    assert output == expected_output


def test_sanitize_html_falls_back_to_latex_when_mathml_is_empty():
    input_html = (
        '<p>Inline <math data-latex="a^2"></math> and</p>'
        '<math display="block" data-latex="\\sum_i x_i"></math>'
    )
    output = sanitize_html(input_html)
    expected_output = (
        '<p>Inline <code class="latex">a^2</code> and</p>'
        '<pre class="latex"><code>\\sum_i x_i</code></pre>'
    )
    assert output == expected_output


def test_sanitize_html_converts_defuddle_callout_to_blockquote():
    input_html = (
        '<div data-callout="tip" class="callout"><div class="callout-title">'
        '<div class="callout-title-inner">Tip</div></div>'
        '<div class="callout-content"><p>Be kind.</p></div></div>'
    )
    output = sanitize_html(input_html)
    expected_output = (
        '<blockquote data-callout="tip"><p><strong>Tip</strong></p>'
        "<p>Be kind.</p></blockquote>"
    )
    assert output == expected_output


def test_sanitize_html_keeps_code_blocks_media_and_lazy_images():
    input_html = (
        '<pre><code data-lang="py" class="language-py">x</code></pre>'
        '<figure><img src="https://x.example/a.png" srcset="a 1x" alt="A" '
        'width="10" height="5"><figcaption>Cap</figcaption></figure>'
        '<video controls poster="https://x.example/p.jpg">'
        '<source src="https://x.example/v.mp4" type="video/mp4"></video>'
        '<audio controls src="https://x.example/a.wav"></audio>'
        '<ol start="3"><li>three</li></ol>'
    )
    output = sanitize_html(input_html)
    expected_output = (
        '<pre><code data-lang="py" class="language-py">x</code></pre>'
        '<figure><img src="https://x.example/a.png" alt="A" width="10" height="5" '
        'loading="lazy"><figcaption>Cap</figcaption></figure>'
        '<video controls="" poster="https://x.example/p.jpg">'
        '<source src="https://x.example/v.mp4" type="video/mp4"></video>'
        '<audio controls="" src="https://x.example/a.wav"></audio>'
        '<ol start="3"><li>three</li></ol>'
    )
    assert output == expected_output


def test_sanitize_html_drops_iframes_svg_and_forms_with_content():
    input_html = (
        '<p>a</p><iframe src="https://x.example"></iframe><svg><text>icon</text>'
        "</svg><form><input></form><p>b</p>"
    )
    output = sanitize_html(input_html)
    assert output == "<p>a</p><p>b</p>"
