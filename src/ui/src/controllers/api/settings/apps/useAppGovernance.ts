import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";

export type TAppGovernanceMode = "disabled" | "approved_only" | "personal_allowed";
export interface IAppGovernance {
    mode: TAppGovernanceMode;
    effective_mode: TAppGovernanceMode;
    revision: string;
}

export const useAppGovernance = () => {
    const { query, mutate, queryClient } = useQueryMutation();
    const queryKey = ["app-governance"];
    const config = { env: { interceptToast: true } as never };
    const load = query(queryKey, async () => (await api.get<IAppGovernance>("/settings/apps/governance", config)).data, {
        retry: 0,
        staleTime: Infinity,
        refetchOnMount: "always",
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        refetchInterval: false,
    });
    const save = mutate(
        ["save-app-governance"],
        async (input: { mode: TAppGovernanceMode; expected_revision: string }) =>
            (await api.put<IAppGovernance>("/settings/apps/governance", input, config)).data,
        { retry: 0, onSuccess: (governance) => queryClient.setQueryData(queryKey, governance) }
    );
    return { load, save };
};
