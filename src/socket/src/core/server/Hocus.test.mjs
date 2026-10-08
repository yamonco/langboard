import fs from "node:fs";
import assert from "node:assert/strict";
import ts from "typescript";
import { setImmediate } from "node:timers";
import { Connection, Document, OutgoingMessage, IncomingMessage, MessageType } from "@hocuspocus/server";
import * as Y from "yjs";

const source =
    fs
        .readFileSync("src/core/server/Hocus.ts", "utf8")
        .replace(/^import .*;\n/gm, "")
        .replace(/export default Hocus;/, "")
        .replace(/export const /g, "const ") +
    "\nreturn Object.assign(Hocus, {patchEditorSyncText, requestEditorSyncRichPatch, clearInactiveEditorSyncDocument});";
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
let allowed = true;
let unavailable = false;
let canEdit = false;
const validations = [];
const guardSource =
    fs
        .readFileSync("src/core/server/guardEditorConnection.ts", "utf8")
        .replace(/^import .*;\n/gm, "")
        .replace("export default function", "function") + "\nreturn guardEditorConnection;";
const guard = new Function(
    ts.transpileModule(guardSource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
)();
const hooks = new Function(
    "Hocuspocus",
    "Subscription",
    "ESocketTopic",
    "EEditorCollaborationType",
    "resolveCardAudience",
    "guardEditorConnection",
    "EditorSyncStorage",
    output
)(
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
    { Card: "card" },
    async () => new Set(canEdit ? ["recipient"] : []),
    guard,
    { load: async () => null }
);
const user = { uid: "recipient" };
const connectionConfig = {};
const authenticated = await hooks.onAuthenticate({ context: { user }, documentName: "card:fixture:description", connectionConfig });
assert.equal(connectionConfig.readOnly, true);
const connection = { readOnly: true };
canEdit = true;
await hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description", connection });
assert.equal(connection.readOnly, false);
canEdit = false;
await hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description", connection });
assert.equal(connection.readOnly, true);
await hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description", connection });
allowed = false;
await assert.rejects(hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description" }), /permission-denied/);
allowed = true;
unavailable = true;
await assert.rejects(hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description" }), /unavailable/);
unavailable = false;
await assert.rejects(hooks.beforeHandleMessage({ context: {}, documentName: "card:fixture:description" }), /unauthorized/);
await assert.rejects(hooks.beforeHandleMessage({ context: authenticated, documentName: "card:fixture:description:extra" }), /invalid-document/);
assert.equal(validations.length, 6);
assert(validations.every((entry) => entry.uid === "recipient" && entry.card === "fixture"));

// The installed receiver must see the updated readOnly flag before applying Yjs updates.
const document = new Document("card:fixture:description");
const wire = new Connection({ readyState: 1, send: (_message, callback) => callback?.() }, { headers: {} }, document, "wire", authenticated);
wire.beforeHandleMessage(() => hooks.beforeHandleMessage({ context: authenticated, documentName: document.name, connection: wire }));
const draft = new Y.Doc();
draft.getText("body").insert(0, "authorized content");
const update = new OutgoingMessage(document.name).createSyncMessage().writeUpdate(Y.encodeStateAsUpdate(draft)).toUint8Array();
canEdit = true;
wire.handleMessage(update);
await new Promise((resolve) => setImmediate(resolve));
assert.equal(document.getText("body").toString(), "authorized content");
draft.getText("body").insert(0, "unauthorized ");
canEdit = false;
wire.handleMessage(new OutgoingMessage(document.name).createSyncMessage().writeUpdate(Y.encodeStateAsUpdate(draft)).toUint8Array());
await new Promise((resolve) => setImmediate(resolve));
assert.equal(document.getText("body").toString(), "authorized content");
assert.equal(wire.readOnly, true);
wire.close();
document.destroy();
draft.destroy();
await assert.rejects(hooks.patchEditorSyncText(document.name, "body", "denied", user), /permission-denied/);
await assert.rejects(hooks.requestEditorSyncRichPatch(document.name, "denied", user), /permission-denied/);
await assert.rejects(hooks.clearInactiveEditorSyncDocument(document.name, user), /permission-denied/);

// Constructor awareness must be guarded before the connected hook.
for (const permitted of [false, true]) {
    const initial = new Document("card:fixture:description");
    await hooks.onLoadDocument({ documentName: initial.name, document: initial });
    initial.awareness.setLocalState({ user: { name: "participant" } });
    const sent = [];
    allowed = permitted;
    const wire = new Connection(
        {
            readyState: 1,
            send: (message, callback) => {
                sent.push(message);
                callback?.();
            },
        },
        { headers: {} },
        initial,
        "initial",
        authenticated
    );
    assert.equal(sent.length, 0);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(initial.getConnectionsCount(), permitted ? 1 : 0);
    assert.equal(sent.length, 1);
    const frame = new IncomingMessage(sent[0]);
    assert.equal(frame.readVarString(), initial.name);
    assert.equal(frame.readVarUint(), permitted ? MessageType.Awareness : MessageType.CLOSE);
    // Both cases send one frame: permitted awareness or denied close, never denied awareness.
    wire.close();
    initial.destroy();
}
