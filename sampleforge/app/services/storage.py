"""Artifact storage for rendered samples.

Two backends behind one protocol: :class:`LocalStorage` for development and
:class:`S3Storage` for production. The worker only sees the protocol, and
:class:`StorageError` carries the transient/permanent distinction the retry
policy needs.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: Characters allowed in a generated object key. Anything else is rejected
# rather than escaped: keys reach a filesystem in local development and a
# bucket in production, and a traversal in a key is a bug either way.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class StorageError(RuntimeError):
    """Base class for storage failures."""


class TransientStorageError(StorageError):
    """A storage failure worth retrying: timeouts, 5xx, connection resets."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    """A file that has been written somewhere."""

    key: str
    url: str
    size_bytes: int


def build_key(job_id: str, variant: int, extension: str) -> str:
    """Build a storage key for one variant of one job.

    Args:
        job_id: The job the variant belongs to.
        variant: Zero-based index within the batch.
        extension: File extension without the dot.

    Returns:
        A key of the form ``samples/<job_id>/<job_id>_0.wav``.

    Raises:
        ValueError: If any component contains unsafe characters.
    """
    suffix = extension.lstrip(".")
    key = f"{settings.s3_prefix.strip('/')}/{job_id}/{job_id}_{variant}.{suffix}"
    if not _KEY_PATTERN.match(key):
        raise ValueError(f"unsafe storage key: {key!r}")
    return key


class Storage(Protocol):
    """Where rendered samples are written."""

    async def upload(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        """Write ``data`` at ``key``.

        Args:
            key: Destination key, from :func:`build_key`.
            data: File contents.
            content_type: MIME type recorded with the object.

        Returns:
            The stored object's key, URL, and size.

        Raises:
            TransientStorageError: If the write failed but retrying may help.
            StorageError: If the write failed permanently.
        """
        ...


class LocalStorage:
    """Writes artifacts to a directory on disk.

    The default backend so a developer needs no credentials to run the worker.
    """

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.local_storage_dir)

    async def upload(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Off the event loop: disk I/O with a real network filesystem blocks.
        await asyncio.to_thread(destination.write_bytes, data)
        return StoredObject(
            key=key,
            url=destination.resolve().as_uri(),
            size_bytes=len(data),
        )


class S3Storage:
    """Uploads artifacts to S3 or an S3-compatible store.

    :mod:`boto3` is imported lazily inside :meth:`_client` so that a
    development environment without AWS credentials — or without boto3 at all —
    can still import this module and use the local backend.
    """

    def __init__(
        self,
        bucket: str | None = None,
        *,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        self.bucket = bucket or settings.s3_bucket
        if not self.bucket:
            raise StorageError("s3_bucket is required for the s3 storage backend")
        self.endpoint_url = endpoint_url or settings.s3_endpoint_url
        self.region = region or settings.s3_region

    def _client(self) -> object:
        """Build a boto3 S3 client.

        Returns:
            A ``boto3.client("s3", ...)``.

        Raises:
            StorageError: If boto3 is not installed.
        """
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise StorageError("boto3 is required for the s3 storage backend") from exc
        return boto3.client("s3", endpoint_url=self.endpoint_url, region_name=self.region)

    async def upload(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        client = self._client()
        try:
            await asyncio.to_thread(
                client.put_object,  # type: ignore[attr-defined]
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except Exception as exc:
            # botocore's ClientError carries a status code; anything without a
            # retryable one (access denied, no such bucket) is permanent.
            status = _http_status(exc)
            if status is None or status == 429 or status >= 500:
                raise TransientStorageError(f"s3 upload failed: {exc}") from exc
            raise StorageError(f"s3 upload rejected: {exc}") from exc

        base = (
            f"https://{self.bucket}.s3.amazonaws.com"
            if not self.endpoint_url
            else (f"{self.endpoint_url.rstrip('/')}/{self.bucket}")
        )
        return StoredObject(key=key, url=f"{base}/{key}", size_bytes=len(data))


def _http_status(exc: Exception) -> int | None:
    """Extract an HTTP status code from a botocore-style exception."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(status, int):
            return status
    return None


def get_storage() -> Storage:
    """Return the storage backend named by settings.

    Returns:
        A :class:`S3Storage` or :class:`LocalStorage`.

    Raises:
        StorageError: If the configured backend name is unknown.
    """
    backend = settings.storage_backend.strip().lower()
    if backend == "local":
        return LocalStorage()
    if backend == "s3":
        return S3Storage()
    raise StorageError(f"unknown storage backend: {settings.storage_backend!r}")


_CONTENT_TYPES = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
}


def content_type_for(fmt: str) -> str:
    """MIME type for an encoded sample.

    Args:
        fmt: One of ``wav``, ``flac``, ``mp3``.

    Returns:
        The MIME type to store the object with.

    Raises:
        ValueError: If the format is unknown.
    """
    try:
        return _CONTENT_TYPES[fmt.lower().lstrip(".")]
    except KeyError as exc:
        raise ValueError(f"unknown output format: {fmt!r}") from exc
