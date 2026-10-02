import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";

export interface IGlobalLabel {
    uid: string;
    name: string;
    color: string;
    description: string;
    translations: Record<string, { name: string; description: string }>;
}
export type TGlobalLabelInput = Omit<IGlobalLabel, "uid"> & { uid?: string };

export const useGetGlobalLabels = (options?: TMutationOptions<unknown, IGlobalLabel[]>) => {
    const { mutate } = useQueryMutation();
    return mutate(["get-global-labels"], async () => (await api.get<{ labels: IGlobalLabel[] }>("/settings/global-labels")).data.labels, {
        ...options,
        retry: 0,
    });
};
export const useSaveGlobalLabel = (options?: TMutationOptions<TGlobalLabelInput, IGlobalLabel>) => {
    const { mutate } = useQueryMutation();
    return mutate(
        ["save-global-label"],
        async ({ uid, ...form }: TGlobalLabelInput) => {
            const response = uid
                ? await api.put<{ label: IGlobalLabel }>(`/settings/global-labels/${uid}`, form)
                : await api.post<{ label: IGlobalLabel }>("/settings/global-labels", form);
            return response.data.label;
        },
        { ...options, retry: 0 }
    );
};
