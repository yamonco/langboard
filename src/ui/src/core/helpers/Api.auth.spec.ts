import { expect, test } from "@playwright/test";

test("a current expired token refreshes identity and replays the original HTTP request once", async ({ page }) => {
    await page.goto("/src/controllers/api/board/refreshProjectColumnDock.fixture.html");
    let reads = 0;
    let refreshes = 0;
    let identities = 0;
    let replayAuthorization: string | undefined;
    await page.route("**/__token-replay-proof", async (route) => {
        reads += 1;
        if (reads > 1) replayAuthorization = route.request().headers().authorization;
        await route.fulfill({ status: reads === 1 ? 422 : 200, json: { value: "current" } });
    });
    await page.route("**/auth/refresh", async (route) => {
        refreshes += 1;
        await route.fulfill({ status: 200, json: { access_token: "synthetic-test-token" } });
    });
    await page.route("**/auth/me", async (route) => {
        identities += 1;
        await route.fulfill({
            status: 200,
            json: {
                user: {
                    uid: "token-test-user",
                    type: "user",
                    firstname: "Test",
                    lastname: "User",
                    email: "user@example.invalid",
                    username: "synthetic-user",
                    user_groups: [],
                    api_key_role_actions: [],
                    setting_role_actions: [],
                    mcp_role_actions: [],
                    created_at: "2026-01-01T00:00:00Z",
                    updated_at: "2026-01-01T00:00:00Z",
                },
                bots: [],
            },
        });
    });
    const result = await page.evaluate(async () => {
        const apiPath = "/src/core/helpers/Api.ts";
        const authPath = "/src/core/stores/AuthStore.ts";
        const { api } = await import(apiPath);
        const { getAuthStore } = await import(authPath);
        api.defaults.baseURL = location.origin;
        const response = await api.get(`${location.origin}/__token-replay-proof`);
        return {
            status: response.status,
            value: response.data.value,
            user: getAuthStore().currentUser?.uid,
            version: getAuthStore().getSessionVersion(),
        };
    });
    expect(result).toEqual({ status: 200, value: "current", user: "token-test-user", version: 1 });
    expect({ reads, refreshes, identities }).toEqual({ reads: 2, refreshes: 1, identities: 1 });
    expect(replayAuthorization).toBe("Bearer synthetic-test-token");
});

for (const status of [200, 401, 422]) {
    test(`an old session HTTP ${status} cannot hydrate models, log out or refresh the new session`, async ({ page }) => {
        await page.goto("/src/controllers/api/board/refreshProjectColumnDock.fixture.html");
        let release: () => void = () => {};
        const pending = new Promise<void>((resolve) => {
            release = resolve;
        });
        let requests = 0;
        await page.route("**/__session-proof", async (route) => {
            requests += 1;
            await pending;
            await route.fulfill({
                status,
                json: {
                    project: {
                        uid: "previous-session-project",
                        title: "Old projection",
                        created_at: "2026-01-01T00:00:00Z",
                        updated_at: "2026-01-01T00:00:00Z",
                    },
                },
            });
        });
        await page.route("**/auth/refresh", async (route) => {
            requests += 1;
            await route.fulfill({ status: 401, json: {} });
        });
        const resultPromise = page.evaluate(async () => {
            const apiPath = "/src/core/helpers/Api.ts";
            const modelsPath = "/src/core/models/index.ts";
            const handlerPath = "/src/core/helpers/setupApiErrorHandler.ts";
            const { api } = await import(apiPath);
            api.defaults.baseURL = location.origin;
            const { Project } = await import(modelsPath);
            const { default: setupHandler } = await import(handlerPath);
            let canceled = false;
            let errorHandlers = 0;
            try {
                const response = await api.get(`${location.origin}/__session-proof`);
                Project.Model.fromOne(response.data.project);
            } catch (error) {
                canceled = typeof error === "object" && error !== null && "code" in error && error.code === "ERR_CANCELED";
                const handler = setupHandler({
                    wildcard: {
                        message: () => {
                            errorHandlers += 1;
                        },
                    },
                });
                handler.handle(error);
                await handler.handleAsync(error);
            }
            return { canceled, hydrated: !!Project.Model.getModel("previous-session-project"), errorHandlers };
        });
        await page.waitForRequest("**/__session-proof");
        const version = await page.evaluate(async () => {
            const authPath = "/src/core/stores/AuthStore.ts";
            const { getAuthStore } = await import(authPath);
            getAuthStore().removeToken();
            return getAuthStore().getSessionVersion();
        });
        release();
        expect.soft(await resultPromise).toEqual({ canceled: true, hydrated: false, errorHandlers: 0 });
        expect.soft(requests).toBe(1);
        const afterVersion = await page.evaluate(async () => {
            const authPath = "/src/core/stores/AuthStore.ts";
            const { getAuthStore } = await import(authPath);
            return getAuthStore().getSessionVersion();
        });
        expect.soft(afterVersion).toBe(version);
    });
}

for (const status of [200, 401, 403]) {
    test(`same-session HTTP ${status} retains its normal success or denial behavior`, async ({ page }) => {
        await page.goto("/src/controllers/api/board/refreshProjectColumnDock.fixture.html");
        await page.route("**/__current-session-proof", (route) => route.fulfill({ status, json: { value: "current" } }));
        const result = await page.evaluate(async () => {
            const apiPath = "/src/core/helpers/Api.ts";
            const authPath = "/src/core/stores/AuthStore.ts";
            const { api } = await import(apiPath);
            const { getAuthStore } = await import(authPath);
            const before = getAuthStore().getSessionVersion();
            let status = 0;
            let value: string | null = null;
            try {
                const response = await api.get(`${location.origin}/__current-session-proof`);
                status = response.status;
                value = response.data.value;
            } catch (error) {
                if (typeof error === "object" && error !== null && "response" in error) status = (error.response as { status: number }).status;
            }
            return { status, value, versionChanged: getAuthStore().getSessionVersion() !== before };
        });
        expect(result).toEqual({ status, value: status === 200 ? "current" : null, versionChanged: status === 401 });
    });
}

for (const status of [200, 401]) {
    test(`an obsolete cookie refresh HTTP ${status} cannot restore or clear authentication`, async ({ page }) => {
        await page.goto("/src/controllers/api/board/refreshProjectColumnDock.fixture.html");
        let release: () => void = () => {};
        const pending = new Promise<void>((resolve) => {
            release = resolve;
        });
        let requests = 0;
        await page.route("**/auth/refresh", async (route) => {
            requests += 1;
            await pending;
            await route.fulfill({ status, json: { access_token: "synthetic-test-token" } });
        });
        const resultPromise = page.evaluate(async () => {
            const apiPath = "/src/core/helpers/Api.ts";
            const { api, refresh } = await import(apiPath);
            api.defaults.baseURL = location.origin;
            return refresh();
        });
        const request = await page.waitForRequest("**/auth/refresh");
        expect(request.headers().authorization).toBeUndefined();
        const version = await page.evaluate(async () => {
            const authPath = "/src/core/stores/AuthStore.ts";
            const { getAuthStore } = await import(authPath);
            getAuthStore().removeToken();
            return getAuthStore().getSessionVersion();
        });
        release();
        expect(await resultPromise).toBe(false);
        const after = await page.evaluate(async () => {
            const authPath = "/src/core/stores/AuthStore.ts";
            const { getAuthStore } = await import(authPath);
            return { version: getAuthStore().getSessionVersion(), token: getAuthStore().getToken() };
        });
        expect(after).toEqual({ version, token: null });
        expect(requests).toBe(1);
    });
}
