"""Workflow guidance changes preserve unrelated column and card state."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ....helpers import InfraHelper
from ....publishers import ProjectColumnPublisher
from .ProjectColumnService import ProjectColumnService


def test_description_change_is_scoped_bounded_and_replay_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """The service checks column ancestry before updating guidance and never touches cards."""
    column = SimpleNamespace(name="Standby", order=3, description="Old", is_archive=False, get_uid=lambda: "c")
    project = object()
    update, publish = Mock(), Mock()
    repository = SimpleNamespace(project_column=SimpleNamespace(update=update))
    service = ProjectColumnService(lambda _: None, lambda _: None, repository)
    monkeypatch.setattr(InfraHelper, "get_records_with_foreign_by_params", lambda *_: (project, column))
    monkeypatch.setattr(ProjectColumnPublisher, "description_changed", publish)
    assert service.change_description("p", "c", "Owned work, waiting to start") is True
    assert column.name == "Standby" and column.order == 3
    update.assert_called_once_with(column)
    publish.assert_called_once_with(project, column)
    assert service.change_description("p", "c", column.description) is True
    update.assert_called_once()
    assert service.change_description("p", "c", "") is True
    assert column.description == ""
    with pytest.raises(ValueError, match="4096"):
        service.change_description("p", "c", "x" * 4097)
    column.is_archive = True
    assert service.change_description("p", "c", "Do not edit archive") is False
    monkeypatch.setattr(InfraHelper, "get_records_with_foreign_by_params", lambda *_: None)
    assert service.change_description("different-project", "c", "No") is False
    assert update.call_count == 2


def test_workflow_edit_fences_readiness_and_publishes_after_commit(monkeypatch):
    from contextlib import contextmanager
    from importlib import import_module

    module = import_module(ProjectColumnService.__module__)
    column = SimpleNamespace(id=2, project_id=1, workflow_stage="active", is_archive=False)
    project = SimpleNamespace(id=1)
    events = []
    execution = SimpleNamespace(
        db=SimpleNamespace(exec=Mock(return_value=SimpleNamespace(first=lambda: column))),
        before={3: False, 4: False},
        watch_project=lambda project_id: events.append(("watch", project_id)),
    )

    @contextmanager
    def uow():
        yield execution
        events.append("commit")

    monkeypatch.setattr(module, "execution_readiness_uow", uow)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *_: (project, column))
    monkeypatch.setattr(module.ProjectColumnPublisher, "workflow_stage_changed", lambda *_: events.append("column"))
    service = ProjectColumnService(
        lambda _: None, lambda _: None,
        SimpleNamespace(project_column=SimpleNamespace(update=lambda item: events.append(("update", item.workflow_stage)))),
    )
    monkeypatch.setattr(service, "_get_service", lambda _: SimpleNamespace(
        publish_work_states=lambda actual_project, ids: events.append(("states", actual_project.id, ids))
    ))
    assert service.change_workflow_stage("p", "c", "closed") is True
    assert events == [("watch", 1), ("update", "closed"), "commit", "column", ("states", 1, [3, 4])]
    events.clear()
    assert service.change_workflow_stage("p", "c", "closed") is True
    assert events == ["commit"]
    column.project_id = 9
    events.clear()
    assert service.change_workflow_stage("p", "c", "active") is False
    assert events == []
