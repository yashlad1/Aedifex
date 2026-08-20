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
import uuid
from decimal import Decimal
from ipaddress import ip_address
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config as BotoConfig
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

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
from aedifex.acquisition.registry.models import SourceDefinition
from aedifex.config import Settings, get_settings
from aedifex.errors import AedifexError, ConfigurationError
from aedifex.extraction.projects import reconcile_projects
from aedifex.extraction.runner import (
    DEFAULT_MAX_PAGES,
    AnalysisOutcome,
    ProjectAnalysis,
    analyse_document,
    analyse_project,
)
from aedifex.infrastructure.database.models import Document, ExtractedFact, Project
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
        if args.command == "analyse":
            return _analyse(args, settings)
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

    analyse = commands.add_parser(
        "analyse", help="Extract facts from an acquired document and evaluate the rules"
    )
    target = analyse.add_mutually_exclusive_group(required=True)
    target.add_argument("document_id", nargs="?", help="A document UUID from the catalog")
    target.add_argument(
        "--all", action="store_true", help="Analyse every acquired document, oldest first"
    )
    target.add_argument(
        "--project", metavar="PROJECT_ID", help="Evaluate cross-document rules for one project"
    )
    target.add_argument(
        "--all-projects",
        action="store_true",
        help="Reconcile projects from extracted identifiers, then evaluate every one",
    )
    analyse.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    analyse.add_argument(
        "--prescribed-share",
        type=Decimal,
        default=None,
        metavar="FRACTION",
        help=(
            "Bid-security rate to judge against, as a fraction (0.01 for 1%%). Use only for a rate "
            "you can cite; without it, a document that states no rate is measured, not judged."
        ),
    )

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


def _is_remote(source: SourceDefinition) -> bool:
    """Whether crawling this source puts packets on a network someone else operates.

    Loopback is the only exemption, because the one legitimate placeholder-contact crawl is against
    a portal we are running ourselves. Anything else — including a source that merely looks
    internal — is somebody's server, and it gets a real contact address.
    """
    if source.base_url is None:
        return False
    host = (source.base_url.host or "").lower()
    if host in {"localhost", "localhost."}:
        return False
    try:
        return not ip_address(host).is_loopback
    except ValueError:
        # A name, not a literal. It could resolve to loopback, but deciding that here would mean
        # trusting DNS to tell us whether a safety rule applies.
        return True


def _crawl(args: argparse.Namespace, settings: Settings) -> int:
    source = get_registry(settings).get(args.source_id)
    if _is_remote(source) and not settings.user_agent_names_a_real_contact():
        # A fake contact is worse than an anonymous one: a site operator who tries to reach us about
        # our traffic gets a bounce. Refused here rather than in Settings, because the default
        # placeholder has to keep working for tests and local runs — what must not happen is sending
        # it to a real portal.
        #
        # This used to exempt --dry-run, which was wrong. A dry run skips *document* downloads; it
        # still fetches robots.txt and every listing page, so the operator still sees the traffic
        # and still reads the contact. DATA_SOURCES.md lists crawling without a reachable contact
        # under hard limits that hold regardless of review outcome, and a rehearsal against a real
        # portal is still a crawl of it. The exemption is the host, not the mode.
        raise ConfigurationError(
            f"user_agent {settings.user_agent!r} carries a placeholder contact address, and "
            f"{source.id!r} is a real remote source. A crawl of one — including a --dry-run, which "
            f"still requests robots.txt and listing pages — must offer a contact a site operator "
            f"can reach (see DATA_SOURCES.md). Set AEDIFEX_USER_AGENT."
        )
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


def _analyse(args: argparse.Namespace, settings: Settings) -> int:
    """Run the analysis pipeline and print the evidence behind every verdict.

    The output leads with the finding and then shows the facts it rested on, page by page, because a
    verdict a reader cannot trace is not worth printing. An ``INCONCLUSIVE`` result is displayed as
    plainly as a pass: the ratio is still shown, and ``expected`` reads ``NOT SOURCED`` so that
    "we did not judge this" can never be mistaken for "this passed".
    """
    engine = build_engine(settings)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    if args.project or args.all_projects:
        return _analyse_projects(args, sessions)

    store = RawObjectStore(_s3(settings), bucket=settings.storage_bucket)

    with sessions() as session:
        if args.all:
            targets = list(
                session.execute(select(Document.id).order_by(Document.first_seen_at)).scalars()
            )
        else:
            targets = [uuid.UUID(args.document_id)]

        if not targets:
            print("no acquired documents to analyse")
            return 0

        failures = 0
        for index, document_id in enumerate(targets):
            if index:
                print()
            try:
                outcome = analyse_document(
                    session,
                    store,
                    document_id,
                    max_pages=args.max_pages,
                    prescribed_share=args.prescribed_share,
                )
                session.commit()
            except AedifexError as error:
                session.rollback()
                failures += 1
                print(f"{document_id}  ERROR  {error}")
                continue
            _print_analysis(session, outcome)

    return 1 if failures else 0


def _analyse_projects(args: argparse.Namespace, sessions: sessionmaker[Session]) -> int:
    """Evaluate cross-document rules, reconciling project membership first.

    Reconciliation runs before evaluation for ``--all-projects``: a project that does not exist yet
    cannot be evaluated, and membership derives from facts analysis has already stored. It is
    idempotent, so doing it every time costs nothing and removes a step an operator can forget.
    """
    with sessions() as session:
        if args.all_projects:
            outcome = reconcile_projects(session)
            session.commit()
            print(f"RECONCILED\n  {outcome.describe()}\n")
            project_ids = list(
                session.execute(select(Project.id).order_by(Project.external_ref)).scalars()
            )
        else:
            project_ids = [uuid.UUID(args.project)]

        if not project_ids:
            print("no projects; run `analyse --all` first so documents yield identifier facts")
            return 0

        failures = 0
        for index, project_id in enumerate(project_ids):
            if index:
                print()
            try:
                analysis = analyse_project(session, project_id)
                session.commit()
            except AedifexError as error:
                session.rollback()
                failures += 1
                print(f"{project_id}  ERROR  {error}")
                continue
            _print_project(session, analysis)

    return 1 if failures else 0


def _print_project(session: Session, analysis: ProjectAnalysis) -> None:
    """Print a project's evidence chain: documents, relationships, compared facts, findings."""
    project = analysis.project
    print(f"PROJECT  {project.external_ref}")
    print(f"  id {project.id}   source {project.source_id}")
    print(f"  membership established by {project.established_by}")

    print("\nDOCUMENTS")
    for document in analysis.documents:
        print(
            f"  {(document.original_filename or str(document.id)):38} "
            f"{document.size_bytes:>9} bytes  {document.id}"
        )

    print("\nRELATIONSHIPS")
    if not analysis.relationships:
        print("  (none: a project of one document has no pairs to relate)")
    for link in analysis.relationships:
        print(
            f"  {analysis.filename(link.from_document_id)} "
            f"--{link.relationship_type.value}--> {analysis.filename(link.to_document_id)}"
        )
        print(f"  {'':4}established by {link.established_by}")

    print("\nFACTS")
    for fact in sorted(analysis.facts, key=lambda f: (f.fact_type, str(f.document_id))):
        value = f"{fact.numeric_value:,}" if fact.numeric_value is not None else fact.literal
        print(
            f"  {fact.fact_type:32} {value:>18}  [{fact.kind.value}]  "
            f"{analysis.filename(fact.document_id)} p{fact.page}"
        )

    print("\nFINDINGS")
    for finding in analysis.findings:
        print(f"  {finding.rule_id} (v{finding.rule_version})")
        print(f"    observed  {finding.observed}")
        print(f"    expected  {finding.expected}")
        print(f"    result    {finding.outcome.upper()}")
        print(f"    {finding.summary}")
        for citation in sorted(finding.evidence, key=lambda e: e.role):
            cited = session.get(ExtractedFact, citation.fact_id)
            if cited is None:
                continue
            print(
                f"    evidence  {citation.role:26} {analysis.filename(cited.document_id)} "
                f"p{cited.page}: {cited.snippet[:90]}"
            )


def _print_analysis(session: Session, outcome: AnalysisOutcome) -> None:
    document = session.get(Document, outcome.document_id)
    name = (document.original_filename if document else None) or str(outcome.document_id)
    print(f"DOCUMENT  {name}")
    print(f"  id {outcome.document_id}")
    print(
        f"  {outcome.page_count} pages, {outcome.pages_read} read"
        f"{'' if outcome.had_text_layer else '  (NO TEXT LAYER - needs OCR)'}"
    )

    if outcome.facts:
        print("\nFACTS")
        for fact in sorted(outcome.facts, key=lambda f: f.fact_type):
            value = f"{fact.numeric_value:,}" if fact.numeric_value is not None else fact.literal
            unit = f" {fact.currency}" if fact.currency else ""
            print(f"  {fact.fact_type:32} {value}{unit}")
            print(f"  {'':32} literal {fact.literal!r}  page {fact.page}  [{fact.method}]")

    print("\nFINDINGS")
    for finding in outcome.findings:
        print(f"  {finding.rule_id} (v{finding.rule_version})")
        print(f"    observed  {finding.observed}")
        print(f"    expected  {finding.expected}")
        print(f"    result    {finding.outcome.upper()}")
        print(f"    {finding.summary}")
        for link in sorted(finding.evidence, key=lambda e: e.role):
            cited = session.get(ExtractedFact, link.fact_id)
            if cited is not None:
                print(f"    evidence  {link.role} -> page {cited.page}: {cited.snippet[:140]}")

    for note in outcome.unsupported:
        print(f"  not extracted: {note}")


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
