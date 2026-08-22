"""Project intake: declaring a project, giving it documents, and reading its state back.

Integration rather than unit, because every property worth pinning here is a property of the
database and the object store together: the artifact is content-addressed, the membership is a
separate row from the artifact, and a failed intake must leave neither behind.

Justified as tests on three of the project's five grounds:

* **the trust boundary** — a classifier's proposal must never reach ``document_type``, and the one
  path that may change it needs a named person. Silent failure here reintroduces the defect that
  produced five false facts from real documents;
* **provenance correctness** — an upload must never record a retrieval, and a refused upload must
  store nothing;
* **a real defect, regressed** — the project document list used to describe documents through the
  corpus catalog, which inner-joins ``document_retrievals`` and therefore hid every uploaded
  document. On the corpus this was written against that was 41 of 45.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aedifex.acquisition.catalog import catalog_entry
from aedifex.acquisition.registry import SourceDefinition, load_registry
from aedifex.domain.documents import ClassificationAuthority, DocumentState, DocumentType
from aedifex.domain.evidence import DocumentRole
from aedifex.domain.review import ReviewDecision
from aedifex.domain.workflow import ProcessingStatus, WorkflowCategory
from aedifex.infrastructure.database.models import (
    Document,
    DocumentRetrieval,
    DocumentUpload,
    Finding,
    Project,
    ProjectDocument,
)
from aedifex.infrastructure.storage.objects import RawObjectStore
from aedifex.review import record_review
from aedifex.workspace import (
    IntakeError,
    attach_upload,
    confirm_document_type,
    create_project,
    process_project,
    project_inventory,
    project_summary,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# A tiny but structurally real PDF: enough for the signature check to pass and for pypdf to refuse
# it, which is the interesting case. Parseable PDFs are exercised against the actual corpus.
_PDF = b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
_XLSX_MAGIC = b"PK\x03\x04" + b"\x00" * 64


@pytest.fixture(scope="module")
def source() -> SourceDefinition:
    """The synthetic source: approved, enabled and ``manual_upload``, which is what intake needs."""
    return load_registry(PROJECT_ROOT / "config" / "sources").get("synthetic_projects")


def _project(session: Session, source: SourceDefinition, name: str = "Hostel 19") -> Project:
    return create_project(
        session,
        source=source,
        name=name,
        description="G+9 student hostel, 1,052 residents",
        created_by="qs.reviewer",
    )


def _unique_pdf(marker: str) -> bytes:
    """Distinct bytes, so two tests cannot deduplicate onto each other's document."""
    return _PDF + f"% {marker} {uuid.uuid4()}\n".encode()


class TestDeclaration:
    def test_a_project_can_be_declared_before_it_holds_anything(
        self, session: Session, source: SourceDefinition
    ) -> None:
        """The point of creating it first: documents attach to something that already exists."""
        project = _project(session, source)

        assert project.external_ref is None, "an identifier is not invented when none is given"
        assert project.label == "Hostel 19", "and display never falls through to null"
        assert project.established_by == "declared:qs.reviewer"
        assert project_summary(session, project.id).documents == 0

    def test_an_identifier_is_reused_rather_than_duplicated(
        self, session: Session, source: SourceDefinition
    ) -> None:
        """A declaration and the evidence must converge on one row, not compete.

        Reconciliation finds a project by ``(source, external_ref)``. If declaring the same
        reference twice created a second project, the two would split one project's documents and
        every cross-document rule would see half the evidence.
        """
        create_project(session, source=source, name="First", external_ref="AEDX/1", created_by="qs")
        with pytest.raises(IntakeError, match="already has a project"):
            create_project(
                session, source=source, name="Second", external_ref="AEDX/1", created_by="qs"
            )

    def test_a_declaration_needs_an_author(
        self, session: Session, source: SourceDefinition
    ) -> None:
        with pytest.raises(IntakeError):
            create_project(session, source=source, name="Nameless", created_by="   ")


class TestIntake:
    def test_an_upload_becomes_evidence_with_upload_provenance(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        project = _project(session, source)

        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("notice"),
            filename="iitb-h19-notice-inviting-tender.pdf",
            uploaded_by="pmc.lead",
            declared_type=DocumentType.TENDER_NOTICE,
        )

        assert outcome.artifact_was_new and outcome.membership_was_new
        assert outcome.status is ProcessingStatus.UPLOADED

        upload = session.execute(
            select(DocumentUpload).where(DocumentUpload.document_id == outcome.document.id)
        ).scalar_one()
        assert upload.uploaded_by == "pmc.lead"
        # The bytes came from a request, not from the temporary file they were written to.
        assert upload.original_path == "upload:iitb-h19-notice-inviting-tender.pdf"
        retrievals = session.execute(
            select(func.count())
            .select_from(DocumentRetrieval)
            .where(DocumentRetrieval.document_id == outcome.document.id)
        ).scalar_one()
        assert retrievals == 0, "an upload must never record an HTTP retrieval that never happened"

        assert outcome.membership.role is DocumentRole.TENDER_NOTICE
        assert outcome.membership.established_by == "declared:upload:pmc.lead"

    def test_a_windows_path_does_not_become_a_filename(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """``Path.name`` on POSIX treats a Windows path as one long name, and clients send those."""
        project = _project(session, source)
        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("windows"),
            filename=r"C:\Users\qs\Desktop\RA_Bill_17.pdf",
            uploaded_by="qs",
        )
        assert outcome.document.original_filename == "RA_Bill_17.pdf"

    def test_the_same_bytes_twice_in_one_project_change_nothing(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        project = _project(session, source)
        content = _unique_pdf("twice")
        first = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=content,
            filename="boq.pdf",
            uploaded_by="qs",
            declared_type=DocumentType.BILL_OF_QUANTITIES,
        )
        second = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=content,
            filename="boq (1).pdf",
            uploaded_by="qs",
        )

        assert second.document.id == first.document.id, "identity is the digest"
        assert not second.artifact_was_new
        assert not second.membership_was_new
        assert (
            session.execute(
                select(func.count())
                .select_from(ProjectDocument)
                .where(ProjectDocument.document_id == first.document.id)
            ).scalar_one()
            == 1
        )

    def test_a_re_upload_without_a_type_does_not_erase_the_declared_one(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """Absent is not ``unknown``. Passing UNKNOWN through would downgrade a correct type."""
        project = _project(session, source)
        content = _unique_pdf("retype")
        attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=content,
            filename="boq.pdf",
            uploaded_by="qs",
            declared_type=DocumentType.BILL_OF_QUANTITIES,
        )
        again = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=content,
            filename="whatever.pdf",
            uploaded_by="someone else",
        )
        assert again.document.document_type is DocumentType.BILL_OF_QUANTITIES

    def test_two_uploaders_of_the_same_bytes_are_two_upload_events(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """An upload is an event, and the second one used to be discarded.

        Found by an independent review. The unique key was ``(document_id, source_id)``, which was
        tolerable while every source had one operator and became wrong the moment a shared
        ``customer_provided`` source existed: a contractor's bill sent to both the owner and the PMC
        is identical content from two people, and the second uploader, their filename, their
        timestamp and their note were simply not recorded.
        """
        from aedifex.infrastructure.database.models import DocumentUpload

        first = _project(session, source, name="Owner")
        second = _project(session, source, name="PMC")
        content = _unique_pdf("two uploaders")

        attach_upload(
            session,
            store,
            project=first,
            source=source,
            content=content,
            filename="Final_RA_Bill.xlsx.pdf",
            uploaded_by="owner.finance",
        )
        outcome = attach_upload(
            session,
            store,
            project=second,
            source=source,
            content=content,
            filename="Contractor_Claim_07.pdf",
            uploaded_by="pmc.lead",
            note="Received by email from the contractor.",
        )

        uploads = list(
            session.execute(
                select(DocumentUpload).where(DocumentUpload.document_id == outcome.document.id)
            ).scalars()
        )
        assert len(uploads) == 2, "two people supplied these bytes; that is two events"
        assert {row.uploaded_by for row in uploads} == {"owner.finance", "pmc.lead"}
        assert {row.original_path for row in uploads} == {
            "upload:Final_RA_Bill.xlsx.pdf",
            "upload:Contractor_Claim_07.pdf",
        }
        assert any(row.note is not None for row in uploads), "and the second one's note survives"

    def test_each_project_sees_the_name_its_own_uploader_used(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """``documents.original_filename`` is content-level, and content is shared.

        So a second project uploading identical bytes was shown the *first* project's filename. For
        a shared rate schedule that is merely odd; for a bill one contractor sent to two parties it
        displays one customer's naming inside another customer's project.
        """
        first = _project(session, source, name="Owner")
        second = _project(session, source, name="PMC")
        content = _unique_pdf("naming")

        attach_upload(
            session,
            store,
            project=first,
            source=source,
            content=content,
            filename="Final_RA_Bill.pdf",
            uploaded_by="owner.finance",
        )
        attach_upload(
            session,
            store,
            project=second,
            source=source,
            content=content,
            filename="Contractor_Claim_07.pdf",
            uploaded_by="pmc.lead",
        )

        assert [entry.filename for entry in project_inventory(session, first.id)] == [
            "Final_RA_Bill.pdf"
        ]
        assert [entry.filename for entry in project_inventory(session, second.id)] == [
            "Contractor_Claim_07.pdf"
        ]

    def test_the_same_person_re_ingesting_the_same_file_is_still_idempotent(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """What the narrower key was protecting, and what the wider one must keep protecting."""
        from aedifex.infrastructure.database.models import DocumentUpload

        project = _project(session, source)
        content = _unique_pdf("rerun")
        for _ in range(3):
            outcome = attach_upload(
                session,
                store,
                project=project,
                source=source,
                content=content,
                filename="boq.pdf",
                uploaded_by="qs",
            )

        uploads = session.execute(
            select(func.count())
            .select_from(DocumentUpload)
            .where(DocumentUpload.document_id == outcome.document.id)
        ).scalar_one()
        assert uploads == 1

    def test_one_artifact_can_belong_to_two_projects(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """Artifact identity is not project membership, and this is where the two are told apart.

        The same schedule of rates governs many projects, and the same bill can be given to an
        auditor and to a PMC. One set of bytes, two memberships, each with its own attribution.
        """
        first = _project(session, source, name="Tower A")
        second = _project(session, source, name="Tower B")
        content = _unique_pdf("shared")

        attach_upload(
            session,
            store,
            project=first,
            source=source,
            content=content,
            filename="dsr-2023.pdf",
            uploaded_by="qs.a",
        )
        outcome = attach_upload(
            session,
            store,
            project=second,
            source=source,
            content=content,
            filename="dsr-2023.pdf",
            uploaded_by="qs.b",
        )

        assert not outcome.artifact_was_new, "the bytes are already held"
        assert outcome.membership_was_new, "but this project has not seen them"
        assert (
            session.execute(select(func.count()).select_from(Document)).scalar_one() == 1
        ), "one artifact"
        memberships = list(
            session.execute(
                select(ProjectDocument).where(ProjectDocument.document_id == outcome.document.id)
            ).scalars()
        )
        assert {row.established_by for row in memberships} == {
            "declared:upload:qs.a",
            "declared:upload:qs.b",
        }, "and the second upload event is recorded on the membership that carries it"


class TestRefusals:
    def test_content_that_contradicts_its_name_is_refused_and_stores_nothing(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """An archive named ``.pdf`` would reach the PDF reader as untrusted, mislabelled input."""
        project = _project(session, source)
        with pytest.raises(IntakeError, match="content"):
            attach_upload(
                session,
                store,
                project=project,
                source=source,
                content=_XLSX_MAGIC,
                filename="boq.pdf",
                uploaded_by="qs",
            )
        assert session.execute(select(func.count()).select_from(Document)).scalar_one() == 0

    def test_a_pdf_that_is_not_a_pdf_is_refused(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """For a format with a signature, its absence is evidence: a PDF starts with ``%PDF-``."""
        project = _project(session, source)
        with pytest.raises(IntakeError):
            attach_upload(
                session,
                store,
                project=project,
                source=source,
                content=b"Dear sir, please find attached",
                filename="claim.pdf",
                uploaded_by="qs",
            )

    def test_a_format_outside_the_allowlist_is_refused(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """The format enum *is* the allowlist. Storing bytes nothing can ever open is not
        preservation."""
        project = _project(session, source)
        with pytest.raises(IntakeError, match="no allowed format"):
            attach_upload(
                session,
                store,
                project=project,
                source=source,
                content=b"MZ\x90\x00",
                filename="setup.exe",
                uploaded_by="qs",
            )

    def test_an_empty_upload_is_refused(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        project = _project(session, source)
        with pytest.raises(IntakeError):
            attach_upload(
                session,
                store,
                project=project,
                source=source,
                content=b"",
                filename="empty.pdf",
                uploaded_by="qs",
            )


class TestClassificationBoundary:
    def test_a_suggestion_never_becomes_the_type(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """The boundary this whole design exists to hold.

        The filename says "priced bill of quantities" and the classifier says so too. The document
        is still ``unknown``, because ``document_type`` decides whether the extractor treats a
        quoted amount as a fact about the document, and a filename is not a person.
        """
        project = _project(session, source)
        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("suggest"),
            filename="iitb-h19-priced-bill-of-quantities.pdf",
            uploaded_by="qs",
        )

        assert outcome.document.document_type is DocumentType.UNKNOWN
        assert outcome.document.suggested_document_type is DocumentType.BILL_OF_QUANTITIES
        assert outcome.document.classifier_version == "filename_keywords:1"
        entry = project_inventory(session, project.id)[0]
        assert entry.classification_disputed, "and the disagreement is what the workspace shows"

    def test_a_person_confirms_a_type_and_the_suggestion_is_kept(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """ "The classifier said X and a human said Y" is worth more than either alone."""
        project = _project(session, source)
        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("confirm"),
            filename="cpwd-general-specifications-2013-amendment-2.pdf",
            uploaded_by="qs",
        )
        assert outcome.document.suggested_document_type is DocumentType.TECHNICAL_SPECIFICATION

        confirmed = confirm_document_type(
            session,
            outcome.document.id,
            document_type=DocumentType.CORRIGENDUM,
            confirmed_by="contracts.lead",
        )

        assert confirmed.document_type is DocumentType.CORRIGENDUM
        assert confirmed.type_authority is ClassificationAuthority.HUMAN_CONFIRMED
        assert (
            confirmed.suggested_document_type is DocumentType.TECHNICAL_SPECIFICATION
        ), "the proposal stays on the record, including when a person disagreed with it"

    def test_a_confirmation_needs_an_author(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        project = _project(session, source)
        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("unattributed"),
            filename="boq.pdf",
            uploaded_by="qs",
        )
        with pytest.raises(IntakeError):
            confirm_document_type(
                session,
                outcome.document.id,
                document_type=DocumentType.BILL_OF_QUANTITIES,
                confirmed_by="",
            )


class TestReadModel:
    def test_the_inventory_shows_documents_the_corpus_catalog_hides(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """The defect this read model was written to fix, pinned as a regression.

        ``catalog_entry`` inner-joins ``document_retrievals``, so an uploaded document has no entry
        — and the project document list used to be built from it. Both halves are asserted, because
        the day the catalog learns about uploads this test should keep passing rather than start
        silently checking nothing.
        """
        project = _project(session, source)
        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("invisible"),
            filename="boq.pdf",
            uploaded_by="qs",
            declared_type=DocumentType.BILL_OF_QUANTITIES,
        )

        entries = project_inventory(session, project.id)
        assert [entry.document_id for entry in entries] == [outcome.document.id]
        assert entries[0].origin == "upload"
        assert entries[0].source_id == source.id
        assert entries[0].category is WorkflowCategory.BOQ
        if catalog_entry(session, outcome.document.id) is not None:
            pytest.skip("the corpus catalog now describes uploads; this regression is closed")

    def test_an_unreadable_format_stays_stored_and_visible(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """ "Unsupported" is a product outcome, not a failure and not a disappearance."""
        project = _project(session, source)
        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=b'{"series": "CPI-IW", "value": 143.2}',
            filename="cpi-iw-2026-06.json",
            uploaded_by="ops",
        )
        assert outcome.status is ProcessingStatus.UNSUPPORTED

        report = process_project(session, store, project.id)
        assert [item for item, _ in report.unsupported] == [outcome.document.id]
        assert report.processed == ()

        entry = project_inventory(session, project.id)[0]
        assert entry.status is ProcessingStatus.UNSUPPORTED
        assert entry.sha256, "the bytes are held and addressable"

    def test_one_document_failing_costs_the_others_nothing(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """A PDF the reader cannot open is reported by id and reason, and does not raise."""
        project = _project(session, source)
        broken = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("broken"),
            filename="scan0007.pdf",
            uploaded_by="qs",
        )
        attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=b'{"series": "CPI-IW"}',
            filename="cpi.json",
            uploaded_by="ops",
        )

        report = process_project(session, store, project.id)

        assert [item for item, _ in report.failed] == [broken.document.id]
        assert len(report.unsupported) == 1

        # The state records the attempt, not just the report. Found by opening the workspace: a
        # document whose PDF cannot be parsed showed as "uploaded", indistinguishable from one
        # nobody had tried, because extraction raises before the first state transition. A reviewer
        # would press Process forever with nothing to show that anything had happened.
        by_id = {entry.document_id: entry for entry in project_inventory(session, project.id)}
        assert len(by_id) == 2, "both documents are still listed"
        assert by_id[broken.document.id].status is ProcessingStatus.FAILED
        assert [
            entry.status for entry in by_id.values() if entry.status is ProcessingStatus.UNSUPPORTED
        ] == [ProcessingStatus.UNSUPPORTED]

    def test_the_summary_counts_what_a_reviewer_needs(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        project = _project(session, source)
        attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("bill"),
            filename="ra-bill-17.pdf",
            uploaded_by="billing",
            declared_type=DocumentType.RUNNING_BILL,
        )
        attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("dsr"),
            filename="dsr-2023.pdf",
            uploaded_by="qs",
            declared_type=DocumentType.SCHEDULE_OF_RATES,
        )

        summary = project_summary(session, project.id)

        assert summary.documents == 2
        assert summary.by_status[ProcessingStatus.UPLOADED] == 2
        assert summary.by_category[WorkflowCategory.RA_BILL] == 1
        assert summary.by_category[WorkflowCategory.REFERENCE] == 1
        assert (
            WorkflowCategory.MEASUREMENT not in summary.by_category
        ), "an absent link is the summary's most useful signal"

    def test_a_review_clears_the_attention_flag_and_a_revised_rule_restores_it(
        self, session: Session, store: RawObjectStore, source: SourceDefinition
    ) -> None:
        """Where human review meets the workspace: the only thing that closes an open finding.

        And the staleness property carried through to the product surface — revising the rule makes
        the review stop speaking for the finding, so the document asks for a person again.
        """
        project = _project(session, source)
        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=_unique_pdf("finding"),
            filename="ra-bill-17.pdf",
            uploaded_by="billing",
            declared_type=DocumentType.RUNNING_BILL,
        )
        # Processing would have moved it here, and the projection is deliberately ordered so that an
        # earlier stage wins: a document still being read cannot be asking for a reviewer.
        outcome.document.state = DocumentState.PROCESSED
        finding = Finding(
            document_id=outcome.document.id,
            rule_id="claim_within_measurement",
            rule_version="1",
            outcome="review",
            summary="Item 4.7.2: cumulative claim 520 m3 exceeds the measured 470 m3 by 50 m3",
            expected="claim <= measured",
            observed="520 m3",
        )
        session.add(finding)
        session.flush()

        assert project_summary(session, project.id).review_needed == 1
        assert project_inventory(session, project.id)[0].status is ProcessingStatus.NEEDS_ATTENTION

        record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="Checked against the MB extract: the claim really is 50 m3 ahead.",
            reviewer="qs.reviewer",
        )
        session.expire(finding)

        summary = project_summary(session, project.id)
        assert summary.review_needed == 0
        assert summary.reviews_by_decision == {"accepted": 1}

        finding.rule_version = "2"
        session.flush()
        session.expire(finding)

        reopened = project_summary(session, project.id)
        assert reopened.review_needed == 1, "a revised rule re-opens what was accepted under it"
        assert reopened.stale_reviews == 1, "and the earlier decision is kept and counted"
