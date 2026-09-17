"""Only a successfully committed dock replacement reaches realtime publication."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from .ProjectColumnService import ProjectColumnService


@pytest.mark.parametrize("outcome", [None, {"column_uids": [], "revision": 2}, "failure"])
def test_delete_publishes_only_committed_dock_snapshot(monkeypatch: pytest.MonkeyPatch, outcome):
    module = import_module(ProjectColumnService.__module__)
    project = SimpleNamespace(id=1)
    column = SimpleNamespace(id=2, is_archive=False)
    archive = SimpleNamespace(id=3)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *args: (project, column))
    for helper, method in [
        (module.BotScopeHelper, "delete_by_scope"),
        (module.BotScheduleHelper, "unschedule_by_scope"),
    ]:
        monkeypatch.setattr(helper, method, Mock())
    monkeypatch.setattr(module.ProjectColumnActivityTask, "project_column_deleted", Mock())
    monkeypatch.setattr(module.ProjectColumnBotTask, "project_column_deleted", Mock())
    events = []
    monkeypatch.setattr(module.ProjectColumnPublisher, "deleted", lambda *args: events.append("deleted"))
    monkeypatch.setattr(
        module.ProjectColumnPublisher, "dock_changed", lambda owner, snapshot: events.append((owner, snapshot))
    )
    command = (
        Mock(side_effect=RuntimeError("test-only delete failure"))
        if outcome == "failure"
        else Mock(return_value=outcome)
    )
    service = SimpleNamespace(
        repo=SimpleNamespace(
            project_column=SimpleNamespace(
                get_or_create_archive_if_not_exists=Mock(return_value=archive),
                count_cards=Mock(return_value=0),
                delete_with_dock_snapshot=command,
            ),
            card=SimpleNamespace(move_all_by_column=Mock()),
        ),
        _get_service=lambda *args: SimpleNamespace(cancel_pending_by_scope=Mock()),
    )
    column.get_uid = lambda: "column-a"
    if outcome == "failure":
        with pytest.raises(RuntimeError, match="test-only delete failure"):
            ProjectColumnService.delete(service, object(), project, column)
    else:
        assert ProjectColumnService.delete(service, object(), project, column) == (outcome is not None)
    command.assert_called_once_with(project, column)
    assert events == (["deleted", (project, outcome)] if isinstance(outcome, dict) else [])


def test_read_snapshot_does_not_publish_or_replace(monkeypatch: pytest.MonkeyPatch):
    module = import_module(ProjectColumnService.__module__)
    publish = Mock()
    monkeypatch.setattr(module.ProjectColumnPublisher, "dock_changed", publish)
    result = {"column_uids": [], "revision": 2}
    read = Mock(return_value=result)
    replace = Mock()
    service = SimpleNamespace(
        repo=SimpleNamespace(project_column=SimpleNamespace(get_dock_snapshot=read, replace_dock_columns=replace))
    )
    assert ProjectColumnService.get_dock_snapshot(service, "project-a") == result
    read.assert_called_once_with("project-a")
    replace.assert_not_called()
    publish.assert_not_called()


@pytest.mark.parametrize("result", [None, {"column_uids": ["column-a"], "revision": 1}])
def test_publish_committed_configuration_only(monkeypatch: pytest.MonkeyPatch, result):
    module = import_module(ProjectColumnService.__module__)
    project = SimpleNamespace(id=1)
    monkeypatch.setattr(module.InfraHelper, "get_by_id_like", lambda *args: project)
    publish = Mock()
    monkeypatch.setattr(module.ProjectColumnPublisher, "dock_changed", publish)
    command = Mock(return_value=result)
    service = SimpleNamespace(repo=SimpleNamespace(project_column=SimpleNamespace(replace_dock_columns=command)))
    assert ProjectColumnService.replace_dock_columns(service, project, ["column-a"], 0) == result
    command.assert_called_once_with(project, ["column-a"], 0)
    if result is None:
        publish.assert_not_called()
    else:
        publish.assert_called_once_with(project, result)


def test_commit_failure_publishes_no_configuration(monkeypatch: pytest.MonkeyPatch):
    module = import_module(ProjectColumnService.__module__)
    project = SimpleNamespace(id=1)
    monkeypatch.setattr(module.InfraHelper, "get_by_id_like", lambda *args: project)
    publish = Mock()
    monkeypatch.setattr(module.ProjectColumnPublisher, "dock_changed", publish)
    service = SimpleNamespace(
        repo=SimpleNamespace(
            project_column=SimpleNamespace(
                replace_dock_columns=Mock(side_effect=RuntimeError("test-only failed commit"))
            )
        )
    )
    with pytest.raises(RuntimeError, match="test-only failed commit"):
        ProjectColumnService.replace_dock_columns(service, project, [], 0)
    publish.assert_not_called()
