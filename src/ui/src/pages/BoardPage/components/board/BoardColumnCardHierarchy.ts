import type { ProjectCard } from "@/core/models";

export interface IBoardColumnCardHierarchyItem {
    card: ProjectCard.TModel;
    depth: number;
}

export interface IBoardColumnCardHierarchyGroup {
    root: ProjectCard.TModel;
    descendants: IBoardColumnCardHierarchyItem[];
    hasContainmentCycle: boolean;
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
            const semantic = relationshipSemantic(relationship);
            if (semantic && semantic !== "contains") return;
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
        groups.push({ root, descendants, hasContainmentCycle: hasContainmentCycle([root, ...descendants.map((item) => item.card)]) });
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
    isRelatedCardVisible: boolean,
    semantic?: string | null
) => (!semantic || semantic === "contains") && !!relatedCard && relatedCard.project_column_uid === card.project_column_uid && isRelatedCardVisible;

export const relationshipSemantic = (relationship: ProjectCard.TModel["relationships"][number]) =>
    relationship.machine_semantic ?? relationship.relationship_type?.machine_semantic;

/** Only composition cycles need a finite-tree warning; shared children are not cycles. */
export const hasContainmentCycle = (cards: ProjectCard.TModel[], rootUID?: string): boolean => {
    const visible = new Set(cards.map((card) => card.uid));
    const children = buildCardRelationshipIndex(cards, "contains");
    const completed = new Set<string>();
    const active = new Set<string>();
    for (const card of rootUID ? cards.filter((candidate) => candidate.uid === rootUID) : cards) {
        if (completed.has(card.uid)) continue;
        const pending = [{ uid: card.uid, exit: false }];
        while (pending.length) {
            const item = pending.pop()!;
            if (item.exit) {
                active.delete(item.uid);
                completed.add(item.uid);
                continue;
            }
            if (active.has(item.uid)) return true;
            if (completed.has(item.uid)) continue;
            active.add(item.uid);
            pending.push({ uid: item.uid, exit: true });
            for (const child of children.get(item.uid) ?? []) {
                if (visible.has(child)) pending.push({ uid: child, exit: false });
            }
        }
    }
    return false;
};

export type TCardRelationshipIndex = Map<string, Set<string>>;

export const buildCardRelationshipIndex = (cards: ProjectCard.TModel[], semantic?: string): TCardRelationshipIndex => {
    const childrenByParentUID: TCardRelationshipIndex = new Map();
    cards.forEach((card) => {
        card.relationships.forEach((relationship) => {
            if (semantic && relationshipSemantic(relationship) !== semantic) return;
            const children = childrenByParentUID.get(relationship.parent_card_uid) ?? new Set<string>();
            children.add(relationship.child_card_uid);
            childrenByParentUID.set(relationship.parent_card_uid, children);
        });
    });
    return childrenByParentUID;
};

export const canCreateCardRelationship = (
    cards: ProjectCard.TModel[],
    sourceCardUID: string,
    targetCardUID: string,
    type: "parents" | "children",
    childrenByParentUID = buildCardRelationshipIndex(cards),
    semantic?: string | null
): boolean => {
    if (sourceCardUID === targetCardUID) {
        return false;
    }

    const parentCardUID = type === "children" ? sourceCardUID : targetCardUID;
    const childCardUID = type === "children" ? targetCardUID : sourceCardUID;
    if (childrenByParentUID.get(parentCardUID)?.has(childCardUID)) {
        return false;
    }

    // The drag target is selected before the relationship type. Server validation owns unknown semantics.
    if (semantic !== "blocks") return true;
    const blockingChildren = buildCardRelationshipIndex(cards, "blocks");
    const pending = [childCardUID];
    const visited = new Set<string>();
    while (pending.length) {
        const currentUID = pending.pop()!;
        if (currentUID === parentCardUID) {
            return false;
        }
        if (visited.has(currentUID)) {
            continue;
        }

        visited.add(currentUID);
        pending.push(...(blockingChildren.get(currentUID) ?? []));
    }

    return true;
};
