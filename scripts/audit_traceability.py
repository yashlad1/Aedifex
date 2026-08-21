"""Walk every stored finding back to an immutable raw artifact, and report where the walk stops.

    Finding -> Evidence -> Derived Fact -> Fact         -> Document -> Page/Cell -> Raw Artifact
                        -> Policy Provision -^

This is the property the platform exists to provide, so it is checked rather than assumed. Nothing
here reads the pipeline's code paths: it reads only what was persisted, which is the point — a chain
that holds only because the code that wrote it is still in memory is not a chain an auditor can use.

Exits non-zero when a **conclusive** finding cannot be traced. A PASS, FAIL or REVIEW that cites
nothing is a verdict with no basis, and the first run of this audit found thirty-eight of them.
An INCONCLUSIVE citing nothing is reported but tolerated: it asserts only that a fact was missing,
and there is no evidence for an absence.

Needs the database and the object store, so it is an operator command rather than a CI gate::

    python -m scripts.audit_traceability
    python -m scripts.audit_traceability --skip-objects   # database only, no S3 calls
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING

import boto3
from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.config import Settings, get_settings
from aedifex.infrastructure.database.models import (
    DerivedFact,
    Document,
    DocumentRetrieval,
    DocumentUpload,
    ExtractedFact,
    Finding,
    FindingEvidence,
    PolicyProvision,
)
from aedifex.infrastructure.database.session import build_engine
from aedifex.infrastructure.storage.objects import RawObjectStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

# Outcomes that assert something about the world. These must be traceable; an INCONCLUSIVE need not
# be, because its whole content is that the evidence was not there.
_CONCLUSIVE = frozenset({"pass", "fail", "review"})


class Audit:
    """Accumulated results. Breaks are grouped by kind so one systemic fault reads as one fault."""

    def __init__(self) -> None:
        self.counts: defaultdict[str, int] = defaultdict(int)
        self.breaks: defaultdict[str, list[str]] = defaultdict(list)
        self.fatal = False

    def note(self, key: str) -> None:
        self.counts[key] += 1

    def broke(self, kind: str, detail: str, *, fatal: bool) -> None:
        self.breaks[kind].append(detail)
        if fatal:
            self.fatal = True


def _s3_client(settings: Settings) -> S3Client:
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
    )
    return client


def _check_provision(
    session: Session, provision_id: uuid.UUID, audit: Audit, *, fatal: bool, **kwargs: object
) -> None:
    """A cited provision, from its clause down to the reference document's bytes.

    A provision is a third kind of evidence and traces the same way as the other two: it names a
    clause, a page and a document, and that document has to exist with a matching digest. What it
    does *not* do is claim to be a measurement, which is the distinction the type exists for.
    """
    audit.note("provisions")
    provision = session.get(PolicyProvision, provision_id)
    if provision is None:
        audit.broke("evidence points at a missing provision", str(provision_id), fatal=fatal)
        return
    document = session.get(Document, provision.document_id)
    if document is None:
        audit.broke(
            "provision belongs to no document",
            f"{provision.clause} id={provision.id}",
            fatal=fatal,
        )
        return
    audit.note("documents reached")
    store = kwargs.get("store")
    verified = kwargs.get("verified")
    if not isinstance(store, RawObjectStore) or not isinstance(verified, dict):
        return
    key = document.storage_key
    if key not in verified:
        metadata = store.head(key)
        verified[key] = metadata is not None and metadata.sha256 == document.sha256
    if verified[key]:
        audit.note("raw artifacts confirmed")
    else:
        audit.broke(
            "raw artifact missing, or its digest does not match the document",
            f"{document.original_filename} key={key}",
            fatal=fatal,
        )


def _facts_behind(
    session: Session, link: FindingEvidence, finding: Finding, audit: Audit, *, fatal: bool
) -> list[ExtractedFact]:
    """The extracted facts one evidence link ultimately rests on.

    A link cites exactly one of a fact, a derived fact, or a policy provision — the check constraint
    enforces it. A derived fact is resolved through its recorded inputs, because a computed value is
    only evidence if the values it came from are; a provision is handled by the caller, since it
    resolves to a clause rather than to a fact.
    """
    if link.provision_id is not None:
        return []
    if link.fact_id is not None:
        fact = session.get(ExtractedFact, link.fact_id)
        if fact is None:
            audit.broke("evidence points at a missing fact", f"rule {finding.rule_id}", fatal=fatal)
            return []
        return [fact]

    if link.derived_fact_id is None:
        audit.broke(
            "evidence cites none of a fact, a derived fact, or a provision",
            f"rule {finding.rule_id} finding={finding.id}",
            fatal=fatal,
        )
        return []

    audit.note("derived facts")
    derived = session.get(DerivedFact, link.derived_fact_id)
    if derived is None:
        audit.broke(
            "evidence points at a missing derived fact", str(link.derived_fact_id), fatal=fatal
        )
        return []
    inputs = [row.fact for row in derived.inputs if row.fact is not None]
    # A calculation may rest partly on a provision, which is a legitimate input rather than a
    # missing one -- "required bid security" is a rate schedule's share applied to a stated cost.
    applied = [row for row in derived.inputs if row.provision_id is not None]
    for row in applied:
        if row.provision_id is not None:
            _check_provision(session, row.provision_id, audit, fatal=fatal)
    if not inputs and not applied:
        audit.broke(
            "derived fact records no inputs",
            f"{derived.fact_type} id={derived.id} (rule {finding.rule_id})",
            fatal=fatal,
        )
    return inputs


def _check_fact(
    session: Session,
    fact: ExtractedFact,
    audit: Audit,
    *,
    fatal: bool,
    store: RawObjectStore | None,
    verified: dict[str, bool],
) -> None:
    """One fact, from its locator down to the bytes it was read out of."""
    audit.note("facts reached")

    # The locator needs no check here: ``extracted_facts.page`` is NOT NULL and carries a
    # ``page >= 1`` constraint, with ``sheet_row``/``sheet_column`` narrowing it to a cell for
    # spreadsheet facts. mypy rejected the check as unreachable, which is the better outcome — an
    # invariant the database enforces is stronger than one a script confirms after the fact.
    document = session.get(Document, fact.document_id) if fact.document_id is not None else None
    if document is None:
        audit.broke("fact belongs to no document", f"{fact.fact_type} id={fact.id}", fatal=fatal)
        return
    audit.note("documents reached")

    # Provenance is either a retrieval or an upload. Both are real; neither may be absent.
    retrieved = session.execute(
        select(DocumentRetrieval.document_id).where(DocumentRetrieval.document_id == document.id)
    ).first()
    uploaded = session.execute(
        select(DocumentUpload.document_id).where(DocumentUpload.document_id == document.id)
    ).first()
    if retrieved is None and uploaded is None:
        audit.broke(
            "document has no provenance row",
            f"{document.original_filename} id={document.id}",
            fatal=fatal,
        )

    if store is None:
        return
    key = document.storage_key
    if key not in verified:
        metadata = store.head(key)
        verified[key] = metadata is not None and metadata.sha256 == document.sha256
    if verified[key]:
        audit.note("raw artifacts confirmed")
    else:
        audit.broke(
            "raw artifact missing, or its digest does not match the document",
            f"{document.original_filename} key={key}",
            fatal=fatal,
        )


def run(*, skip_objects: bool) -> Audit:
    settings = get_settings()
    audit = Audit()
    store = (
        None
        if skip_objects
        else RawObjectStore(_s3_client(settings), bucket=settings.storage_bucket)
    )
    verified: dict[str, bool] = {}

    with Session(build_engine(settings)) as session:
        for finding in session.execute(select(Finding)).scalars():
            audit.note("findings")
            conclusive = finding.outcome in _CONCLUSIVE
            links = list(
                session.execute(
                    select(FindingEvidence).where(FindingEvidence.finding_id == finding.id)
                ).scalars()
            )
            if not links:
                audit.broke(
                    f"{finding.outcome} finding cites no evidence at all",
                    f"{finding.rule_id} id={finding.id}",
                    fatal=conclusive,
                )
                continue
            for link in links:
                audit.note("evidence links")
                if link.provision_id is not None:
                    _check_provision(
                        session,
                        link.provision_id,
                        audit,
                        fatal=conclusive,
                        store=store,
                        verified=verified,
                    )
                    continue
                for fact in _facts_behind(session, link, finding, audit, fatal=conclusive):
                    _check_fact(
                        session, fact, audit, fatal=conclusive, store=store, verified=verified
                    )
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-objects",
        action="store_true",
        help="Do not contact object storage; check the database chain only.",
    )
    args = parser.parse_args(argv)

    audit = run(skip_objects=args.skip_objects)

    print("=" * 78)
    print("TRACEABILITY AUDIT  —  Finding -> ... -> Immutable Raw Artifact")
    print("=" * 78)
    for key in sorted(audit.counts):
        print(f"  {key:<26} {audit.counts[key]}")
    print()

    if not audit.breaks:
        print("  Chain intact for every finding.")
        return 0

    for kind in sorted(audit.breaks):
        details = sorted(set(audit.breaks[kind]))
        print(f"  {kind}  ({len(audit.breaks[kind])})")
        for detail in details[:8]:
            print(f"    - {detail}")
        if len(details) > 8:
            print(f"    ... and {len(details) - 8} more distinct")
        print()

    if audit.fatal:
        print("FAILED: a finding that asserts something cannot be traced to stored evidence.")
        return 1
    print("Tolerated: every break is an inconclusive finding, which asserts no value to trace.")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    sys.exit(main())
