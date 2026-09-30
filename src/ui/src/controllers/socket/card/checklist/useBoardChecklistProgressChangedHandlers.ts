import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";

interface IProgressChangedPayload {
    card_uid: string;
}

interface IProps extends IBaseUseSocketHandlersProps<IProgressChangedPayload> {
    projectUID: string;
    subscriberKey?: string;
}

const useBoardChecklistProgressChangedHandlers = ({ callback, projectUID, subscriberKey }: IProps) =>
    useSocketHandler<IProgressChangedPayload>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-card-checklist-progress-changed-${projectUID}${subscriberKey ? `-${subscriberKey}` : ""}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CARD.CHECKLIST.PROGRESS_CHANGED,
            params: { uid: projectUID },
            callback,
        },
    });

export default useBoardChecklistProgressChangedHandlers;
