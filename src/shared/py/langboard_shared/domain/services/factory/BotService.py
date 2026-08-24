import re
from typing import Any, Mapping, Sequence
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.domain import BaseDomainService
from ....core.domain.BaseDomainService import TMutableValidatorMap
from ....core.storage import FileModel
from ....core.types import SafeDateTime
from ....core.types.BotRelatedTypes import AVAILABLE_BOT_TARGET_TABLES
from ....core.types.ParamTypes import TBotParam
from ....core.utils.Converter import convert_python_data
from ....core.utils.IpAddress import ALLOWED_ALL_IPS, is_valid_ipv4_address_or_range, make_valid_ipv4_range
from ....core.utils.String import generate_random_string
from ....helpers import BotHelper, InfraHelper
from ....publishers import BotPublisher, ProjectBotPublisher
from ....tasks.bots import BotDefaultTask
from ...models import Bot, BotDefaultScopeBranch, BotSchedule, Card, Project, ProjectBotScope, ProjectColumn
from ...models.BaseBotModel import BotPlatform, BotPlatformRunningType
from ...models.bases import BaseBotScheduleModel, BaseBotScopeModel, BotTriggerCondition
from ...models.BotSchedule import BotScheduleRunningType
from ...models.GraphApprovalRequest import GraphApprovalOriginType
from .GraphApprovalRequestService import GraphApprovalRequestService


ACTION_SUGGESTION_RISK_BY_PERMISSION = {
    "read": "low",
    "create": "medium",
    "edit": "medium",
    "delete": "high",
}


class BotServiceError(ValueError):
    """Stable domain error shared by REST and MCP Bot adapters."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BotService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "bot"

    def get_by_id_like(self, bot: TBotParam | None) -> Bot | None:
        bot = InfraHelper.get_by_id_like(Bot, bot)
        return bot

    def get_api_list(self, is_setting: bool = False) -> list[dict[str, Any]]:
        bots = InfraHelper.get_all(Bot)
        api_bots = []
        for bot in bots:
            api_bot = bot.api_response(is_setting=is_setting)
            api_bots.append(api_bot)
        return api_bots

    def has_project_access(self, bot: TBotParam | None, project: str | None) -> bool:
        """Return whether a Bot already owns a Hook on the project."""

        if not project:
            return False
        resolved_bot = InfraHelper.get_by_id_like(Bot, bot)
        resolved_project = InfraHelper.get_by_id_like(Project, project)
        if not resolved_bot or not resolved_project:
            return False
        return bool(BotScopeHelper.get_list(ProjectBotScope, bot_id=resolved_bot.id, project_id=resolved_project.id))

    def create(
        self,
        name: str,
        bot_uname: str,
        platform: BotPlatform,
        platform_running_type: BotPlatformRunningType,
        api_url: str,
        api_key: str,
        ip_whitelist: list[str],
        value: str | None = None,
        avatar: FileModel | None = None,
    ) -> Bot | None:
        existing_bot = InfraHelper.get_by(Bot, "bot_uname", bot_uname)
        if existing_bot:
            return None

        bot = Bot(
            name=name,
            bot_uname=bot_uname,
            platform=platform,
            platform_running_type=platform_running_type,
            avatar=avatar,
            api_url=api_url,
            api_key=api_key,
            app_api_token=self.generate_api_key(),
            ip_whitelist=self.filter_valid_ip_whitelist(ip_whitelist),
            value=value or "",
        )

        self.repo.bot.insert(bot)

        BotPublisher.bot_created(bot)
        BotDefaultTask.bot_created(bot)

        return bot

    def upsert_hook(
        self,
        bot: TBotParam | None,
        target_table: str,
        target_uid: str,
        events: list[BotTriggerCondition],
        *,
        active: bool = True,
        project: str | None = None,
    ) -> dict[str, Any] | None:
        """Converge one bot event subscription on one native target."""

        resolved_bot = InfraHelper.get_by_id_like(Bot, bot)
        target_result = BotHelper.get_target_model_by_param("scope", target_table, target_uid)
        if not resolved_bot or not target_result:
            return None

        scope_model_class, target = target_result
        self._require_hook_project(target, project)
        if len(events) != len(set(events)):
            raise ValueError("Bot Hook events must be unique")
        invalid_events = set(events) - scope_model_class.get_available_conditions()
        if invalid_events:
            names = ", ".join(sorted(event.value for event in invalid_events))
            raise ValueError(f"Events are not available for {target_table}: {names}")

        scope_column_name = scope_model_class.get_scope_column_name()
        existing = BotScopeHelper.get_list(
            scope_model_class,
            None,
            bot_id=resolved_bot.id,
            **{scope_column_name: target.id},
        )
        if len(existing) > 1:
            raise ValueError("Duplicate Bot Hooks require administrator repair")
        previous_events = tuple(existing[0].conditions) if existing else None
        previous_active = not existing[0].is_frozen if existing else None

        upserted = BotScopeHelper.upsert_conditions(scope_model_class, resolved_bot, target, events)
        if not upserted:
            return None
        scope, created = upserted
        active_changed = previous_active is None or previous_active != active
        if scope.is_frozen == active:
            updated = BotScopeHelper.set_freeze(scope_model_class, scope, not active)
            if not updated:
                return None
            scope = updated

        project = self._hook_project(target)
        if project:
            if created:
                ProjectBotPublisher.scope_created(project, scope)
            elif previous_events != tuple(events):
                ProjectBotPublisher.scope_conditions_updated(project, scope)
            if not created and active_changed:
                ProjectBotPublisher.scope_freeze_updated(project, scope)

        return self._hook_response(resolved_bot, scope, target_table, target.get_uid())

    def get_hook(
        self,
        bot: TBotParam | None,
        target_table: str,
        hook_uid: str,
        *,
        project: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one Bot-owned Hook within an optional project boundary."""

        resolved = self._resolve_hook(bot, target_table, hook_uid)
        if not resolved:
            return None
        resolved_bot, scope, target = resolved
        self._require_hook_project(target, project)
        return self._hook_response(resolved_bot, scope, target_table, target.get_uid())

    def update_hook(
        self,
        bot: TBotParam | None,
        target_table: str,
        hook_uid: str,
        *,
        events: list[BotTriggerCondition] | None = None,
        active: bool | None = None,
        project: str | None = None,
    ) -> dict[str, Any] | None:
        """Update one existing Bot Hook without bypassing its ownership boundary."""

        resolved = self._resolve_hook(bot, target_table, hook_uid)
        if not resolved:
            return None
        resolved_bot, scope, target = resolved
        self._require_hook_project(target, project)
        return self.upsert_hook(
            resolved_bot,
            target_table,
            target.get_uid(),
            list(scope.conditions) if events is None else events,
            active=not scope.is_frozen if active is None else active,
            project=project,
        )

    def delete_hook(
        self,
        bot: TBotParam | None,
        target_table: str,
        hook_uid: str,
        *,
        project: str | None = None,
    ) -> dict[str, Any] | None:
        """Delete one owned Bot Hook and cancel work that can no longer run."""

        resolved = self._resolve_hook(bot, target_table, hook_uid)
        if not resolved:
            return None
        resolved_bot, scope, target = resolved
        self._require_hook_project(target, project)
        hook = self._hook_response(resolved_bot, scope, target_table, target.get_uid())
        scope_model_class = type(scope)
        BotScopeHelper.delete(scope_model_class, scope)

        project = self._hook_project(target)
        if project:
            approval_service = self._get_service(GraphApprovalRequestService)
            for origin_type in (GraphApprovalOriginType.Trigger, GraphApprovalOriginType.ManualScopeRun):
                approval_service.cancel_pending_by_scope(
                    project,
                    target_table,
                    target.get_uid(),
                    origin_type=origin_type,
                    bot=resolved_bot,
                    reason="bot hook deleted",
                )
            ProjectBotPublisher.scope_deleted(project, scope)
        return hook

    def _require_hook_project(self, target: Project | ProjectColumn | Card, project: str | None) -> None:
        """Fail closed when an authorized project does not own the Hook target."""

        if project is None:
            return
        resolved_project = InfraHelper.get_by_id_like(Project, project)
        target_project = self._hook_project(target)
        if not resolved_project or not target_project or resolved_project.id != target_project.id:
            raise BotServiceError("project_mismatch", "Bot Hook target is outside the authorized project")

    def _resolve_hook(
        self,
        bot: TBotParam | None,
        target_table: str,
        hook_uid: str,
    ) -> tuple[Bot, BaseBotScopeModel, Project | ProjectColumn | Card] | None:
        """Resolve an existing hook and fail closed when its Bot does not own it."""

        resolved_bot = InfraHelper.get_by_id_like(Bot, bot)
        scope_model_class = BotHelper.get_bot_model_class("scope", target_table)
        if not resolved_bot or not scope_model_class:
            return None
        scope = BotScopeHelper.get_by_id_like(scope_model_class, hook_uid)
        if not scope or scope.bot_id != resolved_bot.id:
            return None

        target_id = scope.__dict__.get(scope.get_scope_column_name())
        target_result = BotHelper.get_target_model_by_param("scope", target_table, target_id)
        if not target_result:
            return None
        _, target = target_result
        return resolved_bot, scope, target

    def get_owned_schedule(
        self,
        bot: TBotParam | None,
        target_table: str,
        schedule_uid: str,
    ) -> tuple[type[BaseBotScheduleModel], BaseBotScheduleModel, Project | ProjectColumn | Card] | None:
        """Resolve a schedule only when the requested Bot owns its runtime record."""

        resolved_bot = InfraHelper.get_by_id_like(Bot, bot)
        schedule_model_class = BotHelper.get_bot_model_class("schedule", target_table)
        if not resolved_bot or not schedule_model_class:
            return None
        schedule_model = InfraHelper.get_by_id_like(schedule_model_class, schedule_uid)
        if not schedule_model:
            return None
        schedule = InfraHelper.get_by_id_like(BotSchedule, schedule_model.bot_schedule_id)
        if not schedule or schedule.bot_id != resolved_bot.id:
            return None

        target_id = schedule_model.__dict__.get(schedule_model_class.get_scope_column_name())
        target_result = BotHelper.get_target_model_by_param("schedule", target_table, target_id)
        if not target_result:
            return None
        _, target = target_result
        return schedule_model_class, schedule_model, target

    def create_schedule(
        self,
        bot: TBotParam | None,
        target_table: str,
        target_uid: str,
        interval: str,
        running_type: BotScheduleRunningType | None = None,
        start_at: SafeDateTime | None = None,
        end_at: SafeDateTime | None = None,
        timezone: str | float = "UTC",
    ) -> dict[str, Any]:
        """Create a Bot Schedule and return its canonical operation receipt."""

        normalized_interval = BotScheduleHelper.utils.convert_valid_interval_str(interval)
        if not normalized_interval:
            raise BotServiceError("invalid_interval", "Invalid Bot Schedule interval")
        normalized_running_type = running_type or BotScheduleRunningType.Infinite
        if normalized_running_type == BotScheduleRunningType.Duration and not start_at:
            start_at = SafeDateTime.now()
        if not BotScheduleHelper.get_default_status_with_dates(
            running_type=normalized_running_type,
            start_at=start_at,
            end_at=end_at,
        ):
            raise BotServiceError("invalid_window", "Invalid Bot Schedule time window")

        resolved_bot = InfraHelper.get_by_id_like(Bot, bot)
        if not resolved_bot:
            raise BotServiceError("bot_not_found", "Bot not found")
        if not BotHelper.get_bot_model_class("schedule", target_table):
            raise BotServiceError("target_type_invalid", "Bot Schedule target type is invalid")
        target_result = BotHelper.get_target_model_by_param("schedule", target_table, target_uid)
        if not target_result:
            raise BotServiceError("target_not_found", "Bot Schedule target not found")
        schedule_model_class, target = target_result
        scheduled = BotScheduleHelper.schedule(
            schedule_model_class,
            resolved_bot,
            normalized_interval,
            target,
            normalized_running_type,
            start_at,
            end_at,
            timezone,
        )
        if not scheduled:
            raise BotServiceError("schedule_failed", "Bot Schedule could not be created")

        project = self._hook_project(target)
        if project:
            ProjectBotPublisher.scheduled(project, scheduled)
        schedule, schedule_model = scheduled
        return self._schedule_receipt(
            "created",
            resolved_bot,
            schedule,
            schedule_model,
            target_table,
            target.get_uid(),
        )

    def update_schedule(
        self,
        bot: TBotParam | None,
        target_table: str,
        schedule_uid: str,
        interval: str | None = None,
        running_type: BotScheduleRunningType | None = None,
        start_at: SafeDateTime | None = None,
        end_at: SafeDateTime | None = None,
        timezone: str | float = "UTC",
    ) -> dict[str, Any]:
        """Update an owned Bot Schedule and publish the same result for every adapter."""

        normalized_interval = interval
        if interval:
            normalized_interval = BotScheduleHelper.utils.convert_valid_interval_str(interval)
            if not normalized_interval:
                raise BotServiceError("invalid_interval", "Invalid Bot Schedule interval")
        if not BotScheduleHelper.get_default_status_with_dates(
            running_type=running_type,
            start_at=start_at,
            end_at=end_at,
        ):
            raise BotServiceError("invalid_window", "Invalid Bot Schedule time window")

        if not BotHelper.get_bot_model_class("schedule", target_table):
            raise BotServiceError("target_type_invalid", "Bot Schedule target type is invalid")
        owned = self.get_owned_schedule(bot, target_table, schedule_uid)
        if not owned:
            raise BotServiceError("schedule_not_found", "Bot Schedule not found or not owned by Bot")
        schedule_model_class, schedule_model, target = owned
        updated = BotScheduleHelper.reschedule(
            schedule_model_class,
            schedule_model,
            normalized_interval,
            running_type,
            start_at,
            end_at,
            timezone,
        )
        if not updated:
            raise BotServiceError("schedule_failed", "Bot Schedule could not be updated")
        schedule, updated_schedule_model, changes = updated

        project = self._hook_project(target)
        if project:
            ProjectBotPublisher.rescheduled(project, updated_schedule_model, changes)
        resolved_bot = InfraHelper.get_by_id_like(Bot, bot)
        if not resolved_bot:
            raise BotServiceError("bot_not_found", "Bot not found")
        return self._schedule_receipt(
            "updated",
            resolved_bot,
            schedule,
            updated_schedule_model,
            target_table,
            target.get_uid(),
            changes=changes,
        )

    def delete_schedule(
        self,
        bot: TBotParam | None,
        target_table: str,
        schedule_uid: str,
    ) -> dict[str, Any]:
        """Delete an owned Bot Schedule and cancel its pending approval work."""

        if not BotHelper.get_bot_model_class("schedule", target_table):
            raise BotServiceError("target_type_invalid", "Bot Schedule target type is invalid")
        owned = self.get_owned_schedule(bot, target_table, schedule_uid)
        if not owned:
            raise BotServiceError("schedule_not_found", "Bot Schedule not found or not owned by Bot")
        schedule_model_class, schedule_model, target = owned
        resolved_bot = InfraHelper.get_by_id_like(Bot, bot)
        schedule = InfraHelper.get_by_id_like(BotSchedule, schedule_model.bot_schedule_id)
        if not resolved_bot or not schedule:
            raise BotServiceError("schedule_not_found", "Bot Schedule not found or not owned by Bot")
        receipt = self._schedule_receipt(
            "deleted",
            resolved_bot,
            schedule,
            schedule_model,
            target_table,
            target.get_uid(),
        )
        deleted = BotScheduleHelper.unschedule(schedule_model_class, schedule_model)
        if not deleted:
            raise BotServiceError("schedule_failed", "Bot Schedule could not be deleted")
        _, deleted_schedule_model = deleted

        project = self._hook_project(target)
        if project:
            self._get_service(GraphApprovalRequestService).cancel_pending_by_scope(
                project,
                target_table,
                target.get_uid(),
                origin_type=GraphApprovalOriginType.Schedule,
                bot=resolved_bot,
                reason="bot schedule deleted",
            )
            ProjectBotPublisher.unscheduled(project, deleted_schedule_model)
        return receipt

    @staticmethod
    def _schedule_receipt(
        operation: str,
        bot: Bot,
        schedule: BotSchedule,
        schedule_model: BaseBotScheduleModel,
        target_table: str,
        target_uid: str,
        *,
        changes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return one canonical Schedule receipt for REST, MCP, and audit consumers."""

        receipt: dict[str, Any] = {
            "operation": operation,
            "schedule": {
                **schedule.api_response(),
                **schedule_model.api_response(),
                "bot_uid": bot.get_uid(),
                "target": {"type": target_table, "uid": target_uid},
            },
            "changes": convert_python_data(changes or {}, recursive=True),
        }
        return receipt

    def _hook_project(self, target: Project | ProjectColumn | Card) -> Project | None:
        """Resolve the project that owns a hook target."""

        if isinstance(target, Project):
            return target
        return InfraHelper.get_by_id_like(Project, target.project_id)

    @staticmethod
    def _hook_response(
        bot: Bot,
        scope: BaseBotScopeModel,
        target_table: str,
        target_uid: str,
    ) -> dict[str, Any]:
        """Return the canonical public Bot Hook representation."""

        return {
            "uid": scope.get_uid(),
            "bot_uid": bot.get_uid(),
            "target": {"type": target_table, "uid": target_uid},
            "events": [event.value for event in scope.conditions],
            "active": not scope.is_frozen,
        }

    def copy(self, bot: TBotParam | None) -> Bot | None:
        source_bot = InfraHelper.get_by_id_like(Bot, bot)
        if not source_bot:
            return None

        copied_bot = Bot(
            name=f"{source_bot.name} Copy",
            bot_uname=self.generate_copied_bot_uname(source_bot.bot_uname),
            platform=source_bot.platform,
            platform_running_type=source_bot.platform_running_type,
            avatar=source_bot.avatar,
            api_url=source_bot.api_url,
            api_key=source_bot.api_key,
            app_api_token=self.generate_api_key(),
            ip_whitelist=[*source_bot.ip_whitelist],
            value=source_bot.value,
        )

        self.repo.bot.insert(copied_bot)
        BotPublisher.bot_created(copied_bot)
        self.copy_default_scope_branches(source_bot, copied_bot)
        BotDefaultTask.bot_created(copied_bot)

        return copied_bot

    def update(self, bot: TBotParam | None, form: dict) -> bool | tuple[Bot, dict[str, Any]] | None:
        bot = InfraHelper.get_by_id_like(Bot, bot)
        if not bot:
            return None
        validators: TMutableValidatorMap = {
            "name": "default",
            "bot_uname": "default",
            "avatar": "default",
            "api_url": "default",
            "platform": "default",
            "platform_running_type": "default",
            "api_key": "default",
            "value": "default",
        }
        unpublishable_keys = [
            "api_url",
            "platform",
            "platform_running_type",
            "api_key",
            "value",
        ]

        if "platform" in form and form["platform"] != bot.platform:
            if form["platform"] not in Bot.ALLOWED_ALL_IPS_BY_PLATFORMS:
                form.pop("platform", None)
                form.pop("platform_running_type", None)
            else:
                available_running_types = Bot.AVAILABLE_RUNNING_TYPES_BY_PLATFORM[form["platform"]]
                platform_running_type = form.get("platform_running_type", available_running_types[0])
                if platform_running_type not in available_running_types:
                    form["platform_running_type"] = available_running_types[0]

        if "platform_running_type" in form:
            platform = form.get("platform", bot.platform)
            if platform not in Bot.AVAILABLE_RUNNING_TYPES_BY_PLATFORM:
                form.pop("platform_running_type", None)
            else:
                available_running_types = Bot.AVAILABLE_RUNNING_TYPES_BY_PLATFORM[platform]
                if form["platform_running_type"] not in available_running_types:
                    form.pop("platform_running_type", None)

        if "bot_uname" in form:
            existing_bot = InfraHelper.get_by(Bot, "bot_uname", form["bot_uname"])
            if existing_bot:
                return False

        old_record = self.apply_mutates(bot, form, validators)

        if "delete_avatar" in form and form["delete_avatar"]:
            old_record["avatar"] = convert_python_data(bot.avatar)
            bot.avatar = None

        if not old_record:
            return True

        self.repo.bot.update(bot)

        model: dict[str, Any] = {}
        unpublishable_model: dict[str, Any] = {}
        for key in form:
            if key in unpublishable_keys:
                if key in old_record:
                    unpublishable_model[key] = convert_python_data(getattr(bot, key))
                continue

            if key not in validators or key not in old_record:
                continue
            if key == "avatar":
                if bot.avatar:
                    model[key] = bot.avatar.path
                else:
                    model["deleted_avatar"] = True
            else:
                model[key] = convert_python_data(getattr(bot, key))

        BotPublisher.bot_updated(bot.get_uid(), model)
        BotPublisher.bot_setting_updated(bot.get_uid(), unpublishable_model)

        model = {**model}
        for key in unpublishable_keys:
            if key in old_record:
                model[key] = convert_python_data(getattr(bot, key))

        return bot, model

    def update_ip_whitelist(self, bot: TBotParam | None, ip_whitelist: list[str]) -> bool | tuple[Bot, dict[str, Any]]:
        bot = InfraHelper.get_by_id_like(Bot, bot)
        if not bot:
            return False

        valid_ip_whitelist = self.filter_valid_ip_whitelist(ip_whitelist)

        bot.ip_whitelist = valid_ip_whitelist
        self.repo.bot.update(bot)

        BotPublisher.bot_setting_updated(bot.get_uid(), {"ip_whitelist": valid_ip_whitelist})

        return bot, {"ip_whitelist": valid_ip_whitelist}

    def generate_new_api_token(self, bot: TBotParam | None) -> Bot | None:
        bot = InfraHelper.get_by_id_like(Bot, bot)
        if not bot:
            return None

        bot.app_api_token = self.generate_api_key()
        self.repo.bot.update(bot)

        BotPublisher.bot_setting_updated(bot.get_uid(), {"app_api_token": bot.app_api_token})

        return bot

    def delete(self, bot: TBotParam | None) -> bool:
        bot = InfraHelper.get_by_id_like(Bot, bot)
        if not bot:
            return False

        self._get_service(GraphApprovalRequestService).cancel_pending_by_bot(bot, reason="bot deleted")
        self.repo.bot.delete(bot)

        BotPublisher.bot_deleted(bot.get_uid())

        return True

    def suggest_action_candidates(
        self,
        prompt: str,
        api_schemas: Mapping[str, Mapping[str, Any]],
        comfort_tools: Sequence[dict[str, Any]],
        mcp_tools: Sequence[dict[str, Any]] | None = None,
        mcp_tool_groups: Sequence[dict[str, Any]] | None = None,
        selected_api_names: Sequence[str] | None = None,
        selected_comfort_tool_names: Sequence[str] | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        prompt_text = prompt.strip()
        if not prompt_text:
            return []

        selected_api_set = set(selected_api_names or [])
        selected_comfort_tool_set = set(selected_comfort_tool_names or [])
        prompt_tokens = self._tokenize_action_suggestion_text(prompt_text)
        candidates: list[dict[str, Any]] = []

        for comfort_tool in comfort_tools:
            name = str(comfort_tool.get("name") or "")
            api_names = [str(api_name) for api_name in comfort_tool.get("api_names", [])]
            if not name or not api_names:
                continue

            label = str(comfort_tool.get("label") or name)
            description = str(comfort_tool.get("description") or "")
            permissions = [
                self._normalize_api_permission(api_schemas.get(api_name, {}).get("permission"))
                for api_name in api_names
            ]
            risk = self._get_highest_action_risk(permissions)
            score = self._score_action_suggestion(prompt_text, prompt_tokens, [name, label, description, *api_names])
            if score <= 0:
                continue

            candidates.append(
                {
                    "source": "comfort_tool",
                    "name": name,
                    "label": label,
                    "description": description,
                    "api_names": api_names,
                    "risk": risk,
                    "confidence": min(100, score),
                    "already_selected": name in selected_comfort_tool_set,
                    "reason": self._create_action_suggestion_reason(label, risk),
                }
            )

        for mcp_tool in mcp_tools or []:
            name = str(mcp_tool.get("name") or "")
            description = str(mcp_tool.get("description") or "")
            if not name:
                continue

            score = self._score_action_suggestion(prompt_text, prompt_tokens, [name, description])
            if score <= 0:
                continue

            candidates.append(
                {
                    "source": "mcp_tool",
                    "name": name,
                    "label": name,
                    "description": description,
                    "api_names": [],
                    "risk": "medium",
                    "confidence": min(100, score),
                    "already_selected": False,
                    "reason": f"{name} is an MCP tool candidate. Add it through an MCP tool group before the bot can use it.",
                }
            )

        for mcp_tool_group in mcp_tool_groups or []:
            name = str(mcp_tool_group.get("name") or "")
            description = str(mcp_tool_group.get("description") or "")
            tool_names = [str(tool_name) for tool_name in mcp_tool_group.get("tools", [])]
            if not name or not tool_names:
                continue

            score = self._score_action_suggestion(prompt_text, prompt_tokens, [name, description, *tool_names])
            if score <= 0:
                continue

            candidates.append(
                {
                    "source": "mcp_tool_group",
                    "name": name,
                    "label": name,
                    "description": description,
                    "api_names": [],
                    "risk": "medium",
                    "confidence": min(100, score),
                    "already_selected": False,
                    "reason": f"{name} is an active MCP tool group candidate. Review its tools before enabling bot use.",
                }
            )

        for api_name, api_schema in api_schemas.items():
            description = str(api_schema.get("description") or "")
            permission = self._normalize_api_permission(api_schema.get("permission"))
            risk = ACTION_SUGGESTION_RISK_BY_PERMISSION.get(permission, "medium")
            score = self._score_action_suggestion(prompt_text, prompt_tokens, [api_name, description])
            if score <= 0:
                continue

            candidates.append(
                {
                    "source": "api",
                    "name": api_name,
                    "label": api_name,
                    "description": description,
                    "api_names": [api_name],
                    "risk": risk,
                    "confidence": min(100, score),
                    "already_selected": api_name in selected_api_set,
                    "reason": self._create_action_suggestion_reason(api_name, risk),
                }
            )

        candidates.sort(
            key=lambda candidate: (
                -int(candidate["confidence"]),
                0 if candidate["source"] == "comfort_tool" else 1,
                str(candidate["name"]),
            )
        )
        return candidates[: max(limit, 0)]

    def create_bot_draft(
        self,
        instruction: str,
        api_schemas: Mapping[str, Mapping[str, Any]],
        comfort_tools: Sequence[dict[str, Any]],
        mcp_tools: Sequence[dict[str, Any]] | None = None,
        mcp_tool_groups: Sequence[dict[str, Any]] | None = None,
        selected_api_names: Sequence[str] | None = None,
        selected_comfort_tool_names: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        prompt = instruction.strip()
        suggestions = self.suggest_action_candidates(
            prompt,
            api_schemas,
            comfort_tools,
            mcp_tools=mcp_tools,
            mcp_tool_groups=mcp_tool_groups,
            selected_api_names=selected_api_names,
            selected_comfort_tool_names=selected_comfort_tool_names,
            limit=6,
        )
        bot_name = self._create_draft_bot_name(prompt)
        return {
            "bot_name": bot_name,
            "bot_uname": self._create_draft_bot_uname(bot_name),
            "value_patch": {
                "system_prompt": prompt,
            },
            "suggestions": suggestions,
        }

    def _score_action_suggestion(
        self,
        prompt_text: str,
        prompt_tokens: set[str],
        candidate_texts: Sequence[str],
    ) -> int:
        candidate_text = " ".join(candidate_texts).lower()
        candidate_tokens = self._tokenize_action_suggestion_text(candidate_text)
        token_score = len(prompt_tokens.intersection(candidate_tokens)) * 16
        direct_score = sum(20 for text in candidate_texts if text and text.lower() in prompt_text.lower())
        return token_score + direct_score

    def _tokenize_action_suggestion_text(self, value: str) -> set[str]:
        tokens = re.findall(r"[a-zA-Z0-9_]+", value.lower())
        return {token for token in tokens if len(token) > 1}

    def _normalize_api_permission(self, permission: Any) -> str:
        if hasattr(permission, "value"):
            permission = permission.value
        return str(permission or "read").lower()

    def _get_highest_action_risk(self, permissions: Sequence[str]) -> str:
        if "delete" in permissions:
            return "high"
        if any(permission in {"create", "edit"} for permission in permissions):
            return "medium"
        return "low"

    def _create_action_suggestion_reason(self, label: str, risk: str) -> str:
        if risk == "high":
            return f"{label} may change or remove data. Review before applying."
        if risk == "medium":
            return f"{label} can perform changes requested by the prompt."
        return f"{label} can gather context requested by the prompt."

    def _create_draft_bot_name(self, instruction: str) -> str:
        first_line = next((line.strip() for line in instruction.splitlines() if line.strip()), "")
        if not first_line:
            return "New assistant"
        return first_line[:48].rstrip(" .,:;")

    def _create_draft_bot_uname(self, bot_name: str) -> str:
        base_uname = re.sub(r"[^a-z0-9]+", "-", bot_name.lower()).strip("-")
        if not base_uname:
            base_uname = "new-assistant"

        candidate = base_uname[:48].strip("-") or "new-assistant"
        index = 2
        while InfraHelper.get_by(Bot, "bot_uname", candidate):
            suffix = f"-{index}"
            candidate = f"{base_uname[: 48 - len(suffix)].strip('-')}{suffix}"
            index += 1

        return candidate

    def merge_generated_bot_draft(
        self,
        fallback_draft: dict[str, Any],
        generated_draft: dict[str, Any] | None,
        _api_schemas: Mapping[str, Mapping[str, Any]],
        _comfort_tools: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(generated_draft, dict):
            return fallback_draft

        draft = {
            **fallback_draft,
            "value_patch": dict(fallback_draft.get("value_patch") or {}),
            "suggestions": list(fallback_draft.get("suggestions") or []),
        }
        generated_name = str(generated_draft.get("bot_name") or "").strip()
        if generated_name:
            draft["bot_name"] = generated_name[:48].rstrip(" .,:;")
            draft["bot_uname"] = self._create_draft_bot_uname(str(draft["bot_name"]))

        generated_value = generated_draft.get("value_patch")
        if not isinstance(generated_value, dict):
            return draft

        patch = draft["value_patch"]
        system_prompt = str(generated_value.get("system_prompt") or "").strip()
        if system_prompt:
            patch["system_prompt"] = system_prompt

        return draft

    def generate_api_key(self) -> str:
        api_key = f"sk-{generate_random_string(53)}"
        while True:
            is_existed = InfraHelper.get_by(Bot, "api_key", api_key)
            if not is_existed:
                break
            api_key = f"sk-{generate_random_string(53)}"
        return api_key

    def generate_copied_bot_uname(self, bot_uname: str) -> str:
        base_uname = bot_uname
        candidate = f"{base_uname}-copy"
        index = 2

        while InfraHelper.get_by(Bot, "bot_uname", candidate):
            candidate = f"{base_uname}-copy-{index}"
            index += 1

        return candidate

    def copy_default_scope_branches(self, source_bot: Bot, copied_bot: Bot) -> None:
        source_branches = InfraHelper.get_all_by(BotDefaultScopeBranch, "bot_id", source_bot.id)

        for source_branch in source_branches:
            copied_branch = BotDefaultScopeBranch(bot_id=copied_bot.id, name=source_branch.name)
            self.repo.bot_default_scope_branch.insert(copied_branch)

            for target_table in AVAILABLE_BOT_TARGET_TABLES:
                default_scope_model = BotHelper.get_default_scope_model_class(target_table)
                default_scope_repo = self.get_default_scope_repo(target_table)
                if not default_scope_model or not default_scope_repo:
                    continue

                source_default_scopes = InfraHelper.get_all_by(
                    default_scope_model, "bot_default_scope_branch_id", source_branch.id
                )
                if not source_default_scopes:
                    continue

                copied_default_scope = default_scope_model(
                    bot_default_scope_branch_id=copied_branch.id,
                    conditions=[*source_default_scopes[0].conditions],
                )
                default_scope_repo.insert(copied_default_scope)

            BotPublisher.default_scope_branch_created(copied_branch)

    def get_default_scope_repo(self, target_table: str):
        if target_table == Project.__tablename__:
            return self.repo.project_bot_default_scope
        if target_table == ProjectColumn.__tablename__:
            return self.repo.project_column_bot_default_scope
        if target_table == Card.__tablename__:
            return self.repo.card_bot_default_scope
        return None

    def filter_valid_ip_whitelist(self, ip_whitelist: list[str]) -> list[str]:
        valid_ip_whitelist = []
        if ALLOWED_ALL_IPS in ip_whitelist:
            valid_ip_whitelist.append(ALLOWED_ALL_IPS)
        else:
            for ip in ip_whitelist:
                if not is_valid_ipv4_address_or_range(ip):
                    continue
                if ip.endswith("/24"):
                    ip = make_valid_ipv4_range(ip)
                valid_ip_whitelist.append(ip)
        return valid_ip_whitelist
