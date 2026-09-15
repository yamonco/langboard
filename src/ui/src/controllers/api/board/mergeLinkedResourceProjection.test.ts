import assert from "node:assert/strict";
import test from "node:test";
import { mergeLinkedResourceProjection } from "./mergeLinkedResourceProjection.ts";

test("a board header refresh retains already authorized detail", () => {
    const content = { content: "loaded body" };
    const result = mergeLinkedResourceProjection(
        { uid: "wiki", status: "available", title: "Updated title" },
        { uid: "wiki", status: "available", title: "Old title", preview: "loaded", content }
    );

    assert.deepEqual(result, {
        uid: "wiki",
        status: "available",
        title: "Updated title",
        preview: "loaded",
        content,
    });
});

test("permission and source changes never retain detail", () => {
    const existing = { uid: "wiki", status: "available" as const, content: { content: "private" } };

    assert.equal(mergeLinkedResourceProjection({ uid: "wiki", status: "forbidden" }, existing).content, undefined);
    assert.equal(mergeLinkedResourceProjection({ uid: "wiki", status: "missing" }, existing).content, undefined);
    assert.equal(mergeLinkedResourceProjection({ uid: "replacement", status: "available" }, existing).content, undefined);
});

test("a fresh detail response replaces stale detail", () => {
    const incoming = { uid: "wiki", status: "available" as const, content: { content: "fresh" } };
    const result = mergeLinkedResourceProjection(incoming, {
        uid: "wiki",
        status: "available",
        content: { content: "stale" },
    });

    assert.equal(result, incoming);
});
