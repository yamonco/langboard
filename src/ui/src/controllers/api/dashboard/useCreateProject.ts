import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";

interface ICreateProjectForm {
    title: string;
    description?: string;
    project_type: string;
    template_name?: string;
}

interface ICreateProjectResponse {
    project_uid: string;
}

const useCreateProject = (options?: TMutationOptions<ICreateProjectForm, ICreateProjectResponse>) => {
    const { mutate } = useQueryMutation();

    const createProject = async (params: ICreateProjectForm) => {
        const res = await api.post(Routing.API.DASHBOARD.CREATE_PROJECT, params, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        return res.data;
    };

    const result = mutate(["create-project"], createProject, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useCreateProject;
