import assert from "node:assert/strict";
import test from "node:test";
import { acquireProjectWorkload } from "./projectWorkloadSubscriptions.ts";

test("shared views retain topics, burst refresh cancels stale reads, reconnect and last release", async (context) => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const listeners = new Map<string, () => void>();
    const subscribed: string[][] = [];
    const unsubscribed: string[][] = [];
    const order: string[] = [];
    let open = () => {};
    const client = {
        cancelQueries: async () => {
            order.push("cancel");
        },
        invalidateQueries: async () => {
            order.push("read");
        },
    };
    const socket = {
        subscribe: (uids: string[]) => subscribed.push(uids),
        unsubscribe: (uids: string[]) => unsubscribed.push(uids),
        listen: (uid: string, callback: () => void) => {
            listeners.set(uid, callback);
            return () => {
                listeners.delete(uid);
            };
        },
        listenOpen: (callback: () => void) => {
            open = callback;
            return () => {
                open = () => {};
            };
        },
    };
    const first = acquireProjectWorkload(client as never, ["a", "b"], socket);
    const second = acquireProjectWorkload(client as never, ["a"], socket);
    assert.deepEqual(subscribed, [["a", "b"]]);
    listeners.get("a")!();
    listeners.get("b")!();
    listeners.get("a")!();
    context.mock.timers.tick(250);
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(order, ["cancel", "read"]);
    first();
    assert.deepEqual(unsubscribed, [["b"]]);
    assert.equal(listeners.has("a"), true);
    open();
    assert.deepEqual(subscribed, [["a", "b"], ["a"]]);
    listeners.get("a")!();
    second();
    context.mock.timers.tick(250);
    await Promise.resolve();
    assert.deepEqual(order, ["cancel", "read", "read"]);
    assert.deepEqual(unsubscribed, [["b"], ["a"]]);
    assert.equal(listeners.size, 0);
});
