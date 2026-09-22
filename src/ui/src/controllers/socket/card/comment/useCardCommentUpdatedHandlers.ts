import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectCardComment } from "@/core/models";
import { IEditorContent } from "@/core/models/Base";
import { ESocketTopic } from "@langboard/core/enums";

export interface ICardCommentUpdatedRawResponse {
    uid: string;
    content: IEditorContent;
    updated_at: Date;
}

export interface IUseCardCommentUpdatedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
    cardUID: string;
}

const useCardCommentUpdatedHandlers = ({ callback, projectUID, cardUID }: IUseCardCommentUpdatedHandlersProps) => {
    return useSocketHandler<{}, ICardCommentUpdatedRawResponse>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-card-comment-updated-${cardUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CARD.COMMENT.UPDATED,
            params: { uid: cardUID },
            callback,
            responseConverter: (data) => {
                const comment = ProjectCardComment.Model.getModel(data.uid);
                if (comment) {
                    comment.content = data.content;
                    comment.updated_at = data.updated_at;
                    comment.is_edited = true;
                }
                return {};
            },
        },
    });
};

export default useCardCommentUpdatedHandlers;
