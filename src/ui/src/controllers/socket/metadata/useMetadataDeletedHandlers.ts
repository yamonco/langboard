import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { MetadataModel } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";
import { applyMetadataDeleted, IMetadataDeletedRawResponse } from "@/controllers/socket/shared/MetadataSocketHelper";

export interface IUseMetadataDeletedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    type: MetadataModel.TType;
    uid: string;
}

const useMetadataDeletedHandlers = ({ callback, type, uid }: IUseMetadataDeletedHandlersProps) => {
    let topic: ESocketTopic;
    switch (type) {
        case "card":
            topic = ESocketTopic.BoardCard;
            break;
        case "project_wiki":
            topic = ESocketTopic.BoardWikiPrivate;
            break;
    }

    return useSocketHandler<{}, IMetadataDeletedRawResponse>({
        topic: topic,
        topicId: uid,
        eventKey: `metadata-deleted-${topic}-${uid}`,
        onProps: {
            name: SocketEvents.SERVER.METADATA.DELETED,
            params: { uid },
            callback,
            responseConverter: (data) => {
                applyMetadataDeleted(type, uid, data);
                return {};
            },
        },
    });
};

export default useMetadataDeletedHandlers;
