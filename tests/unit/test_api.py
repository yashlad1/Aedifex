"""Tests for the read-only acquisition API.

No database is required: the readiness endpoint is expected to report the database as
unavailable, which is itself one of the behaviours worth testing.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from apps.api.main import REQUEST_ID_HEADER, create_app, registry_dependency, settings_dependency
from fastapi.testclient import TestClient

from aedifex.acquisition.registry import load_registry
from aedifex.config import Environment, Settings

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "config" / "sources"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client wired to the repository's real registry, with no ambient configuration."""
    app = create_app()
    settings = Settings(environment=Environment.TEST, source_registry_dir=str(REGISTRY_DIR))
    registry = load_registry(REGISTRY_DIR)
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[registry_dependency] = lambda: registry
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

    def test_readiness_reports_each_dependency(self, client: TestClient) -> None:
        """With no database running, readiness must fail loudly and say which check failed."""
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["registry"].startswith("ok")
        assert body["checks"]["database"].startswith("unavailable")

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
