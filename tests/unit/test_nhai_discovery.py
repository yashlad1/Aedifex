"""The NHAI adapter, against the responses the live API actually returned.

One test per endpoint, and the payloads below are captured from ``nhai.gov.in`` rather than
invented — the field names, the empty-string conventions, and the duplicated HTTP/HTTPS document
URLs are all verbatim. That is the point: the adapter's only other evidence is a single live run,
and the failure mode it needs protecting from is *silent*. If NHAI renames ``other_documents`` or
moves the URL into ``file_url``, discovery returns zero documents and the run reports success. A red
test is the only thing that turns "the portal changed" into something anybody notices.

Deliberately not exhaustive (rule 19a): this pins the schema contract and the one rule that has real
consequences — take the HTTPS spelling, never the plain-HTTP twin.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import AnyHttpUrl

from aedifex.acquisition.crawl.links import FetchedPage, LinkKind
from aedifex.acquisition.crawl.nhai import NhaiTenderDiscovery
from aedifex.acquisition.registry.models import (
    DataUsePolicy,
    DiscoveryPolicy,
    RetrievalMethod,
    SourceCategory,
    SourceDefinition,
    VerificationStatus,
)
from aedifex.domain.documents import DocumentType
from aedifex.domain.files import FileFormat

API = "https://nhai.gov.in/nhai/api"

# Captured live, 2026-08-18. Two of the ten records, trimmed only in count.
LISTING = json.dumps(
    {
        "_resultflag": 1,
        "total_count": 182,
        "message": "success",
        "list": [
            {
                "id": "58646",
                "title": "Notice Inviting Sealed Quotation for Construction of PQC service road",
                "publish_date": "2026-08-14 05:30:00",
                "tender_no": "NHAI/PIU-Chhapra/2026/1163 ",
                "bid_submission_end_date": "2026-08-21",
                "bid_opening_date": "",
                "tender_document_sales_end": "",
                "tender_document_sales": "",
            },
            {
                "id": "58645",
                "title": "RFP for Consultancy Services",
                "publish_date": "2026-08-14 05:30:00",
                "tender_no": "NHAI/RO-Patna/2026/1162",
                "bid_submission_end_date": "2026-08-28",
                "bid_opening_date": "",
                "tender_document_sales_end": "",
                "tender_document_sales": "",
            },
        ],
    }
)

DETAIL = json.dumps(
    {
        "_resultflag": "1",
        "message": "success",
        "detail": {
            "title": "Notice Inviting Sealed Quotation for Construction of PQC service road",
            "body": "",
            "basic_information": [{"Tender No": "NHAI/PIU-Chhapra/2026/1163 ", "Section": ""}],
            # The named-slot shape, empty as it was on every tender observed.
            "documents": [{"Notice Inviting Tender": "", "Tender Document": "", "Result": ""}],
            "important_dates": [{"Date Published": "2026-08-14 05:30 AM"}],
            "other_documents": [
                {
                    "file": "https://nhai.gov.in/nhai/sites/default/files/2020/NIQ_PIU_Chhapra.pdf",
                    "description": "NIQ",
                    # The same document over plain HTTP. Present on every record.
                    "path": "http://nhai.gov.in/nhai/sites/default/files/2020/NIQ_PIU_Chhapra.pdf",
                    "filesize": "1.11 MB",
                }
            ],
        },
    }
)


def a_source() -> SourceDefinition:
    return SourceDefinition(
        id="nhai",
        name="NHAI",
        country="IN",
        category=SourceCategory.GOVERNMENT_PROCUREMENT,
        retrieval=RetrievalMethod.HTTP_API,
        base_url=AnyHttpUrl("https://nhai.gov.in/"),
        enabled=True,
        verification_status=VerificationStatus.APPROVED,
        crawler="nhai_tenders",
        discovery=DiscoveryPolicy(
            seed_paths=("/nhai/api/tenderlist?language=en&totalrecord=10&index=0",),
            max_depth=2,
            api_post_paths=("/nhai/api/tenderlist", "/nhai/api/tenderdetail"),
        ),
        data_use=DataUsePolicy(
            license="Government of India website content",
            allowed_use="Publicly listed tender notices and their attached documents.",
            reviewed_by="project owner",
            reviewed_on=datetime(2026, 8, 18, tzinfo=UTC),
        ),
        document_types=(DocumentType.TENDER_NOTICE,),
        file_formats=(FileFormat.PDF,),
    )


def strategy() -> NhaiTenderDiscovery:
    return NhaiTenderDiscovery.from_source(a_source())


def test_the_listing_yields_one_detail_page_per_tender_and_the_next_page() -> None:
    """The listing is an index, not a manifest: it carries no document links at all."""
    page = FetchedPage(url=f"{API}/tenderlist?language=en&totalrecord=10&index=0", body=LISTING)
    links = strategy().links(page)

    assert [link.url for link in links] == [
        f"{API}/tenderdetail?language=en&nid=58646",
        f"{API}/tenderdetail?language=en&nid=58645",
        f"{API}/tenderlist?language=en&totalrecord=10&index=10",
    ]
    assert {link.kind for link in links} == {LinkKind.PAGE}
    # Pagination is not depth. Nineteen pages of one listing must not exhaust max_depth.
    assert [link.depth for link in links] == [1, 1, 0]


def test_the_detail_yields_the_https_document_and_refuses_its_plain_http_twin() -> None:
    """The rule with real consequences: taking `path` would make every document unfetchable."""
    page = FetchedPage(url=f"{API}/tenderdetail?language=en&nid=58646", body=DETAIL, depth=1)
    links = strategy().links(page)

    documents = [link for link in links if link.kind is LinkKind.DOCUMENT]
    assert [link.url for link in documents] == [
        "https://nhai.gov.in/nhai/sites/default/files/2020/NIQ_PIU_Chhapra.pdf"
    ]
    refused = [link for link in links if link.kind is LinkKind.IGNORED]
    assert [link.url for link in refused] == [
        "http://nhai.gov.in/nhai/sites/default/files/2020/NIQ_PIU_Chhapra.pdf"
    ]
    assert all(link.reason for link in refused)


def test_the_listing_and_detail_endpoints_are_posted_and_nothing_else_is() -> None:
    """The whole of what replaced "GET only" in the transport.

    A document URL is fetched with a plain GET even though it is on the same approved host, because
    only the two paths named in the registry may carry a body.
    """
    built = strategy()
    listing = built.request_for(f"{API}/tenderlist?language=en&totalrecord=10&index=0")
    assert listing.method == "POST"
    assert listing.body == b"language=en&totalrecord=10&index=0"
    assert (listing.headers or {})["Content-Type"] == "application/x-www-form-urlencoded"

    document = built.request_for("https://nhai.gov.in/nhai/sites/default/files/2020/x.pdf")
    assert document.method == "GET"
    assert document.body is None


def test_an_id_that_is_not_a_number_never_reaches_a_request() -> None:
    """The only value from a response that is interpolated into a body we send."""
    hostile = json.dumps(
        {"total_count": 1, "list": [{"id": "58646 OR 1=1"}, {"id": "../../etc/passwd"}]}
    )
    page = FetchedPage(url=f"{API}/tenderlist?language=en&totalrecord=10&index=0", body=hostile)
    assert strategy().links(page) == ()


def test_a_body_that_is_not_json_is_reported_rather_than_raised() -> None:
    """A portal answering with a maintenance page must not end the run."""
    body = "<html>down for maintenance</html>"
    page = FetchedPage(url=f"{API}/tenderlist?language=en", body=body)
    (link,) = strategy().links(page)
    assert link.kind is LinkKind.IGNORED
    assert link.reason == "response was not JSON"
