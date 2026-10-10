import { secretReferenceHistoryHref } from "@/core/utils/SecretReferenceLink";
import { createSlatePlugin, ElementApi, type TElement } from "platejs";

export const SECRET_REFERENCE_KEY = "secretReference";
export interface TSecretReferenceElement extends TElement {
    uri: string;
}
export const BaseSecretReferencePlugin = createSlatePlugin({
    key: SECRET_REFERENCE_KEY,
    node: { isElement: true, isInline: true, isVoid: true },
}).overrideEditor(({ editor, tf: { normalizeNode } }) => ({
    transforms: {
        normalizeNode([node, path]) {
            if (node.type === "a" && secretReferenceHistoryHref(node.url)) {
                editor.tf.replaceNodes({ type: SECRET_REFERENCE_KEY, uri: node.url, children: [{ text: "" }] }, { at: path });
                return;
            }
            if (
                node.type === SECRET_REFERENCE_KEY &&
                ElementApi.isElement(node) &&
                (node.children.length !== 1 || node.children[0].text !== "" || Object.keys(node.children[0]).length !== 1)
            ) {
                editor.tf.replaceNodes([{ text: "" }], { at: path, children: true, voids: true, removeNodes: { voids: true } });
                return;
            }
            normalizeNode([node, path]);
        },
    },
}));
