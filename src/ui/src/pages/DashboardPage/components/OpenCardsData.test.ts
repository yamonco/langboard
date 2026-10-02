import assert from "node:assert/strict";
import test from "node:test";
import {
    recentOpenCards,
    closeOpenCard,
    closeProjectCards,
    focusOpenCard,
    getOpenCards,
    retainProjectCards,
    toggleOpenCardPin,
} from "./OpenCardsData.ts";

test("open cards focus without duplicates, keep pins, and close only the chosen card", () => {
    const first = focusOpenCard([], { projectUID: "board", cardUID: "one", title: "One" }, "2026-09-01T00:00:00Z");
    const second = focusOpenCard(first, { projectUID: "board", cardUID: "two", title: "Two" }, "2026-09-02T00:00:00Z");
    const pinned = toggleOpenCardPin(second, "board", "one");
    const focused = focusOpenCard(pinned, { projectUID: "board", cardUID: "one", title: "Renamed" }, "2026-09-03T00:00:00Z");

    assert.deepEqual(
        focused.map(({ cardUID, title, pinned }) => [cardUID, title, pinned]),
        [
            ["one", "Renamed", true],
            ["two", "Two", false],
        ]
    );
    assert.equal(closeOpenCard(focused, "board", "one").length, 1);
    assert.equal(closeProjectCards(focused, "board").length, 0);
    assert.equal(retainProjectCards(focused, new Set(["elsewhere"])).length, 0);
    assert.deepEqual(getOpenCards({ alice: focused }, "bob"), []);
});

test("open cards retain pinned entries and bound the recent unpinned list", () => {
    let cards = focusOpenCard([], { projectUID: "board", cardUID: "pinned", title: "Pinned" }, "2026-09-01T00:00:00Z");
    cards = toggleOpenCardPin(cards, "board", "pinned");
    for (let index = 0; index < 24; index++) {
        cards = focusOpenCard(
            cards,
            { projectUID: "board", cardUID: String(index), title: String(index) },
            `2026-09-02T00:00:${String(index).padStart(2, "0")}Z`
        );
    }
    assert.equal(cards.length, 21);
    assert.equal(cards[0].cardUID, "pinned");
    assert.equal(cards.at(-1)?.cardUID, "4");
});

test("recent card view sorts latest first, deduplicates and preserves older/pinned records", () => {
    let cards: ReturnType<typeof focusOpenCard> = [];
    for (let index = 0; index < 14; index++) {
        cards = focusOpenCard(
            cards,
            { projectUID: "board", cardUID: String(index), title: String(index) },
            `2026-10-02T00:00:${String(index).padStart(2, "0")}Z`
        );
    }
    cards = toggleOpenCardPin(cards, "board", "0");
    const recent = recentOpenCards([...cards, cards[0]]);
    assert.equal(recent.length, 14);
    assert.deepEqual(
        recent.slice(0, 10).map((card) => card.cardUID),
        ["13", "12", "11", "10", "9", "8", "7", "6", "5", "4"]
    );
    assert.equal(recent.at(-1)?.pinned, true);
    const focused = focusOpenCard(cards, { projectUID: "board", cardUID: "0", title: "Read again" }, "2026-10-02T01:00:00Z");
    assert.equal(recentOpenCards(focused)[0].cardUID, "0");
    assert.equal(recentOpenCards(focused).length, 14);
});
