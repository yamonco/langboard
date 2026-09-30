import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";

interface IAcknowledgeCommentForm {
    project_uid: string;
    card_uid: string;
    comment_uid: string;
    acknowledged: boolean;
}

export default function useAcknowledgeCardComment() {
    const { mutate } = useQueryMutation();
    return mutate(
        ["acknowledge-card-comment"],
        async ({ project_uid, card_uid, comment_uid, acknowledged }: IAcknowledgeCommentForm) => {
            const path = [project_uid, card_uid, comment_uid].map(encodeURIComponent);
            const response = await api.post<{ acknowledged_user_uids: string[] }>(
                `/board/${path[0]}/card/${path[1]}/comment/${path[2]}/acknowledgement`,
                { acknowledged }
            );
            return response.data;
        },
        { retry: 0 }
    );
}
