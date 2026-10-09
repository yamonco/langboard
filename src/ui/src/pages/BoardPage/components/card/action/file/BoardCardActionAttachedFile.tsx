import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Progress from "@/components/base/Progress";
import useUploadCardAttachment from "@/controllers/api/card/attachment/useUploadCardAttachment";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { formatFileSize } from "@/core/utils/LocaleFormat";
import { useTranslation } from "react-i18next";
import { IAttachedFile } from "@/pages/BoardPage/components/card/action/types";
import { memo, useState } from "react";

interface IBoardCardActionAttachedFileProps {
    attachedFile: IAttachedFile;
    deleteFile: (key: string) => void;
}

const BoardCardActionAttachedFile = memo(({ attachedFile, deleteFile }: IBoardCardActionAttachedFileProps) => {
    const { projectUID, card } = useBoardCard();
    const [, i18n] = useTranslation();
    const [isUploading, setIsUploading] = useState(false);
    const [progress, setProgress] = useState(0);
    const [isError, setIsError] = useState(false);
    const { mutateAsync: uploadCardAttachmentMutateAsync } = useUploadCardAttachment();
    attachedFile.upload = async () => {
        setIsUploading(true);

        try {
            await uploadCardAttachmentMutateAsync({
                project_uid: projectUID,
                card_uid: card.uid,
                attachment: attachedFile.file,
                onUploadProgress: (progressEvent) => {
                    const total = progressEvent.total ?? 0;
                    const progress = (progressEvent.loaded / total) * 100;
                    setProgress(progress);
                },
            });
            return attachedFile.uid;
        } catch {
            setIsError(true);
            return undefined;
        }
    };

    return (
        <Flex gap="2" w="full" items="center" className="text-left text-sm">
            <Flex items="center" justify="center" inline w="12" h="9" textSize="xs" rounded="sm" className="bg-muted">
                {attachedFile.file.name.split(".").at(-1)?.toUpperCase() ?? "FILE"}
            </Flex>
            <Flex direction="col" w="full" className="max-w-[calc(100%_-_theme(spacing.24)_+_theme(spacing.2))]">
                <Box className="truncate">{attachedFile.file.name}</Box>
                <Box textSize="xs" className="truncate text-muted-foreground/70">
                    {!isUploading ? (
                        formatFileSize(attachedFile.file.size, i18n.language, 1)
                    ) : (
                        <Progress value={progress} height="2" indicatorClassName={isError ? "bg-destructive" : ""} />
                    )}
                </Box>
            </Flex>
            {!isUploading && (
                <Button variant="destructive" size="icon-sm" className="size-6" disabled={isUploading} onClick={() => deleteFile(attachedFile.uid)}>
                    <IconComponent icon="trash-2" size="4" />
                </Button>
            )}
        </Flex>
    );
});

export default BoardCardActionAttachedFile;
