import type { Link, Node, Parent, RootContent } from "mdast";
import type { Plugin } from "unified";
import { visit } from "unist-util-visit";
import { secretReferenceHistoryHref } from "@/core/utils/SecretReferenceLink";
import { SECRET_REFERENCE_KEY, type TSecretReferenceElement } from "../secret-reference-base";

interface SecretReferenceNode extends Node {
    type: typeof SECRET_REFERENCE_KEY;
    uri: string;
}

declare module "mdast" {
    interface RootContentMap {
        secretReference: SecretReferenceNode;
    }
}

/** A canonical reference becomes metadata-only; captions are never secret material. */
export const remark: Plugin = function () {
    return (tree: Node) => {
        visit(tree, "link", (node: Link, index: number | undefined, parent: Parent | undefined) => {
            if (!parent || index === undefined || !secretReferenceHistoryHref(node.url)) return;
            parent.children.splice(index, 1, { type: SECRET_REFERENCE_KEY, uri: node.url } as RootContent);
        });
    };
};

export const rules = {
    secretReference: {
        deserialize: (node: SecretReferenceNode): TSecretReferenceElement => ({
            type: SECRET_REFERENCE_KEY,
            uri: node.uri,
            children: [{ text: "" }],
        }),
        serialize: (node: TSecretReferenceElement): Link => ({
            type: "link",
            url: secretReferenceHistoryHref(node.uri) ? node.uri : "",
            children: [{ type: "text", value: "••••" }],
        }),
    },
};
