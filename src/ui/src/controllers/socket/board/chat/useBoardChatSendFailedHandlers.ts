import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ESocketTopic } from "@langboard/core/enums";

interface IBoardChatSendFailedResponse {
    task_id: string;
    already_started: bool;
}

interface IUseBoardChatSendFailedHandlersProps extends IBaseUseSocketHandlersProps<IBoardChatSendFailedResponse> {
    projectUID: string;
}

const useBoardChatSendFailedHandlers = ({ callback, projectUID }: IUseBoardChatSendFailedHandlersProps) => {
    return useSocketHandler<IBoardChatSendFailedResponse, IBoardChatSendFailedResponse>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-chat-send-failed-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CHAT.SEND_FAILED,
            callback,
        },
    });
};

export default useBoardChatSendFailedHandlers;
