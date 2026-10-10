import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Routing } from "@langboard/core/constants";

export interface IProjectTemplate {
    uid: string;
    name: string;
    columns: string[];
    column_descriptions?: string[];
    is_builtin: boolean;
    is_default: boolean;
}

export const useGetProjectTemplates = (options?: TMutationOptions<unknown, IProjectTemplate[]>) => {
    const { mutate } = useQueryMutation();
    return mutate(
        ["get-project-templates"],
        async () => {
            const response = await api.get<{ templates: IProjectTemplate[] }>(Routing.API.SETTINGS.PROJECT_TEMPLATES.GET_LIST);
            return response.data.templates;
        },
        { ...options, retry: 0 }
    );
};

export const useSetDefaultProjectTemplate = (options?: TMutationOptions<{ template_name: string }, IProjectTemplate>) => {
    const { mutate } = useQueryMutation();
    return mutate(
        ["set-default-project-template"],
        async ({ template_name }: { template_name: string }) => {
            const response = await api.put<{ template: IProjectTemplate }>(Routing.API.SETTINGS.PROJECT_TEMPLATES.SET_DEFAULT, {
                template_name,
            });
            return response.data.template;
        },
        { ...options, retry: 0 }
    );
};
