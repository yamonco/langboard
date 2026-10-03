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


@pytest.mark.parametrize("custom", [False, True])
@pytest.mark.parametrize("database", ["sqlite", "postgresql"])
@pytest.mark.parametrize("fail_after_policy", [False, True])
def test_native_project_membership_labels_roles_and_policy_share_template_transaction(
    monkeypatch, fail_after_policy, database, custom
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
        models.Card,
        models.Project,
        models.ProjectColumn,
        models.ProjectLabel,
        models.ProjectAssignedUser,
        models.ProjectRole,
        models.InternalBot,
        models.ProjectAssignedInternalBot,
        models.ProjectTemplate,
        models.GlobalLabel,
        models.Bot,
        models.BotDefaultScopeBranch,
        models.ProjectBotScope,
        models.ProjectColumnBotScope,
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
    monkeypatch.setattr(service.project_label, "dispatch_created", lambda *_args: effects.append("label"))
    try:
        with DbSession.use(readonly=False) as db:
            actor = models.User(
                firstname="Native", lastname="Owner", email="native-atomic@example.invalid", password="test-only"
            )
            db.insert(actor)
            for key in SI_WORKFLOW_STAGES:
                db.insert(models.WorkflowStageDefinition(key=key, name=key))
            if custom:
                from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
                from langboard_shared.domain.models.bases import BotTriggerCondition
                from langboard_shared.domain.models.InternalBot import InternalBotType

                internal = models.InternalBot(
                    bot_type=InternalBotType.EditorChat,
                    display_name="Template test editor",
                    platform=BotPlatform.Default,
                    platform_running_type=BotPlatformRunningType.Default,
                )
                bot = models.Bot(
                    name="Template test worker",
                    bot_uname="template-test-worker",
                    app_api_token="test-only",
                    platform=BotPlatform.Default,
                    platform_running_type=BotPlatformRunningType.Default,
                )
                label = models.GlobalLabel(
                    name="Template contract",
                    description="Preserve contract guidance",
                    color="#8B5CF6",
                    emoji="📜",
                    translations={"ko": {"name": "템플릿 계약", "description": "계약 지침"}},
                )
                db.insert(internal)
                db.insert(bot)
                db.insert(label)
                branch = models.BotDefaultScopeBranch(bot_id=bot.id, name="Template branch")
                db.insert(branch)
                scope = {
                    "bot_uname": bot.bot_uname,
                    "default_scope_branch": branch.name,
                    "conditions": [BotTriggerCondition.CardCreated.value],
                    "is_frozen": True,
                }
                template = models.ProjectTemplate(
                    name="Custom atomic",
                    columns=[
                        {
                            "name": "Queue",
                            "workflow_stage": "ready",
                            "description": "Column contract",
                            "translations": {"ko": {"name": "대기", "description": "칼럼 지침"}},
                        }
                    ],
                    global_label_uids=[label.get_uid()],
                    internal_bots=[
                        {
                            "internal_bot_uid": internal.get_uid(),
                            "bot_type": "editor_chat",
                            "prompt": "Keep this custom prompt",
                            "use_default_prompt": False,
                        }
                    ],
                    project_bot_scopes=[scope],
                    column_bot_scopes=[{**scope, "column_name": "Queue"}],
                    email_notification_policy={"is_enabled": False, "categories": ["cards"]},
                )
                db.insert(template)
        apply_policy = service.project_template._apply_email_notification_policy

        def policy(project, template):
            apply_policy(project, template)
            assert effects == []
            if fail_after_policy:
                raise RuntimeError("failure after native policy persistence")

        monkeypatch.setattr(service.project_template, "_apply_email_notification_policy", policy)
        if fail_after_policy:
            with pytest.raises(RuntimeError, match="failure after native"):
                service.project_template.create_project(
                    actor, "Native atomic", template_name="Custom atomic" if custom else "SI"
                )
        else:
            _project, columns, _ = service.project_template.create_project(
                actor, "Native atomic", template_name="Custom atomic" if custom else "SI"
            )
            assert [column.workflow_stage for column in columns] == (["ready"] if custom else SI_WORKFLOW_STAGES)
        with DbSession.use(readonly=True) as db:
            rows = {
                model: db.exec(SqlBuilder.select.table(model)).all()
                for model in tables
                if model
                not in (
                    models.User,
                    models.WorkflowStageDefinition,
                    models.ProjectTemplate,
                    models.GlobalLabel,
                    models.Bot,
                    models.BotDefaultScopeBranch,
                    models.InternalBot,
                )
            }
        if fail_after_policy:
            assert all(not records for records in rows.values())
            assert effects == []
        else:
            assert len(rows[models.Project]) == 1
            assert len(rows[models.ProjectColumn]) == (2 if custom else 6)
            assert len(rows[models.ProjectLabel]) == len(models.ProjectLabel.DEFAULT_LABELS) + int(custom)
            assert len(rows[models.ProjectAssignedUser]) == 1
            assert rows[models.ProjectRole][0].actions == ["*"]
            assert len(rows[models.ProjectEmailNotificationPolicy]) == 1
            assert effects == (["project", "column", "label"] if custom else ["project", *(["column"] * 5)])
            if custom:
                assigned = rows[models.ProjectAssignedInternalBot]
                assert len(assigned) == 1
                assert assigned[0].internal_bot_id == internal.id
                assert assigned[0].prompt == "Keep this custom prompt"
                assert assigned[0].use_default_prompt is False
                copied_label = next(item for item in rows[models.ProjectLabel] if item.global_label_id == label.id)
                assert copied_label.description == label.description
                assert copied_label.global_display == {"emoji": label.emoji, "translations": label.translations}
                for model in (models.ProjectBotScope, models.ProjectColumnBotScope):
                    assert len(rows[model]) == 1
                    copied_scope = rows[model][0]
                    assert copied_scope.bot_id == bot.id
                    assert copied_scope.default_scope_branch_id == branch.id
                    assert copied_scope.conditions == [BotTriggerCondition.CardCreated]
                    assert copied_scope.is_frozen is True
                active_column = next(item for item in rows[models.ProjectColumn] if not item.is_archive)
                assert active_column.description == "Column contract"
                assert active_column.translations["ko"]["name"] == "대기"
                effects.clear()
                copied_template = service.project_template.copy_from_project(_project, "Roundtrip custom")
                restored, restored_columns, _ = service.project_template.create_project(
                    actor, "Restored roundtrip", template_name=copied_template.name
                )
                assert restored.id != _project.id
                assert [column.workflow_stage for column in restored_columns] == ["ready"]
                assert restored_columns[0].description == active_column.description
                assert restored_columns[0].translations == active_column.translations
                restored_bots = service.project_template.repo.project_assigned_internal_bot.get_all_by_project(restored)
                assert len(restored_bots) == 1
                assert restored_bots[0][0].id == internal.id
                assert restored_bots[0][1].prompt == assigned[0].prompt
                assert restored_bots[0][1].use_default_prompt is False
                assert copied_template.global_label_uids == [label.get_uid()]
                restored_labels = service.project_template.repo.project_label.get_all_by_project(restored)
                assert len(restored_labels) == len(models.ProjectLabel.DEFAULT_LABELS) + 1
                restored_global = next(item for item in restored_labels if item.global_label_id == label.id)
                assert restored_global.global_display == copied_label.global_display
                assert restored_global.description == copied_label.description
                assert copied_template.internal_bots == template.internal_bots
                assert copied_template.project_bot_scopes == template.project_bot_scopes
                assert copied_template.column_bot_scopes == template.column_bot_scopes
    finally:
        service.close()
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            admin.dispose()
