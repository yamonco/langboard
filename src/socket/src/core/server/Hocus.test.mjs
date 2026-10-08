import fs from "node:fs";
import assert from "node:assert/strict";
import ts from "typescript";

const source =
    fs
        .readFileSync("src/core/server/Hocus.ts", "utf8")
        .replace(/^import .*;\n/gm, "")
        .replace(/export default Hocus;/, "")
        .replace(/export const /g, "const ") + "\nreturn Hocus;";
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
let allowed = true;
let unavailable = false;
const validations = [];
const hooks = new Function("Hocuspocus", "Subscription", "ESocketTopic", "EEditorCollaborationType", output)(
    class {
        constructor(options) {
            return options;
        }
    },
    {
        validate: async (topic, context) => {
            validations.push({ topic, uid: context.client.user.uid, card: context.topicId });
            if (unavailable) throw new Error("unavailable");
            return allowed;
        },
    },
    { BoardCard: "card" },
    { Card: "card" }
);
const user = { uid: "recipient" };
const authenticated = await hooks.onAuthenticate({ context: { user }, documentName: "card:fixture:description" });
await hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description" });
allowed = false;
await assert.rejects(hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description" }), /permission-denied/);
allowed = true;
unavailable = true;
await assert.rejects(hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description" }), /unavailable/);
unavailable = false;
await assert.rejects(hooks.beforeHandleMessage({ context: {}, documentName: "card:fixture:description" }), /unauthorized/);
await assert.rejects(hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description:extra" }), /invalid-document/);
assert.equal(validations.length, 4);
assert(validations.every((entry) => entry.uid === "recipient" && entry.card === "fixture"));
