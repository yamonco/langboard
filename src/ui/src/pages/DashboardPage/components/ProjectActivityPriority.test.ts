import assert from "node:assert/strict";
import test from "node:test";
import { compareProjectActivityPriority, newerProjectActivity, projectActivityAt, type IProjectActivityPriority } from "./ProjectActivityPriority.ts";

const project = (overrides: Partial<IProjectActivityPriority>): IProjectActivityPriority => ({
    uid: "project-a",
    title: "Alpha",
    starred: false,
    created_at: new Date("2026-01-01T00:00:00Z"),
    last_activity_at: null,
    ...overrides,
});

test("starred projects stay above newer unstarred activity", () => {
    const projects = [
        project({ uid: "new", title: "New", last_activity_at: new Date("2026-09-10T02:00:00Z") }),
        project({ uid: "starred", title: "Starred", starred: true, last_activity_at: new Date("2026-09-01T02:00:00Z") }),
    ];

    projects.sort(compareProjectActivityPriority);

    assert.deepEqual(
        projects.map(({ uid }) => uid),
        ["starred", "new"]
    );
});

test("actual activity determines recency", () => {
    const projects = [
        project({ uid: "older", title: "Older", last_activity_at: new Date("2026-09-08T02:00:00Z") }),
        project({ uid: "newer", title: "Newer", last_activity_at: new Date("2026-09-09T02:00:00Z") }),
    ];

    projects.sort(compareProjectActivityPriority);

    assert.deepEqual(
        projects.map(({ uid }) => uid),
        ["newer", "older"]
    );
});

test("projects without activity fall back to creation time with stable ties", () => {
    const projects = [
        project({ uid: "b", title: "Same", created_at: new Date("2026-09-01T00:00:00Z") }),
        project({ uid: "a", title: "Same", created_at: new Date("2026-09-01T00:00:00Z") }),
        project({ uid: "new", title: "New", created_at: new Date("2026-09-02T00:00:00Z") }),
    ];

    projects.sort(compareProjectActivityPriority);

    assert.deepEqual(
        projects.map(({ uid }) => uid),
        ["new", "a", "b"]
    );
});

test("realtime activity never regresses or accepts invalid timestamps", () => {
    const current = new Date("2026-09-10T02:00:00Z");

    assert.equal(newerProjectActivity(current, "2026-09-09T02:00:00Z"), current);
    assert.equal(newerProjectActivity(current, "not-a-date"), current);
    assert.equal(newerProjectActivity(current, "2026-09-11T02:00:00Z")?.toISOString(), "2026-09-11T02:00:00.000Z");
});

test("related sections display the same activity clock used for their ordering", () => {
    const globalActivity = new Date("2026-09-10T02:00:00Z");
    const relatedActivity = new Date("2026-09-09T02:00:00Z");
    const candidate = project({ last_activity_at: globalActivity, related_activity_at: relatedActivity });

    assert.equal(projectActivityAt(candidate, "project"), globalActivity);
    assert.equal(projectActivityAt(candidate, "related"), relatedActivity);
});
