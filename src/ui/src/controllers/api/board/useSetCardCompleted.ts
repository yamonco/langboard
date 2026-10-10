import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Utils } from "@langboard/core/utils";

export interface ISetCardCompletedForm {
    project_uid: string;
    card_uid: string;
    completed: boolean;
}

const useSetCardCompleted = (options?: TMutationOptions<ISetCardCompletedForm>) => {
    const { mutate } = useQueryMutation();

    const setCardCompleted = async (params: ISetCardCompletedForm) => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.SET_COMPLETED, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const res = await api.post(
            url,
            { completed: params.completed },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        return res.data as { completed: boolean };
    };

    const result = mutate(["set-card-completed"], setCardCompleted, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useSetCardCompleted;
