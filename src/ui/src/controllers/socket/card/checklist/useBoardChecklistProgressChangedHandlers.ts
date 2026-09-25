import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";

interface IProgressChangedPayload {
    card_uid: string;
}

interface IProps extends IBaseUseSocketHandlersProps<IProgressChangedPayload> {
    projectUID: string;
}

const useBoardChecklistProgressChangedHandlers = ({ callback, projectUID }: IProps) =>
    useSocketHandler<IProgressChangedPayload>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-card-checklist-progress-changed-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CARD.CHECKLIST.PROGRESS_CHANGED,
            params: { uid: projectUID },
            callback,
        },
    });

export default useBoardChecklistProgressChangedHandlers;
