import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectCard } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

export interface ICardColumnChangedRawResponse {
    to_column_uid: string;
    project_column_name: string;
    updated_at?: string;
}

export interface IUseCardColumnChangedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    card: ProjectCard.TModel;
}

const useCardColumnChangedHandlers = ({ callback, card }: IUseCardColumnChangedHandlersProps) => {
    return useSocketHandler<{}, ICardColumnChangedRawResponse>({
        topic: ESocketTopic.BoardCard,
        topicId: card.uid,
        eventKey: `board-card-column-changed-${card.uid}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CARD.ORDER_CHANGED,
            params: { uid: card.uid },
            callback,
            responseConverter: (data) => {
                card.project_column_uid = data.to_column_uid;
                card.project_column_name = data.project_column_name;
                if (data.updated_at) card.updated_at = data.updated_at;
                return {};
            },
        },
    });
};

export default useCardColumnChangedHandlers;
