import { createSlatePlugin, type TElement } from "platejs";

export const SECRET_REFERENCE_KEY = "secretReference";
export interface TSecretReferenceElement extends TElement {
    uri: string;
}
export const BaseSecretReferencePlugin = createSlatePlugin({
    key: SECRET_REFERENCE_KEY,
    node: { isElement: true, isInline: true, isVoid: true },
});
