"""Index exact live attachment provenance without changing stored files."""

from alembic import op


revision = "48f716ecb2d0"
down_revision = "3d5a71e8c942"
branch_labels = None
depends_on = None
INDEX_NAME = "ix_card_attachment_live_file_identity"


def _dialect():
    dialect = op.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError("Attachment provenance index requires SQLite or PostgreSQL")
    return dialect


def upgrade():
    dialect = _dialect()
    # FileModel is stored as a JSON string inside the JSON column.
    keys = ("storage_type", "storage_name", "filename")
    if dialect == "postgresql":
        expressions = [f"((file::jsonb #>> ARRAY[]::text[])::jsonb ->> '{key}')" for key in keys]
    else:
        expressions = [f"json_extract(json_extract(file, '$'), '$.{key}')" for key in keys]
    op.execute(f"CREATE INDEX {INDEX_NAME} ON card_attachment ({', '.join(expressions)}) WHERE deleted_at IS NULL")


def downgrade():
    _dialect()
    op.drop_index(INDEX_NAME, table_name="card_attachment")
