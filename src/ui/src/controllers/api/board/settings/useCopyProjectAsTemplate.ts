import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";

interface ICopyProjectAsTemplateForm {
    project_uid: string;
    name: string;
}

const useCopyProjectAsTemplate = (options?: TMutationOptions<ICopyProjectAsTemplateForm>) => {
    const { mutate } = useQueryMutation();
    return mutate(
        ["copy-project-as-template"],
        async ({ project_uid, name }: ICopyProjectAsTemplateForm) => {
            const url = Utils.String.format(Routing.API.BOARD.COPY_AS_TEMPLATE, { uid: project_uid });
            return (await api.post(url, { name })).data;
        },
        { ...options, retry: 0 }
    );
};

export default useCopyProjectAsTemplate;
