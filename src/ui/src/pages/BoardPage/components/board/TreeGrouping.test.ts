import assert from "node:assert/strict";
import test from "node:test";
import { buildCardTree, type ITreeCard } from "./ColumnCardTree.ts";
import {
    collapseAll,
    expandAll,
    hasCollapsedDescendant,
    summarizeGroup,
    toggleGroupRecursive,
} from "./TreeGrouping.ts";

const makeTrees = (): ITreeCard[] => {
    const cards = [
        { uid: "a", title: "A", order: 0 },
        { uid: "b", title: "B", order: 0 },
        { uid: "c", title: "C", order: 0 },
        { uid: "d", title: "D", order: 1 },
    ];
    const edges = [
        { parent_card_uid: "a", child_card_uid: "b" },
        { parent_card_uid: "b", child_card_uid: "c" },
        { parent_card_uid: "a", child_card_uid: "d" },
    ];
    return buildCardTree(cards, edges);
};

test("summarizeGroup counts all cards", () => {
    const trees = makeTrees();
    const summary = summarizeGroup(trees, new Set());
    assert.equal(summary.total_cards, 4);
    assert.equal(summary.root_count, 1); // only a is root
    assert.equal(summary.max_depth, 2); // a→b→c
    assert.equal(summary.collapsed_count, 0);
    assert.equal(summary.hidden_count, 0);
});

test("collapseAll collapses every parent", () => {
    const trees = makeTrees();
    const collapsed = collapseAll(trees);
    // a and b have children
    assert.ok(collapsed.has("a"));
    assert.ok(collapsed.has("b"));
    assert.ok(!collapsed.has("c")); // leaf
    assert.ok(!collapsed.has("d")); // leaf
});

test("expandAll returns empty set", () => {
    const trees = makeTrees();
    const collapsed = expandAll(trees);
    assert.equal(collapsed.size, 0);
});

test("summarizeGroup tracks hidden when collapsed", () => {
    const trees = makeTrees();
    const collapsed = new Set(["a"]);
    const summary = summarizeGroup(trees, collapsed);
    assert.equal(summary.collapsed_count, 1);
    assert.equal(summary.hidden_count, 3); // b, c, d all hidden
});

test("toggleGroupRecursive expands descendants", () => {
    const trees = makeTrees();
    const collapsed = collapseAll(trees); // {a, b}
    const next = toggleGroupRecursive(trees, "a", collapsed);
    // Expanding a should also expand b (descendant)
    assert.ok(!next.has("a"));
    assert.ok(!next.has("b"));
});

test("toggleGroupRecursive collapses single node", () => {
    const trees = makeTrees();
    const collapsed = new Set<string>();
    const next = toggleGroupRecursive(trees, "b", collapsed);
    assert.ok(next.has("b"));
});

test("hasCollapsedDescendant detects hidden children", () => {
    const trees = makeTrees();
    const collapsed = new Set(["b"]);
    assert.ok(hasCollapsedDescendant(trees, "a", collapsed));
    assert.ok(!hasCollapsedDescendant(trees, "d", collapsed));
});
