"""Source-registry schema.

Every external data source is declared as data, never as ad-hoc code. A crawler receives
its target, its rate limits, and its legal constraints from a :class:`SourceDefinition`;
it does not embed them.

The schema encodes the project's collection ethics as validation rules, so that an unsafe
source cannot be expressed at all:

* A source cannot be enabled until a human has reviewed its terms
  (``verification_status: approved``) and a crawler exists to handle it.
* A source behind an access control cannot be enabled, ever.
* An HTML-crawling source must declare that it respects ``robots.txt``.
* Plain-HTTP endpoints must opt in explicitly, because evidence fetched over a tamperable
  channel is weak evidence.
* Licence and permitted-use metadata are mandatory fields, not optional documentation.

Rate limits are bounded on both sides: the ceiling protects the remote site, and the floor
(``min_delay_seconds``) prevents a misconfigured burst.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from aedifex.domain.documents import DocumentType
from aedifex.domain.files import FileFormat

__all__ = [
    "AccessLevel",
    "DataUsePolicy",
    "DiscoveryPolicy",
    "RateLimitPolicy",
    "RetrievalMethod",
    "RobotsPolicy",
    "SourceCategory",
    "SourceDefinition",
    "SourceFile",
    "VerificationStatus",
]

_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+\.?$"
)

SourceId = Annotated[
    str,
    Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Stable lower_snake_case identifier; appears in storage paths.",
    ),
]


class SourceCategory(StrEnum):
    GOVERNMENT_PROCUREMENT = "government_procurement"
    MULTILATERAL_PROCUREMENT = "multilateral_procurement"
    OPEN_DATA_STANDARD = "open_data_standard"
    RESEARCH_DATASET = "research_dataset"
    SYNTHETIC = "synthetic"


class RetrievalMethod(StrEnum):
    """How documents are obtained from a source."""

    HTTP_CRAWL = "http_crawl"
    HTTP_API = "http_api"
    BULK_DOWNLOAD = "bulk_download"
    MANUAL_UPLOAD = "manual_upload"


class VerificationStatus(StrEnum):
    """Outcome of the human review of a source's terms of use.

    ``UNVERIFIED`` is the default and deliberately blocks collection: a source is
    presumed off-limits until someone has read its terms and recorded the finding.
    """

    UNVERIFIED = "unverified"
    APPROVED = "approved"
    BLOCKED = "blocked"


class AccessLevel(StrEnum):
    PUBLIC = "public"
    REGISTRATION_REQUIRED = "registration_required"
    RESTRICTED = "restricted"


class RobotsPolicy(StrEnum):
    RESPECT = "respect"
    NOT_APPLICABLE = "not_applicable"


class DataUsePolicy(BaseModel):
    """Licence and permitted-use metadata. Mandatory for every source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    license: str = Field(
        min_length=2,
        max_length=200,
        description="Licence identifier or short description, e.g. 'CC-BY-4.0' or "
        "'Government of India Open Data Licence'.",
    )
    terms_url: AnyHttpUrl | None = Field(
        default=None, description="Where the terms were read from during review."
    )
    access: AccessLevel = AccessLevel.PUBLIC
    allowed_use: str = Field(
        min_length=10,
        max_length=2000,
        description="What the reviewer concluded we may do with this data.",
    )
    attribution_required: bool = True
    contains_personal_data: bool = Field(
        default=False,
        description="Set when the source is known to publish personal data; enables "
        "mandatory PII screening before the corpus is used downstream.",
    )
    reviewed_by: str | None = Field(
        default=None, max_length=200, description="Who reviewed the terms."
    )
    reviewed_on: datetime | None = Field(default=None, description="When terms were reviewed.")

    @field_validator("reviewed_on")
    @classmethod
    def _require_aware_past_datetime(cls, value: datetime | None) -> datetime | None:
        return _validate_aware_past(value, field_name="reviewed_on")


class RateLimitPolicy(BaseModel):
    """Politeness limits applied per source.

    Bounded above so no configuration can turn a crawler into a load generator, and the
    concurrency ceiling is intentionally low: public procurement portals are frequently
    fragile.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    requests_per_minute: int = Field(default=20, ge=1, le=600)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    min_delay_seconds: float = Field(
        default=1.0, ge=0.0, le=300.0, description="Minimum gap between consecutive requests."
    )
    max_documents_per_run: int | None = Field(
        default=None,
        ge=1,
        description="Optional cap per crawl run, to bound the blast radius of a new crawler.",
    )

    @model_validator(mode="after")
    def _check_delay_consistency(self) -> Self:
        # A 60 rpm budget cannot be spent if each request must be 5 seconds apart. Rather
        # than silently letting one limit win, reject the contradiction at load time.
        if self.min_delay_seconds > 0:
            implied_maximum = 60.0 / self.min_delay_seconds
            if self.requests_per_minute > implied_maximum:
                raise ValueError(
                    f"requests_per_minute={self.requests_per_minute} is unreachable with "
                    f"min_delay_seconds={self.min_delay_seconds} "
                    f"(implies at most {implied_maximum:.1f} requests/minute)"
                )
        return self


class DiscoveryPolicy(BaseModel):
    """Where a crawl starts, how far it goes, and which paths it may follow.

    Data rather than code, for the same reason as everything else in this file: a crawl that
    walked further than intended, or into a search endpoint that generates infinite URLs, should be
    fixable by a reviewed configuration change and visible in one place.

    The bounds are not advisory. ``max_depth`` and ``max_pages`` are what stop a crawler that has
    found a calendar widget from following it until the portal stops answering.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed_paths: tuple[str, ...] = Field(
        default=("/",),
        min_length=1,
        description="Absolute paths on the source's own host where discovery begins.",
    )
    max_depth: int = Field(
        default=2, ge=0, le=10, description="Links from a seed. 0 fetches only the seeds."
    )
    max_pages: int = Field(
        default=200,
        ge=1,
        le=100_000,
        description="Listing pages fetched per run, excluding the documents themselves.",
    )
    follow_patterns: tuple[str, ...] = Field(
        default=(),
        description="Regular expressions a path must match to be followed as a listing page. "
        "Empty means any path on a permitted host, which is only safe with a small max_depth.",
    )
    deny_patterns: tuple[str, ...] = Field(
        default=(),
        description="Regular expressions that exclude a path entirely. Checked before "
        "follow_patterns, so a deny always wins.",
    )
    api_post_paths: tuple[str, ...] = Field(
        default=(),
        description="Exact paths on this source that may be requested with POST. Empty means none, "
        "which is the right default: a crawler that can POST anywhere it finds a link can be "
        "pointed at an admin endpoint. Parameter values may come from a remote response; the "
        "endpoint may not. Matched exactly, never by prefix.",
    )

    @field_validator("api_post_paths")
    @classmethod
    def _require_absolute_exact_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Absolute, query-free, and unique.

        Query-free because the path is the thing being authorised and the query carries the form
        body; allowing a query here would make the allowlist look like it constrained parameters
        when it does not.
        """
        for path in value:
            if not path.startswith("/"):
                raise ValueError(f"api_post_path {path!r} must start with '/'")
            if "?" in path or "#" in path:
                raise ValueError(
                    f"api_post_path {path!r} must be a bare path; the query string carries the "
                    f"form body and is not part of what is authorised"
                )
        if len(set(value)) != len(value):
            raise ValueError("api_post_paths entries must be unique")
        return value

    @field_validator("seed_paths")
    @classmethod
    def _require_absolute_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for path in value:
            if not path.startswith("/"):
                raise ValueError(
                    f"seed path {path!r} must start with '/'; it is joined onto base_url"
                )
        return value

    @field_validator("follow_patterns", "deny_patterns")
    @classmethod
    def _require_compilable_patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Compile every pattern at load time.

        A bad regular expression must fail when the registry is validated, not on the first page of
        a crawl — by which point the run has already made requests and has to be unwound.
        """
        for pattern in value:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"pattern {pattern!r} is not a valid regex: {error}") from error
        return value


class SourceDefinition(BaseModel):
    """A single external data source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: SourceId
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    country: str = Field(
        default="XX",
        pattern=r"^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 country code; 'XX' for multinational sources.",
    )
    category: SourceCategory
    retrieval: RetrievalMethod
    base_url: AnyHttpUrl | None = Field(
        default=None,
        description="Entry point for crawling or API access. Optional only for "
        "manual_upload sources.",
    )
    allow_insecure_transport: bool = Field(
        default=False,
        description="Required to be true for plain-HTTP base URLs, so that the weaker "
        "evidence chain is a recorded decision rather than an oversight.",
    )
    robots_policy: RobotsPolicy = RobotsPolicy.RESPECT
    enabled: bool = False
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    crawler: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.]*$",
        description="Registered crawler implementation name.",
    )
    rate_limit: RateLimitPolicy = RateLimitPolicy()
    discovery: DiscoveryPolicy = DiscoveryPolicy()
    data_use: DataUsePolicy
    document_types: tuple[DocumentType, ...] = Field(
        min_length=1, description="Document types this source is expected to yield."
    )
    file_formats: tuple[FileFormat, ...] = Field(
        min_length=1, description="Formats accepted from this source; others are rejected."
    )
    additional_hosts: tuple[str, ...] = Field(
        default=(),
        description="Extra hostnames this source legitimately serves documents from, e.g. a "
        "CDN. Matched exactly, never by subdomain: authorising a shared object-storage domain "
        "by suffix would authorise every other tenant of it. Adding one is a configuration "
        "change and never a relaxation of global network safety.",
    )
    notes: str | None = Field(default=None, max_length=4000)
    last_successful_run: datetime | None = None

    @field_validator("document_types", "file_formats", "additional_hosts")
    @classmethod
    def _reject_duplicates(cls, value: tuple[object, ...]) -> tuple[object, ...]:
        if len(set(value)) != len(value):
            raise ValueError("entries must be unique")
        return value

    @field_validator("additional_hosts")
    @classmethod
    def _validate_additional_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require plain, fully-qualified, lowercase hostnames.

        Wildcards and IP literals are rejected deliberately: a wildcard would reintroduce the
        suffix matching this field exists to avoid, and an IP literal would bypass the hostname
        allowlist that constrains where a source may be fetched from.
        """
        for host in value:
            if host != host.strip().lower():
                raise ValueError(f"host {host!r} must be lowercase and unpadded")
            if "*" in host or "/" in host or ":" in host:
                raise ValueError(f"host {host!r} must be a plain hostname, not a pattern or URL")
            if "." not in host.rstrip("."):
                raise ValueError(f"host {host!r} must be fully qualified")
            if not _HOSTNAME_PATTERN.match(host):
                raise ValueError(f"host {host!r} is not a valid hostname")
            try:
                ipaddress.ip_address(host.rstrip("."))
            except ValueError:
                pass  # Not an address, which is what we require.
            else:
                raise ValueError(
                    f"host {host!r} is an IP address; this field takes hostnames, and an "
                    f"address here would be unreachable anyway because IP-literal URLs are "
                    f"refused by the fetch guard"
                )
        return value

    @field_validator("last_successful_run")
    @classmethod
    def _require_aware_past_datetime(cls, value: datetime | None) -> datetime | None:
        return _validate_aware_past(value, field_name="last_successful_run")

    @model_validator(mode="after")
    def _check_collection_safety(self) -> Self:
        problems: list[str] = []

        if self.retrieval is not RetrievalMethod.MANUAL_UPLOAD and self.base_url is None:
            problems.append(f"base_url is required for retrieval={self.retrieval.value}")

        if self.base_url is not None and self.base_url.scheme == "http":
            if not self.allow_insecure_transport:
                problems.append(
                    "base_url uses plain HTTP; set allow_insecure_transport=true to "
                    "acknowledge that documents may be tampered with in transit"
                )
        elif self.allow_insecure_transport:
            problems.append(
                "allow_insecure_transport is set but base_url is not plain HTTP; remove it"
            )

        if (
            self.retrieval is RetrievalMethod.HTTP_CRAWL
            and self.robots_policy is not RobotsPolicy.RESPECT
        ):
            problems.append("robots_policy must be 'respect' for HTML-crawling sources")

        if self.data_use.access is AccessLevel.RESTRICTED and self.enabled:
            problems.append(
                "a source behind an access control cannot be enabled; collection would "
                "require bypassing that control"
            )

        if self.enabled:
            if self.verification_status is not VerificationStatus.APPROVED:
                problems.append(
                    f"cannot enable a source with verification_status="
                    f"{self.verification_status.value}; its terms of use must be reviewed "
                    f"and recorded first"
                )
            if self.retrieval is not RetrievalMethod.MANUAL_UPLOAD and self.crawler is None:
                problems.append("cannot enable a source with no crawler implementation")

        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def is_collectable(self) -> bool:
        """Whether a crawl run may fetch from this source right now."""
        return self.enabled and self.verification_status is VerificationStatus.APPROVED


class SourceFile(BaseModel):
    """Top-level schema of a registry YAML file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sources: tuple[SourceDefinition, ...] = Field(min_length=1)


def _validate_aware_past(value: datetime | None, *, field_name: str) -> datetime | None:
    """Reject naive datetimes and future timestamps.

    Naive timestamps are ambiguous across deployments, and a future timestamp in this
    field usually means a clock problem or a hand-edited file — either way it would
    corrupt incremental-crawl decisions that compare against it.
    """
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    if value > datetime.now(UTC):
        raise ValueError(f"{field_name} is in the future")
    return value
