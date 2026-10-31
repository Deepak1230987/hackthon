import asyncio
import socket
import ssl
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import certifi
import httpx

from app.acquisition.proxy import GuardedProxy
from app.acquisition.ssrf import GuardedBackend, UrlRejected, check_url, is_public, parse_url

CERTS = Path(__file__).parent / "certs"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
MAX_REDIRECTS = 5
MAX_HTML_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 45
MAX_LINK_OPTIONS = 10


class FetchFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Fetched:
    method: str
    url: str
    content: bytes | None = None
    links: list[dict[str, str]] = field(default_factory=list)


def tls_context() -> ssl.SSLContext:
    """certifi's roots, plus intermediates some government servers fail to send.

    Bundled intermediates only help build a chain. It must still end at a certifi root.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    for path in sorted(CERTS.glob("*.pem")):
        context.load_verify_locations(cafile=str(path))
    return context


def guarded_transport() -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport(verify=tls_context(), trust_env=False)
    pool = transport._pool
    pool._network_backend = GuardedBackend(pool._network_backend)
    return transport


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def _undo_double_encoding(url: str) -> str:
    """Some sites encode a Hindi file name twice, so the link as published doesn't work.

    Real on pmkisan.gov.in, whose Hindi guidelines link gets a 400 until this is undone.
    A link that wasn't encoded twice fails this conversion and is left as it is.
    """
    try:
        raw = b"".join(
            bytes([ord(c)]) if ord(c) < 256 else c.encode("cp1252") for c in url
        )
        return raw.decode("utf-8")
    except ValueError:
        return url


def pdf_links(html: str, base_url: str) -> list[dict[str, str]]:
    parser = _LinkParser()
    parser.feed(html)
    found: dict[str, str] = {}
    for href, label in parser.links:
        url = _undo_double_encoding(urljoin(base_url, href))
        if urlsplit(url).path.lower().endswith(".pdf") and url not in found:
            found[url] = label[:200]
    return [{"url": url, "label": label} for url, label in found.items()][:MAX_LINK_OPTIONS]


async def http_fetch(
    url: str, limit_bytes: int, transport: httpx.AsyncBaseTransport | None = None
) -> Fetched:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html,*/*"}
    try:
        async with httpx.AsyncClient(
            transport=transport or guarded_transport(), headers=headers, timeout=TIMEOUT_S
        ) as client:
            async with asyncio.timeout(TIMEOUT_S):
                for _ in range(MAX_REDIRECTS + 1):
                    await check_url(url)
                    async with client.stream("GET", url) as response:
                        if response.has_redirect_location:
                            url = urljoin(url, response.headers["location"])
                            continue
                        if response.status_code >= 300:
                            raise FetchFailed(f"http_{response.status_code}")
                        return await _read(response, url, limit_bytes)
                raise FetchFailed("too_many_redirects")
    except UrlRejected as exc:
        raise FetchFailed("blocked") from exc
    except (ValueError, httpx.InvalidURL) as exc:
        # A server can send a redirect that isn't a usable URL.
        raise FetchFailed("bad_redirect") from exc
    except TimeoutError as exc:
        raise FetchFailed("timeout") from exc
    except httpx.TimeoutException as exc:
        raise FetchFailed("timeout") from exc
    except httpx.HTTPError as exc:
        raise FetchFailed("tls" if "CERTIFICATE" in str(exc) else "connection") from exc


async def _read(response: httpx.Response, url: str, limit_bytes: int) -> Fetched:
    data = bytearray()
    limit = limit_bytes
    async for chunk in response.aiter_bytes():
        data += chunk
        if len(data) >= 5 and not data.startswith(b"%PDF-"):
            limit = min(limit_bytes, MAX_HTML_BYTES)
        if len(data) > limit:
            raise FetchFailed("too_large")
    if data.startswith(b"%PDF-"):
        return Fetched("http", url, content=bytes(data))
    if "html" not in response.headers.get("content-type", "html").lower():
        raise FetchFailed("not_a_pdf")
    return Fetched("http", url, links=pdf_links(data.decode("utf-8", "replace"), url))


async def browser_fetch(url: str, limit_bytes: int) -> Fetched:
    # A direct PDF can be read twice: once by the navigation, then by the download.
    async with GuardedProxy(limit_bytes * 2 + MAX_HTML_BYTES) as proxy:
        try:
            # The sync API runs its own event loop in this thread. That also keeps it working on
            # Windows, where the server's selector loop can't start a browser process.
            return await asyncio.wait_for(
                asyncio.to_thread(_browser_fetch, url, limit_bytes, proxy.url),
                timeout=TIMEOUT_S * 2,
            )
        except FetchFailed as exc:
            if exc.reason == "browser_error" and proxy.over_limit:
                raise FetchFailed("too_large") from exc
            if exc.reason == "browser_error" and proxy.blocked:
                raise FetchFailed("blocked") from exc
            raise


def _public_url(url: str) -> bool:
    try:
        host, port = parse_url(url)
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (UrlRejected, OSError):
        return False
    return all(is_public(info[4][0]) for info in infos)


def _browser_fetch(url: str, limit_bytes: int, proxy_url: str) -> Fetched:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    if not _public_url(url):
        raise FetchFailed("blocked")

    def guard(route) -> None:
        request = route.request
        if request.resource_type in ("image", "font", "media"):
            route.abort()
        elif request.url.startswith(("http:", "https:")) and not _public_url(request.url):
            route.abort("blockedbyclient")
        else:
            route.continue_()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(proxy={"server": proxy_url})
            try:
                context = browser.new_context(user_agent=USER_AGENT)
                context.route("**/*", guard)
                page = context.new_page()
                pdf_responses: list[str] = []
                page.on(
                    "response",
                    lambda r: pdf_responses.append(r.url)
                    if "pdf" in r.headers.get("content-type", "").lower()
                    else None,
                )
                final_url, links = url, []
                try:
                    page.goto(url, timeout=TIMEOUT_S * 1000, wait_until="domcontentloaded")
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PlaywrightError as exc:
                    # Chromium treats a direct PDF as a download and aborts the navigation.
                    if "Download" not in str(exc) and "ERR_ABORTED" not in str(exc) and (
                        "Timeout" not in str(exc)
                    ):
                        raise
                else:
                    final_url = page.url
                if pdf_responses:
                    final_url = pdf_responses[0]
                else:
                    try:
                        links = pdf_links(page.content(), final_url)
                    except PlaywrightError:
                        links = []
                if links:
                    return Fetched("browser", final_url, links=links)
                return _browser_download(context, final_url, limit_bytes)
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise FetchFailed("browser_error") from exc


def _browser_download(context, url: str, limit_bytes: int) -> Fetched:
    for _ in range(MAX_REDIRECTS + 1):
        if not _public_url(url):
            raise FetchFailed("blocked")
        response = context.request.get(url, max_redirects=0, timeout=TIMEOUT_S * 1000)
        if response.status in (301, 302, 303, 307, 308):
            url = urljoin(url, response.headers.get("location", ""))
            continue
        if response.status >= 400:
            raise FetchFailed(f"http_{response.status}")
        if int(response.headers.get("content-length") or 0) > limit_bytes:
            raise FetchFailed("too_large")
        body = response.body()
        if len(body) > limit_bytes:
            raise FetchFailed("too_large")
        if body.startswith(b"%PDF-"):
            return Fetched("browser", url, content=body)
        raise FetchFailed("not_a_pdf")
    raise FetchFailed("too_many_redirects")
