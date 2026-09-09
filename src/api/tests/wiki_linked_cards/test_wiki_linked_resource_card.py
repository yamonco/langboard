import importlib
import os
from types import SimpleNamespace
from unittest.mock import ANY, Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import Card  # noqa: E402
from langboard_shared.domain.services.factory.BotService import BotService, BotServiceError  # noqa: E402
from langboard_shared.domain.services.factory.CardAttachmentService import CardAttachmentService  # noqa: E402
from langboard_shared.domain.services.factory.CardCommentService import CardCommentService  # noqa: E402
from langboard_shared.domain.services.factory.CardRelationshipService import CardRelationshipService  # noqa: E402
from langboard_shared.domain.services.factory.CardService import CardService  # noqa: E402
from langboard_shared.domain.services.factory.ChecklistService import ChecklistService  # noqa: E402
from langboard_shared.domain.services.factory.MetadataService import MetadataService  # noqa: E402
from langboard_shared.domain.services.factory.OrchestrationTaskService import OrchestrationTaskService  # noqa: E402


class FakeUser:
    def __init__(self, user_id: int, *, is_admin: bool = False):
        self.id = user_id
        self.is_admin = is_admin


def linked_card(uid: str, source_uid: str) -> SimpleNamespace:
    return SimpleNamespace(
        source_type=Card.LINKED_RESOURCE_PROJECT_WIKI,
        source_uid=source_uid,
        get_uid=lambda: uid,
    )


def test_card_schema_enforces_atomic_and_unique_source_identity() -> None:
    constraints = {constraint.name for constraint in Card.__table__.constraints}
    column_names = {column.name for column in Card.__table__.columns}

    assert {"source_type", "source_uid"}.issubset(column_names)
    assert "ck_card_`linked_source_complete`" in constraints
    assert "uq_card_linked_resource" in constraints


def test_batch_preview_never_exposes_forbidden_wiki_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    monkeypatch.setattr(module, "User", FakeUser)

    public = SimpleNamespace(
        id=10,
        is_public=True,
        title="Public",
        content=SimpleNamespace(content="public body"),
        get_uid=lambda: "w-public",
    )
    private = SimpleNamespace(
        id=11,
        is_public=False,
        title="Secret",
        content=SimpleNamespace(content="secret body"),
        get_uid=lambda: "w-private",
    )
    wiki_query = Mock(return_value=[public, private])
    assignment_query = Mock(return_value=set())
    service = SimpleNamespace(
        LINKED_RESOURCE_PREVIEW_MAX_LENGTH=240,
        repo=SimpleNamespace(
            project_wiki=SimpleNamespace(get_by_project_and_uids=wiki_query),
            project_wiki_assigned_user=SimpleNamespace(get_assigned_wiki_ids=assignment_query),
        ),
    )
    cards = [
        linked_card("c-public", "w-public"),
        linked_card("c-private", "w-private"),
        linked_card("c-missing", "w-missing"),
    ]

    payloads = CardService._get_linked_resource_payloads(
        service,
        FakeUser(2),
        SimpleNamespace(owner_id=1),
        cards,
        include_content=True,
    )

    assert payloads["c-public"]["title"] == "Public"
    assert payloads["c-public"]["content"].content == "public body"
    assert payloads["c-private"] == {"type": "project_wiki", "uid": "w-private", "status": "forbidden"}
    assert payloads["c-missing"] == {"type": "project_wiki", "uid": "w-missing", "status": "missing"}
    wiki_query.assert_called_once()
    assignment_query.assert_called_once_with(ANY, {11})


def test_board_projection_reads_headers_without_loading_wiki_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    monkeypatch.setattr(module, "User", FakeUser)
    wiki_id = SnowflakeID(123456)
    source_uid = wiki_id.to_short_code()
    full_body_query = Mock(side_effect=AssertionError("board projection loaded Wiki bodies"))
    header_query = Mock(return_value=[(wiki_id, "Reference", True)])
    service = SimpleNamespace(
        repo=SimpleNamespace(
            project_wiki=SimpleNamespace(
                get_by_project_and_uids=full_body_query,
                get_headers_by_project_and_uids=header_query,
            ),
            project_wiki_assigned_user=SimpleNamespace(get_assigned_wiki_ids=Mock(return_value=set())),
        )
    )

    payloads = CardService._get_linked_resource_payloads(
        service,
        FakeUser(2),
        SimpleNamespace(owner_id=1),
        [linked_card("card-1", source_uid)],
        include_content=False,
    )

    assert payloads["card-1"] == {
        "type": "project_wiki",
        "uid": source_uid,
        "status": "available",
        "title": "Reference",
    }
    header_query.assert_called_once()
    full_body_query.assert_not_called()


def test_archive_and_archive_column_drop_delete_only_the_link(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard_shared.core.exceptions.CardDeleteForbidden import CardDeleteForbidden

    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, project_column_id=10, is_linked_resource=True)
    old_column = SimpleNamespace(id=10, project_id=1, is_archive=False)
    archive_column = SimpleNamespace(id=20, project_id=1, is_archive=True)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *args: (project, card))
    monkeypatch.setattr(
        module.InfraHelper, "get_by_id_like", lambda model, value: old_column if value == 10 else archive_column
    )

    delete_link = Mock(return_value=True)
    can_delete = Mock(return_value=False)
    service = SimpleNamespace(_delete_card=delete_link, can_delete=can_delete)

    with pytest.raises(CardDeleteForbidden, match="original card author or an administrator"):
        CardService.archive(service, object(), project, card)
    with pytest.raises(CardDeleteForbidden, match="original card author or an administrator"):
        CardService.change_order(service, object(), project, card, 0, archive_column)
    delete_link.assert_not_called()

    can_delete.return_value = True

    assert CardService.archive(service, object(), project, card) is True
    assert CardService.change_order(service, object(), project, card, 0, archive_column) is True
    assert delete_link.call_count == 2
    delete_link.assert_called_with(ANY, project, card)


def test_linked_card_deletion_purges_reference_row(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    card = SimpleNamespace(
        id=30,
        project_column_id=20,
        order=4,
        is_linked_resource=True,
        get_uid=lambda: "card-1",
    )
    project = SimpleNamespace()
    card_repo = SimpleNamespace(delete=Mock(), reoder_after_delete=Mock())
    repo = SimpleNamespace(
        checkitem=SimpleNamespace(get_all_started_checkitem_by_card=Mock(return_value=[])),
        card_assigned_user=SimpleNamespace(delete_all_by_card=Mock()),
        card_relationship=SimpleNamespace(delete_all_by_card=Mock()),
        card=card_repo,
    )
    graph_approval = SimpleNamespace(cancel_pending_by_scope=Mock())
    service = SimpleNamespace(
        repo=repo,
        _get_service=lambda service_type: graph_approval,
    )
    monkeypatch.setattr(module.BotScopeHelper, "delete_by_scope", Mock())
    monkeypatch.setattr(module.BotScheduleHelper, "unschedule_by_scope", Mock())
    monkeypatch.setattr(module.CardPublisher, "deleted", Mock())
    activity_deleted = Mock()
    bot_deleted = Mock()
    monkeypatch.setattr(module.CardActivityTask, "card_deleted", activity_deleted)
    monkeypatch.setattr(module.CardBotTask, "card_deleted", bot_deleted)

    assert CardService._delete_card(service, object(), project, card) is True

    card_repo.delete.assert_called_once_with(card, purge=True)
    card_repo.reoder_after_delete.assert_called_once_with(20, 4)
    activity_deleted.assert_not_called()
    bot_deleted.assert_not_called()


def test_regular_column_move_keeps_linked_card_movable(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, project_column_id=10, is_linked_resource=True, order=2, archived_at=None)
    old_column = SimpleNamespace(id=10, project_id=1, is_archive=False)
    destination = SimpleNamespace(id=20, project_id=1, is_archive=False)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *args: (project, card))
    monkeypatch.setattr(
        module.InfraHelper, "get_by_id_like", lambda model, value: old_column if value == 10 else destination
    )
    monkeypatch.setattr(module.CardPublisher, "order_changed", Mock())
    monkeypatch.setattr(module.CardActivityTask, "card_moved", Mock())
    monkeypatch.setattr(module.CardBotTask, "enqueue_card_moved_webhook", Mock())
    monkeypatch.setattr(module.CardBotTask, "card_moved", Mock())
    repo = SimpleNamespace(card=SimpleNamespace(update_row_order=Mock(), update=Mock()))
    service = SimpleNamespace(repo=repo)

    assert CardService.change_order(service, object(), project, card, 0, destination) is True
    assert card.project_column_id == destination.id
    repo.card.update.assert_called_once_with(card)
    module.CardActivityTask.card_moved.assert_not_called()
    module.CardBotTask.enqueue_card_moved_webhook.assert_not_called()
    module.CardBotTask.card_moved.assert_not_called()


def test_existing_wiki_link_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    project = SimpleNamespace(id=1)
    wiki = SimpleNamespace(project_id=1, get_uid=lambda: "wiki-1")
    column = SimpleNamespace(id=10, project_id=1, is_archive=False)
    existing = SimpleNamespace(
        board_api_response=lambda *args: {"uid": "card-1"},
        get_uid=lambda: "card-1",
    )
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *args: (project, wiki))
    repo = SimpleNamespace(
        project_column=SimpleNamespace(get_all_by_project=Mock(return_value=[(column, 0)])),
        card=SimpleNamespace(find_linked_resource=Mock(return_value=existing), insert=Mock()),
    )
    service = SimpleNamespace(
        repo=repo,
        _get_linked_resource_payloads=lambda *args, **kwargs: {
            "card-1": {"type": "project_wiki", "uid": "wiki-1", "status": "available"}
        },
    )

    card, payload, created = CardService.create_linked_wiki_card(service, object(), project, wiki)

    assert card is existing
    assert payload["linked_resource"]["uid"] == "wiki-1"
    assert created is False
    repo.card.insert.assert_not_called()


@pytest.mark.parametrize(
    ("service_class", "method_name", "tail_args"),
    [
        (CardService, "update_assigned_users", [[]]),
        (CardService, "update_labels", [[]]),
        (CardRelationshipService, "update", [True, []]),
        (ChecklistService, "create", ["Checklist"]),
        (CardCommentService, "create", [{"content": "Comment"}]),
        (CardAttachmentService, "create", [SimpleNamespace(original_filename="file.txt")]),
    ],
)
def test_linked_resource_rejects_task_feature_creation(
    monkeypatch: pytest.MonkeyPatch,
    service_class: type,
    method_name: str,
    tail_args: list[object],
) -> None:
    module = importlib.import_module(service_class.__module__)
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, is_linked_resource=True)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *args: (project, card))
    service = SimpleNamespace(repo=Mock())

    result = getattr(service_class, method_name)(service, object(), project, card, *tail_args)

    assert result is None
    assert not service.repo.mock_calls


def test_linked_resource_has_no_card_metadata_surface() -> None:
    card = Card(
        project_id=SnowflakeID(1),
        project_column_id=SnowflakeID(2),
        title="",
        source_type=Card.LINKED_RESOURCE_PROJECT_WIKI,
        source_uid="wiki-1",
    )
    repo = SimpleNamespace(metadata=Mock())
    service = SimpleNamespace(repo=repo)

    assert MetadataService.get_all_as_api(service, object(), card, as_dict=True) == {}
    assert MetadataService.get_by_key_as_api(service, object(), card, "key") is None
    assert MetadataService.save(service, object(), card, "key", "value") is None
    assert MetadataService.delete(service, object(), card, "key") is False
    assert not repo.metadata.mock_calls


def test_linked_resource_cannot_be_used_as_orchestration_task(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("langboard_shared.domain.services.factory.OrchestrationTaskService")
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, is_linked_resource=True)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *args: (project, card))
    service = SimpleNamespace(repo=Mock())

    assert OrchestrationTaskService.record_run(service, project, card, {"status": "done"}) is None
    assert OrchestrationTaskService.record_suggestions(service, project, card, []) is None
    assert not service.repo.mock_calls


def test_linked_resource_cannot_run_bots_or_scheduled_notifications() -> None:
    card = Card(
        project_id=SnowflakeID(1),
        project_column_id=SnowflakeID(2),
        title="",
        source_type=Card.LINKED_RESOURCE_PROJECT_WIKI,
        source_uid="wiki-1",
    )

    with pytest.raises(BotServiceError, match="cannot run Bots"):
        BotService.require_target_project(SimpleNamespace(), card, None)
    assert card.get_notification_schedule_rule_message_vars("created_at", "older_than_days", Mock()) is None
