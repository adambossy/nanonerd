"""Where cached article media lives: local disk for dev, S3-compatible for prod."""

import logging
import os
from pathlib import Path
from typing import Protocol

import boto3

from nanonerd.reader.errors import ReaderError

logger = logging.getLogger(__name__)


class StorageError(ReaderError):
    """A media object could not be stored."""


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> str:
        """Store `data` under `key` and return its public URL."""
        ...


class LocalStorage:
    def __init__(self, root: Path, *, base_url: str = "/media") -> None:
        self.root = root
        self._base_url = base_url.rstrip("/")

    def put(self, key: str, data: bytes, content_type: str) -> str:
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise StorageError(f"refusing to write outside media root: {key}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            raise StorageError(f"could not write {key}: {exc}") from exc
        return f"{self._base_url}/{key}"


class S3Storage:
    def __init__(
        self,
        *,
        bucket: str,
        public_base_url: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/")
        self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def put(self, key: str, data: bytes, content_type: str) -> str:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl="public, max-age=31536000, immutable",
            )
        except Exception as exc:  # boto3 raises many unrelated classes
            raise StorageError(f"S3 upload of {key} failed: {exc}") from exc
        return f"{self._public_base_url}/{key}"


class UnavailableStorage:
    """Stand-in when no durable store is configured on an ephemeral host.

    Every `put` fails, so `cache_images` leaves each image on its origin URL
    (still renders, just not re-hosted) rather than writing `/media/...` links
    that point at a disk nothing serves.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def put(self, key: str, data: bytes, content_type: str) -> str:
        raise StorageError(self._reason)


def storage_from_env() -> Storage:
    """S3 when `MEDIA_S3_BUCKET` (or Tigris' `BUCKET_NAME`) is set, else local disk.

    Fly Tigris injects `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
    `AWS_ENDPOINT_URL_S3` and `BUCKET_NAME`; boto3 picks the credentials up
    from the environment on its own.

    On Fly (`FLY_APP_NAME` set) the root disk is ephemeral and the web process
    only serves `/media` when it is itself on local storage, so without a
    bucket — and without an explicit `MEDIA_DIR` opt-in — images are left
    un-cached instead of silently stored where nobody can read them.
    """
    bucket = os.environ.get("MEDIA_S3_BUCKET") or os.environ.get("BUCKET_NAME")
    if bucket:
        endpoint = os.environ.get("MEDIA_S3_ENDPOINT") or os.environ.get(
            "AWS_ENDPOINT_URL_S3"
        )
        public_base = os.environ.get(
            "MEDIA_PUBLIC_BASE_URL", f"https://{bucket}.fly.storage.tigris.dev"
        )
        return S3Storage(
            bucket=bucket, public_base_url=public_base, endpoint_url=endpoint
        )
    media_dir = os.environ.get("MEDIA_DIR")
    if media_dir is None and os.environ.get("FLY_APP_NAME"):
        reason = (
            "no media bucket configured (set BUCKET_NAME/MEDIA_S3_BUCKET, or "
            "MEDIA_DIR to opt into local disk); images will not be cached"
        )
        logger.warning(reason)
        return UnavailableStorage(reason)
    root = Path(media_dir or "./media")
    return LocalStorage(root, base_url=os.environ.get("MEDIA_BASE_URL", "/media"))
