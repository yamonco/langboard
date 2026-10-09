// Executable in Node; frame/window doubles demonstrate the real MessageChannel protocol.
import assert from "node:assert/strict";
import { setTimeout as delay } from "node:timers/promises";
import { connectPanel, createPanelHost, PanelStateCache } from "./index.mjs";

const listeners = new Map();
const parent = {};
globalThis.window = {
    parent,
    addEventListener(type, listener) { listeners.set(type, listener); },
    removeEventListener(type, listener) { if (listeners.get(type) === listener) listeners.delete(type); },
};
const cache = new PanelStateCache();
const context = { project_uid: "board-1", app_key: "notes", app_version: "1", language: "en" };
const key = JSON.stringify(["user-1", context.project_uid, context.app_key, context.app_version]);
const connected = connectPanel({ expectedHostOrigin: "https://board.example" });
const frame = {
    contentWindow: {
        postMessage(data, targetOrigin, ports) {
            assert.equal(targetOrigin, "*");
            const transfer = structuredClone({ data, port: ports[0] }, { transfer: ports });
            listeners.get("message")({ source: parent, origin: "https://board.example", data: transfer.data, ports: [transfer.port] });
        },
    },
    setAttribute() {},
    remove() { this.removed = true; },
};
const dispose = createPanelHost({ frame, context, state: cache.get(key), onState(state) { cache.set(key, state); } });
const panel = await connected;
panel.saveState({ draft: "Saved during editing" });
await delay(20);
assert.equal(cache.get(key).draft, "Saved during editing");
dispose();
await delay(20);
assert.equal(panel.signal.aborted, true);
assert.equal(frame.removed, true);
// A reopened authorized frame receives cache.get(key). Logout must clear all state.
cache.clear();
delete globalThis.window;
console.log("Incremental snapshot preserved; session disposed; logout cache cleared.");
