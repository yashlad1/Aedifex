"""Tests for the source-registry loader.

Emphasis on error reporting. A registry mistake is a configuration bug that could point a
crawler at the wrong host, so the loader must say exactly which file and which source is
wrong, and must report every problem at once rather than one per run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aedifex.acquisition.registry import load_registry
from aedifex.errors import SourceRegistryError


def write(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


class TestLoading:
    def test_loads_a_valid_file(self, registry_dir: Path, valid_source_yaml: str) -> None:
        write(registry_dir, "sources.yaml", valid_source_yaml)
        registry = load_registry(registry_dir)
        assert len(registry) == 1
        assert registry.get("example_portal").name == "Example Procurement Portal"

    def test_merges_multiple_files(self, registry_dir: Path, valid_source_yaml: str) -> None:
        write(registry_dir, "a.yaml", valid_source_yaml)
        write(registry_dir, "b.yml", valid_source_yaml.replace("example_portal", "other_portal"))
        assert len(load_registry(registry_dir)) == 2

    def test_accepts_both_yaml_extensions(self, registry_dir: Path, valid_source_yaml: str) -> None:
        write(registry_dir, "a.yml", valid_source_yaml)
        assert len(load_registry(registry_dir)) == 1

    def test_ignores_unrelated_files(self, registry_dir: Path, valid_source_yaml: str) -> None:
        write(registry_dir, "sources.yaml", valid_source_yaml)
        write(registry_dir, "README.md", "not a registry file")
        write(registry_dir, "notes.txt", "also not one")
        assert len(load_registry(registry_dir)) == 1

    def test_ordering_is_deterministic(self, registry_dir: Path, valid_source_yaml: str) -> None:
        """Load order must not depend on filesystem iteration order."""
        for index in range(5):
            write(
                registry_dir,
                f"file_{index}.yaml",
                valid_source_yaml.replace("example_portal", f"portal_{index}"),
            )
        first = [source.id for source in load_registry(registry_dir)]
        second = [source.id for source in load_registry(registry_dir)]
        assert first == second == sorted(first)


class TestContainerBehaviour:
    @pytest.fixture
    def registry(self, registry_dir: Path, valid_source_yaml: str) -> Path:
        write(registry_dir, "a.yaml", valid_source_yaml)
        write(registry_dir, "b.yaml", valid_source_yaml.replace("example_portal", "another"))
        return registry_dir

    def test_membership(self, registry: Path) -> None:
        loaded = load_registry(registry)
        assert "example_portal" in loaded
        assert "nonexistent" not in loaded

    def test_iteration_yields_every_source(self, registry: Path) -> None:
        assert {source.id for source in load_registry(registry)} == {"example_portal", "another"}

    def test_collectable_excludes_unverified_sources(self, registry: Path) -> None:
        assert load_registry(registry).collectable() == ()

    def test_unknown_source_error_lists_what_is_available(self, registry: Path) -> None:
        with pytest.raises(SourceRegistryError, match="unknown source 'nope'") as error:
            load_registry(registry).get("nope")
        assert "example_portal" in str(error.value)


class TestDirectoryProblems:
    def test_missing_directory(self, tmp_path: Path) -> None:
        with pytest.raises(SourceRegistryError, match="does not exist"):
            load_registry(tmp_path / "absent")

    def test_empty_directory(self, registry_dir: Path) -> None:
        """An empty registry is a deployment bug, not a valid state of zero sources."""
        with pytest.raises(SourceRegistryError, match="no source definitions found"):
            load_registry(registry_dir)

    def test_path_that_is_a_file(self, tmp_path: Path) -> None:
        path = tmp_path / "sources.yaml"
        path.write_text("sources: []", encoding="utf-8")
        with pytest.raises(SourceRegistryError, match="does not exist"):
            load_registry(path)


class TestFileProblems:
    def test_malformed_yaml_names_the_file(self, registry_dir: Path) -> None:
        write(registry_dir, "broken.yaml", "sources: [\n  - id: x\n    name: 'unclosed")
        with pytest.raises(SourceRegistryError, match=r"broken\.yaml") as error:
            load_registry(registry_dir)
        assert "not valid YAML" in str(error.value)

    def test_empty_file(self, registry_dir: Path) -> None:
        write(registry_dir, "empty.yaml", "")
        with pytest.raises(SourceRegistryError, match=r"empty\.yaml: is empty"):
            load_registry(registry_dir)

    def test_top_level_list_is_rejected(self, registry_dir: Path) -> None:
        write(registry_dir, "list.yaml", "- id: x\n- id: y\n")
        with pytest.raises(SourceRegistryError, match="must contain a mapping"):
            load_registry(registry_dir)

    def test_missing_sources_key(self, registry_dir: Path) -> None:
        write(registry_dir, "wrong.yaml", "source:\n  - id: x\n")
        with pytest.raises(SourceRegistryError, match=r"wrong\.yaml"):
            load_registry(registry_dir)

    def test_empty_sources_list_is_rejected(self, registry_dir: Path) -> None:
        write(registry_dir, "none.yaml", "sources: []\n")
        with pytest.raises(SourceRegistryError, match=r"none\.yaml"):
            load_registry(registry_dir)

    def test_yaml_object_construction_is_not_possible(self, registry_dir: Path) -> None:
        """safe_load only: a registry file must never be able to construct arbitrary objects."""
        write(
            registry_dir,
            "evil.yaml",
            "sources: !!python/object/apply:os.system ['echo pwned']\n",
        )
        with pytest.raises(SourceRegistryError, match="not valid YAML"):
            load_registry(registry_dir)

    def test_invalid_utf8_is_reported(self, registry_dir: Path) -> None:
        (registry_dir / "bad.yaml").write_bytes(b"sources:\n  - id: \xff\xfe\n")
        with pytest.raises(SourceRegistryError, match=r"bad\.yaml"):
            load_registry(registry_dir)


class TestErrorReporting:
    def test_duplicate_ids_across_files_name_both_files(
        self, registry_dir: Path, valid_source_yaml: str
    ) -> None:
        """The same id in two files would make crawl state ambiguous."""
        write(registry_dir, "a_first.yaml", valid_source_yaml)
        write(registry_dir, "b_second.yaml", valid_source_yaml)
        with pytest.raises(SourceRegistryError) as error:
            load_registry(registry_dir)
        message = str(error.value)
        assert "duplicate source id 'example_portal'" in message
        assert "a_first.yaml" in message
        assert "b_second.yaml" in message

    def test_duplicate_ids_within_one_file(
        self, registry_dir: Path, valid_source_yaml: str
    ) -> None:
        doubled = valid_source_yaml + valid_source_yaml.split("sources:")[1]
        write(registry_dir, "dupes.yaml", doubled)
        with pytest.raises(SourceRegistryError, match="duplicate source id"):
            load_registry(registry_dir)

    def test_validation_error_names_the_offending_source_by_id(self, registry_dir: Path) -> None:
        write(
            registry_dir,
            "bad.yaml",
            """
sources:
  - id: good_portal
    name: Good Portal
    category: government_procurement
    retrieval: http_api
    base_url: https://good.test/
    robots_policy: not_applicable
    data_use:
      license: CC-BY-4.0
      allowed_use: Redistribution permitted with attribution.
    document_types: [tender_notice]
    file_formats: [pdf]
  - id: bad_portal
    name: Bad Portal
    category: government_procurement
    retrieval: http_api
    base_url: https://bad.test/
    robots_policy: not_applicable
    enabled: true
    data_use:
      license: CC-BY-4.0
      allowed_use: Redistribution permitted with attribution.
    document_types: [tender_notice]
    file_formats: [pdf]
""",
        )
        with pytest.raises(SourceRegistryError) as error:
            load_registry(registry_dir)
        assert "bad_portal" in str(error.value)
        assert "good_portal" not in str(error.value)

    def test_all_problems_are_reported_at_once(self, registry_dir: Path) -> None:
        """Fixing a registry one exception per run is unusable."""
        write(registry_dir, "a.yaml", "sources:\n  - id: 'BAD ID'\n")
        write(registry_dir, "b.yaml", "")
        write(registry_dir, "c.yaml", "- not a mapping\n")
        with pytest.raises(SourceRegistryError) as error:
            load_registry(registry_dir)
        message = str(error.value)
        assert "a.yaml" in message
        assert "b.yaml" in message
        assert "c.yaml" in message
        # a.yaml alone yields several field errors, so the total exceeds the file count; the
        # contract is that every problem is listed and the reported count matches the list.
        bullets = [line for line in message.splitlines() if line.strip().startswith("- ")]
        assert len(bullets) >= 3
        assert f"{len(bullets)} problem(s)" in message

    def test_problem_count_is_reported(self, registry_dir: Path) -> None:
        write(registry_dir, "a.yaml", "")
        with pytest.raises(SourceRegistryError, match=r"1 problem\(s\)"):
            load_registry(registry_dir)


class TestCrawlerRegistration:
    ENABLED_SOURCE = """
sources:
  - id: live_portal
    name: Live Portal
    category: government_procurement
    retrieval: http_crawl
    base_url: https://live.test/
    enabled: true
    verification_status: approved
    crawler: live_crawler
    data_use:
      license: CC-BY-4.0
      access: public
      allowed_use: Redistribution permitted with attribution.
      reviewed_by: a reviewer
    document_types: [tender_notice]
    file_formats: [pdf]
"""

    def test_enabled_source_with_a_registered_crawler_loads(self, registry_dir: Path) -> None:
        write(registry_dir, "live.yaml", self.ENABLED_SOURCE)
        registry = load_registry(registry_dir, known_crawlers={"live_crawler"})
        assert len(registry.collectable()) == 1

    def test_enabled_source_with_an_unregistered_crawler_is_rejected(
        self, registry_dir: Path
    ) -> None:
        """Otherwise a crawl run fails at dispatch time instead of at configuration time."""
        write(registry_dir, "live.yaml", self.ENABLED_SOURCE)
        with pytest.raises(SourceRegistryError, match="not registered"):
            load_registry(registry_dir, known_crawlers={"some_other_crawler"})

    def test_the_check_is_skipped_when_crawlers_are_not_supplied(self, registry_dir: Path) -> None:
        """The read-only API only needs metadata and must not require the crawler package."""
        write(registry_dir, "live.yaml", self.ENABLED_SOURCE)
        assert len(load_registry(registry_dir)) == 1

    def test_disabled_source_with_an_unknown_crawler_is_tolerated(self, registry_dir: Path) -> None:
        """Naming a not-yet-written crawler on a disabled source is normal in-progress work."""
        write(
            registry_dir,
            "live.yaml",
            self.ENABLED_SOURCE.replace("enabled: true", "enabled: false"),
        )
        assert len(load_registry(registry_dir, known_crawlers=set())) == 1
