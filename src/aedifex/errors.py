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
    "InvalidStateTransitionError",
    "SourceRegistryError",
    "UnsafeContentError",
]


class AedifexError(Exception):
    """Base class for all errors raised by this project."""


class ConfigurationError(AedifexError):
    """Configuration is absent, malformed, or unsafe for the target environment."""


class SourceRegistryError(ConfigurationError):
    """A source-registry definition is invalid or the registry is inconsistent."""


class AcquisitionError(AedifexError):
    """A document could not be discovered, downloaded, or validated."""


class UnsafeContentError(AcquisitionError):
    """Remote content violated a safety limit and was rejected.

    Raised for oversized payloads, disallowed media types, and filenames that attempt
    path traversal. Carrying its own type means these events can be counted and alerted
    on separately from ordinary transport failures.
    """


class InvalidStateTransitionError(AedifexError):
    """An attempt was made to move a document into a state it cannot reach."""
