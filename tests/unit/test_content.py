"""Tests for content identity and untrusted-content validation.

The format-resolution tests carry the most weight here: they encode what the pipeline does
when a remote server lies about what it is sending, which is the difference between storing
a construction document and storing a session-expiry page.
"""

from __future__ import annotations

import hashlib
import io
import uuid

import pytest

from aedifex.acquisition.content import (
    DOCUMENT_ID_NAMESPACE,
    ContentAccumulator,
    ContentIdentity,
    digests_are_distinct,
    document_id_for_digest,
    hash_bytes,
    hash_stream,
    resolve_format,
    safe_filename,
)
from aedifex.domain.files import FileFormat
from aedifex.errors import UnsafeContentError

PDF_PAYLOAD = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
ZIP_PAYLOAD = b"PK\x03\x04\x14\x00\x00\x00\x08\x00fake-archive-body"
ALL_FORMATS = frozenset(FileFormat)


class TestDocumentIdNamespace:
    def test_namespace_matches_its_documented_derivation(self) -> None:
        """The pinned literal must equal the derivation recorded next to it.

        Document ids are persisted primary keys. If this namespace ever changed, every
        future ingest would produce a different id for content already in the corpus, and
        deduplication would silently stop working.
        """
        assert (
            uuid.uuid5(uuid.NAMESPACE_URL, "https://aedifex.dev/ns/document")
            == DOCUMENT_ID_NAMESPACE
        )

    def test_document_id_is_deterministic(self) -> None:
        digest = hashlib.sha256(b"anything").hexdigest()
        assert document_id_for_digest(digest) == document_id_for_digest(digest)

    def test_different_content_yields_different_ids(self) -> None:
        first = document_id_for_digest(hashlib.sha256(b"a").hexdigest())
        second = document_id_for_digest(hashlib.sha256(b"b").hexdigest())
        assert first != second

    def test_id_is_a_uuid5(self) -> None:
        identifier = document_id_for_digest(hashlib.sha256(b"x").hexdigest())
        assert identifier.version == 5

    @pytest.mark.parametrize(
        "invalid",
        [
            "",
            "abc",
            "A" * 64,
            "g" * 64,
            hashlib.sha256(b"x").hexdigest().upper(),
            hashlib.sha256(b"x").hexdigest() + "0",
        ],
    )
    def test_malformed_digests_are_rejected(self, invalid: str) -> None:
        with pytest.raises(ValueError, match="sha-256 digest"):
            document_id_for_digest(invalid)


class TestHashing:
    def test_matches_hashlib(self) -> None:
        identity = hash_bytes(PDF_PAYLOAD, max_bytes=1024)
        assert identity.sha256 == hashlib.sha256(PDF_PAYLOAD).hexdigest()

    def test_records_size_and_derived_id(self) -> None:
        identity = hash_bytes(PDF_PAYLOAD, max_bytes=1024)
        assert identity.size_bytes == len(PDF_PAYLOAD)
        assert identity.document_id == document_id_for_digest(identity.sha256)

    def test_sniffs_the_format_while_hashing(self) -> None:
        """One pass over the stream must yield both identity and format confirmation."""
        assert hash_bytes(PDF_PAYLOAD, max_bytes=1024).sniffed_format is FileFormat.PDF

    def test_text_payload_has_no_confirmed_format(self) -> None:
        assert hash_bytes(b'{"a": 1}', max_bytes=1024).sniffed_format is None

    def test_identical_content_produces_identical_identity(self) -> None:
        first = hash_bytes(PDF_PAYLOAD, max_bytes=1024)
        second = hash_bytes(PDF_PAYLOAD, max_bytes=1024)
        assert first == second

    def test_sniffing_works_across_chunk_boundaries(self) -> None:
        """The prefix is accumulated across reads, so a dribbling stream still sniffs."""

        class DribblingStream(io.RawIOBase):
            def __init__(self, payload: bytes) -> None:
                self._payload = payload
                self._position = 0

            def read(self, size: int = -1) -> bytes:
                if self._position >= len(self._payload):
                    return b""
                chunk = self._payload[self._position : self._position + 1]
                self._position += 1
                return chunk

        identity = hash_stream(DribblingStream(PDF_PAYLOAD), max_bytes=1024)  # type: ignore[arg-type]
        assert identity.sniffed_format is FileFormat.PDF
        assert identity.sha256 == hashlib.sha256(PDF_PAYLOAD).hexdigest()

    def test_short_digest_helper(self) -> None:
        identity = hash_bytes(PDF_PAYLOAD, max_bytes=1024)
        assert identity.short_digest(8) == identity.sha256[:8]

    def test_identity_is_immutable(self) -> None:
        identity = hash_bytes(PDF_PAYLOAD, max_bytes=1024)
        with pytest.raises(AttributeError):
            identity.sha256 = "x" * 64  # type: ignore[misc]

    def test_construction_is_possible_for_fixtures(self) -> None:
        identity = ContentIdentity(
            sha256="0" * 64,
            size_bytes=1,
            document_id=document_id_for_digest("0" * 64),
            sniffed_format=None,
        )
        assert identity.size_bytes == 1


class TestSafetyLimits:
    def test_oversized_payload_is_rejected(self) -> None:
        with pytest.raises(UnsafeContentError, match="exceeds"):
            hash_bytes(b"x" * 2048, max_bytes=1024)

    def test_payload_exactly_at_the_limit_is_accepted(self) -> None:
        assert hash_bytes(b"x" * 1024, max_bytes=1024).size_bytes == 1024

    def test_the_cap_is_enforced_while_streaming(self) -> None:
        """A hostile stream must be abandoned mid-read, not buffered then measured.

        The stream below is effectively infinite; if the limit were applied after reading
        to completion, this test would never finish.
        """
        chunks_served = 0

        class EndlessStream(io.RawIOBase):
            def read(self, size: int = -1) -> bytes:
                nonlocal chunks_served
                chunks_served += 1
                if chunks_served > 100:
                    raise AssertionError("cap was not enforced during streaming")
                return b"x" * (1024 * 1024)

        with pytest.raises(UnsafeContentError, match="exceeds"):
            hash_stream(EndlessStream(), max_bytes=4 * 1024 * 1024)  # type: ignore[arg-type]

        assert chunks_served <= 6

    def test_empty_payload_is_rejected(self) -> None:
        """Every empty file shares one digest, which would corrupt deduplication."""
        with pytest.raises(UnsafeContentError, match="empty"):
            hash_bytes(b"", max_bytes=1024)

    @pytest.mark.parametrize("max_bytes", [0, -1])
    def test_nonpositive_limit_is_a_programming_error(self, max_bytes: int) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            hash_bytes(b"data", max_bytes=max_bytes)


class TestContentAccumulator:
    """The incremental core, used directly by the downloader as it writes bytes to disk.

    ``hash_stream`` is a loop over this, so the rules are tested above through that path too. What
    only shows up here is the single-use contract, which the downloader depends on and no reader of
    the loop would notice was missing.
    """

    def test_it_produces_the_same_identity_as_hashing_the_whole_payload(self) -> None:
        payload = b"%PDF-1.7\n" + b"x" * 5000
        accumulator = ContentAccumulator(max_bytes=1024 * 1024)
        for start in range(0, len(payload), 512):
            accumulator.update(payload[start : start + 512])

        assert accumulator.finish() == hash_bytes(payload, max_bytes=1024 * 1024)

    def test_the_sniff_prefix_survives_being_split_across_chunks(self) -> None:
        """A one-byte-at-a-time arrival must still identify the format.

        The prefix is assembled from the front of the stream however the chunks fall, so a server
        dribbling a PDF header out in single bytes is recognised the same as one sending it at once.
        """
        accumulator = ContentAccumulator(max_bytes=1024)
        for byte in b"%PDF-1.7\nbody":
            accumulator.update(bytes([byte]))

        assert accumulator.finish().sniffed_format is FileFormat.PDF

    def test_feeding_it_after_finishing_is_refused(self) -> None:
        """Otherwise the identity would describe neither what was hashed nor what was written."""
        accumulator = ContentAccumulator(max_bytes=1024)
        accumulator.update(b"data")
        accumulator.finish()

        with pytest.raises(ValueError, match="already finished"):
            accumulator.update(b"more")

    def test_an_empty_accumulator_has_no_identity(self) -> None:
        with pytest.raises(UnsafeContentError, match="empty"):
            ContentAccumulator(max_bytes=1024).finish()

    def test_the_ceiling_is_reported_with_what_had_arrived(self) -> None:
        accumulator = ContentAccumulator(max_bytes=1000)
        accumulator.update(b"x" * 600)
        with pytest.raises(UnsafeContentError, match="read 1200 bytes so far"):
            accumulator.update(b"x" * 600)


class TestResolveFormat:
    def test_media_type_alone_is_enough(self) -> None:
        assert resolve_format(allowed=ALL_FORMATS, media_type="application/pdf") is FileFormat.PDF

    def test_filename_alone_is_enough(self) -> None:
        assert resolve_format(allowed=ALL_FORMATS, filename="tender.pdf") is FileFormat.PDF

    def test_magic_bytes_alone_are_enough(self) -> None:
        assert resolve_format(allowed=ALL_FORMATS, sniffed=FileFormat.PDF) is FileFormat.PDF

    def test_declared_format_wins_when_compatible_with_magic_bytes(self) -> None:
        """An .xlsx sniffs as ZIP; the more specific declared format is the useful answer."""
        resolved = resolve_format(
            allowed=ALL_FORMATS,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="boq.xlsx",
            sniffed=FileFormat.ZIP,
        )
        assert resolved is FileFormat.XLSX

    def test_html_error_page_served_for_a_pdf_request_is_rejected(self) -> None:
        """The failure mode that matters most: a login or session-expiry page with HTTP 200.

        Without this check the corpus quietly fills with error pages, and every downstream
        metric is computed over garbage.
        """
        with pytest.raises(UnsafeContentError, match="contradicts"):
            resolve_format(
                allowed=ALL_FORMATS,
                media_type="text/html; charset=utf-8",
                filename="tender_document.pdf",
            )

    def test_content_masquerading_as_another_format_is_rejected(self) -> None:
        with pytest.raises(UnsafeContentError, match="actually zip"):
            resolve_format(
                allowed=ALL_FORMATS,
                media_type="application/pdf",
                filename="report.pdf",
                sniffed=FileFormat.ZIP,
            )

    def test_unrecognisable_content_is_rejected(self) -> None:
        with pytest.raises(UnsafeContentError, match="cannot determine format"):
            resolve_format(allowed=ALL_FORMATS, media_type="application/octet-stream")

    def test_no_signals_at_all_is_rejected(self) -> None:
        with pytest.raises(UnsafeContentError, match="cannot determine format"):
            resolve_format(allowed=ALL_FORMATS)

    def test_format_outside_the_source_allowlist_is_rejected(self) -> None:
        """A source declares what it may yield; anything else is refused even if valid."""
        with pytest.raises(UnsafeContentError, match="not accepted from this source"):
            resolve_format(
                allowed={FileFormat.PDF},
                media_type="text/csv",
                filename="data.csv",
            )

    def test_generic_binary_media_type_falls_back_to_the_filename(self) -> None:
        """Portals commonly serve everything as octet-stream; the extension is all we have."""
        resolved = resolve_format(
            allowed=ALL_FORMATS,
            media_type="application/octet-stream",
            filename="award.pdf",
        )
        assert resolved is FileFormat.PDF

    def test_magic_bytes_override_a_wrong_but_unrecognised_media_type(self) -> None:
        resolved = resolve_format(
            allowed=ALL_FORMATS,
            media_type="application/octet-stream",
            sniffed=FileFormat.PDF,
        )
        assert resolved is FileFormat.PDF

    def test_empty_allowlist_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError, match="at least one format"):
            resolve_format(allowed=frozenset(), media_type="application/pdf")

    def test_real_payload_end_to_end(self) -> None:
        identity = hash_bytes(ZIP_PAYLOAD, max_bytes=4096)
        resolved = resolve_format(
            allowed={FileFormat.XLSX},
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="boq.xlsx",
            sniffed=identity.sniffed_format,
        )
        assert resolved is FileFormat.XLSX


class TestSafeFilename:
    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            ("tender.pdf", "tender.pdf"),
            ("Tender_Notice-2026.pdf", "Tender_Notice-2026.pdf"),
            ("../../../../etc/passwd", "passwd"),
            ("..\\..\\windows\\system32\\config", "config"),
            ("/absolute/path/doc.pdf", "doc.pdf"),
            ("C:\\Users\\admin\\doc.pdf", "doc.pdf"),
            ("doc with spaces.pdf", "doc_with_spaces.pdf"),
            ("../.././evil.pdf", "evil.pdf"),
        ],
    )
    def test_path_components_are_stripped(self, candidate: str, expected: str) -> None:
        assert safe_filename(candidate) == expected

    def test_null_bytes_are_removed(self) -> None:
        assert "\x00" not in safe_filename("doc\x00.pdf")

    def test_control_characters_are_removed(self) -> None:
        result = safe_filename("doc\r\n\tname.pdf")
        assert "\r" not in result
        assert "\n" not in result
        assert "\t" not in result

    def test_result_never_contains_separators(self) -> None:
        for candidate in ("../../x", "a/b/c.pdf", "a\\b\\c.pdf", "....//....//x.pdf"):
            result = safe_filename(candidate)
            assert "/" not in result
            assert "\\" not in result
            assert not result.startswith(".")

    def test_windows_reserved_names_are_defused(self) -> None:
        assert safe_filename("con.pdf") != "con.pdf"
        assert safe_filename("NUL") != "NUL"

    def test_overlong_names_are_truncated_but_keep_their_extension(self) -> None:
        result = safe_filename("a" * 500 + ".pdf")
        assert len(result) <= 128
        assert result.endswith(".pdf")

    def test_unusable_input_falls_back(self) -> None:
        assert safe_filename(None) == "document"
        assert safe_filename("") == "document"
        assert safe_filename("///") == "document"
        assert safe_filename("...") == "document"

    def test_fallback_format_supplies_an_extension(self) -> None:
        assert safe_filename(None, fallback_format=FileFormat.PDF) == "document.pdf"
        assert safe_filename("noext", fallback_format=FileFormat.PDF) == "noext.pdf"

    def test_existing_valid_extension_is_not_duplicated(self) -> None:
        assert safe_filename("report.pdf", fallback_format=FileFormat.PDF) == "report.pdf"

    def test_unicode_is_normalized_to_ascii_where_possible(self) -> None:
        result = safe_filename("ﬁle.pdf")
        assert result == "file.pdf"

    def test_non_latin_names_degrade_safely(self) -> None:
        """Devanagari or CJK filenames must not crash or escape the allowlist."""
        result = safe_filename("निविदा.pdf", fallback_format=FileFormat.PDF)
        assert result.endswith(".pdf")
        assert all(character.isascii() for character in result)


class TestDigestUniqueness:
    def test_distinct_digests(self) -> None:
        assert digests_are_distinct(["a" * 64, "b" * 64])

    def test_repeated_digest_is_detected(self) -> None:
        assert not digests_are_distinct(["a" * 64, "b" * 64, "a" * 64])

    def test_empty_iterable_is_trivially_distinct(self) -> None:
        assert digests_are_distinct([])
