import { createRoot } from "react-dom/client";
import { createPlateEditor, Plate } from "platejs/react";
import { ImagePlugin } from "@platejs/media/react";
import { ImageElement } from "./media-image-node";
import { MediaPreviewDialog } from "./media-preview-dialog";
import { Editor } from "./editor";
import "@/assets/styles/main.css";

const imageUrl = (width: number, height: number) => {
    const opening = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">`;
    const rectangle = "<rect width='100%' height='100%' fill='teal'/></svg>";
    return `data:image/svg+xml,${encodeURIComponent(opening + rectangle)}`;
};

function Fixture() {
    return (
        <div style={{ width: "min(100%, 320px)", padding: 12 }}>
            {[
                { width: 1800, height: 900 },
                { width: 900, height: 1800 },
            ].map(({ width, height }) => {
                const editor = createPlateEditor({
                    plugins: [ImagePlugin.configure({ render: { node: ImageElement, afterEditable: MediaPreviewDialog } })],
                    value: [{ type: "img", url: imageUrl(width, height), children: [{ text: "" }] }],
                });
                return (
                    <div key={width} className="grid grid-cols-[32px,minmax(0,1fr)] gap-2">
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
    );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
