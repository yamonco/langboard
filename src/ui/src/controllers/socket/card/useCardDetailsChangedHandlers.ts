import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { cardReadStateKey } from "@/controllers/api/board/useCardReadState";
import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectCard } from "@/core/models";
import type { IWorkState } from "@/core/models/ProjectCard";
import { IEditorContent } from "@/core/models/Base";
import { ESocketTopic } from "@langboard/core/enums";

export interface ICardDetailsChangedRawResponse {
    read_state_changed?: boolean;
    updated_at?: string;
    title?: string;
    description?: IEditorContent;
    deadline_at?: string | null;
    work_state?: IWorkState;
}

export interface IUseCardDetailsChangedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
    cardUID: string;
}

const useCardDetailsChangedHandlers = ({ callback, projectUID, cardUID }: IUseCardDetailsChangedHandlersProps) => {
    const { queryClient } = useQueryMutation();
    return useSocketHandler<{}, ICardDetailsChangedRawResponse>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-card-details-changed-${cardUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CARD.DETAILS_CHANGED,
            params: { uid: cardUID },
            callback,
            responseConverter: (data) => {
                if (data.read_state_changed) void queryClient.invalidateQueries({ queryKey: cardReadStateKey(projectUID, cardUID) });
                const card = ProjectCard.Model.getModel(cardUID);
                if (card) {
                    if (data.title !== undefined) card.title = data.title;
                    if (data.description !== undefined) card.description = data.description;
                    if (data.deadline_at !== undefined) card.deadline_at = data.deadline_at ?? undefined;
                    if (data.work_state !== undefined) card.work_state = data.work_state;
                    if (data.updated_at !== undefined) card.updated_at = data.updated_at;
                }
                return {};
            },
        },
    });
};

export default useCardDetailsChangedHandlers;
