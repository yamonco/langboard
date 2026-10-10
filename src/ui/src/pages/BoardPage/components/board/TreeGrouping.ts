/** Tree grouping: collapse all, expand all, and grouped-card visual state. */

import type { ITreeCard } from "./ColumnCardTree.ts";
import { computeDisplayList, toggleCollapse, type CollapseState } from "./TreeRenderer.ts";

export interface IGroupSummary {
    total_cards: number;
    root_count: number;
    max_depth: number;
    collapsed_count: number;
    hidden_count: number;
}

/**
 * Summarize the tree state for UI badges.
 */
export const summarizeGroup = (
    trees: ITreeCard[],
    collapsed: CollapseState
): IGroupSummary => {
    const display = computeDisplayList(trees, collapsed);
    const all = flattenAll(trees);

    let maxDepth = 0;
    const walk = (nodes: ITreeCard[]): void => {
        for (const n of nodes) {
            if (n.depth > maxDepth) maxDepth = n.depth;
            walk(n.children);
        }
    };
    walk(trees);

    return {
        total_cards: all.length,
        root_count: trees.length,
        max_depth: maxDepth,
        collapsed_count: collapsed.size,
        hidden_count: all.length - display.length,
    };
};

/**
 * Collapse all nodes that have children.
 */
export const collapseAll = (trees: ITreeCard[]): CollapseState => {
    const collapsed = new Set<string>();
    const walk = (nodes: ITreeCard[]): void => {
        for (const n of nodes) {
            if (n.children.length > 0) collapsed.add(n.uid);
            walk(n.children);
        }
    };
    walk(trees);
    return collapsed;
};

/**
 * Expand all nodes (empty collapse set).
 */
export const expandAll = (_trees: ITreeCard[]): CollapseState => new Set();

/**
 * Toggle a group and all its descendants' collapse state.
 */
export const toggleGroupRecursive = (
    trees: ITreeCard[],
    uid: string,
    collapsed: CollapseState
): CollapseState => {
    const node = findNode(trees, uid);
    if (!node) return collapsed;

    const isCurrentlyCollapsed = collapsed.has(uid);
    const descendants = getDescendantUids(node);
    let next = new Set(collapsed);

    if (isCurrentlyCollapsed) {
        // Expand this node and all descendants
        next.delete(uid);
        for (const d of descendants) next.delete(d);
    } else {
        // Collapse this node (descendants become hidden anyway)
        next.add(uid);
    }

    return next;
};

/**
 * Check if a node's subtree contains any collapsed descendants.
 * Useful for showing a "has hidden children" indicator.
 */
export const hasCollapsedDescendant = (
    trees: ITreeCard[],
    uid: string,
    collapsed: CollapseState
): boolean => {
    const node = findNode(trees, uid);
    if (!node) return false;
    return getDescendantUids(node).some((d) => collapsed.has(d));
};

const flattenAll = (trees: ITreeCard[]): ITreeCard[] => {
    const result: ITreeCard[] = [];
    const walk = (nodes: ITreeCard[]): void => {
        for (const n of nodes) {
            result.push(n);
            walk(n.children);
        }
    };
    walk(trees);
    return result;
};

const findNode = (nodes: ITreeCard[], uid: string): ITreeCard | null => {
    for (const n of nodes) {
        if (n.uid === uid) return n;
        const found = findNode(n.children, uid);
        if (found) return found;
    }
    return null;
};

const getDescendantUids = (node: ITreeCard): string[] => {
    const uids: string[] = [];
    const walk = (children: ITreeCard[]): void => {
        for (const ch of children) {
            uids.push(ch.uid);
            walk(ch.children);
        }
    };
    walk(node.children);
    return uids;
};
