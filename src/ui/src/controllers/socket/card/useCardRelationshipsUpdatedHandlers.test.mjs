import fs from "node:fs";
import assert from "node:assert/strict";
import ts from "typescript";
const source = fs
    .readFileSync("src/controllers/socket/card/useCardRelationshipsUpdatedHandlers.ts", "utf8")
    .replace(/^import .*;\n/gm, "")
    .replace(/export interface /g, "interface ")
    .replace("export default useCardRelationshipsUpdatedHandlers;", "return useCardRelationshipsUpdatedHandlers;");
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const reads = [];
const synchronized = [];
const hook = new Function("useSocketHandler", "ESocketTopic", "SocketEvents", "Routing", "Utils", "api", "syncCardRelationships", code)(
    (options) => options.onProps.responseConverter,
    { Board: "board" },
    { SERVER: { BOARD: { CARD: { RELATIONSHIPS_UPDATED: "updated" } } } },
    { API: { BOARD: { CARD: { UPDATE_RELATIONSHIPS: "/relationships" } } } },
    { String: { format: (value) => value } },
    { get: () => new Promise((resolve, reject) => reads.push({ resolve, reject })) },
    (value) => synchronized.push(value)
);
const convert = hook({ projectUID: "board" });
const first = convert({ card_uid: "card", relationships_invalidated: true });
const second = convert({ card_uid: "card", relationships_invalidated: true });
reads[1].resolve({ data: { relationships: ["current"] } });
await second;
reads[0].resolve({ data: { relationships: ["obsolete"] } });
await first;
assert.deepEqual(
    synchronized.map((x) => x.relationships),
    [[], [], ["current"]]
);
const denied = convert({ card_uid: "card", relationships_invalidated: true });
reads[2].reject(new Error("access revoked"));
await denied;
assert.deepEqual(synchronized.at(-1).relationships, []);
const stale = convert({ card_uid: "card", relationships_invalidated: true });
await convert({ card_uid: "card", relationships: ["legacy-current"] });
reads[3].resolve({ data: { relationships: ["obsolete"] } });
await stale;
assert.deepEqual(synchronized.at(-1).relationships, ["legacy-current"]);
