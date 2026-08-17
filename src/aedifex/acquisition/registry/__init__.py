"""Source registry: declarative definitions of every external data source."""

from __future__ import annotations

from aedifex.acquisition.registry.loader import SourceRegistry, get_registry, load_registry
from aedifex.acquisition.registry.models import (
    AccessLevel,
    DataUsePolicy,
    RateLimitPolicy,
    RetrievalMethod,
    RobotsPolicy,
    SourceCategory,
    SourceDefinition,
    SourceFile,
    VerificationStatus,
)

__all__ = [
    "AccessLevel",
    "DataUsePolicy",
    "RateLimitPolicy",
    "RetrievalMethod",
    "RobotsPolicy",
    "SourceCategory",
    "SourceDefinition",
    "SourceFile",
    "SourceRegistry",
    "VerificationStatus",
    "get_registry",
    "load_registry",
]
