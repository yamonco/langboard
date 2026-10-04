import assert from "node:assert/strict";
import { test } from "node:test";
import { setCardCompletion } from "./CardCompletionMutation.ts";

test("board and detail share one completion write and can retry after settlement", async () => {
    const card = { completed: false };
    let resolve!: (result: { completed: boolean }) => void;
    let writes = 0;
    const first = setCardCompletion(card, true, () => {
        writes++;
        return new Promise((done) => { resolve = done; });
    });
    assert.equal(card.completed, true);
    const second = setCardCompletion(card, false, async () => { writes++; return { completed: false }; });
    assert.equal(first, second);
    await Promise.resolve();
    assert.equal(writes, 1);
    resolve({ completed: true });
    await first;
    await setCardCompletion(card, false, async () => ({ completed: false }));
    assert.equal(card.completed, false);
});

test("failed write restores the prior value and does not overwrite a newer model value", async () => {
    const card: { completed?: boolean } = {};
    await assert.rejects(setCardCompletion(card, true, async () => { throw new Error("denied"); }), /denied/);
    assert.equal(card.completed, undefined);
    const request = setCardCompletion(card, true, async () => { throw new Error("offline"); });
    card.completed = false;
    await assert.rejects(request, /offline/);
    assert.equal(card.completed, false);
    await setCardCompletion(card, true, async () => ({ completed: true }));
    assert.equal(card.completed, true);
});
