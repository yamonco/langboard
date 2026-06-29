import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { MetadataModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IOrchestrationTaskSuggestionForm {
    title: string;
    type?: string;
    assigned_agent?: string;
    assigned_bot_uid?: string;
    risk_level?: string;
    acceptance_criteria?: string[];
    related_files?: string[];
    created_card_uid?: string;
}

export interface IRecordOrchestrationSuggestionsForm {
    project_uid: string;
    card_uid: string;
    suggestions: IOrchestrationTaskSuggestionForm[];
}

interface IRecordOrchestrationSuggestionsResponse {
    metadata: Record<string, string>;
}

const useRecordOrchestrationSuggestions = (
    options?: TMutationOptions<IRecordOrchestrationSuggestionsForm, IRecordOrchestrationSuggestionsResponse>
) => {
    const { mutate } = useQueryMutation();

    const recordSuggestions = async (params: IRecordOrchestrationSuggestionsForm): Promise<IRecordOrchestrationSuggestionsResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.ORCHESTRATION.RECORD_SUGGESTIONS, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const res = await api.put<IRecordOrchestrationSuggestionsResponse>(
            url,
            {
                suggestions: params.suggestions,
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

    const result = mutate(["record-orchestration-suggestions"], recordSuggestions, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useRecordOrchestrationSuggestions;
