import assert from "node:assert/strict";
import { test } from "node:test";
import { slateNodesToInsertDelta, yTextToSlateElement } from "@slate-yjs/core";
import type { Value } from "platejs";
import * as Y from "yjs";
import { prepareRichDraftPatch } from "./prepareRichDraftPatch.ts";

test("prepares rich content without mutating the source document and preserves node attributes", () => {
    const source = new Y.Doc();
    const root = source.get("content", Y.XmlText);
    const initial: Value = [{ type: "p", children: [{ text: "Before" }] }];
    root.applyDelta(slateNodesToInsertDelta(initial));
    const original = Y.encodeStateAsUpdate(source);
    const next = [
        { type: "h2", children: [{ text: "Heading", bold: true }] },
        { type: "p", children: [{ type: "a", url: "#reference", children: [{ text: "Link" }] }] },
        { type: "img", url: "data:image/png;base64,AA==", children: [{ text: "" }] },
    ];
    const request = JSON.stringify({
        type: "rich_patch_prepare",
        request_id: "a".repeat(32),
        snapshot: Buffer.from(original).toString("base64"),
        value: "Markdown input",
    });
    const response = prepareRichDraftPatch(request, (markdown) => {
        assert.equal(markdown, "Markdown input");
        return next;
    });
    assert.ok(response);
    assert.deepEqual(Y.encodeStateAsUpdate(source), original);
    const prepared = JSON.parse(response);
    assert.equal(prepared.request_id, "a".repeat(32));
    assert.equal(prepared.type, "rich_patch_prepared");
    const update = Buffer.from(prepared.update, "base64");
    Y.applyUpdate(source, update);
    Y.applyUpdate(source, update);
    assert.deepEqual(yTextToSlateElement(root).children, next);
    source.destroy();
});

test("an empty replacement remains an editable paragraph", () => {
    const doc = new Y.Doc();
    const response = prepareRichDraftPatch(
        JSON.stringify({
            type: "rich_patch_prepare",
            request_id: "b".repeat(32),
            snapshot: Buffer.from(Y.encodeStateAsUpdate(doc)).toString("base64"),
            value: "",
        }),
        () => []
    );
    assert.ok(response);
    Y.applyUpdate(doc, Buffer.from(JSON.parse(response).update, "base64"));
    assert.deepEqual(yTextToSlateElement(doc.get("content", Y.XmlText)).children, [{ type: "p", children: [{ text: "" }] }]);
    doc.destroy();
});

test("invalid frames and conversion failures do not produce an update", () => {
    for (const payload of ["not json", "null", "{}", JSON.stringify({ type: "other" })]) {
        assert.equal(
            prepareRichDraftPatch(payload, () => []),
            null
        );
    }
    const doc = new Y.Doc();
    const request = {
        type: "rich_patch_prepare",
        request_id: "c".repeat(32),
        snapshot: Buffer.from(Y.encodeStateAsUpdate(doc)).toString("base64"),
        value: "",
    };
    assert.equal(
        prepareRichDraftPatch(JSON.stringify(request), () => {
            throw new Error("Conversion failed");
        }),
        null
    );
    assert.equal(
        prepareRichDraftPatch(JSON.stringify({ ...request, snapshot: "%%%" }), () => []),
        null
    );
    doc.destroy();
});
