"""Downloader tests.

The downloader sits between a response and a file, so what matters is what ends up on disk and
what does not. Almost every test here asserts on the directory rather than on a return value: a
download that fails must leave nothing behind, and "nothing behind" is a statement about the
filesystem that no amount of inspecting an exception can make.

Responses are built directly rather than fetched. The fetch layer has its own suites against real
sockets, and what is under test here is the handling of a body that has already arrived — which is
exercised far more thoroughly by scripting the bytes than by asking a server to send them. The one
end-to-end case, a real PDF over a real socket through the whole stack, lives in
``test_fetch_adversarial.py`` where the server harness already is.

The bodies are real magic bytes, not placeholder text. ``%PDF-`` and ``PK\\x03\\x04`` are what the
format resolution actually keys on, so a test using ``b"payload"`` would exercise the
unrecognisable-bytes path while appearing to test a PDF.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path

import pytest
from pydantic import ValidationError

from aedifex.acquisition.content import document_id_for_digest
from aedifex.acquisition.download import (
    DownloadedFile,
    DownloadPolicy,
    FetchedResponse,
    download,
    filename_from_disposition,
)
from aedifex.acquisition.fetch.controller import AttemptRecord
from aedifex.acquisition.fetch.guard import ValidatedTarget
from aedifex.acquisition.fetch.redirect_controller import ChainResult
from aedifex.acquisition.fetch.retry import AttemptOutcome
from aedifex.acquisition.fetch.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    RawResponse,
    ResponseHeaders,
)
from aedifex.acquisition.registry.models import (
    DataUsePolicy,
    RetrievalMethod,
    SourceCategory,
    SourceDefinition,
)
from aedifex.domain.documents import DocumentType
from aedifex.domain.files import FileFormat
from aedifex.errors import UnsafeContentError
from aedifex.infrastructure.storage.keys import raw_key

SOURCE = "cpwd"
URL = "https://cpwd.test/tenders/notice.pdf"

PDF = b"%PDF-1.7\n" + b"tender text " * 64 + b"\n%%EOF\n"
ZIP = b"PK\x03\x04" + b"\x00" * 200
HTML = b"<!DOCTYPE html><html><body>Your session has expired. Please log in.</body></html>"

PDF_ONLY = DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF}))
PDF_OR_XLSX = DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF, FileFormat.XLSX}))

TARGET = ValidatedTarget(
    url=URL,
    scheme="https",
    hostname="cpwd.test",
    port=443,
    ip_address=ip_address("93.184.216.34"),
    source_id=SOURCE,
    validated_addresses=(ip_address("93.184.216.34"),),
)


@dataclass
class Fetched:
    """A response with a scripted body. Satisfies :class:`FetchedResponse` structurally."""

    response: RawResponse
    requested_url: str
    final_url: str
    attempts: tuple[AttemptRecord, ...] = field(default_factory=tuple)


def fetched(
    body: bytes,
    *,
    headers: Sequence[tuple[str, str]] = (),
    declare_length: bool | int = True,
    status: int = 200,
    requested_url: str = URL,
    final_url: str | None = None,
    attempts: tuple[AttemptRecord, ...] = (),
    on_chunk: object = None,
) -> Fetched:
    """Build a response whose body arrives in chunks.

    ``declare_length`` controls ``Content-Length`` independently of the real body, because the
    interesting cases are exactly the ones where the two disagree. ``True`` declares the truth,
    ``False`` declares nothing (a chunked response), and an integer declares a lie.
    """
    header_items = list(headers)
    declared: int | None
    if declare_length is True:
        declared = len(body)
    elif declare_length is False:
        declared = None
    else:
        declared = int(declare_length)
    if declared is not None and not any(
        name.lower() == "content-length" for name, _ in header_items
    ):
        header_items.append(("content-length", str(declared)))

    def stream(chunk_size: int) -> Iterator[bytes]:
        for start in range(0, len(body), max(1, chunk_size)):
            chunk = body[start : start + chunk_size]
            if callable(on_chunk):
                on_chunk(chunk)
            yield chunk

    return Fetched(
        response=RawResponse(
            target=TARGET,
            status_code=status,
            http_version="HTTP/1.1",
            headers=ResponseHeaders(tuple(header_items)),
            stream=stream,
            close=lambda: None,
            declared_content_length=declared,
        ),
        requested_url=requested_url,
        final_url=final_url if final_url is not None else requested_url,
    )


def contents(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def make_source(**overrides: object) -> SourceDefinition:
    kwargs: dict[str, object] = {
        "id": SOURCE,
        "name": "CPWD",
        "category": SourceCategory.GOVERNMENT_PROCUREMENT,
        "retrieval": RetrievalMethod.HTTP_CRAWL,
        "base_url": "https://cpwd.test/",
        "data_use": DataUsePolicy(
            license="unknown (pending review)",
            allowed_use="Pending review; no collection permitted yet.",
        ),
        "document_types": (DocumentType.TENDER_NOTICE,),
        "file_formats": (FileFormat.PDF,),
    }
    kwargs.update(overrides)
    return SourceDefinition(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# What lands on disk
# ---------------------------------------------------------------------------


class TestASuccessfulDownload:
    def test_the_bytes_on_disk_are_the_bytes_that_arrived(self, tmp_path: Path) -> None:
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)

        assert result.path.read_bytes() == PDF
        assert result.sha256 == hashlib.sha256(PDF).hexdigest()
        assert result.size_bytes == len(PDF)

    def test_the_file_is_named_by_its_digest(self, tmp_path: Path) -> None:
        """Content-addressed, so the name cannot be influenced by anything a server sends."""
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)

        assert result.path.name == f"{hashlib.sha256(PDF).hexdigest()}.pdf"
        assert result.path.parent == tmp_path
        assert contents(tmp_path) == [result.path.name], "a partial file was left behind"

    def test_the_document_id_is_derived_from_the_digest(self, tmp_path: Path) -> None:
        """So the same bytes from a different URL are the same document (FR-002, FR-014)."""
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert result.identity.document_id == document_id_for_digest(result.sha256)

    def test_the_storage_key_is_content_addressed(self, tmp_path: Path) -> None:
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert result.storage_key == raw_key(
            source_id=SOURCE, sha256=result.sha256, file_format=FileFormat.PDF
        )
        assert result.sha256 in result.storage_key

    def test_the_directory_is_created_if_absent(self, tmp_path: Path) -> None:
        nested = tmp_path / "staging" / "cpwd"
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=nested)
        assert result.path.is_file()

    def test_the_format_is_resolved_from_the_bytes(self, tmp_path: Path) -> None:
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert result.file_format is FileFormat.PDF
        assert result.identity.sniffed_format is FileFormat.PDF

    def test_a_zip_container_keeps_the_more_specific_declared_format(self, tmp_path: Path) -> None:
        """An ``.xlsx`` sniffs as ZIP. Storing it as ZIP would lose what it is."""
        result = download(
            fetched(
                ZIP,
                headers=(
                    (
                        "content-type",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ),
                final_url="https://cpwd.test/boq.xlsx",
            ),
            source_id=SOURCE,
            policy=PDF_OR_XLSX,
            directory=tmp_path,
        )
        assert result.file_format is FileFormat.XLSX
        assert result.path.suffix == ".xlsx"


class TestProvenance:
    def test_both_urls_are_kept(self, tmp_path: Path) -> None:
        """Requested and answering URLs tell different halves of one story."""
        result = download(
            fetched(
                PDF,
                requested_url="https://cpwd.test/tenders/notice.pdf",
                final_url="https://docs.cpwd.test/store/9931.pdf",
            ),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
        )
        assert result.requested_url == "https://cpwd.test/tenders/notice.pdf"
        assert result.final_url == "https://docs.cpwd.test/store/9931.pdf"

    def test_the_http_metadata_is_kept(self, tmp_path: Path) -> None:
        result = download(
            fetched(PDF, headers=(("content-type", "application/pdf"), ("etag", '"abc"'))),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
        )
        assert result.http_status == 200
        assert result.http_version == "HTTP/1.1"
        assert result.declared_media_type == "application/pdf"
        assert result.declared_content_length == len(PDF)
        assert ("etag", '"abc"') in result.response_headers

    def test_the_attempt_history_is_carried_through(self, tmp_path: Path) -> None:
        """ "Retrieved on attempt 2 after a 503" is a different claim from "retrieved"."""
        history = (
            AttemptRecord(
                attempt=1, outcome=AttemptOutcome.HTTP_STATUS, duration_ms=12.0, status_code=503
            ),
            AttemptRecord(
                attempt=2, outcome=AttemptOutcome.SUCCESS, duration_ms=30.0, status_code=200
            ),
        )
        source = fetched(PDF)
        source.attempts = history
        result = download(source, source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert result.attempts == history

    def test_the_retrieval_time_is_timezone_aware_utc(self, tmp_path: Path) -> None:
        """A naive timestamp is a bug waiting for a deployment in another timezone."""
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert result.retrieved_at.tzinfo is not None
        assert result.retrieved_at.utcoffset() is not None
        assert result.retrieved_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_the_description_carries_no_body(self, tmp_path: Path) -> None:
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        described = result.describe()
        assert "notice.pdf" in described
        assert result.identity.short_digest() in described
        assert "tender text" not in described

    def test_a_chain_result_satisfies_what_the_downloader_needs(self, tmp_path: Path) -> None:
        """The structural claim, asserted rather than described.

        The downloader takes a protocol so it need not know whether redirects were involved. If
        ``ChainResult`` ever stops satisfying it, this fails here rather than at a call site.
        """
        source = fetched(PDF)
        chain = ChainResult(
            response=source.response,
            requested_url=URL,
            final_url=URL,
        )
        assert isinstance(chain, FetchedResponse)
        result = download(chain, source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert isinstance(result, DownloadedFile)
        assert result.attempts == ()


# ---------------------------------------------------------------------------
# Nothing is buffered, and nothing partial survives
# ---------------------------------------------------------------------------


class TestStreaming:
    def test_writing_begins_before_the_body_has_finished_arriving(self, tmp_path: Path) -> None:
        """The claim that the payload is never held in memory, made observable.

        A partial file existing in the directory *while* the body is still being produced is what
        distinguishes streaming from buffering-then-writing. Asserted from inside the generator,
        because afterwards the evidence is gone either way.
        """
        seen: list[list[str]] = []
        big = b"%PDF-1.7\n" + b"x" * (512 * 1024)

        result = download(
            fetched(big, on_chunk=lambda _chunk: seen.append(contents(tmp_path))),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
            chunk_size=64 * 1024,
        )

        assert len(seen) > 1, "the body arrived in one piece; this proves nothing"
        assert any(
            name.startswith(".partial-") for snapshot in seen[1:] for name in snapshot
        ), "no partial file existed while the body was still arriving"
        assert contents(tmp_path) == [result.path.name]

    def test_a_failure_part_way_through_leaves_nothing(self, tmp_path: Path) -> None:
        """A truncated PDF that looks like a document is worse than no document."""
        chunks = 0

        def explode(_chunk: bytes) -> None:
            nonlocal chunks
            chunks += 1
            if chunks == 3:
                raise OSError("connection reset while streaming")

        with pytest.raises(OSError, match="connection reset"):
            download(
                fetched(b"%PDF-1.7\n" + b"x" * (512 * 1024), on_chunk=explode),
                source_id=SOURCE,
                policy=PDF_ONLY,
                directory=tmp_path,
                chunk_size=64 * 1024,
            )

        assert contents(tmp_path) == [], "a partial download survived"

    def test_an_interruption_also_leaves_nothing(self, tmp_path: Path) -> None:
        """``KeyboardInterrupt`` is not an ``Exception``, and cleanup must not depend on that."""

        def interrupt(_chunk: bytes) -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            download(
                fetched(PDF, on_chunk=interrupt),
                source_id=SOURCE,
                policy=PDF_ONLY,
                directory=tmp_path,
            )

        assert contents(tmp_path) == []

    def test_the_same_bytes_converge_on_one_file(self, tmp_path: Path) -> None:
        """Idempotence, which is what makes re-running a crawl safe."""
        first = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        second = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)

        assert first.path == second.path
        assert first.sha256 == second.sha256
        assert first.identity.document_id == second.identity.document_id
        assert contents(tmp_path) == [first.path.name]

    def test_different_bytes_land_in_different_files(self, tmp_path: Path) -> None:
        first = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        other = PDF + b"amendment 1\n"
        second = download(fetched(other), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)

        assert first.path != second.path
        assert len(contents(tmp_path)) == 2


# ---------------------------------------------------------------------------
# The size ceiling
# ---------------------------------------------------------------------------


class TestSizeCeiling:
    def test_a_body_over_the_ceiling_is_refused_and_nothing_is_kept(self, tmp_path: Path) -> None:
        policy = DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF}), max_bytes=1024)
        with pytest.raises(UnsafeContentError, match="exceeds the 1024 byte limit"):
            download(
                fetched(b"%PDF-1.7\n" + b"x" * 8192),
                source_id=SOURCE,
                policy=policy,
                directory=tmp_path,
                chunk_size=512,
            )
        assert contents(tmp_path) == []

    def test_a_body_exactly_at_the_ceiling_is_accepted(self, tmp_path: Path) -> None:
        """The boundary belongs to the document, not to the error path."""
        body = b"%PDF-1.7\n" + b"x" * (1024 - 9)
        policy = DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF}), max_bytes=1024)
        result = download(
            fetched(body), source_id=SOURCE, policy=policy, directory=tmp_path, chunk_size=128
        )
        assert result.size_bytes == 1024

    def test_an_empty_body_is_refused(self, tmp_path: Path) -> None:
        """Its digest would collide with every other empty download, corrupting deduplication."""
        with pytest.raises(UnsafeContentError, match="empty"):
            download(fetched(b""), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert contents(tmp_path) == []


# ---------------------------------------------------------------------------
# The declared length
# ---------------------------------------------------------------------------


class TestDeclaredLength:
    def test_a_short_body_against_a_declared_length_is_a_truncation(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafeContentError, match="Content-Length declared"):
            download(
                fetched(PDF, declare_length=len(PDF) + 500),
                source_id=SOURCE,
                policy=PDF_ONLY,
                directory=tmp_path,
            )
        assert contents(tmp_path) == []

    def test_a_matching_declared_length_is_accepted(self, tmp_path: Path) -> None:
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert result.size_bytes == result.declared_content_length

    def test_no_declared_length_is_not_an_error(self, tmp_path: Path) -> None:
        """A chunked response legitimately says nothing about its size."""
        result = download(
            fetched(PDF, declare_length=False),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
        )
        assert result.declared_content_length is None
        assert result.size_bytes == len(PDF)

    def test_a_mismatch_is_ignored_when_the_body_was_content_encoded(self, tmp_path: Path) -> None:
        """``Content-Length`` counts compressed bytes; we counted decompressed ones.

        The transport decodes transparently, so a mismatch here is arithmetic rather than
        truncation. Treating it as truncation would reject every gzipped document.
        """
        result = download(
            fetched(
                PDF,
                headers=(("content-encoding", "gzip"),),
                declare_length=len(PDF) // 2,
            ),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
        )
        assert result.size_bytes == len(PDF)

    @pytest.mark.parametrize("encoding", ["identity", "IDENTITY", " identity "])
    def test_an_identity_encoding_still_gets_the_check(self, tmp_path: Path, encoding: str) -> None:
        """``identity`` means "not encoded", so the exemption must not apply to it."""
        with pytest.raises(UnsafeContentError, match="Content-Length declared"):
            download(
                fetched(
                    PDF,
                    headers=(("content-encoding", encoding),),
                    declare_length=len(PDF) + 10,
                ),
                source_id=SOURCE,
                policy=PDF_ONLY,
                directory=tmp_path,
            )


# ---------------------------------------------------------------------------
# What the bytes actually are
# ---------------------------------------------------------------------------


class TestFormatValidation:
    def test_a_login_page_served_as_a_pdf_is_refused(self, tmp_path: Path) -> None:
        """The case this check exists for.

        Portals answer a request for ``tender.pdf`` with a session-expiry page and HTTP 200. Every
        declared signal says PDF; only the bytes say otherwise.
        """
        with pytest.raises(UnsafeContentError, match="carries no pdf signature"):
            download(
                fetched(HTML, headers=(("content-type", "application/pdf"),)),
                source_id=SOURCE,
                policy=PDF_ONLY,
                directory=tmp_path,
            )
        assert contents(tmp_path) == []

    def test_a_format_the_source_may_not_serve_is_refused(self, tmp_path: Path) -> None:
        policy = DownloadPolicy(allowed_formats=frozenset({FileFormat.XLSX}))
        with pytest.raises(UnsafeContentError, match="not accepted from this source"):
            download(fetched(PDF), source_id=SOURCE, policy=policy, directory=tmp_path)
        assert contents(tmp_path) == []

    def test_unrecognisable_bytes_with_no_declaration_are_refused(self, tmp_path: Path) -> None:
        """Unable to decide means refuse, never store-and-hope (rule 81b)."""
        with pytest.raises(UnsafeContentError, match="cannot determine format"):
            download(
                fetched(
                    b"\x01\x02\x03\x04nothing recognisable",
                    requested_url="https://cpwd.test/download.aspx",
                ),
                source_id=SOURCE,
                policy=PDF_ONLY,
                directory=tmp_path,
            )
        assert contents(tmp_path) == []

    def test_a_contradiction_between_declared_signals_is_refused(self, tmp_path: Path) -> None:
        """An HTML media type for a ``.pdf`` URL: refuse rather than pick a winner."""
        with pytest.raises(UnsafeContentError):
            download(
                fetched(
                    HTML,
                    headers=(("content-type", "text/html"),),
                    final_url="https://cpwd.test/notice.pdf",
                ),
                source_id=SOURCE,
                policy=DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF, FileFormat.HTML})),
                directory=tmp_path,
            )


# ---------------------------------------------------------------------------
# The remote filename
# ---------------------------------------------------------------------------


class TestFilename:
    def test_the_url_basename_is_used_when_no_header_says_otherwise(self, tmp_path: Path) -> None:
        result = download(fetched(PDF), source_id=SOURCE, policy=PDF_ONLY, directory=tmp_path)
        assert result.filename == "notice.pdf"

    def test_a_content_disposition_filename_wins_over_the_url(self, tmp_path: Path) -> None:
        result = download(
            fetched(
                PDF,
                headers=(("content-disposition", 'attachment; filename="Tender Notice 2026.pdf"'),),
            ),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
        )
        assert result.filename == "Tender_Notice_2026.pdf"

    @pytest.mark.parametrize(
        "disposition",
        [
            'attachment; filename="../../../etc/passwd.pdf"',
            'attachment; filename="..\\..\\windows\\system32\\notice.pdf"',
            'attachment; filename="/absolute/notice.pdf"',
            "attachment; filename=../notice.pdf",
        ],
    )
    def test_a_traversal_attempt_cannot_escape_a_basename(
        self, tmp_path: Path, disposition: str
    ) -> None:
        """The filename is metadata, and the stored path comes from the digest — but a name that
        still contained a separator would eventually be joined to something by a later component.
        """
        result = download(
            fetched(PDF, headers=(("content-disposition", disposition),)),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
        )
        assert "/" not in result.filename
        assert "\\" not in result.filename
        assert not result.filename.startswith(".")
        assert ".." not in result.filename
        # And the file itself landed where the digest says, regardless.
        assert result.path.parent == tmp_path

    def test_a_non_ascii_name_is_reduced_to_something_storable(self, tmp_path: Path) -> None:
        """A Devanagari filename is legitimate input from an Indian portal, not an attack."""
        # "निविदा.pdf" — the Hindi word for tender, percent-encoded as RFC 8187 requires.
        encoded = "%E0%A4%A8%E0%A4%BF%E0%A4%B5%E0%A4%BF%E0%A4%A6%E0%A4%BE.pdf"
        devanagari = f"attachment; filename*=UTF-8''{encoded}"
        result = download(
            fetched(PDF, headers=(("content-disposition", devanagari),)),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
        )
        assert result.filename.endswith(".pdf")
        assert result.filename.isascii()

    def test_a_url_with_no_basename_falls_back(self, tmp_path: Path) -> None:
        result = download(
            fetched(PDF, requested_url="https://cpwd.test/"),
            source_id=SOURCE,
            policy=PDF_ONLY,
            directory=tmp_path,
        )
        assert result.filename == "document.pdf"


class TestContentDispositionParsing:
    """The parser on its own, because it takes hostile input and the cases are enumerable."""

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ('attachment; filename="notice.pdf"', "notice.pdf"),
            ("attachment; filename=notice.pdf", "notice.pdf"),
            ("attachment;filename=notice.pdf", "notice.pdf"),
            ("ATTACHMENT; FILENAME=notice.pdf", "notice.pdf"),
            ('inline; filename="notice.pdf"', "notice.pdf"),
            ('attachment; filename="a;b.pdf"', "a;b.pdf"),
            ("attachment; filename*=UTF-8''report%20final.pdf", "report final.pdf"),
            ("attachment; filename*=utf-8''report.pdf", "report.pdf"),
            # The extended form wins: it is the one that can carry a name outside ASCII.
            (
                "attachment; filename=\"fallback.pdf\"; filename*=UTF-8''real.pdf",
                "real.pdf",
            ),
            ("attachment", None),
            ("", None),
            ("attachment; filename=", None),
            ('attachment; filename=""', None),
            # An unsupported charset is treated as absent rather than guessed at.
            ("attachment; filename*=ISO-8859-1''report.pdf", None),
            ("attachment; size=1234", None),
        ],
    )
    def test_the_filename_is_extracted_or_refused(self, header: str, expected: str | None) -> None:
        assert filename_from_disposition(header) == expected

    def test_none_is_handled(self) -> None:
        assert filename_from_disposition(None) is None

    def test_a_semicolon_inside_quotes_does_not_split_the_name(self) -> None:
        """Splitting naively would return a different name than the server sent."""
        assert filename_from_disposition('attachment; filename="minutes; annexure A.pdf"') == (
            "minutes; annexure A.pdf"
        )


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class TestDownloadPolicy:
    def test_an_empty_format_set_is_refused_at_construction(self) -> None:
        """Failing here names the real problem; failing later would report "cannot determine"."""
        with pytest.raises(ValueError, match="must not be empty"):
            DownloadPolicy(allowed_formats=frozenset())

    @pytest.mark.parametrize("max_bytes", [0, -1])
    def test_a_non_positive_ceiling_is_refused(self, max_bytes: int) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF}), max_bytes=max_bytes)

    def test_the_permitted_formats_come_from_the_source_entry(self) -> None:
        """Widening what a portal may serve is a configuration change, not a code change."""
        source = make_source(file_formats=(FileFormat.PDF, FileFormat.XLSX))
        policy = DownloadPolicy.from_source(source)

        assert policy.allowed_formats == frozenset({FileFormat.PDF, FileFormat.XLSX})
        assert policy.max_bytes == DEFAULT_MAX_RESPONSE_BYTES

    def test_the_ceiling_can_be_tightened_per_source(self) -> None:
        """A per-source limit is the eventual home for this; the default is only a default."""
        policy = DownloadPolicy.from_source(make_source(), max_bytes=4096)
        assert policy.max_bytes == 4096
        assert policy.allowed_formats == frozenset({FileFormat.PDF})

    def test_a_source_permitting_nothing_cannot_exist(self) -> None:
        """The registry refuses it first, so the policy's own guard is defence in depth.

        Worth pinning down which layer says no: the registry model requires at least one format, so
        a source permitting nothing never reaches the downloader. The check in ``DownloadPolicy``
        stays because a policy can also be constructed directly.
        """
        with pytest.raises(ValidationError, match="at least 1 item"):
            make_source(file_formats=())
