/* eslint-disable @typescript-eslint/no-explicit-any */
import { MarkdownPlugin, remarkMdx } from "@platejs/markdown";
import { KEYS, bindFirst } from "platejs";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { EscapeMarkdown, InternalLinkMarkdown, MentionMarkdown, CodeDrawingMarkdown } from "@/components/Editor/plugins/markdown";
import { serializeListNumbers } from "./markdown/list-number";

export const MarkdownKit = [
    MarkdownPlugin.configure({
        options: {
            disallowedNodes: [KEYS.suggestion],
            remarkPlugins: [remarkMath, CodeDrawingMarkdown.remark, remarkGfm, remarkMdx, InternalLinkMarkdown.remark, MentionMarkdown.remark],
            rules: {
                ...InternalLinkMarkdown.rules,
                ...(MentionMarkdown.rules as any),
                ...CodeDrawingMarkdown.rules,
            },
        },
    }).extendApi(({ editor }) => ({
        deserialize: bindFirst(EscapeMarkdown.deserialize(false), editor),
        deserializeInlineMd: bindFirst(EscapeMarkdown.deserialize(true), editor),
        serialize: bindFirst(serializeListNumbers, editor),
    })),
];
