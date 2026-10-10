import assert from "node:assert/strict";
import { test } from "node:test";
import { setupPreloadRecovery } from "./setupPreloadRecovery.ts";

function fixture(values = new Map<string, string>()) {
    const events = new EventTarget();
    let reloads = 0;
    let time = 100_000;
    const browser = {
        addEventListener: events.addEventListener.bind(events),
        sessionStorage: {
            getItem: (key: string) => values.get(key) ?? null,
            setItem: (key: string, value: string) => values.set(key, value),
        },
        location: { reload: () => reloads++ },
    } as unknown as Pick<Window, "addEventListener" | "sessionStorage" | "location">;
    setupPreloadRecovery(browser, () => time);
    return { browser, values, events, reloads: () => reloads, advance: () => (time += 60_000) };
}

async function failedImport(events: EventTarget, error: Error) {
    // Vite dispatches this cancelable event before propagating import failures.
    return Promise.reject(error).catch((failure) => {
        const event = new Event("vite:preloadError", { cancelable: true });
        events.dispatchEvent(event);
        if (!event.defaultPrevented) throw failure;
    });
}

test("failed imports preserve rejection across recovery, restart and cooldown", async () => {
    const first = fixture();
    const error = new Error("Missing route chunk");
    await assert.rejects(failedImport(first.events, error), (failure) => failure === error);
    assert.equal(first.reloads(), 1);
    const restarted = fixture(first.values);
    await assert.rejects(failedImport(restarted.events, error), (failure) => failure === error);
    assert.equal(restarted.reloads(), 0);
    restarted.advance();
    await assert.rejects(failedImport(restarted.events, error), (failure) => failure === error);
    assert.equal(restarted.reloads(), 1);
});

test("unavailable storage preserves rejection without an unguarded reload", async () => {
    const current = fixture();
    current.browser.sessionStorage.setItem = () => {
        throw new Error("Storage blocked");
    };
    const error = new Error("Missing chunk");
    await assert.rejects(failedImport(current.events, error), (failure) => failure === error);
    assert.equal(current.reloads(), 0);
});

test("legacy reload marker does not permanently disable recovery", async () => {
    const current = fixture(new Map([["langboard:vite-preload-reload", "1"]]));
    await assert.rejects(failedImport(current.events, new Error("Missing chunk")));
    assert.equal(current.reloads(), 1);
});
