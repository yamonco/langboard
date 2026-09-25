export const GRAPH_CARD_WIDTH = 248;
export const GRAPH_CARD_HEIGHT = 88;
export const GRAPH_LANE_WIDTH = 280;
export const GRAPH_LANE_GAP = 64;
export const GRAPH_ROW_GAP = 36;
export const GRAPH_LANE_HEADER = 64;
export const GRAPH_DEFAULT_VIEWPORT = { x: 16, y: 16, zoom: 1 };

interface IGraphRelationship {
    parent_card_uid: string;
    child_card_uid: string;
    relationship_type_uid: string;
}

interface IGraphCard {
    uid: string;
    title: string;
    project_column_uid: string;
    order: number;
    archived_at?: unknown;
    relationships: readonly IGraphRelationship[];
}

/** Force engines mutate positions and link endpoints; never hand them canonical models. */
export function networkBoardGraph(layout: ReturnType<typeof layoutBoardGraph>) {
    const degree = new Map<string, number>();
    for (const edge of layout.edges) {
        degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
        degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
    return {
        nodes: layout.lanes.flatMap(({ column, cards }, columnIndex) =>
            cards.map(({ card }) => ({
                id: card.uid,
                title: card.title,
                columnUID: column.uid,
                column: column.name,
                columnIndex,
                degree: degree.get(card.uid) ?? 0,
            }))
        ),
        links: layout.edges.map(({ id, source, target }) => ({ id, source, target })),
    };
}

interface IGraphColumn {
    uid: string;
    name: string;
    order: number;
    is_archive: boolean;
}

/** A read-only projection of board order: graph ranks never redefine workflow columns. */
export function layoutBoardGraph<TCard extends IGraphCard>(
    cards: readonly TCard[],
    columns: readonly IGraphColumn[],
    { includeArchive = false, showUnlinked = false } = {}
) {
    const lanes = columns
        .filter((column) => includeArchive || !column.is_archive)
        .sort((a, b) => Number(a.is_archive) - Number(b.is_archive) || a.order - b.order || a.uid.localeCompare(b.uid));
    const columnIndices = new Map(lanes.map((column, index) => [column.uid, index]));
    const availableCards = cards.filter((card) => columnIndices.has(card.project_column_uid) && (includeArchive || !card.archived_at));
    const cardsByUID = new Map(availableCards.map((card) => [card.uid, card]));
    const edges = new Map<string, { id: string; source: string; target: string; typeUID: string; sourceHandle: string; targetHandle: string }>();
    const connected = new Set<string>();
    for (const card of availableCards) {
        for (const relationship of card.relationships) {
            const source = cardsByUID.get(relationship.parent_card_uid);
            const target = cardsByUID.get(relationship.child_card_uid);
            if (!source || !target || source === target) continue;
            const id = `${relationship.relationship_type_uid}:${source.uid}:${target.uid}`;
            const sourceColumn = columnIndices.get(source.project_column_uid)!;
            const targetColumn = columnIndices.get(target.project_column_uid)!;
            edges.set(id, {
                id,
                source: source.uid,
                target: target.uid,
                typeUID: relationship.relationship_type_uid,
                sourceHandle: sourceColumn <= targetColumn ? "source-right" : "source-left",
                // Same-column edges curve outside cards instead of through intervening titles.
                targetHandle: sourceColumn < targetColumn ? "target-left" : "target-right",
            });
            connected.add(source.uid);
            connected.add(target.uid);
        }
    }
    const rows = lanes.map(() => [] as TCard[]);
    for (const card of availableCards) {
        if (showUnlinked || connected.has(card.uid)) rows[columnIndices.get(card.project_column_uid)!].push(card);
    }
    for (const row of rows) row.sort((a, b) => a.order - b.order || a.uid.localeCompare(b.uid));
    const height = GRAPH_LANE_HEADER + Math.max(1, ...rows.map((row) => row.length)) * (GRAPH_CARD_HEIGHT + GRAPH_ROW_GAP);
    return {
        lanes: lanes.map((column, index) => ({
            column,
            x: index * (GRAPH_LANE_WIDTH + GRAPH_LANE_GAP),
            height,
            cards: rows[index].map((card, rowIndex) => ({ card, y: GRAPH_LANE_HEADER + rowIndex * (GRAPH_CARD_HEIGHT + GRAPH_ROW_GAP) })),
        })),
        edges: [...edges.values()],
        cardCount: rows.reduce((sum, row) => sum + row.length, 0),
    };
}
