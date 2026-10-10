/** Parse markdown checkboxes and convert them to native checklist payloads. */

export interface IParsedCheckboxItem {
    title: string;
    is_checked: boolean;
}

export interface ICheckboxConversionResult {
    items: IParsedCheckboxItem[];
    remaining_markdown: string;
}

const CHECKBOX_LINE = /^[\t ]*(?:[-*+]|\d+\.)\s+\[([ xX])\]\s+(.+)$/;

/**
 * Detect whether a markdown fragment contains at least one checkbox line.
 */
export const hasMarkdownCheckboxes = (markdown: string): boolean => {
    return markdown.split("\n").some((line) => CHECKBOX_LINE.test(line));
};

/**
 * Parse markdown checkbox lines into structured items.
 * Recognizes `- [ ]`, `* [ ]`, `+ [ ]`, `1. [ ]` and their `[x]` variants.
 */
export const parseCheckboxes = (markdown: string): IParsedCheckboxItem[] => {
    const items: IParsedCheckboxItem[] = [];
    for (const line of markdown.split("\n")) {
        const match = line.match(CHECKBOX_LINE);
        if (match) {
            const is_checked = match[1].toLowerCase() === "x";
            const title = match[2].trim();
            if (title) {
                items.push({ title, is_checked });
            }
        }
    }
    return items;
};

/**
 * Remove checkbox lines from the markdown, preserving everything else.
 */
export const stripCheckboxLines = (markdown: string): string => {
    const kept = markdown.split("\n").filter((line) => !CHECKBOX_LINE.test(line));
    return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
};

/**
 * Full conversion: parse checkboxes and strip them from the body.
 * Returns empty items if no checkboxes found.
 */
export const convertMarkdownCheckboxes = (markdown: string): ICheckboxConversionResult => {
    const items = parseCheckboxes(markdown);
    if (!items.length) {
        return { items: [], remaining_markdown: markdown };
    }
    return { items, remaining_markdown: stripCheckboxLines(markdown) };
};
