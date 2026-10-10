import { api } from "@/core/helpers/Api";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { useEditorData } from "@/core/providers/EditorDataProvider";
import { Utils } from "@langboard/core/utils";
import { EHttpStatus } from "@langboard/core/enums";
import { AxiosProgressEvent } from "axios";
import * as React from "react";
import { useTranslation } from "react-i18next";

export interface UploadedFile {
    name: string;
    url: string;
}

export function useUploadFile() {
    const [t] = useTranslation();
    const { uploadPath, uploadedCallback } = useEditorData();
    const [uploadedFile, setUploadedFile] = React.useState<UploadedFile>();
    const [uploadingFile, setUploadingFile] = React.useState<File>();
    const [progress, setProgress] = React.useState<number>(0);
    const [isUploading, setIsUploading] = React.useState(false);

    async function uploadThing(file: File) {
        if (!uploadPath) {
            return;
        }

        setIsUploading(true);
        setUploadingFile(file);

        const formData = new FormData();
        formData.append("attachment", file);

        try {
            const uploadURL = Utils.String.convertServerFileURL(uploadPath);
            const result = await api.post(uploadURL, formData, {
                onUploadProgress: (progressEvent: AxiosProgressEvent) => {
                    const total = progressEvent.total ?? 0;
                    const progress = (progressEvent.loaded / total) * 100;
                    setProgress(progress);
                },
            });

            const { name, url } = result.data;
            const uploadedFile = {
                name,
                url: Utils.String.convertServerFileURL(url as string),
            };

            setUploadedFile(uploadedFile);
            uploadedCallback?.(result.data);

            return uploadedFile;
        } catch (error) {
            // TODO: Show error message
            const { handle } = setupApiErrorHandler({
                [EHttpStatus.HTTP_404_NOT_FOUND]: {
                    message: t("editor.errors.upload.unknown"),
                    toast: true,
                },
                [EHttpStatus.HTTP_400_BAD_REQUEST]: {
                    message: t("editor.errors.upload.unknown"),
                    toast: true,
                },
                [EHttpStatus.HTTP_500_INTERNAL_SERVER_ERROR]: {
                    message: t("editor.errors.upload.unknown"),
                    toast: true,
                },
            });

            handle(error);
            throw error;
        } finally {
            setProgress(0);
            setIsUploading(false);
            setUploadingFile(undefined);
        }
    }

    return {
        isUploading,
        progress,
        uploadFile: uploadThing,
        uploadedFile,
        uploadingFile,
    };
}
