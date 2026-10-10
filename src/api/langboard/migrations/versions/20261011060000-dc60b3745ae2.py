"""Bind runtime permits to the credential that authorized them."""

from datetime import datetime, timezone
import sqlalchemy as sa
from alembic import op


revision = "dc60b3745ae2"
down_revision = "cb5fa26349d1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_execution_lease", sa.Column("credential_id", sa.BigInteger(), nullable=True))
    # Existing permits have no trustworthy credential lineage. Fail closed;
    # do not infer an authorizer from other currently valid app credentials.
    leases = sa.table(
        "app_execution_lease",
        sa.column("id", sa.BigInteger()),
        sa.column("state", sa.String()),
        sa.column("history", sa.JSON()),
    )
    db = op.get_bind()
    at = datetime.now(timezone.utc).isoformat()
    for row in db.execute(sa.select(leases.c.id, leases.c.history).where(leases.c.state == "authorized")).all():
        db.execute(
            leases.update()
            .where(leases.c.id == row.id)
            .values(
                state="stop_requested",
                history=[
                    *(row.history or []),
                    {"state": "stop_requested", "at": at, "reason": "credential_lineage_missing"},
                ],
            )
        )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_execution_lease LIMIT 1")).first():
        raise RuntimeError("Cannot remove runtime credential fencing with retained permits")
    op.drop_column("app_execution_lease", "credential_id")
