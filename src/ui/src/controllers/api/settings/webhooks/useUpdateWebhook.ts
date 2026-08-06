import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { WebhookModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IUpdateWebhookForm {
    name?: string;
    url?: string;
    events?: string[] | null;
}

const useUpdateWebhook = (webhook: WebhookModel.TModel, options?: TMutationOptions<IUpdateWebhookForm>) => {
    const { mutate } = useQueryMutation();

    const updateWebhook = async (params: IUpdateWebhookForm) => {
        const url = Utils.String.format(Routing.API.SETTINGS.WEBHOOKS.UPDATE, { webhook_uid: webhook.uid });
        const payload: IUpdateWebhookForm = {};
        if ("name" in params) {
            payload.name = params.name;
        }
        if ("url" in params) {
            payload.url = params.url;
        }
        if ("events" in params) {
            payload.events = params.events;
        }
        const res = await api.put(url, payload, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        WebhookModel.Model.fromOne(res.data.webhook, true);

        return res.data.webhook;
    };

    const result = mutate(["update-webhook"], updateWebhook, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useUpdateWebhook;
