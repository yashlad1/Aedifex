"""The parts of the acquirer and the provenance writer that need no database.

Most of both modules is about rows, and rows are covered in ``tests/integration/test_acquirer.py``
against real PostgreSQL and MinIO — the coverage report shows this file reaching only a fraction of
either, which is expected rather than a gap. What is covered here is the part that decides *what to
write*: how a failure is labelled, and how an attempt history is turned into JSON.

Those are worth testing directly because they are the parts a later reader is most likely to change
without noticing what depends on them. A label is written into a column that something will query;
an attempt record's JSON shape is written into rows that cannot be migrated after the fact.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aedifex.acquisition.download import DownloadPolicy
from aedifex.acquisition.fetch.controller import AttemptRecord, FetchFailedError
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.ratelimit import RateLimits
from aedifex.acquisition.fetch.redirect_controller import RedirectRejectedError
from aedifex.acquisition.fetch.retry import AttemptOutcome
from aedifex.acquisition.fetch.timing import TimeoutPolicy
from aedifex.acquisition.fetch.transport import ReadTimeoutError, TlsVerificationError
from aedifex.acquisition.fetch.urls import RejectionReason, SsrfRejectionError
from aedifex.acquisition.pipeline import (
    AcquisitionPolicy,
    AcquisitionResult,
    ObjectStore,
    _classify,
)
from aedifex.acquisition.provenance import _attempt_as_json
from aedifex.acquisition.registry import load_registry
from aedifex.acquisition.registry.models import (
    AccessLevel,
    DataUsePolicy,
    RateLimitPolicy,
    RetrievalMethod,
    SourceCategory,
    SourceDefinition,
    VerificationStatus,
)
from aedifex.domain.documents import DocumentState, DocumentType
from aedifex.domain.files import FileFormat
from aedifex.errors import AcquisitionError, SourceNotCollectableError, UnsafeContentError
from aedifex.infrastructure.database.models import DiscoveredUrl
from aedifex.infrastructure.storage.objects import (
    RawObjectStore,
    StorageError,
    StoredObject,
    Verification,
)

SOURCE = "cpwd"


def a_policy() -> AcquisitionPolicy:
    return AcquisitionPolicy(
        host_policy=SourceHostPolicy(
            source_id=SOURCE, base_hosts=frozenset({"cpwd.test"}), exact_hosts=frozenset()
        ),
        limits=RateLimits(requests_per_minute=60, max_concurrency=2, min_delay_seconds=0.0),
        download=DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF})),
    )


def a_row(url: str = "https://cpwd.test/a.pdf") -> DiscoveredUrl:
    """An unpersisted frontier row. Enough for the value objects; not enough to write."""
    return DiscoveredUrl(source_id=SOURCE, url=url, url_sha256="ab" * 32)


def a_stored_object(*, already_present: bool = False) -> StoredObject:
    return StoredObject(
        bucket="aedifex-test",
        key=f"raw/{SOURCE}/aa/bb/{'aa' * 32}.pdf",
        sha256="aa" * 32,
        size_bytes=4096,
        version_id="v1",
        etag="etag",
        verification=Verification.SERVER_CHECKSUM,
        already_present=already_present,
    )


class TestFailureLabels:
    """What lands in ``error_type``, which is a column something will eventually group by."""

    def test_a_fetch_failure_is_labelled_by_its_outcome(self) -> None:
        error = FetchFailedError("no luck", final_outcome=AttemptOutcome.HTTP_STATUS, attempts=())
        assert _classify(error) == "http_status"

    def test_a_refused_redirect_is_labelled_by_why_it_was_refused(self) -> None:
        """The case a Python type name flattens.

        ``RedirectRejectedError`` covers an SSRF refusal and a hop-cap breach alike, and those are
        different events — one is a server pointing us somewhere we must not go, the other is a
        server wasting our time. Recording the class name would make them indistinguishable in the
        one place someone would look.
        """
        ssrf = RedirectRejectedError(
            "refused", final_outcome=AttemptOutcome.SSRF_REJECTED, chain=()
        )
        loop = RedirectRejectedError(
            "refused", final_outcome=AttemptOutcome.INVALID_REDIRECT, chain=()
        )

        assert _classify(ssrf) == "ssrf_rejected"
        assert _classify(loop) == "invalid_redirect"
        assert _classify(ssrf) != _classify(loop)

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (ReadTimeoutError("slow"), "read_timeout"),
            (TlsVerificationError("bad cert"), "tls_error"),
        ],
    )
    def test_a_transport_failure_is_labelled_by_its_own_classification(
        self, error: Exception, expected: str
    ) -> None:
        assert _classify(error) == expected

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (UnsafeContentError("not a pdf"), "UnsafeContentError"),
            (StorageError("bucket is on fire"), "StorageError"),
            (SsrfRejectionError(RejectionReason.MALFORMED_URL, "nope"), "SsrfRejectionError"),
        ],
    )
    def test_an_error_carrying_no_classification_falls_back_to_its_type(
        self, error: Exception, expected: str
    ) -> None:
        """Which is why the column is a string and not an enum: not every failure has an outcome.

        Note ``SsrfRejectionError`` here: on its own it carries no outcome, and it reaches the
        acquirer wrapped in a ``RedirectRejectedError`` that does. This is the unwrapped shape.
        """
        assert _classify(error) == expected

    def test_a_label_is_bounded_by_the_column(self) -> None:
        """A pathological exception name must not fail the write it is describing."""

        absurd = type("X" * 400, (Exception,), {})
        assert len(_classify(absurd("boom"))) <= 128

    def test_a_non_string_outcome_is_ignored_rather_than_written(self) -> None:
        """Defensive, and cheap: something must reach the column, and it must be a string."""

        class OddError(Exception):
            outcome = 42

        assert _classify(OddError("boom")) == "OddError"


class TestAcquisitionResult:
    def test_a_success_reports_the_object_and_the_document(self) -> None:
        result = AcquisitionResult(
            url="https://cpwd.test/a.pdf",
            source_id=SOURCE,
            state=DocumentState.DOWNLOADED,
            frontier=a_row(),
            stored=a_stored_object(),
        )
        assert result.succeeded is True
        assert result.was_already_stored is False
        assert "s3://aedifex-test/raw/cpwd/" in result.describe()

    def test_a_failure_describes_the_reason_and_names_no_object(self) -> None:
        result = AcquisitionResult(
            url="https://cpwd.test/a.pdf",
            source_id=SOURCE,
            state=DocumentState.FAILED,
            frontier=a_row(),
            error_type="http_status",
        )
        assert result.succeeded is False
        assert result.document_id is None
        assert result.was_already_stored is False
        assert "http_status" in result.describe()
        assert "s3://" not in result.describe()

    def test_a_failure_with_no_recorded_reason_still_describes_itself(self) -> None:
        """A log line that reads "None" teaches nobody anything."""
        result = AcquisitionResult(
            url="https://cpwd.test/a.pdf",
            source_id=SOURCE,
            state=DocumentState.FAILED,
            frontier=a_row(),
        )
        assert "no reason recorded" in result.describe()

    def test_an_object_that_was_already_there_is_reported_as_such(self) -> None:
        result = AcquisitionResult(
            url="https://cpwd.test/a.pdf",
            source_id=SOURCE,
            state=DocumentState.DOWNLOADED,
            frontier=a_row(),
            stored=a_stored_object(already_present=True),
        )
        assert result.was_already_stored is True

    def test_a_quarantined_result_is_not_a_success(self) -> None:
        result = AcquisitionResult(
            url="https://cpwd.test/a.pdf",
            source_id=SOURCE,
            state=DocumentState.QUARANTINED,
            frontier=a_row(),
            error_type="UnsafeContentError",
        )
        assert result.succeeded is False


class TestAcquisitionPolicy:
    def test_the_source_comes_from_the_host_policy(self) -> None:
        """One source of truth, so a request cannot be charged to the wrong source."""
        assert a_policy().source_id == SOURCE

    def test_the_timeouts_have_a_default(self) -> None:
        assert a_policy().timeouts == TimeoutPolicy()

    def test_two_policies_do_not_share_a_timeout_object(self) -> None:
        """A ``default_factory``: the day ``TimeoutPolicy`` stops being frozen, this stays safe."""
        assert a_policy().timeouts is not a_policy().timeouts


class TestObjectStoreProtocol:
    def test_the_real_store_satisfies_what_the_acquirer_needs(self) -> None:
        """Asserted, not assumed — the acquirer takes a protocol so a test can substitute one."""
        assert isinstance(RawObjectStore.__new__(RawObjectStore), ObjectStore)


class TestAttemptSerialisation:
    def test_an_attempt_becomes_a_flat_json_object(self) -> None:
        record = AttemptRecord(
            attempt=2,
            outcome=AttemptOutcome.HTTP_STATUS,
            duration_ms=123.4567,
            status_code=503,
            error_type=None,
            retry_after_seconds=5.0,
            delay_before_next_seconds=1.5,
            reason="HTTP 503 is retryable",
        )
        assert _attempt_as_json(record) == {
            "attempt": 2,
            "outcome": "http_status",
            "duration_ms": 123.457,
            "status_code": 503,
            "error_type": None,
            "retry_after_seconds": 5.0,
            "delay_before_next_seconds": 1.5,
            "reason": "HTTP 503 is retryable",
        }

    def test_the_enum_is_written_as_its_value(self) -> None:
        """So a query reads ``'read_timeout'`` rather than ``'READ_TIMEOUT'``."""
        record = AttemptRecord(attempt=1, outcome=AttemptOutcome.READ_TIMEOUT, duration_ms=1.0)
        assert _attempt_as_json(record)["outcome"] == "read_timeout"

    def test_the_shape_is_fixed_rather_than_derived_from_the_dataclass(self) -> None:
        """Written out field by field on purpose.

        A field added to ``AttemptRecord`` must not silently change the shape of rows already
        written, because JSONB already in the database cannot be migrated by adding a column. So the
        set of keys is pinned here, and adding one is a decision that fails this test first.
        """
        keys = set(_attempt_as_json(AttemptRecord(1, AttemptOutcome.SUCCESS, 1.0)))
        assert keys == {
            "attempt",
            "outcome",
            "duration_ms",
            "status_code",
            "error_type",
            "retry_after_seconds",
            "delay_before_next_seconds",
            "reason",
        }

    def test_no_response_body_can_reach_a_row(self) -> None:
        """``AttemptRecord`` holds none, and this is the boundary where that matters."""
        serialised = _attempt_as_json(
            AttemptRecord(1, AttemptOutcome.SUCCESS, 1.0, status_code=200)
        )
        assert not any(
            key in serialised for key in ("body", "content", "text", "payload", "response")
        )


class TestUuidIsNotInvented:
    def test_the_result_reports_no_document_when_nothing_was_recorded(self) -> None:
        """A caller must not be handed an id for a document that does not exist."""
        result = AcquisitionResult(
            url="https://cpwd.test/a.pdf",
            source_id=SOURCE,
            state=DocumentState.FAILED,
            frontier=a_row(),
        )
        assert result.document_id is None
        assert not isinstance(result.document_id, uuid.UUID)


def an_approved_source(**overrides: object) -> SourceDefinition:
    """A source a human has reviewed and enabled. The only kind that may produce traffic.

    Note what it takes to build one: approval, a reviewer, a review date, and a crawler. That is the
    point — the schema makes an unreviewed source unfetchable, and this factory is the shape of a
    decision somebody signed for.
    """
    fields: dict[str, object] = {
        "id": "example_portal",
        "name": "Example Portal",
        "country": "IN",
        "category": SourceCategory.GOVERNMENT_PROCUREMENT,
        "retrieval": RetrievalMethod.HTTP_CRAWL,
        "base_url": "https://portal.example.test/",
        "enabled": True,
        "verification_status": VerificationStatus.APPROVED,
        "crawler": "example_tenders",
        "rate_limit": RateLimitPolicy(
            requests_per_minute=10, max_concurrency=1, min_delay_seconds=3.0
        ),
        "data_use": DataUsePolicy(
            license="Government Open Data Licence - India",
            allowed_use="Redistribution permitted with attribution.",
            access=AccessLevel.PUBLIC,
            reviewed_by="an actual human",
            reviewed_on=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        "document_types": (DocumentType.TENDER_NOTICE,),
        "file_formats": (FileFormat.PDF,),
    }
    fields.update(overrides)
    return SourceDefinition(**fields)  # type: ignore[arg-type]


class TestPolicyComesFromTheRegistry:
    """The one door from registry data to network policy (FR-074).

    Every value below is asserted to have come from the definition rather than from a default,
    because the failure this guards against is silent: a policy that looks assembled but carries a
    library default would crawl a fragile portal at the wrong rate and nothing would complain.
    """

    def test_every_limit_is_taken_from_the_definition(self) -> None:
        source = an_approved_source(
            id="nhai",
            base_url="https://nhai.gov.in/",
            rate_limit=RateLimitPolicy(
                requests_per_minute=6, max_concurrency=1, min_delay_seconds=5.0
            ),
            file_formats=(FileFormat.PDF, FileFormat.XLSX),
        )

        policy = AcquisitionPolicy.from_source(source, max_bytes=8 * 1024 * 1024)

        assert policy.source_id == "nhai"
        assert policy.host_policy.permits("nhai.gov.in")
        assert policy.limits.requests_per_minute == 6
        assert policy.limits.max_concurrency == 1
        assert policy.limits.min_delay_seconds == 5.0
        assert policy.download.allowed_formats == frozenset({FileFormat.PDF, FileFormat.XLSX})
        assert policy.download.max_bytes == 8 * 1024 * 1024

    def test_the_host_allowlist_keeps_its_asymmetry(self) -> None:
        """Subdomains of the source's own domain, exact matches for anything else.

        Asserted here and not only in ``test_fetch_hosts.py`` because this is where the two
        allowlists are assembled from one definition, and a swap between them would be invisible:
        both are frozensets of strings.
        """
        source = an_approved_source(
            base_url="https://nhai.gov.in/", additional_hosts=("library.nhai.org",)
        )
        hosts = AcquisitionPolicy.from_source(source).host_policy

        assert hosts.permits("nhai.gov.in")
        assert hosts.permits("documents.nhai.gov.in")
        assert hosts.permits("library.nhai.org")
        # The CDN rule: an exact host does not bring its subdomains with it.
        assert not hosts.permits("tenants.library.nhai.org")
        # And the lookalike, which a plain suffix match would have allowed.
        assert not hosts.permits("evilnhai.gov.in")

    def test_a_format_the_registry_omits_is_not_permitted(self) -> None:
        """The archive decision, enforced where it takes effect.

        The first production source declares no ``zip``, so ZIP attachments are discovered and
        refused rather than opened — rule 52 forbids archive expansion until bounded extraction
        exists. If someone adds ``zip`` to the YAML, this is the test that should stop being true
        only because the extractor was built.
        """
        policy = AcquisitionPolicy.from_source(an_approved_source())
        assert FileFormat.ZIP not in policy.download.allowed_formats

    def test_the_byte_ceiling_defaults_rather_than_being_unbounded(self) -> None:
        assert AcquisitionPolicy.from_source(an_approved_source()).download.max_bytes > 0

    def test_timeouts_default_because_the_registry_declares_none(self) -> None:
        """Our patience is not the source's licence to grant."""
        assert AcquisitionPolicy.from_source(an_approved_source()).timeouts == TimeoutPolicy()

    def test_an_explicit_timeout_policy_is_honoured(self) -> None:
        timeouts = TimeoutPolicy(connect_seconds=1.0, read_seconds=2.0, total_seconds=3.0)
        policy = AcquisitionPolicy.from_source(an_approved_source(), timeouts=timeouts)
        assert policy.timeouts is timeouts


class TestTheReviewGateIsEnforcedAtTheDoor:
    """No approval, no policy, no traffic — rule 60.

    The schema already refuses to *enable* an unreviewed source. These assert the same rule at the
    point of use, because a definition that is valid and says ``enabled: false`` is still a
    definition that must not produce a single request.
    """

    def test_a_source_nobody_has_reviewed_cannot_be_fetched_from(self) -> None:
        unreviewed = an_approved_source(
            enabled=False, verification_status=VerificationStatus.UNVERIFIED, crawler=None
        )
        with pytest.raises(SourceNotCollectableError, match="may not be collected from"):
            AcquisitionPolicy.from_source(unreviewed)

    def test_approval_alone_is_not_permission(self) -> None:
        """Reviewed and then switched off. Approval records a finding; ``enabled`` is the decision.

        Worth its own test because ``is_collectable`` is an ``and`` of two fields, and a reading
        that checked only the review status would pass every other test in this class.
        """
        approved_but_off = an_approved_source(enabled=False)
        assert approved_but_off.verification_status is VerificationStatus.APPROVED

        with pytest.raises(SourceNotCollectableError, match="enabled=False"):
            AcquisitionPolicy.from_source(approved_but_off)

    def test_a_blocked_source_cannot_be_fetched_from(self) -> None:
        blocked = an_approved_source(
            enabled=False, verification_status=VerificationStatus.BLOCKED, crawler=None
        )
        with pytest.raises(SourceNotCollectableError, match="blocked"):
            AcquisitionPolicy.from_source(blocked)

    def test_a_manual_upload_source_has_nothing_to_fetch(self) -> None:
        uploaded = an_approved_source(
            retrieval=RetrievalMethod.MANUAL_UPLOAD, base_url=None, crawler=None
        )
        with pytest.raises(SourceNotCollectableError, match="no target to fetch"):
            AcquisitionPolicy.from_source(uploaded)

    def test_the_refusal_names_the_source_and_points_at_the_process(self) -> None:
        """An error that says only "not collectable" sends the reader to the source code."""
        with pytest.raises(SourceNotCollectableError) as caught:
            AcquisitionPolicy.from_source(an_approved_source(id="cpwd", enabled=False))

        message = str(caught.value)
        assert "cpwd" in message
        assert "DATA_SOURCES.md" in message

    def test_the_refusal_is_not_an_acquisition_error(self) -> None:
        """Which matters, because the acquirer catches those and records them against a URL.

        If this became an ``AcquisitionError``, "we are not permitted to collect from this portal"
        would be written into a frontier row as a per-URL failure and the run would carry on to the
        next URL of the same forbidden source. It has to stop the run instead.
        """
        error = SourceNotCollectableError("nope")
        assert not isinstance(error, AcquisitionError)


REGISTRY_DIR = Path(__file__).resolve().parents[2] / "config" / "sources"


class TestAgainstTheShippedRegistry:
    """The same rule, applied to the YAML that actually ships.

    Written as an invariant rather than as a snapshot of today's registry, which is the convention
    in ``test_registry_data.py`` and the right one: approving a source should not require editing a
    test. Both branches below are live — every source in the repository is currently unfetchable, so
    the refusal half runs for real, and the policy half is what will check the first approved source
    without anyone remembering to come back here.
    """

    def test_a_policy_exists_for_every_fetchable_source_and_for_no_other(self) -> None:
        for source in load_registry(REGISTRY_DIR):
            has_a_target = source.retrieval is not RetrievalMethod.MANUAL_UPLOAD
            if not (source.is_collectable and has_a_target):
                with pytest.raises(SourceNotCollectableError):
                    AcquisitionPolicy.from_source(source)
                continue

            policy = AcquisitionPolicy.from_source(source)
            assert source.base_url is not None and source.base_url.host is not None
            assert policy.source_id == source.id
            assert policy.host_policy.permits(source.base_url.host)
            assert policy.download.allowed_formats == frozenset(source.file_formats)
            assert policy.limits.requests_per_minute == source.rate_limit.requests_per_minute
