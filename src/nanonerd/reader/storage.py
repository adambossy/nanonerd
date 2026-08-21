"""Where cached article media lives: local disk for dev, S3-compatible for prod."""

import os
from pathlib import Path
from typing import Protocol

import boto3

from nanonerd.reader.errors import ReaderError


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


def storage_from_env() -> Storage:
    """S3 when `MEDIA_S3_BUCKET` (or Tigris' `BUCKET_NAME`) is set, else local disk.

    Fly Tigris injects `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
    `AWS_ENDPOINT_URL_S3` and `BUCKET_NAME`; boto3 picks the credentials up
    from the environment on its own.
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
    root = Path(os.environ.get("MEDIA_DIR", "./media"))
    return LocalStorage(root, base_url=os.environ.get("MEDIA_BASE_URL", "/media"))
