import fs from "node:fs";
import assert from "node:assert/strict";
import ts from "typescript";
import { setImmediate } from "node:timers";
import { Connection, Document } from "@hocuspocus/server";
const source =
    fs
        .readFileSync("src/core/server/guardEditorConnection.ts", "utf8")
        .replace(/^import .*;\n/gm, "")
        .replace("export default function", "function") + "\nreturn guardEditorConnection;";
const guard = new Function(
    ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
)();
const tick = () => new Promise((resolve) => setImmediate(resolve));
function fixture(name, validate) {
    const sent = [];
    const document = new Document(name);
    const websocket = {
        readyState: 1,
        send: (message, callback) => {
            sent.push(message);
            callback?.();
        },
    };
    const connection = new Connection(websocket, { headers: {} }, document, "fixture", {});
    guard(connection, validate);
    return { connection, document, sent };
}
let allow = true;
const requests = [];
const normal = fixture("card:normal", () => new Promise((resolve, reject) => requests.push({ resolve, reject })));
normal.connection.send("first");
normal.connection.send("second");
await tick();
assert.equal(normal.sent.length, 0);
assert.equal(requests.length, 1);
requests[0].resolve();
await tick();
assert.deepEqual(normal.sent, ["first"]);
assert.equal(requests.length, 2);
requests[1].resolve();
await tick();
assert.deepEqual(normal.sent, ["first", "second"]);
normal.connection.close();
normal.document.destroy();
const revoked = fixture("card:revoked", async () => {
    if (!allow) throw new Error("revoked");
});
revoked.connection.send("authorized");
await tick();
assert(revoked.sent.includes("authorized"));
allow = false;
revoked.document.getText("body").insert(0, "secret after revocation");
revoked.connection.send("another queued secret");
await tick();
assert.equal(revoked.document.getConnectionsCount(), 0);
assert(!revoked.sent.includes("another queued secret"));
// Only the original permitted payload and a native close frame can be sent.
assert.equal(revoked.sent.length, 2);
revoked.document.destroy();
const outage = fixture("card:outage", async () => {
    throw new Error("unavailable");
});
outage.document.getText("body").insert(0, "secret");
await tick();
assert.equal(outage.document.getConnectionsCount(), 0);
assert.equal(outage.sent.length, 1);
outage.document.destroy();
let finish;
const disconnected = fixture(
    "card:disconnected",
    () =>
        new Promise((resolve) => {
            finish = resolve;
        })
);
disconnected.connection.send("queued");
await tick();
disconnected.connection.close();
finish();
await tick();
assert(!disconnected.sent.includes("queued"));
disconnected.document.destroy();
const saturated = fixture("card:saturated", () => new Promise(() => {}));
for (let i = 0; i < 129; i++) saturated.connection.send("queued");
await tick();
assert.equal(saturated.document.getConnectionsCount(), 0);
assert.equal(saturated.sent.length, 1);
saturated.document.destroy();
