/** Transform-based card open/close animation constants and helpers. */

export const CARD_ANIMATION_DURATION_MS = 180;
export const CARD_ANIMATION_EASING = "cubic-bezier(0.2, 0.8, 0.2, 1)";

export type CardRect = Pick<DOMRect, "left" | "top" | "width" | "height">;

let pendingOrigin: { projectUID: string; cardUID: string; rect: CardRect; capturedAt: number } | null = null;

export const captureCardOrigin = (projectUID: string, cardUID: string, rect: CardRect): void => {
    pendingOrigin = {
        projectUID,
        cardUID,
        rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
        capturedAt: Date.now(),
    };
};

export const takeCardOrigin = (projectUID: string, cardUID: string): CardRect | null => {
    const origin = pendingOrigin;
    pendingOrigin = null;
    return origin && origin.projectUID === projectUID && origin.cardUID === cardUID && Date.now() - origin.capturedAt < 2000 ? origin.rect : null;
};

/**
 * Build the CSS properties for the card open animation.
 * Uses transform and opacity only — no layout-triggering properties.
 */
export const cardOpenAnimation = (): string =>
    `transform ${CARD_ANIMATION_DURATION_MS}ms ${CARD_ANIMATION_EASING}, ` + `opacity ${CARD_ANIMATION_DURATION_MS}ms ${CARD_ANIMATION_EASING}`;

/**
 * Check if the user prefers reduced motion.
 */
export const prefersReducedMotion = (): boolean => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Get the effective animation duration, 0 if reduced motion is preferred.
 */
export const effectiveAnimationDuration = (): number => (prefersReducedMotion() ? 0 : CARD_ANIMATION_DURATION_MS);

/**
 * Build the initial (closed) transform for a card at a given position.
 */
export const closedTransform = (rect: CardRect, targetRect: CardRect): string => {
    const scaleX = rect.width / Math.max(targetRect.width, 1);
    const scaleY = rect.height / Math.max(targetRect.height, 1);
    const translateX = rect.left - targetRect.left - (targetRect.width - rect.width) / 2;
    const translateY = rect.top - targetRect.top - (targetRect.height - rect.height) / 2;
    return `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})`;
};

/**
 * Get the animation style object, respecting reduced motion.
 */
export const getCardAnimationStyle = (): React.CSSProperties => {
    if (prefersReducedMotion()) {
        return {};
    }
    return {
        transition: cardOpenAnimation(),
        willChange: "transform, opacity",
    };
};
