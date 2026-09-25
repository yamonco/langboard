import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ChatTemplateModel, InternalBotModel, Project, ProjectCard, ProjectColumn } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import refreshProjectColumnDock from "@/controllers/api/board/refreshProjectColumnDock";

export interface IGetProjectDetailsForm {
    uid: string;
}

export interface IGetProjectDetailsResponse {
    project: Project.TModel;
    internal_bots: InternalBotModel.TModel[];
    columns: ProjectColumn.TModel[];
    cards: ProjectCard.TModel[];
}

const useGetProjectDetails = (form: IGetProjectDetailsForm, options?: TQueryOptions<unknown, IGetProjectDetailsResponse>) => {
    const { query } = useQueryMutation();

    const getProjectDetails = async () => {
        const url = Utils.String.format(Routing.API.BOARD.DETAILS, { uid: form.uid });
        const res = await api.get(url, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        const result = {
            project: Project.Model.fromOne(res.data.project),
            internal_bots: InternalBotModel.Model.fromArray(res.data.internal_bots),
            columns: ProjectColumn.Model.fromArray(res.data.columns),
            cards: ProjectCard.Model.fromArray(res.data.cards),
            chat_templates: ChatTemplateModel.Model.fromArray(res.data.chat_templates),
        };
        await refreshProjectColumnDock(form.uid);
        return result;
    };

    const result = query([`get-project-details-${form.uid}`], getProjectDetails, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: false,
    });
    return result;
};

export default useGetProjectDetails;
