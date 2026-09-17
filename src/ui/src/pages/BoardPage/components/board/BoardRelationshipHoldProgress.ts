export const RELATIONSHIP_HOLD_OPEN_MS = 2_000;
export const RELATIONSHIP_HOLD_RADIUS = 12;
export const RELATIONSHIP_HOLD_CIRCUMFERENCE = 2 * Math.PI * RELATIONSHIP_HOLD_RADIUS;

export const relationshipHoldProgress = (elapsed: number): number => {
    if (!Number.isFinite(elapsed) || elapsed <= 0) return 0;
    return Math.min(elapsed / RELATIONSHIP_HOLD_OPEN_MS, 1);
};

export const relationshipHoldStrokeOffset = (progress: number): number => RELATIONSHIP_HOLD_CIRCUMFERENCE * (1 - relationshipHoldProgress(progress));
