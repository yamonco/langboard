import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { AuthUser, UserNotification } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

export interface IUserNotifiedRawResponse {
    notification: UserNotification.Interface;
}

export interface IUseUserNotifiedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    currentUser: AuthUser.TModel;
}

const useUserNotifiedHandlers = ({ callback, currentUser }: IUseUserNotifiedHandlersProps) => {
    return useSocketHandler<{ isNew: bool }, IUserNotifiedRawResponse>({
        topic: ESocketTopic.UserPrivate,
        topicId: currentUser.uid,
        eventKey: `user-notified-${currentUser.uid}`,
        onProps: {
            name: SocketEvents.SERVER.USER.NOTIFIED,
            callback: ({ isNew }) => {
                if (isNew) {
                    callback?.({});
                }
            },
            responseConverter: (data) => {
                const isNew = !UserNotification.Model.getModel(data.notification.uid);
                UserNotification.Model.fromOne(data.notification, true);
                return { isNew };
            },
        },
    });
};

export default useUserNotifiedHandlers;
