# Haq backend

Needs [uv](https://docs.astral.sh/uv/). Run commands from `backend/`.

## Set up

1. Copy `.env.example` from the repo root to `.env`, and fill in `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` and `EMBEDDING_DIM`.
2. Create the storage bucket named by `STORAGE_BUCKET` in Supabase. Keep it private.
3. Install and migrate:

```
uv sync
uv run alembic upgrade head
```

## Run

```
uv run python -m app
```

The API listens on port 8000. Check it at `http://localhost:8000/v1/health`.

Try a run:

```
curl -F file=@policy.pdf -F language=hi http://localhost:8000/v1/documents
curl -N http://localhost:8000/v1/runs/<run_id>/events
```

## Add a document to the library

With the API running, this sends a real document through the pipeline and lists it if the run completes. Read the document to get its title, and use its official URL.

```
uv run python -m app.add_to_library <pdf-url> --title "Scheme guidelines"
```

## Test

Unit tests need nothing else. Integration tests need a Postgres with pgvector, and they **wipe the database they connect to**, so never point them at Supabase.

```
docker run -d --name haq-test-db -e POSTGRES_PASSWORD=test -p 54329:5432 pgvector/pgvector:pg16
$env:TEST_DATABASE_URL = "postgresql://postgres:test@localhost:54329/postgres"
uv run pytest
```

Without `TEST_DATABASE_URL`, integration tests are skipped.
