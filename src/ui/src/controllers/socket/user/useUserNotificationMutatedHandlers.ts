import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { AuthUser, UserNotification } from "@/core/models";
import { ENotificationMutationAction, INotificationMutation } from "@/core/models/types/notification.type";

export interface IUseUserNotificationMutatedHandlersProps extends IBaseUseSocketHandlersProps<INotificationMutation> {
    currentUser: AuthUser.TModel;
}

const useUserNotificationMutatedHandlers = ({ callback, currentUser }: IUseUserNotificationMutatedHandlersProps) => {
    return useSocketHandler<INotificationMutation>({
        topic: ESocketTopic.UserPrivate,
        topicId: currentUser.uid,
        eventKey: `user-notification-mutated-${currentUser.uid}`,
        onProps: {
            name: SocketEvents.SERVER.USER.NOTIFICATION_MUTATED,
            callback: (mutation) => {
                switch (mutation.action) {
                    case ENotificationMutationAction.Read: {
                        const notification = mutation.notification_uid ? UserNotification.Model.getModel(mutation.notification_uid) : undefined;
                        if (notification && mutation.read_at) {
                            notification.read_at = new Date(mutation.read_at);
                        }
                        break;
                    }
                    case ENotificationMutationAction.ReadAll: {
                        if (mutation.read_at) {
                            const readAt = new Date(mutation.read_at);
                            const notifications = UserNotification.Model.getModels(() => true);
                            for (let i = 0; i < notifications.length; ++i) {
                                notifications[i].read_at = readAt;
                            }
                        }
                        break;
                    }
                    case ENotificationMutationAction.Delete:
                        if (mutation.notification_uid) {
                            UserNotification.Model.deleteModel(mutation.notification_uid);
                        }
                        break;
                    case ENotificationMutationAction.DeleteAll:
                        UserNotification.Model.deleteModels(() => true);
                        break;
                }
                callback?.(mutation);
            },
        },
    });
};

export default useUserNotificationMutatedHandlers;
