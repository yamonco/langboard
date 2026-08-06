import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { WebhookModel } from "@/core/models";

export interface ICreateWebhookForm {
    name: string;
    url: string;
    events?: string[] | null;
}

const useCreateWebhook = (options?: TMutationOptions<ICreateWebhookForm>) => {
    const { mutate } = useQueryMutation();

    const createWebhook = async (params: ICreateWebhookForm) => {
        const res = await api.post(
            Routing.API.SETTINGS.WEBHOOKS.CREATE,
            {
                name: params.name,
                url: params.url,
                events: params.events,
            },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        WebhookModel.Model.fromOne(res.data.webhook, true);

        return {
            revealed_value: res.data.revealed_value,
        };
    };

    const result = mutate(["create-webhook"], createWebhook, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useCreateWebhook;
