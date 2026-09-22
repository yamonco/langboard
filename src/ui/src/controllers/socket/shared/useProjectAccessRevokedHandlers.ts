import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import { deleteProjectModel } from "@/core/helpers/ModelHelper";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";

export interface IUseProjectAccessRevokedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    topic: ESocketTopic.Board | ESocketTopic.Dashboard;
    projectUID: string;
}

const useProjectAccessRevokedHandlers = ({ callback, topic, projectUID }: IUseProjectAccessRevokedHandlersProps) => {
    return useSocketHandler<{}, {}>({
        topic,
        topicId: projectUID,
        eventKey: `project-access-revoked-${topic}-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.SUBSCRIPTION_REVOKED,
            callback,
            responseConverter: () => {
                deleteProjectModel(topic, projectUID);
                return {};
            },
        },
    });
};

export default useProjectAccessRevokedHandlers;
