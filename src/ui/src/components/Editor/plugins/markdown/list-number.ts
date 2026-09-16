import { ElementApi, KEYS } from "platejs";
import type { Descendant, SlateEditor } from "platejs";
import { getMergedOptionsSerialize, markdownToAstProcessor, serializeMd } from "@platejs/markdown";
import type { DeserializeMdOptions } from "@platejs/markdown";
import type { Root, RootContent } from "mdast";
import { defaultHandlers } from "mdast-util-to-markdown";
import type { Options } from "mdast-util-to-markdown";
import { toggleList } from "@platejs/list";
import { unified } from "unified";

export function formatOrderedList(editor: SlateEditor, { matchString }: { matchString: string }): void {
    toggleList(editor, { listRestart: Number.parseInt(matchString, 10) || 1, listStyleType: KEYS.ol });
}

function orderedNodes(value: Descendant[]): Descendant[] {
    return value.flatMap((node) => {
        if (!ElementApi.isElement(node)) return [];
        return [...(node.listStyleType === "decimal" ? [node] : []), ...orderedNodes(node.children)];
    });
}

function listHandler(extensions: Options[] = []): typeof defaultHandlers.listItem | undefined {
    return extensions.reduce<typeof defaultHandlers.listItem | undefined>(
        (handler, extension) => extension.handlers?.listItem ?? listHandler(extension.extensions ?? []) ?? handler,
        undefined
    );
}

/** Use the native parser's source positions, not a second Markdown grammar. */
export function preserveListNumbers(editor: SlateEditor, source: string, value: Descendant[], options?: DeserializeMdOptions): Descendant[] {
    const numbers: number[] = [];
    const walk = (node: Root | RootContent) => {
        if (node.type === "list") {
            for (const item of node.children) {
                if (node.ordered && item.position?.start.offset !== undefined) {
                    const marker = /^(\d+)[.)](?=\s)/.exec(source.slice(item.position.start.offset));
                    if (marker) numbers.push(Number(marker[1]));
                }
                item.children.forEach(walk);
            }
        } else if ("children" in node) {
            node.children.forEach((child) => walk(child as RootContent));
        }
    };
    walk(markdownToAstProcessor(editor, source, options));
    const nodes = orderedNodes(value);
    // Never attach one source item's number to a different converted item.
    if (numbers.length !== nodes.length) return value;
    nodes.forEach((node, index) => {
        node.listStart = numbers[index];
        node.listRestart = numbers[index];
    });
    return value;
}

/** Let the native handler calculate indentation using each actual marker. */
export function serializeListNumbers(editor: SlateEditor, options?: Parameters<typeof serializeMd>[1]): string {
    const merged = getMergedOptionsSerialize(editor, options);
    const prepare = (value: Descendant[]): Descendant[] =>
        value.map((node) => {
            if (!ElementApi.isElement(node)) return node;
            if (node.type === KEYS.img && node.listStyleType === "decimal") {
                // Native Markdown only groups paragraph blocks into lists.
                const { indent, listStart, listRestart, listStyleType, ...image } = node;
                return { type: KEYS.p, indent, listStart, listRestart, listStyleType, children: [image] };
            }
            return { ...node, children: prepare(node.children) };
        });
    const value = prepare(merged.value ?? editor.children);
    const nodes = orderedNodes(value);
    const extensions = unified()
        .use(merged.remarkPlugins ?? [])
        .freeze()
        .data("toMarkdownExtensions") as Options[] | undefined;
    const native = merged.remarkStringifyOptions?.handlers?.listItem ?? listHandler(extensions) ?? defaultHandlers.listItem;
    let index = 0;
    const serialized = serializeMd(editor, {
        ...merged,
        value,
        remarkStringifyOptions: {
            ...merged.remarkStringifyOptions,
            handlers: {
                ...merged.remarkStringifyOptions?.handlers,
                listItem(node, parent, state, info) {
                    if (parent?.type !== "list" || !parent.ordered) {
                        return native(node, parent, state, info);
                    }
                    const item = nodes[index++];
                    const marker = item?.listRestart ?? item?.listStart ?? 1;
                    if (typeof marker !== "number") return native(node, parent, state, info);
                    return native(
                        node,
                        {
                            ...parent,
                            start: marker,
                        },
                        { ...state, options: { ...state.options, incrementListMarker: false } },
                        info
                    );
                },
            },
        },
    });
<<<<<<< HEAD

    // A wide parent marker makes remark indent child items to its content
    // column. Keep the separating blank line so CommonMark parses them as
    // nested items instead of lazy paragraph continuation text.
    return (
        serialized
            // Underscores are safe literal text outside emphasis spans, but
            // remark escapes them even in ordinary identifiers. Undo only
            // single escapes so intentional backslashes remain intact.
            .replace(/(?<!\\)\\_/g, "_")
            .replace(/^(\s*\d+[.)][^\n]*)\n(?=\s{4,}\d+[.)]\s)/gm, "$1\n\n")
    );
}
