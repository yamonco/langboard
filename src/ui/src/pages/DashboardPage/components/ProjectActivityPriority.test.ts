import assert from "node:assert/strict";
import test from "node:test";
import {
    compareProjectActivityPriority,
    newerProjectActivity,
    projectActivityAt,
    projectPriorityScore,
    type IProjectActivityPriority,
} from "./ProjectActivityPriority.ts";
import { parseProjectActivityTimestamp } from "../../../core/models/projectActivityTimestamp.ts";

const project = (overrides: Partial<IProjectActivityPriority>): IProjectActivityPriority => ({
    uid: "project-a",
    title: "Alpha",
    starred: false,
    created_at: new Date("2026-01-01T00:00:00Z"),
    last_viewed_at: new Date("2026-01-01T00:00:00Z"),
    view_count: 0,
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

test("activity timestamp parsing preserves dates and accepts nullable API values", () => {
    const existing = new Date("2026-09-10T02:00:00Z");

    assert.equal(parseProjectActivityTimestamp(existing), existing);
    assert.equal(parseProjectActivityTimestamp(null), null);
    assert.equal(parseProjectActivityTimestamp(undefined), null);
    assert.equal(parseProjectActivityTimestamp("not-a-date"), null);
    assert.equal(parseProjectActivityTimestamp("2026-09-11T02:00:00Z")?.toISOString(), "2026-09-11T02:00:00.000Z");
});

test("related sections display the same activity clock used for their ordering", () => {
    const globalActivity = new Date("2026-09-10T02:00:00Z");
    const relatedActivity = new Date("2026-09-09T02:00:00Z");
    const candidate = project({ last_activity_at: globalActivity, related_activity_at: relatedActivity });

    assert.equal(projectActivityAt(candidate, "project"), globalActivity);
    assert.equal(projectActivityAt(candidate, "related"), relatedActivity);
});

test("smart priority combines viewing, actual work, related work, and frequency", () => {
    const now = new Date("2026-09-11T00:00:00Z").getTime();
    const baseline = project({
        last_viewed_at: new Date("2026-08-01T00:00:00Z"),
        last_activity_at: new Date("2026-08-01T00:00:00Z"),
    });
    const engaged = project({
        last_viewed_at: new Date("2026-09-10T00:00:00Z"),
        last_activity_at: new Date("2026-09-09T00:00:00Z"),
        related_activity_at: new Date("2026-09-08T00:00:00Z"),
        view_count: 20,
    });

    assert.ok(projectPriorityScore(engaged, now) > projectPriorityScore(baseline, now));
});
