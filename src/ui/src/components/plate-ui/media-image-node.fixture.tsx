import { createRoot } from "react-dom/client";
import { createPlateEditor, Plate } from "platejs/react";
import { ImagePlugin } from "@platejs/media/react";
import { ImageElement } from "./media-image-node";
import { MediaPreviewDialog } from "./media-preview-dialog";
import ImageThumbnail from "@/components/ImagePreviewDialog/ImageThumbnail";
import Markdown from "@/components/Markdown";
import { createSlateEditor } from "platejs";
import { PlateStatic } from "platejs/static";
import { BaseImagePlugin } from "@platejs/media";
import { ImageElementStatic } from "./media-image-node-static";
import { Editor } from "./editor";
import Dialog from "@/components/base/Dialog";
import { useState } from "react";
import "@/assets/styles/main.css";

const imageUrl = (width: number, height: number) => {
    const opening = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">`;
    const rectangle = "<rect width='100%' height='100%' fill='teal'/></svg>";
    return `data:image/svg+xml,${encodeURIComponent(opening + rectangle)}`;
};

function Fixture() {
    const [opened, setOpened] = useState(true);
    const staticEditor = createSlateEditor({
        plugins: [BaseImagePlugin.withComponent(ImageElementStatic)],
        value: [{ type: "img", url: imageUrl(900, 1800), children: [{ text: "" }] }],
    });
    return (
        <Dialog.Root open={opened} onOpenChange={setOpened}>
            <Dialog.Content>
                <Dialog.Title>Image card</Dialog.Title>
                <Dialog.Description>Read-only image preview</Dialog.Description>
                <div style={{ width: "min(100%, 320px)", padding: 12 }}>
                    <div data-thumbnail-fixture>
                        <ImageThumbnail src={imageUrl(900, 1800)} />
                    </div>
                    <div data-thumbnail-fixture>
                        <PlateStatic editor={staticEditor} />
                    </div>
                    <div data-thumbnail-fixture>
                        <Markdown message={{ content: "![](/src/components/plate-ui/media-image-node.fixture.svg)" }} />
                    </div>
                    {[
                        { width: 1800, height: 900 },
                        { width: 900, height: 1800 },
                    ].map(({ width, height }) => {
                        const editor = createPlateEditor({
                            plugins: [ImagePlugin.configure({ render: { node: ImageElement, afterEditable: MediaPreviewDialog } })],
                            value: [{ type: "img", url: imageUrl(width, height), children: [{ text: "" }] }],
                        });
                        return (
                            <div key={width} data-dynamic-image-fixture className="grid grid-cols-[32px,minmax(0,1fr)] gap-2">
                                <div />
                                <div className="min-w-0 max-w-full">
                                    <div className="flex w-fit max-w-full px-3 py-1.5">
                                        <Plate editor={editor} readOnly>
                                            <Editor variant="ai" />
                                        </Plate>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </Dialog.Content>
        </Dialog.Root>
    );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
