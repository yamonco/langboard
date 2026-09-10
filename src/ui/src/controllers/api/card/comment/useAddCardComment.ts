import { sanitizeEditorValue } from "@/components/Editor/utils";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { IEditorContent } from "@/core/models/Base";
import { Utils } from "@langboard/core/utils";
import type { ICardCommentAnchor } from "@/core/models/types/card-comment-anchor.type";

export interface IAddCardCommentForm {
    project_uid: string;
    card_uid: string;
    content: IEditorContent;
    anchor?: ICardCommentAnchor | null;
}

const useAddCardComment = (options?: TMutationOptions<IAddCardCommentForm>) => {
    const { mutate } = useQueryMutation();

    const addCardComment = async (params: IAddCardCommentForm) => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.COMMENT.ADD, { uid: params.project_uid, card_uid: params.card_uid });
        const res = await api.post(
            url,
            {
                ...sanitizeEditorValue(params.content),
                anchor: params.anchor ?? null,
            },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        return res.data;
    };

    const result = mutate(["add-card-comment"], addCardComment, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useAddCardComment;
