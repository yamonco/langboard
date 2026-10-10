import assert from "node:assert/strict";
import test from "node:test";
import { acquireProjectWorkload } from "./projectWorkloadSubscriptions.ts";

test("shared views retain topics, burst refresh cancels stale reads, reconnect and last release", async (context) => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const listeners = new Map<string, () => void>();
    const subscribed: string[][] = [];
    const unsubscribed: string[][] = [];
    const order: string[] = [];
    const acknowledgements: (() => void)[] = [];
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
        subscribe: (uids: string[], acknowledged?: () => void) => {
            subscribed.push(uids);
            if (acknowledged) acknowledgements.push(acknowledged);
        },
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
    acknowledgements.shift()!();
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
    assert.deepEqual(order, ["cancel", "read"], "reconnect must wait for topic acknowledgement");
    acknowledgements.shift()!();
    listeners.get("a")!();
    context.mock.timers.tick(250);
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(order, ["cancel", "read", "cancel", "read"]);
    listeners.get("a")!();
    second();
    context.mock.timers.tick(250);
    await Promise.resolve();
    assert.deepEqual(order, ["cancel", "read", "cancel", "read"]);
    assert.deepEqual(unsubscribed, [["b"], ["a"]]);
    assert.equal(listeners.size, 0);
});

test("late acknowledgement cannot refresh released or replacement owners", async (context) => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const acknowledgements: (() => void)[] = [];
    let reconnect = () => {};
    let reads = 0;
    const client = {
        cancelQueries: async () => {},
        invalidateQueries: async () => {
            reads++;
        },
    };
    const socket = {
        subscribe: (_uids: string[], acknowledged?: () => void) => {
            if (acknowledged) acknowledgements.push(acknowledged);
        },
        unsubscribe: () => {},
        listen: () => () => {},
        listenOpen: (callback: () => void) => {
            reconnect = callback;
            return () => {};
        },
    };
    const release = acquireProjectWorkload(client as never, ["a"], socket);
    reconnect();
    const late = acknowledgements.splice(0);
    release();
    const replacement = acquireProjectWorkload(client as never, ["b"], socket);
    late.forEach((acknowledge) => acknowledge());
    context.mock.timers.tick(250);
    await Promise.resolve();
    assert.equal(reads, 0);
    acknowledgements.shift()!();
    context.mock.timers.tick(250);
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(reads, 1);
    replacement();
});
