import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import * as Y from "yjs";

const source = new Y.Doc();
source.clientID = 305419896;
source.getText("title").insert(0, "Before");
const bold = new Y.XmlElement("bold");
bold.insert(0, [new Y.XmlText("Rich")]);
const paragraph = new Y.XmlElement("p");
paragraph.insert(0, [bold]);
source.getXmlFragment("description").insert(0, [paragraph]);
const initial = Y.encodeStateAsUpdate(source);

const nodeEditor = new Y.Doc();
Y.applyUpdate(nodeEditor, initial);
nodeEditor.clientID = 741852963;
nodeEditor.getText("title").insert(2, "N");
const nodeUpdate = Y.encodeStateAsUpdate(nodeEditor, Y.encodeStateVector(source));

function exchangeWithPhoenix(update, args = []) {
    const exported = spawnSync("mix", ["run", "--no-start", "scripts/export_yjs_interop_update.exs", ...args], {
        cwd: path.resolve("../socket_phoenix"),
        input: Buffer.from(update).toString("base64"),
        encoding: "utf8",
        shell: process.platform === "win32",
        timeout: 30_000,
        maxBuffer: 1024 * 1024,
    });
    assert.equal(exported.status, 0, exported.error?.message ?? exported.stderr);
    const encodedUpdate = exported.stdout.trim().split(/\r?\n/).at(-1);
    assert.match(encodedUpdate, /^[A-Za-z0-9+/]+={0,2}$/);
    return Buffer.from(encodedUpdate, "base64");
}

const phoenixUpdate = exchangeWithPhoenix(initial);

const titles = [];
for (const updates of [
    [nodeUpdate, phoenixUpdate],
    [phoenixUpdate, nodeUpdate],
]) {
    const merged = new Y.Doc();
    Y.applyUpdate(merged, initial);
    for (const update of updates) Y.applyUpdate(merged, update);
    Y.applyUpdate(merged, updates[0]);

    const title = merged.getText("title").toString();
    assert.ok(["BeNPfore", "BePNfore"].includes(title));
    assert.equal(merged.getXmlFragment("description").toString(), "<p><bold>Rich</bold></p>");

    const restored = new Y.Doc();
    Y.applyUpdate(restored, Y.encodeStateAsUpdate(merged));
    assert.equal(restored.getText("title").toString(), title);
    assert.equal(restored.getXmlFragment("description").toString(), "<p><bold>Rich</bold></p>");
    titles.push(title);
    restored.destroy();
    merged.destroy();
}

assert.equal(titles[0], titles[1]);

const offline = new Y.Doc();
Y.applyUpdate(offline, initial);
const offlineTitle = offline.getText("title");
const offlineDescription = offline.getXmlFragment("description");
const undo = new Y.UndoManager([offlineTitle, offlineDescription]);
offline.transact(() => {
    offlineTitle.delete(0, 1);
    offlineTitle.insert(0, "Offline-");
    const divider = new Y.XmlElement("hr");
    const image = new Y.XmlElement("img");
    image.setAttribute("src", "https://example.invalid/fixture.png");
    image.setAttribute("width", "320");
    const formatted = new Y.XmlText();
    formatted.insert(0, "Between divider and image", { italic: true });
    const paragraph = new Y.XmlElement("p");
    paragraph.insert(0, [formatted]);
    offlineDescription.insert(1, [divider, paragraph, image]);
});
const editedTitle = offlineTitle.toString();
const editedDescription = offlineDescription.toString();
undo.undo();
assert.equal(offlineTitle.toString(), "Before");
assert.equal(offlineDescription.toString(), source.getXmlFragment("description").toString());
undo.redo();
assert.equal(offlineTitle.toString(), editedTitle);
assert.equal(offlineDescription.toString(), editedDescription);

// Merge the server edit that occurred while this client was disconnected.
const offlineDelta = Y.encodeStateAsUpdate(offline, Y.encodeStateVector(source));
Y.applyUpdate(offline, phoenixUpdate);
for (const updates of [
    [offlineDelta, phoenixUpdate],
    [phoenixUpdate, offlineDelta],
]) {
    const merged = new Y.Doc();
    Y.applyUpdate(merged, initial);
    for (const update of updates) Y.applyUpdate(merged, update);
    const persisted = exchangeWithPhoenix(Y.encodeStateAsUpdate(merged), ["--roundtrip"]);
    const reconnected = new Y.Doc();
    Y.applyUpdate(reconnected, persisted);
    for (const update of updates) Y.applyUpdate(reconnected, update);
    assert.equal(reconnected.getText("title").toString(), offlineTitle.toString());
    assert.equal(reconnected.getXmlFragment("description").toString(), editedDescription);
    assert.deepEqual(Y.encodeStateVector(reconnected), Y.encodeStateVector(offline));
    reconnected.destroy();
    merged.destroy();
}
undo.destroy();
offline.destroy();

for (const seed of [1, 7, 42, 2026, 65537]) {
    let state = seed;
    const random = (max) => {
        state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
        return state % max;
    };
    const updates = [initial];
    const expected = new Y.Doc();
    for (let client = 0; client < 3; client += 1) {
        const doc = new Y.Doc();
        doc.clientID = 10000 + client;
        Y.applyUpdate(doc, initial);
        doc.on("update", (update) => updates.push(update));
        const title = doc.getText("title");
        const description = doc.getXmlFragment("description");
        for (let operation = 0; operation < 12; operation += 1) {
            switch (random(5)) {
                case 0:
                    title.insert(random(title.length + 1), `${client}-${operation}`);
                    break;
                case 1:
                    if (title.length) title.delete(random(title.length), 1);
                    break;
                case 2:
                    if (title.length) title.format(random(title.length), 1, { bold: Boolean(random(2)) });
                    break;
                case 3: {
                    const paragraph = new Y.XmlElement("p");
                    paragraph.insert(0, [new Y.XmlText(`Client ${client} edit ${operation}`)]);
                    description.insert(random(description.length + 1), [paragraph]);
                    break;
                }
                case 4:
                    if (description.length) description.delete(random(description.length), 1);
                    break;
            }
        }
        doc.destroy();
    }
    for (const update of updates) Y.applyUpdate(expected, update);
    for (let delivery = 0; delivery < 2; delivery += 1) {
        const shuffled = [...updates, ...updates];
        for (let index = shuffled.length - 1; index > 0; index -= 1) {
            const other = random(index + 1);
            [shuffled[index], shuffled[other]] = [shuffled[other], shuffled[index]];
        }
        const payload = Buffer.from(JSON.stringify(shuffled.map((update) => Buffer.from(update).toString("base64"))));
        const persisted = exchangeWithPhoenix(payload, ["--replay"]);
        const restored = new Y.Doc();
        Y.applyUpdate(restored, persisted);
        const label = `seed=${seed}, delivery=${delivery}`;
        assert.deepEqual(restored.getText("title").toDelta(), expected.getText("title").toDelta(), label);
        assert.equal(restored.getXmlFragment("description").toString(), expected.getXmlFragment("description").toString(), label);
        assert.deepEqual(Y.encodeStateVector(restored), Y.encodeStateVector(expected), label);
        restored.destroy();
    }
    expected.destroy();
}
nodeEditor.destroy();
source.destroy();
process.stdout.write("Yjs/Yex concurrent delivery, offline rich edits, undo/redo, binary roundtrip, and seeded replay passed\n");
