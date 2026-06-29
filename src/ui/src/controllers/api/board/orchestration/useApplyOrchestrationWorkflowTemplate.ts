import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectColumn } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IApplyOrchestrationWorkflowTemplateForm {
    project_uid: string;
}

interface IApplyOrchestrationWorkflowTemplateResponse {
    columns: ProjectColumn.Interface[];
}

const useApplyOrchestrationWorkflowTemplate = (
    options?: TMutationOptions<IApplyOrchestrationWorkflowTemplateForm, IApplyOrchestrationWorkflowTemplateResponse>
) => {
    const { mutate } = useQueryMutation();

    const applyWorkflowTemplate = async (params: IApplyOrchestrationWorkflowTemplateForm): Promise<IApplyOrchestrationWorkflowTemplateResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.ORCHESTRATION.APPLY_WORKFLOW_TEMPLATE, {
            uid: params.project_uid,
        });
        const res = await api.post<IApplyOrchestrationWorkflowTemplateResponse>(
            url,
            {},
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        ProjectColumn.Model.fromArray(res.data.columns, true);
        return res.data;
    };

    const result = mutate(["apply-orchestration-workflow-template"], applyWorkflowTemplate, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useApplyOrchestrationWorkflowTemplate;
