import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";

interface IGraphApprovalCountResponse {
    count: number;
}

export default function useGetGraphApprovalCount(projectUID: string, options?: TQueryOptions<IGraphApprovalCountResponse>) {
    const { query } = useQueryMutation();
    return query(
        ["get-graph-approval-count", projectUID, "board-scope"],
        async ({ signal }): Promise<IGraphApprovalCountResponse> => {
            const url = Utils.String.format(Routing.API.BOARD.GRAPH_APPROVAL.COUNT, { uid: projectUID });
            const response = await api.get<IGraphApprovalCountResponse>(url, {
                params: { board_scope_only: true },
                signal,
                env: { interceptToast: options?.interceptToast } as never,
            });
            return response.data;
        },
        { ...options, retry: 0, refetchOnWindowFocus: false }
    );
}
