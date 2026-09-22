import { slateNodesToInsertDelta } from "@slate-yjs/core";
import type { Value } from "platejs";
import * as Y from "yjs";

export const prepareRichDraftPatch = (payload: string, deserialize: (markdown: string) => Value): string | null => {
    let request: unknown;
    try {
        request = JSON.parse(payload);
    } catch {
        return null;
    }
    if (
        !request ||
        typeof request !== "object" ||
        !("type" in request) ||
        request.type !== "rich_patch_prepare" ||
        !("request_id" in request) ||
        typeof request.request_id !== "string" ||
        request.request_id.length !== 32 ||
        !("snapshot" in request) ||
        typeof request.snapshot !== "string" ||
        !("value" in request) ||
        typeof request.value !== "string"
    ) {
        return null;
    }

    // Prepare against the owner's snapshot without changing any connected editor.
    const draft = new Y.Doc();
    try {
        Y.applyUpdate(
            draft,
            Uint8Array.from(atob(request.snapshot), (char) => char.charCodeAt(0))
        );
        const vector = Y.encodeStateVector(draft);
        const root = draft.get("content", Y.XmlText);
        const nodes = deserialize(request.value);
        const nextNodes: Value = nodes.length ? nodes : [{ type: "p", children: [{ text: "" }] }];
        draft.transact(() => {
            root.delete(0, root.length);
            root.applyDelta(slateNodesToInsertDelta(nextNodes));
        });
        const update = Y.encodeStateAsUpdate(draft, vector);
        return JSON.stringify({
            type: "rich_patch_prepared",
            request_id: request.request_id,
            update: btoa(Array.from(update, (byte) => String.fromCharCode(byte)).join("")),
        });
    } catch {
        return null;
    } finally {
        draft.destroy();
    }
};
