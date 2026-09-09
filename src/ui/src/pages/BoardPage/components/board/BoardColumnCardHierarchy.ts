import type { ProjectCard } from "@/core/models";

export interface IBoardColumnCardHierarchyItem {
    card: ProjectCard.TModel;
    depth: number;
}

export interface IBoardColumnCardHierarchyGroup {
    root: ProjectCard.TModel;
    descendants: IBoardColumnCardHierarchyItem[];
}

/**
 * Projects same-column relationships as a tree without changing card order or
 * relationship data. Shared descendants are mirrored once in every top-level
 * parent group that reaches them. A per-group visited set keeps legacy cycles
 * finite without suppressing mirrors in independent groups.
 */
export const buildBoardColumnCardHierarchy = (cards: ProjectCard.TModel[]): IBoardColumnCardHierarchyGroup[] => {
    // useRowReordered already supplies board order. Keeping that order here
    // makes the projection linear and avoids sorting every visible column.
    const cardsByUID = new Map(cards.map((card) => [card.uid, card]));
    const parentUIDsByChildUID = new Map<string, Set<string>>();
    const childUIDsByParentUID = new Map<string, Set<string>>();
    const childUIDs = new Set<string>();

    cards.forEach((card) => {
        card.relationships.forEach((relationship) => {
            const parent = cardsByUID.get(relationship.parent_card_uid);
            const child = cardsByUID.get(relationship.child_card_uid);
            if (!parent || !child || parent.uid === child.uid) {
                return;
            }

            const parents = parentUIDsByChildUID.get(child.uid) ?? new Set<string>();
            parents.add(parent.uid);
            parentUIDsByChildUID.set(child.uid, parents);
            childUIDs.add(child.uid);
        });
    });

    cards.forEach((child) => {
        parentUIDsByChildUID.get(child.uid)?.forEach((parentUID) => {
            const children = childUIDsByParentUID.get(parentUID) ?? new Set<string>();
            children.add(child.uid);
            childUIDsByParentUID.set(parentUID, children);
        });
    });

    const groups: IBoardColumnCardHierarchyGroup[] = [];
    const coveredUIDs = new Set<string>();

    const appendGroup = (root: ProjectCard.TModel) => {
        const descendants: IBoardColumnCardHierarchyItem[] = [];
        const emittedUIDs = new Set<string>();
        const pending = [{ card: root, depth: 0 }];
        // Explicit DFS preserves sibling order without using the call stack for deep chains.
        while (pending.length) {
            const item = pending.pop()!;
            if (emittedUIDs.has(item.card.uid)) continue;
            emittedUIDs.add(item.card.uid);
            coveredUIDs.add(item.card.uid);
            if (item.depth) descendants.push(item);

            const children = [...(childUIDsByParentUID.get(item.card.uid) ?? [])];
            for (let index = children.length - 1; index >= 0; index--) {
                const child = cardsByUID.get(children[index]);
                if (child) pending.push({ card: child, depth: item.depth + 1 });
            }
        }
        groups.push({ root, descendants });
    };

    cards.filter((card) => !childUIDs.has(card.uid)).forEach(appendGroup);
    cards.forEach((card) => {
        if (!coveredUIDs.has(card.uid)) {
            appendGroup(card);
        }
    });
    return groups;
};

export const isRelationshipRenderedInHierarchy = (
    card: ProjectCard.TModel,
    relatedCard: ProjectCard.TModel | undefined,
    isRelatedCardVisible: boolean
) => !!relatedCard && relatedCard.project_column_uid === card.project_column_uid && isRelatedCardVisible;
