from datetime import timedelta
from sqlalchemy import create_engine, event, select
from ...core.db import DbSession
from ...core.db.DbEngine import DbEngine
from ...core.types import SafeDateTime
from ...helpers import ModelHelper
from ..models import Card, EditorGraphApprovalRequest, GraphApprovalRequest
from ..models.bases import BaseGraphApprovalRequestModel
from ..models.GraphApprovalRequest import GraphApprovalRequestType, GraphApprovalStatus
from .CardApprovalGate import pending_card_approvals


def test_current_card_scope_counts_without_exposing_payload_or_mutating_expiry(monkeypatch):
    engine = create_engine("sqlite://")
    details = ModelHelper.get_models_by_base_class(BaseGraphApprovalRequestModel)
    for model in [Card, GraphApprovalRequest, *details]:
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)

    def refuse_replica():
        raise AssertionError("Pending approvals must read the primary")

    monkeypatch.setattr(DbEngine, "get_readonly_engine", refuse_replica)
    with DbSession.use(readonly=False) as db:
        card = Card(project_id=1, project_column_id=1, title="Visible")
        foreign = Card(project_id=2, project_column_id=2, title="Unrequested")
        deleted = Card(project_id=1, project_column_id=1, title="Deleted", deleted_at=SafeDateTime.now())
        for item in [card, foreign, deleted]:
            db.insert(item)

        def insert(scope_id, **changes):
            scope_table = changes.pop("scope_table", "card")
            approval = GraphApprovalRequest(
                thread_id="fixture",
                request_type=changes.pop("request_type", GraphApprovalRequestType.Editor),
                **changes,
            )
            db.insert(approval)
            detail = EditorGraphApprovalRequest(
                approval_request_id=approval.id,
                scope_id=scope_id,
                scope_table=scope_table,
                document_name="Private payload",
            )
            db.insert(detail)
            return approval

        pending = insert(card.id)
        insert(card.id, expires_at=SafeDateTime.now() + timedelta(days=1))
        expired = insert(card.id, expires_at=SafeDateTime.now() - timedelta(days=1))
        insert(card.id, status=GraphApprovalStatus.Approved)
        insert(card.id, scope_table="project")
        insert(card.id, request_type=GraphApprovalRequestType.Chat)
        insert(foreign.id)
        insert(deleted.id)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    assert pending_card_approvals([int(card.id), int(deleted.id)]) == {int(card.id): 2}
    assert len(statements) == 1
    assert all("request_payload" not in sql and "preview_payload" not in sql for sql in statements)
    with DbSession.use(readonly=False) as db:
        pending.status = GraphApprovalStatus.Resolved
        db.update(pending)
    assert pending_card_approvals([int(card.id)]) == {int(card.id): 1}
    before = len(statements)
    assert pending_card_approvals([]) == {}
    assert len(statements) == before
    with DbSession.use(readonly=False) as db:
        persisted = db.exec(select(GraphApprovalRequest).where(GraphApprovalRequest.id == expired.id)).first()
    assert persisted[0].status == GraphApprovalStatus.Pending
