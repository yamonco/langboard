import assert from "node:assert/strict";
import test from "node:test";
import {
    buildBoardColumnCardHierarchy,
    buildCardRelationshipIndex,
    canCreateCardRelationship,
    isRelationshipRenderedInHierarchy,
} from "./BoardColumnCardHierarchy.ts";

interface IRelationship {
    parent_card_uid: string;
    child_card_uid: string;
}

const card = (uid: string, order: number, relationships: IRelationship[] = []) =>
    ({ uid, order, relationships }) as Parameters<typeof buildBoardColumnCardHierarchy>[0][number];

test("groups visible descendants directly after their parent", () => {
    const relationship = { parent_card_uid: "parent", child_card_uid: "child" };
    const groups = buildBoardColumnCardHierarchy([card("unrelated", 0), card("parent", 1, [relationship]), card("child", 2, [relationship])]);

    assert.deepEqual(
        groups.map(({ root, descendants }) => [root.uid, descendants.map(({ card: item, depth }) => [item.uid, depth])]),
        [
            ["unrelated", []],
            ["parent", [["child", 1]]],
        ]
    );
});

test("keeps a same-column relationship badge when filters hide the related card", () => {
    const source = { ...card("parent", 0), project_column_uid: "column" };
    const related = { ...card("child", 1), project_column_uid: "column" };

    assert.equal(isRelationshipRenderedInHierarchy(source, related, true), true);
    assert.equal(isRelationshipRenderedInHierarchy(source, related, false), false);
});

test("keeps cards independent when their related card is not visible", () => {
    const relationship = { parent_card_uid: "other-column", child_card_uid: "child" };
    const groups = buildBoardColumnCardHierarchy([card("child", 0, [relationship])]);

    assert.deepEqual(
        groups.map(({ root, descendants }) => [root.uid, descendants.length]),
        [["child", 0]]
    );
});

test("renders every card once when legacy relationships contain a cycle", () => {
    const relationships = [
        { parent_card_uid: "a", child_card_uid: "b" },
        { parent_card_uid: "b", child_card_uid: "a" },
    ];
    const groups = buildBoardColumnCardHierarchy([card("a", 0, relationships), card("b", 1, relationships)]);

    assert.deepEqual(
        groups.flatMap(({ root, descendants }) => [root.uid, ...descendants.map(({ card: item }) => item.uid)]),
        ["a", "b"]
    );
});

test("places grandchildren inside the top-level parent group", () => {
    const relationships = [
        { parent_card_uid: "parent", child_card_uid: "child" },
        { parent_card_uid: "child", child_card_uid: "grandchild" },
    ];
    const groups = buildBoardColumnCardHierarchy([
        card("parent", 0, relationships),
        card("child", 1, relationships),
        card("grandchild", 2, relationships),
    ]);

    assert.deepEqual(
        groups.map(({ root, descendants }) => [root.uid, descendants.map(({ card: item, depth }) => [item.uid, depth])]),
        [
            [
                "parent",
                [
                    ["child", 1],
                    ["grandchild", 2],
                ],
            ],
        ]
    );
});
test("mirrors a shared child in every top-level parent group", () => {
    const relationships = [
        { parent_card_uid: "parent-a", child_card_uid: "shared" },
        { parent_card_uid: "parent-b", child_card_uid: "shared" },
    ];
    const groups = buildBoardColumnCardHierarchy([
        card("parent-a", 0, relationships),
        card("parent-b", 1, relationships),
        card("shared", 2, relationships),
    ]);

    assert.deepEqual(
        groups.map(({ root, descendants }) => [root.uid, descendants.map(({ card: item }) => item.uid)]),
        [
            ["parent-a", ["shared"]],
            ["parent-b", ["shared"]],
        ]
    );
});

test("renders a converging descendant once inside the same top-level group", () => {
    const relationships = [
        { parent_card_uid: "root", child_card_uid: "left" },
        { parent_card_uid: "root", child_card_uid: "right" },
        { parent_card_uid: "left", child_card_uid: "shared" },
        { parent_card_uid: "right", child_card_uid: "shared" },
    ];
    const groups = buildBoardColumnCardHierarchy([
        card("root", 0, relationships),
        card("left", 1, relationships),
        card("right", 2, relationships),
        card("shared", 3, relationships),
    ]);

    assert.deepEqual(
        groups.map(({ root, descendants }) => [root.uid, descendants.map(({ card: item }) => item.uid)]),
        [["root", ["left", "shared", "right"]]]
    );
});

test("rejects duplicate, self, and cyclic relationship candidates", () => {
    const relationships = [
        { parent_card_uid: "a", child_card_uid: "b" },
        { parent_card_uid: "b", child_card_uid: "c" },
    ];
    const cards = [card("a", 0, relationships), card("b", 1, relationships), card("c", 2, relationships), card("d", 3)];
    const relationshipIndex = buildCardRelationshipIndex(cards);

    assert.equal(canCreateCardRelationship(cards, "a", "a", "children"), false);
    assert.equal(canCreateCardRelationship(cards, "a", "b", "children"), false);
    assert.equal(canCreateCardRelationship(cards, "c", "a", "children"), false);
    assert.equal(canCreateCardRelationship(cards, "a", "d", "children"), true);
    assert.equal(canCreateCardRelationship(cards, "d", "c", "parents"), true);
    assert.equal(canCreateCardRelationship(cards, "c", "a", "children", relationshipIndex), false);
});

test("preserves a deep relationship chain without recursive stack overflow", () => {
    const cards = Array.from({ length: 10_000 }, (_, index) =>
        card(String(index), index, index ? [{ parent_card_uid: String(index - 1), child_card_uid: String(index) }] : [])
    );
    const groups = buildBoardColumnCardHierarchy(cards);
    assert.equal(groups.length, 1);
    assert.equal(groups[0].root.uid, "0");
    assert.equal(groups[0].descendants.length, cards.length - 1);
    groups[0].descendants.forEach(({ card: item, depth }, index) => {
        assert.equal(item.uid, String(index + 1));
        assert.equal(depth, index + 1);
    });
});
