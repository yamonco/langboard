import assert from "node:assert/strict";
import { test } from "node:test";

const values = new Map<string, string>();
Object.defineProperty(globalThis, "sessionStorage", {
    value: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
    },
    configurable: true,
});
const { useCardFlipStore: store } = await import("./CardFlipStore.ts");

test("flip, swap, restore and deletion preserve project and user isolation", async () => {
    store.setState({ trays: {} });
    const a = { uid: "a", title: "A" };
    const b = { uid: "b", title: "B" };
    store.getState().flip("u1", "p1", a);
    store.getState().flip("u1", "p1", b);
    store.getState().flip("u1", "p1", a);
    store.getState().flip("u1", "p2", b);
    store.getState().flip("u2", "p1", b);
    assert.deepEqual(store.getState().trays["u1:p1"], [a, b]);
    store.getState().swap("u1", "p1", "b", { uid: "c", title: "C" });
    assert.deepEqual(
        store.getState().trays["u1:p1"].map((card) => card.uid),
        ["c", "a"]
    );
    store.getState().swap("u1", "p1", "c");
    assert.deepEqual(store.getState().trays["u1:p1"], [a]);
    store.setState({ trays: {} });
    await store.persist.rehydrate();
    // setState persists too; replay a saved session explicitly below.
    values.set("langboard-card-flip-session", JSON.stringify({ state: { trays: { "u1:p1": [a], "u1:p2": [b], "u2:p1": [b] } }, version: 0 }));
    await store.persist.rehydrate();
    assert.deepEqual(store.getState().trays["u1:p1"], [a]);
    store.getState().removeCard("b");
    assert.deepEqual(store.getState().trays["u1:p2"], []);
    assert.deepEqual(store.getState().trays["u2:p1"], []);
    store.getState().removeProject("p1");
    assert.equal(store.getState().trays["u1:p1"], undefined);
    assert.deepEqual(store.getState().trays["u1:p2"], []);
});

test("unavailable cards are removed and malformed stored entries cannot crash the tray", async () => {
    values.set(
        "langboard-card-flip-session",
        JSON.stringify({
            state: {
                trays: {
                    "u:p": [
                        { uid: "a", title: "A" },
                        { uid: "b", title: "B" },
                    ],
                    broken: null,
                },
            },
            version: 0,
        })
    );
    await store.persist.rehydrate();
    assert.equal(store.getState().trays.broken, undefined);
    store.getState().retain("u", "p", new Set(["a"]));
    assert.deepEqual(store.getState().trays["u:p"], [{ uid: "a", title: "A" }]);
    store.getState().remove("u", "p", "a");
    assert.deepEqual(store.getState().trays["u:p"], []);
});
