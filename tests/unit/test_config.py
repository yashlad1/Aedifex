"""Tests for typed configuration and production hardening."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from aedifex.config import Environment, LogFormat, Settings, get_settings


class TestDefaults:
    def test_defaults_are_development_safe(self) -> None:
        settings = Settings()
        assert settings.environment is Environment.DEVELOPMENT
        assert settings.debug is False
        assert settings.log_format is LogFormat.JSON

    def test_reads_from_environment_with_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AEDIFEX_ENVIRONMENT", "staging")
        monkeypatch.setenv("AEDIFEX_STORAGE_BUCKET", "corpus-staging")
        settings = Settings()
        assert settings.environment is Environment.STAGING
        assert settings.storage_bucket == "corpus-staging"

    def test_unknown_setting_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A typo in a deployment manifest must fail loudly, not be ignored."""
        monkeypatch.setenv("AEDIFEX_DATABSE_URL", "postgresql://x/y")
        with pytest.raises(ValidationError, match="AEDIFEX_DATABSE_URL"):
            Settings()

    def test_known_nested_prefix_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The unknown-variable check must not reject a valid field name outright."""
        monkeypatch.setenv("AEDIFEX_STORAGE_BUCKET", "corpus")
        assert Settings().storage_bucket == "corpus"

    def test_get_settings_is_cached(self) -> None:
        assert get_settings() is get_settings()


class TestValidation:
    def test_log_level_is_normalized(self) -> None:
        assert Settings(log_level="debug").log_level == "DEBUG"

    def test_invalid_log_level_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="log_level must be one of"):
            Settings(log_level="verbose")

    @pytest.mark.parametrize(
        "user_agent",
        [
            "AedifexBot/0.1 (+https://aedifex.example/bot)",
            "AedifexBot/0.1 (contact: ops@aedifex.example)",
            "AedifexBot/0.1 (mailto:ops@aedifex.example)",
        ],
    )
    def test_contactable_user_agents_are_accepted(self, user_agent: str) -> None:
        assert Settings(user_agent=user_agent).user_agent == user_agent

    def test_anonymous_user_agent_is_rejected(self) -> None:
        """Crawler traffic must be attributable to us and give operators a way to complain."""
        with pytest.raises(ValidationError, match="contact URL or email"):
            Settings(user_agent="Mozilla/5.0 compatible")

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("max_download_bytes", 0),
            ("max_download_bytes", -1),
            ("request_timeout_seconds", 0),
            ("request_timeout_seconds", -5),
            ("database_pool_size", 0),
            ("database_pool_size", 100),
            ("database_statement_timeout_seconds", 0),
        ],
    )
    def test_out_of_range_limits_are_rejected(self, field: str, value: int) -> None:
        with pytest.raises(ValidationError):
            Settings(**{field: value})  # type: ignore[arg-type]

    def test_frozen_settings_cannot_be_mutated(self) -> None:
        """Configuration must not drift at runtime; a mutable singleton invites that."""
        settings = Settings()
        with pytest.raises(ValidationError):
            settings.debug = True  # type: ignore[misc]


class TestProductionHardening:
    """Production must refuse to boot with development credentials.

    These checks exist because the compose stack and .env.example ship well-known
    passwords. Failing to start is strictly better than serving with `postgres:postgres`.
    """

    def test_default_database_url_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="development placeholder"):
            Settings(environment=Environment.PRODUCTION)

    def test_default_bucket_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="development bucket"):
            Settings(
                environment=Environment.PRODUCTION,
                database_url="postgresql+psycopg://svc:s3cr3t-Xk9@db.internal:5432/aedifex",  # type: ignore[arg-type]
                user_agent="AedifexBot/1.0 (+https://aedifex.example/bot)",
            )

    def test_placeholder_user_agent_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="placeholder contact"):
            Settings(
                environment=Environment.PRODUCTION,
                database_url="postgresql+psycopg://svc:s3cr3t-Xk9@db.internal:5432/aedifex",  # type: ignore[arg-type]
                storage_bucket="aedifex-corpus-prod",
            )

    def test_placeholder_storage_secret_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="storage_secret_access_key"):
            Settings(
                environment=Environment.PRODUCTION,
                database_url="postgresql+psycopg://svc:s3cr3t-Xk9@db.internal:5432/aedifex",  # type: ignore[arg-type]
                storage_bucket="aedifex-corpus-prod",
                user_agent="AedifexBot/1.0 (+https://aedifex.example/bot)",
                storage_secret_access_key=SecretStr("minioadmin"),
            )

    def test_debug_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="debug must be disabled"):
            Settings(
                environment=Environment.PRODUCTION,
                debug=True,
                database_url="postgresql+psycopg://svc:s3cr3t-Xk9@db.internal:5432/aedifex",  # type: ignore[arg-type]
                storage_bucket="aedifex-corpus-prod",
                user_agent="AedifexBot/1.0 (+https://aedifex.example/bot)",
            )

    def test_valid_production_configuration_is_accepted(self) -> None:
        settings = Settings(
            environment=Environment.PRODUCTION,
            database_url="postgresql+psycopg://svc:s3cr3t-Xk9@db.internal:5432/aedifex",  # type: ignore[arg-type]
            storage_bucket="aedifex-corpus-prod",
            user_agent="AedifexBot/1.0 (+https://aedifex.example/bot)",
        )
        assert settings.environment is Environment.PRODUCTION

    def test_development_placeholders_are_fine_outside_production(self) -> None:
        for environment in (Environment.DEVELOPMENT, Environment.TEST, Environment.STAGING):
            assert Settings(environment=environment).environment is environment


class TestSecretHandling:
    def test_secrets_are_not_exposed_in_repr(self) -> None:
        settings = Settings(storage_secret_access_key=SecretStr("super-secret-value"))
        assert "super-secret-value" not in repr(settings)
        assert settings.storage_secret_access_key is not None
        assert settings.storage_secret_access_key.get_secret_value() == "super-secret-value"

    def test_safe_database_url_masks_the_password(self) -> None:
        settings = Settings(
            database_url="postgresql+psycopg://svc:hunter2@db.internal:5432/aedifex"  # type: ignore[arg-type]
        )
        safe = settings.safe_database_url()
        assert "hunter2" not in safe
        assert "***" in safe
        assert "db.internal:5432" in safe

    def test_safe_database_url_without_password_is_unchanged(self) -> None:
        settings = Settings(
            database_url="postgresql+psycopg://svc@db.internal:5432/aedifex"  # type: ignore[arg-type]
        )
        assert "***" not in settings.safe_database_url()
