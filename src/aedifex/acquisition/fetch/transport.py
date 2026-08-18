"""The transport boundary: the only layer in Aedifex permitted to open a socket.

Deliberately the smallest module in the fetch stack. Its entire job:

.. code-block:: text

    ValidatedTarget
        ↓  open a connection to the validated IP address, and only that address
        ↓  present the original hostname for TLS SNI, certificate verification, and Host
        ↓  send the request
        ↓  return status, headers, and an unread body stream

What it does **not** do, by design: retries, redirect following, backoff, rate limiting,
concurrency accounting, size ceilings, politeness, or anything a crawler would call policy. Those
live in their own modules, are pure wherever they can be, and are tested without a socket. A
transport that also decides *whether to try again* is one whose security behaviour cannot be
reasoned about on its own — and a redirect the transport follows by itself is a request that never
passed the guard.

Security invariants
-------------------

============================  =========================================================
TCP destination               ``target.ip_address`` — already validated, never re-resolved
TLS SNI                       ``target.hostname``
TLS certificate identity      ``target.hostname``
HTTP ``Host`` header           ``target.host_header`` (hostname, plus non-default port)
============================  =========================================================

No DNS resolution happens here. The transport has no resolver, is given none, and cannot obtain
one; the address it connects to was validated during :func:`~aedifex.acquisition.fetch.guard
.validate_url` and travels inside the :class:`~aedifex.acquisition.fetch.guard.ValidatedTarget`.
That is what closes the DNS-rebinding window (FR-107): there is no second lookup for a hostile
answer to win.

The split between the *address* we connect to and the *name* we verify is the security-critical
centre of the design. Verifying a certificate against the IP would defeat the point — the whole
purpose of pinning the address is to keep talking to the host we validated, and only the name can
establish that. Verification can never be switched off: no constructor argument, no setting, and no
registry field reaches it. A source's ``allow_insecure_transport`` permits the plain ``http``
scheme; it has no bearing on TLS verification when the scheme *is* ``https``.

Errors
------

Library exceptions are not our API. ``httpx``, ``httpcore``, ``socket``, and ``ssl`` all raise
their own hierarchies, and letting those reach callers would mean every layer above has to know
which HTTP library we use, and would let a swap silently change retry behaviour. Everything is
converted into the small taxonomy below, and each error carries the
:class:`~aedifex.acquisition.fetch.retry.AttemptOutcome` it classifies as, so retry policy is
decided by the error type itself rather than re-derived by whoever catches it (rule 81d).

.. code-block:: text

    TransportError
    ├── ConnectTimeoutError      → CONNECT_TIMEOUT          retryable
    ├── ReadTimeoutError         → READ_TIMEOUT             retryable
    ├── ConnectionFailedError    → CONNECTION_ERROR         retryable
    ├── TlsVerificationError     → TLS_ERROR                NEVER retryable
    ├── ProtocolError            → PROTOCOL_ERROR           retryable
    ├── ResponseStreamError      → RESPONSE_STREAM_ERROR    retryable
    └── UnclassifiedTransportError → TRANSPORT_UNCLASSIFIED NEVER retryable
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import ClassVar, Final, Protocol, runtime_checkable

from aedifex.acquisition.fetch.guard import ValidatedTarget
from aedifex.acquisition.fetch.retry import AttemptOutcome
from aedifex.acquisition.fetch.timing import TimeoutBudget, TimeoutBudgetExhaustedError
from aedifex.errors import AcquisitionError

__all__ = [
    "ALLOWED_METHODS",
    "DEFAULT_CHUNK_SIZE",
    "BudgetExhaustedError",
    "ConnectTimeoutError",
    "ConnectionFailedError",
    "Deadline",
    "ProtocolError",
    "RawResponse",
    "ReadTimeoutError",
    "ResponseHeaders",
    "ResponseStreamError",
    "TlsVerificationError",
    "Transport",
    "TransportError",
    "TransportTimeouts",
    "UnclassifiedTransportError",
]

ALLOWED_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD"})
"""Aedifex acquires documents; it never submits anything.

An allowlist rather than a convention, because a crawler that can issue a state-changing request
is a crawler that can be pointed at someone's admin endpoint. ``POST`` is not "not yet
implemented" here — it is refused.
"""

DEFAULT_CHUNK_SIZE: Final[int] = 64 * 1024


class TransportError(AcquisitionError):
    """Base class for every failure the transport converts from a library exception.

    Subclasses must declare ``outcome``. That is enforced at class-definition time rather than by a
    test, because the failure mode being prevented is a *new* error type quietly inheriting a
    retry classification it was never given — precisely how a security refusal becomes retryable
    (rule 81d).
    """

    outcome: ClassVar[AttemptOutcome]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "outcome" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must declare its own `outcome`, because retry classification "
                "lives with the error type so no controller can invent one (rule 81d)."
            )


class ConnectTimeoutError(TransportError):
    """The connection could not be established within the connect timeout."""

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.CONNECT_TIMEOUT


class ReadTimeoutError(TransportError):
    """The server accepted the connection but did not deliver data in time."""

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.READ_TIMEOUT


class ConnectionFailedError(TransportError):
    """The connection was refused, reset, or otherwise failed below the HTTP layer."""

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.CONNECTION_ERROR


class TlsVerificationError(TransportError):
    """TLS failed: the certificate did not verify for the hostname, or the handshake failed.

    Never retryable, and not merely as a default. A certificate that does not verify for the name
    we validated means either a misconfigured server or an interception attempt. Neither improves
    on a second attempt, and retrying would convert a security signal into background noise.

    Any TLS-layer failure during connection setup is classified here, not only a certificate
    mismatch. Erring towards refusal is the correct direction inside a security boundary: the cost
    of refusing a fetch is a delayed document, and the cost of the opposite mistake is treating a
    possible interception as a transient blip.
    """

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.TLS_ERROR


class ProtocolError(TransportError):
    """The peer's response violated HTTP framing badly enough that it could not be parsed."""

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.PROTOCOL_ERROR


class ResponseStreamError(TransportError):
    """The body failed part-way through, or an already-consumed stream was read again."""

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.RESPONSE_STREAM_ERROR


class BudgetExhaustedError(TransportError, TimeoutBudgetExhaustedError):
    """The total time allowed for the whole request ran out.

    Inherits from both hierarchies deliberately, rather than duplicating the concept. There is one
    condition here — the operation's time is gone — and two audiences for it: code handling
    transport failures catches :class:`TransportError`, while the retry controller reasons about
    budgets and catches
    :class:`~aedifex.acquisition.fetch.timing.TimeoutBudgetExhaustedError`. Defining two separate
    classes for one condition would guarantee that some ``except`` clause eventually misses one.

    Never retryable, and for a different reason from a TLS failure: retrying is not *unsafe*, it is
    impossible. There is no time left to do it in.
    """

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.BUDGET_EXHAUSTED


class UnclassifiedTransportError(TransportError):
    """A library exception the mapping does not recognise.

    Not retryable. An error we cannot classify cannot be shown to be transient, and the fetch
    boundary treats "unable to decide" as a refusal rather than an omission (rule 81b). If this is
    ever raised in practice it is a defect in the mapping, and the fix is to classify the
    exception explicitly — never to make this case retryable.
    """

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.TRANSPORT_UNCLASSIFIED


@runtime_checkable
class Deadline(Protocol):
    """The read-only face of a time budget, as the transport sees it.

    Narrow on purpose. The transport must be able to ask "is there time left?" without being able
    to extend, reset, or restart anything — resetting a budget across attempts is the exact bug
    :class:`~aedifex.acquisition.fetch.timing.TimeoutBudget` exists to prevent, so the socket layer
    is handed no method that could do it.
    """

    @property
    def remaining_seconds(self) -> float: ...

    def check(self) -> None:
        """Raise if no time remains."""
        ...


@dataclass(frozen=True, slots=True)
class TransportTimeouts:
    """Per-attempt timeouts plus the deadline for the whole operation.

    The transport applies these; it does not decide them, and it cannot construct a budget of its
    own — it takes no :class:`~aedifex.acquisition.fetch.timing.TimeoutPolicy`. That is what keeps a
    total that spans retries from being reset by the layer that opens sockets.

    ``deadline`` carries the total. Without it, per-attempt timeouts alone are escapable: every
    received chunk restarts the read timeout, so a server trickling one byte just inside that window
    holds the connection open indefinitely while never once timing out. The deadline is what makes
    the whole exchange bounded, and it is why this is a required part of the value rather than an
    optional extra a caller might forget — see :meth:`from_budget`.
    """

    connect_seconds: float
    read_seconds: float
    deadline: Deadline | None = None

    def __post_init__(self) -> None:
        if self.connect_seconds <= 0 or self.read_seconds <= 0:
            raise ValueError(
                "timeouts must be positive; a non-positive timeout either means 'no limit' or "
                f"fails immediately depending on the library, and neither is acceptable "
                f"(connect={self.connect_seconds}, read={self.read_seconds})"
            )

    @classmethod
    def from_budget(cls, budget: TimeoutBudget) -> TransportTimeouts:
        """Derive per-attempt timeouts from what remains of the request's total allowance.

        The single supported way to run a real fetch, because it does two things together that are
        wrong to do separately: it clamps this attempt's timeouts to the remaining budget, and it
        attaches the budget as the deadline so the body read is bounded too.

        Raises:
            TimeoutBudgetExhaustedError: if nothing remains, before any socket is opened.
        """
        connect_seconds, read_seconds = budget.attempt_timeouts()
        return cls(
            connect_seconds=connect_seconds,
            read_seconds=read_seconds,
            deadline=budget,
        )


@dataclass(frozen=True, slots=True)
class ResponseHeaders:
    """Response headers as our own type, so no HTTP library's header class becomes our API.

    Order-preserving and duplicate-preserving: ``Set-Cookie`` and ``Via`` may legitimately repeat,
    and a layer that collapses duplicates loses the evidence that they were sent.
    """

    items: tuple[tuple[str, str], ...] = ()

    def get(self, name: str, default: str | None = None) -> str | None:
        """Return the first value for ``name``, matched case-insensitively."""
        wanted = name.lower()
        for key, value in self.items:
            if key.lower() == wanted:
                return value
        return default

    def get_all(self, name: str) -> tuple[str, ...]:
        """Return every value sent for ``name``, in order."""
        wanted = name.lower()
        return tuple(value for key, value in self.items if key.lower() == wanted)

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def __len__(self) -> int:
        return len(self.items)


class RawResponse:
    """A response whose body has not been read.

    Nothing is buffered. The body is available only by iteration, so a caller cannot accidentally
    pull an unbounded payload into memory by touching an attribute, and the size ceiling can be
    enforced while reading rather than after (FR-123).
    """

    __slots__ = (
        "_close",
        "_consumed",
        "_stream",
        "headers",
        "http_version",
        "status_code",
        "target",
    )

    def __init__(
        self,
        *,
        target: ValidatedTarget,
        status_code: int,
        http_version: str,
        headers: ResponseHeaders,
        stream: Callable[[int], Iterator[bytes]],
        close: Callable[[], None],
    ) -> None:
        self.target = target
        self.status_code = status_code
        self.http_version = http_version
        self.headers = headers
        self._stream = stream
        self._close = close
        self._consumed = False

    def iter_bytes(self, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
        """Yield the body in chunks. Consumable exactly once.

        Raises:
            ResponseStreamError: if the body was already consumed, or the stream fails mid-read.
            ValueError: if ``chunk_size`` is not positive.
        """
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if self._consumed:
            raise ResponseStreamError(
                "response body has already been consumed; a stream cannot be re-read, and "
                "silently returning nothing would look like an empty document"
            )
        self._consumed = True
        return self._stream(chunk_size)

    @property
    def body_consumed(self) -> bool:
        """Whether iteration has begun. Useful to assert a caller did not skip the body."""
        return self._consumed


@runtime_checkable
class Transport(Protocol):
    """Opens one connection to one already-validated destination.

    The signature is the boundary: it accepts a :class:`ValidatedTarget` and nothing else. There is
    no overload taking a ``str``, because "remember to validate first" is not a control — the type
    is (FR-100).
    """

    def open(
        self,
        target: ValidatedTarget,
        *,
        timeouts: TransportTimeouts,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
    ) -> AbstractContextManager[RawResponse]:
        """Send one request and return its unread response.

        Returns a context manager because the connection must be released deterministically on
        every path: success, failure, partial consumption of the body, and interruption.
        """
        ...
