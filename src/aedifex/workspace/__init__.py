"""The project workspace: declaring a project, giving it documents, and reading its state back.

This is the beginning of the product, and it exists because the middle of the pipeline was built
first. Facts, rules, findings, evidence and human review all worked before this module; what nobody
could do was *start* — a project could only come into existence by being inferred from two documents
that happened to quote the same identifier, and documents could only arrive through a shell command
run by someone holding the object-store credentials.

Four responsibilities, and the seams between them are the design:

**Declaration.** A project is now something a person states, not only something reconciliation
derives. Both write the same row, and ``established_by`` says which — ``declared:alice`` or
``shared_fact:nit_number``. They converge rather than compete: a declared project whose
``external_ref`` matches what the documents turn out to state is the row reconciliation finds.

**Intake.** Bytes arrive, become an immutable content-addressed artifact, get upload provenance, and
join a project. Never an invented HTTP retrieval — an upload has no status code, no requested URL
and no response headers, and inventing them would be fabricating provenance.

**Suggestion without authority.** A deterministic classifier proposes a document type into its own
column. Nothing here promotes a proposal, because ``document_type`` decides whether the extractor
treats a quoted amount as a fact about the document, and a role that looked inferable has already
produced five false facts from real documents.

**Projection.** The read models answer a reviewer's questions in one call each — what is in this
project, and where has it got to — rather than making a client reassemble state from the corpus
catalog, the facts endpoint, the findings endpoint and the reviews endpoint. They are read models
over existing tables and add no table of their own: every number below is already recorded
somewhere, and a stored summary would be a second copy that can disagree with the first.

What this module deliberately does not do: no queue (processing is synchronous and says so), no
authorization (see the API's own warning), no tenancy, no notifications, no assignment. Each of
those is a real thing to build once a real deployment needs it, and none is needed to move a real
building project through the workflow.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from aedifex import __version__
from aedifex.acquisition.content import document_id_for_digest
from aedifex.acquisition.registry.models import SourceDefinition
from aedifex.classification import Suggestion, classifier_identity, suggest_document_type
from aedifex.domain.documents import (
    ClassificationAuthority,
    DocumentState,
    DocumentType,
    category_for,
)
from aedifex.domain.evidence import DocumentRole
from aedifex.domain.files import (
    FORMATS_WITH_A_SIGNATURE,
    FileFormat,
    format_for_extension,
    format_for_media_type,
    formats_are_compatible,
    sniff_format,
)
from aedifex.domain.workflow import (
    ProcessingStatus,
    WorkflowCategory,
    needs_human_review,
    processing_status,
)
from aedifex.domain.workflow import workflow_category as category_of
from aedifex.errors import AedifexError
from aedifex.extraction import READABLE_FORMATS
from aedifex.extraction.ingest import ingest_file
from aedifex.extraction.projects import normalise_project_key
from aedifex.extraction.runner import (
    analyse_document,
    analyse_project,
    analyse_spreadsheet,
    record_analysis_failure,
)
from aedifex.infrastructure.database.models import (
    Document,
    DocumentRetrieval,
    DocumentUpload,
    ExtractedFact,
    Finding,
    Project,
    ProjectDocument,
)
from aedifex.infrastructure.observability.logging import get_logger
from aedifex.infrastructure.storage.objects import RawObjectStore

__all__ = [
    "AttachOutcome",
    "DocumentEntry",
    "IntakeError",
    "ProcessingReport",
    "ProjectSummary",
    "attach_upload",
    "confirm_document_type",
    "create_project",
    "process_project",
    "project_inventory",
    "project_summary",
]

_log = get_logger(__name__)

# Filenames arrive from a client and are attacker-controlled. They never reach a storage key — that
# is built from the digest — but they are stored, displayed, and used to name a temporary file, so
# the path separators of both families and any control characters come out here.
_PATH_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[\\/]")
_UNSAFE_NAME_CHARS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f]")
_MAX_FILENAME_CHARS: Final[int] = 128


class IntakeError(AedifexError):
    """An intake request that cannot be honoured as asked."""


def safe_filename(filename: str) -> str:
    """Reduce a client-stated filename to something safe to store and display.

    Takes the last path segment under either separator convention, because ``Path.name`` on POSIX
    treats a Windows path as one long name, and a client on Windows sends exactly that. Strips
    control characters, collapses whitespace, and bounds the length to the column's.

    Never used to build a storage key: those come from the content digest, so a hostile name cannot
    decide where bytes land. This is about what is *shown* and what a temporary file is called.
    """
    last = _PATH_SEPARATORS.split(filename)[-1]
    cleaned = _UNSAFE_NAME_CHARS.sub("", last).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(". ")
    return cleaned[:_MAX_FILENAME_CHARS] or "upload"


def create_project(
    session: Session,
    *,
    source: SourceDefinition,
    name: str,
    external_ref: str | None = None,
    description: str | None = None,
    created_by: str,
) -> Project:
    """Declare a project. The first thing a user does, and until now not possible at all.

    Args:
        source: Which registered source **namespaces this project's identifier**. Required because
            the column is, and because it carries one real invariant: ``external_ref`` is unique
            only within the authority that issued it, so two authorities can both publish tender
            ``PWD/2026/14`` and those are two projects.

            It is **not** ownership and it will not become tenancy. An earlier version of this
            docstring said it would; that was wrong, and it is the kind of wrong that turns into a
            security defect, because an authorization check written against an acquisition field
            looks correct and scopes nothing. Authorization arrives as
            ``Organization → Membership → Project``, in new columns.

            It also does not constrain what may be attached. A real project holds an owner-uploaded
            bill, a contractor's claim, a PMC certificate and a published rate schedule; those come
            from different sources and each document records its own origin. For a customer's own
            project the honest value is ``customer_provided``.
        name: What the owner calls it. Required and non-blank — a project nobody can name is not
            usefully distinguishable from the next one.
        external_ref: The identifier the *documents* use, if the owner knows it. Optional, and left
            null rather than synthesised: an invented reference in this column would break the one
            promise it makes.
        description: Free prose. Never parsed and never read by a rule.
        created_by: Who declared it. Recorded in ``established_by``, so the row says what justifies
            it in the same field a derived project uses to cite the fact that grouped it.

    Raises:
        IntakeError: if the name is blank, or if this source already has a project with this
            identifier. The existing project's id is in the message, because the caller almost
            certainly wants to attach documents to it rather than create a second one.
    """
    if not name.strip():
        raise IntakeError("a project needs a name")
    if not created_by.strip():
        raise IntakeError("a project needs an author: 'who declared this' is provenance")

    # Normalised exactly as reconciliation normalises an extracted identifier — case and internal
    # whitespace only. Otherwise a project declared as "IITB/Dean (IPS)/..." and the same reference
    # read off page 1 as "IITB/DEAN (IPS)/..." would become two projects for one building, and every
    # cross-document rule would see half the evidence.
    reference = (
        normalise_project_key(external_ref) if external_ref and external_ref.strip() else None
    )
    if reference is not None:
        existing = session.execute(
            select(Project).where(Project.source_id == source.id, Project.external_ref == reference)
        ).scalar_one_or_none()
        if existing is not None:
            raise IntakeError(
                f"source {source.id!r} already has a project with reference {reference!r}: "
                f"{existing.id}"
            )

    project = Project(
        source_id=source.id,
        external_ref=reference,
        name=name.strip(),
        description=description.strip() if description and description.strip() else None,
        established_by=f"declared:{created_by.strip()}"[:128],
    )
    session.add(project)
    session.flush()

    _log.info(
        "workspace.project_created",
        project_id=str(project.id),
        source_id=source.id,
        external_ref=reference,
        established_by=project.established_by,
    )
    return project


@dataclass(frozen=True, slots=True)
class AttachOutcome:
    """What one upload did, stated so a client can tell storage from membership.

    The distinction the fields exist to make: ``artifact_was_new`` is about *content identity* and
    ``membership_was_new`` is about *project membership*, and conflating them is the mistake the
    dedup rules are written to prevent. The same bill uploaded to two projects is one artifact and
    two memberships; the same bill uploaded twice to one project is neither.
    """

    document: Document
    membership: ProjectDocument
    artifact_was_new: bool
    membership_was_new: bool
    suggestion: Suggestion | None
    status: ProcessingStatus

    def describe(self) -> str:
        artifact = "stored" if self.artifact_was_new else "already held"
        membership = "attached" if self.membership_was_new else "already attached"
        proposed = f"  suggests {self.suggestion.describe()}" if self.suggestion is not None else ""
        return (
            f"{self.document.original_filename}  {artifact}, {membership}  "
            f"{self.status.value}{proposed}"
        )


def attach_upload(
    session: Session,
    store: RawObjectStore,
    *,
    project: Project,
    source: SourceDefinition,
    content: bytes,
    filename: str,
    uploaded_by: str,
    declared_type: DocumentType | None = None,
    declared_media_type: str | None = None,
    note: str | None = None,
) -> AttachOutcome:
    """Take uploaded bytes all the way to a document that belongs to a project.

    .. code-block:: text

        bytes -> format check -> immutable artifact -> document -> upload provenance
              -> project membership -> type suggestion

    Coherent or nothing. The caller's transaction covers every database write here, so a failure
    part-way leaves no document without provenance and no membership without a document. The one
    asymmetry is deliberate: the object may be written to immutable storage and the transaction then
    roll back, leaving bytes nobody references. That is the safe direction — storage is
    content-addressed, so a later upload of the same bytes finds them already there and verifies
    them, whereas a document row pointing at bytes that were never stored is unrecoverable.

    Deduplication, stated explicitly because it is easy to get subtly wrong:

    * **Same bytes, same project.** One artifact, one membership, nothing new. The upload *event*
      is logged but not stored a second time — ``document_uploads`` is unique per (document, source)
      by design, so re-ingesting is idempotent rather than append-only.
    * **Same bytes, two projects.** One artifact, two memberships. The second project's membership
      row carries its own ``established_by`` and ``linked_at``, which is where the second event is
      recorded.
    * **Different bytes, same document.** Impossible: identity *is* the digest.

    Args:
        declared_type: What the uploader says this is. Absent means absent — for a document already
            held, its existing type is kept rather than being overwritten with ``UNKNOWN``, because
            a re-upload with no declaration is not a statement that the type is unknown.
        declared_media_type: The request's content type, used only when the extension does not
            identify the format.

    Raises:
        IntakeError: for empty content, a format outside the storage allowlist, or content whose
            leading bytes contradict its declared format.
    """
    if not content:
        raise IntakeError("refusing to store an empty upload")
    if not uploaded_by.strip():
        raise IntakeError("an upload needs an uploader: provenance has to be attributable")

    display_name = safe_filename(filename)
    file_format = _format_of(display_name, declared_media_type)
    _refuse_content_that_contradicts_its_name(content, file_format, display_name)

    digest = hashlib.sha256(content).hexdigest()
    held = session.get(Document, document_id_for_digest(digest))

    # Absent declaration, keep what the document already says. Passing UNKNOWN here would trip
    # ingest_file's reclassification path and *downgrade* a correctly typed document, which is the
    # opposite of what a re-upload means.
    document_type = declared_type or (
        held.document_type if held is not None else DocumentType.UNKNOWN
    )

    with tempfile.TemporaryDirectory(prefix="aedifex-upload-") as scratch:
        staged = Path(scratch) / display_name
        staged.write_bytes(content)
        outcome = ingest_file(
            session,
            store,
            staged,
            source=source,
            document_type=document_type,
            file_format=file_format,
            uploaded_by=uploaded_by.strip(),
            software_version=__version__,
            note=note,
            # The bytes came from an HTTP request, not from this temporary file. Record what is
            # true: the name the client stated.
            original_path=f"upload:{display_name}",
        )

    document = outcome.document
    if declared_type is not None:
        document.type_authority = ClassificationAuthority.DECLARED
        document.document_category = category_for(declared_type)

    suggestion = suggest_document_type(display_name)
    if suggestion is not None:
        # Into its own column, every time, including when it disagrees with the declaration. The
        # disagreement is the useful part: "you filed this as unknown and it looks like a bill of
        # quantities" is the workspace's most valuable sentence, and it is only sayable if the
        # proposal is stored beside the decision instead of replacing it.
        document.suggested_document_type = suggestion.document_type
        document.classification_confidence = suggestion.confidence
        document.classifier_version = classifier_identity()

    membership = session.get(ProjectDocument, (project.id, document.id))
    membership_was_new = membership is None
    if membership is None:
        membership = ProjectDocument(
            project_id=project.id,
            document_id=document.id,
            # A declared type is a person saying what part this document plays, which is exactly
            # what the role column is for. A *suggested* type is not, and never reaches here.
            role=_role_for(declared_type),
            established_by=f"declared:upload:{uploaded_by.strip()}"[:128],
        )
        session.add(membership)
    session.flush()

    status = processing_status(
        document.state,
        is_readable=document.file_format in READABLE_FORMATS,
        needs_attention=False,
    )
    _log.info(
        "workspace.document_attached",
        project_id=str(project.id),
        document_id=str(document.id),
        source_id=source.id,
        filename=display_name,
        file_format=file_format.value,
        bytes=len(content),
        artifact_was_new=not outcome.already_present,
        membership_was_new=membership_was_new,
        declared_type=None if declared_type is None else declared_type.value,
        suggested_type=None if suggestion is None else suggestion.document_type.value,
        status=status.value,
    )
    return AttachOutcome(
        document=document,
        membership=membership,
        artifact_was_new=not outcome.already_present,
        membership_was_new=membership_was_new,
        suggestion=suggestion,
        status=status,
    )


def _format_of(display_name: str, declared_media_type: str | None) -> FileFormat:
    """Decide the format from the name, falling back to the request's content type.

    The extension first, because it is what the person who named the file believed, and browsers
    routinely send ``application/octet-stream`` for anything they do not recognise. A format outside
    the allowlist is refused rather than stored: the enum *is* the allowlist, and storing bytes we
    can never open or reason about is not preservation, it is an unlabelled blob.
    """
    extension = Path(display_name).suffix
    file_format = format_for_extension(extension) if extension else None
    if file_format is None and declared_media_type:
        file_format = format_for_media_type(declared_media_type)
    if file_format is None:
        raise IntakeError(
            f"{display_name!r}: no allowed format for extension {extension or '(none)'!r}"
            + (f" or media type {declared_media_type!r}" if declared_media_type else "")
        )
    return file_format


def _refuse_content_that_contradicts_its_name(
    content: bytes, file_format: FileFormat, display_name: str
) -> None:
    """Check the leading bytes against the declared format, and refuse a contradiction.

    Not theoretical: the format decides which extractor runs, and an archive named ``.pdf`` reaching
    the PDF reader is untrusted input arriving at a parser under a false description. For formats
    with a signature, its *absence* is evidence too — a PDF always starts with ``%PDF-``.
    """
    sniffed = sniff_format(content)
    if sniffed is not None and not formats_are_compatible(file_format, sniffed):
        raise IntakeError(
            f"{display_name!r} is declared {file_format.value} but its content is "
            f"{sniffed.value}; refusing to store bytes under a description they contradict"
        )
    if sniffed is None and file_format in FORMATS_WITH_A_SIGNATURE:
        raise IntakeError(
            f"{display_name!r} is declared {file_format.value}, whose content is always "
            f"recognisable, and these bytes are not it"
        )


def _role_for(declared_type: DocumentType | None) -> DocumentRole:
    """The part a document plays in its project, when a person has said what it is.

    Only for a declaration, and only where the two vocabularies name the same thing. A document type
    describes a document; a role describes its place in one project, and the overlap between them is
    real but partial — there is no role for a schedule of rates, because a rate schedule does not
    have a place in one project's chain of evidence.
    """
    if declared_type is None:
        return DocumentRole.UNCLASSIFIED
    try:
        return DocumentRole(declared_type.value)
    except ValueError:
        return DocumentRole.UNCLASSIFIED


def confirm_document_type(
    session: Session,
    document_id: uuid.UUID,
    *,
    document_type: DocumentType,
    confirmed_by: str,
) -> Document:
    """Record that a person decided what a document is. The other half of a suggestion.

    This is the only path by which a proposal becomes a decision, and it requires a name. The
    authority becomes ``human_confirmed`` rather than ``declared`` because the two are answerable
    differently: a declaration is what the uploader believed when filing, a confirmation is what a
    reviewer concluded after looking.

    The suggestion column is left exactly as it was, including when the person disagreed with it.
    "The classifier said corrigendum and a human said specification" is worth more than either
    statement alone, and it is the only feedback this classifier will ever get.

    Facts already extracted under the previous type are **not** re-extracted here. Re-analysis is a
    separate, explicit operation, and it retracts what the old type produced — see
    ``persist_retractions``. Doing it silently inside a classification change would mean a rename
    quietly rewriting evidence.

    Raises:
        IntakeError: if the document does not exist or the confirmer is unnamed.
    """
    if not confirmed_by.strip():
        raise IntakeError("a confirmation needs an author: an unattributed decision is a guess")
    document = session.get(Document, document_id)
    if document is None:
        raise IntakeError(f"no document {document_id}")

    was = document.document_type
    document.document_type = document_type
    document.document_category = category_for(document_type)
    document.type_authority = ClassificationAuthority.HUMAN_CONFIRMED
    session.flush()

    _log.info(
        "workspace.type_confirmed",
        document_id=str(document_id),
        was=was.value,
        now=document_type.value,
        suggested=(
            None
            if document.suggested_document_type is None
            else document.suggested_document_type.value
        ),
        confirmed_by=confirmed_by.strip(),
    )
    return document


@dataclass(frozen=True, slots=True)
class ProcessingReport:
    """What processing a project did, per document, with nothing swallowed."""

    project_id: uuid.UUID
    processed: tuple[uuid.UUID, ...] = ()
    already_processed: tuple[uuid.UUID, ...] = ()
    unsupported: tuple[tuple[uuid.UUID, str], ...] = ()
    failed: tuple[tuple[uuid.UUID, str], ...] = ()
    facts: int = 0
    findings: int = 0
    project_findings: int = 0

    @property
    def attempted(self) -> int:
        return len(self.processed) + len(self.failed)

    def describe(self) -> str:
        return (
            f"processed {len(self.processed)}, already processed {len(self.already_processed)}, "
            f"unsupported {len(self.unsupported)}, failed {len(self.failed)}; "
            f"{self.facts} facts, {self.findings} document findings, "
            f"{self.project_findings} project findings"
        )


def process_project(
    session: Session,
    store: RawObjectStore,
    project_id: uuid.UUID,
    *,
    reprocess: bool = False,
    max_pages: int | None = None,
) -> ProcessingReport:
    """Run the existing pipeline over a project's documents, then over the project itself.

    **No second pipeline.** Every document goes through ``analyse_document`` or
    ``analyse_spreadsheet`` — the same functions the CLI calls — and the project then goes through
    ``analyse_project``. This function chooses which capability each format needs and reports what
    happened; it extracts nothing, judges nothing, and stores no fact of its own. If a rule
    improves, this path gets it for free, and if this path is wrong the fix is in one place.

    Synchronous, and honest about it: a 261-page contract takes seconds and a large priced bill
    takes longer, so a caller with many documents waits. There is no queue in this deployment, and
    inventing one for a vertical slice would be the wrong order of work; what matters is that the
    state a reader sees is never a lie about work still running.

    Reconciliation is deliberately **not** run here. Membership in this project was *declared* by
    the person who owns the work, and re-deriving it from shared identifier facts could only agree
    or invent a second project for the same documents. Declared membership needs no inference.

    Args:
        reprocess: Re-run documents already processed. Safe — facts and findings are keyed by
            extractor and rule version, so a second pass updates rather than duplicates — but off by
            default so a routine call does not re-read a 5 MB specification.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise IntakeError(f"no project {project_id}")

    documents = list(
        session.execute(
            select(Document)
            .join(ProjectDocument, ProjectDocument.document_id == Document.id)
            .where(ProjectDocument.project_id == project_id)
            .order_by(Document.size_bytes)
        ).scalars()
    )

    processed: list[uuid.UUID] = []
    already: list[uuid.UUID] = []
    unsupported: list[tuple[uuid.UUID, str]] = []
    failed: list[tuple[uuid.UUID, str]] = []
    facts = 0
    findings = 0

    for document in documents:
        if document.file_format not in READABLE_FORMATS:
            # Stored, provenanced, visible, and unread. Refusing by name rather than letting the PDF
            # reader fail on it: "no reader for json" sends someone to write one, while "stream has
            # ended unexpectedly" sends them hunting for a corrupt download that does not exist.
            unsupported.append((document.id, f"no reader for {document.file_format.value}"))
            continue
        if document.state is DocumentState.PROCESSED and not reprocess:
            already.append(document.id)
            continue
        try:
            if document.file_format is FileFormat.XLSX:
                outcome = analyse_spreadsheet(session, store, document.id)
            elif max_pages is not None:
                outcome = analyse_document(session, store, document.id, max_pages=max_pages)
            else:
                outcome = analyse_document(session, store, document.id)
        except AedifexError as error:
            # One document's failure must not cost the others their analysis, and it must not be
            # silent either. The reason goes in the report *and* the state moves to FAILED, because
            # a report is read once and the state is read every time the workspace is opened —
            # without it, a document whose PDF cannot be opened shows as "uploaded" forever.
            record_analysis_failure(document, str(error))
            _log.warning(
                "workspace.document_failed",
                project_id=str(project_id),
                document_id=str(document.id),
                error=str(error),
                error_type=type(error).__name__,
            )
            failed.append((document.id, str(error)))
            continue
        processed.append(document.id)
        facts += len(outcome.facts)
        findings += len(outcome.findings)

    project_findings = analyse_project(session, project_id).findings

    report = ProcessingReport(
        project_id=project_id,
        processed=tuple(processed),
        already_processed=tuple(already),
        unsupported=tuple(unsupported),
        failed=tuple(failed),
        facts=facts,
        findings=findings,
        project_findings=len(project_findings),
    )
    _log.info("workspace.project_processed", project_id=str(project_id), summary=report.describe())
    return report


@dataclass(frozen=True, slots=True)
class DocumentEntry:
    """One document as the project workspace needs to show it.

    Everything a document list has to answer, in one row, because the alternative is a client
    stitching together the corpus catalog, the facts endpoint, the findings endpoint and the reviews
    endpoint and getting the joins subtly wrong.
    """

    document_id: uuid.UUID
    filename: str | None
    file_format: FileFormat
    size_bytes: int
    sha256: str
    document_type: DocumentType
    type_authority: ClassificationAuthority
    category: WorkflowCategory
    role: DocumentRole
    suggested_type: DocumentType | None
    classification_confidence: float | None
    classifier: str | None
    status: ProcessingStatus
    origin: str
    """``upload`` or ``crawl`` — how these bytes reached us, which is provenance, not status."""

    source_id: str | None
    acquired_at: datetime | None
    attached_at: datetime
    attached_by: str
    fact_count: int
    finding_count: int
    review_needed: int

    @property
    def classification_disputed(self) -> bool:
        """Whether a classifier proposes something other than what the document is filed as.

        The workspace's cheapest useful signal, and the reason the suggestion has its own column.
        ``False`` when there is no suggestion: silence is not disagreement.
        """
        return self.suggested_type is not None and self.suggested_type is not self.document_type


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    """A project in one object: enough for a reviewer to know where to start.

    Counts, not analytics. The question it answers is "what is in here, how much of it has been
    read, and what is waiting for me" — and, by what is *missing* from ``by_category``, which links
    of the chain cannot be verified at all.
    """

    project: Project
    documents: int
    by_status: Mapping[ProcessingStatus, int]
    by_category: Mapping[WorkflowCategory, int]
    facts: int
    findings_by_outcome: Mapping[str, int]
    reviews_by_decision: Mapping[str, int]
    stale_reviews: int
    review_needed: int
    unclassified: int
    disputed_classifications: int
    entries: tuple[DocumentEntry, ...] = field(default=(), repr=False)

    def describe(self) -> str:
        statuses = ", ".join(
            f"{status.value} {count}" for status, count in sorted(self.by_status.items())
        )
        return (
            f"{self.project.label}: {self.documents} documents ({statuses or 'none'}), "
            f"{self.facts} facts, {self.review_needed} findings awaiting review"
        )


def project_inventory(session: Session, project_id: uuid.UUID) -> tuple[DocumentEntry, ...]:
    """Every document in one project, with the state a workspace has to show beside it.

    Reads memberships, not retrievals. The corpus catalog joins ``document_retrievals``, which makes
    every *uploaded* document invisible to it — 41 of 45 in the corpus this was written against, at
    the same time as the same API reported 45 held. A product surface cannot be built on a query
    that hides the documents customers give it.
    """
    memberships = list(
        session.execute(
            select(ProjectDocument)
            .where(ProjectDocument.project_id == project_id)
            .order_by(ProjectDocument.linked_at, ProjectDocument.document_id)
        ).scalars()
    )
    if not memberships:
        return ()

    document_ids = [membership.document_id for membership in memberships]
    documents = {
        document.id: document
        for document in session.execute(
            select(Document).where(Document.id.in_(document_ids))
        ).scalars()
    }
    origins = _origins(session, document_ids)
    fact_counts = Counter(
        session.execute(
            select(ExtractedFact.document_id).where(ExtractedFact.document_id.in_(document_ids))
        ).scalars()
    )
    findings = list(
        session.execute(
            select(Finding)
            .options(selectinload(Finding.reviews))
            .where(Finding.document_id.in_(document_ids))
        ).scalars()
    )
    finding_counts: Counter[uuid.UUID] = Counter()
    open_counts: Counter[uuid.UUID] = Counter()
    for finding in findings:
        if finding.document_id is None:
            continue
        finding_counts[finding.document_id] += 1
        if _is_open(finding):
            open_counts[finding.document_id] += 1

    entries: list[DocumentEntry] = []
    for membership in memberships:
        document = documents.get(membership.document_id)
        if document is None:  # pragma: no cover - a membership without a document cannot exist
            continue
        origin_kind, source_id, acquired_at = origins.get(document.id, ("unknown", None, None))
        open_findings = open_counts[document.id]
        entries.append(
            DocumentEntry(
                document_id=document.id,
                filename=document.original_filename,
                file_format=document.file_format,
                size_bytes=document.size_bytes,
                sha256=document.sha256,
                document_type=document.document_type,
                type_authority=document.type_authority,
                category=category_of(document.document_type),
                role=membership.role,
                suggested_type=document.suggested_document_type,
                classification_confidence=document.classification_confidence,
                classifier=document.classifier_version,
                status=processing_status(
                    document.state,
                    is_readable=document.file_format in READABLE_FORMATS,
                    needs_attention=bool(open_findings),
                ),
                origin=origin_kind,
                source_id=source_id,
                acquired_at=acquired_at,
                attached_at=membership.linked_at,
                attached_by=membership.established_by,
                fact_count=fact_counts[document.id],
                finding_count=finding_counts[document.id],
                review_needed=open_findings,
            )
        )
    return tuple(entries)


def project_summary(session: Session, project_id: uuid.UUID) -> ProjectSummary:
    """One project's state, aggregated from the inventory and its findings.

    Built on :func:`project_inventory` rather than a second set of queries, so the summary and the
    document list cannot disagree about how many documents there are or which of them need someone.

    Raises:
        IntakeError: if the project does not exist. An empty summary for a project that was never
            created would answer a question nobody asked.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise IntakeError(f"no project {project_id}")

    entries = project_inventory(session, project_id)
    document_ids = [entry.document_id for entry in entries]

    # Both scopes, because a project's findings are not only its documents': "these two documents
    # disagree" is scoped to the project and belongs to neither of them.
    findings = list(
        session.execute(
            select(Finding)
            .options(selectinload(Finding.reviews))
            .where(
                (Finding.project_id == project_id)
                | (Finding.document_id.in_(document_ids) if document_ids else False)
            )
        ).scalars()
    )

    reviews: Counter[str] = Counter()
    stale = 0
    for finding in findings:
        current = finding.current_review
        if current is not None:
            reviews[current.decision] += 1
        stale += sum(1 for review in finding.reviews if review is not current)

    return ProjectSummary(
        project=project,
        documents=len(entries),
        by_status=Counter(entry.status for entry in entries),
        by_category=Counter(entry.category for entry in entries),
        facts=sum(entry.fact_count for entry in entries),
        findings_by_outcome=Counter(finding.outcome for finding in findings),
        reviews_by_decision=reviews,
        stale_reviews=stale,
        review_needed=sum(1 for finding in findings if _is_open(finding)),
        unclassified=sum(1 for entry in entries if entry.document_type is DocumentType.UNKNOWN),
        disputed_classifications=sum(1 for entry in entries if entry.classification_disputed),
        entries=entries,
    )


def _is_open(finding: Finding) -> bool:
    """Whether a finding still needs a person. Delegates, so there is one definition.

    ``current_review`` rather than "has any review" is what makes a revised rule re-open a finding
    somebody already accepted, which is the behaviour the staleness columns exist for.
    """
    return needs_human_review(
        finding.outcome, has_current_review=finding.current_review is not None
    )


def _origins(
    session: Session, document_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str | None, datetime | None]]:
    """How each document arrived: uploaded or crawled, from which source, when.

    Uploads are read first and retrievals second, so a document that arrived both ways is described
    by its retrieval — the earlier, more specific event, with a URL behind it. Neither path is
    privileged elsewhere; here one of them has to be shown first, and this is the choice.
    """
    origins: dict[uuid.UUID, tuple[str, str | None, datetime | None]] = {}
    for upload in session.execute(
        select(DocumentUpload)
        .where(DocumentUpload.document_id.in_(document_ids))
        .order_by(DocumentUpload.uploaded_at)
    ).scalars():
        origins[upload.document_id] = ("upload", upload.source_id, upload.uploaded_at)
    for retrieval in session.execute(
        select(DocumentRetrieval)
        .where(DocumentRetrieval.document_id.in_(document_ids))
        .order_by(DocumentRetrieval.retrieved_at)
    ).scalars():
        origins[retrieval.document_id] = ("crawl", retrieval.source_id, retrieval.retrieved_at)
    return origins
