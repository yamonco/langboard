import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { UserNotification } from "@/core/models";
import { IUserSettings } from "@/core/stores/UserSettingsStore";

export interface IGetNotificationListForm {
    time_range?: IUserSettings["notifications_time_range"];
    page?: number;
    limit?: number;
    unread_only?: boolean;
}

export interface IGetNotificationListResponse {
    notifications: UserNotification.TModel[];
    has_more?: boolean;
    unread_count?: number;
}

const useGetNotificationList = (options?: TMutationOptions<IGetNotificationListForm, IGetNotificationListResponse>) => {
    const { mutate } = useQueryMutation();

    const toggleAllScopedByTypeNotificationSettings = async (params: IGetNotificationListForm) => {
        const res = await api.get(Routing.API.NOTIFICATION.GET_LIST, {
            params: {
                time_range: params.time_range || "3d",
                page: params.page || 1,
                limit: params.limit || 20,
                unread_only: params.unread_only || false,
            },
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        UserNotification.Model.fromArray(res.data.notifications || [], true);

        return res.data;
    };

    const result = mutate(["toggle-all-scoped-by-type-notification-settings"], toggleAllScopedByTypeNotificationSettings, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useGetNotificationList;
