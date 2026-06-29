import { sanitizeEditorValue } from "@/components/Editor/utils";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { MetadataModel, ProjectCard } from "@/core/models";
import type { IEditorContent } from "@/core/models/Base";
import { Utils } from "@langboard/core/utils";

export interface IOrchestrationTaskMetadataForm {
    source?: string;
    source_url?: string;
    external_id?: string;
    type?: string;
    assigned_agent?: string;
    assigned_bot_uid?: string;
    acceptance_criteria?: string[];
    risk_level?: string;
    related_files?: string[];
    pr_url?: string;
}

export interface ICreateOrchestrationTaskForm {
    project_uid: string;
    project_column_uid?: string;
    title: string;
    description?: IEditorContent;
    assign_users?: string[];
    metadata?: IOrchestrationTaskMetadataForm;
}

interface ICreateOrchestrationTaskResponse {
    card: ProjectCard.IStore;
    metadata: Record<string, string>;
}

const useCreateOrchestrationTask = (options?: TMutationOptions<ICreateOrchestrationTaskForm, ICreateOrchestrationTaskResponse>) => {
    const { mutate } = useQueryMutation();

    const createOrchestrationTask = async (params: ICreateOrchestrationTaskForm): Promise<ICreateOrchestrationTaskResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.ORCHESTRATION.CREATE_TASK, {
            uid: params.project_uid,
        });
        const res = await api.post<ICreateOrchestrationTaskResponse>(
            url,
            {
                project_column_uid: params.project_column_uid,
                title: params.title,
                description: params.description ? sanitizeEditorValue(params.description) : params.description,
                assign_users: params.assign_users,
                metadata: params.metadata,
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
        return res.data;
    };

    const result = mutate(["create-orchestration-task"], createOrchestrationTask, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useCreateOrchestrationTask;
