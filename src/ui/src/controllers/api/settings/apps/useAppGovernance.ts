import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";

export type TAppGovernanceMode = "disabled" | "approved_only" | "personal_allowed";
export interface IAppGovernance {
    mode: TAppGovernanceMode | null;
    effective_mode: TAppGovernanceMode;
    revision: string;
}

export const useAppGovernance = (organizationUID?: string) => {
    const { query, mutate, queryClient } = useQueryMutation();
    const queryKey = ["app-governance", organizationUID ?? "global"];
    const path = organizationUID ? `/settings/apps/governance/organizations/${encodeURIComponent(organizationUID)}` : "/settings/apps/governance";
    const config = { env: { interceptToast: true } as never };
    const load = query(queryKey, async () => (await api.get<IAppGovernance>(path, config)).data, {
        retry: 0,
        staleTime: Infinity,
        refetchOnMount: "always",
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        refetchInterval: false,
    });
    const save = mutate(
        ["save-app-governance", organizationUID ?? "global"],
        async (input: { mode: TAppGovernanceMode | null; expected_revision: string }) => (await api.put<IAppGovernance>(path, input, config)).data,
        { retry: 0, onSuccess: (governance) => queryClient.setQueryData(queryKey, governance) }
    );
    return { load, save };
};

export function useManagedAppOrganizations(cursor?: string) {
    const { query } = useQueryMutation();
    return query(
        ["app-governance-organizations", cursor ?? ""],
        async () =>
            (
                await api.get<{ items: { uid: string; name: string }[]; next_cursor: string | null }>("/settings/apps/governance/organizations", {
                    params: { cursor },
                    env: { interceptToast: true } as never,
                })
            ).data,
        { retry: 0, refetchOnWindowFocus: false, refetchOnReconnect: false }
    );
}
