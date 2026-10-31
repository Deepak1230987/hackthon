import asyncio

import pytest
from sqlalchemy import func, select, text

from app.acquisition import fetchers
from app.acquisition.fetchers import Fetched, FetchFailed
from app.db.models import Clause, Document
from tests.conftest import make_pdf, make_scanned_pdf
from tests.integration.test_runs import upload

pytestmark = pytest.mark.integration


async def wait_for_end(client, run_id):
    for _ in range(400):
        view = (await client.get(f"/v1/runs/{run_id}")).json()
        if view["status"] in ("completed", "partial", "failed"):
            return view
        await asyncio.sleep(0.05)
    raise AssertionError(f"Run didn't finish: {view}")


def events_of(view, kind):
    return [e["payload"] for e in view["events"] if e["type"] == kind]


async def clauses_of(client, view):
    return (await client.get(f"/v1/documents/{view['document']['id']}/clauses")).json()


async def start_url(client, url="https://8.8.8.8/a.pdf"):
    response = await client.post("/v1/documents", json={"url": url, "language": "hi"})
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


@pytest.fixture
def fake_fetchers(monkeypatch):
    """Replace the two fetch tiers with functions a test can set."""

    class Tiers:
        http = None
        browser = None

    async def fail(url, limit):
        raise FetchFailed("connection")

    Tiers.http = Tiers.browser = staticmethod(fail)

    async def http(url, limit):
        return await Tiers.http(url, limit)

    async def browser(url, limit):
        return await Tiers.browser(url, limit)

    monkeypatch.setattr(fetchers, "http_fetch", http)
    monkeypatch.setattr(fetchers, "browser_fetch", browser)
    return Tiers


async def test_digital_pdf_becomes_clauses_with_positions(client, gateway):
    run = await upload(client, make_pdf("1. Every resident may apply for this scheme."))
    view = await wait_for_end(client, run)
    assert view["status"] == "completed"
    body = await clauses_of(client, view)
    clause = body["clauses"][0]
    assert clause["text"] == "1. Every resident may apply for this scheme."
    assert clause["page"] == 1
    assert clause["extraction"] == "native"
    assert len(clause["bbox"]) == 4
    assert gateway.ocr_calls == 0
    assert events_of(view, "segment_done")[0]["clauses"] == 1


async def test_scanned_pdf_goes_through_ocr(client, gateway, app):
    view = await wait_for_end(client, await upload(client, make_scanned_pdf(seed=1, pages=2)))
    assert view["status"] == "completed"
    assert view["document"]["is_scanned"] is True
    assert gateway.ocr_calls == 2
    assert len(events_of(view, "page_ocr")) == 2
    clauses = (await clauses_of(client, view))["clauses"]
    assert {c["extraction"] for c in clauses} == {"ocr"}
    assert all(c["bbox"] is None for c in clauses)
    assert clauses[0]["lang"] == "hi"
    assert any(c["kind"] == "table_row" and "₹5,000" in c["text"] for c in clauses)


async def test_norm_text_and_embeddings_are_stored(client, app):
    view = await wait_for_end(client, await upload(client, make_scanned_pdf(seed=2)))
    async with app.state.services.deps.sessions() as session:
        rows = (await session.scalars(
            select(Clause).where(Clause.document_id == view["document"]["id"])
        )).all()
    assert all(row.embedding is not None for row in rows)
    assert all(row.norm_text == row.norm_text.casefold() for row in rows)


async def test_second_run_does_no_repeat_work(client, gateway):
    content = make_scanned_pdf(seed=3, pages=2)
    first = await wait_for_end(client, await upload(client, content))
    ocr, embeds = gateway.ocr_calls, gateway.embed_calls
    before = await clauses_of(client, first)

    second = await wait_for_end(client, await upload(client, content))
    assert second["status"] == "completed"
    assert gateway.ocr_calls == ocr
    assert gateway.embed_calls == embeds
    assert await clauses_of(client, second) == before


async def test_failed_ocr_page_is_reported_then_recovered_in_reading_order(client, gateway):
    gateway.ocr_failures = 1
    content = make_scanned_pdf(seed=4, pages=2)
    first = await wait_for_end(client, await upload(client, content))
    assert first["status"] == "partial"
    body = await clauses_of(client, first)
    assert len(body["failed_pages"]) == 1
    assert events_of(first, "segment_done")[0]["failed_pages"] == body["failed_pages"]
    kept = {c["id"]: c["text"] for c in body["clauses"]}

    second = await wait_for_end(client, await upload(client, content))
    assert second["status"] == "completed"
    after = await clauses_of(client, second)
    assert after["failed_pages"] == []
    assert len(after["clauses"]) == 2 * len(kept)
    # Citations held by earlier runs store ids, which must keep pointing at the same text.
    assert {c["id"]: c["text"] for c in after["clauses"] if c["id"] in kept} == kept
    assert [c["ordinal"] for c in after["clauses"]] == list(range(1, len(after["clauses"]) + 1))
    pages = [c["page"] for c in after["clauses"]]
    assert pages == sorted(pages)


async def test_all_pages_failing_is_a_clear_error(client, gateway):
    gateway.ocr_failures = 5
    view = await wait_for_end(client, await upload(client, make_scanned_pdf(seed=5)))
    assert view["status"] == "failed"
    assert view["error"]["code"] == "PROVIDERS_UNAVAILABLE"


async def test_embedding_failure_is_not_fatal_and_is_retried(client, gateway, app):
    gateway.embed_fails = True
    content = make_pdf("Embedding failure should leave the clauses usable here.")
    first = await wait_for_end(client, await upload(client, content))
    assert first["status"] == "completed"
    assert events_of(first, "segment_done")[0]["embedded"] is False

    gateway.embed_fails = False
    second = await wait_for_end(client, await upload(client, content))
    assert events_of(second, "segment_done")[0]["embedded"] is True


async def test_database_outage_returns_the_error_format(app, client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def down():
        raise OperationalError("SELECT 1", {}, OSError("network down"))

    monkeypatch.setattr(app.state.services.deps, "sessions", down)
    response = await client.get("/v1/library")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


async def test_blank_pdf_is_a_clear_error(client):
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    view = await wait_for_end(client, await upload(client, document.tobytes()))
    assert view["status"] == "failed"
    assert view["error"]["code"] == "NO_READABLE_TEXT"


async def test_too_many_pages_is_stopped_before_any_ocr(client, gateway, settings):
    settings.max_pages = 2
    view = await wait_for_end(client, await upload(client, make_scanned_pdf(seed=6, pages=3)))
    assert view["error"]["code"] == "DOC_TOO_LONG"
    assert gateway.ocr_calls == 0


async def test_same_document_run_twice_at_once_does_not_duplicate_clauses(client):
    content = make_pdf("Both of these runs read the same document at once here.")
    runs = await asyncio.gather(upload(client, content), upload(client, content))
    views = await asyncio.gather(*(wait_for_end(client, run) for run in runs))
    assert {v["status"] for v in views} == {"completed"}
    assert len((await clauses_of(client, views[0]))["clauses"]) == 1


async def test_url_input_fetches_and_records_provenance(client, fake_fetchers, storage):
    content = make_pdf("1. A rule fetched from an official site.")

    async def http(url, limit):
        return Fetched("http", "https://8.8.8.8/final.pdf", content=content)

    fake_fetchers.http = http
    view = await wait_for_end(client, await start_url(client))
    assert view["status"] == "completed"
    assert view["document"]["fetch_method"] == "http"
    assert view["document"]["source_url"] == "https://8.8.8.8/final.pdf"
    assert events_of(view, "fetch_attempt") == [{"method": "http"}]


async def test_url_fetch_adds_provenance_to_an_earlier_upload(client, fake_fetchers):
    content = make_pdf("4. A rule first uploaded, then fetched from its official link.")
    uploaded = await wait_for_end(client, await upload(client, content))
    assert uploaded["document"]["source_url"] is None

    async def http(url, limit):
        return Fetched("http", "https://8.8.8.8/official.pdf", content=content)

    fake_fetchers.http = http
    fetched = await wait_for_end(client, await start_url(client))
    assert fetched["document"]["id"] == uploaded["document"]["id"]
    assert fetched["document"]["source_url"] == "https://8.8.8.8/official.pdf"
    assert fetched["document"]["fetch_method"] == "http"


async def test_browser_is_tried_when_plain_fetch_fails(client, fake_fetchers):
    content = make_pdf("2. A rule only a real browser could reach here.")

    async def browser(url, limit):
        return Fetched("browser", url, content=content)

    fake_fetchers.browser = browser
    view = await wait_for_end(client, await start_url(client))
    assert view["document"]["fetch_method"] == "browser"
    assert events_of(view, "fetch_attempt") == [{"method": "http"}, {"method": "browser"}]


async def test_unreachable_source_offers_upload_and_lists_attempts(client, fake_fetchers):
    view = await wait_for_end(client, await start_url(client))
    assert view["status"] == "failed"
    assert view["error"]["code"] == "SOURCE_UNREACHABLE"
    assert view["error"]["action"] == "upload"
    assert [a["method"] for a in view["error"]["details"]["attempts"]] == ["http", "browser"]


@pytest.mark.parametrize(
    ("reason", "code"), [("blocked", "URL_BLOCKED"), ("too_large", "FILE_TOO_LARGE")]
)
async def test_browser_is_not_tried_when_the_url_or_file_is_refused(
    client, fake_fetchers, reason, code
):
    async def http(url, limit):
        raise FetchFailed(reason)

    fake_fetchers.http = http
    view = await wait_for_end(client, await start_url(client))
    assert view["error"]["code"] == code
    assert events_of(view, "fetch_attempt") == [{"method": "http"}]


async def test_a_language_that_is_not_text_is_rejected(client):
    response = await client.post(
        "/v1/documents", json={"url": "https://8.8.8.8/a.pdf", "language": ["hi"]}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_LANGUAGE"


async def test_retrying_one_failed_page_keeps_a_document_marked_as_scanned(client, gateway):
    gateway.ocr_failures = 1
    content = make_scanned_pdf(seed=9, pages=4)
    await wait_for_end(client, await upload(client, content))
    view = await wait_for_end(client, await upload(client, content))
    assert view["status"] == "completed"
    assert view["document"]["is_scanned"] is True


async def test_page_with_one_pdf_link_is_followed(client, fake_fetchers):
    content = make_pdf("3. A rule linked once from a listing page here.")

    async def http(url, limit):
        if url.endswith("only.pdf"):
            return Fetched("http", url, content=content)
        return Fetched("http", url, links=[{"url": "https://8.8.8.8/only.pdf", "label": "Only"}])

    fake_fetchers.http = http
    view = await wait_for_end(client, await start_url(client, "https://8.8.8.8/list"))
    assert view["document"]["source_url"] == "https://8.8.8.8/only.pdf"


async def test_page_with_several_pdf_links_returns_the_choices(client, fake_fetchers):
    options = [
        {"url": "https://8.8.8.8/a.pdf", "label": "A"},
        {"url": "https://8.8.8.8/b.pdf", "label": "B"},
    ]

    async def http(url, limit):
        return Fetched("http", url, links=options)

    fake_fetchers.http = http
    view = await wait_for_end(client, await start_url(client, "https://8.8.8.8/list"))
    assert view["error"]["code"] == "MULTIPLE_PDFS"
    assert view["error"]["details"]["options"] == options


async def test_library_lists_only_marked_documents_and_runs_without_refetching(
    app, client, fake_fetchers, gateway
):
    listed = (await upload(client, make_scanned_pdf(seed=7)))
    view = await wait_for_end(client, listed)
    await wait_for_end(client, await upload(client, make_pdf("Not marked for the library at all.")))
    async with app.state.services.deps.sessions() as session:
        await session.execute(
            text("UPDATE documents SET in_library = true, title = 'Real scheme' WHERE id = :id"),
            {"id": view["document"]["id"]},
        )
        await session.commit()

    library = (await client.get("/v1/library")).json()["documents"]
    assert view["document"]["id"] in [d["id"] for d in library]
    assert all(d["title"] for d in library)

    calls = gateway.ocr_calls
    response = await client.post(
        f"/v1/library/{view['document']['id']}/runs", json={"language": "hi"}
    )
    assert response.status_code == 202
    run = await wait_for_end(client, response.json()["run_id"])
    assert run["status"] == "completed"
    assert run["document"]["id"] == view["document"]["id"]
    assert gateway.ocr_calls == calls
    assert events_of(run, "fetch_attempt") == []


async def test_library_rejects_a_document_not_in_it(client):
    view = await wait_for_end(client, await upload(client, make_pdf("Never added to the library.")))
    response = await client.post(
        f"/v1/library/{view['document']['id']}/runs", json={"language": "hi"}
    )
    assert response.status_code == 404


async def test_restart_during_ocr_does_not_redo_finished_pages(settings, storage, gateway):
    """A resumed run asks OCR only for the pages it hadn't finished."""
    import httpx

    from app.main import create_app

    content = make_scanned_pdf(seed=8, pages=4)
    original = gateway.vision_ocr
    release = asyncio.Event()
    finished = asyncio.Event()

    async def slow_after_two(image):
        if gateway.ocr_calls >= 2:
            finished.set()
            await release.wait()
        return await original(image)

    gateway.vision_ocr = slow_after_two
    first = create_app(settings, storage, gateway)
    async with first.router.lifespan_context(first):
        transport = httpx.ASGITransport(app=first)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            run = await upload(http, content)
            await asyncio.wait_for(finished.wait(), timeout=10)
            await asyncio.sleep(0.3)

    done_before = gateway.ocr_calls
    assert done_before < 4
    gateway.vision_ocr = original
    second = create_app(settings, storage, gateway)
    async with second.router.lifespan_context(second):
        transport = httpx.ASGITransport(app=second)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            view = await wait_for_end(http, run)
    assert view["status"] == "completed", view["error"]
    assert gateway.ocr_calls <= 4


async def test_document_row_count_stays_one_per_file(app, client):
    content = make_pdf("Only one row should exist for this file ever.")
    await asyncio.gather(*[wait_for_end(client, await upload(client, content)) for _ in range(2)])
    import hashlib

    async with app.state.services.deps.sessions() as session:
        count = await session.scalar(
            select(func.count()).select_from(Document).where(
                Document.sha256 == hashlib.sha256(content).hexdigest()
            )
        )
    assert count == 1
