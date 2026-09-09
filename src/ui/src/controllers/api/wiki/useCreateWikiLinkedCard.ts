import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectCard } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface ICreateWikiLinkedCardForm {
    project_uid: string;
    wiki_uid: string;
}

export interface ICreateWikiLinkedCardResponse {
    card: ProjectCard.TModel;
    created: boolean;
}

const useCreateWikiLinkedCard = (options?: TMutationOptions<ICreateWikiLinkedCardForm, ICreateWikiLinkedCardResponse>) => {
    const { mutate } = useQueryMutation();

    const createLinkedCard = async (form: ICreateWikiLinkedCardForm): Promise<ICreateWikiLinkedCardResponse> => {
        const url = Utils.String.format(Routing.API.BOARD.WIKI.CREATE_LINKED_CARD, {
            uid: form.project_uid,
            wiki_uid: form.wiki_uid,
        });
        const response = await api.post(url, undefined, { env: { interceptToast: options?.interceptToast } as never });
        return {
            card: ProjectCard.Model.fromOne(response.data.card, true),
            created: response.data.created,
        };
    };

    return mutate<ICreateWikiLinkedCardForm, ICreateWikiLinkedCardResponse>(["create-wiki-linked-card"], createLinkedCard, {
        ...options,
        retry: 0,
    });
};

export default useCreateWikiLinkedCard;
