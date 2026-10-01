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
import { mergeLinkedResourceProjection } from "@/controllers/api/board/mergeLinkedResourceProjection";

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
        const cards = res.data.cards.map((card: ProjectCard.Interface) => {
            if (!card.linked_resource) {
                return card;
            }

            const existing = ProjectCard.Model.getModel(card.uid)?.linked_resource;
            return {
                ...card,
                linked_resource: mergeLinkedResourceProjection(card.linked_resource, existing),
            };
        });
        const cardUIDs = new Set<string>(cards.map((card: ProjectCard.Interface) => card.uid));
        const columnUIDs = new Set<string>(res.data.columns.map((column: ProjectColumn.TModel) => column.uid));

        ProjectCard.Model.fromArray(cards, true);
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

    // Optional enrichment must never delay or reject the authorized board snapshot.
    query(
        ["get-board-card-metadata", params.project_uid, result.dataUpdatedAt],
        async ({ signal }) => {
            const url = Utils.String.format(Routing.API.METADATA.PROJECT_CARDS, { uid: params.project_uid });
            const res = await api.get<IGetProjectCardMetadataResponse>(url, { signal, env: { interceptToast: false } as never });
            const models: MetadataModel.Interface[] = Object.entries(res.data.metadata ?? {})
                .filter(([uid]) => ProjectCard.Model.getModel(uid)?.project_uid === params.project_uid)
                .map(([uid, metadata]) => ({ uid, type: "card", metadata, created_at: new Date(), updated_at: new Date() }));
            MetadataModel.Model.fromArray(models, true);
            return res.data;
        },
        {
            // One attempt per successful snapshot; observers cannot retry a failed older snapshot.
            enabled: (enrichment) => result.isEnabled && result.isSuccess && !result.isFetching && enrichment.state.status !== "error",
            staleTime: Infinity,
            gcTime: 0,
            retry: 0,
            refetchInterval: Infinity,
            refetchOnWindowFocus: false,
        }
    );

    return result;
};

export default useGetCards;
