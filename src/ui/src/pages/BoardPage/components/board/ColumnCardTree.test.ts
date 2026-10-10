import assert from "node:assert/strict";
import test from "node:test";
import { buildCardTree, flattenTree, maxDepth } from "./ColumnCardTree.ts";

const flatCards = [
    { uid: "a", title: "Root A", order: 0 },
    { uid: "b", title: "Root B", order: 1 },
    { uid: "c", title: "Child of A", order: 0 },
    { uid: "d", title: "Grandchild", order: 0 },
    { uid: "e", title: "Orphan", order: 2 },
];

test("builds tree from cards and edges", () => {
    const edges = [
        { parent_card_uid: "a", child_card_uid: "c" },
        { parent_card_uid: "c", child_card_uid: "d" },
    ];
    const trees = buildCardTree(flatCards, edges);
    assert.equal(trees.length, 3); // a, b, e (e is a root)
    const rootA = trees.find((t) => t.uid === "a");
    assert.ok(rootA);
    assert.equal(rootA.children.length, 1);
    assert.equal(rootA.children[0].uid, "c");
    assert.equal(rootA.children[0].children[0].uid, "d");
    assert.equal(rootA.children[0].depth, 1);
    assert.equal(rootA.children[0].children[0].depth, 2);
});

test("orphans become roots", () => {
    const trees = buildCardTree(flatCards, []);
    assert.equal(trees.length, 5);
    assert.ok(trees.every((t) => t.depth === 0 && t.children.length === 0));
});

test("sorts roots and children by order", () => {
    const edges = [{ parent_card_uid: "a", child_card_uid: "c" }];
    const trees = buildCardTree(flatCards, edges);
    // Roots: a(0), d(0), b(1), e(2) — d and a tie at order 0
    const rootUids = trees.map((t) => t.uid);
    assert.ok(rootUids.includes("a"));
    assert.ok(rootUids.includes("b"));
    assert.ok(rootUids.includes("d")); // d has no parent in this edge set
    assert.ok(rootUids.includes("e"));
    assert.ok(!rootUids.includes("c")); // c is a child of a
    assert.ok(trees[0].order <= trees[trees.length - 1].order, "roots sorted by order");
});

test("prevents cycles", () => {
    const edges = [
        { parent_card_uid: "a", child_card_uid: "c" },
        { parent_card_uid: "c", child_card_uid: "a" }, // cycle!
    ];
    const trees = buildCardTree(flatCards, edges);
    // 'a' should still be a root (cycle edge ignored)
    const rootA = trees.find((t) => t.uid === "a");
    assert.ok(rootA);
    assert.equal(rootA.children.length, 1);
    assert.equal(rootA.children[0].uid, "c");
});

test("flattenTree returns DFS pre-order", () => {
    const edges = [
        { parent_card_uid: "a", child_card_uid: "c" },
        { parent_card_uid: "c", child_card_uid: "d" },
    ];
    const trees = buildCardTree(flatCards, edges);
    const flat = flattenTree(trees);
    const uids = flat.map((t) => t.uid);
    // DFS pre-order: a's subtree first (a,c,d), then remaining roots (b,e)
    assert.equal(uids.length, 5);
    assert.equal(uids[0], "a");
    assert.ok(uids.indexOf("c") < uids.indexOf("d"), "c before d");
    assert.ok(uids.indexOf("a") < uids.indexOf("c"), "a before c");
    assert.ok(new Set(uids).size === 5, "no duplicates");
});

test("maxDepth returns deepest level", () => {
    const edges = [
        { parent_card_uid: "a", child_card_uid: "c" },
        { parent_card_uid: "c", child_card_uid: "d" },
    ];
    const trees = buildCardTree(flatCards, edges);
    assert.equal(maxDepth(trees), 2);
});

test("handles empty input", () => {
    const trees = buildCardTree([], []);
    assert.equal(trees.length, 0);
    assert.equal(maxDepth(trees), 0);
    assert.equal(flattenTree(trees).length, 0);
});
