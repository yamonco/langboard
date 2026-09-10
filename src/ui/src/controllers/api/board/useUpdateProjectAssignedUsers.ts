import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Utils } from "@langboard/core/utils";

export interface IUpdateProjectAssignedUsersForm {
    uid: string;
    emails: string[];
    member_uids: string[];
}

const useUpdateProjectAssignedUsers = (options?: TMutationOptions<IUpdateProjectAssignedUsersForm>) => {
    const { mutate } = useQueryMutation();

    const updateProjectAssignedUsers = async (params: IUpdateProjectAssignedUsersForm) => {
        const url = Utils.String.format(Routing.API.BOARD.UPDATE_ASSIGNED_USERS, {
            uid: params.uid,
        });
        const res = await api.put(
            url,
            {
                ...params,
            },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        return res.data;
    };

    const result = mutate(["update-project-assigned-users"], updateProjectAssignedUsers, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useUpdateProjectAssignedUsers;
