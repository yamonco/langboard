import assert from "node:assert/strict";
import test from "node:test";
import {
    buildProjectDiscoverySections,
    buildProjectQuickSwitcherSections,
    isProjectQuickSwitcherShortcut,
    parseProjectListView,
    projectQuickSwitcherShortcutLabel,
    projectListViewStorageKey,
} from "./ProjectDiscovery.ts";

interface ITestProject {
    uid: string;
    title: string;
    starred: boolean;
    created_at: Date;
    last_activity_at: Date | null;
}

const project = (uid: string, overrides: Partial<ITestProject> = {}): ITestProject => ({
    uid,
    title: uid,
    starred: false,
    created_at: new Date("2026-09-01T00:00:00Z"),
    last_activity_at: null,
    ...overrides,
});

test("discovery keeps favorites absolute and derives recent work from actual activity", () => {
    const sections = buildProjectDiscoverySections([
        project("older", { last_activity_at: new Date("2026-09-02T00:00:00Z") }),
        project("favorite", { starred: true, last_activity_at: new Date("2026-09-01T00:00:00Z") }),
        project("newer", { last_activity_at: new Date("2026-09-03T00:00:00Z") }),
    ]);

    assert.deepEqual(
        sections.all.map(({ uid }) => uid),
        ["favorite", "newer", "older"]
    );
    assert.deepEqual(
        sections.favorites.map(({ uid }) => uid),
        ["favorite"]
    );
    assert.deepEqual(
        sections.recent.map(({ uid }) => uid),
        ["newer", "older"]
    );
});

test("recent work is bounded and never duplicates favorites", () => {
    const sections = buildProjectDiscoverySections(
        [
            project("favorite", { starred: true }),
            project("three", { last_activity_at: new Date("2026-09-03T00:00:00Z") }),
            project("two", { last_activity_at: new Date("2026-09-02T00:00:00Z") }),
            project("one", { last_activity_at: new Date("2026-09-01T00:00:00Z") }),
        ],
        2
    );

    assert.deepEqual(
        sections.recent.map(({ uid }) => uid),
        ["three", "two"]
    );
});

test("quick switcher promotes projects without rendering duplicate choices", () => {
    const sections = buildProjectQuickSwitcherSections([
        project("favorite", { starred: true }),
        project("recent", { last_activity_at: new Date("2026-09-03T00:00:00Z") }),
        project("other", { last_activity_at: new Date("2026-09-02T00:00:00Z") }),
    ]);
    const renderedUIDs = [...sections.favorites, ...sections.recent, ...sections.other].map(({ uid }) => uid);

    assert.deepEqual(renderedUIDs, ["favorite", "recent", "other"]);
    assert.equal(new Set(renderedUIDs).size, renderedUIDs.length);
});

test("compact is the safe default and preferences are isolated per user", () => {
    assert.equal(parseProjectListView(undefined), "compact");
    assert.equal(parseProjectListView("unexpected"), "compact");
    assert.equal(parseProjectListView("cards"), "cards");
    assert.notEqual(projectListViewStorageKey("user-a"), projectListViewStorageKey("user-b"));
});

test("quick switcher uses the conventional unmodified command shortcut", () => {
    assert.equal(isProjectQuickSwitcherShortcut({ key: "k", metaKey: true, ctrlKey: false, altKey: false, shiftKey: false }), true);
    assert.equal(isProjectQuickSwitcherShortcut({ key: "K", metaKey: false, ctrlKey: true, altKey: false, shiftKey: false }), true);
    assert.equal(isProjectQuickSwitcherShortcut({ key: "k", metaKey: true, ctrlKey: false, altKey: false, shiftKey: true }), false);
    assert.equal(isProjectQuickSwitcherShortcut({ key: "p", metaKey: true, ctrlKey: false, altKey: false, shiftKey: false }), false);
});

test("quick switcher shows the shortcut for the active platform", () => {
    assert.equal(projectQuickSwitcherShortcutLabel("MacIntel"), "⌘K");
    assert.equal(projectQuickSwitcherShortcutLabel("iPhone"), "⌘K");
    assert.equal(projectQuickSwitcherShortcutLabel("Win32"), "Ctrl K");
    assert.equal(projectQuickSwitcherShortcutLabel("Linux x86_64"), "Ctrl K");
});
