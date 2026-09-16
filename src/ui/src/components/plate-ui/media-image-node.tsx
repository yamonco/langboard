/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import type { TImageElement } from "platejs";
import type { PlateElementProps } from "platejs/react";
import { useDraggable } from "@platejs/dnd";
import { Image, ImagePlugin, useMediaState } from "@platejs/media/react";
import { ResizableProvider, useResizableValue } from "@platejs/resizable";
import { PlateElement, useEditorRef, withHOC } from "platejs/react";
import { cn } from "@/core/utils/ComponentUtils";
import { Caption, CaptionTextarea } from "@/components/plate-ui/caption";
import { MediaToolbar } from "@/components/plate-ui/media-toolbar";
import { insertParagraphBesideBlock } from "@/components/plate-ui/block-gap-insertion";
import { mediaResizeHandleVariants, Resizable, ResizeHandle } from "@/components/plate-ui/resize-handle";
import { useTranslation } from "react-i18next";
import type { MouseEvent } from "react";

export const ImageElement = withHOC(ResizableProvider, function ImageElement(props: PlateElementProps<TImageElement>) {
    const [t] = useTranslation();
    const { align = "center", focused, readOnly, selected } = useMediaState();
    const width = useResizableValue("width");
    const editor = useEditorRef();

    const { isDragging, handleRef } = useDraggable({
        element: props.element,
    });
    const insertParagraphFromGap = (edge: "before" | "after") => (event: MouseEvent<HTMLDivElement>) => {
        if (readOnly) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        insertParagraphBesideBlock(editor, props.element, edge);
    };

    return (
        <MediaToolbar plugin={ImagePlugin}>
            <PlateElement {...props}>
                <div className="h-2.5" contentEditable={false} onMouseDown={insertParagraphFromGap("before")} />
                <figure className="group relative m-0" contentEditable={false}>
                    <Resizable
                        align={align}
                        options={{
                            align,
                            readOnly,
                        }}
                    >
                        <ResizeHandle className={mediaResizeHandleVariants({ direction: "left" })} options={{ direction: "left" }} />
                        <Image
                            ref={handleRef}
                            className={cn(
                                "block w-full max-w-full cursor-pointer object-cover px-0",
                                "rounded-sm",
                                focused && selected && "ring-2 ring-ring ring-offset-2",
                                isDragging && "opacity-50"
                            )}
                            alt={(props.attributes as any).alt}
                        />
                        <ResizeHandle
                            className={mediaResizeHandleVariants({
                                direction: "right",
                            })}
                            options={{ direction: "right" }}
                        />
                    </Resizable>

                    <Caption style={{ width }} align={align}>
                        <CaptionTextarea
                            readOnly={readOnly}
                            onFocus={(e) => {
                                e.preventDefault();
                            }}
                            placeholder={t("editor.Write a caption...")}
                        />
                    </Caption>
                </figure>
                <div className="h-2.5" contentEditable={false} onMouseDown={insertParagraphFromGap("after")} />

                {props.children}
            </PlateElement>
        </MediaToolbar>
    );
});
