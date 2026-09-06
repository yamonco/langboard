"""Backward-compatible template guidance and additive schema migration proof."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard.routes.board.forms import ColumnDescriptionForm, CreateColumnForm
from langboard_shared.domain.models import ProjectTemplate
from langboard_shared.domain.services.factory.ProjectTemplateService import ProjectTemplateService


@pytest.mark.parametrize("descriptions", [[], ["First queue", "Second queue"]])
def test_template_creation_preserves_order_and_legacy_empty_guidance(descriptions: list[str]) -> None:
    """Descriptions follow positions, including duplicate column names and older templates."""
    template = ProjectTemplate(name="Duplicate", columns=["Queue", "Queue"], column_descriptions=descriptions)
    archive = SimpleNamespace(order=-1)
    repository = SimpleNamespace(
        project_column=SimpleNamespace(get_or_create_archive_if_not_exists=lambda _: archive, update=Mock())
    )
    created: list[SimpleNamespace] = []
    project = SimpleNamespace(id=1)

    def create_column(_user: object, _project: object, name: str, description: str = "") -> SimpleNamespace:
        column = SimpleNamespace(name=name, description=description, order=99)
        created.append(column)
        return column

    services = {
        "project": SimpleNamespace(create=Mock(return_value=project), delete=Mock()),
        "project_column": SimpleNamespace(create=create_column),
    }
    service = ProjectTemplateService(lambda _: None, services.__getitem__, repository)
    service.get = Mock(return_value=template)
    service._apply_internal_bots = Mock()
    service._apply_scopes = Mock()
    service._apply_email_notification_policy = Mock()
    _, columns, _ = service.create_project(object(), "Test", template_name="Duplicate")
    assert [column.name for column in columns] == ["Queue", "Queue"]
    assert [column.description for column in columns] == (descriptions or ["", ""])
    assert [column.order for column in columns] == [0, 1] and archive.order == 2
    services["project"].delete.assert_not_called()


def test_column_forms_keep_name_only_creation_and_bound_guidance() -> None:
    """Old clients may omit descriptions; clearing and length limits remain explicit."""
    assert CreateColumnForm(name="Queue").description == ""
    assert ColumnDescriptionForm(description="").description == ""
    with pytest.raises(ValueError):
        ColumnDescriptionForm(description="x" * 4097)


def test_guidance_migration_preserves_existing_rows_and_roundtrips(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schema changes do not rename columns, rewrite template structure, or lose rows."""
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20260906072000-7a92d6c13f04.py"
    spec = importlib.util.spec_from_file_location("column_guidance_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE project_column (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
            connection.execute(sa.text("CREATE TABLE project_template (id INTEGER PRIMARY KEY, columns JSON NOT NULL)"))
            connection.execute(sa.text("INSERT INTO project_column VALUES (1, 'Keep name')"))
            connection.execute(sa.text('INSERT INTO project_template VALUES (1, \'["Queue","Queue"]\')'))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.execute(sa.text("SELECT name, description FROM project_column")).one() == (
                "Keep name",
                "",
            )
            assert connection.execute(sa.text("SELECT columns, column_descriptions FROM project_template")).one() == (
                '["Queue","Queue"]',
                "[]",
            )
            migration.downgrade()
            assert connection.execute(sa.text("SELECT name FROM project_column")).scalar_one() == "Keep name"
            assert (
                connection.execute(sa.text("SELECT columns FROM project_template")).scalar_one() == '["Queue","Queue"]'
            )
    finally:
        engine.dispose()
