import asyncio
import http.server
import threading

import httpx
import pytest

from app.acquisition import fetchers, proxy
from app.acquisition.proxy import GuardedProxy
from app.acquisition.ssrf import UrlRejected


class _Site(http.server.ThreadingHTTPServer):
    """A local web server that records what reaches it."""

    def __init__(self, routes) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes = routes
        self.hits: list[str] = []
        self.request_headers: list[dict[str, str]] = []
        self.daemon_threads = True

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.server.hits.append(self.path)
        self.server.request_headers.append(dict(self.headers))
        status, headers, body = self.server.routes(self.path)
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def sites(monkeypatch):
    """A site treated as public, and one treated as internal."""
    internal = _Site(lambda path: (200, {"Content-Type": "text/html"}, b"secret"))
    public = _Site(
        lambda path: (302, {"Location": f"{internal.base}/secret"}, b"")
        if path == "/redirect"
        else (200, {"Content-Type": "text/html"}, b"x" * 5000)
    )
    for site in (public, internal):
        threading.Thread(target=site.serve_forever, daemon=True).start()

    async def allowed(host, port):
        if port == internal.server_port:
            raise UrlRejected("URL_BLOCKED", "blocked")
        return [host]

    monkeypatch.setattr(proxy, "allowed_addresses", allowed)
    monkeypatch.setattr(fetchers, "_public_url", lambda url: f":{internal.server_port}" not in url)
    yield public, internal
    public.shutdown()
    internal.shutdown()


def _client(guard: GuardedProxy) -> httpx.AsyncClient:
    return httpx.AsyncClient(proxy=guard.url, trust_env=False)


async def test_proxy_forwards_to_an_allowed_address(sites):
    public, _ = sites
    async with GuardedProxy(1_000_000) as guard, _client(guard) as client:
        response = await client.get(f"{public.base}/page?x=1")
    assert response.status_code == 200
    assert public.hits == ["/page?x=1"]
    assert public.request_headers[0]["Connection"] == "close"
    assert "Proxy-Connection" not in public.request_headers[0]


async def test_proxy_refuses_an_internal_address(sites):
    _, internal = sites
    async with GuardedProxy(1_000_000) as guard, _client(guard) as client:
        response = await client.get(f"{internal.base}/secret")
    assert response.status_code == 403
    assert guard.blocked
    assert internal.hits == []


async def test_proxy_refuses_a_tunnel_to_an_internal_address(sites):
    _, internal = sites
    async with GuardedProxy(1_000_000) as guard, _client(guard) as client:
        with pytest.raises(httpx.ProxyError):
            await client.get(f"https://127.0.0.1:{internal.server_port}/secret")
    assert guard.blocked
    assert internal.hits == []


async def test_proxy_checks_the_real_rules_by_default():
    with pytest.raises(UrlRejected):
        await proxy.allowed_addresses("169.254.169.254", 80)
    with pytest.raises(UrlRejected):
        await proxy.allowed_addresses("8.8.8.8", 8443)


async def test_proxy_cuts_a_download_over_its_limit(sites):
    public, _ = sites
    async with GuardedProxy(1000) as guard, _client(guard) as client:
        with pytest.raises(httpx.HTTPError):
            await client.get(f"{public.base}/big")
    assert guard.over_limit


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch().close()
    except Exception:
        return False
    return True


async def test_browser_cannot_be_redirected_to_an_internal_address(sites):
    # Set here, not in a fixture, because pytest-asyncio applies its own policy after fixtures.
    # This is the server's setup: only its main loop is a selector loop, not the browser thread's.
    original = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    try:
        # CI doesn't install Chromium. The proxy tests above still run there.
        if not await asyncio.to_thread(_chromium_available):
            pytest.skip("Chromium is not installed")
        public, internal = sites
        with pytest.raises(fetchers.FetchFailed) as caught:
            await fetchers.browser_fetch(f"{public.base}/redirect", 1_000_000)
    finally:
        asyncio.set_event_loop_policy(original)
    assert caught.value.reason == "blocked"
    assert public.hits == ["/redirect"]
    assert internal.hits == []
