import re
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseDomainService
from ....helpers import InfraHelper
from ....publishers import AppSettingPublisher
from ....tasks.webhooks.ExecutionReadinessUow import execution_readiness_uow
from ...models import Project, WorkflowStageDefinition


class WorkflowStageEditConflict(Exception):
    """The editor's snapshot no longer matches the locked registry row."""


class WorkflowStageService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "workflow_stage"

    def get_api_list(self) -> list[dict]:
        usage = self.repo.workflow_stage.get_column_usage()
        return [
            {**stage.api_response(), "used_column_count": usage.get(stage.key, 0)}
            for stage in sorted(InfraHelper.get_all(WorkflowStageDefinition), key=lambda s: (s.order, s.key))
        ]

    def get_api_by_keys(self, keys: set[str]) -> dict[str, dict]:
        """Resolve only workflow definitions used by an authorized result page."""
        return {key: stage.api_response() for key, stage in self.repo.workflow_stage.get_by_keys(keys).items()}

    def save(self, fields: dict, uid: str | None = None) -> WorkflowStageDefinition | None:
        fields = dict(fields)
        expected_revision = fields.pop("expected_revision", None)
        if set(fields) - {
            "key",
            "name",
            "description",
            "color",
            "order",
            "counts_as_completed",
            "active_queue_policy",
            "overdue_policy",
            "entry_effects",
            "translations",
        }:
            raise ValueError("Unsupported workflow fields")
        stage = InfraHelper.get_by_id_like(WorkflowStageDefinition, uid) if uid else None
        if uid and not stage:
            return None
        key = fields["key"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or (stage and stage.key != key):
            raise ValueError("Workflow key is invalid or immutable")
        name, description, color = fields["name"].strip(), fields["description"], fields["color"]
        if not name or len(name) > 100 or len(description) > 4000 or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Invalid workflow display")
        if fields["active_queue_policy"] not in {"include", "exclude", "conditional"} or fields[
            "overdue_policy"
        ] not in {"normal", "suppress"}:
            raise ValueError("Invalid workflow policy")
        effects = fields["entry_effects"]
        if len(effects) != len(set(effects)) or set(effects) - {"complete_checkitems", "stop_running_timers"}:
            raise ValueError("Unsupported native workflow effect")
        translations = {lang: dict(text) for lang, text in fields["translations"].items()}
        if len(set(translations) | {"en"}) > 30:
            raise ValueError("Too many workflow languages")
        for lang, text in translations.items():
            if (
                not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", lang)
                or set(text) - {"name", "description"}
                or len(text.get("name", "")) > 100
                or len(text.get("description", "")) > 4000
            ):
                raise ValueError("Invalid workflow translation")
        translations["en"] = {"name": name, "description": description}
        existing = InfraHelper.get_by(WorkflowStageDefinition, "key", key)
        if existing and (not stage or existing.id != stage.id):
            raise ValueError("Workflow key already exists")
        values = {**fields, "name": name, "color": color.upper(), "translations": translations}
        if stage:
            with DbSession.atomic() as db:
                stage = db.exec(
                    SqlBuilder.select.table(WorkflowStageDefinition)
                    .where(WorkflowStageDefinition.column("id") == stage.id)
                    .with_for_update()
                ).first()
                if stage is None:
                    return None
                if expected_revision is not None and expected_revision != stage.edit_revision():
                    raise WorkflowStageEditConflict()
                policy_changed = any(
                    getattr(stage, field) != values[field]
                    for field in (
                        "counts_as_completed",
                        "active_queue_policy",
                        "overdue_policy",
                    )
                )
                if stage.counts_as_completed != values["counts_as_completed"]:
                    with execution_readiness_uow() as execution:
                        execution.watch_workflow_stage(stage.key)
                        for field, value in values.items():
                            setattr(stage, field, value)
                        self.repo.workflow_stage.update(stage)
                else:
                    for field, value in values.items():
                        setattr(stage, field, value)
                    self.repo.workflow_stage.update(stage)
                if policy_changed:
                    stage_key = stage.key
                    db.after_commit(lambda: self._publish_work_states(stage_key))
                db.after_commit(AppSettingPublisher.workflow_stages_changed)
        else:
            stage = WorkflowStageDefinition(**values)
            with DbSession.atomic() as db:
                self.repo.workflow_stage.insert(stage)
                db.after_commit(AppSettingPublisher.workflow_stages_changed)
        return stage

    def deactivate(self, uid: str, expected_revision: str | None = None) -> WorkflowStageDefinition | None:
        stage = InfraHelper.get_by_id_like(WorkflowStageDefinition, uid)
        if stage:
            with DbSession.atomic() as db:
                stage = db.exec(
                    SqlBuilder.select.table(WorkflowStageDefinition)
                    .where(WorkflowStageDefinition.column("id") == stage.id)
                    .with_for_update()
                ).first()
                if stage is None:
                    return None
                if expected_revision is not None and expected_revision != stage.edit_revision():
                    raise WorkflowStageEditConflict()
                stage.is_active = False
                self.repo.workflow_stage.update(stage)
                db.after_commit(AppSettingPublisher.workflow_stages_changed)
        return stage

    def _publish_work_states(self, key: str) -> None:
        """Refresh native card projections after commit; never replay entry effects."""
        from .CardService import CardService

        grouped = {}
        for project_id, card_id in self.repo.workflow_stage.get_policy_affected_cards(key):
            grouped.setdefault(project_id, []).append(card_id)
        for project_id, card_ids in grouped.items():
            project = InfraHelper.get_by_id_like(Project, project_id)
            if project is not None:
                self._get_service(CardService).publish_work_states(project, card_ids)
