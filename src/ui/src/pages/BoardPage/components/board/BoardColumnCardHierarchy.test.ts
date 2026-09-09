import assert from "node:assert/strict";
import test from "node:test";
import { buildBoardColumnCardHierarchy } from "./BoardColumnCardHierarchy.ts";

interface IRelationship {
    parent_card_uid: string;
    child_card_uid: string;
}

const card = (uid: string, order: number, relationships: IRelationship[] = []) =>
    ({ uid, order, relationships }) as Parameters<typeof buildBoardColumnCardHierarchy>[0][number];

test("groups visible descendants directly after their parent", () => {
    const relationship = { parent_card_uid: "parent", child_card_uid: "child" };
    const groups = buildBoardColumnCardHierarchy([card("child", 0, [relationship]), card("unrelated", 1), card("parent", 2, [relationship])]);

    assert.deepEqual(
        groups.map(({ root, descendants }) => [root.uid, descendants.map(({ card: item, depth }) => [item.uid, depth])]),
        [
            ["unrelated", []],
            ["parent", [["child", 1]]],
        ]
    );
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
