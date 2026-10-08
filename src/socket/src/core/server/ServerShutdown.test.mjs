import assert from "node:assert/strict";
import console from "node:console";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import * as http from "node:http";
import { once } from "node:events";
import { setImmediate, setTimeout, clearTimeout } from "node:timers";
import { URLSearchParams } from "node:url";
import ts from "typescript";
import { WebSocket, WebSocketServer } from "ws";
import { Document, Hocuspocus } from "@hocuspocus/server";
import * as Y from "yjs";
const directory = await fs.mkdtemp(path.join(os.tmpdir(), "langboard-server-shutdown-"));
async function load(file, bindings, result) {
    const source = (await fs.readFile(file, "utf8"))
        .replace(/^import .*;\n/gm, "")
        .replace(/export default .*;\n/gm, "")
        .replace(/export default /g, "");
    return new Function(
        ...Object.keys(bindings),
        ts.transpileModule(source + "\nreturn " + result + ";", { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
    )(...Object.values(bindings));
}
const storage = await load("src/core/server/EditorSyncStorage.ts", { DATA_DIR: directory, fs, path, crypto }, "EditorSyncStorage");
const flush = await load("src/core/server/flushEditorSyncDocuments.ts", {}, "flushEditorSyncDocuments");
async function fixture(fail) {
    let releaseSave, saveStarted, transport;
    const held = new Promise((r) => (releaseSave = r)),
        started = new Promise((r) => (saveStarted = r));
    const hocus = new Hocuspocus({
        onStoreDocument: async ({ document, documentName }) => {
            saveStarted();
            await held;
            if (fail) throw new Error("disk failure");
            await storage.save(documentName, Y.encodeStateAsUpdate(document));
        },
    });
    const doc = new Document(`card:${fail ? "failed" : "successful"}:description`);
    doc.isLoading = false;
    doc.directConnectionsCount = 1;
    doc.getText("body").insert(0, "last edit before shutdown");
    hocus.documents.set(doc.name, doc);
    const server = await load(
        "src/core/server/Server.ts",
        {
            PORT: 0,
            SOCKET_MAX_PAYLOAD_MB: 8,
            http: { createServer: (...args) => (transport = http.createServer(...args)) },
            WebSocketServer,
            Logger: { cyan: () => {} },
            Routes: { route: async (_req, res) => res.end("ok") },
            SocketManager: class {
                async destroy() {}
            },
            Hocus: hocus,
            flushEditorSyncDocuments: flush,
            ESocketStatus: { WS_1012_SERVICE_RESTART: 1012 },
            setTimeout,
            clearTimeout,
        },
        "Server"
    );
    await new Promise((resolve) => server.run(undefined, resolve));
    const port = transport.address().port;
    const client = new WebSocket(`ws://127.0.0.1:${port}`);
    await once(client, "open");
    const close = once(client, "close");
    let settled = false;
    const errors = console.error;
    console.error = () => {};
    try {
        const stop = server.destroy();
        const outcome = stop.then(
            () => {
                settled = true;
                return null;
            },
            (error) => {
                settled = true;
                return error;
            }
        );
        const [code] = await close;
        assert.equal(code, 1012);
        await started;
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(settled, false, "transport closure cannot complete before persistence");
        await assert.rejects(
            new Promise((resolve, reject) => http.get(`http://127.0.0.1:${port}`, resolve).on("error", reject)),
            "closed transport cannot accept requests"
        );
        releaseSave();
        const error = await outcome;
        if (fail) {
            assert(error instanceof AggregateError);
            assert.equal(error.errors[0].message, "disk failure");
        } else {
            assert.equal(error, null);
            const restored = new Y.Doc();
            Y.applyUpdate(restored, await storage.load(doc.name));
            assert.equal(restored.getText("body").toString(), "last edit before shutdown");
            restored.destroy();
        }
    } finally {
        console.error = errors;
        releaseSave();
        client.terminate();
        doc.destroy();
        hocus.documents.clear();
    }
}
try {
    await fixture(false);
    await fixture(true);
    console.log(
        "PASS actual Server.destroy + HTTP/WebSocket + native Hocuspocus: close1012, transport stopped, save awaited, disk restore, failure rejects"
    );
} finally {
    await fs.rm(directory, { recursive: true, force: true });
}
