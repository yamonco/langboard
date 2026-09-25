import { expect, test } from "@playwright/test";

test("native Dock models reject stale metadata and recover unloaded columns through Axios", async ({ page }) => {
    await page.goto("/src/controllers/api/board/refreshProjectColumnDock.fixture.html");
    const result = await page.evaluate(async () => {
        const modelsPath = "/src/core/models/index.ts";
        const refreshPath = "/src/controllers/api/board/refreshProjectColumnDock.ts";
        const applyPath = "/src/core/helpers/applyProjectDockSnapshot.ts";
        const apiPath = "/src/core/helpers/Api.ts";
        const { Project, ProjectColumn } = await import(modelsPath);
        const { default: refresh } = await import(refreshPath);
        const { default: apply } = await import(applyPath);
        const { api } = await import(apiPath);
        const base = { created_at: new Date(), updated_at: new Date() };
        const project = Project.Model.fromOne({ ...base, uid: "dock-test", title: "Original", dock_revision: 0 });
        const column = ProjectColumn.Model.fromOne({ ...base, uid: "first", project_uid: project.uid, name: "First", order: 0, dock_order: 4 });
        const coldOrder = column.dock_order;
        apply(project.uid, { revision: 3, column_uids: [column.uid] });
        Project.Model.fromOne({ ...base, uid: project.uid, title: "Updated", dock_revision: 1 });
        ProjectColumn.Model.fromArray([{ ...base, uid: column.uid, project_uid: project.uid, name: "Renamed", dock_order: null }]);
        const metadata = { revision: project.dock_revision, title: project.title, order: column.dock_order, name: column.name };
        const calls: string[] = [];
        api.defaults.adapter = async (config: { url: string }) => {
            calls.push(config.url);
            if (config.url.endsWith("/columns")) apply(project.uid, { revision: 5, column_uids: ["first", "second"] });
            const data = config.url.endsWith("/columns")
                ? { columns: [{ ...base, uid: "second", project_uid: project.uid, name: "Second", order: 1, is_archive: false }] }
                : { revision: 4, column_uids: ["second", "first"] };
            return { data, status: 200, statusText: "OK", headers: {}, config };
        };
        await Promise.all([refresh(project.uid), refresh(project.uid)]);
        return {
            coldOrder,
            metadata,
            calls,
            revision: project.dock_revision,
            first: column.dock_order,
            second: ProjectColumn.Model.getModel("second")?.dock_order,
        };
    });
    expect(result.coldOrder).toBeNull();
    expect(result.metadata).toEqual({ revision: 3, title: "Updated", order: 0, name: "Renamed" });
    expect(result.calls).toHaveLength(2);
    expect(result.calls[1]).toMatch(/\/columns$/);
    expect(result).toMatchObject({ revision: 5, first: 0, second: 1 });
});

test("logout invalidates an in-flight Dock response even before model cleanup", async ({ page }) => {
    await page.goto("/src/controllers/api/board/refreshProjectColumnDock.fixture.html");
    const result = await page.evaluate(async () => {
        const modelsPath = "/src/core/models/index.ts";
        const refreshPath = "/src/controllers/api/board/refreshProjectColumnDock.ts";
        const apiPath = "/src/core/helpers/Api.ts";
        const authPath = "/src/core/stores/AuthStore.ts";
        const { Project, ProjectColumn } = await import(modelsPath);
        const { default: refresh } = await import(refreshPath);
        const { api } = await import(apiPath);
        const { getAuthStore } = await import(authPath);
        const base = { created_at: new Date(), updated_at: new Date() };
        const project = Project.Model.fromOne({ ...base, uid: "logout-dock", dock_revision: 0 });
        const column = ProjectColumn.Model.fromOne({ ...base, uid: "logout-column", project_uid: project.uid });
        let release: () => void = () => {};
        let started: () => void = () => {};
        const ready = new Promise<void>((resolve) => {
            started = resolve;
        });
        const pending = new Promise<void>((resolve) => {
            release = resolve;
        });
        api.defaults.adapter = async (config: { url: string }) => {
            started();
            await pending;
            return { data: { revision: 8, column_uids: [column.uid] }, status: 200, statusText: "OK", headers: {}, config };
        };
        const request = refresh(project.uid);
        await ready;
        getAuthStore().removeToken();
        release();
        await request.catch((error: { code: string }) => {
            if (error.code !== "ERR_CANCELED") throw error;
        });
        return { revision: project.dock_revision, snapshot: project.latestDockSnapshot, order: column.dock_order };
    });
    expect(result).toEqual({ revision: 0, snapshot: null, order: null });
});

test("old session completion cannot clear or reuse the new session's pending request", async ({ page }) => {
    await page.goto("/src/controllers/api/board/refreshProjectColumnDock.fixture.html");
    const result = await page.evaluate(async () => {
        const modelsPath = "/src/core/models/index.ts";
        const refreshPath = "/src/controllers/api/board/refreshProjectColumnDock.ts";
        const apiPath = "/src/core/helpers/Api.ts";
        const authPath = "/src/core/stores/AuthStore.ts";
        const { Project, ProjectColumn } = await import(modelsPath);
        const { default: refresh } = await import(refreshPath);
        const { api } = await import(apiPath);
        const { getAuthStore } = await import(authPath);
        const base = { created_at: new Date(), updated_at: new Date() };
        const project = Project.Model.fromOne({ ...base, uid: "session-dock", dock_revision: 0 });
        const column = ProjectColumn.Model.fromOne({ ...base, uid: "session-column", project_uid: project.uid });
        const releases: (() => void)[] = [];
        let firstStarted: () => void = () => {};
        let secondStarted: () => void = () => {};
        const firstReady = new Promise<void>((resolve) => {
            firstStarted = resolve;
        });
        const secondReady = new Promise<void>((resolve) => {
            secondStarted = resolve;
        });
        api.defaults.adapter = async (config: { url: string }) => {
            const index = releases.length;
            const pending = new Promise<void>((resolve) => {
                releases.push(resolve);
            });
            if (index === 0) firstStarted();
            if (index === 1) secondStarted();
            await pending;
            return { data: { revision: index === 0 ? 20 : 9, column_uids: [column.uid] }, status: 200, statusText: "OK", headers: {}, config };
        };
        const oldRequest = refresh(project.uid);
        await firstReady;
        getAuthStore().removeToken();
        const newRequest = refresh(project.uid);
        await secondReady;
        releases[0]();
        await oldRequest.catch((error: { code: string }) => {
            if (error.code !== "ERR_CANCELED") throw error;
        });
        const joined = refresh(project.uid);
        releases[1]();
        await Promise.all([newRequest, joined]);
        return { calls: releases.length, revision: project.dock_revision, order: column.dock_order };
    });
    expect(result).toEqual({ calls: 2, revision: 9, order: 0 });
});

test("a failed Dock read preserves the projection and permits an explicit fresh read", async ({ page }) => {
    await page.goto("/src/controllers/api/board/refreshProjectColumnDock.fixture.html");
    const result = await page.evaluate(async () => {
        const modelsPath = "/src/core/models/index.ts";
        const refreshPath = "/src/controllers/api/board/refreshProjectColumnDock.ts";
        const apiPath = "/src/core/helpers/Api.ts";
        const { Project, ProjectColumn } = await import(modelsPath);
        const { default: refresh } = await import(refreshPath);
        const { api } = await import(apiPath);
        const base = { created_at: new Date(), updated_at: new Date() };
        const project = Project.Model.fromOne({ ...base, uid: "failure-dock", dock_revision: 0 });
        const column = ProjectColumn.Model.fromOne({ ...base, uid: "failure-column", project_uid: project.uid });
        let calls = 0;
        api.defaults.adapter = async (config: { url: string }) => {
            calls += 1;
            if (calls === 1) throw new Error("Synthetic Dock read failure");
            return { data: { revision: 1, column_uids: [column.uid] }, status: 200, statusText: "OK", headers: {}, config };
        };
        let rejected = false;
        try {
            await refresh(project.uid);
        } catch {
            rejected = true;
        }
        const failed = { revision: project.dock_revision, snapshot: project.latestDockSnapshot, order: column.dock_order };
        await refresh(project.uid);
        return { rejected, failed, calls, revision: project.dock_revision, order: column.dock_order };
    });
    expect(result).toEqual({ rejected: true, failed: { revision: 0, snapshot: null, order: null }, calls: 2, revision: 1, order: 0 });
});
