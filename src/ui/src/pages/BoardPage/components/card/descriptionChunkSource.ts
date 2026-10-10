import type { Node } from "unist";

export function descriptionChunkSource(content: string, nodes: readonly Pick<Node, "position">[]): string {
    if (!nodes.length) return "";
    const start = nodes[0].position?.start.offset;
    const end = nodes[nodes.length - 1].position?.end.offset;
    if (start === undefined || end === undefined || start < 0 || end < start || end > content.length) return content;
    return content.slice(start, end);
}
