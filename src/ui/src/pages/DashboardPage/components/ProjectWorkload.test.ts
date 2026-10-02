import assert from "node:assert/strict";
import test from "node:test";
import { workloadColumns, workloadSearch, workloadTotal, matchesWorkload, type WorkloadColumn } from "./ProjectWorkload.ts";
const column = (fields: Partial<WorkloadColumn> = {}): WorkloadColumn => ({
    uid: "open",
    name: "Done",
    order: 0,
    is_archive: false,
    workflow_stage: "active",
    incomplete_count: 3,
    ...fields,
});
test("counts require authoritative values and exclude closed/archive/reference rather than names", () => {
    const columns = [
        column(),
        column({ uid: "closed", workflow_stage: "closed", incomplete_count: 99 }),
        column({ uid: "archive", is_archive: true, incomplete_count: 88 }),
        column({ uid: "reference", workflow_stage: "reference", incomplete_count: 77 }),
        column({ uid: "next", name: "Ready", order: 1, incomplete_count: 2 }),
    ];
    assert.equal(workloadTotal(columns), 5);
    assert.equal(workloadTotal([column({ workflow_stage: null, name: "Done" })]), 0);
    assert.equal(matchesWorkload({ project_column_uid: "open" }, column({ workflow_stage: null, name: "Done" })), false);
    assert.deepEqual(
        workloadColumns(columns).map((value) => value.uid),
        ["open", "next"]
    );
    assert.equal(workloadTotal([column({ incomplete_count: undefined })]), undefined);
    assert.equal(workloadTotal([column({ incomplete_count: -1 })]), undefined);
    assert.equal(workloadTotal([column({ incomplete_count: 0 })]), 0);
});
test("badge links retain exact column identity and unfinished filter", () => {
    const params = new URLSearchParams(workloadSearch("uid:a,b"));
    const parts = params.get("filters")!.split(",");
    assert.equal(parts[0], "unfinished:yes");
    assert.equal(decodeURIComponent(decodeURIComponent(parts[1].slice("columns:".length))), "uid:a,b");
});
test("board filter uses same completion and resource semantics", () => {
    const card = { project_column_uid: "open", work_state: { checklist_progress: { total: 2, completed: 1 } } };
    assert.equal(matchesWorkload(card, column()), true);
    assert.equal(matchesWorkload({ ...card, work_state: { checklist_progress: { total: 2, completed: 2 } } }, column()), false);
    assert.equal(matchesWorkload({ ...card, work_state: { checklist_progress: { total: 0, completed: 0 } } }, column()), true);
    assert.equal(matchesWorkload({ ...card, source_type: "project_wiki" }, column()), false);
    assert.equal(matchesWorkload(card, column({ workflow_stage: "closed" })), false);
    assert.equal(matchesWorkload(card, column({ is_archive: true })), false);
    assert.equal(matchesWorkload(card, undefined), false);
});
