import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";

export interface IWebhookEventOption {
    label: string;
    value: string;
}

const useGetWebhookEvents = (options?: TMutationOptions<{}, IWebhookEventOption[]>) => {
    const { mutate } = useQueryMutation();

    const getWebhookEvents = async (): Promise<IWebhookEventOption[]> => {
        const res = await api.get(Routing.API.SETTINGS.SCHEMAS.WEBHOOK, {
            env: {
                noToast: options?.interceptToast,
            } as never,
        });
        const schemas = (res.data.components?.schemas ?? {}) as Record<string, { title?: string }>;

        return Object.entries(schemas)
            .map(([value, schema]) => ({
                value,
                label: schema.title ?? value.replaceAll("_", " "),
            }))
            .sort((a, b) => a.label.localeCompare(b.label));
    };

    return mutate(["get-webhook-events"], getWebhookEvents, {
        ...options,
        retry: 0,
    });
};

export default useGetWebhookEvents;
