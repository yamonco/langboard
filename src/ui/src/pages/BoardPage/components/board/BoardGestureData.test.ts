import assert from "node:assert/strict";
import test from "node:test";
import { BOARD_MEMBER_DRAG_TYPE, draggedBoardCard, draggedBoardMember, nextCardOrder } from "./BoardGestureData.ts";

test("member drops stay within their originating board", () => {
    const member = { type: BOARD_MEMBER_DRAG_TYPE, projectUID: "board", memberUID: "member" };
    assert.equal(draggedBoardMember(member, "board"), "member");
    assert.equal(draggedBoardMember(member, "other"), undefined);
    for (const invalid of [{}, { ...member, memberUID: 42 }, { ...member, memberUID: "" }, { ...member, type: "card" }]) {
        assert.equal(draggedBoardMember(invalid, "board"), undefined);
    }
});

test("archive accepts only a card payload from the same board, never a member, column or relationship", () => {
    const rowSymbol = Symbol("card");
    const card = { [rowSymbol]: true, row: { uid: "card", project_uid: "board" } };
    assert.equal(draggedBoardCard(card, rowSymbol, "board"), "card");
    assert.equal(draggedBoardCard(card, rowSymbol, "other"), undefined);
    for (const invalid of [
        {},
        { ...card, [rowSymbol]: false },
        { ...card, row: null },
        { ...card, row: { uid: 1 } },
        { type: BOARD_MEMBER_DRAG_TYPE },
    ]) {
        assert.equal(draggedBoardCard(invalid, rowSymbol, "board"), undefined);
    }
});

test("move appends after sparse destination order without changing source cards or relationships", () => {
    const cards = [
        { project_column_uid: "source", order: 99 },
        { project_column_uid: "dest", order: 2 },
        { project_column_uid: "dest", order: 8 },
    ];
    const before = structuredClone(cards);
    assert.equal(nextCardOrder(cards, "dest"), 9);
    assert.equal(nextCardOrder(cards, "empty"), 0);
    assert.deepEqual(cards, before);
});
