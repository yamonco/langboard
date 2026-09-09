import assert from "node:assert/strict";
import test from "node:test";
import { buildBoardColumnCardHierarchy, isRelationshipRenderedInHierarchy } from "./BoardColumnCardHierarchy.ts";

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
