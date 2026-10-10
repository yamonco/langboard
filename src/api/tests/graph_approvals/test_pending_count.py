"""Exercise production count SQL, including requests beyond the list page limit."""

import os
from contextlib import contextmanager
from types import SimpleNamespace


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import DbSession  # noqa: E402
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
from langboard_shared.infrastructure.repositories.factory.GraphApprovalRequestRepository import (
    GraphApprovalRequestRepository,  # noqa: E402
)
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine  # noqa: E402


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
        GraphApprovalRequest.__tablename__, metadata, Column("id", Integer, primary_key=True), Column("status", String)
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
        assert repository.count_pending_by_project(1, board_scope_only=True) == 122
        assert repository.count_pending_by_project(1) == 127
        assert repository.count_pending_by_project(2, board_scope_only=True) == 1
        assert repository.count_pending_by_project(99, board_scope_only=True) == 0
