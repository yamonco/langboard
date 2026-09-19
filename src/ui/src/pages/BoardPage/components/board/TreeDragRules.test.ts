import assert from "node:assert/strict";
import test from "node:test";
import { buildCardTree, type ITreeCard } from "./ColumnCardTree.ts";
import { executeDrag, groupSubtree, resolveDragIntent } from "./TreeDragRules.ts";

const makeTrees = (): ITreeCard[] => {
    const cards = [
        { uid: "a", title: "A", order: 0 },
        { uid: "b", title: "B", order: 1 },
        { uid: "c", title: "C", order: 2 },
        { uid: "d", title: "D", order: 3 },
    ];
    const edges = [
        { parent_card_uid: "a", child_card_uid: "b" },
        { parent_card_uid: "a", child_card_uid: "c" },
    ];
    return buildCardTree(cards, edges);
};

test("resolveDragIntent: child position nests under target", () => {
    const trees = makeTrees();
    const result = resolveDragIntent(
        { dragged_uid: "d", target_uid: "a", position: "child" },
        trees
    );
    assert.ok(result.valid);
    assert.equal(result.new_parent_uid, "a");
});

test("resolveDragIntent: before position becomes sibling", () => {
    const trees = makeTrees();
    const result = resolveDragIntent(
        { dragged_uid: "d", target_uid: "a", position: "before" },
        trees
    );
    assert.ok(result.valid);
    assert.equal(result.new_parent_uid, null); // a is root
});

test("resolveDragIntent: rejects self-drop", () => {
    const trees = makeTrees();
    const result = resolveDragIntent(
        { dragged_uid: "a", target_uid: "a", position: "child" },
        trees
    );
    assert.ok(!result.valid);
    assert.equal(result.reason, "self");
});

test("resolveDragIntent: rejects cycle (parent onto own child)", () => {
    const trees = makeTrees();
    const result = resolveDragIntent(
        { dragged_uid: "a", target_uid: "b", position: "child" },
        trees
    );
    assert.ok(!result.valid);
    assert.equal(result.reason, "cycle-or-depth");
});

test("executeDrag: reparents card to new parent", () => {
    const trees = makeTrees();
    const result = executeDrag(
        { dragged_uid: "d", target_uid: "b", position: "child" },
        trees
    );
    // d should now be under b
    const bNode = findInTrees(result, "b");
    assert.ok(bNode);
    assert.ok(bNode.children.some((ch) => ch.uid === "d"));
    assert.equal(bNode.children[0].depth, 2);
});

test("executeDrag: reorders as sibling before target", () => {
    const trees = makeTrees();
    const result = executeDrag(
        { dragged_uid: "d", target_uid: "a", position: "before" },
        trees
    );
    // d should be a root before a
    assert.equal(result[0].uid, "d");
    assert.equal(result[1].uid, "a");
});

test("groupSubtree: groups multiple cards under a parent", () => {
    const trees = makeTrees();
    // Make d and c children of b
    const result = groupSubtree(["d", "c"], "b", trees);
    const bNode = findInTrees(result, "b");
    assert.ok(bNode);
    assert.equal(bNode.children.length, 2); // c was moved from a, d was root
});

const findInTrees = (trees: ITreeCard[], uid: string): ITreeCard | null => {
    for (const t of trees) {
        if (t.uid === uid) return t;
        const found = findInTrees(t.children, uid);
        if (found) return found;
    }
    return null;
};
