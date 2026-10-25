"""Small, bounded public-web transport for search and verification.

No cookies, credentials, proxies, browser impersonation, or user-image uploads are
used. DNS answers are checked and the chosen address is pinned to the socket,
including on every redirect. The TLS hostname remains the original public host.
"""
from __future__ import annotations

import asyncio
import errno
import gzip
import http.client
import io
import ipaddress
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit


FetchState = Literal["blocked", "unsupported", "inaccessible", "failed"]
FetchStage = Literal["url", "dns", "connect", "tls", "http", "decode", "resource"]

# Shared across requests and AsyncFetcher instances. A stalled system resolver
# must retain its slot until its daemon worker exits; timing out its caller does
# not make room for an unlimited succession of replacement DNS threads.
_PROCESS_FETCH_SLOTS = threading.BoundedSemaphore(32)


@dataclass(frozen=True)
class FetchPage:
    url: str
    status: int
    text: str
    headers: dict[str, str]


class FetchError(Exception):
    def __init__(self, state: FetchState, detail: str, url: str = "", status: int | None = None, *, stage: FetchStage | None = None, error_code: str | int | None = None):
        super().__init__(detail)
        self.state = state
        self.detail = detail
        self.url = url
        self.status = status
        self.stage = stage
        self.error_code = error_code


def _diagnostic_error(exc: BaseException, url: str, stage: FetchStage, status: int | None = None) -> FetchError:
    """Expose stable operation/code diagnostics, never raw exception messages."""
    if isinstance(exc, socket.gaierror):
        code = next((name for name in dir(socket) if name.startswith("EAI_") and getattr(socket, name) == exc.errno), "DNS_ERROR")
        return FetchError("inaccessible", f"DNS resolution failed ({code}); no merchant HTTP response", url, stage="dns", error_code=code)
    if isinstance(exc, ssl.SSLCertVerificationError):
        return FetchError("inaccessible", "TLS certificate verification failed; no merchant HTTP response", url, stage="tls", error_code="CERTIFICATE_VERIFY_FAILED")
    if isinstance(exc, ssl.SSLError):
        reason = getattr(exc, "reason", None)
        code = reason if isinstance(reason, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", reason) else "TLS_ERROR"
        return FetchError("inaccessible", f"TLS handshake failed ({code}); no merchant HTTP response", url, stage="tls", error_code=code)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return FetchError("inaccessible", f"Request timed out during {stage}", url, status, stage=stage, error_code="TIMEOUT")
    if isinstance(exc, OSError):
        code = errno.errorcode.get(exc.errno, "OS_ERROR")
        if exc.errno in {errno.EPERM, errno.EACCES}:
            detail = f"Network operation denied during {stage} ({code}); OS or environment permission restriction possible"
        else:
            detail = f"Network operation failed during {stage} ({code})"
        return FetchError("inaccessible", detail, url, status, stage=stage, error_code=code)
    if isinstance(exc, http.client.HTTPException):
        return FetchError("inaccessible", "Invalid or interrupted HTTP response", url, status, stage="http", error_code="HTTP_PROTOCOL_ERROR")
    if isinstance(exc, (UnicodeError, ValueError)):
        return FetchError("inaccessible", "Document decoding failed", url, status, stage="decode", error_code="DECODE_ERROR")
    return FetchError("failed", "Transport failed", url, status, stage=stage, error_code="TRANSPORT_ERROR")


@dataclass(frozen=True)
class _Target:
    url: str
    scheme: str
    host: str
    port: int
    path: str


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # NAT64 and transition tunnels can translate a seemingly public IPv6
        # destination into an internal IPv4 address; do not use these routes.
        if address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"):
            return False
        if address.ipv4_mapped is not None or address.sixtofour is not None or address.teredo is not None:
            return False
    return True


def _blocked_ip_class(value: str) -> str:
    """Describe the guard outcome without disclosing an internal address."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "invalid-address"
    for attribute, label in (("is_unspecified", "unspecified"), ("is_loopback", "loopback"), ("is_link_local", "link-local"), ("is_multicast", "multicast"), ("is_reserved", "reserved"), ("is_private", "private-or-special-use")):
        if getattr(address, attribute):
            return label
    return "IPv6-transition" if isinstance(address, ipaddress.IPv6Address) else "non-global"


def validate_url(url: str) -> _Target:
    """Validate a URL without resolving it; all DNS answers are checked later."""
    if not isinstance(url, str) or not url or len(url) > 8192:
        raise FetchError("blocked", "Invalid or oversized URL", str(url)[:120], stage="url", error_code="INVALID_URL")
    if re.search(r"[\x00-\x20\x7f\\]", url):
        raise FetchError("blocked", "URL contains whitespace, controls, or backslashes", url, stage="url", error_code="INVALID_URL")
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise FetchError("unsupported", "Only HTTP and HTTPS URLs are supported", url)
        if parsed.username is not None or parsed.password is not None:
            raise FetchError("blocked", "Credential-bearing URLs are forbidden", url)
        host = parsed.hostname
        if not host or "%" in host:
            raise FetchError("blocked", "URL has no valid public hostname", url)
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
        if not host or len(host) > 253 or ".." in host:
            raise FetchError("blocked", "Invalid hostname", url)
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
        if port != (443 if scheme == "https" else 80):
            raise FetchError("blocked", "Only the standard HTTP(S) port is allowed", url)
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".invalid", ".test", ".onion")) or "." not in host and ":" not in host:
            raise FetchError("blocked", "Local and special-use hostnames are forbidden", url)
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and not _public_ip(host):
            raise FetchError("blocked", "Destination is not a public IP address", url)
        authority = f"[{host}]" if ":" in host else host
        path = parsed.path or "/"
        # Unicode path/query characters must be percent encoded by the caller.
        (path + parsed.query).encode("ascii")
        normalized = urlunsplit((scheme, authority, path, parsed.query, ""))
        request_path = path + ("?" + parsed.query if parsed.query else "")
        return _Target(normalized, scheme, host, port, request_path)
    except FetchError as exc:
        if exc.stage is None:
            exc.stage = "url"
        if exc.error_code is None:
            exc.error_code = "URL_POLICY"
        raise
    except (ValueError, UnicodeError) as exc:
        raise FetchError("blocked", "Malformed URL", url, stage="url", error_code="INVALID_URL") from exc


class _Control:
    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.connection: http.client.HTTPConnection | None = None
        self.stage: FetchStage = "url"
        self.url: str = ""
        self.status: int | None = None

    def attach(self, connection: http.client.HTTPConnection) -> None:
        with self.lock:
            self.connection = connection
        if self.cancelled.is_set():
            self.abort()
            raise TimeoutError("Request cancelled")

    def abort(self) -> None:
        self.cancelled.set()
        with self.lock:
            connection = self.connection
        if connection is not None:
            sock = connection.sock or getattr(connection, "_transport_socket", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Request budget exhausted")
    return max(0.001, remaining)


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, target: _Target, address: tuple, deadline: float, control: _Control):
        super().__init__(target.host, port=target.port, timeout=_remaining(deadline))
        self._target = target
        self._address = address
        self._deadline = deadline
        self._control = control

    def connect(self) -> None:
        self._control.stage = "connect"
        if self._control.cancelled.is_set():
            raise TimeoutError("Request cancelled")
        family, _, _, _, sockaddr = self._address
        sock = socket.socket(family, socket.SOCK_STREAM)
        self.sock = sock
        self._transport_socket = sock
        try:
            sock.settimeout(_remaining(self._deadline))
            if self._control.cancelled.is_set():
                raise TimeoutError("Request cancelled")
            sock.connect(sockaddr)
            if self._target.scheme == "https":
                self._control.stage = "tls"
                context = ssl.create_default_context()
                sock.settimeout(_remaining(self._deadline))
                self.sock = context.wrap_socket(sock, server_hostname=self._target.host)
                self._transport_socket = self.sock
            self._control.stage = "http"
            if self._control.cancelled.is_set():
                raise TimeoutError("Request cancelled")
        except BaseException:
            sock.close()
            raise


ConnectionFactory = Callable[[_Target, tuple, float, _Control], http.client.HTTPConnection]


class AsyncFetcher:
    """Fetch only public text documents with a complete-request time budget.

    Each operation runs in a bounded daemon worker because the operating system
    resolver does not offer a portable deadline. The caller always returns or is
    cancelled within its budget; a stuck system DNS lookup cannot keep the app
    alive or create an unlimited number of threads. Both per-instance and
    process-wide limits are acquired without queuing. Socket operations are
    timed and the active socket is shut down when the async caller is cancelled.
    """

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 4,
        max_inflight: int = 8,
        *,
        resolver: Callable = socket.getaddrinfo,
        connection_factory: ConnectionFactory = _PinnedConnection,
    ):
        if not 0 < timeout_seconds <= 60 or not 0 < max_bytes <= 10_000_000 or not 0 <= max_redirects <= 10 or not 0 < max_inflight <= 32:
            raise ValueError("Invalid fetch resource limits")
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self._slots = threading.BoundedSemaphore(max_inflight)
        self._resolver = resolver
        self._connection_factory = connection_factory

    async def fetch(self, url: str) -> FetchPage:
        # Invalid URLs never create threads or touch the network.
        target = validate_url(url)
        loop = asyncio.get_running_loop()
        result: asyncio.Future[FetchPage] = loop.create_future()
        control = _Control()
        deadline = time.monotonic() + self.timeout_seconds
        if not self._slots.acquire(blocking=False):
            raise FetchError("failed", "Transport concurrency limit reached", target.url, stage="resource", error_code="INSTANCE_CONCURRENCY_LIMIT")
        # Capture the exact semaphore acquired so the worker always releases the
        # same process-wide pool, including during isolated dependency injection.
        process_slots = _PROCESS_FETCH_SLOTS
        if not process_slots.acquire(blocking=False):
            self._slots.release()
            raise FetchError("failed", "Process transport concurrency limit reached", target.url, stage="resource", error_code="PROCESS_CONCURRENCY_LIMIT")

        def complete(page: FetchPage | None, error: BaseException | None) -> None:
            if result.done():
                return
            if error is not None:
                result.set_exception(error)
            else:
                result.set_result(page)  # type: ignore[arg-type]

        def run() -> None:
            page, error = None, None
            try:
                page = self._fetch_sync(target, deadline, control)
            except FetchError as exc:
                error = exc
            except Exception as exc:
                error = _diagnostic_error(exc, control.url or target.url, control.stage, control.status)
            finally:
                self._slots.release()
                process_slots.release()
            try:
                loop.call_soon_threadsafe(complete, page, error)
            except RuntimeError:
                pass  # The caller and its event loop have already terminated.

        try:
            threading.Thread(target=run, name="velor-public-fetch", daemon=True).start()
        except Exception as exc:
            self._slots.release()
            process_slots.release()
            raise FetchError("failed", "Unable to start transport worker", target.url, stage="resource", error_code="THREAD_START_FAILED") from exc
        try:
            return await asyncio.wait_for(result, timeout=self.timeout_seconds)
        except TimeoutError as exc:
            control.abort()
            raise FetchError("inaccessible", f"Request timed out during {control.stage}", control.url or target.url, control.status, stage=control.stage, error_code="TIMEOUT") from exc
        except asyncio.CancelledError:
            control.abort()
            raise

    def _resolve(self, target: _Target, deadline: float) -> list[tuple]:
        _remaining(deadline)
        try:
            literal = ipaddress.ip_address(target.host)
        except ValueError:
            addresses = list(self._resolver(target.host, target.port, type=socket.SOCK_STREAM))
        else:
            family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
            sockaddr = (target.host, target.port, 0, 0) if literal.version == 6 else (target.host, target.port)
            addresses = [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]
        _remaining(deadline)
        if not addresses:
            raise FetchError("inaccessible", "DNS returned no addresses; no merchant HTTP response", target.url, stage="dns", error_code="DNS_NO_ADDRESSES")
        blocked_classes = {
            "unsupported-address-family" if item[0] not in {socket.AF_INET, socket.AF_INET6} else _blocked_ip_class(item[4][0])
            for item in addresses
            if item[0] not in {socket.AF_INET, socket.AF_INET6} or not _public_ip(item[4][0])
        }
        if blocked_classes:
            classes = ", ".join(sorted(blocked_classes))
            raise FetchError("blocked", f"DNS includes a non-public destination ({classes}); blocked before connect/TLS/HTTP", target.url, stage="dns", error_code="NON_PUBLIC_IP")
        return addresses

    def _fetch_sync(self, target: _Target, deadline: float, control: _Control) -> FetchPage:
        for redirect_count in range(self.max_redirects + 1):
            control.stage, control.url, control.status = "dns", target.url, None
            addresses = self._resolve(target, deadline)
            if control.cancelled.is_set():
                raise TimeoutError("Request cancelled")
            # Never fall back through unvalidated DNS or a proxy. Retrying another
            # address is intentionally left to a later, separately budgeted run.
            control.stage = "connect"
            connection = self._connection_factory(target, addresses[0], deadline, control)
            control.attach(connection)
            try:
                connection.request("GET", target.path, headers={
                    "User-Agent": "VELOR/1.0 (+public-product-search; no-auth)",
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,text/plain;q=0.5",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                })
                control.stage = "http"
                response = connection.getresponse()
                headers = {key.lower(): value for key, value in response.getheaders()}
                status = response.status
                control.status = status
                if status in {301, 302, 303, 307, 308}:
                    if redirect_count >= self.max_redirects:
                        raise FetchError("inaccessible", "Redirect limit reached", target.url, status, stage="resource", error_code="REDIRECT_LIMIT")
                    location = headers.get("location")
                    if not location:
                        raise FetchError("failed", "Redirect has no destination", target.url, status, stage="http", error_code="INVALID_REDIRECT")
                    redirected = validate_url(urljoin(target.url, location))
                    if target.scheme == "https" and redirected.scheme != "https":
                        raise FetchError("blocked", "HTTPS downgrade redirect is forbidden", target.url, status, stage="url", error_code="HTTPS_DOWNGRADE")
                    target = redirected
                    continue
                if status in {401, 403, 407, 429, 451}:
                    raise FetchError("inaccessible", f"Source denied access (HTTP {status}); no bypass attempted", target.url, status, stage="http", error_code=f"HTTP_{status}")
                if status < 200 or status >= 300:
                    raise FetchError("inaccessible" if status >= 500 else "failed", f"Source returned HTTP {status}", target.url, status, stage="http", error_code=f"HTTP_{status}")
                mime = headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if mime and mime not in {"text/html", "application/xhtml+xml", "application/json", "application/ld+json", "text/plain"}:
                    raise FetchError("unsupported", f"Unsupported document type: {mime}", target.url, status, stage="decode", error_code="UNSUPPORTED_CONTENT_TYPE")
                content_length = headers.get("content-length")
                if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
                    raise FetchError("unsupported", "Document exceeds size budget", target.url, status, stage="resource", error_code="RESPONSE_SIZE_LIMIT")
                content = bytearray()
                while True:
                    timeout = _remaining(deadline)
                    if control.cancelled.is_set():
                        raise TimeoutError("Request cancelled")
                    if connection.sock is not None:
                        connection.sock.settimeout(timeout)
                    chunk = response.read1(min(65536, self.max_bytes + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > self.max_bytes:
                        raise FetchError("unsupported", "Document exceeds size budget", target.url, status, stage="resource", error_code="RESPONSE_SIZE_LIMIT")
                control.stage = "decode"
                encoding = headers.get("content-encoding", "identity").lower().strip()
                if encoding == "gzip":
                    try:
                        with gzip.GzipFile(fileobj=io.BytesIO(content)) as compressed:
                            content = bytearray(compressed.read(self.max_bytes + 1))
                    except (OSError, EOFError) as exc:
                        raise FetchError("failed", "Invalid compressed document", target.url, status, stage="decode", error_code="INVALID_GZIP") from exc
                    if len(content) > self.max_bytes:
                        raise FetchError("unsupported", "Decoded document exceeds size budget", target.url, status, stage="resource", error_code="DECODED_SIZE_LIMIT")
                elif encoding not in {"", "identity"}:
                    raise FetchError("unsupported", f"Unsupported content encoding: {encoding}", target.url, status, stage="decode", error_code="UNSUPPORTED_ENCODING")
                charset_match = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", headers.get("content-type", ""), re.I)
                charset = charset_match.group(1) if charset_match else "utf-8"
                try:
                    text = content.decode(charset, errors="replace")
                except LookupError:
                    text = content.decode("utf-8", errors="replace")
                # These markers identify access challenges, not ordinary product
                # copy mentioning a captcha-related help page.
                challenge = text[:150_000].lower()
                if any(marker in challenge for marker in (
                    "<title>access denied", "<title>just a moment", "cf-chl-", "id=\"challenge-form\"",
                    "<title>captcha", "<title>доступ ограничен", "проверка, что вы не робот", "подтвердите, что вы не робот",
                )):
                    raise FetchError("inaccessible", "Source returned an access challenge; no bypass attempted", target.url, status, stage="http", error_code="ACCESS_CHALLENGE")
                _remaining(deadline)
                return FetchPage(target.url, status, text, headers)
            finally:
                connection.close()
        raise FetchError("failed", "Redirect handling failed", target.url, stage="http", error_code="REDIRECT_ERROR")
