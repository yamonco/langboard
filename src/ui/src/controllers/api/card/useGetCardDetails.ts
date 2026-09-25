import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import {
    ProjectCardBotScope,
    GlobalRelationshipType,
    ProjectCard,
    ProjectCardAttachment,
    ProjectCheckitem,
    ProjectChecklist,
    ProjectColumn,
    ProjectLabel,
} from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IGetCardDetailsForm {
    project_uid: string;
    card_uid: string;
}

export interface IGetCardDetailsResponse {
    card: ProjectCard.TModel;
    attachments: ProjectCardAttachment.TModel[];
    checklists: ProjectChecklist.TModel[];
    global_relationships: GlobalRelationshipType.TModel[];
    project_columns: ProjectColumn.TModel[];
    project_labels: ProjectLabel.TModel[];
    bot_scopes: ProjectCardBotScope.TModel[];
    execution_receipts: {
        generation: number;
        created_at: string;
        checklist_projection: { item_uid: string; kind: string; refs: string[]; is_checked: boolean }[];
        receipt: {
            status: string;
            summary: string;
            artifacts: { type: string; url: string }[];
            checklist_evidence: { item_uid: string; kind: string; refs: string[] }[];
        };
    }[];
}

const useGetCardDetails = (params: IGetCardDetailsForm, options?: TQueryOptions<unknown, IGetCardDetailsResponse>) => {
    const { query } = useQueryMutation();

    const getCardDetails = async () => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.GET_DETAILS, { uid: params.project_uid, card_uid: params.card_uid });
        const res = await api.get(url, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        ProjectCheckitem.Model.fromArray(
            res.data.checklists.flatMap((checklist: { checkitems?: ProjectCheckitem.Interface[] }) => checklist.checkitems ?? []),
            true
        );
        const checklists = ProjectChecklist.Model.fromArray(res.data.checklists, true);
        checklists.forEach((checklist, index) => {
            const checkitems = ProjectCheckitem.Model.fromArray(res.data.checklists[index]?.checkitems ?? [], true);
            checklist.checkitems = checkitems;
        });

        return {
            card: ProjectCard.Model.fromOne(res.data.card),
            attachments: ProjectCardAttachment.Model.fromArray(res.data.attachments, true),
            checklists,
            global_relationships: GlobalRelationshipType.Model.fromArray(res.data.global_relationships, true),
            project_columns: ProjectColumn.Model.fromArray(res.data.project_columns, true),
            project_labels: ProjectLabel.Model.fromArray(res.data.project_labels, true),
            bot_scopes: ProjectCardBotScope.Model.fromArray(res.data.bot_scopes, true),
            execution_receipts: res.data.execution_receipts ?? [],
        };
    };

    const result = query([`get-card-details-${params.project_uid}-${params.card_uid}`], getCardDetails, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: false,
    });

    return result;
};

export default useGetCardDetails;
