export enum ENotificationType {
    ProjectInvited = "project_invited",
    MentionedInCard = "mentioned_in_card",
    MentionedInComment = "mentioned_in_comment",
    MentionedInWiki = "mentioned_in_wiki",
    AssignedToCard = "assigned_to_card",
    ReactedToComment = "reacted_to_comment",
    NotifiedFromChecklist = "notified_from_checklist",
    ScheduledRule = "scheduled_rule",
}
export enum ENotificationScope {
    All = "all",
    Specific = "specific",
}

export enum ENotificationChannel {
    Web = "web",
    Email = "email",
    Mobile = "mobile",
    IoT = "iot",
}

export enum ENotificationMutationAction {
    Read = "read",
    ReadAll = "read_all",
    Delete = "delete",
    DeleteAll = "delete_all",
}

export interface INotificationMutation {
    action: ENotificationMutationAction;
    unread_count: number;
    notification_uid?: string;
    read_at?: string;
}

export type TNotificationType = Exclude<ENotificationType, ENotificationType.ProjectInvited>;

export type TNotificationSpecificType = "project" | "column" | "wiki" | "card";

const DISABLED_NOTIFICATION_TYPES = [ENotificationType.ProjectInvited];

export const ALL_NOTIFICATION_TYPES = Object.keys(ENotificationType)
    .filter((key) => !DISABLED_NOTIFICATION_TYPES.includes(ENotificationType[key]))
    .map((key) => ENotificationType[key]) as TNotificationType[];

export const DEEP_NOTIFICATION_TYPE_MAP = {
    project: {
        column: {
            card: [
                ENotificationType.MentionedInCard,
                ENotificationType.MentionedInComment,
                ENotificationType.AssignedToCard,
                ENotificationType.ReactedToComment,
                ENotificationType.NotifiedFromChecklist,
                ENotificationType.ScheduledRule,
            ],
        },
        wiki: [ENotificationType.MentionedInWiki],
    },
};

export const FLAT_NOTIFICATION_TYPE_MAP: Record<TNotificationSpecificType, TNotificationType[]> = {
    project: [
        ENotificationType.MentionedInCard,
        ENotificationType.MentionedInComment,
        ENotificationType.AssignedToCard,
        ENotificationType.ReactedToComment,
        ENotificationType.NotifiedFromChecklist,
        ENotificationType.ScheduledRule,
        ENotificationType.MentionedInWiki,
    ],
    column: [
        ENotificationType.MentionedInCard,
        ENotificationType.MentionedInComment,
        ENotificationType.AssignedToCard,
        ENotificationType.ReactedToComment,
        ENotificationType.NotifiedFromChecklist,
        ENotificationType.ScheduledRule,
    ],
    card: [
        ENotificationType.MentionedInCard,
        ENotificationType.MentionedInComment,
        ENotificationType.AssignedToCard,
        ENotificationType.ReactedToComment,
        ENotificationType.NotifiedFromChecklist,
        ENotificationType.ScheduledRule,
    ],
    wiki: [ENotificationType.MentionedInWiki],
};
