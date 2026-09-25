/** Drag execution rules for tree cards: reorder, reparent, group operations. */

import type { ITreeCard } from "./ColumnCardTree.ts";
import { canDropAsChild, TREE_MAX_DEPTH } from "./TreeRenderer.ts";

export type DragPosition = "before" | "after" | "child";

export interface IDragIntent {
    dragged_uid: string;
    target_uid: string;
    position: DragPosition;
}

export interface IDragResult {
    valid: boolean;
    reason: string;
    new_parent_uid: string | null;
    new_order: number;
}

/**
 * Validate and compute the result of a drag intent.
 * Position "child" nests under the target; "before"/"after" reorders as sibling.
 */
export const resolveDragIntent = (
    intent: IDragIntent,
    trees: ITreeCard[]
): IDragResult => {
    const { dragged_uid, target_uid, position } = intent;

    if (dragged_uid === target_uid) {
        return { valid: false, reason: "self", new_parent_uid: null, new_order: 0 };
    }

    const target = findNode(trees, target_uid);
    if (!target) {
        return { valid: false, reason: "target-not-found", new_parent_uid: null, new_order: 0 };
    }

    const dragged = findNode(trees, dragged_uid);
    if (!dragged) {
        return { valid: false, reason: "dragged-not-found", new_parent_uid: null, new_order: 0 };
    }

    if (position === "child") {
        if (!canDropAsChild(dragged_uid, target_uid, trees)) {
            return { valid: false, reason: "cycle-or-depth", new_parent_uid: null, new_order: 0 };
        }
        const siblings = target.children;
        const newOrder = siblings.length > 0 ? Math.max(...siblings.map((s) => s.order)) + 1 : 0;
        return { valid: true, reason: "ok", new_parent_uid: target_uid, new_order: newOrder };
    }

    // before/after: sibling of target (same parent)
    const parentUid = target.parent_uid;

    // Check if this would create a cycle (dragging a parent before/after its own child)
    if (parentUid === dragged_uid) {
        return { valid: false, reason: "would-orphan-self", new_parent_uid: null, new_order: 0 };
    }

    // Find sibling order
    const siblings = parentUid
        ? (findNode(trees, parentUid)?.children ?? [])
        : trees;
    const targetIdx = siblings.findIndex((s) => s.uid === target_uid);
    const newOrder =
        position === "before"
            ? targetIdx > 0
                ? (siblings[targetIdx - 1].order + target.order) / 2
                : target.order - 0.5
            : targetIdx < siblings.length - 1
              ? (target.order + siblings[targetIdx + 1].order) / 2
              : target.order + 1;

    return { valid: true, reason: "ok", new_parent_uid: parentUid, new_order: newOrder };
};

/**
 * Execute a validated drag by mutating the tree structure.
 * Returns a new trees array (immutable update).
 */
export const executeDrag = (
    intent: IDragIntent,
    trees: ITreeCard[]
): ITreeCard[] => {
    const result = resolveDragIntent(intent, trees);
    if (!result.valid) return trees;

    const dragged = findNode(trees, intent.dragged_uid);
    if (!dragged) return trees;

    // Deep clone for immutable update
    const clone = structuredClone(trees);

    // Remove from old position
    const removeFrom = (nodes: ITreeCard[]): boolean => {
        const idx = nodes.findIndex((n) => n.uid === intent.dragged_uid);
        if (idx !== -1) {
            nodes.splice(idx, 1);
            return true;
        }
        return nodes.some((n) => removeFrom(n.children));
    };
    removeFrom(clone);

    // Set new parent and order
    const draggedClone = findNode(clone, intent.dragged_uid);
    const updatedDragged: ITreeCard = {
        ...dragged,
        parent_uid: result.new_parent_uid,
        order: result.new_order,
    };

    if (result.new_parent_uid) {
        const parent = findNode(clone, result.new_parent_uid);
        if (parent) {
            parent.children.push(updatedDragged);
            parent.children.sort((a, b) => a.order - b.order);
        }
    } else {
        clone.push(updatedDragged);
        clone.sort((a, b) => a.order - b.order);
    }

    // Recompute depths
    const recomputeDepth = (nodes: ITreeCard[], depth: number): void => {
        for (const n of nodes) {
            n.depth = depth;
            recomputeDepth(n.children, depth + 1);
        }
    };
    recomputeDepth(clone, 0);

    return clone;
};

/**
 * Find a node by uid in the forest.
 */
const findNode = (nodes: ITreeCard[], uid: string): ITreeCard | null => {
    for (const node of nodes) {
        if (node.uid === uid) return node;
        const found = findNode(node.children, uid);
        if (found) return found;
    }
    return null;
};

/**
 * Group a subtree under a new parent (for bulk operations).
 */
export const groupSubtree = (
    childUids: string[],
    newParentUid: string,
    trees: ITreeCard[]
): ITreeCard[] => {
    let result = trees;
    for (const uid of childUids) {
        result = executeDrag(
            { dragged_uid: uid, target_uid: newParentUid, position: "child" },
            result
        );
    }
    return result;
};
