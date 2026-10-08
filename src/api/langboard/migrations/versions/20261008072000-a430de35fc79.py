"""Allow explicit credential rotation audit while preserving prior records."""

import sqlalchemy as sa
from alembic import op


revision = "a430de35fc79"
down_revision = "932fcd24eb68"
branch_labels = None
depends_on = None


def replace_action_constraint(actions):
    names = {item["name"] for item in sa.inspect(op.get_bind()).get_check_constraints("secret_reference_audit")}
    candidates = names & {
        "ck_secret_reference_audit_action",
        "ck_secret_reference_audit_`ck_secret_reference_audit_action`",
    }
    if len(candidates) != 1:
        raise RuntimeError("Expected exactly one secret audit action constraint")
    with op.batch_alter_table("secret_reference_audit") as batch:
        batch.drop_constraint(sa.schema.conv(candidates.pop()), type_="check")
        batch.create_check_constraint(sa.schema.conv("ck_secret_reference_audit_action"), f"action IN ({actions})")


def upgrade():
    replace_action_constraint("'created','resolved','renamed','moved','revoked','rotated'")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM secret_reference_audit WHERE action='rotated' LIMIT 1")).first():
        raise RuntimeError("Cannot discard credential rotation audit")
    replace_action_constraint("'created','resolved','renamed','moved','revoked'")
