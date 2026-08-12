import pytest

from nanonerd.reader.urlnorm import normalize_url


@pytest.mark.parametrize(
    ("input_url", "expected_output"),
    [
        ("HTTPS://Example.COM/Article/", "https://example.com/Article"),
        ("https://example.com/a?utm_source=x&utm_medium=y", "https://example.com/a"),
        ("https://example.com/a?fbclid=123&keep=1", "https://example.com/a?keep=1"),
        ("https://example.com/a?gclid=9", "https://example.com/a"),
        ("https://example.com/a#section-2", "https://example.com/a"),
        ("https://example.com/a?b=2&keep=1", "https://example.com/a?b=2&keep=1"),
        ("https://example.com/", "https://example.com"),
        ("  https://example.com/a ", "https://example.com/a"),
    ],
)
def test_normalize_url(input_url: str, expected_output: str) -> None:
    output = normalize_url(input_url)
    assert output == expected_output
