from enum import Enum
from .bases import BaseRoleModel


class SettingRoleAction(Enum):
    # User Management
    UserRead = "user_read"
    UserCreate = "user_create"
    UserUpdate = "user_update"
    UserDelete = "user_delete"

    # Bot Management
    BotRead = "bot_read"
    BotCreate = "bot_create"
    BotUpdate = "bot_update"
    BotDelete = "bot_delete"

    # Internal Bot Management
    InternalBotRead = "internal_bot_read"
    InternalBotCreate = "internal_bot_create"
    InternalBotUpdate = "internal_bot_update"
    InternalBotDelete = "internal_bot_delete"

    # Global Relationship Management
    GlobalRelationshipRead = "global_relationship_read"
    GlobalRelationshipCreate = "global_relationship_create"
    GlobalRelationshipUpdate = "global_relationship_update"
    GlobalRelationshipDelete = "global_relationship_delete"

    # Webhook Management
    WebhookRead = "webhook_read"
    WebhookCreate = "webhook_create"
    WebhookUpdate = "webhook_update"
    WebhookDelete = "webhook_delete"

    # Notification Schedule Management
    NotificationScheduleRead = "notification_schedule_read"
    NotificationScheduleCreate = "notification_schedule_create"
    NotificationScheduleUpdate = "notification_schedule_update"
    NotificationScheduleDelete = "notification_schedule_delete"

    # API Comfort Tool Management
    ApiComfortToolRead = "api_comfort_tool_read"
    ApiComfortToolCreate = "api_comfort_tool_create"
    ApiComfortToolUpdate = "api_comfort_tool_update"
    ApiComfortToolDelete = "api_comfort_tool_delete"

    # Ollama Management
    OllamaRead = "ollama_read"


class SettingRoleCategory(Enum):
    User = "user"
    Bot = "bot"
    InternalBot = "internal_bot"
    GlobalRelationship = "global_relationship"
    Webhook = "webhook"
    NotificationSchedule = "notification_schedule"
    ApiComfortTool = "api_comfort_tool"
    Ollama = "ollama"


class SettingRole(BaseRoleModel, table=True):
    @staticmethod
    def get_all_actions() -> list[Enum]:
        return list(SettingRoleAction._member_map_.values())

    @staticmethod
    def get_default_actions() -> list[Enum]:
        # Default setting role has read-only permissions
        return [
            SettingRoleAction.UserRead,
            SettingRoleAction.BotRead,
            SettingRoleAction.InternalBotRead,
            SettingRoleAction.GlobalRelationshipRead,
            SettingRoleAction.WebhookRead,
            SettingRoleAction.NotificationScheduleRead,
            SettingRoleAction.ApiComfortToolRead,
            SettingRoleAction.OllamaRead,
        ]

    def has_category_permission(self, category: SettingRoleCategory) -> bool:
        category_prefix = f"{category.value}_"
        for action in self.actions:
            action_value = action.value if isinstance(action, Enum) else action
            if action_value.startswith(category_prefix):
                return True
        return False
