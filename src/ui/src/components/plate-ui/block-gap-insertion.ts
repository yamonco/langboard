import { KEYS, PathApi, type TElement } from "platejs";
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
    editor.tf.insertNodes(paragraph, {
        at,
        select: true,
    });
    window.setTimeout(() => {
        editor.tf.focus();
    });
};
