from typing import Any, Literal, Sequence
from uuid import uuid4
from ....ai import BotScheduleHelper
from ....core.domain import BaseDomainService
from ....core.domain.BaseDomainService import TMutableValidatorMap
from ....core.security import KeyVault
from ....core.types.ParamTypes import TGlobalCardRelationshipTypeParam
from ....core.utils.Converter import convert_python_data
from ....helpers import InfraHelper, ModelHelper
from ....publishers import AppSettingPublisher
from ....tasks.webhooks.utils import validate_webhook_events, validate_webhook_url
from ...models import ApiComfortTool, GlobalCardRelationshipType, NotificationScheduleRule, WebhookSetting
from ...models.ApiComfortTool import ApiComfortToolMap
from ...models.BaseNotificationScheduleModel import BaseNotificationScheduleModel


CRON_COMMENT = "notification-schedule"
CRON_COMMAND = "/app/scripts/run_notification_cron.sh"


class AppSettingService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "app_setting"

    def get_api_global_relationship_list(self) -> list[dict[str, Any]]:
        global_relationships = InfraHelper.get_all(GlobalCardRelationshipType)
        return [relationship.api_response() for relationship in global_relationships]

    def create_global_relationship(
        self, parent_name: str, child_name: str, description: str = ""
    ) -> GlobalCardRelationshipType:
        global_relationship = GlobalCardRelationshipType(
            parent_name=parent_name,
            child_name=child_name,
            description=description,
        )

        self.repo.global_card_relationship_type.insert(global_relationship)

        model = {"global_relationships": [global_relationship.api_response()]}
        AppSettingPublisher.global_relationship_created(model)

        return global_relationship

    def import_global_relationship(
        self, relationships: list[tuple[str, str, str | None]]
    ) -> list[GlobalCardRelationshipType]:
        global_relationships: list[GlobalCardRelationshipType] = []
        for parent_name, child_name, description in relationships:
            global_relationship = GlobalCardRelationshipType(
                parent_name=parent_name,
                child_name=child_name,
                description=description or "",
            )
            global_relationships.append(global_relationship)

        self.repo.global_card_relationship_type.insert(global_relationships)

        model = {"global_relationships": [gr.api_response() for gr in global_relationships]}
        AppSettingPublisher.global_relationship_created(model)

        return global_relationships

    def update_global_relationship(
        self, global_relationship: TGlobalCardRelationshipTypeParam | None, form: dict
    ) -> bool | tuple[GlobalCardRelationshipType, dict[str, Any]] | None:
        global_relationship = InfraHelper.get_by_id_like(GlobalCardRelationshipType, global_relationship)
        if not global_relationship:
            return None
        validators: TMutableValidatorMap = {
            "parent_name": "default",
            "child_name": "default",
            "description": "default",
        }

        old_record = self.apply_mutates(global_relationship, form, validators)
        if not old_record:
            return True

        self.repo.global_card_relationship_type.update(global_relationship)

        model = {}
        for key in form:
            if key not in validators or key not in old_record:
                continue
            model[key] = convert_python_data(getattr(global_relationship, key))

        AppSettingPublisher.global_relationship_updated(global_relationship.get_uid(), model)

        return global_relationship, model

    def delete_global_relationship(self, global_relationship: TGlobalCardRelationshipTypeParam | None) -> bool:
        global_relationship = InfraHelper.get_by_id_like(GlobalCardRelationshipType, global_relationship)
        if not global_relationship:
            return False

        self.repo.global_card_relationship_type.delete(global_relationship)

        AppSettingPublisher.global_relationship_deleted(global_relationship.get_uid())

        return True

    def delete_selected_global_relationships(self, relationships: Sequence[TGlobalCardRelationshipTypeParam]) -> bool:
        self.repo.global_card_relationship_type.delete(relationships)

        if isinstance(relationships, str):
            relationships = [relationships]
        uids = [InfraHelper.convert_uid(r) for r in relationships]
        AppSettingPublisher.selected_global_relationships_deleted(uids)

        return True

    def get_api_webhook_setting_list(self) -> list[dict[str, Any]]:
        webhook_settings = InfraHelper.get_all(WebhookSetting)
        return [setting.api_response() for setting in webhook_settings]

    def get_api_webhook_setting(self, webhook_setting_uid: str) -> dict[str, Any] | None:
        setting = InfraHelper.get_by_id_like(WebhookSetting, webhook_setting_uid)
        if not setting:
            return None
        return setting.api_response()

    def create_webhook_setting(
        self, name: str, url: str, events: list[str] | None = None
    ) -> tuple[WebhookSetting, str]:
        """Create a webhook and return its one-time signing secret."""

        events = validate_webhook_events(events)
        secret_id = str(uuid4())
        secret = KeyVault.create_key(secret_id)
        webhook_setting = WebhookSetting(
            name=name,
            url=validate_webhook_url(url),
            secret_id=secret_id,
            events=events,
        )
        try:
            self.repo.webhook_setting.insert(webhook_setting)
        except Exception:
            KeyVault.delete_key(secret_id)
            raise

        AppSettingPublisher.webhook_setting_created(webhook_setting)

        return webhook_setting, secret

    def update_webhook_setting(
        self,
        webhook_setting_uid: str,
        name: str | None = None,
        url: str | None = None,
        events: list[str] | None = None,
        *,
        replace_events: bool = False,
    ) -> WebhookSetting | None:
        """Update a webhook, distinguishing omitted events from explicit null."""

        setting = InfraHelper.get_by_id_like(WebhookSetting, webhook_setting_uid)
        if not setting:
            return None

        if name is not None:
            setting.name = name
        if url is not None:
            setting.url = validate_webhook_url(url)
        if replace_events or events is not None:
            setting.events = validate_webhook_events(events)

        model = {}
        if name is not None:
            model["name"] = setting.name
        if url is not None:
            model["url"] = setting.url
        if replace_events or events is not None:
            model["events"] = setting.events

        if not setting.has_changes():
            return setting

        self.repo.webhook_setting.update(setting)

        AppSettingPublisher.webhook_setting_updated(setting.get_uid(), model)

        return setting

    def delete_webhook_setting(self, webhook_setting_uid: str) -> bool:
        setting = InfraHelper.get_by_id_like(WebhookSetting, webhook_setting_uid)
        if not setting:
            return False

        secret_id = setting.secret_id
        self.repo.webhook_setting.delete(setting)
        if secret_id:
            KeyVault.delete_key(secret_id)

        AppSettingPublisher.webhook_setting_deleted(setting.get_uid())

        return True

    def delete_selected_webhook_settings(self, webhook_setting_uids: Sequence[str]) -> bool:
        if isinstance(webhook_setting_uids, str):
            webhook_setting_uids = [webhook_setting_uids]
        secret_ids: list[str] = []
        for webhook_setting_uid in webhook_setting_uids:
            setting = InfraHelper.get_by_id_like(WebhookSetting, webhook_setting_uid)
            if setting and setting.secret_id:
                secret_ids.append(setting.secret_id)
        self.repo.webhook_setting.delete(webhook_setting_uids)
        for secret_id in secret_ids:
            KeyVault.delete_key(secret_id)

        uids = [InfraHelper.convert_uid(r) for r in webhook_setting_uids]
        AppSettingPublisher.selected_webhook_settings_deleted(uids)

        return True

    def get_api_comfort_tool_list(self) -> dict[str, ApiComfortToolMap]:
        return {
            **ApiComfortTool.DEFAULT_TOOLS,
            **{
                comfort_tool.name: comfort_tool.to_api_comfort_tool_map()
                for comfort_tool in self.__get_custom_api_comfort_tools()
            },
        }

    def get_api_comfort_tool_response_list(self) -> list[dict[str, Any]]:
        return [
            *[
                ApiComfortTool.create_default_api_response(name, comfort_tool)
                for name, comfort_tool in ApiComfortTool.DEFAULT_TOOLS.items()
            ],
            *[comfort_tool.api_response() for comfort_tool in self.__get_custom_api_comfort_tools()],
        ]

    def get_api_comfort_tool(self, name: str) -> ApiComfortTool | None:
        return self.__get_custom_api_comfort_tool(name)

    def create_api_comfort_tool(
        self,
        name: str,
        *,
        label: str,
        description: str,
        api_names: list[str],
        query: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
        api_queries: dict[str, dict[str, Any]] | None = None,
        api_forms: dict[str, dict[str, Any]] | None = None,
    ) -> ApiComfortTool:
        comfort_tool_name = self.__normalize_api_comfort_tool_name(name, label)
        if comfort_tool_name in ApiComfortTool.DEFAULT_TOOLS or self.__get_custom_api_comfort_tool(comfort_tool_name):
            raise ValueError("Comfort tool name already exists.")

        comfort_tool = ApiComfortTool(
            name=comfort_tool_name,
            label=label.strip(),
            description=description.strip(),
            api_names=list(dict.fromkeys(api_names)),
            query=query or {},
            form=form or {},
            api_queries=api_queries or {},
            api_forms=api_forms or {},
            is_default=False,
        )
        self.repo.api_comfort_tool.insert(comfort_tool)
        AppSettingPublisher.api_comfort_tool_created(comfort_tool)
        return comfort_tool

    def update_api_comfort_tool(
        self,
        name: str,
        *,
        next_name: str,
        label: str,
        description: str,
        api_names: list[str],
        query: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
        api_queries: dict[str, dict[str, Any]] | None = None,
        api_forms: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[str, ApiComfortTool] | None:
        comfort_tool = self.get_api_comfort_tool(name)
        if not comfort_tool:
            return None

        next_comfort_tool_name = self.__normalize_api_comfort_tool_name(next_name, label)
        if next_comfort_tool_name != name and (
            next_comfort_tool_name in ApiComfortTool.DEFAULT_TOOLS
            or self.__get_custom_api_comfort_tool(next_comfort_tool_name)
        ):
            raise ValueError("Comfort tool name already exists.")

        old_name = comfort_tool.name
        comfort_tool.name = next_comfort_tool_name
        comfort_tool.label = label.strip()
        comfort_tool.description = description.strip()
        comfort_tool.api_names = list(dict.fromkeys(api_names))
        comfort_tool.query = query or {}
        comfort_tool.form = form or {}
        comfort_tool.api_queries = api_queries or {}
        comfort_tool.api_forms = api_forms or {}
        self.repo.api_comfort_tool.update(comfort_tool)

        if old_name != comfort_tool.name:
            AppSettingPublisher.api_comfort_tool_deleted(comfort_tool.get_uid(), old_name)
            AppSettingPublisher.api_comfort_tool_created(comfort_tool)
        else:
            AppSettingPublisher.api_comfort_tool_updated(comfort_tool)
        return comfort_tool.name, comfort_tool

    def delete_api_comfort_tool(self, name: str) -> bool:
        comfort_tool = self.get_api_comfort_tool(name)
        if not comfort_tool:
            return False

        deleted_name = comfort_tool.name
        deleted_uid = comfort_tool.get_uid()
        self.repo.api_comfort_tool.delete(comfort_tool)
        AppSettingPublisher.api_comfort_tool_deleted(deleted_uid, deleted_name)
        return True

    def get_api_notification_schedule_rules(self) -> list[dict[str, Any]]:
        return [rule.api_response() for rule in self.repo.notification_schedule_rule.get_all()]

    def get_notification_schedule_rule(self, rule_uid: str) -> NotificationScheduleRule | None:
        return InfraHelper.get_by_id_like(NotificationScheduleRule, rule_uid)

    def create_notification_schedule_rule(self, form: dict[str, Any]) -> NotificationScheduleRule:
        rules = self.repo.notification_schedule_rule.get_all()
        display_order = max([rule.display_order for rule in rules], default=-1) + 1
        interval_str = BotScheduleHelper.utils.convert_valid_interval_str(str(form.get("interval_str") or "0 9 * * *"))
        timezone = form.get("timezone", "UTC")
        interval_str = BotScheduleHelper.utils.adjust_interval_for_utc(interval_str, timezone)
        rule = NotificationScheduleRule(
            name=str(form.get("name") or ""),
            is_enabled=bool(form.get("is_enabled")),
            interval_str=interval_str,
            target=str(form.get("target") or ""),
            field=str(form.get("field") or ""),
            operator=str(form.get("operator") or ""),
            value=form.get("value"),
            recipients=[str(recipient) for recipient in form.get("recipients") or [] if str(recipient)],
            repeat_after_hours=max(int(form.get("repeat_after_hours") or 24), 1),
            display_order=display_order,
        )

        self.repo.notification_schedule_rule.insert(rule)
        if rule.is_enabled:
            cron = BotScheduleHelper.utils.get_cron()
            has_changed = self.__create_notification_schedule_cron_job(cron, rule.interval_str)
            if has_changed:
                BotScheduleHelper.utils.save_cron(cron)
        AppSettingPublisher.notification_schedule_rule_created(rule)
        return rule

    def update_notification_schedule_rule(
        self,
        rule_uid: str,
        form: dict[str, Any],
    ) -> NotificationScheduleRule | Literal[True] | None:
        rule = InfraHelper.get_by_id_like(NotificationScheduleRule, rule_uid)
        if not rule:
            return None

        old_is_enabled = rule.is_enabled
        old_interval_str = rule.interval_str

        timezone = form.pop("timezone", "UTC")
        if "interval_str" in form and form["interval_str"] is not None:
            interval_str = BotScheduleHelper.utils.convert_valid_interval_str(str(form["interval_str"]))
            form["interval_str"] = BotScheduleHelper.utils.adjust_interval_for_utc(interval_str, timezone)
        if "recipients" in form and form["recipients"] is not None:
            form["recipients"] = [str(recipient) for recipient in form.get("recipients") or [] if str(recipient)]
        if "repeat_after_hours" in form and form["repeat_after_hours"] is not None:
            form["repeat_after_hours"] = max(int(form.get("repeat_after_hours") or 24), 1)

        validators: TMutableValidatorMap = {
            "name": "not_empty",
            "is_enabled": "default",
            "interval_str": "not_empty",
            "target": "not_empty",
            "field": "not_empty",
            "operator": "not_empty",
            "value": "nullable",
            "recipients": "default",
            "repeat_after_hours": "default",
        }

        old_record = self.apply_mutates(rule, form, validators)
        if not old_record:
            return True

        self.repo.notification_schedule_rule.update(rule)
        new_interval_str = rule.interval_str
        cron = None
        has_cron_changed = False

        if rule.is_enabled:
            cron = BotScheduleHelper.utils.get_cron()
            has_cron_changed = self.__create_notification_schedule_cron_job(cron, new_interval_str)

        if old_is_enabled and (not rule.is_enabled or old_interval_str != new_interval_str):
            if not self.__has_notification_schedule_interval(old_interval_str):
                if not cron:
                    cron = BotScheduleHelper.utils.get_cron()
                BotScheduleHelper.utils.remove_job(
                    cron, self.__get_notification_schedule_cron_comment(old_interval_str)
                )
                has_cron_changed = True

        if cron and has_cron_changed:
            BotScheduleHelper.utils.save_cron(cron)

        AppSettingPublisher.notification_schedule_rule_updated(
            rule.get_uid(), {"notification_rule": rule.api_response()}
        )
        return rule

    def delete_notification_schedule_rule(self, rule_uid: str) -> bool:
        rule = InfraHelper.get_by_id_like(NotificationScheduleRule, rule_uid)
        if not rule:
            return False

        deleted_rule_uid = rule.get_uid()
        old_is_enabled = rule.is_enabled
        old_interval_str = rule.interval_str

        self.repo.notification_schedule_rule.delete([deleted_rule_uid])
        if old_is_enabled and not self.__has_notification_schedule_interval(old_interval_str):
            cron = BotScheduleHelper.utils.get_cron()
            BotScheduleHelper.utils.remove_job(cron, self.__get_notification_schedule_cron_comment(old_interval_str))
            BotScheduleHelper.utils.save_cron(cron)
        AppSettingPublisher.notification_schedule_rule_deleted(deleted_rule_uid)
        return True

    def delete_selected_notification_schedule_rules(self, rule_uids: Sequence[str]) -> bool:
        rule_uid_set = {InfraHelper.convert_uid(rule_uid) for rule_uid in rule_uids}
        existing_rules = [
            rule for rule in self.repo.notification_schedule_rule.get_all() if rule.get_uid() in rule_uid_set
        ]
        existing_rule_uids = {rule.get_uid() for rule in existing_rules}
        if not existing_rule_uids:
            return False

        old_interval_strs = {rule.interval_str for rule in existing_rules if rule.is_enabled}

        self.repo.notification_schedule_rule.delete(list(existing_rule_uids))
        cron = None
        has_cron_changed = False
        for interval_str in old_interval_strs:
            if self.__has_notification_schedule_interval(interval_str):
                continue
            if not cron:
                cron = BotScheduleHelper.utils.get_cron()
            BotScheduleHelper.utils.remove_job(cron, self.__get_notification_schedule_cron_comment(interval_str))
            has_cron_changed = True

        if cron and has_cron_changed:
            BotScheduleHelper.utils.save_cron(cron)

        AppSettingPublisher.selected_notification_schedule_rules_deleted(list(existing_rule_uids))
        return True

    def get_notification_schedule_rule_schema(self) -> dict[str, Any]:
        target_models: list[type[BaseNotificationScheduleModel]] = ModelHelper.get_models_by_base_class(
            BaseNotificationScheduleModel
        )
        values: dict[str, list[Any]] = {}
        for target_model in target_models:
            target = str(target_model.__tablename__)
            for field, field_values in target_model.get_notification_schedule_rule_field_values().items():
                values[f"{target}.{field}"] = field_values

        return {
            "targets": [
                {
                    "key": str(target_model.__tablename__),
                    "fields": target_model.get_notification_schedule_rule_fields(),
                    "recipients": target_model.get_notification_schedule_rule_recipients(),
                }
                for target_model in target_models
            ],
            "operators": {
                BaseNotificationScheduleModel.OPERATOR_WITHIN_NEXT_DAYS: {"value_type": "number", "min": 0},
                BaseNotificationScheduleModel.OPERATOR_OVERDUE: {"value_type": "none"},
                BaseNotificationScheduleModel.OPERATOR_OLDER_THAN_DAYS: {"value_type": "number", "min": 0},
                BaseNotificationScheduleModel.OPERATOR_GREATER_THAN_SECONDS: {"value_type": "number", "min": 0},
                BaseNotificationScheduleModel.OPERATOR_EQUALS: {"value_type": "dynamic"},
                BaseNotificationScheduleModel.OPERATOR_IS_EMPTY: {"value_type": "none"},
                BaseNotificationScheduleModel.OPERATOR_IS_NOT_EMPTY: {"value_type": "none"},
            },
            "values": values,
        }

    def __get_custom_api_comfort_tools(self) -> list[ApiComfortTool]:
        return [comfort_tool for comfort_tool in self.repo.api_comfort_tool.get_all() if not comfort_tool.is_default]

    def __get_custom_api_comfort_tool(self, name: str) -> ApiComfortTool | None:
        comfort_tool = self.repo.api_comfort_tool.get_by_name(name)
        if not comfort_tool or comfort_tool.is_default:
            return None
        return comfort_tool

    def __normalize_api_comfort_tool_name(self, name: str, label: str) -> str:
        if name.strip() and not ApiComfortTool.is_valid_name(name.strip()):
            raise ValueError("Comfort tool name can only contain letters, numbers, hyphens, and underscores.")

        comfort_tool_name = ApiComfortTool.normalize_name(name, label)
        if not comfort_tool_name:
            raise ValueError("Comfort tool name is required.")
        return comfort_tool_name

    def __has_notification_schedule_interval(self, interval_str: str) -> bool:
        return any(rule.interval_str == interval_str for rule in self.repo.notification_schedule_rule.get_enabled())

    def __create_notification_schedule_cron_job(self, cron: Any, interval_str: str) -> bool:
        comment = self.__get_notification_schedule_cron_comment(interval_str)
        command = self.__get_notification_schedule_cron_command(interval_str)
        existing_jobs = list(cron.find_comment(comment))
        matching_jobs = [
            job for job in existing_jobs if str(job.command) == command and str(job.slices) == interval_str
        ]
        if len(existing_jobs) == 1 and matching_jobs:
            return False

        if existing_jobs:
            BotScheduleHelper.utils.remove_job(cron, comment)

        return BotScheduleHelper.utils.create_job(cron, interval_str, command, comment)

    def __get_notification_schedule_cron_comment(self, rule_or_interval: NotificationScheduleRule | str) -> str:
        if isinstance(rule_or_interval, NotificationScheduleRule):
            interval_str = rule_or_interval.interval_str
        else:
            interval_str = rule_or_interval
        return f"{CRON_COMMENT}:{interval_str}"

    def __get_notification_schedule_cron_command(self, rule_or_interval: NotificationScheduleRule | str) -> str:
        if isinstance(rule_or_interval, NotificationScheduleRule):
            interval_str = rule_or_interval.interval_str
        else:
            interval_str = rule_or_interval
        return f"{CRON_COMMAND} '{interval_str}'"
