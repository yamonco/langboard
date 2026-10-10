import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Utils } from "@langboard/core/utils";

export interface IChangeProjectColumnDescriptionForm {
    project_uid: string;
    project_column_uid: string;
    description: string;
}

/** Save guidance through the existing board-update authorization boundary. */
const useChangeProjectColumnDescription = (options?: TMutationOptions<IChangeProjectColumnDescriptionForm, { description: string }>) => {
    const { mutate } = useQueryMutation();
    return mutate(
        ["change-project-column-description"],
        async (params: IChangeProjectColumnDescriptionForm) => {
            const url = Utils.String.format(Routing.API.BOARD.COLUMN.CHANGE_DESCRIPTION, {
                uid: params.project_uid,
                project_column_uid: params.project_column_uid,
            });
            const response = await api.put<{ description: string }>(url, { description: params.description });
            return response.data;
        },
        { ...options, retry: 0 }
    );
};

export default useChangeProjectColumnDescription;
