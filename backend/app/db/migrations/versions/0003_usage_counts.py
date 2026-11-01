"""Count each run's questions and speech calls, so their limits survive a restart."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE runs
          ADD COLUMN qa_calls int NOT NULL DEFAULT 0,
          ADD COLUMN stt_calls int NOT NULL DEFAULT 0;
        CREATE INDEX runs_client_hash_created_at ON runs (client_hash, created_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX runs_client_hash_created_at;
        ALTER TABLE runs DROP COLUMN qa_calls, DROP COLUMN stt_calls;
        """
    )
