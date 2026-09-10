export interface IRelationshipRect {
    left: number;
    top: number;
    right: number;
    bottom: number;
}

export type TRelationshipDirection = "left" | "right" | "up" | "down";

export const intersectRelationshipRects = (first: IRelationshipRect, second: IRelationshipRect): IRelationshipRect | undefined => {
    const result = {
        left: Math.max(first.left, second.left),
        top: Math.max(first.top, second.top),
        right: Math.min(first.right, second.right),
        bottom: Math.min(first.bottom, second.bottom),
    };
    return result.left < result.right && result.top < result.bottom ? result : undefined;
};

export const getRelationshipDirection = (target: IRelationshipRect, viewport: IRelationshipRect): TRelationshipDirection | undefined => {
    if (target.right <= viewport.left) return "left";
    if (target.left >= viewport.right) return "right";
    if (target.bottom <= viewport.top) return "up";
    if (target.top >= viewport.bottom) return "down";
    return undefined;
};

/** Keep the arrow parent-to-child even when the hovered card is the child. */
export const relationshipCurve = (source: { x: number; y: number }, target: { x: number; y: number }, sourceIsParent: boolean) => {
    const [parent, child] = sourceIsParent ? [source, target] : [target, source];
    const curve = Math.max(56, Math.abs(child.x - parent.x) * 0.42);
    return `M ${parent.x} ${parent.y} C ${parent.x + curve} ${parent.y}, ${child.x - curve} ${child.y}, ${child.x} ${child.y}`;
};
