"""Transport tests, run against real local servers over real sockets and real TLS.

These bind loopback sockets rather than mocking an HTTP client, and they are still unit tests: no
external infrastructure, no database, nothing shared between them, and the whole file runs in about
a second. They live here rather than under ``tests/integration`` because that directory means
"needs PostgreSQL or object storage" in this project, and these need neither.

Mocking was rejected deliberately. The security-critical behaviour of this layer is *what happens
on the wire*: which address the TCP connection goes to, which name appears in the TLS SNI
extension, which identity the certificate is checked against, and whether the connection is
released. A mock would assert that we called a library the way we currently call it, which is a
restatement of the implementation rather than evidence about behaviour (rule 21a). So there is a
throwaway certificate authority, a real handshake, and a server that records the SNI value it was
sent.

The certificate is issued for ``example.test`` and **not** for ``127.0.0.1``, which is what makes
the central pair of assertions decisive: every connection here goes to ``127.0.0.1``, so a
handshake that succeeds proves the identity being verified is the hostname, and a handshake that
fails when the hostname is replaced by the address proves the address is not an acceptable
identity.
"""

from __future__ import annotations

import contextlib
import inspect
import socket
import ssl
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import trustme

from aedifex.acquisition.fetch.guard import ValidatedTarget
from aedifex.acquisition.fetch.httpx_transport import (
    HttpxTransport,
    _build_ssl_context,
    _is_tls_failure,
    _map_open_error,
    _map_stream_error,
    _request_url,
)
from aedifex.acquisition.fetch.retry import (
    _NEVER_RETRY,
    AttemptOutcome,
    AttemptResult,
    RetryPolicy,
    RetryVerdict,
)
from aedifex.acquisition.fetch.timing import (
    MonotonicClock,
    SystemRandomSource,
    TimeoutBudget,
    TimeoutBudgetExhaustedError,
    TimeoutPolicy,
)
from aedifex.acquisition.fetch.transport import (
    ALLOWED_METHODS,
    BudgetExhaustedError,
    ConnectionFailedError,
    ConnectTimeoutError,
    Deadline,
    ProtocolError,
    RawResponse,
    ReadTimeoutError,
    ResponseHeaders,
    ResponseStreamError,
    TlsVerificationError,
    Transport,
    TransportError,
    TransportTimeouts,
    UnclassifiedTransportError,
)

HOSTNAME = "example.test"
USER_AGENT = "AedifexBot/0.1 (+mailto:ops@example.org)"
FAST = TransportTimeouts(connect_seconds=5.0, read_seconds=5.0)


# ---------------------------------------------------------------------------
# Local servers
# ---------------------------------------------------------------------------


@dataclass
class RecordedRequest:
    """What a server actually received, as opposed to what we believe we sent."""

    method: str
    path: str
    host_header: str | None
    user_agent: str | None
    client_port: int


Responder = Callable[[BaseHTTPRequestHandler], None]


class _RecordingServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, responder: Responder) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.responder = responder
        self.recorded: list[RecordedRequest] = []
        self.sni_values: list[str | None] = []
        self.suppressed_errors: list[BaseException] = []

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Record expected client disconnects instead of printing a traceback.

        Several tests deliberately abandon a response part-way or let one time out, so the server
        sees a reset connection. That is the behaviour under test, not a fault. Narrowly scoped on
        purpose: anything other than the disconnect family still prints, because a silenced server
        would turn a genuine handler bug into a passing test.
        """
        error = sys.exc_info()[1]
        if isinstance(error, ConnectionResetError | BrokenPipeError | ssl.SSLError | TimeoutError):
            self.suppressed_errors.append(error)
            return
        super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self) -> None:
        server = cast(_RecordingServer, self.server)
        server.recorded.append(
            RecordedRequest(
                method=self.command,
                path=self.path,
                host_header=self.headers.get("Host"),
                user_agent=self.headers.get("User-Agent"),
                client_port=self.client_address[1],
            )
        )
        server.responder(self)

    # Names dictated by BaseHTTPRequestHandler's dispatch, so the naming rule does not apply.
    do_GET = _handle  # noqa: N815
    do_HEAD = _handle  # noqa: N815
    do_POST = _handle  # noqa: N815

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence the default stderr logging; failures are asserted, not read."""


def ok_body(body: bytes = b"payload", status: int = 200) -> Responder:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Content-Type", "application/pdf")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(body)

    return respond


def redirect_to(location: str, status: int = 302) -> Responder:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        handler.send_header("Location", location)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    return respond


def stall_before_body(delay: float = 3.0, body: bytes = b"late") -> Responder:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.flush()
        # Headers are already out, so the client is past connect and into the read phase. This is
        # the shape of a slow-drip server, which is why read timeout is separate from connect.
        threading.Event().wait(delay)
        with contextlib.suppress(OSError):
            # The client has usually timed out and gone by now, which is the point.
            handler.wfile.write(body)

    return respond


def drip_body(
    interval: float = 0.02, declared_length: int = 10_000_000, max_bytes: int = 100
) -> Responder:
    """Send one byte at a time, never pausing long enough to time out a read.

    The shape of a hostile or dying server, and the reason a total budget exists. While the
    interval stays shorter than the read timeout, every read succeeds, so no per-read timeout ever
    fires and the connection is held for as long as the server likes.

    ``max_bytes`` stops it after about two seconds even though it promised ten megabytes. That is
    a safety stop for the suite, not part of the scenario: if the deadline check were removed, an
    unbounded drip would hang the run forever rather than fail it, and a suite that hangs on a
    regression reports nothing at all. With the stop, the client sees a truncated body and the
    test fails properly.
    """

    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Length", str(declared_length))
        handler.end_headers()
        handler.wfile.flush()
        with contextlib.suppress(OSError):
            for _ in range(max_bytes):
                handler.wfile.write(b"x")
                handler.wfile.flush()
                threading.Event().wait(interval)

    return respond


def duplicate_headers() -> Responder:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Set-Cookie", "a=1")
        handler.send_header("Set-Cookie", "b=2")
        handler.send_header("Content-Length", "2")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(b"ok")

    return respond


@dataclass
class RunningServer:
    server: _RecordingServer
    thread: threading.Thread

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def recorded(self) -> list[RecordedRequest]:
        return self.server.recorded

    @property
    def sni_values(self) -> list[str | None]:
        return self.server.sni_values


def start_server(responder: Responder, *, tls: ssl.SSLContext | None = None) -> RunningServer:
    server = _RecordingServer(responder)
    if tls is not None:

        def record_sni(
            sslsocket: ssl.SSLSocket, server_name: str | None, context: ssl.SSLContext
        ) -> None:
            server.sni_values.append(server_name)

        tls.sni_callback = record_sni  # type: ignore[assignment]
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return RunningServer(server, thread)


class RawTcpServer:
    """Writes fixed bytes and closes, for framing failures a real HTTP server cannot produce."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(4)
        self.port = self._socket.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._running = True
        self._thread.start()

    def _serve(self) -> None:
        while self._running:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            with connection:
                try:
                    connection.recv(4096)
                    connection.sendall(self._payload)
                except OSError:
                    pass

    def close(self) -> None:
        self._running = False
        self._socket.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def authority(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, ssl.SSLContext]:
    """A throwaway CA, a certificate for the hostname only, and the server context.

    Session-scoped because key generation is the slowest thing in this file, and every test wants
    the same authority. Crucially the certificate covers ``example.test`` and nothing else — no IP
    SAN — because the absence of ``127.0.0.1`` is what several assertions below depend on.
    """
    directory = tmp_path_factory.mktemp("tls")
    ca = trustme.CA()
    certificate = ca.issue_cert(HOSTNAME)

    ca_path = directory / "ca.pem"
    server_path = directory / "server.pem"
    ca.cert_pem.write_to_path(ca_path)
    certificate.private_key_and_cert_chain_pem.write_to_path(server_path)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(server_path)
    return ca_path, context


@pytest.fixture
def ca_path(authority: tuple[Path, ssl.SSLContext]) -> Path:
    return authority[0]


@pytest.fixture
def server_tls(authority: tuple[Path, ssl.SSLContext]) -> ssl.SSLContext:
    ca_file, _ = authority
    fresh = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # A separate context per test, because the SNI callback is recorded per server.
    fresh.load_cert_chain(ca_file.parent / "server.pem")
    return fresh


@pytest.fixture
def transport(ca_path: Path) -> Iterator[HttpxTransport]:
    with HttpxTransport(user_agent=USER_AGENT, trust_bundle=ca_path) as instance:
        yield instance


def target_for(
    port: int,
    *,
    hostname: str = HOSTNAME,
    scheme: str = "http",
    ip: str = "127.0.0.1",
    path: str = "/doc.pdf",
) -> ValidatedTarget:
    """Build the target the guard would have produced, for a server we control.

    Constructed directly rather than through :func:`validate_url`, because the guard correctly
    refuses loopback addresses — that is its job, and it has its own 62 tests. What is under test
    here is whether the transport honours a target's separation of address from name.
    """
    address = ip_address(ip)
    return ValidatedTarget(
        url=f"{scheme}://{hostname}:{port}{path}",
        scheme=scheme,
        hostname=hostname,
        port=port,
        ip_address=address,
        source_id="test-source",
        validated_addresses=(address,),
    )


# ---------------------------------------------------------------------------
# The boundary: only a ValidatedTarget gets in
# ---------------------------------------------------------------------------


class TestTargetBoundary:
    def test_the_transport_satisfies_the_protocol(self, transport: HttpxTransport) -> None:
        assert isinstance(transport, Transport)

    @pytest.mark.parametrize(
        "not_a_target",
        ["https://example.test/doc.pdf", b"https://example.test/", 42, None, ("example.test", 443)],
    )
    def test_a_raw_url_or_anything_else_is_refused(
        self, transport: HttpxTransport, not_a_target: object
    ) -> None:
        """The type is the control (FR-100), and it is also checked at runtime.

        mypy already rejects these calls. The runtime check exists for the paths type checking does
        not cover — a dynamic caller, a deserialised value — and it is an explicit raise rather than
        an assert, because assertions are stripped under ``-O`` and this one must not be.
        """
        with (
            pytest.raises(TypeError, match="requires a ValidatedTarget"),
            transport.open(cast(Any, not_a_target), timeouts=FAST),
        ):
            pass

    def test_open_accepts_no_parameter_that_could_carry_an_unvalidated_url(self) -> None:
        """There is no second door: no ``url=``, ``host=``, or ``address=`` overload."""
        parameters = set(inspect.signature(HttpxTransport.open).parameters)
        assert parameters == {"self", "target", "timeouts", "method", "headers"}


# ---------------------------------------------------------------------------
# The central invariant: connect to the IP, present the hostname
# ---------------------------------------------------------------------------


class TestConnectionInvariant:
    def test_the_connection_goes_to_the_validated_address(
        self, transport: HttpxTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No DNS resolution happens inside the transport (FR-107).

        Asserted by watching ``socket.getaddrinfo``: the hostname must never be looked up. The
        transport is given no resolver and cannot obtain one, but structure is not evidence — a
        library that helpfully re-resolved a ``Host`` header would break the guarantee without
        changing any of our code, and this test would catch it.
        """
        server = start_server(ok_body())
        looked_up: list[object] = []
        real_getaddrinfo = socket.getaddrinfo

        def watching(host: object, port: object, *args: Any, **kwargs: Any) -> Any:
            looked_up.append(host)
            return real_getaddrinfo(host, port, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(socket, "getaddrinfo", watching)

        with transport.open(target_for(server.port), timeouts=FAST) as response:
            assert b"".join(response.iter_bytes()) == b"payload"

        assert HOSTNAME not in looked_up, f"the hostname was resolved during transport: {looked_up}"
        assert looked_up, "expected the address to be used for the connection"
        assert all(host == "127.0.0.1" for host in looked_up), looked_up

    def test_the_host_header_carries_the_hostname_and_the_non_default_port(
        self, transport: HttpxTransport
    ) -> None:
        """The server is asked for the name that was validated, not the address it answers on."""
        server = start_server(ok_body())
        with transport.open(target_for(server.port), timeouts=FAST) as response:
            assert response.status_code == 200

        assert server.recorded[0].host_header == f"{HOSTNAME}:{server.port}"

    def test_a_default_port_is_omitted_from_the_host_header(self) -> None:
        """Derived by the target, asserted here so the transport's use of it stays honest."""
        assert target_for(443, scheme="https").host_header == HOSTNAME
        assert target_for(80, scheme="http").host_header == HOSTNAME
        assert target_for(8443, scheme="https").host_header == f"{HOSTNAME}:8443"

    def test_the_request_url_addresses_the_ip_and_preserves_path_and_query(self) -> None:
        target = target_for(8080, path="/a/b.pdf?q=1&r=2")
        url = _request_url(target)
        assert url.host == "127.0.0.1"
        assert url.port == 8080
        assert url.raw_path == b"/a/b.pdf?q=1&r=2"

    def test_an_ipv6_address_is_bracketed_in_the_request_url(self) -> None:
        """Pure check, so it runs where an IPv6 loopback server may not be available."""
        target = target_for(8080, ip="2606:4700::1111")
        assert _request_url(target).host == "2606:4700::1111"
        assert "[2606:4700::1111]" in str(_request_url(target))

    def test_the_user_agent_identifies_the_crawler(self, transport: HttpxTransport) -> None:
        server = start_server(ok_body())
        with transport.open(target_for(server.port), timeouts=FAST):
            pass
        assert server.recorded[0].user_agent == USER_AGENT


class TestTlsIdentity:
    """The security-critical centre: address pinned, identity by name.

    Every test connects to ``127.0.0.1``. The certificate is valid for ``example.test`` only.
    """

    def test_the_hostname_is_sent_as_sni(
        self, transport: HttpxTransport, server_tls: ssl.SSLContext
    ) -> None:
        server = start_server(ok_body(), tls=server_tls)
        with transport.open(target_for(server.port, scheme="https"), timeouts=FAST) as response:
            assert response.status_code == 200

        assert server.sni_values == [HOSTNAME], (
            "SNI must carry the hostname; sending the address would break virtual hosting and "
            f"would mean the certificate was selected for the wrong identity: {server.sni_values}"
        )

    def test_a_certificate_valid_for_the_hostname_verifies_over_a_pinned_address(
        self, transport: HttpxTransport, server_tls: ssl.SSLContext
    ) -> None:
        """Succeeds, and the success is the proof.

        The certificate contains no IP SAN, so if verification were performed against
        ``127.0.0.1`` — the address actually connected to — this handshake could not succeed.
        """
        server = start_server(ok_body(b"secure"), tls=server_tls)
        with transport.open(target_for(server.port, scheme="https"), timeouts=FAST) as response:
            assert b"".join(response.iter_bytes()) == b"secure"

    def test_using_the_address_as_the_tls_identity_fails(
        self, transport: HttpxTransport, server_tls: ssl.SSLContext
    ) -> None:
        """The other half of the pair: the address is not an acceptable identity.

        Same server, same certificate, same TCP destination. Only the name being verified changes,
        and verification fails — so the identity in use is demonstrably the hostname.
        """
        server = start_server(ok_body(), tls=server_tls)
        target = target_for(server.port, hostname="127.0.0.1", scheme="https")

        with pytest.raises(TlsVerificationError) as caught, transport.open(target, timeouts=FAST):
            pass
        assert "TLS verification failed" in str(caught.value)

    def test_a_wrong_hostname_fails_verification(
        self, transport: HttpxTransport, server_tls: ssl.SSLContext
    ) -> None:
        server = start_server(ok_body(), tls=server_tls)
        target = target_for(server.port, hostname="other.test", scheme="https")

        with pytest.raises(TlsVerificationError), transport.open(target, timeouts=FAST):
            pass

    def test_an_untrusted_authority_fails_verification(
        self, server_tls: ssl.SSLContext, tmp_path: Path
    ) -> None:
        """A different CA is not trusted merely because the hostname matches."""
        other_ca = trustme.CA()
        other_path = tmp_path / "other-ca.pem"
        other_ca.cert_pem.write_to_path(other_path)

        server = start_server(ok_body(), tls=server_tls)
        target = target_for(server.port, scheme="https")
        with (
            HttpxTransport(user_agent=USER_AGENT, trust_bundle=other_path) as transport,
            pytest.raises(TlsVerificationError),
            transport.open(target, timeouts=FAST),
        ):
            pass

    def test_verification_cannot_be_disabled_through_the_api(self) -> None:
        """There is no parameter for it, on the constructor or on ``open``.

        Enforced as a property of the signatures rather than as a comment, because "nobody would
        add that" is not a control. A ``verify=False`` escape hatch is the single most common way
        this class of protection is lost, usually while debugging.
        """
        forbidden = (
            "verify",
            "insecure",
            "ssl",
            "no_verify",
            "skip_verify",
            "cert_reqs",
            "context",
        )
        for function in (HttpxTransport.__init__, HttpxTransport.open):
            parameters = set(inspect.signature(function).parameters)
            assert not parameters & set(forbidden), f"{function.__qualname__}: {parameters}"

    def test_the_ssl_context_verifies_and_checks_hostnames(self, ca_path: Path) -> None:
        context = _build_ssl_context(ca_path)
        assert context.check_hostname is True
        assert context.verify_mode is ssl.CERT_REQUIRED
        assert context.minimum_version is ssl.TLSVersion.TLSv1_2

    def test_the_default_context_uses_certifi_and_still_verifies(self) -> None:
        context = _build_ssl_context(None)
        assert context.check_hostname is True
        assert context.verify_mode is ssl.CERT_REQUIRED

    def test_a_missing_trust_bundle_fails_closed(self, tmp_path: Path) -> None:
        """Rather than silently falling back to the default store."""
        with pytest.raises(ValueError, match="does not exist"):
            _build_ssl_context(tmp_path / "absent.pem")

    def test_source_configuration_cannot_reach_tls_verification(self) -> None:
        """``allow_insecure_transport`` permits the http scheme; it says nothing about TLS.

        Structural: the transport accepts no source, no registry entry, and no settings object, so
        there is no path by which per-source data could weaken verification (the guard's rule that
        source policy must not become global network policy).
        """
        parameters = set(inspect.signature(HttpxTransport.__init__).parameters)
        assert parameters == {"self", "user_agent", "trust_bundle", "max_connections"}

    def test_an_environment_proxy_cannot_reroute_a_validated_connection(
        self, ca_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A proxy in the environment must not send a validated request somewhere else.

        The proxy points at a closed port, so honouring it fails the request outright — which is
        what gives this test teeth.

        What actually provides the protection is passing an explicit ``transport=``, because httpx
        computes ``allow_env_proxies = trust_env and transport is None``. Measured, not assumed:
        mutating ``trust_env`` to ``True`` leaves this test passing, while a client built without an
        explicit transport does mount the proxy. Stated precisely here so nobody later "simplifies"
        the transport away believing ``trust_env`` alone was holding the line.
        """
        server = start_server(ok_body(b"direct"))
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")

        with (
            HttpxTransport(user_agent=USER_AGENT, trust_bundle=ca_path) as transport,
            transport.open(target_for(server.port), timeouts=FAST) as response,
        ):
            assert b"".join(response.iter_bytes()) == b"direct"

    def test_the_environment_cannot_inject_a_certificate_authority(
        self,
        ca_path: Path,
        server_tls: ssl.SSLContext,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``SSL_CERT_FILE`` must not decide who we trust.

        httpx reads that variable only when ``verify is True``; we pass a context we built, so the
        environment is shut out. This test has teeth in both directions: pointing the variable at an
        unrelated CA must not break a legitimate connection, and if ``verify=`` were ever changed
        back to ``True`` the connection would fail because that CA cannot verify this certificate.
        """
        unrelated = trustme.CA()
        unrelated_path = tmp_path / "unrelated-ca.pem"
        unrelated.cert_pem.write_to_path(unrelated_path)
        monkeypatch.setenv("SSL_CERT_FILE", str(unrelated_path))
        monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))

        server = start_server(ok_body(b"trusted"), tls=server_tls)
        with (
            HttpxTransport(user_agent=USER_AGENT, trust_bundle=ca_path) as transport,
            transport.open(target_for(server.port, scheme="https"), timeouts=FAST) as response,
        ):
            assert b"".join(response.iter_bytes()) == b"trusted"


# ---------------------------------------------------------------------------
# What the transport must refuse to do
# ---------------------------------------------------------------------------


class TestRedirectsAreNotFollowed:
    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_a_redirect_is_returned_as_a_response(
        self, transport: HttpxTransport, status: int
    ) -> None:
        """FR-110. A redirect the library follows is a request that never passed the guard."""
        server = start_server(redirect_to("https://evil.test/next", status=status))
        with transport.open(target_for(server.port), timeouts=FAST) as response:
            assert response.status_code == status
            assert response.headers.get("Location") == "https://evil.test/next"

        assert len(server.recorded) == 1, "the transport must not have followed the redirect"


class TestMethodPolicy:
    @pytest.mark.parametrize("method", ["GET", "HEAD", "get", "head"])
    def test_read_methods_are_allowed(self, transport: HttpxTransport, method: str) -> None:
        server = start_server(ok_body())
        with transport.open(target_for(server.port), timeouts=FAST, method=method) as response:
            assert response.status_code == 200
        assert server.recorded[0].method == method.upper()

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"])
    def test_write_methods_are_refused(self, transport: HttpxTransport, method: str) -> None:
        """An acquisition platform that can POST is one that can be aimed at an admin endpoint."""
        server = start_server(ok_body())
        with (
            pytest.raises(ValueError, match="not permitted"),
            transport.open(target_for(server.port), timeouts=FAST, method=method),
        ):
            pass
        assert server.recorded == [], "nothing may reach the network before the method is checked"

    def test_the_allowlist_is_read_only(self) -> None:
        assert {"GET", "HEAD"} == ALLOWED_METHODS


class TestHeaderOwnership:
    def test_a_caller_supplied_host_is_refused(self, transport: HttpxTransport) -> None:
        """Refused rather than overwritten: silently ignoring it would hide the misunderstanding."""
        with (
            pytest.raises(ValueError, match="Host is derived from the validated target"),
            transport.open(target_for(9), timeouts=FAST, headers={"Host": "evil.test"}),
        ):
            pass

    def test_the_check_is_case_insensitive(self, transport: HttpxTransport) -> None:
        with (
            pytest.raises(ValueError, match="Host is derived"),
            transport.open(target_for(9), timeouts=FAST, headers={"hOsT": "evil.test"}),
        ):
            pass

    def test_other_headers_are_passed_through(self, transport: HttpxTransport) -> None:
        server = start_server(ok_body())
        with transport.open(
            target_for(server.port), timeouts=FAST, headers={"Accept": "application/pdf"}
        ) as response:
            assert response.status_code == 200
        assert server.recorded[0].host_header == f"{HOSTNAME}:{server.port}"


# ---------------------------------------------------------------------------
# Failures, and their classification
# ---------------------------------------------------------------------------


class TestFailureClassification:
    def test_a_refused_connection_is_a_connection_failure(self, transport: HttpxTransport) -> None:
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()

        with pytest.raises(ConnectionFailedError), transport.open(target_for(port), timeouts=FAST):
            pass

    def test_the_transport_does_not_retry_internally(self, transport: HttpxTransport) -> None:
        """``retries=0``, asserted by timing rather than by reading the constructor.

        httpcore retries connection failures itself when allowed to, with exponential backoff. A
        hidden second retry loop would silently multiply every attempt budget decided above it, and
        would be invisible in logs that only record our own attempts. A refused loopback connection
        returns in about a millisecond; httpcore's first backoff alone is 0.5s, so the margin here
        is three orders of magnitude and is not a timing race.
        """
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()

        started = time.monotonic()
        with pytest.raises(ConnectionFailedError), transport.open(target_for(port), timeouts=FAST):
            pass
        elapsed = time.monotonic() - started

        assert elapsed < 0.4, f"refused connection took {elapsed:.3f}s; the transport is retrying"

    def test_a_stalled_body_is_a_read_timeout(self, transport: HttpxTransport) -> None:
        server = start_server(stall_before_body(delay=3.0))
        timeouts = TransportTimeouts(connect_seconds=5.0, read_seconds=0.2)

        with (
            pytest.raises(ReadTimeoutError),
            transport.open(target_for(server.port), timeouts=timeouts) as response,
        ):
            b"".join(response.iter_bytes())

    def test_a_non_http_response_is_a_protocol_error(self, transport: HttpxTransport) -> None:
        server = RawTcpServer(b"NOT-HTTP-AT-ALL\r\n\r\n")
        try:
            with (
                pytest.raises(ProtocolError),
                transport.open(target_for(server.port), timeouts=FAST) as response,
            ):
                b"".join(response.iter_bytes())
        finally:
            server.close()

    def test_a_truncated_body_fails_rather_than_returning_a_short_document(
        self, transport: HttpxTransport
    ) -> None:
        """Silently returning 5 of 100 promised bytes would corrupt the corpus."""
        server = RawTcpServer(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nshort")
        try:
            with (
                pytest.raises(TransportError) as caught,
                transport.open(target_for(server.port), timeouts=FAST) as response,
            ):
                b"".join(response.iter_bytes())
            assert isinstance(caught.value, ProtocolError | ResponseStreamError)
        finally:
            server.close()

    def test_a_tls_failure_is_never_reported_as_a_connection_failure(
        self, transport: HttpxTransport, server_tls: ssl.SSLContext
    ) -> None:
        """The misclassification that would matter most, asserted directly.

        httpx reports a certificate failure as ``ConnectError`` wrapping
        ``SSLCertVerificationError``. Matching on the outermost type would classify it as a
        connection error, which is retryable — and a verification failure that retries is rule 81d
        broken by an ordering mistake rather than by a decision.
        """
        server = start_server(ok_body(), tls=server_tls)
        target = target_for(server.port, hostname="other.test", scheme="https")

        with pytest.raises(TransportError) as caught, transport.open(target, timeouts=FAST):
            pass
        assert isinstance(caught.value, TlsVerificationError)
        assert not isinstance(caught.value, ConnectionFailedError)

    def test_tls_failures_are_detected_through_a_wrapped_exception_chain(self) -> None:
        wrapped = httpx.ConnectError("connection failed")
        wrapped.__cause__ = ssl.SSLCertVerificationError("hostname mismatch")
        assert _is_tls_failure(wrapped)

    def test_a_self_referential_exception_chain_terminates(self) -> None:
        """A cycle in ``__context__`` must not hang the classifier."""
        first = httpx.ConnectError("a")
        second = httpx.ConnectError("b")
        first.__context__ = second
        second.__context__ = first
        assert _is_tls_failure(first) is False

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (httpx.ConnectTimeout("slow"), ConnectTimeoutError),
            (httpx.PoolTimeout("no connection"), ConnectTimeoutError),
            (httpx.ReadTimeout("slow read"), ReadTimeoutError),
            (httpx.WriteTimeout("slow write"), ReadTimeoutError),
            (httpx.ConnectError("refused"), ConnectionFailedError),
            (httpx.ReadError("reset"), ConnectionFailedError),
            (httpx.RemoteProtocolError("bad framing"), ProtocolError),
            (httpx.LocalProtocolError("bad request"), ProtocolError),
            (httpx.UnsupportedProtocol("gopher"), ProtocolError),
            (httpx.StreamError("closed"), ResponseStreamError),
            (RuntimeError("something new"), UnclassifiedTransportError),
        ],
    )
    def test_every_library_exception_maps_to_our_taxonomy(
        self, error: Exception, expected: type[TransportError]
    ) -> None:
        mapped = _map_open_error(error, target_for(443, scheme="https"))
        assert isinstance(mapped, expected), f"{type(error).__name__} → {type(mapped).__name__}"

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (ssl.SSLCertVerificationError("renegotiated badly"), TlsVerificationError),
            (httpx.ReadTimeout("slow"), ReadTimeoutError),
            (httpx.RemoteProtocolError("truncated"), ProtocolError),
            (httpx.StreamError("closed"), ResponseStreamError),
            (ssl.SSLError("record layer failure"), ResponseStreamError),
            (OSError("connection reset"), ResponseStreamError),
            (RuntimeError("something new"), UnclassifiedTransportError),
        ],
    )
    def test_stream_failures_map_separately_from_connection_failures(
        self, error: Exception, expected: type[TransportError]
    ) -> None:
        """A TLS error mid-body is a broken stream; a certificate error is still a refusal."""
        mapped = _map_stream_error(error, target_for(443, scheme="https"))
        assert isinstance(mapped, expected)


class TestErrorTaxonomyIsSingleSourced:
    """Classification lives with the error type, so no controller can invent one (rule 81d)."""

    @pytest.mark.parametrize(
        ("error_type", "outcome"),
        [
            (ConnectTimeoutError, AttemptOutcome.CONNECT_TIMEOUT),
            (ReadTimeoutError, AttemptOutcome.READ_TIMEOUT),
            (ConnectionFailedError, AttemptOutcome.CONNECTION_ERROR),
            (TlsVerificationError, AttemptOutcome.TLS_ERROR),
            (ProtocolError, AttemptOutcome.PROTOCOL_ERROR),
            (ResponseStreamError, AttemptOutcome.RESPONSE_STREAM_ERROR),
            (UnclassifiedTransportError, AttemptOutcome.TRANSPORT_UNCLASSIFIED),
        ],
    )
    def test_each_error_declares_its_outcome(
        self, error_type: type[TransportError], outcome: AttemptOutcome
    ) -> None:
        assert error_type.outcome is outcome

    def test_a_new_error_type_cannot_inherit_a_classification_silently(self) -> None:
        """Enforced when the class is defined, not when it is first raised.

        The dangerous version of this mistake is a subclass added months from now that quietly
        picks up a retryable outcome it was never assessed for.
        """
        with pytest.raises(TypeError, match="must declare its own `outcome`"):

            class UndeclaredError(TransportError):
                pass

    @pytest.mark.parametrize("error_type", [TlsVerificationError, UnclassifiedTransportError])
    def test_refusals_are_in_the_never_retry_set(self, error_type: type[TransportError]) -> None:
        assert error_type.outcome in _NEVER_RETRY

    @pytest.mark.parametrize("error_type", [TlsVerificationError, UnclassifiedTransportError])
    def test_the_retry_policy_refuses_them_end_to_end(
        self, error_type: type[TransportError]
    ) -> None:
        """Ties the transport's taxonomy to the actual policy rather than to a parallel table."""
        decision = RetryPolicy().classify(
            AttemptResult(
                outcome=error_type.outcome, attempt=1, status_code=503, retry_after_seconds=1.0
            ),
            randomness=SystemRandomSource(),
            remaining_budget_seconds=3600.0,
        )
        assert decision.verdict is RetryVerdict.DO_NOT_RETRY

    @pytest.mark.parametrize(
        "error_type", [ConnectTimeoutError, ReadTimeoutError, ConnectionFailedError, ProtocolError]
    )
    def test_transient_failures_remain_retryable(self, error_type: type[TransportError]) -> None:
        assert error_type.outcome not in _NEVER_RETRY


# ---------------------------------------------------------------------------
# Resource discipline
# ---------------------------------------------------------------------------


class TestResourceRelease:
    def test_the_body_is_not_buffered_by_default(self) -> None:
        """There is no attribute that returns the whole payload.

        Structural, because the failure mode is a convenience accessor added later: one
        ``response.content`` and the size ceiling has been bypassed before it can be applied.
        """
        for attribute in ("content", "text", "read", "json", "body"):
            assert not hasattr(RawResponse, attribute), attribute

    def test_the_connection_is_released_when_the_body_is_never_read(
        self, transport: HttpxTransport
    ) -> None:
        server = start_server(ok_body())
        target = target_for(server.port)

        with transport.open(target, timeouts=FAST) as response:
            assert response.status_code == 200

        with pytest.raises(ResponseStreamError):
            b"".join(response.iter_bytes())

    def test_partial_consumption_releases_the_connection(self, transport: HttpxTransport) -> None:
        """Abandoning a body mid-read is what a size-ceiling rejection does, so it must be clean."""
        server = start_server(ok_body(b"x" * 4096))
        with transport.open(target_for(server.port), timeouts=FAST) as response:
            for _ in response.iter_bytes(64):
                break

        with transport.open(target_for(server.port), timeouts=FAST) as second:
            assert b"".join(second.iter_bytes()) == b"x" * 4096

    def test_an_exception_in_the_caller_still_releases_the_connection(
        self, transport: HttpxTransport
    ) -> None:
        server = start_server(ok_body())

        class CallerFailureError(Exception):
            pass

        with (
            pytest.raises(CallerFailureError),
            transport.open(target_for(server.port), timeouts=FAST) as response,
        ):
            assert response.status_code == 200
            raise CallerFailureError

        with transport.open(target_for(server.port), timeouts=FAST) as second:
            assert b"".join(second.iter_bytes()) == b"payload"

    def test_consumption_is_observable(self, transport: HttpxTransport) -> None:
        """So a later layer can tell an empty document from a body nobody read."""
        server = start_server(ok_body())
        with transport.open(target_for(server.port), timeouts=FAST) as response:
            assert response.body_consumed is False
            b"".join(response.iter_bytes())
            assert response.body_consumed is True

    def test_a_body_cannot_be_consumed_twice(self, transport: HttpxTransport) -> None:
        server = start_server(ok_body())
        with transport.open(target_for(server.port), timeouts=FAST) as response:
            assert b"".join(response.iter_bytes()) == b"payload"
            with pytest.raises(ResponseStreamError, match="already been consumed"):
                response.iter_bytes()

    @pytest.mark.parametrize("chunk_size", [0, -1, -4096])
    def test_a_non_positive_chunk_size_is_refused(self, chunk_size: int) -> None:
        response = RawResponse(
            target=target_for(443, scheme="https"),
            status_code=200,
            http_version="HTTP/1.1",
            headers=ResponseHeaders(),
            stream=lambda _size: iter([b""]),
            close=lambda: None,
        )
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            response.iter_bytes(chunk_size)

    def test_connections_are_not_reused_across_requests(self, transport: HttpxTransport) -> None:
        """Keep-alive is off until pool identity includes the validated hostname (ADR 0011).

        httpcore keys its pool by ``(scheme, host, port)`` where our host is the *address*, so two
        hostnames behind one address could otherwise share a connection whose TLS identity was
        verified for the first of them. Observed here through the client source port: a reused
        connection would show the same one twice.
        """
        server = start_server(ok_body())
        for _ in range(2):
            with transport.open(target_for(server.port), timeouts=FAST) as response:
                b"".join(response.iter_bytes())

        ports = [record.client_port for record in server.recorded]
        assert len(ports) == 2
        assert ports[0] != ports[1], f"connection was reused across requests: {ports}"


class TestTotalBudget:
    """FR-121: the total bounds the whole exchange, including a body that never ends.

    These use real time deliberately, with small values. A fake clock would have to be advanced from
    inside the streaming loop, which means the test would be driving the very mechanism it claims to
    verify. The drip interval is an order of magnitude below the read timeout, so the per-read
    timeout provably cannot be what stops these.
    """

    @staticmethod
    def budget(total: float, *, connect: float, read: float) -> TimeoutBudget:
        """A real budget on a real clock.

        Values are passed explicitly rather than defaulted, because TimeoutPolicy requires the total
        to permit one whole attempt and a mismatched default would fail confusingly. Note that
        connect + read must stay clear of the total by more than float noise: 0.2 + 0.4 is
        0.6000000000000001, which a total of 0.6 rejects. Production values are whole seconds, so
        the policy is left as it is rather than loosened to suit a test.
        """
        return TimeoutBudget(
            policy=TimeoutPolicy(connect_seconds=connect, read_seconds=read, total_seconds=total),
            clock=MonotonicClock(),
        )

    def test_a_slow_drip_body_is_stopped_by_the_total_budget(
        self, transport: HttpxTransport
    ) -> None:
        """The case a per-read timeout cannot catch.

        Bytes arrive every 20ms against a 300ms read timeout, so every read succeeds and the
        server would hold the connection as long as it liked. Only the total ends it.
        """
        server = start_server(drip_body(interval=0.02))
        timeouts = TransportTimeouts.from_budget(self.budget(0.5, connect=0.1, read=0.3))

        started = time.monotonic()
        with (
            pytest.raises(BudgetExhaustedError, match="while reading the body"),
            transport.open(target_for(server.port), timeouts=timeouts) as response,
        ):
            b"".join(response.iter_bytes(1))
        elapsed = time.monotonic() - started

        assert 0.4 < elapsed < 3.0, f"expected the budget to end it near 0.5s, took {elapsed:.2f}s"

    def test_the_read_timeout_still_catches_a_stall(self, transport: HttpxTransport) -> None:
        """The companion case, so the two mechanisms are shown to be distinct rather than assumed.

        Here the gap exceeds the read timeout and the read timeout fires, with plenty of total
        budget left, so the budget cannot be what did the work.
        """
        server = start_server(stall_before_body(delay=3.0))
        timeouts = TransportTimeouts(
            connect_seconds=1.0,
            read_seconds=0.2,
            deadline=self.budget(60.0, connect=10.0, read=30.0),
        )

        with (
            pytest.raises(ReadTimeoutError),
            transport.open(target_for(server.port), timeouts=timeouts) as response,
        ):
            b"".join(response.iter_bytes())

    def test_an_exhausted_budget_opens_no_socket(self, transport: HttpxTransport) -> None:
        """Checked before connecting: a request with no time left cannot succeed."""
        server = start_server(ok_body())
        budget = self.budget(0.1, connect=0.02, read=0.05)
        # Derived while time remained, then spent — exactly what a backoff sleep does between
        # attempts. So this exercises the transport's own pre-flight check, not from_budget's.
        timeouts = TransportTimeouts.from_budget(budget)
        time.sleep(0.12)

        with (
            pytest.raises(BudgetExhaustedError, match="no time remains"),
            transport.open(target_for(server.port), timeouts=timeouts),
        ):
            pass

        assert server.recorded == [], "the server was contacted despite an exhausted budget"

    def test_from_budget_clamps_the_attempt_to_what_remains(self) -> None:
        """A 30s read timeout is a fiction when 4s of the operation remain."""
        generous = TransportTimeouts.from_budget(self.budget(60.0, connect=10.0, read=30.0))
        assert (generous.connect_seconds, generous.read_seconds) == (10.0, 30.0)

        nearly_spent = self.budget(0.5, connect=0.2, read=0.25)
        time.sleep(0.3)
        tight = TransportTimeouts.from_budget(nearly_spent)
        assert tight.connect_seconds <= 0.2
        assert tight.read_seconds <= 0.25
        assert tight.read_seconds < 0.25, "the read timeout was not clamped to the remaining budget"

    def test_from_budget_attaches_the_deadline(self) -> None:
        """Clamping and attaching happen together, so a caller cannot do one and skip the other."""
        budget = self.budget(10.0, connect=1.0, read=2.0)
        assert TransportTimeouts.from_budget(budget).deadline is budget

    def test_from_budget_refuses_an_exhausted_budget(self) -> None:
        budget = self.budget(0.1, connect=0.02, read=0.05)
        time.sleep(0.12)
        with pytest.raises(TimeoutBudgetExhaustedError):
            TransportTimeouts.from_budget(budget)

    def test_the_budget_is_not_reset_by_the_transport(self, transport: HttpxTransport) -> None:
        """Structural: the transport is handed a read-only deadline and cannot restart it.

        The ``Deadline`` protocol exposes ``remaining_seconds`` and ``check`` and nothing else, and
        the transport takes no ``TimeoutPolicy``, so it has no way to build a fresh budget either.
        A budget that resets per attempt is the bug this whole layer exists to prevent.
        """
        assert hasattr(Deadline, "check") and hasattr(Deadline, "remaining_seconds")
        for mutator in ("reset", "restart", "extend", "clear", "policy", "attempt_timeouts"):
            assert not hasattr(Deadline, mutator), f"Deadline exposes {mutator}"
        assert "timeouts" in inspect.signature(HttpxTransport.open).parameters
        assert not {"policy", "budget", "timeout_policy"} & set(
            inspect.signature(HttpxTransport.__init__).parameters
        )

    def test_the_budget_survives_across_sequential_attempts(
        self, transport: HttpxTransport
    ) -> None:
        """One budget, several requests: the remaining time only ever decreases.

        This is the retry-spanning property, exercised through the transport rather than only in the
        budget's own unit tests — a per-attempt reset would show up here as time going back up.
        """
        server = start_server(ok_body())
        budget = self.budget(30.0, connect=10.0, read=20.0)
        observed: list[float] = []

        for _ in range(3):
            observed.append(budget.remaining_seconds)
            with transport.open(
                target_for(server.port), timeouts=TransportTimeouts.from_budget(budget)
            ) as response:
                b"".join(response.iter_bytes())

        assert observed == sorted(observed, reverse=True), observed
        assert observed[0] > observed[-1], "the budget did not advance across attempts"

    def test_budget_exhaustion_is_never_retryable(self) -> None:
        """Not because it is unsafe, but because there is no time left to retry in."""
        assert BudgetExhaustedError.outcome is AttemptOutcome.BUDGET_EXHAUSTED
        assert BudgetExhaustedError.outcome in _NEVER_RETRY
        decision = RetryPolicy().classify(
            AttemptResult(
                outcome=BudgetExhaustedError.outcome,
                attempt=1,
                status_code=503,
                retry_after_seconds=1.0,
            ),
            randomness=SystemRandomSource(),
            remaining_budget_seconds=3600.0,
        )
        assert decision.verdict is RetryVerdict.DO_NOT_RETRY

    def test_budget_exhaustion_is_catchable_as_either_concern(self) -> None:
        """One condition, two audiences: transport handling and budget reasoning."""
        assert issubclass(BudgetExhaustedError, TransportError)
        assert issubclass(BudgetExhaustedError, TimeoutBudgetExhaustedError)

    def test_a_deadline_is_optional_so_the_transport_stays_testable_alone(
        self, transport: HttpxTransport
    ) -> None:
        """Without one, per-attempt timeouts still apply; only the total is absent."""
        server = start_server(ok_body())
        with transport.open(target_for(server.port), timeouts=FAST) as response:
            assert FAST.deadline is None
            assert b"".join(response.iter_bytes()) == b"payload"


class TestResponseSurface:
    def test_status_headers_and_version_are_reported(self, transport: HttpxTransport) -> None:
        server = start_server(ok_body(b"payload", status=404))
        with transport.open(target_for(server.port), timeouts=FAST) as response:
            assert response.status_code == 404
            assert response.http_version == "HTTP/1.1"
            assert response.headers.get("Content-Type") == "application/pdf"
            assert response.target.source_id == "test-source"

    def test_duplicate_headers_are_preserved(self, transport: HttpxTransport) -> None:
        """Collapsing repeats would discard evidence that they were sent."""
        server = start_server(duplicate_headers())
        with transport.open(target_for(server.port), timeouts=FAST) as response:
            assert response.headers.get_all("Set-Cookie") == ("a=1", "b=2")

    def test_a_head_request_has_no_body(self, transport: HttpxTransport) -> None:
        server = start_server(ok_body())
        with transport.open(target_for(server.port), timeouts=FAST, method="HEAD") as response:
            assert response.status_code == 200
            assert b"".join(response.iter_bytes()) == b""

    def test_headers_are_case_insensitive_and_report_absence(self) -> None:
        headers = ResponseHeaders((("Content-Type", "application/pdf"), ("ETag", "abc")))
        assert headers.get("content-type") == "application/pdf"
        assert headers.get("CONTENT-TYPE") == "application/pdf"
        assert headers.get("Missing") is None
        assert headers.get("Missing", "fallback") == "fallback"
        assert "etag" in headers
        assert "missing" not in headers
        assert len(headers) == 2
        assert headers.get_all("absent") == ()


class TestTransportConstruction:
    @pytest.mark.parametrize("user_agent", ["", "   ", "\t\n"])
    def test_an_empty_user_agent_is_refused(self, user_agent: str) -> None:
        with pytest.raises(ValueError, match="user_agent must identify"):
            HttpxTransport(user_agent=user_agent)

    def test_closing_is_idempotent(self, ca_path: Path) -> None:
        transport = HttpxTransport(user_agent=USER_AGENT, trust_bundle=ca_path)
        transport.close()
        transport.close()

    @pytest.mark.parametrize(
        ("connect", "read"), [(0.0, 1.0), (1.0, 0.0), (-1.0, 1.0), (1.0, -1.0), (0.0, 0.0)]
    )
    def test_non_positive_timeouts_are_refused(self, connect: float, read: float) -> None:
        """Zero means "no limit" in some libraries and "fail now" in others; neither is wanted."""
        with pytest.raises(ValueError, match="timeouts must be positive"):
            TransportTimeouts(connect_seconds=connect, read_seconds=read)

    def test_timeouts_are_immutable(self) -> None:
        timeouts = TransportTimeouts(connect_seconds=1.0, read_seconds=2.0)
        with pytest.raises(AttributeError):
            timeouts.read_seconds = 999.0  # type: ignore[misc]
