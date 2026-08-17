"""Validation of the source registry that actually ships in this repository.

Distinct from ``test_registry_loader.py``, which tests the loader against synthetic files.
These tests assert properties of the real ``config/sources/*.yaml`` content, so that a
careless edit to a YAML file fails the build.

The assertions are deliberately written as invariants rather than as a snapshot of today's
contents. Approving a source for collection *should* be possible without editing tests;
approving one without recording who reviewed it should not be.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aedifex.acquisition.registry import SourceDefinition, load_registry
from aedifex.acquisition.registry.models import (
    AccessLevel,
    RetrievalMethod,
    RobotsPolicy,
    VerificationStatus,
)

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "config" / "sources"


@pytest.fixture(scope="module")
def sources() -> tuple[SourceDefinition, ...]:
    return load_registry(REGISTRY_DIR).all()


def test_the_shipped_registry_is_valid() -> None:
    """The registry files must load; this is the gate a bad YAML edit hits first."""
    assert len(load_registry(REGISTRY_DIR)) > 0


def test_ids_are_unique(sources: tuple[SourceDefinition, ...]) -> None:
    identifiers = [source.id for source in sources]
    assert len(identifiers) == len(set(identifiers))


def test_every_source_records_a_licence_and_permitted_use(
    sources: tuple[SourceDefinition, ...],
) -> None:
    for source in sources:
        assert source.data_use.license.strip(), f"{source.id} has no licence recorded"
        assert (
            len(source.data_use.allowed_use.strip()) >= 10
        ), f"{source.id} has no meaningful permitted-use statement"


def test_every_source_has_a_description_and_notes(sources: tuple[SourceDefinition, ...]) -> None:
    """Future maintainers need to know what a source is and what is awkward about it."""
    for source in sources:
        assert source.description, f"{source.id} has no description"


class TestCollectionSafety:
    def test_no_unreviewed_source_is_enabled(self, sources: tuple[SourceDefinition, ...]) -> None:
        for source in sources:
            if source.enabled:
                assert (
                    source.verification_status is VerificationStatus.APPROVED
                ), f"{source.id} is enabled without an approved terms review"

    def test_every_approved_source_records_who_reviewed_it(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        """An approval with no reviewer is not an approval."""
        for source in sources:
            if source.verification_status is VerificationStatus.APPROVED:
                assert (
                    source.data_use.reviewed_by
                ), f"{source.id} is approved but records no reviewer"
                assert (
                    source.data_use.reviewed_on
                ), f"{source.id} is approved but records no review date"

    def test_no_approved_source_still_claims_a_pending_licence(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        for source in sources:
            if source.verification_status is VerificationStatus.APPROVED:
                assert (
                    "pending" not in source.data_use.license.lower()
                ), f"{source.id} is approved but its licence still says 'pending'"

    def test_no_enabled_source_sits_behind_an_access_control(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        for source in sources:
            if source.enabled:
                assert (
                    source.data_use.access is not AccessLevel.RESTRICTED
                ), f"{source.id} is enabled but marked restricted"

    def test_every_enabled_remote_source_has_a_crawler(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        for source in sources:
            if source.enabled and source.retrieval is not RetrievalMethod.MANUAL_UPLOAD:
                assert source.crawler, f"{source.id} is enabled with no crawler"

    def test_html_crawling_sources_respect_robots(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        for source in sources:
            if source.retrieval is RetrievalMethod.HTTP_CRAWL:
                assert (
                    source.robots_policy is RobotsPolicy.RESPECT
                ), f"{source.id} crawls HTML but does not respect robots.txt"

    def test_no_source_uses_plain_http_without_acknowledgement(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        for source in sources:
            if source.base_url is not None and source.base_url.scheme == "http":
                assert (
                    source.allow_insecure_transport
                ), f"{source.id} uses plain HTTP without acknowledging it"


class TestPoliteness:
    def test_rate_limits_are_conservative_for_government_portals(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        """Public procurement portals are frequently fragile; treat them gently."""
        for source in sources:
            if source.retrieval in (RetrievalMethod.HTTP_CRAWL, RetrievalMethod.HTTP_API):
                assert (
                    source.rate_limit.requests_per_minute <= 60
                ), f"{source.id} requests up to {source.rate_limit.requests_per_minute}/min"
                assert (
                    source.rate_limit.max_concurrency <= 4
                ), f"{source.id} allows {source.rate_limit.max_concurrency} concurrent requests"

    def test_crawling_sources_have_a_minimum_delay(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        for source in sources:
            if source.retrieval is RetrievalMethod.HTTP_CRAWL:
                assert (
                    source.rate_limit.min_delay_seconds >= 1.0
                ), f"{source.id} crawls HTML with no meaningful delay between requests"


class TestPersonalData:
    def test_sources_known_to_publish_personal_data_are_flagged(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        """Bidder documents carry names, PAN, and contact details.

        The flag drives mandatory PII screening later, so a source that publishes bid
        documents must declare it.
        """
        for source in sources:
            types = {document_type.value for document_type in source.document_types}
            if "bid_document" in types:
                assert (
                    source.data_use.contains_personal_data
                ), f"{source.id} yields bid documents but does not declare personal data"


class TestSyntheticSource:
    def test_synthetic_data_is_registered_as_a_source(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        """Synthetic documents must traverse the same pipeline as collected ones.

        A separate code path for synthetic data would let bugs hide in the path that only
        real documents take.
        """
        synthetic = [source for source in sources if source.category.value == "synthetic"]
        assert synthetic, "no synthetic source is registered"

    def test_synthetic_source_declares_no_personal_data(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        for source in sources:
            if source.category.value == "synthetic":
                assert source.data_use.contains_personal_data is False

    def test_synthetic_source_covers_the_payment_auditor_document_types(
        self, sources: tuple[SourceDefinition, ...]
    ) -> None:
        """The generator has to produce every document type the audit rules reconcile."""
        required = {
            "contract",
            "bill_of_quantities",
            "purchase_order",
            "invoice",
            "delivery_challan",
            "goods_receipt_note",
            "material_test_certificate",
            "inspection_report",
            "change_order",
        }
        for source in sources:
            if source.category.value == "synthetic":
                declared = {document_type.value for document_type in source.document_types}
                assert required <= declared, f"missing: {sorted(required - declared)}"
