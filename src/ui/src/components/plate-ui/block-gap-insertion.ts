import { KEYS, PathApi, type TElement, type TRange } from "platejs";
import type { PlateEditor } from "platejs/react";

export const insertParagraphBesideBlock = (editor: PlateEditor, element: TElement, edge: "before" | "after") => {
    const path = editor.api.findPath(element);
    if (!path) {
        return;
    }

    const paragraph = {
        children: [{ text: "" }],
        type: KEYS.p,
    };
    const at = edge === "after" ? PathApi.next(path) : path;
    const textPath = [...at, 0];
    const selection: TRange = {
        anchor: { path: textPath, offset: 0 },
        focus: { path: textPath, offset: 0 },
    };

    editor.tf.insertNodes(paragraph, {
        at,
    });
    editor.tf.select(selection, { focus: true });
    window.setTimeout(() => {
        editor.tf.select(selection, { focus: true });
    });
};
