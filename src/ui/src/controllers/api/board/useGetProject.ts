import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Project, ProjectBotSchedule, ProjectBotScope } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import refreshProjectColumnDock from "@/controllers/api/board/refreshProjectColumnDock";

export interface IGetProjectForm {
    uid: string;
}

export interface IGetProjectResponse {
    project: Project.TModel;
}

const useGetProject = (form: IGetProjectForm, options?: TQueryOptions<unknown, IGetProjectResponse>) => {
    const { query } = useQueryMutation();

    const getProject = async () => {
        const url = Utils.String.format(Routing.API.BOARD.GET, { uid: form.uid });
        const res = await api.get(url, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        const project = Project.Model.fromOne(res.data.project);
        project.last_viewed_at = new Date();

        ProjectBotScope.Model.fromArray(res.data.project_bot_scopes, true);
        ProjectBotSchedule.Model.fromArray(res.data.project_bot_schedules, true);
        await refreshProjectColumnDock(form.uid);

        return {
            project,
        };
    };

    const result = query([`get-project-${form.uid}`], getProject, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: false,
    });
    return result;
};

export default useGetProject;
