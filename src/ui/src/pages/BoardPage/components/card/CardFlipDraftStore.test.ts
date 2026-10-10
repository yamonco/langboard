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
const { useCardFlipDraftStore: store, flipDraftKey } = await import("./CardFlipDraftStore.ts");
test("suspended title, body and deadline survive rehydration without crossing identity scope", async () => {
    const key = flipDraftKey("user", "board", "card");
    store.getState().save(key, { title: "Draft title", description: { content: "Unsaved body" }, deadline_at: "2030-01-01T00:00:00Z" });
    const persisted = values.get("langboard-card-flip-drafts")!;
    store.setState({ drafts: {} });
    values.set("langboard-card-flip-drafts", persisted);
    await store.persist.rehydrate();
    assert.equal(store.getState().drafts[key].description?.content, "Unsaved body");
    assert.equal(store.getState().drafts[flipDraftKey("other-user", "board", "card")], undefined);
    store.getState().clear(key);
    assert.equal(store.getState().drafts[key], undefined);
    values.set(
        "langboard-card-flip-drafts",
        JSON.stringify({ state: { drafts: { malformed: { deadline_at: "invalid", description: 5 } } }, version: 0 })
    );
    await store.persist.rehydrate();
    assert.equal(store.getState().drafts.malformed, undefined);
});
