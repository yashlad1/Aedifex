"""Building the S3 client both applications hand to :class:`RawObjectStore`.

Its own module rather than a function in ``objects.py``, because that module documents a deliberate
decision: the store takes an *injected* client, since credentials, endpoints and retry policy are
the caller's concern and a store that builds its own from ambient settings cannot be pointed at a
different bucket. That still holds. What was not sensible was two applications each carrying an
identical copy of the construction — the CLI had one, and the API needed the same one the moment it
accepted an upload, which is exactly when a drift between them would matter.

Settings are passed in, never read here. ``endpoint_url`` is ``None`` against real S3 and set
against MinIO, and the explicit keys are ``None`` when an instance role or ``~/.aws/credentials``
should supply them — boto's own resolution order is right, and this must not preempt it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config as BotoConfig

from aedifex.config import Settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

__all__ = ["build_s3_client"]


def build_s3_client(settings: Settings) -> S3Client:
    """An S3 client configured from ``settings``. Signature v4, three attempts."""
    client: S3Client = boto3.client(
        "s3",
        endpoint_url=settings.storage_endpoint_url,
        aws_access_key_id=(
            settings.storage_access_key_id.get_secret_value()
            if settings.storage_access_key_id
            else None
        ),
        aws_secret_access_key=(
            settings.storage_secret_access_key.get_secret_value()
            if settings.storage_secret_access_key
            else None
        ),
        region_name=settings.storage_region,
        config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 3}),
    )
    return client
