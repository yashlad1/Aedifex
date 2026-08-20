"""Exception hierarchy.

Every failure mode this project raises deliberately descends from :class:`AedifexError`,
so callers can distinguish "our code rejected this input" from "a dependency blew up".
Errors are never swallowed to make a code path succeed; unrecoverable inputs are
quarantined with the reason recorded (see ``docs/requirements/non-functional.md``).
"""

from __future__ import annotations

__all__ = [
    "AcquisitionError",
    "AedifexError",
    "ConfigurationError",
    "ExtractionError",
    "InvalidStateTransitionError",
    "SourceNotCollectableError",
    "SourceRegistryError",
    "UnsafeContentError",
]


class AedifexError(Exception):
    """Base class for all errors raised by this project."""


class ConfigurationError(AedifexError):
    """Configuration is absent, malformed, or unsafe for the target environment."""


class SourceRegistryError(ConfigurationError):
    """A source-registry definition is invalid or the registry is inconsistent."""


class SourceNotCollectableError(ConfigurationError):
    """A fetch policy was requested for a source that may not be collected from.

    Distinct from :class:`SourceRegistryError`: the definition is perfectly valid, and what it
    says is *no*. Either nobody has reviewed the source's terms yet, or it is disabled, or it
    is a manual-upload source with nothing to fetch.

    A configuration error rather than an acquisition one, and deliberately not a subclass of
    :class:`AcquisitionError`: the acquirer catches those and records them against a URL, which
    would turn "we are not permitted to collect from this portal" into a per-URL failure row.
    This should stop a run.
    """


class AcquisitionError(AedifexError):
    """A document could not be discovered, downloaded, or validated."""


class UnsafeContentError(AcquisitionError):
    """Remote content violated a safety limit and was rejected.

    Raised for oversized payloads, disallowed media types, and filenames that attempt
    path traversal. Carrying its own type means these events can be counted and alerted
    on separately from ordinary transport failures.
    """


class ExtractionError(AedifexError):
    """A document could not be turned into text or facts.

    Distinct from :class:`AcquisitionError`: the bytes arrived intact and are still valid evidence.
    What failed is our reading of them, which is our problem and not the source's. Raising this
    never invalidates a stored object or its provenance.
    """


class InvalidStateTransitionError(AedifexError):
    """An attempt was made to move a document into a state it cannot reach."""
