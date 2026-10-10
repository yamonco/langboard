import fs from "node:fs";
import assert from "node:assert/strict";
import ts from "typescript";
import process from "node:process";
import console from "node:console";
let calls = [];
let fail = false;
let mode = "allowed";
const api = {
    post: async (_, body) => {
        calls.push(body);
        if (fail) throw Error("unavailable");
        return { data: mode === "allowed" ? { allowed_recipient_uids: body.recipient_uids.filter((x) => x !== "external") } : {} };
    },
};
let source = fs
    .readFileSync("src/core/helpers/CardAudience.ts", "utf8")
    .replace(/^import .*;\n/gm, "")
    .replace("export const", "const");
source += "\nreturn resolveCardAudience;";
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const resolve = new Function("api", "API_INTERNAL_URL", "SnowflakeID", "createOneTimeToken", output)(
    api,
    "http://fixture",
    class {
        constructor(x) {
            this.id = x;
        }
    },
    () => "fixture"
);
const clients = Array.from({ length: 205 }, (_, i) => ({ user: { uid: i === 1 ? "external" : String(i), id: String(i) } }));
(async () => {
    let result = await resolve(clients, ["card", "card"]);
    assert.equal(result.size, 204);
    assert.equal(calls.length, 3);
    assert(calls.every((x) => x.recipient_uids.length <= 100 && x.card_uids.length === 1));
    calls = [];
    assert.equal((await resolve(clients, [])).size, 0);
    assert.equal(calls.length, 0);
    assert.equal((await resolve(clients, ["a", "b", "c"])).size, 0);
    assert.equal(calls.length, 0);
    fail = true;
    assert.equal((await resolve(clients, ["card"])).size, 0);
    fail = false;
    mode = "malformed";
    assert.equal((await resolve(clients, ["card"])).size, 0);
    console.log("PASS: batching, duplicate references, denied recipient, missing provenance, excessive references, outage, malformed response");
})().catch((e) => {
    console.error(e);
    process.exit(1);
});
