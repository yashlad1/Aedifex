"""``aedifex-crawl``: the operator's entry point to the acquisition pipeline.

Four commands, and the split between them is the operational story:

.. code-block:: text

    sources                 what is registered, and what may actually be collected
    crawl <id> --dry-run    discover only: read listing pages, fill the frontier, fetch nothing
    crawl <id>              the real thing
    status                  the corpus, the queue depth, and recent runs

``--dry-run`` exists because a portal nobody has crawled before deserves a rehearsal. It answers
"does discovery work here, and what would we have collected?" at the cost of the site's listing
pages and nothing else, and it should precede the first real crawl of any new source.

This module is composition: it builds the stack and hands it a source. Every decision it appears to
make is really the registry's, which is the point — an operator cannot pass a URL, a rate, or a
permitted format on the command line, because those are reviewed configuration and not runtime
arguments.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config as BotoConfig
from sqlalchemy.orm import sessionmaker

from aedifex import __version__
from aedifex.acquisition.catalog import (
    corpus_summary,
    crawl_runs,
    queue_depth_by_source,
)
from aedifex.acquisition.crawl.runner import CrawlLimits, CrawlRunner
from aedifex.acquisition.fetch.controller import RetryController
from aedifex.acquisition.fetch.httpx_transport import HttpxTransport
from aedifex.acquisition.fetch.ratelimit import RateLimiter
from aedifex.acquisition.fetch.redirect_controller import RedirectController
from aedifex.acquisition.fetch.resolver import SystemResolver
from aedifex.acquisition.pipeline import Acquirer
from aedifex.acquisition.registry import get_registry
from aedifex.config import Settings, get_settings
from aedifex.errors import AedifexError
from aedifex.infrastructure.database.session import build_engine
from aedifex.infrastructure.observability.logging import configure_logging, get_logger
from aedifex.infrastructure.storage.objects import RawObjectStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

_log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    try:
        if args.command == "sources":
            return _sources()
        if args.command == "crawl":
            return _crawl(args, settings)
        if args.command == "status":
            return _status(args, settings)
    except AedifexError as error:
        # Our own refusals are operator-facing: a source that is not approved, a registry that does
        # not load, a Crawl-delay we will not wait for. A traceback would bury the sentence that
        # matters.
        print(f"error: {error}", file=sys.stderr)
        return 2
    parser.print_help()
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aedifex-crawl", description="Acquire public construction documents."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("sources", help="List registered sources and their review status")

    crawl = commands.add_parser("crawl", help="Crawl one source")
    crawl.add_argument("source_id")
    crawl.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover only: read listing pages and fill the frontier, downloading nothing",
    )
    crawl.add_argument("--max-documents", type=int, default=None)
    crawl.add_argument("--max-pages", type=int, default=None)
    crawl.add_argument("--max-seconds", type=float, default=None)
    crawl.add_argument("--batch-size", type=int, default=10)

    status = commands.add_parser("status", help="Show the corpus, the queue, and recent runs")
    status.add_argument("--source", default=None)
    status.add_argument("--runs", type=int, default=10)
    return parser


def _sources() -> int:
    registry = get_registry()
    print(f"{'SOURCE':<28} {'COLLECTABLE':<12} {'REVIEW':<12} {'CRAWLER':<14} RATE")
    print("-" * 88)
    for source in registry:
        print(
            f"{source.id:<28} {'yes' if source.is_collectable else 'no':<12} "
            f"{source.verification_status.value:<12} {source.crawler or '-':<14} "
            f"{source.rate_limit.requests_per_minute}/min"
        )
    print(f"\nCollectable now: {len(registry.collectable())} of {len(registry)}")
    return 0


def _crawl(args: argparse.Namespace, settings: Settings) -> int:
    source = get_registry(settings).get(args.source_id)
    limits = CrawlLimits(
        max_documents=args.max_documents,
        max_pages=args.max_pages,
        max_seconds=args.max_seconds,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )

    engine = build_engine(settings)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    store = RawObjectStore(_s3(settings), bucket=settings.storage_bucket)
    if not args.dry_run:
        # Idempotent, and an operator starting a crawl should not have to create a bucket by hand.
        # Skipped for a dry run, which stores nothing and should need no write permission at all.
        store.ensure_bucket()
    shutdown = _shutdown_signal()

    with HttpxTransport(user_agent=settings.user_agent) as transport:
        limiter = RateLimiter(global_concurrency=settings.max_global_concurrency)
        redirects = RedirectController(
            controller=RetryController(transport=transport, limiter=limiter),
            resolver=SystemResolver(),
        )
        runner = CrawlRunner(
            acquirer=Acquirer(
                redirects=redirects,
                store=store,
                staging=Path(settings.staging_dir),
                cancellation=shutdown,
            ),
            redirects=redirects,
            sessions=sessions,
            software_version=__version__,
            user_agent=settings.user_agent,
            cancellation=shutdown,
        )
        outcome = runner.run(source, limits=limits)

    print(outcome.describe())
    print(f"success rate {outcome.success_rate:.1%}, duplicate rate {outcome.duplicate_rate:.1%}")
    # A cancelled run is not a failure; it is a run that was asked to stop and did so cleanly.
    return 0 if outcome.succeeded or outcome.stop_reason.value == "cancelled" else 1


def _status(args: argparse.Namespace, settings: Settings) -> int:
    engine = build_engine(settings)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        summary = corpus_summary(session)
        depth = queue_depth_by_source(session)
        runs = crawl_runs(session, source_id=args.source, limit=args.runs)

    print("CORPUS")
    print(f"  {summary.describe()}")
    for source_id, count in sorted(summary.by_source.items()):
        print(f"    {source_id:<28} {count} documents")
    for file_format, count in sorted(summary.by_format.items()):
        print(f"    {file_format:<28} {count} documents")

    print("\nQUEUE DEPTH")
    if not depth:
        print("  (nothing waiting)")
    for source_id, count in sorted(depth.items()):
        print(f"  {source_id:<28} {count} URLs claimable")

    print("\nRECENT RUNS")
    if not runs:
        print("  (none)")
    for run in runs:
        duration = f"{run.duration_seconds:.0f}s" if run.duration_seconds is not None else "running"
        print(
            f"  {run.started_at:%Y-%m-%d %H:%M} {run.source_id:<20} {run.status.value:<10} "
            f"{run.stop_reason or '-':<18} stored={run.documents_stored:<5} "
            f"dup={run.documents_duplicate:<5} failed={run.documents_failed:<5} "
            f"bytes={run.bytes_downloaded:<12} {duration}"
        )
    return 0


def _s3(settings: Settings) -> S3Client:
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


def _shutdown_signal() -> threading.Event:
    """SIGINT and SIGTERM set a flag rather than raising.

    A crawler killed mid-fetch should finish releasing its lease and close its job row, so the next
    run resumes cleanly instead of waiting for a lease to expire. The flag is the same
    ``Cancellation`` token the fetch layer already understands, so a backoff is interrupted too.
    """
    flag = threading.Event()

    def stop(signum: int, _frame: FrameType | None) -> None:
        _log.warning("crawl.shutdown_requested", signal=signum)
        flag.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    return flag


if __name__ == "__main__":
    sys.exit(main())
