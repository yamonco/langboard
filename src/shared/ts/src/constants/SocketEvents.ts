const SERVER = {
    DASHBOARD: {
        PROJECT: {
            ASSIGNED_USERS_UPDATED: "dashboard:project:assigned-users:updated:{uid}",
            DELETED: "dashboard:project:deleted:{uid}",
            COLUMN: {
                CREATED: "dashboard:project:column:created:{uid}",
                NAME_CHANGED: "dashboard:project:column:name:changed:{uid}",
                DESCRIPTION_CHANGED: "dashboard:project:column:description:changed:{uid}",
                ORDER_CHANGED: "dashboard:project:column:order:changed:{uid}",
                DELETED: "dashboard:project:column:deleted:{uid}",
            },
        },
        CARD: {
            CREATED: "dashboard:card:created:{uid}",
            TITLE_CHANGED: "dashboard:card:title:changed:{uid}",
            ORDER_CHANGED: "dashboard:card:order:changed:{uid}",
            DELETED: "dashboard:card:deleted:{uid}",
        },
        CHECKITEM: {
            TITLE_CHANGED: "dashboard:checkitem:title:changed:{uid}",
            DEADLINE_CHANGED: "dashboard:checkitem:deadline:changed:{uid}",
            STATUS_CHANGED: "dashboard:checkitem:status:changed:{uid}",
            CHECKED_CHANGED: "dashboard:checkitem:checked:changed:{uid}",
            DELETED: "dashboard:checkitem:deleted:{uid}",
        },
    },
    BOARD: {
        ASSIGNED_USERS_UPDATED: "board:assigned-users:updated:{uid}",
        USER_ROLES_UPDATED: "board:roles:user:updated:{uid}",
        DETAILS_CHANGED: "board:details:changed:{uid}",
        DELETED: "board:deleted:{uid}",
        CHAT: {
            IS_AVAILABLE: "board:chat:available",
            SESSION: "board:chat:session",
            SENT: "board:chat:sent",
            STREAM: "board:chat:stream",
            TEMPLATE: {
                CREATED: "board:chat:template:created:{uid}",
                UPDATED: "board:chat:template:updated:{uid}",
                DELETED: "board:chat:template:deleted:{uid}",
            },
        },
        GRAPH_APPROVAL: {
            REQUESTED: "board:graph:approval:requested",
            UPDATED: "board:graph:approval:updated",
            DELETED: "board:graph:approval:deleted",
        },
        LABEL: {
            CREATED: "board:label:created:{uid}",
            DETAILS_CHANGED: "board:label:details:changed:{uid}",
            ORDER_CHANGED: "board:label:order:changed:{uid}",
            DELETED: "board:label:deleted:{uid}",
        },
        COLUMN: {
            CREATED: "board:column:created:{uid}",
            NAME_CHANGED: "board:column:name:changed:{uid}",
            DESCRIPTION_CHANGED: "board:column:description:changed:{uid}",
            ORDER_CHANGED: "board:column:order:changed:{uid}",
            DELETED: "board:column:deleted:{uid}",
        },
        CARD: {
            CREATED: "board:card:created:{uid}",
            ORDER_CHANGED: "board:card:order:changed:{uid}",
            DETAILS_CHANGED: "board:card:details:changed:{uid}",
            ASSIGNED_USERS_UPDATED: "board:card:assigned-users:updated:{uid}",
            RELATIONSHIPS_UPDATED: "board:card:relationships:updated:{uid}",
            LABELS_UPDATED: "board:card:labels:updated:{uid}",
            EDITOR_USERS: "board:card:editor:users:{uid}",
            EDITOR_START_EDITING: "board:card:editor:start:{uid}",
            EDITOR_STOP_EDITING: "board:card:editor:stop:{uid}",
            DELETED: "board:card:deleted:{uid}",
            ATTACHMENT: {
                UPLOADED: "board:card:attachment:uploaded:{uid}",
                NAME_CHANGED: "board:card:attachment:name:changed:{uid}",
                ORDER_CHANGED: "board:card:attachment:order:changed",
                DELETED: "board:card:attachment:deleted",
            },
            COMMENT: {
                ADDED: "board:card:comment:added:{uid}",
                UPDATED: "board:card:comment:updated:{uid}",
                DELETED: "board:card:comment:deleted:{uid}",
                REACTED: "board:card:comment:reacted:{uid}",
            },
            CHECKLIST: {
                CREATED: "board:card:checklist:created:{uid}",
                TITLE_CHANGED: "board:card:checklist:title:changed:{uid}",
                ORDER_CHANGED: "board:card:checklist:order:changed:{uid}",
                CHECKED_CHANGED: "board:card:checklist:checked:changed:{uid}",
                DELETED: "board:card:checklist:deleted:{uid}",
            },
            CHECKITEM: {
                CREATED: "board:card:checkitem:created:{uid}",
                TITLE_CHANGED: "board:card:checkitem:title:changed:{uid}",
                DEADLINE_CHANGED: "board:card:checkitem:deadline:changed:{uid}",
                ORDER_CHANGED: "board:card:checkitem:order:changed:{uid}",
                STATUS_CHANGED: "board:card:checkitem:status:changed:{uid}",
                CHECKED_CHANGED: "board:card:checkitem:checked:changed:{uid}",
                CARDIFIED: "board:card:checkitem:cardified:{uid}",
                DELETED: "board:card:checkitem:deleted:{uid}",
            },
        },
        WIKI: {
            CREATED: "board:wiki:created:{uid}",
            EDITOR_USERS: "board:wiki:editor:users:{uid}",
            EDITOR_START_EDITING: "board:wiki:editor:start:{uid}",
            EDITOR_STOP_EDITING: "board:wiki:editor:stop:{uid}",
            DETAILS_CHANGED: "board:wiki:details:changed:{uid}",
            PUBLIC_CHANGED: "board:wiki:public:changed:{uid}",
            ASSIGNEES_UPDATED: "board:wiki:assignees:updated:{uid}",
            ORDER_CHANGED: "board:wiki:order:changed:{uid}",
            DELETED: "board:wiki:deleted:{uid}",
        },
        BOT: {
            STATUS_MAP: "board:bot:status:map",
            STATUS_CHANGED: "board:bot:status:changed:{uid}",
            SCOPE: {
                CREATED: "board:bot:scope:created",
                TRIGGER_CONDITION_TOGGLED: "board:bot:scope:conditions:updated",
                FREEZE_UPDATED: "board:bot:scope:freeze:updated",
                DELETED: "board:bot:scope:deleted",
            },
            SCHEDULE: {
                SCHEDULED: "board:bot:cron:scheduled",
                RESCHEDULED: "board:bot:cron:rescheduled",
                UNSCHEDULED: "board:bot:cron:unscheduled",
            },
            LOG: {
                CREATED: "board:bot:log:created",
                STACK_ADDED: "board:bot:log:stack:added",
            },
        },
        SETTINGS: {
            INTERNAL_BOT: {
                ASSIGNED_BOT_CHANGED: "board:assigned-internal-bot:changed:{uid}",
                SETTINGS_CHANGED: "board:assigned-internal-bot:settings:changed:{uid}",
            },
        },
    },
    METADATA: {
        UPDATED: "metadata:updated:{uid}",
        DELETED: "metadata:deleted:{uid}",
    },
    USER: {
        UPDATED: "user:updated",
        NOTIFIED: "user:notified",
        NOTIFICATION_DELETED: "user:notification:deleted",
        API_KEY_ROLES_UPDATED: "user:api-key-roles:updated:{uid}",
        SETTING_ROLES_UPDATED: "user:setting-roles:updated:{uid}",
        MCP_ROLES_UPDATED: "user:mcp-roles:updated:{uid}",
        PROJECT_ASSIGNED: "user:project:assigned",
        PROJECT_ROLES_UPDATED: "user:project-roles:updated",
        DELETED: "user:deleted:{uid}",
        DEACTIVATED: "user:deactivated:{uid}",
    },
    GLOBALS: {
        BOTS: {
            CREATED: "bot:created",
            UPDATED: "bot:updated:{uid}",
            DELETED: "bot:deleted:{uid}",
            DEFAULT_SCOPE_BRANCH: {
                CREATED: "bot:default-scope-branch:created",
                UPDATED: "bot:default-scope-branch:updated:{uid}",
                DELETED: "bot:default-scope-branch:deleted:{uid}",
            },
        },
        GLOBAL_RELATIONSHIPS: {
            CREATED: "global-relationship:created",
            UPDATED: "global-relationship:updated:{uid}",
            DELETED: "global-relationship:deleted:{uid}",
            SELECTIONS_DELETED: "global-relationship:deleted",
        },
        INTERNAL_BOTS: {
            CREATED: "internal-bot:created",
            UPDATED: "internal-bot:updated",
            DELETED: "internal-bot:deleted",
        },
        TASK_ABORTED: "task:aborted",
    },
    SETTINGS: {
        USERS: {
            CREATED: "settings:user:created",
            UPDATED: "settings:user:updated:{uid}",
            SELECTIONS_DELETED: "user:deleted",
        },
        BOTS: {
            CREATED: "settings:bot:created",
            UPDATED: "settings:bot:updated:{uid}",
            TRIGGER_CONDITION_TOGGLED: "settings:bot:trigger-condition:toggled:{uid}",
        },
        INTERNAL_BOTS: {
            DEFAULT_CHANGED: "settings:internal-bot:default-changed:{uid}",
        },
        OLLAMA: {
            MODEL_COPIED: "settings:ollama:model:copied",
            MODEL_DELETED: "settings:ollama:model:deleted",
            MODEL_PULLING_STATUS: "settings:ollama:model:pull:status",
        },
        MCP_TOOL_GROUP: {
            CREATED: "mcp-tool-group:created",
            UPDATED: "mcp-tool-group:updated:{uid}",
            DELETED: "mcp-tool-group:deleted:{uid}",
            SELECTIONS_DELETED: "mcp-tool-group:deleted",
        },
        WEBHOOKS: {
            CREATED: "settings:webhook:created",
            UPDATED: "settings:webhook:updated:{uid}",
            DELETED: "settings:webhook:deleted:{uid}",
            SELECTIONS_DELETED: "settings:webhook:deleted",
        },
        NOTIFICATION_SCHEDULE: {
            RULE: {
                CREATED: "settings:notification-schedule:rule:created",
                UPDATED: "settings:notification-schedule:rule:updated:{uid}",
                DELETED: "settings:notification-schedule:rule:deleted:{uid}",
                SELECTIONS_DELETED: "settings:notification-schedule:rule:deleted",
            },
        },
        API_COMFORT_TOOL: {
            CREATED: "settings:api-comfort-tool:created",
            UPDATED_ANY: "settings:api-comfort-tool:updated",
            UPDATED: "settings:api-comfort-tool:updated:{uid}",
            DELETED_ANY: "settings:api-comfort-tool:deleted",
            DELETED: "settings:api-comfort-tool:deleted:{uid}",
        },
    },
} as const;

const CLIENT = {
    BOARD: {
        CHAT: {
            IS_AVAILABLE: "board:chat:available",
            SEND: "board:chat:send",
            RESUME: "board:chat:resume",
            CANCEL: "board:chat:cancel",
        },
        WIKI: {
            GET_DETAILS: "board:wiki:details",
        },
        BOT: {
            STATUS_MAP: "board:bot:status:map",
        },
    },
    USER: {
        READ_NOTIFICATION: "user:notification:read",
        READ_ALL_NOTIFICATIONS: "user:notification:read-all",
        DELETE_NOTIFICATION: "user:notification:delete",
        DELETE_ALL_NOTIFICATIONS: "user:notification:delete-all",
    },
    SETTINGS: {
        OLLAMA: {
            COPY_MODEL: "settings:ollama:model:copy",
            DELETE_MODEL: "settings:ollama:model:delete",
            PULL_MODEL: "settings:ollama:model:pull",
        },
    },
} as const;

export const SocketEvents = {
    SERVER,
    CLIENT,
} as const;
