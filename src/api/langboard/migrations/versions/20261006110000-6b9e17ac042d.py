"""Search existing Docling transcriptions without embeddings or graph execution."""

import json
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.types import SnowflakeID


revision = "6b9e17ac042d"
down_revision = "2f8c4d0e9a61"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("card_attachment") as batch:
        batch.add_column(sa.Column("document_text", sa.Text(), nullable=False, server_default=""))
    bind = op.get_bind()
    # One-time database projection only: no file reads, inference or embedding calls.
    cursor = 0
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT id, card_id, value FROM card_metadata WHERE key = :key AND id > :cursor ORDER BY id LIMIT 100"
            ),
            {"key": "__system.docling_documents", "cursor": cursor},
        ).all()
        if not rows:
            break
        for row in rows:
            cursor = row.id
            try:
                documents = json.loads(row.value)
            except (ValueError, TypeError):
                continue
            if not isinstance(documents, list):
                continue
            for document in documents:
                if not isinstance(document, dict):
                    continue
                content = document.get("content")
                markdown = content.get("markdown") if isinstance(content, dict) else None
                uid = document.get("attachment_uid")
                if not isinstance(markdown, str) or not isinstance(uid, str):
                    continue
                try:
                    attachment_id = int(SnowflakeID.from_short_code(uid))
                except (ValueError, TypeError):
                    continue
                bind.execute(
                    sa.text(
                        "UPDATE card_attachment SET document_text = :content "
                        "WHERE id = :id AND card_id = :card_id AND deleted_at IS NULL"
                    ),
                    {"content": markdown, "id": attachment_id, "card_id": row.card_id},
                )
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        op.create_index(
            "ix_card_attachment_document_text_trgm",
            "card_attachment",
            ["document_text"],
            postgresql_using="gin",
            postgresql_ops={"document_text": "gin_trgm_ops"},
            postgresql_where=sa.text("deleted_at IS NULL AND document_text <> ''"),
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_card_attachment_document_text_trgm", table_name="card_attachment")
    with op.batch_alter_table("card_attachment") as batch:
        batch.drop_column("document_text")
