"""Tests for the source-registry schema invariants.

These are the collection ethics expressed as code. Each test names a way the project could
accidentally collect data it has no right to, and asserts the schema makes it impossible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from aedifex.acquisition.registry.models import (
    AccessLevel,
    DataUsePolicy,
    RateLimitPolicy,
    RetrievalMethod,
    RobotsPolicy,
    SourceCategory,
    SourceDefinition,
    VerificationStatus,
)
from aedifex.domain.documents import DocumentType
from aedifex.domain.files import FileFormat


def source_kwargs(**overrides: Any) -> dict[str, Any]:
    """A valid, disabled source definition, for mutation in individual tests."""
    base: dict[str, Any] = {
        "id": "example_portal",
        "name": "Example Portal",
        "country": "IN",
        "category": SourceCategory.GOVERNMENT_PROCUREMENT,
        "retrieval": RetrievalMethod.HTTP_CRAWL,
        "base_url": "https://example.test/",
        "data_use": DataUsePolicy(
            license="CC-BY-4.0",
            allowed_use="Redistribution permitted with attribution.",
        ),
        "document_types": (DocumentType.TENDER_NOTICE,),
        "file_formats": (FileFormat.PDF,),
    }
    base.update(overrides)
    return base


class TestDefaults:
    def test_a_new_source_is_disabled_and_unverified(self) -> None:
        """Presumed off-limits until reviewed. The safe default must be the implicit one."""
        source = SourceDefinition(**source_kwargs())
        assert source.enabled is False
        assert source.verification_status is VerificationStatus.UNVERIFIED
        assert source.is_collectable is False

    def test_robots_are_respected_by_default(self) -> None:
        assert SourceDefinition(**source_kwargs()).robots_policy is RobotsPolicy.RESPECT

    def test_default_rate_limit_is_conservative(self) -> None:
        limit = SourceDefinition(**source_kwargs()).rate_limit
        assert limit.requests_per_minute <= 30
        assert limit.max_concurrency <= 2

    def test_definitions_are_immutable(self) -> None:
        source = SourceDefinition(**source_kwargs())
        with pytest.raises(ValidationError):
            source.enabled = True  # type: ignore[misc]

    def test_unknown_field_is_rejected(self) -> None:
        """A misspelled YAML key must fail rather than be silently dropped."""
        with pytest.raises(ValidationError):
            SourceDefinition(**source_kwargs(rate_limits={"requests_per_minute": 5}))


class TestEnablingRequiresReview:
    def test_cannot_enable_an_unverified_source(self) -> None:
        with pytest.raises(ValidationError, match="terms of use must be reviewed"):
            SourceDefinition(**source_kwargs(enabled=True, crawler="example"))

    def test_cannot_enable_a_blocked_source(self) -> None:
        with pytest.raises(ValidationError, match="terms of use must be reviewed"):
            SourceDefinition(
                **source_kwargs(
                    enabled=True,
                    crawler="example",
                    verification_status=VerificationStatus.BLOCKED,
                )
            )

    def test_cannot_enable_without_a_crawler(self) -> None:
        with pytest.raises(ValidationError, match="no crawler implementation"):
            SourceDefinition(
                **source_kwargs(enabled=True, verification_status=VerificationStatus.APPROVED)
            )

    def test_approved_source_with_a_crawler_can_be_enabled(self) -> None:
        source = SourceDefinition(
            **source_kwargs(
                enabled=True,
                crawler="example",
                verification_status=VerificationStatus.APPROVED,
            )
        )
        assert source.is_collectable is True

    def test_manual_upload_needs_no_crawler(self) -> None:
        source = SourceDefinition(
            **source_kwargs(
                retrieval=RetrievalMethod.MANUAL_UPLOAD,
                base_url=None,
                robots_policy=RobotsPolicy.NOT_APPLICABLE,
                enabled=True,
                verification_status=VerificationStatus.APPROVED,
            )
        )
        assert source.is_collectable is True

    def test_approved_but_disabled_source_is_not_collectable(self) -> None:
        source = SourceDefinition(
            **source_kwargs(crawler="example", verification_status=VerificationStatus.APPROVED)
        )
        assert source.is_collectable is False


class TestAccessControls:
    def test_a_restricted_upload_source_may_be_enabled(self) -> None:
        """The one exemption, and why it is not a hole in the rule.

        The prohibition exists because *fetching* from behind an access control would mean
        bypassing that control. A ``manual_upload`` source makes no request: the owner of the
        documents hands them over. ``restricted`` there records that the contents are not ours to
        redistribute — a statement about what we may do with the bytes rather than about how we got
        them. Refusing to model it would force every customer's documents to be filed as ``public``.
        """
        source = SourceDefinition(
            **source_kwargs(
                enabled=True,
                retrieval=RetrievalMethod.MANUAL_UPLOAD,
                base_url=None,
                verification_status=VerificationStatus.APPROVED,
                data_use=DataUsePolicy(
                    license="Proprietary to the customer",
                    access=AccessLevel.RESTRICTED,
                    allowed_use="Review for the customer who supplied it. No redistribution.",
                ),
            )
        )
        assert source.is_collectable is True

    def test_a_restricted_source_can_never_be_enabled(self) -> None:
        """Collecting from behind an access control would mean bypassing it."""
        with pytest.raises(ValidationError, match="behind an access control"):
            SourceDefinition(
                **source_kwargs(
                    enabled=True,
                    crawler="example",
                    verification_status=VerificationStatus.APPROVED,
                    data_use=DataUsePolicy(
                        license="Proprietary",
                        access=AccessLevel.RESTRICTED,
                        allowed_use="Internal use only, requires a licence agreement.",
                    ),
                )
            )

    def test_a_restricted_source_may_be_recorded_while_disabled(self) -> None:
        """Recording that a source exists and is off-limits is useful; collecting is not."""
        source = SourceDefinition(
            **source_kwargs(
                data_use=DataUsePolicy(
                    license="Proprietary",
                    access=AccessLevel.RESTRICTED,
                    allowed_use="Internal use only, requires a licence agreement.",
                )
            )
        )
        assert source.is_collectable is False


class TestTransportSecurity:
    def test_plain_http_requires_explicit_acknowledgement(self) -> None:
        with pytest.raises(ValidationError, match="plain HTTP"):
            SourceDefinition(**source_kwargs(base_url="http://legacy.test/"))

    def test_plain_http_is_allowed_when_acknowledged(self) -> None:
        source = SourceDefinition(
            **source_kwargs(base_url="http://legacy.test/", allow_insecure_transport=True)
        )
        assert source.allow_insecure_transport is True

    def test_the_acknowledgement_is_rejected_when_unnecessary(self) -> None:
        """A stale flag on an HTTPS source is misleading, so it must be removed."""
        with pytest.raises(ValidationError, match="not plain HTTP"):
            SourceDefinition(**source_kwargs(allow_insecure_transport=True))


class TestRobotsPolicy:
    def test_html_crawling_must_respect_robots(self) -> None:
        with pytest.raises(ValidationError, match="robots_policy must be 'respect'"):
            SourceDefinition(
                **source_kwargs(
                    retrieval=RetrievalMethod.HTTP_CRAWL,
                    robots_policy=RobotsPolicy.NOT_APPLICABLE,
                )
            )

    def test_api_sources_may_declare_robots_not_applicable(self) -> None:
        source = SourceDefinition(
            **source_kwargs(
                retrieval=RetrievalMethod.HTTP_API, robots_policy=RobotsPolicy.NOT_APPLICABLE
            )
        )
        assert source.robots_policy is RobotsPolicy.NOT_APPLICABLE


class TestBaseUrl:
    @pytest.mark.parametrize(
        "retrieval",
        [RetrievalMethod.HTTP_CRAWL, RetrievalMethod.HTTP_API, RetrievalMethod.BULK_DOWNLOAD],
    )
    def test_base_url_is_required_for_remote_retrieval(self, retrieval: RetrievalMethod) -> None:
        with pytest.raises(ValidationError, match="base_url is required"):
            SourceDefinition(
                **source_kwargs(
                    retrieval=retrieval,
                    base_url=None,
                    robots_policy=(
                        RobotsPolicy.RESPECT
                        if retrieval is RetrievalMethod.HTTP_CRAWL
                        else RobotsPolicy.NOT_APPLICABLE
                    ),
                )
            )

    def test_manual_upload_needs_no_base_url(self) -> None:
        source = SourceDefinition(
            **source_kwargs(
                retrieval=RetrievalMethod.MANUAL_UPLOAD,
                base_url=None,
                robots_policy=RobotsPolicy.NOT_APPLICABLE,
            )
        )
        assert source.base_url is None

    @pytest.mark.parametrize("url", ["not-a-url", "ftp://example.test/", "file:///etc/passwd"])
    def test_non_http_urls_are_rejected(self, url: str) -> None:
        with pytest.raises(ValidationError):
            SourceDefinition(**source_kwargs(base_url=url))


class TestIdentifiers:
    @pytest.mark.parametrize(
        "source_id", ["a", "A_portal", "1portal", "my-portal", "my portal", ""]
    )
    def test_malformed_ids_are_rejected(self, source_id: str) -> None:
        """Ids appear in storage paths, so the character set is deliberately narrow."""
        with pytest.raises(ValidationError):
            SourceDefinition(**source_kwargs(id=source_id))

    @pytest.mark.parametrize("source_id", ["cpwd", "cppp_eprocure", "nhai2"])
    def test_well_formed_ids_are_accepted(self, source_id: str) -> None:
        assert SourceDefinition(**source_kwargs(id=source_id)).id == source_id

    @pytest.mark.parametrize("country", ["in", "IND", "I", "12", ""])
    def test_malformed_country_codes_are_rejected(self, country: str) -> None:
        with pytest.raises(ValidationError):
            SourceDefinition(**source_kwargs(country=country))


class TestDocumentTypesAndFormats:
    def test_at_least_one_document_type_is_required(self) -> None:
        with pytest.raises(ValidationError):
            SourceDefinition(**source_kwargs(document_types=()))

    def test_at_least_one_file_format_is_required(self) -> None:
        with pytest.raises(ValidationError):
            SourceDefinition(**source_kwargs(file_formats=()))

    def test_duplicate_document_types_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unique"):
            SourceDefinition(
                **source_kwargs(
                    document_types=(DocumentType.TENDER_NOTICE, DocumentType.TENDER_NOTICE)
                )
            )

    def test_duplicate_file_formats_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unique"):
            SourceDefinition(**source_kwargs(file_formats=(FileFormat.PDF, FileFormat.PDF)))

    def test_unknown_document_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceDefinition(**source_kwargs(document_types=("blueprint_thing",)))


class TestRateLimitPolicy:
    def test_bounds(self) -> None:
        with pytest.raises(ValidationError):
            RateLimitPolicy(requests_per_minute=0)
        with pytest.raises(ValidationError):
            RateLimitPolicy(requests_per_minute=10_000)
        with pytest.raises(ValidationError):
            RateLimitPolicy(max_concurrency=0)
        with pytest.raises(ValidationError):
            RateLimitPolicy(max_concurrency=64)

    def test_contradictory_limits_are_rejected(self) -> None:
        """60 rpm cannot coexist with a 5-second minimum gap; refuse rather than pick a winner."""
        with pytest.raises(ValidationError, match="unreachable"):
            RateLimitPolicy(requests_per_minute=60, min_delay_seconds=5.0)

    def test_consistent_limits_are_accepted(self) -> None:
        limit = RateLimitPolicy(requests_per_minute=12, min_delay_seconds=5.0)
        assert limit.requests_per_minute == 12

    def test_zero_delay_disables_the_consistency_check(self) -> None:
        policy = RateLimitPolicy(requests_per_minute=600, min_delay_seconds=0.0)
        assert policy.min_delay_seconds == 0

    def test_document_cap_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            RateLimitPolicy(max_documents_per_run=0)


class TestDataUsePolicy:
    def test_licence_and_permitted_use_are_mandatory(self) -> None:
        """Provenance metadata is a required field, not optional documentation."""
        with pytest.raises(ValidationError):
            DataUsePolicy(allowed_use="Anything goes.")  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            DataUsePolicy(license="CC-BY-4.0")  # type: ignore[call-arg]

    def test_a_perfunctory_allowed_use_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DataUsePolicy(license="CC-BY-4.0", allowed_use="ok")

    def test_attribution_is_assumed_required(self) -> None:
        policy = DataUsePolicy(license="CC-BY-4.0", allowed_use="Redistribution permitted.")
        assert policy.attribution_required is True

    def test_personal_data_defaults_to_absent_but_is_declarable(self) -> None:
        policy = DataUsePolicy(
            license="CC-BY-4.0",
            allowed_use="Redistribution permitted.",
            contains_personal_data=True,
        )
        assert policy.contains_personal_data is True

    def test_naive_review_date_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone"):
            DataUsePolicy(
                license="CC-BY-4.0",
                allowed_use="Redistribution permitted.",
                reviewed_on=datetime(2026, 1, 1),  # noqa: DTZ001 - deliberately naive
            )

    def test_future_review_date_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="future"):
            DataUsePolicy(
                license="CC-BY-4.0",
                allowed_use="Redistribution permitted.",
                reviewed_on=datetime.now(UTC) + timedelta(days=2),
            )


class TestLastSuccessfulRun:
    def test_naive_timestamp_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone"):
            SourceDefinition(
                **source_kwargs(last_successful_run=datetime(2026, 1, 1))  # noqa: DTZ001
            )

    def test_future_timestamp_is_rejected(self) -> None:
        """A future run time usually means a clock problem, and would break incremental crawls."""
        with pytest.raises(ValidationError, match="future"):
            SourceDefinition(
                **source_kwargs(last_successful_run=datetime.now(UTC) + timedelta(hours=1))
            )

    def test_past_aware_timestamp_is_accepted(self) -> None:
        timestamp = datetime.now(UTC) - timedelta(days=1)
        assert SourceDefinition(**source_kwargs(last_successful_run=timestamp)).last_successful_run
