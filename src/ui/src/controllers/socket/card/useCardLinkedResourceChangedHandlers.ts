import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ESocketTopic } from "@langboard/core/enums";

interface ILinkedResourceChangedPayload {
    uid: string;
}

interface IUseCardLinkedResourceChangedHandlersProps extends IBaseUseSocketHandlersProps<ILinkedResourceChangedPayload> {
    projectUID: string;
    cardUID: string;
    detail?: boolean;
}

const useCardLinkedResourceChangedHandlers = ({ callback, projectUID, cardUID, detail = false }: IUseCardLinkedResourceChangedHandlersProps) =>
    useSocketHandler<ILinkedResourceChangedPayload>({
        topic: detail ? ESocketTopic.BoardCard : ESocketTopic.Board,
        topicId: detail ? cardUID : projectUID,
        eventKey: `board-card-linked-resource-changed-${detail ? "detail" : "board"}-${cardUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CARD.LINKED_RESOURCE_CHANGED,
            params: { uid: cardUID },
            callback,
        },
    });

export default useCardLinkedResourceChangedHandlers;
