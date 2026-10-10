import { toMarkdown } from "mdast-util-to-markdown";
import { gfmToMarkdown } from "mdast-util-gfm";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";
import type { Node as MarkdownNode } from "unist";

const MAX_CHUNK_BLOCKS = 10;
const MAX_HEAVY_LIST_ITEMS = 6;
const MAX_HEAVY_PARAGRAPH_LENGTH = 1200;
const PREVIEW_TEXT_LENGTH = 180;

export type TDescriptionChunkType = "heading" | "paragraph" | "list" | "code" | "table" | "quote" | "media" | "mixed";

export interface IMarkdownNode extends Pick<MarkdownNode, "position"> {
    type?: string;
    children?: IMarkdownNode[];
    value?: string;
    alt?: string | null;
    lang?: string | null;
    depth?: number;
}

export interface IDescriptionChunkMetadata {
    type: TDescriptionChunkType;
    heading?: string;
    previewText: string;
    textLength: number;
    isHeavy: boolean;
}

export interface IDescriptionChunk {
    id: string;
    content: string;
    metadata: IDescriptionChunkMetadata;
}

function countMarkdownListItems(node: IMarkdownNode | undefined): number {
    if (!node?.children) {
        return 0;
    }

    return node.children.reduce((count, child) => (child?.type === "listItem" ? count + 1 : count), 0);
}

export function getMarkdownNodeText(node: IMarkdownNode | undefined): string {
    if (!node) {
        return "";
    }

    const ownText = typeof node.value === "string" ? node.value : typeof node.alt === "string" ? node.alt : "";
    if (!node.children?.length) {
        return ownText;
    }

    return [ownText, ...node.children.map(getMarkdownNodeText)].filter(Boolean).join(" ");
}

function getMarkdownTextLength(node: IMarkdownNode | undefined): number {
    return getMarkdownNodeText(node).length;
}

function isHeavyMarkdownBlock(node: IMarkdownNode | undefined): boolean {
    if (!node?.type) {
        return false;
    }

    if (node.type === "table" || node.type === "code" || node.type === "blockquote") {
        return true;
    }

    if (node.type === "list") {
        return countMarkdownListItems(node) >= MAX_HEAVY_LIST_ITEMS;
    }

    if (node.type === "paragraph") {
        return getMarkdownTextLength(node) >= MAX_HEAVY_PARAGRAPH_LENGTH;
    }

    return false;
}

function getChunkType(nodes: IMarkdownNode[]): TDescriptionChunkType {
    if (nodes.length !== 1) {
        return nodes[0]?.type === "heading" ? "heading" : "mixed";
    }

    switch (nodes[0]?.type) {
        case "heading":
            return "heading";
        case "list":
            return "list";
        case "code":
            return "code";
        case "table":
            return "table";
        case "blockquote":
            return "quote";
        case "image":
            return "media";
        default:
            return "paragraph";
    }
}

function createPreviewText(nodes: IMarkdownNode[]): string {
    const text = nodes.map(getMarkdownNodeText).join(" ").replace(/\s+/g, " ").trim();

    return text.length <= PREVIEW_TEXT_LENGTH ? text : `${text.slice(0, PREVIEW_TEXT_LENGTH).trim()}…`;
}

function getChunkHeading(nodes: IMarkdownNode[]): string | undefined {
    const heading = nodes.find((node) => node.type === "heading");
    const text = getMarkdownNodeText(heading).replace(/\s+/g, " ").trim();

    return text || undefined;
}

function serializeChunk(nodes: IMarkdownNode[]): string {
    return toMarkdown({ type: "root", children: nodes } as never, {
        extensions: [gfmToMarkdown()],
    });
}

function createChunk(nodes: IMarkdownNode[], index: number): IDescriptionChunk {
    const textLength = nodes.reduce((sum, node) => sum + getMarkdownTextLength(node), 0);

    return {
        id: `description-chunk-${index}`,
        content: serializeChunk(nodes),
        metadata: {
            type: getChunkType(nodes),
            heading: getChunkHeading(nodes),
            previewText: createPreviewText(nodes),
            textLength,
            isHeavy: nodes.some(isHeavyMarkdownBlock),
        },
    };
}

function createEmptyChunk(): IDescriptionChunk {
    return {
        id: "description-chunk-0",
        content: "",
        metadata: {
            type: "paragraph",
            previewText: "",
            textLength: 0,
            isHeavy: false,
        },
    };
}

export function buildDescriptionChunks(content: string): IDescriptionChunk[] {
    if (!content.trim()) {
        return [createEmptyChunk()];
    }

    const root = unified().use(remarkParse).use(remarkGfm).parse(content) as { children?: IMarkdownNode[] };
    const children = Array.isArray(root.children) ? root.children : [];

    if (!children.length) {
        return [
            {
                id: "description-chunk-0",
                content,
                metadata: {
                    type: "paragraph",
                    previewText: createPreviewText([{ type: "paragraph", children: [{ type: "text", value: content }] }]),
                    textLength: content.length,
                    isHeavy: content.length >= MAX_HEAVY_PARAGRAPH_LENGTH,
                },
            },
        ];
    }

    const grouped: IMarkdownNode[][] = [];
    let current: IMarkdownNode[] = [];

    const flush = () => {
        if (!current.length) {
            return;
        }

        grouped.push(current);
        current = [];
    };

    for (const child of children) {
        if (isHeavyMarkdownBlock(child)) {
            flush();
            grouped.push([child]);
            continue;
        }

        if (child.type === "heading") {
            flush();
            grouped.push([child]);
            continue;
        }

        current.push(child);
        if (current.length >= MAX_CHUNK_BLOCKS) {
            flush();
        }
    }

    flush();
    return grouped.map(createChunk);
}
