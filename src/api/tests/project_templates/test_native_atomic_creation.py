"""Exercise native project repositories together through template commit/rollback."""

import os
from uuid import uuid4
import pytest
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain import models
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.ProjectTemplateService import SI_WORKFLOW_STAGES
from langboard_shared.publishers import ProjectColumnPublisher
from langboard_shared.tasks.activities import ProjectActivityTask, ProjectColumnActivityTask
from langboard_shared.tasks.bots import ProjectColumnBotTask
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("database", ["sqlite", "postgresql"])
@pytest.mark.parametrize("fail_after_policy", [False, True])
def test_native_project_membership_labels_roles_and_policy_share_template_transaction(
    monkeypatch, fail_after_policy, database
):
    admin = None
    schema = None
    if database == "postgresql":
        url = os.getenv("LANGBOARD_TEMPLATE_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Dedicated PostgreSQL template proof URL not set")
        schema = f"template_atomic_{uuid4().hex}"
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine("sqlite://")
    tables = [
        models.User,
        models.Project,
        models.ProjectColumn,
        models.ProjectLabel,
        models.ProjectAssignedUser,
        models.ProjectRole,
        models.InternalBot,
        models.ProjectAssignedInternalBot,
        models.ProjectTemplate,
        models.WorkflowStageDefinition,
        models.ProjectEmailNotificationPolicy,
        models.ProjectEmailNotificationRecipient,
    ]
    required = {model.__table__ for model in tables}
    pending = list(required)
    while pending:
        for foreign_key in pending.pop().foreign_keys:
            parent = foreign_key.column.table
            if parent not in required:
                required.add(parent)
                pending.append(parent)
    models.Project.metadata.create_all(engine, tables=list(required))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    effects = []
    monkeypatch.setattr(ProjectActivityTask, "project_created", lambda *_args: effects.append("project"))
    monkeypatch.setattr(ProjectColumnPublisher, "created", lambda *_args: effects.append("column"))
    monkeypatch.setattr(ProjectColumnActivityTask, "project_column_created", lambda *_args: None)
    monkeypatch.setattr(ProjectColumnBotTask, "project_column_created", lambda *_args: None)
    service = DomainService()
    try:
        with DbSession.use(readonly=False) as db:
            actor = models.User(
                firstname="Native", lastname="Owner", email="native-atomic@example.invalid", password="test-only"
            )
            db.insert(actor)
            for key in SI_WORKFLOW_STAGES:
                db.insert(models.WorkflowStageDefinition(key=key, name=key))
        apply_policy = service.project_template._apply_email_notification_policy

        def policy(project, template):
            apply_policy(project, template)
            assert effects == []
            if fail_after_policy:
                raise RuntimeError("failure after native policy persistence")

        monkeypatch.setattr(service.project_template, "_apply_email_notification_policy", policy)
        if fail_after_policy:
            with pytest.raises(RuntimeError, match="failure after native"):
                service.project_template.create_project(actor, "Native atomic", template_name="SI")
        else:
            project, columns, _ = service.project_template.create_project(actor, "Native atomic", template_name="SI")
            assert [column.workflow_stage for column in columns] == SI_WORKFLOW_STAGES
        with DbSession.use(readonly=True) as db:
            rows = {
                model: db.exec(SqlBuilder.select.table(model)).all()
                for model in tables
                if model not in (models.User, models.WorkflowStageDefinition, models.ProjectTemplate)
            }
        if fail_after_policy:
            assert all(not records for records in rows.values())
            assert effects == []
        else:
            assert len(rows[models.Project]) == 1
            assert len(rows[models.ProjectColumn]) == 6
            assert len(rows[models.ProjectLabel]) == len(models.ProjectLabel.DEFAULT_LABELS)
            assert len(rows[models.ProjectAssignedUser]) == 1
            assert rows[models.ProjectRole][0].actions == ["*"]
            assert len(rows[models.ProjectEmailNotificationPolicy]) == 1
            assert effects == ["project", *(["column"] * 5)]
    finally:
        service.close()
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            admin.dispose()
