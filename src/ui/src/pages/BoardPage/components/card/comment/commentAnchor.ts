import type { ICardCommentAnchor } from "@/core/models/types/card-comment-anchor.type";

export type { ICardCommentAnchor } from "@/core/models/types/card-comment-anchor.type";

const CONTEXT_LENGTH = 256;
const MAX_QUOTE_LENGTH = 4096;
const MAX_PREVIEW_LENGTH = 240;
const SLATE_ELEMENT_SELECTOR = "[data-slate-node=element]";

export const normalizeAnchorText = (value: string): string =>
    value
        .replace(/\uFEFF/g, "")
        .replace(/\s+/g, " ")
        .trim();

export const normalizeAnchorPreview = (value: string): string =>
    normalizeAnchorText(
        value
            .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
            .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
            .replace(/[`*_>#~-]/g, " ")
    ).slice(0, MAX_PREVIEW_LENGTH);

const getTextBeforeRange = (root: HTMLElement, range: Range): string => {
    const before = range.cloneRange();
    before.selectNodeContents(root);
    before.setEnd(range.startContainer, range.startOffset);
    return normalizeAnchorText(before.toString()).slice(-CONTEXT_LENGTH);
};

const getTextAfterRange = (root: HTMLElement, range: Range): string => {
    const after = range.cloneRange();
    after.selectNodeContents(root);
    after.setStart(range.endContainer, range.endOffset);
    return normalizeAnchorText(after.toString()).slice(0, CONTEXT_LENGTH);
};

const getBlockElements = (root: HTMLElement): HTMLElement[] =>
    Array.from(root.querySelectorAll<HTMLElement>(SLATE_ELEMENT_SELECTOR)).filter((element) => {
        const parentBlock = element.parentElement?.closest(SLATE_ELEMENT_SELECTOR);
        return !parentBlock || !root.contains(parentBlock);
    });

const findContainingBlock = (root: HTMLElement, node: Node): HTMLElement | null => {
    const element = node instanceof HTMLElement ? node : node.parentElement;
    let block = element?.closest<HTMLElement>(SLATE_ELEMENT_SELECTOR) ?? null;
    if (!block || !root.contains(block)) return null;
    for (
        let parent = block.parentElement?.closest<HTMLElement>(SLATE_ELEMENT_SELECTOR);
        parent && root.contains(parent);
        parent = block.parentElement?.closest<HTMLElement>(SLATE_ELEMENT_SELECTOR)
    ) {
        block = parent;
    }
    return block;
};

export const captureCardCommentAnchor = (root: HTMLElement, selection: Selection | null): ICardCommentAnchor | null => {
    if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) {
        return null;
    }

    const range = selection.getRangeAt(0);
    if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) {
        return null;
    }

    const exact = normalizeAnchorText(selection.toString());
    if (!exact || exact.length > MAX_QUOTE_LENGTH) {
        return null;
    }

    const blocks = getBlockElements(root);
    const startBlock = findContainingBlock(root, range.startContainer);
    const endBlock = findContainingBlock(root, range.endContainer);
    const startIndex = startBlock ? blocks.indexOf(startBlock) : -1;
    const endIndex = endBlock ? blocks.indexOf(endBlock) : -1;
    if (!startBlock || !endBlock || startIndex < 0 || endIndex < 0) {
        return null;
    }

    return {
        type: "TextQuoteSelector",
        version: 1,
        exact,
        prefix: getTextBeforeRange(root, range),
        suffix: getTextAfterRange(root, range),
        start_block: normalizeAnchorText(startBlock.textContent ?? ""),
        end_block: normalizeAnchorText(endBlock.textContent ?? ""),
        start_path: [startIndex],
        end_path: [endIndex],
    };
};

export const resolveCardCommentAnchorIndex = (anchor: ICardCommentAnchor, blockTexts: string[]): number | null => {
    const exact = normalizeAnchorText(anchor.exact);
    if (!exact) return null;
    const blocks = blockTexts.map(normalizeAnchorText);
    const offsets: number[] = [];
    let length = 0;
    for (const block of blocks) {
        offsets.push(length);
        length += block.length + 1;
    }
    const text = blocks.join(" ");
    const prefix = normalizeAnchorText(anchor.prefix);
    const suffix = normalizeAnchorText(anchor.suffix);
    let blockIndex = 0;
    let bestScore = -1;
    const bestBlocks = new Set<number>();
    for (let position = text.indexOf(exact); position >= 0; position = text.indexOf(exact, position + 1)) {
        while (blockIndex + 1 < offsets.length && offsets[blockIndex + 1] <= position) blockIndex++;
        const before = text.slice(Math.max(0, position - CONTEXT_LENGTH - 1), position).trim();
        const after = text.slice(position + exact.length, position + exact.length + CONTEXT_LENGTH + 1).trim();
        let score = 0;
        for (let i = 1; i <= Math.min(before.length, prefix.length); i++) {
            if (before.at(-i) !== prefix.at(-i)) break;
            score++;
        }
        for (let i = 0; i < Math.min(after.length, suffix.length); i++) {
            if (after[i] !== suffix[i]) break;
            score++;
        }
        if (score > bestScore) {
            bestScore = score;
            bestBlocks.clear();
        }
        if (score === bestScore) bestBlocks.add(blockIndex);
    }
    // A stale position or fuzzy resemblance cannot establish the quoted block's identity.
    return bestBlocks.size === 1 ? [...bestBlocks][0] : null;
};

export const resolveCardCommentAnchorElement = (root: HTMLElement, anchor: ICardCommentAnchor): HTMLElement | null => {
    const blocks = getBlockElements(root);
    const index = resolveCardCommentAnchorIndex(
        anchor,
        blocks.map((block) => block.textContent ?? "")
    );
    return index === null ? null : blocks[index];
};
