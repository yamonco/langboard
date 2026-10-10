/** Comment pane split ratio logic: clamp, persist, and derive CSS values. */

export const PANE_MIN_RATIO = 0.4;
export const PANE_MAX_RATIO = 0.55;
export const PANE_DEFAULT_RATIO = 0.45;
export const PANE_STORAGE_KEY = "card-viewer-comment-pane-ratio";

/**
 * Clamp a ratio to the allowed 40%–55% range.
 */
export const clampPaneRatio = (ratio: number): number => {
    if (Number.isNaN(ratio) || !Number.isFinite(ratio)) {
        return PANE_DEFAULT_RATIO;
    }
    return Math.min(PANE_MAX_RATIO, Math.max(PANE_MIN_RATIO, ratio));
};

/**
 * Compute the comment pane ratio from a drag position within the container.
 */
export const ratioFromPointer = (pointerX: number, containerWidth: number): number => {
    if (containerWidth <= 0) {
        return PANE_DEFAULT_RATIO;
    }
    const rawRatio = 1 - pointerX / containerWidth;
    return clampPaneRatio(rawRatio);
};

/**
 * Save the ratio to the user's profile settings (one value, not per-card).
 */
export const savePaneRatio = (ratio: number): void => {
    try {
        localStorage.setItem(PANE_STORAGE_KEY, String(clampPaneRatio(ratio)));
    } catch {
        // Storage unavailable (private browsing, quota); the default is used.
    }
};

/**
 * Load the saved ratio, returning the default if not stored or invalid.
 */
export const loadPaneRatio = (): number => {
    try {
        const stored = localStorage.getItem(PANE_STORAGE_KEY);
        if (stored === null) {
            return PANE_DEFAULT_RATIO;
        }
        return clampPaneRatio(parseFloat(stored));
    } catch {
        return PANE_DEFAULT_RATIO;
    }
};

/**
 * Derive the CSS width percentages for description and comment panes.
 */
export const paneWidths = (ratio: number): { description: string; comment: string } => {
    const clamped = clampPaneRatio(ratio);
    const commentPercent = Math.round(clamped * 100);
    return {
        description: `${100 - commentPercent}%`,
        comment: `${commentPercent}%`,
    };
};
