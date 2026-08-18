"""Fixtures for the integration suite: PostgreSQL, MinIO, a local portal, and the fetch stack.

Every one of these skips when its infrastructure is missing, so ``make test`` stays runnable with
nothing installed — and fails instead of skipping when ``REQUIRE_INTEGRATION_TESTS=1`` is set, which
CI does. A skipped test must never be mistaken for a verified one (rule 81e).

``test_database.py`` deliberately defines its own ``engine``, ``session``, and ``settings``: its
subject is the migration itself, including a full downgrade/upgrade cycle, and a module-level
fixture shadows the one here. Separate means a failure in either reads as a failure in one.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import boto3
import pytest
from alembic import command
from alembic.config import Config
from botocore.config import Config as BotoConfig
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from aedifex.acquisition.fetch.controller import RetryController
from aedifex.acquisition.fetch.httpx_transport import HttpxTransport
from aedifex.acquisition.fetch.ratelimit import RateLimiter
from aedifex.acquisition.fetch.redirect_controller import RedirectController
from aedifex.acquisition.fetch.resolver import ResolvedAddress
from aedifex.acquisition.fetch.retry import BackoffPolicy, RetryPolicy
from aedifex.config import Environment, Settings
from aedifex.infrastructure.database.session import build_engine
from aedifex.infrastructure.storage.objects import RawObjectStore
from tests.integration.support import HOSTNAME, LOOPBACK, USER_AGENT, Portal

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _require_or_skip(message: str) -> None:
    if os.environ.get("REQUIRE_INTEGRATION_TESTS") == "1":
        pytest.fail(f"{message}. REQUIRE_INTEGRATION_TESTS=1 forbids skipping.")
    pytest.skip(message)


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(environment=Environment.TEST)


@pytest.fixture(scope="module")
def engine(settings: Settings) -> Iterator[Engine]:
    """A database migrated to ``head``."""
    candidate = build_engine(settings)
    try:
        with candidate.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (OperationalError, DBAPIError) as error:
        candidate.dispose()
        _require_or_skip(f"PostgreSQL is not reachable: {type(error).__name__}")
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", str(settings.database_url))
    command.upgrade(config, "head")
    yield candidate
    candidate.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose tables are emptied afterwards, so tests cannot see each other's rows."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as active:
        yield active
        active.rollback()
        active.execute(
            text("TRUNCATE TABLE document_retrievals, discovered_urls, documents CASCADE")
        )
        active.commit()


@pytest.fixture(scope="module")
def store(settings: Settings) -> Iterator[RawObjectStore]:
    """A store against a real MinIO, in a bucket of its own.

    Per-module bucket with a random name, so a leftover object from an earlier run cannot make an
    idempotence assertion pass for the wrong reason.
    """
    endpoint = settings.storage_endpoint_url or "http://localhost:9000"
    access_key = settings.storage_access_key_id
    secret_key = settings.storage_secret_access_key
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.storage_region,
        aws_access_key_id=access_key.get_secret_value() if access_key else "minioadmin",
        aws_secret_access_key=secret_key.get_secret_value() if secret_key else "minioadmin",
        # Short timeouts and one attempt: an absent store should skip in a second rather than
        # spend a minute retrying before deciding.
        config=BotoConfig(
            connect_timeout=2,
            read_timeout=10,
            retries={"max_attempts": 1},
            signature_version="s3v4",
        ),
    )
    bucket = f"aedifex-it-{uuid.uuid4().hex[:12]}"
    candidate = RawObjectStore(client, bucket=bucket)
    try:
        candidate.ensure_bucket()
    except Exception as error:  # any failure here means the store is unusable
        _require_or_skip(f"MinIO is not reachable at {endpoint}: {type(error).__name__}")
    yield candidate

    # Every version has to go before the bucket can, because versioning is on and a plain delete
    # only adds a delete marker. Done here and nowhere else: RawObjectStore deliberately cannot
    # remove raw evidence, and a test's teardown is the only place that ability belongs. The two
    # groups are read separately rather than by looping over their names, which would make both
    # `object` to mypy.
    paginator = client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        targets: list[Any] = [
            {"Key": entry["Key"], "VersionId": entry["VersionId"]}
            for entry in page.get("Versions", [])
        ]
        targets += [
            {"Key": marker["Key"], "VersionId": marker["VersionId"]}
            for marker in page.get("DeleteMarkers", [])
        ]
        if targets:
            client.delete_objects(Bucket=bucket, Delete={"Objects": targets})
    client.delete_bucket(Bucket=bucket)


@pytest.fixture
def portal() -> Iterator[Portal]:
    """A local portal on an ephemeral port.

    ``poll_interval`` is small because ``shutdown()`` waits for the current poll to return, and
    the 0.5s default would be charged to every test as pure teardown.
    """
    server = Portal()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.daemon = True
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


class LoopbackResolver:
    """Points the test hostname at loopback, and records every lookup."""

    def __init__(self) -> None:
        self.lookups: list[str] = []

    def resolve(self, hostname: str, port: int) -> tuple[ResolvedAddress, ...]:
        self.lookups.append(hostname)
        if hostname != HOSTNAME:
            raise OSError(f"no scripted DNS entry for {hostname!r}")
        return (ResolvedAddress(ip=ip_address(LOOPBACK), port=port),)


@pytest.fixture
def resolver() -> LoopbackResolver:
    return LoopbackResolver()


@pytest.fixture
def redirects(resolver: LoopbackResolver) -> Iterator[RedirectController]:
    """The real fetch stack: guard, redirect loop, retry loop, transport.

    Backoff is short so a retried 503 costs milliseconds. Everything else is production
    configuration — the point of these tests is that the real thing works.
    """
    with HttpxTransport(user_agent=USER_AGENT) as transport:
        yield RedirectController(
            controller=RetryController(
                transport=transport,
                limiter=RateLimiter(global_concurrency=4),
                policy=RetryPolicy(
                    backoff=BackoffPolicy(base_seconds=0.01, max_delay_seconds=0.05, max_attempts=3)
                ),
            ),
            resolver=resolver,
        )
