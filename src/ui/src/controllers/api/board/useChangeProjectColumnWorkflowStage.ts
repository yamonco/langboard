import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectColumn } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IChangeProjectColumnWorkflowStageForm {
    project_uid: string;
    project_column_uid: string;
    workflow_stage: ProjectColumn.Interface["workflow_stage"];
}

const useChangeProjectColumnWorkflowStage = (
    options?: TMutationOptions<IChangeProjectColumnWorkflowStageForm, { workflow_stage: ProjectColumn.Interface["workflow_stage"] }>
) => {
    const { mutate } = useQueryMutation();
    return mutate(
        ["change-project-column-workflow-stage"],
        async (params: IChangeProjectColumnWorkflowStageForm) => {
            const url = Utils.String.format(Routing.API.BOARD.COLUMN.CHANGE_WORKFLOW_STAGE, {
                uid: params.project_uid,
                project_column_uid: params.project_column_uid,
            });
            const response = await api.put<{ workflow_stage: ProjectColumn.Interface["workflow_stage"] }>(url, {
                workflow_stage: params.workflow_stage,
            });
            return response.data;
        },
        { ...options, retry: 0 }
    );
};

export default useChangeProjectColumnWorkflowStage;
