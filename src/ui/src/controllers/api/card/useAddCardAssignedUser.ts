import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";

export interface IAddCardAssignedUserForm {
    project_uid: string;
    card_uid: string;
    assignee_uid: string;
}

export interface IAddCardAssignedUserResult {
    member_uids: string[];
}

const useAddCardAssignedUser = (options?: TMutationOptions<IAddCardAssignedUserForm, IAddCardAssignedUserResult>) => {
    const { mutate } = useQueryMutation();

    const addCardAssignedUser = async (params: IAddCardAssignedUserForm) => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.ADD_ASSIGNED_USER, {
            uid: params.project_uid,
            card_uid: params.card_uid,
            assignee_uid: params.assignee_uid,
        });
        const response = await api.put<IAddCardAssignedUserResult>(url, undefined, {
            env: { interceptToast: options?.interceptToast } as never,
        });
        return response.data;
    };

    return mutate<IAddCardAssignedUserForm, IAddCardAssignedUserResult>(["add-card-assigned-user"], addCardAssignedUser, {
        ...options,
        retry: 0,
    });
};

export default useAddCardAssignedUser;
