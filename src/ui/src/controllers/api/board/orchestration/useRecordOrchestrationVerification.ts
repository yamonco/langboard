import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { MetadataModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IOrchestrationTaskFailureForm {
    status?: string;
    summary?: string;
    cause?: string;
    reproduction?: string[];
    recommendation?: string[];
}

export interface IRecordOrchestrationVerificationForm {
    project_uid: string;
    card_uid: string;
    status: string;
    summary?: string;
    checked_at?: string;
    failure?: IOrchestrationTaskFailureForm;
    target_column_name?: string;
}

interface IRecordOrchestrationVerificationResponse {
    metadata: Record<string, string>;
}

const useRecordOrchestrationVerification = (
    options?: TMutationOptions<IRecordOrchestrationVerificationForm, IRecordOrchestrationVerificationResponse>
) => {
    const { mutate } = useQueryMutation();

    const recordVerification = async (params: IRecordOrchestrationVerificationForm): Promise<IRecordOrchestrationVerificationResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.ORCHESTRATION.RECORD_VERIFICATION, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const res = await api.put<IRecordOrchestrationVerificationResponse>(
            url,
            {
                status: params.status,
                summary: params.summary,
                checked_at: params.checked_at,
                failure: params.failure,
                target_column_name: params.target_column_name,
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

    const result = mutate(["record-orchestration-verification"], recordVerification, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useRecordOrchestrationVerification;
