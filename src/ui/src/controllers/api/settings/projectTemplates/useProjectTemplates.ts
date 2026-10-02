import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Routing } from "@langboard/core/constants";

export interface ITemplateColumn {
    name: string;
    description: string;
    workflow_stage: string | null;
    translations?: Record<string, { name: string; description: string }>;
}
export interface IProjectTemplate {
    uid: string;
    name: string;
    description?: string;
    global_label_uids?: string[];
    columns: string[];
    column_definitions?: ITemplateColumn[];
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

export const useSaveProjectTemplate = () => {
    const { mutate } = useQueryMutation();
    return mutate(
        ["save-project-template"],
        async ({ uid, ...form }: { uid?: string; name: string; description?: string; global_label_uids?: string[]; columns: ITemplateColumn[] }) => {
            const response = uid
                ? await api.put<{ template: IProjectTemplate }>(`/settings/project-templates/${uid}`, form)
                : await api.post<{ template: IProjectTemplate }>("/settings/project-templates", form);
            return response.data.template;
        },
        { retry: 0 }
    );
};
