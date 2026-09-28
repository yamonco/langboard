import { isAxiosError } from "axios";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Project, ProjectColumn } from "@/core/models";
import { deleteProjectModel } from "@/core/helpers/ModelHelper";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";

export interface IGetProjectsResponse {
    projects: Project.TModel[];
    columns: ProjectColumn.TModel[];
}

const useGetProjects = (options?: TQueryOptions<unknown, IGetProjectsResponse>) => {
    const { query } = useQueryMutation();

    const getProjects = async (): Promise<IGetProjectsResponse | undefined> => {
        try {
            const res = await api.get(Routing.API.DASHBOARD.PROJECTS, {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            });

            const projects = Project.Model.fromArray(res.data.projects, true);
            const columns = ProjectColumn.Model.fromArray(res.data.columns, true);
            const projectUIDs = new Set<string>(projects.map((project) => project.uid));

            Project.Model.getModels((model) => !projectUIDs.has(model.uid)).forEach((model) => {
                deleteProjectModel(ESocketTopic.Dashboard, model.uid);
            });

            return { projects, columns };
        } catch (e) {
            if (!isAxiosError(e)) {
                throw e;
            }

            if (e.status === EHttpStatus.HTTP_404_NOT_FOUND) {
                return undefined;
            }

            throw e;
        }
    };

    const result = query(["get-dashboard-projects"], getProjects, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: options?.refetchOnWindowFocus ?? false,
    });
    return result;
};

export default useGetProjects;
