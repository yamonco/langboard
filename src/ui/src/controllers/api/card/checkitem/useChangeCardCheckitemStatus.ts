import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectCheckitem } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IChangeCardCheckitemStatusForm {
    project_uid: string;
    card_uid: string;
    checkitem_uid: string;
    status: ProjectCheckitem.ECheckitemStatus;
    replace_active?: bool;
}

const useChangeCardCheckitemStatus = (options?: TMutationOptions<IChangeCardCheckitemStatusForm>) => {
    const { mutate } = useQueryMutation();

    const changeCheckitemStatus = async (params: IChangeCardCheckitemStatusForm) => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.CHECKITEM.CHANGE_STATUS, {
            uid: params.project_uid,
            card_uid: params.card_uid,
            checkitem_uid: params.checkitem_uid,
        });
        const res = await api.put(
            url,
            {
                status: params.status,
                replace_active: params.replace_active ?? false,
            },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        return res.data;
    };

    const result = mutate(["change-card-checkitem-status"], changeCheckitemStatus, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useChangeCardCheckitemStatus;
