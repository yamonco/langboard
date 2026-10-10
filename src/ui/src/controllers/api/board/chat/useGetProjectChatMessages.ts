import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ChatMessageModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import { useRef, useState } from "react";

export interface IGetProjectChatMessagesForm {
    session_uid?: string;
}

const useGetProjectChatMessages = (projectUID: string, limit: number = 20, options?: TMutationOptions<IGetProjectChatMessagesForm>) => {
    const { mutate } = useQueryMutation();
    const [isLastPage, setIsLastPage] = useState(true);
    const lastCurrentDateRef = useRef(new Date());
    const pageRef = useRef(0);
    const lastPagesRef = useRef<Record<string, number>>({});

    const getProjectChatMessages = async (params: IGetProjectChatMessagesForm) => {
        if ((isLastPage && pageRef.current) || !params.session_uid) {
            setIsLastPage(true);
            return;
        }

        if (!ChatMessageModel.Model.getModel((model) => model.chat_session_uid === params.session_uid)) {
            pageRef.current = 0;
        }

        const nextPage = pageRef.current + 1;

        const url = Utils.String.format(Routing.API.BOARD.CHAT.GET_MESSAGES, { uid: projectUID, session_uid: params.session_uid });
        const res = await api.get(url, {
            params: {
                refer_time: lastCurrentDateRef.current,
                page: nextPage,
                limit,
            },
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        ChatMessageModel.Model.fromArray(res.data.histories, true);
        pageRef.current = nextPage;
        setIsLastPage(res.data.histories.length < limit);
    };

    const result = mutate([`get-project-chat-messages-${projectUID}`], getProjectChatMessages, {
        ...options,
        retry: 0,
    });

    return { ...result, isLastPage, setIsLastPage, pageRef, lastCurrentDateRef, lastPagesRef };
};

export default useGetProjectChatMessages;
