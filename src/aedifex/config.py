"""Typed application configuration.

Configuration is read from the environment (and an optional ``.env`` file for local
development) and validated once at process start. Nothing in this project may read
``os.environ`` directly; everything goes through :func:`get_settings` so that the set of
knobs a deployment exposes is discoverable in one place.

Security notes:

* Secrets are typed as :class:`~pydantic.SecretStr` so they do not leak into ``repr``,
  logs, or exception tracebacks.
* :meth:`Settings.safe_database_url` masks the password for log lines.
* Production deployments are rejected outright if they still carry development
  placeholder credentials. A misconfigured production process should fail to boot rather
  than run with a well-known password.
"""

from __future__ import annotations

import os
import re
import tempfile
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Environment", "LogFormat", "Settings", "get_settings"]

# Credentials that ship in docker-compose and .env.example. Harmless locally, fatal in
# production.
#
# Matched as whole values, case-insensitively, against the username and password components
# of a DSN — never as substrings of the whole URL. Substring matching was tried first and was
# wrong: "postgres" appears in the driver scheme "postgresql+psycopg", so every conceivable
# production DSN was rejected.
_PLACEHOLDER_CREDENTIALS: Final[frozenset[str]] = frozenset(
    {
        "postgres",
        "password",
        "passw0rd",
        "changeme",
        "minioadmin",
        "admin",
        "root",
        "secret",
        "test",
    }
)

# Placeholder markers matched as substrings, for free-text fields where that is safe.
_PLACEHOLDER_TOKENS: Final[frozenset[str]] = frozenset({"example.invalid", "changeme"})

# Bucket names used by the local development stack.
_DEVELOPMENT_BUCKETS: Final[frozenset[str]] = frozenset({"aedifex-dev", "aedifex-test"})

# A polite crawler identifies itself and offers a way to be contacted. Enforced here
# rather than in the crawler so that no deployment can quietly become anonymous traffic.
_CONTACTABLE_USER_AGENT: Final[re.Pattern[str]] = re.compile(r"(https?://|mailto:|@)")


class Environment(StrEnum):
    """Deployment environment. Drives validation strictness, not feature behaviour."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    """Validated process configuration.

    Every field is settable as ``AEDIFEX_<FIELD_NAME>``; nested models use a double
    underscore (``AEDIFEX_STORAGE__BUCKET``).
    """

    model_config = SettingsConfigDict(
        env_prefix="AEDIFEX_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        # Unknown AEDIFEX_* variables are a configuration bug (usually a typo in a
        # deployment manifest), not something to silently ignore.
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    # --- Persistence ------------------------------------------------------------
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://postgres:postgres@localhost:5432/aedifex"),
        description="SQLAlchemy-compatible PostgreSQL DSN.",
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_statement_timeout_seconds: int = Field(default=30, ge=1, le=600)

    # --- Object storage ---------------------------------------------------------
    storage_bucket: str = Field(default="aedifex-dev", min_length=3, max_length=63)
    storage_region: str = "us-east-1"
    storage_endpoint_url: str | None = Field(
        default=None,
        description="S3-compatible endpoint. Set for MinIO; leave unset for AWS S3.",
    )
    storage_access_key_id: SecretStr | None = None
    storage_secret_access_key: SecretStr | None = None

    # --- Source registry --------------------------------------------------------
    source_registry_dir: str = Field(
        default="config/sources",
        description="Directory of YAML source-definition files.",
    )

    # --- Acquisition safety limits ----------------------------------------------
    # These are hard ceilings applied to untrusted remote content (see SECURITY.md).
    max_download_bytes: int = Field(default=256 * 1024 * 1024, ge=1024, le=2 * 1024**30)
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    max_global_concurrency: int = Field(
        default=8,
        ge=1,
        le=64,
        description=(
            "Ceiling on in-flight outbound requests across all sources combined. Per-source "
            "limits come from each source's registry entry; this bounds the total, so enabling "
            "twenty sources cannot multiply into twenty simultaneous crawls."
        ),
    )
    staging_dir: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "aedifex-staging"),
        description=(
            "Where partial downloads are written before they are hashed and uploaded. Needs room "
            "for max_download_bytes per concurrent worker, and should be on the same filesystem "
            "for the whole run so the atomic rename into place stays atomic."
        ),
    )
    user_agent: str = Field(
        default="AedifexBot/0.1 (+https://example.invalid/bot; contact: ops@example.invalid)",
        min_length=10,
        max_length=256,
    )

    # --- Observability ----------------------------------------------------------
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        normalized = value.upper()
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return normalized

    @field_validator("user_agent")
    @classmethod
    def _validate_user_agent_is_contactable(cls, value: str) -> str:
        if not _CONTACTABLE_USER_AGENT.search(value):
            raise ValueError(
                "user_agent must include a contact URL or email so that site operators "
                "can reach us about crawler traffic"
            )
        return value

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_environment_variables(cls, values: Any) -> Any:
        """Fail on ``AEDIFEX_*`` variables that match no field.

        pydantic-settings ignores unrecognised environment variables, so a typo such as
        ``AEDIFEX_DATABSE_URL`` would silently leave the default in place — exactly the kind
        of misconfiguration that is discovered in production. ``extra="forbid"`` does not
        cover this, because unknown variables are never collected into the model in the
        first place.
        """
        prefix = "AEDIFEX_"
        known = {f"{prefix}{name}".upper() for name in cls.model_fields}
        unknown = sorted(
            name
            for name in os.environ
            if name.upper().startswith(prefix)
            # Compare only the first segment so nested settings (AEDIFEX_FOO__BAR) resolve
            # against their parent field.
            and f"{prefix}{name.upper().removeprefix(prefix).split('__', 1)[0]}" not in known
        )
        if unknown:
            expected = ", ".join(sorted(f"{prefix}{name}".upper() for name in cls.model_fields))
            raise ValueError(
                f"unknown environment variable(s): {', '.join(unknown)}. "
                f"Recognised settings are: {expected}"
            )
        return values

    @model_validator(mode="after")
    def _enforce_production_hardening(self) -> Settings:
        if self.environment is not Environment.PRODUCTION:
            return self

        problems: list[str] = []
        if self.debug:
            problems.append("debug must be disabled in production")

        for component in _placeholder_dsn_components(self.database_url):
            problems.append(f"database_url {component} is a development placeholder credential")
        if self.storage_bucket.lower() in _DEVELOPMENT_BUCKETS:
            problems.append(
                f"storage_bucket {self.storage_bucket!r} is the development bucket name"
            )
        if _contains_placeholder_token(self.user_agent):
            problems.append("user_agent still contains a placeholder contact address")

        for name in ("storage_access_key_id", "storage_secret_access_key"):
            secret: SecretStr | None = getattr(self, name)
            if secret is None:
                continue
            value = secret.get_secret_value()
            if value.lower() in _PLACEHOLDER_CREDENTIALS or _contains_placeholder_token(value):
                problems.append(f"{name} is a development placeholder credential")

        if problems:
            raise ValueError("invalid production configuration: " + "; ".join(problems))
        return self

    def safe_database_url(self) -> str:
        """Return the database DSN with every password masked, for logging."""
        url = str(self.database_url)
        for host in self.database_url.hosts():
            password = host.get("password")
            if password:
                url = url.replace(f":{password}@", ":***@")
        return url


def _placeholder_dsn_components(dsn: PostgresDsn) -> list[str]:
    """Return the names of DSN credential components that are known placeholders."""
    found: list[str] = []
    for host in dsn.hosts():
        for component in ("username", "password"):
            value = host.get(component)
            if isinstance(value, str) and value.lower() in _PLACEHOLDER_CREDENTIALS:
                found.append(component)
    return found


def _contains_placeholder_token(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in _PLACEHOLDER_TOKENS)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed and validated once.

    Tests that need a different configuration should build :class:`Settings` directly
    rather than mutating the cache.
    """
    return Settings()
