export interface IBoardCardWidgetSummary {
    has_description?: bool;
    count_comment?: number;
}

export interface IBoardCardWidgetVisibility {
    showDescriptionIcon: bool;
    showCommentCount: bool;
}

/**
 * Decide which meta widgets a board card shows from summary fields only.
 *
 * The description icon appears only for cards that actually have body
 * content, and the comment count only when at least one comment exists, so a
 * freshly created title-only card stays minimal.
 */
export const getBoardCardWidgetVisibility = (summary: IBoardCardWidgetSummary): IBoardCardWidgetVisibility => ({
    showDescriptionIcon: summary.has_description === true,
    showCommentCount: (summary.count_comment ?? 0) > 0,
});
