import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { GraphApprovalRequestModel } from "@/core/models";
import { EGraphApprovalOriginType, EGraphApprovalScopeTable, EGraphApprovalStatus } from "@/core/models/GraphApprovalRequestModel";
import { Utils } from "@langboard/core/utils";

export interface IGetGraphApprovalsForm {
    project_uid: string;
    status?: EGraphApprovalStatus;
    origin_type?: EGraphApprovalOriginType;
    scope_table?: EGraphApprovalScopeTable;
    scope_uid?: string;
    limit?: number;
}

export interface IGetGraphApprovalsResponse {
    approvals: GraphApprovalRequestModel.TModel[];
}

const useGetGraphApprovals = (form: IGetGraphApprovalsForm, options?: TQueryOptions<unknown, IGetGraphApprovalsResponse>) => {
    const { query } = useQueryMutation();

    const getGraphApprovals = async (): Promise<IGetGraphApprovalsResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.GRAPH_APPROVAL.GET_LIST, { uid: form.project_uid });
        const res = await api.get(url, {
            params: {
                status: form.status,
                origin_type: form.origin_type,
                scope_table: form.scope_table,
                scope_uid: form.scope_uid,
                limit: form.limit,
            },
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        const approvals = GraphApprovalRequestModel.Model.fromArray(res.data.approvals, true);
        if (form.status === EGraphApprovalStatus.Pending && !(form.limit && approvals.length >= form.limit)) {
            const approvalUIDs = new Set(approvals.map((approval) => approval.uid));
            GraphApprovalRequestModel.Model.deleteModels(
                (approval) =>
                    approval.project_uid === form.project_uid &&
                    approval.status === EGraphApprovalStatus.Pending &&
                    (!form.origin_type || approval.origin_type === form.origin_type) &&
                    (!form.scope_table || approval.scope_table === form.scope_table) &&
                    (!form.scope_uid || approval.scope_uid === form.scope_uid) &&
                    !approvalUIDs.has(approval.uid)
            );
        }

        return {
            approvals,
        };
    };

    return query(["get-graph-approvals", form], getGraphApprovals, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: false,
    });
};

export default useGetGraphApprovals;
