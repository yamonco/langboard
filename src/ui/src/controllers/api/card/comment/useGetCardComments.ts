import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectCardComment } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IGetCardCommentsForm {
    project_uid: string;
    card_uid: string;
}

export interface IGetCardCommentsResponse {
    comments: ProjectCardComment.TModel[];
}

const useGetCardComments = (params: IGetCardCommentsForm, options?: TQueryOptions<unknown, IGetCardCommentsResponse>) => {
    const { query } = useQueryMutation();

    const getCardComments = async () => {
        const existingCommentUIDs = new Set(
            ProjectCardComment.Model.getModels((model) => model.card_uid === params.card_uid).map((model) => model.uid)
        );
        const url = Utils.String.format(Routing.API.BOARD.CARD.COMMENT.GET_LIST, { uid: params.project_uid, card_uid: params.card_uid });
        const res = await api.get(url, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        const comments = ProjectCardComment.Model.fromArray(res.data.comments);
        const commentUIDs = new Set<string>(comments.map((comment) => comment.uid));

        ProjectCardComment.Model.deleteModels(
            (model) => model.card_uid === params.card_uid && existingCommentUIDs.has(model.uid) && !commentUIDs.has(model.uid)
        );

        return {
            comments,
        };
    };

    const result = query([`get-card-comments-${params.project_uid}-${params.card_uid}`], getCardComments, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: false,
    });

    return result;
};

export default useGetCardComments;
