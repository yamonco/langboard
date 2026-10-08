import assert from "node:assert/strict";
import console from "node:console";
import { setImmediate } from "node:timers";
import { URLSearchParams } from "node:url";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import ts from "typescript";
import { Hocuspocus, Document } from "@hocuspocus/server";
import * as Y from "yjs";
const directory = await fs.mkdtemp(path.join(os.tmpdir(), "langboard-editor-flush-"));
async function load(file, bindings) {
    const source = (await fs.readFile(file, "utf8")).replace(/^import .*;\n/gm, "").replace(/export default /g, "");
    const name = file.includes("flushEditorSync") ? "flushEditorSyncDocuments" : "EditorSyncStorage";
    return new Function(
        ...Object.keys(bindings),
        ts.transpileModule(source + "\nreturn " + name + ";", { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
    )(...Object.values(bindings));
}
const storage = await load("src/core/server/EditorSyncStorage.ts", { DATA_DIR: directory, fs, path, crypto });
const flush = await load("src/core/server/flushEditorSyncDocuments.ts", {});
const instance = new Hocuspocus({
    debounce: 60000,
    onStoreDocument: async ({ documentName, document }) => storage.save(documentName, Y.encodeStateAsUpdate(document)),
});
const doc = new Document("card:shutdown:description");
doc.isLoading = false;
doc.directConnectionsCount = 1;
instance.documents.set(doc.name, doc);
const payload = {
    document: doc,
    documentName: doc.name,
    instance,
    clientsCount: 0,
    context: {},
    requestHeaders: {},
    requestParameters: new URLSearchParams(),
    socketId: "",
};
try {
    doc.getText("body").insert(0, "before shutdown");
    await instance.storeDocumentHooks(doc, payload);
    assert.equal(await storage.load(doc.name), null, "native debounce has not persisted yet");
    let release, entered;
    const held = new Promise((r) => (release = r)),
        started = new Promise((r) => (entered = r));
    const oldSave = doc.saveMutex.runExclusive(async () => {
        await storage.save(doc.name, Y.encodeStateAsUpdate(doc));
        entered();
        await held;
    });
    await started;
    doc.getText("body").insert(doc.getText("body").length, " latest edit");
    let completed = false;
    const operation = flush(instance).then(() => (completed = true));
    await new Promise((r) => setImmediate(r));
    assert.equal(completed, false, "flush waits for native in-flight save mutex");
    release();
    await oldSave;
    await operation;
    const restored = new Y.Doc();
    Y.applyUpdate(restored, await storage.load(doc.name));
    assert.equal(restored.getText("body").toString(), "before shutdown latest edit");
    restored.destroy();
    assert.equal(instance.debouncer.isDebounced(`onStoreDocument-${doc.name}`), false, "pending timer consumed");
    const loading = new Document("card:loading:description");
    loading.isLoading = true;
    instance.documents.set(loading.name, loading);
    await flush(instance);
    assert.equal(await storage.load(loading.name), null, "failed/incomplete load not persisted");
    loading.destroy();
    instance.documents.delete(loading.name);
    const other = new Document("card:other:description");
    other.isLoading = false;
    other.directConnectionsCount = 1;
    other.getText("body").insert(0, "another pending document");
    instance.documents.set(other.name, other);
    let releaseOther;
    const heldOther = new Promise((resolve) => {
        releaseOther = resolve;
    });
    instance.configuration.extensions.unshift({
        onStoreDocument: async ({ documentName }) => {
            if (documentName === other.name) {
                await heldOther;
                return;
            }
            throw new Error("storage unavailable");
        },
    });
    const stderr = console.error;
    console.error = () => {};
    try {
        let settled = false;
        const failedFlush = assert
            .rejects(flush(instance), (error) => {
                assert(error instanceof AggregateError);
                assert.equal(error.errors[0].message, "storage unavailable");
                return true;
            })
            .then(() => {
                settled = true;
            });
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(settled, false, "a failed document must not end shutdown while another save is pending");
        releaseOther();
        await failedFlush;
        const restoredOther = new Y.Doc();
        Y.applyUpdate(restoredOther, await storage.load(other.name));
        assert.equal(restoredOther.getText("body").toString(), "another pending document");
        restoredOther.destroy();
    } finally {
        console.error = stderr;
        other.destroy();
    }
    console.log(
        "PASS native Hocuspocus flush: debounce, in-flight mutex, latest Yjs disk restore, incomplete load exclusion, storage failure propagation"
    );
} finally {
    doc.destroy();
    instance.documents.clear();
    await fs.rm(directory, { recursive: true, force: true });
}
