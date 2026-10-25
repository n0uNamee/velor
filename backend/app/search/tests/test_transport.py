"""Transport verification uses no external network or provider credentials."""
import asyncio
import errno
import gzip
import socket
import ssl
import threading
import time
import unittest
from unittest.mock import patch

from app.search.transport import AsyncFetcher, FetchError, _Control, _PinnedConnection, validate_url


PUBLIC = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
PRIVATE = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))


class Response:
    def __init__(self, body=b"<html>Product</html>", status=200, headers=None):
        self.status = status
        self.headers = headers if headers is not None else {"Content-Type": "text/html; charset=utf-8"}
        self.body = body

    def getheaders(self):
        return list(self.headers.items())

    def read1(self, amount):
        result, self.body = self.body[:amount], self.body[amount:]
        return result


class Connection:
    def __init__(self, response):
        self.response = response
        self.sock = None
        self.closed = False
        self.request_args = None

    def request(self, *args, **kwargs):
        self.request_args = (args, kwargs)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def fetcher(self, responses=None, **kwargs):
        self.connections = []
        self.targets = []
        queue = list(responses or [Response()])

        def factory(target, address, deadline, control):
            self.targets.append((target, address))
            connection = Connection(queue.pop(0))
            self.connections.append(connection)
            return connection

        return AsyncFetcher(resolver=lambda *a, **k: [PUBLIC], connection_factory=factory, **kwargs)

    async def test_fetch_public_document_and_close_without_auth(self):
        fetcher = self.fetcher([Response("Товар".encode(), headers={"Content-Type": "text/html; charset=utf-8"})])
        page = await fetcher.fetch("https://shop.example.com/item#size")
        self.assertEqual(page.url, "https://shop.example.com/item")
        self.assertEqual(page.text, "Товар")
        self.assertEqual(page.headers["content-type"], "text/html; charset=utf-8")
        target, address = self.targets[0]
        self.assertEqual(target.host, "shop.example.com")
        self.assertEqual(address, PUBLIC)
        self.assertTrue(self.connections[0].closed)
        args, kwargs = self.connections[0].request_args
        self.assertEqual(args, ("GET", "/item"))
        self.assertFalse(any(x.lower() in {"cookie", "authorization"} for x in kwargs["headers"]))

    async def test_all_dns_answers_are_checked_before_connect(self):
        fetcher = AsyncFetcher(resolver=lambda *a, **k: [PUBLIC, PRIVATE], connection_factory=lambda *a: self.fail("Must not connect"))
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/")
        self.assertEqual(caught.exception.state, "blocked")
        self.assertIn("DNS", caught.exception.detail)
        self.assertIn("loopback", caught.exception.detail)
        self.assertIn("before connect/TLS/HTTP", caught.exception.detail)
        self.assertNotIn("127.0.0.1", caught.exception.detail)
        self.assertEqual(caught.exception.stage, "dns")
        self.assertEqual(caught.exception.error_code, "NON_PUBLIC_IP")

    async def test_dns_failure_has_safe_specific_stage_and_code(self):
        def resolver(*args, **kwargs):
            raise socket.gaierror(socket.EAI_NONAME, "Sensitive local path /private/secret must not appear")

        fetcher = AsyncFetcher(resolver=resolver)
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/")
        self.assertEqual(caught.exception.state, "inaccessible")
        self.assertEqual(caught.exception.stage, "dns")
        self.assertEqual(caught.exception.error_code, "EAI_NONAME")
        self.assertIsNone(caught.exception.status)
        self.assertIn("no merchant HTTP response", caught.exception.detail)
        self.assertNotIn("/private/secret", caught.exception.detail)

    async def test_permission_and_connection_errno_are_preserved_without_raw_message(self):
        for exc, code in ((PermissionError(errno.EPERM, "/private/secret"), "EPERM"), (ConnectionRefusedError(errno.ECONNREFUSED, "/private/secret"), "ECONNREFUSED")):
            with self.subTest(code=code):
                def factory(*args):
                    raise exc

                fetcher = AsyncFetcher(resolver=lambda *a, **k: [PUBLIC], connection_factory=factory)
                with self.assertRaises(FetchError) as caught:
                    await fetcher.fetch("https://shop.example.com/")
                self.assertEqual(caught.exception.stage, "connect")
                self.assertEqual(caught.exception.error_code, code)
                self.assertIsNone(caught.exception.status)
                self.assertNotIn("/private/secret", caught.exception.detail)
                if code == "EPERM":
                    self.assertIn("permission restriction possible", caught.exception.detail)

    async def test_tls_failure_is_distinct_from_dns_and_merchant_http(self):
        for exc, code in ((ssl.SSLCertVerificationError(1, "/private/secret"), "CERTIFICATE_VERIFY_FAILED"), (ssl.SSLError(1, "/private/secret"), "TLS_ERROR")):
            with self.subTest(code=code):
                def factory(*args):
                    raise exc

                fetcher = AsyncFetcher(resolver=lambda *a, **k: [PUBLIC], connection_factory=factory)
                with self.assertRaises(FetchError) as caught:
                    await fetcher.fetch("https://shop.example.com/")
                self.assertEqual(caught.exception.stage, "tls")
                self.assertEqual(caught.exception.error_code, code)
                self.assertEqual(caught.exception.state, "inaccessible")
                self.assertIsNone(caught.exception.status)
                self.assertNotIn("/private/secret", caught.exception.detail)

    async def test_interrupted_http_response_reports_http_io(self):
        class InterruptedConnection(Connection):
            def getresponse(self):
                raise ConnectionResetError(errno.ECONNRESET, "/private/secret")

        fetcher = AsyncFetcher(resolver=lambda *a, **k: [PUBLIC], connection_factory=lambda *args: InterruptedConnection(Response()))
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/")
        self.assertEqual(caught.exception.stage, "http")
        self.assertEqual(caught.exception.error_code, "ECONNRESET")
        self.assertNotIn("/private/secret", caught.exception.detail)

    async def test_decode_diagnostic_and_legacy_error_constructor(self):
        fetcher = self.fetcher([Response(b"not gzip", headers={"Content-Encoding": "gzip"})])
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/")
        self.assertEqual(caught.exception.stage, "decode")
        self.assertEqual(caught.exception.error_code, "INVALID_GZIP")
        self.assertEqual(caught.exception.status, 200)
        legacy = FetchError("inaccessible", "detail", "https://shop.example.com", 403)
        self.assertEqual(legacy.status, 403)
        self.assertIsNone(legacy.stage)
        self.assertIsNone(legacy.error_code)

    async def test_redirect_to_private_host_is_blocked_before_connect(self):
        fetcher = self.fetcher([Response(status=302, headers={"Location": "http://127.0.0.1/admin"})])
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/")
        self.assertEqual(caught.exception.state, "blocked")
        self.assertEqual(len(self.connections), 1)
        self.assertTrue(self.connections[0].closed)

    async def test_redirect_resolves_and_pins_new_host(self):
        answers = []
        fetcher = self.fetcher([Response(status=302, headers={"Location": "https://other.example.com/product"}), Response()])

        def resolver(host, port, **kwargs):
            answers.append(host)
            return [PUBLIC]

        fetcher._resolver = resolver
        page = await fetcher.fetch("https://shop.example.com/start")
        self.assertEqual(answers, ["shop.example.com", "other.example.com"])
        self.assertEqual(page.url, "https://other.example.com/product")
        self.assertTrue(all(x.closed for x in self.connections))

    async def test_same_host_redirect_rechecks_dns_and_blocks_rebinding(self):
        fetcher = self.fetcher([Response(status=302, headers={"Location": "/next"})])
        answers = iter(([PUBLIC], [PRIVATE]))
        fetcher._resolver = lambda *a, **k: next(answers)
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/start")
        self.assertEqual(caught.exception.state, "blocked")
        self.assertEqual(len(self.connections), 1)

    async def test_public_literal_is_pinned_without_dns(self):
        fetcher = self.fetcher()
        fetcher._resolver = lambda *a, **k: self.fail("Literal address must not be resolved")
        page = await fetcher.fetch("https://93.184.216.34/product")
        self.assertEqual(page.url, "https://93.184.216.34/product")
        self.assertEqual(self.targets[0][1][4], ("93.184.216.34", 443))

    async def test_relative_redirect_and_redirect_limit(self):
        fetcher = self.fetcher([Response(status=301, headers={"Location": "/next"}), Response(status=301, headers={"Location": "/again"})], max_redirects=1)
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/start")
        self.assertIn("Redirect limit", caught.exception.detail)
        self.assertEqual(self.targets[-1][0].path, "/next")

    async def test_https_downgrade_is_blocked(self):
        fetcher = self.fetcher([Response(status=301, headers={"Location": "http://shop.example.com/next"})])
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/")
        self.assertEqual(caught.exception.state, "blocked")

    async def test_access_denials_are_explicit_without_retry(self):
        for status in (401, 403, 407, 429, 451):
            with self.subTest(status=status):
                fetcher = self.fetcher([Response(status=status)])
                with self.assertRaises(FetchError) as caught:
                    await fetcher.fetch("https://shop.example.com/")
                self.assertEqual(caught.exception.state, "inaccessible")
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.stage, "http")
                self.assertEqual(caught.exception.error_code, f"HTTP_{status}")
                self.assertEqual(len(self.connections), 1)

    async def test_captcha_is_inaccessible(self):
        fetcher = self.fetcher([Response(b"<html><title>Just a moment...</title><div class='cf-chl-test'></div></html>")])
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/")
        self.assertEqual(caught.exception.state, "inaccessible")
        self.assertIn("challenge", caught.exception.detail)

    async def test_body_and_decoded_body_caps(self):
        for response in (
            Response(b"x" * 17),
            Response(b"x", headers={"Content-Type": "text/html", "Content-Length": "17"}),
            Response(gzip.compress(b"x" * 1000), headers={"Content-Type": "text/html", "Content-Encoding": "gzip"}),
        ):
            with self.subTest(response=response):
                fetcher = self.fetcher([response], max_bytes=16 if response.headers.get("Content-Encoding") != "gzip" else 64)
                with self.assertRaises(FetchError) as caught:
                    await fetcher.fetch("https://shop.example.com/")
                self.assertEqual(caught.exception.state, "unsupported")

    async def test_gzip_and_unsupported_binary(self):
        fetcher = self.fetcher([Response(gzip.compress(b"Product"), headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})])
        self.assertEqual((await fetcher.fetch("https://shop.example.com/")).text, "Product")
        fetcher = self.fetcher([Response(b"binary", headers={"Content-Type": "image/png"})])
        with self.assertRaises(FetchError) as caught:
            await fetcher.fetch("https://shop.example.com/")
        self.assertEqual(caught.exception.state, "unsupported")

    async def test_timeout_covers_system_dns_and_threads_are_bounded(self):
        release = threading.Event()
        entered = threading.Event()

        def resolver(*args, **kwargs):
            entered.set()
            release.wait(2)
            return [PUBLIC]

        fetcher = AsyncFetcher(timeout_seconds=0.03, max_inflight=1, resolver=resolver)
        started = time.monotonic()
        try:
            with self.assertRaises(FetchError) as caught:
                await fetcher.fetch("https://shop.example.com/")
            self.assertEqual(caught.exception.state, "inaccessible")
            self.assertEqual(caught.exception.stage, "dns")
            self.assertEqual(caught.exception.error_code, "TIMEOUT")
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(entered.is_set())
            with self.assertRaises(FetchError) as limited:
                await fetcher.fetch("https://shop.example.com/")
            self.assertIn("concurrency", limited.exception.detail)
        finally:
            release.set()

    async def test_process_thread_limit_spans_fetcher_instances_and_timed_out_dns(self):
        release = threading.Event()
        resolver_calls = []
        process_slots = threading.BoundedSemaphore(2)

        def resolver(host, *args, **kwargs):
            resolver_calls.append(host)
            release.wait(2)
            return [PUBLIC]

        def factory(*args):
            return Connection(Response())

        fetchers = [AsyncFetcher(timeout_seconds=0.03, max_inflight=1, resolver=resolver, connection_factory=factory) for _ in range(3)]
        tasks = []
        with patch("app.search.transport._PROCESS_FETCH_SLOTS", process_slots):
            try:
                tasks = [asyncio.create_task(fetcher.fetch("https://shop.example.com/")) for fetcher in fetchers[:2]]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                self.assertTrue(all(isinstance(result, FetchError) and result.state == "inaccessible" for result in results))
                self.assertEqual(len(resolver_calls), 2)
                started = time.monotonic()
                with self.assertRaises(FetchError) as caught:
                    await fetchers[2].fetch("https://shop.example.com/")
                self.assertEqual(caught.exception.state, "failed")
                self.assertIn("Process transport concurrency", caught.exception.detail)
                self.assertEqual(caught.exception.stage, "resource")
                self.assertEqual(caught.exception.error_code, "PROCESS_CONCURRENCY_LIMIT")
                self.assertLess(time.monotonic() - started, 0.2)
                self.assertEqual(len(resolver_calls), 2)
                # Cancellation/timeouts do not release the process slots early;
                # actual worker completion does, and failed admission does not
                # leak the rejected fetcher's own per-instance slot.
                release.set()
                for _ in range(100):
                    first = process_slots.acquire(blocking=False)
                    second = first and process_slots.acquire(blocking=False)
                    if second:
                        process_slots.release()
                    if first:
                        process_slots.release()
                    if second:
                        break
                    await asyncio.sleep(0.001)
                else:
                    self.fail("Completed DNS workers did not release process slots")
                self.assertEqual((await fetchers[2].fetch("https://shop.example.com/")).status, 200)
            finally:
                release.set()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

    async def test_thread_start_failure_releases_instance_and_process_slots(self):
        fetcher = self.fetcher(max_inflight=1)
        process_slots = threading.BoundedSemaphore(1)
        with patch("app.search.transport._PROCESS_FETCH_SLOTS", process_slots):
            with patch("app.search.transport.threading.Thread", side_effect=RuntimeError("Thread unavailable")):
                with self.assertRaises(FetchError) as caught:
                    await fetcher.fetch("https://shop.example.com/")
            self.assertEqual(caught.exception.state, "failed")
            self.assertIn("start transport worker", caught.exception.detail)
            self.assertEqual((await fetcher.fetch("https://shop.example.com/")).status, 200)

    async def test_cancellation_aborts_active_socket(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingSocket:
            def __init__(self):
                self.shutdown_called = False

            def shutdown(self, how):
                self.shutdown_called = True
                release.set()

        class BlockingConnection(Connection):
            def __init__(self):
                super().__init__(Response())
                self.sock = BlockingSocket()

            def getresponse(self):
                entered.set()
                release.wait(2)
                return self.response

        connection = BlockingConnection()
        fetcher = AsyncFetcher(resolver=lambda *a, **k: [PUBLIC], connection_factory=lambda *a: connection)
        task = asyncio.create_task(fetcher.fetch("https://shop.example.com/"))
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.001)
            self.assertTrue(entered.is_set())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(connection.sock.shutdown_called)
            self.assertTrue(connection.closed)
        finally:
            release.set()


class URLTests(unittest.TestCase):
    def test_reject_unsafe_schemes_hosts_ports_and_credentials(self):
        for url in (
            "file:///etc/passwd", "ftp://public.example.com/a", "https://user:secret@example.com/",
            "http://127.0.0.1/", "http://10.0.0.1/", "http://169.254.169.254/", "http://192.168.1.1/",
            "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::7f00:1]/",
            "http://[2002:7f00:1::]/", "http://localhost/", "http://service.local/", "http://2130706433/",
            "https://example.com:8000/", "https://example.com:80/", "http://example.com:443/", "https://example.com:0/",
            "https://example.com\\@127.0.0.1/", "https://example.com/\r\nX-Test:yes",
            "https://example.com/ spaced", "https://[fe80::1%25eth0]/", "http://example.com:bad/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(FetchError):
                    validate_url(url)

    def test_tls_pins_address_but_verifies_original_hostname(self):
        target = validate_url("https://shop.example.com/product")
        raw_sock = unittest.mock.MagicMock()
        tls_sock = unittest.mock.MagicMock()
        context = unittest.mock.MagicMock()
        context.wrap_socket.return_value = tls_sock
        with patch("app.search.transport.socket.socket", return_value=raw_sock) as factory, patch("app.search.transport.ssl.create_default_context", return_value=context):
            connection = _PinnedConnection(target, PUBLIC, time.monotonic() + 2, _Control())
            connection.connect()
        factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.connect.assert_called_once_with(PUBLIC[4])
        context.wrap_socket.assert_called_once_with(raw_sock, server_hostname="shop.example.com")
        self.assertIs(connection.sock, tls_sock)


if __name__ == "__main__":
    unittest.main()
