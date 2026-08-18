"""The frontier queue against real PostgreSQL: leasing and canonical deduplication.

Deliberately small. Both properties here need a real database — ``FOR UPDATE SKIP LOCKED`` has no
meaning without one — and everything else about the queue is bookkeeping that would pass against a
fake and prove nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from aedifex.acquisition.canonical import canonical_url, url_digest
from aedifex.acquisition.crawl.frontier import Candidate, FrontierQueue
from aedifex.domain.documents import DocumentState
from aedifex.infrastructure.database.models import DiscoveredUrl

pytestmark = pytest.mark.integration

SOURCE = "cpwd"


def queue(worker: str = "worker-a", **kwargs: object) -> FrontierQueue:
    return FrontierQueue(source_id=SOURCE, worker=worker, **kwargs)  # type: ignore[arg-type]


def test_two_spellings_of_one_url_become_one_row(session: Session) -> None:
    """The regression this exists for is a wasted request, not a wrong corpus.

    Content addressing means fetching one document twice still stores it once, so the symptom is
    invisible in the data and shows up only as traffic against a portal we are being polite to. The
    acquirer used to hash the URL exactly as passed in, which made these three URLs three rows.

    Query order and trailing slashes are *not* collapsed, and that is the other half of the
    property: both can change which document a portal serves.
    """
    result = queue().enqueue(
        session,
        [
            Candidate(url="https://cpwd.test/tenders/a.pdf"),
            Candidate(url="https://cpwd.test/tenders/a.pdf#page=2"),
            Candidate(url="HTTPS://CPWD.TEST:443/tenders/a.pdf"),
            Candidate(url="https://cpwd.test/tenders/a.pdf/"),
        ],
    )
    assert result.accepted == 2
    row = session.query(DiscoveredUrl).filter_by(url="https://cpwd.test/tenders/a.pdf").one()
    assert row.url_sha256 == url_digest(canonical_url("https://cpwd.test/tenders/a.pdf#page=2"))


def test_a_url_that_can_never_be_fetched_is_refused_rather_than_stored(session: Session) -> None:
    """A stored unfetchable URL is claimed, attempted, and failed on every pass of every run."""
    result = queue().enqueue(
        session,
        [Candidate(url="javascript:alert(1)"), Candidate(url="https://cpwd.test/good.pdf")],
    )
    assert result.accepted == 1
    assert len(result.rejected) == 1


def test_two_workers_never_hold_the_same_url(engine: Engine) -> None:
    """The property the whole design rests on, and it needs two real transactions.

    ``SKIP LOCKED`` means the second worker steps over rows the first has locked rather than
    blocking on them. Two sessions, because a session cannot lock a row against itself.
    """
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as first, factory() as second:
        try:
            queue().enqueue(first, [Candidate(url=f"https://cpwd.test/{i}.pdf") for i in range(4)])
            first.commit()

            mine = queue("worker-a").claim(first, limit=2)
            theirs = queue("worker-b").claim(second, limit=4)
            first.commit()
            second.commit()

            assert len(mine) == 2
            assert len(theirs) == 2, "the two rows worker-a locked must have been skipped"
            assert {row.url for row in mine}.isdisjoint({row.url for row in theirs})
        finally:
            first.rollback()
            first.execute(delete(DiscoveredUrl))
            first.commit()


def test_a_leased_url_is_not_claimed_twice_and_traversal_is_deterministic(
    session: Session,
) -> None:
    """Shallow first, then by discovery time, so a resumed crawl continues rather than restarts."""
    frontier = queue()
    frontier.enqueue(
        session,
        [
            Candidate(url="https://cpwd.test/deep.pdf", depth=3),
            Candidate(url="https://cpwd.test/shallow.pdf", depth=0),
        ],
    )
    claimed = frontier.claim(session, limit=2)
    assert [row.url for row in claimed] == [
        "https://cpwd.test/shallow.pdf",
        "https://cpwd.test/deep.pdf",
    ]
    assert frontier.claim(session, limit=2) == ()
    assert claimed[0].lease_owner == "worker-a"
    # A lease is not a state change: the acquirer still owns the document state machine.
    assert claimed[0].state is DocumentState.DISCOVERED


def test_a_dead_worker_does_not_hold_its_url_forever(session: Session) -> None:
    """Lease expiry is the only thing separating a crashed worker from work still in flight.

    Recovery charges an attempt: it is the honest record — we tried and do not know what happened —
    and it is what stops a URL that kills its worker from being reclaimed forever. After
    ``max_attempts`` it dead-letters and waits for a person (rule 47).
    """
    frontier = queue(max_attempts=2)
    frontier.enqueue(session, [Candidate(url="https://cpwd.test/poison.pdf")])

    for expected_attempts in (1, 2):
        (claimed,) = frontier.claim(session, limit=1)
        claimed.state = DocumentState.DOWNLOADING
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.flush()
        assert frontier.reclaim_expired(session) == 1
        session.expire_all()
        row = session.query(DiscoveredUrl).one()
        assert row.state is DocumentState.FAILED
        assert row.attempts == expected_attempts
        assert row.error_type == "lease_expired"
        assert row.lease_owner is None

    assert row.dead_lettered_at is not None
    assert frontier.claim(session, limit=1) == ()
    assert frontier.pending(session) == 0
