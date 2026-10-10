import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
import { setImmediate, setTimeout, clearTimeout } from "node:timers";
import console from "node:console";
const source = fs.readFileSync("src/SafeExit.ts", "utf8").replace(/^import .*;\n/gm, "");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
function fixture({ server = async () => {}, consumer = async () => {}, expire = false } = {}) {
    const handlers = new Map(),
        calls = [],
        logs = [],
        exits = [];
    const target = { on: (signal, handler) => handlers.set(signal, handler), exit: (code) => exits.push(code) };
    const timer = expire
        ? (callback) => {
              setImmediate(callback);
              return { unref() {} };
          }
        : setTimeout;
    new Function("Server", "Consumer", "Cache", "DB", "Logger", "process", "setTimeout", "clearTimeout", compiled)(
        {
            destroy: async () => {
                calls.push("server");
                await server();
            },
        },
        {
            stop: async () => {
                calls.push("consumer");
                await consumer();
            },
        },
        { stop: async () => calls.push("cache") },
        { destroy: async () => calls.push("database") },
        { red: (message) => logs.push(message), green: () => {}, cyan: () => {} },
        target,
        timer,
        expire ? () => {} : clearTimeout
    );
    return { handlers, calls, logs, exits };
}
let release;
const held = new Promise((resolve) => (release = resolve));
const waiting = fixture({ server: () => held });
const operation = waiting.handlers.get("SIGTERM")();
await new Promise((resolve) => setImmediate(resolve));
assert.deepEqual(waiting.calls, ["server"]);
assert.equal(waiting.exits.length, 0);
await waiting.handlers.get("SIGTERM")();
assert.deepEqual(waiting.calls, ["server"], "repeated signal does not duplicate shutdown");
release();
await operation;
assert.deepEqual(waiting.calls, ["server", "consumer", "cache", "database"]);
assert.deepEqual(waiting.exits, [0]);
const failed = fixture({
    server: async () => {
        throw new Error("editor persistence failed");
    },
});
await failed.handlers.get("SIGTERM")();
assert.deepEqual(failed.exits, [1]);
assert.deepEqual(failed.calls, ["server", "consumer", "cache", "database"]);
assert(failed.logs.some((x) => x.includes("editor persistence failed")));
const timed = fixture({ consumer: () => new Promise(() => {}), expire: true });
await timed.handlers.get("SIGTERM")();
assert.deepEqual(timed.exits, [1]);
assert(timed.logs.some((x) => x.includes("consumer shutdown timed out")));
assert.equal(timed.calls.at(-1), "database");
const error = fixture();
error.handlers.get("uncaughtException")(new Error("fatal"));
await new Promise((resolve) => setImmediate(resolve));
assert.deepEqual(error.exits, [1]);
console.log(
    "PASS actual signal handlers: await editor persistence, duplicate-signal guard, failure/timeout nonzero exit, continued cleanup, fatal-error exit"
);
