import { useQuery } from "@tanstack/react-query";
import { api } from "@/core/helpers/Api";

export interface CatalogApp {
    key: string;
    name: string;
    description?: string;
    version: string;
    app_revision: string | null;
    is_available?: boolean;
    inbound_connection_management?: boolean;
    panel: { url: string; name: string; icon?: string | null } | null;
    capabilities: string[];
    workflow_requirements: { required: string[]; optional: string[] } | null;
    resources: {
        selected_count: number;
        access_counts: Record<string, number>;
        health_counts: Record<string, number>;
        connection_counts: Record<string, number>;
    };
    binding: { uid: string; revision: string; state: string; granted_capabilities: string[]; stage_transitions_enabled: boolean } | null;
}

export default function useBoardAppCatalog(projectUID: string, userUID: string | undefined) {
    return useQuery({
        queryKey: ["board-app-catalog", projectUID, userUID],
        queryFn: async ({ signal }) =>
            (await api.get<{ apps: CatalogApp[] }>(`/board/${projectUID}/settings/apps`, { signal, env: { interceptToast: true } as never })).data
                .apps,
        enabled: !!userUID,
        retry: 0,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
    });
}
