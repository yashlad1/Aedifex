"""File-format vocabulary, media-type mapping, and magic-byte sniffing.

Two independent questions must be answered about every downloaded byte stream:

1. *What does the server claim it is?* — the ``Content-Type`` header and URL extension.
2. *What is it actually?* — the leading bytes of the payload.

Remote sources get both wrong routinely, and sometimes maliciously. This module keeps the
mapping between formats, extensions, and media types in one place, and provides
:func:`sniff_format` so the acquisition layer can compare claim against reality.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "EXTENSIONS_BY_FORMAT",
    "FORMATS_WITH_A_SIGNATURE",
    "MEDIA_TYPES_BY_FORMAT",
    "SNIFF_PREFIX_BYTES",
    "FileFormat",
    "canonical_extension",
    "format_for_extension",
    "format_for_media_type",
    "formats_are_compatible",
    "normalize_media_type",
    "sniff_format",
]


class FileFormat(StrEnum):
    """File formats the acquisition layer will accept.

    This doubles as the allowlist: a format absent from this enum is rejected rather than
    stored, because we will not have a parser for it and cannot reason about its safety.
    """

    PDF = "pdf"
    XLSX = "xlsx"
    XLS = "xls"
    DOCX = "docx"
    DOC = "doc"
    CSV = "csv"
    JSON = "json"
    XML = "xml"
    HTML = "html"
    ZIP = "zip"
    PNG = "png"
    JPEG = "jpeg"
    TIFF = "tiff"


# The first extension listed is canonical (used when naming stored objects).
EXTENSIONS_BY_FORMAT: Final[MappingProxyType[FileFormat, tuple[str, ...]]] = MappingProxyType(
    {
        FileFormat.PDF: (".pdf",),
        FileFormat.XLSX: (".xlsx",),
        FileFormat.XLS: (".xls",),
        FileFormat.DOCX: (".docx",),
        FileFormat.DOC: (".doc",),
        FileFormat.CSV: (".csv",),
        FileFormat.JSON: (".json",),
        FileFormat.XML: (".xml",),
        FileFormat.HTML: (".html", ".htm"),
        FileFormat.ZIP: (".zip",),
        FileFormat.PNG: (".png",),
        FileFormat.JPEG: (".jpg", ".jpeg"),
        FileFormat.TIFF: (".tif", ".tiff"),
    }
)

MEDIA_TYPES_BY_FORMAT: Final[MappingProxyType[FileFormat, tuple[str, ...]]] = MappingProxyType(
    {
        FileFormat.PDF: ("application/pdf", "application/x-pdf"),
        FileFormat.XLSX: ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
        FileFormat.XLS: ("application/vnd.ms-excel",),
        FileFormat.DOCX: (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        FileFormat.DOC: ("application/msword",),
        FileFormat.CSV: ("text/csv",),
        FileFormat.JSON: ("application/json",),
        FileFormat.XML: ("application/xml", "text/xml"),
        FileFormat.HTML: ("text/html", "application/xhtml+xml"),
        FileFormat.ZIP: ("application/zip", "application/x-zip-compressed"),
        FileFormat.PNG: ("image/png",),
        FileFormat.JPEG: ("image/jpeg",),
        FileFormat.TIFF: ("image/tiff",),
    }
)

_FORMAT_BY_EXTENSION: Final[MappingProxyType[str, FileFormat]] = MappingProxyType(
    {
        extension: file_format
        for file_format, extensions in EXTENSIONS_BY_FORMAT.items()
        for extension in extensions
    }
)

_FORMAT_BY_MEDIA_TYPE: Final[MappingProxyType[str, FileFormat]] = MappingProxyType(
    {
        media_type: file_format
        for file_format, media_types in MEDIA_TYPES_BY_FORMAT.items()
        for media_type in media_types
    }
)

# Magic-byte signatures, longest-first so that more specific prefixes win.
#
# OOXML formats (xlsx/docx) and plain archives are all ZIP containers, so sniffing can
# only report ZIP for them; distinguishing requires reading the archive directory, which
# is the parser's job. Text-based formats (csv/json/xml/html) have no reliable signature
# and are reported as unknown rather than guessed.
_SIGNATURES: Final[tuple[tuple[bytes, FileFormat], ...]] = (
    (b"%PDF-", FileFormat.PDF),
    (b"\x89PNG\r\n\x1a\n", FileFormat.PNG),
    (b"\xff\xd8\xff", FileFormat.JPEG),
    (b"II*\x00", FileFormat.TIFF),
    (b"MM\x00*", FileFormat.TIFF),
    # Legacy OLE compound file: .doc and .xls share this container.
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", FileFormat.DOC),
    (b"PK\x03\x04", FileFormat.ZIP),
)

# Number of leading bytes callers need to buffer for sniffing to be conclusive.
SNIFF_PREFIX_BYTES: Final[int] = max(len(signature) for signature, _ in _SIGNATURES)

# Formats that are structurally ZIP archives on disk.
_ZIP_CONTAINER_FORMATS: Final[frozenset[FileFormat]] = frozenset(
    {FileFormat.ZIP, FileFormat.XLSX, FileFormat.DOCX}
)

# Formats that share the legacy OLE container.
_OLE_CONTAINER_FORMATS: Final[frozenset[FileFormat]] = frozenset({FileFormat.DOC, FileFormat.XLS})

FORMATS_WITH_A_SIGNATURE: Final[frozenset[FileFormat]] = (
    frozenset(file_format for _, file_format in _SIGNATURES)
    | _ZIP_CONTAINER_FORMATS
    | _OLE_CONTAINER_FORMATS
)
"""Formats whose leading bytes are always recognisable, so their absence is evidence.

For these, :func:`sniff_format` returning ``None`` means the content is *not* the declared format —
a PDF always starts with ``%PDF-``. For the rest (CSV, JSON, XML, HTML) ``None`` means only that
there was nothing to confirm, which is why the two cases must be distinguished rather than both
treated as "unconfirmed".

Derived from the signature table rather than listed, so adding a binary format in one place cannot
leave it silently exempt here.
"""


def normalize_media_type(media_type: str) -> str:
    """Strip parameters and casing from a ``Content-Type`` header value.

    ``"Application/PDF; charset=binary"`` becomes ``"application/pdf"``.
    """
    return media_type.split(";", 1)[0].strip().lower()


def format_for_media_type(media_type: str) -> FileFormat | None:
    """Return the format a media type denotes, or ``None`` if it is not allowed."""
    return _FORMAT_BY_MEDIA_TYPE.get(normalize_media_type(media_type))


def format_for_extension(extension: str) -> FileFormat | None:
    """Return the format an extension denotes, or ``None`` if it is not allowed.

    Accepts the extension with or without a leading dot, in any case.
    """
    normalized = extension.strip().lower()
    if normalized and not normalized.startswith("."):
        normalized = f".{normalized}"
    return _FORMAT_BY_EXTENSION.get(normalized)


def canonical_extension(file_format: FileFormat) -> str:
    """Return the extension to use when naming stored objects of this format."""
    return EXTENSIONS_BY_FORMAT[file_format][0]


def sniff_format(payload: bytes) -> FileFormat | None:
    """Identify a format from its leading bytes.

    Returns ``None`` for text-based formats and unrecognised content: the absence of a
    signature is not evidence of a problem, only an absence of confirmation. Callers must
    treat ``None`` as "unconfirmed", never as "invalid".
    """
    for signature, file_format in _SIGNATURES:
        if payload.startswith(signature):
            return file_format
    return None


def formats_are_compatible(declared: FileFormat, sniffed: FileFormat) -> bool:
    """Return whether a sniffed format is consistent with a declared one.

    Container formats are treated as compatible with their members: an ``.xlsx`` that
    sniffs as ZIP is expected, and a ``.doc``/``.xls`` ambiguity is inherent to the OLE
    container. Anything else is a genuine mismatch — for example content claiming to be a
    PDF that is actually a ZIP archive.
    """
    if declared is sniffed:
        return True
    if sniffed is FileFormat.ZIP and declared in _ZIP_CONTAINER_FORMATS:
        return True
    return sniffed in _OLE_CONTAINER_FORMATS and declared in _OLE_CONTAINER_FORMATS
