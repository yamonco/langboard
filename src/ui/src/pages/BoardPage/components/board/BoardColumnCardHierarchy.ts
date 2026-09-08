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
    const sortedCards = [...cards].sort((left, right) => left.order - right.order);
    const cardsByUID = new Map(sortedCards.map((card) => [card.uid, card]));
    const childUIDsByParentUID = new Map<string, Set<string>>();
    const childUIDs = new Set<string>();

    sortedCards.forEach((card) => {
        card.relationships.forEach((relationship) => {
            const parent = cardsByUID.get(relationship.parent_card_uid);
            const child = cardsByUID.get(relationship.child_card_uid);
            if (!parent || !child || parent.uid === child.uid) {
                return;
            }

            const children = childUIDsByParentUID.get(parent.uid) ?? new Set<string>();
            children.add(child.uid);
            childUIDsByParentUID.set(parent.uid, children);
            childUIDs.add(child.uid);
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
            .filter((child): child is ProjectCard.TModel => !!child)
            .sort((left, right) => left.order - right.order);
        children.forEach((child) => append(child, depth + 1));
        visitingUIDs.delete(card.uid);
    };

    sortedCards.filter((card) => !childUIDs.has(card.uid)).forEach((card) => append(card, 0));
    sortedCards.forEach((card) => append(card, 0));

    return result.reduce<IBoardColumnCardHierarchyGroup[]>((groups, item) => {
        if (item.depth === 0 || !groups.length) {
            groups.push({ root: item.card, descendants: [] });
        } else {
            groups.at(-1)!.descendants.push(item);
        }

        return groups;
    }, []);
};

export const canCreateCardRelationship = (
    cards: ProjectCard.TModel[],
    sourceCardUID: string,
    targetCardUID: string,
    type: "parents" | "children"
): boolean => {
    if (sourceCardUID === targetCardUID) {
        return false;
    }

    const parentCardUID = type === "children" ? sourceCardUID : targetCardUID;
    const childCardUID = type === "children" ? targetCardUID : sourceCardUID;
    const childrenByParentUID = new Map<string, Set<string>>();

    cards.forEach((card) => {
        card.relationships.forEach((relationship) => {
            const children = childrenByParentUID.get(relationship.parent_card_uid) ?? new Set<string>();
            children.add(relationship.child_card_uid);
            childrenByParentUID.set(relationship.parent_card_uid, children);
        });
    });

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
