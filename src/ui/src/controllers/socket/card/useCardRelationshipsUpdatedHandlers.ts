import { Routing, SocketEvents } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { api } from "@/core/helpers/Api";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ESocketTopic } from "@langboard/core/enums";
import syncCardRelationships, { ICardRelationshipsUpdatedRawResponse } from "@/controllers/socket/card/syncCardRelationships";

export interface IUseCardRelationshipsUpdatedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
}

const useCardRelationshipsUpdatedHandlers = ({ callback, projectUID }: IUseCardRelationshipsUpdatedHandlersProps) => {
    return useSocketHandler<{}, ICardRelationshipsUpdatedRawResponse & { relationships_invalidated?: boolean }>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-card-relationships-updated-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CARD.RELATIONSHIPS_UPDATED,
            params: { uid: projectUID },
            callback,
            responseConverter: async (data) => {
                if (data.relationships_invalidated) {
                    try {
                        const url = Utils.String.format(Routing.API.BOARD.CARD.UPDATE_RELATIONSHIPS, {
                            uid: projectUID,
                            card_uid: data.card_uid,
                        });
                        const response = await api.get(url);
                        syncCardRelationships({ card_uid: data.card_uid, relationships: response.data.relationships });
                    } catch {
                        // A failed authorized read must not restore a queued relationship snapshot.
                    }
                } else {
                    syncCardRelationships(data);
                }
                return {};
            },
        },
    });
};

export default useCardRelationshipsUpdatedHandlers;
