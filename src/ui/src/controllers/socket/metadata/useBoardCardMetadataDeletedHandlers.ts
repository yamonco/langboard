import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { applyMetadataDeleted, IMetadataDeletedRawResponse } from "@/controllers/socket/shared/MetadataSocketHelper";

interface IUseBoardCardMetadataDeletedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    cardUID: string;
}

const useBoardCardMetadataDeletedHandlers = ({ callback, cardUID }: IUseBoardCardMetadataDeletedHandlersProps) => {
    return useSocketHandler<{}, IMetadataDeletedRawResponse>({
        topic: ESocketTopic.BoardCard,
        topicId: cardUID,
        eventKey: `board-card-metadata-deleted-${cardUID}`,
        onProps: {
            name: SocketEvents.SERVER.METADATA.DELETED,
            params: { uid: cardUID },
            callback,
            responseConverter: (data) => {
                applyMetadataDeleted("card", cardUID, data);
                return {};
            },
        },
    });
};

export default useBoardCardMetadataDeletedHandlers;
