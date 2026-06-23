import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { MetadataModel } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";
import { applyMetadataUpdated, IMetadataUpdatedRawResponse } from "@/controllers/socket/shared/MetadataSocketHelper";

export interface IUseMetadataUpdatedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    type: MetadataModel.TType;
    uid: string;
}

const useMetadataUpdatedHandlers = ({ callback, type, uid }: IUseMetadataUpdatedHandlersProps) => {
    let topic: ESocketTopic;
    switch (type) {
        case "card":
            topic = ESocketTopic.BoardCard;
            break;
        case "project_wiki":
            topic = ESocketTopic.BoardWikiPrivate;
            break;
    }

    return useSocketHandler<{}, IMetadataUpdatedRawResponse>({
        topic: topic,
        topicId: uid,
        eventKey: `metadata-updated-${topic}-${uid}`,
        onProps: {
            name: SocketEvents.SERVER.METADATA.UPDATED,
            params: { uid },
            callback,
            responseConverter: (data) => {
                applyMetadataUpdated(type, uid, data);
                return {};
            },
        },
    });
};

export default useMetadataUpdatedHandlers;
