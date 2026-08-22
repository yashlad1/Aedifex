"""Tests for the read-only acquisition API.

No database is required, and none is used even if one is running: the database probe is
always overridden so both readiness outcomes are covered deterministically.

This file previously asserted that readiness reports the database as *unavailable*, which
passed only because no PostgreSQL was installed on the machine. The moment one was, the test
inverted meaning and failed. A unit test must not depend on ambient infrastructure — the real
probe is exercised in ``tests/integration/test_database.py`` instead.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from apps.api.main import (
    REQUEST_ID_HEADER,
    FactResponse,
    FindingResponse,
    _download_name,
    create_app,
    database_probe_dependency,
    registry_dependency,
    settings_dependency,
)
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from aedifex.acquisition.registry import load_registry
from aedifex.config import Environment, Settings
from aedifex.domain.evidence import FactKind
from aedifex.domain.files import FileFormat
from aedifex.infrastructure.database.models import (
    DerivedFact,
    ExtractedFact,
    Finding,
    FindingEvidence,
    PolicyProvision,
)

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "config" / "sources"


def _unavailable_probe() -> Callable[[], None]:
    """A database probe that always fails, for deterministic readiness tests."""

    def probe() -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    return probe


def _healthy_probe() -> Callable[[], None]:
    """A database probe that always succeeds."""

    def probe() -> None:
        return None

    return probe


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client wired to the repository's real registry, with no ambient configuration.

    The database probe is overridden, so these tests behave identically whether or not a
    PostgreSQL instance happens to be running on the developer's machine. An earlier version
    depended on that ambient state and silently inverted meaning once a database existed.
    """
    app = create_app()
    settings = Settings(environment=Environment.TEST, source_registry_dir=str(REGISTRY_DIR))
    registry = load_registry(REGISTRY_DIR)
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[registry_dependency] = lambda: registry
    app.dependency_overrides[database_probe_dependency] = _unavailable_probe
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def ready_client() -> Iterator[TestClient]:
    """A client whose dependencies all report healthy."""
    app = create_app()
    settings = Settings(environment=Environment.TEST, source_registry_dir=str(REGISTRY_DIR))
    registry = load_registry(REGISTRY_DIR)
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[registry_dependency] = lambda: registry
    app.dependency_overrides[database_probe_dependency] = _healthy_probe
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestHealth:
    def test_liveness_has_no_dependencies(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["environment"] == "test"
        assert body["version"]

    def test_readiness_fails_when_the_database_is_unreachable(self, client: TestClient) -> None:
        """Readiness must fail loudly and name the check that failed."""
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["registry"].startswith("ok")
        assert body["checks"]["database"].startswith("unavailable")

    def test_readiness_succeeds_when_every_dependency_is_healthy(
        self, ready_client: TestClient
    ) -> None:
        """The positive path needs its own deterministic coverage, not ambient infrastructure."""
        response = ready_client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["registry"].startswith("ok")

    def test_readiness_does_not_leak_connection_details(self, client: TestClient) -> None:
        """An unauthenticated caller must not learn internal hostnames or credentials."""
        body = client.get("/health/ready").json()
        detail = body["checks"]["database"]
        assert "postgres" not in detail.lower()
        assert "password" not in detail.lower()
        assert "5432" not in detail


class TestRequestCorrelation:
    def test_a_request_id_is_returned(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.headers[REQUEST_ID_HEADER]

    def test_each_request_gets_a_distinct_id(self, client: TestClient) -> None:
        first = client.get("/health").headers[REQUEST_ID_HEADER]
        second = client.get("/health").headers[REQUEST_ID_HEADER]
        assert first != second

    def test_an_inbound_request_id_is_honoured(self, client: TestClient) -> None:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "upstream-trace-1"})
        assert response.headers[REQUEST_ID_HEADER] == "upstream-trace-1"

    def test_an_overlong_inbound_id_is_truncated(self, client: TestClient) -> None:
        """The header is attacker-controlled and lands in every log line for the request."""
        response = client.get("/health", headers={REQUEST_ID_HEADER: "x" * 5000})
        assert len(response.headers[REQUEST_ID_HEADER]) == 64


class TestSources:
    def test_lists_every_registered_source(self, client: TestClient) -> None:
        body = client.get("/v1/sources").json()
        assert body["total"] == len(body["sources"])
        assert body["total"] > 0

    def test_reports_how_many_are_collectable(self, client: TestClient) -> None:
        body = client.get("/v1/sources").json()
        assert body["collectable"] <= body["total"]

    def test_unreviewed_sources_are_listed_but_not_collectable(self, client: TestClient) -> None:
        """Visibility of pending review work is the point of listing disabled sources."""
        sources = client.get("/v1/sources").json()["sources"]
        unverified = [s for s in sources if s["verification_status"] == "unverified"]
        assert unverified
        assert all(source["is_collectable"] is False for source in unverified)

    def test_collectable_filter(self, client: TestClient) -> None:
        body = client.get("/v1/sources", params={"collectable_only": True}).json()
        assert all(source["is_collectable"] for source in body["sources"])
        assert len(body["sources"]) == body["collectable"]

    def test_licence_metadata_is_exposed(self, client: TestClient) -> None:
        """Anyone consuming the corpus needs to see the constraints attached to it."""
        source = client.get("/v1/sources").json()["sources"][0]
        assert set(source["data_use"]) >= {
            "license",
            "access",
            "allowed_use",
            "attribution_required",
            "contains_personal_data",
        }

    def test_fetch_one_source(self, client: TestClient) -> None:
        listed = client.get("/v1/sources").json()["sources"][0]
        response = client.get(f"/v1/sources/{listed['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == listed["id"]

    def test_unknown_source_is_a_404(self, client: TestClient) -> None:
        response = client.get("/v1/sources/no_such_source")
        assert response.status_code == 404
        assert "no_such_source" in response.json()["detail"]

    def test_response_shape_is_stable(self, client: TestClient) -> None:
        """The response schema is a published contract; changing it needs a deliberate edit."""
        source = client.get("/v1/sources").json()["sources"][0]
        assert set(source) == {
            "id",
            "name",
            "description",
            "country",
            "category",
            "retrieval",
            "base_url",
            "enabled",
            "verification_status",
            "is_collectable",
            "crawler",
            "document_types",
            "file_formats",
            "data_use",
            "requests_per_minute",
            "last_successful_run",
        }


class TestRegistryFailure:
    """Exercises the real ``registry_dependency`` against a registry that cannot load.

    The settings are overridden rather than the registry dependency itself, so the
    error-translation logic under test actually runs.
    """

    @pytest.fixture
    def broken_client(self, tmp_path: Path) -> Iterator[TestClient]:
        app = create_app()
        settings = Settings(
            environment=Environment.TEST,
            source_registry_dir=str(tmp_path / "does_not_exist"),
        )
        app.dependency_overrides[settings_dependency] = lambda: settings
        app.dependency_overrides[database_probe_dependency] = _healthy_probe
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
        app.dependency_overrides.clear()

    def test_a_broken_registry_is_a_503_not_a_500(self, broken_client: TestClient) -> None:
        """A malformed registry is our fault, not the caller's, and must be distinguishable."""
        response = broken_client.get("/v1/sources")
        assert response.status_code == 503
        assert "registry" in response.json()["detail"]

    def test_liveness_still_succeeds_when_the_registry_is_broken(
        self, broken_client: TestClient
    ) -> None:
        """Liveness must not depend on configuration, or a bad deploy looks like a crash loop."""
        assert broken_client.get("/health").status_code == 200

    def test_readiness_fails_when_the_registry_is_broken(self, broken_client: TestClient) -> None:
        assert broken_client.get("/health/ready").status_code == 503


class TestOpenApi:
    def test_schema_is_generated(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "Aedifex Acquisition API"

    def test_endpoints_are_versioned(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/v1/sources" in paths
        assert "/health" in paths


class TestFindingReviewContract:
    """The review endpoint's request contract, which is enforced before any database is touched.

    Deliberately not a full round trip: recording, append-only behaviour and staleness are database
    properties and are tested in ``tests/integration/test_finding_review.py``. What is worth pinning
    here is that a malformed decision cannot reach the service layer, because the vocabulary of what
    a human may conclude is a domain decision and not free text.
    """

    def test_an_unknown_decision_is_refused_before_the_database(self, client: TestClient) -> None:
        response = client.post(
            "/v1/findings/00000000-0000-0000-0000-000000000000/reviews",
            json={"decision": "probably_fine", "note": "hmm", "reviewer": "someone"},
        )
        assert response.status_code == 422

    def test_a_blank_note_is_refused(self, client: TestClient) -> None:
        """A verdict with no reasoning is indistinguishable from a mis-click."""
        response = client.post(
            "/v1/findings/00000000-0000-0000-0000-000000000000/reviews",
            json={"decision": "accepted", "note": "", "reviewer": "someone"},
        )
        assert response.status_code == 422

    def test_a_missing_reviewer_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/v1/findings/00000000-0000-0000-0000-000000000000/reviews",
            json={"decision": "accepted", "note": "checked"},
        )
        assert response.status_code == 422


@pytest.fixture
def production_client() -> Iterator[TestClient]:
    """A client whose settings say production, to prove the write endpoints refuse to serve.

    Real-looking values throughout, because ``Settings`` refuses a production environment that still
    carries development placeholders — which is itself the control being relied on here.
    """
    app = create_app()
    # model_validate rather than the constructor: the DSN field is a PostgresDsn, and handing it the
    # string form is exactly what a deployment does.
    settings = Settings.model_validate(
        {
            "environment": Environment.PRODUCTION,
            "database_url": (
                "postgresql+psycopg://aedifex_app:s3cret-not-a-placeholder@db.internal:5432/aedifex"
            ),
            "storage_bucket": "aedifex-prod-raw",
            "user_agent": "AedifexBot/0.1 (+https://aedifex.test/bot; contact: ops@aedifex.test)",
            "source_registry_dir": str(REGISTRY_DIR),
        }
    )
    registry = load_registry(REGISTRY_DIR)
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[registry_dependency] = lambda: registry
    app.dependency_overrides[database_probe_dependency] = _healthy_probe
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestWriteBoundary:
    """The API has no authentication, and every write endpoint refuses in production.

    This is a stopgap and is documented as one: it makes the gap loud instead of closing it. The
    test exists because the failure it prevents is silent and total: an unauthenticated write API
    on a network lets any caller create projects and upload documents into anyone else's.

    Enumerated from the application's own routes rather than listed by hand, so a write endpoint
    added later cannot quietly escape the guard.
    """

    def test_every_write_endpoint_is_guarded(self, production_client: TestClient) -> None:
        posts: list[str] = []
        for route in create_app().routes:
            path = getattr(route, "path", None)
            if isinstance(path, str) and "POST" in (getattr(route, "methods", None) or set()):
                posts.append(path)
        assert posts, "the write surface should not be empty"
        unguarded: list[str] = []
        for path in posts:
            url = (
                path.replace("{project_id}", "00000000-0000-0000-0000-000000000000")
                .replace("{document_id}", "00000000-0000-0000-0000-000000000000")
                .replace("{finding_id}", "00000000-0000-0000-0000-000000000000")
            )
            response = production_client.post(url, json={})
            if response.status_code != 503:
                unguarded.append(f"{path} -> {response.status_code}")
        assert unguarded == [], "a write endpoint served a request in production"

    def test_the_refusal_says_why(self, production_client: TestClient) -> None:
        response = production_client.post("/v1/projects", json={})
        assert response.status_code == 503
        assert "authorization" in response.json()["detail"]

    def test_reads_are_unaffected(self, production_client: TestClient) -> None:
        """The corpus catalog is read-only and stays available. This guard is about writes."""
        assert production_client.get("/v1/sources").status_code == 200


class TestProjectIntakeContract:
    """The request contract for intake, enforced before any database is touched.

    Deliberately not a round trip: creating a project, storing bytes and reading an inventory back
    are database and object-store properties, and they are exercised in
    ``tests/integration/test_project_intake.py``. What belongs here is that a malformed request
    cannot reach the service layer at all.
    """

    def test_a_project_needs_a_known_source(self, client: TestClient) -> None:
        """Checked against the registry before anything is written.

        A project's source carries a real invariant — two authorities can issue the same reference
        and they are not one project — so an unknown one is a 404 rather than a row with a
        meaningless string in it.
        """
        response = client.post(
            "/v1/projects",
            json={"name": "Hostel 19", "source_id": "not_a_source", "created_by": "qs"},
        )
        assert response.status_code == 404
        assert "unknown source" in response.json()["detail"]

    @pytest.mark.parametrize(
        "body",
        [
            {"source_id": "iitb_building_works", "created_by": "qs"},
            {"name": "", "source_id": "iitb_building_works", "created_by": "qs"},
            {"name": "Hostel 19", "source_id": "iitb_building_works"},
            {"name": "Hostel 19", "created_by": "qs"},
        ],
    )
    def test_an_incomplete_declaration_is_refused(
        self, client: TestClient, body: dict[str, str]
    ) -> None:
        """A name and an author are both required: a project nobody declared has no provenance."""
        assert client.post("/v1/projects", json=body).status_code == 422

    def test_an_upload_needs_a_file(self, client: TestClient) -> None:
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/documents",
            data={"source_id": "iitb_building_works", "uploaded_by": "qs"},
        )
        assert response.status_code == 422

    def test_an_upload_names_a_known_source_before_its_body_is_read(
        self, client: TestClient
    ) -> None:
        """Refused on the source, before the bytes are read and before the database is opened.

        The order matters for more than tidiness: reading the body first would mean accepting an
        upload of arbitrary size on behalf of a source that does not exist.
        """
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/documents",
            data={"source_id": "not_a_source", "uploaded_by": "qs"},
            files={"file": ("boq.pdf", b"%PDF-1.7 not really", "application/pdf")},
        )
        assert response.status_code == 404

    def test_an_unknown_document_type_is_refused(self, client: TestClient) -> None:
        """The vocabulary of what a document *is* is a domain decision, not free text."""
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/documents",
            data={
                "source_id": "iitb_building_works",
                "uploaded_by": "qs",
                "document_type": "probably_a_boq",
            },
            files={"file": ("boq.pdf", b"%PDF-1.7", "application/pdf")},
        )
        assert response.status_code == 422

    def test_a_classification_needs_a_known_type_and_an_author(self, client: TestClient) -> None:
        target = "/v1/documents/00000000-0000-0000-0000-000000000000/classification"
        assert (
            client.post(
                target, json={"document_type": "not_a_type", "confirmed_by": "qs"}
            ).status_code
            == 422
        )
        assert client.post(target, json={"document_type": "bill_of_quantities"}).status_code == 422


class TestEvidenceKinds:
    """A finding's three kinds of evidence, and why the API must keep them apart.

    Pure function over constructed rows, no database. The reason this is worth a test: the provision
    branch did not exist until 2026-08-21, so a finding that had judged a bid security *against a
    cited clause* was served with the clause silently missing — the CLI printed it and the API
    dropped it. A threshold presented as a measurement, or omitted entirely, is the difference
    between "the bill claims this" and "the rulebook permits this".
    """

    @staticmethod
    def _finding() -> tuple[Finding, dict[uuid.UUID, ExtractedFact], dict[uuid.UUID, DerivedFact]]:
        document_id = uuid.uuid4()
        fact = ExtractedFact(
            id=uuid.uuid4(),
            document_id=document_id,
            fact_type="bid_security",
            kind=FactKind.MONEY,
            literal="Rs. 16.93 Lacs",
            numeric_value=Decimal("1693000.00"),
            page=6,
            span_start=0,
            span_end=14,
            snippet="Bid Security Rs. 16.93 Lacs",
            method="text",
            extractor="test",
            extractor_version="1",
        )
        computed = DerivedFact(
            id=uuid.uuid4(),
            document_id=document_id,
            fact_type="required_bid_security",
            kind=FactKind.MONEY,
            numeric_value=Decimal("1692999.38"),
            expression="84649969.00 * 0.02",
            calculation="apply_provision",
            calculation_version="1",
            produced_by="test",
            inputs_fingerprint="x" * 16,
        )
        provision = PolicyProvision(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            provision_type="bid_security_share",
            clause="4.14.1(a)",
            page=79,
            span_start=0,
            span_end=40,
            snippet="two percent of the estimated cost for works up to Rs. 20 crore",
            authority="nhai",
            jurisdiction="IN",
            applies_to="estimated_cost",
            applies_to_max=Decimal("200000000.00"),
            share=Decimal("0.02"),
            extractor="test",
            extractor_version="1",
        )
        finding = Finding(
            id=uuid.uuid4(),
            document_id=document_id,
            rule_id="bid_security_matches_reference_policy",
            rule_version="1",
            outcome="pass",
            summary="Bid security matches the 2% required by clause 4.14.1(a)",
            expected="1692999.38",
            observed="1693000.00",
            # Both are database-side defaults, so a transient row carries None for them.
            detail={},
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
        )
        finding.evidence = [
            FindingEvidence(role="bid_security", fact_id=fact.id),
            FindingEvidence(role="required", derived_fact_id=computed.id),
            FindingEvidence(role="provision", provision_id=provision.id, provision=provision),
        ]
        return finding, {fact.id: fact}, {computed.id: computed}

    def test_all_three_kinds_are_served_and_distinguishable(self) -> None:
        finding, facts, derived = self._finding()

        payload = FindingResponse.from_row(finding, facts, derived)

        by_origin = {item.origin: item for item in payload.evidence}
        assert set(by_origin) == {"extracted", "derived", "policy"}

    def test_a_cited_clause_carries_its_authority_and_band(self) -> None:
        """A threshold with no authority is an opinion, and a band decides which clause applied."""
        finding, facts, derived = self._finding()

        policy = next(
            item
            for item in FindingResponse.from_row(finding, facts, derived).evidence
            if item.origin == "policy"
        )

        assert policy.clause == "4.14.1(a)"
        assert policy.authority == "nhai"
        assert policy.band == "up to 200,000,000.00"
        assert policy.page == 79
        assert policy.document_id is not None, "the clause lives in a different document"

    def test_a_computed_value_names_no_document_and_shows_its_arithmetic(self) -> None:
        """A derived fact may draw on several documents; naming one would be a guess."""
        finding, facts, derived = self._finding()

        computed = next(
            item
            for item in FindingResponse.from_row(finding, facts, derived).evidence
            if item.origin == "derived"
        )

        assert computed.document_id is None
        assert computed.page is None
        assert computed.expression == "84649969.00 * 0.02"


class TestArtifactContentBoundary:
    def test_content_is_not_served_in_production(self, production_client: TestClient) -> None:
        """Same refusal as the write endpoints, for a different reason.

        The corpus mixes sources whose licence terms differ, so one unauthenticated download
        endpoint publishes all of them at once under whichever terms are loosest.
        """
        response = production_client.get(
            "/v1/documents/00000000-0000-0000-0000-000000000000/content"
        )
        assert response.status_code == 503
        assert "licence terms differ" in response.json()["detail"]

    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            ("iitb-h19-priced-bill-of-quantities.pdf", "iitb-h19-priced-bill-of-quantities.pdf"),
            # A header is one of the classic injection points: a quote or a newline in a filename
            # rewrites the response headers.
            ('evil";\r\nSet-Cookie: a=b.pdf', "evilSet-Cookie: a=b.pdf"),
            (None, "abcdef0123456789.pdf"),
            ("", "abcdef0123456789.pdf"),
        ],
    )
    def test_a_download_name_cannot_forge_headers(self, stored: str | None, expected: str) -> None:
        name = _download_name(stored, "abcdef0123456789" + "0" * 48, FileFormat.PDF)
        assert name == expected
        assert '"' not in name and "\r" not in name and "\n" not in name


class TestCellProvenance:
    """A cell reference is served only when the fact knows its sheet — and that is a real trap.

    ``sheet_row`` is *also* used for a row's position in a bill of quantities read out of a PDF,
    because work-item linking groups on the row whichever format it came from. On the corpus this
    was written against, 12,646 facts carry a ``sheet_row`` and only 548 come from a spreadsheet.
    Offering "open cell A37" for a PDF row would send a reviewer to a cell that does not exist.
    """

    @staticmethod
    def _fact(**overrides: object) -> ExtractedFact:
        fields: dict[str, object] = {
            "id": uuid.uuid4(),
            "document_id": uuid.uuid4(),
            "fact_type": "contract_rate",
            "kind": FactKind.MONEY,
            "literal": "8000",
            "numeric_value": Decimal("8000.00"),
            "page": 1,
            "span_start": 0,
            "span_end": 0,
            "snippet": "BOQ!E8",
            "method": "cell:BOQ!E8",
            "extractor": "test",
            "extractor_version": "1",
            "extracted_at": datetime(2026, 8, 22, tzinfo=UTC),
        }
        fields.update(overrides)
        return ExtractedFact(**fields)

    def test_a_spreadsheet_fact_carries_its_cell(self) -> None:
        served = FactResponse.from_row(self._fact(sheet_name="BOQ", sheet_row=8, sheet_column=5))

        assert served.cell == "BOQ!E8"
        assert served.sheet_name == "BOQ"
        assert served.sheet_row == 8

    def test_a_pdf_table_row_is_offered_no_cell(self) -> None:
        """The trap. A row position without a sheet is a row in a printed table, not a cell."""
        served = FactResponse.from_row(self._fact(sheet_row=37, snippet="Item 4.7.2 ... 8,000.00"))

        assert served.cell is None
        assert served.sheet_row == 37, "the row is still reported; it is real"

    def test_evidence_carries_the_cell_so_a_finding_can_link_to_it(self) -> None:
        fact = self._fact(sheet_name="RA Bill", sheet_row=8, sheet_column=7)
        finding = Finding(
            id=uuid.uuid4(),
            document_id=fact.document_id,
            rule_id="claimed_rate_matches_contract_rate",
            rule_version="1",
            outcome="review",
            summary="Item 4.7.3: claimed rate is above the contracted rate",
            expected="equal",
            observed="+2500 INR",
            detail={},
            evaluated_at=datetime(2026, 8, 22, tzinfo=UTC),
        )
        finding.evidence = [FindingEvidence(role="claimed_rate", fact_id=fact.id)]

        payload = FindingResponse.from_row(finding, {fact.id: fact}, {})

        assert payload.evidence[0].cell == "RA Bill!G8"
        assert payload.evidence[0].sheet_name == "RA Bill"

    def test_an_inconclusive_finding_is_not_review_work(self) -> None:
        """Item 2 of the review, at the API boundary rather than in the browser."""
        finding = Finding(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            rule_id="bid_security_matches_reference_policy",
            rule_version="1",
            outcome="inconclusive",
            summary="No reference provision could be applied to this document.",
            expected="NOT SOURCED",
            observed="nothing compared",
            detail={},
            evaluated_at=datetime(2026, 8, 22, tzinfo=UTC),
        )
        finding.evidence = []

        assert FindingResponse.from_row(finding, {}, {}).needs_human_review is False


class TestFindingSubject:
    """What a finding is *about*, stated rather than inferred.

    A project-scoped finding has no document, and ``document_id`` was typed ``str`` — so
    ``str(row.document_id)`` served the literal string ``"None"``. Every cross-document conclusion,
    which is the most valuable kind this system produces, arrived that way. Verified against the
    running API before it was fixed.
    """

    @staticmethod
    def _finding(**overrides: object) -> Finding:
        fields: dict[str, object] = {
            "id": uuid.uuid4(),
            "rule_id": "cross_document_fact_agreement",
            "rule_version": "1",
            "outcome": "pass",
            "summary": "All comparable facts agree.",
            "expected": "identical values",
            "observed": "0 disagreements",
            "detail": {},
            "evaluated_at": datetime(2026, 8, 22, tzinfo=UTC),
        }
        fields.update(overrides)
        finding = Finding(**fields)
        finding.evidence = []
        return finding

    def test_a_project_finding_has_a_null_document_and_says_its_scope(self) -> None:
        project_id = uuid.uuid4()
        payload = FindingResponse.from_row(self._finding(project_id=project_id), {}, {})

        assert payload.document_id is None
        assert payload.project_id == str(project_id)
        assert payload.scope == "project"

    def test_a_document_finding_reports_its_document(self) -> None:
        document_id = uuid.uuid4()
        payload = FindingResponse.from_row(self._finding(document_id=document_id), {}, {})

        assert payload.document_id == str(document_id)
        assert payload.project_id is None
        assert payload.scope == "document"

    def test_a_work_item_finding_carries_both_ids_and_the_narrower_scope(self) -> None:
        """An item exists only within a project, so both ids are set and the item wins."""
        project_id, work_item_id = uuid.uuid4(), uuid.uuid4()
        payload = FindingResponse.from_row(
            self._finding(project_id=project_id, work_item_id=work_item_id), {}, {}
        )

        assert payload.scope == "work_item"
        assert payload.work_item_id == str(work_item_id)
        assert payload.project_id == str(project_id)
