/** Cardify selection: extract chosen body text into a child card with a link back. */

export interface ICardifySelectionForm {
    project_uid: string;
    parent_card_uid: string;
    selected_markdown: string;
}

export interface ICardifySelectionResult {
    child_card_uid: string;
    child_card_title: string;
    link_markdown: string;
    remaining_markdown: string;
}

/**
 * Derive a concise child card title from the selected body text.
 * Uses the first meaningful line, trimmed to a maximum length.
 */
export const deriveCardTitle = (markdown: string, maxLength = 80): string => {
    const firstLine = markdown
        .split("\n")
        .map((line) => line.replace(/^#{1,6}\s+/g, "").replace(/^[-*+]\s+/g, "").trim())
        .find((line) => line.length > 0) || "Untitled";
    return firstLine.length > maxLength ? `${firstLine.slice(0, maxLength - 3)}...` : firstLine;
};

/**
 * Build the markdown link for the created child card.
 */
export const buildCardLink = (title: string): string => `[[${title}]]`;

/**
 * Remove the selected fragment from the parent body and insert the link.
 * The editor provides block-level markdown; we replace the exact selected
 * text fragment and preserve everything else.
 */
export const replaceSelectionWithLink = (fullMarkdown: string, selectedMarkdown: string, link: string): string => {
    const index = fullMarkdown.indexOf(selectedMarkdown);
    if (index === -1) {
        return fullMarkdown;
    }
    return fullMarkdown.slice(0, index) + link + fullMarkdown.slice(index + selectedMarkdown.length);
};

/**
 * Validate that the selection is cardifiable: non-empty, not just whitespace,
 * and not excessively short (a single word is usually a link, not a card).
 */
export const isCardifiableSelection = (markdown: string): boolean => {
    const trimmed = markdown.trim();
    return trimmed.length >= 3 && trimmed.length <= 16000;
};
