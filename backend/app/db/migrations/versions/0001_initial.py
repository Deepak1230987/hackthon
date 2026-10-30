"""Create the initial tables."""

from alembic import op

from app.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    dim = get_settings().embedding_dim
    if not dim:
        raise RuntimeError("Set EMBEDDING_DIM to match EMBEDDING_MODEL before migrating.")

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"""
        CREATE TABLE documents (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          sha256 char(64) UNIQUE NOT NULL,
          source_url text,
          fetch_method text NOT NULL,
          fetched_at timestamptz NOT NULL,
          storage_path text NOT NULL,
          title text, issuing_authority text, issue_date date,
          page_count int NOT NULL, is_scanned boolean NOT NULL DEFAULT false,
          in_library boolean NOT NULL DEFAULT false
        );

        CREATE TABLE clauses (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
          ordinal int NOT NULL, page int NOT NULL,
          bbox real[4],
          text text NOT NULL, norm_text text NOT NULL, lang text NOT NULL,
          kind text NOT NULL,
          extraction text NOT NULL,
          embedding vector({int(dim)}),
          UNIQUE (document_id, ordinal)
        );

        CREATE TABLE runs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id uuid REFERENCES documents,
          language text NOT NULL,
          status text NOT NULL,
          source jsonb NOT NULL,
          error_code text, llm_calls int NOT NULL DEFAULT 0,
          sarvam_chars int NOT NULL DEFAULT 0, client_hash text,
          created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz
        );

        CREATE TABLE run_events (
          run_id uuid REFERENCES runs ON DELETE CASCADE,
          seq int, type text NOT NULL, payload jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (run_id, seq)
        );

        CREATE TABLE claims (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          run_id uuid NOT NULL REFERENCES runs ON DELETE CASCADE,
          field text NOT NULL,
          text text NOT NULL, clause_ids uuid[] NOT NULL, quote text,
          status text NOT NULL,
          failure_reason text, attempts int NOT NULL DEFAULT 0
        );

        CREATE TABLE rules (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          run_id uuid NOT NULL REFERENCES runs ON DELETE CASCADE,
          claim_id uuid NOT NULL REFERENCES claims,
          ast jsonb NOT NULL, fields_required text[] NOT NULL
        );

        CREATE TABLE sentences (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          run_id uuid NOT NULL REFERENCES runs ON DELETE CASCADE,
          ordinal int NOT NULL, language text NOT NULL,
          source_text text NOT NULL, translated_text text,
          claim_ids uuid[] NOT NULL, audio_path text,
          guard_status text NOT NULL,
          translator text,
          UNIQUE (run_id, language, ordinal)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE sentences, rules, claims, run_events, runs, clauses, documents"
    )
