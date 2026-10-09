"""Preserve per-reference evidence for trusted vault provider migration."""

import sqlalchemy as sa
from alembic import op


revision = "b51832cfe4a7"
down_revision = "862af3c591d7"
branch_labels = None
depends_on = None


def _replace(actions):
    with op.batch_alter_table("secret_reference_audit") as batch:
        batch.drop_constraint(sa.schema.conv("ck_secret_reference_audit_action"), type_="check")
        batch.create_check_constraint(sa.schema.conv("ck_secret_reference_audit_action"), f"action IN ({actions})")


def upgrade():
    _replace("'created','resolved','renamed','moved','revoked','rotated','bound','migrated'")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM secret_reference_audit WHERE action='migrated' LIMIT 1")).first():
        raise RuntimeError("Cannot discard secret provider migration audit facts")
    _replace("'created','resolved','renamed','moved','revoked','rotated','bound'")
