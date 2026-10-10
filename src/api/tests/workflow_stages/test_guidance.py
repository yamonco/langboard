"""Registry and column guidance preserve both sources without guessing names."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.card_workspace.application.queries import get_card_bundle
from langboard.card_workspace.domain import CommentPage, SectionPage
from langboard_shared.domain.services.factory.ProjectColumnService import ProjectColumnService
from langboard_shared.infrastructure.repositories.factory.WorkflowStageRepository import WorkflowStageRepository
from test_registry import form


pytest_plugins = ["test_registry"]


@pytest.mark.parametrize("active", [True, False])
def test_guidance_resolves_one_batch_preserves_sources_and_inactive_bindings(registry, active):
    registry_service, _ = registry
    stage = registry_service.save(form())
    if not active:
        registry_service.deactivate(stage.get_uid())
    repo = WorkflowStageRepository(None, None)
    original = repo.get_by_keys
    repo.get_by_keys = Mock(wraps=original)
    service = ProjectColumnService(None, None, SimpleNamespace(workflow_stage=repo))
    columns = [
        SimpleNamespace(id=1, workflow_stage="released", description="Client signs receipt"),
        SimpleNamespace(id=2, workflow_stage="released", description=""),
        SimpleNamespace(id=3, workflow_stage=None, description="Legacy guidance", name="Closed"),
        SimpleNamespace(id=4, workflow_stage="unknown", description="Custom guidance"),
    ]
    result = service.get_workflow_guidance(columns)
    repo.get_by_keys.assert_called_once_with({"released", "unknown"})
    assert result[1] == {
        "workflow_counts_as_completed": False,
        "workflow_stage_description": "Accepted delivery",
        "column_description": "Client signs receipt",
        "workflow_guidance": "Workflow stage:\nAccepted delivery\n\nColumn:\nClient signs receipt",
        "workflow_stage_status": "active" if active else "inactive",
    }
    assert result[2]["workflow_guidance"] == "Workflow stage:\nAccepted delivery"
    assert result[3]["workflow_stage_status"] == "unclassified"
    assert result[3]["workflow_counts_as_completed"] is None
    assert result[3]["workflow_stage_description"] == ""
    assert result[4]["workflow_stage_status"] == "missing"
    assert result[4]["workflow_counts_as_completed"] is None
    assert result[4]["workflow_guidance"] == "Column:\nCustom guidance"


def test_empty_registry_keys_do_not_query(registry, monkeypatch):
    from langboard_shared.core.db import DbSession

    monkeypatch.setattr(DbSession, "use", lambda **_: pytest.fail("Unexpected database query"))
    assert WorkflowStageRepository(None, None).get_by_keys(set()) == {}


def test_mcp_bundle_preserves_full_guidance_but_stays_bounded():
    from langboard.card_workspace.application.ports import CardBundleSource

    text = "s" * 4000
    column_text = "c" * 4096
    guidance = f"Workflow stage:\n{text}\n\nColumn:\n{column_text}"
    details = {
        "uid": "c",
        "workflow_stage_description": text,
        "column_description": column_text,
        "workflow_guidance": guidance,
        "workflow_stage_status": "inactive",
        "internal_policy": "must not leak",
    }
    source = CardBundleSource(
        details=details, checklists=[], attachments=[], metadata={}, bot_scopes=[], bot_schedules=[]
    )
    port = SimpleNamespace(get_card_bundle_source=lambda *_: source)
    result = get_card_bundle(port, "p", "c", CommentPage(), SectionPage()).card.workflow
    assert result["workflow_guidance"] == guidance
    assert result["workflow_stage_description"] == text
    assert result["column_description"] == column_text
    assert "internal_policy" not in result
    details["workflow_guidance"] = "x" * 9000
    result = get_card_bundle(port, "p", "c", CommentPage(), SectionPage()).card.workflow
    assert len(result["workflow_guidance"]) == 8192
    assert result["workflow_guidance_total_chars"] == 9000
    assert result["workflow_guidance_truncated"] is True


def test_native_bundle_and_project_columns_share_registry_guidance(registry, monkeypatch):
    from langboard.card_workspace.infrastructure.native import NativeCardWorkspaceAdapter

    registry_service, _ = registry
    registry_service.save(form())
    column = SimpleNamespace(
        id=3,
        project_id=1,
        workflow_stage="released",
        description="Keep receipt",
        name="Release",
        deleted_at=None,
        api_response=lambda: {"uid": "col", "description": "Keep receipt", "workflow_stage": "released"},
    )
    repository = SimpleNamespace(
        workflow_stage=WorkflowStageRepository(None, None),
        project_column=SimpleNamespace(
            get_all_by_project=lambda _: [(column, 4)],
            get_work_counts=lambda _: {3: {"open_count": 4, "incomplete_count": 2}},
        ),
    )
    column_service = ProjectColumnService(None, None, repository)
    monkeypatch.setattr(column_service, "get_by_id_like", lambda _: column)
    columns = column_service.get_api_list_by_project("p")
    assert columns[0]["count"] == 4 and columns[0]["incomplete_count"] == 2
    card = SimpleNamespace(id=2, project_column_id=3, api_response=lambda: {"uid": "c", "title": "Work"})
    service = SimpleNamespace(
        project_column=column_service,
        card=SimpleNamespace(can_delete=lambda *_: False, get_work_states=lambda _: {2: {}}),
    )
    adapter = NativeCardWorkspaceAdapter(object(), service)
    monkeypatch.setattr(adapter, "_ensure_project_card", lambda *_: (SimpleNamespace(id=1), card))
    monkeypatch.setattr(adapter, "_card_creator", lambda _: None)
    workflow = get_card_bundle(adapter, "p", "c", CommentPage(), SectionPage()).card.workflow
    for key in ["workflow_stage_description", "column_description", "workflow_guidance", "workflow_stage_status"]:
        assert workflow[key] == columns[0][key]
    column.project_id = 99
    monkeypatch.setattr(
        column_service, "get_workflow_guidance", lambda _: pytest.fail("Foreign column guidance leaked")
    )
    assert adapter.get_card_bundle_source("p", "c", frozenset()) is None
