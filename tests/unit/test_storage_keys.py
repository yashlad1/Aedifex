"""Tests for the object-storage key layout."""

from __future__ import annotations

import hashlib

import pytest

from aedifex.domain.files import FileFormat
from aedifex.infrastructure.storage.keys import StorageTier, derived_key, raw_key

DIGEST = hashlib.sha256(b"a construction document").hexdigest()


class TestRawKey:
    def test_layout(self) -> None:
        key = raw_key(source_id="cpwd", sha256=DIGEST, file_format=FileFormat.PDF)
        assert key == f"raw/cpwd/{DIGEST[:2]}/{DIGEST[2:4]}/{DIGEST}.pdf"

    def test_is_deterministic(self) -> None:
        """Re-running a crawl must recompute the same key, so a re-download is idempotent."""
        first = raw_key(source_id="cpwd", sha256=DIGEST, file_format=FileFormat.PDF)
        second = raw_key(source_id="cpwd", sha256=DIGEST, file_format=FileFormat.PDF)
        assert first == second

    def test_contains_no_timestamp(self) -> None:
        """Wall-clock partitioning would break idempotency across runs."""
        key = raw_key(source_id="cpwd", sha256=DIGEST, file_format=FileFormat.PDF)
        assert "20" not in key.removeprefix("raw/cpwd/").split("/")[0]

    def test_source_is_part_of_the_prefix(self) -> None:
        """Provenance must be visible in the object layout, not only in the database."""
        assert raw_key(source_id="nhai", sha256=DIGEST, file_format=FileFormat.PDF).startswith(
            "raw/nhai/"
        )

    def test_same_content_from_two_sources_lands_in_two_places(self) -> None:
        """Deliberate: each source's collection remains independently auditable and deletable."""
        first = raw_key(source_id="cpwd", sha256=DIGEST, file_format=FileFormat.PDF)
        second = raw_key(source_id="nhai", sha256=DIGEST, file_format=FileFormat.PDF)
        assert first != second

    def test_canonical_extension_is_used(self) -> None:
        key = raw_key(source_id="cpwd", sha256=DIGEST, file_format=FileFormat.JPEG)
        assert key.endswith(".jpg")

    @pytest.mark.parametrize(
        "source_id",
        ["", "CPWD", "cp-wd", "cp wd", "1cpwd", "../etc", "cpwd/../nhai", "cpwd\x00"],
    )
    def test_malformed_source_ids_are_rejected(self, source_id: str) -> None:
        with pytest.raises(ValueError, match="source_id"):
            raw_key(source_id=source_id, sha256=DIGEST, file_format=FileFormat.PDF)

    @pytest.mark.parametrize(
        "digest",
        ["", "abc", DIGEST.upper(), "g" * 64, DIGEST + "0", "../" + "a" * 61],
    )
    def test_malformed_digests_are_rejected(self, digest: str) -> None:
        with pytest.raises(ValueError, match="sha-256 digest"):
            raw_key(source_id="cpwd", sha256=digest, file_format=FileFormat.PDF)

    def test_no_traversal_is_possible(self) -> None:
        """Both inputs are pattern-validated, so no key can escape its prefix."""
        key = raw_key(source_id="cpwd", sha256=DIGEST, file_format=FileFormat.PDF)
        assert ".." not in key
        assert not key.startswith("/")
        assert key.count("//") == 0


class TestDerivedKey:
    def test_layout(self) -> None:
        key = derived_key(
            tier=StorageTier.PROCESSED, sha256=DIGEST, stage="pdf_text", extension="txt"
        )
        assert key == f"processed/pdf_text/{DIGEST[:2]}/{DIGEST[2:4]}/{DIGEST}.txt"

    def test_is_keyed_by_the_raw_digest(self) -> None:
        """Every derived artifact must be traceable to the exact bytes it came from."""
        key = derived_key(tier=StorageTier.NORMALIZED, sha256=DIGEST, stage="ocr", extension="json")
        assert DIGEST in key

    def test_writing_to_the_raw_tier_is_refused(self) -> None:
        """Raw bytes are write-once; derived output must not be able to overwrite its input."""
        with pytest.raises(ValueError, match="immutable raw tier"):
            derived_key(tier=StorageTier.RAW, sha256=DIGEST, stage="ocr", extension="json")

    def test_extension_accepts_either_spelling(self) -> None:
        with_dot = derived_key(
            tier=StorageTier.PROCESSED, sha256=DIGEST, stage="ocr", extension=".json"
        )
        without_dot = derived_key(
            tier=StorageTier.PROCESSED, sha256=DIGEST, stage="ocr", extension="json"
        )
        assert with_dot == without_dot

    @pytest.mark.parametrize("stage", ["", "PDF_TEXT", "pdf-text", "pdf text", "../ocr", "1stage"])
    def test_malformed_stages_are_rejected(self, stage: str) -> None:
        with pytest.raises(ValueError, match="stage"):
            derived_key(tier=StorageTier.PROCESSED, sha256=DIGEST, stage=stage, extension="txt")

    @pytest.mark.parametrize("extension", ["", ".", "../x", "tar.gz", "t xt", "js/on"])
    def test_malformed_extensions_are_rejected(self, extension: str) -> None:
        with pytest.raises(ValueError, match="extension"):
            derived_key(tier=StorageTier.PROCESSED, sha256=DIGEST, stage="ocr", extension=extension)

    def test_tiers_do_not_collide(self) -> None:
        keys = {
            derived_key(tier=tier, sha256=DIGEST, stage="ocr", extension="json")
            for tier in StorageTier
            if tier is not StorageTier.RAW
        }
        assert len(keys) == len(StorageTier) - 1
