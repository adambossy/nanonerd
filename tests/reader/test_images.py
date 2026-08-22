from io import BytesIO
import socket

import httpx
from PIL import Image
import pytest

from nanonerd.reader import fetch
from nanonerd.reader.images import MAX_WIDTH, cache_images, process_image
from nanonerd.reader.storage import LocalStorage, StorageError


class RecordingStorage:
    def __init__(self, fail=False):
        self.objects = {}
        self._fail = fail

    def put(self, key, data, content_type):
        if self._fail:
            raise StorageError("disk full")
        self.objects[key] = (data, content_type)
        return f"https://cdn.example/{key}"


def png_bytes(width, height, mode="RGB", exif_orientation=None):
    image = Image.new(mode, (width, height), color=(200, 30, 30, 255)[: len(mode)])
    buffer = BytesIO()
    if exif_orientation is not None:
        exif = image.getexif()
        exif[0x0112] = exif_orientation
        image.save(buffer, format="JPEG", exif=exif.tobytes())
    else:
        image.save(buffer, format="PNG")
    return buffer.getvalue()


def open_image(data):
    return Image.open(BytesIO(data))


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def create_client(responses):
    """`responses` maps URL -> (status, content_type, body)."""
    requests = []

    def handler(request):
        requests.append(request)
        status, content_type, body = responses.get(
            str(request.url), (404, "text/plain", b"nope")
        )
        return httpx.Response(
            status, headers={"content-type": content_type}, content=body
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_process_image_resizes_wide_images_and_strips_exif():
    input_data = png_bytes(2400, 1200, exif_orientation=1)
    output = process_image(input_data, "image/jpeg")
    image = open_image(output.data)
    summary = {
        "size": image.size,
        "content_type": output.content_type,
        "extension": output.extension,
        "has_exif": bool(image.getexif()),
    }
    expected_output = {
        "size": (MAX_WIDTH, 600),
        "content_type": "image/jpeg",
        "extension": "jpg",
        "has_exif": False,
    }
    assert summary == expected_output


def test_process_image_keeps_alpha_as_png():
    output = process_image(png_bytes(100, 50, mode="RGBA"), "image/png")
    assert (output.content_type, open_image(output.data).mode) == ("image/png", "RGBA")


def test_process_image_small_opaque_png_stays_png():
    output = process_image(png_bytes(300, 200), "image/png")
    assert (output.content_type, open_image(output.data).size) == (
        "image/png",
        (300, 200),
    )


def test_process_image_passes_svg_through():
    input_data = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    output = process_image(input_data, "text/plain")
    assert (output.data, output.content_type, output.extension) == (
        input_data,
        "image/svg+xml",
        "svg",
    )


def test_cache_images_rewrites_src_drops_srcset_and_sends_referer():
    input_html = (
        '<p>x</p><figure><img src="/img/a.png" srcset="/img/a-2x.png 2x" '
        'alt="A"></figure><video><source src="/v.mp4"></video>'
    )
    client, requests = create_client(
        {"https://site.example/img/a.png": (200, "image/png", png_bytes(40, 20))}
    )
    storage = RecordingStorage()

    output = cache_images(
        input_html,
        page_url="https://site.example/post",
        storage=storage,
        key_prefix="articles/7",
        client=client,
    )

    ((key, (_data, content_type)),) = storage.objects.items()
    summary = {
        "html": output.html,
        "cached": output.cached_count,
        "content_type": content_type,
        "key_prefix": key.rsplit("/", 1)[0],
        "referer": requests[0].headers["referer"],
    }
    # lxml's HTML serializer closes <source>; nh3 normalizes it downstream.
    expected_output = {
        "html": f'<p>x</p><figure><img src="https://cdn.example/{key}" alt="A">'
        '</figure><video><source src="https://site.example/v.mp4"></source></video>',
        "cached": 1,
        "content_type": "image/png",
        "key_prefix": "articles/7",
        "referer": "https://site.example/post",
    }
    assert summary == expected_output


def test_cache_images_keeps_absolute_original_on_failure():
    input_html = '<img src="a.png"><img src="https://cdn.example/b.png">'
    client, _requests = create_client(
        {"https://cdn.example/b.png": (200, "image/png", b"not an image")}
    )

    output = cache_images(
        input_html,
        page_url="https://site.example/post/",
        storage=RecordingStorage(),
        key_prefix="articles/1",
        client=client,
    )

    expected_output = (
        '<img src="https://site.example/post/a.png">'
        '<img src="https://cdn.example/b.png">'
    )
    assert (output.html, output.cached_count) == (expected_output, 0)


def test_cache_images_keeps_original_when_storage_fails():
    input_html = '<img src="https://site.example/a.png">'
    client, _requests = create_client(
        {"https://site.example/a.png": (200, "image/png", png_bytes(10, 10))}
    )

    output = cache_images(
        input_html,
        page_url="https://site.example/",
        storage=RecordingStorage(fail=True),
        key_prefix="articles/1",
        client=client,
    )

    assert output.html == input_html


def test_cache_images_skips_images_over_budget(monkeypatch):
    image = png_bytes(10, 10)
    # Room for one stored image, not two.
    monkeypatch.setattr("nanonerd.reader.images.MAX_TOTAL_BYTES", len(image) + 10)
    input_html = (
        '<img src="https://site.example/a.png"><img src="https://site.example/b.png">'
    )
    client, _requests = create_client(
        {
            "https://site.example/a.png": (200, "image/png", image),
            "https://site.example/b.png": (200, "image/png", image),
        }
    )
    storage = RecordingStorage()

    output = cache_images(
        input_html,
        page_url="https://site.example/",
        storage=storage,
        key_prefix="articles/1",
        client=client,
    )

    assert (output.cached_count, len(storage.objects)) == (1, 1)


def test_cache_images_refuses_private_hosts(monkeypatch):
    def private_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", private_getaddrinfo)
    client, requests = create_client({})

    output = cache_images(
        '<img src="http://internal.example/a.png">',
        page_url="https://site.example/",
        storage=RecordingStorage(),
        key_prefix="articles/1",
        client=client,
    )

    assert (output.cached_count, requests) == (0, [])


def test_local_storage_writes_under_root_and_returns_url(tmp_path):
    storage = LocalStorage(tmp_path, base_url="/media")
    output = storage.put("articles/3/abc.png", b"data", "image/png")
    assert (output, (tmp_path / "articles/3/abc.png").read_bytes()) == (
        "/media/articles/3/abc.png",
        b"data",
    )


def test_local_storage_rejects_escaping_keys(tmp_path):
    storage = LocalStorage(tmp_path / "media")
    with pytest.raises(StorageError):
        storage.put("../escape.png", b"data", "image/png")


def test_fetch_user_agent_is_phone_class():
    assert "iPhone" in fetch.USER_AGENT


def test_storage_from_env_refuses_local_disk_on_fly(monkeypatch):
    """On Fly without a bucket the disk is ephemeral: never store there, so
    images keep their origin URLs instead of dead `/media/...` links."""
    from nanonerd.reader.storage import storage_from_env

    for name in ("MEDIA_S3_BUCKET", "BUCKET_NAME", "MEDIA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FLY_APP_NAME", "nanonerd-reader")
    storage = storage_from_env()
    assert not isinstance(storage, LocalStorage)
    with pytest.raises(StorageError):
        storage.put("articles/1/x.png", b"png", "image/png")


def test_storage_from_env_honours_explicit_media_dir_on_fly(monkeypatch, tmp_path):
    from nanonerd.reader.storage import storage_from_env

    for name in ("MEDIA_S3_BUCKET", "BUCKET_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FLY_APP_NAME", "nanonerd-reader")
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path))
    storage = storage_from_env()
    assert isinstance(storage, LocalStorage)
    assert storage.put("a/b.png", b"png", "image/png") == "/media/a/b.png"


def test_storage_from_env_defaults_to_local_disk_off_fly(monkeypatch):
    from nanonerd.reader.storage import storage_from_env

    for name in ("MEDIA_S3_BUCKET", "BUCKET_NAME", "MEDIA_DIR", "FLY_APP_NAME"):
        monkeypatch.delenv(name, raising=False)
    assert isinstance(storage_from_env(), LocalStorage)
