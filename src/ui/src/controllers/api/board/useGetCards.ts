import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { deleteCardModel } from "@/core/helpers/ModelHelper";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import {
    ProjectColumn,
    ProjectCard,
    GlobalRelationshipType,
    MetadataModel,
    ProjectChecklist,
    ProjectColumnBotScope,
    ProjectColumnBotSchedule,
} from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IGetCardsForm {
    project_uid: string;
}

export interface IGetCardsResponse {
    isUpdated: true;
}

interface IGetProjectCardMetadataResponse {
    metadata: Record<string, Record<string, string>>;
}

const useGetCards = (params: IGetCardsForm, options?: TQueryOptions<unknown, IGetCardsResponse>) => {
    const { query } = useQueryMutation();

    const getCards = async (): Promise<IGetCardsResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.GET_CARDS, { uid: params.project_uid });
        const res = await api.get(url, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });
        const metadataUrl = Utils.String.format(Routing.API.METADATA.PROJECT_CARDS, { uid: params.project_uid });
        const metadataRes = await api.get<IGetProjectCardMetadataResponse>(metadataUrl, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        const cardUIDs = new Set<string>(res.data.cards.map((card: ProjectCard.TModel) => card.uid));
        const columnUIDs = new Set<string>(res.data.columns.map((column: ProjectColumn.TModel) => column.uid));

        ProjectCard.Model.fromArray(res.data.cards, true);
        const metadataModels: MetadataModel.Interface[] = Object.entries(metadataRes.data.metadata ?? {}).map(([cardUID, metadata]) => ({
            uid: cardUID,
            type: "card",
            metadata,
            created_at: new Date(),
            updated_at: new Date(),
        }));
        MetadataModel.Model.fromArray(metadataModels, true);
        GlobalRelationshipType.Model.fromArray(res.data.global_relationships, true);
        ProjectColumn.Model.fromArray(res.data.columns, true);
        ProjectChecklist.Model.fromArray(res.data.checklists, true);

        ProjectCard.Model.getModels((model) => model.project_uid === params.project_uid && !cardUIDs.has(model.uid)).forEach((model) => {
            deleteCardModel(model.uid, true);
        });
        ProjectColumn.Model.deleteModels((model) => model.project_uid === params.project_uid && !columnUIDs.has(model.uid));

        ProjectColumnBotScope.Model.fromArray(res.data.column_bot_scopes, true);
        ProjectColumnBotSchedule.Model.fromArray(res.data.column_bot_schedules, true);

        return { isUpdated: true };
    };

    const result = query([`get-cards-${params.project_uid}`, params], getCards, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: false,
    });

    return result;
};

export default useGetCards;
