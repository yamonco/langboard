import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { MetadataModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IRecordOrchestrationBypassForm {
    project_uid: string;
    card_uid: string;
    allowed?: bool;
    reason?: string;
    risk_level?: string;
    action_type?: string;
    requires_approval?: bool;
    thread_id?: string;
    session_id?: string;
    run_id?: string;
    origin_type?: string;
    scope_table?: string;
    scope_uid?: string;
    document_name?: string;
    permission?: string;
    tool_name?: string;
    api_name?: string;
    preview?: Record<string, unknown>;
    request_payload?: Record<string, unknown>;
}

interface IRecordOrchestrationBypassResponse {
    metadata: Record<string, string>;
    approval_request?: Record<string, unknown> | null;
}

const useRecordOrchestrationBypass = (options?: TMutationOptions<IRecordOrchestrationBypassForm, IRecordOrchestrationBypassResponse>) => {
    const { mutate } = useQueryMutation();

    const recordBypass = async (params: IRecordOrchestrationBypassForm): Promise<IRecordOrchestrationBypassResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.ORCHESTRATION.RECORD_BYPASS, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const res = await api.put<IRecordOrchestrationBypassResponse>(
            url,
            {
                allowed: params.allowed,
                reason: params.reason,
                risk_level: params.risk_level,
                action_type: params.action_type,
                requires_approval: params.requires_approval,
                thread_id: params.thread_id,
                session_id: params.session_id,
                run_id: params.run_id,
                origin_type: params.origin_type,
                scope_table: params.scope_table,
                scope_uid: params.scope_uid,
                document_name: params.document_name,
                permission: params.permission,
                tool_name: params.tool_name,
                api_name: params.api_name,
                preview: params.preview,
                request_payload: params.request_payload,
            },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        const existingMetadata = MetadataModel.Model.getModel(params.card_uid);
        MetadataModel.Model.fromOne(
            {
                uid: params.card_uid,
                type: "card",
                metadata: {
                    ...(existingMetadata?.metadata ?? {}),
                    ...res.data.metadata,
                },
                created_at: new Date(),
                updated_at: new Date(),
            },
            true
        );
        return res.data;
    };

    const result = mutate(["record-orchestration-bypass"], recordBypass, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useRecordOrchestrationBypass;
