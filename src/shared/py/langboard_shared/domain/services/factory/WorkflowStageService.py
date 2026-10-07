import re
from collections.abc import Mapping
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseDomainService
from ....helpers import InfraHelper
from ....publishers import AppSettingPublisher
from ....tasks.webhooks.ExecutionReadinessUow import execution_readiness_uow
from ...models import (
    BoardAppBinding,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    ProjectRole,
    User,
    WorkflowStageDefinition,
)
from ...models.ProjectRole import ProjectRoleAction
from ..AppWorkflowPolicy import (
    APP_WORKFLOW_REQUIREMENTS,
    WorkflowMappingResult,
    WorkflowRequirements,
    resolve_app_workflow,
)


class WorkflowStageEditConflict(Exception):
    """The editor's snapshot no longer matches the locked registry row."""


class WorkflowStageService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "workflow_stage"

    def preview_app_mapping(
        self, user: User, project: Project | int | str,
        requirements: WorkflowRequirements, explicit: Mapping[str, str],
    ) -> WorkflowMappingResult | None:
        """Preview current host facts, never execution or mutation authority.

        Re-read the primary so stale caller models, roles and replicas cannot
        authorize a board. App binding writes still require their own update gate.
        """
        return self._resolve_app_mapping(user, project, requirements, explicit, ProjectRoleAction.Read)

    def get_app_catalog(self, user: User, project_uid: str) -> list[dict] | None:
        """Host catalog and board-owned status, never installation authority."""
        with DbSession.atomic() as db:
            if self.preview_app_mapping(user, project_uid, APP_WORKFLOW_REQUIREMENTS["github"], {}) is None:
                return None
            bindings = db.exec(SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.project_id == InfraHelper.convert_id(project_uid),
            )).all()
            by_app = {binding.app_key: binding for binding in bindings}
            items = []
            for key, name in (("github", "GitHub"), ("glitchtip", "GlitchTip"), ("dokploy", "Dokploy")):
                binding = by_app.get(key)
                requirements = APP_WORKFLOW_REQUIREMENTS.get(key)
                items.append({
                    "key": key, "name": name,
                    "workflow_requirements": None if requirements is None else {
                        "required": list(requirements.required), "optional": list(requirements.optional),
                    },
                    "connection_setup_available": False,
                    "binding": None if binding is None else {
                        "uid": binding.get_uid(), "state": binding.state,
                        "granted_capabilities": list(binding.granted_capabilities),
                        "stage_transitions_enabled": binding.stage_transitions_enabled,
                    },
                })
            return items

    def get_app_mapping(self, user: User, project_uid: str, app_key: str) -> dict | None:
        requirements = APP_WORKFLOW_REQUIREMENTS.get(app_key)
        if requirements is None:
            return None
        with DbSession.atomic() as db:
            binding = db.exec(
                SqlBuilder.select.table(BoardAppBinding).where(
                    BoardAppBinding.project_id == InfraHelper.convert_id(project_uid),
                    BoardAppBinding.app_key == app_key,
                )
            ).first()
            result = self.preview_app_mapping(
                user,
                project_uid,
                requirements,
                binding.workflow_mapping if binding else {},
            )
            if result is None:
                return None
            columns = db.exec(
                SqlBuilder.select.table(ProjectColumn).where(
                    ProjectColumn.project_id == InfraHelper.convert_id(project_uid),
                    ProjectColumn.deleted_at.is_(None),
                    ProjectColumn.is_archive == False,  # noqa: E712
                )
            ).all()
            return {
                "binding": binding,
                "mapping": result,
                "column_names": {column.get_uid(): column.name for column in columns},
                "available_columns": [
                    {"uid": column.get_uid(), "name": column.name, "workflow_stage": column.workflow_stage}
                    for column in columns
                ],
            }

    def prepare_app_mapping(self, user: User, project_uid: str, app_key: str) -> BoardAppBinding | None:
        """Create only a disabled workflow draft; this is not App installation."""
        requirements = APP_WORKFLOW_REQUIREMENTS.get(app_key)
        if requirements is None:
            return None
        with DbSession.atomic() as db:
            project_id = InfraHelper.convert_id(project_uid)
            board = db.exec(SqlBuilder.select.table(Project).where(
                Project.id == project_id,
            ).with_for_update()).first()
            if board is None:
                return None
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.project_id == project_id, BoardAppBinding.app_key == app_key,
            ).with_for_update()).first()
            result = self._resolve_app_mapping(
                user, project_id, requirements, {}, ProjectRoleAction.Update, lock=True,
            )
            if result is None:
                return None
            if binding is not None:
                return binding
            binding = BoardAppBinding(
                project_id=project_id, app_key=app_key,
                workflow_mapping={choice.stage: choice.column_uid for choice in result.choices if choice.status == "resolved"},
            )
            db.insert(binding)
            return binding

    def save_app_mapping(
        self, user: User, binding_uid: str,
        explicit: Mapping[str, str] | None, *, project_uid: str, app_key: str, expected_revision: str,
        enable_transitions: bool,
    ) -> BoardAppBinding | None:
        """Resolve requirements from the saved App key, never from request bodies.

        Persist current choices without changing resource selections, grants or
        App activation. Incomplete mappings may be saved with transitions off.
        This does not authorize future transition execution.
        """
        with DbSession.atomic() as db:
            # Match draft creation's lock order: board before binding.
            board = db.exec(SqlBuilder.select.table(Project).where(
                Project.id == InfraHelper.convert_id(project_uid),
            ).with_for_update()).first()
            if board is None:
                return None
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.id == InfraHelper.convert_id(binding_uid),
                BoardAppBinding.project_id == InfraHelper.convert_id(project_uid),
                BoardAppBinding.app_key == app_key,
            ).with_for_update()).first()
            if binding is None:
                return None
            requirements = APP_WORKFLOW_REQUIREMENTS.get(binding.app_key)
            if requirements is None:
                return None
            mapping = dict(binding.workflow_mapping if explicit is None else explicit)
            result = self._resolve_app_mapping(
                user, binding.project_id, requirements, mapping, ProjectRoleAction.Update, lock=True,
            )
            if result is None:
                return None
            if binding.edit_revision() != expected_revision:
                raise WorkflowStageEditConflict()
            if enable_transitions and not result.transitions_enabled:
                raise ValueError("App workflow mapping is incomplete or invalid")
            # Save automatic unique choices too, so a later duplicate cannot
            # silently change an existing App destination.
            binding.workflow_mapping = {
                **mapping,
                **{choice.stage: choice.column_uid for choice in result.choices if choice.status == "resolved"},
            }
            binding.stage_transitions_enabled = enable_transitions
            db.update(binding)
            return binding

    def _resolve_app_mapping(
        self, user: User, project: Project | int | str,
        requirements: WorkflowRequirements, explicit: Mapping[str, str],
        action: ProjectRoleAction, *, lock: bool = False,
    ) -> WorkflowMappingResult | None:
        def query(model):
            statement = SqlBuilder.select.table(model)
            return statement.with_for_update() if lock else statement

        if not isinstance(user, User):
            return None
        project_id = InfraHelper.convert_id(project)
        with DbSession.use(readonly=False) as db:
            current = db.exec(query(User).where(User.id == user.id)).first()
            board = db.exec(query(Project).where(Project.id == project_id)).first()
            if current is None or current.deleted_at or not current.activated_at or board is None or board.deleted_at:
                return None
            if not current.is_admin and board.owner_id != current.id:
                member = db.exec(query(ProjectAssignedUser).where(
                    ProjectAssignedUser.project_id == board.id, ProjectAssignedUser.user_id == current.id,
                )).first()
                role = db.exec(query(ProjectRole).where(
                    ProjectRole.project_id == board.id, ProjectRole.user_id == current.id,
                )).first()
                if member is None or role is None or not role.is_granted(action):
                    return None
            columns = db.exec(query(ProjectColumn).where(ProjectColumn.project_id == board.id)).all()
            keys = requirements.required + requirements.optional
            stages = db.exec(query(WorkflowStageDefinition).where(
                WorkflowStageDefinition.key.in_(keys),
            )).all()
        return resolve_app_workflow(
            requirements, int(board.id), columns, stages, explicit,
            authorized_column_ids=frozenset(int(column.id) for column in columns),
        )

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
