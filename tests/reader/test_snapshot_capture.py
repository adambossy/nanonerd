from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

from nanonerd.reader.snapshot.build import BuildLimits, assemble_snapshot  # noqa: E402
from nanonerd.reader.snapshot.capture import (  # noqa: E402
    CaptureLimits,
    SnapshotCaptureError,
    capture_page,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "snapshot_site"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@contextmanager
def serve_fixture_site() -> Iterator[str]:
    handler = partial(_QuietHandler, directory=str(FIXTURE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def capture_fixture():
    limits = CaptureLimits(idle_timeout_s=2.0, scroll_time_s=0.5)
    with serve_fixture_site() as base_url:
        try:
            return base_url, capture_page(base_url + "index.html", limits=limits)
        except SnapshotCaptureError as exc:
            if "Executable doesn't exist" in str(exc) or "install" in str(exc):
                pytest.skip(f"chromium not available: {exc}")
            raise


def test_capture_page_serializes_post_js_dom_with_inlined_css():
    base_url, captured = capture_fixture()

    observed = {
        "has_script_tag": "<script" in captured.html,
        "has_js_paragraph": "Paragraph inserted by script." in captured.html,
        "hidden_removed": "You should not see this." not in captured.html,
        "css_inlined": "font-family: Georgia, serif" in captured.html,
        "css_harvested": base_url + "style.css" in captured.resources,
        "lazy_attr_dropped": 'loading="lazy"' not in captured.html,
        "final_url": captured.url,
    }
    expected_output = {
        "has_script_tag": False,
        "has_js_paragraph": True,
        "hidden_removed": True,
        "css_inlined": True,
        "css_harvested": True,
        "lazy_attr_dropped": True,
        "final_url": base_url + "index.html",
    }
    assert observed == expected_output


def test_capture_then_assemble_yields_tagged_chunks():
    base_url, captured = capture_fixture()

    output = assemble_snapshot(
        captured.html,
        url=captured.url,
        title="Fixture Post",
        resources=captured.resources,
        limits=BuildLimits(),
    )

    observed = (
        output.container,
        [chunk.word_count for chunk in output.chunks],
        'data-chunk-index="3"' in output.html,
        "site-header" in output.html,
    )
    assert observed == ("article", [2, 8, 0, 4], True, False)
