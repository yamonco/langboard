import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Utils } from "@langboard/core/utils";

export interface IMarkCardSeenForm {
    project_uid: string;
    card_uid: string;
}

const useMarkCardSeen = (options?: TMutationOptions<IMarkCardSeenForm>) => {
    const { mutate } = useQueryMutation();

    const markCardSeen = async (params: IMarkCardSeenForm) => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.MARK_SEEN, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const res = await api.post(url, undefined, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        return res.data;
    };

    return mutate(["mark-card-seen"], markCardSeen, {
        ...options,
        retry: 0,
    });
};

export default useMarkCardSeen;
