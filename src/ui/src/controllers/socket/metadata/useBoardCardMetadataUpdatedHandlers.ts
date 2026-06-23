import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { applyMetadataUpdated, IMetadataUpdatedRawResponse } from "@/controllers/socket/shared/MetadataSocketHelper";

interface IUseBoardCardMetadataUpdatedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    cardUID: string;
}

const useBoardCardMetadataUpdatedHandlers = ({ callback, cardUID }: IUseBoardCardMetadataUpdatedHandlersProps) => {
    return useSocketHandler<{}, IMetadataUpdatedRawResponse>({
        topic: ESocketTopic.BoardCard,
        topicId: cardUID,
        eventKey: `board-card-metadata-updated-${cardUID}`,
        onProps: {
            name: SocketEvents.SERVER.METADATA.UPDATED,
            params: { uid: cardUID },
            callback,
            responseConverter: (data) => {
                applyMetadataUpdated("card", cardUID, data);
                return {};
            },
        },
    });
};

export default useBoardCardMetadataUpdatedHandlers;
