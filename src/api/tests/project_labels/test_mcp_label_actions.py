import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")
from langboard.mcp_tools import CardMcp, LabelMcp
from langboard_shared.domain.models import GlobalLabel


def service(local=None):
    local = local or []
    created = []

    def create(actor, project, name, color, description):
        label = {"uid": "new", "name": name, "color": color, "description": description}
        local.append(label)
        created.append(label)
        return object(), label

    svc = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda uid: object()),
        project_label=SimpleNamespace(get_api_list_by_project=lambda project, **kwargs: local, create=create),
    )
    return svc, created


def test_local_creation_is_denied_without_explicit_request():
    svc, created = service()
    for flag in (False, None):
        with pytest.raises(ValueError, match="EXPLICIT_USER_REQUEST"):
            LabelMcp.create_local_project_label("p", "New", object(), svc, flag)
    assert not created
    assert LabelMcp.create_local_project_label("p", "New", object(), svc, True)["created"]
    assert len(created) == 1
    assert not LabelMcp.create_local_project_label("p", " new ", object(), svc, True)["created"]
    assert len(created) == 1


def test_global_catalog_is_read_only_and_local_labels_come_first(monkeypatch):
    svc, created = service([{"uid": "local", "name": "Request", "color": "#112233", "description": "Local"}])
    global_label = GlobalLabel(name="Request", color="#445566", description="Global")
    monkeypatch.setattr(LabelMcp.InfraHelper, "get_all", lambda model: [global_label])
    result = LabelMcp.get_project_label_catalog("p", svc, query="request", limit=1)
    assert result["items"][0]["source"] == "local"
    assert result["next_offset"] == 1
    assert LabelMcp.get_project_label_catalog("p", svc, offset=1)["items"][0]["source"] == "global"
    assert not created


def test_global_selection_reuses_local_match_and_never_mutates_global(monkeypatch):
    svc, created = service([{"uid": "local", "name": "Request", "color": "#112233", "description": "Local"}])
    global_label = GlobalLabel(name="Request", color="#445566", description="Global")
    monkeypatch.setattr(LabelMcp.InfraHelper, "get_by_id_like", lambda model, uid: global_label)
    assert LabelMcp.use_global_project_label("p", global_label.get_uid(), object(), svc)["label"]["uid"] == "local"
    assert not created
    svc, created = service()
    assert LabelMcp.use_global_project_label("p", global_label.get_uid(), object(), svc)["created"]
    assert not LabelMcp.use_global_project_label("p", global_label.get_uid(), object(), svc)["created"]
    assert len(created) == 1
    assert global_label.description == "Global"


def test_attach_detach_preserve_unrelated_labels_and_are_idempotent(monkeypatch):
    project, card = object(), object()
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *args: (project, card))
    all_labels = [{"uid": uid, "name": uid} for uid in ["a", "b"]]
    current = [all_labels[0]]
    writes = []

    def update(actor, project, card, uids):
        current[:] = [label for label in all_labels if label["uid"] in uids]
        writes.append(uids)
        return True

    svc = SimpleNamespace(
        project_label=SimpleNamespace(
            get_api_list_by_project=lambda *a, **kw: all_labels, get_api_list_by_card=lambda card: current
        ),
        card=SimpleNamespace(update_labels=update),
    )
    for action in ["attach", "attach", "detach", "detach"]:
        LabelMcp.change_card_label("p", "c", "b", action, object(), svc)
    assert writes == [["a", "b"], ["a"]]
    assert current == [all_labels[0]]


def test_unknown_label_and_invalid_creation_never_write(monkeypatch):
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *args: (object(), object()))
    svc, created = service()
    svc.card = SimpleNamespace(update_labels=lambda *args: pytest.fail("Unexpected card mutation"))
    with pytest.raises(ValueError, match="Unknown local label"):
        LabelMcp.change_card_label("p", "c", "foreign-label", "attach", object(), svc)
    for name, color, description in [(" ", "#112233", ""), ("New", "red", ""), ("New", "#112233", "x" * 4001)]:
        with pytest.raises(ValueError, match="Invalid label fields"):
            LabelMcp.create_local_project_label("p", name, object(), svc, True, color, description)
    assert not created
