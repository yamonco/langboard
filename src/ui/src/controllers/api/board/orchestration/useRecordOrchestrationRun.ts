import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { MetadataModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IRecordOrchestrationRunForm {
    project_uid: string;
    card_uid: string;
    status: string;
    run_id?: string;
    bot_log_uid?: string;
    assigned_agent?: string;
    summary?: string;
    started_at?: string;
    finished_at?: string;
}

interface IRecordOrchestrationRunResponse {
    metadata: Record<string, string>;
}

const useRecordOrchestrationRun = (options?: TMutationOptions<IRecordOrchestrationRunForm, IRecordOrchestrationRunResponse>) => {
    const { mutate } = useQueryMutation();

    const recordRun = async (params: IRecordOrchestrationRunForm): Promise<IRecordOrchestrationRunResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.ORCHESTRATION.RECORD_RUN, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const res = await api.put<IRecordOrchestrationRunResponse>(
            url,
            {
                status: params.status,
                run_id: params.run_id,
                bot_log_uid: params.bot_log_uid,
                assigned_agent: params.assigned_agent,
                summary: params.summary,
                started_at: params.started_at,
                finished_at: params.finished_at,
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

    return mutate(["record-orchestration-run"], recordRun, {
        ...options,
        retry: 0,
    });
};

export default useRecordOrchestrationRun;
