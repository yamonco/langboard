/** Transform-based card open/close animation constants and helpers. */

export const CARD_ANIMATION_DURATION_MS = 180;
export const CARD_ANIMATION_EASING = "cubic-bezier(0.2, 0.8, 0.2, 1)";

/**
 * Build the CSS properties for the card open animation.
 * Uses transform and opacity only — no layout-triggering properties.
 */
export const cardOpenAnimation = (): string =>
    `transform ${CARD_ANIMATION_DURATION_MS}ms ${CARD_ANIMATION_EASING}, ` +
    `opacity ${CARD_ANIMATION_DURATION_MS}ms ${CARD_ANIMATION_EASING}`;

/**
 * Check if the user prefers reduced motion.
 */
export const prefersReducedMotion = (): boolean =>
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Get the effective animation duration, 0 if reduced motion is preferred.
 */
export const effectiveAnimationDuration = (): number =>
    prefersReducedMotion() ? 0 : CARD_ANIMATION_DURATION_MS;

/**
 * Build the initial (closed) transform for a card at a given position.
 */
export const closedTransform = (rect: DOMRect, targetRect: DOMRect): string => {
    const scaleX = rect.width / Math.max(targetRect.width, 1);
    const scaleY = rect.height / Math.max(targetRect.height, 1);
    const translateX = rect.left - targetRect.left + (rect.width - targetRect.width * scaleX) / 2;
    const translateY = rect.top - targetRect.top + (rect.height - targetRect.height * scaleY) / 2;
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
