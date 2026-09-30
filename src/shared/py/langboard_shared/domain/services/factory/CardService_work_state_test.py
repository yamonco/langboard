from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
from .CardService import CardService


def test_card_batch_uses_bounded_queries_and_no_actor_or_editable_metadata(monkeypatch):
    column = SimpleNamespace(id=3, project_id=1, workflow_stage="review", is_archive=False)
    db = SimpleNamespace(exec=Mock(return_value=SimpleNamespace(all=lambda: [column])))

    @contextmanager
    def use(**kwargs):
        assert kwargs == {"readonly": True}
        yield db

    monkeypatch.setattr(import_module(CardService.__module__).DbSession, "use", use)
    dependency_query = Mock(return_value={2: []})
    monkeypatch.setattr(import_module(CardService.__module__), "dependency_blockers", dependency_query)
    counts = Mock(return_value={2: (2, 2, 1, 0)})
    verifications = Mock(return_value={})
    service = CardService(
        lambda _: None,
        lambda _: None,
        SimpleNamespace(
            checkitem=SimpleNamespace(get_work_state_counts=counts),
            card_verification=SimpleNamespace(get_latest_by_card_ids=verifications),
        ),
    )
    cards = [
        SimpleNamespace(
            id=2,
            project_id=1,
            project_column_id=3,
            archived_at=None,
            is_linked_resource=False,
            last_change_seq=9,
            get_uid=lambda: "card",
        )
    ]
    result = service.get_work_states(cards)
    db.exec.assert_called_once()
    counts.assert_called_once_with([2])
    dependency_query.assert_called_once_with([2])
    verifications.assert_called_once_with([2])
    assert result[2]["workflow_stage"] == "review"
    assert result[2]["execution_state"] == "human_active"
    assert result[2]["verification_state"] == "partial"
    # Older archive rows may lack archived_at; the owned column remains authoritative.
    column.is_archive = True
    archived = service.get_work_states(cards)[2]
    assert archived["lifecycle"] == "archived"
    assert archived["active_queue_eligible"] is False
    assert any(reason["code"] == "archived_with_running_timer" for reason in archived["state_inconsistency"])
    # A malformed foreign column cannot supply another project's semantic or lifecycle.
    column.project_id = 9
    foreign = service.get_work_states(cards)[2]
    assert foreign["workflow_stage"] is None
    assert foreign["lifecycle"] == "active"


def test_empty_authorized_batch_does_not_query():
    service = CardService(lambda _: None, lambda _: None, Mock())
    assert service.get_work_states([]) == {}
    assert not service.repo.mock_calls


def test_projection_publish_batches_cards_and_preserves_timestamps(monkeypatch):
    module = import_module(CardService.__module__)
    card = SimpleNamespace(id=2, project_id=1)
    db = SimpleNamespace(exec=Mock(return_value=SimpleNamespace(all=lambda: [card])))

    @contextmanager
    def use(**kwargs):
        assert kwargs == {"readonly": False}
        yield db

    monkeypatch.setattr(module.DbSession, "use", use)
    publish = Mock()
    monkeypatch.setattr(module.CardPublisher, "updated", publish)
    service = CardService(lambda _: None, lambda _: None, Mock())
    projection = {"dependency_state": {"state": "blocked", "direct_blockers": []}}
    service.get_work_states = Mock(return_value={2: projection})
    project = SimpleNamespace(id=1)
    service.publish_work_states(project, [2, 2])
    service.get_work_states.assert_called_once_with([card])
    publish.assert_called_once_with(project, card, None, {"work_state": projection})
    assert "updated_at" not in card.__dict__
    service.publish_work_states(project, [])
    assert db.exec.call_count == 1
