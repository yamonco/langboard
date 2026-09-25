import assert from "node:assert/strict";
import test from "node:test";
import {
    applyProjectDockProjection,
    monotonicProjectDockRevision,
    pinnedProjectDockColumns,
    preserveProjectDockMetadata,
    reorderProjectDockDraft,
    retainProjectDockSnapshot,
} from "./projectDock.ts";

test("unknown-column snapshot survives until columns load and stale snapshots cannot replace it", () => {
    const source = { revision: 3, column_uids: ["later"] };
    const saved = retainProjectDockSnapshot(2, source)!;
    source.column_uids.push("mutated");
    assert.deepEqual(saved.column_uids, ["later"]);
    const project = { dock_revision: saved.revision };
    assert.equal(applyProjectDockProjection(project, [], saved), false);
    assert.equal(retainProjectDockSnapshot(project.dock_revision, { revision: 2, column_uids: [] }), null);
    assert.equal(retainProjectDockSnapshot(3, { revision: 4, column_uids: ["a", "a"] }), null);
    const loaded = [{ uid: "later", is_archive: false, dock_order: null as number | null }];
    assert.ok(applyProjectDockProjection(project, loaded, saved));
    assert.equal(loaded[0].dock_order, 0);
});

test("late metadata cannot lower Dock revision or overwrite committed positions", () => {
    for (const value of [0, 3, -1, 4.5, "9", undefined, Number.NaN, Number.MAX_SAFE_INTEGER + 1]) {
        assert.equal(monotonicProjectDockRevision(4, value), 4);
    }
    assert.equal(monotonicProjectDockRevision(4, 4), 4);
    assert.equal(monotonicProjectDockRevision(4, 5), 5);
    const incoming = { uid: "a", name: "Renamed", order: 7, dock_order: 0, is_archive: false };
    assert.deepEqual(preserveProjectDockMetadata(incoming, 2), { ...incoming, dock_order: 2 });
    assert.deepEqual(preserveProjectDockMetadata(incoming, null), { ...incoming, dock_order: null });
    assert.equal(incoming.dock_order, 0);
});

test("dock draft keyboard reordering preserves membership and source order", () => {
    const initial = ["a", "b", "c"];
    assert.deepEqual(reorderProjectDockDraft(initial, 1, -1), ["b", "a", "c"]);
    assert.deepEqual(reorderProjectDockDraft(initial, 1, 1), ["a", "c", "b"]);
    for (const index of [-1, 3, 0.5, Number.NaN]) assert.deepEqual(reorderProjectDockDraft(initial, index, 1), initial);
    assert.deepEqual(reorderProjectDockDraft(initial, 0, -1), initial);
    assert.deepEqual(reorderProjectDockDraft(initial, 2, 1), initial);
    assert.deepEqual(reorderProjectDockDraft([], 0, 1), []);
    assert.deepEqual(initial, ["a", "b", "c"]);
});

test("shared dock ordering excludes system and invalid slots without mutating board order", () => {
    const columns = [
        { uid: "c", is_archive: false, dock_order: 1, order: 0 },
        { uid: "a", is_archive: false, dock_order: 0, order: 9 },
        { uid: "b", is_archive: false, dock_order: 1, order: 4 },
        { uid: "archive", is_archive: true, dock_order: 0, order: 2 },
        { uid: "unpin", is_archive: false, dock_order: null, order: 3 },
        { uid: "negative", is_archive: false, dock_order: -1, order: 5 },
        { uid: "fraction", is_archive: false, dock_order: 1.5, order: 6 },
    ];
    const before = structuredClone(columns);
    assert.deepEqual(
        pinnedProjectDockColumns(columns).map((column) => column.uid),
        ["a", "b", "c"]
    );
    assert.deepEqual(columns, before);
    assert.deepEqual(pinnedProjectDockColumns([]), []);
});

function fixture() {
    return {
        project: { dock_revision: 0 },
        columns: ["a", "b", "c", "archive"].map((uid) => ({ uid, is_archive: uid === "archive", dock_order: null as number | null })),
    };
}

test("whole-list replacement, stale arrival, equal replay and clear", () => {
    const { project, columns } = fixture();
    assert.ok(applyProjectDockProjection(project, columns, { column_uids: ["c", "a"], revision: 2 }));
    assert.deepEqual(
        columns.map((c) => c.dock_order),
        [1, null, 0, null]
    );
    assert.equal(applyProjectDockProjection(project, columns, { column_uids: ["b"], revision: 1 }), false);
    assert.equal(project.dock_revision, 2);
    assert.ok(applyProjectDockProjection(project, columns, { column_uids: ["c", "a"], revision: 2 }));
    assert.ok(applyProjectDockProjection(project, columns, { column_uids: [], revision: 3 }));
    assert.ok(columns.every((c) => c.dock_order === null));
});

for (const column_uids of [["a", "a"], ["a", "foreign"], ["archive"]]) {
    test(`invalid target list ${column_uids} changes no projection`, () => {
        const { project, columns } = fixture();
        assert.equal(applyProjectDockProjection(project, columns, { column_uids, revision: 1 }), false);
        assert.equal(project.dock_revision, 0);
        assert.ok(columns.every((c) => c.dock_order === null));
    });
}

test("invalid revisions leave current projection untouched", () => {
    for (const revision of [-1, NaN, Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
        const { project, columns } = fixture();
        assert.equal(applyProjectDockProjection(project, columns, { column_uids: ["a"], revision }), false);
        assert.equal(project.dock_revision, 0);
    }
});
