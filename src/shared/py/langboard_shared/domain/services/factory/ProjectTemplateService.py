import re
from typing import Any
from ....core.domain import BaseDomainService
from ....helpers import InfraHelper
from ...models import (
    Bot,
    BotDefaultScopeBranch,
    GlobalLabel,
    InternalBot,
    Project,
    ProjectAssignedInternalBot,
    ProjectBotScope,
    ProjectColumn,
    ProjectColumnBotScope,
    ProjectTemplate,
    User,
)
from ...models.bases import BotTriggerCondition
from ...models.InternalBot import InternalBotType
from ...models.ProjectEmailNotificationPolicy import ProjectEmailNotificationCategory


SI_COLUMNS = ["Backlog", "Ready", "In Progress", "Review", "Done"]
SI_COLUMN_DESCRIPTIONS = [
    "Untriaged or uncommitted work. Claiming ownership alone does not mean work has started.",
    "Owned, prepared work waiting to start. Suggest this stage when someone commits to take a backlog item.",
    "Work actively being executed. Enter when the assignee explicitly starts work, not merely when assigned.",
    "Implementation is ready for review or acceptance. Do not infer approval from assignment.",
    "Completed and accepted work. Move here only when completion is explicitly confirmed.",
]
SI_WORKFLOW_STAGES = ["backlog", "ready", "active", "review", "closed"]
SI_COLUMN_DEFINITIONS = [
    {"name": name, "workflow_stage": stage, "description": description}
    for name, stage, description in zip(SI_COLUMNS, SI_WORKFLOW_STAGES, SI_COLUMN_DESCRIPTIONS, strict=True)
]
SI_EMAIL_NOTIFICATION_POLICY = {
    "is_enabled": True,
    "notify_all_members": True,
    "categories": [ProjectEmailNotificationCategory.Cards.value],
    "card_move_target_columns": ["Review"],
}


class ProjectTemplateService(BaseDomainService):
    """Capture and apply reusable project structure without copying work data."""

    @staticmethod
    def name() -> str:
        return "project_template"

    def ensure_builtin(self) -> ProjectTemplate:
        template = self.repo.project_template.get_by_name("SI")
        if template:
            if not template.is_builtin:
                raise ValueError("SI is reserved for the built-in project template")
            if self.repo.project_template.get_default() is None:
                self.repo.project_template.replace_default(template)
                template.is_default = True
            if not template.email_notification_policy:
                template.email_notification_policy = SI_EMAIL_NOTIFICATION_POLICY
                self.repo.project_template.update(template)
            if template.columns == SI_COLUMNS:
                definitions = template.column_definitions()
                for index, definition in enumerate(definitions):
                    definition["workflow_stage"] = SI_WORKFLOW_STAGES[index]
                    if not template.column_descriptions:
                        definition["description"] = SI_COLUMN_DESCRIPTIONS[index]
                template.columns = definitions
                template.column_descriptions = []
                self.repo.project_template.update(template)
            return template
        template = ProjectTemplate(
            name="SI",
            columns=[dict(column) for column in SI_COLUMN_DEFINITIONS],
            email_notification_policy=SI_EMAIL_NOTIFICATION_POLICY,
            is_builtin=True,
            is_default=True,
        )
        self.repo.project_template.insert(template)
        if self.repo.project_template.get_default() is None:
            self.repo.project_template.replace_default(template)
        return template

    def get_api_list(self) -> list[dict[str, Any]]:
        self.ensure_builtin()
        return [template.api_response() for template in self.repo.project_template.get_all()]

    def get(self, name: str | None = None) -> ProjectTemplate:
        self.ensure_builtin()
        template = self.repo.project_template.get_by_name(name) if name else self.repo.project_template.get_default()
        if not template:
            raise ValueError(f"Project template not found: {name}")
        return template

    def set_default(self, name: str) -> ProjectTemplate:
        template = self.get(name)
        self.repo.project_template.replace_default(template)
        template.is_default = True
        return template

    def save_columns(
        self,
        name: str,
        columns: list[dict[str, Any]],
        uid: str | None = None,
        *,
        description: str | None = None,
        global_label_uids: list[str] | None = None,
    ) -> ProjectTemplate | None:
        """Edit the existing structural SSOT without replacing automation snapshots."""
        template = InfraHelper.get_by_id_like(ProjectTemplate, uid) if uid else None
        if uid and not template:
            return None
        name = name.strip()
        if not name or len(name) > 100 or not 1 <= len(columns) <= 100:
            raise ValueError("Invalid template structure")
        existing = self.repo.project_template.get_by_name(name)
        if existing and (not template or existing.id != template.id):
            raise ValueError("Template name already exists")
        if (name == "SI" and not template) or (template and template.is_builtin and template.name != name):
            raise ValueError("Built-in template name is immutable")
        if description is not None and len(description) > 4096:
            raise ValueError("Template description is too long")
        if global_label_uids is not None:
            if len(global_label_uids) > 100 or len(set(global_label_uids)) != len(global_label_uids):
                raise ValueError("Invalid template labels")
            for label_uid in global_label_uids:
                if not InfraHelper.get_by_id_like(GlobalLabel, label_uid):
                    raise ValueError("Unknown global label")
        definitions = []
        for column in columns:
            column_name = column["name"].strip()
            column_description = column.get("description", "")
            stage_key = column.get("workflow_stage")
            if not column_name or len(column_name) > 100 or len(column_description) > 4096:
                raise ValueError("Invalid template column")
            if stage_key:
                stage = self.repo.workflow_stage.get_by_keys({stage_key}).get(stage_key)
                old_keys = {item.get("workflow_stage") for item in template.column_definitions()} if template else set()
                if not stage or (not stage.is_active and stage_key not in old_keys):
                    raise ValueError("Unknown or inactive workflow stage")
            translations = {language: dict(text) for language, text in column.get("translations", {}).items()}
            if len(set(translations) | {"en"}) > 30:
                raise ValueError("Too many column languages")
            for language, text in translations.items():
                if (
                    not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language)
                    or set(text) - {"name", "description"}
                    or len(text.get("name", "")) > 100
                    or len(text.get("description", "")) > 4096
                ):
                    raise ValueError("Invalid column translation")
            translations["en"] = {"name": column_name, "description": column_description}
            definitions.append(
                {
                    "name": column_name,
                    "description": column_description,
                    "workflow_stage": stage_key or None,
                    "translations": translations,
                }
            )
        if template:
            scoped_names = {scope.get("column_name") for scope in template.column_bot_scopes}
            if scoped_names - {column["name"] for column in definitions}:
                raise ValueError("Update column bot scopes before renaming or removing bound columns")
            template.name = name
            template.columns = definitions
            template.column_descriptions = []
            if description is not None:
                template.description = description
            if global_label_uids is not None:
                template.global_label_uids = list(global_label_uids)
            self.repo.project_template.update(template)
        else:
            template = ProjectTemplate(
                name=name,
                columns=definitions,
                description=description or "",
                global_label_uids=list(global_label_uids or []),
            )
            self.repo.project_template.insert(template)
        return template

    def copy_from_project(self, project: Project, name: str) -> ProjectTemplate:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Template name is required")
        if self.repo.project_template.get_by_name(clean_name):
            raise ValueError("Project template name already exists")

        raw_columns = [item[0] for item in self.repo.project_column.get_all_by_project(project)]
        columns = sorted((column for column in raw_columns if not column.is_archive), key=lambda item: item.order)
        internal_bots = [
            {
                "internal_bot_uid": internal_bot.get_uid(),
                "bot_type": internal_bot.bot_type.value,
                "prompt": assigned.prompt,
                "use_default_prompt": assigned.use_default_prompt,
            }
            for internal_bot, assigned in self.repo.project_assigned_internal_bot.get_all_by_project(project)
        ]
        project_scopes = [
            self._scope_snapshot(scope) for scope in self.repo.project_bot_scope.get_all_by_project(project)
        ]
        column_by_id = {column.id: column.name for column in columns}
        column_scopes = [
            {**self._scope_snapshot(scope), "column_name": column_by_id[scope.project_column_id]}
            for scope in self.repo.project_column.get_bot_scopes_by_project(project)
            if scope.project_column_id in column_by_id
        ]
        template = ProjectTemplate(
            name=clean_name,
            columns=[
                {"name": column.name, "workflow_stage": column.workflow_stage, "description": column.description}
                for column in columns
            ],
            internal_bots=internal_bots,
            project_bot_scopes=project_scopes,
            column_bot_scopes=column_scopes,
            email_notification_policy=self._email_notification_policy_snapshot(project),
        )
        self.repo.project_template.insert(template)
        return template

    def create_project(
        self,
        user: User,
        title: str,
        description: str | None = None,
        project_type: str = "Other",
        template_name: str | None = None,
        infer_template_prefix: bool = False,
    ) -> tuple[Project, list[ProjectColumn], ProjectTemplate]:
        title, template_name = self.resolve_creation_target(
            title,
            template_name,
            infer_template_prefix,
        )
        template = self.get(template_name)
        project_service = self._get_service_by_name("project")
        column_service = self._get_service_by_name("project_column")
        project = project_service.create(user, title, description, project_type)
        columns: list[ProjectColumn] = []
        try:
            for definition in template.column_definitions():
                fields = {"description": definition.get("description", "")}
                if definition.get("workflow_stage") is not None:
                    fields["workflow_stage"] = definition["workflow_stage"]
                column = column_service.create(user, project, definition["name"], **fields)
                if not column:
                    raise RuntimeError(f"Failed to create project column: {definition['name']}")
                columns.append(column)
            archive = self.repo.project_column.get_or_create_archive_if_not_exists(project)
            for order, column in enumerate(columns):
                column.order = order
            archive.order = len(columns)
            self.repo.project_column.update([*columns, archive])
            if template.global_label_uids:
                label_service = self._get_service_by_name("project_label")
                for label_uid in template.global_label_uids:
                    if not label_service.use_global(user, project, label_uid):
                        raise ValueError("Template global label is unavailable")
            self._apply_internal_bots(project, template.internal_bots)
            self._apply_scopes(project, columns, template)
            self._apply_email_notification_policy(project, template)
        except Exception:
            project_service.delete(user, project)
            raise
        return project, columns, template

    def _email_notification_policy_snapshot(self, project: Project) -> dict[str, Any]:
        policy, _ = self.repo.project_email_notification.get_with_recipients(project)
        if not policy:
            return {}
        return {
            "is_enabled": policy.is_enabled,
            "notify_all_members": policy.notify_all_members,
            "categories": [category.value for category in policy.categories],
            "card_move_target_columns": policy.card_move_target_columns,
        }

    def _apply_email_notification_policy(self, project: Project, template: ProjectTemplate) -> None:
        snapshot = template.email_notification_policy
        if not snapshot:
            return
        categories = [ProjectEmailNotificationCategory(value) for value in snapshot.get("categories", [])]
        self.repo.project_email_notification.replace(
            project,
            is_enabled=bool(snapshot.get("is_enabled")),
            notify_all_members=bool(snapshot.get("notify_all_members")),
            categories=categories,
            card_move_target_columns=[str(value) for value in snapshot.get("card_move_target_columns", [])],
            recipient_user_ids=[],
            external_recipient_emails=[],
        )

    def resolve_creation_target(
        self,
        title: str,
        template_name: str | None,
        infer_template_prefix: bool,
    ) -> tuple[str, str | None]:
        """Resolve an optional real template prefix without making names ambiguous."""

        clean_title = title.strip()
        if not infer_template_prefix or template_name is not None:
            return clean_title, template_name
        candidate, separator, remainder = clean_title.partition(" ")
        if separator and self.repo.project_template.get_by_name(candidate):
            return remainder.strip(), candidate
        return clean_title, None

    @staticmethod
    def _find_bot(bot_uname: str) -> Bot | None:
        return InfraHelper.get_by(Bot, "bot_uname", bot_uname)

    @staticmethod
    def _scope_snapshot(scope: ProjectBotScope | ProjectColumnBotScope) -> dict[str, Any]:
        bot = InfraHelper.get_by_id_like(Bot, scope.bot_id)
        branch = InfraHelper.get_by_id_like(BotDefaultScopeBranch, scope.default_scope_branch_id)
        return {
            "bot_uname": bot.bot_uname if bot else "",
            "default_scope_branch": branch.name if branch else None,
            "conditions": [condition.value for condition in scope.conditions],
            "is_frozen": scope.is_frozen,
        }

    def _apply_internal_bots(self, project: Project, snapshots: list[dict[str, Any]]) -> None:
        for snapshot in snapshots:
            try:
                bot_type = InternalBotType(snapshot["bot_type"])
            except (KeyError, ValueError):
                continue
            internal_bot_uid = str(snapshot.get("internal_bot_uid") or "")
            internal_bot = InfraHelper.get_by_id_like(InternalBot, internal_bot_uid) if internal_bot_uid else None
            if not internal_bot:
                internal_bot = self.repo.internal_bot.get_default_by_type(bot_type)
            if not internal_bot:
                continue
            assigned = self.repo.project_assigned_internal_bot.find_with_internal_bot_by_project_and_type(
                project, bot_type
            )
            if assigned:
                current_bot, setting = assigned
                if current_bot.id != internal_bot.id:
                    setting.internal_bot_id = internal_bot.id
                setting.prompt = str(snapshot.get("prompt") or "")
                setting.use_default_prompt = bool(snapshot.get("use_default_prompt", True))
                self.repo.project_assigned_internal_bot.update(setting)
            else:
                self.repo.project_assigned_internal_bot.insert(
                    ProjectAssignedInternalBot(
                        project_id=project.id,
                        internal_bot_id=internal_bot.id,
                        prompt=str(snapshot.get("prompt") or ""),
                        use_default_prompt=bool(snapshot.get("use_default_prompt", True)),
                    )
                )

    def _apply_scopes(self, project: Project, columns: list[ProjectColumn], template: ProjectTemplate) -> None:
        for snapshot in template.project_bot_scopes:
            scope = self._build_scope(ProjectBotScope, snapshot, project_id=project.id)
            if scope:
                self.repo.project_bot_scope.insert(scope)
        columns_by_name = {column.name: column for column in columns}
        for snapshot in template.column_bot_scopes:
            column = columns_by_name.get(str(snapshot.get("column_name") or ""))
            if not column:
                continue
            scope = self._build_scope(ProjectColumnBotScope, snapshot, project_column_id=column.id)
            if scope:
                self.repo.project_column_bot_scope.insert(scope)

    def _build_scope(self, model: type, snapshot: dict[str, Any], **scope: Any) -> Any | None:
        bot = self._find_bot(str(snapshot.get("bot_uname") or ""))
        if not bot:
            return None
        branch_name = snapshot.get("default_scope_branch")
        branch = next(
            (
                item
                for item in InfraHelper.get_all_by(BotDefaultScopeBranch, "bot_id", bot.id)
                if item.name == branch_name
            ),
            None,
        )
        available = model.get_available_conditions()
        conditions = []
        for value in snapshot.get("conditions", []):
            try:
                condition = BotTriggerCondition(value)
            except ValueError:
                continue
            if condition in available:
                conditions.append(condition)
        return model(
            bot_id=bot.id,
            default_scope_branch_id=branch.id if branch else None,
            conditions=conditions,
            is_frozen=bool(snapshot.get("is_frozen")),
            **scope,
        )
