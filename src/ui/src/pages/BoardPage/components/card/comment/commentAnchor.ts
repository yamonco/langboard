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
    Array.from(root.querySelectorAll<HTMLElement>(SLATE_ELEMENT_SELECTOR)).filter(
        (element) => !element.parentElement?.closest(SLATE_ELEMENT_SELECTOR)
    );

const findContainingBlock = (root: HTMLElement, node: Node): HTMLElement | null => {
    const element = node instanceof HTMLElement ? node : node.parentElement;
    const block = element?.closest<HTMLElement>(SLATE_ELEMENT_SELECTOR) ?? null;
    return block && root.contains(block) ? block : null;
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
    if (!startBlock || !endBlock) {
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
        start_path: [Math.max(0, blocks.indexOf(startBlock))],
        end_path: [Math.max(0, blocks.indexOf(endBlock))],
    };
};

const bigrams = (value: string): Set<string> => {
    const normalized = normalizeAnchorText(value).toLocaleLowerCase();
    if (normalized.length < 2) {
        return new Set(normalized ? [normalized] : []);
    }
    return new Set(Array.from({ length: normalized.length - 1 }, (_, index) => normalized.slice(index, index + 2)));
};

const similarity = (left: string, right: string): number => {
    const leftBigrams = bigrams(left);
    const rightBigrams = bigrams(right);
    if (!leftBigrams.size || !rightBigrams.size) {
        return 0;
    }
    const overlap = [...leftBigrams].filter((value) => rightBigrams.has(value)).length;
    return (2 * overlap) / (leftBigrams.size + rightBigrams.size);
};

export const resolveCardCommentAnchorIndex = (anchor: ICardCommentAnchor, blockTexts: string[]): number | null => {
    const normalizedBlocks = blockTexts.map(normalizeAnchorText);
    const exactBlockIndex = normalizedBlocks.findIndex((text) => text === normalizeAnchorText(anchor.start_block));
    if (exactBlockIndex >= 0) {
        return exactBlockIndex;
    }

    const quoteIndex = normalizedBlocks.findIndex((text) => text.includes(normalizeAnchorText(anchor.exact)));
    if (quoteIndex >= 0) {
        return quoteIndex;
    }

    let bestIndex = -1;
    let bestScore = 0;
    normalizedBlocks.forEach((text, index) => {
        const score = similarity(text, anchor.start_block);
        if (score > bestScore) {
            bestIndex = index;
            bestScore = score;
        }
    });
    if (bestScore >= 0.55) {
        return bestIndex;
    }

    const hintedIndex = anchor.start_path[0];
    return Number.isInteger(hintedIndex) && hintedIndex >= 0 && hintedIndex < blockTexts.length ? hintedIndex : null;
};

export const resolveCardCommentAnchorElement = (root: HTMLElement, anchor: ICardCommentAnchor): HTMLElement | null => {
    const blocks = getBlockElements(root);
    const index = resolveCardCommentAnchorIndex(
        anchor,
        blocks.map((block) => block.textContent ?? "")
    );
    return index === null ? null : blocks[index];
};
