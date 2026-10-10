# ruff: noqa: F811
"""Owner-app metadata cannot authorize bots to mutate exclusive cards."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.card_workspace.application import execution_receipts as receipts
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import ApiException
from langboard_shared.domain.models import (
    Bot,
    CardAppOwnership,
    CardAppOwnershipAudit,
    GraphApprovalRequest,
    InternalBot,
    ManualScopeRunGraphApprovalRequest,
)
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.CardAppGovernance import set_card_app_ownership
from langboard_shared.domain.services.CardAppMutation import guard_card_app_mutation
from langboard_shared.domain.services.factory.CardAttachmentService import CardAttachmentService
from langboard_shared.domain.services.factory.CardCommentService import CardCommentService
from langboard_shared.domain.services.factory.CardRelationshipService import CardRelationshipService
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.domain.services.factory.CheckitemService import CheckitemService
from langboard_shared.domain.services.factory.ChecklistService import ChecklistService
from langboard_shared.domain.services.factory.GraphApprovalRequestService import GraphApprovalRequestService
from langboard_shared.domain.services.factory.OrchestrationTaskService import OrchestrationTaskService
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.infrastructure.repositories.factory.GraphApprovalRequestRepository import (
    GraphApprovalRequestRepository,
)
from test_card_app_ownership import prepare


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("operation", ["card", "stage", "checklist", "checkitem", "comment", "upload", "rename", "delete_file", "file_order", "processing", "embedding"])
def test_native_services_deny_bot_before_mutation(board, operation):
    card = prepare(board)
    set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    actor = Bot(
        name="Automation",
        bot_uname="bot-test",
        app_api_token="test-only",
        platform="default",
        platform_running_type="default",
    )
    # A payload claiming the right app is not an authenticated app connection.
    actor.__dict__["app_key"] = "example-app"
    operations = {
        "card": lambda: CardService(None, None, None).update(actor, board[2], card, {"title": "Changed"}),
        "stage": lambda: CardService(None, None, None).change_order(actor, board[2], card, 0, board[5][1]),
        "checklist": lambda: ChecklistService(None, None, None).create(actor, board[2], card, "Changed"),
        "checkitem": lambda: CheckitemService(None, None, None).create(actor, board[2], card, None, "Changed"),
        "comment": lambda: CardCommentService(None, None, None).create(actor, board[2], card, {}),
        "upload": lambda: CardAttachmentService(None, None, None).create(actor, board[2], card, None),
        "rename": lambda: CardAttachmentService(None, None, None).change_name(actor, board[2], card, None, "Changed"),
        "delete_file": lambda: CardAttachmentService(None, None, None).delete(actor, board[2], card, None),
        "file_order": lambda: CardAttachmentService(None, None, None).change_order(board[2], card, None, 0, user=actor),
        "processing": lambda: CardAttachmentService(None, None, None).request_document_processing(board[2], card, None, user=actor),
        "embedding": lambda: CardAttachmentService(None, None, None).request_document_embedding(board[2], card, None, user=actor),
    }
    with pytest.raises(AppGovernanceDenied):
        operations[operation]()
    assert card.title == "Independent app card" and card.project_column_id == board[5][0].id


@pytest.mark.parametrize("operation", ["change_order", "request_document_processing", "request_document_embedding"])
def test_attachment_writer_requires_actor_before_repository_access(operation):
    service = CardAttachmentService(None, None, None)
    args = ("project", "card", "attachment", 0) if operation == "change_order" else ("project", "card", "attachment")
    with pytest.raises(TypeError, match="user"):
        getattr(service, operation)(*args)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("operation", ["metadata", "verification", "run", "suggestions", "bypass", "child"])
def test_orchestration_denies_bot_before_metadata_or_child_creation(board, operation):
    card = prepare(board)
    set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    actor = Bot(name="Automation", bot_uname="bot-test", app_api_token="test-only",
                platform="default", platform_running_type="default")
    service = OrchestrationTaskService(None, None, None)
    operations = {
        "metadata": lambda: service.save_task_metadata(board[2], card, {"source": "spoof"}, user_or_bot=actor),
        "verification": lambda: service.record_verification(actor, board[2], card, {"passed": True}),
        "run": lambda: service.record_run(board[2], card, {"status": "done"}, user_or_bot=actor),
        "suggestions": lambda: service.record_suggestions(board[2], card, [], user_or_bot=actor),
        "bypass": lambda: service.record_bypass_decision(actor, board[2], card, {"allowed": True}),
        "child": lambda: service.create_child_task_from_suggestion(actor, board[2], card, {"title": "Unauthorized child"}),
    }
    with pytest.raises(AppGovernanceDenied):
        operations[operation]()
    with DbSession.atomic() as db:
        from langboard_shared.domain.models import Card

        assert len(db.exec(SqlBuilder.select.table(Card)).all()) == 1


@pytest.mark.parametrize("operation", ["save_task_metadata", "record_run", "record_suggestions"])
def test_orchestration_metadata_requires_actor(operation):
    with pytest.raises(TypeError, match="user_or_bot"):
        getattr(OrchestrationTaskService(None, None, None), operation)("project", "card", {})


def test_orchestration_routes_pass_authenticated_actor():
    from langboard.routes.board import BoardOrchestrationApi as routes
    from langboard_shared.domain.models import User

    actor = User.model_construct(id=1)
    run = Mock(return_value={"run": "saved"})
    suggestions = Mock(return_value={"suggestions": "saved"})
    service = SimpleNamespace(orchestration_task=SimpleNamespace(record_run=run, record_suggestions=suggestions))
    form = SimpleNamespace(model_dump=lambda **_: {"status": "running"})
    routes.record_orchestration_run("project", "card", form, actor, service)
    run.assert_called_once_with("project", "card", {"status": "running"}, user_or_bot=actor)
    routes.record_orchestration_suggestions("project", "card", SimpleNamespace(suggestions=[form]), actor, service)
    suggestions.assert_called_once_with("project", "card", [{"status": "running"}], user_or_bot=actor)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_owned_card_human_orchestration_metadata_retains_native_write(board, monkeypatch):
    from importlib import import_module

    module = import_module("langboard_shared.domain.services.factory.OrchestrationTaskService")
    card = prepare(board)
    set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    service = OrchestrationTaskService(None, None, None)
    metadata = Mock()
    monkeypatch.setattr(service, "_get_service", lambda _: metadata)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *_: (board[2], card))
    published = Mock()
    monkeypatch.setattr(module.MetadataPublisher, "updated_metadata", published)
    assert service.save_task_metadata(board[2], card, {"source": "human"}, user_or_bot=board[1])
    assert service.record_run(board[2], card, {"status": "running"}, user_or_bot=board[1])
    assert service.record_suggestions(board[2], card, [{"title": "Next"}], user_or_bot=board[1])
    assert metadata.save.call_count == 3
    assert published.call_count == 3


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("mode", ["anchor", "add", "remove", "patch_add", "patch_remove", "preview_remove"])
def test_relationship_fence_covers_owned_endpoints_before_graph_writes(board, monkeypatch, mode):
    from langboard_shared.domain.models import Card

    owned = prepare(board)
    set_card_app_ownership(board[1], board[2].id, owned.id, "example-app", None)
    with DbSession.atomic() as db:
        anchor = Card(project_id=board[2].id, project_column_id=board[5][0].id, title="Unowned anchor")
        db.insert(anchor)
    actor = Bot(name="Automation", bot_uname="bot-test", app_api_token="test-only",
                platform="default", platform_running_type="default")
    actor.__dict__["app_key"] = "example-app"
    service = CardRelationshipService(None, None, None)
    relationship_id = owned.id + 1
    type_id = owned.id + 2
    old = SimpleNamespace(id=relationship_id, relationship_type_id=type_id)
    repo = Mock()
    repo.get_all_by_card_and_relation.return_value = [(old, object(), owned)] if mode == "remove" else []
    repo.get_all_related_card_ids.return_value = [owned.id] if mode == "add" else []
    repo.get_graph_snapshot.return_value = [(relationship_id, anchor.id, owned.id, type_id)]
    monkeypatch.setattr(service, "repo", SimpleNamespace(card_relationship=repo), raising=False)
    def call():
        if mode == "anchor":
            return service.update(actor, board[2], owned, False, [])
        if mode in {"add", "remove"}:
            pairs = [(owned.get_uid(), type(owned.id)(type_id).to_short_code())] if mode == "add" else []
            return service.update(actor, board[2], anchor, False, pairs)
        edges = [(anchor.get_uid(), owned.get_uid(), type(owned.id)(type_id).to_short_code())] if mode == "patch_add" else []
        remove = [] if edges else [type(owned.id)(relationship_id).to_short_code()]
        command = service.preview_graph_patch if mode == "preview_remove" else service.apply_graph_patch
        return command(actor, board[2], anchor, [], edges, remove)
    with pytest.raises(AppGovernanceDenied):
        call()
    repo.insert.assert_not_called()
    repo.delete.assert_not_called()
    repo.apply_graph_patch.assert_not_called()
    with DbSession.atomic() as db:
        assert len(db.exec(SqlBuilder.select.table(Card)).all()) == 2


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("actor_kind", ["bot", "internal_bot", "bot_and_user", "missing"])
def test_card_approval_creation_denies_unbound_automation_before_side_effects(board, monkeypatch, actor_kind):
    card = prepare(board)
    set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    service = GraphApprovalRequestService(None, None, None)
    repository = SimpleNamespace(graph_approval_request=Mock())
    monkeypatch.setattr(service, "repo", repository, raising=False)
    cancel = Mock()
    monkeypatch.setattr(service, "_GraphApprovalRequestService__cancel_unpersisted", cancel)
    args = {}
    if actor_kind in {"bot", "bot_and_user"}:
        args["bot"] = Bot(name="Automation", bot_uname="bot-test", app_api_token="test-only",
                          platform="default", platform_running_type="default")
    elif actor_kind == "internal_bot":
        args["internal_bot"] = InternalBot(bot_type="project_chat", display_name="Assistant",
                                          platform="default", platform_running_type="default")
    if actor_kind == "bot_and_user":
        args["user"] = board[1]
    with pytest.raises(AppGovernanceDenied):
        service.create_from_interrupt(board[2], {
            "type": "approval_request", "origin_type": "manual_scope_run", "scope_table": "card",
            "scope_uid": card.get_uid(), "thread_id": "test-thread", "app_key": "example-app",
        }, **args)
    repository.graph_approval_request.insert_with_detail.assert_not_called()
    cancel.assert_not_called()


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("human", [False, True])
def test_card_approval_human_and_released_bot_retain_native_creation(board, monkeypatch, human):
    card = prepare(board)
    set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    if not human:
        set_card_app_ownership(board[1], board[2].id, card.id, None, 1)
    service = GraphApprovalRequestService(None, None, None)
    repository = SimpleNamespace(card=SimpleNamespace(get_by_id_like=lambda _: card), graph_approval_request=Mock())
    monkeypatch.setattr(service, "repo", repository, raising=False)
    detail = object()
    monkeypatch.setattr(service, "_GraphApprovalRequestService__create_detail", lambda *a, **k: detail)
    actor = {"user": board[1]} if human else {"bot": Bot(name="Automation", bot_uname="bot-test",
             app_api_token="test-only", platform="default", platform_running_type="default")}
    approval = service.create_from_interrupt(board[2], {
        "type": "approval_request", "origin_type": "manual_scope_run", "scope_table": "card",
        "scope_uid": card.get_uid(), "thread_id": "test-thread",
    }, **actor)
    assert approval is not None and approval.thread_id == "test-thread"
    repository.graph_approval_request.insert_with_detail.assert_called_once_with(approval, detail)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_card_approval_and_detail_share_outer_transaction(board, monkeypatch):
    card = prepare(board)
    for model in (GraphApprovalRequest, ManualScopeRunGraphApprovalRequest):
        model.__table__.create(DbEngine.get_main_engine())
    service = GraphApprovalRequestService(None, None, None)
    repository = SimpleNamespace(card=SimpleNamespace(get_by_id_like=lambda _: card),
                                 graph_approval_request=object.__new__(GraphApprovalRequestRepository))
    monkeypatch.setattr(service, "repo", repository, raising=False)
    interrupt = {"type": "approval_request", "origin_type": "manual_scope_run",
                 "scope_table": "card", "scope_uid": card.get_uid(), "thread_id": "test-thread"}
    with pytest.raises(RuntimeError, match="rollback"):
        with DbSession.atomic() as db:
            service.create_from_interrupt(board[2], interrupt, user=board[1])
            assert len(db.exec(SqlBuilder.select.table(GraphApprovalRequest)).all()) == 1
            assert len(db.exec(SqlBuilder.select.table(ManualScopeRunGraphApprovalRequest)).all()) == 1
            raise RuntimeError("rollback")
    with DbSession.atomic() as db:
        assert db.exec(SqlBuilder.select.table(GraphApprovalRequest)).all() == []
        assert db.exec(SqlBuilder.select.table(ManualScopeRunGraphApprovalRequest)).all() == []
    approval = service.create_from_interrupt(board[2], interrupt, user=board[1])
    with DbSession.atomic() as db:
        saved = db.exec(SqlBuilder.select.table(GraphApprovalRequest)).first()
        detail = db.exec(SqlBuilder.select.table(ManualScopeRunGraphApprovalRequest)).first()
        assert saved.id == approval.id == detail.approval_request_id
        assert detail.scope_id == card.id and detail.scope_table == "card"


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("assign_after_lock", [False, True])
def test_receipt_owner_fence_precedes_persistence_and_review(board, monkeypatch, assign_after_lock):
    card = prepare(board)
    actor = Bot(name="Automation", bot_uname="bot-test", app_api_token="test-only",
                platform="default", platform_running_type="default")
    actor.__dict__["app_key"] = "example-app"
    if not assign_after_lock:
        set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    # Isolate the write fence even when a caller has already passed read authority.
    readable = Mock(return_value=(board[2], card))
    monkeypatch.setattr(receipts, "require_receipt_card", readable)
    generation = Mock()
    checklist = Mock()
    review = Mock()
    monkeypatch.setattr(receipts, "current_execution", generation)
    monkeypatch.setattr(receipts, "_reconcile_machine_checklist", checklist)
    monkeypatch.setattr(receipts, "_move_to_review", review)

    def watch(ids):
        assert ids == [card.id]
        if assign_after_lock:
            set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)

    @contextmanager
    def execution():
        with DbSession.atomic() as db:
            yield SimpleNamespace(db=db, watch=watch)

    monkeypatch.setattr(receipts, "execution_readiness_uow", execution)
    form = receipts.PutExecutionReceiptForm(status="review_ready", summary="Evidence",
                                           occurred_at=datetime.now(timezone.utc))
    with pytest.raises(ApiException.Forbidden_403):
        receipts.store_execution_receipt(board[2].get_uid(), card.get_uid(), 1, form,
            f"langboard:{board[2].get_uid()}:{card.get_uid()}:1:receipt", actor)
    assert readable.call_count == (2 if assign_after_lock else 1)
    generation.assert_not_called()
    checklist.assert_not_called()
    review.assert_not_called()


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_release_and_human_permission_paths_do_not_infer_app_grants(board):
    card = prepare(board)
    actor = Bot(
        name="Automation",
        bot_uname="bot-test",
        app_api_token="test-only",
        platform="default",
        platform_running_type="default",
    )
    calls = []

    @guard_card_app_mutation
    def mutation(user_or_bot, project, card):
        calls.append(user_or_bot)
        return "existing permission path"

    assert mutation(actor, board[2], card) == "existing permission path"
    set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    # User calls still reach the native operation's own permissions.
    assert mutation(board[1], board[2], card) == "existing permission path"
    with pytest.raises(AppGovernanceDenied):
        mutation(SimpleNamespace(app_key="example-app"), board[2], card)
    with pytest.raises(AppGovernanceDenied):
        mutation(actor, board[2], card)
    set_card_app_ownership(board[1], board[2].id, card.id, None, 1)
    assert mutation(actor, board[2], card) == "existing permission path"
    with DbSession.atomic() as db:
        assert len(db.exec(SqlBuilder.select.table(CardAppOwnershipAudit)).all()) == 2
        assert db.exec(SqlBuilder.select.table(CardAppOwnership)).first().app_key is None
