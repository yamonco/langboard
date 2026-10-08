"""Rotation migration accepts both deployed constraint naming generations."""

import ast
import importlib.util
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20261008072000-a430de35fc79.py"


@pytest.mark.parametrize("legacy", [True, False])
def test_rotation_constraint_preserves_audit_and_blocks_loss(legacy):
    tree = ast.parse((ROOT / "src/shared/py/langboard_shared/core/db/Models.py").read_text())
    naming = next(
        ast.literal_eval(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "MetaData"
        for keyword in node.keywords
        if keyword.arg == "naming_convention"
    )
    metadata = sa.MetaData(naming_convention=naming)
    name = "ck_secret_reference_audit_action"
    table = sa.Table(
        "secret_reference_audit",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("action", sa.String, nullable=False),
        sa.CheckConstraint(
            "action IN ('created','resolved','renamed','moved','revoked')",
            name=name if legacy else sa.schema.conv(name),
        ),
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(table.insert().values(id=1, action="created"))
        spec = importlib.util.spec_from_file_location("rotation_migration", MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.op = Operations(MigrationContext.configure(connection, opts={"target_metadata": metadata}))
        module.upgrade()
        assert connection.execute(sa.select(table.c.action)).scalars().all() == ["created"]
        checks = sa.inspect(connection).get_check_constraints(table.name)
        assert [item["name"] for item in checks] == [name]
        connection.execute(table.insert().values(id=2, action="rotated"))
        with pytest.raises(RuntimeError, match="Cannot discard credential rotation audit"):
            module.downgrade()
        connection.execute(table.delete().where(table.c.id == 2))
        module.downgrade()
        assert connection.execute(sa.select(table.c.action)).scalars().all() == ["created"]
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(table.insert().values(id=3, action="rotated"))
