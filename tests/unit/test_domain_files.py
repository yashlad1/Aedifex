"""Tests for file-format mapping and magic-byte sniffing."""

from __future__ import annotations

import pytest

from aedifex.domain.files import (
    EXTENSIONS_BY_FORMAT,
    FORMATS_WITH_A_SIGNATURE,
    MEDIA_TYPES_BY_FORMAT,
    SNIFF_PREFIX_BYTES,
    FileFormat,
    canonical_extension,
    format_for_extension,
    format_for_media_type,
    formats_are_compatible,
    normalize_media_type,
    sniff_format,
)

# Minimal real signatures for each sniffable format.
PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF"
ZIP_HEADER = b"PK\x03\x04\x14\x00\x00\x00\x08\x00"
OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8
TIFF_LE_HEADER = b"II*\x00\x08\x00\x00\x00"
TIFF_BE_HEADER = b"MM\x00*\x00\x00\x00\x08"


class TestCompleteness:
    def test_every_format_has_at_least_one_extension(self) -> None:
        assert set(EXTENSIONS_BY_FORMAT) == set(FileFormat)
        for file_format, extensions in EXTENSIONS_BY_FORMAT.items():
            assert extensions, f"{file_format} has no extension"
            for extension in extensions:
                assert extension.startswith("."), f"{extension} must start with a dot"
                assert extension == extension.lower()

    def test_every_format_has_at_least_one_media_type(self) -> None:
        assert set(MEDIA_TYPES_BY_FORMAT) == set(FileFormat)
        for file_format, media_types in MEDIA_TYPES_BY_FORMAT.items():
            assert media_types, f"{file_format} has no media type"

    def test_extensions_are_not_shared_between_formats(self) -> None:
        seen: dict[str, FileFormat] = {}
        for file_format, extensions in EXTENSIONS_BY_FORMAT.items():
            for extension in extensions:
                assert (
                    extension not in seen
                ), f"{extension} maps to both {seen.get(extension)} and {file_format}"
                seen[extension] = file_format

    def test_media_types_are_not_shared_between_formats(self) -> None:
        seen: dict[str, FileFormat] = {}
        for file_format, media_types in MEDIA_TYPES_BY_FORMAT.items():
            for media_type in media_types:
                assert (
                    media_type not in seen
                ), f"{media_type} maps to both {seen.get(media_type)} and {file_format}"
                seen[media_type] = file_format

    def test_canonical_extension_is_the_first_listed(self) -> None:
        assert canonical_extension(FileFormat.JPEG) == ".jpg"
        assert canonical_extension(FileFormat.HTML) == ".html"
        assert canonical_extension(FileFormat.PDF) == ".pdf"


class TestMediaTypeLookup:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("application/pdf", "application/pdf"),
            ("Application/PDF", "application/pdf"),
            ("application/pdf; charset=binary", "application/pdf"),
            ("  text/csv ; q=0.9  ", "text/csv"),
        ],
    )
    def test_normalization(self, raw: str, expected: str) -> None:
        assert normalize_media_type(raw) == expected

    def test_lookup_is_case_and_parameter_insensitive(self) -> None:
        assert format_for_media_type("APPLICATION/PDF; charset=utf-8") is FileFormat.PDF

    def test_unknown_media_type_returns_none(self) -> None:
        assert format_for_media_type("application/octet-stream") is None
        assert format_for_media_type("application/x-msdownload") is None


class TestExtensionLookup:
    @pytest.mark.parametrize("candidate", [".pdf", "pdf", ".PDF", "  .Pdf  "])
    def test_accepts_various_spellings(self, candidate: str) -> None:
        assert format_for_extension(candidate) is FileFormat.PDF

    def test_alternate_extensions_resolve(self) -> None:
        assert format_for_extension(".jpeg") is FileFormat.JPEG
        assert format_for_extension(".htm") is FileFormat.HTML
        assert format_for_extension(".tif") is FileFormat.TIFF

    def test_unknown_extension_returns_none(self) -> None:
        assert format_for_extension(".exe") is None
        assert format_for_extension("") is None


class TestSniffing:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (PDF_HEADER, FileFormat.PDF),
            (PNG_HEADER, FileFormat.PNG),
            (JPEG_HEADER, FileFormat.JPEG),
            (ZIP_HEADER, FileFormat.ZIP),
            (OLE_HEADER, FileFormat.DOC),
            (TIFF_LE_HEADER, FileFormat.TIFF),
            (TIFF_BE_HEADER, FileFormat.TIFF),
        ],
    )
    def test_recognises_signatures(self, payload: bytes, expected: FileFormat) -> None:
        assert sniff_format(payload) is expected

    def test_text_formats_are_unconfirmable(self) -> None:
        """Absence of a signature means 'unconfirmed', never 'invalid'."""
        assert sniff_format(b'{"key": "value"}') is None
        assert sniff_format(b"<html><body>hi</body></html>") is None
        assert sniff_format(b"a,b,c\n1,2,3\n") is None

    def test_empty_and_short_payloads_do_not_crash(self) -> None:
        assert sniff_format(b"") is None
        assert sniff_format(b"%") is None
        assert sniff_format(b"%PD") is None

    def test_signature_must_be_at_the_start(self) -> None:
        assert sniff_format(b"\n\n%PDF-1.7") is None

    def test_prefix_length_is_enough_for_every_signature(self) -> None:
        """Callers buffer only SNIFF_PREFIX_BYTES, so it must cover the longest signature."""
        for payload in (PDF_HEADER, PNG_HEADER, ZIP_HEADER, OLE_HEADER, TIFF_LE_HEADER):
            assert sniff_format(payload[:SNIFF_PREFIX_BYTES]) is not None


class TestFormatsWithASignature:
    """Which formats make a missing signature meaningful rather than merely inconclusive.

    The distinction earns its place in the downloader: a payload declared as a PDF that carries no
    PDF signature is something else, while a payload declared as CSV has nothing to be missing. Both
    look identical to :func:`sniff_format`, which returns ``None`` either way.
    """

    @pytest.mark.parametrize(
        "file_format",
        [
            FileFormat.PDF,
            FileFormat.PNG,
            FileFormat.JPEG,
            FileFormat.TIFF,
            FileFormat.ZIP,
            FileFormat.XLSX,
            FileFormat.DOCX,
            FileFormat.DOC,
            FileFormat.XLS,
        ],
    )
    def test_binary_formats_always_carry_one(self, file_format: FileFormat) -> None:
        assert file_format in FORMATS_WITH_A_SIGNATURE

    @pytest.mark.parametrize(
        "file_format",
        [FileFormat.CSV, FileFormat.JSON, FileFormat.XML, FileFormat.HTML],
    )
    def test_text_formats_do_not(self, file_format: FileFormat) -> None:
        assert file_format not in FORMATS_WITH_A_SIGNATURE

    def test_every_listed_format_is_actually_recognised_from_its_own_bytes(self) -> None:
        """The set must not claim a signature exists where sniffing cannot find one.

        Otherwise the downloader would refuse a legitimate document for lacking a marker that was
        never detectable in the first place. Checked against the container members too, since an
        ``.xlsx`` is recognised through its ZIP header rather than one of its own.
        """
        samples: dict[FileFormat, bytes] = {
            FileFormat.PDF: PDF_HEADER,
            FileFormat.PNG: PNG_HEADER,
            FileFormat.JPEG: JPEG_HEADER,
            FileFormat.TIFF: TIFF_LE_HEADER,
            FileFormat.ZIP: ZIP_HEADER,
            FileFormat.XLSX: ZIP_HEADER,
            FileFormat.DOCX: ZIP_HEADER,
            FileFormat.DOC: OLE_HEADER,
            FileFormat.XLS: OLE_HEADER,
        }
        assert set(samples) == set(
            FORMATS_WITH_A_SIGNATURE
        ), "a format was added to FORMATS_WITH_A_SIGNATURE without a sample proving it sniffs"
        for file_format, payload in samples.items():
            sniffed = sniff_format(payload)
            assert sniffed is not None
            assert formats_are_compatible(file_format, sniffed)


class TestCompatibility:
    def test_identical_formats_are_compatible(self) -> None:
        for file_format in FileFormat:
            assert formats_are_compatible(file_format, file_format)

    @pytest.mark.parametrize("declared", [FileFormat.XLSX, FileFormat.DOCX, FileFormat.ZIP])
    def test_ooxml_declared_as_zip_is_expected(self, declared: FileFormat) -> None:
        """An .xlsx is a ZIP container; sniffing cannot see past that."""
        assert formats_are_compatible(declared, FileFormat.ZIP)

    def test_legacy_office_container_ambiguity_is_tolerated(self) -> None:
        assert formats_are_compatible(FileFormat.XLS, FileFormat.DOC)
        assert formats_are_compatible(FileFormat.DOC, FileFormat.XLS)

    @pytest.mark.parametrize(
        ("declared", "sniffed"),
        [
            (FileFormat.PDF, FileFormat.ZIP),
            (FileFormat.PDF, FileFormat.PNG),
            (FileFormat.CSV, FileFormat.ZIP),
            (FileFormat.PNG, FileFormat.PDF),
            (FileFormat.XLSX, FileFormat.PDF),
        ],
    )
    def test_genuine_mismatches_are_incompatible(
        self, declared: FileFormat, sniffed: FileFormat
    ) -> None:
        assert not formats_are_compatible(declared, sniffed)
