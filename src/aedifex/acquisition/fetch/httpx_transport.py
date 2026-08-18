"""The ``httpx`` implementation of :class:`~aedifex.acquisition.fetch.transport.Transport`.

Kept in its own module so the boundary in ``transport.py`` stays free of any HTTP library, and so
replacing the library means rewriting one file whose behaviour is pinned by tests against a real
local server.

How the connection invariant is achieved
---------------------------------------

``httpcore`` connects to the *URL's* host and performs the TLS handshake against
``server_hostname``, which it takes from the ``sni_hostname`` request extension when present
(``httpcore/_sync/connection.py``). That gives exactly the separation the guard requires:

.. code-block:: text

    request URL host   = the validated IP address   → where the TCP connection goes
    sni_hostname ext   = the original hostname      → TLS SNI and certificate identity
    Host header        = target.host_header         → what the server is asked for

The certificate is therefore verified against the hostname while the socket is pinned to an
address that was already validated, which is what makes DNS rebinding a non-event: no second
resolution exists to be poisoned.

Deliberate configuration, each item load-bearing
-----------------------------------------------

``follow_redirects=False``
    A redirect followed by the library is a request that never passed the guard. Redirects are
    returned to the caller as ordinary responses (FR-110).
``retries=0``
    ``httpcore`` will retry connection failures itself if allowed to. Retry policy belongs to one
    place, and a hidden second retry loop would silently multiply every attempt budget above it.
explicit ``transport=`` and explicit ``verify=<SSLContext>``
    These, not ``trust_env``, are what keep the environment out of a validated request. Measured
    rather than assumed, because the obvious reading is wrong:

    * ``httpx`` computes ``allow_env_proxies = trust_env and transport is None``
      (``_client.py``), so supplying an explicit transport is what leaves the proxy mount map
      empty. Verified: with no explicit transport and ``HTTPS_PROXY`` set, the client mounts a
      proxy; with one, it mounts nothing.
    * ``create_ssl_context`` consults ``SSL_CERT_FILE`` and ``SSL_CERT_DIR`` only when ``verify is
      True`` (``_config.py``), so passing a context we built ourselves is what stops the
      environment from injecting a certificate authority.

    Both matter. A proxy would send the request somewhere other than the validated address, which
    would make the SSRF guard decorative; an environment-supplied CA would silently widen who can
    impersonate a source.
``trust_env=False``
    Kept, but honestly: given the two settings above it currently changes nothing, which a
    mutation test confirmed — flipping it to ``True`` broke no test. It is defence in depth for the
    day someone removes the explicit transport or the explicit context, so that reopening the
    environment requires two mistakes rather than one.
``max_keepalive_connections=0``
    No connection reuse — see below.
``http2=False``
    One protocol, so framing behaviour under test is the framing behaviour in production.

Why connection reuse is disabled
--------------------------------

``httpcore`` keys its pool by origin: ``(scheme, host, port)``. Our host is the *IP address*, while
SNI is a per-request extension, so two different hostnames that resolve to the same address would
be eligible to share one connection — and the second request would travel over a TLS session
negotiated and verified for the first hostname. That is a real confusion of identity, not a
theoretical one, on shared hosting and CDNs where many names sit behind one address.

Correct pool identity for this design is ``(scheme, validated hostname, validated IP, port)``, and
implementing that means either a custom pool key or a pool per destination. Until it exists,
keep-alive is off: a connection per request is slower, and being slower is an acceptable price for
not inheriting someone else's verified identity. Recorded in ADR 0011.
"""

from __future__ import annotations

import ssl
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Final

import certifi
import httpx

from aedifex.acquisition.fetch.guard import ValidatedTarget
from aedifex.acquisition.fetch.timing import Deadline, TimeoutBudgetExhaustedError
from aedifex.acquisition.fetch.transport import (
    ALLOWED_METHODS,
    DEFAULT_MAX_RESPONSE_BYTES,
    BudgetExhaustedError,
    ConnectionFailedError,
    ConnectTimeoutError,
    ProtocolError,
    RawResponse,
    ReadTimeoutError,
    ResponseHeaders,
    ResponseStreamError,
    ResponseTooLargeError,
    TlsVerificationError,
    TransportError,
    TransportTimeouts,
    UnclassifiedTransportError,
    parse_content_length,
)

__all__ = ["HttpxTransport"]

_DEFAULT_MAX_CONNECTIONS: Final[int] = 10
"""A resource bound, not a policy. The real per-source rate limit and global concurrency cap are a
separate slice; this only stops a caller bug from opening unbounded sockets.
"""


def _build_ssl_context(trust_bundle: Path | None) -> ssl.SSLContext:
    """Build a context that verifies. There is no argument that makes it not verify.

    ``trust_bundle`` changes *which* certificate authorities are trusted — it exists so tests can
    run against a private CA and a real TLS handshake instead of mocking the security-critical
    path. It cannot switch verification off, and it is a transport construction parameter, so no
    registry entry or scraped value can reach it.
    """
    if trust_bundle is not None and not trust_bundle.is_file():
        raise ValueError(
            f"trust bundle {trust_bundle} does not exist; refusing to fall back to the default "
            "store, because a typo would silently change which authorities are trusted"
        )

    context = ssl.create_default_context(
        cafile=str(trust_bundle) if trust_bundle is not None else certifi.where()
    )
    # create_default_context already sets both. Set them again anyway: this is the one assertion in
    # the codebase whose failure is indistinguishable from working correctly until someone is
    # actively intercepting traffic, so it does not rely on a default staying put.
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _request_url(target: ValidatedTarget) -> httpx.URL:
    """Rewrite the target's URL to address the validated IP, preserving path and query.

    The authority is replaced; nothing else is. Keeping the path and query verbatim matters because
    the URL that was validated is the URL that must be requested.
    """
    return httpx.URL(target.url).copy_with(host=str(target.ip_address), port=target.port)


def _prepare_headers(target: ValidatedTarget, headers: Mapping[str, str] | None) -> dict[str, str]:
    """Build request headers, with ``Host`` owned by the transport.

    A caller-supplied ``Host`` is refused rather than overwritten. Overwriting would be safe but
    silent, and a caller trying to set it has misunderstood something that matters — the header is
    derived from the validated authority, and letting it be chosen separately would decouple the
    name we ask for from the name we verified.
    """
    prepared: dict[str, str] = {}
    for name, value in (headers or {}).items():
        if name.lower() == "host":
            raise ValueError(
                "Host is derived from the validated target and cannot be supplied by a caller; "
                f"attempted value {value!r} for {target.describe()}"
            )
        prepared[name] = value
    prepared["Host"] = target.host_header
    return prepared


def _is_tls_failure(error: BaseException) -> bool:
    """Whether an exception chain contains a TLS-layer failure.

    ``httpx`` reports a certificate failure as ``ConnectError`` wrapping
    ``ssl.SSLCertVerificationError``, so the chain has to be walked. Checking only the outermost
    type would classify a failed certificate check as an ordinary connection error — which is
    retryable — and that single misclassification would undo the guarantee that a verification
    failure is never retried (rule 81d).
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _map_open_error(error: Exception, target: ValidatedTarget) -> TransportError:
    """Convert a library exception raised while opening the exchange into our taxonomy.

    TLS is tested first and deliberately: during connection setup any TLS failure is a verification
    failure as far as this layer is concerned, and an ordering mistake here would make it retryable.
    """
    context = target.describe()

    if _is_tls_failure(error):
        return TlsVerificationError(f"TLS verification failed for {context}: {error}")
    if isinstance(error, httpx.ConnectTimeout | httpx.PoolTimeout):
        return ConnectTimeoutError(f"connect timed out for {context}: {error}")
    if isinstance(error, httpx.ReadTimeout | httpx.WriteTimeout):
        return ReadTimeoutError(f"read timed out for {context}: {error}")
    if isinstance(error, httpx.ProtocolError | httpx.UnsupportedProtocol):
        return ProtocolError(f"protocol error for {context}: {error}")
    if isinstance(error, httpx.ConnectError | httpx.NetworkError):
        return ConnectionFailedError(f"connection failed for {context}: {error}")
    if isinstance(error, httpx.StreamError):
        return ResponseStreamError(f"response stream failed for {context}: {error}")
    return UnclassifiedTransportError(f"unrecognised {type(error).__name__} for {context}: {error}")


def _map_stream_error(error: Exception, target: ValidatedTarget) -> TransportError:
    """Convert a library exception raised while reading the body.

    Differs from :func:`_map_open_error` on purpose. By this point the certificate has already been
    verified, so a TLS-level error mid-body is a truncated or broken stream rather than a
    verification failure — with one exception: an actual certificate error (renegotiation) is still
    a verification failure and stays non-retryable.
    """
    context = target.describe()

    if isinstance(error, ssl.SSLCertVerificationError):
        return TlsVerificationError(f"certificate verification failed mid-stream for {context}")
    if isinstance(error, httpx.ReadTimeout | httpx.WriteTimeout):
        return ReadTimeoutError(f"read timed out streaming body for {context}: {error}")
    if isinstance(error, httpx.ProtocolError):
        return ProtocolError(f"protocol error streaming body for {context}: {error}")
    if isinstance(error, httpx.StreamError | httpx.NetworkError | ssl.SSLError | OSError):
        return ResponseStreamError(f"body stream failed for {context}: {error}")
    return UnclassifiedTransportError(
        f"unrecognised {type(error).__name__} streaming body for {context}: {error}"
    )


class HttpxTransport:
    """Opens connections to validated destinations, and does nothing else.

    Owns an :class:`httpx.Client` for the SSL context and socket limits, but not for connection
    reuse, which is disabled. Close it when finished, or use it as a context manager.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        trust_bundle: Path | None = None,
        max_connections: int = _DEFAULT_MAX_CONNECTIONS,
    ) -> None:
        if not user_agent.strip():
            raise ValueError(
                "user_agent must identify this crawler and a contact; anonymous automated "
                "requests are exactly what a site operator is entitled to block"
            )
        self._user_agent = user_agent
        self._client = httpx.Client(
            transport=httpx.HTTPTransport(
                verify=_build_ssl_context(trust_bundle),
                retries=0,
                trust_env=False,
                http1=True,
                http2=False,
                limits=httpx.Limits(
                    max_connections=max_connections,
                    max_keepalive_connections=0,
                ),
            ),
            follow_redirects=False,
            trust_env=False,
        )

    def __enter__(self) -> HttpxTransport:
        return self

    def __exit__(self, *exc_details: object) -> None:
        self.close()

    def close(self) -> None:
        """Release pooled sockets. Idempotent."""
        self._client.close()

    @contextmanager
    def open(
        self,
        target: ValidatedTarget,
        *,
        timeouts: TransportTimeouts,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> Iterator[RawResponse]:
        """Send one request to ``target`` and yield the unread response.

        Raises:
            TypeError: if ``target`` is not a :class:`ValidatedTarget`. The type annotation is the
                real control, but an explicit check keeps a plain string from reaching a socket in
                code that skipped type checking. Not an ``assert``: those vanish under ``-O``.
            ValueError: for a method outside :data:`ALLOWED_METHODS`, or a caller-supplied ``Host``.
            TransportError: for every network, TLS, and protocol failure.
        """
        if not isinstance(target, ValidatedTarget):
            raise TypeError(
                f"transport requires a ValidatedTarget, got {type(target).__name__}. Only "
                "validate_url() produces one, which is what stops an unvalidated URL reaching a "
                "socket."
            )
        if max_response_bytes <= 0:
            raise ValueError(
                f"max_response_bytes must be positive, got {max_response_bytes}; a non-positive "
                "ceiling would either reject everything or, read as 'unlimited', defeat the control"
            )
        normalized_method = method.upper()
        if normalized_method not in ALLOWED_METHODS:
            raise ValueError(
                f"method {method!r} is not permitted; this platform reads documents and never "
                f"submits, so only {sorted(ALLOWED_METHODS)} are allowed"
            )

        if timeouts.deadline is not None:
            # Before the socket, not after. A request issued with no time left cannot succeed, and
            # opening it anyway would consume a connection slot and touch a remote server to learn
            # something already known.
            try:
                timeouts.deadline.check()
            except TimeoutBudgetExhaustedError as error:
                raise BudgetExhaustedError(
                    f"no time remains to fetch {target.describe()}: {error}"
                ) from error

        request = self._client.build_request(
            normalized_method,
            _request_url(target),
            headers={"User-Agent": self._user_agent, **_prepare_headers(target, headers)},
            timeout=httpx.Timeout(
                connect=timeouts.connect_seconds,
                read=timeouts.read_seconds,
                write=timeouts.read_seconds,
                pool=timeouts.connect_seconds,
            ),
            # The hostname, not the address: SNI and certificate identity both follow this.
            extensions={"sni_hostname": target.hostname},
        )

        try:
            response = self._client.send(request, stream=True)
        except Exception as error:
            raise _map_open_error(error, target) from error

        try:
            declared = _declared_length(response, target)
            if (
                declared is not None
                and declared > max_response_bytes
                and normalized_method != "HEAD"
            ):
                # Rejected here, before a single body byte is read: the cheapest possible refusal,
                # and the only one that costs no bandwidth. Skipped for HEAD, where the header
                # describes a body that will not be sent — refusing there would break the one
                # request whose purpose is to discover a resource's size before fetching it.
                raise ResponseTooLargeError(
                    f"{target.describe()} declared {declared} bytes, over the "
                    f"{max_response_bytes} byte limit; refused before reading the body",
                    limit_bytes=max_response_bytes,
                    declared=True,
                )
            yield RawResponse(
                target=target,
                status_code=response.status_code,
                http_version=response.http_version,
                headers=ResponseHeaders(tuple(response.headers.multi_items())),
                declared_content_length=declared,
                stream=lambda chunk_size: _iter_mapped(
                    response, target, chunk_size, timeouts.deadline, max_response_bytes
                ),
                close=response.close,
            )
        finally:
            # Runs on success, on an exception from the caller, on an unconsumed body, and on
            # interruption. A connection that leaks on one of those paths is the one that leaks in
            # production, because that is the path a crawler takes on a bad day.
            response.close()


def _declared_length(response: httpx.Response, target: ValidatedTarget) -> int | None:
    """Parse the declared body length, treating an unparseable header as a framing error.

    A present-but-malformed value must not be read as "absent" (rule 81b). ``ProtocolError`` is the
    right classification and is also what happens today without this code: h11 validates the header
    itself and raises ``RemoteProtocolError`` for every malformed form, which maps to the same
    type. Agreeing with the layer below keeps one condition from having two different outcomes
    depending on which library version is installed.
    """
    try:
        return parse_content_length(response.headers.get("content-length"))
    except ValueError as error:
        raise ProtocolError(f"{target.describe()} sent a {error}") from error


def _iter_mapped(
    response: httpx.Response,
    target: ValidatedTarget,
    chunk_size: int,
    deadline: Deadline | None,
    max_bytes: int,
) -> Iterator[bytes]:
    """Iterate the body, converting library exceptions and enforcing the total deadline.

    The deadline check is what makes a slow-drip response fail. A per-read timeout restarts on
    every read, so a server sending a byte just inside that window never trips it and holds the
    connection as long as it likes. Checking the total as the bytes arrive is the only thing that
    bounds the exchange (FR-121).

    **As they arrive, not as they are yielded.** ``httpx.Response.iter_bytes(n)`` buffers until it
    holds ``n`` bytes, so checking once per yielded chunk means checking once per ``n`` bytes — and
    a server dripping one byte at a time never reaches that point. With the 256 KB default that
    left the deadline unconsulted for the whole exchange, which is precisely the attack it exists
    to stop. Found by the adversarial suite; the earlier test passed only because it read with a
    chunk size of one, so every byte happened to be a checkpoint. ``iter_bytes(None)`` is therefore
    used here to receive every piece the moment it decodes, and the caller's ``chunk_size`` is
    honoured by re-chunking below, where it cannot delay a check.

    The bound is the deadline plus at most one read timeout: a check happens between reads, so a
    single read already in flight still runs to its own limit. That limit was itself clamped to the
    remaining budget when the attempt started, so the overrun is bounded rather than open-ended.
    Stated precisely because "enforces a 300s total" and "returns no later than 300s" are different
    claims, and only the first is true.
    """
    received = 0
    pending = bytearray()
    try:
        for chunk in response.iter_bytes(None):
            received += len(chunk)
            if received > max_bytes:
                # The check that actually protects us. A server can omit Content-Length, send a
                # chunked response, or simply be wrong, so the declared size is a courtesy and
                # the running total is the control. Raised before the chunk is yielded, so no
                # caller receives a byte of a response already known to be over the limit.
                #
                # Checked before the deadline on purpose. At a boundary where both are blown,
                # size is the more useful thing to report: it is a permanent property of the
                # response, while the deadline belongs to this attempt. Both are non-retryable,
                # so nothing about safety turns on the order — only the quality of the report.
                raise ResponseTooLargeError(  # noqa: TRY301 - see the TransportError re-raise
                    f"{target.describe()} exceeded the {max_bytes} byte limit while streaming "
                    f"(at least {received} bytes received)",
                    limit_bytes=max_bytes,
                    declared=False,
                    observed_bytes=received,
                )
            if deadline is not None:
                try:
                    deadline.check()
                except TimeoutBudgetExhaustedError as error:
                    raise BudgetExhaustedError(
                        f"request budget exhausted while reading the body of "
                        f"{target.describe()}: {error}"
                    ) from error
            # Re-chunk to what the caller asked for. Bounded by chunk_size plus one arriving piece,
            # so the memory claim survives the change: nothing accumulates while the connection is
            # merely slow, because the checks above have already run on every byte counted here.
            pending += chunk
            while len(pending) >= chunk_size:
                yield bytes(pending[:chunk_size])
                del pending[:chunk_size]
        if pending:
            yield bytes(pending)
    except TransportError:
        # Already ours: mapping it again would relabel a budget exhaustion as a stream failure,
        # which is retryable. Rule 81d forbids a refusal becoming transient by re-classification.
        raise
    except Exception as error:
        raise _map_stream_error(error, target) from error
