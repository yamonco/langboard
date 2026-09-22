import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { ChatMessageModel } from "@/core/models";
import { EInternalBotRunStatus } from "@/core/constants/InternalBotRun";

export interface IProjectChatRunResponse {
    task_id: string;
    status: EInternalBotRunStatus;
    session_uid: string;
    user_message: ChatMessageModel.Interface;
    ai_message: ChatMessageModel.Interface | null;
    ai_message_uid: string | null;
}

const useGetProjectChatRun = (projectUID: string) => {
    const { mutate } = useQueryMutation();

    return mutate<string, IProjectChatRunResponse>([`get-project-chat-run-${projectUID}`], async (taskId) => {
        const url = Utils.String.format(Routing.API.BOARD.CHAT.GET_RUN, { uid: projectUID, task_id: taskId });
        const response = await api.get<IProjectChatRunResponse>(url, {
            env: { interceptToast: true } as never,
        });
        return response.data;
    });
};

export default useGetProjectChatRun;
