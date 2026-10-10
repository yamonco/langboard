import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { AuthUser } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

export interface IUseUserNotifiedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    currentUser: AuthUser.TModel;
}

const useUserNotifiedHandlers = ({ callback, currentUser }: IUseUserNotifiedHandlersProps) => {
    return useSocketHandler({
        topic: ESocketTopic.UserPrivate,
        topicId: currentUser.uid,
        eventKey: `user-notified-${currentUser.uid}`,
        onProps: {
            name: SocketEvents.SERVER.USER.NOTIFIED,
            callback: () => callback?.({}),
        },
    });
};

export default useUserNotifiedHandlers;
