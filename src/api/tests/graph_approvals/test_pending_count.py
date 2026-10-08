"""Exercise production count SQL, including requests beyond the list page limit."""

import os
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import DbSession  # noqa: E402
from langboard_shared.core.types import SafeDateTime  # noqa: E402
from langboard_shared.domain.models import (  # noqa: E402
    BotScheduleGraphApprovalRequest,
    BotTriggerGraphApprovalRequest,
    Card,
    ChatGraphApprovalRequest,
    EditorGraphApprovalRequest,
    GraphApprovalRequest,
    ManualScopeRunGraphApprovalRequest,
    Project,
    ProjectColumn,
    ProjectWiki,
)
from langboard_shared.domain.services.factory.GraphApprovalRequestService import (
    GraphApprovalRequestService,  # noqa: E402
)
from langboard_shared.infrastructure.repositories.factory.GraphApprovalRequestRepository import (
    GraphApprovalRequestRepository,  # noqa: E402
)
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine  # noqa: E402


def test_count_preserves_board_scope_and_counts_beyond_list_limit(monkeypatch):
    details = [
        BotTriggerGraphApprovalRequest,
        BotScheduleGraphApprovalRequest,
        ManualScopeRunGraphApprovalRequest,
        ChatGraphApprovalRequest,
        EditorGraphApprovalRequest,
    ]
    engine = create_engine("sqlite://")
    metadata = MetaData()
    approvals = Table(
        GraphApprovalRequest.__tablename__,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("status", String),
        Column("expires_at", DateTime(timezone=True)),
    )
    detail_tables = {
        model: Table(
            model.__tablename__,
            metadata,
            Column("approval_request_id", Integer),
            Column("scope_table", String),
            Column("scope_id", Integer),
        )
        for model in details
    }
    scopes = {
        model: Table(model.__tablename__, metadata, Column("id", Integer), Column("project_id", Integer))
        for model in [Card, ProjectColumn, ProjectWiki]
    }
    metadata.create_all(engine)
    with engine.begin() as connection:
        for table in scopes.values():
            connection.execute(table.insert(), {"id": 10, "project_id": 1})
        rows = [(BotTriggerGraphApprovalRequest, Project.__tablename__, 1, "pending")] * 120
        rows += [(model, Project.__tablename__, 1, "pending") for model in details[1:]]
        rows += [(BotTriggerGraphApprovalRequest, model.__tablename__, 10, "pending") for model in scopes]
        rows += [
            (BotTriggerGraphApprovalRequest, Project.__tablename__, 2, "pending"),
            (BotTriggerGraphApprovalRequest, Project.__tablename__, 1, "approved"),
        ]
        for uid, (model, scope, scope_id, status) in enumerate(rows, 1):
            connection.execute(approvals.insert(), {"id": uid, "status": status})
            connection.execute(
                detail_tables[model].insert(), {"approval_request_id": uid, "scope_table": scope, "scope_id": scope_id}
            )
        now = SafeDateTime.now()
        for uid, expires_at in enumerate([now - timedelta(seconds=1), now, now + timedelta(seconds=1)], len(rows) + 1):
            connection.execute(approvals.insert(), {"id": uid, "status": "pending", "expires_at": expires_at})
            connection.execute(
                detail_tables[BotTriggerGraphApprovalRequest].insert(),
                {"approval_request_id": uid, "scope_table": Project.__tablename__, "scope_id": 1},
            )
        monkeypatch.setattr(SafeDateTime, "now", classmethod(lambda cls, tz=None: now))

        @contextmanager
        def use(*, readonly):
            assert readonly
            yield SimpleNamespace(exec=lambda statement: connection.execute(statement).scalars())

        monkeypatch.setattr(DbSession, "use", use)
        monkeypatch.setattr(
            GraphApprovalRequestRepository,
            "_GraphApprovalRequestRepository__get_model_classes",
            staticmethod(lambda: details),
        )
        repository = GraphApprovalRequestRepository(lambda _: None, lambda _: None)
        assert repository.count_pending_by_project(1, board_scope_only=True) == 123
        assert repository.count_pending_by_project(1) == 128
        assert repository.count_pending_by_project(2, board_scope_only=True) == 1
        assert repository.count_pending_by_project(99, board_scope_only=True) == 0


def test_count_never_resumes_or_expires_unrelated_graphs():
    repository = SimpleNamespace(graph_approval_request=Mock())
    repository.graph_approval_request.count_pending_by_project.return_value = 3
    service = GraphApprovalRequestService(None, None, repository)
    service.expire_pending = Mock(side_effect=AssertionError("Count must remain read-only"))
    assert service.count_pending_by_project(1, board_scope_only=True) == 3
    repository.graph_approval_request.count_pending_by_project.assert_called_once_with(1, board_scope_only=True)
