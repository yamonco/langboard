/** Compute per-section comment counts for the description gutter. */

export interface ISectionCommentCount {
    anchor: string;
    count: number;
}

export interface ICommentWithAnchor {
    uid: string;
    section_anchor?: string | null;
}

/**
 * Group comments by their section_anchor and return counts.
 * Comments without an anchor are excluded from the gutter.
 */
export const computeSectionCommentCounts = (comments: ICommentWithAnchor[]): ISectionCommentCount[] => {
    const counts = new Map<string, number>();
    for (const comment of comments) {
        const anchor = comment.section_anchor;
        if (!anchor) continue;
        counts.set(anchor, (counts.get(anchor) ?? 0) + 1);
    }
    return Array.from(counts.entries())
        .map(([anchor, count]) => ({ anchor, count }))
        .sort((a, b) => a.anchor.localeCompare(b.anchor));
};

/**
 * Extract section anchors from markdown headings.
 * A heading like `## Section Name` produces anchor `section-name`.
 */
export const extractSectionAnchors = (markdown: string): string[] => {
    const anchors: string[] = [];
    for (const line of markdown.split("\n")) {
        const match = line.match(/^#{1,6}\s+(.+)$/);
        if (match) {
            const anchor = match[1]
                .trim()
                .toLowerCase()
                .replace(/[^\w가-힣-]+/g, "-")
                .replace(/^-+|-+$/g, "");
            if (anchor) {
                anchors.push(anchor);
            }
        }
    }
    return anchors;
};

/**
 * Build the gutter model: for each section in the body, how many comments are attached.
 * Sections with 0 comments are included so the gutter can render a consistent rail.
 */
export const buildGutterModel = (
    markdown: string,
    comments: ICommentWithAnchor[]
): ISectionCommentCount[] => {
    const sectionAnchors = extractSectionAnchors(markdown);
    const commentCounts = new Map(computeSectionCommentCounts(comments).map((c) => [c.anchor, c.count]));
    return sectionAnchors.map((anchor) => ({
        anchor,
        count: commentCounts.get(anchor) ?? 0,
    }));
};
