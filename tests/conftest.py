"""Shared test fixtures.

Two rules this file enforces:

* **No ambient environment.** ``AEDIFEX_*`` variables from the developer's shell are cleared
  for every test, so a passing suite locally means a passing suite in CI.
* **No shared cached state.** ``get_settings`` and the registry loader are
  ``lru_cache``-backed; the caches are cleared between tests so ordering cannot affect
  outcomes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from aedifex.acquisition.registry import loader as registry_loader
from aedifex.config import Environment, Settings, get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove ambient AEDIFEX_* variables and clear cached singletons."""
    for name in [key for key in os.environ if key.startswith("AEDIFEX_")]:
        monkeypatch.delenv(name, raising=False)

    get_settings.cache_clear()
    registry_loader._cached_registry.cache_clear()
    yield
    get_settings.cache_clear()
    registry_loader._cached_registry.cache_clear()


@pytest.fixture
def test_settings() -> Settings:
    """Settings for a test run, pointing at the repository's own registry."""
    return Settings(
        environment=Environment.TEST,
        source_registry_dir=str(PROJECT_ROOT / "config" / "sources"),
    )


@pytest.fixture
def registry_dir(tmp_path: Path) -> Path:
    """An empty directory for building throwaway registry files."""
    directory = tmp_path / "sources"
    directory.mkdir()
    return directory


@pytest.fixture
def valid_source_yaml() -> str:
    """A minimal, valid source definition, used as the base for mutation tests."""
    return """
sources:
  - id: example_portal
    name: Example Procurement Portal
    country: IN
    category: government_procurement
    retrieval: http_crawl
    base_url: https://example.test/
    enabled: false
    verification_status: unverified
    data_use:
      license: CC-BY-4.0
      access: public
      allowed_use: Redistribution permitted with attribution.
    document_types: [tender_notice]
    file_formats: [pdf]
"""
