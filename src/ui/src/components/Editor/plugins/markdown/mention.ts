import { type TMentionElement } from "platejs";
import { convertNodesSerialize, MentionNode as IBaseMentionNode, MdLink, SerializeMdOptions } from "@platejs/markdown";
import type { Node, Parent, Link, RootContent } from "mdast";
import type { Plugin } from "unified";
import { visit } from "unist-util-visit";

export interface IMentionNode extends IBaseMentionNode {
    uid: string;
}

export interface IMentionElement extends TMentionElement {
    key: string;
}

const isAbsoluteWebURL = (value: string): bool => {
    try {
        return ["http:", "https:"].includes(new URL(value).protocol);
    } catch {
        return false;
    }
};

declare module "mdast" {
    interface StaticPhrasingContent {
        mention: IMentionNode;
    }

    interface StaticPhrasingContentMap extends StaticPhrasingContent {}
}
/**
 * A remark plugin that converts <@uid> patterns in text nodes into mention
 * nodes. This plugin runs after remark-gfm and transforms <@uid> patterns
 * into special mention nodes that can be later converted into Plate mention
 * elements.
 */
export const remark: Plugin = function () {
    return (tree: Node) => {
        visit(tree, "link", (node: Link, index: number, parent: Parent | undefined) => {
            if (
                !parent ||
                typeof index !== "number" ||
                isAbsoluteWebURL(node.url) ||
                node.children?.[0].type !== "strong" ||
                node.children[0].children?.[0].type !== "text"
            )
                return;

            const uid = node.url;
            const username = node.children[0].children[0].value.replace(/@/g, "");

            const mentionNode = {
                type: "mention",
                uid,
                username,
                children: [{ type: "text", value: `@${username}` }],
            };

            parent.children.splice(index, 1, mentionNode as RootContent);
        });
    };
};

export const rules = {
    mention: {
        deserialize: (node: IMentionNode): TMentionElement => ({
            children: [{ text: "" }],
            type: "mention",
            key: node.uid,
            value: node.username,
        }),
        serialize: (node: IMentionElement, options: SerializeMdOptions): Link => ({
            children: convertNodesSerialize(
                [
                    {
                        text: `@${node.value.replace(/\s/g, "_")}`,
                        bold: true,
                    },
                ],
                options
            ) as MdLink["children"],
            url: node.key,
            type: "link",
        }),
    },
};
