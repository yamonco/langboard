import { API_URL, IS_PHOENIX_SOCKET_RUNTIME, SOCKET_URL } from "@/constants";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Utils } from "@langboard/core/utils";
import { AxiosProgressEvent } from "axios";

export interface IUploadProjectChatAttachmentForm {
    project_uid: string;
    task_id: string;
    attachment: File;
    onUploadProgress?: (progressEvent: AxiosProgressEvent) => void;
    abortController?: AbortController;
}

export interface IUploadProjectChatAttachmentResponse {
    file_path?: string;
    file_token?: string;
}

const useUploadProjectChatAttachment = (options?: TMutationOptions<IUploadProjectChatAttachmentForm, IUploadProjectChatAttachmentResponse>) => {
    const { mutate } = useQueryMutation();

    const updateProjectChatComment = async (params: IUploadProjectChatAttachmentForm) => {
        const url = Utils.String.format(Routing.API.BOARD.CHAT.UPLOAD, {
            uid: params.project_uid,
        });
        const formData = new FormData();
        formData.append("attachment", params.attachment);
        if (IS_PHOENIX_SOCKET_RUNTIME) {
            formData.append("task_id", params.task_id);
        }
        const res = await api.post(url, formData, {
            baseURL: IS_PHOENIX_SOCKET_RUNTIME ? API_URL : SOCKET_URL,
            withCredentials: true,
            onUploadProgress: params.onUploadProgress,
            signal: params.abortController?.signal,
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        return res.data;
    };

    const result = mutate(["upload-project-chat-attachment"], updateProjectChatComment, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useUploadProjectChatAttachment;
