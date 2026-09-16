import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";

export interface IWebhookEventOption {
    label: string;
    value: string;
}

interface IWebhookSchemaResponse {
    components?: {
        schemas?: Record<string, { title?: string }>;
    };
}

const useGetWebhookEvents = (options?: TQueryOptions<IWebhookEventOption[]>) => {
    const { query } = useQueryMutation();

    const getWebhookEvents = async (): Promise<IWebhookEventOption[]> => {
        const res = await api.get<IWebhookSchemaResponse>(Routing.API.SETTINGS.SCHEMAS.WEBHOOK, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });
        const schemas = res.data.components?.schemas ?? {};

        return Object.entries(schemas)
            .map(([value, schema]) => ({
                value,
                label: schema.title ?? value.replaceAll("_", " "),
            }))
            .sort((a, b) => a.label.localeCompare(b.label));
    };

    return query(["get-webhook-events"], getWebhookEvents, {
        ...options,
        retry: 0,
    });
};

export default useGetWebhookEvents;
