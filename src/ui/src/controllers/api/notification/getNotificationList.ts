import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { UserNotification } from "@/core/models";
import { IUserSettings } from "@/core/stores/UserSettingsStore";

export interface IGetNotificationListForm {
    time_range?: IUserSettings["notifications_time_range"];
    page?: number;
    limit?: number;
}

export interface IGetNotificationListResponse {
    notifications: UserNotification.Interface[];
    has_more?: boolean;
    unread_count?: number;
}

export const getNotificationList = async (params: IGetNotificationListForm, interceptToast?: bool): Promise<IGetNotificationListResponse> => {
    const res = await api.get<IGetNotificationListResponse>(Routing.API.NOTIFICATION.GET_LIST, {
        params: {
            time_range: params.time_range || "3d",
            page: params.page || 1,
            limit: params.limit || 20,
        },
        env: {
            interceptToast,
        } as never,
    });

    return res.data;
};
