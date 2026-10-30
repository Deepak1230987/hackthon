import asyncio
import hashlib
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.main import create_app
from tests.conftest import make_pdf

pytestmark = pytest.mark.integration


async def upload(client: httpx.AsyncClient, content: bytes, language: str = "hi") -> str:
    response = await client.post(
        "/v1/documents",
        files={"file": ("policy.pdf", content, "application/pdf")},
        data={"language": language},
    )
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


async def wait_for_end(client: httpx.AsyncClient, run_id: str) -> dict:
    for _ in range(200):
        view = (await client.get(f"/v1/runs/{run_id}")).json()
        if view["status"] in ("completed", "failed"):
            return view
        await asyncio.sleep(0.05)
    raise AssertionError(f"Run didn't finish: {view}")


def parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if fields:
            events.append(fields)
    return events


async def test_health_reports_database_and_keys(client):
    body = (await client.get("/v1/health")).json()
    assert body["database"] == "ok"
    assert set(body["keys_configured"]) == {"gemini", "openai", "sarvam", "supabase"}


async def test_upload_runs_to_the_end_and_stores_file_with_hash(client, storage):
    content = make_pdf()
    run_id = await upload(client, content)
    view = await wait_for_end(client, run_id)

    sha256 = hashlib.sha256(content).hexdigest()
    assert view["status"] == "completed"
    assert view["document"]["sha256"] == sha256
    assert view["document"]["fetch_method"] == "upload"
    assert view["document"]["page_count"] == 1
    assert storage.objects[f"pdfs/{sha256}.pdf"] == content

    served = await client.get(f"/v1/documents/{view['document']['id']}/file")
    assert served.content == content
    assert served.headers["content-type"] == "application/pdf"


async def test_trace_shows_which_nodes_are_not_built(client):
    run_id = await upload(client, make_pdf("trace"))
    view = await wait_for_end(client, run_id)
    finished = {s["node"]: s["implemented"] for s in view["steps"] if s["type"] == "node_finished"}
    assert finished["acquire"] is True
    assert finished["tts"] is False
    assert len(finished) == 12


async def test_same_file_reuses_the_document(client, storage):
    content = make_pdf("reuse")
    first = await wait_for_end(client, await upload(client, content))
    second = await wait_for_end(client, await upload(client, content))
    assert first["document"]["id"] == second["document"]["id"]
    assert storage.put_calls == 1


async def test_sse_replays_only_events_after_last_event_id(client):
    run_id = await upload(client, make_pdf("replay"))
    await wait_for_end(client, run_id)

    everything = parse_sse((await client.get(f"/v1/runs/{run_id}/events")).text)
    assert [int(e["id"]) for e in everything] == list(range(1, len(everything) + 1))
    assert everything[-1]["event"] == "run_completed"

    rest = parse_sse(
        (await client.get(f"/v1/runs/{run_id}/events", headers={"Last-Event-ID": "5"})).text
    )
    assert [e["id"] for e in rest] == [e["id"] for e in everything[5:]]


@pytest.mark.parametrize(
    ("content", "code"),
    [(b"not a pdf", "PDF_INVALID"), (make_pdf(password="secret"), "PDF_ENCRYPTED")],
)
async def test_bad_pdf_fails_with_an_event(client, content, code):
    run_id = await upload(client, content)
    view = await wait_for_end(client, run_id)
    assert view["status"] == "failed"
    assert view["error"]["code"] == code
    events = parse_sse((await client.get(f"/v1/runs/{run_id}/events")).text)
    assert events[-1]["event"] == "run_failed"


async def test_oversized_file_is_rejected(client, settings):
    response = await client.post(
        "/v1/documents",
        files={"file": ("big.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")},
        data={"language": "hi"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert not list(settings.upload_dir.iterdir())


async def test_request_errors_use_the_error_format(client):
    missing = await client.get(f"/v1/runs/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"

    url_input = await client.post("/v1/documents", json={"url": "https://x.in", "language": "hi"})
    assert url_input.json()["error"]["code"] == "URL_INPUT_UNAVAILABLE"

    bad_language = await client.post(
        "/v1/documents",
        files={"file": ("a.pdf", make_pdf(), "application/pdf")},
        data={"language": "xx"},
    )
    assert bad_language.json()["error"]["code"] == "INVALID_LANGUAGE"


async def test_concurrent_emits_get_unique_ordered_seq(app, client):
    run_id = await upload(client, make_pdf("concurrent"))
    await wait_for_end(client, run_id)
    events = app.state.services.deps.events
    await asyncio.gather(*(events.emit(run_id, "probe") for _ in range(20)))
    async with app.state.services.deps.sessions() as session:
        rows = await events.since(session, run_id, 0)
    seqs = [row.seq for row in rows]
    assert seqs == list(range(1, len(seqs) + 1))


async def test_restart_resumes_an_interrupted_run(settings, storage):
    content = make_pdf("restart")
    storage.hold = asyncio.Event()

    first = create_app(settings, storage)
    async with first.router.lifespan_context(first):
        transport = httpx.ASGITransport(app=first)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            run_id = await upload(http, content)
            await asyncio.wait_for(storage.entered.wait(), timeout=5)
    # The first app has shut down with the run stuck inside acquire.
    assert storage.objects == {}

    storage.hold = None
    second = create_app(settings, storage)
    async with second.router.lifespan_context(second):
        transport = httpx.ASGITransport(app=second)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            view = await wait_for_end(http, run_id)
            events = parse_sse((await http.get(f"/v1/runs/{run_id}/events")).text)

    assert view["status"] == "completed"
    assert view["document"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert [e["event"] for e in events].count("run_completed") == 1


async def test_checkpoints_are_written_to_postgres(app, client):
    run_id = await upload(client, make_pdf("checkpoint"))
    await wait_for_end(client, run_id)
    async with app.state.services.deps.sessions() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :id"), {"id": run_id}
        )
    assert count > 0
