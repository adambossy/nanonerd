import socket
from types import SimpleNamespace

import httpx
import pytest

from nanonerd.reader import extract
from nanonerd.reader.extract import _ensure_public_http_url, extract_article

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


def create_blocked_response(status_code=403, text="<html>bot wall</html>"):
    return SimpleNamespace(status_code=status_code, headers={}, text=text)


def test_fetch_html_raises_fetch_error_carrying_status_and_body(monkeypatch):
    # input
    input_url = "https://example.com/blocked"

    # helper setup
    monkeypatch.setattr(extract, "_ensure_public_http_url", lambda url: None)
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: create_blocked_response())

    # act
    with pytest.raises(extract.FetchError) as raised:
        extract.fetch_html(input_url)
    output = {"status_code": raised.value.status_code, "body": raised.value.body}

    # expected
    expected_output = {"status_code": 403, "body": "<html>bot wall</html>"}

    # assert
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
