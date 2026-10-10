import assert from "node:assert/strict";
import test from "node:test";
import {
    GRAPH_CARD_HEIGHT,
    GRAPH_DEFAULT_VIEWPORT,
    GRAPH_LANE_GAP,
    GRAPH_LANE_WIDTH,
    layoutBoardGraph,
    networkBoardGraph,
} from "./BoardGraphLayout.ts";

const columns = [
    { uid: "doing", name: "Doing", order: 2, is_archive: false },
    { uid: "archive", name: "Archive", order: 0, is_archive: true },
    { uid: "request", name: "Request", order: 0, is_archive: false },
    { uid: "standby", name: "Standby", order: 1, is_archive: false },
];
const relation = (source: string, target: string) => ({ parent_card_uid: source, child_card_uid: target, relationship_type_uid: "child" });
const card = (uid: string, column = "request", order = 0, relationships: ReturnType<typeof relation>[] = []) => ({
    uid,
    title: uid,
    project_column_uid: column,
    order,
    relationships,
    archived_at: undefined as string | undefined,
});

test("workflow columns fix horizontal position, including an empty intervening column", () => {
    const edge = relation("parent", "child");
    const result = layoutBoardGraph([card("child", "doing", 0, [edge]), card("parent", "request", 0, [edge])], columns);
    assert.deepEqual(
        result.lanes.map((lane) => lane.column.name),
        ["Request", "Standby", "Doing"]
    );
    assert.deepEqual(
        result.lanes.map((lane) => lane.x),
        [0, GRAPH_LANE_WIDTH + GRAPH_LANE_GAP, 2 * (GRAPH_LANE_WIDTH + GRAPH_LANE_GAP)]
    );
    assert.deepEqual(
        result.lanes.map((lane) => lane.cards.map(({ card: item }) => item.uid)),
        [["parent"], [], ["child"]]
    );
    assert.equal(result.edges.length, 1);
    assert.equal(result.edges[0].sourceHandle, "source-right");
    assert.equal(result.edges[0].targetHandle, "target-left");
});

test("archive and unlinked cards require independent explicit opt-ins", () => {
    const edge = relation("parent", "archived");
    const cards = [card("parent", "request", 0, [edge]), card("archived", "archive", 0, [edge]), card("standalone")];
    assert.equal(layoutBoardGraph(cards, columns).cardCount, 0);
    assert.equal(layoutBoardGraph(cards, columns, { showUnlinked: true }).cardCount, 2);
    const included = layoutBoardGraph(cards, columns, { includeArchive: true });
    assert.equal(included.cardCount, 2);
    assert.equal(included.lanes.at(-1)?.column.uid, "archive");
    assert.equal(layoutBoardGraph(cards, columns, { includeArchive: true, showUnlinked: true }).cardCount, 3);
    cards[0].archived_at = "2026-01-01";
    assert.equal(layoutBoardGraph(cards, columns, { showUnlinked: true }).cardCount, 1);
});

test("absent or out-of-scope endpoints never create placeholder cards or leaked edges", () => {
    const cards = [
        card("visible", "request", 0, [relation("visible", "missing"), relation("visible", "other-board")]),
        card("other-board", "unknown"),
    ];
    const result = layoutBoardGraph(cards, columns, { showUnlinked: true });
    assert.equal(result.cardCount, 1);
    assert.deepEqual(result.edges, []);
});

test("reverse and same-column edges preserve parent-to-child direction without changing board order", () => {
    const reverse = relation("later", "earlier");
    const same = relation("earlier", "sibling");
    const cards = [card("later", "doing", 0, [reverse]), card("sibling", "request", 0, [same]), card("earlier", "request", 1, [same, reverse])];
    const before = JSON.stringify(cards);
    const result = layoutBoardGraph(cards, columns);
    const edge = result.edges.find((item) => item.source === "later")!;
    assert.equal(edge.target, "earlier");
    assert.equal(edge.sourceHandle, "source-left");
    assert.equal(edge.targetHandle, "target-right");
    assert.deepEqual(
        result.lanes[0].cards.map(({ card: item }) => item.uid),
        ["sibling", "earlier"]
    );
    assert.equal(result.edges.find((item) => item.source === "earlier")?.targetHandle, "target-right");
    assert.equal(JSON.stringify(cards), before);
});

test("a moved card is projected only under its current column; cycles do not recurse or mutate relationships", () => {
    const relations = [relation("a", "b"), relation("b", "a"), relation("a", "a")];
    const cards = [card("a", "request", 0, relations), card("b", "doing", 0, relations)];
    cards[1].project_column_uid = "standby";
    const result = layoutBoardGraph(cards, columns);
    assert.deepEqual(
        result.lanes.map((lane) => lane.cards.map(({ card: item }) => item.uid)),
        [["a"], ["b"], []]
    );
    assert.equal(result.edges.length, 2);
    assert.equal(cards[0].relationships.length, 3);
});

test("large columns remain non-overlapping without a fit-all zoom or layout-engine pass", () => {
    const cards = Array.from({ length: 10000 }, (_, index) => card(`card-${index}`, "request", index));
    assert.equal(layoutBoardGraph(cards, columns).cardCount, 0);
    const result = layoutBoardGraph(cards, columns, { showUnlinked: true });
    assert.equal(result.cardCount, 10000);
    const rows = result.lanes[0].cards;
    assert.ok(rows.every((row, index) => !index || row.y >= rows[index - 1].y + GRAPH_CARD_HEIGHT));
    assert.ok(result.lanes[0].height >= rows.at(-1)!.y + GRAPH_CARD_HEIGHT);
    assert.equal(GRAPH_DEFAULT_VIEWPORT.zoom, 1);
});

test("the force engine receives detached nodes and links, never canonical card objects", () => {
    const cards = [card("a", "request", 0, [relation("a", "b")]), card("b")];
    const before = JSON.stringify(cards);
    const layout = layoutBoardGraph(cards, columns);
    const graph = networkBoardGraph(layout);
    assert.equal(graph.nodes[0].degree, 1);
    graph.nodes[0].title = "simulation-local value";
    graph.links[0].source = "simulation-local endpoint";
    assert.equal(JSON.stringify(cards), before);
    assert.equal(layout.edges[0].source, "a");
});
