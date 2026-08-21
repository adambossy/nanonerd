import httpx

from nanonerd.reader.archive import find_archive_ph_snapshot, find_wayback_snapshot

URL = "https://news.example/story"
TIMEMAP = (
    '<https://news.example/story>; rel="original",\n'
    '<http://archive.md/timemap/https://news.example/story>; rel="self"; '
    'type="application/link-format",\n'
    "<http://archive.md/20260101000000/https://news.example/story>; "
    'rel="first memento"; datetime="Thu, 01 Jan 2026 00:00:00 GMT",\n'
    "<http://archive.md/20260704005836/https://news.example/story>; "
    'rel="last memento"; datetime="Sat, 04 Jul 2026 00:58:36 GMT",\n'
)


def create_client(routes):
    """`routes` maps a URL prefix -> list of responses served in order."""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        for prefix, responses in routes.items():
            if str(request.url).startswith(prefix):
                response = responses.pop(0) if len(responses) > 1 else responses[0]
                return response
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_find_archive_ph_snapshot_returns_latest_memento():
    client, _calls = create_client(
        {"https://archive.ph/timemap/": [httpx.Response(200, text=TIMEMAP)]}
    )
    output = find_archive_ph_snapshot(URL, client=client, submit=False)
    assert output == "https://archive.md/20260704005836/https://news.example/story"


def test_find_archive_ph_snapshot_submits_then_polls():
    slept: list[float] = []
    client, calls = create_client(
        {
            "https://archive.ph/timemap/": [
                httpx.Response(404),
                httpx.Response(404),
                httpx.Response(200, text=TIMEMAP),
            ],
            "https://archive.ph/submit/": [httpx.Response(200, text="ok")],
        }
    )
    output = find_archive_ph_snapshot(URL, client=client, sleep_fn=slept.append)
    summary = {
        "snapshot": output,
        "submitted": any(
            call.startswith("https://archive.ph/submit/") for call in calls
        ),
        "polls": slept,
    }
    expected_output = {
        "snapshot": "https://archive.md/20260704005836/https://news.example/story",
        "submitted": True,
        "polls": [5.0, 10.0],
    }
    assert summary == expected_output


def test_find_archive_ph_snapshot_gives_up_after_bounded_polls():
    slept: list[float] = []
    client, _calls = create_client(
        {
            "https://archive.ph/timemap/": [httpx.Response(404)],
            "https://archive.ph/submit/": [httpx.Response(200, text="ok")],
        }
    )
    output = find_archive_ph_snapshot(URL, client=client, sleep_fn=slept.append)
    assert (output, slept) == (None, [5.0, 10.0, 20.0])


def test_find_archive_ph_snapshot_treats_rate_limit_as_missing():
    client, calls = create_client(
        {"https://archive.ph/timemap/": [httpx.Response(429, text="One more step")]}
    )
    output = find_archive_ph_snapshot(URL, client=client, submit=False)
    assert (output, len(calls)) == (None, 1)


def test_find_wayback_snapshot_uses_latest_ok_capture():
    client, _calls = create_client(
        {
            "https://web.archive.org/cdx/search/cdx": [
                httpx.Response(200, json=[["timestamp"], ["20260501000144"]])
            ]
        }
    )
    output = find_wayback_snapshot(URL, client=client)
    assert (
        output
        == "https://web.archive.org/web/20260501000144/https://news.example/story"
    )


def test_find_wayback_snapshot_falls_back_to_newest_redirect():
    client, _calls = create_client(
        {
            "https://web.archive.org/cdx/search/cdx": [httpx.Response(200, json=[])],
            "https://web.archive.org/web/2/": [
                httpx.Response(
                    302,
                    headers={
                        "location": "/web/20260819234256/https://news.example/story"
                    },
                )
            ],
        }
    )
    output = find_wayback_snapshot(URL, client=client)
    assert (
        output
        == "https://web.archive.org/web/20260819234256/https://news.example/story"
    )


def test_find_wayback_snapshot_returns_none_when_nothing_archived():
    client, _calls = create_client(
        {
            "https://web.archive.org/cdx/search/cdx": [httpx.Response(200, json=[])],
            "https://web.archive.org/web/2/": [httpx.Response(404)],
        }
    )
    assert find_wayback_snapshot(URL, client=client) is None
