import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";

export interface ISerializedBlockPayload {
    block_type: string;
    payload: Record<string, unknown>;
}

export interface IReplaceCardContentBlocksForm {
    project_uid: string;
    card_uid: string;
    blocks: ISerializedBlockPayload[];
}

const useReplaceCardContentBlocks = (options?: TMutationOptions<IReplaceCardContentBlocksForm>) => {
    const { mutate } = useQueryMutation();

    const replaceCardContentBlocks = async (params: IReplaceCardContentBlocksForm) => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.CONTENT_BLOCKS, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const res = await api.put(
            url,
            { blocks: params.blocks },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        return res.data;
    };

    return mutate(["replace-card-content-blocks"], replaceCardContentBlocks, {
        ...options,
        retry: 0,
    });
};

export default useReplaceCardContentBlocks;
