"""The whole fetch stack against a hostile local server.

Every layer below this has its own tests: the guard, the pure policies, the transport, the retry
controller, the redirect controller. What none of them can show is what the *composition* does when
a real server misbehaves — whether the layers' assumptions about each other survive contact with
sockets, framing errors, and a server that lies about the size of what it is sending.

.. code-block:: text

    validate_url  ->  RedirectController  ->  RetryController  ->  HttpxTransport  ->  socket
                          per-hop guard        per-attempt slot      one request

So these tests bind real loopback sockets and drive the assembled stack. Two harnesses, because
they answer different questions:

* a routed HTTP server, for behaviour a conforming server can produce — statuses, redirect chains,
  ``Retry-After``, stalls, oversized bodies;
* a raw TCP server, for behaviour it cannot — a garbage status line, a negative ``Content-Length``,
  a header with no colon, an abrupt reset.

They are unit tests by this project's definition: no PostgreSQL, no object storage, nothing shared,
and they run in a few seconds. They live here rather than under ``tests/integration`` for the same
reason ``test_fetch_transport.py`` does.

**Every assertion about wire behaviour here was measured before it was written.** Several plausible
expectations turned out to be wrong — a ``Location`` carrying a raw CRLF never reaches us intact
because ``h11`` splits it into two headers, and an obs-folded one arrives joined with a space rather
than rejected. Those are recorded as tests stating what actually happens, because a suite that
asserts what we assumed proves only that we are consistent.

Not covered here, deliberately: the ``https`` → ``http`` downgrade rule, which is pure policy with
full coverage in ``test_fetch_redirects.py`` and ``test_fetch_redirect_controller.py``. Adding a
second TLS harness would not put a new claim on the wire.
"""

from __future__ import annotations

import contextlib
import socket
import struct
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from typing import Any, cast

import pytest

from aedifex.acquisition.fetch import guard as guard_module
from aedifex.acquisition.fetch import urls as urls_module
from aedifex.acquisition.fetch.addresses import IpAddress, classify_address
from aedifex.acquisition.fetch.controller import (
    FetchCancelledError,
    FetchFailedError,
    RetryController,
)
from aedifex.acquisition.fetch.guard import ValidatedTarget, validate_url
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.httpx_transport import HttpxTransport
from aedifex.acquisition.fetch.ratelimit import RateLimiter, RateLimits
from aedifex.acquisition.fetch.redirect_controller import (
    RedirectController,
    RedirectRejectedError,
)
from aedifex.acquisition.fetch.redirects import RedirectPolicy
from aedifex.acquisition.fetch.resolver import ResolvedAddress
from aedifex.acquisition.fetch.retry import AttemptOutcome, BackoffPolicy, RetryPolicy
from aedifex.acquisition.fetch.timing import (
    MonotonicClock,
    SystemRandomSource,
    TimeoutBudget,
    TimeoutPolicy,
)
from aedifex.acquisition.fetch.transport import (
    BudgetExhaustedError,
    ReadTimeoutError,
    ResponseTooLargeError,
    TransportError,
)
from aedifex.acquisition.fetch.urls import SsrfRejectionError

HOSTNAME = "example.test"
OTHER_HOSTNAME = "docs.example.test"
USER_AGENT = "AedifexBot/0.1 (+mailto:ops@example.org)"
LOOPBACK = "127.0.0.1"

# Politeness limits that never make a test wait. The limiter's own behaviour is verified in
# test_fetch_ratelimit.py with a fake clock; here it must simply not interfere.
OPEN_LIMITS = RateLimits(requests_per_minute=600, max_concurrency=4, min_delay_seconds=0.0)

# Small enough that a full retry sequence costs a fraction of a second, large enough that a real
# sleep is still a real sleep.
FAST_BACKOFF = BackoffPolicy(base_seconds=0.05, factor=2.0, max_delay_seconds=0.2, max_attempts=3)


# ---------------------------------------------------------------------------
# A routed HTTP server
# ---------------------------------------------------------------------------

Responder = Callable[[BaseHTTPRequestHandler], None]


@dataclass(frozen=True)
class RecordedRequest:
    """What the server actually received, as opposed to what we believe we sent."""

    method: str
    path: str
    host_header: str | None
    headers: Mapping[str, str]


class _RoutedServer(ThreadingHTTPServer):
    """Serves a scripted queue of responses per path.

    Per path, because a redirect chain is a sequence of *different* paths, and a retry is a sequence
    of *different answers to the same path*. Both shapes are needed, so the routing table holds a
    queue for each path and the last entry repeats once the queue is down to one.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, routes: Mapping[str, list[Responder]]) -> None:
        super().__init__((LOOPBACK, 0), _Handler)
        self.routes = {path: list(queue) for path, queue in routes.items()}
        self.recorded: list[RecordedRequest] = []
        self.suppressed_errors: list[BaseException] = []

    def next_responder(self, path: str) -> Responder:
        queue = self.routes.get(path)
        if not queue:
            return status_only(404)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Record the disconnects these tests deliberately cause, instead of printing a traceback.

        Narrow on purpose: anything outside the disconnect family still prints, because a silenced
        server would turn a genuine handler bug into a passing test.
        """
        import sys

        error = sys.exc_info()[1]
        if isinstance(error, ConnectionResetError | BrokenPipeError | TimeoutError):
            self.suppressed_errors.append(error)
            return
        super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self) -> None:
        server = cast(_RoutedServer, self.server)
        path = self.path
        server.recorded.append(
            RecordedRequest(
                method=self.command,
                path=path,
                host_header=self.headers.get("Host"),
                headers={key.lower(): value for key, value in self.headers.items()},
            )
        )
        server.next_responder(path)(self)

    # Names dictated by BaseHTTPRequestHandler's dispatch, so the naming rule does not apply.
    do_GET = _handle  # noqa: N815
    do_HEAD = _handle  # noqa: N815

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence the default stderr logging; failures are asserted, not read."""


def body_response(body: bytes = b"payload", status: int = 200) -> Responder:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Content-Type", "application/pdf")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(body)

    return respond


def status_only(status: int, *, headers: Sequence[tuple[str, str]] = ()) -> Responder:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        for name, value in headers:
            handler.send_header(name, value)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    return respond


def redirect_to(location: str, status: int = 302) -> Responder:
    return status_only(status, headers=(("Location", location),))


def retry_after(value: str, status: int = 503) -> Responder:
    return status_only(status, headers=(("Retry-After", value),))


def stall_before_headers(seconds: float, body: bytes = b"late") -> Responder:
    """Accept the connection, then say nothing at all.

    The read timeout fires while the response is being *established*, so the failure reaches the
    retry controller and can be retried. Distinguished from :func:`stall_after_headers` because the
    two land on opposite sides of the boundary in :class:`TestWhereFailuresSurface`.
    """

    def respond(handler: BaseHTTPRequestHandler) -> None:
        threading.Event().wait(seconds)
        with contextlib.suppress(OSError):
            handler.send_response(200)
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

    return respond


def stall_after_headers(seconds: float, body: bytes = b"late") -> Responder:
    """Send headers, then go quiet. The failure lands in the caller's body iteration."""

    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.flush()
        threading.Event().wait(seconds)
        with contextlib.suppress(OSError):
            handler.wfile.write(body)

    return respond


def drip(interval: float = 0.02, declared: int = 10_000_000, stop_after: int = 200) -> Responder:
    """One byte at a time, never pausing long enough to trip a read timeout.

    The reason a total budget exists: while each write lands inside the read timeout, no per-read
    timeout ever fires and the connection is held for as long as the server likes. ``stop_after`` is
    a safety stop for the suite rather than part of the scenario — without it, a regression that
    removed the deadline check would hang the run instead of failing it (rule 81g).
    """

    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Length", str(declared))
        handler.end_headers()
        handler.wfile.flush()
        with contextlib.suppress(OSError):
            for _ in range(stop_after):
                handler.wfile.write(b"x")
                handler.wfile.flush()
                threading.Event().wait(interval)

    return respond


def chunked(total: int, chunk: int = 512) -> Responder:
    """A body with no ``Content-Length``, so the running total is the only protection there is."""

    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        handler.wfile.flush()
        remaining = total
        with contextlib.suppress(OSError):
            while remaining > 0:
                size = min(chunk, remaining)
                handler.wfile.write(f"{size:x}\r\n".encode() + b"z" * size + b"\r\n")
                handler.wfile.flush()
                remaining -= size
            handler.wfile.write(b"0\r\n\r\n")

    return respond


# ---------------------------------------------------------------------------
# A raw TCP server, for responses no HTTP library would produce
# ---------------------------------------------------------------------------


class RawServer:
    """Writes fixed bytes and closes, or resets the connection without answering.

    ``payloads`` is consumed one per connection, the last entry repeating, so a retry sequence can
    be scripted at the byte level.
    """

    def __init__(self, payloads: Sequence[bytes] | None, *, reset: bool = False) -> None:
        self._payloads = list(payloads) if payloads is not None else []
        self._reset = reset
        self.connections = 0
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((LOOPBACK, 0))
        self._socket.listen(8)
        self.port = int(self._socket.getsockname()[1])
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while self._running:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            self.connections += 1
            try:
                connection.recv(4096)
                if self._reset:
                    # SO_LINGER with a zero timeout sends RST instead of FIN, which is what a
                    # load balancer dropping a connection actually looks like.
                    connection.setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                    )
                elif self._payloads:
                    payload = (
                        self._payloads.pop(0) if len(self._payloads) > 1 else self._payloads[0]
                    )
                    connection.sendall(payload)
            except OSError:
                pass
            finally:
                with contextlib.suppress(OSError):
                    connection.close()

    def close(self) -> None:
        self._running = False
        with contextlib.suppress(OSError):
            self._socket.close()


# ---------------------------------------------------------------------------
# The assembled stack
# ---------------------------------------------------------------------------


@dataclass
class RecordingSleeper:
    """Really sleeps, and writes down what it was asked to wait for.

    Real sleeping, because the point of this file is that the composition works against real time
    and real sockets. The delays are kept small by :data:`FAST_BACKOFF` rather than by faking the
    clock, which the layer-level tests already do.
    """

    slept: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        if seconds > 0:
            time.sleep(seconds)


class MappingResolver:
    """Scripted DNS pointing every test hostname at the loopback server, recording each lookup."""

    def __init__(self, hosts: Sequence[str]) -> None:
        self._hosts = set(hosts)
        self.lookups: list[str] = []

    def resolve(self, hostname: str, port: int) -> Sequence[ResolvedAddress]:
        self.lookups.append(hostname)
        if hostname not in self._hosts:
            raise OSError(f"no scripted DNS entry for {hostname!r}")
        return (ResolvedAddress(ip=ip_address(LOOPBACK), port=port),)


@dataclass
class Stack:
    server: _RoutedServer
    transport: HttpxTransport
    fetcher: RetryController
    redirects: RedirectController
    sleeper: RecordingSleeper
    resolver: MappingResolver

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def recorded(self) -> list[RecordedRequest]:
        return self.server.recorded

    @property
    def paths(self) -> list[str]:
        return [request.path for request in self.server.recorded]

    def target(self, path: str = "/doc.pdf", *, hostname: str = HOSTNAME) -> ValidatedTarget:
        """Build the target the guard would have produced for a server we control.

        Constructed directly, as in the transport tests, because the guard correctly refuses both
        loopback addresses and non-standard ports — that is its job, and it has its own tests. The
        redirect tests below cannot do this, since the controller validates internally; they use
        :func:`permit_the_test_server` and assert that the exemption stays narrow.
        """
        address = ip_address(LOOPBACK)
        return ValidatedTarget(
            url=f"http://{hostname}:{self.port}{path}",
            scheme="http",
            hostname=hostname,
            port=self.port,
            ip_address=address,
            source_id="test-source",
            validated_addresses=(address,),
        )

    def url(self, path: str = "/doc.pdf", *, hostname: str = HOSTNAME) -> str:
        return f"http://{hostname}:{self.port}{path}"

    def budget(
        self, *, total: float = 10.0, connect: float = 2.0, read: float = 2.0
    ) -> TimeoutBudget:
        return TimeoutBudget(
            policy=TimeoutPolicy(connect_seconds=connect, read_seconds=read, total_seconds=total),
            clock=MonotonicClock(),
        )


@contextmanager
def stack(
    routes: Mapping[str, list[Responder]],
    *,
    max_attempts: int = 3,
    max_hops: int = 5,
    hosts: Sequence[str] = (HOSTNAME, OTHER_HOSTNAME),
) -> Iterator[Stack]:
    server = _RoutedServer(routes)
    # serve_forever polls its selector on this interval and shutdown() waits for the current poll to
    # return, so the default 0.5s was charged to every test in this file as pure teardown — more
    # than the work most of them do. Measured: 33s for the file before, 3s after.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.daemon = True
    thread.start()
    sleeper = RecordingSleeper()
    resolver = MappingResolver(hosts)
    try:
        # A transport per test, so nothing is shared. Measured at 4.2ms to build, which is not worth
        # trading for shared state — the suite's cost was the poll interval above, not this.
        with HttpxTransport(user_agent=USER_AGENT) as transport:
            fetcher = RetryController(
                transport=transport,
                limiter=RateLimiter(global_concurrency=4),
                policy=RetryPolicy(
                    backoff=BackoffPolicy(
                        base_seconds=FAST_BACKOFF.base_seconds,
                        factor=FAST_BACKOFF.factor,
                        max_delay_seconds=FAST_BACKOFF.max_delay_seconds,
                        max_attempts=max_attempts,
                    )
                ),
                randomness=SystemRandomSource(),
                clock=MonotonicClock(),
                sleeper=sleeper,
            )
            yield Stack(
                server=server,
                transport=transport,
                fetcher=fetcher,
                redirects=RedirectController(
                    controller=fetcher,
                    resolver=resolver,
                    policy=RedirectPolicy(max_hops=max_hops),
                ),
                sleeper=sleeper,
                resolver=resolver,
            )
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def raw_stack(
    payloads: Sequence[bytes] | None, *, reset: bool = False, max_attempts: int = 2
) -> Iterator[tuple[RawServer, RetryController, RecordingSleeper]]:
    server = RawServer(payloads, reset=reset)
    sleeper = RecordingSleeper()
    try:
        with HttpxTransport(user_agent=USER_AGENT) as transport:
            yield (
                server,
                RetryController(
                    transport=transport,
                    limiter=RateLimiter(global_concurrency=4),
                    policy=RetryPolicy(
                        backoff=BackoffPolicy(
                            base_seconds=0.02,
                            factor=2.0,
                            max_delay_seconds=0.05,
                            max_attempts=max_attempts,
                        )
                    ),
                    randomness=SystemRandomSource(),
                    clock=MonotonicClock(),
                    sleeper=sleeper,
                ),
                sleeper,
            )
    finally:
        server.close()


def raw_target(port: int, path: str = "/doc.pdf") -> ValidatedTarget:
    address = ip_address(LOOPBACK)
    return ValidatedTarget(
        url=f"http://{HOSTNAME}:{port}{path}",
        scheme="http",
        hostname=HOSTNAME,
        port=port,
        ip_address=address,
        source_id="test-source",
        validated_addresses=(address,),
    )


def raw_budget(total: float = 10.0) -> TimeoutBudget:
    return TimeoutBudget(
        policy=TimeoutPolicy(connect_seconds=2.0, read_seconds=2.0, total_seconds=total),
        clock=MonotonicClock(),
    )


HOST_POLICY = SourceHostPolicy(
    source_id="test-source",
    base_hosts=frozenset({HOSTNAME}),
    exact_hosts=frozenset(),
)


def permit_the_test_server(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    """Let the real guard validate a URL that names our own loopback server.

    The redirect controller validates internally — deliberately, because an injectable validator
    would be an injectable bypass — so a chain cannot be driven over real HTTP without the guard
    accepting the destination. Two things stand in the way, and both are the guard working
    correctly: an ephemeral port is not in ``ALLOWED_PORTS``, and ``127.0.0.1`` is loopback.

    So exactly two exemptions are granted: this one port, and this one address. Everything else
    stays live, which is asserted rather than assumed — see
    :meth:`TestRedirectChainsOverTheWire.test_the_exemption_does_not_disable_the_address_policy`.
    """
    monkeypatch.setattr(urls_module, "ALLOWED_PORTS", urls_module.ALLOWED_PORTS | {port})

    def only_our_loopback(address: IpAddress) -> object:
        if str(address) == LOOPBACK:
            return None
        return classify_address(address)

    monkeypatch.setattr(guard_module, "classify_address", only_our_loopback)


# ---------------------------------------------------------------------------
# Nothing happens that we did not ask for
# ---------------------------------------------------------------------------


class TestNoHiddenClientBehaviour:
    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_the_client_never_follows_a_redirect_on_its_own(self, status: int) -> None:
        """FR-110 through the assembled stack, not only through the transport.

        The redirect is handed back as a response and the server sees exactly one request. If httpx
        were following redirects, the second path would appear in the server's log.
        """
        with stack(
            {"/a": [redirect_to("/final", status)], "/final": [body_response(b"secret")]}
        ) as s:
            with s.fetcher.fetch(s.target("/a"), limits=OPEN_LIMITS, budget=s.budget()) as result:
                assert result.response.status_code == status
                assert result.response.headers.get("location") == "/final"
            assert s.paths == ["/a"], "the client followed a redirect by itself"

    def test_the_client_never_retries_on_its_own(self) -> None:
        """httpcore would spend 0.5s on its first internal retry; the attempt cap is ours alone."""
        # A port with nothing listening. Bound and closed, so nothing can start using it.
        probe = socket.socket()
        probe.bind((LOOPBACK, 0))
        closed_port = int(probe.getsockname()[1])
        probe.close()

        with stack({}, max_attempts=1) as s:
            address = ip_address(LOOPBACK)
            target = ValidatedTarget(
                url=f"http://{HOSTNAME}:{closed_port}/doc.pdf",
                scheme="http",
                hostname=HOSTNAME,
                port=closed_port,
                ip_address=address,
                source_id="test-source",
                validated_addresses=(address,),
            )
            started = time.monotonic()
            with (
                pytest.raises(FetchFailedError) as caught,
                s.fetcher.fetch(target, limits=OPEN_LIMITS, budget=s.budget()),
            ):
                pass
            elapsed = time.monotonic() - started

        assert caught.value.final_outcome is AttemptOutcome.CONNECTION_ERROR
        assert len(caught.value.attempts) == 1
        assert elapsed < 0.4, f"took {elapsed:.3f}s, long enough to be a hidden retry"

    def test_a_head_request_sends_no_body_and_reads_none(self) -> None:
        with stack({"/doc.pdf": [body_response(b"payload")]}) as s:
            with s.fetcher.fetch(
                s.target(), limits=OPEN_LIMITS, budget=s.budget(), method="HEAD"
            ) as result:
                assert result.response.status_code == 200
                assert result.response.declared_content_length == 7
                assert b"".join(result.response.iter_bytes()) == b""
            assert [request.method for request in s.recorded] == ["HEAD"]

    def test_the_user_agent_identifies_the_crawler(self) -> None:
        """A site operator is entitled to know who is calling and how to reach us."""
        with stack({"/doc.pdf": [body_response()]}) as s:
            with s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()):
                pass
            assert s.recorded[0].headers["user-agent"] == USER_AGENT
            assert s.recorded[0].host_header == f"{HOSTNAME}:{s.port}"


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------


class TestStatusHandling:
    def test_a_retryable_status_is_retried_until_it_succeeds(self) -> None:
        with stack(
            {"/doc.pdf": [status_only(503), status_only(503), body_response(b"finally")]}
        ) as s:
            with s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()) as result:
                assert b"".join(result.response.iter_bytes()) == b"finally"

            assert len(s.paths) == 3
            assert result.attempt_count == 3
            assert len(s.sleeper.slept) == 2, "a backoff was skipped between attempts"

    @pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
    def test_each_retryable_status_is_retried(self, status: int) -> None:
        with stack({"/doc.pdf": [status_only(status)]}, max_attempts=2) as s:
            with (
                pytest.raises(FetchFailedError) as caught,
                s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()),
            ):
                pass
            assert len(s.paths) == 2, f"HTTP {status} was not retried"
        assert caught.value.final_outcome is AttemptOutcome.HTTP_STATUS

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 410, 451, 501, 505])
    def test_each_permanent_status_is_not_retried(self, status: int) -> None:
        with stack({"/doc.pdf": [status_only(status)]}) as s:
            with (
                pytest.raises(FetchFailedError) as caught,
                s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()),
            ):
                pass
            assert len(s.paths) == 1, f"HTTP {status} was retried"
            assert s.sleeper.slept == []
        assert "permanent" in str(caught.value)

    def test_an_unfamiliar_status_fails_closed(self) -> None:
        """No policy for it means no retry. Hammering an endpoint we do not understand is worse."""
        with stack({"/doc.pdf": [status_only(418)]}) as s:
            with (
                pytest.raises(FetchFailedError) as caught,
                s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()),
            ):
                pass
            assert len(s.paths) == 1
        assert "no retry policy" in str(caught.value)

    @pytest.mark.parametrize("status", [200, 201, 204, 206])
    def test_a_success_is_handed_straight_back(self, status: int) -> None:
        with stack({"/doc.pdf": [body_response(b"ok", status=status)]}) as s:
            with s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()) as result:
                assert result.response.status_code == status
            assert len(s.paths) == 1


# ---------------------------------------------------------------------------
# Retry-After, as a real header
# ---------------------------------------------------------------------------


class TestRetryAfterOverTheWire:
    def test_zero_retries_without_touching_the_sleeper(self) -> None:
        with stack({"/doc.pdf": [retry_after("0"), body_response(b"ok")]}) as s:
            with s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()) as result:
                assert result.response.status_code == 200
            assert s.sleeper.slept == [], "a zero delay should not reach the sleeper at all"
            assert len(s.paths) == 2

    def test_a_short_requested_delay_is_honoured_exactly(self) -> None:
        """One real second of waiting, because the claim is that we wait when asked to."""
        with stack({"/doc.pdf": [retry_after("1"), body_response(b"ok")]}) as s:
            started = time.monotonic()
            with s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()):
                pass
            elapsed = time.monotonic() - started

            assert s.sleeper.slept == [1.0]
            assert elapsed >= 1.0, "the delay was recorded but not taken"

    def test_an_absurd_requested_delay_abandons_rather_than_parking_a_worker(self) -> None:
        """``Retry-After: 86400``. Not clamped to the cap and retried early — abandoned.

        Returning before the server said it would be ready is impolite and the most direct route to
        being blocked. A scheduler can come back later, which is what the server asked for.
        """
        with stack({"/doc.pdf": [retry_after("86400"), body_response(b"ok")]}) as s:
            with (
                pytest.raises(FetchFailedError) as caught,
                s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()),
            ):
                pass
            assert s.sleeper.slept == []
            assert len(s.paths) == 1
        assert "over the" in str(caught.value)

    def test_a_past_http_date_retries_immediately(self) -> None:
        past = formatdate(time.time() - 3600, usegmt=True)
        with stack({"/doc.pdf": [retry_after(past), body_response(b"ok")]}) as s:
            with s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()) as result:
                assert result.response.status_code == 200
            assert s.sleeper.slept == [], "a past date became a wait"

    def test_a_far_future_http_date_abandons(self) -> None:
        future = formatdate(time.time() + 86_400, usegmt=True)
        with stack({"/doc.pdf": [retry_after(future), body_response(b"ok")]}) as s:
            with (
                pytest.raises(FetchFailedError),
                s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()),
            ):
                pass
            assert s.sleeper.slept == []
            assert len(s.paths) == 1

    def test_duplicate_values_take_the_first_rather_than_the_longer(self) -> None:
        """Measured: duplicate headers arrive joined as ``"1, 86400"``.

        Taking the larger would let a server extend its own hold by appending a value; taking the
        first is what the header means. Asserted through the wire rather than only in the parser,
        because "arrives joined" is an assumption about the HTTP stack, not about our code.
        """
        with stack({"/doc.pdf": [retry_after("1, 86400"), body_response(b"ok")]}) as s:
            with s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()) as result:
                assert result.response.status_code == 200
            assert s.sleeper.slept == [1.0]

    def test_an_unparseable_value_falls_back_to_computed_backoff(self) -> None:
        """Unparseable means "no instruction" — not "retry now" and not "wait forever"."""
        with stack({"/doc.pdf": [retry_after("soon please"), body_response(b"ok")]}) as s:
            with s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()):
                pass
            assert len(s.sleeper.slept) == 1
            assert 0.0 < s.sleeper.slept[0] <= FAST_BACKOFF.base_seconds

    def test_a_retry_after_on_a_permanent_status_does_not_make_it_retryable(self) -> None:
        """A hostile server offering a friendly header must not reopen a closed decision."""
        with stack({"/doc.pdf": [retry_after("1", status=403), body_response(b"ok")]}) as s:
            with (
                pytest.raises(FetchFailedError) as caught,
                s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget()),
            ):
                pass
            assert len(s.paths) == 1
            assert s.sleeper.slept == []
        assert "permanent" in str(caught.value)


# ---------------------------------------------------------------------------
# Slow servers
# ---------------------------------------------------------------------------


class TestWhereFailuresSurface:
    """The boundary between a fetch's two halves, which this suite discovered rather than assumed.

    A fetch has two phases and they fail differently:

    .. code-block:: text

        establishing the response   ->  RetryController catches it  ->  FetchFailedError, with
        (connect, request, headers)     classifies, may retry           the attempt history

        consuming the body          ->  nobody catches it           ->  the transport's own typed
        (inside the caller's with)      the caller is mid-iteration     error, carrying .outcome

    The second half is not an oversight. Once the response has been handed over, the caller may
    already have written bytes to disk, so a retry is not the controller's to make — and the typed
    error still carries the same ``outcome``, so the classification is not lost. But it does mean a
    caller that only catches ``FetchFailedError`` will be surprised by a body that fails half way,
    which is the downloader's problem to handle deliberately rather than discover.
    """

    def test_a_failure_while_establishing_the_response_becomes_a_fetch_failure(self) -> None:
        with stack({"/doc.pdf": [stall_before_headers(1.0)]}, max_attempts=2) as s:
            with (
                pytest.raises(FetchFailedError) as caught,
                s.fetcher.fetch(s.target(), limits=OPEN_LIMITS, budget=s.budget(read=0.2)),
            ):
                pass

            assert caught.value.final_outcome is AttemptOutcome.READ_TIMEOUT
            assert len(caught.value.attempts) == 2, "the history of a retried failure is kept"

    def test_a_failure_while_reading_the_body_reaches_the_caller_untranslated(self) -> None:
        with stack({"/doc.pdf": [stall_after_headers(2.0)]}) as s:
            with (
                pytest.raises(ReadTimeoutError) as caught,
                s.fetcher.fetch(
                    s.target(), limits=OPEN_LIMITS, budget=s.budget(read=0.2)
                ) as result,
            ):
                b"".join(result.response.iter_bytes())

            assert isinstance(caught.value, TransportError)
            assert caught.value.outcome is AttemptOutcome.READ_TIMEOUT
            assert len(s.paths) == 1, "a body failure was retried behind the caller's back"

    def test_a_body_failure_is_not_a_fetch_failure(self) -> None:
        """Stated explicitly, because a caller writing ``except FetchFailedError`` would miss it."""
        with stack({"/doc.pdf": [stall_after_headers(2.0)]}) as s:
            with (
                pytest.raises(TransportError) as caught,
                s.fetcher.fetch(
                    s.target(), limits=OPEN_LIMITS, budget=s.budget(read=0.2)
                ) as result,
            ):
                b"".join(result.response.iter_bytes())

            assert not isinstance(caught.value, FetchFailedError)
            assert len(s.paths) == 1


class TestSlowServers:
    def test_a_stall_before_the_headers_is_retried_and_can_succeed(self) -> None:
        """A read timeout while establishing the response is transient, so it earns a second try."""
        with stack(
            {"/doc.pdf": [stall_before_headers(1.0), body_response(b"second time lucky")]}
        ) as s:
            with s.fetcher.fetch(
                s.target(), limits=OPEN_LIMITS, budget=s.budget(read=0.3)
            ) as result:
                assert b"".join(result.response.iter_bytes()) == b"second time lucky"

            assert result.attempts[0].outcome is AttemptOutcome.READ_TIMEOUT
            assert result.attempt_count == 2

    def test_a_drip_feed_is_stopped_by_the_total_budget(self) -> None:
        """The attack a per-read timeout cannot see: every read is prompt, the exchange is endless.

        This one found a defect. The size and deadline checks used to run once per chunk *yielded*,
        and ``httpx.iter_bytes(n)`` buffers until it holds ``n`` bytes — so with the 256 KB
        default a one-byte drip never reached a checkpoint and the budget was never consulted.
        The transport's own test had passed because it read with a chunk size of one, which made
        every byte a checkpoint by accident. The checks now run as bytes arrive, and this reads with
        the default chunk size on purpose, so a regression to per-yield checking fails here.
        """
        with stack({"/doc.pdf": [drip(interval=0.02, stop_after=2000)]}) as s:
            started = time.monotonic()
            with (
                pytest.raises(BudgetExhaustedError) as caught,
                s.fetcher.fetch(
                    s.target(),
                    limits=OPEN_LIMITS,
                    budget=s.budget(total=0.8, connect=0.3, read=0.5),
                ) as result,
            ):
                for _ in result.response.iter_bytes():
                    pass
            elapsed = time.monotonic() - started

            assert caught.value.outcome is AttemptOutcome.BUDGET_EXHAUSTED
            assert len(s.paths) == 1, "a dying server was asked again"
            # The drip alone would run for 40s. The budget is what ends it.
            assert elapsed < 3.0, f"took {elapsed:.3f}s; the budget did not bound the exchange"


# ---------------------------------------------------------------------------
# Oversized bodies
# ---------------------------------------------------------------------------


class TestOversizedBodies:
    def test_a_declared_oversize_is_refused_before_the_body_arrives(self) -> None:
        with stack({"/doc.pdf": [body_response(b"x" * 4096)]}) as s:
            with (
                pytest.raises(FetchFailedError) as caught,
                s.fetcher.fetch(
                    s.target(), limits=OPEN_LIMITS, budget=s.budget(), max_response_bytes=1024
                ),
            ):
                pass
            assert len(s.paths) == 1, "an oversized response was requested again"
            assert s.sleeper.slept == []
        assert caught.value.final_outcome is AttemptOutcome.OVERSIZED_RESPONSE

    def test_an_undeclared_oversize_is_stopped_while_streaming(self) -> None:
        """No ``Content-Length`` to check, so the running total is the only protection.

        The refusal must arrive during iteration — which is the difference between a bounded reader
        and one that discovers the problem after the payload is already in memory.
        """
        with stack({"/doc.pdf": [chunked(64 * 1024)]}) as s:
            received = 0
            with (
                pytest.raises(ResponseTooLargeError) as caught,
                s.fetcher.fetch(
                    s.target(), limits=OPEN_LIMITS, budget=s.budget(), max_response_bytes=4096
                ) as result,
            ):
                for chunk in result.response.iter_bytes(1024):
                    received += len(chunk)

            assert caught.value.outcome is AttemptOutcome.OVERSIZED_RESPONSE
            assert received <= 4096 + 1024, "more than the limit plus one chunk was held"
            assert len(s.paths) == 1

    def test_the_default_chunk_size_does_not_weaken_the_ceiling(self) -> None:
        """The ceiling must not depend on how the caller chooses to read.

        Same defect as the drip test: a check that runs per yielded chunk is a check the caller's
        ``chunk_size`` can postpone. Read here with no argument at all.
        """
        with stack({"/doc.pdf": [chunked(256 * 1024)]}) as s:
            with (
                pytest.raises(ResponseTooLargeError),
                s.fetcher.fetch(
                    s.target(), limits=OPEN_LIMITS, budget=s.budget(), max_response_bytes=8192
                ) as result,
            ):
                for _ in result.response.iter_bytes():
                    pass
            assert len(s.paths) == 1


# ---------------------------------------------------------------------------
# Malformed responses, at the byte level
# ---------------------------------------------------------------------------


class TestMalformedResponses:
    """Measured classifications. Every expectation here was run before it was written."""

    @pytest.mark.parametrize(
        ("name", "payload"),
        [
            ("non-numeric Content-Length", b"HTTP/1.1 200 OK\r\nContent-Length: abc\r\n\r\n"),
            ("negative Content-Length", b"HTTP/1.1 200 OK\r\nContent-Length: -5\r\n\r\n"),
            (
                "conflicting Content-Lengths",
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 9\r\n\r\nab",
            ),
            ("garbage status line", b"NOT-HTTP AT ALL\r\n\r\n"),
            ("header with no colon", b"HTTP/1.1 200 OK\r\nBroken-Header\r\n\r\n"),
        ],
    )
    def test_a_framing_failure_is_a_protocol_error_and_is_retried(
        self, name: str, payload: bytes
    ) -> None:
        """A malformed exchange may well succeed on a second attempt, and is not a security event.

        Note where the rejection comes from: ``h11`` refuses these before our own
        ``Content-Length`` parser is reached, which is why that parser's tests describe its own
        reachability honestly rather than claiming to be the only guard.
        """
        with raw_stack([payload]) as (server, fetcher, sleeper):
            with (
                pytest.raises(FetchFailedError) as caught,
                fetcher.fetch(raw_target(server.port), limits=OPEN_LIMITS, budget=raw_budget()),
            ):
                pass

            assert caught.value.final_outcome is AttemptOutcome.PROTOCOL_ERROR, name
            assert server.connections == 2, f"{name} was not retried"
            assert len(sleeper.slept) == 1

    def test_a_server_that_answers_nothing_at_all_is_a_protocol_error(self) -> None:
        with raw_stack([b""]) as (server, fetcher, _):
            with (
                pytest.raises(FetchFailedError) as caught,
                fetcher.fetch(raw_target(server.port), limits=OPEN_LIMITS, budget=raw_budget()),
            ):
                pass
            assert caught.value.final_outcome is AttemptOutcome.PROTOCOL_ERROR
            assert server.connections == 2

    def test_an_abrupt_reset_is_a_connection_error_and_is_retried(self) -> None:
        with raw_stack(None, reset=True) as (server, fetcher, _):
            with (
                pytest.raises(FetchFailedError) as caught,
                fetcher.fetch(raw_target(server.port), limits=OPEN_LIMITS, budget=raw_budget()),
            ):
                pass
            assert caught.value.final_outcome is AttemptOutcome.CONNECTION_ERROR
            assert server.connections == 2

    def test_a_crlf_in_a_location_header_never_reaches_us_intact(self) -> None:
        """Measured, and not what one would guess: ``h11`` splits it into two headers.

        So the smuggled content becomes a separate header rather than part of the ``Location``
        value, and the redirect target stays ``/a``. The policy's own CRLF check is therefore a belt
        for a value that arrives *intact* — from a component that builds one, or a parser less
        strict than this one — rather than the only thing standing between us and header injection.
        Stated as a test because the reachability of a check is part of what the check is worth.
        """
        payload = (
            b"HTTP/1.1 302 Found\r\n"
            b"Location: /a\r\n"
            b"X-Injected: yes\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        with (
            raw_stack([payload]) as (server, fetcher, _),
            fetcher.fetch(
                raw_target(server.port), limits=OPEN_LIMITS, budget=raw_budget()
            ) as result,
        ):
            assert result.response.status_code == 302
            assert result.response.headers.get("location") == "/a"
            assert result.response.headers.get("x-injected") == "yes"

    def test_an_obs_folded_location_cannot_change_the_host(self) -> None:
        """Measured: a folded header arrives joined with a space, not rejected.

        ``Location: /a\\r\\n https://evil.test/`` therefore becomes the single value
        ``/a https://evil.test/``, which resolves as a *path* on the current host — so a fold cannot
        move the request to another authority. Recorded because the alternative reading, that the
        folded remainder is treated as a URL, would be an escape.
        """
        payload = (
            b"HTTP/1.1 302 Found\r\n"
            b"Location: /a\r\n https://evil.test/\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        with (
            raw_stack([payload]) as (server, fetcher, _),
            fetcher.fetch(
                raw_target(server.port), limits=OPEN_LIMITS, budget=raw_budget()
            ) as result,
        ):
            location = result.response.headers.get("location")

        assert location == "/a https://evil.test/"
        policy = RedirectPolicy()
        decision = policy.evaluate(
            status_code=302,
            location=location,
            current_url=f"http://{HOSTNAME}/start",
            current_scheme="http",
            history=(f"http://{HOSTNAME}/start",),
        )
        assert decision.url is not None
        assert decision.url.startswith(f"http://{HOSTNAME}/")
        assert "evil.test" not in decision.url.split("://", 1)[1].split("/", 1)[0]

    def test_an_understated_content_length_truncates_rather_than_overreading(self) -> None:
        """Measured: HTTP framing stops at the declared length, so the extra bytes are unreachable.

        Worth pinning down, because the plausible fear — that a short declaration lets a large body
        through the size check — is not how the framing works.
        """
        payload = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n" + b"x" * 10_000
        with (
            raw_stack([payload]) as (server, fetcher, _),
            fetcher.fetch(
                raw_target(server.port), limits=OPEN_LIMITS, budget=raw_budget()
            ) as result,
        ):
            assert b"".join(result.response.iter_bytes()) == b"xx"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_a_shutdown_signal_during_a_backoff_stops_the_fetch(self) -> None:
        stopping = threading.Event()
        stopping.set()
        with stack({"/doc.pdf": [status_only(503), body_response(b"never reached")]}) as s:
            with (
                pytest.raises(FetchCancelledError) as caught,
                s.fetcher.fetch(
                    s.target(), limits=OPEN_LIMITS, budget=s.budget(), cancellation=stopping
                ),
            ):
                pass

            assert len(s.paths) == 1, "the server was contacted after shutdown was signalled"
            assert s.sleeper.slept == [], "the uninterruptible sleeper was used despite a token"
        assert caught.value.attempts[0].outcome is AttemptOutcome.HTTP_STATUS

    def test_an_unset_signal_does_not_interfere(self) -> None:
        stopping = threading.Event()
        with stack({"/doc.pdf": [status_only(503), body_response(b"ok")]}) as s:
            with s.fetcher.fetch(
                s.target(), limits=OPEN_LIMITS, budget=s.budget(), cancellation=stopping
            ) as result:
                assert result.response.status_code == 200
            assert len(s.paths) == 2

    def test_a_signal_interrupts_a_real_wait_rather_than_outlasting_it(self) -> None:
        """Set from another thread mid-backoff. The wait must end early, not run to completion."""
        stopping = threading.Event()
        with stack({"/doc.pdf": [retry_after("30"), body_response(b"ok")]}) as s:
            timer = threading.Timer(0.15, stopping.set)
            timer.start()
            started = time.monotonic()
            try:
                with (
                    pytest.raises(FetchCancelledError),
                    s.fetcher.fetch(
                        s.target(),
                        limits=OPEN_LIMITS,
                        budget=s.budget(total=60.0),
                        cancellation=stopping,
                    ),
                ):
                    pass
            finally:
                timer.cancel()
            elapsed = time.monotonic() - started

        assert elapsed < 5.0, f"waited {elapsed:.3f}s of a 30s delay before noticing shutdown"


# ---------------------------------------------------------------------------
# Redirect chains, over real HTTP
# ---------------------------------------------------------------------------


class TestRedirectChainsOverTheWire:
    def test_a_three_hop_chain_is_followed_once_per_hop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with stack(
            {
                "/start": [redirect_to("/b")],
                "/b": [redirect_to("/c", 301)],
                "/c": [redirect_to("/final", 308)],
                "/final": [body_response(b"the document")],
            }
        ) as s:
            permit_the_test_server(monkeypatch, s.port)
            with s.redirects.fetch(
                s.url("/start"),
                host_policy=HOST_POLICY,
                limits=OPEN_LIMITS,
                budget=s.budget(),
            ) as chain:
                assert b"".join(chain.response.iter_bytes()) == b"the document"

            assert s.paths == ["/start", "/b", "/c", "/final"], "a hop was repeated or skipped"
            assert chain.hop_count == 3
            assert chain.requested_url == s.url("/start")
            assert chain.final_url == s.url("/final")
            assert [hop.status_code for hop in chain.chain] == [302, 301, 308, 200]

    def test_a_relative_location_is_resolved_against_the_url_that_sent_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with stack(
            {
                "/docs/tender.html": [redirect_to("report.pdf")],
                "/docs/report.pdf": [body_response()],
            }
        ) as s:
            permit_the_test_server(monkeypatch, s.port)
            with s.redirects.fetch(
                s.url("/docs/tender.html"),
                host_policy=HOST_POLICY,
                limits=OPEN_LIMITS,
                budget=s.budget(),
            ) as chain:
                assert chain.response.status_code == 200
            assert s.paths == ["/docs/tender.html", "/docs/report.pdf"]

    def test_a_server_that_redirects_forever_is_stopped_by_the_hop_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each hop is a new path, so loop detection does not fire and the cap is what stops it."""
        routes = {f"/hop{n}": [redirect_to(f"/hop{n + 1}")] for n in range(12)}
        with stack(routes, max_hops=3) as s:
            permit_the_test_server(monkeypatch, s.port)
            with (
                pytest.raises(RedirectRejectedError) as caught,
                s.redirects.fetch(
                    s.url("/hop0"),
                    host_policy=HOST_POLICY,
                    limits=OPEN_LIMITS,
                    budget=s.budget(),
                ),
            ):
                pass

            assert s.paths == ["/hop0", "/hop1", "/hop2", "/hop3"]
        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert "exceeded 3 hops" in str(caught.value)

    def test_a_cycle_is_detected_rather_than_burning_the_hop_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with stack({"/a": [redirect_to("/b")], "/b": [redirect_to("/a")]}) as s:
            permit_the_test_server(monkeypatch, s.port)
            with (
                pytest.raises(RedirectRejectedError) as caught,
                s.redirects.fetch(
                    s.url("/a"), host_policy=HOST_POLICY, limits=OPEN_LIMITS, budget=s.budget()
                ),
            ):
                pass
            assert s.paths == ["/a", "/b"]
        assert "loop" in str(caught.value)

    def test_a_redirect_to_the_metadata_endpoint_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The attack this whole layer exists for, delivered by a real server over a real socket."""
        with stack({"/a": [redirect_to("https://169.254.169.254/latest/meta-data/")]}) as s:
            permit_the_test_server(monkeypatch, s.port)
            with (
                pytest.raises(RedirectRejectedError) as caught,
                s.redirects.fetch(
                    s.url("/a"), host_policy=HOST_POLICY, limits=OPEN_LIMITS, budget=s.budget()
                ),
            ):
                pass
            assert s.paths == ["/a"]
        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED

    def test_a_redirect_off_the_allowlist_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with stack({"/a": [redirect_to("http://elsewhere.test/x")]}) as s:
            permit_the_test_server(monkeypatch, s.port)
            with (
                pytest.raises(RedirectRejectedError) as caught,
                s.redirects.fetch(
                    s.url("/a"), host_policy=HOST_POLICY, limits=OPEN_LIMITS, budget=s.budget()
                ),
            ):
                pass
            assert s.paths == ["/a"]
            assert "elsewhere.test" not in s.resolver.lookups, "an unpermitted host was resolved"
        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED

    def test_headers_are_not_carried_to_a_host_a_server_chose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-114 observed at the receiving end, rather than at the call we made."""
        with stack(
            {"/a": [redirect_to(f"http://{OTHER_HOSTNAME}:PORT/b")], "/b": [body_response()]}
        ) as s:
            # The location has to name the port, which is only known once the server is bound.
            s.server.routes["/a"] = [redirect_to(f"http://{OTHER_HOSTNAME}:{s.port}/b")]
            permit_the_test_server(monkeypatch, s.port)
            with s.redirects.fetch(
                s.url("/a"),
                host_policy=HOST_POLICY,
                limits=OPEN_LIMITS,
                budget=s.budget(),
                headers={"X-Aedifex-Trace": "abc123"},
            ) as chain:
                assert chain.response.status_code == 200

            assert s.paths == ["/a", "/b"]
            assert s.recorded[0].headers.get("x-aedifex-trace") == "abc123"
            assert "x-aedifex-trace" not in s.recorded[1].headers
            # The Host header follows the new authority, not the old one.
            assert s.recorded[1].host_header == f"{OTHER_HOSTNAME}:{s.port}"

    def test_a_retry_inside_a_hop_does_not_re_resolve_the_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One resolution per hop. A second lookup is the DNS-rebinding window reopening."""
        with stack({"/a": [redirect_to("/b")], "/b": [status_only(503), body_response()]}) as s:
            permit_the_test_server(monkeypatch, s.port)
            with s.redirects.fetch(
                s.url("/a"), host_policy=HOST_POLICY, limits=OPEN_LIMITS, budget=s.budget()
            ) as chain:
                assert chain.response.status_code == 200

            assert s.paths == ["/a", "/b", "/b"]
            assert s.resolver.lookups == [HOSTNAME, HOSTNAME], "a retry resolved the host again"
            assert len(chain.attempts) == 3

    def test_the_exemption_does_not_disable_the_address_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fixture above grants two exemptions. This asserts it grants no third.

        Without this, every redirect test in this class could be passing because the guard had been
        switched off rather than because the controller refuses the target. A test harness inside a
        security boundary needs its own boundary checked (rule 81f).
        """
        with stack({}, hosts=(HOSTNAME, OTHER_HOSTNAME, "metadata.example.test")) as s:
            permit_the_test_server(monkeypatch, s.port)

            # The exempted address still validates, which is what makes the other tests possible.
            assert validate_url(
                s.url("/a"), policy=HOST_POLICY, resolver=s.resolver
            ).ip_address == ip_address(LOOPBACK)

            metadata_resolver = _FixedResolver("169.254.169.254")
            with pytest.raises(SsrfRejectionError) as caught:
                validate_url(
                    f"http://metadata.example.test:{s.port}/x",
                    policy=HOST_POLICY,
                    resolver=metadata_resolver,
                )
            assert "169.254.169.254" in str(caught.value)

            private_resolver = _FixedResolver("10.0.0.5")
            with pytest.raises(SsrfRejectionError):
                validate_url(
                    f"http://metadata.example.test:{s.port}/x",
                    policy=HOST_POLICY,
                    resolver=private_resolver,
                )

            # And an unpermitted host is still unpermitted.
            with pytest.raises(SsrfRejectionError):
                validate_url(
                    f"http://elsewhere.test:{s.port}/x",
                    policy=HOST_POLICY,
                    resolver=s.resolver,
                )


class _FixedResolver:
    """Answers every lookup with one address, whatever was asked for."""

    def __init__(self, address: str) -> None:
        self._address = address

    def resolve(self, hostname: str, port: int) -> Sequence[ResolvedAddress]:
        return (ResolvedAddress(ip=ip_address(self._address), port=port),)
