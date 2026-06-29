import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { MetadataModel, ProjectCard, ProjectCardRelationship } from "@/core/models";
import syncCardRelationships from "@/controllers/socket/card/syncCardRelationships";
import { Utils } from "@langboard/core/utils";
import { IOrchestrationTaskSuggestionForm } from "@/controllers/api/board/orchestration/useRecordOrchestrationSuggestions";

export interface ICreateOrchestrationSuggestionTaskForm {
    project_uid: string;
    card_uid: string;
    suggestion: IOrchestrationTaskSuggestionForm;
    target_column_name?: string;
    relationship_type_uid?: string;
}

interface ICreateOrchestrationSuggestionTaskResponse {
    card: ProjectCard.IStore;
    metadata: Record<string, string>;
    relationships: ProjectCardRelationship.Interface[];
}

const useCreateOrchestrationSuggestionTask = (
    options?: TMutationOptions<ICreateOrchestrationSuggestionTaskForm, ICreateOrchestrationSuggestionTaskResponse>
) => {
    const { mutate } = useQueryMutation();

    const createSuggestionTask = async (params: ICreateOrchestrationSuggestionTaskForm): Promise<ICreateOrchestrationSuggestionTaskResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.ORCHESTRATION.CREATE_SUGGESTION_TASK, {
            uid: params.project_uid,
            card_uid: params.card_uid,
        });
        const res = await api.post<ICreateOrchestrationSuggestionTaskResponse>(
            url,
            {
                suggestion: params.suggestion,
                target_column_name: params.target_column_name,
                relationship_type_uid: params.relationship_type_uid,
            },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        ProjectCard.Model.fromOne(res.data.card, true);
        const existingMetadata = MetadataModel.Model.getModel(res.data.card.uid);
        MetadataModel.Model.fromOne(
            {
                uid: res.data.card.uid,
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
        syncCardRelationships({ card_uid: params.card_uid, relationships: res.data.relationships });
        return res.data;
    };

    const result = mutate(["create-orchestration-suggestion-task"], createSuggestionTask, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useCreateOrchestrationSuggestionTask;
