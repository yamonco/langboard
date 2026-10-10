import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectLabel } from "@/core/models";
import type { IGlobalLabel } from "@/controllers/api/settings/globalLabels/useGlobalLabels";

export const useBoardGlobalLabels = (projectUID: string, enabled: boolean) => {
    const { query, mutate } = useQueryMutation();
    const catalog = query(
        ["board-global-labels", projectUID],
        async () => {
            return (await api.get<{ labels: IGlobalLabel[] }>(`/board/${projectUID}/settings/global-labels`)).data.labels;
        },
        { enabled, retry: false, staleTime: 60000 }
    );
    const useGlobal = mutate(
        ["use-board-global-label", projectUID],
        async (uid: string) => {
            const response = await api.post<{ label: ProjectLabel.Interface }>(
                `/board/${projectUID}/settings/global-labels/use`,
                {
                    global_label_uid: uid,
                },
                { env: { interceptToast: true } as never }
            );
            ProjectLabel.Model.fromOne(response.data.label, true);
            return response.data.label.uid;
        },
        { retry: 0 }
    );
    return { catalog, useGlobal };
};
