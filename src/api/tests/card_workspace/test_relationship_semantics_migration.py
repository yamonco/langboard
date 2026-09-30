"""Migration keeps legacy edge identity while adding three distinct defaults."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


os.environ.setdefault("PROJECT_NAME", "langboard")
MIGRATION_PATH = Path(__file__).parents[2] / "langboard/migrations/versions/20260929121000-2c4e8a1f6b30.py"


def _migration():
    spec = importlib.util.spec_from_file_location("relationship_semantics", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_relationship_defaults_preserve_legacy_edges() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """CREATE TABLE global_card_relationship_type (
                       id BIGINT PRIMARY KEY, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                       parent_name VARCHAR NOT NULL, child_name VARCHAR NOT NULL,
                       description VARCHAR NOT NULL)"""
            )
        )
        connection.execute(
            sa.text("CREATE TABLE card_relationship (id BIGINT PRIMARY KEY, relationship_type_id BIGINT NOT NULL)")
        )
        connection.execute(
            sa.text(
                """INSERT INTO global_card_relationship_type
                   VALUES (7, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '선행작업', '후속작업', 'legacy')"""
            )
        )
        connection.execute(sa.text("INSERT INTO card_relationship VALUES (99, 7)"))

        migration = _migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        legacy = connection.execute(
            sa.text(
                """SELECT id, machine_semantic, is_system_default, is_active, affects_readiness
                   FROM global_card_relationship_type WHERE id = 7"""
            )
        ).one()
        assert tuple(legacy) == (7, None, 0, 0, 0)
        assert (
            connection.execute(sa.text("SELECT relationship_type_id FROM card_relationship WHERE id = 99")).scalar_one()
            == 7
        )
        defaults = connection.execute(
            sa.text(
                """SELECT machine_semantic, affects_readiness FROM global_card_relationship_type
                   WHERE is_system_default = true ORDER BY machine_semantic"""
            )
        ).all()
        assert defaults == [("blocks", 1), ("contains", 0), ("references", 0)]
        assert len({row[0] for row in defaults}) == 3

        # A used system type cannot be dropped on downgrade.
        blocks_id = connection.execute(
            sa.text("SELECT id FROM global_card_relationship_type WHERE machine_semantic = 'blocks'")
        ).scalar_one()
        connection.execute(sa.text("INSERT INTO card_relationship VALUES (100, :type_id)"), {"type_id": blocks_id})
        with pytest.raises(RuntimeError, match="have edges"):
            migration.downgrade()


def test_child_card_link_uses_containment_even_when_legacy_type_is_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard_shared.domain.services.factory.CardService import CardService
    from langboard_shared.helpers import InfraHelper

    legacy = SimpleNamespace(machine_semantic=None, is_system_default=False, is_active=True)
    contains = SimpleNamespace(machine_semantic="contains", is_system_default=True, is_active=True)
    monkeypatch.setattr(InfraHelper, "get_all", lambda _model: [legacy, contains])

    assert CardService._contains_relationship_type() is contains
    monkeypatch.setattr(InfraHelper, "get_all", lambda _model: [legacy])
    with pytest.raises(ValueError, match="contains relationship type is missing"):
        CardService._contains_relationship_type()


def test_edge_projection_exposes_semantic_without_reclassifying_legacy() -> None:
    from langboard_shared.domain.services.factory.CardRelationshipService import CardRelationshipService

    edge = SimpleNamespace(api_response=lambda: {"uid": "edge", "relationship_type_uid": "legacy"})
    legacy = SimpleNamespace(
        parent_name="선행작업",
        child_name="후속작업",
        machine_semantic=None,
        affects_readiness=False,
        is_system_default=False,
    )
    result = CardRelationshipService.public_relationship(edge, legacy)
    assert result["relationship_type_uid"] == "legacy"
    assert result["machine_semantic"] is None
    assert result["affects_readiness"] is False


def test_system_relationship_type_cannot_be_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard_shared.domain.services.factory.AppSettingService import AppSettingService
    from langboard_shared.helpers import InfraHelper

    relation_type = SimpleNamespace(is_system_default=True)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, _uid: relation_type)
    delete = Mock()
    service = SimpleNamespace(repo=SimpleNamespace(global_card_relationship_type=SimpleNamespace(delete=delete)))

    with pytest.raises(ValueError, match="cannot be deleted"):
        AppSettingService.delete_global_relationship(service, "system")
    with pytest.raises(ValueError, match="cannot be deleted"):
        AppSettingService.delete_selected_global_relationships(service, ["system"])
    delete.assert_not_called()
