import { api } from "@/core/helpers/Api";
import { TMutationOptions, TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";

export type TProjectEmailNotificationCategory = "board" | "cards" | "comments" | "attachments" | "checklists" | "wiki";

export interface IProjectEmailNotificationRecipient {
    uid: string;
    firstname: string;
    lastname: string;
    email: string;
}

export interface IProjectEmailNotificationPolicy {
    is_enabled: boolean;
    notify_all_members: boolean;
    categories: TProjectEmailNotificationCategory[];
    recipient_user_uids: string[];
    card_move_target_columns: string[];
    available_recipients: IProjectEmailNotificationRecipient[];
    available_columns: string[];
    smtp_available: boolean;
}

export interface IUpdateProjectEmailNotificationPolicyForm {
    is_enabled: boolean;
    notify_all_members: boolean;
    categories: TProjectEmailNotificationCategory[];
    recipient_user_uids: string[];
    card_move_target_columns: string[];
}

const policyKey = (projectUID: string) => ["project-email-notification-policy", projectUID];

export const useGetProjectEmailNotificationPolicy = (projectUID: string, options?: TQueryOptions<unknown, IProjectEmailNotificationPolicy>) => {
    const { query } = useQueryMutation();
    return query(
        policyKey(projectUID),
        async () => {
            const url = Utils.String.format(Routing.API.BOARD.SETTINGS.EMAIL_NOTIFICATIONS, { uid: projectUID });
            return (await api.get(url)).data.policy as IProjectEmailNotificationPolicy;
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
            return (await api.put(url, form)).data.policy as IProjectEmailNotificationPolicy;
        },
        { ...options, retry: 0 }
    );
};
