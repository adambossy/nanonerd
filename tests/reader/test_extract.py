from nanonerd.reader.extract import extract_article

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
