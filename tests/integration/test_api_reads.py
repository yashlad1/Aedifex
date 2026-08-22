"""The read endpoints a viewer depends on, against a real database and a real object store.

Two of these pin defects found by pointing a client at the API rather than by reading it, which is
the only way either would have surfaced:

* ``GET /v1/projects/{id}/facts`` returned **500 for every project holding any fact**. The response
  is built after the session closes and ``FactResponse.from_row`` reads ``retraction``, so the lazy
  load happened on a detached instance. Measured on three real projects — 3,319, 578 and 120 facts,
  two of them with no retractions at all — all three returned ``DetachedInstanceError``. The
  document-level endpoint had the eager load; the project-level one did not.
* ``GET /v1/documents/{id}/content`` did not exist, so a viewer could show our *extraction* of a
  document but never the document. An extraction a reader cannot check against the page is an
  assertion.

The client is wired to the test database through the environment, the same way a deployment is,
rather than by monkeypatching a session in — the point of the first test is what happens when the
real ``session_scope`` closes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from apps.api.main import (
    create_app,
    database_probe_dependency,
    settings_dependency,
    store_dependency,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aedifex.acquisition.registry import SourceDefinition, load_registry
from aedifex.config import Settings
from aedifex.domain.documents import DocumentType
from aedifex.infrastructure.database import session as session_module
from aedifex.infrastructure.storage.objects import RawObjectStore
from aedifex.workspace import attach_upload, create_project

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PDF = b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


@pytest.fixture(scope="module")
def source() -> SourceDefinition:
    return load_registry(PROJECT_ROOT / "config" / "sources").get("synthetic_projects")


@pytest.fixture
def client(
    settings: Settings, store: RawObjectStore, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A client whose ``session_scope`` really points at the test database.

    ``get_engine`` and ``get_sessionmaker`` are ``lru_cache``d over ``get_settings``, so redirecting
    the DSN means clearing all three — and clearing them again afterwards, or the next test in the
    process inherits an engine bound to a database this one truncates.
    """
    monkeypatch.setenv("AEDIFEX_DATABASE_URL", str(settings.database_url))
    from aedifex.config import get_settings

    get_settings.cache_clear()
    session_module.get_engine.cache_clear()
    session_module.get_sessionmaker.cache_clear()

    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[store_dependency] = lambda: store
    app.dependency_overrides[database_probe_dependency] = lambda: (lambda: None)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        session_module.get_engine.cache_clear()
        session_module.get_sessionmaker.cache_clear()


def _attached(
    session: Session,
    store: RawObjectStore,
    source: SourceDefinition,
    *,
    filename: str = "boq.pdf",
    content: bytes | None = None,
    declared: DocumentType | None = DocumentType.BILL_OF_QUANTITIES,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A project with one document in it. Returns (project id, document id)."""
    project = create_project(
        session, source=source, name=f"Viewer {uuid.uuid4().hex[:8]}", created_by="test"
    )
    outcome = attach_upload(
        session,
        store,
        project=project,
        source=source,
        content=content if content is not None else _PDF + uuid.uuid4().bytes,
        filename=filename,
        uploaded_by="test",
        declared_type=declared,
    )
    session.commit()
    return project.id, outcome.document.id


class TestProjectFacts:
    def test_a_project_s_facts_can_be_read(
        self,
        client: TestClient,
        session: Session,
        store: RawObjectStore,
        source: SourceDefinition,
    ) -> None:
        """The regression. Before the eager load this was a 500 for any project with facts."""
        from aedifex.domain.evidence import FactKind
        from aedifex.infrastructure.database.models import ExtractedFact

        project_id, document_id = _attached(session, store, source)
        session.add(
            ExtractedFact(
                document_id=document_id,
                fact_type="estimated_cost",
                kind=FactKind.MONEY,
                literal="Rs.85,39,81,318.41",
                numeric_value=None,
                page=2,
                span_start=0,
                span_end=18,
                snippet="Total Rs.85,39,81,318.41/-",
                method="text",
                extractor="test",
                extractor_version="1",
            )
        )
        session.commit()

        response = client.get(f"/v1/projects/{project_id}/facts")

        assert response.status_code == 200
        body = response.json()
        assert body["returned"] == 1
        assert body["facts"][0]["retracted"] is False

    def test_a_retracted_fact_is_labelled_rather_than_hidden(
        self,
        client: TestClient,
        session: Session,
        store: RawObjectStore,
        source: SourceDefinition,
    ) -> None:
        """Returned with its reason, because a finding computed from it stays explainable.

        A client must never render this as something the document states — which is what the flag is
        for, and why serving the row is safe and hiding it would not be.
        """
        from aedifex.domain.evidence import FactKind
        from aedifex.infrastructure.database.models import ExtractedFact, FactRetraction

        project_id, document_id = _attached(session, store, source)
        fact = ExtractedFact(
            document_id=document_id,
            fact_type="estimated_cost",
            kind=FactKind.MONEY,
            literal="Rs. 5 crores",
            numeric_value=None,
            page=48,
            span_start=0,
            span_end=12,
            snippet="estimated cost put to tender being less than Rs. 5 crores",
            method="text",
            extractor="test",
            extractor_version="1",
        )
        session.add(fact)
        session.flush()
        session.add(
            FactRetraction(
                fact_id=fact.id,
                retracted_by_extractor="test",
                retracted_by_version="2",
                reason="quoted inside a model agreement, so it is not a fact about this document",
                software_version="0",
            )
        )
        session.commit()

        body = client.get(f"/v1/projects/{project_id}/facts").json()

        assert body["returned"] == 1
        served = body["facts"][0]
        assert served["retracted"] is True
        assert "model agreement" in served["retracted_reason"]


class TestDocumentContent:
    def test_the_original_bytes_are_served_for_a_pdf(
        self,
        client: TestClient,
        session: Session,
        store: RawObjectStore,
        source: SourceDefinition,
    ) -> None:
        """Byte-for-byte, inline, and sandboxed. This is what makes a citation checkable."""
        content = _PDF + b"% hostel 19\n"
        _, document_id = _attached(session, store, source, content=content)

        response = client.get(f"/v1/documents/{document_id}/content")

        assert response.status_code == 200
        assert response.content == content, "the artifact is the evidence; it is not re-rendered"
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"].startswith("inline")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "sandbox"

    def test_a_format_a_browser_would_not_render_is_a_download(
        self,
        client: TestClient,
        session: Session,
        store: RawObjectStore,
        source: SourceDefinition,
    ) -> None:
        """The corpus contains crawled HTML. Serving that inline would run someone else's markup."""
        _, document_id = _attached(
            session,
            store,
            source,
            filename="cpi.json",
            content=b'{"series": "CPI-IW"}',
            declared=None,
        )

        response = client.get(f"/v1/documents/{document_id}/content")

        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment")

    def test_bytes_that_do_not_match_their_digest_are_refused(
        self,
        client: TestClient,
        session: Session,
        store: RawObjectStore,
        source: SourceDefinition,
    ) -> None:
        """A 409, never a silent 200.

        Showing a reviewer bytes that are not the ones the provenance chain records breaks the only
        guarantee this product sells. The record is altered here rather than the object, because the
        store refuses to overwrite an artifact — which is itself the point.
        """
        from aedifex.infrastructure.database.models import Document

        _, document_id = _attached(session, store, source)
        document = session.get(Document, document_id)
        assert document is not None
        document.sha256 = "0" * 64
        session.commit()

        response = client.get(f"/v1/documents/{document_id}/content")

        assert response.status_code == 409
        assert "does not match its provenance" in response.json()["detail"]

    def test_an_unknown_document_is_a_404(self, client: TestClient) -> None:
        assert client.get(f"/v1/documents/{uuid.uuid4()}/content").status_code == 404


class TestSheetWindow:
    """A spreadsheet region, served so a cell citation can be looked at.

    The integration half of the item that made spreadsheet evidence usable. What is worth pinning
    against a real store: the right sheet comes back for a real workbook, and a PDF is refused by
    name rather than producing an empty grid.
    """

    @staticmethod
    def _workbook() -> bytes:
        from io import BytesIO

        from openpyxl import Workbook

        book = Workbook()
        sheet = book.create_sheet("BOQ")
        del book["Sheet"]
        sheet["A5"] = "1.2"
        sheet["B5"] = "PCC 1:4:8 in foundation"
        sheet["D5"] = 86
        sheet["E5"] = 631
        buffer = BytesIO()
        book.save(buffer)
        return buffer.getvalue()

    def test_a_cell_can_be_looked_at(
        self,
        client: TestClient,
        session: Session,
        store: RawObjectStore,
        source: SourceDefinition,
    ) -> None:
        _, document_id = _attached(
            session, store, source, filename="BOQ.xlsx", content=self._workbook(), declared=None
        )

        response = client.get(f"/v1/documents/{document_id}/sheet", params={"row": 5, "radius": 1})

        assert response.status_code == 200
        body = response.json()
        assert body["sheet"] == "BOQ"
        assert body["sheets"] == ["BOQ"]
        cited = [
            cell
            for entry in body["rows"]
            for cell in entry["cells"]
            if cell["reference"] == "BOQ!E5"
        ]
        assert [cell["value"] for cell in cited] == ["631"]
        assert "authoritative artifact" in body["note"]

    def test_a_pdf_is_refused_by_name(
        self,
        client: TestClient,
        session: Session,
        store: RawObjectStore,
        source: SourceDefinition,
    ) -> None:
        """Not an empty grid. "This is a PDF, use /content" sends the reader somewhere useful."""
        _, document_id = _attached(session, store, source)

        response = client.get(f"/v1/documents/{document_id}/sheet")

        assert response.status_code == 415
        assert "not a spreadsheet" in response.json()["detail"]
