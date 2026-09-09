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
 * relationship data. A card is rendered once even when legacy data contains
 * multiple parents or a cycle.
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

    const result: IBoardColumnCardHierarchyItem[] = [];
    const renderedUIDs = new Set<string>();
    const visitingUIDs = new Set<string>();

    const append = (card: ProjectCard.TModel, depth: number) => {
        if (renderedUIDs.has(card.uid) || visitingUIDs.has(card.uid)) {
            return;
        }

        visitingUIDs.add(card.uid);
        renderedUIDs.add(card.uid);
        result.push({ card, depth });

        const children = [...(childUIDsByParentUID.get(card.uid) ?? [])]
            .map((uid) => cardsByUID.get(uid))
            .filter((child): child is ProjectCard.TModel => !!child);
        children.forEach((child) => append(child, depth + 1));
        visitingUIDs.delete(card.uid);
    };

    cards.filter((card) => !childUIDs.has(card.uid)).forEach((card) => append(card, 0));
    cards.forEach((card) => append(card, 0));

    return result.reduce<IBoardColumnCardHierarchyGroup[]>((groups, item) => {
        if (item.depth === 0 || !groups.length) {
            groups.push({ root: item.card, descendants: [] });
        } else {
            groups.at(-1)!.descendants.push(item);
        }

        return groups;
    }, []);
};

export const isRelationshipRenderedInHierarchy = (
    card: ProjectCard.TModel,
    relatedCard: ProjectCard.TModel | undefined,
    isRelatedCardVisible: boolean
) => !!relatedCard && relatedCard.project_column_uid === card.project_column_uid && isRelatedCardVisible;

export type TCardRelationshipIndex = Map<string, Set<string>>;

export const buildCardRelationshipIndex = (cards: ProjectCard.TModel[]): TCardRelationshipIndex => {
    const childrenByParentUID: TCardRelationshipIndex = new Map();
    cards.forEach((card) => {
        card.relationships.forEach((relationship) => {
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
    childrenByParentUID = buildCardRelationshipIndex(cards)
): boolean => {
    if (sourceCardUID === targetCardUID) {
        return false;
    }

    const parentCardUID = type === "children" ? sourceCardUID : targetCardUID;
    const childCardUID = type === "children" ? targetCardUID : sourceCardUID;
    if (childrenByParentUID.get(parentCardUID)?.has(childCardUID)) {
        return false;
    }

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
        pending.push(...(childrenByParentUID.get(currentUID) ?? []));
    }

    return true;
};
