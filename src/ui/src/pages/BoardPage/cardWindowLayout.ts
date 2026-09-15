// Non-modal card windows leave the existing h-16 application header interactive.
export const CARD_WINDOW_OVERLAY_CLASS = "!top-16";
export const CARD_WINDOW_EMBEDDED_OVERLAY_CLASS = "!absolute !inset-0";
export const CARD_WINDOW_HEIGHT_CLASS =
    "h-[calc(100dvh-theme(spacing.16)-theme(spacing.6))] max-h-[calc(100dvh-theme(spacing.16)-theme(spacing.6))] " +
    "sm:h-[calc(100dvh-theme(spacing.16)-theme(spacing.8))] sm:max-h-[calc(100dvh-theme(spacing.16)-theme(spacing.8))]";
