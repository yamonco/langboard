/** Block-level anchor utilities for the mini-options hover menu. */

export interface IBlockAnchor {
    id: string;
    type: "heading" | "paragraph" | "list" | "code" | "quote";
    text: string;
    line: number;
}

export interface IBlockAnchorResult {
    anchors: IBlockAnchor[];
    total_blocks: number;
}

const HEADING_RE = /^(#{1,6})\s+(.+)$/;
const LIST_RE = /^[\t ]*[-*+]\s+(.+)$/;
const CODE_RE = /^```/;
const QUOTE_RE = /^>\s+(.+)$/;

let counter = 0;
const nextId = (): string => `blk-${Date.now().toString(36)}-${(counter++).toString(36)}`;

/**
 * Parse markdown into block-level anchors with stable IDs.
 * Each heading, list group, code block, and standalone paragraph gets an anchor.
 */
export const parseBlockAnchors = (markdown: string): IBlockAnchorResult => {
    const lines = markdown.split("\n");
    const anchors: IBlockAnchor[] = [];
    let inCodeBlock = false;
    let codeStartLine = -1;
    let paragraphBuffer: string[] = [];
    let paragraphStartLine = -1;
    let listBuffer: string[] = [];
    let listStartLine = -1;

    const flushParagraph = () => {
        if (paragraphBuffer.length > 0) {
            anchors.push({
                id: nextId(),
                type: "paragraph",
                text: paragraphBuffer.join(" ").trim(),
                line: paragraphStartLine,
            });
            paragraphBuffer = [];
        }
    };

    const flushList = () => {
        if (listBuffer.length > 0) {
            anchors.push({
                id: nextId(),
                type: "list",
                text: listBuffer.join(" · ").trim(),
                line: listStartLine,
            });
            listBuffer = [];
        }
    };

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];

        if (CODE_RE.test(line)) {
            flushParagraph();
            flushList();
            if (!inCodeBlock) {
                inCodeBlock = true;
                codeStartLine = i;
            } else {
                inCodeBlock = false;
                anchors.push({
                    id: nextId(),
                    type: "code",
                    text: `code block (lines ${codeStartLine + 1}-${i + 1})`,
                    line: codeStartLine,
                });
            }
            continue;
        }

        if (inCodeBlock) continue;

        const headingMatch = line.match(HEADING_RE);
        if (headingMatch) {
            flushParagraph();
            flushList();
            anchors.push({
                id: nextId(),
                type: "heading",
                text: headingMatch[2].trim(),
                line: i,
            });
            continue;
        }

        const listMatch = line.match(LIST_RE);
        if (listMatch) {
            flushParagraph();
            if (listBuffer.length === 0) listStartLine = i;
            listBuffer.push(listMatch[1].trim());
            continue;
        }

        const quoteMatch = line.match(QUOTE_RE);
        if (quoteMatch) {
            flushParagraph();
            flushList();
            anchors.push({
                id: nextId(),
                type: "quote",
                text: quoteMatch[1].trim(),
                line: i,
            });
            continue;
        }

        if (line.trim() === "") {
            flushParagraph();
            flushList();
            continue;
        }

        flushList();
        if (paragraphBuffer.length === 0) paragraphStartLine = i;
        paragraphBuffer.push(line.trim());
    }

    flushParagraph();
    flushList();

    return { anchors, total_blocks: anchors.length };
};

/**
 * Find the anchor that contains a given line number.
 */
export const findAnchorAtLine = (anchors: IBlockAnchor[], line: number): IBlockAnchor | null => {
    let best: IBlockAnchor | null = null;
    for (const anchor of anchors) {
        if (anchor.line <= line) {
            best = anchor;
        } else {
            break;
        }
    }
    return best;
};
