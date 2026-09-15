export interface IRelationshipRect {
    left: number;
    top: number;
    right: number;
    bottom: number;
}

export type TRelationshipDirection = "left" | "right" | "up" | "down";

export const relationshipSideCounts = (sourceOrder: number | undefined, targets: { uid: string; order: number | undefined }[]) => {
    const counts = { left: 0, right: 0 };
    if (!Number.isFinite(sourceOrder)) return counts;
    const seen = new Set<string>();
    for (const target of targets) {
        if (seen.has(target.uid) || !Number.isFinite(target.order) || target.order === sourceOrder) continue;
        seen.add(target.uid);
        counts[target.order! < sourceOrder! ? "left" : "right"]++;
    }
    return counts;
};

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

export const getVisibleRelationshipTarget = (
    card: IRelationshipRect,
    viewport: IRelationshipRect,
    title: IRelationshipRect = card
): IRelationshipRect | undefined => (intersectRelationshipRects(title, viewport) ? intersectRelationshipRects(card, viewport) : undefined);

/** Attach to the edge facing the visible card or offscreen shortcut. */
export const relationshipAnchor = (rect: IRelationshipRect, target: { x: number; y: number }) => {
    const center = { x: (rect.left + rect.right) / 2, y: (rect.top + rect.bottom) / 2 };
    if (target.x !== center.x) return { x: target.x < center.x ? rect.left : rect.right, y: center.y };
    return { x: center.x, y: target.y < center.y ? rect.top : rect.bottom };
};

/** Geometry follows column position; arrow semantics remain parent-to-child. */
export const relationshipCurve = (source: { x: number; y: number }, target: { x: number; y: number }, sourceIsParent: boolean) => {
    const [parent, child] = sourceIsParent ? [source, target] : [target, source];
    const curve = Math.max(56, Math.abs(child.x - parent.x) * 0.42) * (child.x < parent.x ? -1 : 1);
    return `M ${parent.x} ${parent.y} C ${parent.x + curve} ${parent.y}, ${child.x - curve} ${child.y}, ${child.x} ${child.y}`;
};
