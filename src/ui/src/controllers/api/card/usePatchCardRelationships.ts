import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Utils } from "@langboard/core/utils";

export interface ICardGraphEdge {
    parent_ref: string;
    child_ref: string;
    relationship_type_uid: string;
}

export interface IPatchCardRelationshipsForm {
    project_uid: string;
    card_uid: string;
    add_edges: ICardGraphEdge[];
}

const usePatchCardRelationships = (options?: TMutationOptions<IPatchCardRelationshipsForm>) => {
    const { mutate } = useQueryMutation();
    const patchCardRelationships = async (params: IPatchCardRelationshipsForm) => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.PATCH_RELATIONSHIPS, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const response = await api.post(
            url,
            {
                new_cards: [],
                add_edges: params.add_edges,
                remove_relationship_uids: [],
            },
            { env: { interceptToast: options?.interceptToast } as never }
        );
        return response.data;
    };

    return mutate<IPatchCardRelationshipsForm, unknown>(["patch-card-relationships"], patchCardRelationships, {
        ...options,
        retry: 0,
    });
};

export default usePatchCardRelationships;
