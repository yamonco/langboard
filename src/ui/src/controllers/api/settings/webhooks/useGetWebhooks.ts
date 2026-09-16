import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { WebhookModel } from "@/core/models";

const useGetWebhooks = (options?: TMutationOptions) => {
    const { mutate } = useQueryMutation();

    const getWebhooks = async () => {
        const res = await api.get<{ webhooks: WebhookModel.Interface[] }>(Routing.API.SETTINGS.WEBHOOKS.GET_LIST, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        WebhookModel.Model.fromArray(res.data.webhooks, true);

        return {};
    };

    const result = mutate(["get-webhooks"], getWebhooks, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useGetWebhooks;
