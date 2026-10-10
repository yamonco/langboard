import assert from "node:assert/strict";
import test from "node:test";
import { buildCardTree, flattenTree, type ITreeCard } from "./ColumnCardTree.ts";
import {
    TREE_INDENT_PX,
    TREE_MAX_DEPTH,
    canDropAsChild,
    computeDisplayList,
    connectorLines,
    toggleCollapse,
} from "./TreeRenderer.ts";

const makeTree = (): ITreeCard[] => {
    const cards = [
        { uid: "root", title: "Root", order: 0 },
        { uid: "child1", title: "Child 1", order: 0 },
        { uid: "grandchild", title: "Grandchild", order: 0 },
        { uid: "child2", title: "Child 2", order: 1 },
    ];
    const edges = [
        { parent_card_uid: "root", child_card_uid: "child1" },
        { parent_card_uid: "root", child_card_uid: "child2" },
        { parent_card_uid: "child1", child_card_uid: "grandchild" },
    ];
    return buildCardTree(cards, edges);
};

test("computes display list with indentation", () => {
    const trees = makeTree();
    const items = computeDisplayList(trees, new Set());
    assert.equal(items.length, 4);
    assert.equal(items[0].uid, "root");
    assert.equal(items[0].indent_px, 0);
    assert.equal(items[1].uid, "child1");
    assert.equal(items[1].indent_px, TREE_INDENT_PX);
    assert.equal(items[2].uid, "grandchild");
    assert.equal(items[2].indent_px, TREE_INDENT_PX * 2);
});

test("respects collapse state", () => {
    const trees = makeTree();
    const collapsed = new Set(["child1"]);
    const items = computeDisplayList(trees, collapsed);
    // child1 is collapsed → grandchild hidden
    assert.equal(items.length, 3);
    assert.ok(items.some((i) => i.uid === "root"));
    assert.ok(items.some((i) => i.uid === "child1" && i.is_collapsed));
    assert.ok(!items.some((i) => i.uid === "grandchild"));
});

test("toggleCollapse toggles correctly", () => {
    let collapsed = new Set<string>();
    collapsed = toggleCollapse(collapsed, "a");
    assert.ok(collapsed.has("a"));
    collapsed = toggleCollapse(collapsed, "a");
    assert.ok(!collapsed.has("a"));
});

test("canDropAsChild rejects self-drop", () => {
    const trees = makeTree();
    assert.equal(canDropAsChild("root", "root", trees), false);
});

test("canDropAsChild rejects ancestor drop (cycle)", () => {
    const trees = makeTree();
    // root is ancestor of child1 → can't drop root onto child1
    assert.equal(canDropAsChild("root", "child1", trees), false);
});

test("canDropAsChild allows valid child drop", () => {
    const trees = makeTree();
    // child2 is not ancestor of grandchild → can drop
    assert.equal(canDropAsChild("child2", "grandchild", trees), true);
});

test("respects max depth limit", () => {
    // Build a deep tree
    const cards = Array.from({ length: 8 }, (_, i) => ({ uid: `n${i}`, title: `N${i}`, order: 0 }));
    const edges = Array.from({ length: 7 }, (_, i) => ({
        parent_card_uid: `n${i}`,
        child_card_uid: `n${i + 1}`,
    }));
    const trees = buildCardTree(cards, edges);
    // n6 is at depth 6, dropping n0 onto n6 would make it depth 7 > max
    assert.equal(canDropAsChild("n0", "n6", trees), false);
});

test("connectorLines draws vertical lines", () => {
    const lines = connectorLines(2, false, true);
    assert.equal(lines.length, 2);
    assert.ok(lines.every((l) => l === true));
});
