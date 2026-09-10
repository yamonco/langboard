import { api } from "@/core/helpers/Api";
import { TMutationOptions, TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";

export enum EProjectEmailNotificationCategory {
    Board = "board",
    Cards = "cards",
    Comments = "comments",
    Attachments = "attachments",
    Checklists = "checklists",
    Wiki = "wiki",
}

export enum EProjectEmailNotificationDeliveryStatus {
    Succeeded = "succeeded",
    Failed = "failed",
}

export interface IProjectEmailNotificationRecipient {
    uid: string;
    firstname: string;
    lastname: string;
    email: string;
}

export interface IProjectEmailNotificationPolicy {
    is_enabled: boolean;
    notify_all_members: boolean;
    categories: EProjectEmailNotificationCategory[];
    recipient_user_uids: string[];
    external_recipient_emails: string[];
    card_move_target_columns: string[];
    available_recipients: IProjectEmailNotificationRecipient[];
    available_columns: string[];
    smtp_available: boolean;
    last_delivery_status: EProjectEmailNotificationDeliveryStatus | null;
    last_delivery_at: string | null;
    last_delivery_recipient_email: string | null;
    last_delivery_error: string | null;
}

export interface IUpdateProjectEmailNotificationPolicyForm {
    is_enabled: boolean;
    notify_all_members: boolean;
    categories: EProjectEmailNotificationCategory[];
    recipient_user_uids: string[];
    external_recipient_emails: string[];
    card_move_target_columns: string[];
}

const policyKey = (projectUID: string) => ["project-email-notification-policy", projectUID];

export const useGetProjectEmailNotificationPolicy = (projectUID: string, options?: TQueryOptions<unknown, IProjectEmailNotificationPolicy>) => {
    const { query } = useQueryMutation();
    return query(
        policyKey(projectUID),
        async () => {
            const url = Utils.String.format(Routing.API.BOARD.SETTINGS.EMAIL_NOTIFICATIONS, { uid: projectUID });
            return (
                await api.get<{ policy: IProjectEmailNotificationPolicy }>(url, {
                    env: {
                        interceptToast: options?.interceptToast,
                    } as never,
                })
            ).data.policy;
        },
        { ...options, retry: 0 }
    );
};

export const useUpdateProjectEmailNotificationPolicy = (
    projectUID: string,
    options?: TMutationOptions<IUpdateProjectEmailNotificationPolicyForm, IProjectEmailNotificationPolicy>
) => {
    const { mutate } = useQueryMutation();
    return mutate(
        policyKey(projectUID),
        async (form) => {
            const url = Utils.String.format(Routing.API.BOARD.SETTINGS.EMAIL_NOTIFICATIONS, { uid: projectUID });
            return (
                await api.put<{ policy: IProjectEmailNotificationPolicy }>(url, form, {
                    env: {
                        interceptToast: options?.interceptToast,
                    } as never,
                })
            ).data.policy;
        },
        { ...options, retry: 0 }
    );
};
