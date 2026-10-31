import httpcore
import httpx
import pytest

from app.acquisition.fetchers import FetchFailed, guarded_transport, http_fetch, pdf_links
from app.acquisition.ssrf import GuardedBackend, UrlRejected, check_url, is_public, parse_url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.gov.in/a.pdf",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://",
        "not a url",
        "https://example.gov.in:8443/a.pdf",
        "http://example.gov.in:22/",
        "https://user:pass@example.gov.in/a.pdf",
        "https://" + "a" * 70 + ".gov.in/a.pdf",  # DNS can't encode this label
        "https://.gov.in/a.pdf",
        "https://exa\x00mple.gov.in/a.pdf",
    ],
)
def test_rejects_bad_urls(url):
    with pytest.raises(UrlRejected) as caught:
        parse_url(url)
    assert caught.value.code == "INVALID_URL"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://100.64.0.1/",  # carrier-grade NAT
        "http://[::1]/",
        "http://[fd00::1]/",
        "http://[::ffff:127.0.0.1]/",  # IPv4 hidden inside IPv6
        "http://2130706433/",  # 127.0.0.1 as a decimal
        "http://0x7f.0.0.1/",
        "http://0/",
        "http://224.0.0.1/",  # multicast
    ],
)
async def test_blocks_internal_addresses(url):
    with pytest.raises(UrlRejected) as caught:
        await check_url(url)
    assert caught.value.code == "URL_BLOCKED"


@pytest.mark.parametrize(
    ("address", "public"),
    [("8.8.8.8", True), ("2001:4860:4860::8888", True), ("10.1.1.1", False), ("::1", False)],
)
def test_is_public(address, public):
    assert is_public(address) is public


async def test_connection_is_refused_if_dns_now_points_inside(monkeypatch):
    """DNS rebinding: a name passes the first check, then resolves to an internal address."""

    async def rebound(host, port):
        raise UrlRejected("URL_BLOCKED", "blocked")

    monkeypatch.setattr("app.acquisition.ssrf.resolve_public", rebound)

    class NeverConnects(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, *args, **kwargs):
            raise AssertionError("must not connect")

    with pytest.raises(httpcore.ConnectError):
        await GuardedBackend(NeverConnects()).connect_tcp("evil.example", 80)


def test_real_transport_uses_the_guard():
    assert isinstance(guarded_transport()._pool._network_backend, GuardedBackend)


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_redirect_to_internal_address_is_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/secrets.pdf"})

    with pytest.raises(FetchFailed) as caught:
        await http_fetch("https://8.8.8.8/a.pdf", 1024, _transport(handler))
    assert caught.value.reason == "blocked"


async def test_redirect_loop_stops():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://8.8.8.8/again.pdf"})

    with pytest.raises(FetchFailed) as caught:
        await http_fetch("https://8.8.8.8/a.pdf", 1024, _transport(handler))
    assert caught.value.reason == "too_many_redirects"


async def test_follows_redirect_and_reads_pdf():
    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b.pdf"})
        return httpx.Response(200, content=b"%PDF-1.7 body")

    fetched = await http_fetch("https://8.8.8.8/a", 1024, _transport(handler))
    assert fetched.content == b"%PDF-1.7 body"
    assert fetched.url == "https://8.8.8.8/b.pdf"
    assert fetched.method == "http"


async def test_stops_reading_at_the_size_limit():
    def handler(request):
        return httpx.Response(200, content=b"%PDF-" + b"x" * 5000)

    with pytest.raises(FetchFailed) as caught:
        await http_fetch("https://8.8.8.8/a.pdf", 1024, _transport(handler))
    assert caught.value.reason == "too_large"


@pytest.mark.parametrize(
    ("status", "reason"), [(403, "http_403"), (404, "http_404"), (500, "http_500")]
)
async def test_http_errors_are_reported(status, reason):
    with pytest.raises(FetchFailed) as caught:
        await http_fetch(
            "https://8.8.8.8/a.pdf", 1024, _transport(lambda r: httpx.Response(status))
        )
    assert caught.value.reason == reason


async def test_html_page_returns_its_pdf_links():
    html = '<a href="/x/one.pdf"> One </a><a href="/page">Not this</a><a href="two.PDF">Two</a>'

    def handler(request):
        return httpx.Response(200, html=html)

    fetched = await http_fetch("https://8.8.8.8/dir/", 1024 * 1024, _transport(handler))
    assert fetched.content is None
    assert fetched.links == [
        {"url": "https://8.8.8.8/x/one.pdf", "label": "One"},
        {"url": "https://8.8.8.8/dir/two.PDF", "label": "Two"},
    ]


async def test_non_html_non_pdf_is_rejected():
    def handler(request):
        return httpx.Response(200, content=b"PK\x03\x04", headers={"content-type": "application/zip"})

    with pytest.raises(FetchFailed) as caught:
        await http_fetch("https://8.8.8.8/a.pdf", 1024, _transport(handler))
    assert caught.value.reason == "not_a_pdf"


async def test_redirect_with_no_location_is_a_clean_failure():
    with pytest.raises(FetchFailed) as caught:
        await http_fetch("https://8.8.8.8/a.pdf", 1024, _transport(lambda r: httpx.Response(302)))
    assert caught.value.reason == "http_302"


async def test_redirect_to_an_unusable_url_is_a_clean_failure():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://[bad"})

    with pytest.raises(FetchFailed) as caught:
        await http_fetch("https://8.8.8.8/a.pdf", 1024, _transport(handler))
    assert caught.value.reason == "bad_redirect"


def test_pdf_link_encoded_twice_is_repaired():
    # As published on pmkisan.gov.in: UTF-8 bytes read as Windows-1252, then encoded again.
    name = "प्रधानमंत्री किसान.pdf"
    mangled = "".join(
        bytes([b]).decode("cp1252") if b not in (0x81, 0x8D, 0x8F, 0x90, 0x9D) else chr(b)
        for b in name.encode()
    )
    html = f'<a href="/Documents/{mangled}">Hindi Version</a>'
    assert pdf_links(html, "https://8.8.8.8/")[0]["url"] == f"https://8.8.8.8/Documents/{name}"


@pytest.mark.parametrize(
    "name", ["प्रधानमंत्री.pdf", "Yojanā é.pdf", "plain name.pdf"]
)
def test_pdf_link_encoded_once_is_left_alone(name):
    html = f'<a href="/{name}">x</a>'
    assert pdf_links(html, "https://8.8.8.8/")[0]["url"] == f"https://8.8.8.8/{name}"


def test_pdf_links_are_deduplicated():
    html = '<a href="a.pdf">x</a><a href="a.pdf">y</a>'
    assert len(pdf_links(html, "https://8.8.8.8/")) == 1
