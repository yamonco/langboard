import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import { visit } from "unist-util-visit";

const parser = unified().use(remarkParse).use(remarkGfm);

/** MDX requires self-closing tags. Use Markdown positions to leave code and escaped text intact. */
export function normalizeBreakTags(source: string): string {
    if (!/<br\s*\/?\s*>/i.test(source)) return source;
    const edits: { start: number; end: number }[] = [];
    visit(parser.parse(source), "html", (node) => {
        const start = node.position?.start.offset;
        const end = node.position?.end.offset;
        if (start !== undefined && end !== undefined && /^<br\s*\/?\s*>$/i.test(node.value)) {
            edits.push({ start, end });
        }
    });
    for (const { start, end } of edits.reverse()) {
        source = source.slice(0, start) + "<br />" + source.slice(end);
    }
    return source;
}
