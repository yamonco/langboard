import { TRoleAllGranted } from "@/core/models/roles/base";

export enum EAction {
    UserRead = "user_read",
    UserCreate = "user_create",
    UserUpdate = "user_update",
    UserDelete = "user_delete",
    BotRead = "bot_read",
    BotCreate = "bot_create",
    BotUpdate = "bot_update",
    BotDelete = "bot_delete",
    InternalBotRead = "internal_bot_read",
    InternalBotCreate = "internal_bot_create",
    InternalBotUpdate = "internal_bot_update",
    InternalBotDelete = "internal_bot_delete",
    GlobalRelationshipRead = "global_relationship_read",
    GlobalRelationshipCreate = "global_relationship_create",
    GlobalRelationshipUpdate = "global_relationship_update",
    GlobalRelationshipDelete = "global_relationship_delete",
    WebhookRead = "webhook_read",
    WebhookCreate = "webhook_create",
    WebhookUpdate = "webhook_update",
    WebhookDelete = "webhook_delete",
    NotificationScheduleRead = "notification_schedule_read",
    NotificationScheduleCreate = "notification_schedule_create",
    NotificationScheduleUpdate = "notification_schedule_update",
    NotificationScheduleDelete = "notification_schedule_delete",
    ApiComfortToolRead = "api_comfort_tool_read",
    ApiComfortToolCreate = "api_comfort_tool_create",
    ApiComfortToolUpdate = "api_comfort_tool_update",
    ApiComfortToolDelete = "api_comfort_tool_delete",
    OllamaRead = "ollama_read",
}

export type TActions = EAction | keyof typeof EAction | TRoleAllGranted;

export const CATEGORIZED_MAP = {
    User: [EAction.UserRead, EAction.UserCreate, EAction.UserUpdate, EAction.UserDelete],
    Bot: [EAction.BotRead, EAction.BotCreate, EAction.BotUpdate, EAction.BotDelete],
    InternalBot: [EAction.InternalBotRead, EAction.InternalBotCreate, EAction.InternalBotUpdate, EAction.InternalBotDelete],
    GlobalRelationship: [
        EAction.GlobalRelationshipRead,
        EAction.GlobalRelationshipCreate,
        EAction.GlobalRelationshipUpdate,
        EAction.GlobalRelationshipDelete,
    ],
    Webhook: [EAction.WebhookRead, EAction.WebhookCreate, EAction.WebhookUpdate, EAction.WebhookDelete],
    NotificationSchedule: [
        EAction.NotificationScheduleRead,
        EAction.NotificationScheduleCreate,
        EAction.NotificationScheduleUpdate,
        EAction.NotificationScheduleDelete,
    ],
    ApiComfortTool: [EAction.ApiComfortToolRead, EAction.ApiComfortToolCreate, EAction.ApiComfortToolUpdate, EAction.ApiComfortToolDelete],
    Ollama: [EAction.OllamaRead],
};
