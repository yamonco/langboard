/** Tree renderer utilities: indentation, collapse state, drag targets. */

import type { ITreeCard } from "./ColumnCardTree.ts";

export const TREE_INDENT_PX = 24;
export const TREE_MAX_DEPTH = 5;

export interface ITreeDisplayItem {
    uid: string;
    title: string;
    depth: number;
    indent_px: number;
    has_children: boolean;
    is_collapsed: boolean;
    is_visible: boolean;
}

export type CollapseState = Set<string>;

/**
 * Compute the display list from a tree, respecting collapse state.
 * Collapsed nodes hide their entire subtree.
 */
export const computeDisplayList = (
    trees: ITreeCard[],
    collapsed: CollapseState
): ITreeDisplayItem[] => {
    const items: ITreeDisplayItem[] = [];

    const walk = (nodes: ITreeCard[], visible: boolean): void => {
        for (const node of nodes) {
            const isCollapsed = collapsed.has(node.uid);
            items.push({
                uid: node.uid,
                title: node.title,
                depth: node.depth,
                indent_px: Math.min(node.depth, TREE_MAX_DEPTH) * TREE_INDENT_PX,
                has_children: node.children.length > 0,
                is_collapsed: isCollapsed,
                is_visible: visible,
            });
            if (!isCollapsed) {
                walk(node.children, visible);
            }
        }
    };

    walk(trees, true);
    return items;
};

/**
 * Toggle a node's collapse state.
 */
export const toggleCollapse = (collapsed: CollapseState, uid: string): CollapseState => {
    const next = new Set(collapsed);
    if (next.has(uid)) {
        next.delete(uid);
    } else {
        next.add(uid);
    }
    return next;
};

/**
 * Determine if a card can be dropped onto a target as a child.
 * Rules: no self-drop, no drop onto own descendant, depth limit.
 */
export const canDropAsChild = (
    draggedUid: string,
    targetUid: string,
    trees: ITreeCard[]
): boolean => {
    if (draggedUid === targetUid) return false;

    const findNode = (nodes: ITreeCard[]): ITreeCard | null => {
        for (const node of nodes) {
            if (node.uid === targetUid) return node;
            const found = findNode(node.children);
            if (found) return found;
        }
        return null;
    };

    const target = findNode(trees);
    if (!target) return false;

    if (target.depth + 1 > TREE_MAX_DEPTH) return false;

    // Build a uid→node lookup for ancestor traversal
    const nodeMap = new Map<string, ITreeCard>();
    const indexNodes = (nodes: ITreeCard[]): void => {
        for (const n of nodes) {
            nodeMap.set(n.uid, n);
            indexNodes(n.children);
        }
    };
    indexNodes(trees);

    // Check if draggedUid is an ancestor of target by walking up parent links
    const isAncestorOfTarget = (ancestorUid: string, node: ITreeCard): boolean => {
        let current: ITreeCard | undefined = node;
        while (current && current.parent_uid) {
            if (current.parent_uid === ancestorUid) return true;
            current = nodeMap.get(current.parent_uid);
        }
        return false;
    };

    if (isAncestorOfTarget(draggedUid, target)) return false;

    return true;
};

/**
 * Compute visual connector lines for a node at a given depth.
 * Returns array of booleans: true if a vertical line should be drawn at that level.
 */
export const connectorLines = (depth: number, is_last: boolean, has_sibling: boolean): boolean[] => {
    const lines: boolean[] = [];
    for (let i = 0; i < depth; i++) {
        lines.push(i < depth - 1 ? true : has_sibling || !is_last);
    }
    return lines;
};
