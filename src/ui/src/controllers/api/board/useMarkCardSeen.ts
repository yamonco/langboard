import { cardReadStateKey } from "./useCardReadState";
import { ProjectCard } from "@/core/models";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Utils } from "@langboard/core/utils";

export interface IMarkCardSeenForm {
    project_uid: string;
    card_uid: string;
}

const useMarkCardSeen = (options?: TMutationOptions<IMarkCardSeenForm>) => {
    const { mutate, queryClient } = useQueryMutation();

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
        onSuccess: async (data, variables, onMutateResult, context) => {
            const card = ProjectCard.Model.getModel(variables.card_uid);
            if (card) card.has_unread_change = false;
            await queryClient.invalidateQueries({ queryKey: [`get-cards-${variables.project_uid}`] });
            await queryClient.invalidateQueries({ queryKey: cardReadStateKey(variables.project_uid, variables.card_uid) });
            await options?.onSuccess?.(data, variables, onMutateResult, context);
        },
    });
};

export default useMarkCardSeen;
