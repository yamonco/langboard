import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import type { IWorkflowStage } from "@/controllers/api/settings/workflowStages/useWorkflowStages";

export default function useProjectWorkflowStages(projectUid: string, enabled: boolean) {
    const { query } = useQueryMutation();
    return query(
        [`project-workflow-stages-${projectUid}`],
        async () => (await api.get<{ stages: IWorkflowStage[] }>(`/board/${projectUid}/workflow-stages`)).data.stages,
        { enabled, retry: 0, staleTime: 30000, refetchOnWindowFocus: false }
    );
}
