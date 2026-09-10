"use client";

import * as React from "react";
import type { TPlaceholderElement } from "platejs";
import type { PlateElementProps } from "platejs/react";
import { PlaceholderPlugin, PlaceholderProvider, updateUploadHistory } from "@platejs/media/react";
import { AudioLines, FileUp, Film, ImageIcon, Loader2Icon } from "lucide-react";
import { KEYS } from "platejs";
import { PlateElement, useEditorPlugin, withHOC } from "platejs/react";
import { useFilePicker } from "use-file-picker";
import { cn } from "@/core/utils/ComponentUtils";
import { useUploadFile } from "@/components/plate-ui/uploadthing";
import { getInitialImageWidth } from "@/components/plate-ui/media-image-width";
import { useTranslation } from "react-i18next";
import { Utils } from "@langboard/core/utils";

const CONTENT: Record<
    string,
    {
        accept: string[];
        content: React.ReactNode;
        icon: React.ReactNode;
    }
> = {
    [KEYS.audio]: {
        accept: ["audio/*"],
        content: "editor.Add an audio file",
        icon: <AudioLines />,
    },
    [KEYS.file]: {
        accept: ["*"],
        content: "editor.Add a file",
        icon: <FileUp />,
    },
    [KEYS.img]: {
        accept: ["image/*"],
        content: "editor.Add an image",
        icon: <ImageIcon />,
    },
    [KEYS.video]: {
        accept: ["video/*"],
        content: "editor.Add a video",
        icon: <Film />,
    },
};

export const PlaceholderElement = withHOC(PlaceholderProvider, function PlaceholderElement(props: PlateElementProps<TPlaceholderElement>) {
    const [t] = useTranslation();
    const { editor, element } = props;
    const { api } = useEditorPlugin(PlaceholderPlugin);
    const { isUploading, progress, uploadedFile, uploadFile, uploadingFile } = useUploadFile();
    const loading = isUploading && uploadingFile;
    const currentContent = typeof element.mediaType === "string" ? CONTENT[element.mediaType] : undefined;
    const isImage = element.mediaType === KEYS.img;
    const imageRef = React.useRef<HTMLImageElement>(null);

    const replaceCurrentPlaceholder = React.useCallback(
        (file: File) => {
            if (typeof element.id !== "string") {
                return;
            }

            void uploadFile(file);
            api.placeholder.addUploadingFile(element.id, file);
        },
        [element]
    );

    const { openFilePicker } = useFilePicker({
        accept: currentContent?.accept ?? [],
        multiple: true,
        readFilesContent: false,
        onFilesSelected: ({ plainFiles: updatedFiles }) => {
            if (!updatedFiles?.length) {
                return;
            }

            const firstFile = updatedFiles[0];
            const restFiles = updatedFiles.slice(1);

            replaceCurrentPlaceholder(firstFile);

            if (restFiles.length > 0) {
                const dataTransfer = new DataTransfer();
                restFiles.forEach((file) => dataTransfer.items.add(file));
                editor.getTransforms(PlaceholderPlugin).insert.media(dataTransfer.files);
            }
        },
    });

    React.useEffect(() => {
        const placeholderId = element.id;
        const mediaType = element.mediaType;
        if (!uploadedFile || typeof placeholderId !== "string" || typeof mediaType !== "string") return;

        const path = editor.api.findPath(element);
        const image = imageRef.current;
        const imageWidth = image?.naturalWidth && image.clientWidth ? getInitialImageWidth(image) : undefined;

        editor.tf.withoutSaving(() => {
            editor.tf.removeNodes({ at: path });

            const node = {
                children: [{ text: "" }],
                isUpload: true,
                name: mediaType === KEYS.file ? uploadedFile.name : "",
                placeholderId,
                type: mediaType,
                url: uploadedFile.url,
                ...(imageWidth === undefined ? {} : { width: imageWidth }),
            };

            editor.history.undos.reverse().forEach((batch) => {
                const insertedPlaceholder = batch.operations.some(
                    (operation) =>
                        operation.type === "insert_node" &&
                        Utils.Type.isObject<Record<string, unknown>>(operation.node) &&
                        operation.node.id === node.placeholderId
                );
                if (insertedPlaceholder) {
                    Object.assign(batch, { [PlaceholderPlugin.key]: true });
                }
            });

            editor.tf.insertNodes(node, { at: path });

            updateUploadHistory(editor, node);
        });

        api.placeholder.removeUploadingFile(placeholderId);
    }, [uploadedFile, element]);

    // React dev mode will call React.useEffect twice
    const isReplaced = React.useRef(false);

    /** Paste and drop */
    React.useEffect(() => {
        if (isReplaced.current) return;

        isReplaced.current = true;
        if (typeof element.id !== "string") return;

        const currentFiles = api.placeholder.getUploadingFile(element.id);

        if (!currentFiles) return;

        replaceCurrentPlaceholder(currentFiles);
    }, []);

    if (!currentContent) {
        return null;
    }

    return (
        <PlateElement className="my-1" {...props}>
            {(!loading || !isImage) && (
                <div
                    className={cn("flex cursor-pointer select-none items-center rounded-sm bg-muted p-3 pr-9 hover:bg-primary/10")}
                    onClick={() => !loading && openFilePicker()}
                    contentEditable={false}
                >
                    <div className="relative mr-3 flex text-muted-foreground/80 [&_svg]:size-6">{currentContent.icon}</div>
                    <div className="whitespace-nowrap text-sm text-muted-foreground">
                        <div>
                            {loading
                                ? uploadingFile?.name
                                : Utils.Type.isString(currentContent.content)
                                  ? t(currentContent.content)
                                  : currentContent.content}
                        </div>

                        {loading && !isImage && (
                            <div className="mt-1 flex items-center gap-1.5">
                                <div>{Utils.String.formatBytes(uploadingFile?.size ?? 0)}</div>
                                <div>–</div>
                                <div className="flex items-center">
                                    <Loader2Icon className="mr-1 size-3.5 animate-spin text-muted-foreground" />
                                    {progress ?? 0}%
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {isImage && loading && <ImageProgress file={uploadingFile} imageRef={imageRef} progress={progress} />}

            {props.children}
        </PlateElement>
    );
});

export function ImageProgress({
    className,
    file,
    imageRef,
    progress = 0,
}: {
    file: File;
    className?: string;
    imageRef?: React.RefObject<HTMLImageElement | null>;
    progress?: number;
}) {
    const [objectUrl, setObjectUrl] = React.useState<string | null>(null);

    React.useEffect(() => {
        const url = URL.createObjectURL(file);
        setObjectUrl(url);

        return () => {
            URL.revokeObjectURL(url);
        };
    }, [file]);

    if (!objectUrl) {
        return null;
    }

    return (
        <div className={cn("relative", className)} contentEditable={false}>
            <img ref={imageRef} className="mx-auto h-auto w-full max-w-2xl rounded-sm object-cover" alt={file.name} src={objectUrl} />
            {progress < 100 && (
                <div className="absolute bottom-1 right-1 flex items-center space-x-2 rounded-full bg-black/50 px-1 py-0.5">
                    <Loader2Icon className="size-3.5 animate-spin text-muted-foreground" />
                    <span className="text-xs font-medium text-white">{Math.round(progress)}%</span>
                </div>
            )}
        </div>
    );
}
