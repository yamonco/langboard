"""MCP people must recover native timer state without changing card ownership."""

import os
from types import SimpleNamespace
from unittest.mock import Mock


os.environ.setdefault("PROJECT_NAME", "langboard")

from ..application.queries import get_card_bundle  # noqa: E402
from ..domain import CardBundleInclude, CommentPage, SectionPage  # noqa: E402
from .native import NativeCardWorkspaceAdapter  # noqa: E402


def test_people_bundle_uses_native_workers_and_core_read_does_not_overfetch(monkeypatch) -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(
        id=2, project_column_id=3,
        api_response=lambda: {"uid": "card", "title": "Work", "description": {"content": ""}},
    )
    workers = Mock(return_value={2: [{"user_uid": "worker", "status": "started", "checkitems": [{"uid": "item"}]}]})
    service = SimpleNamespace(
        card=SimpleNamespace(
            can_delete=lambda *_: False,
            get_api_assigned_user_list=lambda *_args, **_kwargs: [{"uid": "owner"}],
            get_active_workers=workers,
            get_work_states=lambda _: {2: {"workflow_stage": None, "blocker_state": None}},
        ),
        project_column=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(project_id=1, name="Doing")),
    )
    adapter = NativeCardWorkspaceAdapter(SimpleNamespace(), service)
    monkeypatch.setattr(adapter, "_ensure_project_card", lambda *_: (project, card))
    monkeypatch.setattr(adapter, "_card_creator", lambda _: None)
    core = get_card_bundle(adapter, "project", "card", CommentPage(), SectionPage())
    assert core.card.people is None
    assert core.card.work_state == {"workflow_stage": None, "blocker_state": None}
    workers.assert_not_called()

    result = get_card_bundle(adapter, "project", "card", CommentPage(), SectionPage(), [CardBundleInclude.People])
    assert result.card.people.items == [{"uid": "owner"}]
    assert result.card.people.active_workers[0]["user_uid"] == "worker"
    workers.assert_called_once_with(project, card)
