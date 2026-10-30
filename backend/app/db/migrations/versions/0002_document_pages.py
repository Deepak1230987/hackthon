"""Create the document_pages table.

Written from the live database schema, because the original file wasn't pushed.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_pages (
          document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
          page int NOT NULL,
          extraction text NOT NULL,
          status text NOT NULL,
          ocr_reason text,
          data jsonb NOT NULL,
          segmented boolean NOT NULL DEFAULT false,
          PRIMARY KEY (document_id, page)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE document_pages")
