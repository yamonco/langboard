/** Build a card tree from parent-child relationships within a column. */

export interface ITreeCard {
    uid: string;
    title: string;
    order: number;
    depth: number;
    children: ITreeCard[];
    parent_uid: string | null;
}

export interface IRelationshipEdge {
    parent_card_uid: string;
    child_card_uid: string;
}

export interface IFlatCard {
    uid: string;
    title: string;
    order: number;
}

/**
 * Build a forest (list of root trees) from flat cards + relationship edges.
 * Cards not referenced in any edge become depth-0 roots.
 * Cards in edges are placed under their parent, sorted by order.
 */
export const buildCardTree = (
    cards: IFlatCard[],
    edges: IRelationshipEdge[]
): ITreeCard[] => {
    const cardMap = new Map<string, ITreeCard>(
        cards.map((c) => [c.uid, { ...c, depth: 0, children: [], parent_uid: null }])
    );

    // Link children to parents
    const childUids = new Set<string>();
    for (const edge of edges) {
        const parent = cardMap.get(edge.parent_card_uid);
        const child = cardMap.get(edge.child_card_uid);
        if (!parent || !child) continue;

        // Prevent cycles: don't add if child is an ancestor of parent
        if (isAncestor(cardMap, edge.child_card_uid, edge.parent_card_uid)) continue;

        child.parent_uid = edge.parent_card_uid;
        childUids.add(edge.child_card_uid);

        // Remove from previous parent if re-linked
        const prevParent = [...cardMap.values()].find((p) =>
            p.children.some((ch) => ch.uid === edge.child_card_uid)
        );
        if (prevParent && prevParent.uid !== edge.parent_card_uid) {
            prevParent.children = prevParent.children.filter((ch) => ch.uid !== edge.child_card_uid);
        }

        if (!parent.children.some((ch) => ch.uid === edge.child_card_uid)) {
            parent.children.push(child);
        }
    }

    // Compute depths
    const roots = [...cardMap.values()].filter((c) => !childUids.has(c.uid));
    const computeDepth = (node: ITreeCard, depth: number): void => {
        node.depth = depth;
        node.children.sort((a, b) => a.order - b.order);
        for (const child of node.children) {
            computeDepth(child, depth + 1);
        }
    };
    roots.sort((a, b) => a.order - b.order);
    for (const root of roots) {
        computeDepth(root, 0);
    }

    return roots;
};

/**
 * Check if `ancestorUid` is an ancestor of `descendantUid` in the card map.
 */
const isAncestor = (
    cardMap: Map<string, ITreeCard>,
    ancestorUid: string,
    descendantUid: string
): boolean => {
    let current = cardMap.get(descendantUid);
    while (current && current.parent_uid) {
        if (current.parent_uid === ancestorUid) return true;
        current = cardMap.get(current.parent_uid);
    }
    return false;
};

/**
 * Flatten a tree back to a display-ordered list (DFS pre-order).
 */
export const flattenTree = (trees: ITreeCard[]): ITreeCard[] => {
    const result: ITreeCard[] = [];
    const walk = (nodes: ITreeCard[]): void => {
        for (const node of nodes) {
            result.push(node);
            walk(node.children);
        }
    };
    walk(trees);
    return result;
};

/**
 * Find the maximum depth in the forest.
 */
export const maxDepth = (trees: ITreeCard[]): number => {
    let max = 0;
    const walk = (nodes: ITreeCard[]): void => {
        for (const node of nodes) {
            if (node.depth > max) max = node.depth;
            walk(node.children);
        }
    };
    walk(trees);
    return max;
};
