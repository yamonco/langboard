export const DEFAULT_COMMENT_PANEL_WIDTH = 360;
export const MIN_COMMENT_PANEL_WIDTH = 280;
export const MAX_COMMENT_PANEL_WIDTH = 560;
export const MIN_CARD_BODY_WIDTH = 400;

export function getCommentPanelWidthBounds(sharedWidth: number): { min: number; max: number } {
    const max = Math.max(MIN_COMMENT_PANEL_WIDTH, Math.min(MAX_COMMENT_PANEL_WIDTH, sharedWidth * 0.48, sharedWidth - MIN_CARD_BODY_WIDTH));
    return { min: MIN_COMMENT_PANEL_WIDTH, max };
}

export function clampCommentPanelWidth(width: number, sharedWidth: number): number {
    const { min, max } = getCommentPanelWidthBounds(sharedWidth);
    return Math.min(max, Math.max(min, Number.isFinite(width) ? width : DEFAULT_COMMENT_PANEL_WIDTH));
}
